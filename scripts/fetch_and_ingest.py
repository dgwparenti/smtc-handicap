"""Fetch daily-results emails from staff senders, download PDFs, and ingest into DB.

Usage:
    python scripts/fetch_and_ingest.py [--after YYYY/MM/DD] [--dry-run]

By default fetches emails from 2026/02/01 onwards from three known senders.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from smtc_handicap.db import CrestaDB
from smtc_handicap.gmail_extractor import GmailExtractor
from smtc_handicap.pipeline import ingest_single_pdf

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"

SENDERS = [
    "annabel.kettler@cresta-run.com",
    "tilly.macdonald@cresta-run.com",
    "andrew.mills@cresta-run.com",
]


def build_query(after_date: str) -> str:
    """Build Gmail search query for the known staff senders."""
    from_clauses = " OR ".join(f"from:{s}" for s in SENDERS)
    return f"({from_clauses}) after:{after_date}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch timesheet emails and ingest PDFs into DB")
    parser.add_argument(
        "--after",
        default="2026/02/01",
        help="Only process emails after this date (YYYY/MM/DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and extract links but don't download or ingest",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # --- Phase 1: Fetch emails and download PDFs ---
    extractor = GmailExtractor()
    query = build_query(args.after)
    print(f"\nSearching Gmail: {query}\n")

    message_ids = extractor.search_emails(query=query)
    print(f"Found {len(message_ids)} emails\n")

    downloaded_files: list[Path] = []
    skipped = 0
    failed = 0

    for i, msg_id in enumerate(message_ids, 1):
        metadata = extractor.get_email_metadata(msg_id)
        subject = metadata["subject"]
        date = metadata["date"]
        print(f"[{i}/{len(message_ids)}] {date} — {subject}")

        html = extractor.get_email_html(msg_id)
        if not html:
            print("  SKIP: no HTML body")
            skipped += 1
            time.sleep(0.1)
            continue

        link = extractor.extract_pdf_link(html)
        if not link:
            print("  SKIP: no PDF link found")
            skipped += 1
            time.sleep(0.1)
            continue

        if args.dry_run:
            print(f"  [dry-run] Would download: {link}")
            time.sleep(0.1)
            continue

        try:
            pdf_url = extractor.resolve_pdf_url(link)
            result = extractor.download_pdf(pdf_url, force=True)
            if result and result.exists():
                print(f"  Downloaded: {result.name}")
                downloaded_files.append(result)
            else:
                print("  FAIL: download returned None")
                failed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

        time.sleep(0.1)

    print(f"\n--- Download summary ---")
    print(f"  Emails found:  {len(message_ids)}")
    print(f"  Downloaded:    {len(downloaded_files)}")
    print(f"  Skipped:       {skipped}")
    print(f"  Failed:        {failed}")

    if args.dry_run or not downloaded_files:
        return

    # --- Phase 2: Ingest into DB ---
    print(f"\n--- Ingesting into {DB_PATH} ---")

    with CrestaDB(DB_PATH) as db:
        already_ingested = db.get_ingested_pdf_sources()
        counts_before = db.get_counts()

        re_ingested = 0
        newly_ingested = 0

        for pdf_path in downloaded_files:
            pdf_source = pdf_path.name
            if pdf_source in already_ingested:
                deleted = db.delete_by_pdf_source(pdf_source)
                print(f"  Re-ingesting {pdf_source} (deleted {deleted} old records)")
                re_ingested += 1
            else:
                print(f"  New: {pdf_source}")
                newly_ingested += 1

            try:
                stats = ingest_single_pdf(db, pdf_path)
                if stats.warnings:
                    for w in stats.warnings:
                        print(f"    WARN: {w}")
            except Exception as e:
                print(f"    FAIL: {e}")

        counts_after = db.get_counts()

    print(f"\n--- Ingestion summary ---")
    print(f"  Re-ingested:   {re_ingested}")
    print(f"  Newly ingested:{newly_ingested}")
    print(f"  Races:  {counts_before['races']} → {counts_after['races']}")
    print(f"  Records:{counts_before['time_records']} → {counts_after['time_records']}")
    print(f"  Riders: {counts_before['riders']} → {counts_after['riders']}")


if __name__ == "__main__":
    main()
