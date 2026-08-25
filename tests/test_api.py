"""API contract tests.

Focus is on the guarantees the frontend and any future consumer rely on:
injection safety, sector masking, catalog validation, and pagination honesty.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ----------------------------------------------------------- health/meta
def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok"
    assert r["companies"] == 750


def test_catalog_is_complete(client):
    r = client.get("/meta/catalog").json()
    assert r["n"] > 400
    assert {"name", "segment", "polarity", "screenable"} <= set(r["columns"][0])


def test_segments_partition_the_catalog(client):
    cat = client.get("/meta/catalog").json()
    segs = client.get("/meta/segments").json()["segments"]
    assert sum(s["n"] for s in segs) == cat["n"]


def test_enums_populate_screener_dropdowns(client):
    e = client.get("/meta/enums").json()
    assert len(e["sector"]) > 10
    assert {x["value"] for x in e["cap_tier"]} == {"Large", "Mid", "Small",
                                                   "Micro"}
    assert len(e["index_memberships"]) > 90


# --------------------------------------------------------------- safety
def test_sql_injection_is_rejected_not_executed(client):
    r = client.post("/screen", json={"filters": [
        {"field": "pe_ratio; DROP TABLE companies", "op": "gt", "value": 1}]})
    assert r.status_code == 422
    assert client.get("/health").json()["companies"] == 750


def test_unknown_sort_field_rejected(client):
    r = client.post("/screen", json={"sort": [{"field": "nope", "dir": "asc"}]})
    assert r.status_code == 422


def test_unknown_column_rejected(client):
    r = client.post("/screen", json={"columns": ["symbol", "made_up"]})
    assert r.status_code == 422


def test_bad_arity_rejected(client):
    r = client.post("/screen", json={"filters": [
        {"field": "pe_ratio", "op": "between", "value": [10]}]})
    assert r.status_code == 422


def test_limit_is_bounded(client):
    assert client.post("/screen", json={"limit": 10_000}).status_code == 422


# ------------------------------------------------------------ screening
def test_filters_actually_filter(client):
    r = client.post("/screen", json={
        "filters": [{"field": "cap_tier", "op": "eq", "value": "Large"}],
        "limit": 200}).json()
    assert r["total"] == 100
    assert all(x["cap_tier"] == "Large" for x in r["rows"])


def test_combined_filters_narrow_results(client):
    one = client.post("/screen", json={"filters": [
        {"field": "cap_tier", "op": "in", "value": ["Small", "Micro"]}],
        "limit": 1}).json()["total"]
    two = client.post("/screen", json={"filters": [
        {"field": "cap_tier", "op": "in", "value": ["Small", "Micro"]},
        {"field": "ema_stack_bullish", "op": "eq", "value": True}],
        "limit": 1}).json()["total"]
    assert 0 < two < one == 500


def test_sort_is_respected(client):
    r = client.post("/screen", json={
        "sort": [{"field": "perf_1y_pct", "dir": "desc"}],
        "columns": ["symbol", "perf_1y_pct"], "limit": 20}).json()
    vals = [x["perf_1y_pct"] for x in r["rows"] if x["perf_1y_pct"] is not None]
    assert vals == sorted(vals, reverse=True)


def test_pagination_does_not_overlap(client):
    body = {"sort": [{"field": "market_cap", "dir": "desc"}],
            "columns": ["symbol"], "limit": 10}
    p1 = client.post("/screen", json={**body, "offset": 0}).json()["rows"]
    p2 = client.post("/screen", json={**body, "offset": 10}).json()["rows"]
    assert not ({x["symbol"] for x in p1} & {x["symbol"] for x in p2})


# --------------------------------------------------------- finance mask
def test_finance_metrics_masked_for_banks(client):
    r = client.get("/companies/HDFCBANK").json()
    assert r["sector"] == "Finance"
    assert "roce" in r["masked_fields"]


def test_non_finance_untouched(client):
    assert client.get("/companies/TCS").json()["masked_fields"] == []


def test_mask_applies_to_screen_results(client):
    r = client.post("/screen", json={
        "filters": [{"field": "sector", "op": "eq", "value": "Finance"}],
        "columns": ["symbol", "roce"], "limit": 5}).json()
    assert all(x["roce"] is None for x in r["rows"])


# ------------------------------------------------------- company & misc
def test_company_card_groups_by_segment(client):
    r = client.get("/companies/TCS").json()
    assert "Valuation" in r["segments"]
    assert r["percentile_ranks"]["roe"]["sector"] > 0


def test_unknown_symbol_404(client):
    assert client.get("/companies/NOTREAL").status_code == 404


def test_history_returns_series(client):
    r = client.get("/companies/TCS/history?freq=FY").json()
    assert r["n"] == 15
    assert r["series"][0]["periods_ago"] == 0


def test_compare_marks_best_by_polarity(client):
    r = client.post("/compare", json={
        "symbols": ["TCS", "INFY", "WIPRO"], "segments": ["Valuation"]}).json()
    pe = next(m for m in r["metrics"]["Valuation"] if m["name"] == "pe_ratio")
    assert pe["best_index"] == pe["values"].index(min(pe["values"]))


def test_compare_reports_missing_symbols(client):
    r = client.post("/compare", json={"symbols": ["TCS", "NOTREAL"]}).json()
    assert r["missing"] == ["NOTREAL"]


def test_pulse_breadth_is_a_percentage(client):
    b = client.get("/pulse").json()["breadth"]
    assert 0 <= b["pct_above_ema200"] <= 100


def test_explore_excludes_finance_from_roce(client):
    r = client.get("/explore/sector").json()
    assert r["note"] and "Finance" in r["note"]


def test_explore_rejects_bad_dimension(client):
    assert client.get("/explore/banana").status_code == 400


def test_movers_rejects_non_numeric_field(client):
    assert client.get("/movers?field=sector").status_code == 422


def test_search_ranks_exact_symbol_first(client):
    r = client.get("/search?q=tcs").json()["results"]
    assert r[0]["symbol"] == "TCS"
