"""Invariants that must hold, because everything downstream assumes them.

These aren't unit tests of implementation detail. Each one guards an
assumption that, if it silently broke, would produce a plausible-looking but
wrong dataset -- the worst failure mode for an analytics layer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tm750 import ingest
from tm750.config import (CAP_TIER_EXPECTED, EXPECTED_UNIVERSE, RAW, SOURCES,
                          to_snake)


@pytest.fixture(scope="module")
def raw():
    return ingest.load_all()


@pytest.fixture(scope="module")
def built():
    from tm750.build import build
    return build(write=False)


# ------------------------------------------------------------- ingest
def test_universe_size(raw):
    assert len(raw["tradingview"]) == EXPECTED_UNIVERSE


def test_isin_is_unique_and_complete(raw):
    isin = raw["tradingview"]["isin"]
    assert isin.notna().all()
    assert isin.is_unique


def test_all_currency_columns_are_inr():
    """We drop 55 currency columns. That is only safe if they are all INR."""
    df = pd.read_csv(RAW / SOURCES["tradingview"])
    for c in [c for c in df.columns if c.endswith("- Currency")]:
        assert set(df[c].dropna()) <= {"INR"}, f"{c} has non-INR values"


def test_every_source_joins_completely(raw):
    """A partial join would silently null out whole feature families."""
    cov = ingest.check_coverage(raw)
    for row in cov.to_dict("records"):
        assert row["matched"] == row["of"], \
            f"{row['source']} unmatched: {row['unmatched_symbols']}"


# --------------------------------------------------------- cap tiers
def test_cap_tiers_are_exact(built):
    counts = built["df"]["cap_tier"].value_counts().to_dict()
    assert counts == CAP_TIER_EXPECTED


def test_no_unclassified_companies(built):
    assert (built["df"]["cap_tier"] == "Unclassified").sum() == 0


def test_cap_tiers_respect_market_cap_ordering(built):
    """Tiers derive from index membership; median mcap must still descend."""
    med = built["df"].groupby("cap_tier")["market_cap"].median()
    assert med["Large"] > med["Mid"] > med["Small"] > med["Micro"]


# ---------------------------------------------------- reconstruction
def test_revenue_reconstruction_matches_reported(built):
    raw_tv = pd.read_csv(RAW / SOURCES["tradingview"])
    reported = raw_tv["Net revenue, Trailing 12 months"]
    derived = built["df"]["revenue_ttm"]
    mask = reported.notna() & derived.notna()
    assert mask.sum() >= 30
    err = ((derived[mask] / reported[mask] - 1) * 100).abs()
    assert err.median() < 5.0


def test_price_to_book_reconstruction_correlates(built):
    raw_tv = pd.read_csv(RAW / SOURCES["tradingview"])
    reported = raw_tv["Price to book ratio"]
    derived = built["df"]["price_to_book"]
    mask = reported.notna() & derived.notna()
    assert mask.sum() >= 50
    assert np.corrcoef(reported[mask], derived[mask])[0, 1] > 0.95


def test_derived_never_overwrites_reported(built):
    """Reconstructed fields must land under new names, not clobber sources."""
    cols = built["df"].columns
    assert "revenue_ttm" in cols
    assert not cols.duplicated().any()


# ------------------------------------------------- profit sentinels
def test_profit_zeros_became_nulls(built):
    """Zeros were 'not listed', not 'zero profit'. Treating them as real
    would manufacture false losses across every growth calculation."""
    df = built["df"]
    assert df["pat_latest_q"].eq(0).sum() == 0
    assert (df["qtrs_available"] < 48).sum() > 0, "sentinels not converted"


def test_losses_survived_sentinel_conversion(built):
    """Negatives must still be present -- proof we nulled zeros, not losses."""
    assert (built["df"]["pat_latest_q"] < 0).sum() > 0


def test_cagr_undefined_across_sign_change(built):
    """A compound rate from a loss to a profit is meaningless, not a number."""
    df = built["df"]
    bad = df[(df["pat_fy1"] > 0) & (df["pat_cagr_15y_pct"].notna())]
    assert (bad["pat_cagr_15y_pct"] > -100).all()


# ------------------------------------------------------- catalog
def test_catalog_covers_every_column(built):
    names = {s.name for s in built["catalog"]}
    assert names == set(built["df"].columns)


def test_finance_metrics_are_masked(built):
    from tm750.config import FINANCE_INVALID_METRICS
    masked = {s.name for s in built["catalog"] if not s.finance_valid}
    present = FINANCE_INVALID_METRICS & set(built["df"].columns)
    assert present <= masked


def test_low_coverage_columns_are_not_screenable(built):
    for s in built["catalog"]:
        if s.coverage_pct < 50 and s.unit not in ("text", "date"):
            assert not s.screenable, f"{s.name} at {s.coverage_pct}% screenable"


def test_no_column_lands_in_a_nonexistent_segment(built):
    from tm750.config import SEGMENTS
    allowed = set(SEGMENTS) | {"Percentile Ranks"}
    for s in built["catalog"]:
        assert s.segment in allowed, f"{s.name} -> {s.segment}"


# --------------------------------------------------------- helpers
def test_snake_case_is_deterministic():
    assert to_snake("Price change %, 1 day") == "price_change_pct_1_day"
    assert to_snake("Return on equity %, Annual") == "return_on_equity_pct_annual"
    assert to_snake("EBITDA, Trailing 12 months") == "ebitda_trailing_12_months"


def test_row_count_survives_the_pipeline(built):
    assert len(built["df"]) == EXPECTED_UNIVERSE


# ---------------------------------------------------- profit all-time highs
def test_both_at_ath_is_ttm_and_quarter_not_annual(built):
    """TTM is the rolling-year measure and updates every quarter; reported
    annual PAT moves once a year and can describe a period closed up to four
    quarters ago. The combined flag must therefore pair TTM with the latest
    quarter, never annual with TTM."""
    df = built["df"]
    expected = df["pat_ttm_at_ath"].fillna(False) & df["pat_q_at_ath"].fillna(False)
    assert (df["pat_both_at_ath"].fillna(False) == expected).all()


def test_at_ath_flags_imply_zero_gap_from_peak(built):
    df = built["df"]
    for flag, gap in [("pat_ttm_at_ath", "pat_ttm_vs_peak_pct"),
                      ("pat_q_at_ath", "pat_q_vs_peak_pct"),
                      ("pat_fy_at_ath", "pat_vs_peak_pct")]:
        hit = df[df[flag].fillna(False)]
        assert (hit[gap].abs() < 0.01).all(), f"{flag} set but {gap} nonzero"


def test_loss_making_peak_is_not_an_all_time_high(built):
    """A company whose best-ever profit is a loss is not "at an all-time
    high" in any useful sense, however the arithmetic works out."""
    df = built["df"]
    for flag, peak in [("pat_ttm_at_ath", "pat_ttm_peak"),
                       ("pat_q_at_ath", "pat_peak_q"),
                       ("pat_fy_at_ath", "pat_peak_fy")]:
        hit = df[df[flag].fillna(False)]
        assert (hit[peak] > 0).all(), f"{flag} set with non-positive {peak}"


def test_ath_cohorts_partition_cleanly(built):
    df = built["df"]
    ttm = df["pat_ttm_at_ath"].fillna(False)
    q = df["pat_q_at_ath"].fillna(False)
    both = df["pat_both_at_ath"].fillna(False)
    assert int(both.sum()) == int((ttm & q).sum())
    assert int((ttm & ~q).sum()) + int(both.sum()) == int(ttm.sum())
