"""Tests for rider name normalization."""

import pytest

from smtc_handicap.name_normalizer import normalize_rider_id


@pytest.mark.parametrize(
    "input_name, expected_id",
    [
        ("F.P. Rueda (Jnr)", "rueda_fp_jnr"),
        ("The Hon M.V.O. de C. Wrottesley", "wrottesley_mvo_de_c"),
        ("Count F. Guerrini-Maraldi", "guerrini_maraldi_f"),
        ("Lord Doune", "doune"),
        ("B.A.P. Bracher", "bracher_bap"),
        ("Lt-Cdr J.R. Smith", "smith_jr"),
        ("C.E. Wallace", "wallace_ce"),
        ("Sir A.B. Charles", "charles_ab"),
        ("Dr M. Fischer", "fischer_m"),
        ("James B Sunley", "sunley_james_b"),
        ("T.G.L. Albers-Schoenberg", "albers_schoenberg_tgl"),
    ],
)
def test_normalize(input_name, expected_id):
    assert normalize_rider_id(input_name) == expected_id


def test_empty_name_raises():
    with pytest.raises(ValueError):
        normalize_rider_id("")


def test_whitespace_only_raises():
    with pytest.raises(ValueError):
        normalize_rider_id("   ")


def test_strips_am_marker():
    result = normalize_rider_id("T.J. Hooper (AM)")
    assert result == "hooper_tj"


def test_strips_sl_marker():
    result = normalize_rider_id("M.M. Hochstrasser SL")
    # SL is stripped, then normal processing
    assert "sl" not in result
    assert result == "hochstrasser_mm"


def test_strips_stars():
    result = normalize_rider_id("** C. Evans")
    assert result == "evans_c"
