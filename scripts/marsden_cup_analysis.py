#!/usr/bin/env python3
"""Marsden Cup 2026 — Bayesian Handicap Analysis.

Queries the Marsden Cup 2026 race data from the DB, loads the fitted TOP model,
computes committee vs Bayesian handicaps, and outputs an Excel file with
tightness metrics.
"""

import sqlite3
from pathlib import Path

import arviz as az
import pandas as pd

from smtc_handicap.model.data_prep import build_stan_data
from smtc_handicap.model.predict import calculate_handicaps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"
NC_PATH = PROJECT_ROOT / "data" / "model_fits" / "top.nc"
OUTPUT_XLSX = PROJECT_ROOT / "data" / "marsden_cup_2026_analysis.xlsx"

RACE_ID = "MARSDEN_CUP_2026-02-19"

# Optimized post-processing parameters (from Ralph Loop)
PHI_INV_P = -1.30
HANDICAP_POWER = 0.84
HANDICAP_SCALE = 1.175


def query_race_data(db_path: Path) -> pd.DataFrame:
    """Query all time records for the Marsden Cup 2026."""
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            """
            SELECT tr.rider_id, tr.run_number, tr.finish_time, tr.handicap,
                   tr.is_fall, tr.fall_location,
                   rd.display_name
            FROM time_records tr
            JOIN riders rd ON tr.rider_id = rd.rider_id
            WHERE tr.race_id = ?
            ORDER BY tr.rider_id, tr.run_number
            """,
            conn,
            params=(RACE_ID,),
        )
    finally:
        conn.close()
    return df


def group_by_rider(df: pd.DataFrame) -> list[dict]:
    """Group race records by rider, extracting run 1/2 times and fall status."""
    riders = {}
    for _, row in df.iterrows():
        rid = row["rider_id"]
        if rid not in riders:
            riders[rid] = {
                "rider_id": rid,
                "display_name": row["display_name"],
                "committee_handicap": row["handicap"] if pd.notna(row["handicap"]) else None,
                "run_1": None,
                "run_2": None,
                "run_1_fall": False,
                "run_2_fall": False,
                "fall_location": None,
            }
        run = int(row["run_number"])
        if run == 1:
            if row["is_fall"]:
                riders[rid]["run_1_fall"] = True
                riders[rid]["fall_location"] = row["fall_location"]
            else:
                riders[rid]["run_1"] = row["finish_time"] if pd.notna(row["finish_time"]) else None
        elif run == 2:
            if row["is_fall"]:
                riders[rid]["run_2_fall"] = True
                riders[rid]["fall_location"] = row["fall_location"]
            else:
                riders[rid]["run_2"] = row["finish_time"] if pd.notna(row["finish_time"]) else None

    return list(riders.values())


def resolve_model_indices(stan_data: dict) -> tuple[int, int]:
    """Resolve race_type_idx and season_idx for the Marsden Cup 2026."""
    race_type_map = stan_data["meta_race_type_map"]
    season_map = stan_data["meta_season_map"]

    # MARSDEN CUP (after stripping leading "THE ")
    race_type_idx = race_type_map.get("MARSDEN CUP")
    if race_type_idx is None:
        # May have been collapsed into OTHER
        race_type_idx = race_type_map.get("OTHER")
        print("  Warning: MARSDEN CUP collapsed into OTHER")
    print(f"  race_type_idx = {race_type_idx}")

    season_idx = season_map[2026]
    print(f"  season_idx = {season_idx}")

    return race_type_idx, season_idx


def compute_tightness(ranked_df: pd.DataFrame, col: str, top_n: int) -> float | None:
    """Compute tightness (range) of net times for top N riders."""
    top = ranked_df.head(top_n)
    vals = top[col].dropna()
    if len(vals) < 2:
        return None
    return float(vals.max() - vals.min())


def main() -> None:
    print("=" * 60)
    print("MARSDEN CUP 2026 — BAYESIAN HANDICAP ANALYSIS")
    print("=" * 60)

    # 1. Query race data
    print(f"\nQuerying {RACE_ID} ...")
    df = query_race_data(DB_PATH)
    print(f"  {len(df)} records, {df['rider_id'].nunique()} riders")

    riders = group_by_rider(df)

    # Separate completed riders from falls/incomplete
    # Require: both runs completed, no fall, and a non-null committee handicap
    completed = []
    incomplete = []
    for r in riders:
        has_fall = r["run_1_fall"] or r["run_2_fall"]
        both_runs = r["run_1"] is not None and r["run_2"] is not None
        has_handicap = r["committee_handicap"] is not None
        if both_runs and not has_fall and has_handicap:
            r["total_time"] = r["run_1"] + r["run_2"]
            r["committee_net"] = r["total_time"] - 2 * r["committee_handicap"]
            completed.append(r)
        else:
            incomplete.append(r)

    # Sort completed by committee net (ascending = best first)
    completed.sort(key=lambda r: r["committee_net"])
    print(f"  {len(completed)} completed, {len(incomplete)} incomplete/falls")

    # 2. Load Bayesian model
    print(f"\nLoading model from {NC_PATH} ...")
    idata = az.from_netcdf(str(NC_PATH))

    print("Building stan_data ...")
    stan_data = build_stan_data(DB_PATH, "TOP", min_runs=50)
    rider_map = stan_data["meta_rider_map"]
    print(f"  {len(rider_map)} riders in model")

    race_type_idx, season_idx = resolve_model_indices(stan_data)

    # Collect rider_ids for those in the model
    field_rider_ids = [r["rider_id"] for r in completed if r["rider_id"] in rider_map]
    missing_ids = [r["rider_id"] for r in completed if r["rider_id"] not in rider_map]
    print(f"  {len(field_rider_ids)} in model, {len(missing_ids)} not in model")
    if missing_ids:
        print(f"  Missing: {missing_ids}")

    # 3. Calculate Bayesian handicaps
    print("\nCalculating Bayesian handicaps ...")
    bayes_df = calculate_handicaps(
        idata,
        stan_data,
        field_rider_ids,
        race_type_idx=race_type_idx,
        season_idx=season_idx,
        scratch_rider_id="hoare_rl",
        phi_inv_p=PHI_INV_P,
        handicap_power=HANDICAP_POWER,
        handicap_scale=HANDICAP_SCALE,
    )
    # Build lookup: rider_id -> bayesian handicap
    bayes_lookup = dict(zip(bayes_df["rider_id"], bayes_df["handicap_mean"]))
    print(f"  {len(bayes_lookup)} handicaps computed")

    # 4. Build output rows
    rows = []
    rank = 1
    for r in completed:
        bayes_h = bayes_lookup.get(r["rider_id"])
        bayes_net = r["total_time"] - 2 * bayes_h if bayes_h is not None else None
        rows.append(
            {
                "Rank": rank,
                "Rider": r["display_name"],
                "Run 1": r["run_1"],
                "Run 2": r["run_2"],
                "Total Time": round(r["total_time"], 2),
                "Committee Handicap": r["committee_handicap"],
                "Committee Net": round(r["committee_net"], 2),
                "Bayesian Handicap": round(bayes_h, 2) if bayes_h is not None else "N/A",
                "Bayesian Net": round(bayes_net, 2) if bayes_net is not None else "N/A",
            }
        )
        rank += 1

    # Add incomplete/fall riders at bottom
    for r in incomplete:
        run_1_str = f"Fall ({r['fall_location']})" if r["run_1_fall"] else r["run_1"]
        run_2_str = f"Fall ({r['fall_location']})" if r["run_2_fall"] else r["run_2"]
        rows.append(
            {
                "Rank": "",
                "Rider": r["display_name"],
                "Run 1": run_1_str,
                "Run 2": run_2_str,
                "Total Time": "",
                "Committee Handicap": r["committee_handicap"],
                "Committee Net": "",
                "Bayesian Handicap": "",
                "Bayesian Net": "",
            }
        )

    out_df = pd.DataFrame(rows)

    # Compute Bayesian rank (among completed riders with Bayesian data)
    bayes_ranks = []
    for _, row in out_df.iterrows():
        if isinstance(row["Bayesian Net"], (int, float)):
            bayes_ranks.append((row.name, row["Bayesian Net"]))
    bayes_ranks.sort(key=lambda x: x[1])
    rank_map = {idx: rank + 1 for rank, (idx, _) in enumerate(bayes_ranks)}
    out_df["Bayesian Rank"] = out_df.index.map(lambda i: rank_map.get(i, ""))

    # 5. Tightness metrics
    # Build a numeric dataframe for tightness computation
    ranked_numeric = out_df[out_df["Rank"] != ""].copy()
    ranked_numeric["Committee Net Num"] = pd.to_numeric(
        ranked_numeric["Committee Net"], errors="coerce"
    )
    ranked_numeric["Bayesian Net Num"] = pd.to_numeric(
        ranked_numeric["Bayesian Net"], errors="coerce"
    )

    print("\n" + "=" * 60)
    print("TIGHTNESS METRICS")
    print("=" * 60)
    for n in [3, 6, 10]:
        c_tight = compute_tightness(ranked_numeric, "Committee Net Num", n)
        b_tight = compute_tightness(ranked_numeric, "Bayesian Net Num", n)
        c_str = f"{c_tight:.2f}s" if c_tight is not None else "N/A"
        b_str = f"{b_tight:.2f}s" if b_tight is not None else "N/A"
        print(f"  Top {n:>2}: Committee = {c_str:>7s}  |  Bayesian = {b_str:>7s}")

    # 6. Write Excel
    out_df.to_excel(OUTPUT_XLSX, index=False, sheet_name="Marsden Cup 2026")
    print(f"\nExcel saved to {OUTPUT_XLSX}")
    print(f"  {len(rows)} rows ({len(completed)} ranked + {len(incomplete)} falls/incomplete)")

    # 7. Show top 10
    print(f"\nTop 10 by committee ranking:")
    for _, row in out_df.head(10).iterrows():
        bayes_h_str = (
            f"{row['Bayesian Handicap']:>5}" if row["Bayesian Handicap"] != "N/A" else "  N/A"
        )
        bayes_net_str = f"{row['Bayesian Net']:>7}" if row["Bayesian Net"] != "N/A" else "    N/A"
        bayes_rank_str = f"{row['Bayesian Rank']:>3}" if row["Bayesian Rank"] != "" else "  -"
        print(
            f"  {row['Rank']:>2}. {row['Rider']:<25s} "
            f"comm_h={row['Committee Handicap']:>4}  net={row['Committee Net']:>7}  "
            f"bayes_h={bayes_h_str}  bayes_net={bayes_net_str}  "
            f"bayes_rank={bayes_rank_str}"
        )


if __name__ == "__main__":
    main()
