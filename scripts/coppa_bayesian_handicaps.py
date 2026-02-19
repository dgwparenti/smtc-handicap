#!/usr/bin/env python3
"""Generate Coppa d'Italia 2026 CSV with committee and Bayesian handicaps.

Queries the DB for all time records in the 2026 Coppa d'Italia race,
loads the Bayesian TOP model, and outputs a CSV with both handicap systems.
Rows are ordered to match the PDF ranking.
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
OUTPUT_CSV = PROJECT_ROOT / "data" / "coppa_2026_handicaps.csv"

RACE_ID = "COPPA_D_ITALIA_2026-02-12"
SEASON_YEAR = 2026  # 2025/2026 season


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
    season_num = idata.constant_data["season_num"].values

    alpha_mean = idata.posterior["alpha"].mean(dim=["chain", "draw"]).values
    beta_trend_mean = idata.posterior["beta_trend"].mean(dim=["chain", "draw"]).values

    J = len(alpha_mean)
    S = len(season_num)
    print(f"  {J} riders, {S} seasons")

    return {
        "rider_map": rider_map,
        "season_num": season_num,
        "alpha_mean": alpha_mean,
        "beta_trend_mean": beta_trend_mean,
    }


def get_season_num_val(model: dict, db_path: Path) -> float:
    """Get the season_num value for the 2025/2026 season."""
    season_num = model["season_num"]

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

    val = lookup[SEASON_YEAR]
    print(f"  Season {SEASON_YEAR} -> season_num = {val:.4f}")
    return val


def query_coppa_data(db_path: Path) -> pd.DataFrame:
    """Query all time records for the Coppa d'Italia 2026."""
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            """
            SELECT tr.rider_id, tr.run_number, tr.finish_time, tr.handicap,
                   tr.is_fall, tr.fall_location, tr.is_dnf,
                   rd.display_name, rd.nationality
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

    print(f"\n{RACE_ID}: {len(df)} records, {df['rider_id'].nunique()} riders")
    return df


def model_rider_id(rider_id: str) -> str:
    """Map DB rider_id to model rider_id (strip asterisk from guest riders)."""
    return rider_id.replace("*", "")


def compute_bayesian_ability(model: dict, rider_id: str, season_num_val: float) -> float | None:
    """Compute estimated ability for a rider at the given season. Returns None if not in model."""
    mapped_id = model_rider_id(rider_id)
    rider_map = model["rider_map"]
    if mapped_id not in rider_map:
        return None
    j = rider_map[mapped_id] - 1  # 1-indexed in map
    return float(model["alpha_mean"][j] + model["beta_trend_mean"][j] * season_num_val)


def build_rows(df: pd.DataFrame, model: dict, season_num_val: float) -> list[dict]:
    """Build CSV rows from race data and model."""
    # Find Bayesian scratch: use the faster of the two committee scratch riders
    scratch_ids = ["nani_e", "wrottesley"]
    scratch_abilities = {}
    for sid in scratch_ids:
        ability = compute_bayesian_ability(model, sid, season_num_val)
        if ability is not None:
            scratch_abilities[sid] = ability
    # Lower ability = faster rider; use the faster one as scratch reference
    bayesian_scratch_id = min(scratch_abilities, key=scratch_abilities.get)
    bayesian_scratch_ability = scratch_abilities[bayesian_scratch_id]
    print(f"\nBayesian scratch: {bayesian_scratch_id} (ability={bayesian_scratch_ability:.2f}s)")
    for sid, ab in scratch_abilities.items():
        print(f"  {sid}: {ab:.2f}s")

    # Group by rider
    riders = {}
    for _, row in df.iterrows():
        rid = row["rider_id"]
        if rid not in riders:
            riders[rid] = {
                "rider_id": rid,
                "display_name": row["display_name"],
                "nationality": row["nationality"],
                "handicap": row["handicap"] if pd.notna(row["handicap"]) else None,
                "runs": [],
            }
        riders[rid]["runs"].append(row)

    # Categorize riders
    ranked = []  # 2 completed runs, has handicap
    unranked_2run = []  # 2 completed runs, no handicap (boinville)
    single_run = []  # 1 run, no fall
    falls = []  # has a fall

    for rid, rdata in riders.items():
        runs = rdata["runs"]
        fall_runs = [r for r in runs if r["is_fall"]]
        completed_runs = [
            r for r in runs if not r["is_fall"] and not r["is_dnf"] and pd.notna(r["finish_time"])
        ]

        if len(fall_runs) > 0:
            falls.append(rdata)
        elif len(completed_runs) == 2 and rdata["handicap"] is not None:
            ranked.append(rdata)
        elif len(completed_runs) == 2 and rdata["handicap"] is None:
            unranked_2run.append(rdata)
        else:
            single_run.append(rdata)

    # Sort ranked by committee net time
    for rdata in ranked:
        completed = [r for r in rdata["runs"] if pd.notna(r["finish_time"])]
        total = sum(r["finish_time"] for r in completed)
        rdata["total_time"] = total
        rdata["committee_net"] = total - 2 * rdata["handicap"]

    ranked.sort(key=lambda r: r["committee_net"])

    # Sort unranked groups by display name
    unranked_2run.sort(key=lambda r: r["display_name"])
    single_run.sort(key=lambda r: r["display_name"])
    falls.sort(key=lambda r: r["display_name"])

    # Build CSV rows
    csv_rows = []
    rank = 1

    def format_run(run_data) -> str:
        if run_data["is_fall"]:
            loc = run_data["fall_location"] if pd.notna(run_data["fall_location"]) else "?"
            return f"Fall({loc})"
        if pd.notna(run_data["finish_time"]):
            return f"{run_data['finish_time']:.2f}"
        return ""

    def make_row(rdata, rank_val=None, completed_race=True):
        runs = sorted(rdata["runs"], key=lambda r: r["run_number"])
        run_1 = format_run(runs[0]) if len(runs) >= 1 else ""
        run_2 = format_run(runs[1]) if len(runs) >= 2 else ""

        committee_h = rdata["handicap"]
        committee_net = rdata.get("committee_net") if completed_race else None

        # Bayesian handicap
        ability = compute_bayesian_ability(model, rdata["rider_id"], season_num_val)
        if ability is not None:
            bayes_h = ability - bayesian_scratch_ability
        else:
            bayes_h = None

        # Bayesian net: only for riders who completed the full race (2 runs)
        bayes_net = None
        if completed_race and bayes_h is not None and "total_time" in rdata:
            bayes_net = rdata["total_time"] - 2 * bayes_h

        return {
            "rank": rank_val if rank_val is not None else "",
            "rider_name": rdata["display_name"],
            "nationality": rdata["nationality"],
            "committee_handicap": f"{committee_h:.1f}" if committee_h is not None else "",
            "run_1": run_1,
            "run_2": run_2,
            "committee_net": f"{committee_net:.2f}" if committee_net is not None else "",
            "bayesian_handicap": f"{bayes_h:.2f}" if bayes_h is not None else "",
            "bayesian_net": f"{bayes_net:.2f}" if bayes_net is not None else "",
        }

    # 1. Ranked finishers
    for rdata in ranked:
        csv_rows.append(make_row(rdata, rank_val=rank))
        rank += 1

    # 2. Unranked 2-run finishers (boinville — guest, no handicap)
    for rdata in unranked_2run:
        # Compute total_time for Bayesian net
        completed = [r for r in rdata["runs"] if pd.notna(r["finish_time"])]
        rdata["total_time"] = sum(r["finish_time"] for r in completed)
        csv_rows.append(make_row(rdata))

    # 3. Single-run riders (DNF on 2nd run)
    for rdata in single_run:
        csv_rows.append(make_row(rdata, completed_race=False))

    # 4. Falls
    for rdata in falls:
        csv_rows.append(make_row(rdata, completed_race=False))

    return csv_rows


def main() -> None:
    print("=" * 60)
    print("COPPA D'ITALIA 2026 — BAYESIAN HANDICAP CSV")
    print("=" * 60)

    model = load_bayesian_model(NC_PATH)
    season_num_val = get_season_num_val(model, DB_PATH)
    df = query_coppa_data(DB_PATH)

    rows = build_rows(df, model, season_num_val)

    # Write CSV
    out_df = pd.DataFrame(rows)
    out_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nCSV saved to {OUTPUT_CSV}")
    print(f"  {len(rows)} rows")

    # Summary
    ranked_count = sum(1 for r in rows if r["rank"] != "")
    bayes_count = sum(1 for r in rows if r["bayesian_handicap"] != "")
    print(f"  {ranked_count} ranked, {len(rows) - ranked_count} unranked")
    print(f"  {bayes_count} with Bayesian handicap, {len(rows) - bayes_count} without")

    # Show top 5
    print("\nTop 5:")
    for r in rows[:5]:
        print(
            f"  {r['rank']:>2}. {r['rider_name']:<25s} "
            f"comm_h={r['committee_handicap']:>4s} net={r['committee_net']:>7s}  "
            f"bayes_h={r['bayesian_handicap']:>6s} bayes_net={r['bayesian_net']:>7s}"
        )


if __name__ == "__main__":
    main()
