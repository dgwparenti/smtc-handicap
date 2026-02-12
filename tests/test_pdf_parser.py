"""Tests for PDF parser utility functions and section detection."""

import datetime

from smtc_handicap.pdf_parser import (
    Section,
    _make_race_id,
    detect_sections,
    parse_practice_section,
    parse_race_section,
    parse_time_cell,
    split_row_into_columns,
)


class TestParseTimeCell:
    def test_normal_time(self):
        val, is_fall, loc = parse_time_cell("51.67")
        assert val == 51.67
        assert is_fall is False
        assert loc is None

    def test_fall_shuttlecock(self):
        val, is_fall, loc = parse_time_cell("Fall(S)")
        assert val is None
        assert is_fall is True
        assert loc == "S"

    def test_fall_thoma(self):
        val, is_fall, loc = parse_time_cell("Fall(TH)")
        assert val is None
        assert is_fall is True
        assert loc == "TH"

    def test_empty_string(self):
        val, is_fall, loc = parse_time_cell("")
        assert val is None
        assert is_fall is False

    def test_dash(self):
        val, is_fall, loc = parse_time_cell("-")
        assert val is None
        assert is_fall is False

    def test_fall_battledore(self):
        val, is_fall, loc = parse_time_cell("Fall(BR)")
        assert val is None
        assert is_fall is True
        assert loc == "BR"


class TestSplitRow:
    def test_basic_split(self):
        cols = split_row_into_columns("B.A.P. Bracher    GB    51.67    52.10")
        assert len(cols) == 4
        assert cols[0] == "B.A.P. Bracher"
        assert cols[1] == "GB"

    def test_single_spaces_preserved(self):
        cols = split_row_into_columns("Count F. Guerrini-Maraldi    I    55.00")
        assert cols[0] == "Count F. Guerrini-Maraldi"

    def test_empty_line(self):
        cols = split_row_into_columns("   ")
        assert cols == []


class TestMakeRaceId:
    def test_practice(self):
        rid = _make_race_id("PRACTICE", "TOP", datetime.date(2026, 1, 21), is_practice=True)
        assert rid == "PRACTICE_TOP_2026-01-21"

    def test_named_race(self):
        rid = _make_race_id("THE STAGNI CUP", "TOP", datetime.date(2026, 1, 21), is_practice=False)
        assert rid == "STAGNI_CUP_2026-01-21"

    def test_multi_day(self):
        rid = _make_race_id(
            "THE BRABAZON TROPHY",
            "TOP",
            datetime.date(2026, 2, 8),
            is_practice=False,
            day_number=2,
        )
        assert rid == "BRABAZON_TROPHY_DAY2_2026-02-08"


class TestDetectSections:
    def test_practice_detected(self):
        lines = [
            "CRESTA RUN",
            "PRACTICE - TOP",
            "9th February 2026",
            "B.A.P. Bracher    GB    51.67",
        ]
        meta = {"has_practice_top": True, "has_practice_junction": False}
        sections = detect_sections(lines, meta)
        assert len(sections) == 1
        assert sections[0].section_type == "PRACTICE"
        assert sections[0].start_position == "TOP"

    def test_split_section_detected(self):
        lines = [
            "Split Results",
            "Name    Start    Junction    Rise    Stream    Bulpetts    Finish    Speed",
            "BRACHER B.A.P.    09:00:00    19.68    25.53    30.00    40.00    51.67    75.00",
        ]
        meta = {}
        sections = detect_sections(lines, meta)
        assert len(sections) == 1
        assert sections[0].section_type == "SPLIT"

    def test_no_split_section_when_absent(self):
        lines = [
            "PRACTICE - JUNCTION",
            "B.A.P. Bracher    GB    43.50",
        ]
        meta = {}
        sections = detect_sections(lines, meta)
        assert all(s.section_type != "SPLIT" for s in sections)

    def test_race_handicap_detected(self):
        lines = [
            "THE STAGNI CUP",
            "(Top Handicap)",
            "25th January 2026",
            "H'Cap    1st    2nd    3rd    Net Total",
            "1    B.A.P. Bracher    GB    Scr    51.00    52.00    53.00    156.00    156.00",
        ]
        meta = {"has_race_top": True}
        sections = detect_sections(lines, meta)
        assert len(sections) == 1
        assert sections[0].section_type == "RACE_HANDICAP"


class TestParsePracticeSection:
    def test_basic_practice(self):
        section = Section(
            section_type="PRACTICE",
            header_line="PRACTICE - TOP",
            start_position="TOP",
            race_name="PRACTICE",
            day_number=None,
            lines=[
                "B.A.P. Bracher    GB    51.67    52.10    53.50",
                "C.E. Wallace    GB    55.00    Fall(S)",
            ],
        )
        race, riders, records = parse_practice_section(
            section, datetime.date(2026, 1, 21), "test.pdf"
        )
        assert race.race_id == "PRACTICE_TOP_2026-01-21"
        assert race.is_practice is True
        assert len(riders) == 2
        assert len(records) == 5  # 3 for Bracher + 2 for Wallace

        # Check fall record
        fall_records = [r for r in records if r.is_fall]
        assert len(fall_records) == 1
        assert fall_records[0].fall_location == "S"


class TestParseRaceSection:
    def test_handicap_race(self):
        section = Section(
            section_type="RACE_HANDICAP",
            header_line="THE TEST CUP",
            start_position="TOP",
            race_name="THE TEST CUP",
            day_number=None,
            lines=[
                "H'Cap    1st    2nd    3rd    Net Total",
                "1    A.B. Smith    GB    Scr    51.00    52.00    53.00    156.00    156.00",
                "2    C.D. Jones    CH    3.00    54.00    55.00    56.00    165.00    156.00",
            ],
        )
        race, riders, records = parse_race_section(section, datetime.date(2026, 1, 25), "test.pdf")
        assert race.is_handicap_race is True
        assert len(riders) == 2
        assert len(records) == 6  # 3 runs each

        smith_records = [r for r in records if r.rider_id == "smith_ab"]
        assert len(smith_records) == 3
        assert smith_records[0].handicap == 0.0  # Scr = scratch
