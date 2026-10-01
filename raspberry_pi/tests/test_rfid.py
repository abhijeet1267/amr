"""Tests for RFID shelf / payload identification (C17).

Covers, with no reader and no hardware attached:

* :mod:`amr.rfid.reader` — the ``RfidTag`` model, the ``rfid.tags`` parser, the
  pure ``confirm`` rule, ``SimulatedRfidReader`` and the backend factory.
* ``config/rfid.yaml`` — the shipped default (no reader attached) and the
  fail-fast validation, including the silent no-op where tags are written down
  but the configured backend would never read them.
* The integration — :class:`~amr.warehouse.task_manager.WarehouseTaskManager`
  confirming the shelf before it lets the end effector act, and behaving
  exactly as it did before this feature when no reader is attached.

**No RFID hardware exists in this repository.** Every reader here is simulated,
and no real tag has ever been read by this code.
"""

from __future__ import annotations

import dataclasses
import shutil

import pytest

from amr.navigation import LocalNavigator, Pose
from amr.rfid import (
    RfidReader,
    RfidTag,
    RfidTagKind,
    SimulatedRfidReader,
    confirm,
    make_rfid_reader,
    tags_from_config,
)
from amr.robot import RobotManager
from amr.utils.config import ConfigError, RfidConfig, load_config
from amr.warehouse import TaskStatus, WarehouseTaskManager

DT = 0.05

#: A simulated reader wired to the *shipped* warehouse map: one shelf carrying a
#: tagged payload ("box-1"), one handoff station with only a location tag. The
#: asymmetry is deliberate — it is what lets a test tell "the shelf was
#: confirmed" apart from "the payload was confirmed".
_RFID_YAML = """\
rfid:
  backend: "simulated"
  tags:
    shelf_a:
      - {tag_id: "E200-0001", kind: "location"}
      - {tag_id: "E200-1001", kind: "payload", ref: "box-1"}
    station:
      - {tag_id: "E200-0005", kind: "location"}
"""


# =========================================================================== #
# Fixtures / helpers
# =========================================================================== #
@pytest.fixture
def app_config(config_dir):
    return load_config(config_dir)


@pytest.fixture
def rfid_config_dir(tmp_path, config_dir):
    """A copy of the shipped config with the simulated reader enabled.

    Copied rather than synthesised so these tests run against the real
    warehouse map: a tag mounted on a shelf the robot cannot navigate to would
    otherwise pass here and fail on the robot.
    """
    dst = tmp_path / "config"
    shutil.copytree(str(config_dir), dst)
    (dst / "rfid.yaml").write_text(_RFID_YAML, encoding="utf-8")
    return dst


def _stack(config, rfid=None):
    """Offline stack: mock robot + gated navigator + warehouse manager.

    Built through the same ``WarehouseTaskManager.create`` the runtime uses, so
    the reader under test is the one the config actually produces. Pass ``rfid``
    to inject a reader explicitly (the same seam a real backend would use).
    """
    mgr, _transport = RobotManager.create_mock(config)
    mgr.start()
    nav = LocalNavigator(
        command=mgr.move,
        start_pose=Pose(0.0, 0.0, 0.0),
        wheel_base_m=config.warehouse.wheel_base_m,
        max_linear_speed=config.warehouse.task_speed,
        max_angular_speed=config.warehouse.turn_speed,
        max_pwm=config.robot.motors.max_speed,
    )
    return mgr, nav, WarehouseTaskManager.create(config, mgr, nav, rfid=rfid)


@pytest.fixture
def with_rfid(rfid_config_dir):
    """Stack whose manager built a simulated reader from ``rfid.yaml``."""
    return _stack(load_config(str(rfid_config_dir)))


@pytest.fixture
def without_rfid(app_config):
    """Stack with the shipped config: no reader attached."""
    return _stack(app_config)


def run_to_empty(wh: WarehouseTaskManager, dt: float = DT, max_ticks: int = 3000):
    """Drive ``process`` until the queue drains; fail loudly if it never does."""
    st = None
    for _ in range(max_ticks):
        st = wh.process(dt)
        if wh.queue_empty():
            return st
    raise AssertionError(f"manager did not drain in {max_ticks} ticks: {st.to_dict()}")


def _tag(tag_id: str, kind: RfidTagKind, ref: str) -> RfidTag:
    return RfidTag(tag_id=tag_id, kind=kind, ref=ref)


# =========================================================================== #
# reader.py — the tag model and the config parser
# =========================================================================== #
class TestRfidTag:
    def test_to_dict_uses_the_wire_spelling_of_kind(self):
        t = _tag("E200-0001", RfidTagKind.LOCATION, "shelf_a")
        assert t.to_dict() == {
            "tag_id": "E200-0001", "kind": "location", "ref": "shelf_a",
        }

    def test_is_frozen(self):
        """A tag is shared by every inventory call; nothing may mutate one."""
        t = _tag("E200-0001", RfidTagKind.LOCATION, "shelf_a")
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.ref = "shelf_b"  # type: ignore[misc]

    def test_tags_with_the_same_contents_are_equal(self):
        assert _tag("T1", RfidTagKind.LOCATION, "shelf_a") == _tag(
            "T1", RfidTagKind.LOCATION, "shelf_a"
        )


class TestTagsFromConfig:
    def test_location_tag_defaults_its_ref_to_the_location(self):
        """A location tag identifies the place it is mounted on, so the name
        would be a second copy of the same fact — and a second thing to get
        wrong. It is filled in rather than demanded."""
        parsed = tags_from_config({"shelf_a": [{"tag_id": "T1"}]})
        assert parsed == {"shelf_a": (_tag("T1", RfidTagKind.LOCATION, "shelf_a"),)}

    def test_location_is_the_default_kind(self):
        parsed = tags_from_config({"shelf_a": [{"tag_id": "T1"}]})
        assert parsed["shelf_a"][0].kind is RfidTagKind.LOCATION

    def test_payload_tag_keeps_its_explicit_ref(self):
        parsed = tags_from_config(
            {"shelf_a": [{"tag_id": "T2", "kind": "payload", "ref": "box-1"}]}
        )
        assert parsed == {"shelf_a": (_tag("T2", RfidTagKind.PAYLOAD, "box-1"),)}

    def test_mixed_tags_on_one_location_keep_their_order(self):
        parsed = tags_from_config(
            {"shelf_a": [{"tag_id": "T1"}, {"tag_id": "T2", "kind": "payload",
                                            "ref": "box-1"}]}
        )
        assert [t.tag_id for t in parsed["shelf_a"]] == ["T1", "T2"]

    def test_kind_is_case_insensitive(self):
        parsed = tags_from_config(
            {"shelf_a": [{"tag_id": "T2", "kind": "Payload", "ref": "box-1"}]}
        )
        assert parsed["shelf_a"][0].kind is RfidTagKind.PAYLOAD

    def test_empty_and_missing_config_yields_no_tags(self):
        assert tags_from_config({}) == {}
        assert tags_from_config(None) == {}

    def test_non_mapping_blob_is_rejected(self):
        with pytest.raises(ValueError, match="mapping"):
            tags_from_config(["shelf_a"])

    def test_location_whose_value_is_not_a_list_is_rejected(self):
        with pytest.raises(ValueError, match="must be a list"):
            tags_from_config({"shelf_a": {"tag_id": "T1"}})

    def test_entry_that_is_not_a_mapping_is_rejected(self):
        with pytest.raises(ValueError, match="must be mappings"):
            tags_from_config({"shelf_a": ["T1"]})

    def test_entry_without_a_tag_id_is_rejected(self):
        with pytest.raises(ValueError, match="no tag_id"):
            tags_from_config({"shelf_a": [{"kind": "location"}]})

    def test_entry_with_a_blank_tag_id_is_rejected(self):
        with pytest.raises(ValueError, match="no tag_id"):
            tags_from_config({"shelf_a": [{"tag_id": "  "}]})

    def test_unknown_kind_is_rejected_and_names_the_alternatives(self):
        with pytest.raises(ValueError, match="expected one of"):
            tags_from_config({"shelf_a": [{"tag_id": "T1", "kind": "pallet"}]})

    def test_payload_tag_without_a_ref_is_rejected(self):
        """A payload tag that does not say what it is on identifies nothing, so
        it is refused rather than quietly matching its own shelf name."""
        with pytest.raises(ValueError, match="must name its payload"):
            tags_from_config({"shelf_a": [{"tag_id": "T1", "kind": "payload"}]})


# =========================================================================== #
# reader.py — the identification rule
# =========================================================================== #
class TestConfirm:
    def test_no_error_when_the_location_tag_is_present(self):
        tags = [_tag("T1", RfidTagKind.LOCATION, "shelf_a")]
        assert confirm(tags, "shelf_a") is None

    def test_error_when_no_location_tag_is_read(self):
        reason = confirm([], "shelf_a")
        assert reason is not None
        assert "shelf_a" in reason and "nothing" in reason

    def test_an_empty_inventory_is_a_failure_not_a_pass(self):
        """The whole point of the rule: "I could not confirm this shelf" must
        never be reported as "this shelf is confirmed"."""
        assert confirm((), "shelf_a") is not None

    def test_error_when_a_different_location_tag_is_read(self):
        tags = [_tag("T1", RfidTagKind.LOCATION, "shelf_b")]
        assert confirm(tags, "shelf_a") is not None

    def test_payload_request_is_satisfied_by_the_payload_tag(self):
        tags = [
            _tag("T1", RfidTagKind.LOCATION, "shelf_a"),
            _tag("T2", RfidTagKind.PAYLOAD, "box-1"),
        ]
        assert confirm(tags, "shelf_a", "box-1") is None

    def test_payload_request_fails_when_only_the_shelf_is_tagged(self):
        tags = [_tag("T1", RfidTagKind.LOCATION, "shelf_a")]
        reason = confirm(tags, "shelf_a", "box-1")
        assert reason is not None
        assert "box-1" in reason

    def test_payload_request_fails_for_a_different_payload(self):
        tags = [
            _tag("T1", RfidTagKind.LOCATION, "shelf_a"),
            _tag("T2", RfidTagKind.PAYLOAD, "box-2"),
        ]
        assert confirm(tags, "shelf_a", "box-1") is not None

    def test_kinds_are_not_interchangeable(self):
        """A payload tag must not be mistaken for the shelf's own tag, or a
        pick could be cleared by the very item it is about to take."""
        only_payload = [_tag("T2", RfidTagKind.PAYLOAD, "shelf_a")]
        assert confirm(only_payload, "shelf_a") is not None

    def test_a_payload_id_is_not_required_when_none_is_asked_for(self):
        tags = [_tag("T1", RfidTagKind.LOCATION, "station")]
        assert confirm(tags, "station") is None


# =========================================================================== #
# reader.py — the simulated backend and the factory
# =========================================================================== #
class TestSimulatedRfidReader:
    def _reader(self, where, tags=None):
        tags = tags if tags is not None else {
            "shelf_a": [_tag("T1", RfidTagKind.LOCATION, "shelf_a")],
        }
        return SimulatedRfidReader(tags, location_provider=lambda: where)

    def test_reads_the_tags_mounted_at_the_robots_location(self):
        r = self._reader("shelf_a")
        assert r.inventory() == (_tag("T1", RfidTagKind.LOCATION, "shelf_a"),)

    def test_unknown_location_reads_nothing(self):
        assert self._reader("nowhere").inventory() == ()

    def test_no_location_reads_nothing(self):
        assert self._reader(None).inventory() == ()

    def test_no_provider_reads_nothing(self):
        """Default-constructed, the reader has no idea where it is and must not
        invent a location to be helpful."""
        r = SimulatedRfidReader({"shelf_a": [_tag("T1", RfidTagKind.LOCATION,
                                                  "shelf_a")]})
        assert r.inventory() == ()

    def test_each_call_reads_again(self):
        """A reader is polled, not memoised: the antenna can lose a tag."""
        r = self._reader("shelf_a")
        r.inventory()
        r.inventory()
        assert r.reads == 2

    def test_name(self):
        assert self._reader("shelf_a").name == "simulated"

    def test_satisfies_the_reader_protocol(self):
        assert isinstance(self._reader("shelf_a"), RfidReader)


class TestMakeRfidReader:
    @pytest.mark.parametrize("backend", ["null", "none", "", None])
    def test_no_backend_means_no_reader(self, backend):
        """``None`` — not a no-op reader — because "no antenna" and "an antenna
        that read nothing" have to stay distinguishable."""
        assert make_rfid_reader(RfidConfig(backend=backend or "null")) is None

    def test_missing_config_is_not_an_error(self):
        assert make_rfid_reader(None) is None

    def test_simulated_backend_is_wired_to_the_config_tags(self):
        cfg = RfidConfig(backend="simulated", tags={"shelf_a": [{"tag_id": "T1"}]})
        r = make_rfid_reader(cfg, location_provider=lambda: "shelf_a")
        assert isinstance(r, SimulatedRfidReader)
        assert r.inventory() == (_tag("T1", RfidTagKind.LOCATION, "shelf_a"),)

    def test_backend_is_case_insensitive(self):
        cfg = RfidConfig(backend="Simulated", tags={})
        assert isinstance(make_rfid_reader(cfg), SimulatedRfidReader)

    def test_unknown_backend_is_rejected(self):
        with pytest.raises(ValueError, match="unknown rfid backend"):
            make_rfid_reader(RfidConfig(backend="zebra"))


# =========================================================================== #
# config/rfid.yaml — the shipped default and the fail-fast validation
# =========================================================================== #
def _load_with(tmp_path, rfid_body: str, warehouse_body: str | None = None):
    (tmp_path / "rfid.yaml").write_text(rfid_body, encoding="utf-8")
    if warehouse_body is not None:
        (tmp_path / "warehouse.yaml").write_text(warehouse_body, encoding="utf-8")
    return load_config(str(tmp_path))


class TestShippedRfidConfig:
    def test_shipped_config_attaches_no_reader(self, app_config):
        """Promoting identification has to be an operator's decision. The
        shipped default must leave the task manager exactly as it was."""
        assert app_config.rfid.backend == "null"
        assert app_config.rfid.tags == {}
        assert make_rfid_reader(app_config.rfid) is None

    def test_absent_file_falls_back_to_no_reader(self, tmp_path):
        cfg = load_config(str(tmp_path))  # no rfid.yaml at all
        assert cfg.rfid.backend == "null"
        assert cfg.rfid.tags == {}

    def test_the_shipped_tags_block_is_empty_and_commented(self, config_dir):
        """The documented example must stay commented out: uncommenting it is
        what an operator does deliberately, and an active example would make
        the shipped default a silent no-op the moment the file is copied."""
        text = (config_dir / "rfid.yaml").read_text(encoding="utf-8")
        active = [ln.strip() for ln in text.splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
        assert active == ["rfid:", 'backend: "null"', "tags: {}"], active


class TestRfidConfigValidation:
    def test_unknown_backend_is_rejected(self, tmp_path):
        with pytest.raises(ConfigError, match="rfid.backend"):
            _load_with(tmp_path, 'rfid:\n  backend: "zebra"\n')

    def test_tags_without_a_reading_backend_are_rejected(self, tmp_path):
        """The silent no-op this validation exists for: the operator wrote the
        tags down, so they believe every pick is verified — and nothing reads
        them. A config that cannot do what it looks like it does must fail."""
        body = (
            'rfid:\n  backend: "null"\n  tags:\n'
            '    shelf_a:\n      - {tag_id: "T1"}\n'
        )
        with pytest.raises(ConfigError, match="would ever be read"):
            _load_with(tmp_path, body)

    def test_malformed_tag_is_rejected_at_load_time(self, tmp_path):
        body = (
            'rfid:\n  backend: "simulated"\n  tags:\n'
            '    shelf_a:\n      - {tag_id: "T1", kind: "payload"}\n'
        )
        with pytest.raises(ConfigError, match="must name its payload"):
            _load_with(tmp_path, body)

    def test_tag_on_a_location_outside_the_map_is_rejected(self, tmp_path):
        """A tag on a shelf the robot cannot navigate to is unreachable
        configuration, not a working pick."""
        body = (
            'rfid:\n  backend: "simulated"\n  tags:\n'
            '    shelf_z:\n      - {tag_id: "T1"}\n'
        )
        warehouse = (
            "warehouse:\n  enabled: true\n  locations:\n"
            "    dock: {x: 0.0, y: 0.0, theta: 0.0}\n"
            "    shelf_a: {x: 2.0, y: 0.0, theta: 0.0}\n"
        )
        with pytest.raises(ConfigError, match="not in the warehouse map"):
            _load_with(tmp_path, body, warehouse)

    def test_tags_are_not_cross_checked_when_no_map_is_declared(self, tmp_path):
        """An empty ``warehouse.locations`` means the built-in default map, so
        the tag list must not be rejected for failing to match a map that was
        never written down."""
        body = (
            'rfid:\n  backend: "simulated"\n  tags:\n'
            '    shelf_a:\n      - {tag_id: "T1"}\n'
        )
        cfg = _load_with(tmp_path, body)
        assert cfg.rfid.backend == "simulated"
        assert "shelf_a" in cfg.rfid.tags

    def test_a_valid_simulated_config_loads(self, tmp_path, config_dir):
        body = _RFID_YAML
        warehouse = (config_dir / "warehouse.yaml").read_text(encoding="utf-8")
        cfg = _load_with(tmp_path, body, warehouse)
        assert cfg.rfid.backend == "simulated"
        assert set(cfg.rfid.tags) == {"shelf_a", "station"}
        assert isinstance(make_rfid_reader(cfg.rfid), SimulatedRfidReader)


# =========================================================================== #
# Integration — the task manager identifying the shelf before it acts
# =========================================================================== #
class TestManagerWithoutReader:
    def test_no_reader_is_attached_by_default(self, without_rfid):
        _mgr, _nav, wh = without_rfid
        assert wh._rfid is None

    def test_a_pick_still_completes_with_no_reader(self, without_rfid):
        """Opt-in means the pre-existing path is untouched: nothing is
        verified, and nothing is failed. This is the regression that matters
        most — the feature must not be able to change a robot that never asked
        for it."""
        _mgr, _nav, wh = without_rfid
        wh.submit_pick("shelf_a", "box-1")
        run_to_empty(wh)
        assert [t.status for t in wh.completed()] == [TaskStatus.DONE]
        assert wh.failed() == []
        assert wh._manip.payload == "box-1"

    def test_an_untagged_shelf_is_fine_with_no_reader(self, without_rfid):
        _mgr, _nav, wh = without_rfid
        wh.submit_pick("shelf_b", "box-1")
        run_to_empty(wh)
        assert [t.status for t in wh.completed()] == [TaskStatus.DONE]


class TestManagerWithReader:
    def test_the_configured_reader_is_attached(self, with_rfid):
        _mgr, _nav, wh = with_rfid
        assert isinstance(wh._rfid, SimulatedRfidReader)

    def test_a_confirmed_pick_completes(self, with_rfid):
        _mgr, _nav, wh = with_rfid
        wh.submit_pick("shelf_a", "box-1")
        run_to_empty(wh)
        assert [t.status for t in wh.completed()] == [TaskStatus.DONE]
        assert wh._manip.payload == "box-1"

    def test_a_pick_of_an_unlisted_payload_fails_without_acting(self, with_rfid):
        """The reason this feature exists: the shelf is right, the item is not,
        and the gripper must never close on the wrong box."""
        _mgr, _nav, wh = with_rfid
        wh.submit_pick("shelf_a", "box-9")
        run_to_empty(wh)
        failed = wh.failed()
        assert [t.status for t in failed] == [TaskStatus.FAILED]
        assert "box-9" in failed[0].last_error
        assert wh._manip.picks == 0
        assert wh._manip.payload is None

    def test_a_pick_at_an_untagged_shelf_fails_without_acting(self, with_rfid):
        _mgr, _nav, wh = with_rfid
        wh.submit_pick("shelf_b", "box-1")
        run_to_empty(wh)
        assert "shelf_b" in wh.failed()[0].last_error
        assert wh._manip.picks == 0

    def test_pick_then_place_at_a_tagged_station_succeeds(self, with_rfid):
        _mgr, _nav, wh = with_rfid
        wh.submit_pick("shelf_a", "box-1")
        wh.submit_place("station", "box-1")
        run_to_empty(wh)
        assert [t.status for t in wh.completed()] == [
            TaskStatus.DONE, TaskStatus.DONE,
        ]
        assert (wh._manip.picks, wh._manip.places) == (1, 1)

    def test_a_place_at_an_untagged_location_fails(self, with_rfid):
        _mgr, _nav, wh = with_rfid
        wh.submit_pick("shelf_a", "box-1")
        wh.submit_place("shelf_b", "box-1")
        run_to_empty(wh)
        assert len(wh.completed()) == 1
        assert "shelf_b" in wh.failed()[0].last_error
        assert wh._manip.places == 0

    def test_a_move_to_an_untagged_shelf_is_not_failed(self, with_rfid):
        """Identification gates manipulation, not navigation: a move touches
        nothing, so there is no shelf to confirm and no reason to fail one."""
        _mgr, _nav, wh = with_rfid
        wh.submit_move("shelf_b")
        run_to_empty(wh)
        assert [t.status for t in wh.completed()] == [TaskStatus.DONE]
        assert wh.failed() == []

    def test_returning_to_dock_is_not_identified(self, with_rfid):
        _mgr, _nav, wh = with_rfid
        wh.submit_return_to_dock()
        run_to_empty(wh)
        assert [t.status for t in wh.completed()] == [TaskStatus.DONE]

    def test_the_location_provider_follows_the_active_task(self, with_rfid):
        """What the antenna can read depends on where the robot is parked, so
        the simulated reader asks the manager — and gets ``None`` until there
        really is an active task."""
        _mgr, _nav, wh = with_rfid
        assert wh._current_location() is None          # idle
        task = wh.submit_pick("shelf_a", "box-1")
        assert wh._current_location() is None          # queued, not started
        wh.process(DT)
        assert wh._current_location() == task.location

    def test_an_injected_reader_wins_over_the_config(self, app_config):
        """The seam a real backend plugs into: the shipped config attaches no
        reader, the caller supplies one, and it is the caller's that is used."""
        reader = SimulatedRfidReader(
            {
                "shelf_a": [
                    _tag("T1", RfidTagKind.LOCATION, "shelf_a"),
                    _tag("T2", RfidTagKind.PAYLOAD, "box-1"),
                ],
            },
            location_provider=lambda: "shelf_a",
        )
        _mgr, _nav, wh = _stack(app_config, rfid=reader)
        assert wh._rfid is reader
        wh.submit_pick("shelf_a", "box-1")
        run_to_empty(wh)
        assert wh._manip.payload == "box-1"
        assert reader.reads >= 1

    def test_an_attached_reader_that_reads_nothing_fails_the_pick(self, app_config):
        """An antenna that is present but silent is a fault, not a pass. This
        is the distinction ``make_rfid_reader`` returns ``None`` to preserve."""
        silent = SimulatedRfidReader({}, location_provider=lambda: "shelf_a")
        _mgr, _nav, wh = _stack(app_config, rfid=silent)
        wh.submit_pick("shelf_a", "box-1")
        run_to_empty(wh)
        assert [t.status for t in wh.failed()] == [TaskStatus.FAILED]
        assert wh._manip.picks == 0




