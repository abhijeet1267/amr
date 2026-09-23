"""Mock camera for tests and mock mode.

The real camera must degrade gracefully when unavailable. This mock lets
tests and ``--mock`` mode cover the camera states (available, unavailable,
error) without touching any imaging library.

``capture()`` returns **real JPEG bytes** (a minimal 1x1 image) so the full
image pipeline — ``CameraManager.capture_jpeg()`` and the web ``/image``
endpoint — can be exercised in mock mode. It never returns ``None`` while
available, and mock mode stays dependency-free (no numpy, no cv2).
"""

from __future__ import annotations

import base64
from typing import Optional

#: A valid, minimal 1x1 JPEG (SOI .. EOI) as base64. Serves as a stand-in
#: frame so HTTP content-type / decode checks are meaningful in tests.
_JPEG_1PX_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA"
    "/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEA"
    "AD8AKp//2Q=="
)


class MockCamera:
    """A virtual camera with controllable availability and frame source."""

    #: Advertised frame size (the real frame is the 1x1 JPEG stand-in).
    frame_size = (1280, 720)

    def __init__(self, available: bool = True, jpeg: Optional[bytes] = None):
        self._available = available
        self._jpeg = (
            bytes(jpeg)
            if jpeg is not None
            else base64.b64decode(_JPEG_1PX_B64)
        )
        self.capture_count = 0

    def set_available(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def capture(self) -> Optional[bytes]:
        """Return a JPEG frame, or ``None`` when unavailable."""
        if not self._available:
            return None
        self.capture_count += 1
        return self._jpeg
