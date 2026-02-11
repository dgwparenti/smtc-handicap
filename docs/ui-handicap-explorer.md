# Handicap Explorer UI — Design & Implementation Plan

## 1. Purpose

An interactive Streamlit application for exploring rider performance and handicap data from the Cresta Run. The UI helps the handicap committee answer three questions:

1. **How is this person riding overall and this season?**
2. **How is this person comparing to the whole field?**
3. **How does this person compare to the scratch rider?**

The Bayesian model (see `bayesian-model-plan.md`) is not yet implemented. This UI initially uses **empirical distributions** (KDE over raw finish times) and the **median finish time** as a proxy for the model's predicted expected time. Explicit swap points are documented for when the model is ready.

---

## 2. Architecture

Three-layer separation keeps query logic testable independent of the UI framework:

```
SQLite (data/cresta.db)
    |
    v
queries.py   — data query & aggregation layer
    |
    v
plots.py     — Plotly chart factory functions
    |
    v
app.py       — Streamlit application (layout, controls, rendering)
```

### File Structure

```
src/smtc_handicap/
  ui/
    __init__.py          # empty package init
    queries.py           # data query & aggregation
    plots.py             # Plotly chart factories
    app.py               # Streamlit entry point

tests/
  test_ui_queries.py     # unit tests for query layer
  test_ui_plots.py       # smoke tests for plot functions
```

### Dependencies

Add as an optional group in `pyproject.toml` to keep the core pipeline lightweight:

```toml
[project.optional-dependencies]
ui = [
    "streamlit>=1.30",
    "plotly>=5.18",
    "scipy>=1.11",
]
```

Install: `pip install -e ".[ui]"`

---

## 3. Season Definition

The Cresta Run season spans **December through March**. A race's season label is determined by:

- Oct–Dec dates belong to the season starting that year
- Jan–Sep dates belong to the season that started the previous year

| Race Date   | Season Label |
|-------------|-------------|
| 2025-12-20  | 2025/26     |
| 2026-01-15  | 2025/26     |
| 2026-03-01  | 2025/26     |

```python
def get_season_label(date: datetime.date) -> str:
    if date.month >= 10:
        return f"{date.year}/{str(date.year + 1)[2:]}"
    else:
        return f"{date.year - 1}/{str(date.year)[2:]}"
```

---

## 4. Data Filtering Rules

All queries exclude invalid finish times before computing distributions:

| Filter | Rule |
|--------|------|
| Falls | `is_fall = 0` |
| DNFs | `is_dnf = 0` |
| Null times | `finish_time IS NOT NULL` |
| TOP outliers | `45s <= finish_time <= 120s` |
| JUNCTION outliers | `35s <= finish_time <= 90s` |

**Estimated time proxy**: Median of valid finish times for the rider on that course. This will be replaced by the Bayesian posterior mean (`alpha_j + delta_{s,j} + gamma_r`) when the model is implemented.

---

## 5. UI Layout

### Sidebar Controls

| Control | Purpose | Scope |
|---------|---------|-------|
| **Season** selector | Filters "season best" and season-specific stats | Sections 1, 2, 3 |
| **Rider** selector | Primary rider for Sections 1 and 2 | Sections 1, 2 |
| **Scratch Rider** selector | Reference rider for handicap comparison | Section 3 |
| **Compared Rider** selector | Rider to compare against scratch | Section 3 |

All rider dropdowns show `display_name` (e.g. "F.P. Rueda (Jnr)") and use `rider_id` internally. Only riders with at least one valid finish time appear in the dropdowns.

---

### Section 1: Individual Rider Performance

> *"How is this person riding overall and this season?"*

**Layout**: Two plots side by side — TOP (left) and JUNCTION (right).

**Each plot contains**:

| Element | Visual | Description |
|---------|--------|-------------|
| Histogram | Light blue bars, low opacity | Raw finish time distribution (all time) |
| KDE (all-time) | Solid blue line, filled area | Smoothed density of all valid finish times |
| KDE (season) | Dashed blue line | Smoothed density of current season finish times only |
| Best-ever line | Solid green vertical line | Minimum finish time across all data |
| Season-best line | Dashed red vertical line | Minimum finish time in selected season |

**Below each plot**: metric cards showing total runs (all-time) and season runs.

**Edge cases**:
- Fewer than 2 times on a course: show individual times as dots instead of KDE
- No data for a course: show "No data available" annotation

```
┌─────────────────────────────────────────────────────┐
│  Section 1: Individual Rider Performance            │
│                                                     │
│  ┌──────────────────┐  ┌──────────────────┐         │
│  │   TOP             │  │   JUNCTION        │       │
│  │                   │  │                   │       │
│  │  ░░░▓▓▓▓▓░░      │  │  ░░▓▓▓▓░░░       │       │
│  │  │g    │r         │  │  │g  │r           │       │
│  │                   │  │                   │       │
│  └──────────────────┘  └──────────────────┘         │
│  Runs: 42 (season: 12)   Runs: 28 (season: 8)      │
└─────────────────────────────────────────────────────┘
  g = best ever (green)   r = season best (red)
```

---

### Section 2: Rider vs Field

> *"How is this person comparing to the whole field?"*

**Layout**: Two plots side by side — TOP (left) and JUNCTION (right).

**Each plot contains**:

| Element | Visual | Description |
|---------|--------|-------------|
| Field KDE | Light blue filled area | Distribution of ALL riders' finish times on this course |
| Rider KDE | Darker blue filled area (semi-transparent overlay) | This rider's finish time distribution |
| Rider median line | Blue vertical line | Rider's estimated time (median) |
| Field median line | Grey dashed vertical line | Overall field median |

The rider's distribution is overlaid on the field distribution, making it immediately visible whether the rider is faster than average, in the middle, or slower.

```
┌─────────────────────────────────────────────────────┐
│  Section 2: Rider vs Field                          │
│                                                     │
│  ┌──────────────────┐  ┌──────────────────┐         │
│  │   TOP             │  │   JUNCTION        │       │
│  │                   │  │                   │       │
│  │ ░░░░░░░░░░░░░░   │  │ ░░░░░░░░░░░░░    │       │
│  │    ▓▓▓▓▓▓         │  │   ▓▓▓▓▓          │       │
│  │    │b  │g         │  │   │b │g           │       │
│  │                   │  │                   │       │
│  └──────────────────┘  └──────────────────┘         │
└─────────────────────────────────────────────────────┘
  ░ = field   ▓ = rider   b = rider median   g = field median
```

---

### Section 3: Handicap Comparison

> *"How does this person compare to the scratch rider?"*

**Layout**: Two plots side by side — TOP (left) and JUNCTION (right).

**Controls**: Independent scratch rider and compared rider dropdowns in the sidebar.

**Each plot contains**:

| Element | Visual | Description |
|---------|--------|-------------|
| Scratch rider KDE | Orange filled area | Scratch rider's finish time distribution |
| Compared rider KDE | Blue filled area (semi-transparent overlay) | Compared rider's finish time distribution |
| Scratch estimated line | Orange vertical line | Scratch rider's median time |
| Rider estimated line | Blue vertical line | Compared rider's median time |
| Handicap annotation | Arrow + text between the two vertical lines | Gap = handicap value |

**Metric card** below each plot: "Estimated Handicap (TOP): X.XXs"

The handicap is computed as: `rider_median - scratch_median`. When the Bayesian model is implemented, this will be replaced by the posterior mean of `hat{y}_rider - hat{y}_scratch`.

```
┌─────────────────────────────────────────────────────┐
│  Section 3: Handicap Comparison                     │
│                                                     │
│  ┌──────────────────┐  ┌──────────────────┐         │
│  │   TOP             │  │   JUNCTION        │       │
│  │                   │  │                   │       │
│  │ ▒▒▒▒▒  ▓▓▓▓▓     │  │ ▒▒▒▒  ▓▓▓▓       │       │
│  │   │o     │b       │  │  │o    │b         │       │
│  │   ├──3.2s──┤      │  │  ├─2.8s──┤        │       │
│  │                   │  │                   │       │
│  └──────────────────┘  └──────────────────┘         │
│  H'cap: 3.20s            H'cap: 2.80s               │
└─────────────────────────────────────────────────────┘
  ▒ = scratch (orange)   ▓ = rider (blue)
  o = scratch median     b = rider median
```

---

## 6. Data Query Layer (`queries.py`)

### Key Data Structures

```python
@dataclass
class RiderTimeSummary:
    rider: Rider
    start_position: str          # "TOP" or "JUNCTION"
    all_times: list[float]       # all valid finish times
    season_times: list[float]    # valid times for selected season
    best_ever: float | None      # min(all_times)
    season_best: float | None    # min(season_times)
    median_time: float | None    # median(all_times) — proxy for estimated time
    season_median: float | None  # median(season_times)
    num_runs_total: int
    num_runs_season: int

@dataclass
class FieldTimeSummary:
    start_position: str
    all_times: list[float]       # all valid times from all riders
    season_times: list[float]
    num_riders: int
    num_runs: int

@dataclass
class HandicapComparison:
    rider_summary_top: RiderTimeSummary | None
    rider_summary_junction: RiderTimeSummary | None
    scratch_summary_top: RiderTimeSummary | None
    scratch_summary_junction: RiderTimeSummary | None
    handicap_top: float | None       # rider_median - scratch_median
    handicap_junction: float | None
```

### Key Functions

| Function | Input | Output | Description |
|----------|-------|--------|-------------|
| `get_season_label(date)` | `datetime.date` | `str` | Compute season label |
| `get_available_seasons(db)` | `CrestaDB` | `list[str]` | Distinct seasons in DB |
| `get_rider_options(db)` | `CrestaDB` | `list[(rider_id, display_name)]` | Riders with valid times |
| `get_rider_time_summary(db, rider_id, position, season)` | ... | `RiderTimeSummary` | Single rider stats |
| `get_field_time_summary(db, position, season)` | ... | `FieldTimeSummary` | All-rider stats |
| `get_handicap_comparison(db, rider_id, scratch_id, season)` | ... | `HandicapComparison` | Handicap gap data |

### SQL Queries

**Rider times for a position** (used by `get_rider_time_summary`):
```sql
SELECT tr.finish_time, ra.date
FROM time_records tr
JOIN races ra ON tr.race_id = ra.race_id
WHERE tr.rider_id = ?
  AND ra.start_position = ?
  AND tr.finish_time IS NOT NULL
  AND tr.is_fall = 0 AND tr.is_dnf = 0
  AND tr.finish_time BETWEEN ? AND ?
ORDER BY ra.date
```

**All field times** (used by `get_field_time_summary`):
```sql
SELECT tr.finish_time, ra.date
FROM time_records tr
JOIN races ra ON tr.race_id = ra.race_id
WHERE ra.start_position = ?
  AND tr.finish_time IS NOT NULL
  AND tr.is_fall = 0 AND tr.is_dnf = 0
  AND tr.finish_time BETWEEN ? AND ?
```

**Rider options** (used for dropdowns):
```sql
SELECT DISTINCT r.rider_id, r.display_name
FROM riders r
JOIN time_records tr ON r.rider_id = tr.rider_id
WHERE tr.finish_time IS NOT NULL AND tr.is_fall = 0 AND tr.is_dnf = 0
ORDER BY r.display_name
```

These queries leverage existing indexes: `idx_time_records_rider`, `idx_races_position`, `idx_races_date`, `idx_time_records_rider_race`.

Queries are implemented directly in `queries.py` via `db.conn.execute()` (following the pattern in `scripts/inspect_db.py`), not added as methods to `CrestaDB`.

---

## 7. Plot Layer (`plots.py`)

### Color Palette

| Element | Color | Hex |
|---------|-------|-----|
| Rider distribution | Blue | `#1f77b4` |
| Field distribution | Light blue | `#aec7e8` |
| Scratch rider | Orange | `#ff7f0e` |
| Best-ever line | Green | `#2ca02c` |
| Season-best line | Red | `#d62728` |

### KDE Computation

- Library: `scipy.stats.gaussian_kde` with Silverman bandwidth
- Grid: 200 points, extending 3s beyond data min/max
- Minimum data requirement: 2 points for KDE; below that, show individual times as markers

### Plot Functions

| Function | Section | Returns |
|----------|---------|---------|
| `plot_rider_distribution(summary)` | 1 | KDE + histogram + best-ever/season-best lines |
| `plot_rider_vs_field(rider_summary, field_summary)` | 2 | Field KDE (light) + rider KDE (dark overlay) |
| `plot_handicap_comparison(rider_summary, scratch_summary, handicap)` | 3 | Two KDEs + median lines + handicap annotation |

All functions return `plotly.graph_objects.Figure`. They are testable without Streamlit.

---

## 8. Streamlit App (`app.py`)

### Caching Strategy

| Decorator | Applied To | Rationale |
|-----------|-----------|-----------|
| `@st.cache_resource` | DB connection | Non-serializable; share across reruns |
| `@st.cache_data` | Query functions | Results change only on data ingestion |

### Layout

```python
# Sidebar
st.sidebar:
    season_selector
    rider_selector
    ---
    scratch_rider_selector
    compared_rider_selector

# Main area
st.header("1. Individual Rider Performance")
col_top, col_junc = st.columns(2)

st.header("2. Rider vs Field")
col_top, col_junc = st.columns(2)

st.header("3. Handicap Comparison")
col_top, col_junc = st.columns(2)
```

### Launch Command

```bash
streamlit run src/smtc_handicap/ui/app.py
```

---

## 9. Bayesian Model Integration (Future)

When the Stan model from `bayesian-model-plan.md` is implemented, the following swap points are ready:

| Current (Empirical) | Future (Bayesian) | Location |
|---------------------|-------------------|----------|
| `median(all_times)` as estimated time | Posterior mean of `alpha_j + delta_{s,j} + gamma_r` | `RiderTimeSummary.median_time` |
| `rider_median - scratch_median` as handicap | Posterior mean of `hat{y}_rider - hat{y}_scratch` | `HandicapComparison.handicap_*` |
| KDE over raw times | Posterior predictive density from `y_rep` | `plots.py` KDE computation |
| No uncertainty bands | 95% credible interval shading | New traces in plot functions |

The `queries.py` interface (`RiderTimeSummary`, `HandicapComparison`) remains stable — only the internal computation changes.

---

## 10. Testing

### Unit Tests (`test_ui_queries.py`)

- `get_season_label`: Dec 2025 -> "2025/26", Jan 2026 -> "2025/26"
- `get_rider_time_summary`: excludes falls/DNFs, applies outlier bounds, computes correct best-ever/season-best/median
- `get_field_time_summary`: aggregates across all riders correctly
- `get_rider_options`: excludes riders with zero valid finish times
- `get_handicap_comparison`: handicap = rider_median - scratch_median

Use in-memory SQLite (`:memory:`) with fixtures following the pattern in `tests/test_db.py`.

### Smoke Tests (`test_ui_plots.py`)

- Each plot function returns a valid `plotly.graph_objects.Figure`
- Empty data renders annotation instead of error
- Handicap comparison with same rider as scratch produces ~0 handicap

### Manual Verification

```bash
pip install -e ".[ui]"
streamlit run src/smtc_handicap/ui/app.py
```

Checklist:
- [ ] Rider dropdown populated with display names
- [ ] Season dropdown shows available seasons
- [ ] Section 1: TOP/JUNCTION plots render with KDE, histogram, vertical lines
- [ ] Section 1: Best-ever (green) and season-best (red) lines visible
- [ ] Section 2: Field distribution (light) with rider overlay (dark)
- [ ] Section 3: Two independent rider selectors work correctly
- [ ] Section 3: Handicap gap annotated between median lines
- [ ] Charts are interactive (hover, zoom, pan)
- [ ] Changing selections updates all charts
- [ ] Riders with no data on a course show graceful "No data" message

---

## 11. Implementation Order

| Step | Files | Description |
|------|-------|-------------|
| 1 | `pyproject.toml` | Add `[project.optional-dependencies].ui` |
| 2 | `src/smtc_handicap/ui/__init__.py` | Empty package init |
| 3 | `src/smtc_handicap/ui/queries.py` | Data query layer with all functions and dataclasses |
| 4 | `tests/test_ui_queries.py` | Unit tests for query layer |
| 5 | `src/smtc_handicap/ui/plots.py` | Plotly chart factory functions |
| 6 | `tests/test_ui_plots.py` | Smoke tests for plots |
| 7 | `src/smtc_handicap/ui/app.py` | Streamlit application wiring |
| 8 | Manual verification | Run app against real `data/cresta.db` |
