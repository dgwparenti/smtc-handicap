# Progress

## Current Branch: `feature/bayesian-handicap-model`

### Completed

- **PDF parsing pipeline** — Built end-to-end pipeline: PDF text extraction (`pdf_parser.py`), filename parsing (`filename_parser.py`), name normalization (`name_normalizer.py`), SQLite storage (`db.py`), and orchestrator (`pipeline.py`). 19 PDFs → 36 races, 620 riders, 3480 time records with 0 orphans.
- **Data models** — `Race`, `Rider`, `TimeRecord` dataclasses in `models.py`
- **Unit tests** — 113 tests covering parsing, normalization, DB, pipeline, and model data prep
- **UI specification** — Handicap Explorer Streamlit app spec with KDE bell curves
- **Dev tooling** — Pre-push hook (ruff check + format --check), pre-commit hook (auto-format staged Python files with ruff), lint fixes
- **Project config** — CLAUDE.md with branch workflow and progress tracking instructions
- **Bayesian handicap model** — Hierarchical Stan model for computing rider handicaps:
  - Stan model (`cresta_handicap.stan`): non-centered parameterization, population/rider/season/race-type hierarchy, SL improvement trend, shared sigma_obs
  - Data prep (`model/data_prep.py`): SQLite → Stan data dict with outlier filtering, min_runs filtering, contiguous index mapping
  - Fit (`model/fit.py`): CmdStanPy compilation and MCMC sampling (adapt_delta=0.9, max_treedepth=12)
  - Diagnostics (`model/diagnostics.py`): R-hat, ESS, divergence checks via arviz
  - Predict (`model/predict.py`): Posterior handicap calculation with credible intervals, post-hoc per-rider consistency
  - Both TOP (N=1220, J=174, R=8) and JUNCTION (N=1528, J=264, R=3) models converge cleanly: R-hat=1.000, ESS>900, 0 divergences, ~5-8s runtime

### Observations / Known Issues

- `sigma_obs=15.0` hits the upper bound for TOP model — suggests high residual variance in the data (diverse rider population). May warrant investigation or a higher cap.
- With S=1 (single season), the season component is effectively disabled via tight prior (sigma_season_sd=0.01). Will become useful when multi-season data is available.
- `beta_improve ≈ -0.05` for SL riders — slight improvement per run but credible interval crosses zero with current data.

### Next Steps

- **Validate against committee handicaps** — Compare model-suggested handicaps to actual committee handicaps in the DB, compute MAE
- **Investigate sigma_obs cap** — Determine if the 15s upper bound is too restrictive or if the high residual variance is expected
- **Merge to develop** — PR `feature/pdf-parsing-pipeline` → `develop`, then `feature/bayesian-handicap-model` → `develop`
- **Streamlit UI** — Implement the Handicap Explorer app per the UI spec
- **Incremental PDF ingestion** — Skip already-processed PDFs, handle new downloads
