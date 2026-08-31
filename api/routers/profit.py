"""Global profit feed: one fetch, both systems.

Deliberately not under /scanner or /admin. Profit is now a whole-app concern
-- the header shows its freshness, the upload page warns when it is stale,
data quality reports its coverage, and the scanner reads the verdicts it
produces -- so it gets its own top-level route rather than living inside
whichever module happened to build it first.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from tm750 import profit_feed
from tm750.scanner.profit import ProfitFetchError

router = APIRouter(prefix="/profit", tags=["profit"])


@router.get("/status")
def profit_status():
    """Freshness, for any part of the UI that needs to show it."""
    return profit_feed.status()


@router.post("/fetch")
def profit_fetch():
    """Fetch both feeds and publish to both systems, or change nothing.

    Slow by nature -- two Apps Script calls returning 5,500+ companies each,
    around 45-60 seconds in practice. The caller should expect to wait rather
    than treat a long request as a hang.
    """
    try:
        return profit_feed.fetch_all()
    except ProfitFetchError as exc:
        # A source problem, not a bug: the endpoint was unreachable or the
        # payload was unusable. Nothing was written.
        raise HTTPException(502, f"Profit fetch failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(500, f"Profit fetch failed: {exc}") from exc


@router.get("/coverage")
def profit_coverage():
    """Which universe members the last fetch does not cover.

    Universe sizes are read live, never assumed -- the platform universe is
    whatever the current snapshot holds and the scan list is whatever Excel
    was last uploaded. Companies in the feed but outside a universe are not
    reported; only universe members the feed misses.
    """
    from tm750.scanner import store as scanner_store
    try:
        rows = scanner_store.cursor().execute(
            "SELECT isin FROM profit").fetchall()
    except Exception as exc:
        raise HTTPException(
            503, f"No profit data stored yet: {exc}") from exc
    return profit_feed.coverage({r[0] for r in rows if r[0]})
