"""Tests for the validation module."""

import pytest

from smtc_handicap.validation import (
    is_team_relay_race,
    is_valid_finish_time,
    normalize_scratch_handicaps,
)


class TestIsTeamRelayRace:
    def test_inter_club_challenge(self):
        assert is_team_relay_race("INTER_CLUB_CHALLENGE") is True

    def test_inter_club_challenge_garbled(self):
        assert is_team_relay_race("INTER CLUB CHALLENGE") is True

    def test_fairchilds_maccarthy_cup(self):
        assert is_team_relay_race("FAIRCHILDS_MACCARTHY_CUP") is True

    def test_fairchild_maccarthy_no_s(self):
        assert is_team_relay_race("FAIRCHILD_MACCARTHY_CUP") is True

    def test_university_challenge_cup(self):
        assert is_team_relay_race("UNIVERSITY_CHALLENGE_CUP") is True

    def test_garbled_badrutt(self):
        assert is_team_relay_race("JOH_ANN_ES_BADRU_TT_MEMORIAL") is True

    def test_normal_race_not_relay(self):
        assert is_team_relay_race("HEATON_GOLD_CUP") is False

    def test_practice_not_relay(self):
        assert is_team_relay_race("PRACTICE") is False

    def test_case_insensitive(self):
        assert is_team_relay_race("Inter_Club_Challenge") is True


class TestIsValidFinishTime:
    # -- Non-strict (absolute bounds) --

    def test_none_is_valid(self):
        assert is_valid_finish_time(None) is True

    def test_sub_one_second_invalid(self):
        assert is_valid_finish_time(0.5) is False

    def test_over_100s_invalid(self):
        assert is_valid_finish_time(150.0) is False

    def test_normal_top_time_valid(self):
        assert is_valid_finish_time(55.0) is True

    def test_boundary_min(self):
        assert is_valid_finish_time(1.0) is True

    def test_boundary_max(self):
        assert is_valid_finish_time(100.0) is True

    def test_just_below_min(self):
        assert is_valid_finish_time(0.99) is False

    def test_just_above_max(self):
        assert is_valid_finish_time(100.01) is False

    # -- Strict (position-specific bounds) --

    def test_strict_top_valid(self):
        assert is_valid_finish_time(55.0, "TOP", strict=True) is True

    def test_strict_top_too_fast(self):
        assert is_valid_finish_time(45.0, "TOP", strict=True) is False

    def test_strict_top_too_slow(self):
        assert is_valid_finish_time(75.0, "TOP", strict=True) is False

    def test_strict_junction_valid(self):
        assert is_valid_finish_time(48.0, "JUNCTION", strict=True) is True

    def test_strict_junction_too_fast(self):
        assert is_valid_finish_time(38.0, "JUNCTION", strict=True) is False

    def test_strict_junction_too_slow(self):
        assert is_valid_finish_time(60.0, "JUNCTION", strict=True) is False

    def test_strict_requires_position(self):
        with pytest.raises(ValueError, match="position is required"):
            is_valid_finish_time(55.0, strict=True)

    def test_strict_unknown_position(self):
        with pytest.raises(ValueError, match="Unknown position"):
            is_valid_finish_time(55.0, "BOTTOM", strict=True)


class TestNormalizeScratchHandicaps:
    def test_already_scratch(self):
        result = normalize_scratch_handicaps([0.0, 2.5, 5.0])
        assert result == [0.0, 2.5, 5.0]

    def test_needs_normalization(self):
        result = normalize_scratch_handicaps([3.0, 5.5, 8.0])
        assert result == [0.0, 2.5, 5.0]

    def test_empty_list(self):
        assert normalize_scratch_handicaps([]) == []

    def test_single_entry(self):
        result = normalize_scratch_handicaps([4.0])
        assert result == [0.0]

    def test_all_same(self):
        result = normalize_scratch_handicaps([2.0, 2.0, 2.0])
        assert result == [0.0, 0.0, 0.0]
