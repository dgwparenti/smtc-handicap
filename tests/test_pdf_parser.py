"""Tests for PDF parser utility functions and section detection."""

import datetime

from smtc_handicap.pdf_parser import (
    RE_RACE_HEADER,
    Section,
    _strip_trailing_totals,
    detect_sections,
    make_race_id,
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
        rid = make_race_id("PRACTICE", "TOP", datetime.date(2026, 1, 21), is_practice=True)
        assert rid == "PRACTICE_TOP_2026-01-21"

    def test_named_race(self):
        rid = make_race_id("THE STAGNI CUP", "TOP", datetime.date(2026, 1, 21), is_practice=False)
        assert rid == "STAGNI_CUP_2026-01-21"

    def test_multi_day(self):
        rid = make_race_id(
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


class TestCoppaRaceHeader:
    """Tests for COPPA d'ITALIA race header detection."""

    def test_coppa_ditalia_matches(self):
        m = RE_RACE_HEADER.match("THE COPPA d\u2019ITALIA")
        assert m is not None
        assert "COPPA" in m.group(1).upper()
        assert "ITALIA" in m.group(1).upper()

    def test_coppa_with_ascii_apostrophe(self):
        m = RE_RACE_HEADER.match("THE COPPA d'ITALIA")
        assert m is not None

    def test_existing_patterns_still_work(self):
        assert RE_RACE_HEADER.match("THE STAGNI CUP") is not None
        assert RE_RACE_HEADER.match("THE BRABAZON TROPHY") is not None
        assert RE_RACE_HEADER.match("THE CINGHIALE TROPHY") is not None

    def test_coppa_section_detected(self):
        lines = [
            "CRESTA RUN",
            "THE COPPA d\u2019ITALIA",
            "(Top Handicap)",
            "And",
            "THE CINGHIALE TROPHY",
            "(For Fastest Time in the Coppa d\u2019Italia)",
            "12th February 2026",
            "H'Cap 1st 2nd Net Total",
            "1 N.J. Halusa A 6.00 56.96 55.63 100.59",
        ]
        meta = {"has_race_top": True}
        sections = detect_sections(lines, meta)
        # Should detect exactly 1 race section (CINGHIALE is a sub-prize)
        race_sections = [s for s in sections if s.section_type.startswith("RACE")]
        assert len(race_sections) == 1
        assert race_sections[0].section_type == "RACE_HANDICAP"
        assert "COPPA" in race_sections[0].race_name.upper()

    def test_cinghiale_is_subprize(self):
        """THE CINGHIALE TROPHY after 'And' should not create a separate section."""
        lines = [
            "THE COPPA d\u2019ITALIA",
            "(Top Handicap)",
            "And",
            "THE CINGHIALE TROPHY",
            "(For Fastest Time in the Coppa d\u2019Italia)",
            "12th February 2026",
            "H'Cap 1st 2nd Net Total",
        ]
        meta = {"has_race_top": True}
        sections = detect_sections(lines, meta)
        race_sections = [s for s in sections if s.section_type.startswith("RACE")]
        assert len(race_sections) == 1


class TestStripTrailingTotals2Run:
    """Tests for _strip_trailing_totals with expected_runs=2."""

    def test_2run_handicap_complete(self):
        # hcap already stripped: time1 + time2 + NetTotal
        times = ["56.96", "55.63", "100.59"]
        result = _strip_trailing_totals(times, is_handicap=True, expected_runs=2)
        assert result == ["56.96", "55.63"]

    def test_2run_handicap_one_run(self):
        # Only 1 run completed — no total to strip
        times = ["54.65"]
        result = _strip_trailing_totals(times, is_handicap=True, expected_runs=2)
        assert result == ["54.65"]

    def test_2run_handicap_fall(self):
        times = ["Fall(S)"]
        result = _strip_trailing_totals(times, is_handicap=True, expected_runs=2)
        assert result == ["Fall(S)"]

    def test_3run_handicap_still_works(self):
        # Backwards compat: 3 runs + Total + NetTotal = 5 values
        times = ["51.00", "52.00", "53.00", "156.00", "156.00"]
        result = _strip_trailing_totals(times, is_handicap=True, expected_runs=3)
        assert result == ["51.00", "52.00", "53.00"]

    def test_3run_nonhandicap_still_works(self):
        # 3 runs + Total = 4 values
        times = ["51.00", "52.00", "53.00", "156.00"]
        result = _strip_trailing_totals(times, is_handicap=False, expected_runs=3)
        assert result == ["51.00", "52.00", "53.00"]


class TestParseCoppaRaceSection:
    """Tests for parsing a 2-run handicap race (Coppa format)."""

    def _make_coppa_section(self, data_lines):
        return Section(
            section_type="RACE_HANDICAP",
            header_line="THE COPPA d\u2019ITALIA",
            start_position="TOP",
            race_name="COPPA d\u2019ITALIA",
            day_number=None,
            lines=["H'Cap 1st 2nd Net Total"] + data_lines,
        )

    def test_ranked_riders_2run(self):
        section = self._make_coppa_section(
            [
                "1 N.J. Halusa A 6.00 56.96 55.63 100.59",
                "2 F.A. Strange GB 8.00 58.39 58.78 101.17",
            ]
        )
        race, riders, records = parse_race_section(section, datetime.date(2026, 2, 12), "test.pdf")
        assert len(riders) == 2
        assert len(records) == 4  # 2 runs each

        halusa = [r for r in records if "halusa" in r.rider_id]
        assert len(halusa) == 2
        assert halusa[0].handicap == 6.0
        assert halusa[0].finish_time == 56.96
        assert halusa[1].finish_time == 55.63

    def test_single_run_dnf(self):
        """Rider with only 1 completed run (DNF on 2nd)."""
        section = self._make_coppa_section(
            [
                "A.C.A.L. Spillmann CH 2.00 54.65",
            ]
        )
        _, _, records = parse_race_section(section, datetime.date(2026, 2, 12), "test.pdf")
        assert len(records) == 1
        assert records[0].finish_time == 54.65
        assert records[0].handicap == 2.0

    def test_fall_rider(self):
        section = self._make_coppa_section(
            [
                "James B Sunley GB 4.00 Fall(S)",
            ]
        )
        _, _, records = parse_race_section(section, datetime.date(2026, 2, 12), "test.pdf")
        assert len(records) == 1
        assert records[0].is_fall is True
        assert records[0].fall_location == "S"
        assert records[0].handicap == 4.0

    def test_riding_but_not_racing_skipped(self):
        """Lines prefixed with ** should be skipped."""
        section = self._make_coppa_section(
            [
                "1 N.J. Halusa A 6.00 56.96 55.63 100.59",
                "** G.M. Kasper CH 59.80 60.55",
                "** J.E. Rawstron GB Fall(TH)",
                "** Riding but not Racing",
            ]
        )
        _, riders, records = parse_race_section(section, datetime.date(2026, 2, 12), "test.pdf")
        # Only Halusa should be parsed
        assert len(riders) == 1
        assert len(records) == 2  # 2 runs for Halusa only

    def test_scratch_rider_single_run(self):
        section = self._make_coppa_section(
            [
                "E. Nani CH Scr 52.16",
            ]
        )
        _, _, records = parse_race_section(section, datetime.date(2026, 2, 12), "test.pdf")
        assert len(records) == 1
        assert records[0].handicap == 0.0
        assert records[0].finish_time == 52.16
