"""Monte Carlo race simulator for the Handicap Planner.

Provides:
- simulate_race: simulate many races from posterior predictive draws
- build_prediction_arrays: compute (mu_draws, sigma_draws) from posterior samples
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RiderSimStats:
    """Per-rider simulation statistics across all posterior draws."""

    median_rank: float
    rank_lo: int  # 5th percentile rank
    rank_hi: int  # 95th percentile rank
    win_pct: float  # percentage (0–100) of draws where rider finishes 1st
    median_gross: float  # median total gross time (sum of n_runs run times)
    median_net: float  # median total net time (gross - n_runs * handicap)


@dataclass
class SimulationResult:
    """Aggregate simulation output."""

    top_k_spread: float  # median across draws of (max - min) among top-k net times
    n_draws: int  # number of posterior draws used
    rider_stats: list[RiderSimStats]  # one entry per rider, same order as input


def simulate_race(
    mu_draws: np.ndarray,  # (D, n_riders) expected single-run time per posterior draw
    sigma_draws: np.ndarray,  # (D, n_riders) per-rider observation noise per draw
    handicaps: np.ndarray,  # (n_riders,) handicap in seconds
    n_runs: int = 3,  # number of runs in the race
    top_k: int = 6,  # top riders for spread calc
    seed: int | None = None,  # for reproducibility
) -> SimulationResult:
    """Simulate many races via Monte Carlo and return outcome statistics.

    Parameters
    ----------
    mu_draws : (D, n_riders) array of expected single-run times per posterior draw
    sigma_draws : (D, n_riders) array of per-rider observation noise per draw
    handicaps : (n_riders,) handicap for each rider in seconds
    n_runs : number of independent runs per rider per race
    top_k : number of top finishers used for spread calculation
    seed : random seed for reproducibility

    Returns
    -------
    SimulationResult with per-rider statistics and race-level spread metric
    """
    rng = np.random.default_rng(seed)
    n_draws, n_riders = mu_draws.shape

    # Sample n_runs independent run times: shape (n_draws, n_riders, n_runs)
    # Each run: observed = mu + Normal(0, sigma)
    noise = rng.standard_normal((n_draws, n_riders, n_runs))
    # broadcasts to (n_draws, n_riders, 1)
    run_times = mu_draws[:, :, np.newaxis] + sigma_draws[:, :, np.newaxis] * noise

    # Total gross = sum over n_runs dimension: shape (n_draws, n_riders)
    gross = run_times.sum(axis=2)

    # Total net = gross - n_runs * handicap; handicaps shape (n_riders,) broadcasts
    net = gross - n_runs * handicaps[np.newaxis, :]

    # Rank riders by net time (1 = best/lowest), shape (n_draws, n_riders)
    order = np.argsort(net, axis=1)
    ranks = np.empty_like(order)
    draw_idx = np.arange(n_draws)[:, np.newaxis]
    pos_idx = np.arange(n_riders)[np.newaxis, :]
    ranks[draw_idx, order] = pos_idx + 1  # 1-based ranks

    # top_k_spread: median across draws of (max - min) among top-k net times
    actual_k = min(top_k, n_riders)
    net_sorted = np.sort(net, axis=1)  # ascending (best first)
    top_k_net = net_sorted[:, :actual_k]
    spreads = top_k_net[:, actual_k - 1] - top_k_net[:, 0]
    top_k_spread = float(np.median(spreads))

    # Per-rider stats
    rider_stats: list[RiderSimStats] = []
    for i in range(n_riders):
        rider_ranks = ranks[:, i]
        win_count = int(np.sum(rider_ranks == 1))
        rider_stats.append(
            RiderSimStats(
                median_rank=float(np.median(rider_ranks)),
                rank_lo=int(np.percentile(rider_ranks, 5)),
                rank_hi=int(np.percentile(rider_ranks, 95)),
                win_pct=100.0 * win_count / n_draws,
                median_gross=float(np.median(gross[:, i])),
                median_net=float(np.median(net[:, i])),
            )
        )

    return SimulationResult(
        top_k_spread=top_k_spread,
        n_draws=n_draws,
        rider_stats=rider_stats,
    )


def build_prediction_arrays(
    posterior: dict[str, np.ndarray | None],  # from get_posterior_samples
    rider_indices: list[int],  # 0-based indices into J dimension
    season_idx: int,  # 0-based into S dimension
    race_type_idx: int,  # 0-based into R dimension
    season_num: np.ndarray,  # (S,) centered season numbers
) -> tuple[np.ndarray, np.ndarray]:  # (mu_draws, sigma_draws)
    """Compute (mu_draws, sigma_draws) for a set of riders in a given season/race-type.

    Parameters
    ----------
    posterior : dict of posterior arrays from get_posterior_samples
    rider_indices : 0-based indices into the J (riders) dimension
    season_idx : 0-based index into the S (seasons) dimension
    race_type_idx : 0-based index into the R (race types) dimension
    season_num : (S,) array of centered season numbers

    Returns
    -------
    mu_draws : (D, n_riders) expected single-run times
    sigma_draws : (D, n_riders) per-rider observation noise
    """
    alpha = posterior["alpha"]  # (n_draws, n_riders_total)
    eta = posterior["eta"]  # (n_draws, n_seasons)
    beta_trend = posterior["beta_trend"]  # (n_draws, n_riders_total)
    gamma = posterior["gamma"]  # (n_draws, n_race_types)
    n_draws = alpha.shape[0]
    n_riders = len(rider_indices)

    idx_arr = np.array(rider_indices)
    sn = float(season_num[season_idx])

    # mu = alpha[:, idx] + eta[:, season_idx]
    #      + beta_trend[:, idx] * season_num[season_idx]
    #      + gamma[:, race_type_idx]
    mu_draws = (
        alpha[:, idx_arr]
        + eta[:, season_idx : season_idx + 1]  # (n_draws, 1) broadcasts
        + beta_trend[:, idx_arr] * sn
        + gamma[:, race_type_idx : race_type_idx + 1]  # (n_draws, 1) broadcasts
    )

    # Optional quadratic season term
    beta_quad = posterior.get("beta_quad")
    if beta_quad is not None:
        # beta_quad: (n_draws,) → (n_draws, 1) broadcasts
        mu_draws = mu_draws + beta_quad[:, np.newaxis] * (sn**2)

    # sigma: use per-rider sigma_rider if available, else broadcast sigma_obs
    sigma_rider = posterior.get("sigma_rider")
    if sigma_rider is not None:
        sigma_draws = sigma_rider[:, idx_arr]  # (n_draws, n_riders)
    else:
        sigma_obs = posterior["sigma_obs"]  # (n_draws,)
        sigma_draws = np.broadcast_to(sigma_obs[:, np.newaxis], (n_draws, n_riders)).copy()

    return mu_draws, sigma_draws
