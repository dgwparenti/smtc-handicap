"""Compute handicaps from posterior samples."""

from __future__ import annotations

import numpy as np
import pandas as pd
from cmdstanpy import CmdStanMCMC


def get_posterior_samples(fit: CmdStanMCMC) -> dict[str, np.ndarray]:
    """Extract key parameter arrays from the fit.

    Returns dict with arrays shaped (num_draws, ...):
      - alpha: (D, J)
      - eta: (D, S)
      - beta_trend: (D, J)
      - beta_trend_mu: (D,)
      - sigma_trend: (D,)
      - gamma: (D, R)
      - beta_improve: (D,)
      - sigma_obs: (D,)
    """
    draws = fit.draws_pd()

    alpha_cols = sorted(
        [c for c in draws.columns if c.startswith("alpha[")],
        key=lambda c: int(c.split("[")[1].rstrip("]")),
    )
    alpha = draws[alpha_cols].values  # (D, J)

    eta_cols = sorted(
        [c for c in draws.columns if c.startswith("eta[")],
        key=lambda c: int(c.split("[")[1].rstrip("]")),
    )
    eta = draws[eta_cols].values  # (D, S)

    beta_trend_cols = sorted(
        [c for c in draws.columns if c.startswith("beta_trend[")],
        key=lambda c: int(c.split("[")[1].rstrip("]")),
    )
    beta_trend = draws[beta_trend_cols].values  # (D, J)

    gamma_cols = sorted(
        [c for c in draws.columns if c.startswith("gamma[")],
        key=lambda c: int(c.split("[")[1].rstrip("]")),
    )
    gamma = draws[gamma_cols].values  # (D, R)

    sigma_obs = draws["sigma_obs"].values  # (D,)
    beta_improve = draws["beta_improve"].values  # (D,)
    beta_trend_mu = draws["beta_trend_mu"].values  # (D,)
    sigma_trend = draws["sigma_trend"].values  # (D,)

    return {
        "alpha": alpha,
        "eta": eta,
        "beta_trend": beta_trend,
        "beta_trend_mu": beta_trend_mu,
        "sigma_trend": sigma_trend,
        "gamma": gamma,
        "beta_improve": beta_improve,
        "sigma_obs": sigma_obs,
    }


def _compute_rider_consistency(stan_data: dict, posterior: dict) -> dict[str, float]:
    """Compute per-rider residual SD post-hoc from posterior mean predictions."""
    df = stan_data["meta_df"]
    rider_map = stan_data["meta_rider_map"]
    season_num = stan_data["season_num"]

    # Use posterior means for prediction
    alpha_mean = posterior["alpha"].mean(axis=0)
    eta_mean = posterior["eta"].mean(axis=0)
    beta_trend_mean = posterior["beta_trend"].mean(axis=0)
    gamma_mean = posterior["gamma"].mean(axis=0)
    beta_mean = float(posterior["beta_improve"].mean())

    residuals_by_rider: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        rid = row["rider_id"]
        j = rider_map[rid] - 1
        s = int(row["season_idx"]) - 1
        r = int(row["race_type_idx"]) - 1
        pred = alpha_mean[j] + eta_mean[s] + beta_trend_mean[j] * season_num[s] + gamma_mean[r]
        if stan_data["is_sl"][j]:
            pred += beta_mean * row["run_seq"]
        residual = row["finish_time"] - pred
        residuals_by_rider.setdefault(rid, []).append(residual)

    consistency = {}
    for rid, resids in residuals_by_rider.items():
        if len(resids) >= 2:
            consistency[rid] = float(np.std(resids, ddof=1))
        else:
            # Not enough data — use the shared sigma_obs as fallback
            consistency[rid] = float(posterior["sigma_obs"].mean())
    return consistency


def calculate_handicaps(
    fit: CmdStanMCMC,
    stan_data: dict,
    field_rider_ids: list[str],
    race_type_idx: int,
    season_idx: int = 1,
) -> pd.DataFrame:
    """Compute handicaps for a field of riders in a given race type.

    Parameters
    ----------
    fit : fitted CmdStanMCMC object
    stan_data : the dict returned by build_stan_data (includes meta_ keys)
    field_rider_ids : list of rider_id strings to include
    race_type_idx : 1-based index into race types
    season_idx : 1-based season index (default 1)

    Returns
    -------
    DataFrame with columns:
        rider_id, display_name, expected_time, handicap_mean,
        handicap_lo, handicap_hi, consistency, run_count, confidence
    """
    rider_map = stan_data["meta_rider_map"]
    df = stan_data["meta_df"]
    season_num = stan_data["season_num"]

    posterior = get_posterior_samples(fit)
    num_draws = posterior["alpha"].shape[0]
    rider_consistency = _compute_rider_consistency(stan_data, posterior)

    # Resolve rider indices and metadata
    riders_info = []
    for rid in field_rider_ids:
        if rid not in rider_map:
            continue
        idx = rider_map[rid] - 1  # 0-based for numpy
        run_count = int((df["rider_id"] == rid).sum())
        is_sl = stan_data["is_sl"][idx]
        max_run_seq = float(df.loc[df["rider_id"] == rid, "run_seq"].max())
        riders_info.append(
            {
                "rider_id": rid,
                "idx": idx,
                "run_count": run_count,
                "is_sl": is_sl,
                "max_run_seq": max_run_seq,
            }
        )

    if not riders_info:
        return pd.DataFrame()

    # Compute predicted times: (num_draws, num_riders)
    n_field = len(riders_info)
    pred_times = np.zeros((num_draws, n_field))

    s = season_idx - 1  # 0-based for numpy
    r = race_type_idx - 1  # 0-based for numpy

    for i, info in enumerate(riders_info):
        j = info["idx"]

        pred_times[:, i] = (
            posterior["alpha"][:, j]
            + posterior["eta"][:, s]
            + posterior["beta_trend"][:, j] * season_num[s]
            + posterior["gamma"][:, r]
        )
        if info["is_sl"]:
            next_run = info["max_run_seq"] + 1
            pred_times[:, i] += posterior["beta_improve"] * next_run

    # Handicap = rider time - scratch (fastest) time per draw
    scratch_times = pred_times.min(axis=1, keepdims=True)  # (D, 1)
    handicaps = pred_times - scratch_times  # (D, n_field)

    # Summaries
    results = []
    for i, info in enumerate(riders_info):
        h_mean = float(np.mean(handicaps[:, i]))
        h_lo = float(np.percentile(handicaps[:, i], 2.5))
        h_hi = float(np.percentile(handicaps[:, i], 97.5))
        exp_time = float(np.mean(pred_times[:, i]))
        consistency = rider_consistency.get(info["rider_id"], float(posterior["sigma_obs"].mean()))

        run_count = info["run_count"]
        ci_width = h_hi - h_lo
        if run_count >= 20 and ci_width < 3.0:
            confidence = "HIGH"
        elif run_count >= 10:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        results.append(
            {
                "rider_id": info["rider_id"],
                "expected_time": round(exp_time, 2),
                "handicap_mean": round(h_mean, 2),
                "handicap_lo": round(h_lo, 2),
                "handicap_hi": round(h_hi, 2),
                "consistency": round(consistency, 2),
                "run_count": run_count,
                "confidence": confidence,
            }
        )

    return pd.DataFrame(results).sort_values("handicap_mean").reset_index(drop=True)
