"""Screener contract.

The frontend builds a filter DSL from the catalog and offers a fixed operator
vocabulary per column type. Every operator it can emit must be accepted, and
filters must actually compose -- adding one can only ever narrow the result.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def screen(client, filters, **kw):
    body = {"filters": filters, "limit": 1, "include_total": True, **kw}
    res = client.post("/screen", json=body)
    assert res.status_code == 200, res.json()
    return res.json()["total"]


# Every operator the UI offers, by column type.
NUMERIC = ["gte", "lte", "gt", "lt", "eq", "between", "is_null", "not_null"]
TEXT = ["in", "not_in", "contains", "is_null", "not_null"]


@pytest.mark.parametrize("op", NUMERIC)
def test_numeric_operators_accepted(client, op):
    value = ([5, 25] if op == "between" else None if op in ("is_null", "not_null")
             else 15)
    f = {"field": "pe_ratio", "op": op}
    if value is not None:
        f["value"] = value
    assert screen(client, [f]) >= 0


@pytest.mark.parametrize("op", TEXT)
def test_text_operators_accepted(client, op):
    value = (["Large", "Mid"] if op in ("in", "not_in")
             else "bank" if op == "contains" else None)
    f = {"field": "cap_tier" if op in ("in", "not_in") else "name", "op": op}
    if value is not None:
        f["value"] = value
    assert screen(client, [f]) >= 0


def test_boolean_filter(client):
    assert 0 < screen(client, [
        {"field": "ema_stack_bullish", "op": "eq", "value": True}]) < 750


def test_null_and_not_null_partition_the_universe(client):
    nulls = screen(client, [{"field": "pe_ratio", "op": "is_null"}])
    present = screen(client, [{"field": "pe_ratio", "op": "not_null"}])
    assert nulls + present == 750


def test_in_and_not_in_are_complements(client):
    inc = screen(client, [
        {"field": "cap_tier", "op": "in", "value": ["Small", "Micro"]}])
    exc = screen(client, [
        {"field": "cap_tier", "op": "not_in", "value": ["Small", "Micro"]}])
    assert inc + exc == 750


def test_adding_a_filter_can_only_narrow(client):
    """Filters compose with AND. If a second filter ever widened the result,
    the compiler would be building an OR somewhere."""
    one = screen(client, [
        {"field": "cap_tier", "op": "in", "value": ["Small", "Micro"]}])
    two = screen(client, [
        {"field": "cap_tier", "op": "in", "value": ["Small", "Micro"]},
        {"field": "roe", "op": "gte", "value": 15}])
    three = screen(client, [
        {"field": "cap_tier", "op": "in", "value": ["Small", "Micro"]},
        {"field": "roe", "op": "gte", "value": 15},
        {"field": "ema_stack_bullish", "op": "eq", "value": True}])
    assert one >= two >= three


def test_between_matches_the_pair_of_bounds(client):
    between = screen(client, [
        {"field": "pe_ratio", "op": "between", "value": [10, 20]}])
    bounded = screen(client, [
        {"field": "pe_ratio", "op": "gte", "value": 10},
        {"field": "pe_ratio", "op": "lte", "value": 20}])
    assert between == bounded


# The presets shipped in the UI. If a column is renamed in the data layer,
# these fail here rather than silently in the browser.
PRESETS = {
    "quality-momentum": [
        {"field": "ema_stack_bullish", "op": "eq", "value": True},
        {"field": "roe", "op": "gte", "value": 15},
        {"field": "debt_to_equity", "op": "lte", "value": 1},
        {"field": "perf_1y_pct", "op": "gt", "value": 0}],
    "record-earnings": [
        {"field": "pat_both_at_ath", "op": "eq", "value": True}],
    "divergent": [
        {"field": "pat_both_at_ath", "op": "eq", "value": True},
        {"field": "perf_1y_pct", "op": "lt", "value": 0}],
    "value-smallcap": [
        {"field": "cap_tier", "op": "in", "value": ["Small", "Micro"]},
        {"field": "pe_ratio", "op": "between", "value": [5, 20]},
        {"field": "peg_ratio", "op": "lte", "value": 1},
        {"field": "roe", "op": "gte", "value": 12}],
    "near-high": [
        {"field": "dist_52w_high_pct", "op": "gte", "value": -5},
        {"field": "above_ema_200", "op": "eq", "value": True}],
}


@pytest.mark.parametrize("name,filters", PRESETS.items())
def test_ui_presets_run_and_return_something(client, name, filters):
    n = screen(client, filters)
    assert 0 < n < 750, f"preset '{name}' returned {n}"


def test_divergent_preset_is_a_subset_of_record_earnings(client):
    assert (screen(client, PRESETS["divergent"])
            < screen(client, PRESETS["record-earnings"]))


def test_result_columns_are_all_valid(client):
    cols = ["symbol", "name", "cap_tier", "sector", "market_cap", "price",
            "perf_1y_pct", "momentum_12_1_pct", "pe_ratio", "roe",
            "dist_52w_high_pct"]
    res = client.post("/screen", json={"columns": cols, "limit": 3})
    assert res.status_code == 200
    assert all(c in res.json()["rows"][0] for c in cols)


def test_pulse_panel_endpoints_all_serve(client):
    for path in ["/pulse", "/pulse/breadth?by=sector", "/pulse/breadth?by=tier",
                 "/pulse/profit-ath", "/pulse/drawdown", "/pulse/valuation",
                 "/pulse/flows", "/pulse/factors"]:
        assert client.get(path).status_code == 200, path
