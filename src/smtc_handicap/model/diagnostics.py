"""Convergence diagnostics for the fitted Stan model."""

from __future__ import annotations

import arviz as az
from cmdstanpy import CmdStanMCMC


def check_diagnostics(fit: CmdStanMCMC) -> dict:
    """Run standard MCMC convergence checks.

    Returns a dict with:
      - passed: bool — True if all checks pass
      - rhat_ok: bool
      - ess_ok: bool
      - divergences: int
      - max_rhat: float
      - min_ess_bulk: float
      - summary: pd.DataFrame (arviz summary of key params)
    """
    idata = az.from_cmdstanpy(fit)

    key_params = ["mu_pop", "sigma_pop", "sigma_obs", "sigma_season", "sigma_race", "beta_improve"]
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
