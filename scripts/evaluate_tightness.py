#!/usr/bin/env python3
"""Fit the Bayesian handicap model and evaluate net-time tightness vs committee.

This script:
1. Fits the TOP model with min_runs=50
2. For each handicap race with ≥5 riders in the model, computes:
   - Committee net time = finish_time - committee_handicap
   - Model net time = finish_time - bayesian_handicap_mean
3. Takes the top 5 finishers by net time, computes range (max − min)
4. Prints per-race and aggregate comparison
5. Prints PASS if avg model range < 1.0s, else FAIL
"""

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from smtc_handicap.model.data_prep import build_stan_data
from smtc_handicap.model.predict import calculate_handicaps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"
MIN_RUNS = 50  # FIXED — do not change
MIN_RIDERS_PER_RACE = 5
TOP_N = 5  # top finishers to evaluate tightness on


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate handicap model tightness vs committee")
    parser.add_argument(
        "--load-fit",
        type=Path,
        metavar="PATH",
        help="Load a pre-fitted model from ArviZ NetCDF instead of re-fitting",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("TIGHTNESS EVALUATION — TOP Handicap Model (min_runs=50)")
    print("=" * 70)

    # ---- Step 1: Build data and fit/load model ----
    print("\n[1/3] Building Stan data...")
    stan_data = build_stan_data(DB_PATH, "TOP", min_runs=MIN_RUNS)
    print(f"  N={stan_data['N']:,}  J={stan_data['J']}  S={stan_data['S']}  R={stan_data['R']}")

    if args.load_fit:
        import arviz as az

        print(f"\n[2/3] Loading pre-fitted model from {args.load_fit}...")
        fit = az.from_netcdf(args.load_fit)
        print("  Loaded.")
    else:
        from smtc_handicap.model.fit import compile_model, fit_model

        print("\n[2/3] Compiling and fitting model...")
        t0 = time.time()
        model = compile_model()
        fit = fit_model(model, stan_data)
        elapsed = time.time() - t0
        print(f"  Fit complete in {elapsed:.0f}s ({elapsed / 60:.1f} min)")

    # ---- Step 2: Identify handicap races ----
    meta_df = stan_data["meta_df"]
    handicap_df = meta_df[meta_df["handicap"].notna()].copy()

    print(f"\n[3/3] Evaluating tightness...")
    print(f"  Records with committee handicap: {len(handicap_df)}")

    race_groups = handicap_df.groupby("race_id")
    print(f"  Handicap races found: {len(race_groups)}")

    # ---- Step 3: Per-race comparison ----
    results = []

    for race_id, group in race_groups:
        rider_ids = group["rider_id"].unique().tolist()

        if len(rider_ids) < MIN_RIDERS_PER_RACE:
            continue

        # All riders in meta_df are in the model — take race_type_idx and season_idx
        race_type_idx = int(group["race_type_idx"].iloc[0])
        season_idx = int(group["season_idx"].iloc[0])

        # Find committee-designated scratch rider (handicap == 0.0)
        scratch_rows = group[group["handicap"] == 0.0]
        scratch_rider_id = scratch_rows["rider_id"].iloc[0] if len(scratch_rows) > 0 else None

        # Calculate Bayesian handicaps
        hcap_df = calculate_handicaps(
            fit,
            stan_data,
            rider_ids,
            race_type_idx,
            season_idx,
            scratch_rider_id=scratch_rider_id,
        )

        if len(hcap_df) < MIN_RIDERS_PER_RACE:
            continue

        # Merge with actual finish times and committee handicap
        # Use the first (or only) record per rider in this race
        race_records = group.drop_duplicates(subset="rider_id")[
            ["rider_id", "finish_time", "handicap"]
        ].copy()
        race_records = race_records.rename(columns={"handicap": "committee_handicap"})

        merged = race_records.merge(
            hcap_df[["rider_id", "handicap_mean"]], on="rider_id", how="inner"
        )

        if len(merged) < MIN_RIDERS_PER_RACE:
            continue

        # Compute net times
        merged["committee_net"] = merged["finish_time"] - merged["committee_handicap"]
        merged["model_net"] = merged["finish_time"] - merged["handicap_mean"]

        # Top 5 by committee net (ascending = fastest)
        top5_committee = merged.nsmallest(TOP_N, "committee_net")
        committee_range = (
            top5_committee["committee_net"].max() - top5_committee["committee_net"].min()
        )

        # Top 5 by model net (ascending = fastest)
        top5_model = merged.nsmallest(TOP_N, "model_net")
        model_range = top5_model["model_net"].max() - top5_model["model_net"].min()

        race_name = group["race_name"].iloc[0]
        race_date = group["race_date"].iloc[0]

        results.append(
            {
                "race_id": race_id,
                "race_name": race_name,
                "race_date": race_date,
                "n_riders": len(merged),
                "committee_top5_range": round(committee_range, 2),
                "model_top5_range": round(model_range, 2),
                "diff": round(model_range - committee_range, 2),
                "model_tighter": model_range < committee_range,
            }
        )

    # ---- Step 4: Print results ----
    if not results:
        print("\n  ERROR: No qualifying races found!")
        print("FAIL")
        return

    results_df = pd.DataFrame(results).sort_values("race_date")

    print(f"\n  Qualifying races (≥{MIN_RIDERS_PER_RACE} riders): {len(results_df)}")
    print()
    print("=" * 90)
    print(
        f"{'Race':<30s} {'Date':<12s} {'#':<4s} {'Comm.Range':>10s} {'Model.Range':>11s} {'Diff':>7s} {'Tighter?':>8s}"
    )
    print("-" * 90)

    for _, row in results_df.iterrows():
        name = row["race_name"][:28]
        tighter = "YES" if row["model_tighter"] else "no"
        print(
            f"{name:<30s} {row['race_date']:<12s} {row['n_riders']:<4d} "
            f"{row['committee_top5_range']:>10.2f} {row['model_top5_range']:>11.2f} "
            f"{row['diff']:>7.2f} {tighter:>8s}"
        )

    print("-" * 90)

    # Aggregates
    avg_committee = results_df["committee_top5_range"].mean()
    avg_model = results_df["model_top5_range"].mean()
    pct_tighter = results_df["model_tighter"].mean() * 100
    n_tighter = results_df["model_tighter"].sum()
    n_total = len(results_df)

    print()
    print(f"  Average committee top-5 range: {avg_committee:.3f}s")
    print(f"  Average model top-5 range:     {avg_model:.3f}s")
    print(f"  Difference (model - committee): {avg_model - avg_committee:.3f}s")
    print(f"  Model tighter in {n_tighter}/{n_total} races ({pct_tighter:.1f}%)")
    print()

    if avg_model < 1.0:
        print("PASS")
    else:
        print("FAIL")


if __name__ == "__main__":
    main()
