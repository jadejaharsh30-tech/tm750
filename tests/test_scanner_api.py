"""Scanner endpoints, exercised against a live TestClient.

The router is mounted on a bare FastAPI app rather than api.main, so these
tests cover the scanner surface without depending on the rest of the API
being importable.
"""
from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import scanner as scanner_router
from tm750.scanner import prices, profit, scan, store, universe


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(scanner_router.router)

    @app.on_event("startup")
    def _init():
        store.init_schema()

    # Never TestClient(app) without `with` -- startup hooks would not fire.
    with TestClient(app) as c:
        yield c


def _reset():
    store.init_schema()
    cur = store.cursor()
    for t in ["ath", "ath_events", "universe", "profit", "scan_results",
              "result_dates", "feed_identifiers"]:
        cur.execute(f"DELETE FROM {t}")


def _xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


# ---------------------------------------------------------------- status
def test_status_endpoint_responds(client):
    r = client.get("/scanner/status")
    assert r.status_code == 200
    assert "running" in r.json()


def test_starting_a_scan_twice_is_rejected(client, monkeypatch):
    """Two concurrent scans would interleave their today_ath writes."""
    monkeypatch.setattr(scan, "get_status",
                        lambda: {"running": True, "progress": 1, "total": 2,
                                 "message": "busy", "last_updated": None})
    assert client.post("/scanner/scan").status_code == 409


# --------------------------------------------------------------- results
def test_results_endpoint_returns_the_expected_shape(client):
    _reset()
    body = client.get("/scanner/results").json()
    assert set(body) == {"rows", "post_sync", "profit_fetched_at"}
    assert body["rows"] == []


def test_results_reports_post_sync_only_after_a_real_sync(client):
    """The banner must key off a logged sync event, not price equality --
    a symbol seeded today also has NEW ATH == TRIGGER, and wrongly claiming
    a sync happened would tell the user a manual button had fired itself."""
    _reset()
    row = {
        "symbol": "AAA", "new_ath_price": 120.0, "trigger_price": 120.0,
        "green_candle": "Y", "close_gt_ath": "N", "ath_outperformance": "Y",
        "current_rs": 1.0, "ath_rs": 1.0, "profit_state": "at_ath",
        "profit_stale": False, "result_date": None, "stop_loss": None}
    scan.save_results([row])
    assert client.get("/scanner/results").json()["post_sync"] is False

    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 120.0, NULL, NULL)")
    client.post("/scanner/sync", json={"symbols": ["AAA"]})
    scan.save_results([row])
    assert client.get("/scanner/results").json()["post_sync"] is True


# ------------------------------------------------------------------ sync
def test_sync_rejects_an_empty_symbol_list(client):
    """Silently promoting everything on a mis-click is not recoverable."""
    assert client.post("/scanner/sync", json={"symbols": []}).status_code == 400


def test_sync_promotes_and_clears_today_ath(client):
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 120.0, NULL, NULL)")
    r = client.post("/scanner/sync", json={"symbols": ["AAA"]})
    assert r.json()["promoted"] == 1
    row = store.cursor().execute(
        "SELECT ath_price, today_ath FROM ath WHERE symbol='AAA'").fetchone()
    assert row == (120.0, None)


def test_sync_twice_promotes_once(client):
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 120.0, NULL, NULL)")
    client.post("/scanner/sync", json={"symbols": ["AAA"]})
    r = client.post("/scanner/sync", json={"symbols": ["AAA"]})
    assert r.json()["promoted"] == 0


# --------------------------------------------------------- manage database
def test_ath_list_is_searchable_by_prefix(client):
    _reset()
    cur = store.cursor()
    cur.execute("INSERT INTO ath VALUES ('AAPL', 1.0, NULL, NULL, NULL, NULL)")
    cur.execute("INSERT INTO ath VALUES ('ZEEL', 2.0, NULL, NULL, NULL, NULL)")
    rows = client.get("/scanner/ath", params={"q": "A"}).json()["rows"]
    assert [r["symbol"] for r in rows] == ["AAPL"]


def test_editing_an_ath_logs_the_change(client):
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    r = client.post("/scanner/ath/edit",
                    json={"symbol": "AAA", "price": 110.0,
                          "date": "2026-02-02"})
    assert r.status_code == 200
    ev = client.get("/scanner/ath/events", params={"symbol": "AAA"}).json()
    assert ev["rows"][0]["source"] == "manual"
    assert ev["rows"][0]["new_price"] == 110.0


def test_a_negative_edit_price_is_rejected(client):
    r = client.post("/scanner/ath/edit",
                    json={"symbol": "AAA", "price": -5.0, "date": "2026-02-02"})
    assert r.status_code == 422


# ---------------------------------------------------------------- universe
def test_uploading_a_universe_merges_and_reports(client):
    _reset()
    xlsx = _xlsx(pd.DataFrame({"SYMBOL": ["RELIANCE", "TCS"]}))
    r = client.post("/scanner/universe/upload",
                    files={"file": ("u.xlsx", xlsx,
                                    "application/vnd.ms-excel")})
    body = r.json()
    assert body["inserted"] == 2
    assert body["total"] == 2
    assert body["feed_available"] is False


def test_a_second_upload_reports_missing_symbols_without_deleting(client):
    """A truncated export must not silently shrink the scan list."""
    _reset()
    client.post("/scanner/universe/upload", files={"file": (
        "u.xlsx", _xlsx(pd.DataFrame({"SYMBOL": ["AAA", "BBB"]})),
        "application/vnd.ms-excel")})
    body = client.post("/scanner/universe/upload", files={"file": (
        "u2.xlsx", _xlsx(pd.DataFrame({"SYMBOL": ["AAA"]})),
        "application/vnd.ms-excel")}).json()
    assert body["missing"] == ["BBB"]
    assert len(client.get("/scanner/universe").json()["rows"]) == 2


def test_a_file_with_no_symbol_column_is_rejected_with_a_reason(client):
    _reset()
    xlsx = _xlsx(pd.DataFrame({"price": [1], "date": ["2026-01-01"]}))
    r = client.post("/scanner/universe/upload",
                    files={"file": ("bad.xlsx", xlsx,
                                    "application/vnd.ms-excel")})
    assert r.status_code == 400
    assert "symbol column" in r.json()["detail"]


def test_a_non_excel_file_is_rejected(client):
    r = client.post("/scanner/universe/upload",
                    files={"file": ("x.txt", b"not a spreadsheet",
                                    "text/plain")})
    assert r.status_code == 400


def test_upload_resolves_isins_when_the_feed_is_cached(client):
    """The join that makes the profit column work."""
    _reset()
    profit.store_identifiers(pd.DataFrame([{
        "ISIN": "INE002A01018", "NSE CODE": "RELIANCE", "ACCORD CODE": "1",
        "COMPANY NAME": "Reliance", "TRADING STATUS": "Active"}]))
    body = client.post("/scanner/universe/upload", files={"file": (
        "u.xlsx", _xlsx(pd.DataFrame({"SYMBOL": ["RELIANCE", "NOTREAL"]})),
        "application/vnd.ms-excel")}).json()
    assert body["feed_available"] is True
    assert body["resolved"] == 1
    assert [u["symbol"] for u in body["unresolved"]] == ["NOTREAL"]


def test_a_manual_mapping_survives_the_next_upload(client):
    """Otherwise the nine renames become nine chores every single time."""
    _reset()
    client.post("/scanner/universe/upload", files={"file": (
        "u.xlsx", _xlsx(pd.DataFrame({"SYMBOL": ["TATAMOTORS"]})),
        "application/vnd.ms-excel")})
    client.post("/scanner/universe/map",
                json={"symbol": "TATAMOTORS", "isin": "INE1TAE01010"})
    client.post("/scanner/universe/upload", files={"file": (
        "u2.xlsx", _xlsx(pd.DataFrame({"SYMBOL": ["TATAMOTORS"]})),
        "application/vnd.ms-excel")})
    row = store.cursor().execute(
        "SELECT isin, resolution FROM universe WHERE symbol='TATAMOTORS'"
    ).fetchone()
    assert row == ("INE1TAE01010", "manual")


def test_removal_requires_an_explicit_list(client):
    assert client.post("/scanner/universe/remove",
                       json={"symbols": []}).status_code == 400


# ------------------------------------------------------------------ profit
def test_profit_status_reports_emptiness_honestly(client):
    _reset()
    body = client.get("/scanner/profit/status").json()
    assert body["companies"] == 0
    assert body["fetched_at"] is None


def test_a_failing_profit_fetch_returns_502_not_500(client, monkeypatch):
    """An upstream outage is not our bug, and the UI needs to say so."""
    def boom():
        raise profit.ProfitFetchError("endpoint unreachable")

    monkeypatch.setattr(profit, "refresh_from_api", boom)
    r = client.post("/scanner/profit/refresh")
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"]


# ------------------------------------------------------------ result dates
def test_result_dates_endpoint_returns_a_row_per_symbol(client):
    _reset()
    from datetime import date
    from tm750.scanner import result_dates
    result_dates.store_date("AAA", date(2026, 7, 24), "announced")
    body = client.get("/scanner/result-dates",
                      params={"symbols": "AAA,BBB"}).json()["rows"]
    assert body["AAA"]["result_date"] == "2026-07-24"
    assert body["BBB"]["result_date"] is None


# ------------------------------------------------------------------ reset
def test_reset_without_confirmation_is_rejected(client):
    """Must never fire from a bare POST -- only an explicit confirm."""
    r = client.post("/scanner/universe/reset", json={"confirm": False})
    assert r.status_code == 400


def test_reset_with_confirmation_clears_the_universe(client):
    _reset()
    client.post("/scanner/universe/upload", files={"file": (
        "u.xlsx", _xlsx(pd.DataFrame({"SYMBOL": ["AAA", "BBB"]})),
        "application/vnd.ms-excel")})
    r = client.post("/scanner/universe/reset", json={"confirm": True})
    assert r.json()["removed"] == 2
    assert client.get("/scanner/universe").json()["rows"] == []


# ------------------------------------------------------------- ath reset
def test_ath_reset_without_confirmation_is_rejected(client):
    r = client.post("/scanner/ath/reset", json={"confirm": False})
    assert r.status_code == 400


def test_ath_reset_clears_ath_but_preserves_events_by_default(client):
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    r = client.post("/scanner/ath/reset", json={"confirm": True})
    body = r.json()
    assert body["ath_rows"] == 1
    assert body["events_cleared"] == 0


def test_suspected_repeat_halvings_endpoint_responds(client):
    _reset()
    r = client.get("/scanner/ath/suspected-repeat-halvings")
    assert r.status_code == 200
    assert "rows" in r.json()
