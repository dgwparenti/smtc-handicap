"""Data layer for the Handicap Explorer UI.

Provides query functions and a BayesianModel wrapper for extracting
rider/field summaries from the CrestaDB and the fitted Stan model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from smtc_handicap.db import CrestaDB

# Outlier bounds per start position (wider than model training bounds —
# we want to show the full distribution, just exclude clearly erroneous values).
OUTLIER_BOUNDS: dict[str, tuple[float, float]] = {
    "TOP": (45.0, 120.0),
    "JUNCTION": (35.0, 90.0),
}


def get_season_label(season_year: int) -> str:
    """Format a season year as 'YYYY/YY', e.g. 2026 -> '2025/26'."""
    start = season_year - 1
    end_short = str(season_year)[-2:]
    return f"{start}/{end_short}"


def _date_to_season(date_str: str) -> int:
    """Map a race date string to its Cresta season year.

    The Cresta season runs roughly Nov–Mar. Dates in Oct+ belong to the
    following year's season; Jan–Sep belong to the current year.
    """
    parts = date_str.split("-")
    year, month = int(parts[0]), int(parts[1])
    return year + 1 if month >= 10 else year


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RiderTimeSummary:
    """Summary of a rider's times for one start position."""

    rider_id: str
    display_name: str
    position: str
    all_times: list[float] = field(default_factory=list)
    season_times: list[float] = field(default_factory=list)
    best_ever: float | None = None
    season_best: float | None = None
    estimated_time: float | None = None
    estimated_source: str = ""  # "Bayesian" or "empirical"


@dataclass
class FieldTimeSummary:
    """Summary of all riders' times for one start position."""

    position: str
    all_times: list[float] = field(default_factory=list)
    n_riders: int = 0
    median_time: float | None = None


@dataclass
class HandicapComparison:
    """Handicap comparison between two riders."""

    scratch_summary: RiderTimeSummary
    rider_summary: RiderTimeSummary
    handicap_value: float | None = None
    handicap_source: str = ""  # "Bayesian" or "empirical"


# ---------------------------------------------------------------------------
# Bayesian model wrapper
# ---------------------------------------------------------------------------


class BayesianModel:
    """Wrapper around the fitted Stan model (NetCDF inference data)."""

    def __init__(self, nc_path: str | Path, db: CrestaDB) -> None:
        import arviz as az

        idata = az.from_netcdf(str(nc_path))

        self.rider_map: dict[str, int] = json.loads(idata.attrs["rider_map"])
        self.season_num: np.ndarray = idata.constant_data["season_num"].values
        self.alpha_mean: np.ndarray = idata.posterior["alpha"].mean(dim=["chain", "draw"]).values
        self.beta_trend_mean: np.ndarray = (
            idata.posterior["beta_trend"].mean(dim=["chain", "draw"]).values
        )
        self.season_lookup = self._build_season_lookup(db)

    def _build_season_lookup(self, db: CrestaDB) -> dict[int, float]:
        """Map season_year -> centered season_num value."""
        max_date = db.conn.execute(
            "SELECT MAX(date) FROM races WHERE start_position = 'TOP'"
        ).fetchone()[0]
        if max_date is None:
            return {}
        max_season = _date_to_season(max_date)
        mean_year = max_season - self.season_num[-1]
        season_years = np.round(self.season_num + mean_year).astype(int)
        return dict(zip(season_years.tolist(), self.season_num.tolist(), strict=False))

    def get_estimated_time(self, rider_id: str, season_year: int) -> float | None:
        """Return posterior-mean estimated time for a rider in a season."""
        if rider_id not in self.rider_map:
            return None
        season_num_val = self.season_lookup.get(season_year)
        if season_num_val is None:
            return None
        j = self.rider_map[rider_id] - 1  # Stan 1-indexed → Python 0-indexed
        return float(self.alpha_mean[j] + self.beta_trend_mean[j] * season_num_val)


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


def get_available_seasons(db: CrestaDB) -> list[tuple[int, str]]:
    """Return (season_year, label) pairs sorted most-recent first."""
    rows = db.conn.execute("SELECT DISTINCT date FROM races").fetchall()
    season_years = {_date_to_season(r[0]) for r in rows}
    sorted_years = sorted(season_years, reverse=True)
    return [(y, get_season_label(y)) for y in sorted_years]


def get_rider_options(db: CrestaDB) -> list[tuple[str, str]]:
    """Return (rider_id, display_name) for riders with at least one finish time.

    Sorted alphabetically by display_name.
    """
    rows = db.conn.execute(
        """SELECT DISTINCT rd.rider_id, rd.display_name
           FROM riders rd
           JOIN time_records tr ON rd.rider_id = tr.rider_id
           WHERE tr.finish_time IS NOT NULL
             AND tr.is_fall = 0 AND tr.is_dnf = 0
           ORDER BY rd.display_name"""
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _get_valid_times(
    db: CrestaDB,
    rider_id: str,
    position: str,
    season_year: int | None = None,
) -> list[float]:
    """Fetch valid finish times for a rider/position, optionally filtered by season."""
    lo, hi = OUTLIER_BOUNDS[position]
    if season_year is not None:
        # Build date range for the season
        start_date = f"{season_year - 1}-10-01"
        end_date = f"{season_year}-09-30"
        rows = db.conn.execute(
            """SELECT tr.finish_time FROM time_records tr
               JOIN races r ON tr.race_id = r.race_id
               WHERE tr.rider_id = ? AND r.start_position = ?
                 AND tr.is_fall = 0 AND tr.is_dnf = 0
                 AND tr.finish_time IS NOT NULL
                 AND tr.finish_time BETWEEN ? AND ?
                 AND r.date BETWEEN ? AND ?""",
            (rider_id, position, lo, hi, start_date, end_date),
        ).fetchall()
    else:
        rows = db.conn.execute(
            """SELECT tr.finish_time FROM time_records tr
               JOIN races r ON tr.race_id = r.race_id
               WHERE tr.rider_id = ? AND r.start_position = ?
                 AND tr.is_fall = 0 AND tr.is_dnf = 0
                 AND tr.finish_time IS NOT NULL
                 AND tr.finish_time BETWEEN ? AND ?""",
            (rider_id, position, lo, hi),
        ).fetchall()
    return [r[0] for r in rows]


def _get_field_times(db: CrestaDB, position: str) -> tuple[list[float], int]:
    """Fetch all valid finish times for a position and the count of distinct riders."""
    lo, hi = OUTLIER_BOUNDS[position]
    rows = db.conn.execute(
        """SELECT tr.finish_time FROM time_records tr
           JOIN races r ON tr.race_id = r.race_id
           WHERE r.start_position = ?
             AND tr.is_fall = 0 AND tr.is_dnf = 0
             AND tr.finish_time IS NOT NULL
             AND tr.finish_time BETWEEN ? AND ?""",
        (position, lo, hi),
    ).fetchall()
    times = [r[0] for r in rows]
    n_riders = db.conn.execute(
        """SELECT COUNT(DISTINCT tr.rider_id) FROM time_records tr
           JOIN races r ON tr.race_id = r.race_id
           WHERE r.start_position = ?
             AND tr.is_fall = 0 AND tr.is_dnf = 0
             AND tr.finish_time IS NOT NULL
             AND tr.finish_time BETWEEN ? AND ?""",
        (position, lo, hi),
    ).fetchone()[0]
    return times, n_riders


def get_rider_time_summary(
    db: CrestaDB,
    rider_id: str,
    position: str,
    season_year: int,
    model: BayesianModel | None = None,
) -> RiderTimeSummary:
    """Build a RiderTimeSummary for a rider on a given position/season."""
    display_name = ""
    rider = db.get_rider(rider_id)
    if rider:
        display_name = rider.display_name

    all_times = _get_valid_times(db, rider_id, position)
    season_times = _get_valid_times(db, rider_id, position, season_year)

    best_ever = min(all_times) if all_times else None
    season_best = min(season_times) if season_times else None

    estimated_time = None
    estimated_source = ""
    if model is not None:
        estimated_time = model.get_estimated_time(rider_id, season_year)
    if estimated_time is not None:
        estimated_source = "Bayesian"
    elif all_times:
        estimated_time = float(np.median(all_times))
        estimated_source = "empirical"

    return RiderTimeSummary(
        rider_id=rider_id,
        display_name=display_name,
        position=position,
        all_times=all_times,
        season_times=season_times,
        best_ever=best_ever,
        season_best=season_best,
        estimated_time=estimated_time,
        estimated_source=estimated_source,
    )


def get_field_time_summary(db: CrestaDB, position: str) -> FieldTimeSummary:
    """Build a FieldTimeSummary for all riders on a given position."""
    times, n_riders = _get_field_times(db, position)
    median_time = float(np.median(times)) if times else None
    return FieldTimeSummary(
        position=position,
        all_times=times,
        n_riders=n_riders,
        median_time=median_time,
    )


def get_handicap_comparison(
    db: CrestaDB,
    scratch_id: str,
    compared_id: str,
    position: str,
    season_year: int,
    model: BayesianModel | None = None,
) -> HandicapComparison:
    """Compute handicap between a compared rider and a scratch rider."""
    scratch_summary = get_rider_time_summary(db, scratch_id, position, season_year, model)
    rider_summary = get_rider_time_summary(db, compared_id, position, season_year, model)

    handicap_value = None
    handicap_source = ""

    if scratch_summary.estimated_time is not None and rider_summary.estimated_time is not None:
        handicap_value = rider_summary.estimated_time - scratch_summary.estimated_time
        # Source is the weaker of the two
        if (
            rider_summary.estimated_source == "Bayesian"
            and scratch_summary.estimated_source == "Bayesian"
        ):
            handicap_source = "Bayesian"
        else:
            handicap_source = "empirical"

    return HandicapComparison(
        scratch_summary=scratch_summary,
        rider_summary=rider_summary,
        handicap_value=handicap_value,
        handicap_source=handicap_source,
    )
