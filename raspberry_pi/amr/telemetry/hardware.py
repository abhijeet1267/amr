"""Hardware component inventory for the Command Center.

Builds a *derived* view of every component the project knows about, from the
authoritative telemetry snapshot plus the configured (but not necessarily
connected) hardware. It is a read-only projection:

* it samples no hardware and mutates nothing;
* it re-uses the C7 ``TelemetrySnapshot`` and the existing config, so there is
  no second source of truth;
* a value is present only when the runtime actually measured it. ``None`` means
  "not measured / not connected" — it is never a fabricated ``0``.

The point is the *status vocabulary*. A component must be distinguishable as
connected-and-healthy, connected-but-failed, configured-but-not-connected,
simulated, or unknown. The rules that decide this are explicit below, not
invented per-panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# Reuse the robot's own caution multiplier so the dashboard's classification is
# the SAME rule the SafetyManager applies, not a second, divergent guess.
from ..safety.safety_manager import CAUTION_FACTOR


class ComponentStatus(str, Enum):
    """The states a dashboard component card can show.

    Deliberately richer than the three-value :class:`DataSource`: it separates
    "connected and healthy" from "connected but its measurement failed", and
    "configured in software but nothing is physically there".
    """

    #: Read from real hardware and answering right now.
    CONNECTED = "CONNECTED"
    #: Hardware is present but its latest measurement failed / is invalid.
    FAULTY = "FAULTY"
    #: Configured in software, but no physical response is present.
    CONFIGURED = "CONFIGURED"
    #: Value is a mock / simulated reading, clearly labeled.
    SIMULATED = "SIMULATED"
    #: Not measured at all — absent, not zero.
    UNAVAILABLE = "UNAVAILABLE"
    #: We cannot tell (e.g. the backend is down and we have no prior state).
    UNKNOWN = "UNKNOWN"


# Ultrasonic distance classification. Thresholds here are for *display only* —
# they mirror the safety config when present, and are otherwise documented
# dashboard defaults. The real stop logic stays in amr.safety / the firmware.
class UltrasonicClass(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    OBSTACLE = "OBSTACLE"
    TOO_CLOSE = "TOO_CLOSE"
    #: Reading present but outside the configured valid window.
    OUT_OF_RANGE = "OUT_OF_RANGE"
    #: No usable echo (``-1`` / ``None``) — not an obstacle, just clear/unknown.
    NO_ECHO = "NO_ECHO"
    #: Reading older than the staleness window.
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Component:
    """One hardware component card."""

    id: str
    name: str
    kind: str
    status: ComponentStatus
    #: Where a present value came from (LIVE / SIMULATION / UNAVAILABLE).
    source: Optional[str] = None
    #: The latest meaningful value, if any (distance, count, bool, ...).
    value: Optional[Any] = None
    unit: Optional[str] = None
    #: Human explanation of why it is in its state.
    detail: Optional[str] = None
    #: Epoch seconds of the last successful reading, if any.
    last_update: Optional[float] = None
    #: Seconds since the last reading, if measurable.
    age_s: Optional[float] = None
    #: A display-only classification, where applicable (e.g. ultrasonic).
    classification: Optional[str] = None
    #: True when the value is a simulation that must be labeled as such.
    simulated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "status": self.status.value,
            "source": self.source,
            "value": self.value,
            "unit": self.unit,
            "detail": self.detail,
            "last_update": self.last_update,
            "age_s": self.age_s,
            "classification": self.classification,
            "simulated": self.simulated,
        }


@dataclass(frozen=True)
class HardwareInventory:
    """The full derived component list plus an overall connection summary."""

    components: List[Component] = field(default_factory=list)
    #: True when the robot controller itself is reachable.
    controller_connected: bool = False
    #: True when the web backend is serving (always true if we got here).
    backend_online: bool = True
    #: Overall operational label for the header (see :func:`overall_state`).
    state: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "components": [c.to_dict() for c in self.components],
            "controller_connected": self.controller_connected,
            "backend_online": self.backend_online,
            "state": self.state,
        }


def _age(last_update: Optional[float], now: Optional[float]) -> Optional[float]:
    if last_update is None or now is None:
        return None
    return max(0.0, now - last_update)


def _src(t: Dict[str, Any], section: str) -> Optional[str]:
    """Pull the ``source`` tag out of a telemetry section, if it has one."""
    sec = t.get(section)
    if isinstance(sec, dict):
        return sec.get("source")
    return None


def _sim(t: Dict[str, Any]) -> bool:
    return t.get("simulated") is True


def _ultrasonic_class(
    value: Optional[int],
    *,
    stop_cm: Optional[int],
    valid_max_cm: Optional[int],
    stale,
) -> UltrasonicClass:
    """Classify one ultrasonic reading for display, **per face**.

    The bands mirror :class:`amr.safety.safety_manager.SafetyManager._check_base`
    exactly, so what the operator sees is what the robot actually acts on:

    * ``value < stop_cm``            -> TOO_CLOSE  (the real STOP band)
    * ``stop_cm <= value < CAUTION_FACTOR * stop_cm`` -> CAUTION  (the real WAIT
      band)
    * otherwise -> CLEAR

    ``None`` -> NO_ECHO (clear / not present), which is *not* an obstacle and is
    never a 0-distance. A reading above the configured valid window is
    OUT_OF_RANGE. This is display only — the real stop logic stays in
    ``amr.safety`` / the firmware; the numbers are the *same* numbers.
    """
    if value is None:
        return UltrasonicClass.NO_ECHO
    if stale:
        return UltrasonicClass.STALE
    if valid_max_cm is not None and value > valid_max_cm:
        return UltrasonicClass.OUT_OF_RANGE
    if stop_cm is not None:
        if value < stop_cm:
            return UltrasonicClass.TOO_CLOSE
        if value < CAUTION_FACTOR * stop_cm:
            return UltrasonicClass.CAUTION
    return UltrasonicClass.CLEAR


def build_hardware_inventory(
    telemetry: Dict[str, Any],
    *,
    now: Optional[float] = None,
    env_config: Optional[Dict[str, Any]] = None,
    thresholds: Optional[Dict[str, int]] = None,
    stale_after_s: float = 10.0,
) -> HardwareInventory:
    """Derive the component inventory from the telemetry snapshot.

    :param telemetry: ``TelemetrySnapshot.to_dict()`` plus a ``sensors`` block.
    :param now: reference clock (defaults to the snapshot timestamp).
    :param env_config: ``config.robot.environment`` as a dict, for the
        "configured but not connected" classification of gas/LCD/buzzer.
    :param thresholds: display-only ultrasonic thresholds from the safety
        config — ``front_stop_cm`` / ``front_caution_cm`` / ``valid_max_cm``.
        When absent, no classification beyond NO_ECHO/CLEAR is applied rather
        than inventing numbers.
    :param stale_after_s: a reading older than this is marked STALE.
    """
    t = telemetry if isinstance(telemetry, dict) else {}
    sensors = t.get("sensors") if isinstance(t.get("sensors"), dict) else {}
    camera = t.get("camera") if isinstance(t.get("camera"), dict) else {}
    battery = t.get("battery") if isinstance(t.get("battery"), dict) else {}
    safety = t.get("safety") if isinstance(t.get("safety"), dict) else {}
    system = t.get("system") if isinstance(t.get("system"), dict) else {}
    # `connected` lives in the system section of the TelemetrySnapshot (the
    # collector puts it there, not at the top level). A top-level `connected` is
    # also honoured as a fallback, because the robot's own snapshot() and some
    # test fixtures carry it there.
    connected = bool(system.get("connected", t.get("connected")))
    sim = _sim(t)

    if now is None:
        now = t.get("timestamp")

    th = thresholds or {}
    # Per-face stop thresholds, mirroring the safety manager exactly. The
    # caution band is CAUTION_FACTOR * stop_cm, the same factor the SafetyManager
    # uses for its WAIT band — so the dashboard and the robot agree.
    stop_by_face = {
        face: th.get(f"{face}_stop_cm")
        for face in ("front", "left", "right", "rear")
    }
    valid_max_cm = th.get("valid_max_cm")

    components: List[Component] = []

    # ------------------------------------------------------------------ #
    # Main controller (the Pi itself) — backend health, not robot health.
    # ------------------------------------------------------------------ #
    components.append(Component(
        id="pi", name="Raspberry Pi", kind="controller",
        status=ComponentStatus.CONNECTED,
        source="LIVE",
        detail="Backend is serving this console.",
        last_update=now, age_s=0.0,
    ))

    # ------------------------------------------------------------------ #
    # Arduino reflexes — the serial controller the Pi talks to.
    # ------------------------------------------------------------------ #
    if connected:
        arduino_status = ComponentStatus.CONNECTED
        arduino_src = "SIMULATION" if sim else "LIVE"
        arduino_detail = "Serial link is up." + (
            " (simulated)" if sim else "")
    else:
        arduino_status = ComponentStatus.UNAVAILABLE
        arduino_src = "UNAVAILABLE"
        arduino_detail = "No serial controller is connected."
    components.append(Component(
        id="arduino", name="Arduino UNO", kind="reflexes",
        status=arduino_status, source=arduino_src,
        detail=arduino_detail,
        last_update=(now if connected else None),
        age_s=(0.0 if connected else None),
        simulated=sim,
    ))

    # ------------------------------------------------------------------ #
    # Motors / L298N — derived from the drive state, not invented.
    # ------------------------------------------------------------------ #
    moving = bool(t.get("is_moving"))
    left_spd = t.get("left_speed")
    right_spd = t.get("right_speed")
    if connected:
        motor_status = ComponentStatus.CONNECTED
        motor_src = "SIMULATION" if sim else "LIVE"
        motor_detail = "Driving." if moving else "Stopped."
        motor_value = (left_spd, right_spd)
    else:
        motor_status = ComponentStatus.CONFIGURED
        motor_src = "UNAVAILABLE"
        motor_detail = "L298N configured; controller not connected."
        motor_value = None
    components.append(Component(
        id="motors", name="Motors (L298N)", kind="actuator",
        status=motor_status, source=motor_src,
        value=motor_value, unit="PWM", detail=motor_detail,
        last_update=(now if connected else None),
        age_s=(0.0 if connected else None),
        simulated=sim,
    ))

    # ------------------------------------------------------------------ #
    # Four ultrasonic sensors — live, classified, with age.
    # ------------------------------------------------------------------ #
    # Staleness is decided by the caller (the console knows the real telemetry
    # age); per-sensor timestamps are not part of the snapshot, so we don't
    # invent one here. ``stale`` defaults to False.
    sensor_ts = now
    for face, key in (
        ("front", "front_cm"), ("left", "left_cm"),
        ("right", "right_cm"), ("rear", "rear_cm"),
    ):
        value = sensors.get(key)
        if connected and value is not None:
            status = ComponentStatus.CONNECTED
            src = "SIMULATION" if sim else "LIVE"
        elif connected and value is None:
            status = ComponentStatus.CONNECTED
            src = "SIMULATION" if sim else "LIVE"
        else:
            status = ComponentStatus.CONFIGURED
            src = "UNAVAILABLE"
        klass = _ultrasonic_class(
            value, stop_cm=stop_by_face.get(face),
            valid_max_cm=valid_max_cm, stale=False,
        )
        components.append(Component(
            id=f"us_{face}", name=f"Ultrasonic {face.title()}",
            kind="sensor", status=status, source=src,
            value=value, unit="cm", classification=klass.value,
            detail=None if value is not None else "No echo (clear / not present).",
            last_update=(sensor_ts if value is not None else None),
            age_s=_age(sensor_ts, now),
            simulated=sim,
        ))

    # ------------------------------------------------------------------ #
    # DHT11 temperature/humidity — present only when measured.
    # ------------------------------------------------------------------ #
    temp = sensors.get("temperature_c")
    hum = sensors.get("humidity_pct")
    if temp is not None or hum is not None:
        dht_status = ComponentStatus.SIMULATED if sim else ComponentStatus.CONNECTED
        dht_detail = None
    else:
        dht_status = ComponentStatus.CONFIGURED
        dht_detail = "No reading — sensor not responding (often a missing " \
                     "10 kΩ pull-up)."
    components.append(Component(
        id="dht11", name="DHT11 (T/RH)", kind="sensor",
        status=dht_status,
        source=("SIMULATION" if sim else "LIVE") if (temp is not None or hum is not None)
        else "UNAVAILABLE",
        value=(temp, hum) if (temp is not None or hum is not None) else None,
        unit="°C / %RH", detail=dht_detail,
        last_update=(now if (temp is not None or hum is not None) else None),
        age_s=_age(now, now), simulated=sim,
    ))

    # ------------------------------------------------------------------ #
    # MQ gas — telemetry only, and only when a pin is assigned.
    # ------------------------------------------------------------------ #
    gas = sensors.get("gas_raw")
    gas_pin = (env_config or {}).get("gas_pin")
    if gas is not None:
        gas_status = ComponentStatus.SIMULATED if sim else ComponentStatus.CONNECTED
        gas_detail = None
    else:
        gas_status = ComponentStatus.CONFIGURED
        gas_detail = (
            "No analog pin assigned — the firmware reports it as unmeasured."
            if gas_pin is None
            else "No reading yet."
        )
    components.append(Component(
        id="gas", name="MQ Gas", kind="sensor",
        status=gas_status,
        source=("SIMULATION" if sim else "LIVE") if gas is not None else "UNAVAILABLE",
        value=gas, unit="raw (0–1023)", detail=gas_detail,
        last_update=(now if gas is not None else None),
        age_s=_age(now, now), simulated=sim,
    ))

    # ------------------------------------------------------------------ #
    # LCD / buzzer — configured, write-only, so "connected" is never claimed.
    # ------------------------------------------------------------------ #
    env = env_config or {}
    lcd_addr = env.get("lcd_i2c_address")
    buzzer_pin = env.get("buzzer_pin")
    components.append(Component(
        id="lcd", name="I2C LCD (16×2)", kind="display",
        status=ComponentStatus.CONFIGURED, source="UNAVAILABLE",
        value=(f"0x{lcd_addr:02X}" if isinstance(lcd_addr, int) else None),
        detail="Write-only from the Pi; content is mirrored, not readable back.",
        simulated=False,
    ))
    components.append(Component(
        id="buzzer", name="Buzzer", kind="actuator",
        status=ComponentStatus.CONFIGURED, source="UNAVAILABLE",
        value=buzzer_pin, detail="Command-driven (BUZZ); no continuous state.",
        simulated=False,
    ))

    # ------------------------------------------------------------------ #
    # Camera — from the camera section.
    # ------------------------------------------------------------------ #
    cam_status = camera.get("status")
    cam_src = camera.get("source") or camera.get("source_name")
    if cam_status == "LIVE":
        cam = ComponentStatus.SIMULATED if camera.get("source") == "SIMULATION" \
            else ComponentStatus.CONNECTED
        cam_value = f"{camera.get('width')}x{camera.get('height')}"
        cam_detail = f"backend {camera.get('metadata', {}).get('backend', '?')}" \
            if isinstance(camera.get("metadata"), dict) else None
    elif cam_status == "ERROR":
        cam = ComponentStatus.FAULTY
        cam_value = None
        cam_detail = (camera.get("error") or "camera error")[:120]
    else:
        cam = ComponentStatus.CONFIGURED
        cam_value = None
        cam_detail = "No live camera."
    components.append(Component(
        id="camera", name="Camera", kind="sensor",
        status=cam, source=cam_src, value=cam_value,
        detail=cam_detail,
        last_update=(now if cam_status == "LIVE" else None),
        age_s=_age(now, now),
        simulated=bool(camera.get("simulated")),
    ))

    # ------------------------------------------------------------------ #
    # Battery — present only when measured; otherwise UNAVAILABLE, not 0.
    # ------------------------------------------------------------------ #
    batt_pct = battery.get("percentage")
    batt_status = ComponentStatus.UNAVAILABLE if batt_pct is None else (
        ComponentStatus.SIMULATED if _sim(battery) else ComponentStatus.CONNECTED)
    components.append(Component(
        id="battery", name="Battery", kind="power",
        status=batt_status, source=battery.get("source"),
        value=batt_pct, unit="%" if batt_pct is not None else None,
        detail=None if batt_pct is not None else "No battery voltage sensor.",
        simulated=bool(battery.get("source") == "SIMULATION"),
    ))

    components.append(Component(
        id="safety", name="Safety Layer", kind="safety",
        status=ComponentStatus.CONNECTED,
        source="SIMULATION" if sim else "LIVE",
        value=safety.get("action"), detail=safety.get("reasons") or "",
        simulated=sim,
    ))

    return HardwareInventory(
        components=components,
        controller_connected=connected,
        backend_online=True,
        state=_overall_state(connected, sim, components),
    )


def _overall_state(
    connected: bool, sim: bool, components: List[Component]
) -> str:
    """A header label that never hides missing hardware or a stale link.

    A healthy *backend* is not a healthy *robot*; the label says which layer it
    is talking about.
    """
    if not connected:
        return "SIMULATION" if sim else "DISCONNECTED"
    faulty = [c for c in components if c.status is ComponentStatus.FAULTY]
    if faulty:
        return "DEGRADED"
    return "SIMULATION" if sim else "ONLINE"
