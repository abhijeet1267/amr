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
