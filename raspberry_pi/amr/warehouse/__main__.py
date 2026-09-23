"""Demo: run a scripted warehouse task in mock mode.

Run with::

    python -m amr.warehouse

Builds the full offline stack (mock transport, local navigator, mock
manipulator), then executes: pick at ``shelf_a`` -> place at ``station`` ->
return to the dock. Prints a compact progress line, then a final result.
"""

from __future__ import annotations

import sys
from typing import Callable, List

from ..navigation import LocalNavigator
from ..robot import RobotManager
from ..utils.config import load_config
from .map import map_from_config
from .tasks import Task, TaskType
from .task_manager import WarehouseTaskManager


def run(out: Callable[[str], None] = print) -> int:
    config = load_config()
    whcfg = config.warehouse

    mgr, _transport = RobotManager.create_mock(config)
    mgr.start()
    if not mgr.state.connected:
        out("FATAL: mock link did not connect")
        return 1

    mapping = map_from_config(whcfg)
    wheel_base = config.robot.wheel_track_m or whcfg.wheel_base_m
    nav = LocalNavigator(
        command=mgr.move,
        start_pose=None,  # starts at the map's dock (0, 0, 0)
        wheel_base_m=wheel_base,
        max_linear_speed=whcfg.task_speed,
        max_angular_speed=whcfg.turn_speed,
        max_pwm=mgr.drive.max_speed,
    )
    wh = WarehouseTaskManager.create(config, mgr, nav, warehouse_map=mapping)

    # Script: pick at shelf_a, place at the station, return to the dock.
    wh.submit_pick("shelf_a", payload_id="SKU-1")
    wh.submit_place("station", payload_id="SKU-1")
    wh.submit_return_to_dock()

    dt = 0.05
    max_steps = 6000
    for i in range(max_steps):
        st = wh.process(dt)
        if i % 100 == 0 or st.idle:
            out(
                f"[{i:4d}] mode={st.mode:<10} cur={st.current} "
                f"queued={st.queued} done={st.completed} "
                f"pos=({st.pose['x']:.2f},{st.pose['y']:.2f},{st.pose['theta']:.2f})"
            )
        if st.idle:
            break
    else:
        out("WARNING: hit max steps before queue drained")

    mgr.shutdown()
    final = wh.status()
    out(
        f"RESULT: completed={final.completed} failed={final.failed} "
        f"final_mode={final.mode}"
    )
    return 0 if final.failed == 0 else 1


def main(argv: List[str] | None = None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
