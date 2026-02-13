"""Validation constants and functions for Cresta Run race data."""

from __future__ import annotations

import re

# Position-specific time bounds (seconds) for strict/analysis filtering
TIME_BOUNDS: dict[str, tuple[float, float]] = {
    "TOP": (49.0, 70.0),
    "JUNCTION": (41.0, 55.0),
}

# Absolute bounds for ingestion-time filtering (any position)
ABSOLUTE_MIN_TIME = 1.0
ABSOLUTE_MAX_TIME = 100.0

# Regex patterns matching team relay race names
TEAM_RELAY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"INTER.CLUB.CHALLENGE", re.IGNORECASE),
    re.compile(r"FAIRCHILDS?.MACCARTHY", re.IGNORECASE),
    re.compile(r"UNIVERSITY.CHALLENGE.CUP", re.IGNORECASE),
    re.compile(r"JOH.ANN.ES.BADRU.TT", re.IGNORECASE),
]

# Known misclassified races: race_id → correct start_position
RACE_POSITION_OVERRIDES: dict[str, str] = {
    "ARMY_UNOFFICIAL_JUNCTION_CHAMPIONSHIP_2025-01-20": "JUNCTION",
}


def is_team_relay_race(name: str) -> bool:
    """Return True if the race name matches a known team relay pattern."""
    return any(pat.search(name) for pat in TEAM_RELAY_PATTERNS)


def is_valid_finish_time(
    time: float | None,
    position: str | None = None,
    *,
    strict: bool = False,
) -> bool:
    """Check whether a finish time is valid.

    Parameters
    ----------
    time : finish time in seconds, or None (falls/DNFs are always valid)
    position : "TOP" or "JUNCTION" (required when strict=True)
    strict : if True, use position-specific bounds; if False, use absolute bounds
    """
    if time is None:
        return True

    if strict:
        if position is None:
            raise ValueError("position is required when strict=True")
        bounds = TIME_BOUNDS.get(position)
        if bounds is None:
            raise ValueError(f"Unknown position: {position!r}")
        lower, upper = bounds
    else:
        lower = ABSOLUTE_MIN_TIME
        upper = ABSOLUTE_MAX_TIME

    return lower <= time <= upper


def normalize_scratch_handicaps(handicaps: list[float]) -> list[float]:
    """Normalize handicaps so the best rider (lowest handicap) becomes scratch (0.0).

    Parameters
    ----------
    handicaps : list of handicap values for a single race

    Returns
    -------
    list of adjusted handicap values with min subtracted
    """
    if not handicaps:
        return []
    min_h = min(handicaps)
    if min_h == 0.0:
        return handicaps
    return [h - min_h for h in handicaps]
