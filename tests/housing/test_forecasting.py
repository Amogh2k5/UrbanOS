"""Tests for Housing Resale Price Forecasting module."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from backend.app.planning.housing.forecasting import (
    _quarter_to_ts,
    _ts_to_quarter,
    _next_quarter,
    _prev_quarter,
    _period_key,
    _compute_metrics,
    _evaluate_baseline_persistence,
    _evaluate_baseline_seasonal,
    SeriesData,
)


SG = timezone(timedelta(hours=8))


class TestQuarterHelpers:
    def test_quarter_to_ts(self):
        assert _quarter_to_ts("2023-Q1") == datetime(2023, 3, 1, tzinfo=timezone.utc).replace(tzinfo=SG)
        assert _quarter_to_ts("2023-Q2") == datetime(2023, 6, 1, tzinfo=timezone.utc).replace(tzinfo=SG)
        assert _quarter_to_ts("2023-Q3") == datetime(2023, 9, 1, tzinfo=timezone.utc).replace(tzinfo=SG)
        assert _quarter_to_ts("2023-Q4") == datetime(2023, 12, 1, tzinfo=timezone.utc).replace(tzinfo=SG)

    def test_ts_to_quarter(self):
        ts = datetime(2023, 3, 1, tzinfo=SG)
        assert _ts_to_quarter(ts) == "2023-Q1"
        ts = datetime(2023, 6, 1, tzinfo=SG)
        assert _ts_to_quarter(ts) == "2023-Q2"
        ts = datetime(2023, 9, 1, tzinfo=SG)
        assert _ts_to_quarter(ts) == "2023-Q3"
        ts = datetime(2023, 12, 1, tzinfo=SG)
        assert _ts_to_quarter(ts) == "2023-Q4"

    def test_next_quarter(self):
        assert _next_quarter("2023-Q1") == "2023-Q2"
        assert _next_quarter("2023-Q2") == "2023-Q3"
        assert _next_quarter("2023-Q3") == "2023-Q4"
        assert _next_quarter("2023-Q4") == "2024-Q1"

    def test_prev_quarter(self):
        assert _prev_quarter("2023-Q2") == "2023-Q1"
        assert _prev_quarter("2023-Q3") == "2023-Q2"
        assert _prev_quarter("2023-Q4") == "2023-Q3"
        assert _prev_quarter("2024-Q1") == "2023-Q4"

    def test_period_key_sorting(self):
        quarters = ["2023-Q4", "2023-Q1", "2022-Q4", "2023-Q2", "2023-Q3"]
        sorted_quarters = sorted(quarters, key=_period_key)
        assert sorted_quarters == ["2022-Q4", "2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4"]


class TestMetrics:
    def test_compute_metrics_perfect(self):
        y_true = [100.0, 200.0, 300.0]
        y_pred = [100.0, 200.0, 300.0]
        mae, rmse, mape = _compute_metrics(y_true, y_pred)
        assert mae == 0.0
        assert rmse == 0.0
        assert mape == 0.0

    def test_compute_metrics_offset(self):
        y_true = [100.0, 200.0, 300.0]
        y_pred = [110.0, 210.0, 310.0]
        mae, rmse, mape = _compute_metrics(y_true, y_pred)
        assert mae == 10.0
        assert rmse == 10.0
        # mape = (10/100 + 10/200 + 10/300) / 3 * 100 = (0.1 + 0.05 + 0.0333) / 3 * 100 = 6.11%
        assert abs(mape - 6.11) < 0.1

    def test_compute_metrics_with_nan(self):
        y_true = [100.0, float("nan"), 300.0]
        y_pred = [110.0, 210.0, 310.0]
        mae, rmse, mape = _compute_metrics(y_true, y_pred)
        # Should only use indices 0 and 2
        assert mae == 10.0
        assert rmse == 10.0


class TestBaselineEvaluation:
    def _make_series(self, values: list[float]) -> SeriesData:
        periods = [f"2023-Q{i%4+1}" if i < 4 else f"2024-Q{i%4+1}" for i in range(len(values))]
        return SeriesData(
            town="TOWN",
            flat_type="4-room",
            periods=periods,
            values=values,
            timestamps=[datetime(2023, 3*(i%4+1), 1, tzinfo=SG) for i in range(len(values))],
        )

    def test_persistence_baseline_perfect(self):
        """Persistence should be perfect when values don't change."""
        series = self._make_series([500000.0] * 6)
        result = _evaluate_baseline_persistence(series)
        assert result.mae == 0.0
        assert result.rmse == 0.0

    def test_persistence_baseline_constant_change(self):
        """Persistence with constant quarterly increase of 10k."""
        series = self._make_series([500000.0, 510000.0, 520000.0, 530000.0, 540000.0, 550000.0])
        result = _evaluate_baseline_persistence(series)
        # Each prediction is off by 10000
        assert result.mae == 10000.0
        assert result.rmse == 10000.0

    def test_seasonal_baseline_perfect(self):
        """Seasonal persistence should be perfect with yearly cycle."""
        # Year 1: 500, 510, 520, 530
        # Year 2: 500, 510, 520, 530
        series = self._make_series([500000.0, 510000.0, 520000.0, 530000.0, 500000.0, 510000.0, 520000.0, 530000.0])
        result = _evaluate_baseline_seasonal(series)
        # Should be perfect for last 4 predictions (index 4,5,6,7 predicted from index 0,1,2,3)
        assert result.mae == 0.0
        assert result.rmse == 0.0

    def test_seasonal_baseline_no_cycle(self):
        """Seasonal persistence fails when no yearly pattern."""
        series = self._make_series([500000.0, 510000.0, 520000.0, 530000.0, 540000.0, 550000.0, 560000.0, 570000.0])
        result = _evaluate_baseline_seasonal(series)
        # Each prediction is off by 40000
        assert result.mae == 40000.0
        assert result.rmse == 40000.0


class TestSeriesData:
    def test_series_data_creation(self):
        series = SeriesData(
            town="ANG MO KIO",
            flat_type="4-room",
            periods=["2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4"],
            values=[500000.0, 510000.0, 520000.0, 530000.0],
            timestamps=[
                datetime(2023, 3, 1, tzinfo=SG),
                datetime(2023, 6, 1, tzinfo=SG),
                datetime(2023, 9, 1, tzinfo=SG),
                datetime(2023, 12, 1, tzinfo=SG),
            ],
        )
        assert series.town == "ANG MO KIO"
        assert series.flat_type == "4-room"
        assert len(series.periods) == 4
        assert len(series.values) == 4
        assert len(series.timestamps) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])