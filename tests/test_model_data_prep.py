"""Unit tests for smtc_handicap.model.data_prep."""

from __future__ import annotations

import datetime

import numpy as np
import pytest

from smtc_handicap.db import CrestaDB
from smtc_handicap.model.data_prep import build_stan_data
from smtc_handicap.models import Race, Rider, TimeRecord


@pytest.fixture()
def sample_db(tmp_path):
    """Create a small in-memory DB with known data for testing."""
    db_path = tmp_path / "test.db"
    db = CrestaDB(db_path)

    # --- Riders ---
    riders = [
        Rider(
            "rider_a", "A. Alpha", "GBR", is_sl=False, first_seen_date=datetime.date(2025, 1, 1)
        ),
        Rider("rider_b", "B. Bravo", "SUI", is_sl=True, first_seen_date=datetime.date(2025, 1, 1)),
        Rider(
            "rider_c", "C. Charlie", "USA", is_sl=False, first_seen_date=datetime.date(2025, 1, 1)
        ),
    ]
    for r in riders:
        db.upsert_rider(r)

    # --- Races ---
    races = [
        Race(
            "PRACTICE_TOP_2025-01-10",
            "PRACTICE",
            datetime.date(2025, 1, 10),
            "TOP",
            is_handicap_race=False,
            is_practice=True,
            pdf_source="p1.pdf",
        ),
        Race(
            "STAGNI_CUP_2025-01-15",
            "THE STAGNI CUP",
            datetime.date(2025, 1, 15),
            "TOP",
            is_handicap_race=True,
            is_practice=False,
            pdf_source="p2.pdf",
        ),
        Race(
            "PRACTICE_JUNC_2025-01-10",
            "PRACTICE",
            datetime.date(2025, 1, 10),
            "JUNCTION",
            is_handicap_race=False,
            is_practice=True,
            pdf_source="p1.pdf",
        ),
    ]
    for race in races:
        db.insert_race(race)

    # --- Time records ---
    records = [
        # Practice TOP — rider_a: 2 runs
        TimeRecord("r1", "PRACTICE_TOP_2025-01-10", "rider_a", 1, finish_time=55.0),
        TimeRecord("r2", "PRACTICE_TOP_2025-01-10", "rider_a", 2, finish_time=54.5),
        # Practice TOP — rider_b (SL): 1 run
        TimeRecord("r3", "PRACTICE_TOP_2025-01-10", "rider_b", 1, finish_time=60.0),
        # Practice TOP — rider_c: 1 run, a fall (should be excluded)
        TimeRecord(
            "r4",
            "PRACTICE_TOP_2025-01-10",
            "rider_c",
            1,
            finish_time=None,
            is_fall=True,
            fall_location="S",
        ),
        # Practice TOP — rider_c: 1 valid run
        TimeRecord("r5", "PRACTICE_TOP_2025-01-10", "rider_c", 2, finish_time=57.0),
        # Stagni Cup TOP — rider_a
        TimeRecord("r6", "STAGNI_CUP_2025-01-15", "rider_a", 1, finish_time=53.0),
        # Stagni Cup TOP — rider_b (SL)
        TimeRecord("r7", "STAGNI_CUP_2025-01-15", "rider_b", 1, finish_time=58.5),
        # Stagni Cup TOP — rider_c
        TimeRecord("r8", "STAGNI_CUP_2025-01-15", "rider_c", 1, finish_time=56.0),
        # JUNCTION practice — rider_a (different start position)
        TimeRecord("r9", "PRACTICE_JUNC_2025-01-10", "rider_a", 1, finish_time=45.0),
    ]
    for rec in records:
        db.insert_time_record(rec)

    db.close()
    return db_path


class TestBuildStanData:
    def test_basic_shape(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        assert data["N"] > 0
        assert data["J"] > 0
        assert data["S"] == 1
        assert data["R"] > 0

    def test_fall_excluded(self, sample_db):
        """Falls should not appear in the data."""
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        # We have 7 valid TOP records (r1,r2,r3,r5,r6,r7,r8), 1 fall excluded (r4)
        assert data["N"] == 7

    def test_junction_separation(self, sample_db):
        """JUNCTION data should be separate from TOP."""
        data = build_stan_data(sample_db, "JUNCTION", min_runs=1)
        assert data["N"] == 1  # only r9
        assert data["J"] == 1  # only rider_a

    def test_rider_indices_contiguous(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        rider_indices = data["rider"]
        assert min(rider_indices) == 1
        assert max(rider_indices) == data["J"]
        assert set(rider_indices) == set(range(1, data["J"] + 1))

    def test_race_type_indices_contiguous(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        rt_indices = data["race_type"]
        assert min(rt_indices) == 1
        assert max(rt_indices) == data["R"]

    def test_practice_is_index_1(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        race_type_map = data["meta_race_type_map"]
        assert race_type_map["PRACTICE"] == 1

    def test_is_sl_array(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        rider_map = data["meta_rider_map"]
        is_sl = data["is_sl"]
        # rider_b is SL
        assert is_sl[rider_map["rider_b"] - 1] == 1
        # rider_a is not SL
        assert is_sl[rider_map["rider_a"] - 1] == 0

    def test_run_seq_per_rider(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        df = data["meta_df"]
        # rider_a has 3 valid TOP runs (r1, r2, r6) -> run_seq 1, 2, 3
        rider_a_seqs = sorted(df.loc[df["rider_id"] == "rider_a", "run_seq"].tolist())
        assert rider_a_seqs == [1, 2, 3]
        # rider_b has 2 valid TOP runs (r3, r7) -> run_seq 1, 2
        rider_b_seqs = sorted(df.loc[df["rider_id"] == "rider_b", "run_seq"].tolist())
        assert rider_b_seqs == [1, 2]

    def test_prior_mu_top(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        assert data["prior_mu_pop"] == 57.0

    def test_prior_mu_junction(self, sample_db):
        data = build_stan_data(sample_db, "JUNCTION", min_runs=1)
        assert data["prior_mu_pop"] == 48.0

    def test_y_values_are_floats(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        assert data["y"].dtype == np.float64

    def test_invalid_position_raises(self, sample_db):
        with pytest.raises(ValueError, match="start_position must be"):
            build_stan_data(sample_db, "BOTTOM")

    def test_outlier_filtering(self, tmp_path):
        """Times > 3x median should be excluded."""
        db_path = tmp_path / "outlier.db"
        db = CrestaDB(db_path)

        db.upsert_rider(Rider("r1", "Test", "GBR", first_seen_date=datetime.date(2025, 1, 1)))
        db.insert_race(
            Race(
                "PRAC_2025-01-10",
                "PRACTICE",
                datetime.date(2025, 1, 10),
                "TOP",
                is_handicap_race=False,
                is_practice=True,
            )
        )

        # Normal times around 55s, one extreme outlier at 200s
        for i in range(10):
            db.insert_time_record(
                TimeRecord(
                    f"rec_{i}",
                    "PRAC_2025-01-10",
                    "r1",
                    i + 1,
                    finish_time=55.0 + i * 0.5,
                )
            )
        db.insert_time_record(
            TimeRecord(
                "outlier",
                "PRAC_2025-01-10",
                "r1",
                11,
                finish_time=200.0,  # > 3 * ~57 = 171
            )
        )
        db.close()

        data = build_stan_data(db_path, "TOP", min_runs=1)
        assert 200.0 not in data["y"]
        assert data["N"] == 10

    def test_stan_data_array_lengths(self, sample_db):
        """All observation-level arrays must have length N."""
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        n_obs = data["N"]
        assert len(data["rider"]) == n_obs
        assert len(data["season"]) == n_obs
        assert len(data["race_type"]) == n_obs
        assert len(data["y"]) == n_obs
        assert len(data["run_seq"]) == n_obs

    def test_is_sl_array_length(self, sample_db):
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        assert len(data["is_sl"]) == data["J"]

    def test_min_runs_filtering(self, sample_db):
        """min_runs=3 should exclude riders with < 3 observations."""
        # With min_runs=1: all 3 riders included (rider_a:3, rider_b:2, rider_c:2)
        data_all = build_stan_data(sample_db, "TOP", min_runs=1)
        assert data_all["J"] == 3

        # With min_runs=3: only rider_a (3 runs) survives
        data_filtered = build_stan_data(sample_db, "TOP", min_runs=3)
        assert data_filtered["J"] == 1
        assert data_filtered["N"] == 3
        assert "rider_a" in data_filtered["meta_rider_map"]

    def test_prior_sigma_season_sd(self, sample_db):
        """With S=1, prior_sigma_season_sd should be 0.01."""
        data = build_stan_data(sample_db, "TOP", min_runs=1)
        assert data["prior_sigma_season_sd"] == 0.01
