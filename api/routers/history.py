"""Time-series endpoints.

Everything here reads `companies_history`, which spans every committed
snapshot. The plain `companies` table stays latest-only so existing queries
keep their meaning -- the history is opted into, never inherited by accident.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..models import Filter, build_where

router = APIRouter(prefix="/history", tags=["history"])


def _snapshots() -> list[str]:
    rows = db.query("SELECT DISTINCT snapshot_date AS d FROM companies_history "
                    "ORDER BY d")
    return [r["d"] for r in rows]


def _resolve_pair(frm: str | None, to: str | None) -> tuple[str, str]:
    snaps = _snapshots()
    if len(snaps) < 2:
        raise HTTPException(
            409, "Only one snapshot is held. Add another day before asking "
                 "what changed.")
    return (frm or snaps[-2], to or snaps[-1])


@router.get("/snapshots")
def snapshots():
    """Every held snapshot with its universe size and build provenance."""
    from tm750 import snapshots as snap_mod
    rows = snap_mod.describe()
    return {"snapshots": rows, "n": len(rows),
            "latest": rows[-1]["snapshot_date"] if rows else None,
            "can_compare": len(rows) > 1}


@router.get("/company/{symbol}")
def company_series(symbol: str, metrics: str | None = Query(None)):
    """One company's metrics across every snapshot."""
    want = ([m.strip() for m in metrics.split(",")] if metrics else
            ["price", "market_cap", "pe_ratio", "perf_1y_pct",
             "momentum_12_1_pct", "rsi_14", "dist_52w_high_pct",
             "fii_holding", "roe"])
    unknown = [m for m in want if m not in db.valid_fields()]
    if unknown:
        raise HTTPException(422, f"unknown metrics: {unknown}")

    cols = ", ".join(f'"{m}"' for m in want)
    rows = db.query(
        f'SELECT "snapshot_date", {cols} FROM companies_history '
        f'WHERE upper("symbol") = ? ORDER BY "snapshot_date"', [symbol.upper()])
    if not rows:
        raise HTTPException(404, f"symbol '{symbol}' not found in any snapshot")
    return {"symbol": symbol.upper(), "metrics": want, "n": len(rows),
            "series": rows}


@router.get("/universe")
def universe_series(metric: str = Query("perf_1y_pct")):
    """A market-wide aggregate across snapshots.

    Medians and breadth over time, which is the question a single snapshot
    cannot answer at all.
    """
    if metric not in db.numeric_fields():
        raise HTTPException(422, f"'{metric}' is not a numeric field")
    rows = db.query(f"""
        SELECT "snapshot_date", count(*) AS companies,
          round(median("{metric}"), 2) AS median,
          round(quantile_cont("{metric}", 0.25), 2) AS p25,
          round(quantile_cont("{metric}", 0.75), 2) AS p75,
          round(100.0 * avg(CASE WHEN "above_ema_200" THEN 1.0 ELSE 0 END), 1)
            AS pct_above_ema200,
          round(100.0 * avg(CASE WHEN "ema_stack_bullish" THEN 1.0 ELSE 0 END), 1)
            AS pct_ema_stacked,
          round(sum("market_cap") / 1e12, 2) AS mcap_lakh_cr
        FROM companies_history GROUP BY 1 ORDER BY 1
    """)
    return {"metric": metric, "n": len(rows), "series": rows}


@router.get("/changes")
def changes(metric: str = Query("price"), frm: str | None = Query(None, alias="from"),
            to: str | None = None, n: int = Query(15, ge=1, le=100)):
    """What moved most between two snapshots.

    Joined on ISIN rather than symbol: symbols get renamed, ISINs do not, so
    a ticker change would otherwise look like one company leaving and another
    arriving.
    """
    if metric not in db.numeric_fields():
        raise HTTPException(422, f"'{metric}' is not a numeric field")
    a, b = _resolve_pair(frm, to)

    rows = db.query(f"""
        SELECT b."symbol", b."name", b."cap_tier", b."sector", b."market_cap",
               a."{metric}" AS before, b."{metric}" AS after,
               b."{metric}" - a."{metric}" AS delta,
               CASE WHEN a."{metric}" = 0 OR a."{metric}" IS NULL THEN NULL
                    ELSE round(100.0 * (b."{metric}" / abs(a."{metric}") - 1), 2)
               END AS pct_change
        FROM companies_history a
        JOIN companies_history b USING("isin")
        WHERE a."snapshot_date" = ? AND b."snapshot_date" = ?
          AND a."{metric}" IS NOT NULL AND b."{metric}" IS NOT NULL
        ORDER BY abs(b."{metric}" - a."{metric}") DESC
        LIMIT ?
    """, [a, b, n])

    summary = db.query_one(f"""
        SELECT count(*) AS compared,
          sum(CASE WHEN b."{metric}" > a."{metric}" THEN 1 ELSE 0 END) AS up,
          sum(CASE WHEN b."{metric}" < a."{metric}" THEN 1 ELSE 0 END) AS down,
          sum(CASE WHEN b."{metric}" = a."{metric}" THEN 1 ELSE 0 END) AS flat,
          round(median(b."{metric}" - a."{metric}"), 4) AS median_delta
        FROM companies_history a JOIN companies_history b USING("isin")
        WHERE a."snapshot_date" = ? AND b."snapshot_date" = ?
          AND a."{metric}" IS NOT NULL AND b."{metric}" IS NOT NULL
    """, [a, b]) or {}

    return {"metric": metric, "from": a, "to": b,
            "summary": summary, "movers": rows}


@router.get("/universe-changes")
def universe_changes(frm: str | None = Query(None, alias="from"),
                     to: str | None = None):
    """Companies that entered or left the universe between two snapshots.

    The 750 is not a fixed list: constituents change at each index review, so
    "the universe" is itself a time series.
    """
    a, b = _resolve_pair(frm, to)
    entered = db.query("""
        SELECT "symbol", "name", "sector", "cap_tier", "market_cap"
        FROM companies_history WHERE "snapshot_date" = ?
          AND "isin" NOT IN (SELECT "isin" FROM companies_history
                             WHERE "snapshot_date" = ?)
        ORDER BY "market_cap" DESC
    """, [b, a])
    left = db.query("""
        SELECT "symbol", "name", "sector", "cap_tier", "market_cap"
        FROM companies_history WHERE "snapshot_date" = ?
          AND "isin" NOT IN (SELECT "isin" FROM companies_history
                             WHERE "snapshot_date" = ?)
        ORDER BY "market_cap" DESC
    """, [a, b])
    moved = db.query("""
        SELECT b."symbol", b."name", a."cap_tier" AS from_tier,
               b."cap_tier" AS to_tier, b."market_cap"
        FROM companies_history a JOIN companies_history b USING("isin")
        WHERE a."snapshot_date" = ? AND b."snapshot_date" = ?
          AND a."cap_tier" != b."cap_tier"
        ORDER BY b."market_cap" DESC
    """, [a, b])
    return {"from": a, "to": b, "entered": entered, "left": left,
            "tier_moves": moved,
            "stable": len(entered) == 0 and len(left) == 0}


@router.post("/screen-changes")
def screen_changes(body: dict):
    """Which companies entered or left a screen between two snapshots.

    The single most useful thing multi-snapshot data buys: not what passes a
    screen today, but what started passing it since yesterday.
    """
    raw = body.get("filters") or []
    try:
        filters = [Filter(**f) for f in raw]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"invalid filter: {exc}") from exc

    a, b = _resolve_pair(body.get("from"), body.get("to"))
    where, params = build_where(filters)
    snap_clause = 'WHERE "snapshot_date" = ?' if not where \
        else where + ' AND "snapshot_date" = ?'

    def matching(date_):
        return {r["isin"]: r for r in db.query(
            f'SELECT "isin", "symbol", "name", "sector", "cap_tier", '
            f'"market_cap", "perf_1y_pct" FROM companies_history {snap_clause}',
            [*params, date_])}

    before, after = matching(a), matching(b)
    entered = [v for k, v in after.items() if k not in before]
    exited = [v for k, v in before.items() if k not in after]
    held = [v for k, v in after.items() if k in before]

    key = lambda r: -(r.get("market_cap") or 0)  # noqa: E731
    return {
        "from": a, "to": b,
        "count_before": len(before), "count_after": len(after),
        "entered": sorted(entered, key=key),
        "exited": sorted(exited, key=key),
        "held_n": len(held),
    }
