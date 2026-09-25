"""Read-only telemetry projection of the AMR runtime (C7 dashboard foundation).

This package is a **viewer**, never a controller. It exposes the existing
runtime state (robot, navigation, safety, hazards, sensors, mission, camera) as
one stable, JSON-serialisable contract for the dashboard and digital twin.

Safety contract
---------------
Nothing in :mod:`amr.telemetry` may move the robot. The collector never calls
``RobotManager.tick()`` / ``dispatch()`` and imports no motor driver, transport
or GPIO, so reading telemetry cannot advance the control loop or actuate
hardware. All motion continues to flow exclusively through the existing,
safety-gated ``POST /command`` path.
"""
from .collector import TelemetryCollector
from .console import (
    AT_ARRIVAL,
    CONSOLE_SCHEMA_VERSION,
    NOT_AVAILABLE,
    build_console_state,
    component_health,
    hazard_summary,
    mission_phase,
    route_progress_points,
    source_of,
)
from .recorder import (
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_RECORDING_CAPACITY,
    RECORDING_SCHEMA_VERSION,
    ReplayFrame,
    TelemetryRecorder,
    frame_from_snapshot,
    read_recording,
)
from .auto_record import AutoRecorder, recording_name
from .replay import (
    STANDARD_SPEEDS,
    ReplayPlayer,
    ReplayState,
)
from .types import (
    TELEMETRY_SCHEMA_VERSION,
    BatteryTelemetry,
    CameraStatus,
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

__all__ = [
    "AT_ARRIVAL",
    "AutoRecorder",
    "CONSOLE_SCHEMA_VERSION",
    "DEFAULT_MIN_INTERVAL_S",
    "DEFAULT_RECORDING_CAPACITY",
    "NOT_AVAILABLE",
    "RECORDING_SCHEMA_VERSION",
    "STANDARD_SPEEDS",
    "TELEMETRY_SCHEMA_VERSION",
    "BatteryTelemetry",
    "CameraTelemetry",
    "DataSource",
    "HazardTelemetry",
    "MissionTelemetry",
    "NavigationTelemetry",
    "Orientation",
    "SafetyTelemetry",
    "SensorTelemetry",
    "SystemTelemetry",
    "ReplayFrame",
    "ReplayPlayer",
    "ReplayState",
    "TelemetryCollector",
    "TelemetryRecorder",
    "TelemetrySnapshot",
    "Vector3",
    "Velocity",
    "build_console_state",
    "component_health",
    "frame_from_snapshot",
    "hazard_summary",
    "mission_phase",
    "read_recording",
    "recording_name",
    "route_progress_points",
    "source_of",
]
