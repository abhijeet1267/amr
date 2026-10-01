"""RFID shelf / payload identification (C17).

Define the reader once and wire it where identification matters::

    from amr.rfid import make_rfid_reader

    reader = make_rfid_reader(config.rfid, location_provider=where_am_i)

``None`` means no reader is attached — the default, and the reason adding this
package cannot change an existing deployment's behaviour. See ``docs/rfid.md``
and ``config/rfid.yaml``.

**No RFID hardware exists in this repository.** :class:`SimulatedRfidReader`
reads tags out of configuration, so the identification path is tested end to
end without an antenna; a real backend satisfies the same
:class:`RfidReader` protocol and nothing above it changes.
"""

from .reader import (
    NO_READER_BACKENDS,
    RfidReader,
    RfidTag,
    RfidTagKind,
    SimulatedRfidReader,
    confirm,
    make_rfid_reader,
    tags_by_ref,
    tags_from_config,
)

__all__ = [
    "NO_READER_BACKENDS",
    "RfidReader",
    "RfidTag",
    "RfidTagKind",
    "SimulatedRfidReader",
    "confirm",
    "make_rfid_reader",
    "tags_by_ref",
    "tags_from_config",
]
