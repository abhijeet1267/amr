"""Tests for :mod:`amr.net.connectivity` (Wi-Fi / Bluetooth inspection).

Hardware-free by construction: the sysfs path is redirected into a temp
directory, so every result is produced by a fixture rather than by whatever
machine happens to run the suite. That matters because the *interesting* cases
are exactly the ones a developer machine will not produce naturally — a Pi with
a wireless interface, a Pi with a dead one, a desktop with neither.

The property under test throughout is that the module reports what it measured
and says UNAVAILABLE when it measured nothing. A connectivity card that invents
a result is worse than no card, because an operator reads it as evidence.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from amr.net import connectivity


def _fake_sysfs(tmp_path, interfaces):
    """Build a /sys/class/net tree and return the path to it.

    ``interfaces`` maps a name to a dict with optional ``flags`` (hex string,
    as the kernel writes it), ``operstate`` and ``address``.
    """
    root = tmp_path / "class" / "net"
    for name, spec in interfaces.items():
        d = root / name
        d.mkdir(parents=True)
        if "flags" in spec:
            (d / "flags").write_text(spec["flags"], encoding="utf-8")
        if "operstate" in spec:
            (d / "operstate").write_text(spec["operstate"], encoding="utf-8")
        if "address" in spec:
            (d / "address").write_text(spec["address"], encoding="utf-8")
    return root


@pytest.fixture
def fake_net(tmp_path, monkeypatch):
    """Redirect the module's sysfs root at a temp tree."""

    def _install(interfaces):
        root = _fake_sysfs(tmp_path, interfaces)
        monkeypatch.setattr(connectivity, "_SYS_CLASS_NET", str(root))
        return root

    return _install


# --------------------------------------------------------------------------- #
# Interface enumeration
# --------------------------------------------------------------------------- #
def test_reports_a_wireless_interface_that_is_up(fake_net):
    fake_net({"wlan0": {"flags": "0x1003", "operstate": "up"}})
    w = connectivity.wifi()
    assert w["status"] == "CONNECTED"
    assert w["connected"] is True
    assert w["interface"]["name"] == "wlan0"
    assert w["interface"]["kind"] == "wireless"


def test_wireless_present_but_down_is_not_reported_as_connected(fake_net):
    """Hardware present and link down are different operator problems."""
    fake_net({"wlan0": {"flags": "0x1002", "operstate": "down"}})
    w = connectivity.wifi()
    assert w["status"] == "DISCONNECTED"
    assert w["available"] is True
    assert w["connected"] is False
    assert "down" in w["note"].lower()


def test_loopback_is_never_counted_as_wireless(fake_net):
    """``lo`` is always up and says nothing about a radio."""
    fake_net({"lo": {"flags": "0x1003", "operstate": "up"},
              "wlan0": {"flags": "0x1000", "operstate": "down"}})
    w = connectivity.wifi()
    assert w["connected"] is False, "loopback must not read as a Wi-Fi link"
    # interfaces() yields Interface objects, not the JSON dicts.
    kinds = {i.name: i.kind for i in connectivity.interfaces()}
    assert kinds["lo"] == "loopback"


def test_wired_and_wireless_are_told_apart(fake_net):
    fake_net({"eth0": {"flags": "0x1003", "operstate": "up"},
              "wlan0": {"flags": "0x1003", "operstate": "up"}})
    kinds = {i.name: i.kind for i in connectivity.interfaces()}
    assert kinds == {"eth0": "wired", "wlan0": "wireless"}


def test_unreadable_flags_fall_back_to_operstate(fake_net):
    """A driver that writes garbage to ``flags`` must not crash the probe."""
    fake_net({"wlan0": {"flags": "not-hex", "operstate": "up"}})
    w = connectivity.wifi()
    assert w["status"] == "CONNECTED", "operstate should still decide the link"


# --------------------------------------------------------------------------- #
# The honesty rules
# --------------------------------------------------------------------------- #
def test_no_wireless_hardware_reports_unavailable_not_off(fake_net):
    """No wireless NIC is a *different* answer from a disconnected one."""
    fake_net({"eth0": {"flags": "0x1003", "operstate": "up"}})
    w = connectivity.wifi()
    assert w["status"] == "UNAVAILABLE"
    assert w["available"] is False
    assert w["connected"] is False
    assert w["note"], "an unavailable radio must say why"


def test_ssid_is_never_invented(fake_net):
    """Reading an SSID needs a privileged ioctl, so it stays ``None``.

    A plausible-looking network name would be a fabrication the operator has no
    way to distinguish from a real reading.
    """
    fake_net({"wlan0": {"flags": "0x1003", "operstate": "up"}})
    assert connectivity.wifi()["ssid"] is None


def test_bluetooth_absent_is_unavailable(fake_net):
    fake_net({"eth0": {"flags": "0x1003", "operstate": "up"}})
    b = connectivity.bluetooth()
    assert b["status"] == "UNAVAILABLE"
    assert b["available"] is False
    assert b["note"]


def test_bluetooth_present_is_detected(fake_net):
    fake_net({"hci0": {"flags": "0x1003", "operstate": "up"}})
    b = connectivity.bluetooth()
    assert b["available"] is True
    assert b["status"] == "READY"
    assert b["adapters"][0]["kind"] == "bluetooth"


def test_paired_devices_is_null_never_zero(fake_net):
    """No scan is run, so a count would be a claim about work never done.

    ``0`` says "we looked and there were none". ``None`` says "we did not
    look". Only the second is true here.
    """
    fake_net({"hci0": {"flags": "0x1003", "operstate": "up"}})
    assert connectivity.bluetooth()["paired_devices"] is None
    assert connectivity.snapshot()["bluetooth"]["paired_devices"] is None


def test_missing_sysfs_degrades_instead_of_raising(monkeypatch):
    """A non-Linux host has no ``/sys/class/net``; that is not an exception."""
    monkeypatch.setattr(connectivity, "_SYS_CLASS_NET", "/nonexistent/net")
    snap = connectivity.snapshot()
    assert snap["version"] == 1
    assert snap["wifi"]["status"] == "UNAVAILABLE"
    assert snap["bluetooth"]["status"] == "UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Read-only guarantees
# --------------------------------------------------------------------------- #
def test_module_never_shells_out():
    """A subprocess would be the easy way to read link state, and the wrong one.

    ``nmcli``/``bluetoothctl`` are external, version-dependent, and in the
    Bluetooth case a *privileged* scan. This module is stdlib-only by
    construction, and this asserts it stays that way.
    """
    source = pathlib.Path(connectivity.__file__).read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "popen", "nmcli", "bluetoothctl"):
        assert forbidden not in source, (
            f"connectivity must not use {forbidden}: it would be a privileged "
            "or external dependency in a read-only probe"
        )


def test_snapshot_is_json_serialisable_and_read_only(fake_net):
    fake_net({"wlan0": {"flags": "0x1003", "operstate": "up"}})
    snap = connectivity.snapshot()
    json.dumps(snap)                     # must not raise
    assert snap["read_only"] is True
    assert snap["counts"]["wireless"] == 1


def test_counts_match_the_listed_interfaces(fake_net):
    """The summary must not drift from the detail it summarises."""
    fake_net({"eth0": {"flags": "0x1003", "operstate": "up"},
              "wlan0": {"flags": "0x1003", "operstate": "up"},
              "hci0": {"flags": "0x1003", "operstate": "up"}})
    snap = connectivity.snapshot()
    assert snap["counts"]["total"] == len(snap["interfaces"]) == 3
    assert snap["counts"]["wireless"] == 1
    assert snap["counts"]["bluetooth"] == 1