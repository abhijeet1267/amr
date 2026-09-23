"""Warehouse map model (Phase 16).

A :class:`WarehouseMap` is a named set of 2D locations (waypoints) the robot
can travel to: a mapping of ``name -> Pose``. It is deliberately simple. The
map normally comes from ``config/warehouse.yaml`` (parsed by
:func:`amr.utils.config.load_config` into
:data:`amr.utils.config.WarehouseConfig.locations`); a built-in default map
keeps the demo and the tests working with no config file present.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping

from ..navigation.types import Pose


class MapError(Exception):
    """Raised for malformed maps or unknown locations."""


#: Built-in default layout: a dock plus a small L-shaped shelf run and a
#: handoff station. Coordinates are metres in the world frame.
_DEFAULT_LOCATIONS: Mapping[str, Iterable[float]] = {
    "dock": (0.0, 0.0, 0.0),
    "shelf_a": (2.0, 0.0, 0.0),
    "shelf_b": (2.0, 1.5, 0.0),
    "shelf_c": (4.0, 1.5, 0.0),
    "station": (0.0, 3.0, 0.0),
}


class WarehouseMap:
    """An immutable named set of world-frame poses."""

    def __init__(self, locations: Mapping[str, Pose]):
        if not locations:
            raise MapError("a warehouse map must contain at least one location")
        self._locations: Dict[str, Pose] = dict(locations)

    # -- construction ------------------------------------------------------ #
    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "WarehouseMap":
        """Build from ``{name: {x,y,theta}}`` or ``{name: [x, y, theta]}``."""
        parsed: Dict[str, Pose] = {}
        for name, val in data.items():
            if isinstance(val, Mapping):
                parsed[str(name)] = Pose.from_dict(dict(val))
            else:
                seq = list(val)
                if len(seq) != 3:
                    raise MapError(
                        f"location '{name}' must be {{x,y,theta}} or [x, y, theta]"
                    )
                parsed[str(name)] = Pose(float(seq[0]), float(seq[1]), float(seq[2]))
        return cls(parsed)

    # -- accessors --------------------------------------------------------- #
    def has(self, name: str) -> bool:
        return name in self._locations

    def pose(self, name: str) -> Pose:
        try:
            return self._locations[name]
        except KeyError:
            raise MapError(
                f"unknown location '{name}' (known: {sorted(self._locations)})"
            ) from None

    def names(self) -> list:
        return list(self._locations)

    def __len__(self) -> int:
        return len(self._locations)

    def __contains__(self, name: str) -> bool:
        return name in self._locations

    def __iter__(self):
        return iter(self._locations)


def default_map() -> WarehouseMap:
    """The built-in :data:`_DEFAULT_LOCATIONS` map."""
    return WarehouseMap.from_dict(_DEFAULT_LOCATIONS)


def map_from_config(whcfg) -> WarehouseMap:
    """Build a map from a :class:`WarehouseConfig`, falling back to the default."""
    if getattr(whcfg, "locations", None):
        return WarehouseMap.from_dict(dict(whcfg.locations))
    return default_map()
