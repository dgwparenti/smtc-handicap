"""Chart layer for the Handicap Explorer UI.

All plot functions return a plotly.graph_objects.Figure. Distributions are
rendered as smoothed histogram curves (spline-interpolated bin counts).
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from scipy.interpolate import make_interp_spline

from smtc_handicap.ui.queries import (
    FieldTimeSummary,
    HandicapComparison,
    RiderTimeSummary,
)

# Colors (from design spec)
BLUE = "#1f77b4"
LIGHT_BLUE = "#aec7e8"
ORANGE = "#ff7f0e"
GREEN = "#2ca02c"
RED = "#d62728"
GREY = "#7f7f7f"

# Typography & styling constants
FONT_FAMILY = "Inter, Source Sans Pro, sans-serif"
TITLE_COLOR = "#2C3E6B"
AXIS_COLOR = "#4A5568"
GRID_COLOR = "rgba(0,0,0,0.06)"
AXIS_LINE_COLOR = "#CBD5E0"

CHART_HEIGHT = 350
CHART_MARGIN = dict(l=50, r=20, t=40, b=50)


def _smoothed_histogram(times: list[float]) -> tuple[np.ndarray, np.ndarray] | None:
    """Compute a smoothed histogram curve from a list of times.

    Returns (x_grid, y_smooth) or None if fewer than 2 points.
    """
    if len(times) < 2:
        return None
    arr = np.array(times)
    counts, bin_edges = np.histogram(arr, bins="auto")
    midpoints = (bin_edges[:-1] + bin_edges[1:]) / 2

    if len(midpoints) < 2:
        return None

    # Use cubic spline if enough points, else linear
    k = min(3, len(midpoints) - 1)
    x_grid = np.linspace(midpoints[0], midpoints[-1], 200)
    spline = make_interp_spline(midpoints, counts.astype(float), k=k)
    y_smooth = spline(x_grid)
    y_smooth = np.maximum(y_smooth, 0)  # clamp negatives
    return x_grid, y_smooth


def _base_layout(title: str) -> dict:
    """Return common Plotly layout kwargs."""
    return dict(
        title=dict(
            text=title,
            x=0.02,
            y=0.95,
            font=dict(size=16, color=TITLE_COLOR, family=FONT_FAMILY, weight="bold"),
        ),
        font=dict(family=FONT_FAMILY, color=AXIS_COLOR),
        height=CHART_HEIGHT,
        margin=CHART_MARGIN,
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(
            title=dict(text="Finish Time (seconds)", font=dict(size=12, color=AXIS_COLOR)),
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=AXIS_LINE_COLOR,
            linewidth=1,
            tickfont=dict(size=11, color=AXIS_COLOR),
        ),
        yaxis=dict(
            title=dict(text="Number of Runs", font=dict(size=12, color=AXIS_COLOR)),
            showgrid=True,
            gridcolor=GRID_COLOR,
            gridwidth=0.5,
            zeroline=False,
            showline=False,
            tickfont=dict(size=11, color=AXIS_COLOR),
        ),
        legend=dict(
            orientation="h",
            x=0.5,
            y=-0.12,
            xanchor="center",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.95)",
            bordercolor="rgba(0,0,0,0.08)",
            borderwidth=1,
            font=dict(size=10, family=FONT_FAMILY),
        ),
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="rgba(0,0,0,0.15)",
            font=dict(size=12, family=FONT_FAMILY, color="#1A1A2E"),
        ),
    )


def _empty_figure(message: str, title: str) -> go.Figure:
    """Return a figure with centered grey text and no axes."""
    fig = go.Figure()
    layout = _base_layout(title)
    layout["xaxis"] = dict(visible=False)
    layout["yaxis"] = dict(visible=False)
    layout["annotations"] = [
        dict(
            text=message,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color="grey", family=FONT_FAMILY),
        )
    ]
    fig.update_layout(**layout)
    return fig


def _add_vline(fig: go.Figure, x: float, color: str, dash: str | None, label: str) -> None:
    """Add a vertical reference line with a legend entry."""
    fig.add_trace(
        go.Scatter(
            x=[x, x],
            y=[0, 0],
            mode="lines",
            line=dict(color=color, width=2, dash=dash),
            name=label,
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_vline(
        x=x,
        line=dict(color=color, width=2, dash=dash or "solid"),
        opacity=0.8,
    )


def _distribution_hovertemplate() -> str:
    """Hover template for smoothed distribution curves."""
    return "<b>%{x:.1f}s</b><br>~%{y:.0f} runs<extra></extra>"


def plot_rider_performance(summary: RiderTimeSummary) -> go.Figure:
    """Section 1: Individual rider all-time + season overlay."""
    title = summary.position

    if not summary.all_times:
        return _empty_figure(
            f"No data available for {summary.display_name} on {summary.position}",
            title,
        )

    fig = go.Figure()

    # All-time distribution
    curve = _smoothed_histogram(summary.all_times)
    if curve is not None:
        x, y = curve
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                fill="tozeroy",
                fillcolor="rgba(31,119,180,0.3)",
                line=dict(color=BLUE, width=2),
                name=f"All time ({len(summary.all_times)} runs)",
                hovertemplate=_distribution_hovertemplate(),
            )
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=summary.all_times,
                y=[0] * len(summary.all_times),
                mode="markers",
                marker=dict(color=BLUE, size=8),
                name=f"All time ({len(summary.all_times)} runs)",
            )
        )

    # Season distribution
    if summary.season_times:
        season_curve = _smoothed_histogram(summary.season_times)
        if season_curve is not None:
            x_s, y_s = season_curve
            fig.add_trace(
                go.Scatter(
                    x=x_s,
                    y=y_s,
                    mode="lines",
                    line=dict(color=BLUE, width=2, dash="dash"),
                    name=f"Season ({len(summary.season_times)} runs)",
                    hovertemplate=_distribution_hovertemplate(),
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=summary.season_times,
                    y=[0] * len(summary.season_times),
                    mode="markers",
                    marker=dict(color=BLUE, size=8, symbol="circle-open"),
                    name=f"Season ({len(summary.season_times)} runs)",
                )
            )

    # Best-ever line
    if summary.best_ever is not None:
        _add_vline(fig, summary.best_ever, GREEN, None, f"Best ever: {summary.best_ever:.1f}s")

    # Season-best line
    if summary.season_best is not None:
        _add_vline(
            fig, summary.season_best, RED, "dash", f"Season best: {summary.season_best:.1f}s"
        )

    fig.update_layout(**_base_layout(title))
    return fig


def plot_rider_vs_field(
    rider_summary: RiderTimeSummary,
    field_summary: FieldTimeSummary,
) -> go.Figure:
    """Section 2: Rider distribution overlaid on the whole field."""
    title = rider_summary.position

    if not field_summary.all_times:
        return _empty_figure(f"No field data for {rider_summary.position}", title)

    fig = go.Figure()

    normalized_hover = "<b>%{x:.1f}s</b><extra></extra>"

    # Field distribution (peak-normalized)
    field_curve = _smoothed_histogram(field_summary.all_times)
    if field_curve is not None:
        x_f, y_f = field_curve
        y_f = y_f / y_f.max()
        fig.add_trace(
            go.Scatter(
                x=x_f,
                y=y_f,
                mode="lines",
                fill="tozeroy",
                fillcolor="rgba(174,199,232,0.3)",
                line=dict(color=LIGHT_BLUE, width=1.5),
                name=(
                    f"All riders ({field_summary.n_riders} riders,"
                    f" {len(field_summary.all_times)} runs)"
                ),
                hovertemplate=normalized_hover,
            )
        )

    # Rider distribution (peak-normalized, overlaid)
    if rider_summary.all_times:
        rider_curve = _smoothed_histogram(rider_summary.all_times)
        if rider_curve is not None:
            x_r, y_r = rider_curve
            y_r = y_r / y_r.max()
            fig.add_trace(
                go.Scatter(
                    x=x_r,
                    y=y_r,
                    mode="lines",
                    fill="tozeroy",
                    fillcolor="rgba(31,119,180,0.35)",
                    line=dict(color=BLUE, width=2),
                    name=f"{rider_summary.display_name} ({len(rider_summary.all_times)} runs)",
                    hovertemplate=normalized_hover,
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=rider_summary.all_times,
                    y=[0] * len(rider_summary.all_times),
                    mode="markers",
                    marker=dict(color=BLUE, size=8),
                    name=f"{rider_summary.display_name} ({len(rider_summary.all_times)} runs)",
                )
            )

    # Rider estimated time line
    if rider_summary.estimated_time is not None:
        label = f"Est. time: {rider_summary.estimated_time:.1f}s"
        if rider_summary.estimated_source == "empirical":
            label += " (empirical)"
        _add_vline(fig, rider_summary.estimated_time, BLUE, None, label)

    # Field median line
    if field_summary.median_time is not None:
        _add_vline(
            fig,
            field_summary.median_time,
            GREY,
            "dash",
            f"Field median: {field_summary.median_time:.1f}s",
        )

    layout = _base_layout(title)
    layout["yaxis"]["title"] = dict(text="Relative Density", font=dict(size=12, color=AXIS_COLOR))
    fig.update_layout(**layout)
    return fig


def plot_handicap_comparison(comparison: HandicapComparison) -> go.Figure:
    """Section 3: Scratch vs compared rider with handicap annotation."""
    title = comparison.rider_summary.position
    scratch = comparison.scratch_summary
    rider = comparison.rider_summary

    if not scratch.all_times and not rider.all_times:
        return _empty_figure(
            f"Insufficient data to compute handicap on {title}",
            title,
        )

    fig = go.Figure()

    # Scratch distribution
    if scratch.all_times:
        scr_curve = _smoothed_histogram(scratch.all_times)
        if scr_curve is not None:
            x_s, y_s = scr_curve
            fig.add_trace(
                go.Scatter(
                    x=x_s,
                    y=y_s,
                    mode="lines",
                    fill="tozeroy",
                    fillcolor="rgba(255,127,14,0.3)",
                    line=dict(color=ORANGE, width=2),
                    name=f"{scratch.display_name} ({len(scratch.all_times)} runs)",
                    hovertemplate=_distribution_hovertemplate(),
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=scratch.all_times,
                    y=[0] * len(scratch.all_times),
                    mode="markers",
                    marker=dict(color=ORANGE, size=8),
                    name=f"{scratch.display_name} ({len(scratch.all_times)} runs)",
                )
            )

    # Compared rider distribution
    if rider.all_times:
        rdr_curve = _smoothed_histogram(rider.all_times)
        if rdr_curve is not None:
            x_r, y_r = rdr_curve
            fig.add_trace(
                go.Scatter(
                    x=x_r,
                    y=y_r,
                    mode="lines",
                    fill="tozeroy",
                    fillcolor="rgba(31,119,180,0.35)",
                    line=dict(color=BLUE, width=2),
                    name=f"{rider.display_name} ({len(rider.all_times)} runs)",
                    hovertemplate=_distribution_hovertemplate(),
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=rider.all_times,
                    y=[0] * len(rider.all_times),
                    mode="markers",
                    marker=dict(color=BLUE, size=8),
                    name=f"{rider.display_name} ({len(rider.all_times)} runs)",
                )
            )

    # Estimated time vertical lines
    if scratch.estimated_time is not None:
        _add_vline(
            fig, scratch.estimated_time, ORANGE, None, f"Est: {scratch.estimated_time:.1f}s"
        )

    if rider.estimated_time is not None:
        _add_vline(fig, rider.estimated_time, BLUE, None, f"Est: {rider.estimated_time:.1f}s")

    # Handicap annotation arrow
    if (
        comparison.handicap_value is not None
        and scratch.estimated_time is not None
        and rider.estimated_time is not None
    ):
        mid_x = (scratch.estimated_time + rider.estimated_time) / 2
        sign = "+" if comparison.handicap_value >= 0 else ""
        hcap_text = f"<b>{sign}{comparison.handicap_value:.2f}s</b>"
        source_text = f"<i>({comparison.handicap_source})</i>"

        annotation_font = dict(size=14, family=FONT_FAMILY, color=TITLE_COLOR)

        if abs(comparison.handicap_value) > 0.01:
            fig.add_annotation(
                x=mid_x,
                y=0.97,
                xref="x",
                yref="paper",
                text=f"{hcap_text}<br>{source_text}",
                showarrow=False,
                font=annotation_font,
                align="center",
                bgcolor="white",
                bordercolor="rgba(0,0,0,0.12)",
                borderpad=6,
                borderwidth=1,
            )
            # Horizontal line between the two estimated times
            fig.add_shape(
                type="line",
                x0=scratch.estimated_time,
                x1=rider.estimated_time,
                y0=0.78,
                y1=0.78,
                xref="x",
                yref="paper",
                line=dict(color=AXIS_COLOR, width=1.5),
            )
            # Left arrowhead (pointing at scratch)
            fig.add_annotation(
                x=scratch.estimated_time,
                y=0.78,
                ax=mid_x,
                ay=0.78,
                xref="x",
                yref="paper",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.2,
                arrowwidth=1.5,
                arrowcolor=AXIS_COLOR,
                text="",
            )
            # Right arrowhead (pointing at rider)
            fig.add_annotation(
                x=rider.estimated_time,
                y=0.78,
                ax=mid_x,
                ay=0.78,
                xref="x",
                yref="paper",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.2,
                arrowwidth=1.5,
                arrowcolor=AXIS_COLOR,
                text="",
            )
        else:
            fig.add_annotation(
                x=mid_x,
                y=0.97,
                xref="x",
                yref="paper",
                text=f"0.00s<br>{source_text}",
                showarrow=False,
                font=annotation_font,
                align="center",
                bgcolor="white",
                bordercolor="rgba(0,0,0,0.12)",
                borderpad=6,
                borderwidth=1,
            )

    fig.update_layout(**_base_layout(title))
    return fig
