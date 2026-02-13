"""Tests for the database cleanup script."""

from __future__ import annotations

import sqlite3

import pytest

# Import cleanup functions directly from the script
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cleanup_db import (  # noqa: E402
    step1_remove_junk_times,
    step2_remove_team_relays,
    step3_fix_misclassified_positions,
    step4_remove_extreme_times,
    step5_normalize_handicaps,
    step6_populate_scratch_riders,
    step7_remove_orphan_races,
    step8_remove_orphan_riders,
)


@pytest.fixture()
def conn():
    """In-memory DB with sample bad data for cleanup testing."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=OFF")  # simplify test setup
    c.executescript(
        """
        CREATE TABLE riders (
            rider_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            nationality TEXT NOT NULL DEFAULT '',
            is_sl INTEGER NOT NULL DEFAULT 0,
            is_am INTEGER NOT NULL DEFAULT 0,
            first_seen_date TEXT NOT NULL
        );
        CREATE TABLE races (
            race_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            start_position TEXT NOT NULL,
            is_handicap_race INTEGER NOT NULL DEFAULT 0,
            is_practice INTEGER NOT NULL DEFAULT 0,
            day_number INTEGER,
            pdf_source TEXT NOT NULL DEFAULT '',
            scratch_rider_id TEXT DEFAULT NULL
        );
        CREATE TABLE time_records (
            record_id TEXT PRIMARY KEY,
            race_id TEXT NOT NULL,
            rider_id TEXT NOT NULL,
            run_number INTEGER NOT NULL,
            start_time TEXT,
            split_junction REAL,
            split_rise REAL,
            split_stream REAL,
            split_bulpetts REAL,
            finish_time REAL,
            speed_mph REAL,
            handicap REAL,
            is_fall INTEGER NOT NULL DEFAULT 0,
            fall_location TEXT,
            is_dnf INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    # -- Sample riders --
    c.execute("INSERT INTO riders VALUES ('rider_a', 'Rider A', 'GB', 0, 0, '2025-01-01')")
    c.execute("INSERT INTO riders VALUES ('rider_b', 'Rider B', 'CH', 0, 0, '2025-01-01')")
    c.execute("INSERT INTO riders VALUES ('orphan_rider', 'Orphan', '', 0, 0, '2025-01-01')")
    c.execute("INSERT INTO riders VALUES ('club_team', 'Some Club', '', 0, 0, '2025-01-01')")

    # -- Normal TOP race --
    c.execute(
        "INSERT INTO races VALUES "
        "('HEATON_2025-01-15', 'HEATON GOLD CUP', '2025-01-15', 'TOP', 0, 0, NULL, '', NULL)"
    )
    c.execute(
        "INSERT INTO time_records VALUES "
        "('rec1', 'HEATON_2025-01-15', 'rider_a', 1, NULL, NULL, NULL, NULL, NULL, "
        "55.0, NULL, NULL, 0, NULL, 0)"
    )
    c.execute(
        "INSERT INTO time_records VALUES "
        "('rec2', 'HEATON_2025-01-15', 'rider_b', 1, NULL, NULL, NULL, NULL, NULL, "
        "57.0, NULL, NULL, 0, NULL, 0)"
    )

    # -- Junk sub-1s time --
    c.execute(
        "INSERT INTO time_records VALUES "
        "('junk1', 'HEATON_2025-01-15', 'rider_a', 2, NULL, NULL, NULL, NULL, NULL, "
        "0.3, NULL, NULL, 0, NULL, 0)"
    )

    # -- Extreme >100s time --
    c.execute(
        "INSERT INTO time_records VALUES "
        "('extreme1', 'HEATON_2025-01-15', 'rider_b', 2, NULL, NULL, NULL, NULL, NULL, "
        "250.0, NULL, NULL, 0, NULL, 0)"
    )

    # -- Relay race --
    c.execute(
        "INSERT INTO races VALUES "
        "('INTER_CLUB_CHALLENGE_2025-02-01', 'INTER CLUB CHALLENGE', '2025-02-01', "
        "'TOP', 0, 0, NULL, '', NULL)"
    )
    c.execute(
        "INSERT INTO time_records VALUES "
        "('relay1', 'INTER_CLUB_CHALLENGE_2025-02-01', 'club_team', 1, "
        "NULL, NULL, NULL, NULL, NULL, 180.0, NULL, NULL, 0, NULL, 0)"
    )

    # -- Misclassified race (TOP but all times in JUNCTION range) --
    c.execute(
        "INSERT INTO races VALUES "
        "('ARMY_UNOFFICIAL_JUNCTION_CHAMPIONSHIP_2025-01-20', "
        "'ARMY UNOFFICIAL JUNCTION CHAMPIONSHIP', '2025-01-20', 'TOP', 0, 0, NULL, '', NULL)"
    )
    c.execute(
        "INSERT INTO time_records VALUES "
        "('mis1', 'ARMY_UNOFFICIAL_JUNCTION_CHAMPIONSHIP_2025-01-20', 'rider_a', 1, "
        "NULL, NULL, NULL, NULL, NULL, 44.0, NULL, NULL, 0, NULL, 0)"
    )
    c.execute(
        "INSERT INTO time_records VALUES "
        "('mis2', 'ARMY_UNOFFICIAL_JUNCTION_CHAMPIONSHIP_2025-01-20', 'rider_b', 1, "
        "NULL, NULL, NULL, NULL, NULL, 46.0, NULL, NULL, 0, NULL, 0)"
    )

    # -- Handicap race with min_handicap > 0 --
    c.execute(
        "INSERT INTO races VALUES "
        "('HCAP_2025-01-25', 'SOME HANDICAP', '2025-01-25', 'TOP', 1, 0, NULL, '', NULL)"
    )
    c.execute(
        "INSERT INTO time_records VALUES "
        "('hcap1', 'HCAP_2025-01-25', 'rider_a', 1, NULL, NULL, NULL, NULL, NULL, "
        "54.0, NULL, 3.0, 0, NULL, 0)"
    )
    c.execute(
        "INSERT INTO time_records VALUES "
        "('hcap2', 'HCAP_2025-01-25', 'rider_b', 1, NULL, NULL, NULL, NULL, NULL, "
        "56.0, NULL, 5.5, 0, NULL, 0)"
    )

    # -- Orphan race (no time records) --
    c.execute(
        "INSERT INTO races VALUES "
        "('ORPHAN_RACE_2025-02-10', 'ORPHAN RACE', '2025-02-10', 'TOP', 0, 0, NULL, '', NULL)"
    )

    c.commit()
    yield c
    c.close()


class TestStep1JunkTimes:
    def test_removes_sub_1s_times(self, conn):
        count = step1_remove_junk_times(conn)
        assert count == 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM time_records WHERE finish_time < 1.0"
        ).fetchone()[0]
        assert remaining == 0

    def test_dry_run_preserves_data(self, conn):
        count = step1_remove_junk_times(conn, dry_run=True)
        assert count == 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM time_records WHERE finish_time < 1.0"
        ).fetchone()[0]
        assert remaining == 1


class TestStep2TeamRelays:
    def test_removes_relay_races(self, conn):
        count = step2_remove_team_relays(conn)
        assert count == 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM races WHERE race_id = 'INTER_CLUB_CHALLENGE_2025-02-01'"
        ).fetchone()[0]
        assert remaining == 0
        # Records for that race should also be gone
        relay_records = conn.execute(
            "SELECT COUNT(*) FROM time_records WHERE race_id = 'INTER_CLUB_CHALLENGE_2025-02-01'"
        ).fetchone()[0]
        assert relay_records == 0


class TestStep3MisclassifiedPositions:
    def test_fixes_override(self, conn):
        count = step3_fix_misclassified_positions(conn)
        assert count >= 1
        row = conn.execute(
            "SELECT start_position FROM races "
            "WHERE race_id = 'ARMY_UNOFFICIAL_JUNCTION_CHAMPIONSHIP_2025-01-20'"
        ).fetchone()
        assert row[0] == "JUNCTION"


class TestStep4ExtremeTimes:
    def test_removes_over_100s(self, conn):
        count = step4_remove_extreme_times(conn)
        assert count >= 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM time_records WHERE finish_time > 100.0"
        ).fetchone()[0]
        assert remaining == 0


class TestStep5NormalizeHandicaps:
    def test_normalizes_handicaps(self, conn):
        count = step5_normalize_handicaps(conn)
        assert count == 1
        handicaps = conn.execute(
            "SELECT handicap FROM time_records WHERE race_id = 'HCAP_2025-01-25' ORDER BY handicap"
        ).fetchall()
        assert handicaps[0][0] == pytest.approx(0.0)
        assert handicaps[1][0] == pytest.approx(2.5)


class TestStep6PopulateScratch:
    def test_populates_scratch_rider(self, conn):
        # First normalize handicaps so someone is at 0.0
        step5_normalize_handicaps(conn)
        count = step6_populate_scratch_riders(conn)
        assert count == 1
        row = conn.execute(
            "SELECT scratch_rider_id FROM races WHERE race_id = 'HCAP_2025-01-25'"
        ).fetchone()
        assert row[0] == "rider_a"  # fastest time (54.0)


class TestStep7OrphanRaces:
    def test_removes_orphan_races(self, conn):
        count = step7_remove_orphan_races(conn)
        assert count >= 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM races WHERE race_id = 'ORPHAN_RACE_2025-02-10'"
        ).fetchone()[0]
        assert remaining == 0


class TestStep8OrphanRiders:
    def test_removes_orphan_riders(self, conn):
        # Run cleanup steps that remove records first
        step1_remove_junk_times(conn)
        step2_remove_team_relays(conn)
        step4_remove_extreme_times(conn)
        count = step8_remove_orphan_riders(conn)
        # orphan_rider has no records; club_team records were deleted with relay
        assert count >= 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM riders WHERE rider_id = 'orphan_rider'"
        ).fetchone()[0]
        assert remaining == 0
