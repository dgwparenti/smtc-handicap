"""Data model classes for Cresta Run race data."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass
class Race:
    """A single race or practice session."""

    race_id: str  # e.g. "STAGNI_CUP_2026-01-21" or "PRACTICE_TOP_2026-01-21"
    name: str  # e.g. "THE STAGNI CUP" or "PRACTICE"
    date: datetime.date
    start_position: str  # "TOP" or "JUNCTION"
    is_handicap_race: bool
    is_practice: bool
    day_number: int | None = None
    pdf_source: str = ""


@dataclass
class Rider:
    """A rider (tobogganist) on the Cresta Run."""

    rider_id: str  # normalized ID, e.g. "rueda_fp_jnr"
    display_name: str  # as first seen, e.g. "F.P. Rueda (Jnr)"
    nationality: str = ""
    is_sl: bool = False  # Supplementary List
    is_am: bool = False  # Amateur
    first_seen_date: datetime.date = field(default_factory=lambda: datetime.date(2099, 1, 1))


@dataclass
class TimeRecord:
    """A single timed run by a rider in a race or practice."""

    record_id: str  # "{race_id}_{rider_id}_{run_number}"
    race_id: str
    rider_id: str
    run_number: int  # 1-based
    # Splits (populated from Split Results section if present)
    start_time: datetime.time | None = None
    split_junction: float | None = None
    split_rise: float | None = None
    split_stream: float | None = None
    split_bulpetts: float | None = None
    finish_time: float | None = None  # total seconds; None if fall/DNF
    speed_mph: float | None = None
    # Handicap
    handicap: float | None = None  # 0.0 = scratch, None = non-handicap race
    # Status
    is_fall: bool = False
    fall_location: str | None = None  # "S", "TH", "JS", "CH", "BA", "ST"
    is_dnf: bool = False
