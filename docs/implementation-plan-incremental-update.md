# Plan: Incremental Data Ingestion & Model Update Pipeline

## Context

The SMTC Handicap system currently has a working Gmail extraction pipeline (Phase 1) that downloads race result PDFs. Phases 2-4 (PDF parsing, SQLite DB, Bayesian model) are designed but not yet implemented. The user needs an incremental update workflow so that next season, they can:
1. Automatically detect where they left off (last race date in the DB)
2. Download only new daily results emails
3. Append new data to the DB without overwriting
4. Trigger a Bayesian model refit after ingestion

This plan adds an **orchestrator layer** on top of the already-planned components, plus minor additions to `db.py`, `pipeline.py`, and `model/fit.py`.

---

## Deliverables

1. Create `docs/implementation-plan-incremental-update.md` containing this plan for the repo
2. Update `docs/implementation-plan-pdf-parsing-db.md` to cross-reference the incremental workflow (add a section noting `get_max_race_date()` and `get_ingested_pdf_sources()` in the `CrestaDB` class, and `ingest_new_pdfs()` in the pipeline)
3. Update `docs/bayesian-model-plan.md` to add a section on incremental model updates via `refit_from_db()` and how the orchestrator triggers refits

---

## Design Decision: Last Extracted Date

**Use `SELECT MAX(date) FROM races` from the SQLite DB.**

- The DB is the source of truth for race data; no separate state file needed
- Returns `NULL` on first run (no DB or empty DB) -> falls back to default `2020/01/01`
- A 2-day buffer (`last_date - 2 days`) accounts for email-vs-race-date lag
- All existing idempotency layers (email ID dedup, file existence check, `INSERT OR IGNORE`) prevent duplicate work

---

## Files to Create/Modify

### New Files

| File | Purpose | Est. Lines |
|------|---------|-----------|
| `src/smtc_handicap/orchestrator.py` | Incremental workflow: detect last date, extract, ingest, refit | ~150 |
| `scripts/run_update.py` | CLI entry point for incremental/full updates | ~80 |
| `tests/test_orchestrator.py` | Unit tests for orchestrator logic | ~120 |
| `docs/implementation-plan-incremental-update.md` | This plan, stored in the repo | — |

### Modifications to Planned (Not Yet Built) Files

| File | Change |
|------|--------|
| `src/smtc_handicap/db.py` | Add `get_max_race_date() -> date \| None` and `get_ingested_pdf_sources() -> set[str]` to `CrestaDB` |
| `src/smtc_handicap/pipeline.py` | Add `ingest_new_pdfs(pdf_dir, db_path)` that skips already-ingested PDFs |
| `src/smtc_handicap/model/fit.py` | Add `refit_from_db(db_path)` wrapper that builds stan data + fits TOP and JUNCTION models |
| `tests/conftest.py` | Add `in_memory_db` and `populated_db` fixtures |

### No Changes Needed

| File | Reason |
|------|--------|
| `src/smtc_handicap/gmail_extractor.py` | Already accepts `after_date` param; orchestrator computes and passes it |

---

## `orchestrator.py` — Key Functions

```python
def get_last_race_date(db_path: Path) -> datetime.date | None:
    """Query SELECT MAX(date) FROM races. Returns None if DB missing/empty."""

def compute_extraction_start_date(last_race_date: date | None) -> str:
    """Returns (last_date - 2 days) as 'YYYY/MM/DD', or '2020/01/01' if None."""

def run_incremental(
    db_path: Path,
    pdf_dir: Path,
    refit_model: bool = True,
    dry_run: bool = False,
    extract: bool = True,
    ingest: bool = True,
) -> dict:
    """
    1. get_last_race_date(db_path) -> last_date
    2. compute_extraction_start_date(last_date) -> after_date
    3. GmailExtractor().run(after_date=after_date) -> download new PDFs
    4. ingest_new_pdfs(pdf_dir, db_path) -> append to DB (INSERT OR IGNORE)
    5. If new data ingested and refit_model: refit_from_db(db_path)
    6. Return summary dict
    """
```

## End-to-End Data Flow

```
scripts/run_update.py
  |
  v
orchestrator.get_last_race_date(db_path)
  -> SELECT MAX(date) FROM races -> e.g., "2026-02-06" or None
  |
  v
orchestrator.compute_extraction_start_date("2026-02-06")
  -> "2026/02/04" (2-day buffer)
  |
  v
GmailExtractor.run(after_date="2026/02/04")
  -> Searches Gmail, downloads new PDFs to data/raw_pdfs/
  -> Idempotent: skips already-processed email IDs + existing files
  |
  v
pipeline.ingest_new_pdfs(pdf_dir, db_path)
  -> Compares PDFs on disk vs races.pdf_source in DB
  -> Parses only new PDFs, inserts with INSERT OR IGNORE
  -> Idempotent: safe to re-run
  |
  v
model.fit.refit_from_db(db_path)
  -> Queries ALL valid time records from DB
  -> Fits TOP + JUNCTION Stan models (full refit, ~5-10 sec each)
  -> Saves posteriors to data/model_output/
  -> Only runs if new data was actually ingested
```

## CLI Usage (`scripts/run_update.py`)

```bash
# Normal daily update (auto-detects start date):
python scripts/run_update.py

# First-time full historical load:
python scripts/run_update.py --full

# Preview without making changes:
python scripts/run_update.py --dry-run

# Run individual phases:
python scripts/run_update.py --extract-only
python scripts/run_update.py --ingest-only
python scripts/run_update.py --refit-only

# Skip model refit:
python scripts/run_update.py --no-refit

# Override start date:
python scripts/run_update.py --after 2026/01/15
```

## Edge Cases

| Case | Handling |
|------|----------|
| First run, no DB | `CrestaDB()` creates tables; `MAX(date)` returns NULL; uses default 2020/01/01 |
| No new emails | Extraction returns 0 downloads; ingestion skipped; model refit skipped |
| PDF downloaded but ingestion fails | PDF stays on disk; next run re-attempts ingestion (INSERT OR IGNORE is safe) |
| Re-running after success | Email dedup + file dedup + INSERT OR IGNORE = no duplicate work |
| DB corrupted | Delete `data/cresta.db`, run `--full` to rebuild from PDFs on disk |
| Older PDFs (~2020) without split data | TimeRecords are valid without splits; split columns are nullable by design, so no special handling is needed |

## `db.py` Additions

```python
# Add to CrestaDB class:

def get_max_race_date(self) -> datetime.date | None:
    """Return latest race date in DB, or None."""
    cursor = self.conn.execute("SELECT MAX(date) FROM races")
    row = cursor.fetchone()
    return datetime.date.fromisoformat(row[0]) if row and row[0] else None

def get_ingested_pdf_sources(self) -> set[str]:
    """Return set of pdf_source filenames already in the races table."""
    cursor = self.conn.execute("SELECT DISTINCT pdf_source FROM races WHERE pdf_source != ''")
    return {row[0] for row in cursor.fetchall()}
```

## `pipeline.py` Addition

```python
def ingest_new_pdfs(pdf_dir: Path, db_path: Path) -> IngestStats:
    """Ingest only PDFs not already in the DB (by pdf_source filename)."""
    with CrestaDB(db_path) as db:
        already_ingested = db.get_ingested_pdf_sources()
        all_pdfs = sorted(pdf_dir.glob("*.pdf"))
        new_pdfs = [p for p in all_pdfs if p.name not in already_ingested]
        # Process each with ingest_single_pdf(db, path)
        # INSERT OR IGNORE ensures safety on re-runs
```

## `model/fit.py` Addition

```python
def refit_from_db(db_path: Path, output_dir: Path | None = None) -> dict:
    """Full refit of TOP + JUNCTION models from all DB data.
    Skips a model if < 20 observations for that start position."""
    for position in ("TOP", "JUNCTION"):
        stan_data = build_stan_data(db_path, start_position=position)
        if stan_data["N"] < 20:
            continue
        model = compile_model()
        fit = fit_model(model, stan_data)
        # Save results + run diagnostics
```

## Testing

| Test File | Key Cases |
|-----------|----------|
| `test_orchestrator.py` | `get_last_race_date` with no DB / empty DB / populated DB; `compute_start_date` with None / valid date / month boundary; `run_incremental` triggers refit only when new data ingested |
| `test_db.py` (additions) | `get_max_race_date` with 0/1/N races; `get_ingested_pdf_sources` empty and populated |
| `test_pipeline.py` (additions) | `ingest_new_pdfs` skips already-ingested; idempotent on re-run; handles empty dir |

## Verification

1. **Unit tests**: `pytest --verbose -m "not integration"` — all orchestrator, DB, and pipeline tests pass
2. **Manual test with 1 PDF**: Place a PDF in `data/raw_pdfs/`, run `python scripts/run_update.py --ingest-only`, verify data in DB with `python scripts/inspect_db.py --counts`
3. **Incremental test**: Run update, add a new PDF, run update again — verify only the new PDF is processed
4. **Dry run**: `python scripts/run_update.py --dry-run` — verify no DB changes or downloads

## Implementation Order

1. Create `docs/implementation-plan-incremental-update.md`
2. Update `docs/implementation-plan-pdf-parsing-db.md` — add incremental ingestion section referencing `get_max_race_date()`, `get_ingested_pdf_sources()`, and `ingest_new_pdfs()`
3. Update `docs/bayesian-model-plan.md` — add section on incremental refits via `refit_from_db()` and orchestrator trigger
4. Add `get_max_race_date()` and `get_ingested_pdf_sources()` to `db.py` (when it's built)
5. Add `ingest_new_pdfs()` to `pipeline.py` (when it's built)
6. Add `refit_from_db()` to `model/fit.py` (when it's built)
7. Create `src/smtc_handicap/orchestrator.py`
8. Create `scripts/run_update.py`
9. Create `tests/test_orchestrator.py`
