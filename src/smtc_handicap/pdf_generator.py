"""Generate archival PDFs from embedded race JSON data."""

from __future__ import annotations

import logging
from pathlib import Path

from fpdf import FPDF

logger = logging.getLogger(__name__)

# Layout constants
PAGE_W = 210  # A4 width mm
MARGIN = 10
COL_GAP = 2


def _format_time(raw: str | int | float | None) -> str:
    """Format a time value, returning '-' for empty/None/zero."""
    if raw is None:
        return "-"
    if isinstance(raw, (int, float)):
        if raw == 0 or raw == 0.0:
            return "-"
        return f"{raw:.2f}"
    raw = str(raw).strip()
    if raw in ("", "0", "0.0", "00:00.00"):
        return "-"
    return raw


def _rider_display_name(ride: dict) -> str:
    """Get the best display name for a rider."""
    return ride.get("NamePrint") or ride.get("NameSort") or "Unknown"


def _fall_text(ride: dict) -> str:
    """Build a fall description string."""
    desc = ride.get("FallDescription", "")
    if desc:
        return f"Fall({desc})"
    return ""


def _sort_time(val: str | int | float | None) -> float:
    """Convert a time value to a float for sorting. Missing/zero → infinity."""
    if val is None:
        return float("inf")
    if isinstance(val, (int, float)):
        return float("inf") if val == 0 else float(val)
    try:
        f = float(val)
        return float("inf") if f == 0 else f
    except (ValueError, TypeError):
        return float("inf")


def _build_practice_rows(race_data: dict) -> list[list[str]]:
    """Build table rows for a practice event."""
    rides = race_data.get("Rides", [])
    # Filter out scratched / not-racing
    rides = [r for r in rides if not r.get("IsScratched") and not r.get("NotRacing")]
    # Sort by total time (riders with no time go last)
    rides.sort(key=lambda r: _sort_time(r.get("T_Total")))

    rows = []
    for r in rides:
        fall = _fall_text(r)
        time_val = _format_time(r.get("T_Total"))
        if fall:
            time_val = fall
        rows.append([
            _rider_display_name(r),
            r.get("CourseStart", ""),
            time_val,
            _format_time(r.get("Speed")),
        ])
    return rows


def _build_race_rows(race_data: dict) -> tuple[list[str], list[list[str]]]:
    """Build table header and rows for a race event.

    Uses Standings if available, otherwise falls back to Rides.
    """
    standings = race_data.get("Standings", [])
    if standings:
        header = ["Pos", "Name", "H'Cap", "Time", "Total"]
        rows = []
        for s in standings:
            rows.append([
                str(s.get("Position", "")),
                s.get("NamePrint") or s.get("NameSort") or "Unknown",
                _format_time(s.get("T_HCP")),
                _format_time(s.get("T_Total")),
                _format_time(s.get("T_Net")),
            ])
        return header, rows

    # Fallback to Rides
    rides = race_data.get("Rides", [])
    rides = [r for r in rides if not r.get("IsScratched") and not r.get("NotRacing")]
    rides.sort(key=lambda r: (r.get("Position") or 999, _sort_time(r.get("T_Total"))))

    header = ["Pos", "Name", "H'Cap", "Time", "Speed", "Falls"]
    rows = []
    for r in rides:
        rows.append([
            str(r.get("Position", "")),
            _rider_display_name(r),
            _format_time(r.get("T_HCP")),
            _format_time(r.get("T_Total")),
            _format_time(r.get("Speed")),
            _fall_text(r),
        ])
    return header, rows


def generate_results_pdf(race_data: dict, output_path: Path) -> Path | None:
    """Generate a results PDF from parsed race JSON data.

    Args:
        race_data: Parsed JSON dict with EventName, Rides, Standings, etc.
        output_path: Full path for the output PDF file.

    Returns:
        Path to the generated PDF, or None if output already exists.
    """
    if output_path.exists():
        logger.debug("PDF already exists: %s", output_path.name)
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    event_name = race_data.get("EventName", "Unknown Event")
    event_date = race_data.get("EventDate", "")
    is_practice = race_data.get("IsPractice", False)

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, event_name, new_x="LMARGIN", new_y="NEXT", align="C")
    if event_date:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, event_date, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    if is_practice:
        header = ["Name", "Start", "Time", "Speed"]
        col_widths = [80, 15, 30, 25]
        rows = _build_practice_rows(race_data)
    else:
        header, rows = _build_race_rows(race_data)
        if len(header) == 5:
            col_widths = [15, 70, 25, 30, 30]
        else:
            col_widths = [15, 60, 25, 30, 20, 40]

    # Table header
    pdf.set_font("Helvetica", "B", 9)
    for i, h in enumerate(header):
        pdf.cell(col_widths[i], 7, h, border=1, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 8)
    for row in rows:
        for i, cell in enumerate(row):
            align = "L" if i == 1 or (is_practice and i == 0) else "C"
            pdf.cell(col_widths[i], 6, cell, border=1, align=align)
        pdf.ln()

    pdf.output(str(output_path))
    logger.info("Generated PDF: %s (%d rows)", output_path.name, len(rows))
    return output_path
