"""C14 — telemetry recording for offline replay.

A recorder is a *witness*, not a participant: it is handed snapshots that
already exist and writes them down. It never reads the robot, never steps a
tick, and has no path to a motor, GPIO or serial port. Recording must therefore
be safe to enable at any time — the worst a recording failure can do is lose
data.

Three properties this module deliberately borrows from the existing
:class:`~amr.hazard.event_log.HazardEventLog`, so the project has one
convention rather than two:

* **Bounded** — a fixed-capacity ring buffer, so a long-running robot cannot
  grow memory without limit (same reasoning as the rotating logger).
* **JSONL** — one JSON object per line, so a recording is readable without this
  Python package.
* **Best effort** — an unwritable path warns and continues, because a logging
  failure must never stop a run.

Frames are kept small and flat. Only the parts a replay actually needs are
stored — pose, navigation, safety, hazards, mission — rather than the whole
telemetry snapshot, so a long recording stays cheap to write and to replay.
"""

from __future__ import annotations

import json
import os
from collections import deque
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Tuple

from ..logging import get_logger

#: Recording format version. Bumped if the frame schema changes incompatibly.
RECORDING_SCHEMA_VERSION = "1.0"

#: Default retained frames. At 1 Hz this is ~16 minutes of run history.
DEFAULT_RECORDING_CAPACITY = 900

#: Ignore samples closer together than this, so a fast poll cannot fill the
#: buffer with near-duplicate frames. 0 disables the filter.
DEFAULT_MIN_INTERVAL_S = 0.5


def _num(value: Any) -> Optional[float]:
    """Finite float or ``None``; a recording must survive a broken sample."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return n


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    out = str(value).strip()
    return out or None


def _sub(snapshot: Mapping[str, Any], *keys: str) -> Dict[str, Any]:
    """Nested lookup returning ``{}`` rather than raising on a short snapshot."""
    node: Any = snapshot
    for key in keys:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key)
    return dict(node) if isinstance(node, Mapping) else {}


def _pose_of(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Flat world pose. Returns unknown keys as ``None``, never as 0.0."""
    pos = _sub(snapshot, "position")
    orient = _sub(snapshot, "orientation")
    return {
        "x": _num(pos.get("x")),
        "y": _num(pos.get("y")),
        "z": _num(pos.get("z")),
        "yaw": _num(orient.get("yaw")),
    }


class ReplayFrame:
    """One recorded instant: the minimum a replay needs to redraw the robot.

    Frames are plain dicts wrapped in a tiny reader so a recording stays
    trivially JSON-serialisable and the rest of the project can treat it as
    data. Unknown values stay ``None`` — a missing pose is reported as unknown,
    never smoothed to the origin.
    """

    __slots__ = ("data",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        self.data: Dict[str, Any] = dict(data)

    # -- accessors -------------------------------------------------------- #
    @property
    def timestamp(self) -> Optional[float]:
        return _num(self.data.get("timestamp"))

    @property
    def offset_s(self) -> float:
        """Seconds from the first frame. Always defined (0.0 for frame 0)."""
        value = _num(self.data.get("offset_s"))
        return 0.0 if value is None else value

    @property
    def pose(self) -> Dict[str, Any]:
        pose = self.data.get("pose")
        return dict(pose) if isinstance(pose, Mapping) else {}

    @property
    def navigation(self) -> Dict[str, Any]:
        nav = self.data.get("navigation")
        return dict(nav) if isinstance(nav, Mapping) else {}

    @property
    def safety(self) -> Dict[str, Any]:
        safety = self.data.get("safety")
        return dict(safety) if isinstance(safety, Mapping) else {}

    @property
    def hazards(self) -> List[Dict[str, Any]]:
        return [dict(h) for h in (self.data.get("hazards") or ())
                if isinstance(h, Mapping)]

    @property
    def mission(self) -> Dict[str, Any]:
        mission = self.data.get("mission")
        return dict(mission) if isinstance(mission, Mapping) else {}

    @property
    def safety_action(self) -> Optional[str]:
        return _text(self.safety.get("action"))

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.data)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ReplayFrame):
            return self.data == other.data
        return NotImplemented

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ReplayFrame(t={self.offset_s:.2f}s, pose={self.pose})"


def frame_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    first_timestamp: Optional[float] = None,
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """Build one storable frame from a C7 telemetry snapshot dict.

    :param first_timestamp: the recording's t0, used to compute ``offset_s``.
        When ``None`` the snapshot's own timestamp becomes t0.
    """
    wall = _num(snapshot.get("timestamp")) if timestamp is None else \
        _num(timestamp)
    t0 = _num(first_timestamp) if first_timestamp is not None else wall
    offset = None
    if wall is not None and t0 is not None:
        offset = max(0.0, wall - t0)

    nav = _sub(snapshot, "navigation")
    safety = _sub(snapshot, "safety")
    hazard = _sub(snapshot, "hazards")
    mission = _sub(snapshot, "mission")

    active: List[Dict[str, Any]] = []
    for h in (hazard.get("active") or ()):
        if not isinstance(h, Mapping):
            continue
        # Only the fields an operator sees in replay; the full event stays in
        # the hazard event log (C3), which is the audit record.
        active.append({
            "kind": _text(h.get("kind")),
            "severity": _text(h.get("severity")),
            "confidence": _num(h.get("confidence")),
            "source": _text(h.get("source")),
            "x": _num(h.get("x")),
            "y": _num(h.get("y")),
        })

    return {
        "schema_version": RECORDING_SCHEMA_VERSION,
        "timestamp": wall,
        "offset_s": offset,
        "pose": _pose_of(snapshot),
        "navigation": {
            "state": _text(nav.get("state")),
            "goal": _text(nav.get("goal")),
            "route_points": nav.get("route_points"),
        },
        "safety": {
            "state": _text(safety.get("state")),
            "action": _text(safety.get("action")),
            "emergency_stop": bool(safety.get("emergency_stop")),
        },
        "hazards": active,
        "hazard_state": _text(hazard.get("state")),
        "mission": {
            "mission_id": _text(mission.get("mission_id")),
            "current_task": _text(mission.get("current_task")),
            "current_task_type": _text(mission.get("current_task_type")),
            "current_task_status": _text(mission.get("current_task_status")),
            "completed_tasks": mission.get("completed_tasks"),
        },
    }


class TelemetryRecorder:
    """Bounded, append-only recorder of replay frames.

    Feed it C7 telemetry snapshot dicts (:meth:`record`) as often as you like;
    it keeps the newest :attr:`capacity` frames and, if a ``path`` is given,
    appends each accepted frame to a JSONL file.

    A recorder is a witness. It never pulls state out of the robot, so enabling
    one cannot change robot behaviour — there is no control path in this class.
    """

    def __init__(
        self,
        capacity: int = DEFAULT_RECORDING_CAPACITY,
        path: Optional[str] = None,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = int(capacity)
        self._frames: Deque[Dict[str, Any]] = deque(maxlen=self._capacity)
        self._path = path
        self._min_interval = max(0.0, float(min_interval_s))
        self._last_wall: Optional[float] = None
        self._t0: Optional[float] = None
        self._dropped = 0
        self._persist_failures = 0
        self.log = get_logger("telemetry.recorder")

    # -- introspection ---------------------------------------------------- #
    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def dropped(self) -> int:
        """Samples skipped by the min-interval filter (not by capacity)."""
        return self._dropped

    def __len__(self) -> int:
        return len(self._frames)

    def frames(self) -> Tuple[ReplayFrame, ...]:
        """Recorded frames, oldest first."""
        return tuple(ReplayFrame(f) for f in self._frames)

    def duration_s(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return float(self._frames[-1].get("offset_s") or 0.0) - \
            float(self._frames[0].get("offset_s") or 0.0)

    # -- recording -------------------------------------------------------- #
    def record(
        self,
        snapshot: Any,
        *,
        timestamp: Optional[float] = None,
    ) -> Optional[ReplayFrame]:
        """Record one telemetry snapshot; returns the stored frame or ``None``.

        ``snapshot`` may be a C7 ``TelemetrySnapshot`` or the plain dict from
        ``collect().to_dict()``. Returns ``None`` when the sample was skipped by
        the min-interval filter.
        """
        data = snapshot if isinstance(snapshot, Mapping) else _snapshot_dict(
            snapshot)
        if data is None:
            return None
        wall = _num(data.get("timestamp")) if timestamp is None else \
            _num(timestamp)
        if wall is None:
            # A frame with no time cannot be placed on a timeline; skipping it
            # is better than recording one that replays at the wrong moment.
            self._dropped += 1
            return None
        if (self._min_interval and self._last_wall is not None
                and wall - self._last_wall < self._min_interval):
            self._dropped += 1
            return None

        frame = frame_from_snapshot(data, first_timestamp=self._t0,
                                    timestamp=wall)
        if self._t0 is None:
            self._t0 = wall
            frame["offset_s"] = 0.0
        self._frames.append(frame)
        self._last_wall = wall
        self._persist(frame)
        return ReplayFrame(frame)

    def clear(self) -> None:
        """Drop in-memory frames and reset t0. Does not touch the JSONL file."""
        self._frames.clear()
        self._last_wall = None
        self._t0 = None
        self._dropped = 0

    # -- persistence (best effort, never raises) -------------------------- #
    def _persist(self, frame: Mapping[str, Any]) -> None:
        if not self._path:
            return
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(frame, sort_keys=True) + "\n")
        except OSError as exc:  # pragma: no cover - environment dependent
            # A recording failure must never stop a run; warn once per burst.
            self._persist_failures += 1
            if self._persist_failures <= 3:
                self.log.warning("telemetry recording write failed: %s", exc)


def _snapshot_dict(snapshot: Any) -> Optional[Dict[str, Any]]:
    """Best-effort conversion of a snapshot object to a dict."""
    for attr in ("to_dict", "snapshot", "collect"):
        fn = getattr(snapshot, attr, None)
        if callable(fn):
            try:
                got = fn()
            except Exception:  # noqa: BLE001
                return None
            return dict(got) if isinstance(got, Mapping) else None
    return dict(snapshot) if isinstance(snapshot, Mapping) else None


def read_recording(path: str) -> Tuple[ReplayFrame, ...]:
    """Load a JSONL recording, skipping any unreadable line.

    A corrupt line is dropped rather than aborting the load: a partially
    written last line (common when a run is interrupted) should not make the
    whole recording unplayable.
    """
    frames: List[ReplayFrame] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(data, Mapping):
                frames.append(ReplayFrame(data))
    return tuple(frames)


