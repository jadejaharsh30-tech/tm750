"""The four strategies, carried over from the running app's scanner_engine."""
from __future__ import annotations

import pandas as pd

from tm750.scanner import strategies


def test_green_candle_is_true_on_a_flat_close():
    assert strategies.green_candle(100.0, 100.0) == "Y"
    assert strategies.green_candle(101.0, 100.0) == "Y"
    assert strategies.green_candle(99.0, 100.0) == "N"


def test_green_candle_is_na_without_a_previous_close():
    assert strategies.green_candle(100.0, None) == "N/A"


def test_close_above_ath_is_strict():
    assert strategies.close_gt_ath(101.0, 100.0) == "Y"
    assert strategies.close_gt_ath(100.0, 100.0) == "N"


def test_close_above_ath_cannot_fire_after_sync():
    """After EOD Sync the trigger equals today's high, and close <= high
    always. Correct post-sync state, not a defect -- the UI banners it."""
    today_high = 120.0
    assert strategies.close_gt_ath(119.0, today_high) == "N"
    assert strategies.close_gt_ath(120.0, today_high) == "N"


def test_relative_strength_is_at_a_high_when_the_ratio_peaks_today():
    idx = pd.date_range("2026-01-01", periods=220)
    stock = pd.Series(range(100, 320), index=idx, dtype=float)
    index = pd.Series([100.0] * 220, index=idx)
    out = strategies.relative_strength(stock, index, window=211)
    assert out["ath_outperformance"] == "Y"
    assert out["current_rs"] == out["ath_rs"]


def test_relative_strength_is_not_at_a_high_after_a_fall():
    idx = pd.date_range("2026-01-01", periods=220)
    values = list(range(100, 310)) + [200.0] * 10
    stock = pd.Series(values, index=idx, dtype=float)
    index = pd.Series([100.0] * 220, index=idx)
    out = strategies.relative_strength(stock, index, window=211)
    assert out["ath_outperformance"] == "N"
    assert out["current_rs"] < out["ath_rs"]


def test_relative_strength_uses_the_ratio_not_the_raw_price():
    """A stock up 50% while the index is up 60% is NOT outperforming."""
    idx = pd.date_range("2026-01-01", periods=215)
    stock = pd.Series([100 + i * 0.5 for i in range(215)], index=idx)
    index = pd.Series([100 + i * 0.8 for i in range(215)], index=idx)
    out = strategies.relative_strength(stock, index, window=211)
    assert out["ath_outperformance"] == "N"
    assert out["current_rs"] < 100


def test_relative_strength_returns_na_on_insufficient_history():
    """A recent listing has not failed the test -- it was never given it."""
    idx = pd.date_range("2026-01-01", periods=30)
    stock = pd.Series(range(100, 130), index=idx, dtype=float)
    index = pd.Series([100.0] * 30, index=idx)
    out = strategies.relative_strength(stock, index, window=211)
    assert out["ath_outperformance"] == "N/A"
    assert out["current_rs"] is None


def test_relative_strength_tolerance_admits_a_near_miss():
    """0.9999 means within 0.01% of the window max still counts."""
    idx = pd.date_range("2026-01-01", periods=211)
    values = [100.0] * 210 + [100.0 * 0.99995]
    stock = pd.Series(values, index=idx)
    index = pd.Series([1.0] * 211, index=idx)
    out = strategies.relative_strength(stock, index, window=211)
    assert out["ath_outperformance"] == "Y"


def test_relative_strength_handles_a_none_benchmark():
    idx = pd.date_range("2026-01-01", periods=220)
    stock = pd.Series(range(100, 320), index=idx, dtype=float)
    assert strategies.relative_strength(stock, None)["ath_outperformance"] == "N/A"
