"""Tests for JSON parser module."""

import datetime
import json
import tempfile
from pathlib import Path

from smtc_handicap.json_parser import (
    extract_day_number,
    get_country_code,
    get_day_courses,
    parse_fall_description,
    parse_json,
    parse_start_time,
)


class TestGetCountryCode:
    def test_known_country(self):
        assert get_country_code(21) == "GB"
        assert get_country_code(45) == "CH"
        assert get_country_code(17) == "DE"
        assert get_country_code(28) == "IT"

    def test_unknown_country(self):
        assert get_country_code(99999) == ""
        assert get_country_code(0) == ""


class TestParseStartTime:
    def test_normal_timestamp(self):
        t = parse_start_time("2025-02-01T12:33:58.213")
        assert t == datetime.time(12, 33, 58, 213000)

    def test_none(self):
        assert parse_start_time(None) is None

    def test_empty(self):
        assert parse_start_time("") is None

    def test_invalid(self):
        assert parse_start_time("not-a-date") is None


class TestExtractDayNumber:
    def test_day_1(self):
        assert extract_day_number("20200111_curzon-day-1-2020-01-11.json") == 1

    def test_day_2(self):
        assert extract_day_number("20200112_curzon-day-2-2020-01-12.json") == 2

    def test_no_day(self):
        assert extract_day_number("20191223_university-2020-12-23.json") is None


class TestGetDayCourses:
    def test_with_course_details(self):
        details = [
            {"CourseNum": 1, "CourseDate": "2020-01-11T00:00:00", "CourseStart": "J"},
            {"CourseNum": 2, "CourseDate": "2020-01-11T00:00:00", "CourseStart": "J"},
            {"CourseNum": 3, "CourseDate": "2020-01-11T00:00:00", "CourseStart": "J"},
            {"CourseNum": 4, "CourseDate": "2020-01-12T00:00:00", "CourseStart": "J"},
            {"CourseNum": 5, "CourseDate": "2020-01-12T00:00:00", "CourseStart": "J"},
            {"CourseNum": 6, "CourseDate": "2020-01-12T00:00:00", "CourseStart": "J"},
        ]
        assert get_day_courses(details, 1) == {1, 2, 3}
        assert get_day_courses(details, 2) == {4, 5, 6}

    def test_empty_fallback(self):
        assert get_day_courses([], 1) == {1, 2, 3}
        assert get_day_courses([], 2) == {4, 5, 6}

    def test_empty_unknown_day(self):
        assert get_day_courses([], 3) == set()


class TestParseFallDescription:
    def test_fall_shuttlecock(self):
        is_fall, loc = parse_fall_description("Fall(S)")
        assert is_fall is True
        assert loc == "S"

    def test_fall_thoma(self):
        is_fall, loc = parse_fall_description("Fall(TH)")
        assert is_fall is True
        assert loc == "TH"

    def test_no_fall(self):
        is_fall, loc = parse_fall_description(None)
        assert is_fall is False
        assert loc is None

    def test_empty_string(self):
        is_fall, loc = parse_fall_description("")
        assert is_fall is False
        assert loc is None


def _make_json_file(data: dict, filename: str = "test-event.json") -> Path:
    """Write a JSON dict to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", prefix=filename[:-5] + "_", delete=False)
    tmp.write(json.dumps(data).encode())
    tmp.close()
    return Path(tmp.name)


class TestParseJsonPractice:
    def test_basic_practice(self):
        data = {
            "EventDate": "2025-02-01T00:00:00",
            "EventName": "PRACTICE - TOP",
            "EventType": "N",
            "IsPractice": True,
            "Rides": [
                {
                    "RideId": 1001,
                    "PersonId": 100,
                    "NamePrint": "B.A.P. Bracher",
                    "NameSort": "BRACHER B.A.P.",
                    "IsSL": False,
                    "CourseDate": "2025-02-01T00:00:00",
                    "CourseStart": "T",
                    "CourseNum": 1,
                    "RideNr": 1,
                    "NotRacing": False,
                    "T_Start": "2025-02-01T09:00:00.000",
                    "T_Junction": 19.5,
                    "T_Rise": 25.0,
                    "T_Stream": 30.0,
                    "T_Bulpetts": 40.0,
                    "T_Run": 51.67,
                    "T_Total": 51.67,
                    "Speed": 75.0,
                    "FallDescription": None,
                    "RidingCountryId": 21,
                    "T_HCP": 0.0,
                },
                {
                    "RideId": 1002,
                    "PersonId": 100,
                    "NamePrint": "B.A.P. Bracher",
                    "NameSort": "BRACHER B.A.P.",
                    "IsSL": False,
                    "CourseDate": "2025-02-01T00:00:00",
                    "CourseStart": "T",
                    "CourseNum": 1,
                    "RideNr": 2,
                    "NotRacing": False,
                    "T_Start": "2025-02-01T10:00:00.000",
                    "T_Junction": 19.8,
                    "T_Rise": 25.5,
                    "T_Stream": 30.5,
                    "T_Bulpetts": 40.5,
                    "T_Run": 52.10,
                    "T_Total": 103.77,
                    "Speed": 74.5,
                    "FallDescription": None,
                    "RidingCountryId": 21,
                    "T_HCP": 0.0,
                },
            ],
            "CourseDetails": [],
            "Honours": [],
            "Standings": [],
            "TeamStandings": [],
        }
        filepath = _make_json_file(data, "practice-top.json")
        result = parse_json(filepath)

        assert len(result.races) == 1
        race = result.races[0]
        assert race.race_id == "PRACTICE_TOP_2025-02-01"
        assert race.is_practice is True
        assert race.start_position == "TOP"

        assert len(result.riders) == 1
        assert result.riders[0].rider_id == "bracher_bap"
        assert result.riders[0].nationality == "GB"

        assert len(result.time_records) == 2
        r1, r2 = result.time_records
        assert r1.run_number == 1
        assert r1.finish_time == 51.67
        assert r1.split_junction == 19.5
        assert r1.speed_mph == 75.0
        assert r1.start_time == datetime.time(9, 0, 0)
        assert r2.run_number == 2
        assert r2.finish_time == 52.10

    def test_speed_threshold(self):
        """Speeds <= 1.0 should be stored as None (unreliable sensor data)."""
        data = {
            "EventDate": "2025-02-01T00:00:00",
            "EventName": "PRACTICE - TOP",
            "EventType": "N",
            "IsPractice": True,
            "Rides": [
                {
                    "RideId": 2001,
                    "PersonId": 200,
                    "NamePrint": "A.B. Test",
                    "NameSort": "TEST A.B.",
                    "IsSL": False,
                    "CourseStart": "T",
                    "CourseNum": 1,
                    "RideNr": 1,
                    "NotRacing": False,
                    "T_Start": None,
                    "T_Junction": 0.0,
                    "T_Rise": 0.0,
                    "T_Stream": 0.0,
                    "T_Bulpetts": 0.0,
                    "T_Run": 55.0,
                    "T_Total": 55.0,
                    "Speed": 0.5,
                    "FallDescription": None,
                    "RidingCountryId": 21,
                    "T_HCP": 0.0,
                },
            ],
            "CourseDetails": [],
            "Honours": [],
            "Standings": [],
            "TeamStandings": [],
        }
        filepath = _make_json_file(data)
        result = parse_json(filepath)

        assert len(result.time_records) == 1
        assert result.time_records[0].speed_mph is None
        assert result.time_records[0].split_junction is None


class TestParseJsonHandicapRace:
    def test_handicap_race(self):
        data = {
            "EventDate": "2019-12-23T00:00:00",
            "EventName": "THE UNIVERSITY CHALLENGE",
            "EventType": "H",
            "IsPractice": False,
            "Rides": [
                {
                    "RideId": 3001,
                    "PersonId": 300,
                    "NamePrint": "K.M. Kuhn",
                    "NameSort": "KUHN K.M.",
                    "IsSL": False,
                    "CourseDate": "2019-12-23T00:00:00",
                    "CourseStart": "J",
                    "CourseNum": 1,
                    "RideNr": 1,
                    "NotRacing": False,
                    "T_Start": "2019-12-23T10:00:00.000",
                    "T_Junction": 0.0,
                    "T_Rise": 12.0,
                    "T_Bulpetts": 35.0,
                    "T_Stream": 28.0,
                    "T_Run": 47.62,
                    "T_Total": 47.62,
                    "Speed": 60.0,
                    "FallDescription": None,
                    "RidingCountryId": 45,
                    "T_HCP": 6.8,
                },
                {
                    "RideId": 3002,
                    "PersonId": 300,
                    "NamePrint": "K.M. Kuhn",
                    "NameSort": "KUHN K.M.",
                    "IsSL": False,
                    "CourseDate": "2019-12-23T00:00:00",
                    "CourseStart": "J",
                    "CourseNum": 2,
                    "RideNr": 1,
                    "NotRacing": False,
                    "T_Start": "2019-12-23T11:00:00.000",
                    "T_Junction": 0.0,
                    "T_Rise": 12.5,
                    "T_Bulpetts": 35.5,
                    "T_Stream": 28.5,
                    "T_Run": 46.64,
                    "T_Total": 94.26,
                    "Speed": 61.0,
                    "FallDescription": None,
                    "RidingCountryId": 45,
                    "T_HCP": 6.8,
                },
            ],
            "CourseDetails": [
                {"CourseNum": 1, "CourseDate": "2019-12-23T00:00:00", "CourseStart": "J"},
                {"CourseNum": 2, "CourseDate": "2019-12-23T00:00:00", "CourseStart": "J"},
                {"CourseNum": 3, "CourseDate": "2019-12-23T00:00:00", "CourseStart": "J"},
            ],
            "Honours": [],
            "Standings": [],
            "TeamStandings": [],
        }
        filepath = _make_json_file(data, "university-2020-12-23.json")
        result = parse_json(filepath)

        assert len(result.races) == 1
        race = result.races[0]
        assert race.is_handicap_race is True
        assert race.start_position == "JUNCTION"

        assert len(result.riders) == 1
        assert result.riders[0].nationality == "CH"

        assert len(result.time_records) == 2
        assert result.time_records[0].handicap == 6.8
        assert result.time_records[0].run_number == 1
        assert result.time_records[1].run_number == 2


class TestParseJsonFall:
    def test_fall_ride(self):
        data = {
            "EventDate": "2025-01-15T00:00:00",
            "EventName": "PRACTICE - TOP",
            "EventType": "N",
            "IsPractice": True,
            "Rides": [
                {
                    "RideId": 4001,
                    "PersonId": 400,
                    "NamePrint": "C.E. Wallace",
                    "NameSort": "WALLACE C.E.",
                    "IsSL": False,
                    "CourseStart": "T",
                    "CourseNum": 1,
                    "RideNr": 1,
                    "NotRacing": False,
                    "T_Start": "2025-01-15T09:30:00.000",
                    "T_Junction": 20.0,
                    "T_Rise": 0.0,
                    "T_Stream": 0.0,
                    "T_Bulpetts": 0.0,
                    "T_Run": 0.0,
                    "T_Total": 0.0,
                    "Speed": 0.0,
                    "FallDescription": "Fall(S)",
                    "RidingCountryId": 21,
                    "T_HCP": 0.0,
                },
            ],
            "CourseDetails": [],
            "Honours": [],
            "Standings": [],
            "TeamStandings": [],
        }
        filepath = _make_json_file(data)
        result = parse_json(filepath)

        assert len(result.time_records) == 1
        rec = result.time_records[0]
        assert rec.is_fall is True
        assert rec.fall_location == "S"
        assert rec.finish_time is None
        assert rec.is_dnf is True
        assert rec.split_junction == 20.0
        assert rec.split_rise is None


class TestParseJsonDedup:
    def test_duplicate_ride_ids_skipped(self):
        ride = {
            "RideId": 5001,
            "PersonId": 500,
            "NamePrint": "A.B. Smith",
            "NameSort": "SMITH A.B.",
            "IsSL": False,
            "CourseStart": "T",
            "CourseNum": 1,
            "RideNr": 1,
            "NotRacing": False,
            "T_Start": None,
            "T_Junction": 0.0,
            "T_Rise": 0.0,
            "T_Stream": 0.0,
            "T_Bulpetts": 0.0,
            "T_Run": 50.0,
            "T_Total": 50.0,
            "Speed": 70.0,
            "FallDescription": None,
            "RidingCountryId": 21,
            "T_HCP": 0.0,
        }
        data = {
            "EventDate": "2025-01-10T00:00:00",
            "EventName": "PRACTICE - TOP",
            "EventType": "N",
            "IsPractice": True,
            "Rides": [ride, ride],  # same RideId twice
            "CourseDetails": [],
            "Honours": [],
            "Standings": [],
            "TeamStandings": [],
        }
        filepath = _make_json_file(data)
        result = parse_json(filepath)

        assert len(result.time_records) == 1


class TestParseJsonMultiDay:
    def test_day_filtering(self):
        """Day-2 file should only include courses 4-6."""
        rides = []
        for course_num in range(1, 7):
            rides.append(
                {
                    "RideId": 6000 + course_num,
                    "PersonId": 600,
                    "NamePrint": "B.A.P. Bracher",
                    "NameSort": "BRACHER B.A.P.",
                    "IsSL": False,
                    "CourseDate": "2020-01-11T00:00:00"
                    if course_num <= 3
                    else "2020-01-12T00:00:00",
                    "CourseStart": "J",
                    "CourseNum": course_num,
                    "RideNr": 1,
                    "NotRacing": False,
                    "T_Start": None,
                    "T_Junction": 0.0,
                    "T_Rise": 12.0,
                    "T_Stream": 28.0,
                    "T_Bulpetts": 35.0,
                    "T_Run": 45.0 + course_num,
                    "T_Total": 45.0 + course_num,
                    "Speed": 70.0,
                    "FallDescription": None,
                    "RidingCountryId": 21,
                    "T_HCP": 0.0,
                }
            )
        data = {
            "EventDate": "2020-01-12T00:00:00",
            "EventName": "THE CURZON CUP",
            "EventType": "N",
            "IsPractice": False,
            "Rides": rides,
            "CourseDetails": [
                {"CourseNum": 1, "CourseDate": "2020-01-11T00:00:00", "CourseStart": "J"},
                {"CourseNum": 2, "CourseDate": "2020-01-11T00:00:00", "CourseStart": "J"},
                {"CourseNum": 3, "CourseDate": "2020-01-11T00:00:00", "CourseStart": "J"},
                {"CourseNum": 4, "CourseDate": "2020-01-12T00:00:00", "CourseStart": "J"},
                {"CourseNum": 5, "CourseDate": "2020-01-12T00:00:00", "CourseStart": "J"},
                {"CourseNum": 6, "CourseDate": "2020-01-12T00:00:00", "CourseStart": "J"},
            ],
            "Honours": [],
            "Standings": [],
            "TeamStandings": [],
        }
        # Simulate day-2 filename
        filepath = _make_json_file(data, "curzon-day-2-2020-01-12.json")
        # We need the actual filename to contain "day-2" for extraction
        # The temp file name contains the prefix, so extract_day_number works
        # But temp filenames may not contain "day-2" — let's use a real temp dir
        import shutil

        tmp_dir = Path(tempfile.mkdtemp())
        real_path = tmp_dir / "20200112_curzon-day-2-2020-01-12.json"
        shutil.move(str(filepath), str(real_path))

        result = parse_json(real_path)

        # Should only have day-2 courses (4, 5, 6)
        assert len(result.time_records) == 3
        run_numbers = sorted(r.run_number for r in result.time_records)
        assert run_numbers == [4, 5, 6]

        race = result.races[0]
        assert race.day_number == 2
        assert "DAY2" in race.race_id


class TestParseJsonNotRacing:
    def test_rnr_rider(self):
        """NotRacing riders should have is_dnf=True and handicap=None."""
        data = {
            "EventDate": "2020-01-05T00:00:00",
            "EventName": "THE TEST CUP",
            "EventType": "H",
            "IsPractice": False,
            "Rides": [
                {
                    "RideId": 7001,
                    "PersonId": 700,
                    "NamePrint": "X.Y. Rider",
                    "NameSort": "RIDER X.Y.",
                    "IsSL": False,
                    "CourseStart": "T",
                    "CourseNum": 1,
                    "RideNr": 1,
                    "NotRacing": True,
                    "T_Start": None,
                    "T_Junction": 20.0,
                    "T_Rise": 25.0,
                    "T_Stream": 30.0,
                    "T_Bulpetts": 40.0,
                    "T_Run": 55.0,
                    "T_Total": 55.0,
                    "Speed": 65.0,
                    "FallDescription": None,
                    "RidingCountryId": 21,
                    "T_HCP": 0.0,
                },
            ],
            "CourseDetails": [
                {"CourseNum": 1, "CourseDate": "2020-01-05T00:00:00", "CourseStart": "T"},
            ],
            "Honours": [],
            "Standings": [],
            "TeamStandings": [],
        }
        filepath = _make_json_file(data)
        result = parse_json(filepath)

        assert len(result.time_records) == 1
        rec = result.time_records[0]
        assert rec.is_dnf is True
        assert rec.handicap is None
        assert rec.finish_time == 55.0
