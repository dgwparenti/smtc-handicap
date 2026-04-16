"""Handicap Planner — build a race field and optimize handicaps."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import streamlit as st

from smtc_handicap.ui.app import (
    MODEL_PATHS,
    cached_rider_options,
    cached_seasons,
    load_db,
    load_models,
)
from smtc_handicap.ui.queries import (
    _get_valid_times,
    get_races_for_position,
    load_planner_posterior,
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

# ===========================================================================
# RESULTS STEP
# ===========================================================================

if st.session_state.planner_results is not None:
    from smtc_handicap.model.handicap_optimizer import optimize_handicaps
    from smtc_handicap.model.race_simulator import build_prediction_arrays, simulate_race

    _field = st.session_state.planner_field
    _position = st.session_state.planner_position
    _season_year = st.session_state.planner_season
    _scratch_id = st.session_state.planner_scratch
    _low_data = st.session_state.planner_low_data

    nc_path = MODEL_PATHS.get(_position)
    if nc_path is None or not nc_path.exists():
        st.error(f"No model file found for {_position}.")
        st.stop()

    # Load posterior and metadata
    posterior, metadata = load_planner_posterior(nc_path)
    rider_map = metadata["rider_map"]
    race_type_map = metadata["race_type_map"]
    season_num_arr = metadata["season_num"]

    # Find non-PRACTICE race type index (0-based)
    race_type_idx_0 = 0
    for label, idx_1 in race_type_map.items():
        if label != "PRACTICE":
            race_type_idx_0 = idx_1 - 1
            break

    # Resolve season index (0-based)
    _model = models.get(_position)
    if _model and _season_year in _model.season_lookup:
        _sn_val = _model.season_lookup[_season_year]
        season_idx_0 = int(np.argmin(np.abs(season_num_arr - _sn_val)))
    else:
        season_idx_0 = len(season_num_arr) - 1

    # Split riders into model vs low-data
    _field_sorted = sorted(_field.items(), key=lambda x: x[1])
    _model_riders = [(r, n) for r, n in _field_sorted if r in rider_map]
    _lowdata_riders = [(r, n) for r, n in _field_sorted if r not in rider_map]

    # Build prediction arrays for model riders
    _model_indices = [rider_map[r] - 1 for r, _ in _model_riders]
    mu_draws, sigma_draws = build_prediction_arrays(
        posterior, _model_indices, season_idx_0, race_type_idx_0, season_num_arr
    )

    # Append empirical estimates for low-data riders
    _n_draws = mu_draws.shape[0]
    for rid, _name in _lowdata_riders:
        times = _get_valid_times(db, rid, _position)
        emp_mu = float(np.median(times)) if times else 62.0
        pop_sigma = float(np.median(posterior["sigma_obs"]))
        mu_draws = np.column_stack([mu_draws, np.full(_n_draws, emp_mu)])
        sigma_draws = np.column_stack([sigma_draws, np.full(_n_draws, pop_sigma)])

    all_riders = _model_riders + _lowdata_riders
    all_rider_ids = [r for r, _ in all_riders]
    all_rider_names = {r: n for r, n in all_riders}

    # Find scratch index
    _scratch_idx = 0
    for i, (r, _) in enumerate(all_riders):
        if r == _scratch_id:
            _scratch_idx = i
            break

    # Initial handicaps from expected times
    _mean_mu = mu_draws.mean(axis=0)
    _init_hcap = np.maximum(0.0, _mean_mu - _mean_mu[_scratch_idx])
    _init_hcap[_scratch_idx] = 0.0

    # Frozen indices for low-data riders
    _frozen = {i for i, (r, _) in enumerate(all_riders) if r in _low_data}

    # --- Run optimization ---
    if st.session_state.planner_results == "running":
        with st.spinner("Optimizing handicaps..."):
            _opt = optimize_handicaps(
                mu_draws,
                sigma_draws,
                _init_hcap,
                scratch_idx=_scratch_idx,
                frozen_indices=_frozen,
                seed=42,
            )
        st.session_state.planner_opt = _opt
        st.session_state.planner_mu = mu_draws
        st.session_state.planner_sigma = sigma_draws
        st.session_state.planner_all_riders = all_riders
        st.session_state.planner_results = "done"
        st.rerun()

    # --- Display results ---
    if st.session_state.planner_results == "done":
        opt_result = st.session_state.planner_opt
        all_riders = st.session_state.planner_all_riders
        all_rider_names = {r: n for r, n in all_riders}
        mu_draws = st.session_state.planner_mu
        sigma_draws = st.session_state.planner_sigma

        st.divider()
        st.header("Simulation Results")

        # Summary banner
        m1, m2, m3 = st.columns(3)
        m1.metric("Top-6 Spread", f"{opt_result.final_spread:.1f}s")
        m2.metric("Simulated Races", f"{opt_result.simulation.n_draws:,}")
        m3.metric(
            "Optimization",
            f"{opt_result.n_iterations} evals",
            delta=f"{opt_result.initial_spread:.1f}s → {opt_result.final_spread:.1f}s",
        )

        # --- Handicap Assignments ---
        st.subheader("Handicap Assignments")
        st.caption("Enter override values to adjust. Leave empty to use model suggestion.")

        overrides = st.session_state.planner_overrides
        hcap_rows = []
        for i, (rid, name) in enumerate(all_riders):
            is_low = rid in _low_data
            recs = db.get_time_records_for_rider(rid, _position)
            n_runs_db = sum(1 for r in recs if r.finish_time is not None)
            model_hcap = None if is_low else round(float(opt_result.handicaps[i]), 2)
            exp_time = round(float(mu_draws.mean(axis=0)[i]), 1)
            sigma_val = round(float(sigma_draws.mean(axis=0)[i]), 2) if not is_low else None

            if is_low or n_runs_db < 10:
                conf = "LOW"
            elif n_runs_db >= 20:
                conf = "HIGH"
            else:
                conf = "MEDIUM"

            hcap_rows.append(
                {
                    "rider_id": rid,
                    "name": name,
                    "runs": n_runs_db,
                    "confidence": conf,
                    "exp_time": exp_time,
                    "sigma": sigma_val,
                    "model_hcap": model_hcap,
                    "idx": i,
                    "is_low": is_low,
                }
            )

        # Render table header
        hdr = st.columns([3, 1, 1, 1, 1, 1, 1.5, 1])
        hdr[0].markdown("**Rider**")
        hdr[1].markdown("**Runs**")
        hdr[2].markdown("**Conf.**")
        hdr[3].markdown("**Exp. Time**")
        hdr[4].markdown("**σ**")
        hdr[5].markdown("**Model**")
        hdr[6].markdown("**Override**")
        hdr[7].markdown("**Active**")

        for row in hcap_rows:
            c = st.columns([3, 1, 1, 1, 1, 1, 1.5, 1])
            c[0].write(row["name"])
            c[1].write(str(row["runs"]))
            c[2].write(row["confidence"])
            c[3].write(f"{'~' if row['is_low'] else ''}{row['exp_time']}s")
            c[4].write(f"{row['sigma']}s" if row["sigma"] else "—")
            c[5].write(f"{row['model_hcap']}s" if row["model_hcap"] is not None else "n/a")

            rid = row["rider_id"]
            prev_val = overrides.get(rid)
            ov = c[6].number_input(
                "ov",
                min_value=0.0,
                value=prev_val if prev_val is not None else None,
                step=0.1,
                format="%.1f",
                key=f"ov_{rid}",
                label_visibility="collapsed",
            )
            if ov is not None and ov > 0:
                overrides[rid] = ov
            elif ov is None or ov == 0:
                overrides.pop(rid, None)

            active_val = overrides.get(rid, row["model_hcap"])
            c[7].write(f"**{active_val}s**" if active_val is not None else "—")

        st.session_state.planner_overrides = overrides

        # Re-simulate button
        if st.button("Re-simulate with overrides", key="planner_resim"):
            active_hcaps = opt_result.handicaps.copy()
            for i, (rid, _) in enumerate(all_riders):
                if rid in overrides and overrides[rid] is not None:
                    active_hcaps[i] = overrides[rid]
            resim = simulate_race(mu_draws, sigma_draws, active_hcaps, seed=42)
            st.session_state.planner_opt = type(opt_result)(
                handicaps=active_hcaps,
                simulation=resim,
                n_iterations=opt_result.n_iterations,
                initial_spread=opt_result.initial_spread,
                final_spread=resim.top_k_spread,
            )
            st.rerun()

        # --- Expected Race Results ---
        st.subheader("Expected Race Results")
        st.caption(
            f"Based on {opt_result.simulation.n_draws:,} simulated races "
            "(3 runs each). Rank range shows 5th–95th percentile."
        )

        sim = opt_result.simulation
        res_rows = []
        for i, (rid, name) in enumerate(all_riders):
            stats = sim.rider_stats[i]
            flag = ""
            if rid in overrides and overrides.get(rid) is not None:
                flag = " ✎"
            elif rid in _low_data:
                flag = " ⚠"

            res_rows.append(
                {
                    "_sort": stats.median_rank,
                    "Exp. Rank": int(round(stats.median_rank)),
                    "Rider": f"{name}{flag}",
                    "Exp. Gross (3 runs)": f"{stats.median_gross:.1f}s",
                    "Handicap (×3)": f"{3 * float(opt_result.handicaps[i]):.1f}s",
                    "Exp. Net (3 runs)": f"{stats.median_net:.1f}s",
                    "Rank Range": f"{stats.rank_lo}–{stats.rank_hi}",
                    "Win %": f"{stats.win_pct:.0f}%",
                }
            )

        res_df = pd.DataFrame(res_rows).sort_values("_sort")
        show_cols = [
            "Exp. Rank",
            "Rider",
            "Exp. Gross (3 runs)",
            "Handicap (×3)",
            "Exp. Net (3 runs)",
            "Rank Range",
            "Win %",
        ]
        st.dataframe(res_df[show_cols], use_container_width=True, hide_index=True)

        # ==================================================================
        # EXPORT
        # ==================================================================
        st.divider()
        st.subheader("Export")

        ex1, ex2 = st.columns(2)

        # --- Excel ---
        with ex1:
            hcap_export = pd.DataFrame(
                [
                    {
                        "Rider": r["name"],
                        "Runs": r["runs"],
                        "Confidence": r["confidence"],
                        "Exp. Time": f"{'~' if r['is_low'] else ''}{r['exp_time']}s",
                        "σ Rider": f"{r['sigma']}s" if r["sigma"] else "—",
                        "Model Handicap": (
                            f"{r['model_hcap']}s" if r["model_hcap"] is not None else "n/a"
                        ),
                        "Override": (
                            f"{overrides[r['rider_id']]}s"
                            if r["rider_id"] in overrides and overrides[r["rider_id"]]
                            else ""
                        ),
                        "Active Handicap": (
                            f"{overrides.get(r['rider_id'], r['model_hcap'])}s"
                            if overrides.get(r["rider_id"], r["model_hcap"]) is not None
                            else "—"
                        ),
                    }
                    for r in hcap_rows
                ]
            )

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                hcap_export.to_excel(writer, sheet_name="Handicaps", index=False)
                res_df[show_cols].to_excel(writer, sheet_name="Race Simulation", index=False)
            buf.seek(0)

            st.download_button(
                "Download Excel",
                data=buf,
                file_name=f"handicap_planner_{_position}_{_season_year}.xlsx",
                mime=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            )

        # --- PDF ---
        with ex2:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(
                0,
                10,
                f"Handicap Planner — {_position}",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(
                0,
                8,
                (
                    f"Season: {_season_year}  |  "
                    f"Top-6 Spread: {opt_result.final_spread:.1f}s  |  "
                    f"Draws: {opt_result.simulation.n_draws}"
                ),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.ln(5)

            # Handicap table
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 8, "Handicap Assignments", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "B", 8)
            hw = [40, 12, 16, 22, 22, 25, 25]
            hh = ["Rider", "Runs", "Conf.", "Exp.Time", "Model", "Override", "Active"]
            for w, h in zip(hw, hh, strict=False):
                pdf.cell(w, 6, h, border=1)
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            for r in hcap_rows:
                rid = r["rider_id"]
                active = overrides.get(rid, r["model_hcap"])
                ov_str = f"{overrides[rid]}s" if rid in overrides and overrides[rid] else ""
                act_str = f"{active}s" if active is not None else "—"
                vals = [
                    r["name"][:22],
                    str(r["runs"]),
                    r["confidence"],
                    f"{'~' if r['is_low'] else ''}{r['exp_time']}s",
                    f"{r['model_hcap']}s" if r["model_hcap"] is not None else "n/a",
                    ov_str,
                    act_str,
                ]
                for w, v in zip(hw, vals, strict=False):
                    pdf.cell(w, 6, v, border=1)
                pdf.ln()

            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(
                0,
                8,
                "Expected Race Results",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_font("Helvetica", "B", 8)
            rw = [12, 38, 28, 22, 28, 22, 18]
            rh = ["Rank", "Rider", "Gross(3r)", "Hcap(x3)", "Net(3r)", "Range", "Win%"]
            for w, h in zip(rw, rh, strict=False):
                pdf.cell(w, 6, h, border=1)
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            for _, rr in res_df.sort_values("_sort").iterrows():
                vals = [
                    str(rr["Exp. Rank"]),
                    str(rr["Rider"])[:20],
                    rr["Exp. Gross (3 runs)"],
                    rr["Handicap (×3)"],
                    rr["Exp. Net (3 runs)"],
                    rr["Rank Range"],
                    rr["Win %"],
                ]
                for w, v in zip(rw, vals, strict=False):
                    pdf.cell(w, 6, v, border=1)
                pdf.ln()

            pdf_out = pdf.output()
            st.download_button(
                "Download PDF",
                data=bytes(pdf_out),
                file_name=f"handicap_planner_{_position}_{_season_year}.pdf",
                mime="application/pdf",
            )
