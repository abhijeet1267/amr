"""Read-only telemetry contract for the monitoring dashboard (C7).

This module defines the *stable data shape* the dashboard and any future
replay/recording system consume. It is deliberately inert: frozen dataclasses
plus JSON serialisation, no I/O, no hardware access, no dependencies.

Two rules govern everything here:

1. **Never fabricate a measurement.** A value that no real sensor produced is
   ``None`` and its section's :class:`DataSource` is ``UNAVAILABLE``. A
   dashboard must be able to tell "battery at 0%" from "no battery sensor".
2. **Never gain a control path.** Nothing in this package imports a motor
   driver, the serial transport, or the command API. Telemetry is a one-way
   projection of the existing runtime.

``SIMULATION`` exists so a mock-backed runtime can be labelled honestly. A
simulated value is still a value — it just must never be presented as a
physical measurement, and the source tag is what says so.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

#: Telemetry schema version. Bump when a field is removed or changes meaning.
#: Additive fields do not require a bump (older readers ignore what they
#: do not know), which keeps the contract forward-compatible.
TELEMETRY_SCHEMA_VERSION = "1.0"


def _f(value: Any) -> Optional[float]:
    """Coerce to a finite float, or ``None`` (never NaN/inf in telemetry)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


class DataSource(str, Enum):
    """Where a value actually came from.

    ``LIVE``        read from real hardware in this process
    ``SIMULATION``  produced by a mock / simulated backend
    ``UNAVAILABLE`` not measured — the value is absent, not zero
    """

    LIVE = "LIVE"
    SIMULATION = "SIMULATION"
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def simulated(self) -> bool:
        return self is DataSource.SIMULATION

    @property
    def available(self) -> bool:
        return self is not DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "available": self.available,
            "simulated": self.simulated,
        }


@dataclass(frozen=True)
class Vector3:
    """A world-frame position in metres (``z`` is unused on a 2D AMR)."""

    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {"x": self.x, "y": self.y, "z": self.z, "source": self.source.value}

    @classmethod
    def from_pose(cls, pose: Any, source: DataSource) -> "Vector3":
        """Build from any object/dict exposing ``x``/``y`` (``theta`` ignored)."""
        if pose is None:
            return cls(source=DataSource.UNAVAILABLE)
        if isinstance(pose, dict):
            x, y = pose.get("x"), pose.get("y")
        else:
            x, y = getattr(pose, "x", None), getattr(pose, "y", None)
        if x is None or y is None:
            return cls(source=DataSource.UNAVAILABLE)
        return cls(x=_f(x), y=_f(y), z=None, source=source)


@dataclass(frozen=True)
class Orientation:
    """Heading in radians (``yaw``). Values are always finite floats."""

    yaw: Optional[float] = None
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {"yaw": self.yaw, "source": self.source.value}

    @classmethod
    def from_pose(cls, pose: Any, source: DataSource) -> "Orientation":
        if pose is None:
            return cls(source=DataSource.UNAVAILABLE)
        theta = (
            pose.get("theta") if isinstance(pose, dict)
            else getattr(pose, "theta", None)
        )
        if theta is None:
            return cls(source=DataSource.UNAVAILABLE)
        return cls(yaw=_f(theta), source=source)


@dataclass(frozen=True)
class Velocity:
    """Linear (m/s) and angular (rad/s) velocity.

    The AMR has no wheel-odometry feed today, so these stay ``None`` unless a
    provider supplies them. A commanded PWM duty cycle is **not** a velocity
    and is deliberately not reported here.
    """

    linear: Optional[float] = None
    angular: Optional[float] = None
    source: DataSource = DataSource.UNAVAILABLE

    @property
    def moving(self) -> bool:
        return bool(self.linear or self.angular)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "linear": self.linear,
            "angular": self.angular,
            "moving": self.moving,
            "source": self.source.value,
        }


@dataclass(frozen=True)
class NavigationTelemetry:
    """Navigation lifecycle, read from the navigator's public state."""

    state: Optional[str] = None
    current_goal: Optional[str] = None
    route: Tuple[Dict[str, float], ...] = ()
    progress: Optional[float] = None
    avoidance: Optional[str] = None
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "current_goal": self.current_goal,
            "route": [dict(p) for p in self.route],
            "progress": self.progress,
            "avoidance": self.avoidance,
            "source": self.source.value,
        }


@dataclass(frozen=True)
class SafetyTelemetry:
    """The layered safety verdict (Layer 3 + Layer 3.5)."""

    action: Optional[str] = None
    state: Optional[str] = None
    emergency_stop: bool = False
    reasons: Tuple[str, ...] = ()
    hazard_state: Optional[str] = None
    hazard_latched: bool = False
    hazard_source: DataSource = DataSource.UNAVAILABLE
    #: Provenance of the Layer-3 verdict itself (distinct from
    #: ``hazard_source``, which tags the Layer-3.5 layer feeding it).
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "state": self.state,
            "emergency_stop": self.emergency_stop,
            "reasons": list(self.reasons),
            "hazard_state": self.hazard_state,
            "hazard_latched": self.hazard_latched,
            "hazard_source": self.hazard_source.value,
            "source": self.source.value,
        }


@dataclass(frozen=True)
class HazardTelemetry:
    """Active hazards, copied from the C5 event log (never re-derived)."""

    state: Optional[str] = None
    latched: bool = False
    active: Tuple[Dict[str, Any], ...] = ()
    recent: Tuple[Dict[str, Any], ...] = ()
    events_recorded: int = 0
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "latched": self.latched,
            "active": [dict(e) for e in self.active],
            "recent": [dict(e) for e in self.recent],
            "events_recorded": self.events_recorded,
            "source": self.source.value,
        }


@dataclass(frozen=True)
class BatteryTelemetry:
    """Battery state. There is **no** battery sensor in this robot yet.

    ``percentage``/``voltage`` therefore stay ``None`` with source
    ``UNAVAILABLE`` until a real pack monitor is wired in. Reporting a
    plausible-looking percentage here would be fabrication.
    """

    percentage: Optional[float] = None
    voltage: Optional[float] = None
    charging: Optional[bool] = None
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "percentage": self.percentage,
            "voltage": self.voltage,
            "charging": self.charging,
            "source": self.source.value,
        }


@dataclass(frozen=True)
class SensorTelemetry:
    """Ultrasonic distances in centimetres.

    ``None`` means "no valid echo", which the existing ultrasonic layer already
    normalises (``-1`` -> ``None``); it is not a distance of zero.
    """

    front_cm: Optional[int] = None
    left_cm: Optional[int] = None
    right_cm: Optional[int] = None
    rear_cm: Optional[int] = None
    source: DataSource = DataSource.UNAVAILABLE

    @property
    def any_available(self) -> bool:
        return any(
            v is not None
            for v in (self.front_cm, self.left_cm, self.right_cm, self.rear_cm)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "front_cm": self.front_cm,
            "left_cm": self.left_cm,
            "right_cm": self.right_cm,
            "rear_cm": self.rear_cm,
            "source": self.source.value,
        }



@dataclass(frozen=True)
class MissionTelemetry:
    """Warehouse task progress, copied from ``WarehouseTaskManager.status()``."""

    mission_id: Optional[str] = None
    current_task: Optional[str] = None
    current_task_type: Optional[str] = None
    current_task_status: Optional[str] = None
    queued: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "current_task": self.current_task,
            "current_task_type": self.current_task_type,
            "current_task_status": self.current_task_status,
            "queued": self.queued,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "source": self.source.value,
        }


@dataclass(frozen=True)
class CameraTelemetry:
    """Camera presence/status. Frames are served by the existing /image route."""

    status: Optional[str] = None
    source_name: Optional[str] = None
    device: Optional[str] = None
    resolution: Optional[str] = None
    fps: Optional[float] = None  # not measurable without a capture pipeline
    source: DataSource = DataSource.UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "source_name": self.source_name,
            "device": self.device,
            "resolution": self.resolution,
            "fps": self.fps,
            "source": self.source.value,
        }


@dataclass(frozen=True)
class SystemTelemetry:
    """Process/runtime facts — always genuinely observable."""

    uptime: float = 0.0
    software_version: Optional[str] = None
    schema_version: str = TELEMETRY_SCHEMA_VERSION
    robot_id: Optional[str] = None
    connected: bool = False
    mode: Optional[str] = None
    last_error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    #: The runtime's own provenance: LIVE or SIMULATION. There is no hardware
    #: "source" for process facts, so this is always one of those two.
    source: DataSource = DataSource.SIMULATION
    #: Mirrors :attr:`TelemetrySnapshot.simulated` so the system block is
    #: self-describing even when it is read on its own.
    simulated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uptime": round(max(0.0, time.time() - self.started_at), 3),
            "software_version": self.software_version,
            "schema_version": self.schema_version,
            "robot_id": self.robot_id,
            "connected": self.connected,
            "mode": self.mode,
            "last_error": self.last_error,
            "source": self.source.value,
            "simulated": self.simulated,
        }


@dataclass(frozen=True)
class TelemetrySnapshot:
    """One immutable, JSON-serialisable picture of the whole AMR.

    Every field is optional: an absent subsystem is represented by an
    ``UNAVAILABLE`` source rather than a zero, so a consumer can always tell
    "not measured" from "measured as zero".
    """

    timestamp: float = field(default_factory=time.time)
    simulated: bool = False
    position: Vector3 = field(default_factory=Vector3)
    orientation: Orientation = field(default_factory=Orientation)
    velocity: Velocity = field(default_factory=Velocity)
    navigation: NavigationTelemetry = field(default_factory=NavigationTelemetry)
    safety: SafetyTelemetry = field(default_factory=SafetyTelemetry)
    hazards: HazardTelemetry = field(default_factory=HazardTelemetry)
    battery: BatteryTelemetry = field(default_factory=BatteryTelemetry)
    sensors: SensorTelemetry = field(default_factory=SensorTelemetry)
    mission: MissionTelemetry = field(default_factory=MissionTelemetry)
    camera: CameraTelemetry = field(default_factory=CameraTelemetry)
    system: SystemTelemetry = field(default_factory=SystemTelemetry)

    @property
    def source(self) -> DataSource:
        """Overall runtime provenance — LIVE or SIMULATION.

        A convenience mirror of ``system.source`` so a client can badge the
        whole dashboard from one field. ``UNAVAILABLE`` means no AMR runtime
        is attached at all, which is different from "attached but simulated".
        """
        return self.system.source

    @property
    def schema_version(self) -> str:
        """The contract version this snapshot conforms to.

        A property, not a field: the version describes the *contract*, so it
        is identical for every snapshot and cannot drift per instance.
        """
        return TELEMETRY_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        """JSON-friendly dict. Keys are explicit so a rename is a visible diff.

        ``mode`` and ``robot_id`` are mirrored at the top level because the
        telemetry contract lists them there, while ``system`` remains their
        single source of truth — the values are identical, never independent.
        """
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "timestamp": self.timestamp,
            "simulated": self.simulated,
            "source": self.source.value,
            "mode": self.system.mode,
            "robot_id": self.system.robot_id,
            "position": self.position.to_dict(),
            "orientation": self.orientation.to_dict(),
            "velocity": self.velocity.to_dict(),
            "navigation": self.navigation.to_dict(),
            "safety": self.safety.to_dict(),
            "hazards": self.hazards.to_dict(),
            "battery": self.battery.to_dict(),
            "sensors": self.sensors.to_dict(),
            "mission": self.mission.to_dict(),
            "camera": self.camera.to_dict(),
            "system": self.system.to_dict(),
        }

    def sources(self) -> Dict[str, str]:
        """Per-subsystem source tag — what the dashboard badges render."""
        return {
            "position": self.position.source.value,
            "orientation": self.orientation.source.value,
            "velocity": self.velocity.source.value,
            "navigation": self.navigation.source.value,
            "sensors": self.sensors.source.value,
            "battery": self.battery.source.value,
            "hazards": self.hazards.source.value,
            "mission": self.mission.source.value,
            "camera": self.camera.source.value,
            "safety": self.safety.source.value,
            "system": self.system.source.value,
        }


__all__ = [
    "TELEMETRY_SCHEMA_VERSION",
    "DataSource",
    "Vector3",
    "Orientation",
    "Velocity",
    "NavigationTelemetry",
    "SafetyTelemetry",
    "HazardTelemetry",
    "BatteryTelemetry",
    "SensorTelemetry",
    "MissionTelemetry",
    "CameraTelemetry",
    "SystemTelemetry",
    "TelemetrySnapshot",
]

