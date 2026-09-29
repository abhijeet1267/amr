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
import subprocess
import sys
from pathlib import Path
from typing import Dict

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


def test_every_fragment_is_a_view_the_console_actually_has(registry):
    """``#map`` must name a real view, not merely a real page.

    ``test_every_url_is_a_real_route`` strips the fragment and checks the path,
    which is the right thing for the *server* — it never sees the hash. But the
    browser does, and ``fromHash()`` silently falls back to ``overview`` for a
    name it does not recognise. A typo'd ``#mapp`` would therefore be a link
    that opens the console on the wrong view with no error anywhere: exactly the
    kind of quietly-wrong link this registry is meant to prevent.

    So the fragments are checked against ``VIEW_KEYS`` read out of the *served*
    JavaScript rather than against a list restated here, which would be a second
    thing able to go stale.
    """
    from amr.web import server

    js = server._STATIC_FILES["command_center.js"]
    match = re.search(r"var\s+VIEW_KEYS\s*=\s*\[(.*?)\]", js, re.S)
    assert match, "could not find VIEW_KEYS in the served console script"
    views = set(re.findall(r'"([a-z]+)"', match.group(1)))
    assert len(views) > 5, f"VIEW_KEYS scrape looks wrong: {sorted(views)}"

    for app in registry.all():
        if not app.url or "#" not in app.url:
            continue
        fragment = app.url.split("#", 1)[1]
        assert fragment in views, (
            f"{app.id}: {app.url!r} targets a view the console does not have "
            f"(known: {sorted(views)}) — it would silently open Overview"
        )


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


def test_connectivity_cards_are_about_the_host_not_the_robot(registry):
    """Wi-Fi/Bluetooth here describe the *machine running the process*.

    The AMR has no radio of its own in this codebase, so a card implying the
    robot has one would be the exact kind of fiction this file exists to stop.
    ``requires_robot`` is therefore False: losing the link breaks the operator
    console, it does not disable a robot capability.
    """
    for app_id in ("connectivity_overview", "wifi_link", "bluetooth_link"):
        app = registry.by_id(app_id)
        assert app is not None, f"{app_id} missing from the registry"
        assert app.requires_robot is False, (
            f"{app_id} claims a robot dependency; this is a host property"
        )
        assert app.read_only is True


def test_connectivity_cards_are_not_oversold(registry):
    """Statuses must not claim more than was actually verified.

    ``wifi_link`` reports presence and link state but never the SSID, so
    PARTIAL is the truthful status. ``bluetooth_link`` was never exercised on
    real hardware, so it cannot be AVAILABLE. Both assertions exist because the
    tempting value is the flattering one.
    """
    wifi = registry.by_id("wifi_link")
    assert wifi.status == "PARTIAL", (
        "wifi_link measures presence and link state but not SSID/signal; "
        "AVAILABLE would overstate it"
    )
    bt = registry.by_id("bluetooth_link")
    assert bt.status == "HARDWARE REQUIRED", (
        "bluetooth_link has never been run against a real adapter"
    )


def test_bluetooth_never_claims_a_device_count(registry):
    """No device discovery is performed, so no count may be implied.

    Discovery needs a privileged scan; doing it from a read-only endpoint would
    also make the web layer an actuator. The payload reports ``None`` and the
    card must not imply otherwise.
    """
    bt = registry.by_id("bluetooth_link")
    assert "null" in bt.description or "not counted" in bt.description.lower() or \
        "always null" in bt.description.lower(), (
        "bluetooth_link should state that it does not count paired devices"
    )


DEMO_IDS = ("unified_demo", "warehouse_roundtrip", "hazard_scenario",
            "vision_pipeline", "hazard_map_svg")


def test_every_runnable_demo_is_registered(registry):
    """The hub's "run it" list is generated from the registry, so a demo that is
    not registered is a demo an operator cannot find.

    This pins the five entry points the README documents. If one is renamed or
    dropped, this fails rather than leaving the hub quietly offering four.
    """
    found = {a.id for a in registry.all() if a.category == "demo"}
    assert found == set(DEMO_IDS), (
        f"demo entries changed: {sorted(found)} (expected {sorted(DEMO_IDS)})"
    )


README_MD = Path(__file__).resolve().parents[2] / "README.md"


def test_readme_publishes_links_that_are_real_routes():
    """Every ``http://localhost:8080/...`` link in the README must be served.

    A broken link in the README is the first thing a new user clicks. They have
    no way to tell a typo from a server that simply is not running, so the
    cheapest possible failure to diagnose is the one to rule out here.

    The port in the link is stripped: the path is what the server routes.
    """
    text = README_MD.read_text(encoding="utf-8")
    links = set(re.findall(r"http://localhost:\d+(/[^\s)\"'|]*)", text))
    assert links, "no localhost links found in the README - did it change?"
    routes = _served_routes()
    for link in sorted(links):
        base = link.split("#", 1)[0]
        assert base in routes, (
            f"README links to {link!r}, which server.py does not serve"
        )


def test_readme_says_how_to_install_the_dependencies():
    """`python -m amr.main` fails with ``No module named 'yaml'`` on a fresh
    checkout, because the dependencies live in the venv and not on the system
    Python.

    That is exactly what happened: the run instructions assumed a working
    environment a first-time user does not have, so the very first command in
    the README died on a stack trace. The install step has to appear BEFORE the
    first runnable command, not only in "Installing & running" further down.

    Compared against the ``python -m amr.main`` *inside a code fence* rather
    than the first mention of those words anywhere: the prose above the block
    names the error on purpose, and matching that would make the test fail for
    the right content.
    """
    text = README_MD.read_text(encoding="utf-8")
    see_it_work = text.split("## See it work", 1)[1]
    blocks = re.findall(r"```bash\n(.*?)```", see_it_work, re.S)
    assert blocks, "no bash blocks in the See it work section"

    first_run = next((i for i, b in enumerate(blocks)
                      if "python -m amr.main" in b), None)
    assert first_run is not None, "no runnable command in See it work"
    install = next((i for i, b in enumerate(blocks)
                    if "pip install" in b), None)
    assert install is not None, "no pip install in the See it work section"
    assert install < first_run, (
        "the install block must come before the first run command, or a new "
        "user hits ModuleNotFoundError before being told how to fix it"
    )


SHOWCASE_HTML = README_MD.parent / "showcase.html"

#: The suite's 2 camera tests skip when opencv-python/numpy are absent. Named
#: here rather than inferred, because a badge that counted them would claim more
#: than actually ran.
SKIPPED = 2


def test_showcase_does_not_go_quietly_stale():
    """The showcase is a public page; its numbers must match reality.

    It claimed **276** tests for a long time while the repository was at 1418,
    and nothing noticed -- the same failure mode as the CURRENT_STATUS table, in
    a file that had no test at all. The badge and the status table are both
    checked, because either alone can drift.
    """
    html = SHOWCASE_HTML.read_text(encoding="utf-8")

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts="],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    ).stdout
    # The badge reports *passed*, not collected: 2 camera tests skip when
    # opencv/numpy are absent, and a badge that counted them would overstate
    # what actually ran.
    total = len([l for l in collected.splitlines() if l.startswith("tests/")])
    passed = total - SKIPPED

    m = re.search(r"tests-(\d+)", html)
    assert m, "the showcase has no test-count badge"
    assert int(m.group(1)) == passed, (
        f"showcase badge says {m.group(1)} tests, suite runs {passed}"
    )

    claimed = {int(x) for x in re.findall(r"(\d+)\s+passed", html)}
    assert claimed, "the showcase status table states no test count"
    assert claimed == {passed}, (
        f"showcase status table says {claimed}, suite runs {passed}"
    )

    # It must not advertise a hardware capability it has never verified.
    assert "NOT TESTED" in html, (
        "the showcase must say hardware is untested; the project's whole "
        "documentation standard depends on that being visible"
    )


def test_showcase_and_app_share_one_palette():
    """Two different design languages read as two different products.

    The showcase had invented its own tokens: --bg #0b0f18 against the app's
    #0b0f16, accent #4da3ff against #22d3ee, and --ok/--err that matched nothing
    in the app at all. Someone who read the showcase and then opened the
    console saw a change of brand. Compared value by value, not by eye.
    """
    html = SHOWCASE_HTML.read_text(encoding="utf-8")
    css = (Path(__file__).resolve().parents[1] / "amr" / "web" / "static"
           / "command_center.css").read_text(encoding="utf-8")

    def token(text: str, name: str) -> str:
        m = re.search(re.escape(name) + r"\s*:\s*(#[0-9a-fA-F]{3,6})", text)
        assert m, f"{name} not found"
        return m.group(1).lower()

    for sc_name, app_name in (
        ("--bg", "--bg"), ("--text", "--text"), ("--line", "--line"),
        ("--muted", "--muted"), ("--dim", "--dim"),
        ("--acc", "--accent"), ("--ok", "--ok"), ("--crit", "--crit"),
    ):
        assert token(html, sc_name) == token(css, app_name), (
            f"{sc_name} is {token(html, sc_name)} in the showcase but "
            f"{token(css, app_name)} in the app"
        )


def test_current_status_test_counts_are_not_stale(registry):
    """The per-file table in CURRENT_STATUS.md must match reality.

    It drifted for a long time: two whole test files were missing from it and two
    other counts were wrong, with nothing to notice. A status document whose
    numbers are quietly fiction is worse than one that says less, so the table
    is checked against a measured collection rather than trusted.

    The file count in section 1 is checked too, because a wrong one is the
    sort of detail that survives for months.
    """
    text = README_MD.parent.joinpath("AI_CONTEXT", "CURRENT_STATUS.md").read_text(
        encoding="utf-8")

    # Counts as "(name.py   38" at the start of a line, ignoring alignment.
    claimed = {m.group(1): int(m.group(2))
               for m in re.finditer(r"(test_[a-z_0-9]+\.py)\s+(\d+)", text)}
    assert claimed, "no per-file counts found in CURRENT_STATUS.md"

    actual: Dict[str, int] = {}
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts="],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    ).stdout
    for m2 in re.finditer(r"^tests/(test_[a-z_0-9]+\.py)", out, re.M):
        actual[m2.group(1)] = actual.get(m2.group(1), 0) + 1
    assert actual, "collection produced no test ids"

    missing = sorted(set(actual) - set(claimed))
    assert not missing, (
        f"CURRENT_STATUS.md does not list these test files: {missing}"
    )
    wrong = {n: (claimed[n], actual[n]) for n in actual
             if n in claimed and claimed[n] != actual[n]}
    assert not wrong, (
        "CURRENT_STATUS.md per-file counts are wrong (claimed, actual): "
        f"{wrong}"
    )

    # Section 1's "Test files" line.
    m = re.search(r"Test files\s*\|\s*(\d+)", text)
    assert m, "CURRENT_STATUS.md has no 'Test files' line"
    assert int(m.group(1)) == len(actual), (
        f"CURRENT_STATUS.md says {m.group(1)} test files, there are {len(actual)}"
    )


def test_demos_are_commands_not_pages(registry):
    """A demo is run in a terminal, so it must have a command and no URL.

    The `demo` category is exempt from the "a card with no URL is dead" rule
    precisely because these have nothing to click; that exemption is only
    correct while every entry in it really is a command.
    """
    for app_id in DEMO_IDS:
        app = registry.by_id(app_id)
        assert app.launch_command, f"{app_id} has no command to run"
        assert app.url is None, f"{app_id} is a command, not a page"
        assert app.read_only is True, f"{app_id} must not be able to actuate"


def test_demo_commands_are_real_module_invocations(registry):
    """Each command must name a module that actually exists.

    The registry is the hub's only source of truth for how to launch this
    project, so a typo'd module name would ship as a copy button that fails for
    the operator. Checked against the filesystem rather than by importing,
    because importing every demo would execute them.
    """
    root = Path(__file__).resolve().parents[1] / "amr"
    for app_id in DEMO_IDS:
        cmd = registry.by_id(app_id).launch_command
        assert cmd.startswith("python -m amr."), cmd
        module = cmd[len("python -m amr."):].split()[0]
        # `amr.demo` is a module (demo.py); the rest are packages with __main__.
        as_pkg = root / Path(module.replace(".", "/")) / "__main__.py"
        as_mod = root / Path(module.replace(".", "/")).with_suffix(".py")
        assert as_pkg.exists() or as_mod.exists(), (
            f"{app_id}: 'python -m amr.{module}' has no runnable target "
            f"(looked for {as_pkg.name} and {as_mod.name})"
        )


def test_no_demo_command_promises_hardware(registry):
    """Every demo must be mock or simulated.

    A demo that quietly talked to real hardware would be the most dangerous
    kind of documentation error in this project: an operator copies it, expects
    a simulation, and gets a moving robot.
    """
    for app_id in DEMO_IDS:
        app = registry.by_id(app_id)
        assert app.requires_hardware is False, f"{app_id} claims hardware"
        blob = (app.description + " " + (app.launch_command or "")).lower()
        assert "mock" in blob or "simulat" in blob or "offline" in blob, (
            f"{app_id} does not say it is simulated; an operator must be able "
            f"to tell that from the card alone"
        )



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


