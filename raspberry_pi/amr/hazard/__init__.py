"""Context-aware multi-hazard safety layer (Layer 3.5 on the Pi).

A deterministic aggregation layer over many hazard inputs — gas/smoke sensors,
camera vision, fire/human detection, robot state, navigation state and robot
location — producing ``NORMAL`` / ``WARNING`` / ``SLOW`` / ``STOP`` /
``EMERGENCY`` and recording an auditable event history.

It **escalates only**: it can tighten the Layer-3 proximity decision but never
relax it, and it never commands the motors directly — motion is still gated by
:class:`amr.robot.robot_manager.RobotManager`.

See ``docs/hazard.md`` and ``config/hazard.yaml``.
"""

from .event_log import DEFAULT_CAPACITY, HazardEventLog, read_events
from .manager import (
    DEFAULT_EMERGENCY_KINDS,
    DEFAULT_SLOW_KINDS,
    HazardManager,
)
from .sources import (
    GasSensorSource,
    HazardSource,
    HazardZone,
    RestrictedZoneSource,
    RobotStateSource,
    VisionHazardSource,
    severity_for,
    zones_from_config,
)
from .types import (
    HazardEvent,
    HazardKind,
    HazardLocation,
    HazardReading,
    HazardSeverity,
    HazardState,
    HazardStatus,
)

__all__ = [
    "DEFAULT_CAPACITY",
    "DEFAULT_EMERGENCY_KINDS",
    "DEFAULT_SLOW_KINDS",
    "GasSensorSource",
    "HazardEvent",
    "HazardEventLog",
    "HazardKind",
    "HazardLocation",
    "HazardManager",
    "HazardReading",
    "HazardSeverity",
    "HazardSource",
    "HazardState",
    "HazardStatus",
    "HazardZone",
    "RestrictedZoneSource",
    "RobotStateSource",
    "VisionHazardSource",
    "read_events",
    "severity_for",
    "zones_from_config",
]
