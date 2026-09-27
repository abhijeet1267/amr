"""Phase C — Applications Hub tests (``/applications`` + ``/applications/state``).

The hub is a **directory**, and the only interesting thing a directory can get
wrong is lying. So these tests are about:

1. it serves (page, assets, route table not accidentally widened),
2. it reads and never writes (no actuator, no POST, no second command path),
3. every status it prints is the registry's decision — and a runtime can only
   make a status *worse*, never better, even when the hardware looks present.

The last point is the one that matters. The Command Center fixture attaches a
mock camera that reports ``available=True``; the camera card must still read
HARDWARE REQUIRED, because no camera has ever been verified on this project.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from amr.apps.registry import STATUSES, Application, ApplicationRegistry
from conftest import NoActuation


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return r.status, r.read()


def _json(port, path):
    return json.loads(_get(port, path)[1])


def _code(port, path):
    try:
        return _get(port, path)[0]
    except urllib.error.HTTPError as e:
        return e.code


def _hub_source(name: str) -> str:
    """The hub's front-end source exactly as served, not re-read from disk."""
    from amr.web import server
    if name.endswith(".html"):
        return server.APPLICATIONS_HTML
    return server._STATIC_FILES[name]


def _strip_comments(src: str) -> str:
    """Drop JS block/line comments, HTML comments and YAML-ish ``#`` lines.

    A comment that *names* the thing it says is absent (this file's own
    "there is no POST here") would otherwise fail the very scan that documents
    it. Same trick as ``test_run_web_does_not_tick_the_robot_itself``.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", src)


def _by_id(port):
    return {a["id"]: a
            for a in _json(port, "/applications/state")["applications"]}


# --------------------------------------------------------------------------- #
# The page is served
# --------------------------------------------------------------------------- #
class TestHubServes:
    def test_page_loads(self, web):
        _app, port, _mgr = web
        status, body = _get(port, "/applications")
        assert status == 200
        assert b"Applications Hub" in body

    def test_page_is_a_real_console_style_document(self, web):
        _app, port, _mgr = web
        html = _get(port, "/applications")[1].decode()
        assert 'class="skip-link"' in html
        assert "aria-live" in html          # filter feedback is announced
        assert 'href="/command-center"' in html
        # Colour is never the only signal: the page says what it is in words.
        assert "read-only" in html
        assert "GET /applications/state" in html

    def test_page_loads_without_a_camera(self, web_no_camera):
        """The hub describes the robot; it must not depend on one."""
        _app, port, _mgr = web_no_camera
        assert _code(port, "/applications") == 200
        assert _code(port, "/applications/state") == 200

    def test_hub_assets_are_served(self, web):
        _app, port, _mgr = web
        assert _code(port, "/static/applications.css") == 200
        assert _code(port, "/static/applications.js") == 200

    def test_the_hub_route_did_not_widen_the_router(self, web):
        _app, port, _mgr = web
        assert _code(port, "/applications/nope") == 404
        assert _code(port, "/applications/state/extra") == 404

    def test_the_console_links_to_the_hub(self, web):
        """A directory nobody can reach from the UI is not integrated."""
        _app, port, _mgr = web
        html = _get(port, "/command-center")[1].decode()
        assert html.count('href="/applications"') >= 2, "topbar + sidebar link"
        assert '"/applications/state"' in _hub_source("applications.js")

    def test_every_page_links_to_the_hub(self, web):
        """The hub must be reachable from wherever a session can *start*.

        The console is not the only entry point: ``/`` is the legacy control
        panel and ``/dashboard`` is the older read-only monitor, and both are
        what a user actually opens. A directory reachable only from one page is
        effectively hidden, so every served HTML surface carries a link.
        """
        _app, port, _mgr = web
        # The hub itself is excluded: a page does not link to itself, it *is*
        # the destination.
        for path in ("/", "/dashboard", "/command-center"):
            html = _get(port, path)[1].decode()
            assert 'href="/applications"' in html, (
                f"{path} offers no link to the applications hub")

    def test_the_hub_links_back_to_the_other_pages(self, web):
        """Leaving the hub must not be a dead end."""
        _app, port, _mgr = web
        hrefs = set(re.findall(r'href="([^"]+)"', _hub_source("applications.html")))
        for target in ("/", "/dashboard", "/command-center"):
            assert target in hrefs, f"the hub never links back to {target}"

    def test_nav_links_are_anchors_not_fetches(self, web):
        """Navigation must not become an API call or a second control path."""
        _app, port, _mgr = web
        for path in ("/", "/dashboard"):
            html = _get(port, path)[1].decode()
            assert 'href="/applications"' in html
            # A nav anchor is markup only: the page must not fetch the hub.
            assert "/applications/state" not in html, (
                f"{path} fetches the hub instead of linking to it")
        # Comments stripped, so prose that *names* the endpoint it says is
        # absent does not fail the very scan that documents it.
        hub_js = _strip_comments(_hub_source("applications.js"))
        assert "/command" not in hub_js


# --------------------------------------------------------------------------- #
# The payload is the registry's, unedited
# --------------------------------------------------------------------------- #
class TestHubPayload:
    def test_payload_shape(self, web):
        _app, port, _mgr = web
        payload = _json(port, "/applications/state")
        assert payload["version"] == 1
        assert payload["count"] == len(payload["applications"]) > 0
        assert payload["categories"], "the hub groups on these"
        for entry in payload["applications"]:
            for key in ("id", "name", "status", "declared_status", "reason",
                        "detail", "category", "platforms", "url"):
                assert key in entry, (entry.get("id"), key)

    def test_payload_matches_the_registry(self, web):
        """The route must report the file, not a second opinion about it."""
        from amr.apps.registry import load_applications
        _app, port, _mgr = web
        served = _json(port, "/applications/state")
        assert [a["id"] for a in served["applications"]] == \
            [a.id for a in load_applications().all()]

    def test_status_never_upgrades(self, web):
        """The load-bearing rule, asserted against the *served* document."""
        _app, port, _mgr = web
        for entry in _json(port, "/applications/state")["applications"]:
            assert STATUSES.index(entry["status"]) >= \
                STATUSES.index(entry["declared_status"]), entry["id"]

    def test_mock_run_is_labelled_mock_not_available(self, web):
        """The fixture runs a mock robot: nothing may claim to be hardware."""
        _app, port, _mgr = web
        cc = _by_id(port)["command_center"]
        assert cc["declared_status"] == "AVAILABLE"
        assert cc["status"] == "MOCK"
        assert cc["reason"] == "mock-robot"

    def test_the_camera_card_is_never_promoted(self, web):
        """A mock camera reporting available=True is NOT a working camera."""
        _app, port, _mgr = web
        cam = _by_id(port)["camera_monitor"]
        assert cam["status"] == "HARDWARE REQUIRED"
        assert cam["declared_status"] == "HARDWARE REQUIRED"

    def test_no_camera_is_explained_by_reason(self, web_no_camera):
        _app, port, _mgr = web_no_camera
        assert _by_id(port)["camera_monitor"]["reason"] == "no-camera"

    def test_url_less_entries_are_marked_as_such(self, web):
        """An API entry is not a screen; the page must be able to tell."""
        _app, port, _mgr = web
        apps = _json(port, "/applications/state")["applications"]
        assert any(a["url"] is None for a in apps), "no API entry to render"
        assert "API" in _hub_source("applications.js")
        assert "app-none" in _hub_source("applications.js")


# --------------------------------------------------------------------------- #
# It reads. It does not write.
# --------------------------------------------------------------------------- #
class TestHubIsReadOnly:
    def test_hub_reads_never_actuate(self, web):
        """Same proof the console uses: a GET must not reach the controller."""
        _app, port, mgr = web
        with NoActuation(mgr.test_transport):
            for path in ("/applications", "/applications/state",
                         "/static/applications.js", "/static/applications.css"):
                _get(port, path)

    def test_the_hub_page_has_no_write_path(self, web):
        """Source-level: this file must not contain a way to move the robot."""
        js = _strip_comments(_hub_source("applications.js"))
        html = _strip_comments(_hub_source("applications.html"))
        for src in (js, html):
            assert "POST" not in src
            assert "method:" not in src        # no verb override on the fetch
            assert "acknowledge" not in src
            assert "replay/" not in src
            assert "<form" not in src
        # The JS may reach exactly one endpoint, and /command is not it.
        assert "fetch(" in js, "the scrape must be looking at real fetches"
        assert "/command" not in js
        assert js.count("fetch(") == 1
        # Every link on the page is a read-only destination: this project's own
        # pages, its own state endpoint, its own assets, or an in-page fragment.
        # The legacy panel "/" is a *page* here, not the /command endpoint --
        # the substring check above is what keeps that distinction honest.
        hrefs = set(re.findall(r'href="([^"]+)"', html))
        assert hrefs, "no links scraped"
        assert all(h == "/" or h.startswith(
            ("/applications", "/command-center", "/dashboard", "/static/", "#"))
                   for h in hrefs), hrefs
        assert re.findall(r'<script src="([^"]+)"', html) == ["/static/applications.js"]

    def test_every_link_on_the_hub_actually_resolves(self, web):
        """A directory full of 404s is worse than no directory."""
        _app, port, _mgr = web
        html = _strip_comments(_hub_source("applications.html"))
        hrefs = sorted(set(re.findall(r'href="([^"]+)"', html)))
        assert hrefs
        for href in hrefs:
            if href.startswith("#") or href.startswith("/static/"):
                continue          # assets are covered by test_hub_assets_are_served
            assert _code(port, href) == 200, f"{href} is linked but not served"

    def test_the_hub_issues_only_get_requests(self, web):
        """One fetch, no options that could change the verb."""
        js = _hub_source("applications.js")
        assert js.count('fetch("/applications/state"') == 1

    def test_the_registry_is_not_a_second_command_path(self, web):
        """No registry card may be writable except the legacy control panel."""
        _app, port, _mgr = web
        writable = [a["id"] for a in _json(port, "/applications/state")["applications"]
                    if not a["read_only"]]
        assert writable == ["control_panel"], writable


# --------------------------------------------------------------------------- #
# Degradation: missing config, empty registry, injected registry
# --------------------------------------------------------------------------- #
class TestHubDegradesHonestly:
    def test_empty_registry_still_serves_an_empty_hub(self, config_dir):
        """A deleted config file must not take the page — or the robot — down."""
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp

        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)
        app = AMRWebApp(mgr, applications=ApplicationRegistry([]))
        port = app.start(host="127.0.0.1", port=0)
        try:
            assert _code(port, "/applications") == 200
            payload = _json(port, "/applications/state")
            assert payload["count"] == 0
            assert payload["applications"] == []
        finally:
            app.stop()
            mgr.shutdown()

    def test_an_injected_registry_is_the_one_served(self, config_dir):
        """Injection is what makes the hub testable; prove it is honoured."""
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp

        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)
        only = Application(
            id="only_card", name="Only Card", description="d" * 40,
            category="reference", status="COMING SOON", platforms=["linux"],
            url="/applications",
        )
        app = AMRWebApp(mgr, applications=ApplicationRegistry([only]))
        assert app.applications().by_id("only_card") is not None
        port = app.start(host="127.0.0.1", port=0)
        try:
            payload = _json(port, "/applications/state")
            assert [a["id"] for a in payload["applications"]] == ["only_card"]
            # COMING SOON outranks nothing: it may not be reported better.
            assert payload["applications"][0]["status"] == "COMING SOON"
        finally:
            app.stop()
            mgr.shutdown()

    def test_a_broken_camera_does_not_break_the_hub(self, config_dir):
        """An honesty layer that can 500 the page is worse than one that says
        'unknown' — the probe must swallow the failure and report the floor."""
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp

        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)

        class BrokenCamera:
            def is_available(self):
                raise RuntimeError("hardware on fire")

        app = AMRWebApp(mgr, camera=BrokenCamera(), simulated=True)
        port = app.start(host="127.0.0.1", port=0)
        try:
            payload = _json(port, "/applications/state")
            cam = {a["id"]: a for a in payload["applications"]}["camera_monitor"]
            assert cam["status"] == "HARDWARE REQUIRED"
            assert cam["reason"] == "no-camera"
        finally:
            app.stop()
            mgr.shutdown()

    def test_a_direct_call_before_start_reports_the_server_as_down(self, config_dir):
        """`server_running` is derived from this process, not assumed."""
        from amr.robot import RobotManager
        from amr.utils.config import load_config
        from amr.web import AMRWebApp

        config = load_config(config_dir)
        mgr, _ = RobotManager.create_mock(config)
        app = AMRWebApp(mgr, simulated=True)
        ctx = app.runtime_context()
        assert ctx.server_running is False
        assert ctx.mock_mode is True
        assert ctx.camera_available is False
        # ...and the payload reflects it rather than claiming the pages are up.
        served = {a["id"]: a for a in app.applications_state()["applications"]}
        assert served["command_center"]["status"] == "OFFLINE"
        assert served["command_center"]["reason"] == "server-unreachable"
        mgr.shutdown()
