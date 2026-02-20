"""Compute handicaps from posterior samples."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import arviz as az
    from cmdstanpy import CmdStanMCMC


def _extract_from_cmdstanmcmc(fit: CmdStanMCMC) -> dict[str, np.ndarray]:
    """Extract posterior samples from a CmdStanMCMC object."""
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

    # Global quadratic season curvature (may not exist in older models)
    beta_quad = draws["beta_quad"].values if "beta_quad" in draws.columns else None  # (D,)

    # Per-rider sigma (heteroscedastic model)
    sigma_rider_cols = sorted(
        [c for c in draws.columns if c.startswith("sigma_rider[")],
        key=lambda c: int(c.split("[")[1].rstrip("]")),
    )
    sigma_rider = draws[sigma_rider_cols].values if sigma_rider_cols else None  # (D, J)

    return {
        "alpha": alpha,
        "eta": eta,
        "beta_trend": beta_trend,
        "beta_trend_mu": beta_trend_mu,
        "sigma_trend": sigma_trend,
        "gamma": gamma,
        "beta_improve": beta_improve,
        "beta_quad": beta_quad,
        "sigma_obs": sigma_obs,
        "sigma_rider": sigma_rider,
    }


def _extract_var(posterior: object, name: str) -> np.ndarray | None:
    """Extract a variable from an xarray posterior, stacking chains+draws into rows."""
    if name not in posterior:
        return None
    return posterior[name].stack(sample=("chain", "draw")).values.T


def _extract_from_inferencedata(idata: az.InferenceData) -> dict[str, np.ndarray]:
    """Extract posterior samples from an ArviZ InferenceData object."""
    post = idata.posterior
    return {
        "alpha": _extract_var(post, "alpha"),  # (D, J)
        "eta": _extract_var(post, "eta"),  # (D, S)
        "beta_trend": _extract_var(post, "beta_trend"),  # (D, J)
        "beta_trend_mu": _extract_var(post, "beta_trend_mu"),  # (D,)
        "sigma_trend": _extract_var(post, "sigma_trend"),  # (D,)
        "gamma": _extract_var(post, "gamma"),  # (D, R)
        "beta_improve": _extract_var(post, "beta_improve"),  # (D,)
        "beta_quad": _extract_var(post, "beta_quad"),  # (D,) or None
        "sigma_obs": _extract_var(post, "sigma_obs"),  # (D,)
        "sigma_rider": _extract_var(post, "sigma_rider"),  # (D, J) or None
    }


def get_posterior_samples(fit: CmdStanMCMC | az.InferenceData) -> dict[str, np.ndarray]:
    """Extract key parameter arrays from a fit.

    Accepts either a CmdStanMCMC object or an ArviZ InferenceData object.

    Returns dict with arrays shaped (num_draws, ...):
      - alpha: (D, J)
      - eta: (D, S)
      - beta_trend: (D, J)
      - beta_trend_mu: (D,)
      - sigma_trend: (D,)
      - gamma: (D, R)
      - beta_improve: (D,)
      - beta_quad: (D,) or None
      - sigma_obs: (D,)
      - sigma_rider: (D, J) or None (if per-rider sigma model)
    """
    # Duck-type: InferenceData has a .posterior attribute
    if hasattr(fit, "posterior"):
        return _extract_from_inferencedata(fit)
    return _extract_from_cmdstanmcmc(fit)


def _compute_rider_consistency(stan_data: dict, posterior: dict) -> dict[str, float]:
    """Compute per-rider consistency (observation noise SD).

    If the model includes per-rider sigma_rider, use the posterior mean directly.
    Otherwise, fall back to computing residual SD post-hoc.
    """
    rider_map = stan_data["meta_rider_map"]

    # If per-rider sigma available from model, use it directly
    if posterior.get("sigma_rider") is not None:
        sigma_rider_mean = posterior["sigma_rider"].mean(axis=0)  # (J,)
        consistency = {}
        for rider_id, idx in rider_map.items():
            consistency[rider_id] = float(sigma_rider_mean[idx - 1])
        return consistency

    # Fallback: compute from residuals (for models without per-rider sigma)
    df = stan_data["meta_df"]
    season_num = stan_data["season_num"]

    alpha_mean = posterior["alpha"].mean(axis=0)
    eta_mean = posterior["eta"].mean(axis=0)
    beta_trend_mean = posterior["beta_trend"].mean(axis=0)
    gamma_mean = posterior["gamma"].mean(axis=0)
    beta_mean = float(posterior["beta_improve"].mean())
    beta_quad_mean = (
        float(posterior["beta_quad"].mean()) if posterior.get("beta_quad") is not None else 0.0
    )

    residuals_by_rider: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        rid = row["rider_id"]
        j = rider_map[rid] - 1
        s = int(row["season_idx"]) - 1
        r = int(row["race_type_idx"]) - 1
        pred = (
            alpha_mean[j]
            + eta_mean[s]
            + beta_trend_mean[j] * season_num[s]
            + beta_quad_mean * season_num[s] ** 2
            + gamma_mean[r]
        )
        if stan_data["is_sl"][j]:
            pred += beta_mean * row["run_seq"]
        residual = row["finish_time"] - pred
        residuals_by_rider.setdefault(rid, []).append(residual)

    consistency = {}
    for rid, resids in residuals_by_rider.items():
        if len(resids) >= 2:
            consistency[rid] = float(np.std(resids, ddof=1))
        else:
            consistency[rid] = float(posterior["sigma_obs"].mean())
    return consistency


def calculate_handicaps(
    fit: CmdStanMCMC | az.InferenceData,
    stan_data: dict,
    field_rider_ids: list[str],
    race_type_idx: int,
    season_idx: int = 1,
    scratch_rider_id: str | None = None,
) -> pd.DataFrame:
    """Compute handicaps for a field of riders in a given race type.

    Parameters
    ----------
    fit : fitted CmdStanMCMC or ArviZ InferenceData object
    stan_data : the dict returned by build_stan_data (includes meta_ keys)
    field_rider_ids : list of rider_id strings to include
    race_type_idx : 1-based index into race types
    season_idx : 1-based season index (default 1)
    scratch_rider_id : if provided, use this rider as scratch (handicap=0).
        Falls back to auto-detection (fastest predicted) if the rider
        is not in the field.

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
        # Quadratic season curvature
        if posterior.get("beta_quad") is not None:
            pred_times[:, i] += posterior["beta_quad"] * season_num[s] ** 2

        if info["is_sl"]:
            next_run = info["max_run_seq"] + 1
            pred_times[:, i] += posterior["beta_improve"] * next_run

    # Quantile-based consistency adjustment for tighter handicaps.
    # Shift predicted times to each rider's competitive quantile (p=0.10),
    # using posterior mean of per-rider sigma (not per-draw, to reduce noise).
    # Cap the maximum shift to prevent over-adjustment for very volatile riders.
    # === TUNABLE PARAMETERS (Ralph Loop optimizes these) ===
    phi_inv_p = -1.4051  # scipy.stats.norm.ppf(0.08) — lower = more aggressive
    max_shift = -2.5  # Cap on quantile shift (more negative = less capping)
    # === END TUNABLE PARAMETERS ===

    if posterior.get("sigma_rider") is not None:
        # Use posterior mean of sigma_rider for stable quantile shift
        sigma_mean = posterior["sigma_rider"].mean(axis=0)  # (J,)
        sigma_arr = np.array([sigma_mean[info["idx"]] for info in riders_info])
        raw_shift = sigma_arr * phi_inv_p  # negative values
        capped_shift = np.maximum(raw_shift, max_shift)  # cap magnitude
        pred_q = pred_times + capped_shift[np.newaxis, :]
    else:
        # Post-hoc fallback: use residual SD for consistency adjustment
        consistency_arr = np.array(
            [
                rider_consistency.get(info["rider_id"], float(posterior["sigma_obs"].mean()))
                for info in riders_info
            ]
        )
        raw_shift = consistency_arr * phi_inv_p
        capped_shift = np.maximum(raw_shift, max_shift)
        pred_q = pred_times + capped_shift[np.newaxis, :]

    # Fix scratch rider across all draws to avoid switching noise.
    # Use committee-designated scratch if provided, else auto-detect fastest.
    scratch_idx = None
    if scratch_rider_id is not None:
        for i, info in enumerate(riders_info):
            if info["rider_id"] == scratch_rider_id:
                scratch_idx = i
                break
    if scratch_idx is None:
        mean_pred_q = pred_q.mean(axis=0)  # (n_field,)
        scratch_idx = int(np.argmin(mean_pred_q))
    scratch_q = pred_q[:, scratch_idx : scratch_idx + 1]  # (D, 1)
    handicaps = pred_q - scratch_q  # (D, n_field)
    handicaps[:, scratch_idx] = 0.0  # exact zero for scratch rider

    # Summaries
    results = []
    for i, info in enumerate(riders_info):
        # Median for robust handicap estimate (insensitive to extreme draws)
        h_mean = float(np.median(handicaps[:, i]))
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
