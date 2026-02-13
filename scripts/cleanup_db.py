#!/usr/bin/env python3
"""Idempotent database cleanup script for the Cresta Run database.

Runs 8 cleanup steps in order. Use --dry-run to preview changes without modifying data.
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from pathlib import Path

from smtc_handicap.validation import (
    ABSOLUTE_MAX_TIME,
    ABSOLUTE_MIN_TIME,
    RACE_POSITION_OVERRIDES,
    TIME_BOUNDS,
    is_team_relay_race,
    normalize_scratch_handicaps,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


def step1_remove_junk_times(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Remove sub-1s junk times (parsing artifacts: speeds/positions read as finish_time)."""
    count = conn.execute(
        "SELECT COUNT(*) FROM time_records WHERE finish_time IS NOT NULL AND finish_time < ?",
        (ABSOLUTE_MIN_TIME,),
    ).fetchone()[0]
    if not dry_run and count > 0:
        conn.execute(
            "DELETE FROM time_records WHERE finish_time IS NOT NULL AND finish_time < ?",
            (ABSOLUTE_MIN_TIME,),
        )
        conn.commit()
    return count


def step2_remove_team_relays(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Remove team relay races and their time records."""
    rows = conn.execute("SELECT race_id, name FROM races").fetchall()
    relay_ids = [race_id for race_id, name in rows if is_team_relay_race(name)]

    # Also catch garbled relay race_ids that might not match the name patterns
    garbled_pattern = re.compile(r"JOH.ANN.ES.BADRU.TT", re.IGNORECASE)
    for race_id, _ in rows:
        if garbled_pattern.search(race_id) and race_id not in relay_ids:
            relay_ids.append(race_id)

    if not relay_ids:
        return 0

    placeholders = ",".join("?" * len(relay_ids))
    records_deleted = conn.execute(
        f"SELECT COUNT(*) FROM time_records WHERE race_id IN ({placeholders})",  # noqa: S608
        relay_ids,
    ).fetchone()[0]

    if not dry_run:
        conn.execute(
            f"DELETE FROM time_records WHERE race_id IN ({placeholders})",  # noqa: S608
            relay_ids,
        )
        conn.execute(
            f"DELETE FROM races WHERE race_id IN ({placeholders})",  # noqa: S608
            relay_ids,
        )
        conn.commit()

    logger.info("Relay races found: %s", relay_ids)
    return len(relay_ids)


def step3_fix_misclassified_positions(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Fix races with wrong start_position.

    Applies explicit overrides, then auto-detects TOP races where all times
    fall within JUNCTION range.
    """
    fixed = 0

    # Apply explicit overrides
    for race_id, correct_pos in RACE_POSITION_OVERRIDES.items():
        row = conn.execute(
            "SELECT start_position FROM races WHERE race_id = ?", (race_id,)
        ).fetchone()
        if row and row[0] != correct_pos:
            if not dry_run:
                conn.execute(
                    "UPDATE races SET start_position = ? WHERE race_id = ?",
                    (correct_pos, race_id),
                )
            logger.info("Override: %s %s -> %s", race_id, row[0], correct_pos)
            fixed += 1

    # Auto-detect: TOP races where ALL finish times are in JUNCTION range
    junc_lower, junc_upper = TIME_BOUNDS["JUNCTION"]
    top_lower, _ = TIME_BOUNDS["TOP"]
    top_races = conn.execute("SELECT race_id FROM races WHERE start_position = 'TOP'").fetchall()

    for (race_id,) in top_races:
        times = conn.execute(
            "SELECT finish_time FROM time_records "
            "WHERE race_id = ? AND finish_time IS NOT NULL AND is_fall = 0",
            (race_id,),
        ).fetchall()
        if not times:
            continue
        all_times = [t[0] for t in times]
        # All times must be in JUNCTION range AND below TOP lower bound
        if all(junc_lower <= t <= junc_upper for t in all_times) and all(
            t < top_lower for t in all_times
        ):
            if not dry_run:
                conn.execute(
                    "UPDATE races SET start_position = 'JUNCTION' WHERE race_id = ?",
                    (race_id,),
                )
            logger.info(
                "Auto-reclassified: %s TOP -> JUNCTION (all %d times in %.0f-%.0fs)",
                race_id,
                len(all_times),
                min(all_times),
                max(all_times),
            )
            fixed += 1

    if fixed and not dry_run:
        conn.commit()
    return fixed


def step4_remove_extreme_times(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Remove time records with finish_time > 100s (relay aggregates in non-relay races)."""
    count = conn.execute(
        "SELECT COUNT(*) FROM time_records WHERE finish_time IS NOT NULL AND finish_time > ?",
        (ABSOLUTE_MAX_TIME,),
    ).fetchone()[0]
    if not dry_run and count > 0:
        conn.execute(
            "DELETE FROM time_records WHERE finish_time IS NOT NULL AND finish_time > ?",
            (ABSOLUTE_MAX_TIME,),
        )
        conn.commit()
    return count


def step5_normalize_handicaps(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Normalize handicaps so best rider becomes scratch (0.0) in each race."""
    # Find handicap races where min handicap > 0
    rows = conn.execute(
        """SELECT r.race_id, MIN(tr.handicap) AS min_h
           FROM races r
           JOIN time_records tr ON r.race_id = tr.race_id
           WHERE r.is_handicap_race = 1
             AND tr.handicap IS NOT NULL
           GROUP BY r.race_id
           HAVING MIN(tr.handicap) > 0"""
    ).fetchall()

    if not rows:
        return 0

    normalized = 0
    for race_id, min_h in rows:
        if not dry_run:
            conn.execute(
                "UPDATE time_records SET handicap = handicap - ? "
                "WHERE race_id = ? AND handicap IS NOT NULL",
                (min_h, race_id),
            )
        logger.info("Normalized handicaps for %s (subtracted %.1fs)", race_id, min_h)
        normalized += 1

    if not dry_run:
        conn.commit()
    return normalized


def step6_populate_scratch_riders(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Set scratch_rider_id for handicap races (rider with handicap=0.0)."""
    rows = conn.execute(
        """SELECT r.race_id
           FROM races r
           WHERE r.is_handicap_race = 1
             AND r.scratch_rider_id IS NULL"""
    ).fetchall()

    populated = 0
    for (race_id,) in rows:
        # Find rider(s) with handicap = 0.0; if multiple, pick fastest finish_time
        scratch = conn.execute(
            """SELECT rider_id FROM time_records
               WHERE race_id = ? AND handicap = 0.0
               ORDER BY finish_time ASC
               LIMIT 1""",
            (race_id,),
        ).fetchone()
        if scratch:
            if not dry_run:
                conn.execute(
                    "UPDATE races SET scratch_rider_id = ? WHERE race_id = ?",
                    (scratch[0], race_id),
                )
            populated += 1

    if populated and not dry_run:
        conn.commit()
    return populated


def step7_remove_orphan_races(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Remove races with zero time records."""
    count = conn.execute(
        """SELECT COUNT(*) FROM races r
           WHERE NOT EXISTS (
               SELECT 1 FROM time_records tr WHERE tr.race_id = r.race_id
           )"""
    ).fetchone()[0]
    if not dry_run and count > 0:
        conn.execute(
            """DELETE FROM races
               WHERE NOT EXISTS (
                   SELECT 1 FROM time_records tr WHERE tr.race_id = races.race_id
               )"""
        )
        conn.commit()
    return count


def step8_remove_orphan_riders(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """Remove riders with zero time records (e.g. team club names)."""
    count = conn.execute(
        """SELECT COUNT(*) FROM riders rd
           WHERE NOT EXISTS (
               SELECT 1 FROM time_records tr WHERE tr.rider_id = rd.rider_id
           )"""
    ).fetchone()[0]
    if not dry_run and count > 0:
        conn.execute(
            """DELETE FROM riders
               WHERE NOT EXISTS (
                   SELECT 1 FROM time_records tr WHERE tr.rider_id = riders.rider_id
               )"""
        )
        conn.commit()
    return count


def get_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Get row counts for all tables."""
    counts = {}
    for table in ("riders", "races", "time_records"):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    return counts


def run_cleanup(db_path: Path, *, dry_run: bool = False) -> None:
    """Run all cleanup steps in order."""
    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"=== Database Cleanup ({mode}) ===")
    print(f"Database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")

    # Ensure scratch_rider_id column exists
    cols = {row[1] for row in conn.execute("PRAGMA table_info(races)").fetchall()}
    if "scratch_rider_id" not in cols:
        conn.execute("ALTER TABLE races ADD COLUMN scratch_rider_id TEXT DEFAULT NULL")
        conn.commit()

    before = get_counts(conn)
    print(f"\nBefore: {before}")

    steps = [
        ("1. Remove sub-1s junk times", step1_remove_junk_times),
        ("2. Remove team relay races", step2_remove_team_relays),
        ("3. Fix misclassified start positions", step3_fix_misclassified_positions),
        ("4. Remove >100s extreme times", step4_remove_extreme_times),
        ("5. Normalize handicaps", step5_normalize_handicaps),
        ("6. Populate scratch_rider_id", step6_populate_scratch_riders),
        ("7. Remove orphan races", step7_remove_orphan_races),
        ("8. Remove orphan riders", step8_remove_orphan_riders),
    ]

    for label, func in steps:
        count = func(conn, dry_run=dry_run)
        action = "would affect" if dry_run else "affected"
        print(f"  {label}: {action} {count}")

    after = get_counts(conn)
    print(f"\nAfter:  {after}")

    for table in ("riders", "races", "time_records"):
        delta = after[table] - before[table]
        if delta != 0:
            print(f"  {table}: {delta:+d}")

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up Cresta Run database")
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "cresta.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying the database",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.db.exists():
        print(f"Error: database not found at {args.db}")
        raise SystemExit(1)

    run_cleanup(args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
