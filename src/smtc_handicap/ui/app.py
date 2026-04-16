"""Cresta Run — SMTC Handicap Tools multi-page app entry point.

Launch with: streamlit run src/smtc_handicap/ui/app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from smtc_handicap.db import CrestaDB
from smtc_handicap.ui.queries import (
    BayesianModel,
    get_available_seasons,
    get_rider_options,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "cresta.db"
MODEL_PATHS: dict[str, Path] = {
    "TOP": PROJECT_ROOT / "data" / "model_fits" / "top.nc",
    "JUNCTION": PROJECT_ROOT / "data" / "model_fits" / "junction.nc",
}

st.set_page_config(
    page_title="Cresta Run — Handicap Tools",
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
            font-size: 0.7rem !important;
        }

        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #2C3E6B !important;
            font-weight: 600;
            font-size: 1.1rem !important;
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
def load_models(_db: CrestaDB) -> dict[str, BayesianModel | None]:
    models: dict[str, BayesianModel | None] = {}
    for position, path in MODEL_PATHS.items():
        if path.exists():
            models[position] = BayesianModel(path, _db, position)
        else:
            models[position] = None
    return models


@st.cache_data
def cached_seasons(_db: CrestaDB) -> list[tuple[int, str]]:
    return get_available_seasons(_db)


@st.cache_data
def cached_rider_options(_db: CrestaDB) -> list[tuple[str, str]]:
    return get_rider_options(_db)


st.title("Cresta Run — SMTC Handicap Tools")
st.caption("Select a tool from the sidebar navigation.")
st.markdown("""
**Explorer** — Analyze individual rider performance, compare to field, view handicaps

**Handicap Planner** — Build a race field, optimize handicaps, simulate race outcomes
""")
