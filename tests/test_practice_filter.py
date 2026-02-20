"""Tests for is_practice_only_file() filename classifier."""

import pytest

from smtc_handicap.pipeline import is_practice_only_file

# -- Practice-only files (should return True) --


@pytest.mark.parametrize(
    "filename",
    [
        # Old-style with "practice" keyword
        "20191222_practice-2020-2358-12-22.pdf",
        "20200105_Practice_Top.pdf",
        # New-style: pt/pj only (no race)
        "20260112 pt + pj + Splits.pdf",
        "20250113_pt___pj___Splits.pdf",
        "20260115 pt + Splits.pdf",
        "20250120_pj.pdf",
        # Mixed separators
        "20260118_pt_pj_splits.pdf",
        "20260118 pt pj splits.pdf",
    ],
    ids=[
        "old-practice-keyword",
        "old-practice-keyword-caps",
        "new-pt-pj-spaces",
        "new-pt-pj-underscores",
        "new-pt-only",
        "new-pj-only",
        "underscore-sep",
        "space-sep",
    ],
)
def test_practice_only_true(filename):
    assert is_practice_only_file(filename) is True


# -- Non-practice files (should return False) --


@pytest.mark.parametrize(
    "filename",
    [
        # Combined race + practice (rt present)
        "20260201 rt (The Morgan Cup) + pt + pj + Splits.pdf",
        "20260205_rt_pt_pj.pdf",
        # Race-only (rt/rj, no pt/pj)
        "20260212 rt Coppa + splits.pdf",
        "20260210_rj_splits.pdf",
        # No practice or race markers at all
        "20260115 Splits.pdf",
        "some_random_file.pdf",
        # Letters adjacent to p/r — should NOT match as standalone pt/pj/rt/rj
        "20260115 spt report.pdf",
        "20260115 aptitude.pdf",
    ],
    ids=[
        "combined-race-practice",
        "combined-underscore",
        "race-only-rt",
        "race-only-rj",
        "splits-only",
        "random-file",
        "spt-not-pt",
        "aptitude-not-pt",
    ],
)
def test_practice_only_false(filename):
    assert is_practice_only_file(filename) is False
