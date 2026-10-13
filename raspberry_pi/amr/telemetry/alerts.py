"""Warning and fault center for the Command Center.

Alerts are *derived* from the authoritative telemetry snapshot on every poll —
not pushed from a separate subsystem and not a second source of truth. Each
poll runs a set of pure rules against the snapshot and reconciles the results
against the previous alert set:

* a rule that fires creates (or refreshes) an alert;
* a rule that stops firing marks its alert **resolved** — the alert stays in
  history, it is not silently deleted;
* **acknowledgement is a flag, not a cure.** Acking an alert does not remove the
  underlying condition; the next poll re-raises it if the condition still holds.
* A physical safety fault (emergency stop / SAFETY_STOP) can never be cleared
  by acknowledgement alone — it is ``clearable_by_user: False`` and stays active
  while the robot state demands it. The safety subsystem alone decides when it
  is resolved.

The engine is stateful only in its bounded alert history; the *current* alert
set is always recomputable from the snapshot.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def rank(self) -> int:
        """Numeric severity for sorting: CRITICAL > ERROR > WARNING > INFO."""
        return {
            Severity.INFO: 0,
            Severity.WARNING: 1,
            Severity.ERROR: 2,
            Severity.CRITICAL: 3,
        }[self]


@dataclass
class Alert:
    """One warning/fault record."""

    alert_id: str
    source: str
    severity: Severity
    description: str
    first_seen: float
    last_updated: float
    #: ACTIVE or RESOLVED.
    status: str
    #: Whether an operator has acknowledged it. Ack does NOT resolve it.
    acknowledged: bool = False
    #: False when the condition can only clear itself (a physical safety fault).
    clearable_by_user: bool = True
    #: Suggested diagnostic action.
    suggestion: Optional[str] = None
    #: A stable key identifying the *condition*, for dedup.
    key: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "source": self.source,
            "severity": self.severity.value,
            "description": self.description,
            "first_seen": self.first_seen,
            "last_updated": self.last_updated,
            "status": self.status,
            "acknowledged": self.acknowledged,
            "clearable_by_user": self.clearable_by_user,
            "suggestion": self.suggestion,
            "age_s": round(self.last_updated - self.first_seen, 2),
        }


#: A condition key -> (severity, description, suggestion, clearable_by_user).
def _rules() -> List[Tuple[str, str, str, Severity, str, bool]]:
    """The explicit monitoring rules.

    Each is ``(key, source, description, severity, suggestion, clearable)``.
    These fire when their predicate holds; a rule that does not fire resolves
    its alert on the next poll.
    """
    return [
        ("backend_disconnected", "backend", "Backend telemetry is not flowing.",
         Severity.CRITICAL, "Check the server process and network.", False),
        ("controller_disconnected", "arduino",
         "No serial controller is connected.",
         Severity.ERROR, "Check the USB link and /dev/ttyACM0.", False),
        ("emergency_stop", "safety",
         "Emergency stop is active.",
         Severity.CRITICAL,
         "Reset from the control panel; the robot cannot move while latched.",
         False),
        ("safety_stop_mode", "safety",
         "Robot is in SAFETY_STOP mode.",
         Severity.CRITICAL,
         "A safety fault stopped the robot; reset explicitly to resume.",
         False),
        ("telemetry_stale", "telemetry",
         "Telemetry has not updated recently.",
         Severity.WARNING, "The robot may be idle or the link is slow.", True),
        ("sensor_invalid_front", "us_front", "Front sensor returned an invalid reading.",
         Severity.WARNING, "Check wiring and the sensor's valid range.", True),
        ("sensor_invalid_rear", "us_rear", "Rear sensor returned an invalid reading.",
         Severity.WARNING, "Check wiring and the sensor's valid range.", True),
        ("sensor_invalid_left", "us_left", "Left sensor returned an invalid reading.",
         Severity.WARNING, "Check wiring and the sensor's valid range.", True),
        ("sensor_invalid_right", "us_right", "Right sensor returned an invalid reading.",
         Severity.WARNING, "Check wiring and the sensor's valid range.", True),
        ("camera_error", "camera", "Camera is in an error state.",
         Severity.ERROR, "Check the camera connection and the camera log.", True),
        ("hazard_critical", "hazards",
         "A critical hazard is active.",
         Severity.CRITICAL, "See the Hazards view for the source and kind.",
         False),
        ("hazard_active", "hazards", "An active hazard is present.",
         Severity.WARNING, "See the Hazards view for details.", True),
        ("task_failed", "mission", "A task failed.",
         Severity.ERROR, "See the Mission view for the failure reason.", True),
        ("nav_failed", "navigation", "Navigation reported a failure.",
         Severity.ERROR, "Check the goal and the route.", True),
        ("dht11_absent", "dht11", "DHT11 is not reporting.",
         Severity.INFO,
         "Likely a missing 10 kΩ pull-up; telemetry only, blocks nothing.",
         True),
        ("gas_unassigned", "gas", "Gas sensor has no analog pin assigned.",
         Severity.INFO,
         "Free an analog pin to enable it; currently reports unmeasured.",
         True),
    ]


class AlertEngine:
    """Derives and reconciles the alert set from telemetry snapshots."""

    def __init__(self, maxlen: int = 200, stale_after_s: float = 10.0):
        self._maxlen = maxlen
        self._stale_after_s = stale_after_s
        self._alerts: Dict[str, Alert] = {}
        self._order: List[str] = []
        self._counter = 0

    # -- rule evaluation ---------------------------------------------------- #
    def _evaluate(self, tele: Dict[str, Any], now: float) -> Dict[str, str]:
        """Return the set of currently-firing condition keys -> severity label."""
        t = tele if isinstance(tele, dict) else {}
        sensors = t.get("sensors") if isinstance(t.get("sensors"), dict) else {}
        cam = t.get("camera") if isinstance(t.get("camera"), dict) else {}
        hz = t.get("hazards") if isinstance(t.get("hazards"), dict) else {}
        safety = t.get("safety") if isinstance(t.get("safety"), dict) else {}
        nav = t.get("navigation") if isinstance(t.get("navigation"), dict) else {}
        mission = t.get("mission") if isinstance(t.get("mission"), dict) else {}
        ts = t.get("timestamp") or now
        firing: Dict[str, str] = {}

        # Backend is up only if we are being polled and the snapshot is fresh.
        if (now - ts) > self._stale_after_s:
            firing["backend_disconnected"] = Severity.CRITICAL.value

        if not t.get("connected"):
            firing["controller_disconnected"] = Severity.ERROR.value

        if safety.get("emergency_stop"):
            firing["emergency_stop"] = Severity.CRITICAL.value
        if safety.get("state") == "SAFETY_STOP":
            firing["safety_stop_mode"] = Severity.CRITICAL.value

        if (now - ts) > self._stale_after_s:
            firing["telemetry_stale"] = Severity.WARNING.value

        # Invalid sensor = present in the config but value None while connected.
        # A "no echo" reading is valid (clear), so this only fires on an actual
        # measurement fault, which the runtime surfaces as a non-null flag.
        for face, key in (("front", "front"), ("rear", "rear"),
                          ("left", "left"), ("right", "right")):
            if sensors.get(f"{face}_valid") is False:
                firing[f"sensor_invalid_{face}"] = Severity.WARNING.value

        if cam.get("status") == "ERROR":
            firing["camera_error"] = Severity.ERROR.value

        if hz.get("critical"):
            firing["hazard_critical"] = Severity.CRITICAL.value
        elif hz.get("active"):
            firing["hazard_active"] = Severity.WARNING.value

        if mission.get("state") == "FAILED":
            firing["task_failed"] = Severity.ERROR.value
        if nav.get("state") == "FAILED":
            firing["nav_failed"] = Severity.ERROR.value

        if t.get("connected") and sensors.get("temperature_c") is None \
                and sensors.get("humidity_pct") is None:
            firing["dht11_absent"] = Severity.INFO.value
        if sensors.get("gas_raw") is None:
            firing["gas_unassigned"] = Severity.INFO.value

        return firing

    def _rule(self, key: str) -> Optional[Tuple]:
        for rule in _rules():
            if rule[0] == key:
                return rule
        return None

    # -- main entry --------------------------------------------------------- #
    def poll(self, tele: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
        """Reconcile the alert set against a fresh snapshot. Returns the state."""
        t = tele if isinstance(tele, dict) else {}
        now = now or t.get("timestamp") or time.time()
        firing = self._evaluate(t, now)

        # Refresh or create alerts for currently-firing conditions.
        for key, sev in firing.items():
            rule = self._rule(key)
            if rule is None:
                continue
            _k, source, desc, severity, suggestion, clearable = rule
            alert = self._alerts.get(key)
            if alert is None:
                self._counter += 1
                alert = Alert(
                    alert_id=f"alr-{self._counter:05d}",
                    source=source, severity=severity, description=desc,
                    first_seen=now, last_updated=now, status="ACTIVE",
                    clearable_by_user=clearable, suggestion=suggestion, key=key,
                )
                self._alerts[key] = alert
                self._order.append(key)
            else:
                # A re-firing condition re-activates and re-clears an ack if the
                # user had acknowledged a *resolved* version of it.
                alert.status = "ACTIVE"
                alert.last_updated = now
                alert.severity = severity
                alert.description = desc
                alert.suggestion = suggestion
                alert.clearable_by_user = clearable

        # Resolve conditions that are no longer firing. A user cannot resolve a
        # non-clearable alert manually; the condition clearing itself does it.
        for key in list(self._alerts.keys()):
            alert = self._alerts[key]
            if key not in firing and alert.status == "ACTIVE":
                alert.status = "RESOLVED"
                alert.last_updated = now

        self._trim()
        return self.to_dict()

    def _trim(self) -> None:
        # Keep only the most recent maxlen by last_updated.
        if len(self._order) > self._maxlen:
            ranked = sorted(
                self._order,
                key=lambda k: self._alerts[k].last_updated,
                reverse=True,
            )
            drop = set(self._order) - set(ranked[: self._maxlen])
            for key in drop:
                self._alerts.pop(key, None)
            self._order = ranked[: self._maxlen]

    def acknowledge(self, alert_id: str) -> bool:
        """Flag an alert acknowledged. Never removes or resolves it."""
        for alert in self._alerts.values():
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        active = [
            a for a in self._alerts.values() if a.status == "ACTIVE"
        ]
        active.sort(key=lambda a: (-a.severity.rank(), -a.last_updated))
        resolved = [
            a for a in self._alerts.values() if a.status == "RESOLVED"
        ]
        resolved.sort(key=lambda a: -a.last_updated)
        return {
            "active": [a.to_dict() for a in active],
            "resolved": [a.to_dict() for a in resolved[:20]],
            "active_count": len(active),
            "critical_count": sum(
                1 for a in active if a.severity is Severity.CRITICAL
            ),
            "warning_count": sum(
                1 for a in active if a.severity in (Severity.WARNING, Severity.ERROR)
            ),
            "unacknowledged_count": sum(
                1 for a in active if not a.acknowledged
            ),
        }
