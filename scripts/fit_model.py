#!/usr/bin/env python3
"""Fit the multi-season Bayesian handicap model for a given start position."""

import argparse
import time
from pathlib import Path

from smtc_handicap.model import run_model
from smtc_handicap.model.data_prep import build_stan_data

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fit the Bayesian handicap model for a given start position"
    )
    parser.add_argument(
        "--position",
        type=str,
        choices=["TOP", "JUNCTION"],
        required=True,
        help="Start position to fit (TOP or JUNCTION)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "cresta.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "model_fits",
        help="Directory for saving InferenceData (.nc)",
    )
    parser.add_argument("--chains", type=int, default=4, help="Number of MCMC chains")
    parser.add_argument(
        "--iter-warmup", type=int, default=1000, help="Warmup iterations per chain"
    )
    parser.add_argument(
        "--iter-sampling", type=int, default=2000, help="Sampling iterations per chain"
    )
    args = parser.parse_args()

    position = args.position

    # Preview data dimensions before fitting
    print("=" * 60)
    print(f"CRESTA RUN HANDICAP MODEL — {position}")
    print("=" * 60)

    stan_data = build_stan_data(args.db, position)
    print(f"\nData summary:")
    print(f"  Observations (N): {stan_data['N']:,}")
    print(f"  Riders (J):       {stan_data['J']:,}")
    print(f"  Seasons (S):      {stan_data['S']}")
    print(f"  Race types (R):   {stan_data['R']}")
    season_map = stan_data["meta_season_map"]
    seasons = sorted(season_map.keys())
    print(f"  Seasons:          {seasons[0]}–{seasons[-1]}")
    print(f"\nMCMC settings:")
    print(f"  Chains:           {args.chains}")
    print(f"  Warmup:           {args.iter_warmup}")
    print(f"  Sampling:         {args.iter_sampling}")
    print()

    # Fit the model
    t0 = time.time()
    result = run_model(
        args.db,
        position,
        chains=args.chains,
        iter_warmup=args.iter_warmup,
        iter_sampling=args.iter_sampling,
        output_dir=args.output_dir,
    )
    elapsed = time.time() - t0

    # Diagnostics
    diag = result["diagnostics"]
    print("\n" + "=" * 60)
    print("CONVERGENCE DIAGNOSTICS")
    print("=" * 60)
    print(f"\n{diag['summary'].to_string()}")

    print(f"\n{'Check':<25s} {'Value':>10s}   {'Status'}")
    print("-" * 50)

    rhat_status = "PASS" if diag["rhat_ok"] else "FAIL"
    print(f"{'Max R-hat < 1.01':<25s} {diag['max_rhat']:>10.4f}   {rhat_status}")

    ess_status = "PASS" if diag["ess_ok"] else "FAIL"
    print(f"{'Min ESS bulk > 400':<25s} {diag['min_ess_bulk']:>10.0f}   {ess_status}")

    div_status = "PASS" if diag["divergences"] == 0 else "FAIL"
    print(f"{'Divergences == 0':<25s} {diag['divergences']:>10d}   {div_status}")

    print("-" * 50)
    overall = "ALL PASSED" if diag["passed"] else "SOME CHECKS FAILED"
    print(f"Overall: {overall}")

    nc_path = args.output_dir / f"{position.lower()}.nc"
    print(f"\nInferenceData saved to: {nc_path}")
    print(f"Fitting time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")


if __name__ == "__main__":
    main()
