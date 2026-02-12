"""Tests for PDF filename parser."""

from smtc_handicap.filename_parser import parse_pdf_filename


def test_practice_only():
    result = parse_pdf_filename("20260209 pt + pj + splits.pdf")
    assert result["date"] == "2026-02-09"
    assert result["has_practice_top"] is True
    assert result["has_practice_junction"] is True
    assert result["has_race_top"] is False
    assert result["has_race_junction"] is False
    assert result["has_splits"] is True
    assert result["race_name"] is None
    assert result["day_number"] is None


def test_race_and_practice():
    result = parse_pdf_filename("20260125 rt (Aris Vatimbella) + pt + pj + Splits.pdf")
    assert result["date"] == "2026-01-25"
    assert result["has_race_top"] is True
    assert result["has_practice_top"] is True
    assert result["has_practice_junction"] is True
    assert result["race_name"] == "Aris Vatimbella"


def test_multi_day_race():
    result = parse_pdf_filename(
        "20260208 rt (Brabazon Trophy) (Day 2) + rj (Roger Gibbs Challenge Cup) + pj + Splits.pdf"
    )
    assert result["date"] == "2026-02-08"
    assert result["has_race_top"] is True
    assert result["has_race_junction"] is True
    assert result["day_number"] == 2
    assert result["race_name"] == "Brabazon Trophy"


def test_junction_race():
    result = parse_pdf_filename("20260114 rj (Escalante Cup) + pj + Splits.pdf")
    assert result["has_race_junction"] is True
    assert result["has_race_top"] is False
    assert result["race_name"] == "Escalante Cup"


def test_junction_practice_only():
    result = parse_pdf_filename("20251220 pj + splits.pdf")
    assert result["date"] == "2025-12-20"
    assert result["has_practice_junction"] is True
    assert result["has_practice_top"] is False
    assert result["has_race_top"] is False


def test_original_filename_preserved():
    fname = "20260209 pt + pj + splits.pdf"
    result = parse_pdf_filename(fname)
    assert result["original_filename"] == fname
