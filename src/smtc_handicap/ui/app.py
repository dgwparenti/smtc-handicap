"""Handicap Explorer — Streamlit dashboard for the SMTC handicap committee.

Launch with: streamlit run src/smtc_handicap/ui/app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from smtc_handicap.db import CrestaDB
from smtc_handicap.ui.plots import (
    plot_handicap_comparison,
    plot_rider_performance,
    plot_rider_vs_field,
)
from smtc_handicap.ui.queries import (
    BayesianModel,
    get_available_seasons,
    get_field_time_summary,
    get_handicap_comparison,
    get_rider_options,
    get_rider_time_summary,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"
NC_PATH = PROJECT_ROOT / "data" / "model_fits" / "top.nc"

st.set_page_config(
    page_title="Cresta Run — Handicap Explorer",
    layout="wide",
)


def _inject_custom_css() -> None:
    """Inject custom CSS for SMTC branded styling."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* Root typography */
        html, body, [class*="stApp"] {
            font-family: 'Inter', 'Source Sans Pro', sans-serif;
        }

        /* Headings */
        h1 {
            color: #2C3E6B !important;
            letter-spacing: -0.02em;
            padding-bottom: 0.45rem !important;
            border-bottom: 3px solid #1f77b4;
            margin-bottom: 1rem !important;
        }

        h2 {
            color: #2C3E6B !important;
            font-weight: 600 !important;
            letter-spacing: -0.01em;
        }

        h3 {
            color: #3D4F7C !important;
            font-weight: 600 !important;
        }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #F8F9FB 0%, #EEF1F6 100%) !important;
            border-right: 1px solid rgba(44, 62, 107, 0.08);
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            font-size: 0.92rem;
        }

        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stSelectbox label {
            font-variant: all-small-caps;
            letter-spacing: 0.06em;
            font-weight: 600;
            color: #4A5568 !important;
            font-size: 0.85rem !important;
        }

        /* Metric cards */
        [data-testid="stMetric"] {
            background: #FAFBFD;
            border: 1px solid rgba(0, 0, 0, 0.06);
            border-radius: 8px;
            padding: 0.75rem 1rem;
            box-shadow: 0 1px 3px rgba(44, 62, 107, 0.04);
        }

        [data-testid="stMetric"] label {
            color: #6B7280 !important;
            font-weight: 500;
        }

        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #2C3E6B !important;
            font-weight: 600;
        }

        /* Captions */
        .stCaption, [data-testid="stCaptionContainer"] {
            color: #6B7280 !important;
            font-size: 0.9rem !important;
        }

        /* Bordered containers */
        [data-testid="stContainer"] {
            border-color: rgba(44, 62, 107, 0.08) !important;
            border-radius: 10px !important;
        }

        /* Selectbox refinement */
        [data-testid="stSelectbox"] > div > div {
            border-color: rgba(44, 62, 107, 0.12) !important;
            border-radius: 6px;
        }

        /* Hide chrome */
        #MainMenu, footer, header[data-testid="stHeader"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


_inject_custom_css()


@st.cache_resource
def load_db() -> CrestaDB:
    return CrestaDB(DB_PATH)


@st.cache_resource
def load_model(_db: CrestaDB) -> BayesianModel | None:
    if NC_PATH.exists():
        return BayesianModel(NC_PATH, _db)
    return None


@st.cache_data
def cached_seasons(_db: CrestaDB) -> list[tuple[int, str]]:
    return get_available_seasons(_db)


@st.cache_data
def cached_rider_options(_db: CrestaDB) -> list[tuple[str, str]]:
    return get_rider_options(_db)


def main() -> None:
    db = load_db()
    model = load_model(db)

    seasons = cached_seasons(db)
    rider_options = cached_rider_options(db)

    if not seasons or not rider_options:
        st.error("No data found. Please run the pipeline first to populate the database.")
        return

    rider_ids = [r[0] for r in rider_options]
    rider_names = [r[1] for r in rider_options]

    # --- Branded header ---
    st.title("Cresta Run — Handicap Explorer")
    st.caption("SMTC Handicap Committee Tool")

    # --- Sidebar ---
    with st.sidebar:
        st.title("Handicap Explorer")

        season_labels = [s[1] for s in seasons]
        season_idx = st.selectbox(
            "Season", range(len(seasons)), format_func=lambda i: season_labels[i]
        )
        season_year = seasons[season_idx][0]

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

        compared_idx = st.selectbox(
            "Compared Rider",
            range(len(rider_options)),
            format_func=lambda i: rider_names[i],
            index=rider_idx,
            key="compared",
        )
        compared_rider_id = rider_ids[compared_idx]

    # --- Section 1: Individual Rider Performance ---
    with st.container(border=True):
        st.header("1. Individual Rider Performance")
        st.caption("How is this rider performing overall and this season?")

        col_top, col_jct = st.columns(2, gap="medium")

        for position, col in [("TOP", col_top), ("JUNCTION", col_jct)]:
            summary = get_rider_time_summary(db, selected_rider_id, position, season_year, model)
            fig = plot_rider_performance(summary)
            with col:
                st.plotly_chart(fig, use_container_width=True)
                mc1, mc2 = st.columns(2)
                mc1.metric(
                    f"Total runs ({position})",
                    f"{len(summary.all_times)} (all time)",
                    help=f"Total number of {position} runs across all seasons",
                )
                mc2.metric(
                    f"Season runs ({position})",
                    f"{len(summary.season_times)} ({seasons[season_idx][1]})",
                    help=f"Number of {position} runs in the selected season",
                )

    # --- Section 2: Rider vs Field ---
    with st.container(border=True):
        st.header("2. Rider vs Field")
        st.caption("How does this rider compare to the whole field?")

        col_top2, col_jct2 = st.columns(2, gap="medium")

        for position, col in [("TOP", col_top2), ("JUNCTION", col_jct2)]:
            rider_summary = get_rider_time_summary(
                db, selected_rider_id, position, season_year, model
            )
            field_summary = get_field_time_summary(db, position)
            fig = plot_rider_vs_field(rider_summary, field_summary)
            with col:
                st.plotly_chart(fig, use_container_width=True)
                mc1, mc2 = st.columns(2)
                src_label = (
                    f" ({rider_summary.estimated_source})"
                    if rider_summary.estimated_source
                    else ""
                )
                est_str = (
                    f"{rider_summary.estimated_time:.1f}s{src_label}"
                    if rider_summary.estimated_time
                    else "N/A"
                )
                med_str = (
                    f"{field_summary.median_time:.1f}s" if field_summary.median_time else "N/A"
                )
                mc1.metric(
                    f"Estimated time ({position})",
                    est_str,
                    help="Bayesian model estimate, or median if rider not in model",
                )
                mc2.metric(
                    f"Field median ({position})",
                    med_str,
                    help=f"Median finish time across all {position} riders",
                )

    # --- Section 3: Handicap Comparison ---
    with st.container(border=True):
        st.header("3. Handicap Comparison")
        st.caption("How does the compared rider's ability differ from scratch?")

        col_top3, col_jct3 = st.columns(2, gap="medium")

        for position, col in [("TOP", col_top3), ("JUNCTION", col_jct3)]:
            comparison = get_handicap_comparison(
                db,
                scratch_rider_id,
                compared_rider_id,
                position,
                season_year,
                model,
            )
            fig = plot_handicap_comparison(comparison)
            with col:
                st.plotly_chart(fig, use_container_width=True)
                if comparison.handicap_value is not None:
                    sign = "+" if comparison.handicap_value >= 0 else ""
                    hcap_str = (
                        f"{sign}{comparison.handicap_value:.2f}s ({comparison.handicap_source})"
                    )
                else:
                    hcap_str = "N/A"
                st.metric(
                    f"Handicap ({position})",
                    hcap_str,
                    help="Time difference between compared rider and scratch rider",
                )


if __name__ == "__main__":
    main()
