"""Convergence diagnostics for the fitted Stan model."""

from __future__ import annotations

import json
from pathlib import Path

import arviz as az
from cmdstanpy import CmdStanMCMC


def check_diagnostics(fit: CmdStanMCMC, stan_data: dict | None = None) -> dict:
    """Run standard MCMC convergence checks.

    Parameters
    ----------
    fit : the fitted CmdStanMCMC object
    stan_data : optional data dict from build_stan_data. If provided, the
        returned InferenceData will include observed data, constant data,
        posterior predictive, log-likelihood, and metadata attributes.

    Returns a dict with:
      - passed: bool — True if all checks pass
      - rhat_ok: bool
      - ess_ok: bool
      - divergences: int
      - max_rhat: float
      - min_ess_bulk: float
      - summary: pd.DataFrame (arviz summary of key params)
      - idata: arviz InferenceData
    """
    az_kwargs: dict = {}
    if stan_data is not None:
        az_kwargs["posterior_predictive"] = "y_rep"
        az_kwargs["log_likelihood"] = "log_lik"
        az_kwargs["observed_data"] = {"y": stan_data["y"]}
        az_kwargs["constant_data"] = {
            "rider": stan_data["rider"],
            "season": stan_data["season"],
            "race_type": stan_data["race_type"],
            "is_sl": stan_data["is_sl"],
            "run_seq": stan_data["run_seq"],
        }

    idata = az.from_cmdstanpy(fit, **az_kwargs)

    if stan_data is not None:
        idata.attrs["start_position"] = stan_data.get("meta_start_position", "")
        idata.attrs["rider_map"] = json.dumps(stan_data["meta_rider_map"])
        idata.attrs["race_type_map"] = json.dumps(stan_data["meta_race_type_map"])

    key_params = [
        "mu_pop",
        "sigma_pop",
        "sigma_obs",
        "sigma_season",
        "sigma_race",
        "beta_improve",
    ]
    summary = az.summary(idata, var_names=key_params)

    max_rhat = summary["r_hat"].max()
    min_ess = summary["ess_bulk"].min()

    divergences = int(idata.sample_stats["diverging"].sum().item())

    rhat_ok = max_rhat < 1.01
    ess_ok = min_ess > 400
    div_ok = divergences == 0

    return {
        "passed": rhat_ok and ess_ok and div_ok,
        "rhat_ok": rhat_ok,
        "ess_ok": ess_ok,
        "divergences": divergences,
        "max_rhat": float(max_rhat),
        "min_ess_bulk": float(min_ess),
        "summary": summary,
        "idata": idata,
    }


def save_inference_data(idata: az.InferenceData, output_path: str | Path) -> Path:
    """Save InferenceData to a NetCDF file.

    Parameters
    ----------
    idata : arviz InferenceData (from check_diagnostics)
    output_path : path for the .nc file

    Returns
    -------
    Path to the saved file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    idata.to_netcdf(str(output_path))
    return output_path
