"""Prepare SQLite data for the Stan hierarchical handicap model."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


def build_stan_data(db_path: str | Path, start_position: str, *, min_runs: int = 3) -> dict:
    """Query the DB and build the dict expected by the Stan model.

    Parameters
    ----------
    db_path : path to the SQLite database
    start_position : "TOP" or "JUNCTION"
    min_runs : minimum number of valid runs for a rider to be included (default 3)

    Returns
    -------
    dict with keys matching the Stan ``data {}`` block, plus metadata keys
    prefixed with ``meta_`` (rider/race-type index maps, the raw dataframe).
    """
    if start_position not in ("TOP", "JUNCTION"):
        raise ValueError(f"start_position must be TOP or JUNCTION, got {start_position!r}")

    conn = sqlite3.connect(str(db_path))
    try:
        df = _query_valid_times(conn, start_position)
    finally:
        conn.close()

    if df.empty:
        raise ValueError(f"No valid time records found for {start_position}")

    df = _filter_outliers(df, start_position)
    df = _filter_min_runs(df, min_runs)

    rider_map = _build_index_map(df["rider_id"].unique())
    race_type_map = _build_race_type_map(df)

    df["rider_idx"] = df["rider_id"].map(rider_map)
    df["race_type_idx"] = df["race_type_label"].map(race_type_map)
    df["season_idx"] = 1  # single season for now

    df = _compute_run_seq(df)

    num_riders = len(rider_map)
    is_sl = _build_is_sl_array(df, rider_map, num_riders)

    prior_mu = 57.0 if start_position == "TOP" else 48.0
    num_seasons = 1  # single season for now
    # With S=1, delta and alpha are confounded — use a tight prior to
    # effectively disable the season component until more seasons exist.
    prior_sigma_season_sd = 0.01 if num_seasons == 1 else 2.0

    stan_data = {
        "N": len(df),
        "J": num_riders,
        "S": num_seasons,
        "R": len(race_type_map),
        "rider": df["rider_idx"].values.astype(int),
        "season": df["season_idx"].values.astype(int),
        "race_type": df["race_type_idx"].values.astype(int),
        "y": df["finish_time"].values.astype(float),
        "is_sl": is_sl,
        "run_seq": df["run_seq"].values.astype(float),
        "prior_mu_pop": prior_mu,
        "prior_sigma_mu_pop": 10.0,
        "prior_sigma_season_sd": prior_sigma_season_sd,
        # Metadata (not passed to Stan, used by Python callers)
        "meta_rider_map": rider_map,
        "meta_race_type_map": race_type_map,
        "meta_df": df,
    }
    return stan_data


def _query_valid_times(conn: sqlite3.Connection, start_position: str) -> pd.DataFrame:
    """Fetch non-fall, non-DNF records with a valid finish_time."""
    query = """
        SELECT
            tr.record_id,
            tr.race_id,
            tr.rider_id,
            tr.finish_time,
            tr.handicap,
            tr.is_fall,
            tr.is_dnf,
            r.name   AS race_name,
            r.date   AS race_date,
            r.is_practice,
            rd.is_sl
        FROM time_records tr
        JOIN races r  ON tr.race_id  = r.race_id
        JOIN riders rd ON tr.rider_id = rd.rider_id
        WHERE r.start_position = ?
          AND tr.is_fall = 0
          AND tr.is_dnf  = 0
          AND tr.finish_time IS NOT NULL
        ORDER BY r.date, tr.rider_id, tr.record_id
    """
    df = pd.read_sql_query(query, conn, params=(start_position,))
    # Derive race-type label: PRACTICE or the named race
    df["race_type_label"] = df.apply(
        lambda row: "PRACTICE" if row["is_practice"] else row["race_name"], axis=1
    )
    return df


def _filter_min_runs(df: pd.DataFrame, min_runs: int) -> pd.DataFrame:
    """Keep only riders with at least ``min_runs`` valid observations."""
    if min_runs <= 1:
        return df
    counts = df.groupby("rider_id").size()
    keep = counts[counts >= min_runs].index
    return df[df["rider_id"].isin(keep)].reset_index(drop=True)


def _filter_outliers(df: pd.DataFrame, start_position: str) -> pd.DataFrame:
    """Remove times > 3x the median for this start position."""
    median_time = df["finish_time"].median()
    cutoff = 3.0 * median_time
    return df[df["finish_time"] <= cutoff].reset_index(drop=True)


def _build_index_map(unique_ids: np.ndarray) -> dict[str, int]:
    """Map unique string IDs to contiguous 1-based integers."""
    sorted_ids = sorted(unique_ids)
    return {uid: i + 1 for i, uid in enumerate(sorted_ids)}


def _build_race_type_map(df: pd.DataFrame) -> dict[str, int]:
    """Map race-type labels to 1-based integers, with PRACTICE = 1."""
    labels = sorted(df["race_type_label"].unique())
    # Ensure PRACTICE is index 1
    if "PRACTICE" in labels:
        labels.remove("PRACTICE")
        labels = ["PRACTICE"] + labels
    return {label: i + 1 for i, label in enumerate(labels)}


def _compute_run_seq(df: pd.DataFrame) -> pd.DataFrame:
    """Add a per-rider sequential run number, ordered by date."""
    df = df.sort_values(["rider_id", "race_date", "record_id"]).copy()
    df["run_seq"] = df.groupby("rider_id").cumcount() + 1
    # Restore original order
    df = df.sort_values(["race_date", "rider_id", "record_id"]).reset_index(drop=True)
    return df


def _build_is_sl_array(df: pd.DataFrame, rider_map: dict[str, int], num_riders: int) -> list[int]:
    """Build a J-length array of SL flags indexed by rider_idx."""
    is_sl = [0] * num_riders
    sl_by_rider = df.groupby("rider_id")["is_sl"].max()
    for rider_id, idx in rider_map.items():
        if rider_id in sl_by_rider.index:
            is_sl[idx - 1] = int(sl_by_rider[rider_id])
    return is_sl
