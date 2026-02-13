# Handicap Explorer — Visual Design Specification

## Overview

A single-page Streamlit dashboard for the SMTC handicap committee to explore rider performance and handicap data from the Cresta Run. The page has a **left sidebar** for controls and a **main content area** with three vertically stacked sections, each containing two side-by-side charts (TOP and JUNCTION).

---

## Page Layout

```
┌──────────┬──────────────────────────────────────────────────────┐
│          │                                                      │
│ SIDEBAR  │  MAIN CONTENT AREA                                   │
│ (280px)  │                                                      │
│          │  ┌─────────────────────────────────────────────────┐  │
│ Season   │  │ Section 1: Individual Rider Performance         │  │
│ selector │  │  ┌──────────────┐  ┌──────────────┐            │  │
│          │  │  │  TOP chart   │  │ JUNCTION     │            │  │
│ Rider    │  │  │              │  │ chart        │            │  │
│ selector │  │  └──────────────┘  └──────────────┘            │  │
│          │  │  Runs: 42 (season: 12)  Runs: 28 (season: 8)   │  │
│ ──────── │  └─────────────────────────────────────────────────┘  │
│          │                                                      │
│ Scratch  │  ┌─────────────────────────────────────────────────┐  │
│ rider    │  │ Section 2: Rider vs Field                       │  │
│ selector │  │  ┌──────────────┐  ┌──────────────┐            │  │
│          │  │  │  TOP chart   │  │ JUNCTION     │            │  │
│ Compared │  │  │              │  │ chart        │            │  │
│ rider    │  │  └──────────────┘  └──────────────┘            │  │
│ selector │  └─────────────────────────────────────────────────┘  │
│          │                                                      │
│          │  ┌─────────────────────────────────────────────────┐  │
│          │  │ Section 3: Handicap Comparison                  │  │
│          │  │  ┌──────────────┐  ┌──────────────┐            │  │
│          │  │  │  TOP chart   │  │ JUNCTION     │            │  │
│          │  │  │              │  │ chart        │            │  │
│          │  │  └──────────────┘  └──────────────┘            │  │
│          │  │  H'cap: 3.20s (Bayesian)  H'cap: 2.80s        │  │
│          │  └─────────────────────────────────────────────────┘  │
│          │                                                      │
└──────────┴──────────────────────────────────────────────────────┘
```

**Page title**: "Cresta Run — Handicap Explorer"
**Background**: Streamlit default white (`#FFFFFF`)
**Font**: Streamlit default (Source Sans Pro)

---

## Sidebar

**Width**: ~280px (Streamlit default)
**Background**: Streamlit default light grey sidebar (`#F0F2F6`)

### Controls (top to bottom)

1. **Season selector** — dropdown
   - Label: "Season"
   - Options: e.g. `["2025/26", "2024/25", "2023/24", ...]` sorted most recent first
   - Default: most recent season
   - Affects all three sections (season-specific overlays and stats)

2. **Rider selector** — dropdown with search/type-ahead
   - Label: "Rider"
   - Options: all riders with at least one valid finish time, sorted alphabetically by display name
   - Display format: `"F.P. Rueda (Jnr)"` (the `display_name` field)
   - Affects Sections 1 and 2

3. **Horizontal divider line** — visual separator

4. **Scratch Rider selector** — dropdown with search/type-ahead
   - Label: "Scratch Rider (reference)"
   - Same rider list as above
   - Affects Section 3 only

5. **Compared Rider selector** — dropdown with search/type-ahead
   - Label: "Compared Rider"
   - Same rider list as above
   - Affects Section 3 only
   - Default: same as the Rider selector above (so Section 3 initially shows the same rider vs scratch)

---

## Color Palette

| Element | Color | Hex | Usage |
|---------|-------|-----|-------|
| Rider distribution (all-time) | Blue | `#1f77b4` | Filled area, solid border |
| Rider distribution (season) | Blue dashed | `#1f77b4` | Dashed line, no fill |
| Field distribution | Light blue | `#aec7e8` | Filled area, lighter tone |
| Scratch rider distribution | Orange | `#ff7f0e` | Filled area, solid border |
| Best-ever line | Green | `#2ca02c` | Solid vertical line |
| Season-best line | Red | `#d62728` | Dashed vertical line |
| Estimated time line (rider) | Blue | `#1f77b4` | Solid vertical line |
| Estimated time line (field) | Grey | `#7f7f7f` | Dashed vertical line |
| Estimated time line (scratch) | Orange | `#ff7f0e` | Solid vertical line |

All filled areas use `opacity=0.3` so overlapping distributions are visible. Outline/border strokes use `opacity=1.0` with `width=2`.

---

## Chart Style (applies to all charts)

- **Library**: Plotly (interactive — hover, zoom, pan)
- **Chart height**: 350px
- **Chart width**: fills column (responsive, ~50% of main area each)
- **Background**: white
- **Grid**: light grey horizontal gridlines only, no vertical gridlines
- **X-axis label**: "Finish Time (seconds)"
- **Y-axis label**: "Number of Runs"
- **Title**: positioned top-left inside the chart area, e.g. "TOP" or "JUNCTION"
- **Legend**: positioned top-right inside the chart, compact
- **Margins**: minimal (Plotly `margin=dict(l=50, r=20, t=40, b=50)`)
- **Hover**: show time value on hover over curves

### Curve rendering — "Smoothed Histogram"

All distributions are shown as **smooth filled curves** (not bar charts, not raw KDE density).

How they're computed:
1. Take the raw finish times and compute a histogram (`np.histogram` with automatic bin selection)
2. Take the bin midpoints and counts
3. Fit a smooth spline through the midpoints (cubic interpolation)
4. Evaluate on a fine 200-point grid
5. Draw as a filled area chart (`fill='tozeroy'`)

This gives a smooth bell-curve shape where the **y-axis represents counts** (number of runs per bin), which is more intuitive for the committee than a density value.

**Minimum data threshold**: If fewer than 2 data points, show individual times as **circular markers** (dots) along the x-axis at y=0 instead of a curve.

---

## Section 1: Individual Rider Performance

**Header**: `"1. Individual Rider Performance"` — Streamlit `st.header`
**Subheader text**: `"How is this rider performing overall and this season?"`
**Layout**: two equal-width columns (TOP left, JUNCTION right)

### Each chart contains

```
         Number of Runs
         ▲
         │
         │      ╱‾‾‾╲          ← all-time curve (solid blue fill)
         │    ╱╱     ╲╲
         │   ╱  ╱‾╲    ╲       ← season curve (dashed blue line, no fill)
         │  ╱  ╱   ╲    ╲
         │ ╱  ╱     ╲    ╲
         │╱__╱_______╲____╲___
         ├──┼────────┼────────► Finish Time (s)
            │g       │r
            │        │
      best-ever   season-best
      (green)     (red dashed)
```

| Layer | Style | Legend label |
|-------|-------|-------------|
| All-time distribution | Filled area, solid blue `#1f77b4`, `opacity=0.3`, solid border `width=2` | "All time ({N} runs)" |
| Season distribution | Dashed blue line `#1f77b4`, `dash='dash'`, `width=2`, **no fill** | "{season} ({N} runs)" |
| Best-ever vertical line | Solid green `#2ca02c`, `width=2` | "Best ever: {time}s" |
| Season-best vertical line | Dashed red `#d62728`, `dash='dash'`, `width=2` | "Season best: {time}s" |

### Metric cards below each chart

Displayed as Streamlit `st.metric` components:
- **Total runs**: e.g. "42 runs (all time)"
- **Season runs**: e.g. "12 runs (2025/26)"

### Empty state

If the rider has no valid times for a course (TOP or JUNCTION):
- Chart area shows a centered text annotation: "No data available for {rider_name} on {course}"
- Grey italic text, no axes

---

## Section 2: Rider vs Field

**Header**: `"2. Rider vs Field"`
**Subheader text**: `"How does this rider compare to the whole field?"`
**Layout**: two equal-width columns (TOP left, JUNCTION right)

### Each chart contains

```
         Number of Runs
         ▲
         │
         │  ╱‾‾‾‾‾‾‾‾‾‾‾╲      ← field curve (light blue fill)
         │╱╱              ╲╲
         │   ╱‾‾‾╲          ╲   ← rider curve (darker blue fill overlay)
         │  ╱     ╲          ╲
         │ ╱       ╲          ╲
         │╱_________╲__________╲
         ├──────┼────┼─────────► Finish Time (s)
                │b   │g
                │    │
           rider     field
           est.time  median
           (blue)    (grey dashed)
```

| Layer | Style | Legend label |
|-------|-------|-------------|
| Field distribution | Filled area, light blue `#aec7e8`, `opacity=0.3`, solid border `width=1.5` | "All riders ({N} riders, {M} runs)" |
| Rider distribution | Filled area, blue `#1f77b4`, `opacity=0.35`, solid border `width=2` | "{rider_name} ({N} runs)" |
| Rider estimated time line | Solid blue `#1f77b4`, `width=2` | "Est. time: {time}s" |
| Field median line | Dashed grey `#7f7f7f`, `dash='dash'`, `width=2` | "Field median: {time}s" |

The rider's estimated time comes from the **Bayesian model** when available (posterior mean of ability at current season). If the rider is not in the model, fall back to median with label "(empirical)".

The field distribution is much wider/larger than the rider distribution (thousands of runs vs tens), so the y-axis scales will differ. The rider curve will appear as a smaller overlay on top of the field curve. Both curves share the same x-axis (finish time).

---

## Section 3: Handicap Comparison

**Header**: `"3. Handicap Comparison"`
**Subheader text**: `"How does the compared rider's ability differ from scratch?"`
**Layout**: two equal-width columns (TOP left, JUNCTION right)

### Each chart contains

```
         Number of Runs
         ▲
         │
         │  ╱‾╲        ╱‾╲
         │ ╱   ╲      ╱   ╲     ← scratch (orange fill) + rider (blue fill)
         │╱     ╲    ╱     ╲
         │       ╲  ╱       ╲
         │________╲╱_________╲___
         ├────┼──────────┼──────► Finish Time (s)
              │o         │b
              │          │
              │←─ 3.2s ──│      ← handicap annotation arrow
              │          │
         scratch est.  rider est.
         (orange)      (blue)
```

| Layer | Style | Legend label |
|-------|-------|-------------|
| Scratch distribution | Filled area, orange `#ff7f0e`, `opacity=0.3`, solid border `width=2` | "{scratch_name} ({N} runs)" |
| Compared rider distribution | Filled area, blue `#1f77b4`, `opacity=0.35`, solid border `width=2` | "{rider_name} ({N} runs)" |
| Scratch estimated time line | Solid orange `#ff7f0e`, `width=2` | "Est: {time}s" |
| Rider estimated time line | Solid blue `#1f77b4`, `width=2` | "Est: {time}s" |
| Handicap annotation | Double-headed arrow between the two vertical lines, with text label above | — |

### Handicap annotation detail

- A **horizontal double-headed arrow** connects the two estimated-time vertical lines
- Above the arrow, centered: bold text showing the handicap value, e.g. **"+3.20s"**
- Below the arrow: source label in smaller text — *"(Bayesian)"* or *"(empirical)"* if the rider/scratch is not in the model
- Positive handicap = rider is slower than scratch (needs time added)
- If handicap is exactly 0 (same rider selected as both scratch and compared): show "0.00s" with no arrow

### Metric cards below each chart

Displayed as Streamlit `st.metric`:
- **"Handicap (TOP)"**: e.g. "+3.20s (Bayesian)" — green delta styling if the value is small (rider is close to scratch), red if large
- **"Handicap (JUNCTION)"**: same format

### Empty state

If either the scratch or compared rider has no valid times for a course:
- Show annotation: "Insufficient data to compute handicap on {course}"

---

## Interactions

All charts are **Plotly interactive**:
- **Hover**: tooltip showing exact finish time and count value at cursor position
- **Zoom**: click-drag to zoom into a region of the chart
- **Pan**: shift-click-drag to pan
- **Reset**: double-click to reset view
- **Plotly toolbar**: shown on hover in top-right of each chart (zoom, pan, reset, download PNG)

**Selector changes**: when any sidebar dropdown changes, all affected sections re-render immediately (Streamlit reactivity).

---

## Responsive Behavior

- On wide screens (>1200px): two charts side by side per section, comfortable spacing
- On narrow screens (<768px): Streamlit columns stack vertically — TOP chart on top, JUNCTION chart below
- Sidebar collapses to hamburger menu on mobile (Streamlit default)

---

## Typography and Spacing

| Element | Style |
|---------|-------|
| Page title | `st.title` — large bold, ~30px |
| Section headers | `st.header` — bold, ~24px |
| Section subheaders | `st.caption` — small grey italic, ~14px |
| Metric labels | `st.metric` — Streamlit default styling |
| Chart titles | Plotly title, 16px bold |
| Chart axis labels | Plotly default, 12px |
| Legend text | Plotly default, 11px |
| Handicap annotation | 14px bold for value, 11px italic for source label |

**Vertical spacing between sections**: Streamlit default `st.header` spacing + a `st.divider()` line between each section.

---

## Summary of Visual Principles

1. **Smooth curves, not bars** — all distributions rendered as smooth filled area curves (smoothed histograms), giving a clean bell-curve appearance
2. **Y-axis = counts** — more intuitive for the committee than density values
3. **Consistent color language** — blue = selected rider, light blue = field, orange = scratch, green = best-ever, red = season-best
4. **Overlay not side-by-side** — rider vs field and rider vs scratch are overlaid on the same axes for direct visual comparison
5. **Bayesian-first** — estimated times come from the fitted model when available, with clear labeling of the source
6. **Interactive** — hover for details, zoom to explore, export charts as PNG
