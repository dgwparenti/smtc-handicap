#!/usr/bin/env python3
"""CLI script to ingest Cresta Run results (JSON + PDF) into SQLite."""

import argparse
import logging
from pathlib import Path

from smtc_handicap.pipeline import ingest_all

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Cresta Run results into SQLite")
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw_pdfs",
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "json_results",
        help="Directory containing JSON files",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "cresta.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Only process JSON files (skip PDFs)",
    )
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="Only process PDF files (skip JSONs)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.pdf_only and args.json_only:
        parser.error("Cannot use --pdf-only and --json-only together")

    json_dir = args.json_dir if not args.pdf_only else None
    pdf_dir = args.pdf_dir if not args.json_only else None
    stats = ingest_all(json_dir, pdf_dir, args.db)

    print("\n" + "=" * 50)
    print("Ingestion Summary")
    print("=" * 50)
    if stats.jsons_processed or stats.jsons_failed:
        print(f"  JSONs processed:     {stats.jsons_processed}")
        print(f"  JSONs failed:        {stats.jsons_failed}")
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
