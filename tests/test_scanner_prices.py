"""Split handling. Get this wrong and symbols silently vanish from the
scanner forever, because a pre-split trigger can never be exceeded."""
from __future__ import annotations

import pandas as pd

from tm750.scanner import prices, store


# ------------------------------------------------------------- split maths
def test_factor_is_one_when_there_are_no_splits():
    idx = pd.date_range("2026-01-01", periods=5)
    splits = pd.Series([0.0] * 5, index=idx)
    assert (prices.split_factors(splits) == 1.0).all()


def test_bars_before_a_split_carry_the_ratio_and_bars_after_do_not():
    idx = pd.date_range("2026-01-01", periods=5)
    splits = pd.Series([0.0, 0.0, 2.0, 0.0, 0.0], index=idx)
    assert list(prices.split_factors(splits)) == [2.0, 2.0, 1.0, 1.0, 1.0]


def test_multiple_splits_compound():
    idx = pd.date_range("2026-01-01", periods=5)
    splits = pd.Series([0.0, 2.0, 0.0, 5.0, 0.0], index=idx)
    assert list(prices.split_factors(splits)) == [10.0, 5.0, 5.0, 1.0, 1.0]


def test_adjusted_high_divides_by_the_factor():
    idx = pd.date_range("2026-01-01", periods=3)
    high = pd.Series([8235.0, 8000.0, 5400.0], index=idx)
    splits = pd.Series([0.0, 0.0, 1.5], index=idx)
    adj = prices.adjust_highs(high, splits)
    assert round(adj.iloc[0], 0) == 5490.0
    assert adj.iloc[2] == 5400.0


def test_ath_from_history_returns_price_and_date_in_current_terms():
    """The TRENT case: a raw pre-split high of 8235 must not become the
    stored ATH, or TRENT never hits an all-time high again."""
    idx = pd.date_range("2025-12-30", periods=4)
    df = pd.DataFrame({"High": [8235.0, 8100.0, 5500.0, 5600.0],
                       "Stock Splits": [0.0, 0.0, 1.5, 0.0]}, index=idx)
    price, when = prices.ath_from_history(df)
    assert round(price, 0) == 5600.0
    assert str(when) == "2026-01-02"


def test_ath_from_history_tolerates_a_missing_splits_column():
    idx = pd.date_range("2026-01-01", periods=3)
    df = pd.DataFrame({"High": [10.0, 30.0, 20.0]}, index=idx)
    price, when = prices.ath_from_history(df)
    assert price == 30.0
    assert str(when) == "2026-01-02"


def test_ath_from_history_returns_none_on_empty_input():
    assert prices.ath_from_history(pd.DataFrame()) == (None, None)


# --------------------------------------------------------------- yfinance
def test_yf_symbol_appends_the_right_suffix():
    assert prices.yf_symbol("RELIANCE", "NSE") == "RELIANCE.NS"
    assert prices.yf_symbol("SOMECO", "BSE") == "SOMECO.BO"


def test_extract_handles_both_multiindex_orientations():
    """yfinance has shipped (field, ticker) and (ticker, field) in different
    versions. Guessing wrong is a KeyError mid-scan."""
    idx = pd.date_range("2026-01-01", periods=2)
    a = pd.DataFrame({("High", "RELIANCE.NS"): [1.0, 2.0]}, index=idx)
    a.columns = pd.MultiIndex.from_tuples(a.columns)
    assert prices.extract(a, "RELIANCE.NS", "High").tolist() == [1.0, 2.0]

    b = pd.DataFrame({("RELIANCE.NS", "High"): [3.0, 4.0]}, index=idx)
    b.columns = pd.MultiIndex.from_tuples(b.columns)
    assert prices.extract(b, "RELIANCE.NS", "High").tolist() == [3.0, 4.0]


def test_extract_handles_flat_columns_for_a_single_ticker():
    idx = pd.date_range("2026-01-01", periods=2)
    flat = pd.DataFrame({"High": [5.0, 6.0]}, index=idx)
    assert prices.extract(flat, "RELIANCE.NS", "High").tolist() == [5.0, 6.0]


def test_extract_returns_none_for_a_missing_ticker():
    idx = pd.date_range("2026-01-01", periods=2)
    a = pd.DataFrame({("High", "TCS.NS"): [1.0, 2.0]}, index=idx)
    a.columns = pd.MultiIndex.from_tuples(a.columns)
    assert prices.extract(a, "RELIANCE.NS", "High") is None


# ------------------------------------------------------------- store ops
def _reset():
    store.init_schema()
    store.cursor().execute("DELETE FROM ath")
    store.cursor().execute("DELETE FROM ath_events")


def test_promote_moves_today_ath_into_the_trigger_and_logs_it():
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 120.0, NULL, NULL)")
    prices.promote(["AAA"], event_date="2026-08-26")
    row = store.cursor().execute(
        "SELECT ath_price, ath_date, today_ath FROM ath WHERE symbol='AAA'"
    ).fetchone()
    assert row[0] == 120.0
    assert str(row[1]) == "2026-08-26"
    assert row[2] is None
    ev = store.cursor().execute(
        "SELECT old_price, new_price, source FROM ath_events WHERE symbol='AAA'"
    ).fetchone()
    assert ev == (100.0, 120.0, "sync")


def test_promote_is_idempotent():
    """Running EOD Sync twice must not double-log or corrupt the trigger."""
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 120.0, NULL, NULL)")
    prices.promote(["AAA"], event_date="2026-08-26")
    prices.promote(["AAA"], event_date="2026-08-26")
    n = store.cursor().execute(
        "SELECT count(*) FROM ath_events WHERE symbol='AAA'").fetchone()[0]
    assert n == 1


def test_promote_clears_today_ath_globally_not_just_for_promoted_names():
    """Otherwise an unpromoted hit carries a stale intraday value into
    tomorrow's comparison."""
    _reset()
    cur = store.cursor()
    cur.execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 120.0, NULL, NULL)")
    cur.execute(
        "INSERT INTO ath VALUES ('BBB', 50.0, DATE '2026-01-01', 60.0, NULL, NULL)")
    prices.promote(["AAA"], event_date="2026-08-26")
    left = cur.execute(
        "SELECT today_ath FROM ath WHERE symbol='BBB'").fetchone()[0]
    assert left is None


def test_promote_ignores_a_today_ath_below_the_trigger():
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', 90.0, NULL, NULL)")
    assert prices.promote(["AAA"], event_date="2026-08-26") == 0
    price = store.cursor().execute(
        "SELECT ath_price FROM ath WHERE symbol='AAA'").fetchone()[0]
    assert price == 100.0


def test_split_repair_rescales_the_trigger_and_logs_the_ratio():
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('TRENT', 8235.0, DATE '2025-12-30', NULL, NULL, NULL)")
    prices.apply_split("TRENT", ratio=1.5, split_date="2026-01-01")
    price = store.cursor().execute(
        "SELECT ath_price FROM ath WHERE symbol='TRENT'").fetchone()[0]
    assert round(price, 0) == 5490.0
    ev = store.cursor().execute(
        "SELECT source, note FROM ath_events WHERE symbol='TRENT'").fetchone()
    assert ev[0] == "split"
    assert "1.5" in ev[1]


def test_split_repair_is_a_noop_for_an_unseeded_symbol():
    _reset()
    assert prices.apply_split("NOSUCH", ratio=2.0, split_date="2026-01-01") is None


def test_manual_edit_is_logged_with_source_manual():
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    prices.manual_edit("AAA", price=110.0, date="2026-02-02")
    ev = store.cursor().execute(
        "SELECT old_price, new_price, source FROM ath_events WHERE symbol='AAA'"
    ).fetchone()
    assert ev == (100.0, 110.0, "manual")


# ------------------------------------------------------ partial-failure bug
def test_extract_ignores_a_ticker_present_under_a_different_field():
    """The AKZOINDIA regression. yfinance can leave a failed symbol partially
    represented -- present under Volume, absent under High -- and checking
    the two MultiIndex levels independently produced a false positive that
    raised a bare KeyError and killed the whole scan. The exact (field,
    ticker) pair must be checked, not each half separately."""
    idx = pd.date_range("2026-08-20", periods=3)
    data = pd.DataFrame({
        ("High", "GOOD.NS"): [10.0, 11.0, 12.0],
        ("Close", "GOOD.NS"): [9.5, 10.5, 11.5],
        ("Volume", "AKZOINDIA.NS"): [0, 0, 0],
    }, index=idx)
    data.columns = pd.MultiIndex.from_tuples(data.columns)

    assert prices.extract(data, "AKZOINDIA.NS", "High") is None
    assert prices.extract(data, "GOOD.NS", "High").tolist() == [10.0, 11.0, 12.0]


# ----------------------------------------------------------------- clear_all
def test_clear_all_wipes_ath_but_preserves_events_by_default():
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    prices.manual_edit("AAA", price=110.0, date="2026-02-02")
    out = prices.clear_all()
    assert out["ath_rows"] == 1
    assert out["events_cleared"] == 0
    assert store.cursor().execute(
        "SELECT count(*) FROM ath").fetchone()[0] == 0
    assert store.cursor().execute(
        "SELECT count(*) FROM ath_events WHERE symbol='AAA'"
    ).fetchone()[0] == 1


def test_clear_all_can_also_wipe_events_when_asked():
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    prices.manual_edit("AAA", price=110.0, date="2026-02-02")
    out = prices.clear_all(wipe_events=True)
    assert out["events_cleared"] >= 1
    assert store.cursor().execute(
        "SELECT count(*) FROM ath_events").fetchone()[0] == 0


def test_suspected_repeat_halvings_flags_symbols_with_two_or_more_split_events():
    _reset()
    store.cursor().execute(
        "INSERT INTO ath VALUES ('BUGGY', 800.0, DATE '2026-01-01', NULL, NULL, NULL)")
    store.cursor().execute(
        "INSERT INTO ath VALUES ('CLEAN', 400.0, DATE '2026-01-01', NULL, NULL, NULL)")
    prices.apply_split("BUGGY", ratio=2.0, split_date="2026-01-01")
    prices.apply_split("BUGGY", ratio=2.0, split_date="2026-01-02")
    prices.apply_split("CLEAN", ratio=2.0, split_date="2026-01-01")

    flagged = {r["symbol"] for r in prices.suspected_repeat_halvings()}
    assert "BUGGY" in flagged
    assert "CLEAN" not in flagged
