#!/usr/bin/env python3
"""Grid search over post-processing parameters for JUNCTION handicap model.

Sweeps combinations of handicap_scale, handicap_power, phi_inv_p, and
sigma_shrinkage against the tightness criteria:
  - avg model top-5 range < 1.0s
  - model tighter in >= 70% of races
"""

import argparse
import itertools
from pathlib import Path

import arviz as az
import pandas as pd

from smtc_handicap.model.data_prep import build_stan_data
from smtc_handicap.model.predict import calculate_handicaps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"
MIN_RUNS = 50
MIN_RIDERS_PER_RACE = 5
TOP_N = 5


def evaluate_params(
    fit,
    stan_data: dict,
    race_groups,
    handicap_df: pd.DataFrame,
    *,
    phi_inv_p: float,
    max_shift: float,
    sigma_shrinkage: float,
    handicap_scale: float,
    handicap_power: float,
    auto_scratch: bool = False,
) -> dict:
    """Evaluate tightness for a single parameter combination."""
    results = []
    for race_id, group in race_groups:
        rider_ids = group["rider_id"].unique().tolist()
        if len(rider_ids) < MIN_RIDERS_PER_RACE:
            continue

        race_type_idx = int(group["race_type_idx"].iloc[0])
        season_idx = int(group["season_idx"].iloc[0])

        scratch_rider_id = None
        if not auto_scratch:
            scratch_rows = group[group["handicap"] == 0.0]
            scratch_rider_id = scratch_rows["rider_id"].iloc[0] if len(scratch_rows) > 0 else None

        hcap_df = calculate_handicaps(
            fit,
            stan_data,
            rider_ids,
            race_type_idx,
            season_idx,
            scratch_rider_id=scratch_rider_id,
            phi_inv_p=phi_inv_p,
            max_shift=max_shift,
            sigma_shrinkage=sigma_shrinkage,
            handicap_scale=handicap_scale,
            handicap_power=handicap_power,
        )

        if len(hcap_df) < MIN_RIDERS_PER_RACE:
            continue

        race_records = group.drop_duplicates(subset="rider_id")[
            ["rider_id", "finish_time", "handicap"]
        ].copy()
        race_records = race_records.rename(columns={"handicap": "committee_handicap"})

        merged = race_records.merge(
            hcap_df[["rider_id", "handicap_mean"]], on="rider_id", how="inner"
        )

        if len(merged) < MIN_RIDERS_PER_RACE:
            continue

        merged["committee_net"] = merged["finish_time"] - merged["committee_handicap"]
        merged["model_net"] = merged["finish_time"] - merged["handicap_mean"]

        top5_committee = merged.nsmallest(TOP_N, "committee_net")
        committee_range = (
            top5_committee["committee_net"].max() - top5_committee["committee_net"].min()
        )

        top5_model = merged.nsmallest(TOP_N, "model_net")
        model_range = top5_model["model_net"].max() - top5_model["model_net"].min()

        results.append(
            {
                "committee_range": committee_range,
                "model_range": model_range,
                "model_tighter": model_range < committee_range,
            }
        )

    if not results:
        return {"avg_range": 999.0, "win_rate": 0.0, "n_races": 0}

    results_df = pd.DataFrame(results)
    return {
        "avg_range": results_df["model_range"].mean(),
        "win_rate": results_df["model_tighter"].mean() * 100,
        "n_races": len(results_df),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid search JUNCTION post-processing params")
    parser.add_argument("--load-fit", type=Path, required=True, help="Path to junction.nc")
    parser.add_argument("--top-n", type=int, default=20, help="Show top N results")
    args = parser.parse_args()

    print("=" * 70)
    print("JUNCTION GRID SEARCH — Post-Processing Parameters")
    print("=" * 70)

    print("\n[1/3] Building Stan data...")
    stan_data = build_stan_data(DB_PATH, "JUNCTION", min_runs=MIN_RUNS)
    print(f"  N={stan_data['N']:,}  J={stan_data['J']}  S={stan_data['S']}  R={stan_data['R']}")

    print(f"\n[2/3] Loading fit from {args.load_fit}...")
    fit = az.from_netcdf(args.load_fit)
    print("  Loaded.")

    meta_df = stan_data["meta_df"]
    handicap_df = meta_df[meta_df["handicap"].notna()].copy()
    race_groups = list(handicap_df.groupby("race_id"))
    print(f"  Handicap races: {len(race_groups)}")

    # Parameter grid
    scales = [0.8, 0.9, 1.0, 1.1, 1.175, 1.25, 1.3, 1.5, 1.75, 2.0]
    powers = [0.5, 0.6, 0.7, 0.75, 0.8, 0.84, 0.9, 1.0]
    phis = [-0.80, -1.00, -1.20, -1.30, -1.40, -1.60]
    shrinkages = [0.0, 0.5, 1.0]

    combos = list(itertools.product(scales, powers, phis, shrinkages))
    print(f"\n[3/3] Evaluating {len(combos)} parameter combinations...")

    all_results = []
    for i, (scale, power, phi, shrink) in enumerate(combos):
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(combos)}...")

        result = evaluate_params(
            fit,
            stan_data,
            race_groups,
            handicap_df,
            phi_inv_p=phi,
            max_shift=-2.5,
            sigma_shrinkage=shrink,
            handicap_scale=scale,
            handicap_power=power,
        )
        all_results.append(
            {
                "scale": scale,
                "power": power,
                "phi_inv_p": phi,
                "shrinkage": shrink,
                "avg_range": round(result["avg_range"], 3),
                "win_rate": round(result["win_rate"], 1),
                "n_races": result["n_races"],
                "pass": result["avg_range"] < 1.0 and result["win_rate"] >= 70.0,
            }
        )

    df = pd.DataFrame(all_results)

    # Sort by: PASS first, then by combined score (low range + high win_rate)
    df["score"] = df["avg_range"] - df["win_rate"] / 100  # lower is better
    df = df.sort_values(["pass", "score"], ascending=[False, True])

    print("\n" + "=" * 100)
    print(
        f"{'Rank':<5s} {'Scale':>6s} {'Power':>6s} {'Phi':>6s} {'Shrink':>7s} "
        f"{'AvgRange':>9s} {'Win%':>6s} {'#Races':>7s} {'PASS':>5s}"
    )
    print("-" * 100)

    for rank, (_, row) in enumerate(df.head(args.top_n).iterrows(), 1):
        status = "PASS" if row["pass"] else ""
        print(
            f"{rank:<5d} {row['scale']:>6.3f} {row['power']:>6.2f} {row['phi_inv_p']:>6.2f} "
            f"{row['shrinkage']:>7.2f} {row['avg_range']:>9.3f} {row['win_rate']:>6.1f} "
            f"{row['n_races']:>7d} {status:>5s}"
        )

    print("-" * 100)

    n_pass = df["pass"].sum()
    print(f"\n  Total PASS combinations: {n_pass}/{len(df)}")

    if n_pass > 0:
        best = df[df["pass"]].iloc[0]
        print(
            f"\n  BEST PASS: scale={best['scale']}, power={best['power']}, "
            f"phi={best['phi_inv_p']}, shrinkage={best['shrinkage']}"
        )
        print(f"    avg_range={best['avg_range']:.3f}s, win_rate={best['win_rate']:.1f}%")
    else:
        best = df.iloc[0]
        print(
            f"\n  BEST (no PASS): scale={best['scale']}, power={best['power']}, "
            f"phi={best['phi_inv_p']}, shrinkage={best['shrinkage']}"
        )
        print(f"    avg_range={best['avg_range']:.3f}s, win_rate={best['win_rate']:.1f}%")


if __name__ == "__main__":
    main()
