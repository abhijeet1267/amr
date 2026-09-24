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
    "STATE_COLORS",
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
    "events_from_snapshot",
    "read_events",
    "render_map_svg",
    "severity_for",
    "zones_from_config",
]

#: Lazily re-exported from :mod:`amr.hazard.visualisation`. Kept lazy so that
#: ``python -m amr.hazard.visualisation`` does not pre-import the module before
#: runpy executes it (runpy would emit a RuntimeWarning otherwise).
_LAZY_VISUALISATION = frozenset(
    {"STATE_COLORS", "events_from_snapshot", "render_map_svg"}
)


def __getattr__(name: str):
    if name in _LAZY_VISUALISATION:
        from . import visualisation

        return getattr(visualisation, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
