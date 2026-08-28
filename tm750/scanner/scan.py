"""Scan orchestration.

Four phases plus the profit join. Phase 2 is a cheap filter across the whole
universe; phase 3 is the expensive work over the handful that survive it. At
roughly 800 symbols that is 16-17 batches and about 78 seconds -- the split is
what makes a full-universe scan affordable at all.

Status is written to a table rather than held in memory, so a --reload restart
mid-scan cannot leave the UI spinning forever.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from tm750.config import RS_BENCHMARK, SCANNER_BATCH_SIZE
from tm750.scanner import prices, profit, result_dates, store, strategies
from tm750.scanner import universe

RESULT_COLS = ["symbol", "new_ath_price", "trigger_price", "green_candle",
               "close_gt_ath", "ath_outperformance", "current_rs", "ath_rs",
               "profit_state", "profit_stale", "result_date", "stop_loss"]


# ----------------------------------------------------------------- status
def set_status(running: bool, progress: int, total: int, message: str) -> None:
    store.cursor().execute(
        """UPDATE scan_status SET is_running = ?, progress = ?, total = ?,
               message = ?, last_updated = now()
           WHERE id = 1""", [running, progress, total, message])


def get_status() -> dict:
    row = store.cursor().execute(
        """SELECT is_running, progress, total, message, last_updated
           FROM scan_status WHERE id = 1""").fetchone()
    if row is None:
        return {"running": False, "progress": 0, "total": 0,
                "message": "Idle", "last_updated": None}
    return {"running": bool(row[0]), "progress": row[1], "total": row[2],
            "message": row[3],
            "last_updated": row[4].isoformat() if row[4] else None}


# ----------------------------------------------------------------- phases
def clear_today() -> None:
    """Phase 0.

    Guards against a skipped EOD Sync bleeding yesterday's intraday values
    into today's comparison.
    """
    store.cursor().execute("UPDATE ath SET today_ath = NULL")


def seed_missing(rows: list[dict]) -> int:
    """Phase 1. Establish a lifetime high for symbols that have none.

    Normally a no-op -- only new universe entries reach here.
    """
    have = {r[0] for r in store.cursor().execute(
        "SELECT symbol FROM ath WHERE ath_price IS NOT NULL").fetchall()}
    todo = [r for r in rows if r["symbol"] not in have]
    for i, r in enumerate(todo, start=1):
        set_status(True, i, len(todo), f"Seeding {r['symbol']} ({i}/{len(todo)})")
        prices.seed(r["symbol"], r["exchange"])
    return len(todo)


def _split_ratio(splits: pd.Series | None) -> float | None:
    """Product of every non-zero split ratio in the window, or None."""
    if splits is None:
        return None
    non_zero = splits.dropna()
    non_zero = non_zero[non_zero > 0]
    if non_zero.empty:
        return None
    return float(non_zero.prod())


def _latest_split_date(splits: pd.Series | None):
    """Date of the most recent non-zero split in the window, or None.

    Used to decide whether an ongoing repair is even necessary -- see the
    TDPOWERSYS comment in find_hits().
    """
    if splits is None:
        return None
    non_zero = splits.dropna()
    non_zero = non_zero[non_zero > 0]
    if non_zero.empty:
        return None
    d = non_zero.index[-1]
    return d.date() if hasattr(d, "date") else d


def find_hits(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Phase 2: cheap filter across the whole universe."""
    cur = store.cursor()
    trig_rows = cur.execute(
        "SELECT symbol, ath_price, last_split_check FROM ath "
        "WHERE ath_price IS NOT NULL").fetchall()
    triggers = {r[0]: r[1] for r in trig_rows}
    checked_through = {r[0]: r[2] for r in trig_rows}

    by_ticker = {prices.yf_symbol(r["symbol"], r["exchange"]): r for r in rows}
    names = list(by_ticker)
    n_batches = max(1, (len(names) + SCANNER_BATCH_SIZE - 1)
                    // SCANNER_BATCH_SIZE)

    hits: list[dict] = []
    failed: list[str] = []

    for b in range(n_batches):
        chunk = names[b * SCANNER_BATCH_SIZE:(b + 1) * SCANNER_BATCH_SIZE]
        set_status(True, b + 1, n_batches,
                   f"Batch {b + 1}/{n_batches}: Downloading prices...")
        data = prices.download_batch(chunk, period="5d")
        if data.empty:
            failed.extend(chunk)
            continue

        for ticker in chunk:
            meta = by_ticker[ticker]
            symbol = meta["symbol"]
            try:
                high = prices.extract(data, ticker, "High")
                close = prices.extract(data, ticker, "Close")
                if high is None or close is None:
                    failed.append(ticker)
                    continue

                # Split repair BEFORE comparison. An unrepaired trigger sits
                # in pre-split rupees, so the symbol can never hit ATH again
                # and it silently disappears from the scanner.
                #
                # BUT: only when this SPECIFIC split has not already been
                # handled. last_split_check records the latest split date
                # already accounted for -- set by seed() from the full
                # history it just processed, or by a previous run of this
                # exact repair. A 5-day lookback window keeps re-including a
                # split for several days after it actually happened, so
                # without this check the same split gets detected and
                # re-applied on every subsequent scan (the TDPOWERSYS bug:
                # 793.50 -> 396.75 -> 198.38, halved again each run).
                # ath_date is NOT used for this comparison -- it records
                # when the true historical peak occurred, a different fact
                # that a split repair correctly never changes.
                splits_series = prices.extract(
                    data, ticker, "Stock Splits")
                ratio = _split_ratio(splits_series)
                if ratio and symbol in triggers:
                    split_date = _latest_split_date(splits_series)
                    checked = checked_through.get(symbol)
                    already_handled = (
                        checked is not None and split_date is not None
                        and str(checked) >= str(split_date))
                    if not already_handled and split_date is not None:
                        repaired = prices.apply_split(
                            symbol, ratio, str(split_date))
                        if repaired is not None:
                            triggers[symbol] = repaired
                            checked_through[symbol] = split_date

                highs = high.dropna()
                closes = close.dropna()
                if highs.empty or len(closes) < 2:
                    failed.append(ticker)
                    continue

                trigger = triggers.get(symbol)
                if trigger is None:
                    continue

                today_high = float(highs.iloc[-1])
                # >= so an already-promoted name still surfaces on a re-scan.
                if round(today_high, 2) >= round(trigger, 2):
                    hits.append({**meta, "ticker": ticker,
                                 "today_high": today_high,
                                 "today_close": float(closes.iloc[-1]),
                                 "prev_close": float(closes.iloc[-2]),
                                 "trigger": trigger})
            except Exception:
                # ANY unforeseen shape from yfinance for this one symbol --
                # not just the cases anticipated above -- is a failed symbol,
                # never a failed scan. This is what should have caught
                # AKZOINDIA before the precise extract() fix existed, and it
                # stays as the backstop for whatever the next quirk turns
                # out to be.
                failed.append(ticker)

    return hits, failed


def analyse(hits: list[dict], check_results: bool = True) -> list[dict]:
    """Phase 3 (strategies), 3b (profit join) and 3c (result dates)."""
    if not hits:
        return []

    set_status(True, 0, len(hits), "Running 4-strategy scan...")
    bench = prices.download_batch([RS_BENCHMARK], period="1y")
    bench_close = prices.extract(bench, RS_BENCHMARK, "Close")

    data = prices.download_batch([h["ticker"] for h in hits], period="1y")
    verdict_table, fetched_at = profit.load_verdicts()

    if check_results:
        set_status(True, 0, len(hits), "Checking result dates...")
        try:
            result_dates.refresh_for([h["symbol"] for h in hits])
        except Exception:
            # Screener being slow must never fail a scan.
            pass

    out = []
    for h in hits:
        rs = strategies.relative_strength(
            prices.extract(data, h["ticker"], "Close"), bench_close)

        cached = result_dates.get_date(h["symbol"]) or {}
        due = cached.get("result_date")

        out.append({
            "symbol": h["symbol"],
            "new_ath_price": h["today_high"],
            "trigger_price": h["trigger"],
            "green_candle": strategies.green_candle(h["today_close"],
                                                    h["prev_close"]),
            "close_gt_ath": strategies.close_gt_ath(h["today_close"],
                                                    h["trigger"]),
            "ath_outperformance": rs["ath_outperformance"],
            "current_rs": rs["current_rs"],
            "ath_rs": rs["ath_rs"],
            "profit_state": profit.verdict_for(h.get("isin"), verdict_table),
            "profit_stale": result_dates.profit_is_stale(due, fetched_at),
            "result_date": due,
            "stop_loss": None,
        })
        store.cursor().execute(
            "UPDATE ath SET today_ath = ? WHERE symbol = ?",
            [h["today_high"], h["symbol"]])

    return out


# ---------------------------------------------------------------- results
def _insert_results(rows: list[dict]) -> None:
    cur = store.cursor()
    for r in rows:
        cur.execute(
            f"""INSERT INTO scan_results ({', '.join(RESULT_COLS)}, scanned_at)
                VALUES ({', '.join('?' * len(RESULT_COLS))}, now())""",
            [r.get(c) for c in RESULT_COLS])


def save_results(rows: list[dict]) -> None:
    """Staging-then-swap.

    The reference app DELETEs then INSERTs, so a crash between the two loses
    the table entirely. Here a failure restores the previous results.
    """
    cur = store.cursor()
    cur.execute("CREATE OR REPLACE TEMP TABLE scan_backup AS "
                "SELECT * FROM scan_results")
    cur.execute("DELETE FROM scan_results")
    try:
        _insert_results(rows)
    except Exception:
        cur.execute("DELETE FROM scan_results")
        cur.execute("INSERT INTO scan_results SELECT * FROM scan_backup")
        raise


def load_results() -> dict:
    """Last scan's rows, plus the two flags the UI needs for context."""
    rows = store.cursor().execute(
        f"""SELECT {', '.join(RESULT_COLS)}, scanned_at
            FROM scan_results ORDER BY symbol""").fetchall()
    out = [dict(zip(RESULT_COLS + ["scanned_at"], r)) for r in rows]
    for r in out:
        r["result_date"] = str(r["result_date"]) if r["result_date"] else None
        r["scanned_at"] = (r["scanned_at"].isoformat()
                           if r["scanned_at"] else None)

    # After EOD Sync every trigger equals its new high, so close_gt_ath
    # cannot fire. Correct state, but it reads as a broken strategy without a
    # banner explaining it.
    #
    # Detected from the EVENT LOG, not from price equality. NEW ATH ==
    # TRIGGER is also true in a completely different situation: a symbol
    # whose lifetime high was seeded TODAY. Full-history seeding includes
    # today's bar, so if today is the record day the seeded trigger already
    # equals today's high -- and the first scan after a fresh seed would then
    # wrongly claim a sync had happened, when EOD Sync is a manual button
    # nobody had pressed. Only a real 'sync' event proves a promotion.
    symbols = [r["symbol"] for r in out]
    synced_today = 0
    if symbols:
        placeholders = ",".join("?" * len(symbols))
        synced_today = store.cursor().execute(
            f"""SELECT count(DISTINCT symbol) FROM ath_events
                WHERE source = 'sync' AND symbol IN ({placeholders})
                  AND CAST(created_at AS DATE) = CURRENT_DATE""",
            symbols).fetchone()[0]
    post_sync = bool(out) and synced_today == len(out)

    _, fetched_at = profit.load_verdicts()
    return {"rows": out, "post_sync": post_sync,
            "profit_fetched_at": fetched_at.isoformat() if fetched_at else None}


# -------------------------------------------------------------------- run
def run(check_results: bool = True) -> dict:
    """Full scan. Called on a background thread by the router."""
    try:
        set_status(True, 0, 0, "Initializing scan...")
        rows = universe.active()
        if not rows:
            set_status(False, 0, 0,
                       "Universe is empty - upload an Excel file first")
            return {"hits": 0, "failed": []}

        clear_today()
        seeded = seed_missing(rows)
        hits, failed = find_hits(rows)
        results = analyse(hits, check_results=check_results)
        save_results(results)

        msg = f"Scan complete. {len(results)} verified ATH hits found."
        if failed:
            msg += f" {len(failed)} symbols failed to download."
        set_status(False, len(rows), len(rows), msg)
        return {"hits": len(results), "failed": failed, "seeded": seeded}
    except Exception as exc:
        set_status(False, 0, 0, f"Scan failed: {exc}")
        raise
