"""Scanner endpoints.

Long operations -- a scan, a profit refresh -- run on a background thread and
report through the persisted scan_status table. The client polls /status
rather than holding a request open for 80 seconds.

Nothing here runs automatically. Every mutation is an explicit POST: the user
presses Run, or Fetch, or EOD Sync. That is deliberate -- the promote step in
particular decides what tomorrow's trigger price will be, and it should never
happen as a side effect of loading a page.
"""
from __future__ import annotations

import io
import threading

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from tm750.scanner import prices, profit, result_dates, scan, store, universe

router = APIRouter(prefix="/scanner", tags=["scanner"])


# ----------------------------------------------------------------- schemas
class SyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class EditRequest(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    date: str


class MapRequest(BaseModel):
    symbol: str
    isin: str


class RemoveRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class ResetRequest(BaseModel):
    confirm: bool = False


class ResetAthRequest(BaseModel):
    confirm: bool = False
    wipe_events: bool = False


# ------------------------------------------------------------------- scan
@router.get("/status")
def status():
    """Polled by the UI while a scan runs."""
    return scan.get_status()


@router.post("/scan")
def start_scan(check_results: bool = Query(True)):
    """Kick off a scan on a background thread.

    409 rather than queueing: two concurrent scans would write the same
    today_ath rows and interleave their status updates.
    """
    if scan.get_status()["running"]:
        raise HTTPException(409, "A scan is already running")

    def _run():
        try:
            scan.run(check_results=check_results)
        except Exception:
            # scan.run already records the failure in scan_status; swallowing
            # here only stops the thread dying noisily in the server log.
            pass

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@router.get("/results")
def results():
    """Last completed scan. Empty rows is a valid answer, not an error."""
    return scan.load_results()


# --------------------------------------------------------------- EOD sync
@router.post("/sync")
def sync(req: SyncRequest):
    """Promote today's highs to tomorrow's trigger prices.

    Takes an explicit symbol list -- the UI sends every ticked row, which
    defaults to all of them. An empty list is rejected rather than treated as
    'all', because silently promoting everything on a mis-click is not
    recoverable without reading the event log.
    """
    if not req.symbols:
        raise HTTPException(400, "No symbols selected to sync")
    return {"promoted": prices.promote(req.symbols)}


# ------------------------------------------------------- manage database
@router.get("/ath")
def ath_list(q: str = Query("", max_length=32), limit: int = Query(200, le=1000)):
    rows = store.cursor().execute(
        """SELECT symbol, ath_price, ath_date, last_updated
           FROM ath WHERE symbol ILIKE ?
           ORDER BY symbol LIMIT ?""", [f"{q}%", limit]).fetchall()
    return {"rows": [{"symbol": s, "ath_price": p,
                      "ath_date": str(d) if d else None,
                      "last_updated": u.isoformat() if u else None}
                     for s, p, d, u in rows]}


@router.post("/ath/edit")
def edit(req: EditRequest):
    """Operator override. Always logged to ath_events as source='manual'."""
    prices.manual_edit(req.symbol, req.price, req.date)
    return {"updated": req.symbol}


@router.get("/ath/events")
def events(symbol: str, limit: int = Query(50, le=200)):
    """Why this symbol's trigger is what it is -- seed, sync, split, manual."""
    rows = store.cursor().execute(
        """SELECT event_date, old_price, new_price, source, note, created_at
           FROM ath_events WHERE symbol = ?
           ORDER BY created_at DESC LIMIT ?""", [symbol, limit]).fetchall()
    return {"rows": [{"date": str(d) if d else None, "old_price": o,
                      "new_price": n, "source": s, "note": note,
                      "created_at": c.isoformat() if c else None}
                     for d, o, n, s, note, c in rows]}


@router.get("/ath/suspected-repeat-halvings")
def suspected_repeat_halvings():
    """Symbols with 2+ logged split-repair events -- a strong signal of the
    repeated-halving bug fixed on 2026-08-27. A lower bound, not a complete
    list; see prices.suspected_repeat_halvings for why a symbol caught only
    once looks identical to a legitimate single repair here.
    """
    return {"rows": prices.suspected_repeat_halvings()}


@router.post("/ath/reset")
def reset_ath(req: ResetAthRequest):
    """Wipe every stored ATH price and trigger, for a full re-seed under
    corrected split-repair logic. Universe and profit data are untouched.

    Requires explicit confirmation -- this is the recovery path for the
    repeated-halving bug, not a routine action.
    """
    if not req.confirm:
        raise HTTPException(400, "Confirmation required to reset ATH data")
    return prices.clear_all(wipe_events=req.wipe_events)


# ---------------------------------------------------------------- universe
@router.get("/universe")
def universe_list():
    return {"rows": universe.active(), "unresolved": universe.unresolved()}


@router.post("/universe/upload")
async def upload(file: UploadFile):
    """Merge an Excel symbol list into the stored universe.

    Merge, never wipe: symbols absent from this file are REPORTED, not
    deleted, so a truncated export cannot silently shrink the scan list.
    """
    raw = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(400, f"Could not read the file: {exc}")

    try:
        rows = universe.parse(df, source_file=file.filename or "upload.xlsx")
    except universe.UniverseError as exc:
        raise HTTPException(400, str(exc))

    if not rows:
        raise HTTPException(400, "No usable symbols found in that file")

    feed = profit.feed_identifiers()
    resolved = universe.resolve(rows, feed) if feed is not None else rows
    report = universe.diff_against_upload([r["symbol"] for r in resolved])
    counts = universe.save(resolved)

    return {**counts, **report,
            "resolved": sum(1 for r in resolved
                            if r.get("resolution") == "auto"),
            "total": len(resolved),
            "feed_available": feed is not None,
            "unresolved": universe.unresolved()}


@router.post("/universe/map")
def map_symbol(req: MapRequest):
    """Hand-map one of the renames. Persists across future uploads."""
    universe.set_manual_isin(req.symbol, req.isin)
    return {"mapped": req.symbol}


@router.post("/universe/remove")
def remove(req: RemoveRequest):
    """Explicit removal, only after the operator confirms."""
    if not req.symbols:
        raise HTTPException(400, "No symbols given to remove")
    return {"removed": universe.remove(req.symbols)}


@router.post("/universe/reset")
def reset_universe(req: ResetRequest):
    """Wipe the universe list entirely, for a clean restart after an upload
    has gone wrong. ATH prices and profit data are untouched -- only which
    symbols are being tracked is cleared.

    Requires an explicit confirm flag so this can never fire from a
    mis-click; the frontend additionally gates it behind typing a
    confirmation phrase before this is ever called.
    """
    if not req.confirm:
        raise HTTPException(400, "Confirmation required to reset the universe")
    return {"removed": universe.clear_all()}


# ------------------------------------------------------------------ profit
@router.get("/profit/status")
def profit_status():
    table, stamp = profit.load_verdicts()
    return {"companies": len(table),
            "fetched_at": stamp.isoformat() if stamp else None}


@router.post("/profit/refresh")
def refresh_profit():
    """Pull both Apps Script endpoints and recompute every verdict."""
    try:
        return profit.refresh_from_api()
    except profit.ProfitFetchError as exc:
        raise HTTPException(502, str(exc))


# ------------------------------------------------------------ result dates
@router.get("/result-dates")
def result_date_list(symbols: str = Query("", max_length=4000)):
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    out = {}
    for sym in wanted:
        row = result_dates.get_date(sym)
        out[sym] = {"result_date": str(row["result_date"])
                    if row and row["result_date"] else None,
                    "status": row["status"] if row else None}
    return {"rows": out}
