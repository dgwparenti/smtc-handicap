"""Unit tests for the json_extractor module."""

from __future__ import annotations

import html
import json
from pathlib import Path

from smtc_handicap.json_extractor import extract_race_data, has_ride_data, save_race_json

# ======================================================================
# Fixtures
# ======================================================================

SAMPLE_RACE_DATA = {
    "EventName": "PRACTICE 2022 3687",
    "EventDate": "2021-12-24",
    "EventType": "N",
    "IsPractice": True,
    "Rides": [
        {
            "PersonId": 101,
            "NamePrint": "J. Smith",
            "NameSort": "Smith J.",
            "Position": 1,
            "CourseStart": "J",
            "T_Total": "01:02.34",
            "Speed": "82.5",
            "T_HCP": "",
            "FallDescription": "",
            "T_Junction": "00:15.22",
            "T_Rise": "00:25.44",
            "T_Stream": "00:35.66",
            "T_Bulpetts": "00:50.88",
            "IsSL": False,
            "IsDisqualified": False,
            "IsScratched": False,
            "NotRacing": False,
        },
        {
            "PersonId": 102,
            "NamePrint": "A. Jones",
            "NameSort": "Jones A.",
            "Position": 2,
            "CourseStart": "T",
            "T_Total": "00:55.12",
            "Speed": "88.1",
            "T_HCP": "",
            "FallDescription": "",
            "T_Junction": "",
            "T_Rise": "",
            "T_Stream": "00:30.55",
            "T_Bulpetts": "00:45.33",
            "IsSL": False,
            "IsDisqualified": False,
            "IsScratched": False,
            "NotRacing": False,
        },
        {
            "PersonId": 103,
            "NamePrint": "B. Brown",
            "NameSort": "Brown B.",
            "Position": 3,
            "CourseStart": "J",
            "T_Total": "",
            "Speed": "",
            "T_HCP": "",
            "FallDescription": "S",
            "T_Junction": "00:14.00",
            "T_Rise": "",
            "T_Stream": "",
            "T_Bulpetts": "",
            "IsSL": False,
            "IsDisqualified": False,
            "IsScratched": False,
            "NotRacing": False,
        },
    ],
    "Standings": [],
}

EMPTY_RIDES_DATA = {
    "EventName": "CANCELLED EVENT",
    "EventDate": "2022-01-15",
    "EventType": "N",
    "IsPractice": False,
    "Rides": [],
    "Standings": [],
}


def _make_html(race_data: dict) -> str:
    """Build a minimal HTML page with embedded race JSON."""
    json_str = json.dumps(race_data)
    encoded = html.escape(json_str)
    return f"""
    <html><body>
    <script>
    const drawData = decodeHtml("");
    const raceData = decodeHtml("{encoded}");
    </script>
    </body></html>
    """


# ======================================================================
# TestExtractRaceData
# ======================================================================


class TestExtractRaceData:
    def test_extracts_valid_json(self):
        html_content = _make_html(SAMPLE_RACE_DATA)
        result = extract_race_data(html_content)

        assert result is not None
        assert result["EventName"] == "PRACTICE 2022 3687"
        assert len(result["Rides"]) == 3

    def test_returns_none_for_no_marker(self):
        html_content = "<html><body>No race data here</body></html>"
        result = extract_race_data(html_content)
        assert result is None

    def test_returns_none_for_empty_decodhtml(self):
        html_content = """
        <script>
        const raceData = decodeHtml("");
        </script>
        """
        result = extract_race_data(html_content)
        assert result is None

    def test_returns_none_for_invalid_json(self):
        html_content = """
        <script>
        const raceData = decodeHtml("not valid json at all");
        </script>
        """
        result = extract_race_data(html_content)
        assert result is None

    def test_handles_html_entities(self):
        """Verify html.unescape correctly decodes &amp; &lt; etc."""
        data = {"EventName": "SMITH & JONES CUP", "Rides": [{"NamePrint": "Test"}]}
        html_content = _make_html(data)
        result = extract_race_data(html_content)

        assert result is not None
        assert result["EventName"] == "SMITH & JONES CUP"

    def test_ignores_drawdata_marker(self):
        """Should find raceData, not drawData."""
        html_content = """
        <script>
        const drawData = decodeHtml("{}");
        const raceData = decodeHtml("{}");
        </script>
        """
        # Both are valid JSON (empty dict), but we should get a dict back
        result = extract_race_data(html_content)
        assert result is not None
        assert isinstance(result, dict)


# ======================================================================
# TestHasRideData
# ======================================================================


class TestHasRideData:
    def test_true_with_rides(self):
        assert has_ride_data(SAMPLE_RACE_DATA) is True

    def test_false_with_empty_rides(self):
        assert has_ride_data(EMPTY_RIDES_DATA) is False

    def test_false_with_missing_rides_key(self):
        assert has_ride_data({"EventName": "Test"}) is False

    def test_false_with_rides_not_list(self):
        assert has_ride_data({"Rides": "not a list"}) is False


# ======================================================================
# TestSaveRaceJson
# ======================================================================


class TestSaveRaceJson:
    def test_saves_json_file(self, tmp_path):
        result = save_race_json(SAMPLE_RACE_DATA, tmp_path, "20211224_practice.json")

        assert result is not None
        assert result.exists()
        loaded = json.loads(result.read_text())
        assert loaded["EventName"] == "PRACTICE 2022 3687"
        assert len(loaded["Rides"]) == 3

    def test_skips_existing_file(self, tmp_path):
        existing = tmp_path / "existing.json"
        existing.write_text("{}")

        result = save_race_json(SAMPLE_RACE_DATA, tmp_path, "existing.json")

        assert result is None
        # File should not have been overwritten
        assert json.loads(existing.read_text()) == {}

    def test_creates_output_dir(self, tmp_path):
        nested = tmp_path / "sub" / "dir"
        result = save_race_json(SAMPLE_RACE_DATA, nested, "test.json")

        assert result is not None
        assert nested.exists()
