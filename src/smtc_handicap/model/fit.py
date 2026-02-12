"""Compile and fit the Stan hierarchical handicap model."""

from __future__ import annotations

from pathlib import Path

from cmdstanpy import CmdStanMCMC, CmdStanModel

_STAN_FILE = Path(__file__).resolve().parent.parent / "stan" / "cresta_handicap.stan"


def compile_model(stan_file: str | Path | None = None) -> CmdStanModel:
    """Compile the Stan model. Cached by CmdStanPy if unchanged."""
    path = Path(stan_file) if stan_file else _STAN_FILE
    if not path.exists():
        raise FileNotFoundError(f"Stan file not found: {path}")
    return CmdStanModel(stan_file=str(path))


def fit_model(
    model: CmdStanModel,
    stan_data: dict,
    *,
    chains: int = 4,
    iter_warmup: int = 1000,
    iter_sampling: int = 2000,
    adapt_delta: float = 0.9,
    max_treedepth: int = 12,
) -> CmdStanMCMC:
    """Run MCMC sampling and return the fit object.

    The ``stan_data`` dict may contain ``meta_*`` keys (ignored by CmdStanPy).
    """
    # Strip metadata keys before passing to Stan
    clean_data = {k: v for k, v in stan_data.items() if not k.startswith("meta_")}

    fit = model.sample(
        data=clean_data,
        chains=chains,
        iter_warmup=iter_warmup,
        iter_sampling=iter_sampling,
        adapt_delta=adapt_delta,
        max_treedepth=max_treedepth,
    )
    return fit
