"""Pipeline orchestrator: parse PDFs and store in SQLite."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from smtc_handicap.db import CrestaDB
from smtc_handicap.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    pdfs_processed: int = 0
    pdfs_failed: int = 0
    races_inserted: int = 0
    riders_upserted: int = 0
    time_records_inserted: int = 0
    warnings: list[str] = field(default_factory=list)


def ingest_single_pdf(db: CrestaDB, filepath: Path) -> IngestStats:
    """Parse one PDF and store in DB."""
    stats = IngestStats()

    parsed = parse_pdf(filepath)
    stats.warnings.extend(parsed.warnings)

    if not parsed.races and not parsed.riders and not parsed.time_records:
        stats.pdfs_failed += 1
        stats.warnings.append(f"No data extracted from {filepath.name}")
        return stats

    stats.pdfs_processed += 1

    # Insert in FK order: riders first, then races, then time_records
    for rider in parsed.riders:
        db.upsert_rider(rider)
        stats.riders_upserted += 1

    for race in parsed.races:
        db.insert_race(race)
        stats.races_inserted += 1

    for record in parsed.time_records:
        db.insert_time_record(record)
        stats.time_records_inserted += 1

    return stats


def ingest_all_pdfs(pdf_dir: Path, db_path: Path) -> IngestStats:
    """Process all PDFs in a directory, sorted by name (date order)."""
    total_stats = IngestStats()

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDF files found in %s", pdf_dir)
        return total_stats

    logger.info("Found %d PDF files to process", len(pdf_files))

    with CrestaDB(db_path) as db:
        for i, pdf_file in enumerate(pdf_files, 1):
            logger.info("[%d/%d] Processing %s", i, len(pdf_files), pdf_file.name)
            try:
                stats = ingest_single_pdf(db, pdf_file)
                total_stats.pdfs_processed += stats.pdfs_processed
                total_stats.pdfs_failed += stats.pdfs_failed
                total_stats.races_inserted += stats.races_inserted
                total_stats.riders_upserted += stats.riders_upserted
                total_stats.time_records_inserted += stats.time_records_inserted
                total_stats.warnings.extend(stats.warnings)
            except Exception as e:
                logger.error("Failed to process %s: %s", pdf_file.name, e)
                total_stats.pdfs_failed += 1
                total_stats.warnings.append(f"FATAL: {pdf_file.name}: {e}")

    return total_stats


def ingest_new_pdfs(pdf_dir: Path, db_path: Path) -> IngestStats:
    """Process only PDFs not already ingested."""
    total_stats = IngestStats()

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        return total_stats

    with CrestaDB(db_path) as db:
        already_ingested = db.get_ingested_pdf_sources()
        new_files = [f for f in pdf_files if f.name not in already_ingested]

        logger.info(
            "%d PDFs on disk, %d already ingested, %d new",
            len(pdf_files),
            len(already_ingested),
            len(new_files),
        )

        for i, pdf_file in enumerate(new_files, 1):
            logger.info("[%d/%d] Processing %s", i, len(new_files), pdf_file.name)
            try:
                stats = ingest_single_pdf(db, pdf_file)
                total_stats.pdfs_processed += stats.pdfs_processed
                total_stats.pdfs_failed += stats.pdfs_failed
                total_stats.races_inserted += stats.races_inserted
                total_stats.riders_upserted += stats.riders_upserted
                total_stats.time_records_inserted += stats.time_records_inserted
                total_stats.warnings.extend(stats.warnings)
            except Exception as e:
                logger.error("Failed to process %s: %s", pdf_file.name, e)
                total_stats.pdfs_failed += 1
                total_stats.warnings.append(f"FATAL: {pdf_file.name}: {e}")

    return total_stats
