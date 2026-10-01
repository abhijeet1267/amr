# RFID shelf / payload identification (C17)

Status: **Implemented, unit-tested, opt-in.** Mock/simulated only. No hardware required.

The warehouse AMR has to know *what* it is standing in front of before it
acts: picking the wrong box is worse than refusing to pick. RFID is the cheap
way to ask the shelf directly instead of trusting dead reckoning. The full
contract lives in `raspberry_pi/amr/rfid/reader.py`; the task-manager wiring
lives in `raspberry_pi/amr/warehouse/task_manager.py`.

> **No RFID hardware exists in this repository.** The only backend besides
> "no reader" is `simulated`, which reads tags out of `config/rfid.yaml`.
> No real tag has ever been read by this code, and the shipped default
> attaches **no reader** at all.

## Where this fits

```
WarehouseTaskManager  --parked at-->  RfidReader.inventory()
        |                                     |
        +-- confirm(location, payload?) ------+
        |        |                 |
     match: act            mismatch / silence: FAIL the task
     (no reader: unchanged behaviour — identify nothing, claim nothing)
```

Identification gates *manipulation*, not navigation: `PICK` and `PLACE` are
confirmed before the manipulator is asked to act; `MOVE` and `RETURN_TO_DOCK`
touch nothing, so there is no shelf to confirm and no reason to fail one.

## Config (`config/rfid.yaml`)

```yaml
rfid:
  backend: "null"   # "null" (no reader — the shipped default) | "simulated"
  tags: {}          # location -> [{tag_id, kind, ref?}, ...]
```

* `kind: "location"` — mounted on a shelf / station; identifies the place.
  `ref` defaults to the location name, because that is the only thing it can
  identify.
* `kind: "payload"` — attached to an item; `ref` **must** name the payload
  (a payload tag that does not say what it is on identifies nothing).

Every location named in `tags` must also appear in `warehouse.locations`
— a tag on a shelf the robot cannot navigate to is unreachable
configuration, not a working pick. The one exception: an empty
`warehouse.locations` means the built-in default map, which the tags are not
cross-checked against.

Validation fails fast at startup (`load_config`):

| Misconfiguration | Result |
|---|---|
| unknown `backend` | `ConfigError` |
| `tags` present but `backend: "null"` | `ConfigError` — the silent no-op (tags written down, nothing reads them) |
| malformed entry (no `tag_id`, bad `kind`, payload tag without `ref`) | `ConfigError` |
| tag location outside the warehouse map | `ConfigError` |

## The identification rule (`confirm`)

`confirm(tags, location, payload_id=None)` returns `None` when the inventory
confirms the location (and, when given, that the payload is present too),
otherwise a human-readable reason. It is pure and reader-independent on
purpose: a real backend cannot quietly disagree with the rule the tests pin.

* An empty inventory is **not** a pass — "I could not confirm this shelf" is
  an identification *failure*, the same distinction the hazard layer draws
  between "the air is clean" and "the gas sensor is not answering".
* The first matching location tag wins; payload is confirmed by `ref`, not
  by tag identity.

## Backends

| Backend | Behaviour |
|---|---|
| `"null"` (default) | `make_rfid_reader` returns `None`. No identification is attempted and nothing is claimed, so adding this feature cannot change an existing deployment. |
| `"simulated"` | `SimulatedRfidReader`: returns the configured tags for the location a `location_provider` callable reports (the manager's own parked position). Each call re-reads the provider and increments `reads`, so tests can assert the antenna was actually consulted. |

A real antenna plugs in behind the same `RfidReader` protocol
(`name` + `inventory() -> Tuple[RfidTag, ...]`) — nothing above it changes.
The manager accepts an injected reader (`create(..., rfid=reader)`), which
always wins over the configured one; that is the seam a real backend uses.

## Tests

`raspberry_pi/tests/test_rfid.py` (63 tests): the tag model, the config
parser, the pure `confirm` rule, the simulated reader and factory, the
shipped-default and fail-fast validation, and the end-to-end integration
(a mismatched payload or an untagged shelf fails *without the manipulator
ever acting*; moves and dock returns are never identified).
