"""Host connectivity inspection (Wi-Fi / Bluetooth) — read-only, stdlib only.

Why this exists
---------------
An AMR that loses its radio stops being supervisable, so "is the link up?" is a
legitimate operator question. It is answered here **by inspecting the host the
process is actually running on** — not by guessing, and not by pretending.

The honesty rule this module obeys
----------------------------------
Every field is measured, and anything that cannot be measured is reported as
``UNAVAILABLE`` with a ``note`` saying why. There is no optimistic default: a
machine with no Bluetooth hardware must never report a Bluetooth adapter, and
a machine where the probe itself failed must say "unknown", not "off". A
connectivity card that invents a result is worse than no card, because an
operator reads it as evidence.

It is also strictly read-only. Nothing here associates, scans, connects, or
changes any link state: scanning and pairing are privileged, disruptive, and
would be a new actuation path in a project whose whole point is that
``/command`` is the only one.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

#: Where Linux exposes per-interface link state. Read-only, and absent on
#: macOS/Windows, which is exactly why every probe below degrades rather than
#: raising.
_SYS_CLASS_NET = "/sys/class/net"

#: Loopback is always "up" and says nothing about the radio, so it is excluded
#: from the wireless findings and never counted as a usable link.
_LOOPBACK = ("lo", "lo0", "Loopback Pseudo-Interface")

#: Interface-name prefixes that indicate a wireless NIC on Linux. A prefix
#: match rather than an exact list because vendors vary (wlan, wl, wifi, ath).
_WIRELESS_PREFIXES = ("wl", "wlan", "wifi", "ath", "ra")

#: Prefixes that identify a Bluetooth interface on Linux.
_BLUETOOTH_PREFIXES = ("bnep", "hci")


@dataclass(frozen=True)
class Interface:
    """One network interface as the host actually reports it.

    ``up`` is the kernel's own view (IFF_UP / operstate), never an assumption:
    a card can be present and down at the same time, and those are different
    operator problems.
    """

    name: str
    kind: str                 # "wireless" | "wired" | "loopback" | "bluetooth"
    up: bool
    address: Optional[str] = None
    operstate: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "up": self.up,
            "address": self.address,
            "operstate": self.operstate,
            "note": self.note,
        }


def _is_wireless(name: str) -> bool:
    return name.lower().startswith(_WIRELESS_PREFIXES)


def _is_bluetooth(name: str) -> bool:
    return name.lower().startswith(_BLUETOOTH_PREFIXES)


def _read(path: str) -> Optional[str]:
    """Read one small sysfs file, or ``None`` if it is not there.

    Never raises: every caller treats "missing" as a data point rather than an
    error, because a missing file is the normal case on a desktop machine.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except (OSError, ValueError):
        return None


def _sysfs_interfaces() -> List[Interface]:
    """Enumerate interfaces via ``/sys/class/net`` (Linux). Empty elsewhere."""
    out: List[Interface] = []
    try:
        names = sorted(os.listdir(_SYS_CLASS_NET))
    except OSError:
        return out
    for name in names:
        base = os.path.join(_SYS_CLASS_NET, name)
        oper = _read(os.path.join(base, "operstate"))
        # The kernel's own up/down flag, read as hex; 0x1 is IFF_UP. operstate
        # is the fallback because a few drivers leave flags unreadable.
        flags = _read(os.path.join(base, "flags"))
        up = (oper == "up")
        if flags is not None:
            try:
                up = bool(int(flags, 16) & 0x1)
            except ValueError:
                pass
        if name in _LOOPBACK:
            kind = "loopback"
        elif _is_bluetooth(name):
            kind = "bluetooth"
        elif _is_wireless(name):
            kind = "wireless"
        else:
            kind = "wired"
        out.append(Interface(
            name=name, kind=kind, up=up,
            address=_read(os.path.join(base, "address")),
            operstate=oper,
        ))
    return out


def _loopback_only() -> List[Interface]:
    """The portable floor: a name and a flag, and nothing invented.

    ``socket`` is the only interface that always works, so this is what a
    non-Linux host reports rather than an empty list pretending to be a scan.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No packet is sent. This asks the OS which local address it would
            # use to leave the host -- a deliberate no-op probe.
            s.connect(("192.0.2.1", 9))     # TEST-NET-1: reserved, unroutable
            local = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return [Interface(name="unknown", kind="wired", up=False,
                          note="could not determine local addressing")]
    return [Interface(
        name="host",
        kind="loopback" if local.startswith("127.") else "wired",
        up=bool(local) and not local.startswith("127."),
        address=local,
        note="reported by socket; interface detail needs /sys/class/net",
    )]


def interfaces() -> List[Interface]:
    """Every interface this host will admit to, best-effort and honest.

    Prefers sysfs (Linux, where the Pi runs) and falls back to the portable
    socket probe. Never returns a fabricated wireless or Bluetooth interface.
    """
    found = _sysfs_interfaces()
    return found if found else _loopback_only()


def _by_kind(ifs: List[Interface], kind: str) -> List[Interface]:
    return [i for i in ifs if i.kind == kind]


def wifi() -> Dict[str, Any]:
    """Wi-Fi status for this host.

    Distinguishes three outcomes that look identical if collapsed to a boolean:
    hardware that is connected, hardware that is present but not connected, and
    no wireless hardware we can find at all.
    """
    ifs = interfaces()
    wireless = _by_kind(ifs, "wireless")
    if not wireless:
        seen = ", ".join(i.name for i in ifs) or "none"
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "connected": False,
            "interface": None,
            "interfaces": [i.to_dict() for i in ifs],
            # None, never a made-up SSID: reading one needs a privileged
            # ioctl, and a plausible-looking name would be a fabrication.
            "ssid": None,
            "note": f"no wireless interface found on this host (saw: {seen})",
        }
    up = [i for i in wireless if i.up]
    return {
        "status": "CONNECTED" if up else "DISCONNECTED",
        "available": True,
        "connected": bool(up),
        "interface": (up[0] if up else wireless[0]).to_dict(),
        "interfaces": [i.to_dict() for i in wireless],
        "ssid": None,
        "note": None if up else "wireless hardware present but the link is down",
    }


def bluetooth() -> Dict[str, Any]:
    """Bluetooth status for this host.

    Reports presence only. It does not scan, pair, or enumerate devices:
    discovery is privileged and disruptive, and doing it from a read-only
    endpoint would make the web layer an actuator.
    """
    ifs = interfaces()
    adapters = _by_kind(ifs, "bluetooth")
    if not adapters:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "adapters": [],
            # None, not 0: "we ran no scan" is not the same claim as "we
            # scanned and found nothing".
            "paired_devices": None,
            "note": ("no Bluetooth adapter reported by this host; devices "
                     "were not enumerated, which would need a privileged scan"),
        }
    return {
        "status": "READY" if any(i.up for i in adapters) else "DISABLED",
        "available": True,
        "adapters": [i.to_dict() for i in adapters],
        "paired_devices": None,
        "note": None,
    }


def snapshot() -> Dict[str, Any]:
    """The whole connectivity picture, for ``GET /connectivity``.

    Read-only and cheap enough for a request handler: no privileged call, no
    network traffic, nothing shelled out.
    """
    ifs = interfaces()
    return {
        "version": 1,
        "read_only": True,
        "interfaces": [i.to_dict() for i in ifs],
        "counts": {
            "total": len(ifs),
            "wireless": len(_by_kind(ifs, "wireless")),
            "wired": len(_by_kind(ifs, "wired")),
            "bluetooth": len(_by_kind(ifs, "bluetooth")),
        },
        "wifi": wifi(),
        "bluetooth": bluetooth(),
        "note": (
            "Measured from this host. Wireless link detail (SSID, signal) and "
            "Bluetooth device discovery need privileged calls that this "
            "read-only endpoint deliberately does not make."
        ),
    }