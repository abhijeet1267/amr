"""C15 — automatic telemetry recording for the running web runtime.

C14 built the recorder, C14b the dashboard controls; the missing link was that
nothing *recorded* during a live run. This module closes that loop without
adding anything to the runtime's timing:

* :class:`AutoRecorder` owns one :class:`~amr.telemetry.recorder.TelemetryRecorder`
  for the lifetime of a session, and gives it a deterministic, collision-free
  name inside the directory the C14b :class:`RecordingStore` already reads.
* It has **no clock, no thread and no timer**. The web runtime calls
  :meth:`record` from the control loop it already runs, passing the same
  :class:`~amr.telemetry.collector.TelemetryCollector` the dashboard reads. One
  collection path feeds both live telemetry and the recording.

Recording is a *witness*. It never commands anything, and a recording failure is
contained: :meth:`record` returns a bool and never raises, so a full disk cannot
stop the control loop.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from ..logging import get_logger
from .recorder import (
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_RECORDING_CAPACITY,
    TelemetryRecorder,
)

#: Name template for an automatic run. Deliberately sortable and free of any
#: character that could be unsafe in a filename or a URL.
NAME_TEMPLATE = "run-{stamp}.jsonl"

#: How many suffixed attempts to make before giving up on naming a run.
MAX_NAME_ATTEMPTS = 100


def recording_name(when: float, suffix: int = 0) -> str:
    """Deterministic recording id for a wall-clock instant.

    ``suffix`` disambiguates two runs started in the same second, so a second
    run never overwrites the first.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(float(when)))
    name = NAME_TEMPLATE.format(stamp=stamp)
    if suffix > 0:
        name = name[:-len(".jsonl")] + f"-{suffix + 1}.jsonl"
    return name


class AutoRecorder:
    """One recording session, owned by the web runtime.

    :param directory: where to write. Must already be the directory the
        ``RecordingStore`` reads, so a recording written here is immediately
        discoverable by ``GET /replay/recordings``.
    :param capacity: in-memory frame ring size.
    :param min_interval_s: C14 throttle, so the control-loop cadence cannot
        flood the file.
    :param clock: injectable, so tests can be deterministic.
    """

    def __init__(
        self,
        directory: Optional[str] = None,
        *,
        enabled: bool = True,
        capacity: int = DEFAULT_RECORDING_CAPACITY,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        clock=time.time,
    ) -> None:
        self._dir = directory
        self._enabled = bool(enabled)
        self._clock = clock
        self._capacity = int(capacity)
        self._min_interval = float(min_interval_s)
        self._recorder: Optional[TelemetryRecorder] = None
        self._name: Optional[str] = None
        self._path: Optional[str] = None
        self._started_at: Optional[float] = None
        self._stopped_at: Optional[float] = None
        self._failures = 0
        self.log = get_logger("telemetry.autorecord")

    # -- lifecycle --------------------------------------------------------- #
    @property
    def available(self) -> bool:
        """A session can start only if recording is enabled *and* the dir exists.

        With no directory configured — the shipped default — this is False and
        nothing is ever written, which is the safe default for a reporting
        feature.
        """
        return (self._enabled and bool(self._dir)
                and os.path.isdir(self._dir or ""))

    @property
    def active(self) -> bool:
        return self._recorder is not None

    @property
    def recording_id(self) -> Optional[str]:
        return self._name

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def started_at(self) -> Optional[float]:
        return self._started_at

    @property
    def failures(self) -> int:
        """Recording errors contained so far."""
        return self._failures

    def start(self) -> Optional[str]:
        """Begin a recording; returns its id, or ``None`` if unavailable.

        Idempotent: starting an already-running session is a no-op, so a
        repeated ``start()`` cannot produce a second, overlapping recording.
        """
        if self.active:
            return self._name
        if not self.available:
            return None
        try:
            name, path = self._allocate()
        except OSError as exc:
            self._failures += 1
            self.log.warning("recording start failed: %s", exc)
            return None
        if path is None:
            return None
        self._recorder = TelemetryRecorder(capacity=self._capacity,
                                           path=path,
                                           min_interval_s=self._min_interval)
        self._name = name
        self._path = path
        self._started_at = self._clock()
        self.log.info("recording to %s", path)
        return name

    def _allocate(self):
        """First free name in the directory — never silently overwriting."""
        for suffix in range(MAX_NAME_ATTEMPTS):
            name = recording_name(self._clock(), suffix)
            path = os.path.join(self._dir or "", name)
            if not os.path.exists(path):
                return name, path
        return None, None

    def record(self, snapshot: Any) -> bool:
        """Record one telemetry snapshot. Never raises.

        Returns ``True`` when a frame was stored, ``False`` when it was skipped
        (throttled, or no usable timestamp) or the write failed. A failure here
        must not disturb the caller, so it is counted and logged, not raised.
        """
        if self._recorder is None:
            return False
        try:
            return self._recorder.record(snapshot) is not None
        except Exception as exc:  # noqa: BLE001 - recording is optional
            self._failures += 1
            self.log.warning("recording frame failed: %s", exc)
            return False

    def stop(self) -> Optional[Dict[str, Any]]:
        """Finish the session and return its summary. Idempotent.

        The C14 recorder opens and closes the file on every write, so nothing is
        left buffered; closing the recorder simply makes it inert, so a late
        tick cannot append to a finished run.
        """
        if self._recorder is None:
            return None
        recorder, self._recorder = self._recorder, None
        try:
            recorder.close()
        except Exception as exc:  # noqa: BLE001
            self._failures += 1
            self.log.warning("recording close failed: %s", exc)
        self._stopped_at = self._clock()
        summary = {
            "recording_id": self._name,
            "frames": len(recorder),
            "dropped": recorder.dropped,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "path": self._path,
        }
        self._name = None
        self._path = None
        self._started_at = None
        return summary

    # -- reporting --------------------------------------------------------- #
    def status(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "active": self.active,
            "recording_id": self._name,
            "frames": len(self._recorder) if self._recorder else 0,
            "dropped": self._recorder.dropped if self._recorder else 0,
            "failures": self._failures,
        }
