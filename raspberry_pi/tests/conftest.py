"""Pytest configuration and shared fixtures.

Ensures the ``amr`` package is importable no matter where pytest is launched
from, and exposes the repo root / config dir to tests.
"""

from __future__ import annotations

import pathlib
import sys

# .../IDP/raspberry_pi/tests/conftest.py
_RASPBERRY_PI = pathlib.Path(__file__).resolve().parents[1]
_REPO_ROOT = _RASPBERRY_PI.parent

if str(_RASPBERRY_PI) not in sys.path:
    sys.path.insert(0, str(_RASPBERRY_PI))

import pytest  # noqa: E402


@pytest.fixture
def repo_root() -> pathlib.Path:
    return _REPO_ROOT


@pytest.fixture
def config_dir() -> pathlib.Path:
    return _REPO_ROOT / "config"
