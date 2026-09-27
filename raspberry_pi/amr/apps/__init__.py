"""Application registry package: describes the interfaces this project ships.

See :mod:`amr.apps.registry` for the honesty rule that governs every status
this package reports.
"""

from __future__ import annotations

from .registry import (
    APPLICATIONS_FILE,
    CATEGORIES,
    PLATFORMS,
    STATUSES,
    Application,
    ApplicationRegistry,
    RuntimeContext,
    load_applications,
    validate_applications,
)

__all__ = [
    "APPLICATIONS_FILE",
    "CATEGORIES",
    "PLATFORMS",
    "STATUSES",
    "Application",
    "ApplicationRegistry",
    "RuntimeContext",
    "load_applications",
    "validate_applications",
]
