# TODO

## Handicap Engine (active project — `ui-design` branch)

- [x] Brainstorm and write design spec (`docs/superpowers/specs/2026-06-12-handicap-engine-design.md`)
- [ ] User reviews + approves spec
- [ ] Invoke superpowers:writing-plans to produce implementation plan
- [ ] Decide implementation branch (new feature branch off `develop`, or continue on `ui-design`)
- [ ] Implement per §11 of the spec:
  - [ ] DB migration: `handicap_decisions` + `handicap_decision_rows`
  - [ ] Extend `model/data_prep.py` for per-course design matrices
  - [ ] New Stan model `model/stan/cresta_course.stan` + `scripts/fit_course_model.py`
  - [ ] Fit TOP and JUNCTION course models; validate against §6.5 gates
  - [ ] Engine package `src/smtc_handicap/handicap/`: `metrics.py` → `simulator.py` → `optimizer.py`
  - [ ] Extend `ui/queries.py` with per-course helpers + decision persistence
  - [ ] Rewrite Streamlit `ui/app.py` around the §8 component decomposition
  - [ ] Manual UI smoke test
  - [ ] Update memory + PROGRESS.md

## Pre-engine maintenance

- [ ] Merge `feature/improve-top-model-tightness` into `develop` (11 commits ahead per memory)
- [ ] Re-fit JUNCTION finish-time model with updated code (separate from the new course-level model)
- [ ] Decide what to do with local-only branches:
  - [ ] `calendar` worktree — race master table builder + Bucherer Trophy fix (2 commits, unpushed)
  - [ ] `feature/rider-names` worktree — effectively empty, safe to delete

## Older standing items

- [x] Archive plans to build the models and the UI
- [x] Keep only the TOP model that met Ralph Wiggum exit criteria
- [ ] Incremental practice-timesheet ingestion + refit script
- [ ] Race-timesheet → Bayesian handicap → tightness-of-top-{3,6,10} script
- [ ] Standard Ralph Wiggum loop script for ongoing model improvement
