"""Application registry: a machine-readable description of every interface
this project ships (see ``config/applications.yaml``).

Why this exists
---------------
The hub page, the mobile client and the desktop client all need to answer
"what can I open, and does it actually work right now?". Answering that in
each client would guarantee the three drift apart, and would make it possible
for one of them to claim an application works when it does not. So the answer
lives here once, derived from a config file whose URLs were copied out of the
route table in :mod:`amr.web.server` (audit:
``AI_CONTEXT/APPLICATION_ECOSYSTEM_AUDIT.md``).

The one rule worth stating loudly
---------------------------------
:meth:`ApplicationRegistry.resolve_status` may only ever make an application's
status *worse* than the status declared in the file. The file records what has
been verified; the runtime can withdraw that claim (no camera attached, server
down, only a mock robot answering) but can never upgrade ``HARDWARE REQUIRED``
to ``AVAILABLE`` because a route happened to respond. A registry that could
upgrade statuses would be a way of lying to the operator, which is the failure
mode this subsystem exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.config import ConfigError, _load_yaml, find_config_dir

#: Config file name, resolved relative to the same config directory every
#: other YAML in this project is read from.
APPLICATIONS_FILE = "applications.yaml"

#: Every status the registry may report. Kept as a tuple rather than an enum
#: because these strings go straight into JSON and into the UI verbatim — a
#: status the operator reads must be the status that was decided here.
#:
#: Order is *best to worst*: :func:`ApplicationRegistry.resolve_status` only
#: walks down this list, never up.
STATUSES = (
    "AVAILABLE",            # verified working in this codebase
    "MOCK",                 # works, but only against the simulated robot
    "PARTIAL",              # works, with a named gap
    "HARDWARE REQUIRED",    # implemented, never exercised on real hardware
    "BUILD NOT AVAILABLE",  # source present, cannot be built in this environment
    "NOT INSTALLED",        # nothing to launch yet
    "DEVELOPMENT",          # being written, not usable
    "COMING SOON",          # planned, not started
    "OFFLINE",              # the robot/server is not reachable right now
)

#: Index into :data:`STATUSES`; higher means "worse". Enforces never-upgrade.
_RANK = {name: i for i, name in enumerate(STATUSES)}

#: Operator-facing gloss for each status. Short, and honest about what the
#: operator is looking at.
_DETAILS = {
    "AVAILABLE": "Verified working in this build.",
    "MOCK": "Working against the simulated robot; no hardware involved.",
    "PARTIAL": "Works, with a gap noted in the description.",
    "HARDWARE REQUIRED": "Implemented, but never exercised on real hardware.",
    "BUILD NOT AVAILABLE": "Source is present; it cannot be built in this environment.",
    "NOT INSTALLED": "Nothing to launch yet.",
    "DEVELOPMENT": "Being written; not usable.",
    "COMING SOON": "Planned, not started.",
    "OFFLINE": "The robot server is not reachable right now.",
}

#: Categories the hub groups applications under. Unknown categories are
#: rejected at load time so a typo cannot silently make a card unreachable.
CATEGORIES = (
    "monitoring",
    "visualization",
    "analysis",
    "safety",
    "diagnostics",
    "control",
    "reference",
    "client",
)

#: Platforms an application may claim. ``web`` applications are served by this
#: very process; the rest are separate artefacts and are judged accordingly.
PLATFORMS = ("web", "android", "ios", "macos", "windows", "linux")


@dataclass(frozen=True)
class Application:
    """One entry of ``config/applications.yaml``.

    Frozen because the registry is read by several request handlers at once; a
    mutated card would mean two browsers showing different truths about the
    same robot.
    """

    id: str
    name: str
    description: str
    category: str
    status: str
    platforms: List[str] = field(default_factory=list)
    #: Route served by this process, a ``name#view`` deep link, or ``None``
    #: for artefacts with no URL. ``None`` renders as "no interface" rather
    #: than as a dead link — the difference matters to an operator clicking
    #: cards in a hurry.
    url: Optional[str] = None
    api_base: Optional[str] = None
    launch_command: Optional[str] = None
    icon: str = "app"
    #: ``False`` only for the legacy control panel. A client that can post
    #: motion is a different kind of thing from a dashboard, and the hub says
    #: so rather than letting the distinction evaporate.
    read_only: bool = True
    requires_robot: bool = False
    requires_camera: bool = False
    requires_hardware: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form for the JSON feed. Field names are public API."""
        return {
            "id": self.id,
            "name": self.name,
            "description": " ".join(self.description.split()),
            "category": self.category,
            "platforms": list(self.platforms),
            "url": self.url,
            "api_base": self.api_base,
            "launch_command": self.launch_command,
            "icon": self.icon,
            "read_only": self.read_only,
            "requires_robot": self.requires_robot,
            "requires_camera": self.requires_camera,
            "requires_hardware": self.requires_hardware,
            # The declared, verified baseline — what the file claimed before
            # the runtime got a chance to contradict it.
            "declared_status": self.status,
        }


@dataclass(frozen=True)
class RuntimeContext:
    """What is true about *this* running process, as far as it can tell.

    Deliberately narrow: the registry is not allowed to assume a camera, a
    robot, or an internet connection exists just because a config file
    mentions one.
    """

    #: ``True`` when the robot is the simulator. Legitimate, but it means no
    #: reading has touched physical hardware.
    mock_mode: bool = True
    #: ``True`` when the web server is serving. Always true from inside a
    #: request handler; kept explicit so the mobile client can reuse this
    #: dataclass when it probes a host that may be asleep.
    server_running: bool = True
    #: ``True`` only when a camera has actually produced a frame.
    camera_available: bool = False


class ApplicationRegistry:
    """An ordered, validated set of :class:`Application` entries."""

    def __init__(self, applications: List[Application]) -> None:
        self._apps: List[Application] = list(applications)
        validate_applications(self._apps)
        self._by_id = {a.id: a for a in self._apps}

    # -- reading ---------------------------------------------------------- #
    def all(self) -> List[Application]:
        """Every application, in the order declared by the config file."""
        return list(self._apps)

    def by_id(self, app_id: str) -> Optional[Application]:
        return self._by_id.get(app_id)

    def by_category(self, category: str) -> List[Application]:
        return [a for a in self._apps if a.category == category]

    def categories(self) -> List[str]:
        """Declared categories, in first-seen order (the hub renders these)."""
        seen: List[str] = []
        for a in self._apps:
            if a.category not in seen:
                seen.append(a.category)
        return seen

    def web_pages(self) -> List[Application]:
        """Applications that are actually openable pages.

        Anything with a ``#`` deep link counts; a pure API entry (``url`` is
        ``None``) does not. This is what stops ``/map`` — a JSON endpoint —
        from being rendered as a navigable card.
        """
        return [a for a in self._apps if a.url]

    def __len__(self) -> int:
        return len(self._apps)

    def __iter__(self):
        return iter(self._apps)

    # -- honest status ---------------------------------------------------- #
    def resolve_status(
        self, app: Application, context: Optional[RuntimeContext] = None
    ) -> Dict[str, Any]:
        """Report ``app``'s status *now*, never better than its baseline.

        Returns ``{"status": ..., "reason": ..., "detail": ...}`` where
        ``reason`` is machine-readable and ``detail`` is the sentence shown to
        the operator. The reason exists so tests (and the mobile client) can
        assert *why* a card is grey rather than pattern-matching prose.
        """
        ctx = context or RuntimeContext()
        baseline = app.status
        if baseline not in _RANK:
            # Defensive: a hand-edited file with a novel status must not be
            # silently promoted past every known value by a missing rank.
            raise ConfigError(f"unknown status for {app.id!r}: {baseline!r}")

        status, reason = baseline, "declared"

        if not ctx.server_running and app.url:
            status, reason = "OFFLINE", "server-unreachable"
        elif app.requires_camera and not ctx.camera_available:
            # Checked before mock_mode: "no camera" is the more specific and
            # more useful thing to tell someone looking at the camera card.
            status, reason = "HARDWARE REQUIRED", "no-camera"
        elif app.requires_robot and ctx.mock_mode and baseline == "AVAILABLE":
            status, reason = "MOCK", "mock-robot"

        # The never-upgrade guarantee, asserted rather than trusted.
        if _RANK[status] < _RANK[baseline]:
            status, reason = baseline, "declared"

        return {
            "status": status,
            "reason": reason,
            "detail": _DETAILS.get(status, status),
        }

    def payload(self, context: Optional[RuntimeContext] = None) -> Dict[str, Any]:
        """The full ``/applications/state`` document."""
        apps = []
        for app in self._apps:
            entry = app.to_dict()
            entry.update(self.resolve_status(app, context))
            apps.append(entry)
        return {
            "version": 1,
            "count": len(apps),
            "applications": apps,
            "categories": self.categories(),
        }
# --------------------------------------------------------------------------- #
# Loading + validation
# --------------------------------------------------------------------------- #
def _str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def load_applications(config_dir: Optional[str] = None) -> ApplicationRegistry:
    """Read ``config/applications.yaml`` into a validated registry.

    A missing file yields an **empty** registry rather than raising, matching
    every other optional config in this project: the robot must still boot if
    somebody deletes the file, because the registry is a convenience layer and
    not part of the control path. An empty registry renders an empty hub, which
    is honest, instead of taking the robot down.
    """
    cfg_dir = find_config_dir(config_dir)
    data = _load_yaml(Path(cfg_dir) / APPLICATIONS_FILE)
    blob = data.get("applications") if isinstance(data, dict) else None
    if not blob:
        return ApplicationRegistry([])
    if not isinstance(blob, list):
        raise ConfigError(f"{APPLICATIONS_FILE}: 'applications' must be a list")

    apps: List[Application] = []
    for i, raw in enumerate(blob):
        if not isinstance(raw, dict):
            raise ConfigError(f"{APPLICATIONS_FILE}: entry {i} must be a mapping")
        app_id = str(raw.get("id", "") or "").strip()
        if not app_id:
            raise ConfigError(f"{APPLICATIONS_FILE}: entry {i} has no id")
        apps.append(
            Application(
                id=app_id,
                name=str(raw.get("name", app_id)),
                description=str(raw.get("description", "")),
                category=str(raw.get("category", "")),
                status=str(raw.get("status", "")),
                platforms=_str_list(raw.get("platforms")),
                url=(None if raw.get("url") in (None, "") else str(raw["url"])),
                api_base=(
                    None if raw.get("api_base") in (None, "") else str(raw["api_base"])
                ),
                launch_command=(
                    None
                    if raw.get("launch_command") in (None, "")
                    else str(raw["launch_command"])
                ),
                icon=str(raw.get("icon", "app")),
                read_only=bool(raw.get("read_only", True)),
                requires_robot=bool(raw.get("requires_robot", False)),
                requires_camera=bool(raw.get("requires_camera", False)),
                requires_hardware=bool(raw.get("requires_hardware", False)),
            )
        )
    return ApplicationRegistry(apps)


def validate_applications(apps: List[Application]) -> None:
    """Fail loudly on a registry that could produce a broken or misleading hub.

    Each check maps to a concrete bad outcome in the UI, so these are not
    stylistic:
      * duplicate id     → two cards, one deep link, ambiguous telemetry
      * unknown category → the card falls out of every group and vanishes
      * unknown status   → the hub renders a status it cannot explain
      * url not starting with ``/`` → a relative link that escapes the app
        subtree, or an absolute URL to a host this project does not control
      * unknown platform → the platform filter silently omits the card
    """
    seen: set = set()
    for app in apps:
        if not app.id:
            raise ConfigError("application entry has an empty id")
        if app.id in seen:
            raise ConfigError(f"duplicate application id: {app.id!r}")
        seen.add(app.id)

        if app.category not in CATEGORIES:
            raise ConfigError(
                f"{app.id}: unknown category {app.category!r} "
                f"(known: {', '.join(CATEGORIES)})"
            )
        if app.status not in _RANK:
            raise ConfigError(
                f"{app.id}: unknown status {app.status!r} "
                f"(known: {', '.join(STATUSES)})"
            )
        if app.url is not None and not app.url.startswith("/"):
            raise ConfigError(
                f"{app.id}: url must be a path served by this process, "
                f"got {app.url!r}"
            )
        if app.api_base is not None and not app.api_base.startswith("/"):
            raise ConfigError(
                f"{app.id}: api_base must start with '/', got {app.api_base!r}"
            )
        for platform in app.platforms:
            if platform not in PLATFORMS:
                raise ConfigError(
                    f"{app.id}: unknown platform {platform!r} "
                    f"(known: {', '.join(PLATFORMS)})"
                )
        if app.url is None and app.category not in ("client", "reference"):
            # A monitoring/visualization card with no URL is a dead card. Only
            # `client` (artefacts) and `reference` (the API) may legitimately
            # have nothing to open.
            raise ConfigError(
                f"{app.id}: category {app.category!r} must declare a url or "
                f"the hub renders an empty card"
            )


