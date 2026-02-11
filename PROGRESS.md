# Progress

## Current Branch: `feature/pdf-parsing-pipeline`

### Completed

- **PDF parsing pipeline** — Built end-to-end pipeline: PDF text extraction (`pdf_parser.py`), filename parsing (`filename_parser.py`), name normalization (`name_normalizer.py`), SQLite storage (`db.py`), and orchestrator (`pipeline.py`). 19 PDFs → 36 races, 620 riders, 3480 time records with 0 orphans.
- **Data models** — `Race`, `Rider`, `TimeRecord` dataclasses in `models.py`
- **Unit tests** — 96 tests covering parsing, normalization, DB, and pipeline logic
- **UI specification** — Handicap Explorer Streamlit app spec with KDE bell curves
- **Dev tooling** — Pre-push hook (ruff check + format --check), pre-commit hook (auto-format staged Python files with ruff), lint fixes
- **Project config** — CLAUDE.md with branch workflow and progress tracking instructions

### Next Steps

- **Merge to develop** — PR `feature/pdf-parsing-pipeline` → `develop` when ready
- **Streamlit UI** — Implement the Handicap Explorer app per the UI spec
- **Incremental PDF ingestion** — Skip already-processed PDFs, handle new downloads
- **Handicap calculation** — Core algorithm for computing rider handicaps from time records
