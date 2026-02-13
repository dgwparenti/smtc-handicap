"""Pipeline orchestrator: parse PDFs/JSONs and store in SQLite."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from smtc_handicap.db import CrestaDB
from smtc_handicap.json_parser import parse_json
from smtc_handicap.pdf_parser import parse_pdf
from smtc_handicap.validation import is_team_relay_race, is_valid_finish_time

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    pdfs_processed: int = 0
    pdfs_failed: int = 0
    jsons_processed: int = 0
    jsons_failed: int = 0
    races_inserted: int = 0
    riders_upserted: int = 0
    time_records_inserted: int = 0
    warnings: list[str] = field(default_factory=list)


def _accumulate_stats(total: IngestStats, part: IngestStats) -> None:
    """Merge partial stats into the running total."""
    total.pdfs_processed += part.pdfs_processed
    total.pdfs_failed += part.pdfs_failed
    total.jsons_processed += part.jsons_processed
    total.jsons_failed += part.jsons_failed
    total.races_inserted += part.races_inserted
    total.riders_upserted += part.riders_upserted
    total.time_records_inserted += part.time_records_inserted
    total.warnings.extend(part.warnings)


def _store_parsed(db: CrestaDB, parsed: object, stats: IngestStats) -> None:
    """Store parsed data (from either PDF or JSON) into the DB.

    Applies validation guards:
    - Skips team relay races entirely
    - Rejects time records with invalid finish times (sub-1s or >100s)
    """
    for rider in parsed.riders:
        db.upsert_rider(rider)
        stats.riders_upserted += 1

    # Build race_id → start_position lookup and filter out relay races
    race_positions: dict[str, str] = {}
    skipped_race_ids: set[str] = set()
    for race in parsed.races:
        if is_team_relay_race(race.name):
            stats.warnings.append(f"Skipped relay race: {race.name} ({race.race_id})")
            skipped_race_ids.add(race.race_id)
            continue
        db.insert_race(race)
        stats.races_inserted += 1
        race_positions[race.race_id] = race.start_position

    for record in parsed.time_records:
        if record.race_id in skipped_race_ids:
            continue
        if not is_valid_finish_time(record.finish_time):
            stats.warnings.append(
                f"Rejected invalid time {record.finish_time}s: {record.record_id}"
            )
            continue
        db.insert_time_record(record)
        stats.time_records_inserted += 1


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
    _store_parsed(db, parsed, stats)
    return stats


def ingest_single_json(db: CrestaDB, filepath: Path) -> IngestStats:
    """Parse one JSON and store in DB."""
    stats = IngestStats()

    parsed = parse_json(filepath)
    stats.warnings.extend(parsed.warnings)

    if not parsed.races and not parsed.riders and not parsed.time_records:
        stats.jsons_failed += 1
        stats.warnings.append(f"No data extracted from {filepath.name}")
        return stats

    stats.jsons_processed += 1
    _store_parsed(db, parsed, stats)
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
                _accumulate_stats(total_stats, stats)
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
                _accumulate_stats(total_stats, stats)
            except Exception as e:
                logger.error("Failed to process %s: %s", pdf_file.name, e)
                total_stats.pdfs_failed += 1
                total_stats.warnings.append(f"FATAL: {pdf_file.name}: {e}")

    return total_stats


def ingest_all(
    json_dir: Path | None,
    pdf_dir: Path | None,
    db_path: Path,
) -> IngestStats:
    """Process all JSONs then all PDFs.

    JSONs are processed first so their richer data (splits, speeds, start times)
    wins via INSERT OR IGNORE. PDFs then fill in the ~111 files without JSON.
    """
    total_stats = IngestStats()

    with CrestaDB(db_path) as db:
        # Phase 1: JSONs
        if json_dir is not None:
            json_files = sorted(json_dir.glob("*.json"))
            if json_files:
                logger.info("Found %d JSON files to process", len(json_files))
                for i, jf in enumerate(json_files, 1):
                    logger.info("[JSON %d/%d] Processing %s", i, len(json_files), jf.name)
                    try:
                        stats = ingest_single_json(db, jf)
                        _accumulate_stats(total_stats, stats)
                    except Exception as e:
                        logger.error("Failed to process %s: %s", jf.name, e)
                        total_stats.jsons_failed += 1
                        total_stats.warnings.append(f"FATAL: {jf.name}: {e}")
            else:
                logger.warning("No JSON files found in %s", json_dir)

        # Phase 2: PDFs
        if pdf_dir is not None:
            pdf_files = sorted(pdf_dir.glob("*.pdf"))
            if pdf_files:
                logger.info("Found %d PDF files to process", len(pdf_files))
                for i, pf in enumerate(pdf_files, 1):
                    logger.info("[PDF %d/%d] Processing %s", i, len(pdf_files), pf.name)
                    try:
                        stats = ingest_single_pdf(db, pf)
                        _accumulate_stats(total_stats, stats)
                    except Exception as e:
                        logger.error("Failed to process %s: %s", pf.name, e)
                        total_stats.pdfs_failed += 1
                        total_stats.warnings.append(f"FATAL: {pf.name}: {e}")
            else:
                logger.warning("No PDF files found in %s", pdf_dir)

    return total_stats
