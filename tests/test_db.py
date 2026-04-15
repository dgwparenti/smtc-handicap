"""Tests for the SQLite database layer."""

import datetime

import pytest

from smtc_handicap.db import CrestaDB
from smtc_handicap.models import Race, Rider, TimeRecord


@pytest.fixture()
def db():
    with CrestaDB(":memory:") as database:
        yield database


@pytest.fixture()
def sample_rider():
    return Rider(
        rider_id="bracher_bap",
        display_name="B.A.P. Bracher",
        nationality="GB",
        first_seen_date=datetime.date(2026, 1, 8),
    )


@pytest.fixture()
def sample_race():
    return Race(
        race_id="PRACTICE_TOP_2026-01-21",
        name="PRACTICE",
        date=datetime.date(2026, 1, 21),
        start_position="TOP",
        is_handicap_race=False,
        is_practice=True,
        pdf_source="test.pdf",
    )


@pytest.fixture()
def sample_record(sample_race, sample_rider):
    return TimeRecord(
        record_id=f"{sample_race.race_id}_{sample_rider.rider_id}_1",
        race_id=sample_race.race_id,
        rider_id=sample_rider.rider_id,
        run_number=1,
        finish_time=51.67,
    )


class TestRiderCRUD:
    def test_insert_and_get(self, db, sample_rider):
        db.upsert_rider(sample_rider)
        got = db.get_rider("bracher_bap")
        assert got is not None
        assert got.display_name == "B.A.P. Bracher"
        assert got.nationality == "GB"

    def test_upsert_keeps_display_name(self, db, sample_rider):
        db.upsert_rider(sample_rider)
        updated = Rider(
            rider_id="bracher_bap",
            display_name="DIFFERENT NAME",
            nationality="CH",
            first_seen_date=datetime.date(2026, 2, 1),
        )
        db.upsert_rider(updated)
        got = db.get_rider("bracher_bap")
        assert got.display_name == "B.A.P. Bracher"  # kept first seen

    def test_upsert_fills_empty_nationality(self, db):
        rider1 = Rider(rider_id="test", display_name="Test", nationality="")
        db.upsert_rider(rider1)
        rider2 = Rider(rider_id="test", display_name="Test", nationality="GB")
        db.upsert_rider(rider2)
        got = db.get_rider("test")
        assert got.nationality == "GB"

    def test_upsert_or_logic_flags(self, db):
        r1 = Rider(rider_id="test", display_name="Test", is_sl=True, is_am=False)
        db.upsert_rider(r1)
        r2 = Rider(rider_id="test", display_name="Test", is_sl=False, is_am=True)
        db.upsert_rider(r2)
        got = db.get_rider("test")
        assert got.is_sl is True
        assert got.is_am is True

    def test_upsert_keeps_earlier_date(self, db):
        r1 = Rider(
            rider_id="test",
            display_name="T",
            first_seen_date=datetime.date(2026, 1, 15),
        )
        db.upsert_rider(r1)
        r2 = Rider(
            rider_id="test",
            display_name="T",
            first_seen_date=datetime.date(2026, 1, 8),
        )
        db.upsert_rider(r2)
        got = db.get_rider("test")
        assert got.first_seen_date == datetime.date(2026, 1, 8)

    def test_get_nonexistent_returns_none(self, db):
        assert db.get_rider("nonexistent") is None

    def test_get_all_riders(self, db, sample_rider):
        db.upsert_rider(sample_rider)
        riders = db.get_all_riders()
        assert len(riders) == 1


class TestRaceCRUD:
    def test_insert_and_get(self, db, sample_race):
        db.insert_race(sample_race)
        got = db.get_race(sample_race.race_id)
        assert got is not None
        assert got.name == "PRACTICE"
        assert got.start_position == "TOP"

    def test_duplicate_insert_ignored(self, db, sample_race):
        db.insert_race(sample_race)
        db.insert_race(sample_race)  # should not raise
        assert db.race_exists(sample_race.race_id)

    def test_race_exists(self, db, sample_race):
        assert db.race_exists(sample_race.race_id) is False
        db.insert_race(sample_race)
        assert db.race_exists(sample_race.race_id) is True


class TestTimeRecordCRUD:
    def test_insert_and_get(self, db, sample_rider, sample_race, sample_record):
        db.upsert_rider(sample_rider)
        db.insert_race(sample_race)
        db.insert_time_record(sample_record)
        records = db.get_time_records_for_rider(sample_rider.rider_id)
        assert len(records) == 1
        assert records[0].finish_time == 51.67

    def test_duplicate_record_ignored(self, db, sample_rider, sample_race, sample_record):
        db.upsert_rider(sample_rider)
        db.insert_race(sample_race)
        db.insert_time_record(sample_record)
        db.insert_time_record(sample_record)  # should not raise
        records = db.get_time_records_for_race(sample_race.race_id)
        assert len(records) == 1


class TestDeleteByPdfSource:
    def test_deletes_races_and_records(self, db, sample_rider, sample_race, sample_record):
        db.upsert_rider(sample_rider)
        db.insert_race(sample_race)
        db.insert_time_record(sample_record)

        deleted = db.delete_by_pdf_source("test.pdf")

        assert deleted == 1
        assert db.get_race(sample_race.race_id) is None
        assert db.get_time_records_for_race(sample_race.race_id) == []

    def test_unknown_source_returns_zero(self, db):
        deleted = db.delete_by_pdf_source("nonexistent.pdf")
        assert deleted == 0

    def test_riders_preserved(self, db, sample_rider, sample_race, sample_record):
        db.upsert_rider(sample_rider)
        db.insert_race(sample_race)
        db.insert_time_record(sample_record)

        db.delete_by_pdf_source("test.pdf")

        assert db.get_rider(sample_rider.rider_id) is not None


class TestCounts:
    def test_empty_db_counts(self, db):
        counts = db.get_counts()
        assert counts["riders"] == 0
        assert counts["races"] == 0
        assert counts["time_records"] == 0

    def test_counts_after_insert(self, db, sample_rider, sample_race, sample_record):
        db.upsert_rider(sample_rider)
        db.insert_race(sample_race)
        db.insert_time_record(sample_record)
        counts = db.get_counts()
        assert counts["riders"] == 1
        assert counts["races"] == 1
        assert counts["time_records"] == 1


class TestGetRacesByPosition:
    def test_returns_top_races_sorted_by_date_desc(self, db):
        db.insert_race(
            Race(
                race_id="HANDICAP_TOP_2026-01-15",
                name="HANDICAP",
                date=datetime.date(2026, 1, 15),
                start_position="TOP",
                is_handicap_race=True,
                is_practice=False,
            )
        )
        db.insert_race(
            Race(
                race_id="HANDICAP_JUNCTION_2026-01-20",
                name="HANDICAP",
                date=datetime.date(2026, 1, 20),
                start_position="JUNCTION",
                is_handicap_race=True,
                is_practice=False,
            )
        )
        db.insert_race(
            Race(
                race_id="PRACTICE_TOP_2026-01-10",
                name="PRACTICE",
                date=datetime.date(2026, 1, 10),
                start_position="TOP",
                is_handicap_race=False,
                is_practice=True,
            )
        )

        top_races = db.get_races_by_position("TOP")

        assert len(top_races) == 2
        assert top_races[0].race_id == "HANDICAP_TOP_2026-01-15"
        assert top_races[0].date == datetime.date(2026, 1, 15)
        assert top_races[1].race_id == "PRACTICE_TOP_2026-01-10"
        assert top_races[1].date == datetime.date(2026, 1, 10)

    def test_returns_junction_races(self, db):
        db.insert_race(
            Race(
                race_id="HANDICAP_TOP_2026-01-15",
                name="HANDICAP",
                date=datetime.date(2026, 1, 15),
                start_position="TOP",
                is_handicap_race=True,
                is_practice=False,
            )
        )
        db.insert_race(
            Race(
                race_id="HANDICAP_JUNCTION_2026-01-20",
                name="HANDICAP",
                date=datetime.date(2026, 1, 20),
                start_position="JUNCTION",
                is_handicap_race=True,
                is_practice=False,
            )
        )
        db.insert_race(
            Race(
                race_id="PRACTICE_TOP_2026-01-10",
                name="PRACTICE",
                date=datetime.date(2026, 1, 10),
                start_position="TOP",
                is_handicap_race=False,
                is_practice=True,
            )
        )

        junction_races = db.get_races_by_position("JUNCTION")

        assert len(junction_races) == 1
        assert junction_races[0].race_id == "HANDICAP_JUNCTION_2026-01-20"
