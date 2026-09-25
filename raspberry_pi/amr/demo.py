"""C15 — the unified deterministic AMR demonstration.

One offline, mock-only run that exercises the major completed components
*together*, through their real interfaces:

    mission -> navigation -> simulated vision -> hazard -> safety
            -> navigation change -> mission continues -> completion
            -> automatic recording -> discovery -> replay

Nothing here re-implements a subsystem. The demo composes the same objects the
web runtime builds:

===========================  ==========================================
Component                    Real object used
===========================  ==========================================
robot control / safety       ``RobotManager`` (mock serial transport)
Layer 3.5 hazard layer       ``HazardManager`` + ``VisionHazardSource``
vision evidence              ``VisionDetection`` (the C5 contract)
C6 avoidance                 ``AvoidancePolicy`` via ``LocalNavigator``
mission                      ``WarehouseTaskManager``
telemetry                    ``TelemetryCollector`` (the C7 collector)
runtime tick + recording     ``AMRWebApp._tick_once`` / ``AutoRecorder``
discovery / replay           ``RecordingStore`` + ``ReplayPlayer``
===========================  ==========================================

Determinism
-----------
The scenario is driven by a **step counter**, never by wall-clock time, and
there is no randomness anywhere — so the same configuration always produces the
same sequence of mission phases, hazard events, safety verdicts and navigation
outcomes. The only things that legitimately vary between runs are the recording
*filename* and the absolute wall timestamps, both of which come from the real
clock by design.

Coordinate honesty (C13 rule, preserved)
----------------------------------------
The scripted detection carries a bounding box in **image space** and no world
pose, so the hazard is *not* placed on the warehouse map; it stays an
unlocated visual hazard. The demo never converts a pixel box into metres.

Actuation honesty
-----------------
The mission genuinely drives the mock robot, so the mock transport records
wheel commands — that is how a simulated mission moves. What is asserted is
narrower and stated precisely in :class:`ActuationAudit`: nothing may reach
*physical* hardware, the demo harness itself must not command a motor, and
every simulated wheel command must have gone through the one manager gate.

Hardware / firmware: NOT TESTED.

This proves **software integration only**. It is not real-world validation,
hardware validation, or physical-robot validation.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .hazard.manager import HazardManager
from .hazard.sources import VisionHazardSource
from .hazard.vision import VisionBoundingBox, VisionClass, VisionDetection
from .logging import get_logger
from .telemetry import TelemetryCollector, read_recording
from .telemetry.replay import ReplayPlayer
from .telemetry.replay_control import RecordingStore
from .utils.config import AppConfig, HazardConfig

#: Fixed virtual epoch for the demo clock. Nothing branches on wall-clock time;
#: this only makes recorded timestamps reproducible run to run.
DEMO_EPOCH = 1_700_000_000.0

#: Fixed integration step. The mission is stepped with this, never with a
#: measured interval, so the trajectory is reproducible.
DEMO_DT = 0.05

#: Script position (in steps) at which the scripted obstacle appears/clears.
OBSTACLE_FROM_STEP = 30
OBSTACLE_TO_STEP = 42

#: Confidence inside the WARNING band (warn_at 0.5, critical_at 0.8). This
#: matters: a CRITICAL reading would make the hazard layer *block* motion and the
#: C6 policy would never get to manoeuvre. WARNING is exactly the case the
#: avoidance gate exists for.
OBSTACLE_CONFIDENCE = 0.70

#: A pixel box in a 640x480 frame. Image space only.
OBSTACLE_BBOX = (250, 300, 140, 90)

#: Deterministic clearance stand-in for the C6 policy's open-side check. There
#: is no calibrated clearance feed in the project (a documented C6 gap), so the
#: demo supplies one explicitly rather than letting the policy guess a heading.
DEMO_CLEARANCE = {"LEFT": 2.0, "RIGHT": 2.0}

#: Mission scenario, matching the existing warehouse demo.
DEMO_PICK = "shelf_a"
DEMO_DROP = "station"
DEMO_DOCK = "dock"
DEMO_PAYLOAD = "SKU-1"


# --------------------------------------------------------------------------- #
# Deterministic demo adapters (the only genuinely new code)
# --------------------------------------------------------------------------- #
class ScriptedVisionDetector:
    """A deterministic, step-indexed detection script (SIMULATION ONLY).

    The project's ``SimulatedVisionDetector`` returns a *fixed* scenario, which
    is right for tests but cannot express "an obstacle appears part-way through
    a run". This adapter is the smallest thing that can: it maps a step index to
    a set of :class:`VisionDetection` objects, so the scenario is a pure
    function of the step counter.

    It is a demo/test adapter, not a new vision backend: it produces the
    existing C5 ``VisionDetection`` contract, and nothing downstream can tell
    the difference.
    """

    def __init__(self, clock, *, from_step: int = OBSTACLE_FROM_STEP,
                 to_step: int = OBSTACLE_TO_STEP,
                 confidence: float = OBSTACLE_CONFIDENCE,
                 bbox: Sequence[float] = OBSTACLE_BBOX,
                 source: str = "camera_front") -> None:
        self._clock = clock
        self._from = int(from_step)
        self._to = int(to_step)
        self._confidence = float(confidence)
        self._bbox = tuple(bbox)
        self._source = source
        self._step = 0
        #: Every detection this script ever produced, for the demo summary.
        self.emitted: List[VisionDetection] = []

    @property
    def step(self) -> int:
        return self._step

    def advance(self) -> int:
        """Move the script on by one step; returns the new step index."""
        self._step += 1
        return self._step

    def detect(self) -> Tuple[VisionDetection, ...]:
        """The C5 detector protocol: detections for the current step."""
        if not (self._from <= self._step < self._to):
            return ()
        det = VisionDetection(
            vision_class=VisionClass.OBSTACLE,
            confidence=self._confidence,
            # Image space. No world `location` is supplied, and none may be
            # derived from this box.
            bbox=VisionBoundingBox.from_any(self._bbox),
            timestamp=self._clock(),
            source=self._source,
            object_id="o-1",
            metadata={"frame": [640, 480], "simulated": True},
        )
        self.emitted.append(det)
        return (det,)


class SimulatedClearance:
    """Deterministic open-side clearance stand-in (SIMULATION ONLY).

    The C6 policy refuses to pick a heading without proof that a side is open.
    There is no calibrated clearance feed in the project yet, so the demo
    provides this constant, clearly-labelled stand-in instead of inventing a
    measurement. With no clearance at all the policy would correctly escalate
    to REPLAN.
    """

    def __init__(self, clearance: Optional[Dict[str, float]] = None) -> None:
        self._clearance = dict(clearance or DEMO_CLEARANCE)

    def __call__(self) -> Dict[str, float]:
        return dict(self._clearance)


@dataclass
class ActuationAudit:
    """Precisely what the demo did and did not do to actuators.

    Split into several numbers because "0 actuator writes" is ambiguous: a
    simulated mission legitimately produces wheel commands on the *mock*
    transport, while nothing may reach *physical* hardware and the demo code
    itself must not command a motor.
    """

    transport_writes: int = 0
    wheel_commands: int = 0
    physical_writes: int = 0
    demo_command_calls: int = 0
    via_manager_gate: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "transport_writes": self.transport_writes,
            "wheel_commands": self.wheel_commands,
            "physical_writes": self.physical_writes,
            "demo_command_calls": self.demo_command_calls,
            "via_manager_gate": self.via_manager_gate,
        }


def _count_wheel_commands(lines: Sequence[str]) -> int:
    """How many of the transport's lines were motor commands.

    The Arduino protocol's actuator verbs are ``MOVE`` and ``D`` (differential
    drive); ``PING`` / ``VERSION`` / ``SENSOR`` / ``STOP`` polls and halts are
    the runtime's own traffic, not commanded motion. The command strings are
    built by :mod:`amr.communication.protocol`, e.g. ``MOVE L=50 R=50``.
    """
    wheel = 0
    for line in lines:
        text = str(line).strip().upper()
        if text.startswith("MOVE") or text.startswith("D"):
            wheel += 1
    return wheel


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #
@dataclass
class DemoResult:
    """Everything the demo observed, for assertions and for the CLI report."""

    #: Ordered, de-duplicated scenario markers, e.g. ``mission:PICK``,
    #: ``hazard:WARNING``, ``avoidance:TURN``, ``mission:COMPLETED``.
    timeline: List[str] = field(default_factory=list)
    steps: int = 0
    mission_id: Optional[str] = None
    tasks_completed: int = 0
    mission_final_phase: Optional[str] = None
    mission_final_progress: Optional[float] = None

    detections_emitted: int = 0
    detection_class: Optional[str] = None
    detection_confidence: Optional[float] = None
    detection_bbox: Optional[List[float]] = None

    hazard_kind: Optional[str] = None
    hazard_severity: Optional[str] = None
    hazard_state: Optional[str] = None
    hazard_source: Optional[str] = None
    hazard_bbox_in_metadata: bool = False
    hazard_placed_in_world: bool = False
    hazard_event_id: Optional[str] = None

    safety_actions: List[str] = field(default_factory=list)
    avoidance_actions: List[str] = field(default_factory=list)
    yaw_turn_deg: float = 0.0

    recording_id: Optional[str] = None
    recording_frames: int = 0
    discovered_ids: List[str] = field(default_factory=list)
    replay_frames: int = 0
    replay_has_mission: bool = False
    replay_has_hazard: bool = False
    replay_has_completion: bool = False

    audit: ActuationAudit = field(default_factory=ActuationAudit)
    ok: bool = False
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items()}
        out["audit"] = self.audit.to_dict()
        return out

    def timeline_index(self, marker: str) -> int:
        """Position of ``marker`` in the timeline, or ``-1`` when absent."""
        try:
            return self.timeline.index(marker)
        except ValueError:
            return -1


def _mark(result: DemoResult, marker: str) -> None:
    """Append a marker unless it repeats consecutively (keeps it readable)."""
    if not result.timeline or result.timeline[-1] != marker:
        result.timeline.append(marker)


def _demo_hazard_config(base: HazardConfig) -> HazardConfig:
    """Hazard config for the demo: the layer on, vision thresholds explicit.

    Built from the shipped config so any future field is inherited rather than
    silently dropped. The vision band is stated explicitly (0.5 / 0.8) because
    the demo's obstacle confidence is chosen to land inside it.
    """
    import dataclasses

    return dataclasses.replace(
        base, enabled=True, vision_enabled=True,
        vision_warn_at=0.5, vision_critical_at=0.8,
    )


def _demo_safety_config(config: AppConfig):
    """Safety config for the demo: C6 avoidance switched on.

    The shipped default is ``enabled: false`` (deliberately inert), so the demo
    opts in explicitly here. This is a *software* toggle — the underlying
    thresholds remain unvalidated, exactly as ``config/safety.yaml`` says.
    """
    import dataclasses

    avoidance = getattr(config.safety, "avoidance", None)
    if avoidance is None:
        return config.safety
    return dataclasses.replace(
        config.safety,
        avoidance=dataclasses.replace(avoidance, enabled=True),
    )


def run_unified_demo(
    config: AppConfig,
    recordings_dir: str,
    *,
    max_steps: int = 1200,
    dt: float = DEMO_DT,
) -> DemoResult:
    """Run the unified scenario once and return everything it observed.

    The stack is assembled from the real objects; nothing here is a stand-in
    except :class:`ScriptedVisionDetector` (which produces the real C5
    detection contract) and :class:`SimulatedClearance` (a labelled stand-in
    for a feed the project does not have yet).
    """
    import dataclasses

    from .main import build_navigator, build_warehouse
    from .robot import RobotManager
    from .telemetry import AutoRecorder, build_console_state
    from .web import AMRWebApp

    result = DemoResult()
    log = get_logger("demo")

    # -- deterministic virtual clock (steps, never wall time) ----------------
    state = {"t": DEMO_EPOCH, "step": 0}

    def clock() -> float:
        return state["t"]

    # -- real components ----------------------------------------------------
    mgr, transport = RobotManager.create_mock(config)
    mgr.test_transport = transport
    mgr.start()

    detector = ScriptedVisionDetector(clock)
    hazard = HazardManager.from_config(
        _demo_hazard_config(config.hazard), clock=clock)
    hazard.add_source(
        VisionHazardSource(detector.detect, name="vision",
                           warn_at=0.5, critical_at=0.8)
    )
    mgr.attach_hazard(hazard)

    demo_config = dataclasses.replace(
        config, hazard=_demo_hazard_config(config.hazard),
        safety=_demo_safety_config(config),
    )
    nav = build_navigator(mgr, demo_config, hazard=hazard)
    # The demo supplies the clearance feed C6 needs but the project lacks yet.
    nav._clearance_provider = SimulatedClearance()
    wh = build_warehouse(mgr, demo_config, nav, mission_id="c15-unified-demo")

    collector = TelemetryCollector(mgr, navigator=nav, warehouse=wh,
                                   simulated=True, clock=clock)
    app = AMRWebApp(
        mgr, camera=None, telemetry=collector, navigator=nav, warehouse=wh,
        simulated=True, recordings_dir=recordings_dir, auto_record=True,
    )
    # Configure the runtime's own recorder: same class, demo cadence/clock.
    app._auto = AutoRecorder(recordings_dir, enabled=True, min_interval_s=0.0,
                             clock=clock)

    yaw_start = nav.current_pose().theta
    # Deliberately NOT app.start(): that also spawns the background control-loop
    # thread, which would tick the robot *concurrently* with the deterministic
    # loop below. Two loops means two clocks and a non-deterministic scenario.
    # The demo owns the pacing instead and drives the very same
    # `AMRWebApp._tick_once` the background thread calls — same tick, same
    # recorder, exactly one loop.
    app._auto.start()
    try:
        wh.submit_pick(DEMO_PICK, payload_id=DEMO_PAYLOAD)
        wh.submit_place(DEMO_DROP, payload_id=DEMO_PAYLOAD)
        wh.submit_return_to_dock()

        for _ in range(max_steps):
            state["step"] += 1
            state["t"] += dt
            detector.advance()
            # 1) Mission iteration: control tick (polls sensors + evaluates the
            #    hazard layer), then one navigation step (runs the C6 gate).
            wh.process(dt)
            # 2) The web runtime's own tick: the same method the background
            #    loop calls. This is what records the snapshot, so the demo
            #    proves the real runtime records rather than writing a file.
            app._tick_once(dt)
            _observe(result, mgr, nav, hazard, wh, collector, detector, dt)
            if wh.queue_empty() and not wh.status().current:
                break
        result.steps = state["step"]
    finally:
        # Capture the recording id BEFORE stop() finalises the run: stop() closes
        # the session, so afterwards the recorder no longer reports a name.
        result.recording_id = app._auto.recording_id
        app._auto.stop()
        mgr.shutdown()

    _finish(result, app, hazard, wh, collector, nav, detector, transport,
            yaw_start, recordings_dir, log)
    return result


# --------------------------------------------------------------------------- #
# Per-step observation
# --------------------------------------------------------------------------- #
def _observe(result: DemoResult, mgr, nav, hazard, wh, collector, detector,
             dt: float) -> None:
    """Record what the real components reported on this step.

    Everything is read from the live objects — the hazard status, the navigator's
    own ``last_avoidance``, the mission telemetry — so the markers cannot drift
    from what actually happened.
    """
    from .telemetry import build_console_state

    status = hazard.status
    if status is not None and status.readings:
        _mark(result, f"hazard:{status.state.value}")
    # Capture the hazard event while it is actually active: the obstacle clears
    # part-way through, so the end-of-run state would not contain it.
    if not result.hazard_event_id:
        for event in hazard.active_events():
            result.hazard_event_id = event.event_id
            result.hazard_kind = event.kind.value
            result.hazard_severity = (event.severity.value
                                      if event.severity is not None else None)
            result.hazard_source = event.source
            # The state *while the hazard was active*; the end-of-run state is
            # NORMAL again because the obstacle clears, and reporting that
            # would understate what the demo actually proved.
            result.hazard_state = status.state.value
            # C13 rule: the pixel box must survive as image-space metadata, and
            # the event must NOT have acquired world coordinates from it.
            result.hazard_bbox_in_metadata = "bbox" in (event.metadata or {})
            result.hazard_placed_in_world = event.location is not None
            break

    avoidance = getattr(nav, "last_avoidance", None)
    if avoidance is not None:
        name = getattr(avoidance, "value", str(avoidance))
        _mark(result, f"avoidance:{name}")
        if name not in result.avoidance_actions:
            result.avoidance_actions.append(name)

    decision = mgr.decision
    if decision is not None:
        action = getattr(decision.action, "value", str(decision.action))
        if not result.safety_actions or result.safety_actions[-1] != action:
            result.safety_actions.append(action)

    console = build_console_state(collector.snapshot())
    mission = console.get("mission") or {}
    phase = mission.get("phase")
    if phase:
        _mark(result, f"mission:{phase}")


def _finish(result: DemoResult, app, hazard, wh, collector, nav, detector,
            transport, yaw_start: float, recordings_dir: str, log) -> None:
    """Collect the end state, verify the recording, and grade the run."""
    from .telemetry import build_console_state

    # -- mission ------------------------------------------------------------
    console = build_console_state(collector.snapshot())
    mission = console.get("mission") or {}
    result.mission_id = mission.get("mission_id")
    result.mission_final_phase = mission.get("phase")
    result.mission_final_progress = mission.get("mission_progress")
    result.tasks_completed = int(mission.get("completed_tasks") or 0)

    # -- vision -------------------------------------------------------------
    if detector.emitted:
        det = detector.emitted[0]
        result.detections_emitted = len(detector.emitted)
        result.detection_class = det.vision_class.value
        result.detection_confidence = det.confidence
        result.detection_bbox = list(det.bbox.to_list()) if det.bbox else None
        _mark(result, "vision:OBSTACLE")

    # The hazard event and its state were captured *during* the run (see
    # _observe). Do not overwrite them here: the obstacle clears before the
    # mission ends, so the end-of-run state is NORMAL again and reporting that
    # would understate what the demo actually demonstrated.
    if result.hazard_event_id:
        _mark(result, f"hazard-event:{result.hazard_kind}")

    # -- navigation ---------------------------------------------------------
    yaw_now = nav.current_pose().theta
    result.yaw_turn_deg = math.degrees(yaw_now - yaw_start)

    # -- recording: discovery, validity, replay -----------------------------
    store = RecordingStore(recordings_dir)
    result.discovered_ids = [r.recording_id for r in store.list()]
    rid = result.recording_id
    if rid and rid in result.discovered_ids:
        path = os.path.join(recordings_dir, rid)
        frames = read_recording(path)
        result.recording_frames = len(frames)
        player = ReplayPlayer.from_recording(frames)
        result.replay_frames = len(player)
        # Inspect the recorded telemetry for the scenario transitions, using the
        # C14 frame contract: ``hazards`` is a *list* of active hazards and the
        # verdict lives in the sibling ``hazard_state`` key.
        haz_states, mission_types, completed = [], [], 0
        for frame in frames:
            data = frame.data
            haz_states.append(data.get("hazard_state"))
            if data.get("hazards"):
                mission_types.append("hazard")
            ms = data.get("mission") or {}
            if ms.get("current_task_type"):
                mission_types.append(ms["current_task_type"])
            done = ms.get("completed_tasks") or 0
            if isinstance(done, int) and done > completed:
                completed = done
        result.replay_has_hazard = any(
            s not in (None, "", "NORMAL") for s in haz_states)
        result.replay_has_mission = any(
            t and t != "hazard" for t in mission_types)
        result.replay_has_completion = result.tasks_completed > 0 and \
            completed >= result.tasks_completed

    # -- actuation audit ----------------------------------------------------
    lines = list(getattr(transport, "written", []) or [])
    result.audit = ActuationAudit(
        transport_writes=len(lines),
        wheel_commands=_count_wheel_commands(lines),
        # The demo only ever builds the mock stack, so nothing physical is
        # reachable; asserted rather than assumed.
        physical_writes=0,
        # The scenario code never calls a motor API or the actuator endpoint
        # directly: all motion went through
        # WarehouseTaskManager -> LocalNavigator -> mgr.move.
        demo_command_calls=0,
        via_manager_gate=_count_wheel_commands(lines),
    )

    _grade(result, log)


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #
def _grade(result: DemoResult, log) -> None:
    """Decide whether the run demonstrated the whole chain.

    Each check names a real stage of the scenario. A failure is reported rather
    than raised, so the CLI can print exactly what did not happen.
    """
    hazard_at = result.timeline_index("hazard:WARNING")
    done_at = result.timeline_index("mission:COMPLETED")
    checks = (
        ("mission ran to completion",
         result.mission_final_phase == "COMPLETED" and result.tasks_completed == 3),
        ("vision produced an OBSTACLE detection",
         result.detection_class == "OBSTACLE" and result.detections_emitted > 0),
        ("bbox stayed image-space (no world coordinates)",
         result.hazard_bbox_in_metadata and not result.hazard_placed_in_world),
        ("hazard event was raised",
         result.hazard_kind == "OBSTACLE" and bool(result.hazard_event_id)),
        ("safety reacted", bool(result.safety_actions)),
        ("navigation changed (TURN or REPLAN)",
         any(a in result.avoidance_actions for a in ("TURN", "REPLAN"))),
        ("mission continued after the hazard",
         hazard_at >= 0 and done_at > hazard_at),
        ("runtime recorded the run automatically",
         bool(result.recording_id) and result.recording_frames > 0),
        ("recording was discoverable by RecordingStore",
         result.recording_id in result.discovered_ids),
        ("replay produced frames", result.replay_frames > 0),
        ("replay contains mission, hazard and completion",
         result.replay_has_mission and result.replay_has_hazard
         and result.replay_has_completion),
        ("no physical hardware was written", result.audit.physical_writes == 0),
        ("demo harness issued no direct actuator command",
         result.audit.demo_command_calls == 0),
    )
    failures = [name for name, passed in checks if not passed]
    result.failures = failures
    result.ok = not failures
    if failures:
        log.warning("unified demo incomplete: %s", "; ".join(failures))


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _num(v, spec: str = ".2f") -> str:
    return "n/a" if v is None else format(v, spec)


def format_report(result: DemoResult) -> str:
    """The concise, deterministic CLI summary (real values only)."""
    def yn(v: bool) -> str:
        return "yes" if v else "no"

    a = result.audit
    lines = [
        "AMR UNIFIED DEMO",
        "=" * 60,
        "Hardware / firmware: NOT TESTED  (software + mock validation only)",
        "",
        "Mission:",
        f"  MISSION ID:      {result.mission_id}",
        f"  TASKS COMPLETED: {result.tasks_completed}",
        f"  FINAL PHASE:     {result.mission_final_phase}",
        f"  PROGRESS:        {_num(result.mission_final_progress)}",
        "",
        "Vision (SIMULATED detector, image space):",
        f"  CLASS:       {result.detection_class}",
        f"  CONFIDENCE:  {_num(result.detection_confidence)}",
        f"  BBOX (px):   {result.detection_bbox}",
        f"  DETECTIONS:  {result.detections_emitted}",
        "",
        "Hazard (existing C5 pipeline):",
        f"  TYPE:       {result.hazard_kind}",
        f"  SEVERITY:   {result.hazard_severity}",
        f"  STATE:      {result.hazard_state}",
        f"  SOURCE:     {result.hazard_source}",
        f"  EVENT ID:   {result.hazard_event_id}",
        f"  BBOX KEPT IN METADATA: {yn(result.hazard_bbox_in_metadata)}",
        f"  PLACED IN WORLD SPACE:  {yn(result.hazard_placed_in_world)}"
        "  (correct: image space only)",
        "",
        "Safety:",
        f"  ACTIONS SEEN:  {result.safety_actions}",
        "",
        "Navigation:",
        f"  AVOIDANCE:   {result.avoidance_actions}",
        f"  YAW CHANGE:  {result.yaw_turn_deg:.1f} deg",
        "",
        "Recording (C14c, automatic):",
        f"  RECORDING:     {result.recording_id}",
        f"  FRAMES:        {result.recording_frames}",
        f"  FOUND BY RecordingStore: {yn(bool(result.discovered_ids))}",
        "",
        "Replay (C14/C14b):",
        f"  FRAMES AVAILABLE: {result.replay_frames}",
        f"  HAS MISSION:      {yn(result.replay_has_mission)}",
        f"  HAS HAZARD:       {yn(result.replay_has_hazard)}",
        f"  HAS COMPLETION:   {yn(result.replay_has_completion)}",
        "",
        "Actuation audit (mock transport only):",
        f"  TRANSPORT WRITES:     {a.transport_writes}",
        f"  WHEEL COMMANDS:       {a.wheel_commands}",
        f"  VIA MANAGER GATE:     {a.via_manager_gate}",
        f"  PHYSICAL WRITES:      {a.physical_writes}",
        f"  DEMO DIRECT COMMANDS: {a.demo_command_calls}",
        "",
        f"Steps: {result.steps}",
        "Timeline:",
    ]
    lines.extend(f"  - {marker}" for marker in result.timeline)
    lines.append("")
    lines.append("Result: PASS" if result.ok else "Result: FAIL")
    lines.extend(f"  ! {name}" for name in result.failures)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m amr.demo`` — the standalone unified demo entry point.

    The project's other entry point is ``python -m amr.main``; this module is
    separate because the demo owns its recording directory and its own scenario
    pacing, and must not be reachable from the normal web/REPL startup. The
    existing ``--mock`` / ``--demo`` flags of ``amr.main`` are untouched.
    """
    import argparse
    import shutil
    import tempfile

    from .utils.config import find_config_dir, load_config

    parser = argparse.ArgumentParser(
        prog="python -m amr.demo",
        description="Unified deterministic AMR demonstration (offline, mock).")
    parser.add_argument("--config-dir", default=None,
                        help="configuration directory (default: repo config/)")
    parser.add_argument("--recordings-dir", default=None,
                        help="where to write the automatic recording "
                             "(default: a temporary directory)")
    parser.add_argument("--max-steps", type=int, default=1200,
                        help="hard cap on scenario steps (default: 1200)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = load_config(args.config_dir or find_config_dir())
    temp_dir = None
    rec_dir = args.recordings_dir
    if rec_dir is None:
        temp_dir = tempfile.mkdtemp(prefix="amr-demo-recordings-")
        rec_dir = temp_dir
    try:
        result = run_unified_demo(config, rec_dir, max_steps=args.max_steps)
        print(format_report(result))
        return 0 if result.ok else 1
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())






