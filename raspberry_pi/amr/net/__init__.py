"""Host connectivity inspection (Wi-Fi / Bluetooth) — read-only, stdlib only.

Public surface is :func:`snapshot`, plus :func:`wifi` and :func:`bluetooth` for
callers that want one radio. Nothing here mutates link state.
"""

from __future__ import annotations

from .connectivity import (
    Interface,
    bluetooth,
    interfaces,
    snapshot,
    wifi,
)

__all__ = [
    "Interface",
    "bluetooth",
    "interfaces",
    "snapshot",
    "wifi",
]
