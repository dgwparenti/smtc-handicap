"""Handicap optimizer for the SMTC Handicap Planner.

Uses scipy Nelder-Mead to find handicaps that minimise the top-K net time
spread as computed by the Monte Carlo race simulator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from smtc_handicap.model.race_simulator import SimulationResult, simulate_race


@dataclass
class OptimizationResult:
    """Result of a handicap optimisation run."""

    handicaps: np.ndarray  # (n_riders,) optimised values
    simulation: SimulationResult  # final simulation with optimised handicaps
    n_iterations: int  # number of objective function evaluations
    initial_spread: float  # top-K spread before optimisation
    final_spread: float  # top-K spread after optimisation


def optimize_handicaps(
    mu_draws: np.ndarray,  # (D, n_riders) expected single-run time per draw
    sigma_draws: np.ndarray,  # (D, n_riders) per-rider noise per draw
    initial_handicaps: np.ndarray,  # (n_riders,) starting handicap values
    scratch_idx: int,  # index of scratch rider (fixed at 0.0)
    frozen_indices: set[int],  # indices whose handicaps don't change
    n_runs: int = 3,  # runs per race
    top_k: int = 6,  # top riders for spread metric
    seed: int | None = None,  # random seed
) -> OptimizationResult:
    """Find handicaps that minimise the top-K net time spread.

    Uses scipy Nelder-Mead optimisation.  The scratch rider's handicap is
    always fixed at 0.0.  Riders listed in *frozen_indices* keep their
    initial handicap values throughout.  All free-parameter handicaps are
    clamped to >= 0.0 inside the objective.

    Parameters
    ----------
    mu_draws:
        (D, n_riders) expected single-run times per posterior draw.
    sigma_draws:
        (D, n_riders) per-rider observation noise per draw.
    initial_handicaps:
        (n_riders,) starting handicap values in seconds.
    scratch_idx:
        Index of the scratch rider; their handicap is always 0.0.
    frozen_indices:
        Set of rider indices whose handicap is held fixed.
    n_runs:
        Number of runs per race in the simulation.
    top_k:
        Number of top finishers used for spread calculation.
    seed:
        Random seed passed to :func:`simulate_race`.

    Returns
    -------
    OptimizationResult
    """
    n_riders = initial_handicaps.shape[0]

    # Determine which riders are free to be optimised
    fixed_indices = frozen_indices | {scratch_idx}
    free_indices = [i for i in range(n_riders) if i not in fixed_indices]

    # Starting values for free parameters
    x0 = initial_handicaps[free_indices].copy()

    # Compute initial spread with the starting handicaps
    initial_sim = simulate_race(
        mu_draws=mu_draws,
        sigma_draws=sigma_draws,
        handicaps=initial_handicaps,
        n_runs=n_runs,
        top_k=top_k,
        seed=seed,
    )
    initial_spread = initial_sim.top_k_spread

    eval_count = [0]

    def objective(x: np.ndarray) -> float:
        eval_count[0] += 1
        # Reconstruct full handicap vector
        h = initial_handicaps.copy()
        for xi, idx in zip(x, free_indices, strict=True):
            h[idx] = max(0.0, xi)
        h[scratch_idx] = 0.0
        sim = simulate_race(
            mu_draws=mu_draws,
            sigma_draws=sigma_draws,
            handicaps=h,
            n_runs=n_runs,
            top_k=top_k,
            seed=seed,
        )
        return sim.top_k_spread

    result = minimize(
        objective,
        x0,
        method="Nelder-Mead",
        options={"maxiter": 200, "xatol": 0.01, "fatol": 0.01},
    )

    # Build final optimised handicap vector (clamp free params >= 0)
    optimised_handicaps = initial_handicaps.copy()
    for xi, idx in zip(result.x, free_indices, strict=True):
        optimised_handicaps[idx] = max(0.0, xi)
    optimised_handicaps[scratch_idx] = 0.0

    # Final simulation with optimised handicaps
    final_sim = simulate_race(
        mu_draws=mu_draws,
        sigma_draws=sigma_draws,
        handicaps=optimised_handicaps,
        n_runs=n_runs,
        top_k=top_k,
        seed=seed,
    )

    return OptimizationResult(
        handicaps=optimised_handicaps,
        simulation=final_sim,
        n_iterations=eval_count[0],
        initial_spread=initial_spread,
        final_spread=final_sim.top_k_spread,
    )
