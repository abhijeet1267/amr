"""Typed configuration loading for the AMR stack.

Configuration lives in YAML files under ``config/`` (see the repository root):

* ``serial.yaml``  — serial port / baudrate / timeouts / protocol version
* ``safety.yaml``  — watchdog + sensor safety thresholds
* ``robot.yaml``   — robot geometry, motor limits, sensor pins, camera

Design goals
------------
* **No hardcoding** — every tunable lives in a YAML file with a sane default.
* **Hardware-agnostic** — unknown hardware details are represented as explicit
  placeholder values (``TODO_VERIFY`` / ``None``) rather than invented numbers.
* **Robust loading** — a missing file or a missing key falls back to defaults;
  a malformed file raises :class:`ConfigError` with a clear message.
* **Status flags** — safety values carry a ``status`` of ``NOT_VERIFIED`` until
  they have been physically validated (see docs/safety.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class ConfigError(Exception):
    """Raised when a configuration file is malformed or a value is invalid."""


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class SerialConfig:
    """USB serial link between the Pi and the Arduino."""

    port: str = "/dev/ttyACM0"
    baudrate: int = 9600
    timeout: float = 1.0            # default per-command timeout (s)
    read_timeout_s: float = 1.0
    write_timeout_s: float = 0.5
    protocol_version: str = "1.0"


@dataclass
class SafetyConfig:
    """Layered safety thresholds.

    ``status`` is ``NOT_VERIFIED`` by default: these are configurable *test*
    values and must be physically validated before the robot is trusted with
    real speed. See docs/safety.md.
    """

    watchdog_timeout_ms: int = 1000
    front_stop_distance_cm: int = 20
    rear_stop_distance_cm: int = 20
    left_stop_distance_cm: int = 15
    right_stop_distance_cm: int = 15
    sensor_min_valid_cm: int = 2
    sensor_max_valid_cm: int = 400
    status: str = "NOT_VERIFIED"


@dataclass
class MotorConfig:
    """Motor speed limits. ``max_speed`` maps to PWM duty (0..255)."""

    max_speed: int = 255


@dataclass
class SensorPinConfig:
    """Pin assignment for one ultrasonic sensor.

    The values are placeholders until the actual wiring is documented.
    """

    trig: str = "TODO_VERIFY"
    echo: str = "TODO_VERIFY"


@dataclass
class UltrasonicConfig:
    """Four ultrasonic sensors (front/left/right/rear) on the Arduino."""

    front: SensorPinConfig = field(default_factory=SensorPinConfig)
    left: SensorPinConfig = field(default_factory=SensorPinConfig)
    right: SensorPinConfig = field(default_factory=SensorPinConfig)
    rear: SensorPinConfig = field(default_factory=SensorPinConfig)
    poll_interval_ms: int = 100


@dataclass
class CameraConfig:
    """Camera settings. ``available`` is detected at runtime; never assumed."""

    enabled: bool = True
    device: str = "pi"               # "pi" (raspichill/libcamera) or "v4l2"
    resolution: str = "1280x720"


@dataclass
class RobotConfig:
    """Robot identity and geometry.

    Geometry values default to ``None`` (unknown) — they MUST be measured
    physically before odometry / Nav2 is used. See docs/hardware.md.
    """

    name: str = "amr-robot"
    wheel_track_m: Optional[float] = None      # distance between wheel centers
    wheel_diameter_m: Optional[float] = None   # rolling diameter
    motors: MotorConfig = field(default_factory=MotorConfig)
    ultrasonic: UltrasonicConfig = field(default_factory=UltrasonicConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)


@dataclass
class WarehouseConfig:
    """Warehouse task manager settings (Phase 16).

    ``locations`` maps ``name -> {x, y, theta}`` (or ``[x, y, theta]``) and
    describes the warehouse map. An empty mapping means "use the built-in
    default map" (see :func:`amr.warehouse.map.default_map`).
    """

    enabled: bool = False
    dock: str = "dock"
    task_speed: float = 0.5          # m/s (maps to drive max_pwm)
    turn_speed: float = 1.0          # rad/s
    wheel_base_m: float = 0.30       # nominal, until measured (robot.wheel_track_m)
    queue_max: int = 16
    manipulator: str = "mock"        # "mock" | "null"
    locations: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    """Aggregated, validated application configuration."""

    serial: SerialConfig
    safety: SafetyConfig
    robot: RobotConfig
    warehouse: WarehouseConfig
    config_dir: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _repo_root() -> Path:
    # <root>/raspberry_pi/amr/utils/config.py -> root is parents[3]
    return Path(__file__).resolve().parents[3]


def find_config_dir(explicit: Optional[str] = None) -> Path:
    """Resolve the configuration directory.

    Priority: explicit argument > ``$AMR_CONFIG_DIR`` > ``<repo>/config``.
    """
    if explicit:
        p = Path(explicit)
        if not p.is_dir():
            raise ConfigError(f"config directory not found: {p}")
        return p
    env = os.environ.get("AMR_CONFIG_DIR")
    if env:
        return Path(env)
    return _repo_root() / "config"


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:  # malformed YAML
        raise ConfigError(f"failed to parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _build(cls, data: dict, ctx: str) -> Any:
    """Build a dataclass from a dict, ignoring unknown keys, erroring on bad types."""
    data = data or {}
    known = {f.name: f for f in fields(cls) if f.name != "config_dir"}
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            # Tolerate (and ignore) unknown keys so config can be forward-compatible.
            continue
        kwargs[key] = value
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise ConfigError(f"invalid value in {ctx}: {exc}") from exc


def _build_pins(data: Optional[dict], ctx: str) -> SensorPinConfig:
    if not data:
        return SensorPinConfig()
    return _build(SensorPinConfig, dict(data), ctx)


def _build_ultrasonic(data: Optional[dict]) -> UltrasonicConfig:
    data = data or {}
    return UltrasonicConfig(
        front=_build_pins(data.get("front"), "ultrasonic.front"),
        left=_build_pins(data.get("left"), "ultrasonic.left"),
        right=_build_pins(data.get("right"), "ultrasonic.right"),
        rear=_build_pins(data.get("rear"), "ultrasonic.rear"),
        poll_interval_ms=int(data.get("poll_interval_ms", 100)),
    )


# --------------------------------------------------------------------------- #
# Public loader
# --------------------------------------------------------------------------- #
def load_config(config_dir: Optional[str] = None) -> AppConfig:
    """Load and validate the full application configuration.

    :param config_dir: override the config directory (used by tests / multi-bot).
    :raises ConfigError: if the directory is missing or a file is malformed.
    """
    cfg_dir = find_config_dir(config_dir)

    serial_data = _load_yaml(cfg_dir / "serial.yaml")
    safety_data = _load_yaml(cfg_dir / "safety.yaml")
    robot_data = _load_yaml(cfg_dir / "robot.yaml")
    warehouse_data = _load_yaml(cfg_dir / "warehouse.yaml")

    serial = _build(SerialConfig, serial_data.get("serial", {}), "serial")
    safety = _build(SafetyConfig, safety_data.get("safety", {}), "safety")

    robot_blob = robot_data.get("robot", robot_data) or {}
    robot = RobotConfig(
        name=str(robot_blob.get("name", "amr-robot")),
        wheel_track_m=robot_blob.get("wheel_track_m"),
        wheel_diameter_m=robot_blob.get("wheel_diameter_m"),
        motors=_build(MotorConfig, robot_blob.get("motors", {}), "robot.motors"),
        ultrasonic=_build_ultrasonic(robot_blob.get("ultrasonic")),
        camera=_build(CameraConfig, robot_blob.get("camera", {}), "robot.camera"),
    )

    warehouse_blob = warehouse_data.get("warehouse", warehouse_data) or {}
    warehouse = WarehouseConfig(
        enabled=bool(warehouse_blob.get("enabled", False)),
        dock=str(warehouse_blob.get("dock", "dock")),
        task_speed=float(warehouse_blob.get("task_speed", 0.5)),
        turn_speed=float(warehouse_blob.get("turn_speed", 1.0)),
        wheel_base_m=float(warehouse_blob.get("wheel_base_m", 0.30)),
        queue_max=int(warehouse_blob.get("queue_max", 16)),
        manipulator=str(warehouse_blob.get("manipulator", "mock")),
        locations=dict(warehouse_blob.get("locations", {}) or {}),
    )

    # ---- validation (fail fast on nonsense) ----
    _validate_serial(serial)
    _validate_safety(safety)
    _validate_motors(robot.motors)
    _validate_warehouse(warehouse)

    return AppConfig(
        serial=serial, safety=safety, robot=robot,
        warehouse=warehouse, config_dir=str(cfg_dir),
    )


def _validate_serial(c: SerialConfig) -> None:
    if not (9600 <= c.baudrate <= 115200):
        raise ConfigError(f"serial.baudrate {c.baudrate} out of expected range")
    if c.port:
        return
    raise ConfigError("serial.port is empty; set it in config/serial.yaml")


def _validate_safety(c: SafetyConfig) -> None:
    if c.watchdog_timeout_ms <= 0:
        raise ConfigError("safety.watchdog_timeout_ms must be > 0")
    for name in ("front", "rear", "left", "right"):
        val = getattr(c, f"{name}_stop_distance_cm")
        if val <= 0:
            raise ConfigError(f"safety.{name}_stop_distance_cm must be > 0")
    if c.sensor_min_valid_cm >= c.sensor_max_valid_cm:
        raise ConfigError(
            "safety.sensor_min_valid_cm must be < sensor_max_valid_cm"
        )


def _validate_motors(c: MotorConfig) -> None:
    if not (1 <= c.max_speed <= 255):
        raise ConfigError(f"motors.max_speed {c.max_speed} out of range [1,255]")


def _validate_warehouse(c: WarehouseConfig) -> None:
    if c.task_speed <= 0:
        raise ConfigError("warehouse.task_speed must be > 0")
    if c.turn_speed <= 0:
        raise ConfigError("warehouse.turn_speed must be > 0")
    if c.wheel_base_m <= 0:
        raise ConfigError("warehouse.wheel_base_m must be > 0")
    if c.queue_max < 1:
        raise ConfigError("warehouse.queue_max must be >= 1")
    if c.dock and not c.locations and c.dock != "dock":
        # No map supplied but a non-default dock requested: keep it, but the
        # map layer will fall back to the default (which defines "dock").
        pass
