"""Tests for data model classes."""

import datetime

from smtc_handicap.models import Race, Rider, TimeRecord


class TestRace:
    def test_create_practice(self):
        race = Race(
            race_id="PRACTICE_TOP_2026-01-21",
            name="PRACTICE",
            date=datetime.date(2026, 1, 21),
            start_position="TOP",
            is_handicap_race=False,
            is_practice=True,
        )
        assert race.race_id == "PRACTICE_TOP_2026-01-21"
        assert race.day_number is None
        assert race.pdf_source == ""

    def test_create_handicap_race(self):
        race = Race(
            race_id="STAGNI_CUP_2026-01-21",
            name="THE STAGNI CUP",
            date=datetime.date(2026, 1, 21),
            start_position="TOP",
            is_handicap_race=True,
            is_practice=False,
            day_number=None,
            pdf_source="20260121 rt (Stagni Cup) + pt + pj + splits.pdf",
        )
        assert race.is_handicap_race is True
        assert race.is_practice is False

    def test_multi_day_race(self):
        race = Race(
            race_id="BRABAZON_TROPHY_DAY2_2026-02-08",
            name="THE BRABAZON TROPHY",
            date=datetime.date(2026, 2, 8),
            start_position="TOP",
            is_handicap_race=False,
            is_practice=False,
            day_number=2,
        )
        assert race.day_number == 2


class TestRider:
    def test_create_basic(self):
        rider = Rider(rider_id="bracher_bap", display_name="B.A.P. Bracher")
        assert rider.nationality == ""
        assert rider.is_sl is False
        assert rider.is_am is False
        assert rider.first_seen_date == datetime.date(2099, 1, 1)

    def test_create_with_flags(self):
        rider = Rider(
            rider_id="hooper_tj",
            display_name="T.J. Hooper",
            nationality="GB",
            is_sl=True,
            is_am=True,
            first_seen_date=datetime.date(2026, 1, 8),
        )
        assert rider.is_sl is True
        assert rider.is_am is True


class TestTimeRecord:
    def test_create_normal(self):
        rec = TimeRecord(
            record_id="PRACTICE_TOP_2026-01-21_bracher_bap_1",
            race_id="PRACTICE_TOP_2026-01-21",
            rider_id="bracher_bap",
            run_number=1,
            finish_time=51.67,
        )
        assert rec.finish_time == 51.67
        assert rec.is_fall is False
        assert rec.handicap is None

    def test_create_fall(self):
        rec = TimeRecord(
            record_id="test_1",
            race_id="test",
            rider_id="test",
            run_number=1,
            is_fall=True,
            fall_location="S",
            is_dnf=True,
        )
        assert rec.finish_time is None
        assert rec.is_fall is True
        assert rec.fall_location == "S"

    def test_create_with_handicap(self):
        rec = TimeRecord(
            record_id="test_1",
            race_id="test",
            rider_id="test",
            run_number=1,
            finish_time=55.0,
            handicap=3.0,
        )
        assert rec.handicap == 3.0
