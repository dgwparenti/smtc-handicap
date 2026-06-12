# Progress

## Current Branch: `ui-design`

Off `develop`. Holds the design spec for the next major piece of work: the **Handicap Engine** — a pre-race decision tool that replaces the existing Handicap Explorer. Implementation plan not yet written.

### Just Committed

- **Handicap engine design spec** — `docs/superpowers/specs/2026-06-12-handicap-engine-design.md` (commit `3e365d4`). Covers: new per-course hierarchical Bayesian model (TOP + JUNCTION), Monte Carlo simulator + greedy optimizer, objective slider (tight finish ↔ volatile leaderboard), Streamlit UI shaped for a future React port, `handicap_decisions` persistence. Brainstormed via superpowers:brainstorming.

### Previously Completed (merged to `develop`)

- **PDF + JSON ingestion pipeline** — `pdf_parser.py`, `json_parser.py`, `filename_parser.py`, `name_normalizer.py`, `pipeline.py`. JSONs ingested first for richer data (splits, speeds, start times). Current DB: 525 races, 3276 riders, 53788 time records, 0 orphans.
- **Bayesian handicap model (finish-time)** — Stan model `cresta_handicap.stan`, fit script `scripts/fit_model.py --position {TOP,JUNCTION}`. TOP fit currently in PASS state (avg range 0.969s, win rate 72.7%) after power-law compression tuning across 9 Ralph Loop iterations. JUNCTION fit exists but needs re-fit with updated code.
- **Handicap Explorer UI** — Streamlit app at `src/smtc_handicap/ui/app.py` (3-layer: queries → plots → app). To be replaced by the handicap engine UI per the new spec.
- **Gmail integration** — `gmail_extractor.py` + `scripts/fetch_and_ingest.py`. Fetches timesheet PDFs, supports re-ingestion via `delete_by_pdf_source`.
- **Webhook API** — FastAPI service for Gmail PDF extraction and ingestion. Provides the precedent for the future engine HTTP layer.
- **Marsden Cup + Coppa analyses** — `scripts/marsden_cup_analysis.py`, `scripts/coppa_bayesian_handicaps.py`. Source of the naive-equalizing-handicap heuristic the new optimizer will reuse as a seed.
- **Dev tooling** — Pre-push hook (ruff check + format), pre-commit hook (auto-format staged Python).

### Handicap Engine — Not Yet Implemented

Design spec approved; implementation plan still to be written via superpowers:writing-plans. Build order per §11 of the spec:

1. Migration: add `handicap_decisions` + `handicap_decision_rows` tables in `db.py`.
2. Extend `model/data_prep.py` for per-course design matrices.
3. New Stan model `model/stan/cresta_course.stan`; fit script `scripts/fit_course_model.py`; validate against §6.5 gates (R-hat < 1.05, < 1% divergences, ≥ 80% PPC coverage on held-out races).
4. New engine package `src/smtc_handicap/handicap/`: `metrics.py` → `simulator.py` → `optimizer.py`. Pure Python, no UI deps.
5. Extend `ui/queries.py` with per-course helpers + decision persistence.
6. Rewrite `ui/app.py` around the component decomposition in §8 of the spec. Drop Explorer-only plots/queries.
7. Manual UI smoke test; update memory.

### Next Session TODO

1. User reviews the design spec and approves or requests changes.
2. Invoke superpowers:writing-plans to produce the implementation plan.
3. Decide branch strategy for implementation (per CLAUDE.md): new feature branch off `develop`, or continue on `ui-design`.
4. Merge `feature/improve-top-model-tightness` into `develop` (still 11 commits ahead per memory).
5. Re-fit JUNCTION finish-time model with updated code (separate from the new course-level model the spec calls for).

### Observations / Known Issues

- Existing TOP/JUNCTION finish-time models stay in place — other scripts (`fit_model.py`, `evaluate_tightness.py`, `marsden_cup_analysis.py`, `coppa_bayesian_handicaps.py`) keep using them. The new course-level models are parallel, not a replacement.
- `race_id` is nullable on `handicap_decisions` so the committee can handicap a race before it exists in the DB. Reconciliation with later-ingested race PDFs is deferred.
- Streamlit `st.data_editor` is the implementation target for the draw table; will need to verify autocomplete + per-row scratch radio work cleanly inside it.
