#!/usr/bin/env python3
"""CLI script to ingest Cresta Run PDF results into SQLite."""

import argparse
import logging
from pathlib import Path

from smtc_handicap.pipeline import ingest_all_pdfs

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Cresta Run PDF results into SQLite")
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw_pdfs",
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "cresta.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    stats = ingest_all_pdfs(args.pdf_dir, args.db)

    print("\n" + "=" * 50)
    print("Ingestion Summary")
    print("=" * 50)
    print(f"  PDFs processed:      {stats.pdfs_processed}")
    print(f"  PDFs failed:         {stats.pdfs_failed}")
    print(f"  Races inserted:      {stats.races_inserted}")
    print(f"  Riders upserted:     {stats.riders_upserted}")
    print(f"  Time records:        {stats.time_records_inserted}")
    print(f"  Warnings:            {len(stats.warnings)}")

    if stats.warnings:
        print("\nWarnings:")
        for w in stats.warnings[:20]:
            print(f"  - {w}")
        if len(stats.warnings) > 20:
            print(f"  ... and {len(stats.warnings) - 20} more")


if __name__ == "__main__":
    main()
