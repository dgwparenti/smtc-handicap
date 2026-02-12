"""Parse Cresta Run JSON results into structured data."""

from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from smtc_handicap.models import Race, Rider, TimeRecord
from smtc_handicap.name_normalizer import normalize_rider_id
from smtc_handicap.pdf_parser import make_race_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Country ID → 2-letter code mapping (SMTC timing system IDs)
# ---------------------------------------------------------------------------

COUNTRY_ID_MAP: dict[int, str] = {
    7: "AU",
    9: "BE",
    15: "CA",
    17: "DE",
    19: "FR",
    20: "GR",
    21: "GB",
    22: "NL",
    28: "IT",
    35: "NZ",
    38: "AT",
    40: "PT",
    41: "ZA",
    44: "SE",
    45: "CH",
    46: "LI",
    51: "US",
    53: "ES",
    84: "PL",
    92: "IE",
}

RE_DAY_NUMBER = re.compile(r"day-(\d+)")
RE_FALL_DESC = re.compile(r"Fall\(([A-Za-z]+)\)", re.IGNORECASE)
RE_PRACTICE_POS = re.compile(r"PRACTICE\s*-\s*(TOP|JUNCTION)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Container dataclass
# ---------------------------------------------------------------------------


@dataclass
class ParsedJSON:
    """Container for all data extracted from a single JSON file."""

    filename: str
    races: list[Race] = field(default_factory=list)
    riders: list[Rider] = field(default_factory=list)
    time_records: list[TimeRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_country_code(country_id: int) -> str:
    """Map a SMTC timing system country ID to a 2-letter code."""
    return COUNTRY_ID_MAP.get(country_id, "")


def parse_start_time(t_start: str | None) -> datetime.time | None:
    """Extract time component from an ISO datetime string."""
    if not t_start:
        return None
    try:
        dt = datetime.datetime.fromisoformat(t_start)
        return dt.time()
    except (ValueError, TypeError):
        return None


def extract_day_number(filename: str) -> int | None:
    """Extract day number from a filename like 'curzon-day-2-2020-01-12.json'."""
    m = RE_DAY_NUMBER.search(filename)
    return int(m.group(1)) if m else None


def get_day_courses(course_details: list[dict], day_number: int) -> set[int]:
    """Get the set of CourseNums belonging to a given day (1-based).

    Uses CourseDetails dates to group courses by day.
    Falls back to courses 1-3 = day 1, 4-6 = day 2 if CourseDetails is empty.
    """
    if not course_details:
        if day_number == 1:
            return {1, 2, 3}
        if day_number == 2:
            return {4, 5, 6}
        return set()

    date_to_courses: dict[str, list[int]] = {}
    for cd in course_details:
        date_str = cd["CourseDate"][:10]
        date_to_courses.setdefault(date_str, []).append(cd["CourseNum"])

    sorted_dates = sorted(date_to_courses.keys())
    if day_number <= len(sorted_dates):
        return set(date_to_courses[sorted_dates[day_number - 1]])
    return set()


def parse_fall_description(fall_desc: str | None) -> tuple[bool, str | None]:
    """Parse a FallDescription like 'Fall(S)' into (is_fall, fall_location)."""
    if not fall_desc:
        return False, None
    m = RE_FALL_DESC.search(fall_desc)
    if m:
        return True, m.group(1).upper()
    return False, None


def _nz(val: float | None) -> float | None:
    """Return val if positive, else None (converts 0.0 → None)."""
    return val if val and val > 0 else None


def _get_start_position(data: dict) -> str:
    """Determine start position (TOP or JUNCTION) from JSON event data."""
    if data.get("IsPractice"):
        m = RE_PRACTICE_POS.search(data.get("EventName", ""))
        if m:
            return m.group(1).upper()

    course_details = data.get("CourseDetails", [])
    if course_details:
        cs = course_details[0].get("CourseStart", "T")
        return "TOP" if cs == "T" else "JUNCTION"

    rides = data.get("Rides", [])
    if rides:
        cs = rides[0].get("CourseStart", "T")
        return "TOP" if cs == "T" else "JUNCTION"

    return "TOP"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_json(filepath: Path) -> ParsedJSON:
    """Parse a Cresta Run JSON results file into structured data."""
    filename = filepath.name
    result = ParsedJSON(filename=filename)

    with open(filepath) as f:
        data = json.load(f)

    # -- Event metadata --
    event_name = data.get("EventName", "").strip()
    event_date_str = data.get("EventDate", "")[:10]
    if not event_date_str:
        result.warnings.append(f"No EventDate in {filename}")
        return result

    race_date = datetime.date.fromisoformat(event_date_str)
    is_practice = data.get("IsPractice", False)
    is_handicap = data.get("EventType") == "H"
    start_position = _get_start_position(data)

    # -- Multi-day handling --
    day_number = extract_day_number(filename)
    course_details = data.get("CourseDetails", [])
    day_courses: set[int] | None = None
    if day_number is not None:
        day_courses = get_day_courses(course_details, day_number)

    # -- Build Race --
    race_name = "PRACTICE" if is_practice else event_name
    race_id = make_race_id(
        race_name,
        start_position,
        race_date,
        is_practice=is_practice,
        day_number=day_number,
    )
    result.races.append(
        Race(
            race_id=race_id,
            name=race_name,
            date=race_date,
            start_position=start_position,
            is_handicap_race=is_handicap,
            is_practice=is_practice,
            day_number=day_number,
            pdf_source=filename,
        )
    )

    # -- Process rides --
    seen_ride_ids: set[int] = set()
    seen_riders: dict[str, Rider] = {}

    for ride in data.get("Rides", []):
        # Deduplicate by RideId within file
        ride_id_val = ride.get("RideId")
        if ride_id_val in seen_ride_ids:
            continue
        seen_ride_ids.add(ride_id_val)

        # Multi-day filtering
        course_num = ride.get("CourseNum", 1)
        if day_courses is not None and course_num not in day_courses:
            continue

        # -- Rider info --
        name_print = ride.get("NamePrint", "").strip()
        if not name_print:
            continue

        country_id = ride.get("RidingCountryId", 0)
        nationality = get_country_code(country_id)
        is_sl = ride.get("IsSL", False)
        is_am = "(AM)" in name_print

        try:
            rider_id = normalize_rider_id(name_print)
        except ValueError:
            rider_id = re.sub(r"\W+", "_", name_print.lower()).strip("_")

        if rider_id not in seen_riders:
            seen_riders[rider_id] = Rider(
                rider_id=rider_id,
                display_name=name_print,
                nationality=nationality,
                is_sl=is_sl,
                is_am=is_am,
                first_seen_date=race_date,
            )

        # -- Timing data --
        t_run = ride.get("T_Run", 0.0) or 0.0
        is_fall, fall_location = parse_fall_description(ride.get("FallDescription"))
        is_not_racing = ride.get("NotRacing", False)

        finish_time = None if is_fall else (t_run if t_run > 0 else None)

        # Skip rides with no useful data
        if finish_time is None and not is_fall:
            continue

        # Run number
        run_number = ride.get("RideNr", 1) if is_practice else course_num

        # Splits (0.0 → None)
        split_junction = _nz(ride.get("T_Junction"))
        split_rise = _nz(ride.get("T_Rise"))
        split_stream = _nz(ride.get("T_Stream"))
        split_bulpetts = _nz(ride.get("T_Bulpetts"))

        # Speed (only if > 1.0)
        speed = ride.get("Speed", 0.0) or 0.0
        speed_mph = speed if speed > 1.0 else None

        # Handicap (only for handicap races; None for RnR)
        handicap: float | None = None
        if is_handicap and not is_not_racing:
            handicap = ride.get("T_HCP", 0.0)

        # Start time
        start_time = parse_start_time(ride.get("T_Start"))

        record_id = f"{race_id}_{rider_id}_{run_number}"
        result.time_records.append(
            TimeRecord(
                record_id=record_id,
                race_id=race_id,
                rider_id=rider_id,
                run_number=run_number,
                start_time=start_time,
                split_junction=split_junction,
                split_rise=split_rise,
                split_stream=split_stream,
                split_bulpetts=split_bulpetts,
                finish_time=finish_time,
                speed_mph=speed_mph,
                handicap=handicap,
                is_fall=is_fall,
                fall_location=fall_location,
                is_dnf=is_fall or is_not_racing,
            )
        )

    result.riders = list(seen_riders.values())

    logger.info(
        "Parsed %s: %d races, %d riders, %d time_records, %d warnings",
        filename,
        len(result.races),
        len(result.riders),
        len(result.time_records),
        len(result.warnings),
    )

    return result
