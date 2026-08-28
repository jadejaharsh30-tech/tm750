"""Scan orchestration. Network calls are stubbed; the logic is real."""
from __future__ import annotations

import pandas as pd
import pytest

from tm750.scanner import prices, profit, result_dates, scan, store, universe


def _reset():
    store.init_schema()
    cur = store.cursor()
    for t in ["ath", "ath_events", "universe", "profit", "scan_results",
              "result_dates", "feed_identifiers"]:
        cur.execute(f"DELETE FROM {t}")


# ----------------------------------------------------------------- status
def test_status_round_trips():
    _reset()
    scan.set_status(True, 3, 17, "Batch 3/17: Downloading prices...")
    s = scan.get_status()
    assert s["running"] is True
    assert s["progress"] == 3
    assert s["total"] == 17
    assert s["message"].startswith("Batch 3/17")


def test_status_survives_a_fresh_connection():
    """Persisted, not in-memory: a --reload restart mid-scan must not leave
    the UI spinning forever."""
    _reset()
    scan.set_status(True, 5, 17, "halfway")
    store.close_all()
    assert scan.get_status()["progress"] == 5


# ---------------------------------------------------------------- phase 0
def test_phase_zero_clears_today_ath_before_anything_else():
    """Guards against a skipped EOD Sync bleeding yesterday's intraday
    values into today's comparison."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 999.0, NULL, NULL)")
    scan.clear_today()
    assert store.cursor().execute(
        "SELECT today_ath FROM ath WHERE symbol='AAA'").fetchone()[0] is None


# ------------------------------------------------------------ split ratio
def test_split_ratio_ignores_zero_rows():
    idx = pd.date_range("2026-01-01", periods=4)
    assert scan._split_ratio(pd.Series([0.0, 0.0, 2.0, 0.0], index=idx)) == 2.0
    assert scan._split_ratio(pd.Series([0.0] * 4, index=idx)) is None
    assert scan._split_ratio(None) is None


def test_split_ratio_compounds_multiple_splits_in_one_window():
    idx = pd.date_range("2026-01-01", periods=4)
    assert scan._split_ratio(pd.Series([2.0, 0.0, 5.0, 0.0], index=idx)) == 10.0


# ---------------------------------------------------------------- phase 2
def _fake_batch(monkeypatch, frames):
    """Stub download_batch with a dict of ticker -> (highs, closes, splits)."""
    def fake(tickers, period="5d", interval="1d", retries=3):
        idx = pd.date_range("2026-08-24", periods=3)
        cols, data = [], {}
        for t in (tickers if isinstance(tickers, list) else [tickers]):
            if t not in frames:
                continue
            highs, closes, splits = frames[t]
            for field, series in [("High", highs), ("Close", closes),
                                  ("Stock Splits", splits)]:
                cols.append((field, t))
                data[(field, t)] = series
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data, index=idx)
        df.columns = pd.MultiIndex.from_tuples(cols)
        return df
    monkeypatch.setattr(prices, "download_batch", fake)


def test_find_hits_keeps_only_symbols_at_or_above_their_trigger(monkeypatch):
    _reset()
    cur = store.cursor()
    cur.execute("INSERT INTO ath VALUES ('WINNER', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    cur.execute("INSERT INTO ath VALUES ('LOSER', 500.0, DATE '2026-01-01', NULL, NULL, NULL)")

    _fake_batch(monkeypatch, {
        "WINNER.NS": ([90.0, 95.0, 120.0], [88.0, 94.0, 118.0], [0.0, 0.0, 0.0]),
        "LOSER.NS": ([100.0, 110.0, 120.0], [99.0, 109.0, 119.0], [0.0, 0.0, 0.0]),
    })
    rows = [{"symbol": "WINNER", "exchange": "NSE", "isin": None},
            {"symbol": "LOSER", "exchange": "NSE", "isin": None}]
    hits, failed = scan.find_hits(rows)
    assert [h["symbol"] for h in hits] == ["WINNER"]
    assert hits[0]["today_high"] == 120.0
    assert hits[0]["prev_close"] == 94.0


def test_an_equal_high_still_counts_as_a_hit(monkeypatch):
    """The >= is what lets an already-promoted name resurface on a re-scan."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('EVEN', 120.0, DATE '2026-01-01', NULL, NULL, NULL)")
    _fake_batch(monkeypatch, {
        "EVEN.NS": ([100.0, 110.0, 120.0], [99.0, 109.0, 119.0], [0.0, 0.0, 0.0])})
    hits, _ = scan.find_hits([{"symbol": "EVEN", "exchange": "NSE", "isin": None}])
    assert len(hits) == 1


def test_a_split_repairs_the_trigger_before_the_comparison(monkeypatch):
    """Without repair the trigger stays in pre-split rupees and the symbol
    can never hit ATH again -- it vanishes from the scanner silently."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('TRENT', 8235.0, DATE '2025-12-30', NULL, NULL, NULL)")
    _fake_batch(monkeypatch, {
        "TRENT.NS": ([8200.0, 5500.0, 5600.0], [8100.0, 5450.0, 5590.0],
                     [0.0, 1.5, 0.0])})
    hits, _ = scan.find_hits([{"symbol": "TRENT", "exchange": "NSE", "isin": None}])
    assert len(hits) == 1
    assert round(hits[0]["trigger"], 0) == 5490.0

    ev = store.cursor().execute(
        "SELECT source FROM ath_events WHERE symbol='TRENT'").fetchone()
    assert ev[0] == "split"


def test_a_symbol_missing_from_the_response_is_reported_not_skipped(monkeypatch):
    """Silent skips are how a delisted name hides for months."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('GHOST', 10.0, DATE '2026-01-01', NULL, NULL, NULL)")
    _fake_batch(monkeypatch, {"OTHER.NS": ([1.0], [1.0], [0.0])})
    hits, failed = scan.find_hits(
        [{"symbol": "GHOST", "exchange": "NSE", "isin": None}])
    assert hits == []
    assert "GHOST.NS" in failed


def test_a_symbol_without_a_trigger_is_not_a_hit(monkeypatch):
    """Unseeded symbols must not report a spurious all-time high."""
    _reset()
    _fake_batch(monkeypatch, {
        "NEW.NS": ([10.0, 20.0, 30.0], [9.0, 19.0, 29.0], [0.0, 0.0, 0.0])})
    hits, _ = scan.find_hits([{"symbol": "NEW", "exchange": "NSE", "isin": None}])
    assert hits == []


# --------------------------------------------------------- phase 3 and 3b
def test_analyse_attaches_the_profit_verdict(monkeypatch):
    _reset()
    profit.store_summary(
        pd.DataFrame([{"ISIN": "INE1",
                       **{f"QL{i}": 0.0 for i in range(1, 49)},
                       "QL1": 100.0, "QL2": 90.0, "QL3": 80.0, "QL4": 70.0}]),
        pd.DataFrame([{"ISIN": "INE1", "NSE CODE": "AAA",
                       "TRADING STATUS": "Active", "TTM": 340.0,
                       **{f"FYL{i}": 0.0 for i in range(1, 16)},
                       "FYL1": 300.0}]))
    monkeypatch.setattr(prices, "download_batch",
                        lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(result_dates, "refresh_for", lambda *a, **k: None)

    out = scan.analyse([{"symbol": "AAA", "exchange": "NSE", "isin": "INE1",
                         "ticker": "AAA.NS", "today_high": 120.0,
                         "today_close": 118.0, "prev_close": 100.0,
                         "trigger": 100.0}])
    assert out[0]["profit_state"] == "at_ath"
    assert out[0]["green_candle"] == "Y"
    assert out[0]["close_gt_ath"] == "Y"
    assert out[0]["ath_outperformance"] == "N/A"   # no benchmark data


def test_a_symbol_outside_the_profit_universe_reads_no_data(monkeypatch):
    """It has not failed the test -- it was never given it."""
    _reset()
    monkeypatch.setattr(prices, "download_batch",
                        lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(result_dates, "refresh_for", lambda *a, **k: None)
    out = scan.analyse([{"symbol": "GROWW", "exchange": "NSE", "isin": None,
                         "ticker": "GROWW.NS", "today_high": 120.0,
                         "today_close": 118.0, "prev_close": 100.0,
                         "trigger": 100.0}])
    assert out[0]["profit_state"] == "no_data"


def test_analyse_writes_today_ath_but_never_the_trigger(monkeypatch):
    """A scan must not promote. Only EOD Sync moves ath_price."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    monkeypatch.setattr(prices, "download_batch",
                        lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(result_dates, "refresh_for", lambda *a, **k: None)
    scan.analyse([{"symbol": "AAA", "exchange": "NSE", "isin": None,
                   "ticker": "AAA.NS", "today_high": 120.0,
                   "today_close": 118.0, "prev_close": 100.0,
                   "trigger": 100.0}])
    row = store.cursor().execute(
        "SELECT ath_price, today_ath FROM ath WHERE symbol='AAA'").fetchone()
    assert row == (100.0, 120.0)


def test_a_screener_failure_never_fails_the_scan(monkeypatch):
    _reset()
    monkeypatch.setattr(prices, "download_batch",
                        lambda *a, **k: pd.DataFrame())

    def boom(*a, **k):
        raise RuntimeError("screener down")

    monkeypatch.setattr(result_dates, "refresh_for", boom)
    out = scan.analyse([{"symbol": "AAA", "exchange": "NSE", "isin": None,
                         "ticker": "AAA.NS", "today_high": 120.0,
                         "today_close": 118.0, "prev_close": 100.0,
                         "trigger": 100.0}])
    assert len(out) == 1


# ---------------------------------------------------------------- results
def _result_row(symbol, **over):
    row = {"symbol": symbol, "new_ath_price": 120.0, "trigger_price": 100.0,
           "green_candle": "Y", "close_gt_ath": "Y",
           "ath_outperformance": "Y", "current_rs": 1.0, "ath_rs": 1.0,
           "profit_state": "at_ath", "profit_stale": False,
           "result_date": None, "stop_loss": None}
    row.update(over)
    return row


def test_results_are_written_atomically(monkeypatch):
    """A crash mid-write must leave yesterday's table intact, not blank it.
    The reference app DELETEs then INSERTs, so a crash between the two loses
    everything."""
    _reset()
    scan.save_results([_result_row("OLD")])

    def boom(*a, **k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(scan, "_insert_results", boom)
    with pytest.raises(RuntimeError):
        scan.save_results([_result_row("NEW")])

    assert store.cursor().execute(
        "SELECT symbol FROM scan_results").fetchall() == [("OLD",)]


def test_price_equality_alone_does_not_flag_post_sync():
    """Superseded by the event-log check below. NEW ATH == TRIGGER is NOT
    sufficient evidence of a sync -- a symbol seeded today has that too."""
    _reset()
    scan.save_results([_result_row("AAA", trigger_price=120.0,
                                   close_gt_ath="N")])
    assert scan.load_results()["post_sync"] is False


def test_a_normal_scan_is_not_flagged_post_sync():
    _reset()
    scan.save_results([_result_row("AAA")])
    assert scan.load_results()["post_sync"] is False


def test_load_results_exposes_the_profit_fetch_timestamp():
    _reset()
    profit.store_summary(
        pd.DataFrame([{"ISIN": "INE1",
                       **{f"QL{i}": 0.0 for i in range(1, 49)},
                       "QL1": 100.0, "QL2": 90.0, "QL3": 80.0, "QL4": 70.0}]),
        pd.DataFrame([{"ISIN": "INE1", "NSE CODE": "AAA",
                       "TRADING STATUS": "Active", "TTM": 340.0,
                       **{f"FYL{i}": 0.0 for i in range(1, 16)},
                       "FYL1": 300.0}]))
    scan.save_results([_result_row("AAA")])
    assert scan.load_results()["profit_fetched_at"] is not None


# -------------------------------------------------------------------- run
def test_an_empty_universe_says_so_instead_of_crashing():
    _reset()
    out = scan.run()
    assert out["hits"] == 0
    assert "upload" in scan.get_status()["message"].lower()
    assert scan.get_status()["running"] is False


def test_a_failure_always_clears_the_running_flag(monkeypatch):
    """Otherwise the UI spins forever and the next scan is refused as busy."""
    _reset()
    universe.save([{"symbol": "AAA", "exchange": "NSE", "isin": None,
                    "accord_code": None, "resolution": "unresolved",
                    "ignored": False, "ignore_reason": None,
                    "source_file": "u.xlsx"}])

    def boom(*a, **k):
        raise RuntimeError("yfinance exploded")

    # Seeding would reach for yfinance first; the failure under test is
    # phase 2, so stub phase 1 out.
    monkeypatch.setattr(scan, "seed_missing", lambda rows: 0)
    monkeypatch.setattr(scan, "find_hits", boom)
    with pytest.raises(RuntimeError):
        scan.run()
    assert scan.get_status()["running"] is False
    assert "failed" in scan.get_status()["message"].lower()


def test_a_malformed_ticker_never_aborts_the_batch(monkeypatch):
    """The AKZOINDIA regression, at the scan level. One symbol's response
    being unreadable -- for any reason, not just the ones anticipated in the
    code -- must mark that symbol failed and keep processing the rest."""
    _reset()
    cur = store.cursor()
    cur.execute("INSERT INTO ath VALUES ('GOOD', 5.0, DATE '2026-01-01', NULL, NULL, NULL)")
    cur.execute("INSERT INTO ath VALUES ('AKZOINDIA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")

    idx = pd.date_range("2026-08-20", periods=3)
    partial = pd.DataFrame({
        ("High", "GOOD.NS"): [10.0, 11.0, 12.0],
        ("Close", "GOOD.NS"): [9.5, 10.5, 11.5],
        ("Volume", "AKZOINDIA.NS"): [0, 0, 0],
    }, index=idx)
    partial.columns = pd.MultiIndex.from_tuples(partial.columns)

    monkeypatch.setattr(prices, "download_batch", lambda *a, **k: partial)
    hits, failed = scan.find_hits(
        [{"symbol": "GOOD", "exchange": "NSE", "isin": None},
         {"symbol": "AKZOINDIA", "exchange": "NSE", "isin": None}])

    assert [h["symbol"] for h in hits] == ["GOOD"]
    assert "AKZOINDIA.NS" in failed


# --------------------------------------------------- TDPOWERSYS regression
def test_a_split_already_reflected_in_a_freshly_seeded_trigger_is_not_repaired(monkeypatch):
    """A trigger with last_split_check already at or after the split's own
    date is current -- exactly what seed() sets on a symbol whose full
    history already incorporates the split."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES "
        "('TDPOWERSYS', 793.50, DATE '2026-08-24', NULL, DATE '2026-08-26', NULL)")
    _fake_batch(monkeypatch, {
        "TDPOWERSYS.NS": ([780.0, 790.0, 793.50], [775.0, 785.0, 790.0],
                          [0.0, 0.0, 2.0])})   # split lands on 2026-08-26
    scan.find_hits([{"symbol": "TDPOWERSYS", "exchange": "NSE", "isin": None}])
    price = store.cursor().execute(
        "SELECT ath_price FROM ath WHERE symbol='TDPOWERSYS'").fetchone()[0]
    assert price == 793.50


def test_the_same_split_seen_across_two_separate_scans_only_repairs_once(monkeypatch):
    """The actual TDPOWERSYS bug, reproduced end to end: a 5-day lookback
    window keeps showing the same split for several days after it happened,
    so this proves running the scan TWICE -- not once -- doesn't halve the
    price a second time. This is the case the first attempted fix missed:
    it compared against ath_date, which apply_split never updates, so
    nothing recorded that the split had already been handled."""
    _reset()
    # Starts with NO last_split_check -- simulates a trigger seeded before
    # this column existed, or before the split had happened at all.
    store.cursor().execute(
        "INSERT INTO ath VALUES "
        "('TDPOWERSYS', 793.50, DATE '2026-08-18', NULL, NULL, NULL)")
    window = {"TDPOWERSYS.NS": ([780.0, 790.0, 793.50],
                                [775.0, 785.0, 790.0], [0.0, 0.0, 2.0])}
    _fake_batch(monkeypatch, window)

    # First scan: split is new, repair fires once. 793.50 -> 396.75.
    scan.find_hits([{"symbol": "TDPOWERSYS", "exchange": "NSE", "isin": None}])
    after_first = store.cursor().execute(
        "SELECT ath_price FROM ath WHERE symbol='TDPOWERSYS'").fetchone()[0]
    assert after_first == 396.75

    # Second scan, SAME split still visible in a fresh 5-day fetch (exactly
    # what happens for days after the ex-date). Must NOT halve again.
    _fake_batch(monkeypatch, window)
    scan.find_hits([{"symbol": "TDPOWERSYS", "exchange": "NSE", "isin": None}])
    after_second = store.cursor().execute(
        "SELECT ath_price FROM ath WHERE symbol='TDPOWERSYS'").fetchone()[0]
    assert after_second == 396.75


def test_a_manual_edit_is_not_immediately_undone_by_the_same_stale_split(monkeypatch):
    """A human correcting a price by hand must not have that correction
    silently reversed by the very next scan -- exactly what happened when
    manual edits kept getting halved again in the live app."""
    _reset()
    from tm750.scanner import prices
    store.cursor().execute(
        "INSERT INTO ath VALUES "
        "('TDPOWERSYS', 396.75, DATE '2026-08-18', NULL, NULL, NULL)")
    prices.manual_edit("TDPOWERSYS", price=798.85, date="2026-08-18")

    _fake_batch(monkeypatch, {
        "TDPOWERSYS.NS": ([780.0, 790.0, 793.50], [775.0, 785.0, 790.0],
                          [0.0, 0.0, 2.0])})
    scan.find_hits([{"symbol": "TDPOWERSYS", "exchange": "NSE", "isin": None}])
    price = store.cursor().execute(
        "SELECT ath_price FROM ath WHERE symbol='TDPOWERSYS'").fetchone()[0]
    assert price == 798.85


def test_a_split_predating_the_stored_trigger_still_repairs_it(monkeypatch):
    """The ordinary case must keep working: a trigger seeded long ago,
    genuinely before this split happened, needs adjusting."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('OLDCO', 800.0, DATE '2020-01-01', NULL, NULL, NULL)")
    _fake_batch(monkeypatch, {
        "OLDCO.NS": ([390.0, 395.0, 400.0], [388.0, 392.0, 398.0],
                    [0.0, 0.0, 2.0])})
    scan.find_hits([{"symbol": "OLDCO", "exchange": "NSE", "isin": None}])
    price = store.cursor().execute(
        "SELECT ath_price FROM ath WHERE symbol='OLDCO'").fetchone()[0]
    assert price == 400.0


def test_an_ath_made_on_the_split_day_itself_is_still_detected(monkeypatch):
    """The third edge case: a genuine new high occurring on the exact day of
    the split. The stale (pre-split) trigger must repair correctly, and the
    day's own high must then be compared against the REPAIRED value."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('NEWHIGH', 780.0, DATE '2020-01-01', NULL, NULL, NULL)")
    # Old trigger 780 -> repairs to 390. Today's high of 395 clears it.
    _fake_batch(monkeypatch, {
        "NEWHIGH.NS": ([380.0, 388.0, 395.0], [378.0, 385.0, 393.0],
                      [0.0, 0.0, 2.0])})
    hits, _ = scan.find_hits(
        [{"symbol": "NEWHIGH", "exchange": "NSE", "isin": None}])
    assert len(hits) == 1
    assert hits[0]["trigger"] == 390.0
    assert hits[0]["today_high"] == 395.0


# ------------------------------------------------- post-sync banner logic
def test_a_freshly_seeded_symbol_is_not_reported_as_post_sync():
    """The banner bug. A symbol whose lifetime high was seeded TODAY has
    NEW ATH == TRIGGER already, because full-history seeding includes
    today's bar. Inferring "post-sync" from that equality wrongly told the
    user a sync had happened when EOD Sync is a manual button they had never
    pressed. Only a real logged 'sync' event counts."""
    _reset()
    scan.save_results([_result_row("SEEDED", new_ath_price=100.0,
                                   trigger_price=100.0, close_gt_ath="N")])
    assert scan.load_results()["post_sync"] is False


def test_post_sync_is_reported_after_an_actual_sync():
    _reset()
    from tm750.scanner import prices
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 120.0, NULL, NULL)")
    prices.promote(["AAA"])          # logs a real 'sync' event, dated today
    scan.save_results([_result_row("AAA", new_ath_price=120.0,
                                   trigger_price=120.0, close_gt_ath="N")])
    assert scan.load_results()["post_sync"] is True
