"""One fetch, both systems.

The two Apps Script endpoints are the source of truth for profit. Until now
that data reached the two halves of the app by two unrelated routes: the
platform got it as two hand-exported workbooks through the upload page, and
the scanner fetched it from the API itself. Same numbers, fetched twice,
stored twice, and free to disagree whenever one side was refreshed and the
other was not.

This module is the single door. It fetches both feeds once and writes:

  * two workbooks, in the exact shape ingest._load_profit already reads, so
    the build path needs no new code and the existing per-snapshot archive
    and carry-forward machinery applies unchanged;
  * the scanner's verdict tables, through the same store_summary the scanner
    already uses -- so tm750.history.profit_at_ath remains the only thing
    that ever decides a verdict, and verify_parity still means something.

Atomicity, because a half-written profit set is worse than a stale one: both
endpoints must return usable payloads before anything is written anywhere. A
failure at any point leaves both the workbooks and the scanner database
exactly as they were.

Fetching is deliberately NOT tied to a build. The usual working order is to
fetch in the morning and upload the TradingView and Screener exports later,
so the fetch stands alone and the build reads whatever is current when it
eventually runs.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import (EXTERNAL, FY_PERIODS, PROFIT_API_QUARTERLY,
                     PROFIT_API_YEARLY, QTR_PERIODS, SOURCES)
from .scanner import profit as scanner_profit
from .scanner.profit import ProfitFetchError

# Where a fetched set lives until a build picks it up. Kept outside the
# per-snapshot archive because a fetch is not a snapshot -- it is an input
# that any later snapshot may consume.
FEED_DIR = EXTERNAL / "profit_feed"
LATEST_DIR = FEED_DIR / "latest"
FEED_ARCHIVE = FEED_DIR / "archive"
META_PATH = FEED_DIR / "meta.json"

Q_NAME = SOURCES["profit_q"]
Y_NAME = SOURCES["profit_y"]


def _pad_periods(df: pd.DataFrame, prefix: str, n: int) -> pd.DataFrame:
    """Guarantee every period column exists.

    ingest._load_profit hard-requires QL1..QL48 / FYL1..FYL15 and raises if
    any are absent. The API omits a column entirely when no company has a
    value for it, so a payload that is perfectly valid on the scanner side --
    scanner.profit.prepare() pads the same way -- would fail the build's
    stricter check. Padding here keeps both readers happy from one file.
    """
    out = df.copy()
    for i in range(1, n + 1):
        col = f"{prefix}{i}"
        if col not in out.columns:
            out[col] = pd.NA
    return out


def _validate(df: pd.DataFrame, label: str, prefix: str, n: int) -> None:
    """Reject a payload before it can replace a good one."""
    if df is None or df.empty:
        raise ProfitFetchError(f"{label}: empty payload")
    cols = {str(c).strip().upper() for c in df.columns}
    if "ISIN" not in cols:
        raise ProfitFetchError(
            f"{label}: no ISIN column. Got {sorted(cols)[:8]}")
    present = sum(f"{prefix}{i}" in cols for i in range(1, n + 1))
    if present == 0:
        raise ProfitFetchError(
            f"{label}: no {prefix} period columns in payload")


def _write_workbooks(raw_q: pd.DataFrame, raw_y: pd.DataFrame,
                     stamp: datetime) -> Path:
    """Write both workbooks to a staging directory. Nothing is published
    until the caller moves it, so an exception here changes nothing."""
    staging = Path(tempfile.mkdtemp(prefix="profit_feed_"))
    _pad_periods(raw_q, "QL", QTR_PERIODS).to_excel(
        staging / Q_NAME, index=False)
    _pad_periods(raw_y, "FYL", FY_PERIODS).to_excel(
        staging / Y_NAME, index=False)
    return staging


def _publish(staging: Path, stamp: datetime) -> Path:
    """Move staging into place, and keep a dated copy.

    The dated copy is what makes a fetch replayable: a snapshot built next
    week from today's profit can be reproduced, which the carry-forward
    machinery alone would not guarantee once `latest` moves on.
    """
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    for name in (Q_NAME, Y_NAME):
        shutil.copy2(staging / name, LATEST_DIR / name)

    dated = FEED_ARCHIVE / stamp.strftime("%Y-%m-%d_%H%M%S")
    dated.mkdir(parents=True, exist_ok=True)
    for name in (Q_NAME, Y_NAME):
        shutil.copy2(staging / name, dated / name)
    shutil.rmtree(staging, ignore_errors=True)
    return dated


def _write_meta(info: dict) -> None:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(info, indent=2, default=str))


def status() -> dict:
    """What the UI needs to show freshness anywhere in the app."""
    if not META_PATH.exists():
        return {"fetched_at": None, "age_hours": None, "stale": True,
                "companies_q": None, "companies_y": None,
                "files_present": LATEST_DIR.joinpath(Q_NAME).exists()}
    try:
        info = json.loads(META_PATH.read_text())
    except Exception:
        return {"fetched_at": None, "age_hours": None, "stale": True,
                "companies_q": None, "companies_y": None,
                "files_present": False}

    stamp = info.get("fetched_at")
    age = None
    if stamp:
        try:
            age = round(
                (datetime.now() - datetime.fromisoformat(stamp))
                .total_seconds() / 3600, 1)
        except Exception:
            age = None
    info["age_hours"] = age
    # "Stale" means: not fetched today. The feeds are refreshed daily at
    # source, so yesterday's fetch is genuinely older data, not merely old.
    info["stale"] = (
        True if not stamp
        else datetime.fromisoformat(stamp).date() != datetime.now().date())
    info["files_present"] = (LATEST_DIR / Q_NAME).exists() and \
                            (LATEST_DIR / Y_NAME).exists()
    return info


def latest_paths() -> dict[str, Path] | None:
    """The fetched workbooks, if a fetch has produced a usable pair."""
    q, y = LATEST_DIR / Q_NAME, LATEST_DIR / Y_NAME
    if q.exists() and y.exists():
        return {"profit_q": q, "profit_y": y}
    return None


def coverage(feed_isins: set[str]) -> dict:
    """How much of each universe the feed actually covers.

    Deliberately universe-relative and never hardcoded: the platform universe
    is whatever the current snapshot holds, the scan list is whatever Excel
    file was last uploaded, and both change. Companies in the feed but
    outside a universe are not reported -- there are thousands of them and
    they are not a problem. The only signal worth surfacing is the reverse: a
    universe member the feed does not cover, which is the unmapped-ISIN case.
    """
    out: dict = {"feed_companies": len(feed_isins), "universes": {}}

    try:
        from api import db as api_db
        rows = api_db.query(
            "SELECT isin, symbol FROM companies WHERE isin IS NOT NULL")
        missing = [{"symbol": r["symbol"], "isin": r["isin"]}
                   for r in rows if r["isin"] not in feed_isins]
        out["universes"]["platform"] = {
            "label": "tm750 platform",
            "size": len(rows),
            "matched": len(rows) - len(missing),
            "unmatched": missing,
        }
    except Exception as exc:
        out["universes"]["platform"] = {"label": "tm750 platform",
                                        "error": str(exc)}

    try:
        from .scanner import store as scanner_store
        rows = scanner_store.cursor().execute(
            "SELECT symbol, isin FROM universe").fetchall()
        missing = [{"symbol": r[0], "isin": r[1]}
                   for r in rows if not r[1] or r[1] not in feed_isins]
        out["universes"]["scanner"] = {
            "label": "Scanner scan list",
            "size": len(rows),
            "matched": len(rows) - len(missing),
            "unmatched": missing,
        }
    except Exception as exc:
        out["universes"]["scanner"] = {"label": "Scanner scan list",
                                       "error": str(exc)}
    return out


def fetch_all() -> dict:
    """Fetch both feeds and publish to both systems, or change nothing.

    Order matters. Everything that can fail is done before anything is
    published: both HTTP calls, both validations, both workbook writes into
    a temporary directory, and the scanner's own transactional write. Only
    once all of that has succeeded do the workbooks move into place.
    """
    started = time.time()
    stamp = datetime.now()

    raw_q = scanner_profit.fetch(PROFIT_API_QUARTERLY)
    raw_y = scanner_profit.fetch(PROFIT_API_YEARLY)
    _validate(raw_q, "quarterly", "QL", QTR_PERIODS)
    _validate(raw_y, "yearly", "FYL", FY_PERIODS)

    staging = _write_workbooks(raw_q, raw_y, stamp)
    try:
        # Transactional inside the scanner store: a failure rolls back and
        # leaves the previous verdicts intact.
        n_scanner = scanner_profit.store_summary(raw_q, raw_y)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    dated = _publish(staging, stamp)

    isin_col = "ISIN" if "ISIN" in raw_y.columns else "isin"
    feed_isins = set(raw_y[isin_col].astype(str).str.strip()) | \
        set(raw_q[isin_col].astype(str).str.strip()
            if isin_col in raw_q.columns else [])

    info = {
        "fetched_at": stamp.isoformat(timespec="seconds"),
        "companies_q": len(raw_q),
        "companies_y": len(raw_y),
        "scanner_rows": n_scanner,
        "archive": dated.name,
        "seconds": round(time.time() - started, 1),
    }
    _write_meta(info)

    info["coverage"] = coverage(feed_isins)
    return info
