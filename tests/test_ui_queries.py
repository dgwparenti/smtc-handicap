"""Tests for the Handicap Explorer UI data layer."""

import datetime

import pytest

pytest.importorskip("scipy", reason="scipy not installed (install with [ui])")

pytestmark = pytest.mark.ui

from smtc_handicap.db import CrestaDB  # noqa: E402
from smtc_handicap.models import Race, Rider, TimeRecord  # noqa: E402
from smtc_handicap.ui.queries import (  # noqa: E402
    HandicapComparison,
    _date_to_season,
    get_available_seasons,
    get_field_time_summary,
    get_handicap_comparison,
    get_rider_options,
    get_rider_time_summary,
    get_season_label,
)


@pytest.fixture()
def db():
    with CrestaDB(":memory:") as database:
        yield database


def _insert_rider(db: CrestaDB, rider_id: str, display_name: str) -> None:
    db.upsert_rider(
        Rider(
            rider_id=rider_id, display_name=display_name, first_seen_date=datetime.date(2024, 1, 1)
        )
    )


def _insert_race(
    db: CrestaDB,
    race_id: str,
    date: datetime.date,
    position: str = "TOP",
    is_handicap: bool = False,
) -> None:
    db.insert_race(
        Race(
            race_id=race_id,
            name=race_id,
            date=date,
            start_position=position,
            is_handicap_race=is_handicap,
            is_practice=False,
        )
    )


def _insert_record(
    db: CrestaDB,
    race_id: str,
    rider_id: str,
    run: int,
    finish_time: float | None = None,
    is_fall: bool = False,
    is_dnf: bool = False,
) -> None:
    db.insert_time_record(
        TimeRecord(
            record_id=f"{race_id}_{rider_id}_{run}",
            race_id=race_id,
            rider_id=rider_id,
            run_number=run,
            finish_time=finish_time,
            is_fall=is_fall,
            is_dnf=is_dnf,
        )
    )


@pytest.fixture()
def populated_db(db):
    """DB with two riders, two seasons, TOP and JUNCTION races."""
    _insert_rider(db, "fast_rider", "A. Fast")
    _insert_rider(db, "slow_rider", "B. Slow")

    # Season 2025 (Jan 2025)
    _insert_race(db, "race_top_s1", datetime.date(2025, 1, 15), "TOP")
    _insert_race(db, "race_jct_s1", datetime.date(2025, 1, 15), "JUNCTION")
    # Season 2026 (Jan 2026)
    _insert_race(db, "race_top_s2", datetime.date(2026, 1, 10), "TOP")
    _insert_race(db, "race_jct_s2", datetime.date(2026, 1, 10), "JUNCTION")

    # fast_rider: TOP times across seasons
    _insert_record(db, "race_top_s1", "fast_rider", 1, 52.0)
    _insert_record(db, "race_top_s1", "fast_rider", 2, 53.0)
    _insert_record(db, "race_top_s1", "fast_rider", 3, 51.5)
    _insert_record(db, "race_top_s2", "fast_rider", 1, 51.0)
    _insert_record(db, "race_top_s2", "fast_rider", 2, 52.5)

    # fast_rider: JUNCTION times
    _insert_record(db, "race_jct_s1", "fast_rider", 1, 42.0)
    _insert_record(db, "race_jct_s2", "fast_rider", 1, 41.5)

    # slow_rider: TOP times
    _insert_record(db, "race_top_s1", "slow_rider", 1, 58.0)
    _insert_record(db, "race_top_s2", "slow_rider", 1, 57.0)
    _insert_record(db, "race_top_s2", "slow_rider", 2, 59.0)

    # A fall and a DNF (should be excluded)
    _insert_record(db, "race_top_s2", "fast_rider", 3, None, is_fall=True)
    _insert_record(db, "race_top_s2", "slow_rider", 3, None, is_dnf=True)

    return db


class TestSeasonLogic:
    def test_season_label(self):
        assert get_season_label(2026) == "2025/26"
        assert get_season_label(2020) == "2019/20"

    def test_date_to_season_jan(self):
        assert _date_to_season("2026-01-15") == 2026

    def test_date_to_season_oct(self):
        assert _date_to_season("2025-10-01") == 2026

    def test_date_to_season_nov(self):
        assert _date_to_season("2025-11-15") == 2026

    def test_date_to_season_sep(self):
        assert _date_to_season("2025-09-30") == 2025


class TestGetAvailableSeasons:
    def test_returns_seasons_sorted_desc(self, populated_db):
        seasons = get_available_seasons(populated_db)
        years = [s[0] for s in seasons]
        assert years == [2026, 2025]
        assert seasons[0][1] == "2025/26"

    def test_empty_db(self, db):
        assert get_available_seasons(db) == []


class TestGetRiderOptions:
    def test_returns_riders_with_times(self, populated_db):
        options = get_rider_options(populated_db)
        ids = [o[0] for o in options]
        assert "fast_rider" in ids
        assert "slow_rider" in ids

    def test_sorted_by_name(self, populated_db):
        options = get_rider_options(populated_db)
        names = [o[1] for o in options]
        assert names == sorted(names)

    def test_excludes_rider_with_no_finish(self, db):
        _insert_rider(db, "ghost", "G. Host")
        _insert_race(db, "r1", datetime.date(2026, 1, 1), "TOP")
        _insert_record(db, "r1", "ghost", 1, None, is_fall=True)
        assert get_rider_options(db) == []

    def test_empty_db(self, db):
        assert get_rider_options(db) == []


class TestRiderTimeSummary:
    def test_all_times(self, populated_db):
        summary = get_rider_time_summary(populated_db, "fast_rider", "TOP", 2026)
        assert len(summary.all_times) == 5  # 3 from s1 + 2 from s2
        assert summary.best_ever == 51.0
        assert summary.display_name == "A. Fast"

    def test_season_times(self, populated_db):
        summary = get_rider_time_summary(populated_db, "fast_rider", "TOP", 2026)
        assert len(summary.season_times) == 2  # only s2 times
        assert summary.season_best == 51.0

    def test_previous_season(self, populated_db):
        summary = get_rider_time_summary(populated_db, "fast_rider", "TOP", 2025)
        assert len(summary.season_times) == 3

    def test_empirical_estimated_time(self, populated_db):
        summary = get_rider_time_summary(populated_db, "fast_rider", "TOP", 2026)
        assert summary.estimated_time is not None
        assert summary.estimated_source == "empirical"

    def test_junction_times(self, populated_db):
        summary = get_rider_time_summary(populated_db, "fast_rider", "JUNCTION", 2026)
        assert len(summary.all_times) == 2
        assert summary.best_ever == 41.5

    def test_no_data(self, populated_db):
        summary = get_rider_time_summary(populated_db, "slow_rider", "JUNCTION", 2026)
        assert summary.all_times == []
        assert summary.best_ever is None
        assert summary.estimated_time is None

    def test_falls_excluded(self, populated_db):
        summary = get_rider_time_summary(populated_db, "fast_rider", "TOP", 2026)
        # Should not include the fall
        assert all(t is not None for t in summary.all_times)


class TestFieldTimeSummary:
    def test_top_field(self, populated_db):
        summary = get_field_time_summary(populated_db, "TOP")
        # 5 fast_rider + 3 slow_rider = 8 valid TOP times
        assert len(summary.all_times) == 8
        assert summary.n_riders == 2
        assert summary.median_time is not None

    def test_junction_field(self, populated_db):
        summary = get_field_time_summary(populated_db, "JUNCTION")
        assert len(summary.all_times) == 2
        assert summary.n_riders == 1

    def test_empty(self, db):
        summary = get_field_time_summary(db, "TOP")
        assert summary.all_times == []
        assert summary.median_time is None


class TestHandicapComparison:
    def test_basic_comparison(self, populated_db):
        comp = get_handicap_comparison(populated_db, "fast_rider", "slow_rider", "TOP", 2026)
        assert isinstance(comp, HandicapComparison)
        assert comp.handicap_value is not None
        # slow_rider should be slower → positive handicap
        assert comp.handicap_value > 0
        assert comp.handicap_source == "empirical"

    def test_same_rider(self, populated_db):
        comp = get_handicap_comparison(populated_db, "fast_rider", "fast_rider", "TOP", 2026)
        assert comp.handicap_value == 0.0

    def test_no_data_for_one(self, populated_db):
        comp = get_handicap_comparison(populated_db, "fast_rider", "slow_rider", "JUNCTION", 2026)
        # slow_rider has no JUNCTION data
        assert comp.handicap_value is None


class TestSingleDataPoint:
    def test_single_time(self, db):
        _insert_rider(db, "solo", "S. Olo")
        _insert_race(db, "r1", datetime.date(2026, 1, 1), "TOP")
        _insert_record(db, "r1", "solo", 1, 55.0)

        summary = get_rider_time_summary(db, "solo", "TOP", 2026)
        assert len(summary.all_times) == 1
        assert summary.best_ever == 55.0
        assert summary.estimated_time == 55.0  # median of single value
