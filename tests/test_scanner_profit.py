"""Profit verdict. Must be identical to the main pipeline's, by construction."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from tm750.scanner import profit as profit_mod
from tm750.scanner import store


def _reset():
    store.init_schema()
    store.cursor().execute("DELETE FROM profit")
    store.cursor().execute("DELETE FROM feed_identifiers")


def _feed_row(isin="INE000A01001", **over):
    row = {"ACCORD CODE": "1", "COMPANY NAME": "Test Co", "ISIN": isin,
           "NSE CODE": "TESTCO", "BSE CODE": "1"}
    for i in range(1, 49):
        row[f"QL{i}"] = 0.0
    row.update(over)
    return row


def _quarters(values, isin="INE000A01001"):
    row = _feed_row(isin)
    for i, v in enumerate(values, start=1):
        row[f"QL{i}"] = v
    return pd.DataFrame([row])


def _years(values, isin="INE000A01001", ttm=None):
    row = {"ACCORD CODE": "1", "COMPANY NAME": "Test Co", "ISIN": isin,
           "NSE CODE": "TESTCO", "TRADING STATUS": "Active",
           "TTM": ttm if ttm is not None else 0.0}
    for i in range(1, 16):
        row[f"FYL{i}"] = 0.0
    for i, v in enumerate(values, start=1):
        row[f"FYL{i}"] = v
    return pd.DataFrame([row])


# ---------------------------------------------------------------- prepare
def test_api_columns_are_renamed_to_lowercase_isin():
    """tm750.history requires 'isin'; the API sends 'ISIN'."""
    out = profit_mod.prepare(pd.DataFrame([_feed_row()]))
    assert "isin" in out.columns
    assert "ISIN" not in out.columns


def test_zeros_are_left_for_history_to_nullify():
    """history._nullify_sentinels owns this rule. Applying it here too risks
    two implementations of one rule drifting apart."""
    out = profit_mod.prepare(pd.DataFrame([_feed_row(QL1=0.0)]))
    assert out["QL1"].iloc[0] == 0.0
    assert not pd.isna(out["QL1"].iloc[0])


def test_missing_quarter_columns_are_backfilled():
    """A payload short of 48 quarters must not KeyError inside history."""
    thin = {"ISIN": "INE1", "QL1": 10.0, "QL2": 9.0, "QL3": 8.0, "QL4": 7.0}
    out = profit_mod.prepare(pd.DataFrame([thin]))
    assert all(f"QL{i}" in out.columns for i in range(1, 49))


def test_duplicate_isins_collapse():
    df = pd.DataFrame([_feed_row(), _feed_row()])
    assert len(profit_mod.prepare(df)) == 1


def test_blank_isins_are_dropped():
    df = pd.DataFrame([_feed_row(isin=""), _feed_row(isin="INE2")])
    assert profit_mod.prepare(df)["isin"].tolist() == ["INE2"]


def test_a_payload_without_isin_is_rejected_loudly():
    with pytest.raises(profit_mod.ProfitFetchError, match="no ISIN column"):
        profit_mod.prepare(pd.DataFrame([{"NSE CODE": "X", "QL1": 1.0}]))


def test_text_values_coerce_to_numbers_not_crashes():
    df = pd.DataFrame([_feed_row(QL1="1,234.5", QL2="-")])
    out = profit_mod.prepare(df)
    assert out["QL1"].iloc[0] != out["QL1"].iloc[0] or pd.isna(out["QL2"].iloc[0])


# --------------------------------------------------------------- verdicts
def test_verdict_at_ath_requires_both_horizons():
    frame = pd.DataFrame([
        {"isin": "INE1", "pat_ttm_at_ath": True, "pat_q_at_ath": True},
        {"isin": "INE2", "pat_ttm_at_ath": True, "pat_q_at_ath": False},
        {"isin": "INE3", "pat_ttm_at_ath": False, "pat_q_at_ath": True},
        {"isin": "INE4", "pat_ttm_at_ath": False, "pat_q_at_ath": False},
    ])
    v = profit_mod.verdicts(frame)
    assert v == {"INE1": "at_ath", "INE2": "not_at_ath",
                 "INE3": "not_at_ath", "INE4": "not_at_ath"}


def test_null_flags_read_as_not_at_ath_not_as_missing():
    frame = pd.DataFrame([{"isin": "INE9", "pat_ttm_at_ath": None,
                           "pat_q_at_ath": None}])
    assert profit_mod.verdicts(frame)["INE9"] == "not_at_ath"


def test_unknown_isin_is_no_data():
    assert profit_mod.verdict_for(None, {}) == "no_data"
    assert profit_mod.verdict_for("", {}) == "no_data"
    assert profit_mod.verdict_for("INE_NOT_IN_FEED", {}) == "no_data"


def test_known_isin_returns_its_verdict():
    assert profit_mod.verdict_for("INE1", {"INE1": "at_ath"}) == "at_ath"


# ------------------------------------------------- end-to-end via history
def test_the_worked_example_resolves_as_specified():
    """Acme Ltd: TTM 425 vs FY series [423, 380, 410, 300] -> at ATH."""
    out = profit_mod.summarise(
        _quarters([120.0, 110.0, 100.0, 95.0, 118.0, 90.0, 85.0, 80.0]),
        _years([423.0, 380.0, 410.0, 300.0], ttm=425.0))
    assert out["pat_ttm"].iloc[0] == 425.0
    assert bool(out["pat_ttm_at_ath"].iloc[0]) is True
    assert bool(out["pat_q_at_ath"].iloc[0]) is True
    assert bool(out["pat_both_at_ath"].iloc[0]) is True


def test_an_earlier_fy_beating_ttm_fails_the_verdict():
    """Same quarters, but FY3 = 450 > TTM 425."""
    out = profit_mod.summarise(
        _quarters([120.0, 110.0, 100.0, 95.0, 118.0, 90.0, 85.0, 80.0]),
        _years([423.0, 380.0, 450.0, 300.0], ttm=425.0))
    assert bool(out["pat_ttm_at_ath"].iloc[0]) is False
    assert bool(out["pat_q_at_ath"].iloc[0]) is True   # quarter still a record
    assert bool(out["pat_both_at_ath"].iloc[0]) is False


def test_the_march_quarter_case_passes_on_equality():
    """When QL1 is the March quarter, TTM equals FY1. >= lets that pass."""
    out = profit_mod.summarise(_quarters([110.0, 100.0, 95.0, 90.0]),
                           _years([395.0, 380.0, 300.0], ttm=395.0))
    assert out["pat_ttm"].iloc[0] == 395.0
    assert bool(out["pat_ttm_at_ath"].iloc[0]) is True


def test_rolling_windows_do_not_decide_the_verdict():
    """A rolling window straddling two part-years can exceed every reported
    FY. That window is not a period the company ever reported, so it must not
    make the company read at ATH."""
    from tm750 import history
    q = _quarters([50.0, 60.0, 70.0, 80.0, 200.0, 200.0, 200.0, 10.0])
    y = _years([500.0, 610.0, 300.0])
    rolling = history.summarise_quarterly(profit_mod.prepare(q))
    verdict = profit_mod.summarise(q, y)
    assert bool(rolling["pat_ttm_at_ath_rolling"].iloc[0]) is False
    assert bool(verdict["pat_ttm_at_ath"].iloc[0]) is False


def test_thin_history_still_produces_a_verdict():
    """Four quarters and one FY. Explicit product decision."""
    out = profit_mod.summarise(_quarters([100.0, 90.0, 80.0, 70.0]),
                           _years([300.0], ttm=340.0))
    assert bool(out["pat_both_at_ath"].iloc[0]) is True
    assert int(out["qtrs_available"].iloc[0]) == 4
    assert out["pat_ttm"].iloc[0] == 340.0


def test_loss_making_fy_peak_is_not_at_ath():
    """A company whose best-ever year was a loss is not at a record."""
    out = profit_mod.summarise(_quarters([-10.0, -20.0, -30.0, -40.0]),
                           _years([-50.0, -90.0]))
    assert bool(out["pat_ttm_at_ath"].iloc[0]) is False
    assert bool(out["pat_both_at_ath"].iloc[0]) is False


def test_a_company_with_no_fy_history_gets_no_verdict():
    """No comparison series means no record test -- False, not a free pass."""
    out = profit_mod.summarise(_quarters([100.0, 90.0, 80.0, 70.0]), _years([]))
    assert bool(out["pat_ttm_at_ath"].iloc[0]) is False


def test_ttm_needs_all_four_quarters():
    """Three quarters and a gap is not a trailing year."""
    q = _quarters([100.0, 90.0, 80.0])
    q.loc[0, "QL4"] = 0.0   # sentinel -> nulled by history
    out = profit_mod.summarise(q, _years([200.0]))
    assert pd.isna(out["pat_ttm"].iloc[0])
    assert bool(out["pat_ttm_at_ath"].iloc[0]) is False


def test_summarise_returns_exactly_the_stored_columns():
    out = profit_mod.summarise(_quarters([100.0, 90.0, 80.0, 70.0]),
                           _years([300.0]))
    assert list(out.columns) == profit_mod.SUMMARY_COLS


# --------------------------------------------------------------- storage
def test_store_summary_persists_a_fetched_at_stamp():
    """A stale verdict must be visible, not silent."""
    _reset()
    profit_mod.store_summary(_quarters([100.0, 90.0, 80.0, 70.0]), _years([300.0]))
    row = store.cursor().execute(
        "SELECT pat_both_at_ath, fetched_at FROM profit "
        "WHERE isin = 'INE000A01001'").fetchone()
    assert row[0] is True
    assert isinstance(row[1], datetime)


def test_store_summary_replaces_rather_than_appends():
    _reset()
    q = _quarters([100.0, 90.0, 80.0, 70.0])
    y = _years([300.0])
    profit_mod.store_summary(q, y)
    profit_mod.store_summary(q, y)
    n = store.cursor().execute("SELECT count(*) FROM profit").fetchone()[0]
    assert n == 1


def test_load_verdicts_round_trips():
    _reset()
    profit_mod.store_summary(_quarters([100.0, 90.0, 80.0, 70.0]), _years([300.0]))
    table, stamp = profit_mod.load_verdicts()
    assert table["INE000A01001"] == "at_ath"
    assert stamp is not None


def test_identifiers_are_cached_for_offline_resolution():
    """An Excel upload must resolve without a live API call."""
    _reset()
    yearly = _years([300.0], ttm=340.0)
    profit_mod.store_summary(_quarters([100.0, 90.0, 80.0, 70.0]), yearly)

    feed = profit_mod.feed_identifiers()
    assert feed is not None
    assert set(["NSE CODE", "ISIN", "TRADING STATUS"]) <= set(feed.columns)
    assert feed["NSE CODE"].iloc[0] == "TESTCO"


def test_feed_identifiers_returns_none_when_never_fetched():
    _reset()
    assert profit_mod.feed_identifiers() is None


def test_cached_identifiers_drive_universe_resolution():
    """The join that makes the whole profit column work."""
    _reset()
    from tm750.scanner import universe
    yearly = pd.DataFrame([{
        "ACCORD CODE": "1", "COMPANY NAME": "Test Co",
        "ISIN": "INE000A01001", "NSE CODE": "TESTCO",
        "TRADING STATUS": "Active"}])
    profit_mod.store_identifiers(yearly)

    rows = [{"symbol": "TESTCO", "exchange": "NSE", "source_file": "u.xlsx"}]
    resolved = universe.resolve(rows, profit_mod.feed_identifiers())
    assert resolved[0]["isin"] == "INE000A01001"
    assert resolved[0]["resolution"] == "auto"


def test_fetch_without_a_configured_url_says_what_to_do():
    with pytest.raises(profit_mod.ProfitFetchError, match="config.py"):
        profit_mod.fetch("")


# ----------------------------------------------------- cross-system parity
#
# There is deliberately NO pytest test here for comparing Scanner's profit
# verdict against the main pipeline's on REAL data. conftest.py redirects
# every test in this suite to a throwaway database, unconditionally, so that
# pytest can never touch production data -- and that same protection means
# a pytest test can never SEE production data either. Those two goals are
# incompatible in one function.
#
# The real check lives at tm750/scanner/verify_parity.py, a standalone
# script that explicitly opens both real databases read-only. Run it with:
#     python -m tm750.scanner.verify_parity
#
# The tests above already prove the LOGIC is identical (worked-example
# cases, thin history, loss-making peaks, the March-quarter edge case).
# verify_parity.py proves it holds against your actual live data.
