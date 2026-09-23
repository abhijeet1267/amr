"""Bounded, append-only hazard event log.

Records every :class:`~amr.hazard.types.HazardEvent` the hazard layer raises so
hazards are *auditable*, not just acted upon. Two properties matter:

* **Bounded** — a fixed-capacity ring buffer, so a long-running robot can never
  grow memory without limit (the same reasoning as the rotating logger in
  :mod:`amr.logging.logger`).
* **Exportable** — an optional JSONL file (one JSON object per line) makes the
  history consumable by a future dashboard / spatial hazard visualisation
  without the reader needing this Python package.

Persistence is deliberately **best effort**: an unwritable path logs a warning
and never raises, because a logging failure must not stop the safety loop.
"""

from __future__ import annotations

import json
import os
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from ..logging import get_logger
from .types import HazardEvent

#: Default number of events retained in memory.
DEFAULT_CAPACITY = 256


class HazardEventLog:
    """A bounded, ordered history of hazard events (newest last)."""

    def __init__(
        self,
        capacity: int = DEFAULT_CAPACITY,
        path: Optional[str] = None,
    ):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = int(capacity)
        self._events: Deque[HazardEvent] = deque(maxlen=self._capacity)
        self._path = path
        self._persist_failures = 0
        self.log = get_logger("hazard.log")

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def path(self) -> Optional[str]:
        return self._path

    def __len__(self) -> int:
        return len(self._events)

    def history(self) -> Tuple[HazardEvent, ...]:
        """All retained events, oldest first."""
        return tuple(self._events)

    def recent(self, count: Optional[int] = None) -> Tuple[HazardEvent, ...]:
        """The ``count`` most recent events (newest last); all when ``None``."""
        if count is None or count >= len(self._events):
            return tuple(self._events)
        if count <= 0:
            return ()
        return tuple(list(self._events)[-count:])

    def active(self) -> Tuple[HazardEvent, ...]:
        """Events that have not been cleared, oldest first."""
        return tuple(e for e in self._events if not e.resolved)

    def counts_by_kind(self) -> Dict[str, int]:
        """How many retained events were recorded per :class:`HazardKind`."""
        counts: Dict[str, int] = {}
        for event in self._events:
            key = event.kind.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #
    def record(self, event: HazardEvent) -> HazardEvent:
        """Append a newly raised event and return it."""
        self._events.append(event)
        self.log.warning("HAZARD %s %s", event.state.value, event.message)
        self._persist(event)
        return event

    def replace(self, event: HazardEvent) -> bool:
        """Swap in an updated copy of an existing event (matched by id).

        Used when an ongoing hazard escalates or is resolved. Returns ``False``
        when the id is unknown (e.g. it has already aged out of the ring).
        """
        for index, existing in enumerate(self._events):
            if existing.event_id == event.event_id:
                self._events[index] = event
                self._persist(event)
                return True
        return False

    def resolve(self, event_id: str, cleared_at: Optional[float] = None) -> bool:
        """Mark one event cleared by id. Returns ``True`` when found."""
        for event in self._events:
            if event.event_id == event_id:
                return self.replace(event.resolved_with(cleared_at))
        return False

    def resolve_all(self, cleared_at: Optional[float] = None) -> int:
        """Mark every open event cleared; returns how many were cleared."""
        cleared = 0
        for event in list(self._events):
            if not event.resolved:
                if self.resolve(event.event_id, cleared_at):
                    cleared += 1
        return cleared

    def clear(self) -> None:
        """Drop all retained events (does not touch the export file)."""
        self._events.clear()

    # ------------------------------------------------------------------ #
    # Persistence (best effort — never raises)
    # ------------------------------------------------------------------ #
    def _persist(self, event: HazardEvent) -> None:
        if not self._path:
            return
        try:
            directory = os.path.dirname(os.path.abspath(self._path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        except OSError as exc:  # pragma: no cover - filesystem dependent
            self._persist_failures += 1
            # Warn once per failure burst, not once per event.
            if self._persist_failures == 1:
                self.log.warning(
                    "could not persist hazard events to %s: %s", self._path, exc
                )


def read_events(path: str) -> Tuple[Dict[str, Any], ...]:
    """Read a JSONL hazard-event export back into plain dicts.

    The read side of :meth:`HazardEventLog._persist`, for a dashboard or the
    future spatial hazard visualisation. Malformed lines are skipped rather than
    raising, so a partially written file is still readable.
    """
    if not os.path.isfile(path):
        return ()
    events: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    events.append(parsed)
    except OSError:  # pragma: no cover - filesystem dependent
        return ()
    return tuple(events)
