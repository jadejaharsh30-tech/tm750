"""Universe upload: parsing, resolution and merge semantics."""
from __future__ import annotations

import pandas as pd
import pytest

from tm750.scanner import store, universe


def _reset():
    store.init_schema()
    store.cursor().execute("DELETE FROM universe")


# ------------------------------------------------------------- normalising
def test_normalise_handles_the_known_variants():
    assert universe.normalise(" reliance ") == "RELIANCE"
    assert universe.normalise("m_m") == "M-M"
    assert universe.normalise("BAJAJ-AUTO") == "BAJAJ-AUTO"


def test_normalise_rejects_empty():
    assert universe.normalise("") is None
    assert universe.normalise("   ") is None
    assert universe.normalise(None) is None


# ----------------------------------------------------------------- parsing
def test_finds_the_symbol_column_under_any_known_header():
    for header in ["SYMBOL", "Symbol", "Ticker", "NSE CODE",
                   "Original Symbol", "TRADINGSYMBOL"]:
        df = pd.DataFrame({header: ["RELIANCE"], "junk": [1]})
        assert universe.find_symbol_column(df) == header


def test_rejects_a_file_with_no_recognisable_symbol_column():
    df = pd.DataFrame({"price": [1], "date": ["2026-01-01"]})
    with pytest.raises(universe.UniverseError, match="No symbol column"):
        universe.find_symbol_column(df)


def test_exchange_defaults_to_nse_when_absent():
    df = pd.DataFrame({"SYMBOL": ["RELIANCE", "TCS"]})
    rows = universe.parse(df, source_file="u.xlsx")
    assert [r["exchange"] for r in rows] == ["NSE", "NSE"]


def test_exchange_column_is_read_when_present():
    """The reference export writes 'NSE (India)', not a bare code."""
    df = pd.DataFrame({"Original Symbol": ["RELIANCE", "SOMEBSE"],
                       "Exchange Found": ["NSE (India)", "BSE"]})
    rows = universe.parse(df, source_file="u.xlsx")
    assert [r["exchange"] for r in rows] == ["NSE", "BSE"]


def test_duplicate_symbols_collapse_to_one_row():
    df = pd.DataFrame({"SYMBOL": ["RELIANCE", "reliance", " RELIANCE "]})
    assert len(universe.parse(df, source_file="u.xlsx")) == 1


def test_blank_rows_are_dropped_not_kept_as_empty_symbols():
    df = pd.DataFrame({"SYMBOL": ["RELIANCE", None, "", "  "]})
    rows = universe.parse(df, source_file="u.xlsx")
    assert [r["symbol"] for r in rows] == ["RELIANCE"]


# -------------------------------------------------------------- resolution
FEED = pd.DataFrame({
    "NSE CODE": ["RELIANCE", "TCS", "", "DEADCO"],
    "ISIN": ["INE002A01018", "INE467B01029", "INE999X01011", "INE000A01001"],
    "ACCORD CODE": ["1", "2", "3", "9"],
    "TRADING STATUS": ["Active", "Active", "Active", "Delisted"],
})


def test_resolution_maps_symbol_to_isin_via_nse_code():
    rows = [{"symbol": "RELIANCE", "exchange": "NSE", "source_file": "u.xlsx"},
            {"symbol": "NOTREAL", "exchange": "NSE", "source_file": "u.xlsx"}]
    by = {r["symbol"]: r for r in universe.resolve(rows, FEED)}
    assert by["RELIANCE"]["isin"] == "INE002A01018"
    assert by["RELIANCE"]["resolution"] == "auto"
    assert by["NOTREAL"]["isin"] is None
    assert by["NOTREAL"]["resolution"] == "unresolved"


def test_dead_statuses_auto_ignore():
    """Replaces the reference app's hardcoded BLACKLIST."""
    rows = [{"symbol": "DEADCO", "exchange": "NSE", "source_file": "u.xlsx"}]
    out = universe.resolve(rows, FEED)[0]
    assert out["ignored"] is True
    assert out["ignore_reason"] == "delisted"


def test_blank_nse_codes_never_match():
    rows = [{"symbol": "", "exchange": "NSE", "source_file": "u.xlsx"}]
    assert universe.resolve(rows, FEED)[0]["isin"] is None


# ------------------------------------------------------------------ merge
def _row(sym, **over):
    base = {"symbol": sym, "exchange": "NSE", "isin": None,
            "accord_code": None, "resolution": "unresolved", "ignored": False,
            "ignore_reason": None, "source_file": "v1.xlsx"}
    base.update(over)
    return base


def test_reupload_merges_and_preserves_manual_mappings():
    """A hand-mapped ISIN must survive the next upload, or the 16 unresolved
    symbols become 16 chores every single time."""
    _reset()
    universe.save([_row("TATAMOTORS")])
    universe.set_manual_isin("TATAMOTORS", "INE1TAE01010")
    universe.save([_row("TATAMOTORS", source_file="v2.xlsx")])
    row = store.cursor().execute(
        "SELECT isin, resolution FROM universe WHERE symbol='TATAMOTORS'"
    ).fetchone()
    assert row == ("INE1TAE01010", "manual")


def test_reupload_reports_removals_instead_of_deleting():
    """A truncated Excel must not silently shrink the universe."""
    _reset()
    universe.save([_row("AAA"), _row("BBB")])
    report = universe.diff_against_upload(["AAA"])
    assert report["missing"] == ["BBB"]
    assert store.cursor().execute(
        "SELECT count(*) FROM universe").fetchone()[0] == 2


def test_removal_happens_only_when_asked_explicitly():
    _reset()
    universe.save([_row("AAA"), _row("BBB")])
    universe.remove(["BBB"])
    assert [r["symbol"] for r in universe.active()] == ["AAA"]


def test_ignored_symbols_are_excluded_from_the_scan_list():
    _reset()
    universe.save([_row("AAA"), _row("DEADCO", ignored=True,
                                     ignore_reason="delisted")])
    assert [r["symbol"] for r in universe.active()] == ["AAA"]


def test_unresolved_list_excludes_ignored_names():
    """SILVERBEES is an ETF -- unresolvable and not worth showing as a chore."""
    _reset()
    universe.save([_row("SILVERBEES", ignored=True,
                        ignore_reason="not_a_company"),
                   _row("LTIM")])
    assert [r["symbol"] for r in universe.unresolved()] == ["LTIM"]


def test_save_counts_inserts_and_updates_separately():
    _reset()
    assert universe.save([_row("AAA")]) == {"inserted": 1, "updated": 0}
    assert universe.save([_row("AAA")]) == {"inserted": 0, "updated": 1}


# --------------------------------------------------------------- clear_all
def test_clear_all_removes_every_symbol_and_reports_the_count():
    _reset()
    universe.save([_row("AAA"), _row("BBB"), _row("CCC")])
    n = universe.clear_all()
    assert n == 3
    assert store.cursor().execute(
        "SELECT count(*) FROM universe").fetchone()[0] == 0


def test_clear_all_does_not_touch_ath_or_profit_data():
    """The reset is scoped to the symbol list -- ATH prices and profit
    verdicts are expensive to rebuild and unrelated to which symbols are
    currently being tracked."""
    _reset()
    cur = store.cursor()
    cur.execute("DELETE FROM ath")
    cur.execute(
        "INSERT INTO ath VALUES ('AAA', 100.0, DATE '2026-01-01', NULL, NULL, NULL)")
    universe.save([_row("AAA")])
    universe.clear_all()
    price = cur.execute(
        "SELECT ath_price FROM ath WHERE symbol='AAA'").fetchone()
    assert price == (100.0,)
