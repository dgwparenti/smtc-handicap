#!/usr/bin/env python3
"""Quick DB inspection tool for the Cresta Run database."""

import argparse
from pathlib import Path

from smtc_handicap.db import CrestaDB

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the Cresta Run SQLite database")
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "cresta.db",
        help="Path to SQLite database",
    )
    parser.add_argument("--counts", action="store_true", default=True, help="Show row counts")
    parser.add_argument("--riders", action="store_true", help="List all riders")
    parser.add_argument("--races", action="store_true", help="List all races")
    parser.add_argument("--records", action="store_true", help="List time records")
    parser.add_argument("--rider", type=str, help="Filter by rider ID (with --records)")
    args = parser.parse_args()

    with CrestaDB(args.db) as db:
        if args.counts:
            counts = db.get_counts()
            print("Row counts:")
            for table, count in counts.items():
                print(f"  {table}: {count}")

        if args.riders:
            print("\nRiders:")
            for rider in db.get_all_riders():
                flags = []
                if rider.is_sl:
                    flags.append("SL")
                if rider.is_am:
                    flags.append("AM")
                flag_str = f" [{','.join(flags)}]" if flags else ""
                print(
                    f"  {rider.rider_id:30s} {rider.display_name:30s} "
                    f"{rider.nationality:4s}{flag_str}"
                )

        if args.races:
            print("\nRaces:")
            rows = db.conn.execute(
                "SELECT race_id, name, date, start_position, is_handicap_race, "
                "is_practice, day_number FROM races ORDER BY date"
            ).fetchall()
            for r in rows:
                rtype = "Practice" if r[5] else ("Handicap" if r[4] else "Scratch")
                day = f" Day {r[6]}" if r[6] else ""
                print(f"  {r[2]} {r[3]:8s} {rtype:10s} {r[1]}{day}")

        if args.records:
            rider_id = args.rider
            if rider_id:
                records = db.get_time_records_for_rider(rider_id)
                print(f"\nTime records for {rider_id}: ({len(records)} records)")
            else:
                records = db.conn.execute(
                    "SELECT * FROM time_records ORDER BY race_id, rider_id, run_number"
                ).fetchall()
                records = [CrestaDB._row_to_time_record(r) for r in records]
                print(f"\nAll time records: ({len(records)} records)")

            for rec in records[:50]:
                fall_str = f" FALL({rec.fall_location})" if rec.is_fall else ""
                hcap_str = f" H={rec.handicap}" if rec.handicap is not None else ""
                time_str = f"{rec.finish_time:.2f}" if rec.finish_time else "DNF"
                print(
                    f"  {rec.race_id:40s} run={rec.run_number} "
                    f"{time_str:>8s}{hcap_str}{fall_str}"
                )


if __name__ == "__main__":
    main()
