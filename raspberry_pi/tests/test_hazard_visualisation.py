"""Tests for the spatial hazard visualisation (``amr.hazard.visualisation``).

C3: pure read-side rendering of recorded hazard events onto the warehouse map.
Everything here runs offline — no hardware, no robot, no network:

* :func:`render_map_svg` — well-formed, deterministic SVG; y-up projection;
  state colours; active/resolved styling; zone rectangles; waypoint labels;
  XML escaping; tolerance for malformed locations/zones/events.
* :func:`events_from_snapshot` — de-duplication (active copies win) and order.
* CLI ``python -m amr.hazard.visualisation`` — file/stdout output, exit codes,
  and no runpy double-import warning.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from amr.hazard import (
    STATE_COLORS,
    HazardEvent,
    HazardEventLog,
    HazardKind,
    HazardLocation,
    HazardSeverity,
    HazardState,
    HazardZone,
    events_from_snapshot,
    read_events,
    render_map_svg,
)
from amr.hazard.visualisation import (
    _bounds,
    _projector,
    _ticks,
)
from amr.hazard.visualisation import (
    main as visualisation_main,
)

SVG = "{http://www.w3.org/2000/svg}"

#: A warehouse map mixing dict-style and list-style entries (both supported).
LOCATIONS = {
    "dock": {"x": 0.0, "y": 0.0, "theta": 0.0},
    "shelf_a": {"x": 2.0, "y": 0.0, "theta": 0.0},
    "shelf_c": {"x": 4.0, "y": 1.5, "theta": 0.0},
    "station": [0.0, 3.0, 0.0],
}


def _event(
    event_id: str,
    *,
    kind: HazardKind = HazardKind.GAS,
    state: HazardState = HazardState.WARNING,
    severity: HazardSeverity = HazardSeverity.WARNING,
    message: str = "msg",
    raised_at: float = 1.0,
    cleared_at: float | None = None,
    location: HazardLocation | None = None,
) -> HazardEvent:
    return HazardEvent(
        event_id=event_id,
        kind=kind,
        severity=severity,
        state=state,
        message=message,
        raised_at=raised_at,
        source="test",
        location=location,
        cleared_at=cleared_at,
    )


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _markers(root: ET.Element) -> list[ET.Element]:
    return [
        el
        for el in root.iter(f"{SVG}circle")
        if el.get("class") == "hazard-event"
    ]


def _marker_for(root: ET.Element, needle: str) -> ET.Element:
    for el in _markers(root):
        title = el.find(f"{SVG}title")
        if title is not None and needle in (title.text or ""):
            return el
    raise AssertionError(f"no marker whose title contains {needle!r}")


# ------------------------------------------------------------------ #
# render_map_svg — geometry, styling, safety of the output
# ------------------------------------------------------------------ #


def test_svg_is_well_formed_xml():
    root = _parse(render_map_svg(LOCATIONS, [_event("e1")]))
    assert root.tag == f"{SVG}svg"
    assert root.get("width") == "780"
    assert root.get("height") == "580"
    assert root.get("viewBox") == "0 0 780 580"


def test_projection_flips_y_axis():
    """World +y must point up the screen (SVG's own y axis points down)."""
    root = _parse(
        render_map_svg(
            LOCATIONS,
            [
                _event(
                    "dock",
                    message="at-dock",
                    location=HazardLocation(x=0.0, y=0.0),
                ),
                _event(
                    "top",
                    message="at-station",
                    location=HazardLocation(x=0.0, y=3.0),
                ),
            ],
        )
    )
    dock_cy = float(_marker_for(root, "at-dock").get("cy"))
    station_cy = float(_marker_for(root, "at-station").get("cy"))
    assert station_cy < dock_cy


def test_markers_carry_state_colour_and_data_attributes():
    root = _parse(
        render_map_svg(
            LOCATIONS,
            [
                _event(
                    "e1",
                    state=HazardState.SLOW,
                    location=HazardLocation(x=2.0, y=0.0),
                ),
            ],
        )
    )
    marker = _marker_for(root, "msg")
    assert marker.get("class") == "hazard-event"
    assert marker.get("data-state") == "SLOW"
    assert marker.get("data-resolved") == "false"
    assert marker.get("fill") == STATE_COLORS["SLOW"] == "#e67e22"
    assert marker.get("fill-opacity") == "1"
    assert marker.find(f"{SVG}title") is not None


def test_resolved_events_are_dimmed():
    root = _parse(
        render_map_svg(
            LOCATIONS,
            [
                _event(
                    "e1",
                    cleared_at=2.0,
                    location=HazardLocation(x=2.0, y=0.0),
                ),
            ],
        )
    )
    marker = _marker_for(root, "msg")
    assert marker.get("data-resolved") == "true"
    assert marker.get("fill-opacity") == "0.45"
    assert marker.get("stroke-width") == "1.5"


def test_active_emergency_gets_white_ring():
    root = _parse(
        render_map_svg(
            LOCATIONS,
            [
                _event(
                    "e1",
                    state=HazardState.EMERGENCY,
                    severity=HazardSeverity.CRITICAL,
                    location=HazardLocation(x=2.0, y=0.0),
                ),
            ],
        )
    )
    marker = _marker_for(root, "msg")
    assert marker.get("fill") == STATE_COLORS["EMERGENCY"] == "#ff3b30"
    assert marker.get("stroke") == "#ffffff"
    assert marker.get("stroke-width") == "4"


def test_message_and_title_are_xml_escaped():
    nasty = '<script>alert("x")</script> & "more"'
    svg = render_map_svg(
        LOCATIONS,
        [_event("e1", message=nasty, location=HazardLocation(x=2.0, y=0.0))],
    )
    assert "<script>" not in svg  # raw markup must never leak
    root = _parse(svg)  # ...and the document must still be well formed
    title = _marker_for(root, "alert").find(f"{SVG}title")
    assert title is not None and nasty in (title.text or "")


def test_render_is_deterministic():
    events = [
        _event(
            "e2",
            state=HazardState.STOP,
            raised_at=2.0,
            location=HazardLocation(x=4.0, y=1.5),
        ),
        _event("e1", raised_at=1.0, location=HazardLocation(x=2.0, y=0.0)),
    ]
    zones = [
        HazardZone(name="bay", x_min=3.0, x_max=5.0, y_min=0.5, y_max=2.5)
    ]
    first = render_map_svg(LOCATIONS, events, zones=zones, title="T")
    second = render_map_svg(LOCATIONS, events, zones=zones, title="T")
    assert first == second


# ------------------------------------------------------------------ #
# Clustering, side panel, zones, waypoints, tolerance
# ------------------------------------------------------------------ #


def test_colocated_events_fan_out_instead_of_overlapping():
    events = [
        _event(
            "a",
            raised_at=1.0,
            message="first",
            location=HazardLocation(x=2.0, y=0.0),
        ),
        _event(
            "b",
            raised_at=2.0,
            message="second",
            location=HazardLocation(x=2.0, y=0.0),
        ),
    ]
    root = _parse(render_map_svg(LOCATIONS, events))
    assert len(_markers(root)) == 2
    first = _marker_for(root, "first")
    second = _marker_for(root, "second")
    dx = float(second.get("cx")) - float(first.get("cx"))
    dy = float(second.get("cy")) - float(first.get("cy"))
    # The second marker is offset, but stays within the fan-out radius.
    assert (dx or dy) != 0.0
    assert math.hypot(dx, dy) <= 11.0 + 1e-6


def test_unlocated_events_go_to_the_panel_not_the_map():
    events = [
        _event(
            "located",
            message="plotted",
            location=HazardLocation(x=2.0, y=0.0),
        ),
        _event(
            "lost",
            kind=HazardKind.FIRE,
            state=HazardState.STOP,
            severity=HazardSeverity.CRITICAL,
            message="nowhere",
        ),
    ]
    root = _parse(render_map_svg(LOCATIONS, events))
    assert len(_markers(root)) == 1
    _marker_for(root, "plotted")  # the located one is on the map ...
    labels = [el.text for el in root.iter(f"{SVG}text") if el.text]
    assert "Without location (1)" in labels  # ... the other in the panel
    assert "FIRE [STOP]" in labels
    assert any("1 without location" in text for text in labels)


def test_zone_rectangles_are_dashed_and_labelled():
    zone = HazardZone(
        name="charging bay",
        x_min=3.0,
        x_max=5.0,
        y_min=0.5,
        y_max=2.5,
        severity=HazardSeverity.CRITICAL,
        kind=HazardKind.ZONE_BREACH,
    )
    root = _parse(render_map_svg(LOCATIONS, [], zones=[zone]))
    rects = [el for el in root.iter(f"{SVG}rect") if el.get("stroke-dasharray")]
    assert len(rects) == 1
    assert rects[0].get("stroke") == "#e74c3c"
    assert rects[0].get("fill-opacity") == "0.10"
    labels = [el.text for el in root.iter(f"{SVG}text") if el.text]
    assert "charging bay" in labels


def test_empty_inputs_still_render_a_valid_map():
    root = _parse(render_map_svg({}, []))
    assert root.tag == f"{SVG}svg"
    assert _markers(root) == []
    labels = [el.text for el in root.iter(f"{SVG}text") if el.text]
    assert any("0 events (0 active)" in text for text in labels)


def test_malformed_entries_are_skipped_not_fatal():
    locations = {
        "good": {"x": 1.0, "y": 2.0},
        "bad_coords": {"x": "left"},
        "not_a_waypoint": "junk",
    }
    zones = [
        {"name": "ok", "x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0},
        {"name": 42, "x_min": "nope"},  # unparseable → skipped
        "not-a-zone",
    ]
    events = [
        123,  # not an event → skipped
        _event("e1", location=HazardLocation(x=1.0, y=2.0)),
        {"event_id": "e2", "location": {"x": "left"}},  # → unlocated panel
    ]
    svg = render_map_svg(locations, events, zones=zones)
    root = _parse(svg)
    labels = [el.text for el in root.iter(f"{SVG}text") if el.text]
    assert "good" in labels
    assert ">bad_coords" not in svg and ">not_a_waypoint" not in svg
    assert len(_markers(root)) == 1
    # Both usable events counted; e2 fell back to the panel, 123 dropped.
    assert any(
        "2 events (2 active) · 1 without location" in text for text in labels
    )


def test_waypoints_and_dock_are_drawn_with_labels():
    root = _parse(render_map_svg(LOCATIONS, []))
    labels = [el.text for el in root.iter(f"{SVG}text") if el.text]
    for name in ("dock", "shelf_a", "shelf_c", "station"):
        assert name in labels
    nodes = [el for el in root.iter(f"{SVG}circle") if el.get("r") == "7"]
    assert len(nodes) == len(LOCATIONS)  # list-style entries render too
    docks = [el for el in nodes if el.get("stroke") == "#2ecc71"]
    assert len(docks) == 1  # exactly one green dock node


# ------------------------------------------------------------------ #
# events_from_snapshot
# ------------------------------------------------------------------ #


def test_events_from_snapshot_dedupes_and_sorts():
    stale = _event("e1", raised_at=1.0, state=HazardState.WARNING).to_dict()
    fresh = _event("e1", raised_at=1.0, state=HazardState.STOP).to_dict()
    later = _event("e2", raised_at=9.0).to_dict()
    snapshot = {"recent_events": [stale, later], "active_events": [fresh]}
    merged = events_from_snapshot(snapshot)
    assert [e["event_id"] for e in merged] == ["e1", "e2"]
    # The active (escalated) copy wins over the stale recent one.
    assert merged[0]["state"] == "STOP"


def test_events_from_snapshot_tolerates_junk():
    assert events_from_snapshot({"active_events": [42, None]}) == []
    assert events_from_snapshot("not a snapshot") == []
    assert events_from_snapshot({}) == []


# ------------------------------------------------------------------ #
# Internal geometry helpers
# ------------------------------------------------------------------ #


def test_bounds_expand_a_degenerate_single_point():
    xmin, xmax, ymin, ymax = _bounds([("solo", 2.0, 3.0)], [], [(2.0, 3.0)])
    assert xmax - xmin >= 1.0 and ymax - ymin >= 1.0
    assert xmin <= 2.0 <= xmax and ymin <= 3.0 <= ymax


def test_bounds_fall_back_to_defaults_when_nothing_to_draw():
    assert _bounds([], [], []) == (0.0, 5.0, 0.0, 3.0)


def test_projector_flips_y_and_preserves_order():
    project = _projector((0.0, 4.0, 0.0, 4.0), 0.0, 0.0, 100.0, 100.0)
    x_lo, y_lo = project(0.0, 0.0)
    _, y_hi = project(0.0, 4.0)
    assert y_hi < y_lo  # +y is up on screen
    assert x_lo == 0.0


def test_ticks_cover_the_range_without_overflow():
    assert _ticks(0.0, 5.0, 1.0) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    # No multiple of 1.0 fits inside (0.4, 0.6).
    assert _ticks(0.4, 0.6, 1.0) == []


# ------------------------------------------------------------------ #
# CLI (python -m amr.hazard.visualisation)
# ------------------------------------------------------------------ #


def test_cli_writes_svg_file(tmp_path, config_dir):
    events_file = tmp_path / "events.jsonl"
    log = HazardEventLog(path=str(events_file))
    log.record(_event("cli-1", location=HazardLocation(x=2.0, y=1.0)))
    out = tmp_path / "map.svg"
    rc = visualisation_main(
        [
            "--config-dir",
            str(config_dir),
            "--events",
            str(events_file),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.is_file()
    recorded = read_events(str(events_file))  # JSONL round trip
    assert [e["event_id"] for e in recorded] == ["cli-1"]
    root = _parse(out.read_text(encoding="utf-8"))
    _marker_for(root, "msg")  # the recorded event made it onto the map


def test_cli_prints_svg_to_stdout(config_dir, capsys, tmp_path):
    missing = tmp_path / "nope.jsonl"
    rc = visualisation_main(
        ["--config-dir", str(config_dir), "--events", str(missing), "--out", "-"]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.lstrip().startswith("<svg")
    # Honest note: a missing events file must not look like "no hazards".
    assert f"no events read from {missing}" in captured.err


def test_cli_bad_config_dir_exits_1(tmp_path, capsys):
    rc = visualisation_main(
        [
            "--config-dir",
            str(tmp_path / "missing"),
            "--events",
            "unused.jsonl",
            "--out",
            "-",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "FATAL" in captured.err


def test_module_run_has_no_runpy_warning():
    """`python -m amr.hazard.visualisation` must not double-import itself."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (here, env.get("PYTHONPATH")) if part
    )
    proc = subprocess.run(
        [sys.executable, "-m", "amr.hazard.visualisation", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=here,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "found in sys.modules" not in proc.stderr
    assert "RuntimeWarning" not in proc.stderr
    assert "usage:" in proc.stdout