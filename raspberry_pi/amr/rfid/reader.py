"""RFID shelf / payload identification (C17).

A warehouse AMR has to know *what* it is standing in front of before it acts:
picking the wrong box is worse than refusing to pick. RFID is the cheap way to
ask the shelf directly instead of trusting dead reckoning.

Every reader satisfies the tiny :class:`RfidReader` protocol::

    class RfidReader(Protocol):
        name: str
        def inventory(self) -> Tuple[RfidTag, ...]: ...

Readers are **thin and dependency-injected**, the same philosophy as
``amr/hazard/sources.py``: a reader wraps a callable supplied by the caller (on
real hardware, a serial / SPI inventory call) rather than talking to a bus
itself. Nothing in this module touches hardware, so the whole identification
path is testable with no reader attached.

No reader is attached by default
--------------------------------
``rfid.backend: "null"`` (the default) makes :func:`make_rfid_reader` return
``None``. No identification is then attempted and nothing is claimed, so adding
this module cannot change the behaviour of an existing deployment until an
operator opts in.

An empty inventory is not a pass
--------------------------------
``inventory()`` returning an empty tuple means "I could not confirm this
shelf", which the task manager treats as an identification *failure*. That is
the same distinction the hazard layer draws between "the air is clean" and "the
gas sensor is not answering" — silence must not read as confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)


class RfidTagKind(str, Enum):
    """What a tag is attached to."""

    LOCATION = "location"   # mounted on a shelf / station: identifies the place
    PAYLOAD = "payload"     # attached to an item: identifies what is here


@dataclass(frozen=True)
class RfidTag:
    """One physical tag.

    ``tag_id`` is the tag's own identity (an EPC on real hardware). ``ref`` is
    the application-level thing it identifies: the map location name for a
    :attr:`RfidTagKind.LOCATION` tag, the payload id for a
    :attr:`RfidTagKind.PAYLOAD` tag.
    """

    tag_id: str
    kind: RfidTagKind
    ref: str

    def to_dict(self) -> dict:
        return {"tag_id": self.tag_id, "kind": self.kind.value, "ref": self.ref}


@runtime_checkable
class RfidReader(Protocol):
    """Structural interface every reader must satisfy."""

    name: str

    def inventory(self) -> Tuple[RfidTag, ...]:
        """Tags currently within range of the antenna (empty when none)."""
        ...


def confirm(
    tags: Iterable[RfidTag],
    location: str,
    payload_id: Optional[str] = None,
) -> Optional[str]:
    """Check an inventory against what the robot expects to be standing at.

    Returns ``None`` when the inventory confirms ``location`` (and, when given,
    that ``payload_id`` is present too), otherwise a human-readable reason.

    Pure and reader-independent on purpose: the identification rule is worth
    testing on its own, and keeping it out of the reader means a real backend
    cannot quietly disagree with the rule the tests pin.
    """
    tags = tuple(tags)
    located = {t.ref for t in tags if t.kind is RfidTagKind.LOCATION}
    if location not in located:
        return (
            f"rfid: no location tag for {location!r} in range "
            f"(read {_describe(tags)})"
        )
    if payload_id is not None:
        present = {t.ref for t in tags if t.kind is RfidTagKind.PAYLOAD}
        if payload_id not in present:
            return (
                f"rfid: no payload tag for {payload_id!r} at {location!r} "
                f"(read {_describe(tags)})"
            )
    return None


def _describe(tags: Sequence[RfidTag]) -> str:
    """A short, honest rendering of an inventory for an error message."""
    if not tags:
        return "nothing"
    return ", ".join(sorted(t.tag_id for t in tags))


class SimulatedRfidReader:
    """Deterministic reader: the tags mounted at the robot's own location.

    The antenna travels with the robot, so what it can read depends on where
    the robot is parked. ``location_provider`` answers that question — a
    callable returning a location name, or ``None`` when the robot's position is
    not known. Nothing is guessed: an unknown location reads an *empty*
    inventory, which callers must treat as "not confirmed" rather than as
    "confirmed absent".
    """

    def __init__(
        self,
        tags: Mapping[str, Sequence[RfidTag]],
        location_provider: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self._tags: Dict[str, Tuple[RfidTag, ...]] = {
            str(loc): tuple(items) for loc, items in dict(tags).items()
        }
        self._where = location_provider or (lambda: None)
        #: Number of :meth:`inventory` calls, for tests and diagnostics.
        self.reads = 0

    @property
    def name(self) -> str:
        return "simulated"

    def inventory(self) -> Tuple[RfidTag, ...]:
        self.reads += 1
        where = self._where()
        if not where:
            return ()
        return self._tags.get(str(where), ())


#: Backend names that mean "no reader attached".
NO_READER_BACKENDS = frozenset({"", "none", "null"})


def make_rfid_reader(
    config: Any,
    location_provider: Optional[Callable[[], Optional[str]]] = None,
) -> Optional[RfidReader]:
    """Build the configured reader, or ``None`` when none is attached.

    ``config`` is an :class:`amr.utils.config.RfidConfig` (anything with
    ``backend`` and ``tags``). The default backend, ``"null"``, returns ``None``
    rather than a no-op reader: "no antenna" and "an antenna that read nothing"
    have to stay distinguishable, and only the second is a fault.
    """
    backend = str(getattr(config, "backend", None) or "null").strip().lower()
    if backend in NO_READER_BACKENDS:
        return None
    if backend == "simulated":
        return SimulatedRfidReader(
            tags_from_config(getattr(config, "tags", None)),
            location_provider=location_provider,
        )
    known = sorted(NO_READER_BACKENDS | {"simulated"})
    raise ValueError(f"unknown rfid backend {backend!r}; known: {known}")


def tags_from_config(blob: Any) -> Dict[str, Tuple[RfidTag, ...]]:
    """Parse the ``rfid.tags`` mapping (``location -> [tag, ...]``).

    Each tag is ``{tag_id, kind, ref?}``. A location tag defaults ``ref`` to the
    location it is mounted on — that is the only thing it can identify — while a
    payload tag must name its payload, because a payload tag that does not say
    what it is on identifies nothing.

    Raises :class:`ValueError` on a malformed entry rather than skipping it: a
    tag the robot cannot parse is a shelf it cannot identify, and discovering
    that at pick time is worse than refusing to start. (``amr.hazard`` skips bad
    *zone* entries because a missing zone only loses an advisory; here it would
    silently change what the robot is willing to touch.)
    """
    out: Dict[str, Tuple[RfidTag, ...]] = {}
    entries = blob or {}
    if not isinstance(entries, Mapping):
        raise ValueError("rfid.tags must be a mapping of location -> [tag, ...]")
    for location, raw in entries.items():
        loc = str(location)
        if not isinstance(raw, (list, tuple)):
            raise ValueError(f"rfid.tags[{loc!r}] must be a list of tags")
        out[loc] = tuple(_tag_from_entry(item, loc) for item in raw)
    return out


def _tag_from_entry(entry: Any, location: str) -> RfidTag:
    """Validate one ``rfid.tags`` entry into an :class:`RfidTag`."""
    if not isinstance(entry, Mapping):
        raise ValueError(f"rfid.tags[{location!r}] entries must be mappings")
    tag_id = str(entry.get("tag_id", "") or "").strip()
    if not tag_id:
        raise ValueError(f"rfid.tags[{location!r}] entry has no tag_id")

    raw_kind = str(entry.get("kind", "location") or "location").strip().lower()
    try:
        kind = RfidTagKind(raw_kind)
    except ValueError:
        known = sorted(k.value for k in RfidTagKind)
        raise ValueError(
            f"rfid.tags[{location!r}] tag {tag_id!r} has kind {raw_kind!r}; "
            f"expected one of {known}"
        ) from None

    ref = str(entry.get("ref", "") or "").strip()
    if not ref:
        if kind is RfidTagKind.PAYLOAD:
            raise ValueError(
                f"rfid.tags[{location!r}] payload tag {tag_id!r} must name its "
                "payload with 'ref'"
            )
        ref = location

    return RfidTag(tag_id=tag_id, kind=kind, ref=ref)


def tags_by_ref(tags: Iterable[RfidTag], kind: RfidTagKind) -> List[str]:
    """Sorted ``ref`` values of the ``tags`` of one ``kind`` (UIs / diagnostics)."""
    return sorted({t.ref for t in tags if t.kind is kind})


