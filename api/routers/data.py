"""Core data endpoints: the screener, the company card, and compare."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..deps import as_of
from ..models import (CompareRequest, ScreenRequest, build_order, build_select,
                      build_where)

router = APIRouter(tags=["data"], dependencies=[Depends(as_of)])


@router.post("/screen")
def screen(req: ScreenRequest):
    """The workhorse. Compiles the filter DSL to parameterised SQL.

    Every field was whitelist-validated against the catalog by Pydantic before
    reaching here, and every value is bound rather than interpolated.
    """
    where, params = build_where(req.filters)
    select = build_select(req.columns)
    order = build_order(req.sort)

    sql = (f"SELECT {select} FROM companies {where} {order} "
           f"LIMIT {req.limit} OFFSET {req.offset}")
    rows = db.query(sql, params)

    total = None
    if req.include_total:
        total = db.query_one(
            f"SELECT count(*) AS n FROM companies {where}", params)["n"]

    if req.mask_finance:
        rows = db.apply_finance_mask(rows)

    return {"rows": rows, "returned": len(rows), "total": total,
            "limit": req.limit, "offset": req.offset}


@router.get("/companies/{symbol}")
def company(symbol: str, mask_finance: bool = True):
    """Full company card: every column, grouped by segment, with the
    percentile ranks precomputed in the data layer."""
    row = db.query_one('SELECT * FROM companies WHERE upper("symbol") = ?',
                       [symbol.upper()])
    if not row:
        raise HTTPException(404, f"symbol '{symbol}' not found")

    if mask_finance:
        row = db.apply_finance_mask([row])[0]

    idx = db.catalog_index()
    grouped: dict[str, list[dict]] = {}
    ranks: dict[str, dict] = {}
    memberships: list[str] = []

    for name, value in row.items():
        if name.startswith("_"):
            continue
        if name.startswith("idx_"):
            if value:
                memberships.append(idx[name]["label"] if name in idx else name)
            continue
        if name.startswith("pct_rank_"):
            base = name.removeprefix("pct_rank_")
            scope = "universe"
            if "_in_sector" in base:
                base, scope = base.replace("_in_sector", ""), "sector"
            elif "_in_tier" in base:
                base, scope = base.replace("_in_tier", ""), "tier"
            ranks.setdefault(base, {})[scope] = value
            continue
        spec = idx.get(name, {})
        grouped.setdefault(spec.get("segment", "Overview"), []).append({
            "name": name, "label": spec.get("label", name), "value": value,
            "unit": spec.get("unit"), "fmt": spec.get("fmt"),
            "polarity": spec.get("polarity"),
            "provenance": spec.get("provenance"),
            "group": spec.get("group", "Other"),
            "segment": spec.get("segment", "Overview"),
            "description": spec.get("description", ""),
            "description_source": spec.get("description_source", "none"),
        })

    return {
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "sector": row.get("sector"),
        "cap_tier": row.get("cap_tier"),
        "segments": grouped,
        "percentile_ranks": ranks,
        "index_memberships": memberships,
        "masked_fields": row.get("_masked_fields", []),
    }


@router.get("/companies/{symbol}/history")
def company_history(symbol: str, freq: str = Query("Q", pattern="^(Q|FY)$")):
    """Profit history for the chart on the company card."""
    isin = db.query_one('SELECT "isin" FROM companies WHERE upper("symbol") = ?',
                        [symbol.upper()])
    if not isin:
        raise HTTPException(404, f"symbol '{symbol}' not found")
    table = "profit_quarterly" if freq == "Q" else "profit_annual"
    rows = db.query(
        f'SELECT "period", "periods_ago", "pat" FROM {table} '
        f'WHERE "isin" = ? ORDER BY "periods_ago"', [isin["isin"]])
    return {"symbol": symbol.upper(), "freq": freq, "n": len(rows),
            "series": rows}


@router.post("/compare")
def compare(req: CompareRequest):
    """2-6 companies aligned as metric rows, with best-in-row resolved
    server-side using the catalog's polarity field."""
    marks = ", ".join("?" * len(req.symbols))
    rows = db.query(
        f'SELECT * FROM companies WHERE upper("symbol") IN ({marks})',
        [s.upper() for s in req.symbols])
    if not rows:
        raise HTTPException(404, "no matching symbols")
    rows = db.apply_finance_mask(rows)

    found = {r["symbol"].upper() for r in rows}
    missing = [s for s in req.symbols if s.upper() not in found]

    idx = db.catalog_index()
    order = {s.upper(): i for i, s in enumerate(req.symbols)}
    rows.sort(key=lambda r: order.get(r["symbol"].upper(), 99))

    metrics: dict[str, list[dict]] = {}
    for name, spec in idx.items():
        if name.startswith(("idx_", "is_", "pct_rank_", "_")):
            continue
        if req.segments and spec["segment"] not in req.segments:
            continue
        if spec["unit"] in ("text", "date"):
            continue

        values = [r.get(name) for r in rows]
        if all(v is None for v in values):
            continue

        best = None
        nums = [(i, v) for i, v in enumerate(values)
                if isinstance(v, (int, float))]
        if nums and spec["polarity"] != "neutral":
            pick = max if spec["polarity"] == "higher_better" else min
            best = pick(nums, key=lambda t: t[1])[0]

        metrics.setdefault(spec["segment"], []).append({
            "name": name, "label": spec["label"], "unit": spec["unit"],
            "fmt": spec["fmt"], "polarity": spec["polarity"],
            "values": values, "best_index": best,
        })

    return {
        "symbols": [r["symbol"] for r in rows],
        "names": [r["name"] for r in rows],
        "sectors": [r["sector"] for r in rows],
        "missing": missing,
        "metrics": metrics,
        "masked": {r["symbol"]: r.get("_masked_fields", []) for r in rows},
    }


@router.get("/search")
def search(q: str = Query(min_length=1), limit: int = Query(10, ge=1, le=50)):
    """Type-ahead over symbol and company name."""
    term = f"%{q.lower()}%"
    rows = db.query(
        'SELECT "symbol", "name", "sector", "cap_tier", "market_cap" '
        'FROM companies WHERE lower("symbol") LIKE ? OR lower("name") LIKE ? '
        'ORDER BY CASE WHEN lower("symbol") = ? THEN 0 '
        '            WHEN lower("symbol") LIKE ? THEN 1 ELSE 2 END, '
        '"market_cap" DESC LIMIT ?',
        [term, term, q.lower(), f"{q.lower()}%", limit])
    return {"query": q, "results": rows}
