"""Handicap Planner — build a race field and optimize handicaps."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from smtc_handicap.ui.app import (
    cached_rider_options,
    cached_seasons,
    load_db,
    load_models,
)
from smtc_handicap.ui.queries import (
    get_races_for_position,
    match_riders_from_names,
)

# ---------------------------------------------------------------------------
# Shared resources
# ---------------------------------------------------------------------------

db = load_db()
models = load_models(db)

seasons = cached_seasons(db)
rider_options = cached_rider_options(db)

if not seasons or not rider_options:
    st.error("No data found. Please run the pipeline first to populate the database.")
    st.stop()

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "planner_field" not in st.session_state:
    st.session_state.planner_field = {}  # rider_id -> display_name
if "planner_results" not in st.session_state:
    st.session_state.planner_results = None  # None | "running" | "done"
if "planner_overrides" not in st.session_state:
    st.session_state.planner_overrides = {}  # rider_id -> float
if "planner_scratch" not in st.session_state:
    st.session_state.planner_scratch = ""  # rider_id
if "planner_position" not in st.session_state:
    st.session_state.planner_position = ""  # "TOP" | "JUNCTION"
if "planner_season" not in st.session_state:
    st.session_state.planner_season = 0  # season_year int
if "planner_low_data" not in st.session_state:
    st.session_state.planner_low_data = set()  # rider_ids not in model

# ---------------------------------------------------------------------------
# Branded header
# ---------------------------------------------------------------------------

st.title("Cresta Run — Handicap Planner")
st.caption("SMTC Handicap Committee Tool — Build a field and simulate handicaps")

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Handicap Planner")

    position = st.radio(
        "Start position",
        ["TOP", "JUNCTION"],
        horizontal=True,
    )

    season_labels = [s[1] for s in seasons]
    season_idx = st.selectbox(
        "Season",
        range(len(seasons)),
        format_func=lambda i: season_labels[i],
    )
    season_year = seasons[season_idx][0]

# ---------------------------------------------------------------------------
# Helper: update low-data set for the current field
# ---------------------------------------------------------------------------


def _refresh_low_data() -> None:
    """Recompute which riders in the field lack Bayesian model coverage."""
    model = models.get(position)
    low: set[str] = set()
    if model is not None:
        for rid in st.session_state.planner_field:
            if rid not in model.rider_map:
                low.add(rid)
    else:
        # No model at all — everyone is low-data
        low = set(st.session_state.planner_field.keys())
    st.session_state.planner_low_data = low


# ---------------------------------------------------------------------------
# Tabs for adding riders
# ---------------------------------------------------------------------------

tab_search, tab_upload, tab_race = st.tabs(["Search Riders", "Upload File", "Load Past Race"])

# --- Search tab ---
with tab_search:
    search_query = st.text_input(
        "Search by name",
        placeholder="Start typing a rider name...",
        key="planner_search",
    )

    if search_query and len(search_query) >= 2:
        query_lower = search_query.lower()
        matches = [(rid, name) for rid, name in rider_options if query_lower in name.lower()]

        if not matches:
            st.info("No riders match your search.")
        else:
            # Show up to 50 matches to keep UI responsive
            for rid, name in matches[:50]:
                in_field = rid in st.session_state.planner_field
                checked = st.checkbox(
                    name,
                    value=in_field,
                    key=f"search_{rid}",
                )
                if checked and not in_field:
                    st.session_state.planner_field[rid] = name
                    _refresh_low_data()
                    st.rerun()
                elif not checked and in_field:
                    del st.session_state.planner_field[rid]
                    st.session_state.planner_overrides.pop(rid, None)
                    _refresh_low_data()
                    st.rerun()

            if len(matches) > 50:
                st.caption(
                    f"Showing 50 of {len(matches)} matches. Refine your search to see more."
                )

# --- Upload tab ---
with tab_upload:
    uploaded = st.file_uploader(
        "Upload rider list (.csv or .xlsx)",
        type=["csv", "xlsx"],
        key="planner_upload",
    )

    if uploaded is not None:
        try:
            if uploaded.name.endswith(".xlsx"):
                df = pd.read_excel(uploaded)
            else:
                df = pd.read_csv(uploaded)

            # Find the name column
            name_col = None
            for candidate in ["rider_name", "name", "rider"]:
                for col in df.columns:
                    if col.strip().lower() == candidate:
                        name_col = col
                        break
                if name_col is not None:
                    break

            if name_col is None:
                st.error(
                    "Could not find a rider name column. Expected one of: rider_name, name, rider"
                )
            else:
                names = df[name_col].dropna().astype(str).tolist()
                matched, unmatched = match_riders_from_names(db, names)

                if matched:
                    for rid, dname in matched:
                        st.session_state.planner_field[rid] = dname
                    _refresh_low_data()
                    st.success(f"Added {len(matched)} rider(s) to the field.")

                if unmatched:
                    st.warning(
                        f"Could not match {len(unmatched)} name(s): " + ", ".join(unmatched)
                    )
        except Exception as exc:
            st.error(f"Error reading file: {exc}")

# --- Load Past Race tab ---
with tab_race:
    races = get_races_for_position(db, position)

    if not races:
        st.info(f"No {position} races found in the database.")
    else:
        race_ids = [r[0] for r in races]
        race_labels = [r[1] for r in races]

        race_idx = st.selectbox(
            "Select a race",
            range(len(races)),
            format_func=lambda i: race_labels[i],
            key="planner_race_select",
        )

        if st.button("Load riders from this race", key="planner_load_race"):
            selected_race_id = race_ids[race_idx]
            records = db.get_time_records_for_race(selected_race_id)
            added_ids: set[str] = set()
            for rec in records:
                rid = rec.rider_id
                if rid not in st.session_state.planner_field:
                    rider = db.get_rider(rid)
                    dname = rider.display_name if rider else rid
                    st.session_state.planner_field[rid] = dname
                    added_ids.add(rid)

            _refresh_low_data()
            if added_ids:
                st.success(f"Added {len(added_ids)} rider(s) from {race_labels[race_idx]}.")
            else:
                st.info("All riders from this race are already in the field.")

# ---------------------------------------------------------------------------
# Selected field display
# ---------------------------------------------------------------------------

st.divider()

field_dict = st.session_state.planner_field
n_riders = len(field_dict)

st.subheader(f"Selected Field \u2014 {n_riders} rider{'s' if n_riders != 1 else ''}")

if n_riders == 0:
    st.info("No riders selected yet. Use the tabs above to add riders to the field.")
else:
    low_data = st.session_state.planner_low_data

    # Display riders as removable buttons in 4 columns
    cols = st.columns(4)
    sorted_riders = sorted(field_dict.items(), key=lambda x: x[1])
    for idx, (rid, dname) in enumerate(sorted_riders):
        col = cols[idx % 4]
        prefix = "\u26a0 " if rid in low_data else ""
        with col:
            if st.button(
                f"\u274c {prefix}{dname}",
                key=f"remove_{rid}",
                use_container_width=True,
            ):
                del st.session_state.planner_field[rid]
                st.session_state.planner_overrides.pop(rid, None)
                _refresh_low_data()
                st.rerun()

    if low_data:
        st.caption(
            "\u26a0 riders are not in the Bayesian model and may need a manual handicap override."
        )

# ---------------------------------------------------------------------------
# Scratch rider selector
# ---------------------------------------------------------------------------

st.divider()

if n_riders >= 1:
    sorted_field = sorted(field_dict.items(), key=lambda x: x[1])
    scratch_ids = [r[0] for r in sorted_field]
    scratch_names = [r[1] for r in sorted_field]

    # Pre-select current scratch if still in field
    default_idx = 0
    if st.session_state.planner_scratch in scratch_ids:
        default_idx = scratch_ids.index(st.session_state.planner_scratch)

    scratch_idx = st.selectbox(
        "Scratch rider (receives no handicap)",
        range(len(scratch_ids)),
        index=default_idx,
        format_func=lambda i: scratch_names[i],
        help=(
            "The scratch rider is the reference \u2014 all other "
            "handicaps are relative to this rider."
        ),
        key="planner_scratch_select",
    )
    st.session_state.planner_scratch = scratch_ids[scratch_idx]
else:
    st.caption("Add at least one rider to select a scratch rider.")

# ---------------------------------------------------------------------------
# Run button
# ---------------------------------------------------------------------------

st.divider()

run_disabled = n_riders < 2
run_help = (
    "Need at least 2 riders in the field."
    if run_disabled
    else "Optimise handicaps for the selected field."
)

if st.button(
    "Run Handicap Simulation",
    type="primary",
    disabled=run_disabled,
    help=run_help,
    key="planner_run",
):
    st.session_state.planner_results = "running"
    st.session_state.planner_position = position
    st.session_state.planner_season = season_year
    st.rerun()
