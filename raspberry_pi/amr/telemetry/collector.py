"""Read-only projection of the existing AMR runtime into telemetry (C7).

This module is the only place that knows how the runtime's public state maps
onto the :mod:`amr.telemetry.types` contract. It is a *reader*, not a second
runtime:

* it never calls ``tick()`` (the control loop) — reading telemetry must not
  advance the robot, poll the serial port, or evaluate the hazard layer;
* it never calls ``dispatch()`` / any ``RobotManager`` motion method;
* it imports no motor driver, transport, or GPIO.

Every source is optional. A subsystem that was not wired in, or that raises,
degrades to ``UNAVAILABLE`` rather than fabricating a number.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple

from ..camera.frame import CameraFrame, CameraStatus
from ..logging import get_logger
from .types import (
    BatteryTelemetry,
    CameraTelemetry,
    DataSource,
    HazardTelemetry,
    MissionTelemetry,
    NavigationTelemetry,
    Orientation,
    SafetyTelemetry,
    SensorTelemetry,
    SystemTelemetry,
    TelemetrySnapshot,
    Vector3,
    Velocity,
)

#: Maps an honest camera status onto the telemetry source tag. ``ERROR`` and
#: ``UNAVAILABLE`` are both ``UNAVAILABLE`` from a consumer's point of view: no
#: trustworthy image is coming. ``SIMULATION`` is its own tag so the UI can
#: never present a placeholder as live footage.
_SOURCE_FOR_STATUS = {
    CameraStatus.LIVE: DataSource.LIVE,
    CameraStatus.SIMULATION: DataSource.SIMULATION,
    CameraStatus.UNAVAILABLE: DataSource.UNAVAILABLE,
    CameraStatus.ERROR: DataSource.UNAVAILABLE,
}


class TelemetryCollector:
    """Build :class:`TelemetrySnapshot` objects from live runtime objects.

    :param robot: a :class:`~amr.robot.RobotManager` (or anything exposing
        ``state`` / ``snapshot()``). Read-only use only.
    :param navigator: optional navigator exposing ``current_pose()``,
        ``status()`` and ``goal``.
    :param warehouse: optional warehouse manager exposing ``status()``.
    :param camera: optional :class:`~amr.camera.CameraManager`.
    :param simulated: ``True`` when the runtime is mock-backed, so every
        derived value is tagged ``SIMULATION`` rather than ``LIVE``.
    :param software_version: reported as-is; no default is invented.
    """

    def __init__(
        self,
        robot: Any = None,
        *,
        navigator: Any = None,
        warehouse: Any = None,
        camera: Any = None,
        simulated: bool = False,
        software_version: Optional[str] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.robot = robot
        self.navigator = navigator
        self.warehouse = warehouse
        self.camera = camera
        self.simulated = bool(simulated)
        self.software_version = software_version
        self._clock = clock or time.time
        self.log = get_logger("telemetry")
        self._started_at = self._clock()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def _runtime_source(self) -> DataSource:
        """Provenance of the runtime itself (drives safety/system tags).

        ``safety`` and ``system`` are not measurements of the world, they are
        facts about the process running the AMR, so their tag reflects whether
        a runtime is attached at all rather than whether a field is populated.
        """
        if self.robot is None:
            return DataSource.UNAVAILABLE
        return self._src(True)

    def collect(self) -> TelemetrySnapshot:
        """One read-only snapshot. Never raises, never drives the robot."""
        state = self._robot_state()
        pose = self._pose()
        hazard = self._hazard()
        safety = self._safety(state)
        return TelemetrySnapshot(
            timestamp=self._clock(),
            simulated=self.simulated,
            position=Vector3.from_pose(pose, self._src(pose is not None)),
            orientation=Orientation.from_pose(pose, self._src(pose is not None)),
            velocity=self._velocity(),
            navigation=self._navigation(),
            safety=safety,
            hazards=hazard,
            battery=self._battery(),
            sensors=self._sensors(state),
            mission=self._mission(),
            camera=self._camera(),
            system=self._system(state),
        )

    def snapshot(self) -> Dict[str, Any]:
        """One read-only snapshot as a plain JSON-ready dict.

        Convenience alias for ``collect().to_dict()`` used by the web layer,
        so a handler never has to know the dataclass layout.
        """
        return self.collect().to_dict()

    def health(self) -> Dict[str, Any]:
        """Liveness/readiness summary for ``GET /health``.

        ``ok`` means "this process can answer and its runtime is reachable" —
        it is a *dashboard* health check, not a claim that the robot is safe to
        drive. Safety posture is reported separately under ``safety``.
        """
        snap = self.collect()
        connected = bool(snap.system.connected)
        errors: list = []
        if snap.system.last_error:
            errors.append(str(snap.system.last_error))
        if not connected:
            errors.append("robot not connected")
        return {
            "ok": True,
            "status": "DEGRADED" if errors else "OK",
            "simulated": snap.simulated,
            "schema_version": snap.schema_version,
            "timestamp": snap.timestamp,
            "connected": connected,
            "mode": snap.system.mode,
            "uptime": snap.system.uptime,
            "software_version": snap.system.software_version,
            "sources": snap.sources(),
            "safety": {
                "action": snap.safety.action,
                "hazard_state": snap.safety.hazard_state,
                "emergency_stop": snap.safety.emergency_stop,
            },
            "errors": errors,
        }


    # ------------------------------------------------------------------ #
    # Section readers. Each one is isolated: a source that raises or is
    # missing yields an UNAVAILABLE section instead of failing the snapshot.
    # ------------------------------------------------------------------ #
    def _src(self, present: bool) -> DataSource:
        """Tag a value as LIVE / SIMULATION / UNAVAILABLE.

        A *present* value is real in simulation mode, so the tag reflects where
        the number actually came from rather than how trustworthy it is.
        """
        if not present:
            return DataSource.UNAVAILABLE
        return DataSource.SIMULATION if self.simulated else DataSource.LIVE

    def _robot_state(self) -> Dict[str, Any]:
        """The runtime's own state dict, or ``{}`` when unreachable."""
        robot = self.robot
        if robot is None:
            return {}
        for attr in ("snapshot", "status"):
            fn = getattr(robot, attr, None)
            if callable(fn):
                try:
                    data = fn()
                except Exception as exc:  # noqa: BLE001 - never break a read
                    self.log.debug("telemetry: %s() failed: %s", attr, exc)
                    continue
                if isinstance(data, dict):
                    return data
        state = getattr(robot, "state", None)
        to_dict = getattr(state, "to_dict", None)
        if callable(to_dict):
            try:
                data = to_dict()
            except Exception as exc:  # noqa: BLE001
                self.log.debug("telemetry: state.to_dict() failed: %s", exc)
                return {}
            if isinstance(data, dict):
                return data
        return {}

    def _pose(self) -> Any:
        """Current pose from the navigator, or ``None``.

        Only the *navigator* is consulted: the odometry-free ``RobotState``
        carries no pose, and inventing one here would be a fabricated
        measurement. Read errors degrade to ``None`` (UNAVAILABLE).
        """
        nav = self.navigator
        if nav is None:
            return None
        fn = getattr(nav, "current_pose", None)
        if not callable(fn):
            return None
        try:
            pose = fn()
        except Exception as exc:  # noqa: BLE001
            self.log.debug("telemetry: current_pose() failed: %s", exc)
            return None
        if pose is None:
            return None
        if all(getattr(pose, axis, None) is not None
               for axis in ("x", "y")):
            return pose
        return None

    def _velocity(self) -> Velocity:
        """Velocities when the runtime publishes them, else UNAVAILABLE.

        ``RobotState`` has no velocity field today, so this is correctly empty
        rather than differenced from poses -- differencing here would invent a
        measurement the runtime never made.
        """
        state = self._robot_state()
        linear = state.get("linear_speed")
        angular = state.get("angular_speed")
        have = linear is not None or angular is not None
        return Velocity(
            linear=float(linear) if _is_number(linear) else None,
            angular=float(angular) if _is_number(angular) else None,
            source=self._src(have),
        )



    def _navigation(self) -> NavigationTelemetry:
        """Navigation section from the navigator, or UNAVAILABLE."""
        nav = self.navigator
        if nav is None:
            return NavigationTelemetry()
        status: Any = None
        for attr in ("status", "snapshot"):
            value = _read_attr(nav, attr, self.log)
            if value is not None:
                status = value
                break
        if status is None:
            return NavigationTelemetry()
        state = _enum_str(status)
        goal = getattr(nav, "goal", None)
        goal_name = getattr(goal, "name", None)
        route = _route_points(nav, self.log)
        # Reuse the same guarded pose resolver as the position section.
        # Passing ``current_pose`` itself (it is a *method*) would make every
        # progress value None without raising.
        progress = _goal_progress(self._pose(), goal)
        avoidance = _enum_str(getattr(nav, "last_avoidance", None))
        present = any(v is not None for v in (state, goal_name, route, progress))
        return NavigationTelemetry(
            state=state,
            current_goal=goal_name,
            route=route,
            progress=progress,
            avoidance=avoidance,
            source=self._src(present),
        )

    def _safety(self, state: Dict[str, Any]) -> SafetyTelemetry:
        """Safety section from ``RobotState`` plus the hazard layer's verdict.

        The mode field is authoritative for the E-STOP flag: only
        ``SAFETY_STOP`` is reported as an active emergency stop, so an
        acknowledged-but-still-stopped robot is never mislabelled as moving.

        ``RobotState.to_dict()`` publishes a single ``safety`` string (the
        rendered :class:`SafetyDecision`), so the action is taken from that
        when present; the manager's last decision is consulted as a fallback
        for a structured action/reasons pair.
        """
        mode = _enum_str(state.get("mode"))
        estop = mode == "SAFETY_STOP"
        action = _enum_str(state.get("safety_action")) or _enum_str(
            state.get("safety")
        )
        reasons = tuple(
            str(r) for r in (state.get("safety_reasons") or ()) if r
        )
        if not reasons:
            decision = self._last_decision()
            if decision is not None:
                action = action or _enum_str(
                    getattr(decision, "action", None)
                )
                reasons = tuple(
                    str(r) for r in (getattr(decision, "reasons", ()) or ())
                    if r
                )
        hazard = self._hazard()
        return SafetyTelemetry(
            action=action,
            state=mode,
            emergency_stop=estop,
            reasons=reasons,
            hazard_state=hazard.state,
            hazard_latched=hazard.latched,
            hazard_source=hazard.source,
            # The Layer-3 verdict is read straight from the robot manager, so
            # it carries the runtime's own provenance.
            source=self._runtime_source,
        )

    def _last_decision(self) -> Any:
        """The manager's most recent :class:`SafetyDecision`, or ``None``."""
        robot = self.robot
        if robot is None:
            return None
        return getattr(robot, "_last_decision", None)

    def _hazard(self) -> HazardTelemetry:
        """Hazard section from the attached ``HazardManager``, if any.

        Reuses ``HazardManager.snapshot()`` verbatim so the dashboard cannot
        disagree with ``GET /hazard``. A failure or a missing layer yields
        ``state=None`` — *no assessment*, which is deliberately distinct from
        ``NORMAL`` — and an UNAVAILABLE source.
        """
        layer = self._hazard_manager()
        if layer is None:
            return HazardTelemetry()
        try:
            snap = layer.snapshot()
        except Exception as exc:  # noqa: BLE001
            self.log.debug("telemetry: hazard snapshot failed: %s", exc)
            return HazardTelemetry()
        if not isinstance(snap, dict) or not snap.get("attached"):
            return HazardTelemetry()
        active = _dict_tuple(snap.get("active_events"))
        recent = _dict_tuple(snap.get("recent_events"))
        return HazardTelemetry(
            state=snap.get("state"),
            latched=bool(snap.get("latched")),
            active=active,
            recent=recent,
            events_recorded=int(snap.get("events_recorded") or 0),
            source=self._src(True),
        )

    def _hazard_manager(self) -> Any:
        """Locate the attached hazard layer without importing it eagerly.

        ``RobotManager.attach_hazard`` stores it as the public ``hazard``
        attribute; a ``_hazard_manager`` alias is also accepted so the
        collector keeps working if that private name is ever introduced.
        """
        robot = self.robot
        for attr in ("hazard", "_hazard_manager"):
            layer = getattr(robot, attr, None)
            if layer is not None:
                return layer
        getter = getattr(robot, "hazard_manager", None)
        if callable(getter):
            try:
                return getter()
            except Exception as exc:  # noqa: BLE001
                self.log.debug("telemetry: hazard_manager() failed: %s", exc)
        return None



    def _battery(self) -> BatteryTelemetry:
        """Battery is UNAVAILABLE until real hardware reports it.

        There is no battery driver in the project. A mock voltage would be a
        fabricated measurement, so every field stays ``None`` with an explicit
        UNAVAILABLE source for the UI to render as "not connected".
        """
        return BatteryTelemetry()

    def _sensors(self, state: Dict[str, Any]) -> SensorTelemetry:
        """Ultrasonic distances from the runtime's last sensor reading.

        ``RobotState.to_dict()`` publishes the four distances as *top-level*
        keys (``front_cm`` ... ``rear_cm``); a nested ``sensors`` mapping is
        also accepted so a richer runtime can supply the same section. A
        missing echo is ``None`` (the runtime's own "no valid echo" sentinel),
        never a fabricated zero distance.
        """
        sensor = state.get("sensors")
        if not isinstance(sensor, dict):
            sensor = state
        values = {}
        for key, field_name in (
            ("front_cm", "front_cm"), ("front", "front_cm"),
            ("left_cm", "left_cm"), ("left", "left_cm"),
            ("right_cm", "right_cm"), ("right", "right_cm"),
            ("rear_cm", "rear_cm"), ("rear", "rear_cm"),
        ):
            if field_name in values:
                continue
            raw = sensor.get(key)
            if _is_number(raw):
                # Distances are centimetres in the existing sensor contract.
                values[field_name] = int(float(raw))
        return SensorTelemetry(source=self._src(bool(values)), **values)

    def _mission(self) -> MissionTelemetry:
        """Mission section from the warehouse manager, or UNAVAILABLE."""
        wh = self.warehouse
        if wh is None:
            return MissionTelemetry()
        fn = getattr(wh, "status", None)
        if not callable(fn):
            return MissionTelemetry()
        try:
            data = fn()
        except Exception as exc:  # noqa: BLE001
            self.log.debug("telemetry: warehouse.status() failed: %s", exc)
            return MissionTelemetry()
        if not isinstance(data, dict):
            return MissionTelemetry()
        current = data.get("current_task")
        if isinstance(current, dict):
            task_id = current.get("task_id") or current.get("id")
            task_type = current.get("type")
            task_status = current.get("status")
        else:
            task_id = current if isinstance(current, str) else None
            task_type = task_status = None
        return MissionTelemetry(
            mission_id=data.get("mission_id"),
            current_task=task_id,
            current_task_type=_enum_str(task_type),
            current_task_status=_enum_str(task_status),
            queued=int(data.get("queued") or 0),
            completed_tasks=int(data.get("completed") or 0),
            failed_tasks=int(data.get("failed") or 0),
            source=self._src(True),
        )

    def _camera(self) -> CameraTelemetry:
        """Camera status/metadata — never image bytes.

        Supports both camera shapes already in the repo:

        * the C8 :class:`~amr.camera.frame.CameraSource` protocol
          (``describe()`` returning ``status``/``simulated``/``name``), and
        * the legacy :class:`~amr.camera.camera_manager.CameraManager`
          (``describe()`` returning ``available``/``device``/``resolution``).

        The source tag is derived from what the backend actually reports, never
        from the runtime's global mode: a mock or simulated camera is tagged
        ``SIMULATION`` even when the rest of the stack runs live.
        """
        cam = self.camera
        if cam is None:
            return CameraTelemetry()
        fn = getattr(cam, "describe", None)
        if not callable(fn):
            return CameraTelemetry()
        try:
            info = fn()
        except Exception as exc:  # noqa: BLE001
            # A camera that *fails to describe itself* is a fault, not an
            # absent camera: reporting UNAVAILABLE here would hide a broken
            # subsystem behind the same shape as "no camera configured".
            self.log.warning("telemetry: camera.describe() failed: %s", exc)
            return CameraTelemetry(
                status=CameraStatus.ERROR, error=str(exc),
            )
        if not isinstance(info, dict):
            return CameraTelemetry()


        # C8 sources publish an explicit status + simulated flag; the legacy
        # manager publishes available/device/resolution instead.
        raw_status = info.get("status")
        available = bool(info.get("available"))
        simulated = bool(info.get("simulated"))
        backend = info.get("backend")
        source_name = info.get("name") or info.get("source") or backend

        if raw_status is not None:
            status = CameraStatus.parse(raw_status)
            available = status in (CameraStatus.LIVE, CameraStatus.SIMULATION)
            simulated = simulated or status is CameraStatus.SIMULATION
            tag = _SOURCE_FOR_STATUS.get(status, DataSource.UNAVAILABLE)
        else:
            # Legacy CameraManager: no status field, infer from availability.
            status = None
            tag = DataSource.UNAVAILABLE
            if available:
                tag = DataSource.SIMULATION if self.simulated else DataSource.LIVE

        # A frame, when the source already has one, supplies the honest
        # resolution/format/frame-id. Absent a frame these stay None.
        frame = self._latest_camera_frame(cam)
        width = info.get("width")
        height = info.get("height")
        fmt = info.get("format")
        frame_id = info.get("frame_id")
        timestamp = None
        has_frame = False
        if frame is not None:
            width = frame.width if width is None else width
            height = frame.height if height is None else height
            fmt = frame.format if fmt is None else fmt
            frame_id = frame.frame_id if not frame_id else frame_id
            timestamp = frame.timestamp
            has_frame = frame.data is not None
            if frame.status is CameraStatus.SIMULATION:
                simulated, tag = True, DataSource.SIMULATION
                status = CameraStatus.SIMULATION

        if not simulated and frame is None:
            # Never claim a live source for a frame we cannot actually see.
            if status is None and not available:
                tag = DataSource.UNAVAILABLE

        # `resolution` is the legacy C7 field; derive it from the C8 dimensions
        # so the two can never disagree about the same camera.
        resolution = _resolution(info.get("resolution"))
        if resolution is None and _is_number(width) and _is_number(height):
            resolution = f"{int(width)}x{int(height)}"

        return CameraTelemetry(
            # A typed CameraStatus throughout; a legacy backend that gives no
            # explicit state is mapped onto the two nearest lifecycle states.
            status=(status if status is not None else
                    (CameraStatus.LIVE if available else CameraStatus.UNAVAILABLE)),
            source_name=source_name,
            device=info.get("device"),
            resolution=resolution,
            # fps is never invented: it is only known with a real capture loop.
            fps=info.get("fps") if _is_number(info.get("fps")) else None,
            source=tag,
            width=width if _is_number(width) else None,
            height=height if _is_number(height) else None,
            format=fmt,
            frame_id=int(frame_id) if _is_number(frame_id) else 0,
            timestamp=timestamp,
            has_frame=bool(has_frame),
            error=info.get("reason") or info.get("error"),
        )

    def _latest_camera_frame(self, cam: Any) -> Optional[CameraFrame]:
        """Return a cached frame if the source exposes one, else ``None``.

        Deliberately does **not** call ``read()``: telemetry must not trigger a
        capture, allocate image bytes, or block the control loop. Only an
        already-available frame attribute is used.
        """
        for attr in ("last_frame", "_last_frame", "latest_frame"):
            frame = getattr(cam, attr, None)
            if isinstance(frame, CameraFrame):
                return frame
        return None

    def _system(self, state: Dict[str, Any]) -> SystemTelemetry:
        """Process/runtime identity and uptime."""
        return SystemTelemetry(
            uptime=max(0.0, self._clock() - self._started_at),
            software_version=self.software_version,
            robot_id=_first_str(
                state.get("robot_id"),
                getattr(self.robot, "robot_id", None),
            ),
            connected=bool(state.get("connected")),
            mode=_enum_str(state.get("mode")),
            last_error=state.get("last_error"),
            started_at=self._started_at,
            source=self._runtime_source,
            simulated=self.simulated,
        )



# --------------------------------------------------------------------------- #
# Small defensive helpers. Each tolerates a missing/None/odd value rather than
# assuming the runtime published a perfectly-formed structure.
# --------------------------------------------------------------------------- #
def _is_number(value: Any) -> bool:
    """``True`` for a real finite number (rejects bool, NaN, inf, strings)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return number == number and number not in (float("inf"), float("-inf"))


def _enum_str(value: Any) -> Optional[str]:
    """Render an enum/str/None as an upper-case string, or ``None``."""
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip()
    return text.upper() if text else None


def _first_str(*values: Any) -> Optional[str]:
    """First non-empty string among ``values``, else ``None``."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _dict_tuple(value: Any) -> Tuple[Dict[str, Any], ...]:
    """Coerce a list of mappings into a tuple of plain dicts."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(v) for v in value if isinstance(v, dict))


def _resolution(value: Any) -> Optional[str]:
    """Format a ``(w, h)`` resolution as ``"640x480"``, or pass a string."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (tuple, list)) and len(value) == 2:
        if all(_is_number(v) for v in value):
            return f"{int(value[0])}x{int(value[1])}"
    return None


def _route_points(nav: Any, log: Any = None) -> Tuple[Dict[str, float], ...]:
    """Planned route waypoints, in the navigator's own coordinates.

    Reuses the navigator's planner so the 2D map, the 3D twin and the
    navigator all agree on one coordinate system (warehouse metres, y-up).

    ``plan()`` takes a required ``goal`` argument, so the active goal is read
    from the public ``goal`` property first. Probing ``plan`` blindly would
    raise ``TypeError`` and silently report every route as unavailable.
    """
    try:
        goal = _read_attr(nav, "goal", log)
        if goal is None:
            return ()
        poses = nav.plan(goal)
    except Exception as exc:  # noqa: BLE001 - telemetry must never raise
        if log is not None:
            log.debug("telemetry: route unavailable: %s", exc)
        return ()
    out: list = []
    for p in (poses or ()):
        data = p.to_dict() if hasattr(p, "to_dict") else None
        if not isinstance(data, dict):
            continue
        try:
            out.append({
                "x": float(data["x"]),
                "y": float(data["y"]),
                "theta": float(data.get("theta", 0.0)),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(out)


def _read_attr(obj: Any, name: str, log: Any = None) -> Any:
    """Read ``obj.name`` whether it is a property, method or plain attribute.

    Runtime collaborators are inconsistent here: ``Navigator.status`` is a
    property while some other implementations expose ``status()``. Probing only
    callables silently reports UNAVAILABLE for a perfectly healthy navigator,
    so both shapes are accepted. A raising getter degrades to ``None`` instead
    of taking the dashboard down.
    """
    try:
        value = getattr(obj, name, None)
    except Exception as exc:  # noqa: BLE001
        if log is not None:
            log.debug("telemetry: reading %s failed: %s", name, exc)
        return None
    if callable(value):
        try:
            return value()
        except Exception as exc:  # noqa: BLE001
            if log is not None:
                log.debug("telemetry: %s() failed: %s", name, exc)
            return None
    return value


def _goal_progress(pose: Any, goal: Any) -> Optional[float]:
    """Straight-line progress toward the goal as a 0..1 fraction.

    Purely geometric, so it is honest about its limitations: it measures how
    much of the *direct* distance has been covered, not path-following
    completion. ``None`` when either pose is unknown.
    """
    if pose is None or goal is None:
        return None
    target = getattr(goal, "pose", goal)
    gx, gy = getattr(target, "x", None), getattr(target, "y", None)
    px, py = getattr(pose, "x", None), getattr(pose, "y", None)
    if not all(_is_number(v) for v in (gx, gy, px, py)):
        return None
    start = (0.0, 0.0)
    total = ((gx - start[0]) ** 2 + (gy - start[1]) ** 2) ** 0.5
    remaining = ((gx - px) ** 2 + (gy - py) ** 2) ** 0.5
    if total <= 1e-9:
        return None
    fraction = 1.0 - (remaining / total)
    return max(0.0, min(1.0, fraction))

