"""Tests for the handicap optimizer module."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy", reason="scipy not installed (install with [ui])")

pytestmark = pytest.mark.ui

from smtc_handicap.model.handicap_optimizer import (  # noqa: E402
    OptimizationResult,
    optimize_handicaps,
)
from smtc_handicap.model.race_simulator import SimulationResult  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _constant_arrays(
    n_draws: int,
    n_riders: int,
    mu_val: float,
    sigma_val: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (mu_draws, sigma_draws) with constant values across all draws."""
    mu = np.full((n_draws, n_riders), mu_val)
    sigma = np.full((n_draws, n_riders), sigma_val)
    return mu, sigma


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOptimizeHandicaps:
    """Tests for optimize_handicaps."""

    def test_returns_correct_structure(self):
        """optimize_handicaps returns an OptimizationResult with all required fields."""
        n_riders = 3
        n_draws = 200
        mu, sigma = _constant_arrays(
            n_draws=n_draws, n_riders=n_riders, mu_val=55.0, sigma_val=1.0
        )
        initial_handicaps = np.array([0.0, 5.0, 10.0])
        scratch_idx = 0
        frozen_indices: set[int] = set()

        result = optimize_handicaps(
            mu_draws=mu,
            sigma_draws=sigma,
            initial_handicaps=initial_handicaps,
            scratch_idx=scratch_idx,
            frozen_indices=frozen_indices,
            n_runs=3,
            top_k=3,
            seed=42,
        )

        assert isinstance(result, OptimizationResult)
        assert isinstance(result.handicaps, np.ndarray)
        assert result.handicaps.shape == (n_riders,)
        assert isinstance(result.simulation, SimulationResult)
        assert isinstance(result.n_iterations, int)
        assert result.n_iterations >= 0
        assert isinstance(result.initial_spread, float)
        assert isinstance(result.final_spread, float)

    def test_optimized_spread_less_than_initial(self):
        """Optimizer reduces top_k_spread relative to deliberately bad initial handicaps.

        Riders have different speeds: rider 0 is fastest (scratch), rider 4 is slowest.
        Initial handicaps are too small for slower riders, so optimizer should improve spread.
        """
        n_riders = 5
        n_draws = 200
        # Different expected times so handicapping matters
        mu_vals = np.array([50.0, 52.0, 54.0, 56.0, 58.0])
        mu = np.tile(mu_vals, (n_draws, 1))  # (n_draws, n_riders)
        sigma = np.full((n_draws, n_riders), 0.5)

        # Bad initial handicaps: too small for slow riders
        initial_handicaps = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        scratch_idx = 0
        frozen_indices: set[int] = set()

        result = optimize_handicaps(
            mu_draws=mu,
            sigma_draws=sigma,
            initial_handicaps=initial_handicaps,
            scratch_idx=scratch_idx,
            frozen_indices=frozen_indices,
            n_runs=3,
            top_k=5,
            seed=42,
        )

        assert result.final_spread <= result.initial_spread

    def test_scratch_rider_stays_zero(self):
        """Scratch rider's handicap is always exactly 0.0 after optimization."""
        n_riders = 4
        n_draws = 200
        mu_vals = np.array([50.0, 53.0, 56.0, 59.0])
        mu = np.tile(mu_vals, (n_draws, 1))
        sigma = np.full((n_draws, n_riders), 1.0)

        initial_handicaps = np.array([0.0, 3.0, 6.0, 9.0])
        scratch_idx = 0
        frozen_indices: set[int] = set()

        result = optimize_handicaps(
            mu_draws=mu,
            sigma_draws=sigma,
            initial_handicaps=initial_handicaps,
            scratch_idx=scratch_idx,
            frozen_indices=frozen_indices,
            n_runs=3,
            top_k=4,
            seed=42,
        )

        assert result.handicaps[scratch_idx] == 0.0

    def test_frozen_riders_unchanged(self):
        """Frozen riders' handicaps are not changed by the optimizer."""
        n_riders = 4
        n_draws = 200
        mu_vals = np.array([50.0, 53.0, 56.0, 59.0])
        mu = np.tile(mu_vals, (n_draws, 1))
        sigma = np.full((n_draws, n_riders), 1.0)

        initial_handicaps = np.array([0.0, 3.0, 6.0, 7.0])
        scratch_idx = 0
        frozen_indices = {2}  # rider 2 frozen at 6.0

        result = optimize_handicaps(
            mu_draws=mu,
            sigma_draws=sigma,
            initial_handicaps=initial_handicaps,
            scratch_idx=scratch_idx,
            frozen_indices=frozen_indices,
            n_runs=3,
            top_k=4,
            seed=42,
        )

        assert result.handicaps[2] == pytest.approx(6.0)

    def test_all_handicaps_non_negative(self):
        """All optimized handicaps are >= 0.0."""
        n_riders = 5
        n_draws = 200
        # All riders similar speed so optimizer might try negative handicaps
        mu = np.full((n_draws, n_riders), 55.0)
        sigma = np.full((n_draws, n_riders), 2.0)

        initial_handicaps = np.array([0.0, 2.0, 4.0, 6.0, 8.0])
        scratch_idx = 0
        frozen_indices: set[int] = set()

        result = optimize_handicaps(
            mu_draws=mu,
            sigma_draws=sigma,
            initial_handicaps=initial_handicaps,
            scratch_idx=scratch_idx,
            frozen_indices=frozen_indices,
            n_runs=3,
            top_k=5,
            seed=42,
        )

        assert np.all(result.handicaps >= 0.0)
