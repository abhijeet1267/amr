"""Tests for the structured, rotating logging layer.

Covers :func:`amr.logging.get_logger` (naming rules), :func:`amr.logging.setup_logging`
(return value, file/console handlers, idempotent re-setup, custom level, real
rotation) and :func:`amr.logging.logger.log_event` (tag upper-casing, level).

Uses ``tmp_path`` for log files so the suite never writes into the repo.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from amr.logging import get_logger, setup_logging
from amr.logging.logger import log_event


# --------------------------------------------------------------------------- #
# get_logger naming
# --------------------------------------------------------------------------- #
def test_get_logger_none_returns_root():
    assert get_logger().name == "amr"


def test_get_logger_plain_child_is_prefixed():
    assert get_logger("serial").name == "amr.serial"


def test_get_logger_already_prefixed_is_kept():
    assert get_logger("amr.web").name == "amr.web"


def test_get_logger_root_name():
    assert get_logger("amr").name == "amr"


# --------------------------------------------------------------------------- #
# setup_logging
# --------------------------------------------------------------------------- #
def test_setup_logging_returns_root_with_default_level(tmp_path):
    lg = setup_logging(log_dir=str(tmp_path), console=False)
    assert lg.name == "amr"
    assert lg.level == logging.INFO
    assert lg.propagate is False


def test_setup_logging_creates_file_handler(tmp_path):
    lg = setup_logging(log_dir=str(tmp_path), console=False)
    file_handlers = [h for h in lg.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename.endswith("amr.log")


def test_setup_logging_console_only_when_no_dir(tmp_path):
    lg = setup_logging(console=True)  # log_dir=None
    assert any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
               for h in lg.handlers)
    assert not any(isinstance(h, RotatingFileHandler) for h in lg.handlers)


def test_setup_logging_idempotent(tmp_path):
    d = str(tmp_path)
    lg1 = setup_logging(log_dir=d, console=False)
    setup_logging(log_dir=d, console=False)
    file_handlers = [h for h in lg1.handlers if isinstance(h, RotatingFileHandler)]
    # Re-running must NOT stack a second file handler.
    assert len(file_handlers) == 1


def test_setup_logging_custom_level(tmp_path):
    lg = setup_logging(log_dir=str(tmp_path), level=logging.DEBUG, console=False)
    assert lg.level == logging.DEBUG


def test_setup_logging_rotates(tmp_path):
    d = str(tmp_path)
    lg = setup_logging(log_dir=d, console=False, max_bytes=40, backup_count=3)
    for i in range(20):
        lg.info("line %d %s", i, "y" * 30)
    for h in lg.handlers:
        h.flush()
    names = {p.name for p in (tmp_path / "").glob("*") }
    assert "amr.log" in names
    assert "amr.log.1" in names  # a backup was produced by rotation


# --------------------------------------------------------------------------- #
# log_event
# --------------------------------------------------------------------------- #
class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_log_event_uppercases_tag_and_uses_info():
    lg = get_logger("events")
    cap = _Capture()
    lg.addHandler(cap)
    try:
        log_event(lg, "move", "L=1 R=2")
    finally:
        lg.removeHandler(cap)
    assert len(cap.records) == 1
    assert cap.records[0].levelno == logging.INFO
    assert cap.records[0].getMessage() == "MOVE L=1 R=2"


def test_log_event_none_logger_falls_back_to_events():
    lg = get_logger("events")
    cap = _Capture()
    lg.addHandler(cap)
    try:
        log_event(None, "safety", "stop")
    finally:
        lg.removeHandler(cap)
    assert len(cap.records) == 1
    assert cap.records[0].getMessage() == "SAFETY stop"
