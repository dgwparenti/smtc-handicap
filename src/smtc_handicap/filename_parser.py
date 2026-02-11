"""Parse PDF filenames to extract date, event types, and race metadata."""

from __future__ import annotations

import re
from pathlib import Path

# Day-word to number mapping
DAY_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
}


def parse_pdf_filename(filename: str) -> dict:
    """Extract structured metadata from a PDF filename.

    Filename format: ``YYYYMMDD [components separated by +].pdf``

    Examples::

        "20260125 rt (Aris Vatimbella) + pt + pj + Splits.pdf"
        "20260208 rt (Brabazon Trophy) (Day 2) + rj (Roger Gibbs) + pj + Splits.pdf"
        "20260209 pt + pj + splits.pdf"

    Returns:
        Dict with keys: date, has_race_top, has_race_junction,
        has_practice_top, has_practice_junction, has_splits,
        race_name, day_number, original_filename
    """
    stem = Path(filename).stem

    # Extract date
    date_match = re.match(r"(\d{8})", stem)
    date_str = None
    if date_match:
        raw = date_match.group(1)
        date_str = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    remainder = stem[8:].strip() if date_match else stem

    # Split by + to get components
    components = [c.strip() for c in remainder.split("+")]
    remainder_lower = remainder.lower()

    has_race_top = bool(re.search(r"\brt\b", remainder_lower))
    has_race_junction = bool(re.search(r"\brj\b", remainder_lower))
    has_practice_top = bool(re.search(r"\bpt\b", remainder_lower))
    has_practice_junction = bool(re.search(r"\bpj\b", remainder_lower))
    has_splits = bool(re.search(r"\bsplits\b", remainder_lower))

    # Extract race name(s) from parentheses attached to rt or rj components
    race_name = None
    day_number = None

    for comp in components:
        comp_stripped = comp.strip()
        comp_lower = comp_stripped.lower()

        # Only look at race components (start with rt or rj)
        if not re.match(r"\b(rt|rj)\b", comp_lower):
            continue

        # Extract parenthesized portions
        parens = re.findall(r"\(([^)]+)\)", comp_stripped)
        for p in parens:
            p_lower = p.strip().lower()
            # Check for day number
            day_match = re.match(r"day\s+(\w+)", p_lower)
            if day_match:
                day_val = day_match.group(1)
                day_number = DAY_WORDS.get(day_val, int(day_val) if day_val.isdigit() else None)
            else:
                # It's a race name — use original case
                if race_name is None:
                    race_name = p.strip()

    return {
        "date": date_str,
        "has_race_top": has_race_top,
        "has_race_junction": has_race_junction,
        "has_practice_top": has_practice_top,
        "has_practice_junction": has_practice_junction,
        "has_splits": has_splits,
        "race_name": race_name,
        "day_number": day_number,
        "original_filename": filename,
    }
