"""Tests for the structured, rotating logging layer.

Covers :func:`amr.logging.get_logger` (naming rules), :func:`amr.logging.setup_logging`
(return value, file/console handlers, idempotent re-setup, custom level, real
rotation) and :func:`amr.logging.logger.log_event` (tag upper-casing, level).

Uses ``tmp_path`` for log files so the suite never writes into the repo.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from amr.logging import default_log_dir, get_logger, setup_logging
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


def test_setup_logging_console_and_file_when_no_dir_given(tmp_path, monkeypatch):
    """``log_dir=None`` now means the *default* directory, not "no file".

    This assertion changed on purpose. It used to require that a None
    ``log_dir`` install no file handler, which is precisely the behaviour that
    let ``main.py`` end up with a logger that discarded everything. ``None`` now
    resolves to :func:`default_log_dir`, and opting out is explicit
    (``log_dir=False``). See ``test_console_false_still_installs_a_handler``.
    """
    monkeypatch.setenv("AMR_LOG_DIR", str(tmp_path / "logs"))
    lg = setup_logging(console=True)             # log_dir=None -> default dir
    assert any(isinstance(h, logging.StreamHandler)
               and not isinstance(h, RotatingFileHandler)
               for h in lg.handlers)
    assert any(isinstance(h, RotatingFileHandler) for h in lg.handlers), (
        "console=True with the default dir should get BOTH, so a robot that is "
        "run headless still leaves a file to read")


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


# --------------------------------------------------------------------------- #
# The bug: setup_logging(console=False) used to install *zero* handlers
#
# main.py called exactly that, so the ``if log_dir:`` branch never ran and the
# console branch was off — leaving a logger that silently discards every record.
# On the Pi that meant a mission could fail with an empty log. The tests below
# are written to fail against that behaviour.
# --------------------------------------------------------------------------- #
def test_console_false_still_installs_a_handler(tmp_path, monkeypatch):
    """The production call shape must not produce a black hole."""
    monkeypatch.setenv("AMR_LOG_DIR", str(tmp_path / "logs"))
    lg = setup_logging(console=False)          # exactly what main.py does
    assert lg.handlers, (
        "a logger with no handlers discards every record — a mission that "
        "fails with an empty log cannot be diagnosed")


def test_default_dir_actually_receives_the_records(tmp_path, monkeypatch):
    """Not just 'a handler exists': the log line must land on disk."""
    monkeypatch.setenv("AMR_LOG_DIR", str(tmp_path / "logs"))
    lg = setup_logging(console=False)
    get_logger("selftest").warning("mission aborted: E_STUCK")
    for h in lg.handlers:
        h.flush()
    log_file = tmp_path / "logs" / "amr.log"
    assert log_file.exists(), "setup_logging advertised a file but wrote none"
    assert "E_STUCK" in log_file.read_text(encoding="utf-8")


def test_default_log_dir_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("AMR_LOG_DIR", str(tmp_path / "elsewhere"))
    assert default_log_dir() == str(tmp_path / "elsewhere")
    monkeypatch.delenv("AMR_LOG_DIR")
    assert default_log_dir() == "logs"


def test_log_dir_false_is_the_explicit_opt_out(tmp_path):
    """``log_dir=False`` means no file; ``None`` no longer does."""
    lg = setup_logging(log_dir=False, console=False)
    assert not any(isinstance(h, RotatingFileHandler) for h in lg.handlers)


def test_main_entry_point_configures_a_usable_logger(tmp_path, monkeypatch):
    """Run the real argparse path from main.py, not a hand-made call."""
    monkeypatch.setenv("AMR_LOG_DIR", str(tmp_path / "logs"))
    from amr import main as main_mod

    try:
        main_mod.main(["--help"])
    except SystemExit:
        pass
    assert get_logger("amr").handlers, "main.py left the logger with no handlers"


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
