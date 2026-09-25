"""Robot manager — the single owner of the robot's runtime behaviour (Phase 8).

Everything above the layers talks to :class:`RobotManager`; nothing else may
drive the motors directly:

    web control / warehouse tasks
                │
                ▼
        RobotManager  ← owns RobotState, ModeController, SafetyManager
                │
    ┌───────────┼─────────────┐
    ▼           ▼             ▼
 Safety      Drive        Sensors
 (L3 gate)  (L2 motion)  (telemetry)

Responsibilities
----------------
* **State** — owns :class:`RobotState` (the single published snapshot).
* **Gating (Layer 3)** — every motion command passes the safety gate
  (mode must allow motion *and* the safety decision must be ``PROCEED``).
  The gate can only *veto*, never bypass safety.
* **Enforcement** — :meth:`tick` evaluates sensors + comm health each
  control-loop iteration and forces ``STOP``/``SAFETY_STOP`` when required.
* **Watchdog (Pi side, Layer 2)** — if the controller stops answering,
  the link is declared lost and the robot is forced to a safety stop.
  (The Arduino hardware watchdog still independently stops the motors if
  the Pi dies entirely — see docs/safety.md.)
* **Modes** — :meth:`request_mode` enforces the Phase 9 state machine, with
  one extra rule: entering ``AUTONOMOUS`` requires a ``PROCEED`` decision.

``stop()`` (motion stop) and :meth:`estop` are *never* gated — you must
always be able to stop the robot.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple

from ..communication.arduino_serial import ArduinoSerial, SerialTimeout
from ..control import ArduinoMotorDriver, DifferentialDrive
from ..control.motor_controller import MotorError
from ..logging import get_logger
from ..safety import SafetyAction, SafetyDecision, SafetyManager
from ..sensors import UltrasonicManager, UltrasonicReading
from ..utils.config import AppConfig
from .mode_controller import ModeController, ModeTransitionError
from .robot_state import RobotMode, RobotState

if TYPE_CHECKING:  # pragma: no cover - typing only; no runtime import cycle
    from ..hazard import HazardManager, HazardStatus


class RobotCommandError(Exception):
    """A command was rejected (gating, mode, or safety)."""


class RobotManager:
    """Central runtime owner for one robot."""

    def __init__(
        self,
        serial: ArduinoSerial,
        driver: ArduinoMotorDriver,
        config: AppConfig,
    ):
        self._serial = serial
        self._driver = driver
        self._config = config
        self.log = get_logger("robot")

        self.state = RobotState()
        self.mode_ctrl = ModeController()
        self.safety = SafetyManager(config.safety)
        self.sensors = UltrasonicManager(serial, config.safety)
        self.drive = DifferentialDrive(
            driver, max_speed=config.robot.motors.max_speed
        )

        self.version: Optional[str] = None
        self._last_reading: Optional[UltrasonicReading] = None
        self._last_decision: Optional[SafetyDecision] = None
        self._last_ok: Optional[float] = None

        # Optional hazard layer (Layer 3.5). ``None`` means "not attached", in
        # which case every behaviour in this class is exactly as it was before
        # the hazard feature existed.
        self.hazard: Optional["HazardManager"] = None
        self._hazard_pose_provider: Optional[Callable[[], Any]] = None
        self._last_hazard_status: Optional["HazardStatus"] = None

    @property
    def decision(self) -> Optional[SafetyDecision]:
        """The most recent Layer-3 safety verdict, or ``None`` before the first
        ``tick()``.

        C15 added this read-only accessor so the C6 avoidance gate can be wired
        to the *real* Layer-3 verdict instead of a second, independent safety
        call — keeping the priority argument (a Layer-3 ``STOP`` outranks every
        manoeuvre) honest. It exposes the existing verdict; it never recomputes
        one and never drives an actuator.
        """
        return self._last_decision

    # ------------------------------------------------------------------ #
    # Factory: full mock stack (no hardware, no pyserial)
    # ------------------------------------------------------------------ #
    @classmethod
    def create_mock(
        cls,
        config: AppConfig,
        start_distances: Tuple[int, int, int, int] = (200, 200, 200, 200),
        drop_after: Optional[int] = None,
    ) -> Tuple["RobotManager", object]:
        """Build a :class:`RobotManager` over :class:`MockSerialTransport`.

        The *entire* high-level stack runs against the mock — the same code
        path used in hardware mode, only the transport differs.
        """
        from ..mocks import MockSerialTransport

        transport = MockSerialTransport(
            start_distances=start_distances, drop_after=drop_after
        )
        serial = ArduinoSerial(transport, timeout=0.05)
        driver = ArduinoMotorDriver(serial, max_speed=config.robot.motors.max_speed)
        return cls(serial, driver, config), transport

    # ------------------------------------------------------------------ #
    # Hazard layer (Layer 3.5, optional)
    # ------------------------------------------------------------------ #
    def attach_hazard(
        self,
        manager: "HazardManager",
        pose_provider: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Attach the optional context-aware multi-hazard safety layer.

        Additive and opt-in: until this is called the manager behaves exactly as
        it did before the hazard feature existed. Once attached the hazard layer
        can only **escalate** — a ``STOP``/``EMERGENCY`` verdict vetoes motion
        and forces ``SAFETY_STOP``, and a ``SLOW`` verdict caps the commanded
        speed. It never relaxes the Layer-3 proximity gate, and it never touches
        the motors itself.

        :param pose_provider: optional callable returning the robot's current
            pose (any object with ``x``/``y``), used to tag hazard events with a
            location for the future spatial hazard visualisation.
        """
        self.hazard = manager
        self._hazard_pose_provider = pose_provider
        names = [
            str(getattr(s, "name", type(s).__name__)) for s in manager.sources
        ]
        self.log.info(
            "hazard layer attached (%d source(s): %s)",
            len(names),
            ", ".join(names) or "none",
        )

    def hazard_snapshot(self) -> Optional[dict]:
        """The hazard layer's JSON snapshot, or ``None`` when not attached."""
        if self.hazard is None:
            return None
        return self.hazard.snapshot()

    def _hazard_location(self) -> Any:
        if self._hazard_pose_provider is None:
            return None
        try:
            return self._hazard_pose_provider()
        except Exception:  # noqa: BLE001 - a bad provider must not stop the loop
            return None

    def _scaled(self, speed: int) -> int:
        """Apply the hazard speed scale (identity when no layer is attached)."""
        if self.hazard is None:
            return speed
        scale = self.hazard.speed_scale
        if scale >= 1.0:
            return speed
        return max(0, int(round(speed * scale)))

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> bool:
        """Connect, ping, and take a first sensor snapshot.

        Raises ``ConnectionError`` if the controller does not answer PING.
        """
        self._serial.connect()
        if not self._serial.ping():
            self.state.connected = False
            raise ConnectionError("controller not responding to PING")
        self._note_ok()
        self.state.connected = True

        try:
            v = self._serial.version()
            self.version = v.version
        except SerialTimeout:
            self.version = None

        self._refresh_sensors()
        self.log.info(
            "started (version=%s)", self.version
        )
        return True

    def tick(self) -> SafetyDecision:
        """One control-loop iteration: poll, evaluate, enforce.

        Call this at a fixed rate from the main loop (e.g. 5–10 Hz).
        Returns the safety decision that was evaluated.
        """
        reading: Optional[UltrasonicReading] = None

        if self.state.connected:
            # Pi-side watchdog: loop is alive but the link has gone silent.
            wdt_s = self._config.safety.watchdog_timeout_ms / 1000.0
            if (
                self._last_ok is not None
                and (time.monotonic() - self._last_ok) > wdt_s
            ):
                self._on_link_loss("Pi-side watchdog timeout")

            if self.state.connected:
                try:
                    reading = self.sensors.poll()
                except (SerialTimeout, ConnectionError) as exc:
                    self._on_link_loss(f"controller stopped responding: {exc}")
                    reading = None
                else:
                    self._note_ok()
                    self._last_reading = reading
                    self.state.front_cm = reading.front
                    self.state.left_cm = reading.left
                    self.state.right_cm = reading.right
                    self.state.rear_cm = reading.rear

        decision = self.safety.check(reading, self.state.connected)
        self._last_decision = decision
        self.state.mode = self.mode_ctrl.mode
        self.state.updated_at = time.time()

        # Only *enforce* a STOP while the link is up: a never-connected
        # manager must not lock the mode to SAFETY_STOP before start()
        # (the gate already rejects motion when disconnected, and a real
        # in-flight link loss goes through _on_link_loss instead).
        if self.state.connected and decision.action is SafetyAction.STOP:
            self._enforce_stop(decision)

        # Layer 3.5 (optional): evaluate the hazard layer and enforce its veto.
        # Deliberately after Layer 3 so a proximity stop is never masked, and it
        # can only escalate the outcome — never clear a Layer-3 stop.
        if self.hazard is not None:
            self._last_hazard_status = self.hazard.evaluate(self._hazard_location())
            if self.state.connected and self._last_hazard_status.blocks_motion:
                reasons = tuple(self._last_hazard_status.reasons) or (
                    f"hazard {self._last_hazard_status.state.value}",
                )
                self._enforce_stop(SafetyDecision(SafetyAction.STOP, reasons))

        return decision

    def shutdown(self) -> None:
        """Best-effort graceful shutdown: stop motors, close the link."""
        try:
            self.drive.stop()
        except (SerialTimeout, ConnectionError, MotorError):
            pass
        try:
            self._serial.disconnect()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass
        self.state.connected = False

    def ping(self) -> bool:
        """Passthrough PING (also counts as a successful round trip)."""
        try:
            ok = self._serial.ping()
        except (SerialTimeout, ConnectionError):
            return False
        if ok:
            self._note_ok()
        return ok

    # ------------------------------------------------------------------ #
    # Motion (gated) — Layer 3
    # ------------------------------------------------------------------ #
    def _gate(self) -> None:
        """Reject unless the mode allows motion AND safety says PROCEED."""
        if not self.state.connected:
            raise RobotCommandError("not connected to controller")
        mode = self.mode_ctrl.mode
        if not mode.is_safe_to_move:
            raise RobotCommandError(f"motion not allowed in mode {mode.value}")
        decision = self.safety.check(self._last_reading, self.state.connected)
        if not decision.allowed:
            raise RobotCommandError(f"safety veto: {decision}")
        # Layer 3.5 (optional): the hazard layer vetoes motion on its own.
        if self.hazard is not None and self.hazard.status.blocks_motion:
            raise RobotCommandError(f"hazard veto: {self.hazard.status}")

    def _apply(self, fn) -> None:
        """Gate, run a drive command, publish the commanded speeds."""
        self._gate()
        fn()
        left, right = self.drive.last_commanded
        self.state.left_speed = left
        self.state.right_speed = right
        self.state.updated_at = time.time()

    # NOTE: speeds pass through _scaled(), which is the identity function unless a
    # hazard layer is attached and currently reports SLOW (see attach_hazard).
    def forward(self, speed: int = 100) -> None:
        self._apply(lambda: self.drive.forward(self._scaled(speed)))

    def backward(self, speed: int = 100) -> None:
        self._apply(lambda: self.drive.backward(self._scaled(speed)))

    def rotate_left(self, speed: int = 100) -> None:
        self._apply(lambda: self.drive.rotate_left(self._scaled(speed)))

    def rotate_right(self, speed: int = 100) -> None:
        self._apply(lambda: self.drive.rotate_right(self._scaled(speed)))

    def turn_left(self, speed: int = 80) -> None:
        self._apply(lambda: self.drive.turn_left(self._scaled(speed)))

    def turn_right(self, speed: int = 80) -> None:
        self._apply(lambda: self.drive.turn_right(self._scaled(speed)))

    def move(self, left: int, right: int) -> None:
        self._apply(lambda: self.drive.move(self._scaled(left), self._scaled(right)))

    def stop(self) -> None:
        """Command a motion stop. Never gated — always allowed."""
        try:
            self.drive.stop()
        except (SerialTimeout, ConnectionError, MotorError) as exc:
            self.log.warning("stop failed to reach controller: %s", exc)
        self.state.left_speed = 0
        self.state.right_speed = 0
        self.state.updated_at = time.time()

    def estop(self) -> None:
        """Software emergency stop: stop motors + force ``SAFETY_STOP``.

        Never gated. Reaching ``IDLE`` again requires :meth:`request_mode`
        (operator acknowledgement) — see docs/safety.md.
        """
        self.log.warning("E-STOP (operator)")
        self.stop()
        if self.mode_ctrl.mode not in (RobotMode.SAFETY_STOP, RobotMode.ERROR):
            self.mode_ctrl.safety_stop()
        self.state.mode = self.mode_ctrl.mode
        self.state.last_error = "E-STOP (operator)"
        self.state.updated_at = time.time()

    # ------------------------------------------------------------------ #
    # Modes (Phase 9 state machine)
    # ------------------------------------------------------------------ #
    def request_mode(self, target: RobotMode) -> RobotMode:
        """Transition to ``target`` subject to the mode state machine.

        Extra rule: entering ``AUTONOMOUS`` requires the current safety
        decision to be ``PROCEED`` (a human may enter ``MANUAL`` in
        ``WAIT``; autonomy may not).
        """
        current = self.mode_ctrl.mode
        if target is current:
            return target

        try:
            if target is RobotMode.IDLE and current in (
                RobotMode.SAFETY_STOP,
                RobotMode.ERROR,
            ):
                self.mode_ctrl.reset()  # operator acknowledgement
            elif target in (RobotMode.MANUAL, RobotMode.AUTONOMOUS):
                if target is RobotMode.AUTONOMOUS:
                    decision = self.safety.check(
                        self._last_reading, self.state.connected
                    )
                    if not decision.allowed:
                        raise RobotCommandError(
                            f"cannot enter AUTONOMOUS: safety={decision}"
                        )
                self.mode_ctrl.request(target)
            else:
                self.mode_ctrl.request(target)
        except ModeTransitionError as exc:
            # Present one public error type to higher layers.
            raise RobotCommandError(str(exc)) from exc

        self.state.mode = self.mode_ctrl.mode
        self.state.updated_at = time.time()
        return self.state.mode

    # ------------------------------------------------------------------ #
    # Snapshot
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict:
        """JSON-friendly snapshot for the web UI / CLI / logging."""
        d = self.state.to_dict()
        d["safety"] = str(self._last_decision) if self._last_decision else None
        d["version"] = self.version
        if self.hazard is not None:
            # Additive key: absent unless a hazard layer is attached.
            d["hazard"] = self.hazard.snapshot()
        return d

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _refresh_sensors(self) -> None:
        try:
            reading = self.sensors.poll()
        except (SerialTimeout, ConnectionError):
            return
        self._note_ok()
        self._last_reading = reading
        self.state.front_cm = reading.front
        self.state.left_cm = reading.left
        self.state.right_cm = reading.right
        self.state.rear_cm = reading.rear

    def _note_ok(self) -> None:
        self._last_ok = time.monotonic()

    def _on_link_loss(self, reason: str) -> None:
        """Declare the comm link lost and force a deterministic safety stop."""
        self.log.error("LINK LOSS: %s", reason)
        self.state.connected = False
        self.state.last_error = reason
        if self.mode_ctrl.mode not in (RobotMode.SAFETY_STOP, RobotMode.ERROR):
            self.mode_ctrl.safety_stop()
        self.state.mode = self.mode_ctrl.mode
        try:
            self.drive.stop()
        except (SerialTimeout, ConnectionError, MotorError):
            pass  # link is down — the firmware watchdog handles the motors
        self.state.left_speed = 0
        self.state.right_speed = 0
        self.state.updated_at = time.time()

    def _enforce_stop(self, decision: SafetyDecision) -> None:
        """Act on a ``STOP`` decision: stop motion + force safety stop mode."""
        if self.state.is_moving:
            try:
                self.drive.stop()
            except (SerialTimeout, ConnectionError, MotorError):
                pass
            self.state.left_speed = 0
            self.state.right_speed = 0
        if self.mode_ctrl.mode not in (RobotMode.SAFETY_STOP, RobotMode.ERROR):
            self.mode_ctrl.safety_stop()
            self.state.mode = self.mode_ctrl.mode
        self.state.last_error = str(decision)
        self.state.updated_at = time.time()
