"""Bayesian hierarchical handicap model for the Cresta Run."""

from __future__ import annotations

from pathlib import Path

from smtc_handicap.model.data_prep import build_stan_data
from smtc_handicap.model.diagnostics import check_diagnostics, save_inference_data
from smtc_handicap.model.fit import compile_model, fit_model
from smtc_handicap.model.handicap_optimizer import optimize_handicaps
from smtc_handicap.model.predict import calculate_handicaps
from smtc_handicap.model.race_simulator import build_prediction_arrays, simulate_race


def run_model(
    db_path: str | Path,
    start_position: str,
    *,
    chains: int = 4,
    iter_warmup: int = 1000,
    iter_sampling: int = 2000,
    output_dir: str | Path | None = None,
) -> dict:
    """Full pipeline: data prep -> compile -> fit -> diagnostics.

    Parameters
    ----------
    db_path : path to the SQLite database
    start_position : "TOP" or "JUNCTION"
    chains, iter_warmup, iter_sampling : MCMC settings
    output_dir : if provided, save InferenceData as NetCDF to this directory
        (e.g. ``data/model_fits/``). File is named ``{start_position.lower()}.nc``.

    Returns
    -------
    dict with keys:
      - fit: CmdStanMCMC object
      - stan_data: the data dict (with meta_ keys)
      - diagnostics: diagnostics summary dict
      - start_position: echoed back
    """
    stan_data = build_stan_data(db_path, start_position)

    if stan_data["N"] < 20:
        raise ValueError(
            f"Only {stan_data['N']} observations for {start_position}; "
            "need at least 20 for a meaningful fit."
        )

    model = compile_model()
    fit = fit_model(
        model,
        stan_data,
        chains=chains,
        iter_warmup=iter_warmup,
        iter_sampling=iter_sampling,
    )
    diag = check_diagnostics(fit, stan_data)

    if output_dir is not None:
        nc_path = Path(output_dir) / f"{start_position.lower()}.nc"
        save_inference_data(diag["idata"], nc_path)

    return {
        "fit": fit,
        "stan_data": stan_data,
        "diagnostics": diag,
        "start_position": start_position,
    }


__all__ = [
    "build_prediction_arrays",
    "build_stan_data",
    "calculate_handicaps",
    "check_diagnostics",
    "compile_model",
    "fit_model",
    "optimize_handicaps",
    "run_model",
    "save_inference_data",
    "simulate_race",
]
