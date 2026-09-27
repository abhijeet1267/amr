"""Tests for the application registry (``config/applications.yaml``).

The point of these tests is not coverage, it is *veracity*. The registry is
the thing the hub, the mobile client and the desktop client all trust when
they answer "does this work?", so a wrong entry here propagates into three
products. The most important test in this file is
:func:`test_every_url_is_a_real_route`, which reads the routing table out of
``amr/web/server.py`` and refuses any registry URL that the server does not
actually serve. That is what stops this project's UI and documentation from
drifting into fiction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from amr.apps.registry import (
    CATEGORIES,
    PLATFORMS,
    STATUSES,
    Application,
    ApplicationRegistry,
    RuntimeContext,
    load_applications,
)

SERVER_PY = Path(__file__).resolve().parents[1] / "amr" / "web" / "server.py"
CONFIG_YAML = Path(__file__).resolve().parents[2] / "config" / "applications.yaml"


@pytest.fixture(scope="module")
def registry() -> ApplicationRegistry:
    return load_applications()


# --------------------------------------------------------------------------- #
# The anti-fiction test
# --------------------------------------------------------------------------- #
def _served_routes() -> set:
    """Every path the server routes, scraped from its own dispatch chain.

    Parsing the source rather than importing a list is deliberate: the
    ``if / elif path == ...`` chain in ``do_GET`` IS the truth, and a constant
    list somewhere else would just be a second thing that can go stale.
    """
    source = SERVER_PY.read_text(encoding="utf-8")
    routes = set(re.findall(r'path\s*==\s*"([^"]+)"', source))
    routes |= set(re.findall(r'path\.startswith\("([^"]+)"\)', source))
    return routes


def test_server_source_actually_parsed():
    """Guard the guard: if the scrape finds nothing, the tests below are
    vacuously green — which would be worse than having no test at all."""
    routes = _served_routes()
    assert len(routes) > 10, f"route scrape found only {len(routes)} routes"
    assert "/command-center" in routes


def test_every_url_is_a_real_route(registry):
    """No registry entry may point at a route that does not exist.

    Fragments (``/command-center#map``) are stripped before checking, because
    the hash is interpreted client-side by ``initViews()``/``fromHash()`` — the
    server only ever sees ``/command-center``.
    """
    routes = _served_routes()
    for app in registry.all():
        for target in (app.url, app.api_base):
            if target is None:
                continue
            base = target.split("#", 1)[0]
            assert base in routes, (
                f"{app.id}: {target!r} is not a route served by server.py "
                f"(known: {sorted(routes)})"
            )


def test_api_reference_declares_no_url(registry):
    """/map and /telemetry are JSON endpoints, not pages. A card that linked
    to one would open raw JSON in a tab and read as a broken application."""
    api = registry.by_id("api_reference")
    assert api is not None
    assert api.url is None
    assert api.api_base  # ...but it does point at something real


# --------------------------------------------------------------------------- #
# Structural validity
# --------------------------------------------------------------------------- #
def test_registry_is_not_empty(registry):
    assert len(registry) >= 10


def test_yaml_file_exists_next_to_the_others():
    assert CONFIG_YAML.is_file()


def test_ids_unique(registry):
    ids = [a.id for a in registry.all()]
    assert len(ids) == len(set(ids))


def test_every_category_and_status_is_declared(registry):
    for app in registry.all():
        assert app.category in CATEGORIES, app.id
        assert app.status in STATUSES, app.id


def test_platforms_are_concrete(registry):
    """``mobile``/``desktop`` are not platforms — Android and iOS differ in
    what they allow (background polling, installability), so filtering on a
    vague label would produce a client list that is wrong for one of them."""
    for app in registry.all():
        for platform in app.platforms:
            assert platform in PLATFORMS, f"{app.id}: {platform}"


def test_descriptions_are_written_for_an_operator(registry):
    for app in registry.all():
        assert len(app.description) > 30, f"{app.id} description too thin"
        assert app.name.strip() == app.name


def test_web_pages_have_urls(registry):
    for app in registry.web_pages():
        assert app.url.startswith("/")



# --------------------------------------------------------------------------- #
# Honesty of statuses
# --------------------------------------------------------------------------- #
def test_camera_is_not_available(registry):
    """There is no verified camera hardware in this project. If this test
    fails, somebody marked the camera AVAILABLE without attaching one."""
    cam = registry.by_id("camera_monitor")
    assert cam.status != "AVAILABLE"
    assert cam.requires_camera is True


def test_status_never_upgrades(registry):
    """The load-bearing rule: no runtime observation may raise a status.

    With a camera attached and a live robot, ``camera_monitor`` must still read
    HARDWARE REQUIRED, because the baseline records what has been *verified*,
    and no camera has ever been exercised here.
    """
    ctx = RuntimeContext(mock_mode=False, server_running=True, camera_available=True)
    for app in registry.all():
        resolved = registry.resolve_status(app, ctx)
        base_rank = STATUSES.index(app.status)
        new_rank = STATUSES.index(resolved["status"])
        assert new_rank >= base_rank, (
            f"{app.id}: {app.status} was upgraded to {resolved['status']}"
        )


def test_downgrades_when_server_is_down(registry):
    ctx = RuntimeContext(server_running=False)
    out = registry.resolve_status(registry.by_id("command_center"), ctx)
    assert out["status"] == "OFFLINE"
    assert out["reason"] == "server-unreachable"


def test_mock_mode_is_labelled_not_hidden(registry):
    """Running on the simulator is fine, but it must be *visible*. Reporting
    AVAILABLE while only a mock robot is answering would imply that hardware
    has been exercised."""
    out = registry.resolve_status(
        registry.by_id("command_center"), RuntimeContext(mock_mode=True)
    )
    assert out["status"] == "MOCK"
    assert out["reason"] == "mock-robot"


def test_clients_are_not_claimed_as_finished(registry):
    mobile = registry.by_id("mobile_client")
    desktop = registry.by_id("desktop_client")
    assert mobile.status == "NOT INSTALLED"
    assert desktop.status == "BUILD NOT AVAILABLE"
    # No download links: an installer that does not exist would be a lie in
    # the UI, and the hub renders whatever URL is present.
    assert mobile.url is None and desktop.url is None
    assert mobile.launch_command is None and desktop.launch_command is None


def test_exactly_one_application_can_command_motion(registry):
    """Safety invariants belong in tests, not in prose.

    The Command Center and every one of its views must be read-only; only the
    legacy web control panel may post to ``/command``. If a future card gains
    ``read_only: false`` this test fails — which is exactly the moment the
    conversation should have happened, in front of SafetyManager rather than
    in a UI.
    """
    writable = [a.id for a in registry.all() if not a.read_only]
    assert writable == ["control_panel"], writable



# --------------------------------------------------------------------------- #
# Validation rejects the mistakes that actually happen
# --------------------------------------------------------------------------- #
def _app(**overrides) -> Application:
    base = dict(
        id="x", name="X", description="d" * 40, category="monitoring",
        status="AVAILABLE", platforms=["web"], url="/command-center",
    )
    base.update(overrides)
    return Application(**base)


def test_duplicate_id_rejected():
    with pytest.raises(Exception, match="duplicate"):
        ApplicationRegistry([_app(), _app()])


def test_unknown_status_rejected():
    with pytest.raises(Exception, match="unknown status"):
        ApplicationRegistry([_app(status="SHIP IT")])


def test_unknown_category_rejected():
    with pytest.raises(Exception, match="unknown category"):
        ApplicationRegistry([_app(category="cool")])


def test_external_url_rejected():
    """An absolute URL means pointing the hub at a host this project does not
    control — including a CDN, which would also break the offline property."""
    with pytest.raises(Exception, match="must be a path"):
        ApplicationRegistry([_app(url="https://example.com/map")])


def test_relative_url_rejected():
    """Relative URLs escape the app hierarchy or behave unpredictably."""
    with pytest.raises(Exception, match="must be a path"):
        ApplicationRegistry([_app(url="map")])


def test_card_without_url_must_be_a_client_or_reference():
    with pytest.raises(Exception, match="must declare a url"):
        ApplicationRegistry([_app(category="visualization", url=None)])


def test_client_without_url_is_allowed():
    """A built-artefact card legitimately has nothing to open."""
    reg = ApplicationRegistry(
        [_app(category="client", url=None, status="NOT INSTALLED")]
    )
    assert reg.web_pages() == []


def test_missing_config_yields_empty_registry_not_a_crash(tmp_path, monkeypatch):
    """The registry is a convenience layer, not part of the control path. If
    the file is deleted the robot must still boot."""
    monkeypatch.setenv("AMR_CONFIG_DIR", str(tmp_path))
    reg = load_applications()
    assert len(reg) == 0
    assert reg.payload()["applications"] == []


def test_payload_shape_is_stable(registry):
    """These field names are the public API of the mobile/desktop clients."""
    payload = registry.payload(RuntimeContext())
    assert payload["count"] == len(registry)
    assert payload["version"] == 1
    first = payload["applications"][0]
    for key in (
        "id", "name", "description", "category", "platforms", "url", "api_base",
        "read_only", "declared_status", "status", "reason", "detail",
    ):
        assert key in first, key


def test_resolve_status_rejects_invented_status(registry):
    """A status string absent from STATUSES must raise, not be silently ranked
    above everything else by a missing dict entry."""
    rogue = _app(id="rogue", status="AVAILABLE")
    object.__setattr__(rogue, "status", "PERFECT")  # frozen; bypass it
    with pytest.raises(Exception, match="unknown status"):
        registry.resolve_status(rogue)


def test_categories_cover_the_hub(registry):
    """Each category is a heading in the hub; an unexpected one would render
    as a group the CSS was never written for."""
    assert set(registry.categories()) <= set(CATEGORIES)


def test_no_application_promises_a_binary(registry):
    """No .apk/.exe/.msi/.dmg is produced by this repository, so no entry may
    hint at one in its launch command either."""
    for app in registry.all():
        cmd = (app.launch_command or "").lower()
        assert not re.search(r"\.(apk|exe|msi|dmg|deb)\b", cmd), app.id
        assert "install" not in cmd, app.id


