"""Tests for configuration loading and validation."""

from __future__ import annotations

import pytest

from amr.utils.config import ConfigError, load_config


def test_load_repo_config(config_dir):
    cfg = load_config(str(config_dir))
    assert cfg.serial.port == "/dev/ttyACM0"
    assert cfg.serial.baudrate == 9600
    assert cfg.safety.watchdog_timeout_ms == 1000
    assert cfg.safety.front_stop_distance_cm == 20
    assert cfg.robot.motors.max_speed == 255
    # Geometry is unknown until measured.
    assert cfg.robot.wheel_track_m is None
    # Safety values are explicitly unverified by default.
    assert cfg.safety.status == "NOT_VERIFIED"


def test_ultrasonic_pins_are_placeholders(config_dir):
    cfg = load_config(str(config_dir))
    # We must NOT have invented real pins.
    assert cfg.robot.ultrasonic.front.trig == "TODO_VERIFY"
    assert cfg.robot.ultrasonic.rear.echo == "TODO_VERIFY"


def test_defaults_when_no_files(tmp_path):
    # An empty config dir should yield full defaults, not crash.
    cfg = load_config(str(tmp_path))
    assert cfg.serial.port == "/dev/ttyACM0"
    assert cfg.serial.baudrate == 9600
    assert cfg.safety.watchdog_timeout_ms == 1000
    assert cfg.robot.motors.max_speed == 255


def test_missing_config_dir_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "does_not_exist"))


def test_malformed_yaml_raises(tmp_path):
    (tmp_path / "serial.yaml").write_text(":\n  - bad\n yaml [", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(tmp_path))


def test_bad_baudrate_rejected(tmp_path):
    (tmp_path / "serial.yaml").write_text(
        "serial:\n  baudrate: 1234\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(str(tmp_path))


def test_bad_watchdog_rejected(tmp_path):
    (tmp_path / "safety.yaml").write_text(
        "safety:\n  watchdog_timeout_ms: 0\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(str(tmp_path))


def test_bad_motor_max_rejected(tmp_path):
    (tmp_path / "robot.yaml").write_text(
        "motors:\n  max_speed: 999\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(str(tmp_path))


def test_custom_values_override(tmp_path):
    (tmp_path / "serial.yaml").write_text(
        'serial:\n  port: "/dev/ttyUSB0"\n  baudrate: 57600\n', encoding="utf-8"
    )
    (tmp_path / "safety.yaml").write_text(
        "safety:\n  front_stop_distance_cm: 30\n  status: VERIFIED\n", encoding="utf-8"
    )
    cfg = load_config(str(tmp_path))
    assert cfg.serial.port == "/dev/ttyUSB0"
    assert cfg.serial.baudrate == 57600
    assert cfg.safety.front_stop_distance_cm == 30
    assert cfg.safety.status == "VERIFIED"
    # Untouched values keep defaults.
    assert cfg.safety.watchdog_timeout_ms == 1000


# --- hazard layer (config/hazard.yaml) ------------------------------------- #
def test_hazard_defaults_when_no_file(tmp_path):
    cfg = load_config(str(tmp_path))
    # The layer must be off and unverified until an operator opts in.
    assert cfg.hazard.enabled is False
    assert cfg.hazard.status == "NOT_VERIFIED"
    assert cfg.hazard.zones == []
    assert cfg.hazard.emergency_kinds is None      # None -> documented default
    assert cfg.hazard.event_log_path is None


def test_repo_hazard_config_loads(config_dir):
    cfg = load_config(str(config_dir))
    assert cfg.hazard.enabled is False
    assert cfg.hazard.status == "NOT_VERIFIED"
    assert cfg.hazard.slow_speed_scale == 0.5
    assert cfg.hazard.max_events == 256
    assert cfg.hazard.gas_warn_at == 300
    assert cfg.hazard.gas_critical_at == 1000
    assert cfg.hazard.gas_unit == "ppm"
    # The placeholder zone is present and must be flagged as unverified.
    assert [z["name"] for z in cfg.hazard.zones] == ["charging_bay"]


def test_hazard_custom_values_override(tmp_path):
    (tmp_path / "hazard.yaml").write_text(
        "hazard:\n"
        "  enabled: true\n"
        "  status: VERIFIED\n"
        "  slow_speed_scale: 0.25\n"
        "  max_events: 8\n"
        "  emergency_kinds: []\n"
        "  zones:\n"
        "    - name: bay\n"
        "      x_min: 1\n"
        "      x_max: 2\n"
        "      y_min: 0\n"
        "      y_max: 1\n",
        encoding="utf-8",
    )
    cfg = load_config(str(tmp_path))
    assert cfg.hazard.enabled is True
    assert cfg.hazard.status == "VERIFIED"
    assert cfg.hazard.slow_speed_scale == 0.25
    assert cfg.hazard.max_events == 8
    assert cfg.hazard.emergency_kinds == []        # explicit "disable latching"
    assert cfg.hazard.zones[0]["name"] == "bay"
    # Untouched hazard values keep their defaults.
    assert cfg.hazard.gas_warn_at == 300


@pytest.mark.parametrize(
    "body",
    [
        "hazard:\n  slow_speed_scale: 0\n",       # must be in (0, 1]
        "hazard:\n  slow_speed_scale: 1.5\n",     # must be in (0, 1]

        "hazard:\n  max_events: 0\n",             # must be >= 1
        "hazard:\n  gas_warn_at: -1\n",           # must be >= 0
        "hazard:\n  gas_critical_at: 10\n  gas_warn_at: 300\n",  # critical < warn
        "hazard:\n  human_warn_at: 2.0\n",        # confidence out of range
    ],
)
def test_bad_hazard_settings_rejected(tmp_path, body):
    (tmp_path / "hazard.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(tmp_path))


# --------------------------------------------------------------------------- #
# C13 — camera detection identity
# --------------------------------------------------------------------------- #
def test_camera_id_defaults_to_undeclared():
    from amr.utils.config import CameraConfig
    assert CameraConfig().camera_id is None


def test_camera_id_is_read_from_config(tmp_path, repo_root):
    import shutil
    from amr.utils.config import load_config
    src = repo_root / "config"
    dst = tmp_path / "config"
    shutil.copytree(src, dst)
    (dst / "robot.yaml").write_text(
        (dst / "robot.yaml").read_text()
        + '\n  camera_id: "camera_front"   # identity detections are stamped with\n',
        encoding="utf-8")
    assert load_config(str(dst)).robot.camera.camera_id == "camera_front"


def test_camera_config_still_loads_without_camera_id(config_dir):
    from amr.utils.config import load_config
    cfg = load_config(str(config_dir))
    assert cfg.robot.camera.camera_id is None
    assert cfg.robot.camera.enabled is True


def test_shipped_camera_settings_are_actually_applied(config_dir):
    """C13 regression guard: `camera:` is a sibling of `robot:` in robot.yaml.

    Reading only ``robot.camera`` silently ignored the shipped config and always
    used dataclass defaults, so this asserts the real file is honoured.
    """
    from amr.utils.config import load_config
    cfg = load_config(str(config_dir))
    assert cfg.robot.camera.device == "pi"
    assert cfg.robot.camera.resolution == "1280x720"
