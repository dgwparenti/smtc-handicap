"""Handicap Explorer — individual rider analysis page."""

from __future__ import annotations

import streamlit as st

from smtc_handicap.ui.app import (
    cached_rider_options,
    cached_seasons,
    load_db,
    load_models,
)
from smtc_handicap.ui.plots import (
    plot_handicap_comparison,
    plot_rider_performance,
    plot_rider_vs_field,
)
from smtc_handicap.ui.queries import (
    get_field_time_summary,
    get_handicap_comparison,
    get_rider_time_summary,
)

db = load_db()
models = load_models(db)

seasons = cached_seasons(db)
rider_options = cached_rider_options(db)

if not seasons or not rider_options:
    st.error("No data found. Please run the pipeline first to populate the database.")
    st.stop()

rider_ids = [r[0] for r in rider_options]
rider_names = [r[1] for r in rider_options]

# --- Branded header ---
st.title("Cresta Run — Handicap Explorer")
st.caption("SMTC Handicap Committee Tool")

# --- Sidebar ---
with st.sidebar:
    st.title("Handicap Explorer")

    all_seasons: list[tuple[int | None, str]] = [(None, "All seasons")] + seasons
    all_season_labels = [s[1] for s in all_seasons]
    season_idx = st.selectbox(
        "Season", range(len(all_seasons)), format_func=lambda i: all_season_labels[i]
    )
    season_year = all_seasons[season_idx][0]

    rider_idx = st.selectbox(
        "Rider",
        range(len(rider_options)),
        format_func=lambda i: rider_names[i],
    )
    selected_rider_id = rider_ids[rider_idx]

    st.divider()

    scratch_idx = st.selectbox(
        "Scratch Rider (reference)",
        range(len(rider_options)),
        format_func=lambda i: rider_names[i],
        key="scratch",
    )
    scratch_rider_id = rider_ids[scratch_idx]

# --- Section 1: Individual Rider Performance ---
with st.container(border=True):
    st.header("1. Individual Rider Performance")
    st.caption("How is this rider performing overall and this season?")

    col_top, col_jct = st.columns(2, gap="medium")

    for position, col in [("TOP", col_top), ("JUNCTION", col_jct)]:
        model = models.get(position)
        summary = get_rider_time_summary(db, selected_rider_id, position, season_year, model)
        fig = plot_rider_performance(summary)
        with col:
            st.plotly_chart(fig, use_container_width=True)
            mc1, mc2 = st.columns(2)
            mc1.metric(
                "All-time runs",
                f"{len(summary.all_times)}",
                help=f"Total number of {position} runs across all seasons",
            )
            mc2.metric(
                "Season runs",
                f"{len(summary.season_times)}",
                help=f"Number of {position} runs in the selected season",
            )

# --- Section 2: Rider vs Field ---
with st.container(border=True):
    st.header("2. Rider vs Field")
    st.caption("How does this rider compare to the whole field?")

    col_top2, col_jct2 = st.columns(2, gap="medium")

    for position, col in [("TOP", col_top2), ("JUNCTION", col_jct2)]:
        model = models.get(position)
        rider_summary = get_rider_time_summary(db, selected_rider_id, position, season_year, model)
        field_summary = get_field_time_summary(db, position)
        fig = plot_rider_vs_field(rider_summary, field_summary)
        with col:
            st.plotly_chart(fig, use_container_width=True)
            mc1, mc2 = st.columns(2)
            src_label = (
                f" ({rider_summary.estimated_source})" if rider_summary.estimated_source else ""
            )
            est_str = (
                f"{rider_summary.estimated_time:.1f}s{src_label}"
                if rider_summary.estimated_time
                else "N/A"
            )
            med_str = f"{field_summary.median_time:.1f}s" if field_summary.median_time else "N/A"
            mc1.metric(
                "Est. time",
                est_str,
                help="Bayesian model estimate, or median if rider not in model",
            )
            mc2.metric(
                "Field median",
                med_str,
                help=f"Median finish time across all {position} riders",
            )

# --- Section 3: Handicap Comparison ---
with st.container(border=True):
    st.header("3. Handicap Comparison")
    st.caption("How does this rider's ability differ from scratch?")

    col_top3, col_jct3 = st.columns(2, gap="medium")

    for position, col in [("TOP", col_top3), ("JUNCTION", col_jct3)]:
        model = models.get(position)
        comparison = get_handicap_comparison(
            db,
            scratch_rider_id,
            selected_rider_id,
            position,
            season_year,
            model,
        )
        fig = plot_handicap_comparison(comparison)
        with col:
            st.plotly_chart(fig, use_container_width=True)
            if comparison.handicap_value is not None:
                sign = "+" if comparison.handicap_value >= 0 else ""
                hcap_str = f"{sign}{comparison.handicap_value:.2f}s ({comparison.handicap_source})"
            else:
                hcap_str = "N/A"
            st.metric(
                "Handicap",
                hcap_str,
                help="Time difference between compared rider and scratch rider",
            )
