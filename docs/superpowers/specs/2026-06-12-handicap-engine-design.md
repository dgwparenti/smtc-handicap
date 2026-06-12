# Handicap Engine — Design Spec

**Date:** 2026-06-12
**Branch (brainstorming):** `ui-design`
**Status:** Design approved, awaiting implementation plan

## 1. Purpose

Build a pre-race decision tool for the Cresta handicapping committee. The committee enters the draw for an upcoming race; the tool suggests handicaps (to 0.1s) that optimize a chosen race-quality objective, lets the committee override, and shows live race-quality metrics (top-N spread, per-rider win probabilities) updated as overrides happen.

This replaces the existing Handicap Explorer (`src/smtc_handicap/ui/app.py`) — the distribution-comparison view becomes a sub-panel of the new workflow.

## 2. Domain primer (for readers without context)

- **Cresta** is a head-first ice-track sport similar to Olympic skeleton. Races run from one of two start positions: **TOP** or **JUNCTION**.
- A handicap race has **3 courses (runs)** per rider. Ranking is on **net time = raw time − handicap**, summed across 3 courses.
- **Scratch rider (`scr`)** is the baseline: handicap = 0. All other riders receive positive handicaps (seconds subtracted from raw time).
- A well-handicapped race has the top finishers within ~0.5–1.0s of each other on net time. The current weakness: occasional "breakout" riders win every course from a soft handicap, killing the drama.

## 3. Decisions locked during brainstorming

| # | Decision |
|---|---|
| 1 | Replace existing Handicap Explorer; distribution view becomes a sub-panel |
| 2 | Slider objective: `w=0` = tight finish spread; `w=1` = volatile leaderboard. Live recompute of metrics on override; optimizer runs only on "Suggest all" |
| 3 | Sample 3 independent per-course times per rider; per-course distributions come from a new hierarchical Bayesian model |
| 4 | Two-phase override: "Suggest all" → manual edits → metrics recompute live; "Reset to suggestions" reverts |
| 5 | Position selector (TOP / JUNCTION) at top of page filters everything |
| 6 | Editable autocomplete draw table; scratch flagged in-row; row order = start order |
| 7 | Multi-rider distribution overlay (2–3 riders vs scratch) |
| 8 | Hierarchical shrinkage handles sparse-data riders |
| 9 | Save final draw + handicaps to new `handicap_decisions` table (race-result reconciliation deferred) |
| 10 | Fixed KPI tiles: spread(top-3), spread(top-6), spread(top-8); CSV export of final draw |
| 11 | Per-course shared race-day random offsets in the simulator |

## 4. Architecture

Four layers. The handicap engine and the UI are decoupled so that a future React frontend can call the engine via a thin FastAPI router (precedent: existing `src/smtc_handicap/api/`).

```
ui/streamlit/      ──┐
                     ├──► handicap/  ──► model/ (top_course.nc | junction_course.nc) ──► db
api/ (future)      ──┘
```

**Layer boundaries:**

- **UI / API adapters** — translate human/HTTP input to engine input; render engine output. No statistics, no DB calls beyond `queries.py` helpers.
- **Handicap engine** (`src/smtc_handicap/handicap/`) — pure Python, no UI or framework deps. Takes plain dicts/lists, returns plain dataclasses. Single source of truth for simulation, optimization, and metrics.
- **Model layer** (`src/smtc_handicap/model/`) — Stan model code + posterior loaders. Extended `data_prep.py` for per-course design matrices.
- **Data layer** (`src/smtc_handicap/db.py`) — extended with `handicap_decisions` + `handicap_decision_rows` tables; new per-course query helpers in `ui/queries.py`.

**Two fitted models** — one per start position. Each is the *same Stan code*, run twice with different filtered data:

- `data/model_fits/top_course.nc`
- `data/model_fits/junction_course.nc`

Per-course structure lives **inside** each model (course-number effect, per-race × per-course offset). Per-start-position lives **across** models (separate fits).

The existing finish-time models (`top.nc`, junction `.nc`) are **not** retired — other scripts (`fit_model.py`, `evaluate_tightness.py`, `marsden_cup_analysis.py`, `coppa_bayesian_handicaps.py`) keep using them. This project adds parallel course-level models.

## 5. Data layer

### 5.1 Existing tables (unchanged)

- `riders`, `races`, `time_records`. The `run_number` column on `time_records` is the course number (1, 2, 3) — per-course data is already there.

### 5.2 New tables

```sql
CREATE TABLE IF NOT EXISTS handicap_decisions (
    decision_id        TEXT PRIMARY KEY,           -- UUID, client-generated
    race_id            TEXT REFERENCES races(race_id),  -- NULL allowed (future race)
    race_date          TEXT NOT NULL,              -- ISO date
    race_name          TEXT,
    start_position     TEXT NOT NULL CHECK (start_position IN ('TOP','JUNCTION')),
    scratch_rider_id   TEXT NOT NULL REFERENCES riders(rider_id),
    objective_weight   REAL NOT NULL,              -- slider value at save time
    created_at         TEXT NOT NULL,              -- ISO datetime
    notes              TEXT
);

CREATE TABLE IF NOT EXISTS handicap_decision_rows (
    decision_id        TEXT NOT NULL REFERENCES handicap_decisions(decision_id) ON DELETE CASCADE,
    start_order        INTEGER NOT NULL,
    rider_id           TEXT NOT NULL REFERENCES riders(rider_id),
    suggested_handicap REAL NOT NULL,
    final_handicap     REAL NOT NULL,
    PRIMARY KEY (decision_id, start_order)
);
```

`race_id` nullable lets the committee handicap a race before it exists in the DB. A later reconciliation step (out of scope) can match `(race_date, start_position)` to the ingested race PDF to backfill the FK.

### 5.3 New query helpers (extension to `ui/queries.py`)

| Function | Purpose |
|---|---|
| `course_records(position, season_window)` | Per-course observations feeding the Bayesian fit. Excludes falls, DNFs, out-of-bounds times. |
| `rider_course_history(rider_id, position)` | Per-course times for the distribution overlay panel (empirical histogram + best-ever / best-of-season). |
| `riders_for_position(position, min_rides=1)` | Autocomplete source for the draw table. |
| `save_decision(decision)` / `load_decision(decision_id)` / `recent_decisions(limit=20)` | Persistence helpers. |

Explorer-only queries from the current `queries.py` are removed in the same change set (listed during implementation; not enumerated here to avoid drift).

## 6. Course-level Bayesian model

### 6.1 Observation unit

One row per (rider, race, course) where:

- `is_practice = 0`. Both handicap and open races are included: `time_records.finish_time` is the **raw** time, and `handicap` is stored separately, so raw observations from handicap races are usable. The exact filter mirrors `model/data_prep.py` — confirmed during implementation.
- `is_fall = 0 AND is_dnf = 0`.
- `finish_time` within outlier bounds: TOP `[49.7, 70.0]s`, JUNCTION `[41.0, 55.0]s`.
- Race-type collapsing as today: rare race types merged when `min_obs < 100`.

### 6.2 Model specification

For observation `i` in rider `j[i]`, race `r[i]`, course `c[i] ∈ {1,2,3}`, season `s[i]`:

```
y_i ~ Normal( μ_{j[i]} + γ_{c[i]} + δ_{r[i], c[i]} + β_{j[i]} · season_num_{s[i]},   σ_{j[i]} )

μ_j     ~ Normal(μ_pop, σ_pop)            # rider mean — shrinkage on sparse riders
log σ_j ~ Normal(log σ_pop, τ_σ)          # rider noise scale — positive, pooled
β_j     ~ Normal(β_pop, τ_β)              # rider seasonal trend

γ_c     ~ Normal(0, 0.5)                  # course baseline (1/2/3), sum-to-zero
δ_{r,c} ~ Normal(0, σ_race)               # per-race × per-course shared offset
```

### 6.3 Mapping requirements → structure

| Requirement (decision #) | Model element |
|---|---|
| Hierarchical shrinkage (8) | `μ_j ~ Normal(μ_pop, σ_pop)` + pooled `log σ_j` |
| Per-course simulation (3) | `γ_c` baseline + `δ_{r,c}` sampled per course |
| Race-day shared conditions (11) | `δ_{r,c}` correlates all riders in one race × course |
| Per-rider noise scale | `σ_j` |
| Season improvement | `β_j · season_num` |

### 6.4 Priors and sampler

Start from the values the existing TOP finish-time model converged on: tight priors, `adapt_delta=0.95`. Tune from there. Specific prior parameter values land during implementation; nothing in this spec depends on a particular choice.

### 6.5 Validation gates

A new course-level fit is accepted as production-ready only when:

- All parameter R-hat < 1.05.
- Divergent transitions < 1% of post-warmup draws.
- Posterior predictive coverage: simulate a held-out historical race; observed finishing spread sits inside the 95% CI of the simulated spread for ≥ 80% of held-out races.

### 6.6 Artifacts

- Stan code: `src/smtc_handicap/model/stan/cresta_course.stan`
- Fit script: `scripts/fit_course_model.py --position {TOP,JUNCTION}` (modeled on existing `fit_model.py`)
- Output: `data/model_fits/{top,junction}_course.nc` (not in git)

## 7. Handicap engine

### 7.1 Public surface

```python
# simulator.py
def simulate_race(
    draw: list[str],              # rider_ids in start order
    scratch_rider_id: str,
    handicaps: dict[str, float],  # rider_id -> seconds; scratch entry forced to 0
    position: Literal["TOP", "JUNCTION"],
    n_iter: int = 4000,
    rng_seed: int | None = None,
) -> SimResult

# optimizer.py
def suggest_handicaps(
    draw: list[str],
    scratch_rider_id: str,
    position: Literal["TOP", "JUNCTION"],
    objective_weight: float,      # 0..1
    locked: dict[str, float] | None = None,   # API support; UI doesn't expose in MVP
) -> SuggestResult

# metrics.py
def compute(sim_result: SimResult) -> Metrics
```

All inputs and outputs are plain Python types or dataclasses — no Streamlit, no Plotly, no DataFrames-with-display-state.

### 7.2 Return shapes

```python
@dataclass
class SimResult:
    net_times: np.ndarray         # shape (n_iter, n_riders, 3); raw − handicap
    rider_ids: list[str]
    warnings: list[str]           # e.g. "rider X has no rides at this position"

@dataclass
class Metrics:
    spread_top: dict[int, float]      # {3: mean, 6: mean, 8: mean}
    spread_top_ci: dict[int, tuple]   # {3: (lo, hi), 6: ..., 8: ...}  80% CI
    p_top8: dict[str, float]          # rider_id -> probability
    p_position: dict[str, dict[int, float]]   # rider_id -> {1: p, 2: p, 3: p}
    p_position_change: dict[str, float]       # rider_id -> probability rank changes across courses

@dataclass
class SuggestResult:
    suggested: dict[str, float]
    naive_seed: dict[str, float]
    final_metrics: Metrics
    iterations: int
```

### 7.3 Simulator algorithm (per Monte Carlo iteration)

1. **Sample rider parameters** `(μ_j, σ_j, β_j)` from the appropriate course-level posterior — one draw per rider per iteration. Unseen riders fall back to `(μ_pop, σ_pop, β_pop)` (the hierarchical fallback comes free).
2. **Sample race conditions** for this iteration: three independent `δ_c ~ Normal(0, σ_race_posterior_draw)`, and `γ_c` posterior draws. Shared across all riders in this iteration — this is the Q11 correlation.
3. **Compute raw time per rider per course:**
   `raw_{j,c} = μ_j + γ_c + δ_c + β_j · current_season_num + ε_{j,c}`, with `ε_{j,c} ~ Normal(0, σ_j)`.
4. **Apply handicap:** `net_{j,c} = raw_{j,c} − handicap_j`.
5. **Standings per course** = cumulative net through course `c`, ranked ascending.

### 7.4 Performance

- Vectorized in NumPy. Target: `n_iter=4000` × ~15 riders × 3 courses simulates in < 100ms.
- Posterior `.nc` loaded once per session; held in `st.session_state` (or module-level for FastAPI).
- Posterior draws for the riders in the draw are pre-extracted on draw-change events, not on every override.
- UI target round-trip on a final-handicap edit: < 300ms. Fallback to `n_iter=2000` if missed; full `n_iter=4000` on "Suggest all".

### 7.5 Optimizer (greedy coordinate descent)

Triggered only by **"Suggest all"** (not by slider drag).

1. **Seed** = naive equalizing handicap per non-scratch rider:
   `h_j^0 = E[μ_j + β_j · current_season + 3·γ̄] − E[μ_scratch + β_scratch · current_season + 3·γ̄]`, rounded to 0.1s. Reuses logic from `coppa_bayesian_handicaps.py`.
2. **Evaluate** loss `L = (1 − w) · S − w · V` where
   - `S` = mean `spread_top6` over iterations, normalized by spread at the naive seed (dimensionless).
   - `V` = sum over top-8 finishers of `p_position_change`, normalized to ~[0, 1].
3. **Sweep** for each non-scratch rider in random order: candidates `h_j^0 ± Δ` for `Δ ∈ {−1.0, −0.9, …, +1.0}` in 0.1s steps (21 candidates). Hold others fixed; pick the candidate minimizing `L` at `n_iter=1500`.
4. **Repeat** for up to 3 passes or until no handicap moves by more than 0.1s in a pass.
5. **Final evaluation** at `n_iter=4000` for the KPI tiles.

Performance budget: 5–10s end-to-end. Spinner with per-pass progress.

`locked` parameter (post-MVP): handicaps in `locked` are passed through and excluded from sweep — engine signature is designed in; UI exposes it later.

### 7.6 Edge cases

- **Scratch handicap.** Forced to 0 inside the engine. UI passes are silently corrected if wrong; a debug log line emits.
- **Unseen rider** (zero rides at this position). Population-level posterior used; `SimResult.warnings` lists the rider so UI can flag.
- **Invalid rider_id.** Engine raises `EngineError`. UI validates upstream.

## 8. UI (Streamlit now, React-shaped)

Streamlit implements the same component decomposition planned for the future React frontend. Each component below has the same props/events surface in both worlds.

### 8.1 Component tree

```
PageHeader              { position, race_name, race_date }
KpiTileRow              { metrics }                       → read-only
ObjectiveSlider         { weight }
DrawTable               { rows, riders, metrics }
DistributionPanel       { selected_rider_ids, scratch_rider_id, position }   collapsible
ActionBar               { is_dirty }
```

### 8.2 Streamlit-specific mapping

| Component | Streamlit primitives |
|---|---|
| `PageHeader` | `st.radio` (position), `st.text_input`, `st.date_input` |
| `KpiTileRow` | `st.columns` + custom HTML/markdown cards |
| `ObjectiveSlider` | `st.slider` |
| `DrawTable` | `st.data_editor` with column config for autocomplete + numeric edit |
| `DistributionPanel` | `st.plotly_chart`, `st.multiselect` |
| `ActionBar` | row of `st.button` |

### 8.3 Single source of truth

`st.session_state["app_state"]` holds: `position`, `race_meta`, `draw_rows`, `objective_weight`, `last_sim_result`, `last_suggest_result`. Every callback mutates this dict. React port: same shape lifted into `useReducer` or a small store.

### 8.4 Recompute trigger graph

| Event | Action |
|---|---|
| Position change | clear draw, reload riders, clear metrics |
| Add/remove row, change scratch | clear suggested + final, clear metrics, mark dirty |
| Slider change | mark dirty (no recompute) |
| Final handicap edit | re-run `simulator` + `metrics` only |
| "Suggest all" | run `optimizer`; fill suggested; final ← suggested; refresh metrics |
| "Reset to suggestions" | copy suggested → final; refresh metrics |
| "Save decision" | validate, write to `handicap_decisions` + `handicap_decision_rows` |
| "Export CSV" | download `start_order, rider_name, rider_id, suggested_handicap, final_handicap` |

### 8.5 MVP scope cut

The `DistributionPanel` is **collapsed by default**. Rendered only when expanded — the most expensive component to draw and not on the critical decision path.

## 9. Distribution panel

### 9.1 Axes and curves

- **X-axis:** per-course finish time in seconds (not cumulative, not net-of-handicap).
- **Y-axis:** counts (smoothed histogram with 0.1s bins + small Gaussian kernel). Matches existing UI convention.

For each of: scratch rider + 2–3 selected comparison riders from the draw:

1. **Posterior predictive curve** — sampled from the course-level model: rider posterior `(μ_j, σ_j, β_j)` + `γ_c` for the currently selected course, binned. The model's current belief.
2. **Empirical histogram** (thin, semi-transparent) — actual per-course times from `time_records`, filtered to position. The raw evidence.
3. **Best-ever vertical line** — fastest per-course time at that position.
4. **Best-of-season vertical line** — fastest per-course time in the current season at that position.

### 9.2 Course selector

Toggle inside the panel: `Course: (1) (2) (3) (avg)`. Default `avg` uses `γ_c = 0`. Specific-course view shifts all curves by `γ_c`.

### 9.3 Colors

- Scratch → **orange** (always present).
- Comparison riders → **blue** shades, distinct at up to 3 riders. Beyond 3, panel forces deselection.
- Best-ever line → **green** dashed, per rider (matched hue to the rider's curve).
- Best-of-season line → **red** dashed, per rider.

### 9.4 Edge case — no historical rides

Empirical histogram and lines omitted for that rider. Posterior predictive drawn from population posterior, labeled "no prior rides — population estimate".

### 9.5 Intentional omissions

- Net-of-handicap times — covered by KPI tiles and per-rider metrics columns.
- Cumulative 3-course distributions — a derived race quantity, not a per-rider property.

## 10. Persistence, errors, testing

### 10.1 Save flow

1. Validate: race date set, position set, scratch chosen, ≥ 2 riders, every row has a final handicap.
2. Insert `handicap_decisions` + N `handicap_decision_rows` in one transaction. UUID generated client-side.
3. Toast with decision ID and copy affordance.
4. No edit-after-save in MVP. "Recent decisions" dropdown shows last 20; selecting one loads a read-only banner; "Clone to new draft" copies into a fresh draft.

CSV export operates on the current draft, independent of save.

### 10.2 Error handling boundaries

- **DB:** SQL errors propagate. App-layer validates before insert.
- **Engine:** raises `EngineError` for: model file missing, rider_id not in DB, scratch not in draw, duplicate riders.
- **UI:** catches `EngineError` inline; on missing `.nc`, surfaces the exact `python scripts/fit_course_model.py --position TOP` command.
- No defensive try/except inside engine math — trusted internal code.

### 10.3 Tests

| Layer | Type | Coverage |
|---|---|---|
| Model fit | Validation script (not pytest) | R-hat, divergences, PPC coverage gates (§6.5) |
| `metrics.py` | Unit | Hand-crafted `SimResult` → expected spread / P(top-K) / P(position-change) |
| `simulator.py` | Unit + integration | Seeded synthetic posterior → deterministic output; real `top_course.nc` → ranges sane |
| `optimizer.py` | Unit + integration | `w=0` synthetic: optimizer moves ≤ 0.1s from naive. `w=1`: optimizer diverges from naive. Real posterior + real draw completes in < 15s |
| `db.py` decisions | Unit | Save → load round-trip; constraint enforcement |
| UI | Manual smoke | Per CLAUDE.md: launch `streamlit run`, walk golden path + edge cases, screenshot |

Approx. 40 new tests across engine + decisions layers. No browser automation in MVP.

## 11. Implementation order (preview for the implementation plan)

1. Add `handicap_decisions` + `handicap_decision_rows` tables; schema migration in `db.py`.
2. Extend `model/data_prep.py` for per-course design matrices.
3. Write `cresta_course.stan`; write `scripts/fit_course_model.py`; fit both TOP and JUNCTION; validate against §6.5 gates.
4. Build `handicap/` package: `metrics.py` → `simulator.py` → `optimizer.py`. Unit + integration tests per layer.
5. Extend `ui/queries.py` with per-course helpers + decision persistence.
6. Rewrite Streamlit `ui/app.py` around the component structure in §8. Adapt `ui/plots.py` distribution overlay; drop Explorer-only plots and queries.
7. Manual UI smoke test; update memory.

## 12. Explicit MVP scope cuts (designed for, deferred)

- Locked handicaps in the optimizer UI (engine surface supports it).
- Edit / version a saved decision.
- Reconciling `handicap_decisions.race_id` with later-ingested race PDFs (post-race "did our decisions hold up?" analysis).
- "Why this handicap?" explanation panel surfacing posterior summaries.
- Configurable top-N tiles (locked at 3 / 6 / 8).
- Storing RNG seed for decision reproducibility.

## 13. Open items to confirm during implementation (not blocking design approval)

- Exact prior parameter values for `cresta_course.stan` — start from existing TOP model values; tune.
- Exact filter rule for handicap vs practice races in `data_prep.py` — mirror the existing rule; confirm in code.
- Specific Plotly color hex codes — pull from existing `plots.py` to maintain visual continuity.
