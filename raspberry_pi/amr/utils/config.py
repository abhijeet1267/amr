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
from typing import Any, Dict, List, Optional

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
class AvoidanceConfig:
    """C6 obstacle-avoidance tuning (see ``config/safety.yaml``).

    ``enabled`` defaults to **False**: avoidance is opt-in, so an unconfigured
    or freshly-cloned robot behaves exactly as it did before C6. Every numeric
    bound is a conservative *software default* and is **not** physically
    validated — see ``docs/safety.md``.
    """

    enabled: bool = False
    #: Replans allowed per obstacle episode before the navigator reports
    #: ``FAILED``. This is the loop guard against repeated manoeuvres.
    max_replans: int = 3
    #: Speed scale (0..1) while executing a turn arc.
    turn_speed_scale: float = 0.5
    #: Duration (s) of a committed turn arc.
    turn_duration_s: float = 0.6
    #: Clearance (m) at or below which a side counts as blocked.
    open_clearance_m: float = 1.0


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
    #: C6 avoidance tuning; nested, so it is built explicitly in load_config().
    avoidance: AvoidanceConfig = field(default_factory=AvoidanceConfig)


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
    #: C13: the **detection identity** of this camera — the value a vision
    #: detector stamps onto ``VisionDetection.source`` (e.g. ``camera_front``).
    #:
    #: This is deliberately not the same as the frame's ``source``, which names
    #: the backend ("SimulatedCamera", "RaspberryPiCamera"). Declaring the
    #: identity is what lets a camera overlay pair a frame with the detections
    #: that actually came from it. ``None`` means "not declared", and the
    #: overlay then falls back to the backend name, which is correct only for a
    #: single-camera deployment.
    camera_id: Optional[str] = None


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
class HazardConfig:
    """Context-aware multi-hazard safety layer (see docs/hazard.md).

    ``status`` mirrors :class:`SafetyConfig`: it is ``NOT_VERIFIED`` until the
    gas/vision thresholds have been validated against real sensors in the real
    warehouse. These are *configurable test values*, not measured ones.

    ``enabled`` defaults to ``False`` so that adding this layer cannot change the
    behaviour of an existing deployment until an operator opts in.

    ``emergency_kinds`` / ``slow_kinds`` select which :class:`HazardKind` values
    escalate to ``EMERGENCY`` / ``SLOW``; ``None`` means "use the documented
    default", while an explicit empty list deliberately disables that band.
    """

    enabled: bool = False
    status: str = "NOT_VERIFIED"

    #: Speed multiplier applied in the SLOW state (0 < scale <= 1).
    slow_speed_scale: float = 0.5

    #: Ring-buffer size for recorded hazard events.
    max_events: int = 256

    #: Optional JSONL export path for hazard events (dashboard / visualisation).
    event_log_path: Optional[str] = None

    #: Gas / smoke sensor thresholds (same unit, see unit).
    gas_warn_at: float = 300.0
    gas_critical_at: float = 1000.0
    gas_unit: str = "ppm"

    #: Vision detector confidence thresholds (0..1).
    human_warn_at: float = 0.5
    human_critical_at: float = 0.8

    # ---- vision detector (C5) ------------------------------------------- #
    #: Master switch for the vision->hazard path. Defaults to ``False`` so an
    #: existing deployment is unaffected until an operator opts in.
    vision_enabled: bool = False

    #: Confidence band for a *generic* vision class. ``None`` means "reuse
    #: ``human_warn_at`` / ``human_critical_at``" so the two cannot drift apart
    #: silently. These are SOFTWARE DEFAULTS, not validated detection rates.
    vision_warn_at: Optional[float] = None
    vision_critical_at: Optional[float] = None

    #: Which detector labels are treated as hazards. ``None`` means "every
    #: label in ``amr.hazard.types.VISION_CLASS_TO_KIND``" (the default, and
    #: the recommended setting). An explicit list narrows the policy; unknown
    #: labels are rejected at load time rather than silently ignored.
    vision_classes: Optional[List[str]] = None

    #: Default camera identity stamped on detections that carry no source.
    vision_source: str = "simulated_camera"

    #: Kinds that latch EMERGENCY / reduce speed at WARNING severity.
    emergency_kinds: Optional[List[str]] = None
    slow_kinds: Optional[List[str]] = None

    #: Rectangular areas of interest: {name, x_min, x_max, y_min, y_max,
    #: severity?, kind?}. Empty means "no location rules".
    zones: List[Dict[str, Any]] = field(default_factory=list)

    def resolved_vision_thresholds(self) -> tuple[float, float]:
        """Return ``(warn_at, critical_at)`` for the vision source.

        Falls back to the human thresholds when the vision-specific values are
        unset, so there is exactly one place to change a confidence band.
        """
        warn = (self.human_warn_at if self.vision_warn_at is None
                else self.vision_warn_at)
        crit = (self.human_critical_at if self.vision_critical_at is None
                else self.vision_critical_at)
        return float(warn), float(crit)


@dataclass
class ReplayConfig:
    """C14b — where recorded runs live and whether replay is offered.

    ``recordings_dir`` is ``None`` by default, exactly like
    :attr:`HazardConfig.event_log_path`: replay is a *reporting* feature, so it
    stays off until a deployment points it at a real directory. With it unset,
    the dashboard still shows a replay panel — it simply reports that no
    recordings are configured, rather than pretending the feature is broken.
    """

    enabled: bool = True
    #: C15: record automatically while the web runtime runs. Because it only
    #: takes effect when ``recordings_dir`` is set, the shipped default
    #: (``recordings_dir: null``) records nothing — a safe default for a
    #: reporting feature that must not silently fill a disk.
    auto_record: bool = True
    recordings_dir: Optional[str] = None

    def resolved_dir(self, config_dir: Optional[str] = None) -> Optional[str]:
        """Absolute recordings directory, or ``None`` when unconfigured.

        A relative path is resolved against the config directory so a config
        can be portable between the repo and a deployed Pi.
        """
        if not self.recordings_dir:
            return None
        path = os.path.expanduser(str(self.recordings_dir))
        if os.path.isabs(path):
            return path
        base = config_dir or os.getcwd()
        return os.path.abspath(os.path.join(base, path))


@dataclass
class AppConfig:
    """Aggregated, validated application configuration."""

    serial: SerialConfig
    safety: SafetyConfig
    robot: RobotConfig
    warehouse: WarehouseConfig
    config_dir: str
    hazard: HazardConfig = field(default_factory=HazardConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)


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
    hazard_data = _load_yaml(cfg_dir / "hazard.yaml")
    serial = _build(SerialConfig, serial_data.get("serial", {}), "serial")
    safety = _build(SafetyConfig, safety_data.get("safety", {}), "safety")
    # `avoidance` is a nested block, so _build() (which only handles flat
    # scalar fields) cannot construct it — build it explicitly.
    safety_blob = safety_data.get("safety", {}) or {}
    safety.avoidance = _build(
        AvoidanceConfig, safety_blob.get("avoidance", {}) or {}, "safety.avoidance"
    )

    robot_blob = robot_data.get("robot", robot_data) or {}
    # C13: `config/robot.yaml` places `camera:` as a *sibling* of `robot:`, not
    # inside it, so reading only `robot_blob["camera"]` silently ignored every
    # camera setting in the shipped config and always fell back to the
    # dataclass defaults. Both layouts are now accepted; the nested one wins if
    # a deployment provides both.
    camera_blob = (robot_blob.get("camera") or robot_data.get("camera") or {})
    robot = RobotConfig(
        name=str(robot_blob.get("name", "amr-robot")),
        wheel_track_m=robot_blob.get("wheel_track_m"),
        wheel_diameter_m=robot_blob.get("wheel_diameter_m"),
        motors=_build(MotorConfig, robot_blob.get("motors", {}), "robot.motors"),
        ultrasonic=_build_ultrasonic(robot_blob.get("ultrasonic")),
        camera=_build(CameraConfig, camera_blob, "robot.camera"),
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

    hazard_blob = hazard_data.get("hazard", hazard_data) or {}
    hazard = _build(HazardConfig, hazard_blob, "hazard")

    # C14b: replay is optional and off by default (no directory configured).
    replay_data = _load_yaml(cfg_dir / "replay.yaml")
    replay_blob = replay_data.get("replay", replay_data) or {}
    replay = _build(ReplayConfig, replay_blob, "replay")

    # ---- validation (fail fast on nonsense) ----
    _validate_serial(serial)
    _validate_safety(safety)
    _validate_motors(robot.motors)
    _validate_warehouse(warehouse)
    _validate_hazard(hazard)

    return AppConfig(
        serial=serial, safety=safety, robot=robot,
        warehouse=warehouse, config_dir=str(cfg_dir), hazard=hazard,
        replay=replay,
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


def _validate_hazard(c: HazardConfig) -> None:
    """Reject hazard settings that would make the layer unsafe or meaningless."""
    if c.max_events < 1:
        raise ConfigError("hazard.max_events must be >= 1")
    if not (0.0 < c.slow_speed_scale <= 1.0):
        raise ConfigError("hazard.slow_speed_scale must be in (0, 1]")
    if c.gas_warn_at < 0:
        raise ConfigError("hazard.gas_warn_at must be >= 0")
    if c.gas_critical_at and c.gas_critical_at < c.gas_warn_at:
        raise ConfigError(
            "hazard.gas_critical_at must be 0 (disabled) or >= gas_warn_at"
        )
    for name in ("human",):
        warn = getattr(c, f"{name}_warn_at")
        crit = getattr(c, f"{name}_critical_at")
        if not (0.0 <= warn <= 1.0):
            raise ConfigError(f"hazard.{name}_warn_at must be within [0, 1]")
        if not (0.0 <= crit <= 1.0):
            raise ConfigError(f"hazard.{name}_critical_at must be within [0, 1]")

    # ---- vision (C5) --------------------------------------------------- #
    for key in ("vision_warn_at", "vision_critical_at"):
        val = getattr(c, key)
        if val is not None and not (0.0 <= val <= 1.0):
            raise ConfigError(f"hazard.{key} must be within [0, 1] or null")
    v_warn, v_crit = c.resolved_vision_thresholds()
    if v_crit < v_warn:
        raise ConfigError(
            "hazard.vision_critical_at must be >= vision_warn_at"
        )
    if c.vision_classes is not None:
        if not isinstance(c.vision_classes, (list, tuple)):
            raise ConfigError("hazard.vision_classes must be a list or null")
        # Import lazily: config loading must not depend on the hazard package.
        from amr.hazard.types import VISION_CLASS_TO_KIND

        known = {k.upper() for k in VISION_CLASS_TO_KIND}
        for label in c.vision_classes:
            if not isinstance(label, str):
                raise ConfigError("hazard.vision_classes entries must be strings")
            if label.strip().upper() not in known:
                raise ConfigError(
                    f"hazard.vision_classes: unknown vision class {label!r}; "
                    f"supported: {sorted(known)}"
                )
    if not str(c.vision_source).strip():
        raise ConfigError("hazard.vision_source must be a non-empty name")


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
