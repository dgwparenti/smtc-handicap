"""Parse Cresta Run PDF results into structured data."""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from smtc_handicap.filename_parser import parse_pdf_filename
from smtc_handicap.models import Race, Rider, TimeRecord
from smtc_handicap.name_normalizer import normalize_rider_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_PAGE_BREAK = re.compile(r"^-\s*\d+\s*-$")
RE_FALL = re.compile(r"Fall\(([A-Za-z]+)\)", re.IGNORECASE)
RE_TIME_VALUE = re.compile(r"^\d+\.\d+$")
RE_PRACTICE_HEADER = re.compile(r"PRACTICE\s*-\s*(TOP|JUNCTION)", re.IGNORECASE)
RE_SPLIT_HEADER = re.compile(r"^Split\s+Results?$", re.IGNORECASE)
RE_HCAP_HEADER = re.compile(r"H.Cap", re.IGNORECASE)
RE_SECOND_DAY = re.compile(r"SECOND\s+DAY", re.IGNORECASE)
RE_NATIONALITY = re.compile(r"^[A-Z]{1,3}$")
RE_RANK = re.compile(r"^=?\d+$")
RE_RACE_HEADER = re.compile(
    r"^(?:THE\s+)?([A-Z][A-Z\s'\-]+?"
    r"(?:CUP|TROPHY|PLATE|PRIZE|CHALLENGE(?:\s+CUP)?|SHIELD|RACE|CHAMPIONSHIP"
    r"|SPOON|AWARD))",
    re.IGNORECASE,
)
RE_START_POS = re.compile(r"\(\s*(Top|Junction)\s*(?:,\s*)?(?:Handicap)?\s*\)", re.IGNORECASE)
RE_HANDICAP_FLAG = re.compile(r"Handicap", re.IGNORECASE)
RE_RNR = re.compile(r"\bRnR\b", re.IGNORECASE)
RE_SL_MARKER = re.compile(r"\bSL\b")
RE_AM_MARKER = re.compile(r"\(AM\)")
RE_STAR_MARKER = re.compile(r"\*\*\s*")


# ---------------------------------------------------------------------------
# Container dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A detected section within a PDF."""

    section_type: str  # RACE_HANDICAP, RACE_NON_HANDICAP, PRACTICE, SPLIT, METADATA
    header_line: str
    start_position: str  # TOP or JUNCTION
    race_name: str
    day_number: int | None
    lines: list[str] = field(default_factory=list)


@dataclass
class ParsedPDF:
    """Container for all data extracted from a single PDF."""

    filename: str
    races: list[Race] = field(default_factory=list)
    riders: list[Rider] = field(default_factory=list)
    time_records: list[TimeRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_all_text_lines(filepath: Path) -> list[str]:
    """Extract all text lines from a PDF, filtering page breaks and blanks."""
    all_lines: list[str] = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                if RE_PAGE_BREAK.match(stripped):
                    continue
                all_lines.append(stripped)
    return all_lines


# ---------------------------------------------------------------------------
# Column / cell parsing
# ---------------------------------------------------------------------------


def split_row_into_columns(line: str) -> list[str]:
    """Split a line on 2+ whitespace chars, keeping names intact."""
    return [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]


def parse_time_cell(cell: str) -> tuple[float | None, bool, str | None]:
    """Parse a time cell value.

    Returns (time_value, is_fall, fall_location).
    """
    cell = cell.strip()
    if not cell or cell == "-":
        return None, False, None

    fall_match = RE_FALL.match(cell)
    if fall_match:
        return None, True, fall_match.group(1).upper()

    if RE_TIME_VALUE.match(cell):
        return float(cell), False, None

    return None, False, None


# ---------------------------------------------------------------------------
# Rider extraction helpers
# ---------------------------------------------------------------------------


def _extract_rider_info(
    name_str: str, nat_str: str = ""
) -> tuple[str, str, str, bool, bool, bool]:
    """Extract rider details from name and nationality strings.

    Returns (display_name, rider_id, nationality, is_sl, is_am, is_rnr).
    """
    is_rnr = bool(RE_RNR.search(name_str))
    name_str = RE_RNR.sub("", name_str).strip()

    is_sl = bool(RE_SL_MARKER.search(name_str)) or bool(RE_SL_MARKER.search(nat_str))
    is_am = bool(RE_AM_MARKER.search(name_str))

    # Clean SL from both name and nationality
    clean_name = RE_SL_MARKER.sub("", name_str).strip()
    clean_name = RE_STAR_MARKER.sub("", clean_name).strip()
    clean_nat = RE_SL_MARKER.sub("", nat_str).strip()

    # Nationality might be embedded after SL in name column
    nationality = clean_nat
    if not nationality:
        # Try to extract from end of name
        parts = clean_name.rsplit(None, 1)
        if len(parts) == 2 and RE_NATIONALITY.match(parts[1]):
            clean_name = parts[0]
            nationality = parts[1]

    display_name = clean_name.strip()
    # Remove (AM) from display name for ID generation but keep in display
    id_name = RE_AM_MARKER.sub("", display_name).strip()

    try:
        rider_id = normalize_rider_id(id_name)
    except ValueError:
        rider_id = re.sub(r"\W+", "_", display_name.lower()).strip("_")

    return display_name, rider_id, nationality, is_sl, is_am, is_rnr


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------


RE_SKIP_HEADER = re.compile(
    r"^(?:THE\s+)?(Fastest\s|For\s+The\s|And\s+The\s|Club\s+Colours)",
    re.IGNORECASE,
)


def _is_subprize_line(line: str, lines: list[str], idx: int) -> bool:
    """Check if a race-header-like line is actually a sub-prize or metadata.

    Sub-prizes appear after 'and' on the previous line, are followed by
    '(for ...' / '(Individual ...' / '(Fastest ...' on the next line,
    or start with known metadata prefixes.
    """
    # Known metadata prefixes
    if RE_SKIP_HEADER.match(line):
        return True
    # Previous line is "and" or matches a race header (this is a sub-prize chained with "and")
    if idx > 0:
        prev = lines[idx - 1].strip().lower()
        if prev == "and":
            return True
        # If previous line is also a race-header-like line, check if we're part of a chain
        # "The Lord Trenchard Trophy" / "The Auty Speed Cup" after the main header
        if (prev.startswith("the ") or prev.startswith("for ")) and RE_RACE_HEADER.match(
            lines[idx - 1].strip()
        ):
            # This line is part of a multi-line header block
            return True
    # Next line starts with "(for", "(Individual", or "(Fastest"
    if idx + 1 < len(lines):
        nxt = lines[idx + 1].strip().lower()
        if nxt.startswith(("(for ", "(individual ", "(fastest ")):
            return True
    # Check if next line is another trophy/cup name (sub-prize chain)
    if idx + 1 < len(lines):
        nxt = lines[idx + 1].strip()
        if RE_RACE_HEADER.match(nxt):
            # Two consecutive race headers = sub-prize listing
            return True
    return False


def detect_sections(lines: list[str], filename_meta: dict) -> list[Section]:
    """Detect and classify sections within a PDF's text lines."""
    sections: list[Section] = []
    current: Section | None = None
    i = 0

    # Track which race positions we've seen to assign correctly
    race_top_used = False
    race_junction_used = False

    while i < len(lines):
        line = lines[i]

        # Check for Practice header
        practice_match = RE_PRACTICE_HEADER.search(line)
        if practice_match:
            pos = practice_match.group(1).upper()
            current = Section(
                section_type="PRACTICE",
                header_line=line,
                start_position=pos,
                race_name="PRACTICE",
                day_number=None,
            )
            sections.append(current)
            i += 1
            continue

        # Check for Split Results header
        if RE_SPLIT_HEADER.match(line):
            current = Section(
                section_type="SPLIT",
                header_line=line,
                start_position="",
                race_name="",
                day_number=None,
            )
            sections.append(current)
            i += 1
            continue

        # Check for Race header — skip sub-prize names and non-race headers
        race_match = RE_RACE_HEADER.match(line)
        if race_match and not _is_subprize_line(line, lines, i):
            race_name = race_match.group(1).strip()

            # Look ahead for start position and handicap flag
            start_pos = ""
            is_handicap = False
            day_number = filename_meta.get("day_number")

            for j in range(i + 1, min(i + 8, len(lines))):
                look_line = lines[j]
                pos_match = RE_START_POS.search(look_line)
                if pos_match:
                    start_pos = pos_match.group(1).upper()
                    if RE_HANDICAP_FLAG.search(look_line):
                        is_handicap = True
                if RE_SECOND_DAY.search(look_line) and day_number is None:
                    day_number = 2
                if RE_HCAP_HEADER.search(look_line):
                    is_handicap = True

            # Infer start position from filename if not found in text
            if not start_pos:
                if filename_meta.get("has_race_top") and not race_top_used:
                    start_pos = "TOP"
                elif filename_meta.get("has_race_junction") and not race_junction_used:
                    start_pos = "JUNCTION"
                else:
                    start_pos = "TOP"  # default

            if start_pos == "TOP":
                race_top_used = True
            else:
                race_junction_used = True

            section_type = "RACE_HANDICAP" if is_handicap else "RACE_NON_HANDICAP"

            current = Section(
                section_type=section_type,
                header_line=line,
                start_position=start_pos,
                race_name=race_name,
                day_number=day_number,
            )
            sections.append(current)
            i += 1
            continue

        # Append line to current section
        if current is not None:
            # Skip metadata-like lines
            if line.startswith("Fastest") or line.startswith("TOMORROW"):
                i += 1
                continue
            current.lines.append(line)

        i += 1

    return sections


# ---------------------------------------------------------------------------
# Race ID generation
# ---------------------------------------------------------------------------


def _make_race_id(
    name: str,
    start_pos: str,
    date: datetime.date,
    is_practice: bool,
    day_number: int | None = None,
) -> str:
    if is_practice:
        return f"PRACTICE_{start_pos}_{date.isoformat()}"
    slug = re.sub(r"^THE\s+", "", name, flags=re.IGNORECASE)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_").upper()
    if day_number:
        return f"{slug}_DAY{day_number}_{date.isoformat()}"
    return f"{slug}_{date.isoformat()}"


# ---------------------------------------------------------------------------
# Practice section parser
# ---------------------------------------------------------------------------


def _is_time_or_fall(tok: str) -> bool:
    """Check if a token is a time value or fall marker."""
    return bool(RE_TIME_VALUE.match(tok) or RE_FALL.match(tok))


def _parse_data_line(tokens: list[str]) -> tuple[list[str], str, list[str]]:
    """Split tokens into (name_tokens, nationality, time_tokens).

    Scans right-to-left to find times/falls, then nationality.
    """
    # Find where time/fall tokens start (scanning from right)
    first_time_idx = len(tokens)
    for i in range(len(tokens) - 1, -1, -1):
        if _is_time_or_fall(tokens[i]):
            first_time_idx = i
        else:
            break

    if first_time_idx >= len(tokens):
        # No time values found — try scanning left-to-right
        for i, tok in enumerate(tokens):
            if _is_time_or_fall(tok):
                first_time_idx = i
                break

    if first_time_idx >= len(tokens):
        return tokens, "", []

    time_tokens = tokens[first_time_idx:]
    pre_time = tokens[:first_time_idx]

    # Last pre-time token might be nationality (2-3 uppercase letters)
    nat = ""
    if pre_time and RE_NATIONALITY.match(pre_time[-1]):
        nat = pre_time[-1]
        pre_time = pre_time[:-1]

    return pre_time, nat, time_tokens


def parse_practice_section(
    section: Section, race_date: datetime.date, pdf_source: str
) -> tuple[Race, list[Rider], list[TimeRecord]]:
    """Parse a PRACTICE section."""
    race_id = _make_race_id("PRACTICE", section.start_position, race_date, is_practice=True)
    race = Race(
        race_id=race_id,
        name="PRACTICE",
        date=race_date,
        start_position=section.start_position,
        is_handicap_race=False,
        is_practice=True,
        pdf_source=pdf_source,
    )

    riders: list[Rider] = []
    records: list[TimeRecord] = []
    seen_riders: set[str] = set()

    for line in section.lines:
        # Skip header/footer/metadata lines
        if any(kw in line for kw in ["Fastest", "TOMORROW", "CRESTA", "Pilot"]):
            continue
        if re.match(r"^\d+(st|nd|rd|th)\s", line, re.IGNORECASE):
            continue

        tokens = line.split()
        if len(tokens) < 3:
            continue

        name_tokens, nat, time_tokens = _parse_data_line(tokens)

        if not name_tokens or not time_tokens:
            continue

        name_str = " ".join(name_tokens)
        display_name, rider_id, nationality, is_sl, is_am, _ = _extract_rider_info(name_str, nat)
        if not nationality:
            nationality = nat

        if rider_id not in seen_riders:
            riders.append(
                Rider(
                    rider_id=rider_id,
                    display_name=display_name,
                    nationality=nationality,
                    is_sl=is_sl,
                    is_am=is_am,
                    first_seen_date=race_date,
                )
            )
            seen_riders.add(rider_id)

        for run_idx, time_str in enumerate(time_tokens, 1):
            time_val, is_fall, fall_loc = parse_time_cell(time_str)
            if time_val is None and not is_fall:
                continue

            record_id = f"{race_id}_{rider_id}_{run_idx}"
            records.append(
                TimeRecord(
                    record_id=record_id,
                    race_id=race_id,
                    rider_id=rider_id,
                    run_number=run_idx,
                    finish_time=time_val,
                    is_fall=is_fall,
                    fall_location=fall_loc,
                    is_dnf=is_fall,
                )
            )

    return race, riders, records


# ---------------------------------------------------------------------------
# Race section parser (handicap)
# ---------------------------------------------------------------------------


def parse_race_section(
    section: Section, race_date: datetime.date, pdf_source: str
) -> tuple[Race, list[Rider], list[TimeRecord]]:
    """Parse a RACE_HANDICAP or RACE_NON_HANDICAP section."""
    is_handicap = section.section_type == "RACE_HANDICAP"
    is_day2 = section.day_number is not None and section.day_number >= 2

    race_id = _make_race_id(
        section.race_name,
        section.start_position,
        race_date,
        is_practice=False,
        day_number=section.day_number,
    )
    race = Race(
        race_id=race_id,
        name=section.race_name,
        date=race_date,
        start_position=section.start_position,
        is_handicap_race=is_handicap,
        is_practice=False,
        day_number=section.day_number,
        pdf_source=pdf_source,
    )

    riders: list[Rider] = []
    records: list[TimeRecord] = []
    seen_riders: set[str] = set()

    # Find the column header line to know where data starts
    data_start = 0
    for li, line in enumerate(section.lines):
        if RE_HCAP_HEADER.search(line):
            data_start = li + 1
            break
        if re.search(r"\b1st\b|\bFirst\s+Day\b", line, re.IGNORECASE):
            data_start = li + 1
            break

    for line in section.lines[data_start:]:
        # Skip metadata lines
        if any(
            kw in line
            for kw in [
                "Fastest",
                "TOMORROW",
                "CRESTA",
                "Pilot Course",
                "Pilot course",
                "Winner",
                "Course",
                "and THE",
                "and the",
                "BEGINNERS",
                "must be present",
                "Over.",
                "Riding but not Racing",
            ]
        ):
            continue
        if RE_START_POS.search(line) or RE_SECOND_DAY.search(line):
            continue

        tokens = line.split()
        if len(tokens) < 3:
            continue

        idx = 0
        # Skip rank at the beginning
        if RE_RANK.match(tokens[0]):
            idx = 1

        remaining = tokens[idx:]

        # Find the boundary between name and numeric data
        # Walk tokens: name parts, then nationality (2-3 uppercase),
        # then Scr/RnR/handicap, then times
        name_tokens: list[str] = []
        nat = ""
        data_tokens: list[str] = []
        is_rnr = False

        for ti, tok in enumerate(remaining):
            if _is_time_or_fall(tok):
                data_tokens = remaining[ti:]
                break
            if tok.upper() in ("SCR", "SCRATCH"):
                data_tokens = remaining[ti:]
                break
            if RE_RNR.match(tok):
                is_rnr = True
                # Next tokens are times
                data_tokens = remaining[ti + 1 :]
                break
            # Check for nationality — must have at least 1 name token before it
            if name_tokens and RE_NATIONALITY.match(tok) and tok.upper() != "SCR":
                # Peek ahead: next token should be a time, Scr, RnR, or Fall
                next_idx = ti + 1
                if next_idx < len(remaining):
                    nxt = remaining[next_idx]
                    if (
                        _is_time_or_fall(nxt)
                        or nxt.upper() in ("SCR", "SCRATCH")
                        or RE_RNR.match(nxt)
                    ):
                        nat = tok
                        data_tokens = remaining[next_idx:]
                        break
            name_tokens.append(tok)

        if not name_tokens:
            continue

        # Must have at least one time/fall
        if not data_tokens:
            continue

        name_str = " ".join(name_tokens)
        display_name, rider_id, nationality, is_sl, is_am, rnr2 = _extract_rider_info(
            name_str, nat
        )
        is_rnr = is_rnr or rnr2
        if not nationality:
            nationality = nat

        # Parse handicap value from data_tokens
        handicap_val: float | None = None
        time_start = 0

        if is_handicap and data_tokens:
            first = data_tokens[0]
            if first.upper() in ("SCR", "SCRATCH"):
                handicap_val = 0.0
                time_start = 1
            elif RE_RNR.match(first):
                is_rnr = True
                time_start = 1
            elif RE_TIME_VALUE.match(first):
                # In a handicap section, first numeric value is ALWAYS the handicap.
                # Handicap values are typically 0.50-10.00; run times are 40-80+.
                val = float(first)
                if val < 15.0:
                    handicap_val = val
                    time_start = 1
                else:
                    # Very large value → probably a time (shouldn't happen in handicap sections)
                    time_start = 0

        time_tokens_raw = data_tokens[time_start:]

        # For day 2 races, first time value is "First Day" cumulative — skip
        first_day_offset = 0
        if is_day2 and time_tokens_raw and RE_TIME_VALUE.match(time_tokens_raw[0]):
            val = float(time_tokens_raw[0])
            if val > 100:  # cumulative total is >> single run
                first_day_offset = 1

        all_times = time_tokens_raw[first_day_offset:]

        # Strip trailing totals (Total / Net Total)
        # Ranked rows with 3 runs have: time time time Total [NetTotal]
        actual_times = _strip_trailing_totals(all_times, is_handicap)

        if rider_id not in seen_riders:
            riders.append(
                Rider(
                    rider_id=rider_id,
                    display_name=display_name,
                    nationality=nationality,
                    is_sl=is_sl,
                    is_am=is_am,
                    first_seen_date=race_date,
                )
            )
            seen_riders.add(rider_id)

        run_number_start = 4 if is_day2 else 1
        for run_idx, time_str in enumerate(actual_times):
            time_val, is_fall, fall_loc = parse_time_cell(time_str)
            if time_val is None and not is_fall:
                continue

            run_num = run_number_start + run_idx
            record_id = f"{race_id}_{rider_id}_{run_num}"
            records.append(
                TimeRecord(
                    record_id=record_id,
                    race_id=race_id,
                    rider_id=rider_id,
                    run_number=run_num,
                    finish_time=time_val,
                    handicap=handicap_val,
                    is_fall=is_fall,
                    fall_location=fall_loc,
                    is_dnf=is_fall,
                )
            )

    return race, riders, records


def _strip_trailing_totals(times: list[str], is_handicap: bool) -> list[str]:
    """Remove trailing Total/Net Total columns from time list.

    For complete ranked rows: 3 run times + Total + (Net Total if handicap)
    For incomplete/DNF rows: fewer times, no totals to strip
    """
    # Count actual time/fall values
    valid = [t for t in times if _is_time_or_fall(t)]
    if not valid:
        return times

    # If handicap and >= 5 values: strip last 2 (Total + NetTotal)
    if is_handicap and len(valid) >= 5:
        return times[:-2]
    # If non-handicap and >= 4 values: strip last 1 (Total or GrandTotal)
    if not is_handicap and len(valid) >= 4:
        return times[:-1]

    return times


# ---------------------------------------------------------------------------
# Split results parser
# ---------------------------------------------------------------------------


def parse_split_section(
    section: Section,
    race_date: datetime.date,
    existing_records: list[TimeRecord],
) -> list[str]:
    """Parse Split Results and merge into existing TimeRecords.

    Returns a list of warnings.
    """
    warnings: list[str] = []

    # Build lookup: (rider_id, finish_time) -> list of TimeRecords
    by_rider: dict[str, list[TimeRecord]] = {}
    for rec in existing_records:
        by_rider.setdefault(rec.rider_id, []).append(rec)

    # Skip header line (column names)
    data_lines = []
    found_header = False
    for line in section.lines:
        if not found_header:
            if "Start" in line and ("Junction" in line or "Finish" in line):
                found_header = True
            continue
        data_lines.append(line)

    for line in data_lines:
        cols = split_row_into_columns(line)
        if len(cols) < 4:
            continue

        # Name is in SURNAME INITIALS [SL] format
        # Find where numeric data starts
        name_parts: list[str] = []
        data_start = 0
        for ci, col in enumerate(cols):
            # Check for start time (HH:MM:SS)
            if re.match(r"\d{1,2}:\d{2}:\d{2}", col):
                data_start = ci
                break
            name_parts.append(col)

        if not name_parts or data_start == 0:
            continue

        name_str = " ".join(name_parts)
        _, rider_id, _, _, _, _ = _extract_rider_info(name_str)

        data_cols = cols[data_start:]
        if not data_cols:
            continue

        # Parse start time
        start_time_obj = None
        try:
            parts = data_cols[0].split(":")
            start_time_obj = datetime.time(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            pass

        # Parse split values: Junction, Rise, Stream, Bulpetts, Finish, Speed
        split_vals = data_cols[1:]

        junction = _parse_split_val(split_vals, 0)
        rise = _parse_split_val(split_vals, 1)
        stream = _parse_split_val(split_vals, 2)
        bulpetts = _parse_split_val(split_vals, 3)
        finish = _parse_split_val(split_vals, 4)
        speed = _parse_split_val(split_vals, 5)

        # Check for fall in split values
        # Match to existing records for this rider
        rider_records = by_rider.get(rider_id, [])
        if not rider_records:
            warnings.append(f"Split: no records for rider {rider_id}")
            continue

        # Try to match by finish time
        matched = False
        for rec in rider_records:
            if (
                rec.finish_time is not None
                and finish is not None
                and abs(rec.finish_time - finish) < 0.05
            ):
                _merge_splits(rec, start_time_obj, junction, rise, stream, bulpetts, speed)
                matched = True
                break

        if not matched:
            # Match by sequential order - find next unmerged record
            for rec in rider_records:
                if rec.start_time is None:  # not yet merged
                    _merge_splits(rec, start_time_obj, junction, rise, stream, bulpetts, speed)
                    matched = True
                    break

        if not matched:
            warnings.append(f"Split: could not match {rider_id} finish={finish}")

    return warnings


def _parse_split_val(vals: list[str], idx: int) -> float | None:
    """Safely parse a split value at index."""
    if idx >= len(vals):
        return None
    val = vals[idx].strip()
    if RE_FALL.match(val):
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _merge_splits(
    rec: TimeRecord,
    start_time: datetime.time | None,
    junction: float | None,
    rise: float | None,
    stream: float | None,
    bulpetts: float | None,
    speed: float | None,
) -> None:
    """Merge split data into an existing TimeRecord."""
    rec.start_time = start_time
    rec.split_junction = junction
    rec.split_rise = rise
    rec.split_stream = stream
    rec.split_bulpetts = bulpetts
    rec.speed_mph = speed


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_pdf(filepath: Path) -> ParsedPDF:
    """Parse a Cresta Run PDF into structured data."""
    filename = filepath.name
    result = ParsedPDF(filename=filename)

    # 1. Parse filename metadata
    meta = parse_pdf_filename(filename)
    date_str = meta.get("date")
    if not date_str:
        result.warnings.append(f"Could not parse date from filename: {filename}")
        return result

    race_date = datetime.date.fromisoformat(date_str)

    # 2. Extract text
    try:
        lines = extract_all_text_lines(filepath)
    except Exception as e:
        result.warnings.append(f"Failed to extract text: {e}")
        return result

    if not lines:
        result.warnings.append("No text extracted from PDF")
        return result

    # 3. Detect sections
    sections = detect_sections(lines, meta)

    if not sections:
        result.warnings.append("No sections detected in PDF")
        return result

    # 4. Parse each section
    all_records: list[TimeRecord] = []

    for section in sections:
        try:
            if section.section_type == "PRACTICE":
                race, riders, records = parse_practice_section(section, race_date, filename)
                result.races.append(race)
                result.riders.extend(riders)
                result.time_records.extend(records)
                all_records.extend(records)

            elif section.section_type in ("RACE_HANDICAP", "RACE_NON_HANDICAP"):
                race, riders, records = parse_race_section(section, race_date, filename)
                result.races.append(race)
                result.riders.extend(riders)
                result.time_records.extend(records)
                all_records.extend(records)

            elif section.section_type == "SPLIT":
                warnings = parse_split_section(section, race_date, all_records)
                result.warnings.extend(warnings)

        except Exception as e:
            result.warnings.append(
                f"Error parsing section {section.section_type} ({section.header_line}): {e}"
            )

    # Deduplicate riders by rider_id
    seen: dict[str, Rider] = {}
    for rider in result.riders:
        if rider.rider_id not in seen:
            seen[rider.rider_id] = rider
    result.riders = list(seen.values())

    logger.info(
        "Parsed %s: %d races, %d riders, %d time_records, %d warnings",
        filename,
        len(result.races),
        len(result.riders),
        len(result.time_records),
        len(result.warnings),
    )

    return result
