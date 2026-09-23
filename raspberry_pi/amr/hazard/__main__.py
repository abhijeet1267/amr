"""Demo: exercise the multi-hazard safety layer offline (no hardware).

Run with::

    python -m amr.hazard

Builds a mocked robot stack (:class:`~amr.robot.robot_manager.RobotManager`) plus
a :class:`~amr.hazard.manager.HazardManager` driven by *scripted* gas and vision
sources, then walks a scenario and checks the resulting hazard state **and** the
robot's response to it:

    clean air -> gas rising (SLOW) -> human in aisle (SLOW) -> flame (EMERGENCY)

The point of the demo is the interaction, not the sensors: when the layer says
``STOP``/``EMERGENCY`` the robot must end up in ``SAFETY_STOP`` with its motors
at zero, and it must stay there until an operator acknowledges — first the
hazard latch, then the robot mode. Neither releases the other.

Prints one line per step and a final RESULT. Exit code 0 iff every expectation
held.
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional, Tuple

from ..robot import RobotManager, RobotMode
from ..utils.config import load_config
from .manager import HazardManager
from .sources import GasSensorSource, VisionHazardSource
from .types import HazardKind, HazardState


class _Scripted:
    """Mutable stand-ins for real sensors, set by the scenario."""

    def __init__(self) -> None:
        self.gas_ppm: float = 0.0
        self.detections: Tuple = ()


#: (label, gas ppm, vision detections, expected hazard state)
SCENARIO = (
    ("clean air", 0.0, (), HazardState.NORMAL),
    ("gas rising", 500.0, (), HazardState.SLOW),
    ("human in aisle", 0.0, ((HazardKind.HUMAN, 0.6),), HazardState.SLOW),
    ("flame detected", 0.0, ((HazardKind.FIRE, 0.95),), HazardState.EMERGENCY),
)


def run(out: Callable[[str], None] = print) -> int:
    config = load_config()
    hzcfg = config.hazard

    mgr, _transport = RobotManager.create_mock(config)
    mgr.start()
    if not mgr.state.connected:
        out("FATAL: mock link did not connect")
        return 1
    mgr.request_mode(RobotMode.MANUAL)

    sensors = _Scripted()
    hazard = HazardManager(
        hzcfg,
        sources=[
            GasSensorSource(
                lambda: sensors.gas_ppm,
                name="mq2",
                warn_at=hzcfg.gas_warn_at,
                critical_at=hzcfg.gas_critical_at,
                unit=hzcfg.gas_unit,
            ),
            VisionHazardSource(
                lambda: sensors.detections,
                name="cam",
                warn_at=hzcfg.human_warn_at,
                critical_at=hzcfg.human_critical_at,
            ),
        ],
    )
    mgr.attach_hazard(hazard)

    out(f"hazard layer: enabled={hzcfg.enabled} thresholds={hzcfg.status}")
    failures = 0

    for label, ppm, detections, expected in SCENARIO:
        sensors.gas_ppm = ppm
        sensors.detections = detections
        mgr.tick()

        got = hazard.state
        ok = got is expected
        failures += 0 if ok else 1
        out(
            f"{'ok ' if ok else 'BAD'} {label:<15} "
            f"hazard={got.value:<9} mode={mgr.state.mode.value:<11} "
            f"L={mgr.state.left_speed:>3} R={mgr.state.right_speed:>3} "
            f"blocked={hazard.status.blocks_motion} events={len(hazard.events)}"
        )

    # The life-safety hazard must have latched and forced a safety stop.
    if mgr.state.mode is not RobotMode.SAFETY_STOP:
        out(f"BAD expected SAFETY_STOP, got {mgr.state.mode.value}")
        failures += 1
    if mgr.state.is_moving:
        out("BAD motors are still commanded non-zero")
        failures += 1

    # Cleared reading, latched state: the robot must NOT resume on its own.
    sensors.gas_ppm = 0.0
    sensors.detections = ()
    held = mgr.tick()
    ok = hazard.state is HazardState.EMERGENCY and mgr.state.mode is RobotMode.SAFETY_STOP
    failures += 0 if ok else 1
    out(
        f"{'ok ' if ok else 'BAD'} hazard cleared but latched  "
        f"hazard={hazard.state.value} mode={mgr.state.mode.value} "
        f"layer3={held.action.value}"
    )

    # Operator acknowledgement, in two explicit steps.
    acked = hazard.acknowledge()
    out(
        f"acknowledge hazard -> {acked.state.value} (latched={acked.latched}); "
        f"robot still {mgr.state.mode.value}"
    )
    mode = mgr.request_mode(RobotMode.IDLE)
    out(f"operator reset mode -> {mode.value}")

    mgr.shutdown()
    out(
        f"RESULT: steps={len(SCENARIO)} failures={failures} "
        f"events_recorded={len(hazard.events)} final_hazard={hazard.state.value} "
        f"final_mode={mgr.state.mode.value}"
    )
    return 0 if failures == 0 else 1


def main(argv: Optional[List[str]] = None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
