"""C14b — recording discovery and dashboard replay control (read-only).

Two things live here, and neither can touch a robot:

* :class:`RecordingStore` — discovery and validated loading of the JSONL files
  the C14 :class:`~amr.telemetry.recorder.TelemetryRecorder` writes.
* :class:`ReplayController` — owns replay *state* (which recording, playing or
  not, speed) and holds one :class:`~amr.telemetry.replay.ReplayPlayer`.

The controller does **not** own a clock. The dashboard's existing 1 Hz loop calls
:meth:`ReplayController.tick` with the elapsed time it already measured, and the
C14 player does the rest. That is the whole point of C14's caller-driven design:
replay adds no thread, no timer and no second update cycle.

Paths are never taken from the client. A request names a ``recording_id``, which
is resolved against the configured recordings directory and validated; a name
containing a separator, ``..`` or an absolute path is refused.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..logging import get_logger
from .recorder import ReplayFrame, read_recording
from .replay import STANDARD_SPEEDS, ReplayPlayer, ReplayState

#: Suffix of a recording file, matching the C14 recorder's JSONL output.
RECORDING_SUFFIX = ".jsonl"


class DashboardReplayState(str, Enum):
    """Replay state as the dashboard presents it.

    ``NO_RECORDING`` is the idle default; ``READY`` means a recording is loaded
    and paused at the start.
    """

    NO_RECORDING = "no_recording"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"

    def __str__(self) -> str:  # pragma: no cover - display convenience
        return self.value


def is_valid_recording_id(name: Any) -> bool:
    """True when ``name`` is a plain filename inside the recordings directory.

    Rejects anything that could escape it: separators, ``..``, absolute paths,
    NUL, hidden files and non-strings. The rule is deliberately strict — a
    recording id is a name, never a path.
    """
    if not isinstance(name, str) or not name or len(name) > 255:
        return False
    if name in (".", "..") or name.startswith("."):
        return False
    if "/" in name or "\\" in name or os.sep in name:
        return False
    if os.altsep and os.altsep in name:
        return False
    if "\x00" in name or os.path.isabs(name):
        return False
    return name.endswith(RECORDING_SUFFIX)


@dataclass
class RecordingInfo:
    """Metadata for one discoverable recording. Metadata only, never frames."""

    recording_id: str
    size_bytes: int
    modified: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recording_id": self.recording_id,
            "size_bytes": self.size_bytes,
            "modified": self.modified,
        }


class RecordingStore:
    """Read-only view of one directory of C14 recordings.

    Discovery is a cheap ``listdir`` — the dashboard calls it on demand, not on
    every 1 Hz tick, so a large directory is never re-scanned per second.
    """

    def __init__(self, directory: Optional[str]) -> None:
        self._dir = directory

    @property
    def directory(self) -> Optional[str]:
        return self._dir

    @property
    def available(self) -> bool:
        return bool(self._dir) and os.path.isdir(self._dir or "")

    def list(self) -> Tuple[RecordingInfo, ...]:
        """Available recordings, newest first, deterministic for equal mtimes."""
        if not self.available:
            return ()
        try:
            names = os.listdir(self._dir or "")
        except OSError:
            return ()
        found: List[RecordingInfo] = []
        for name in names:
            if not is_valid_recording_id(name):
                continue
            full = os.path.join(self._dir or "", name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            if not os.path.isfile(full):
                continue
            found.append(RecordingInfo(name, int(stat.st_size),
                                       float(stat.st_mtime)))
        # Newest first; the id breaks ties so the order never depends on the
        # filesystem's own ordering.
        found.sort(key=lambda r: (-r.modified, r.recording_id))
        return tuple(found)

    def resolve(self, recording_id: Any) -> Optional[str]:
        """Absolute path for a validated id, or ``None`` if it is not usable.

        The id is checked, then the file must actually exist in the directory —
        so a crafted id cannot be used to read something else off disk.
        """
        if not self.available or not is_valid_recording_id(recording_id):
            return None
        full = os.path.join(self._dir or "", recording_id)
        # Belt and braces: the joined path must still sit in the directory.
        root = os.path.abspath(self._dir or "")
        if os.path.dirname(os.path.abspath(full)) != root:
            return None
        return full if os.path.isfile(full) else None

    def load(self, recording_id: Any) -> Tuple[ReplayFrame, ...]:
        """Load frames, or an empty tuple when the recording is unusable."""
        full = self.resolve(recording_id)
        if full is None:
            return ()
        try:
            return read_recording(full)
        except (OSError, ValueError):
            # A corrupt recording is reported as "nothing loaded" rather than
            # crashing the dashboard.
            return ()


class ReplayController:
    """Replay state for the dashboard. No clock, no thread, no robot access.

    The dashboard calls :meth:`tick` from the loop it already runs, passing the
    elapsed time it measured. While a recording is playing, that advances the
    C14 :class:`ReplayPlayer`; when it is not, the controller does nothing, so
    the live data path is completely unaffected.
    """

    def __init__(self, store: Optional[RecordingStore] = None) -> None:
        self._store = store or RecordingStore(None)
        self._player: Optional[ReplayPlayer] = None
        self._state = DashboardReplayState.NO_RECORDING
        self._recording_id: Optional[str] = None
        self._error: Optional[str] = None
        self.log = get_logger("telemetry.replay")

    # -- introspection ----------------------------------------------------- #
    @property
    def state(self) -> DashboardReplayState:
        return self._state

    @property
    def recording_id(self) -> Optional[str]:
        return self._recording_id

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def player(self) -> Optional[ReplayPlayer]:
        return self._player

    @property
    def active(self) -> bool:
        """True when replay data should be shown instead of live telemetry."""
        return self._state in (DashboardReplayState.PLAYING,
                               DashboardReplayState.PAUSED,
                               DashboardReplayState.READY,
                               DashboardReplayState.FINISHED)

    def recordings(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._store.list()]

    # -- discovery / load -------------------------------------------------- #
    def load(self, recording_id: Any) -> DashboardReplayState:
        """Load a recording by id. Invalid or missing ids change nothing else."""
        self._error = None
        if not self._store.available:
            self._state = DashboardReplayState.ERROR
            self._error = "no recordings directory configured"
            return self._state
        if not is_valid_recording_id(recording_id):
            self._state = DashboardReplayState.ERROR
            self._error = "invalid recording id"
            return self._state
        frames = self._store.load(recording_id)
        if not frames:
            self._state = DashboardReplayState.ERROR
            self._error = f"recording not found or empty: {recording_id}"
            return self._state
        self._player = ReplayPlayer(frames)
        self._recording_id = recording_id
        self._state = DashboardReplayState.READY
        return self._state

    def unload(self) -> DashboardReplayState:
        self._player = None
        self._recording_id = None
        self._error = None
        self._state = DashboardReplayState.NO_RECORDING
        return self._state

    # -- transport --------------------------------------------------------- #
    def play(self) -> DashboardReplayState:
        if self._player is None:
            return self._state
        # A finished recording restarts rather than doing nothing, matching
        # every media player.
        self._player.play()
        self._state = (DashboardReplayState.FINISHED
                       if self._player.state is ReplayState.STOPPED
                       else DashboardReplayState.PLAYING)
        return self._state

    def pause(self) -> DashboardReplayState:
        if self._player is None:
            return self._state
        self._player.pause()
        # Pausing keeps the current frame and position; it must not unload.
        if self._state is DashboardReplayState.PLAYING:
            self._state = DashboardReplayState.PAUSED
        return self._state

    def restart(self) -> DashboardReplayState:
        if self._player is None:
            return self._state
        self._player.restart()
        self._state = DashboardReplayState.PAUSED
        return self._state

    def set_speed(self, speed: Any) -> DashboardReplayState:
        """Set playback speed. Only strictly positive values are accepted."""
        if self._player is None:
            return self._state
        try:
            self._player.speed = speed
        except (ValueError, TypeError):
            self._error = "invalid speed"
            return self._state
        return self._state

    # -- the tick, driven by the dashboard's existing loop ----------------- #
    def tick(self, dt: float) -> Optional[ReplayFrame]:
        """Advance replay by ``dt`` seconds of elapsed time.

        Returns the frame that should now be displayed, or ``None`` when replay
        is not loaded. Called from the loop the dashboard already runs, so this
        adds no timer of its own. While not playing, the player is not touched
        at all and the live data path is untouched.
        """
        if self._player is None or self._state is not \
                DashboardReplayState.PLAYING:
            return None
        try:
            frame = self._player.advance(dt)
        except (ValueError, TypeError):
            return self._player.current if self._player else None
        # Mirror the player's own end-of-recording stop.
        if self._player.state is ReplayState.STOPPED:
            self._state = DashboardReplayState.FINISHED
        return frame

    # -- reporting --------------------------------------------------------- #
    def status(self) -> Dict[str, Any]:
        """Compact status for the dashboard. Read-only; no robot state."""
        out: Dict[str, Any] = {
            "state": self._state.value,
            "active": self.active,
            "recording_id": self._recording_id,
            "error": self._error,
            "speeds": list(STANDARD_SPEEDS),
            "recordings_available": self._store.available,
        }
        if self._player is None:
            out.update({"speed": None, "index": None, "frames": 0,
                        "progress": 0.0, "elapsed_s": 0.0, "duration_s": 0.0})
            return out
        out.update({
            "speed": self._player.speed,
            "index": self._player.index,
            "frames": len(self._player),
            "progress": self._player.progress,
            "elapsed_s": self._player.elapsed_s,
            "duration_s": self._player.duration_s,
        })
        return out

    def current_frame(self) -> Optional[Dict[str, Any]]:
        """The frame the dashboard should render, or ``None`` for live mode."""
        if self._player is None:
            return None
        frame = self._player.current
        return frame.to_dict() if frame is not None else None
