"""C14 — deterministic replay of a recorded run.

The player is deliberately **caller-driven**: it has no thread, no ``sleep`` and
no internal clock. You hand it elapsed time via :meth:`ReplayPlayer.advance` and
it tells you which frame should be on screen. That is what makes a replay
reproducible — feed the same ``advance`` sequence twice and you get the same
frames twice — and it is why the whole engine is testable in milliseconds with
no real time passing.

The same property is why the future dashboard controls are a separate step: a
browser loop already owns its timer, so it can drive this directly instead of
starting a second one.

The player is read-only with respect to the robot: it holds a list of dicts and
has no reference to a manager, navigator, motor driver or serial port.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Sequence, Tuple

from .recorder import ReplayFrame

#: Speeds the future dashboard control exposes. Any positive float also works.
STANDARD_SPEEDS: Tuple[float, ...] = (0.5, 1.0, 2.0)


class ReplayState(str, Enum):
    """Playback state. ``STOPPED`` means the end of the recording was reached."""

    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"

    def __str__(self) -> str:  # pragma: no cover - display convenience
        return self.value


class ReplayPlayer:
    """Plays a recorded run forward at a chosen speed.

    :param frames: the recording, oldest first.
    """

    def __init__(self, frames: Sequence[ReplayFrame] = ()) -> None:
        self._frames: Tuple[ReplayFrame, ...] = tuple(frames)
        self._index = 0
        self._state = ReplayState.STOPPED if not self._frames \
            else ReplayState.PAUSED
        self._speed = 1.0
        # Virtual playback clock, in recording-seconds. Never the wall clock.
        self._clock = self._frames[0].offset_s if self._frames else 0.0

    @classmethod
    def from_recording(cls, frames: Sequence[ReplayFrame]) -> "ReplayPlayer":
        return cls(frames)

    # -- introspection ----------------------------------------------------- #
    def __len__(self) -> int:
        return len(self._frames)

    @property
    def frames(self) -> Tuple[ReplayFrame, ...]:
        return self._frames

    @property
    def state(self) -> ReplayState:
        return self._state

    @property
    def index(self) -> int:
        """Index of the frame currently on screen."""
        return self._index

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        try:
            speed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("speed must be a number") from exc
        if not (speed > 0) or speed != speed:
            # Refusing a non-positive speed is what keeps "play" from silently
            # meaning "rewind"; a UI can offer 0.5x/1x/2x, the API allows more.
            raise ValueError("speed must be > 0")
        self._speed = speed

    @property
    def current(self) -> Optional[ReplayFrame]:
        if not self._frames:
            return None
        return self._frames[self._index]

    @property
    def progress(self) -> float:
        """Fraction of the recording played, 0.0 .. 1.0.

        ``0.0`` for an empty recording rather than a division by zero.
        """
        if not self._frames:
            return 0.0
        if len(self._frames) == 1:
            return 1.0
        return self._index / (len(self._frames) - 1)

    @property
    def duration_s(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return self._frames[-1].offset_s - self._frames[0].offset_s

    @property
    def elapsed_s(self) -> float:
        """Recording-time position, which is what speed scales."""
        return self._clock

    # -- transport --------------------------------------------------------- #
    def play(self) -> None:
        if not self._frames:
            return
        if self._state is ReplayState.STOPPED:
            # Pressing play at the end restarts, matching every media player.
            self._index = 0
            self._clock = self._frames[0].offset_s
        self._state = ReplayState.PLAYING

    def pause(self) -> None:
        if self._state is ReplayState.PLAYING:
            self._state = ReplayState.PAUSED

    def toggle(self) -> ReplayState:
        if self._state is ReplayState.PLAYING:
            self.pause()
        else:
            self.play()
        return self._state

    def restart(self) -> None:
        """Back to the first frame, paused. Playback does not auto-resume."""
        self._index = 0
        self._clock = self._frames[0].offset_s if self._frames else 0.0
        self._state = ReplayState.PAUSED if self._frames \
            else ReplayState.STOPPED

    def stop(self) -> None:
        self.restart()
        self._state = ReplayState.STOPPED

    def seek(self, index: int) -> None:
        """Jump to a frame index (clamped). A pure lookup: no time passes."""
        if not self._frames:
            self._index = 0
            return
        idx = max(0, min(len(self._frames) - 1, int(index)))
        self._index = idx
        self._clock = self._frames[idx].offset_s
        if idx >= len(self._frames) - 1 and self._state is ReplayState.PLAYING:
            self._state = ReplayState.STOPPED

    def seek_seconds(self, offset: float) -> None:
        """Jump to the latest frame at or before ``offset`` seconds."""
        if not self._frames:
            return
        target = self._frames[0].offset_s + max(0.0, float(offset))
        self.seek(self._index_for_clock(target))

    # -- the deterministic tick ------------------------------------------- #
    def advance(self, wall_dt: float) -> Optional[ReplayFrame]:
        """Advance the virtual clock by ``wall_dt`` **seconds** of real time.

        Returns the frame that should now be displayed, or ``None`` if the
        recording has no frames. The caller supplies ``wall_dt``, so the same
        sequence of calls always yields the same sequence of frames.

        A paused player does not move. A player that reaches the end reports
        :attr:`ReplayState.STOPPED` and holds the last frame rather than
        wrapping around, because a replay that silently loops is surprising.
        """
        if not self._frames:
            return None
        if self._state is not ReplayState.PLAYING:
            return self.current
        try:
            dt = float(wall_dt)
        except (TypeError, ValueError):
            return self.current
        if dt < 0:
            # Negative elapsed time is a clock glitch, not a rewind request.
            return self.current
        # Speed scales how fast recording-time passes.
        self._clock += dt * self._speed
        self._index = self._index_for_clock(self._clock)
        if self._index >= len(self._frames) - 1:
            self._clock = self._frames[-1].offset_s
            self._state = ReplayState.STOPPED
        return self.current

    def _index_for_clock(self, clock: float) -> int:
        """Index of the latest frame at or before ``clock``.

        Linear rather than binary because recordings are short (bounded
        buffer) and this keeps tie-breaking exact: a frame at exactly ``t`` is
        still on screen until the clock passes it.
        """
        idx = 0
        for i, frame in enumerate(self._frames):
            if frame.offset_s <= clock:
                idx = i
            else:
                break
        return idx

    # -- reporting --------------------------------------------------------- #
    def status(self) -> Dict[str, Any]:
        """A compact status dict for a future UI. Read-only, no robot input."""
        return {
            "state": self._state.value,
            "index": self._index,
            "frames": len(self._frames),
            "progress": self.progress,
            "speed": self._speed,
            "elapsed_s": self._clock,
            "duration_s": self.duration_s,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"ReplayPlayer({self._state.value} "
                f"{self._index + 1}/{len(self._frames)} @ {self._speed}x)")
