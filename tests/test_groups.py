"""Column grouping taxonomy.

The company page, the grid's column picker and the screener's field picker
all read the same `group` field. These tests hold the shape that makes it
useful: no group so large it recreates the wall it replaced, and no rule
misfiring so a record lands under 'Trailing twelve months'.
"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import app

# Segments that appear on the company page.
VISIBLE = [
    "Overview", "Performance", "Per Share", "Valuation", "Profitability",
    "Balance Sheet", "Cash Flow", "Growth", "Income Statement", "History",
    "Trend & Momentum", "Technicals", "Ownership", "Dividend", "Forecasts",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def catalog(client):
    return pd.DataFrame(client.get("/meta/catalog").json()["columns"])


def test_every_column_has_a_group(catalog):
    assert catalog["group"].notna().all()
    assert (catalog["group"].str.len() > 0).all()


def test_visible_segments_are_almost_fully_grouped(catalog):
    """A few genuine miscellany columns may stay in 'Other'; a segment mostly
    in 'Other' means a rule is missing."""
    vis = catalog[catalog["segment"].isin(VISIBLE)]
    other = (vis["group"] == "Other").sum()
    assert other / len(vis) < 0.05, f"{other} of {len(vis)} ungrouped"


def test_no_group_recreates_the_wall(catalog):
    """The whole point was to break up a 90-column tab. If a group grows past
    ~25 it needs splitting."""
    vis = catalog[catalog["segment"].isin(VISIBLE)]
    sizes = vis.groupby(["segment", "group"]).size()
    too_big = sizes[sizes > 25]
    assert too_big.empty, f"oversized groups:\n{too_big}"


def test_large_segments_are_split_into_several_groups(catalog):
    vis = catalog[catalog["segment"].isin(VISIBLE)]
    for segment, rows in vis.groupby("segment"):
        if len(rows) >= 30:
            assert rows["group"].nunique() >= 4, (
                f"{segment} has {len(rows)} columns in only "
                f"{rows['group'].nunique()} group(s)")


# Rule precedence: these were specifically at risk of matching the wrong rule.
@pytest.mark.parametrize("column,expected", [
    ("pat_ttm_at_ath", "Records"),          # record, not TTM
    ("pat_ttm_vs_peak_pct", "Records"),     # record, not TTM
    ("pat_ttm", "Trailing twelve months"),
    ("pat_fy_at_ath", "Records"),           # record, not Annual
    ("pat_cagr_5y_pct", "Annual"),
    ("dist_ema_200_pct", "Moving averages"),
    ("dist_52w_high_pct", "Distance from highs & lows"),
    ("ema_stack_bullish", "Trend state"),
    ("high_52w", "Highs & lows"),
    ("roce", "Returns on capital"),
    ("piotroski_f_score", "Quality scores"),
    ("current_ratio_annual", "Liquidity"),
    ("debt_to_equity", "Leverage"),
    ("rsi_14", "Oscillators"),
    ("atr_pct", "Volatility"),
    ("technical_rating", "Ratings"),
])
def test_rule_precedence(catalog, column, expected):
    row = catalog[catalog["name"] == column]
    assert not row.empty, f"{column} missing from catalog"
    assert row.iloc[0]["group"] == expected


def test_company_items_carry_their_group(client):
    d = client.get("/companies/TCS").json()
    for segment, items in d["segments"].items():
        for it in items:
            assert it.get("group"), f"{it['name']} in {segment} has no group"
            assert it.get("label")


def test_segments_endpoint_carries_group(client):
    segs = client.get("/meta/segments").json()["segments"]
    assert all("group" in c for s in segs for c in s["columns"])


# --------------------------------------------------------- range widget
RANGE_INPUTS = [
    "price", "low_52w", "high_52w", "low_all_time", "high_all_time",
    "pct_of_52w_range", "dist_52w_high_pct", "above_52w_low_pct",
    "dist_ath_pct", "above_atl_pct", "high_1m", "high_3m", "high_6m",
]


def test_range_bar_inputs_are_fully_populated(client):
    r = client.post("/screen", json={"columns": RANGE_INPUTS,
                                     "limit": 750}).json()
    for field in RANGE_INPUTS:
        n = sum(1 for row in r["rows"] if row.get(field) is not None)
        assert n == 750, f"{field} populated for only {n}/750"


def test_range_bounds_are_coherent(client):
    """A range bar with high <= low divides by zero and renders nonsense."""
    r = client.post("/screen", json={
        "columns": ["symbol", "low_52w", "high_52w", "low_all_time",
                    "high_all_time", "price"], "limit": 750}).json()
    for row in r["rows"]:
        assert row["high_52w"] > row["low_52w"], row["symbol"]
        assert row["high_all_time"] > row["low_all_time"], row["symbol"]
        # The all-time range must contain the 52-week range.
        assert row["high_all_time"] >= row["high_52w"] - 0.01, row["symbol"]
        assert row["low_all_time"] <= row["low_52w"] + 0.01, row["symbol"]
