"""LCD state model for the Command Center's physical-display mirror.

The 16×2 I2C LCD is **write-only** from the Pi: the firmware drives it, but there
is no read-back path. This module therefore produces two distinct things and
never conflates them:

* ``intended``  — the text the application *wants* the display to show, derived
  from the authoritative robot state. This is what the virtual preview renders.
* ``confirmed`` — always ``False`` (or a value the firmware reports, if it ever
  adds a read-back command). The dashboard must not present the intended text as
  proof the physical screen is showing it.

If the physical LCD is not connected, the preview is still useful — it shows the
*intended* content — but it is labeled as a virtual preview, not the physical
panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

#: The physical display is 16 columns x 2 rows.
LCD_COLUMNS = 16
LCD_ROWS = 2


def _fit(text: str, columns: int) -> str:
    """Pad or truncate a line to exactly ``columns`` characters."""
    text = (text or "").replace("\r", " ").replace("\n", " ")
    if len(text) > columns:
        return text[:columns]
    return text.ljust(columns)


@dataclass(frozen=True)
class LcdState:
    """The LCD panel's dashboard-facing state."""

    rows: List[str]
    #: True when a physical LCD is believed to be connected and writing.
    connected: bool
    #: True when the firmware has confirmed the content (read-back available).
    #: Always False today: the LCD is write-only.
    content_confirmed: bool
    #: The i2c address the firmware would use.
    address: Optional[int] = None
    #: Human note distinguishing intended vs confirmed.
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": self.rows,
            "columns": LCD_COLUMNS,
            "rows_count": LCD_ROWS,
            "connected": self.connected,
            "content_confirmed": self.content_confirmed,
            "address": (
                f"0x{self.address:02X}" if isinstance(self.address, int) else None
            ),
            "note": self.note,
        }


def build_lcd_state(
    telemetry: Dict[str, Any],
    *,
    connected: bool = False,
    address: int = 0x27,
    command_label: Optional[str] = None,
) -> LcdState:
    """Derive the intended two-row LCD content from the robot state.

    Row 0: operating mode + movement/mission summary.
    Row 1: the most important live number — a hazard, a safety reason, or the
    last accepted command (the dashboard's own history, not a claim about the
    physical screen).

    :param connected: whether a physical LCD is believed connected. The intended
        content is shown either way; this only affects the label.
    :param command_label: the last command accepted by the dashboard, if any.
        Shown on row 1 only when there is no higher-priority message.
    """
    t = telemetry if isinstance(telemetry, dict) else {}
    safety = t.get("safety") if isinstance(t.get("safety"), dict) else {}
    hazard = t.get("hazards") if isinstance(t.get("hazards"), dict) else {}
    nav = t.get("navigation") if isinstance(t.get("navigation"), dict) else {}
    mode = (t.get("mode") or safety.get("state") or "IDLE").upper()
    moving = bool(t.get("is_moving"))

    # Row 0: mode + motion/mission state.
    motion = "DRIVING" if moving else "STOPPED"
    row0 = f"{mode}  {motion}"

    # Row 1: priority order — safety fault > hazard > command > nav > clear.
    estop = bool(safety.get("emergency_stop"))
    reasons = safety.get("reasons") or []
    if estop or safety.get("state") == "SAFETY_STOP":
        row1 = "E-STOP / SAFETY"
    elif hazard.get("critical"):
        row1 = f"CRITICAL HAZARD"
    elif reasons:
        row1 = str(reasons[0])[:LCD_COLUMNS]
    elif hazard.get("active"):
        row1 = f"HAZARD: {str(hazard.get('kinds', [''])[0])[:9]}"
    elif command_label:
        row1 = command_label[:LCD_COLUMNS]
    elif nav.get("state"):
        row1 = f"NAV: {str(nav.get('state'))[:9]}"
    else:
        row1 = "READY"

    note = (
        "Physical LCD connected; content is intended, not read back."
        if connected
        else "Virtual preview — no physical LCD read-back available."
    )

    return LcdState(
        rows=[_fit(row0, LCD_COLUMNS), _fit(row1, LCD_COLUMNS)],
        connected=connected,
        content_confirmed=False,
        address=address,
        note=note,
    )
