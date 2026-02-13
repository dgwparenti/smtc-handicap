#!/usr/bin/env python3
"""Compare race tightness under committee vs Bayesian handicaps.

For each TOP handicap race, compute net times (finish_time - handicap)
under both systems, sum 3 runs per rider, rank riders, and measure
tightness (range of net times) among the top 3, 6, and 10 finishers.
"""

import json
import sqlite3
from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"
NC_PATH = PROJECT_ROOT / "data" / "model_fits" / "top.nc"
OUTPUT_CSV = PROJECT_ROOT / "data" / "handicap_comparison.csv"

TOP_GROUPS = [3, 6, 10]


def _date_to_season(date_str: str) -> int:
    """Map a race date to its Cresta season year (Nov/Dec -> next year)."""
    parts = date_str.split("-")
    year, month = int(parts[0]), int(parts[1])
    return year + 1 if month >= 11 else year


def load_bayesian_model(nc_path: Path) -> dict:
    """Load posterior means and metadata from the fitted model."""
    print(f"Loading model fit from {nc_path} ...")
    idata = az.from_netcdf(str(nc_path))

    rider_map: dict[str, int] = json.loads(idata.attrs["rider_map"])
    season_num = idata.constant_data["season_num"].values  # (S,)

    alpha_mean = idata.posterior["alpha"].mean(dim=["chain", "draw"]).values
    beta_trend_mean = idata.posterior["beta_trend"].mean(dim=["chain", "draw"]).values

    J = len(alpha_mean)
    S = len(season_num)
    print(f"  {J} riders, {S} seasons")
    print(f"  season_num range: [{season_num[0]:.1f}, {season_num[-1]:.1f}]")

    return {
        "rider_map": rider_map,
        "season_num": season_num,
        "alpha_mean": alpha_mean,
        "beta_trend_mean": beta_trend_mean,
    }


def build_season_lookup(season_num: np.ndarray, db_path: Path) -> dict[int, float]:
    """Build season_year -> season_num_value mapping.

    Reconstructs season years from the centered season_num array by
    anchoring to the latest TOP race date in the database.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        max_date = conn.execute(
            "SELECT MAX(date) FROM races WHERE start_position = 'TOP'"
        ).fetchone()[0]
    finally:
        conn.close()

    max_season = _date_to_season(max_date)
    mean_year = max_season - season_num[-1]
    season_years = np.round(season_num + mean_year).astype(int)

    lookup = dict(zip(season_years.tolist(), season_num.tolist()))
    years_str = ", ".join(f"{y}: {v:+.1f}" for y, v in lookup.items())
    print(f"  Season lookup: {{{years_str}}}")
    return lookup


def query_handicap_races(db_path: Path) -> pd.DataFrame:
    """Query all TOP handicap race data (runs 1-3 only)."""
    conn = sqlite3.connect(str(db_path))
    try:
        query = """
            SELECT tr.rider_id, tr.race_id, tr.run_number, tr.finish_time,
                   tr.handicap, tr.is_fall, tr.is_dnf,
                   r.name AS race_name, r.date AS race_date,
                   rd.display_name
            FROM time_records tr
            JOIN races r ON tr.race_id = r.race_id
            JOIN riders rd ON tr.rider_id = rd.rider_id
            WHERE r.start_position = 'TOP'
              AND r.is_handicap_race = 1
              AND tr.run_number <= 3
            ORDER BY r.date, tr.rider_id, tr.run_number
        """
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    n_races = df["race_id"].nunique()
    date_range = f"{df['race_date'].min()} to {df['race_date'].max()}"
    print(f"\nHandicap race data: {len(df)} rows, {n_races} races ({date_range})")
    return df


def process_race(
    race_df: pd.DataFrame,
    model: dict,
    season_lookup: dict[int, float],
) -> dict | None:
    """Process a single handicap race and compute tightness metrics."""
    race_id = race_df["race_id"].iloc[0]
    race_name = race_df["race_name"].iloc[0]
    race_date = race_df["race_date"].iloc[0]

    season_year = _date_to_season(race_date)
    season_num_val = season_lookup.get(season_year)

    # Keep only valid runs (no falls, no DNFs, valid times and handicaps)
    valid = race_df[
        (race_df["is_fall"] == 0)
        & (race_df["is_dnf"] == 0)
        & race_df["finish_time"].notna()
        & race_df["handicap"].notna()
    ]

    # Keep only riders with exactly 3 valid runs
    rider_agg = valid.groupby("rider_id").agg(
        n_runs=("run_number", "count"),
        total_time=("finish_time", "sum"),
        handicap=("handicap", "first"),
        display_name=("display_name", "first"),
    )
    riders = rider_agg[rider_agg["n_runs"] == 3].copy()

    if len(riders) < 3:
        return None

    # Committee net times: total_time - 3 * handicap
    riders["committee_net"] = riders["total_time"] - 3 * riders["handicap"]

    # Find scratch rider (committee handicap = 0)
    scratch_ids = riders[riders["handicap"] == 0.0].index.tolist()

    # Bayesian net times
    has_bayes = False
    if season_num_val is not None and len(scratch_ids) > 0:
        scratch_id = scratch_ids[0]
        rider_map = model["rider_map"]

        if scratch_id in rider_map:
            j_scratch = rider_map[scratch_id] - 1
            scratch_ability = (
                model["alpha_mean"][j_scratch]
                + model["beta_trend_mean"][j_scratch] * season_num_val
            )

            bayes_nets = {}
            for rider_id in riders.index:
                if rider_id not in rider_map:
                    continue
                j = rider_map[rider_id] - 1
                ability = model["alpha_mean"][j] + model["beta_trend_mean"][j] * season_num_val
                bayes_handicap = ability - scratch_ability
                bayes_nets[rider_id] = riders.loc[rider_id, "total_time"] - 3 * bayes_handicap

            if len(bayes_nets) >= 3:
                riders["bayes_net"] = pd.Series(bayes_nets)
                has_bayes = True

    result = {
        "race_id": race_id,
        "race_name": race_name,
        "race_date": race_date,
        "n_riders": len(riders),
        "n_bayes_riders": len(riders["bayes_net"].dropna()) if has_bayes else 0,
    }

    # Tightness for each group size
    comm_ranked = riders.sort_values("committee_net")

    for n in TOP_GROUPS:
        col_c = f"committee_top{n}"
        col_b = f"bayes_top{n}"

        if len(comm_ranked) >= n:
            top_c = comm_ranked.head(n)["committee_net"]
            result[col_c] = float(top_c.max() - top_c.min())
        else:
            result[col_c] = None

        if has_bayes:
            bayes_ranked = riders.dropna(subset=["bayes_net"]).sort_values("bayes_net")
            if len(bayes_ranked) >= n:
                top_b = bayes_ranked.head(n)["bayes_net"]
                result[col_b] = float(top_b.max() - top_b.min())
            else:
                result[col_b] = None
        else:
            result[col_b] = None

    return result


def print_per_race_table(df: pd.DataFrame) -> None:
    """Print per-race tightness table."""
    print("\n" + "=" * 70)
    print("PER-RACE TIGHTNESS (seconds, range among top N finishers)")
    print("=" * 70)

    # Header
    group_labels = "".join(f"  {'Top ' + str(n):^11s}" for n in TOP_GROUPS)
    print(f"\n{'Date':<12s} {'Race':<25s} {'N':>3s}{group_labels}")
    col_labels = "".join(f"  {'Comm':>5s} {'Bayes':>5s}" for _ in TOP_GROUPS)
    print(f"{'':>40s}{col_labels}")
    print("-" * (40 + 13 * len(TOP_GROUPS)))

    for _, row in df.iterrows():
        line = f"{row['race_date']:<12s} {str(row['race_name'])[:25]:<25s} {row['n_riders']:>3d}"
        for n in TOP_GROUPS:
            c = row.get(f"committee_top{n}")
            b = row.get(f"bayes_top{n}")
            c_str = f"{c:5.1f}" if pd.notna(c) else "    -"
            b_str = f"{b:5.1f}" if pd.notna(b) else "    -"
            line += f"  {c_str} {b_str}"
        print(line)


def print_summary(df: pd.DataFrame) -> None:
    """Print summary statistics across all races."""
    print("\n" + "=" * 70)
    print("SUMMARY ACROSS ALL RACES")
    print("=" * 70)

    for n in TOP_GROUPS:
        c_col = f"committee_top{n}"
        b_col = f"bayes_top{n}"

        valid = df[[c_col, b_col]].dropna()
        if valid.empty:
            print(f"\n  Top {n}: No races with both committee and Bayesian data")
            continue

        c_vals = valid[c_col]
        b_vals = valid[b_col]
        diff = c_vals.values - b_vals.values  # positive = Bayesian tighter

        print(f"\n  Top {n} finishers ({len(valid)} races):")
        print(f"    {'Metric':<20s} {'Committee':>10s} {'Bayesian':>10s} {'Diff':>10s}")
        print(f"    {'-' * 52}")
        print(
            f"    {'Mean tightness':<20s} "
            f"{c_vals.mean():>10.1f} {b_vals.mean():>10.1f} {diff.mean():>+10.1f}"
        )
        print(
            f"    {'Median tightness':<20s} "
            f"{c_vals.median():>10.1f} {b_vals.median():>10.1f} {np.median(diff):>+10.1f}"
        )
        print(
            f"    {'Min tightness':<20s} "
            f"{c_vals.min():>10.1f} {b_vals.min():>10.1f} {diff.min():>+10.1f}"
        )
        print(
            f"    {'Max tightness':<20s} "
            f"{c_vals.max():>10.1f} {b_vals.max():>10.1f} {diff.max():>+10.1f}"
        )

        n_tighter = int((diff > 0).sum())
        pct = 100 * n_tighter / len(valid)
        print(f"    Bayesian tighter in {n_tighter}/{len(valid)} races ({pct:.0f}%)")


def main() -> None:
    print("=" * 70)
    print("RACE TIGHTNESS: COMMITTEE vs BAYESIAN HANDICAPS — TOP")
    print("=" * 70)
    print()

    model = load_bayesian_model(NC_PATH)
    season_lookup = build_season_lookup(model["season_num"], DB_PATH)

    race_data = query_handicap_races(DB_PATH)

    results = []
    for _, race_df in race_data.groupby("race_id"):
        result = process_race(race_df, model, season_lookup)
        if result is not None:
            results.append(result)

    if not results:
        print("\nNo races with enough valid data!")
        return

    df = pd.DataFrame(results).sort_values("race_date").reset_index(drop=True)

    print(f"\nProcessed {len(df)} races with >= 3 eligible riders")

    print_per_race_table(df)
    print_summary(df)

    # Save CSV
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nCSV saved to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
