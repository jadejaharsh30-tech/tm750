"""Contracts for Compare, Explorer and Data Quality.

Each test pins a field the frontend actually reads. If the data layer renames
or drops one, this fails here rather than as a blank panel in the browser.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------- compare
def test_compare_returns_aligned_arrays(client):
    r = client.post("/compare", json={"symbols": ["TCS", "INFY", "WIPRO"]}).json()
    n = len(r["symbols"])
    assert n == 3 == len(r["names"]) == len(r["sectors"])
    for items in r["metrics"].values():
        for m in items:
            assert len(m["values"]) == n, f"{m['name']} has {len(m['values'])}"


def test_compare_preserves_requested_order(client):
    order = ["WIPRO", "TCS", "INFY"]
    r = client.post("/compare", json={"symbols": order}).json()
    assert r["symbols"] == order


def test_compare_best_index_follows_polarity(client):
    r = client.post("/compare", json={
        "symbols": ["TCS", "INFY", "WIPRO"], "segments": ["Valuation"]}).json()
    for m in r["metrics"]["Valuation"]:
        if m["best_index"] is None:
            continue
        nums = [v for v in m["values"] if isinstance(v, (int, float))]
        chosen = m["values"][m["best_index"]]
        if m["polarity"] == "lower_better":
            assert chosen == min(nums), m["name"]
        elif m["polarity"] == "higher_better":
            assert chosen == max(nums), m["name"]


def test_compare_never_highlights_neutral_metrics(client):
    r = client.post("/compare", json={"symbols": ["TCS", "INFY"]}).json()
    for items in r["metrics"].values():
        for m in items:
            if m["polarity"] == "neutral":
                assert m["best_index"] is None, m["name"]


def test_compare_masks_financials_per_symbol(client):
    r = client.post("/compare", json={"symbols": ["TCS", "HDFCBANK"]}).json()
    assert r["masked"]["TCS"] == []
    assert "roce" in r["masked"]["HDFCBANK"]


def test_compare_rejects_too_many(client):
    res = client.post("/compare", json={
        "symbols": ["TCS", "INFY", "WIPRO", "ITC", "SBIN", "LT", "M&M"]})
    assert res.status_code == 422


def test_compare_requires_at_least_two(client):
    assert client.post("/compare", json={"symbols": ["TCS"]}).status_code == 422


# ------------------------------------------------------------ explorer
# Every metric key the Explorer offers in its dropdown.
EXPLORER_KEYS = [
    "pe_ratio_median", "peg_ratio_median", "price_to_book_median",
    "roe_median", "roce_median", "perf_1y_pct_median", "perf_3m_pct_median",
    "momentum_12_1_pct_median", "dist_ath_pct_median",
    "dist_52w_high_pct_median", "rsi_14_median", "fii_holding_median",
    "dii_holding_median", "promoter_holding_median", "dividend_yield_median",
    "revenue_growth_ttm_yoy_median", "pat_cagr_5y_pct_median",
    "pct_above_ema200", "pct_ema_stacked", "mcap_lakh_cr",
]


@pytest.mark.parametrize("dim", ["sector", "industry", "tier"])
def test_explore_serves_every_ui_metric(client, dim):
    groups = client.get(f"/explore/{dim}").json()["groups"]
    assert groups
    missing = [k for k in EXPLORER_KEYS if k not in groups[0]]
    assert not missing, f"/explore/{dim} missing {missing}"


def test_explore_group_counts_sum_to_universe(client):
    groups = client.get("/explore/tier").json()["groups"]
    assert sum(g["n"] for g in groups) == 750


def test_explore_flags_finance_exclusion(client):
    """ROCE medians exclude financials. If that silently stopped happening,
    the note would vanish and bank ROCE would quietly rejoin the median."""
    r = client.get("/explore/sector").json()
    assert r["note"] and "Finance" in r["note"]


# ------------------------------------------------------------- quality
def test_quality_reports_every_section_the_ui_renders(client):
    q = client.get("/meta/quality").json()
    for key in ["universe", "columns_retained", "columns_dropped",
                "drop_reasons", "fully_populated_columns",
                "columns_below_50pct", "non_screenable_columns",
                "segment_coverage", "source_conflicts", "history_depth",
                "reconstruction_checks", "sector_masking"]:
        assert key in q, key


def test_quality_drop_reasons_account_for_all_drops(client):
    q = client.get("/meta/quality").json()
    assert sum(q["drop_reasons"].values()) == q["columns_dropped"]


def test_quality_masking_matches_the_api_behaviour(client):
    """The stated mask must equal what the API actually withholds -- a page
    that documents nine masked metrics while the API masks seven is worse
    than no page at all."""
    q = client.get("/meta/quality").json()["sector_masking"]
    bank = client.get("/companies/HDFCBANK").json()
    assert set(bank["masked_fields"]) == set(q["masked_list"])
    assert q["masked_metrics"] == len(q["masked_list"])


def test_quality_reconstruction_checks_are_validated(client):
    q = client.get("/meta/quality").json()
    for r in q["reconstruction_checks"]:
        assert r["within_tolerance"], f"{r['field']} drifted: {r}"
