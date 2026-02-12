"""Unit tests for the pdf_generator module."""

from __future__ import annotations

from smtc_handicap.pdf_generator import generate_results_pdf

# ======================================================================
# Fixtures
# ======================================================================

PRACTICE_DATA = {
    "EventName": "PRACTICE 2022 3687",
    "EventDate": "2021-12-24",
    "EventType": "N",
    "IsPractice": True,
    "Rides": [
        {
            "NamePrint": "J. Smith",
            "CourseStart": "J",
            "T_Total": "01:02.34",
            "Speed": "82.5",
            "FallDescription": "",
            "IsScratched": False,
            "NotRacing": False,
        },
        {
            "NamePrint": "A. Jones",
            "CourseStart": "T",
            "T_Total": "00:55.12",
            "Speed": "88.1",
            "FallDescription": "",
            "IsScratched": False,
            "NotRacing": False,
        },
    ],
    "Standings": [],
}

RACE_DATA_WITH_STANDINGS = {
    "EventName": "HEATON GOLD CUP 2022",
    "EventDate": "2022-01-08",
    "EventType": "H",
    "IsPractice": False,
    "Rides": [
        {
            "NamePrint": "J. Smith",
            "Position": 1,
            "CourseStart": "J",
            "T_Total": "01:02.34",
            "Speed": "82.5",
            "T_HCP": "00:05.00",
            "FallDescription": "",
            "IsScratched": False,
            "NotRacing": False,
        },
    ],
    "Standings": [
        {
            "Position": 1,
            "NamePrint": "J. Smith",
            "T_HCP": "00:05.00",
            "T_Total": "01:02.34",
            "T_Net": "00:57.34",
        },
        {
            "Position": 2,
            "NamePrint": "A. Jones",
            "T_HCP": "00:00.00",
            "T_Total": "01:00.12",
            "T_Net": "01:00.12",
        },
    ],
}

RACE_DATA_NO_STANDINGS = {
    "EventName": "LIGHTNING CUP 2022",
    "EventDate": "2022-01-10",
    "EventType": "H",
    "IsPractice": False,
    "Rides": [
        {
            "NamePrint": "B. Brown",
            "Position": 1,
            "CourseStart": "J",
            "T_Total": "01:01.00",
            "Speed": "84.0",
            "T_HCP": "00:03.00",
            "FallDescription": "S",
            "IsScratched": False,
            "NotRacing": False,
        },
        {
            "NamePrint": "C. Clark",
            "Position": 2,
            "CourseStart": "T",
            "T_Total": "00:58.50",
            "Speed": "86.2",
            "T_HCP": "00:00.00",
            "FallDescription": "",
            "IsScratched": False,
            "NotRacing": False,
        },
    ],
    "Standings": [],
}


# ======================================================================
# Tests
# ======================================================================


class TestGenerateResultsPdf:
    def test_generates_valid_pdf(self, tmp_path):
        output = tmp_path / "practice.pdf"
        result = generate_results_pdf(PRACTICE_DATA, output)

        assert result is not None
        assert output.exists()
        # Check PDF magic bytes
        assert output.read_bytes()[:5] == b"%PDF-"

    def test_practice_layout(self, tmp_path):
        output = tmp_path / "practice.pdf"
        result = generate_results_pdf(PRACTICE_DATA, output)

        assert result is not None
        assert output.stat().st_size > 0

    def test_race_layout_with_standings(self, tmp_path):
        output = tmp_path / "race_standings.pdf"
        result = generate_results_pdf(RACE_DATA_WITH_STANDINGS, output)

        assert result is not None
        assert output.read_bytes()[:5] == b"%PDF-"

    def test_race_layout_no_standings_with_falls(self, tmp_path):
        output = tmp_path / "race_no_standings.pdf"
        result = generate_results_pdf(RACE_DATA_NO_STANDINGS, output)

        assert result is not None
        assert output.read_bytes()[:5] == b"%PDF-"

    def test_skips_existing_file(self, tmp_path):
        output = tmp_path / "existing.pdf"
        output.write_bytes(b"%PDF-1.4 existing content")

        result = generate_results_pdf(PRACTICE_DATA, output)

        assert result is None
        # File should not have been overwritten
        assert output.read_bytes() == b"%PDF-1.4 existing content"

    def test_creates_parent_dirs(self, tmp_path):
        output = tmp_path / "sub" / "dir" / "results.pdf"
        result = generate_results_pdf(PRACTICE_DATA, output)

        assert result is not None
        assert output.exists()
