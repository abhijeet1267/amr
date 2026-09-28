"""Structured logging with rotation.

Provides:

* :func:`setup_logging` — configure the ``amr.*`` logger namespace once at
  startup. Writes to a rotating file (bounded size) and optionally the console.
* :func:`get_logger` — cheap accessor that is safe to call before setup.
* :func:`log_event` — emit compact, grep-friendly event lines such as
  ``COMMAND MOVE L=150 R=150``, ``SENSOR F=82 L=70 R=90 B=120`` or
  ``SAFETY STOP`` (see ``AI_CONTEXT/ARCHITECTURE.md``).

Log files are rotated so the system never grows them without bound.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional, Union

_ROOT_NAME = "amr"
_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%H:%M:%S"

# Default bounded log size (bytes) and number of backups.
_DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_DEFAULT_BACKUP_COUNT = 3


def default_log_dir() -> str:
    """Where log files go when no directory is given: ``$AMR_LOG_DIR`` or ``./logs``."""
    return os.environ.get("AMR_LOG_DIR", "logs")


#: Backwards-compatible private alias.
_default_log_dir = default_log_dir


def setup_logging(
    log_dir: Optional[Union[str, bool]] = None,
    level: int = logging.INFO,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
    console: bool = True,
    filename: str = "amr.log",
) -> logging.Logger:
    """Configure the ``amr`` logger namespace.

    Safe to call more than once: existing handlers are replaced so re-runs
    (e.g. tests, restarts) do not stack duplicate handlers.

    ``log_dir=None`` means "the default location" (:func:`default_log_dir`, i.e.
    ``$AMR_LOG_DIR`` or ``./logs``), *not* "no file". Passing ``log_dir=False``
    is how a caller explicitly asks for no file handler at all.

    That distinction is load-bearing. The alternative — treating ``None`` as
    "console only" — lets ``setup_logging(console=False)`` install **zero**
    handlers, and a logger with no handlers silently discards every record. That
    is what the entry point used to do, so a long mission could fail with nothing
    in the log to explain it. A robot that cannot be diagnosed is not a working
    robot, so the default now writes the file and ``main.py`` relies on that.
    """
    if log_dir is None:
        log_dir = default_log_dir()
    if log_dir is False:            # explicit opt-out (tests, embedding)
        log_dir = None
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(level)
    root.propagate = False

    # Remove any pre-existing handlers (idempotent re-setup).
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    fmt = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DATE_FORMAT)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, filename),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    return root


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child logger under ``amr``. Safe before :func:`setup_logging`."""
    if not name:
        return logging.getLogger(_ROOT_NAME)
    if name == _ROOT_NAME or name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def log_event(logger: Optional[logging.Logger], tag: str, message: str) -> None:
    """Emit a compact, single-token-tagged event line (``TAG message``).

    This gives the human-readable log format requested in the design, e.g.
    ``21:04:10 COMMAND MOVE L=150 R=150``.
    """
    (logger or get_logger("events")).info("%s %s", tag.upper(), message)
