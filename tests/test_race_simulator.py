"""Tests for the race simulator module."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy", reason="scipy not installed (install with [ui])")

pytestmark = pytest.mark.ui

from smtc_handicap.model.race_simulator import (  # noqa: E402
    RiderSimStats,
    SimulationResult,
    build_prediction_arrays,
    simulate_race,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _constant_posterior(
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
# TestSimulateRace
# ---------------------------------------------------------------------------


class TestSimulateRace:
    """Tests for simulate_race."""

    def test_returns_simulation_result_type(self):
        """simulate_race returns a SimulationResult."""
        mu, sigma = _constant_posterior(n_draws=50, n_riders=4, mu_val=55.0, sigma_val=1.0)
        handicaps = np.zeros(4)
        result = simulate_race(mu, sigma, handicaps, seed=42)
        assert isinstance(result, SimulationResult)

    def test_result_structure(self):
        """SimulationResult has correct fields and rider_stats length matches n_riders."""
        n_riders = 6
        n_draws = 100
        mu, sigma = _constant_posterior(
            n_draws=n_draws, n_riders=n_riders, mu_val=55.0, sigma_val=1.0
        )
        handicaps = np.zeros(n_riders)
        result = simulate_race(mu, sigma, handicaps, seed=42)

        assert isinstance(result.top_k_spread, float)
        assert isinstance(result.n_draws, int)
        assert result.n_draws == n_draws
        assert len(result.rider_stats) == n_riders
        for stat in result.rider_stats:
            assert isinstance(stat, RiderSimStats)

    def test_rider_stats_fields(self):
        """RiderSimStats has all required fields with correct types."""
        mu, sigma = _constant_posterior(n_draws=50, n_riders=3, mu_val=55.0, sigma_val=1.0)
        handicaps = np.zeros(3)
        result = simulate_race(mu, sigma, handicaps, seed=1)
        stat = result.rider_stats[0]

        assert isinstance(stat.median_rank, float)
        assert isinstance(stat.rank_lo, int)
        assert isinstance(stat.rank_hi, int)
        assert isinstance(stat.win_pct, float)
        assert isinstance(stat.median_gross, float)
        assert isinstance(stat.median_net, float)

    def test_equal_riders_equal_handicaps_roughly_equal_win_rates(self):
        """Equal mu/sigma/handicap → each rider wins ~equally often."""
        n_riders = 5
        n_draws = 2000
        mu, sigma = _constant_posterior(
            n_draws=n_draws, n_riders=n_riders, mu_val=55.0, sigma_val=2.0
        )
        handicaps = np.zeros(n_riders)
        result = simulate_race(mu, sigma, handicaps, n_runs=3, seed=0)

        win_pcts = [s.win_pct for s in result.rider_stats]
        expected = 100.0 / n_riders  # 20%
        for wp in win_pcts:
            assert abs(wp - expected) < 8.0, f"win_pct {wp:.1f}% too far from {expected:.1f}%"

    def test_handicap_equalizes_unequal_riders(self):
        """Rider 0 is faster but slower riders get a compensating handicap.

        Sign convention: net = gross - n_runs * handicap.
        Scratch rider (fastest) gets handicap=0; slower riders get a positive
        handicap that is subtracted from their net, making them competitive.
        Equalisation: net_0 == net_others
          3*52 - 3*0 = 156  vs  3*55 - 3*3 = 156  →  equal expected nets.
        """
        n_draws = 2000
        n_riders = 4
        # Rider 0 is 3s/run faster than others
        mu = np.full((n_draws, n_riders), 55.0)
        mu[:, 0] = 52.0
        sigma = np.full((n_draws, n_riders), 1.5)
        # Correct equalisation: scratch rider (fastest) = 0, others get +3s handicap
        # net_0 = 3*52 - 3*0 = 156, net_others = 3*55 - 3*3 = 165-9 = 156
        handicaps = np.array([0.0, 3.0, 3.0, 3.0])
        result = simulate_race(mu, sigma, handicaps, n_runs=3, seed=42)

        win_pcts = [s.win_pct for s in result.rider_stats]
        # All riders should have broadly similar win rates
        for wp in win_pcts:
            assert 10.0 < wp < 50.0, f"Expected balanced win_pct, got {wp:.1f}%"

    def test_faster_rider_wins_without_handicap(self):
        """Without handicap, much faster rider wins nearly always."""
        n_draws = 500
        n_riders = 4
        mu = np.full((n_draws, n_riders), 58.0)
        mu[:, 0] = 50.0  # rider 0 is 8s faster — wins almost always
        sigma = np.full((n_draws, n_riders), 0.5)
        handicaps = np.zeros(n_riders)
        result = simulate_race(mu, sigma, handicaps, n_runs=3, seed=7)

        assert result.rider_stats[0].win_pct > 90.0

    def test_good_handicaps_reduce_spread(self):
        """Race with well-calibrated handicaps has smaller top_k_spread than no-handicap."""
        n_draws = 500
        n_riders = 6
        # Riders span a range of abilities
        mu_vals = np.array([50.0, 52.0, 54.0, 56.0, 58.0, 60.0])
        mu = np.tile(mu_vals, (n_draws, 1))
        sigma = np.full((n_draws, n_riders), 1.5)

        # No handicaps
        no_hcap = np.zeros(n_riders)
        result_no = simulate_race(mu, sigma, no_hcap, n_runs=3, top_k=6, seed=10)

        # Calibrated handicaps (scratch = rider 0, others get increasing handicap)
        handicaps = mu_vals - mu_vals[0]
        result_hcap = simulate_race(mu, sigma, handicaps, n_runs=3, top_k=6, seed=10)

        assert result_hcap.top_k_spread < result_no.top_k_spread

    def test_tiny_sigma_gross_near_n_runs_times_mu(self):
        """With near-zero sigma, gross ≈ n_runs * mu for each rider."""
        n_draws = 20
        n_runs = 3
        mu_val = 55.0
        n_riders = 4
        mu = np.full((n_draws, n_riders), mu_val)
        sigma = np.full((n_draws, n_riders), 1e-6)
        handicaps = np.zeros(n_riders)
        result = simulate_race(mu, sigma, handicaps, n_runs=n_runs, seed=99)

        for stat in result.rider_stats:
            assert abs(stat.median_gross - n_runs * mu_val) < 0.01

    def test_seed_reproducibility(self):
        """Same seed → same results."""
        n_draws = 100
        mu, sigma = _constant_posterior(n_draws=n_draws, n_riders=4, mu_val=55.0, sigma_val=1.5)
        handicaps = np.array([0.0, 1.0, 2.0, 3.0])

        r1 = simulate_race(mu, sigma, handicaps, seed=123)
        r2 = simulate_race(mu, sigma, handicaps, seed=123)

        assert r1.top_k_spread == r2.top_k_spread
        for s1, s2 in zip(r1.rider_stats, r2.rider_stats, strict=True):
            assert s1.win_pct == s2.win_pct
            assert s1.median_rank == s2.median_rank


# ---------------------------------------------------------------------------
# TestBuildPredictionArrays
# ---------------------------------------------------------------------------


class TestBuildPredictionArrays:
    """Tests for build_prediction_arrays."""

    def _make_posterior(
        self,
        n_draws: int = 50,
        n_riders_total: int = 5,
        n_seasons: int = 3,
        n_race_types: int = 4,
        *,
        include_beta_quad: bool = False,
        include_sigma_rider: bool = True,
    ) -> dict[str, np.ndarray | None]:
        rng = np.random.default_rng(0)
        post: dict[str, np.ndarray | None] = {
            "alpha": rng.normal(55.0, 1.0, (n_draws, n_riders_total)),
            "eta": rng.normal(0.0, 0.5, (n_draws, n_seasons)),
            "beta_trend": rng.normal(-0.1, 0.05, (n_draws, n_riders_total)),
            "gamma": rng.normal(0.0, 0.3, (n_draws, n_race_types)),
            "sigma_obs": rng.gamma(2.0, 1.0, (n_draws,)),
            "beta_quad": rng.normal(0.0, 0.01, (n_draws,)) if include_beta_quad else None,
            "sigma_rider": (
                rng.gamma(2.0, 0.5, (n_draws, n_riders_total)) if include_sigma_rider else None
            ),
        }
        return post

    def test_output_shapes(self):
        """build_prediction_arrays returns (mu, sigma) with shape (n_draws, n_riders)."""
        nd, nj, ns, nr = 50, 5, 3, 4
        post = self._make_posterior(n_draws=nd, n_riders_total=nj, n_seasons=ns, n_race_types=nr)
        rider_indices = [0, 1, 2]
        season_num = np.linspace(-1.0, 1.0, ns)

        mu_draws, sigma_draws = build_prediction_arrays(
            post,
            rider_indices=rider_indices,
            season_idx=1,
            race_type_idx=0,
            season_num=season_num,
        )

        assert mu_draws.shape == (nd, len(rider_indices))
        assert sigma_draws.shape == (nd, len(rider_indices))

    def test_mu_reflects_alpha(self):
        """mu_draws includes alpha: set eta/beta_trend/gamma=0 → mu_draws == alpha[:, idx]."""
        nd, nj, ns, nr = 30, 3, 2, 2
        rng = np.random.default_rng(1)
        alpha_vals = rng.normal(55.0, 2.0, (nd, nj))
        post: dict[str, np.ndarray | None] = {
            "alpha": alpha_vals,
            "eta": np.zeros((nd, ns)),
            "beta_trend": np.zeros((nd, nj)),
            "gamma": np.zeros((nd, nr)),
            "sigma_obs": np.ones(nd),
            "beta_quad": None,
            "sigma_rider": None,
        }
        season_num = np.zeros(ns)  # season_num = 0 → beta_trend term vanishes
        rider_indices = [0, 1, 2]

        mu_draws, _ = build_prediction_arrays(
            post,
            rider_indices=rider_indices,
            season_idx=0,
            race_type_idx=0,
            season_num=season_num,
        )

        # mu_draws[:, i] should equal alpha[:, rider_indices[i]]
        for i, idx in enumerate(rider_indices):
            np.testing.assert_array_almost_equal(mu_draws[:, i], alpha_vals[:, idx])

    def test_sigma_from_sigma_rider(self):
        """When sigma_rider is available, sigma_draws uses per-rider columns."""
        nd, nj, ns, nr = 40, 4, 2, 2
        rng = np.random.default_rng(2)
        sigma_rider = rng.gamma(2.0, 0.5, (nd, nj))
        post: dict[str, np.ndarray | None] = {
            "alpha": np.full((nd, nj), 55.0),
            "eta": np.zeros((nd, ns)),
            "beta_trend": np.zeros((nd, nj)),
            "gamma": np.zeros((nd, nr)),
            "sigma_obs": np.ones(nd) * 99.0,  # should NOT be used
            "beta_quad": None,
            "sigma_rider": sigma_rider,
        }
        season_num = np.zeros(ns)
        rider_indices = [1, 3]

        _, sigma_draws = build_prediction_arrays(
            post,
            rider_indices=rider_indices,
            season_idx=0,
            race_type_idx=0,
            season_num=season_num,
        )

        for i, idx in enumerate(rider_indices):
            np.testing.assert_array_almost_equal(sigma_draws[:, i], sigma_rider[:, idx])

    def test_sigma_fallback_to_sigma_obs(self):
        """When sigma_rider is None, sigma_draws broadcasts sigma_obs."""
        nd, nj, ns, nr = 30, 3, 2, 2
        sigma_obs_vals = np.linspace(1.5, 2.5, nd)
        post: dict[str, np.ndarray | None] = {
            "alpha": np.full((nd, nj), 55.0),
            "eta": np.zeros((nd, ns)),
            "beta_trend": np.zeros((nd, nj)),
            "gamma": np.zeros((nd, nr)),
            "sigma_obs": sigma_obs_vals,
            "beta_quad": None,
            "sigma_rider": None,
        }
        season_num = np.zeros(ns)
        rider_indices = [0, 2]

        _, sigma_draws = build_prediction_arrays(
            post,
            rider_indices=rider_indices,
            season_idx=0,
            race_type_idx=0,
            season_num=season_num,
        )

        # Each column of sigma_draws should equal sigma_obs
        for i in range(len(rider_indices)):
            np.testing.assert_array_almost_equal(sigma_draws[:, i], sigma_obs_vals)

    def test_beta_quad_affects_mu(self):
        """When beta_quad is present, mu includes the quadratic season term."""
        nd, nj, ns, nr = 20, 2, 3, 2
        beta_q = np.ones(nd) * 0.5  # constant for easy math
        season_num = np.array([-1.0, 0.0, 1.0])
        season_idx = 2  # season_num[2] = 1.0 → beta_quad * 1.0^2 = 0.5

        post: dict[str, np.ndarray | None] = {
            "alpha": np.full((nd, nj), 55.0),
            "eta": np.zeros((nd, ns)),
            "beta_trend": np.zeros((nd, nj)),
            "gamma": np.zeros((nd, nr)),
            "sigma_obs": np.ones(nd),
            "beta_quad": beta_q,
            "sigma_rider": None,
        }
        rider_indices = [0]

        mu_with_quad, _ = build_prediction_arrays(
            post,
            rider_indices=rider_indices,
            season_idx=season_idx,
            race_type_idx=0,
            season_num=season_num,
        )

        post_no_quad = dict(post)
        post_no_quad["beta_quad"] = None
        mu_no_quad, _ = build_prediction_arrays(
            post_no_quad,
            rider_indices=rider_indices,
            season_idx=season_idx,
            race_type_idx=0,
            season_num=season_num,
        )

        # Difference should be beta_quad * season_num[season_idx]^2 = 0.5
        diff = mu_with_quad - mu_no_quad
        np.testing.assert_array_almost_equal(diff, 0.5)
