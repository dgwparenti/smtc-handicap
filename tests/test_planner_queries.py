"""Tests for Handicap Planner query helpers."""

import datetime

import pytest

pytest.importorskip("scipy", reason="scipy not installed (install with [ui])")

pytestmark = pytest.mark.ui

from smtc_handicap.db import CrestaDB  # noqa: E402
from smtc_handicap.models import Race, Rider, TimeRecord  # noqa: E402
from smtc_handicap.ui.queries import (  # noqa: E402
    get_races_for_position,
    match_riders_from_names,
)


@pytest.fixture()
def db():
    with CrestaDB(":memory:") as database:
        for rid, name in [
            ("buhler_n", "N. Bühler"),
            ("von_wrede_c", "C. von Wrede"),
            ("parenti_d", "D. Parenti"),
            ("lloyd_p", "P. Lloyd"),
        ]:
            database.upsert_rider(
                Rider(rider_id=rid, display_name=name, first_seen_date=datetime.date(2024, 1, 1))
            )
        database.insert_race(
            Race(
                race_id="HEIDSCHI_2026-02-08",
                name="HEIDSCHI CUP",
                date=datetime.date(2026, 2, 8),
                start_position="TOP",
                is_handicap_race=True,
                is_practice=False,
            )
        )
        database.insert_race(
            Race(
                race_id="PRAC_2026-02-07",
                name="PRACTICE",
                date=datetime.date(2026, 2, 7),
                start_position="TOP",
                is_handicap_race=False,
                is_practice=True,
            )
        )
        for rid in ["buhler_n", "parenti_d", "lloyd_p"]:
            database.insert_time_record(
                TimeRecord(
                    record_id=f"HEIDSCHI_2026-02-08_{rid}_1",
                    race_id="HEIDSCHI_2026-02-08",
                    rider_id=rid,
                    run_number=1,
                    finish_time=55.0,
                )
            )
        yield database


class TestMatchRidersFromNames:
    def test_exact_match(self, db):
        matches, unmatched = match_riders_from_names(db, ["N. Bühler", "D. Parenti"])
        assert len(matches) == 2
        assert len(unmatched) == 0
        matched_ids = {m[0] for m in matches}
        assert "buhler_n" in matched_ids
        assert "parenti_d" in matched_ids

    def test_normalized_match(self, db):
        # Use names whose normalize_rider_id output matches the stored rider_ids
        # (e.g. "Lloyd P." -> "lloyd_p", "Parenti D." -> "parenti_d")
        matches, unmatched = match_riders_from_names(db, ["Lloyd P.", "Parenti D."])
        assert len(matches) == 2

    def test_unmatched_names(self, db):
        matches, unmatched = match_riders_from_names(db, ["N. Bühler", "Z. Nobody"])
        assert len(matches) == 1
        assert "Z. Nobody" in unmatched

    def test_empty_input(self, db):
        matches, unmatched = match_riders_from_names(db, [])
        assert len(matches) == 0
        assert len(unmatched) == 0


class TestGetRacesForPosition:
    def test_returns_races_with_labels(self, db):
        races = get_races_for_position(db, "TOP")
        assert len(races) >= 1
        race_ids = [r[0] for r in races]
        assert "HEIDSCHI_2026-02-08" in race_ids

    def test_label_contains_date(self, db):
        races = get_races_for_position(db, "TOP")
        for _race_id, label in races:
            assert "—" in label
