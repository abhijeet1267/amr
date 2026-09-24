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
from .types import (
    TELEMETRY_SCHEMA_VERSION,
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

__all__ = [
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
    "TelemetryCollector",
    "TelemetrySnapshot",
    "Vector3",
    "Velocity",
]
