"""Smoke tests for the Handicap Explorer UI chart layer."""

import plotly.graph_objects as go

from smtc_handicap.ui.plots import (
    _smoothed_histogram,
    plot_handicap_comparison,
    plot_rider_performance,
    plot_rider_vs_field,
)
from smtc_handicap.ui.queries import (
    FieldTimeSummary,
    HandicapComparison,
    RiderTimeSummary,
)


def _make_rider_summary(
    times: list[float] | None = None,
    season_times: list[float] | None = None,
    position: str = "TOP",
    estimated_time: float | None = None,
    estimated_source: str = "empirical",
) -> RiderTimeSummary:
    all_t = times or []
    season_t = season_times or []
    return RiderTimeSummary(
        rider_id="test_rider",
        display_name="T. Ester",
        position=position,
        all_times=all_t,
        season_times=season_t,
        best_ever=min(all_t) if all_t else None,
        season_best=min(season_t) if season_t else None,
        estimated_time=estimated_time,
        estimated_source=estimated_source,
    )


def _make_field_summary(
    times: list[float] | None = None,
    position: str = "TOP",
) -> FieldTimeSummary:
    all_t = times or []
    import numpy as np

    return FieldTimeSummary(
        position=position,
        all_times=all_t,
        n_riders=10 if all_t else 0,
        median_time=float(np.median(all_t)) if all_t else None,
    )


class TestSmoothedHistogram:
    def test_returns_none_for_empty(self):
        assert _smoothed_histogram([]) is None

    def test_returns_none_for_single(self):
        assert _smoothed_histogram([55.0]) is None

    def test_returns_arrays(self):
        result = _smoothed_histogram([50.0, 52.0, 53.0, 55.0, 56.0, 58.0, 60.0])
        assert result is not None
        x, y = result
        assert len(x) == 200
        assert len(y) == 200
        assert (y >= 0).all()

    def test_two_points(self):
        result = _smoothed_histogram([50.0, 55.0])
        assert result is not None


class TestPlotRiderPerformance:
    def test_with_data(self):
        summary = _make_rider_summary(
            times=[50.0, 52.0, 53.0, 55.0, 56.0],
            season_times=[50.0, 52.0, 53.0],
        )
        fig = plot_rider_performance(summary)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_empty_data(self):
        summary = _make_rider_summary()
        fig = plot_rider_performance(summary)
        assert isinstance(fig, go.Figure)
        # Should have annotation for empty state
        assert len(fig.layout.annotations) > 0

    def test_single_point(self):
        summary = _make_rider_summary(times=[55.0], season_times=[55.0])
        fig = plot_rider_performance(summary)
        assert isinstance(fig, go.Figure)
        # Should use markers instead of curve
        assert fig.data[0].mode == "markers"


class TestPlotRiderVsField:
    def test_with_data(self):
        rider = _make_rider_summary(
            times=[50.0, 52.0, 53.0, 55.0, 56.0],
            estimated_time=53.0,
        )
        field = _make_field_summary(
            times=[x * 0.5 + 48 for x in range(40)],
        )
        fig = plot_rider_vs_field(rider, field)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2  # field + rider + lines

    def test_empty_field(self):
        rider = _make_rider_summary(times=[55.0])
        field = _make_field_summary()
        fig = plot_rider_vs_field(rider, field)
        assert isinstance(fig, go.Figure)
        assert len(fig.layout.annotations) > 0  # empty state


class TestPlotHandicapComparison:
    def test_with_data(self):
        scratch = _make_rider_summary(
            times=[50.0, 51.0, 52.0, 53.0, 54.0],
            estimated_time=52.0,
            estimated_source="Bayesian",
        )
        scratch.display_name = "S. Cratch"
        rider = _make_rider_summary(
            times=[55.0, 56.0, 57.0, 58.0, 59.0],
            estimated_time=57.0,
            estimated_source="Bayesian",
        )
        comp = HandicapComparison(
            scratch_summary=scratch,
            rider_summary=rider,
            handicap_value=5.0,
            handicap_source="Bayesian",
        )
        fig = plot_handicap_comparison(comp)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2

    def test_same_rider(self):
        summary = _make_rider_summary(
            times=[50.0, 51.0, 52.0, 53.0, 54.0],
            estimated_time=52.0,
        )
        comp = HandicapComparison(
            scratch_summary=summary,
            rider_summary=summary,
            handicap_value=0.0,
            handicap_source="Bayesian",
        )
        fig = plot_handicap_comparison(comp)
        assert isinstance(fig, go.Figure)

    def test_both_empty(self):
        scratch = _make_rider_summary()
        rider = _make_rider_summary()
        comp = HandicapComparison(
            scratch_summary=scratch,
            rider_summary=rider,
        )
        fig = plot_handicap_comparison(comp)
        assert isinstance(fig, go.Figure)
        assert len(fig.layout.annotations) > 0
