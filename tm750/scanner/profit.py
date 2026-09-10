"""Profit history, fetched from source rather than relayed by hand.

The two Apps Script endpoints serve the same data the profit workbooks carry,
maintained daily at source. Fetching directly removes the manual upload step
and makes the scanner independent of the snapshot pipeline -- it can run on a
day when no snapshot was uploaded at all.

The verdict comes from tm750.history.profit_at_ath -- the same function
build.py calls. One implementation, so the Scanner and Pulse can never give
different answers about the same company on the same day. The reference app's
two ATH stores diverged because one number had two write paths; the same
failure applied to a profit verdict would be worse, because nothing about a
wrong boolean looks wrong.

The test, in full:

  TTM at ATH   TTM = QL1+QL2+QL3+QL4, computed ONCE, compared against the
               reported annual series FYL1..FYL15. The comparison run is
               [TTM, FY1, ... FY15].
  Q at ATH     QL1 against the highest of QL1..QL48.
  Verdict      both, ANDed.

Both feeds are therefore required for the verdict -- quarterly for TTM and the
quarter test, yearly for the FY comparison series. The yearly payload also
carries the identifiers and TRADING STATUS that universe resolution needs.
"""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

from tm750 import history
from tm750.config import PROFIT_API_QUARTERLY, PROFIT_API_YEARLY, QTR_PERIODS
from tm750.scanner import store

QL_COLS = [f"QL{i}" for i in range(1, QTR_PERIODS + 1)]

SUMMARY_COLS = ["isin", "pat_ttm_at_ath", "pat_q_at_ath", "pat_both_at_ath",
                "qtrs_available", "pat_ttm", "pat_fy_peak", "pat_latest_q",
                "pat_peak_q", "fetched_at"]


class ProfitFetchError(Exception):
    """Endpoint unreachable, or payload unusable."""


# ------------------------------------------------------------------ fetch
def fetch(url: str, timeout: int = 180) -> pd.DataFrame:
    """GET one endpoint and standardise headers. Values pass through as-is."""
    import requests

    if not url:
        raise ProfitFetchError(
            "No endpoint configured. Set PROFIT_API_QUARTERLY and "
            "PROFIT_API_YEARLY in tm750/config.py.")
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise ProfitFetchError(f"{url}: {exc}") from exc

    df = pd.DataFrame(payload)
    if df.empty:
        raise ProfitFetchError(f"{url}: empty payload")
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Rename ISIN -> isin, coerce period columns, guarantee all 48 exist.

    Zeros are NOT nullified here. history._nullify_sentinels owns that rule,
    driven by PROFIT_ZERO_IS_NULL. Zero means 'not listed in that period' --
    84,059 of 265,200 quarterly cells carry it, and the 55,653 negatives
    elsewhere prove losses are encoded as negatives. Applying the rule in two
    places invites the two implementations drifting apart.
    """
    if "ISIN" not in df.columns and "isin" not in df.columns:
        raise ProfitFetchError(
            f"Payload has no ISIN column. Got: {list(df.columns)[:10]}")

    out = df.rename(columns={"ISIN": "isin"}).copy()
    out["isin"] = out["isin"].astype(str).str.strip()
    out = out[out["isin"].str.len() > 0]

    for col in QL_COLS:
        if col not in out.columns:
            out[col] = pd.NA
    period_cols = [c for c in out.columns
                   if c.startswith(("QL", "FYL")) or c == "TTM"]
    for c in period_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # A duplicated ISIN would silently pick one row at summarise time.
    return out.drop_duplicates("isin", keep="first")


# ---------------------------------------------------------------- verdict
def verdicts(summary: pd.DataFrame) -> dict[str, str]:
    """ISIN -> 'at_ath' | 'not_at_ath'.

    Mirrors build.py exactly:
        pat_both_at_ath = pat_ttm_at_ath.fillna(False) & pat_q_at_ath.fillna(False)

    A null flag reads as not_at_ath, not as missing. A company present in the
    feed with unusable numbers is a real negative; only absence from the feed
    is 'no data'.
    """
    ttm = summary["pat_ttm_at_ath"].fillna(False).astype(bool)
    qtr = summary["pat_q_at_ath"].fillna(False).astype(bool)
    both = ttm & qtr
    return {isin: ("at_ath" if flag else "not_at_ath")
            for isin, flag in zip(summary["isin"], both)}


def verdict_for(isin: str | None, table: dict[str, str]) -> str:
    """A symbol with no ISIN, or an ISIN absent from the feed, is no_data.

    That third state matters: a company outside the profit universe has not
    failed the test, it was never given it, and the UI must not colour it as
    a negative.
    """
    if not isin:
        return "no_data"
    return table.get(isin, "no_data")


def summarise(raw_q: pd.DataFrame, raw_y: pd.DataFrame) -> pd.DataFrame:
    """Both payloads -> the columns the scanner stores.

    history.profit_at_ath owns the verdict; summarise_quarterly supplies the
    context columns the UI tooltip shows. Both feeds are required: without
    the yearly frame there is no FY series to compare TTM against.
    """
    q_prep = prepare(raw_q)
    y_prep = prepare(raw_y)

    ctx = history.summarise_quarterly(q_prep)
    verdict = history.profit_at_ath(q_prep, y_prep)
    fy = (history.summarise_yearly(y_prep)[["isin", "pat_peak_fy"]]
          .rename(columns={"pat_peak_fy": "pat_fy_peak"}))

    summary = (verdict
               .merge(ctx, on="isin", how="left")
               .merge(fy, on="isin", how="left"))
    summary["fetched_at"] = datetime.now()
    return summary[SUMMARY_COLS]


# --------------------------------------------------------------- persist
def store_summary(raw_q: pd.DataFrame, raw_y: pd.DataFrame) -> int:
    """Replace the profit and identifier tables.

    Both payloads are mandatory -- the verdict compares TTM against the FY
    series, so a quarterly-only refresh cannot produce one.

    Staging-then-swap inside one transaction: a failure mid-write leaves the
    previous verdicts intact rather than emptying the table.
    """
    frame = summarise(raw_q, raw_y)
    cur = store.cursor()
    cur.register("profit_new", frame)
    try:
        cur.execute("BEGIN TRANSACTION")
        cur.execute("DELETE FROM profit")
        cur.execute(
            f"INSERT INTO profit SELECT {', '.join(SUMMARY_COLS)} "
            "FROM profit_new")
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        cur.unregister("profit_new")

    store_identifiers(raw_y)
    return len(frame)


def store_identifiers(raw_y: pd.DataFrame) -> int:
    """Cache NSE CODE / ISIN / TRADING STATUS for universe resolution.

    Cached on disk so an Excel upload resolves without a live API call.
    """
    df = raw_y.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    wanted = {"NSE CODE": "nse_code", "ISIN": "isin",
              "ACCORD CODE": "accord_code", "COMPANY NAME": "company_name",
              "TRADING STATUS": "trading_status"}
    have = {src: dst for src, dst in wanted.items() if src in df.columns}
    frame = df[list(have)].rename(columns=have)
    for col in wanted.values():
        if col not in frame.columns:
            frame[col] = None
    frame = frame[list(wanted.values())].astype(str)

    cur = store.cursor()
    cur.register("ident_new", frame)
    try:
        cur.execute("BEGIN TRANSACTION")
        cur.execute("DELETE FROM feed_identifiers")
        cur.execute("INSERT INTO feed_identifiers SELECT * FROM ident_new")
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        cur.unregister("ident_new")
    return len(frame)


def feed_identifiers() -> pd.DataFrame | None:
    """Identifier columns from the last fetch, shaped for universe.resolve."""
    try:
        df = store.cursor().execute(
            """SELECT nse_code AS "NSE CODE", isin AS "ISIN",
                      accord_code AS "ACCORD CODE",
                      company_name AS "COMPANY NAME",
                      trading_status AS "TRADING STATUS"
               FROM feed_identifiers""").fetchdf()
    except Exception:
        return None
    return df if not df.empty else None


def load_verdicts() -> tuple[dict[str, str], datetime | None]:
    """Stored verdicts plus the fetch timestamp, so staleness stays visible."""
    rows = store.cursor().execute(
        "SELECT isin, pat_both_at_ath, fetched_at FROM profit").fetchall()
    table = {r[0]: ("at_ath" if r[1] else "not_at_ath") for r in rows}
    stamp = rows[0][2] if rows else None
    return table, stamp


def refresh_from_api() -> dict:
    """The Fetch button's entry point."""
    started = time.time()
    raw_q = fetch(PROFIT_API_QUARTERLY)
    raw_y = fetch(PROFIT_API_YEARLY)
    n = store_summary(raw_q, raw_y)
    return {"companies": n,
            "identifiers": len(raw_y),
            "seconds": round(time.time() - started, 1)}
