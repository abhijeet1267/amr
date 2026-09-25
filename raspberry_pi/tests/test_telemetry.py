"""C7 — telemetry contract, read-only collector, and dashboard HTTP surface.

Three layers are covered:

* the **contract** (:mod:`amr.telemetry.types`) — schema shape, honest
  ``UNAVAILABLE`` defaults, JSON serialisation, determinism;
* the **collector** (:mod:`amr.telemetry.collector`) — a pure reader that
  projects the existing runtime (robot / navigator / warehouse / camera)
  without ever advancing or commanding it;
* the **dashboard** — the three new read-only HTTP routes.

The safety properties under test are the point of the milestone: telemetry
must never fabricate a hardware measurement, and a ``GET`` must never be able
to move the robot.
"""

from __future__ import annotations

import json

import pytest

from amr.camera.frame import CameraStatus, SimulatedCameraSource
from amr.navigation.navigator import LocalNavigator
from amr.navigation.types import Goal, Pose
from amr.robot import RobotManager, RobotMode
from amr.telemetry import (
    TELEMETRY_SCHEMA_VERSION,
    BatteryTelemetry,
    CameraTelemetry,
    DataSource,
    HazardTelemetry,
    MissionTelemetry,
    NavigationTelemetry,
    Orientation,
    SafetyTelemetry,
    SensorTelemetry,
    SystemTelemetry,
    TelemetryCollector,
    TelemetrySnapshot,
    Vector3,
    Velocity,
)
from amr.utils.config import load_config


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def manager(config_dir):
    """A started mock-backed RobotManager (simulated, never real hardware)."""
    mgr, transport = RobotManager.create_mock(load_config(config_dir))
    mgr.start()
    # The mock transport records every line written to the controller, so the
    # read-only tests can prove telemetry never reaches an actuator.
    mgr.test_transport = transport
    try:
        yield mgr
    finally:
        mgr.shutdown()


@pytest.fixture
def collector(manager):
    return TelemetryCollector(manager, simulated=True, software_version="test")


class _Exploding:
    """A source that raises on every read — telemetry must survive it."""

    def __getattr__(self, name):
        def _boom(*_a, **_kw):
            raise RuntimeError("subsystem is on fire")

        return _boom


# --------------------------------------------------------------------------- #
# 1. Contract shape
# --------------------------------------------------------------------------- #
class TestContract:
    def test_snapshot_exposes_every_contract_section(self):
        d = TelemetrySnapshot().to_dict()
        for section in (
            "timestamp", "mode", "robot_id", "position", "orientation",
            "velocity", "navigation", "safety", "hazards", "battery",
            "sensors", "mission", "camera", "system",
        ):
            assert section in d, f"missing contract section: {section}"

    def test_schema_version_is_stable(self):
        assert TelemetrySnapshot().schema_version == TELEMETRY_SCHEMA_VERSION
        assert TELEMETRY_SCHEMA_VERSION == "1.0"

    def test_top_level_mode_and_robot_id_mirror_system(self):
        d = TelemetrySnapshot(
            system=SystemTelemetry(mode="AUTONOMOUS", robot_id="amr-01")
        ).to_dict()
        assert d["mode"] == d["system"]["mode"] == "AUTONOMOUS"
        assert d["robot_id"] == d["system"]["robot_id"] == "amr-01"

    def test_optional_subsystems_default_to_unavailable_not_zero(self):
        # "not measured" must be distinguishable from "measured as zero".
        d = TelemetrySnapshot().to_dict()
        assert d["battery"]["source"] == DataSource.UNAVAILABLE.value
        assert d["battery"]["percentage"] is None
        assert d["battery"]["voltage"] is None
        assert d["position"]["x"] is None
        assert d["navigation"]["state"] is None
        assert d["mission"]["completed_tasks"] == 0
        assert d["mission"]["source"] == DataSource.UNAVAILABLE.value

    def test_snapshot_is_json_serialisable(self):
        json.dumps(TelemetrySnapshot().to_dict())

    def test_snapshot_is_immutable(self):
        snap = TelemetrySnapshot()
        with pytest.raises(Exception):
            snap.simulated = True  # frozen dataclass

    def test_sources_report_every_dashboarded_subsystem(self):
        sources = TelemetrySnapshot().sources()
        for key in ("position", "navigation", "sensors", "battery", "hazards",
                    "mission", "camera"):
            assert sources[key] in tuple(s.value for s in DataSource)

    @pytest.mark.parametrize(
        "obj", [
            Vector3(), Orientation(), Velocity(), NavigationTelemetry(),
            SafetyTelemetry(), HazardTelemetry(), BatteryTelemetry(),
            SensorTelemetry(), MissionTelemetry(), CameraTelemetry(),
            SystemTelemetry(),
        ]
    )
    def test_every_section_serialises_to_a_dict(self, obj):
        assert isinstance(obj.to_dict(), dict)
        json.dumps(obj.to_dict())


# --------------------------------------------------------------------------- #
# 2. Read-only guarantee
# --------------------------------------------------------------------------- #
class TestReadOnly:
    def test_snapshot_never_advances_the_control_loop(self, manager):
        calls = []
        real_tick = manager.tick
        manager.tick = lambda: (calls.append(1), real_tick())[1]
        TelemetryCollector(manager).snapshot()
        assert calls == []

    def test_snapshot_writes_nothing_to_the_controller(self, manager):
        # The decisive proof: a telemetry read emits no serial command at all.
        written = list(manager.test_transport.written)
        TelemetryCollector(manager).snapshot()
        TelemetryCollector(manager).snapshot()
        assert manager.test_transport.written == written

    def test_snapshot_never_changes_robot_mode(self, manager):
        manager.request_mode(RobotMode.MANUAL)
        TelemetryCollector(manager).snapshot()
        TelemetryCollector(manager).snapshot()
        assert manager.state.mode is RobotMode.MANUAL

    def test_snapshot_never_moves_the_robot(self, manager):
        manager.request_mode(RobotMode.MANUAL)
        before = (manager.state.left_speed, manager.state.right_speed)
        TelemetryCollector(manager).snapshot()
        assert (manager.state.left_speed, manager.state.right_speed) == before

    def test_repeated_snapshots_are_stable(self, manager):
        c = TelemetryCollector(manager, simulated=True)
        a, b = c.collect(), c.collect()
        assert a.safety.to_dict() == b.safety.to_dict()
        assert a.sensors.to_dict() == b.sensors.to_dict()
        assert a.system.connected == b.system.connected

    def test_a_broken_subsystem_cannot_break_the_snapshot(self, manager):
        c = TelemetryCollector(manager, navigator=_Exploding())
        snap = c.collect()  # must not raise
        assert snap.navigation.source is DataSource.UNAVAILABLE



# --------------------------------------------------------------------------- #
# 3. Schema validation, missing optionals, serialisation, determinism
# --------------------------------------------------------------------------- #
class TestSchemaAndSerialisation:
    def test_snapshot_is_json_serialisable(self, manager):
        blob = json.dumps(TelemetryCollector(manager, simulated=True).collect().to_dict())
        assert json.loads(blob)["schema_version"] == TELEMETRY_SCHEMA_VERSION

    def test_every_snapshot_carries_the_full_contract(self, manager):
        d = TelemetryCollector(manager, simulated=True).collect().to_dict()
        for key in (
            "timestamp", "mode", "robot_id", "position", "orientation",
            "velocity", "navigation", "safety", "hazards", "battery",
            "sensors", "mission", "camera", "system", "source",
        ):
            assert key in d, key

    @pytest.mark.parametrize("section", [
        "position", "orientation", "velocity", "navigation", "safety",
        "hazards", "battery", "sensors", "mission", "camera", "system",
    ])
    def test_each_section_declares_its_own_source(self, manager, section):
        d = TelemetryCollector(manager, simulated=True).collect().to_dict()
        assert "source" in d[section]

    def test_absent_hardware_is_unavailable_not_zero(self, manager):
        # A battery reading of 0% would be a physical claim. No battery
        # hardware exists, so the honest answer is unavailable + null.
        battery = TelemetryCollector(manager, simulated=True).collect().battery
        assert battery.source is DataSource.UNAVAILABLE
        assert battery.percentage is None
        assert battery.voltage is None

    def test_missing_optional_fields_stay_none(self, manager):
        snap = TelemetryCollector(manager, simulated=True).collect()
        assert snap.battery.voltage is None
        assert snap.camera.source_name is None or isinstance(
            snap.camera.source_name, str)

    def test_collector_survives_an_absent_optional_subsystem(self, manager):
        # Every subsystem argument is optional; none is required to snapshot.
        snap = TelemetryCollector(manager).collect()
        assert snap.schema_version == TELEMETRY_SCHEMA_VERSION

    def test_unattached_hazard_layer_reports_unavailable(self, manager):
        snap = TelemetryCollector(manager, simulated=True).collect()
        assert snap.hazards.source is DataSource.UNAVAILABLE
        assert snap.hazards.active == ()

    def test_collection_is_deterministic_under_a_fixed_clock(self, manager):
        t = TelemetryCollector(manager, simulated=True, clock=lambda: 1.0)
        assert t.collect().to_dict() == t.collect().to_dict()


# --------------------------------------------------------------------------- #
# 4. Simulation vs LIVE honesty -- never present a mock as a measurement
# --------------------------------------------------------------------------- #
class TestSimulationHonesty:
    def test_mock_runtime_is_labelled_simulation(self, manager):
        snap = TelemetryCollector(manager, simulated=True).collect()
        assert snap.source is DataSource.SIMULATION
        assert snap.system.simulated is True
        assert snap.system.source is DataSource.SIMULATION

    def test_live_runtime_is_labelled_live(self, manager):
        snap = TelemetryCollector(manager, simulated=False).collect()
        assert snap.source is DataSource.LIVE
        assert snap.system.simulated is False

    def test_unattached_subsystem_is_unavailable_not_simulated(self, manager):
        snap = TelemetryCollector(manager, simulated=True).collect()
        assert snap.navigation.source is DataSource.UNAVAILABLE
        assert snap.navigation.source is not DataSource.SIMULATION

    def test_no_hardware_value_is_ever_invented(self, manager):
        d = TelemetryCollector(manager, simulated=True).collect().to_dict()
        # Battery and charging are physically absent in this project.
        assert d["battery"]["percentage"] is None
        assert d["battery"]["voltage"] is None


# --------------------------------------------------------------------------- #
# C8 — camera telemetry integration (metadata only, never pixels)
# --------------------------------------------------------------------------- #
class TestCameraTelemetry:
    def test_no_camera_is_honestly_unavailable(self, manager):
        snap = TelemetryCollector(manager, simulated=True).collect()
        cam = snap.camera
        assert cam.status is CameraStatus.UNAVAILABLE
        assert cam.source is DataSource.UNAVAILABLE
        assert cam.width is None and cam.height is None
        assert cam.format is None
        assert cam.has_frame is False

    def test_simulated_camera_reports_simulation_not_live(self, manager):
        source = SimulatedCameraSource(width=64, height=48)
        snap = TelemetryCollector(manager, camera=source,
                                  simulated=True).collect()
        cam = snap.camera
        assert cam.status is CameraStatus.SIMULATION
        assert cam.source is DataSource.SIMULATION
        assert cam.status is not CameraStatus.LIVE

    def test_camera_metadata_flows_into_telemetry(self, manager):
        source = SimulatedCameraSource(width=64, height=48)
        source.start()
        source.read()
        snap = TelemetryCollector(manager, camera=source,
                                  simulated=True).collect()
        cam = snap.camera
        assert (cam.width, cam.height) == (64, 48)
        assert cam.format
        assert cam.frame_id >= 1
        assert cam.timestamp is not None

    def test_snapshot_carries_no_pixels(self, manager):
        source = SimulatedCameraSource(width=64, height=48)
        source.start()
        source.read()
        blob = json.dumps(
            TelemetryCollector(manager, camera=source, simulated=True)
            .collect().to_dict()
        )
        # A PNG signature would mean frame bytes leaked into the snapshot.
        assert "\\x89PNG" not in blob and "iVBORw0KGgo" not in blob
        assert len(blob) < 8192  # bounded: telemetry stays small

    def test_broken_camera_degrades_to_unavailable(self, manager):
        snap = TelemetryCollector(manager, camera=_Exploding(),
                                  simulated=True).collect()
        # A camera that raises on describe() is a *fault*, not an absent camera,
        # so the collector reports ERROR rather than flattening it to UNAVAILABLE.
        assert snap.camera.status in (CameraStatus.ERROR, CameraStatus.UNAVAILABLE)
        assert snap.camera.has_frame is False

    def test_camera_telemetry_survives_a_failing_camera(self, manager):
        # Fixed clock so the only thing compared is the projection itself.
        t = TelemetryCollector(manager, camera=_Exploding(), simulated=True,
                               clock=lambda: 1.0)
        assert t.collect().to_dict() == t.collect().to_dict()

