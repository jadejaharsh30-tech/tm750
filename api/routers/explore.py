"""Aggregation endpoints: sector/factor exploration and the market pulse."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..deps import as_of

router = APIRouter(tags=["explore"], dependencies=[Depends(as_of)])

DIMENSIONS = {
    "sector": "sector",
    "industry": "industry",
    "tier": "cap_tier",
}

# Metrics aggregated by default. Kept short deliberately: a 40-column
# aggregation table is a data dump, not a view.
DEFAULT_METRICS = [
    "market_cap", "pe_ratio", "peg_ratio", "price_to_book", "roe", "roce",
    "dividend_yield", "perf_1y_pct", "perf_3m_pct", "momentum_12_1_pct",
    "dist_52w_high_pct", "dist_ath_pct", "rsi_14", "promoter_holding",
    "fii_holding", "dii_holding", "revenue_growth_ttm_yoy",
    "net_income_growth_ttm_yoy", "pat_cagr_5y_pct",
]


def _agg_sql(group_col: str, metrics: list[str]) -> str:
    parts = [f'"{group_col}" AS "group"', "count(*) AS n"]
    for m in metrics:
        parts.append(f'round(median("{m}"), 2) AS "{m}_median"')
    parts.append('round(sum("market_cap") / 1e12, 2) AS mcap_lakh_cr')
    parts.append('round(100.0 * sum(CASE WHEN "above_ema_200" THEN 1 ELSE 0 END)'
                 ' / count(*), 1) AS pct_above_ema200')
    parts.append('round(100.0 * sum(CASE WHEN "ema_stack_bullish" THEN 1 ELSE 0'
                 ' END) / count(*), 1) AS pct_ema_stacked')
    return (f'SELECT {", ".join(parts)} FROM companies '
            f'WHERE "{group_col}" IS NOT NULL GROUP BY 1 ORDER BY n DESC')


@router.get("/explore/{dimension}")
def explore(dimension: str, metrics: str | None = Query(None)):
    """Median metrics grouped by sector, industry or cap tier.

    Financial companies are excluded from ROCE/ROIC medians rather than
    dragged in, since those metrics do not apply to them.
    """
    if dimension not in DIMENSIONS:
        raise HTTPException(
            400, f"dimension must be one of {list(DIMENSIONS)}")
    col = DIMENSIONS[dimension]

    wanted = ([m.strip() for m in metrics.split(",")] if metrics
              else DEFAULT_METRICS)
    unknown = [m for m in wanted if m not in db.valid_fields()]
    if unknown:
        raise HTTPException(422, f"unknown metrics: {unknown}")

    rows = db.query(_agg_sql(col, wanted))

    masked = db.finance_masked_fields()
    fin_metrics = [m for m in wanted if m in masked]
    if fin_metrics:
        clean = db.query(_agg_sql(col, fin_metrics).replace(
            'WHERE "%s" IS NOT NULL' % col,
            'WHERE "%s" IS NOT NULL AND "sector" != \'Finance\'' % col))
        lookup = {r["group"]: r for r in clean}
        for r in rows:
            src = lookup.get(r["group"])
            if src:
                for m in fin_metrics:
                    r[f"{m}_median"] = src[f"{m}_median"]

    return {
        "dimension": dimension,
        "groups": rows,
        "metrics": wanted,
        "note": (f"{', '.join(fin_metrics)} computed excluding the Finance "
                 "sector, where these metrics do not apply."
                 if fin_metrics else None),
    }


@router.get("/explore/factors/overlap")
def factor_overlap():
    """How much the Nifty factor indices actually intersect.

    Directly relevant to factor-strategy work: if momentum and quality overlap
    heavily, they are not the independent bets they appear to be.
    """
    factors = [r["column_name"] for r in db.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='companies' AND column_name LIKE 'is\\_%' ESCAPE '\\'"
    )]
    exclude = {"is_sme", "is_any_factor"}
    factors = [f for f in factors if f not in exclude]

    counts = db.query(
        "SELECT " + ", ".join(
            f'sum(CASE WHEN "{f}" THEN 1 ELSE 0 END) AS "{f}"'
            for f in factors) + " FROM companies")[0]

    pairs = []
    for i, a in enumerate(factors):
        for b in factors[i + 1:]:
            n = db.query_one(
                f'SELECT count(*) AS n FROM companies WHERE "{a}" AND "{b}"')["n"]
            if n:
                pairs.append({"a": a, "b": b, "overlap": n,
                              "pct_of_a": round(100 * n / counts[a], 1)
                              if counts[a] else None})

    return {"counts": counts,
            "overlaps": sorted(pairs, key=lambda p: -p["overlap"])}


@router.get("/pulse")
def pulse():
    """Market-wide headline stats and breadth."""
    head = db.query_one("""
        SELECT count(*) AS companies,
               round(sum("market_cap") / 1e12, 1) AS total_mcap_lakh_cr,
               round(median("pe_ratio"), 1) AS median_pe,
               round(median("perf_1y_pct"), 1) AS median_1y_return,
               round(median("dist_52w_high_pct"), 1) AS median_from_52w_high,
               round(median("dist_ath_pct"), 1) AS median_from_ath,
               sum(CASE WHEN "chg_1d_pct" > 0 THEN 1 ELSE 0 END) AS advancing,
               sum(CASE WHEN "chg_1d_pct" < 0 THEN 1 ELSE 0 END) AS declining,
               sum(CASE WHEN "employees" IS NOT NULL THEN "employees" ELSE 0 END)
                   AS total_employees
        FROM companies
    """)

    breadth = db.query_one("""
        SELECT round(100.0 * avg(CASE WHEN "above_ema_200" THEN 1.0 ELSE 0 END), 1)
                   AS pct_above_ema200,
               round(100.0 * avg(CASE WHEN "above_sma_200" THEN 1.0 ELSE 0 END), 1)
                   AS pct_above_sma200,
               round(100.0 * avg(CASE WHEN "ema_stack_bullish" THEN 1.0 ELSE 0 END), 1)
                   AS pct_ema_stacked,
               round(100.0 * avg(CASE WHEN "perf_1y_pct" > 0 THEN 1.0 ELSE 0 END), 1)
                   AS pct_positive_1y,
               round(100.0 * avg(CASE WHEN "dist_52w_high_pct" > -10 THEN 1.0 ELSE 0 END), 1)
                   AS pct_near_52w_high
        FROM companies
    """)

    tiers = db.query("""
        SELECT "cap_tier" AS tier, count(*) AS n,
               round(sum("market_cap") / 1e12, 1) AS mcap_lakh_cr,
               round(median("perf_1y_pct"), 1) AS median_1y,
               round(median("pe_ratio"), 1) AS median_pe,
               round(100.0 * avg(CASE WHEN "above_ema_200" THEN 1.0 ELSE 0 END), 1)
                   AS pct_above_ema200
        FROM companies GROUP BY 1
        ORDER BY CASE "cap_tier" WHEN 'Large' THEN 1 WHEN 'Mid' THEN 2
                                 WHEN 'Small' THEN 3 ELSE 4 END
    """)

    ratings = db.query('SELECT "analyst_rating" AS rating, count(*) AS n '
                       'FROM companies WHERE "analyst_rating" IS NOT NULL '
                       'GROUP BY 1 ORDER BY n DESC')
    tech = db.query('SELECT "technical_rating" AS rating, count(*) AS n '
                    'FROM companies WHERE "technical_rating" IS NOT NULL '
                    'GROUP BY 1 ORDER BY n DESC')
    conflict = db.query_one(
        'SELECT sum(CASE WHEN "rating_conflict" THEN 1 ELSE 0 END) AS n '
        'FROM companies')

    return {
        "snapshot": db.snapshots()[-1] if db.snapshots() else None,
        "headline": head or {},
        "breadth": breadth or {},
        "by_tier": tiers,
        "analyst_ratings": ratings,
        "technical_ratings": tech,
        "rating_conflicts": (conflict or {}).get("n"),
    }


@router.get("/pulse/profit-ath")
def profit_ath():
    """How much of the universe is earning more than it ever has.

    Trailing twelve months is the rolling-year measure: it updates every
    quarter, where reported annual PAT moves only once a year. TTM is measured
    against the reported financial-year series -- the comparison run is
    [TTM, FY1..FY15] -- so a record means the live trailing year has beaten
    every completed year the company has reported.

    "Both" means TTM and the latest quarter together -- a record year that is
    still setting records, rather than a record year already rolling over.
    """
    counts = db.query_one("""
        SELECT count(*) AS universe,
          sum(CASE WHEN "pat_ttm_at_ath" THEN 1 ELSE 0 END) AS ttm_at_ath,
          sum(CASE WHEN "pat_q_at_ath" THEN 1 ELSE 0 END) AS q_at_ath,
          sum(CASE WHEN "pat_both_at_ath" THEN 1 ELSE 0 END) AS both_at_ath,
          sum(CASE WHEN "pat_fy_at_ath" THEN 1 ELSE 0 END) AS fy_at_ath,
          sum(CASE WHEN "pat_ttm_at_ath" AND NOT "pat_q_at_ath"
                   THEN 1 ELSE 0 END) AS ttm_only,
          sum(CASE WHEN "pat_q_at_ath" AND NOT "pat_ttm_at_ath"
                   THEN 1 ELSE 0 END) AS q_only,
          sum(CASE WHEN NOT "pat_ttm_at_ath" AND "pat_ttm_vs_fy_peak_pct" > -10
                   THEN 1 ELSE 0 END) AS ttm_within_10,
          sum(CASE WHEN NOT "pat_ttm_at_ath" AND "pat_ttm_vs_fy_peak_pct" <= -10
                   AND "pat_ttm_vs_fy_peak_pct" > -25 THEN 1 ELSE 0 END) AS ttm_10_25,
          sum(CASE WHEN NOT "pat_ttm_at_ath" AND "pat_ttm_vs_fy_peak_pct" <= -25
                   AND "pat_ttm_vs_fy_peak_pct" > -50 THEN 1 ELSE 0 END) AS ttm_25_50,
          sum(CASE WHEN "pat_ttm_vs_fy_peak_pct" <= -50 THEN 1 ELSE 0 END)
            AS ttm_below_50
        FROM companies
    """) or {}

    by_tier = db.query("""
        SELECT "cap_tier" AS tier, count(*) AS n,
          sum(CASE WHEN "pat_ttm_at_ath" THEN 1 ELSE 0 END) AS ttm_at_ath,
          sum(CASE WHEN "pat_q_at_ath" THEN 1 ELSE 0 END) AS q_at_ath,
          sum(CASE WHEN "pat_both_at_ath" THEN 1 ELSE 0 END) AS both_at_ath,
          round(100.0 * avg(CASE WHEN "pat_both_at_ath" THEN 1.0 ELSE 0 END), 1)
            AS both_pct
        FROM companies GROUP BY 1
        ORDER BY CASE "cap_tier" WHEN 'Large' THEN 1 WHEN 'Mid' THEN 2
                                 WHEN 'Small' THEN 3 ELSE 4 END
    """)

    # Record earnings on both horizons, yet the price is down over 12 months.
    divergent = db.query("""
        SELECT "symbol", "name", "cap_tier", "market_cap", "perf_1y_pct",
               "dist_ath_pct", "pat_yoy_q_pct"
        FROM companies
        WHERE "pat_both_at_ath" AND "perf_1y_pct" < 0
        ORDER BY "market_cap" DESC LIMIT 10
    """)
    divergent_n = db.query_one("""
        SELECT count(*) AS n FROM companies
        WHERE "pat_both_at_ath" AND "perf_1y_pct" < 0
    """) or {}

    # Record rolling year, but the latest quarter is no longer a record --
    # the earliest visible sign that a run of record earnings is fading.
    rolling_over = db.query("""
        SELECT "symbol", "name", "cap_tier", "market_cap",
               "pat_q_vs_peak_pct", "pat_yoy_q_pct", "perf_1y_pct"
        FROM companies
        WHERE "pat_ttm_at_ath" AND NOT "pat_q_at_ath"
        ORDER BY "market_cap" DESC LIMIT 10
    """)

    return {"counts": counts, "by_tier": by_tier,
            "divergent_n": divergent_n.get("n"), "divergent": divergent,
            "rolling_over": rolling_over}


@router.get("/pulse/breadth")
def breadth_detail(by: str = Query("sector", pattern="^(sector|industry|tier)$")):
    """Breadth broken down by group, plus the distribution behind the headline.

    A single "54% above EMA200" hides whether that strength is broad or
    concentrated in two sectors. This shows which.
    """
    col = {"sector": "sector", "industry": "industry", "tier": "cap_tier"}[by]

    groups = db.query(f"""
        SELECT "{col}" AS "group", count(*) AS n,
          round(100.0 * avg(CASE WHEN "above_ema_200" THEN 1.0 ELSE 0 END), 1)
            AS pct_above_ema200,
          round(100.0 * avg(CASE WHEN "ema_stack_bullish" THEN 1.0 ELSE 0 END), 1)
            AS pct_stacked,
          round(100.0 * avg(CASE WHEN "perf_1y_pct" > 0 THEN 1.0 ELSE 0 END), 1)
            AS pct_positive_1y,
          round(100.0 * avg(CASE WHEN "pat_both_at_ath" THEN 1.0 ELSE 0 END), 1)
            AS pct_profit_ath,
          round(median("perf_1y_pct"), 1) AS median_1y
        FROM companies WHERE "{col}" IS NOT NULL
        GROUP BY 1 HAVING count(*) >= 5
        ORDER BY pct_above_ema200 DESC
    """)

    # Where the universe sits relative to its own 52-week high.
    dist = db.query_one("""
        SELECT
          sum(CASE WHEN "dist_52w_high_pct" > -2 THEN 1 ELSE 0 END) AS at_high,
          sum(CASE WHEN "dist_52w_high_pct" <= -2
                   AND "dist_52w_high_pct" > -10 THEN 1 ELSE 0 END) AS within_10,
          sum(CASE WHEN "dist_52w_high_pct" <= -10
                   AND "dist_52w_high_pct" > -25 THEN 1 ELSE 0 END) AS down_10_25,
          sum(CASE WHEN "dist_52w_high_pct" <= -25
                   AND "dist_52w_high_pct" > -50 THEN 1 ELSE 0 END) AS down_25_50,
          sum(CASE WHEN "dist_52w_high_pct" <= -50 THEN 1 ELSE 0 END) AS down_50
        FROM companies
    """) or {}

    # New highs against new lows -- the classic breadth oscillator. A rising
    # index with more new lows than new highs is a narrowing market.
    hl = db.query_one("""
        SELECT
          sum(CASE WHEN "dist_52w_high_pct" > -1 THEN 1 ELSE 0 END) AS new_highs,
          sum(CASE WHEN "above_52w_low_pct" < 5 THEN 1 ELSE 0 END) AS new_lows,
          sum(CASE WHEN "pct_of_52w_range" > 75 THEN 1 ELSE 0 END) AS upper_quartile,
          sum(CASE WHEN "pct_of_52w_range" < 25 THEN 1 ELSE 0 END) AS lower_quartile,
          round(median("pct_of_52w_range"), 1) AS median_range_position
        FROM companies
    """) or {}

    return {"by": by, "groups": groups, "distance_from_52w_high": dist,
            "high_low": hl}


@router.get("/pulse/valuation")
def pulse_valuation():
    """Valuation spread, not just the median.

    A median P/E says the market is expensive. Quartiles say whether that is
    the whole universe or a long right tail dragging the average.
    """
    tiers = db.query("""
        SELECT "cap_tier" AS tier, count(*) AS n,
          round(quantile_cont("pe_ratio", 0.25), 1) AS p25,
          round(median("pe_ratio"), 1) AS p50,
          round(quantile_cont("pe_ratio", 0.75), 1) AS p75,
          round(quantile_cont("pe_ratio", 0.90), 1) AS p90,
          round(median("peg_ratio"), 2) AS peg,
          round(median("earnings_yield_pct"), 2) AS earnings_yield
        FROM companies WHERE "pe_ratio" IS NOT NULL AND "pe_ratio" > 0
        GROUP BY 1
        ORDER BY CASE "cap_tier" WHEN 'Large' THEN 1 WHEN 'Mid' THEN 2
                                 WHEN 'Small' THEN 3 ELSE 4 END
    """)

    sectors = db.query("""
        SELECT "sector" AS sector, count(*) AS n,
          round(median("pe_ratio"), 1) AS pe,
          round(median("price_to_book"), 2) AS pb,
          round(median("earnings_yield_pct"), 2) AS earnings_yield,
          round(median("pe_vs_own_5y_pct"), 1) AS vs_own_5y
        FROM companies
        WHERE "sector" IS NOT NULL AND "pe_ratio" IS NOT NULL AND "pe_ratio" > 0
        GROUP BY 1 HAVING count(*) >= 5
        ORDER BY pe ASC
    """)
    return {"by_tier": tiers, "by_sector": sectors}


@router.get("/pulse/flows")
def pulse_flows():
    """Institutional ownership by tier, and how it has moved over three years."""
    tiers = db.query("""
        SELECT "cap_tier" AS tier, count(*) AS n,
          round(median("fii_holding"), 2) AS fii,
          round(median("dii_holding"), 2) AS dii,
          round(median("promoter_holding"), 2) AS promoter,
          round(median("chg_fii_holding_3y"), 2) AS fii_chg_3y,
          round(median("chg_dii_holding_3y"), 2) AS dii_chg_3y,
          round(median("chg_promoter_holding_3y"), 2) AS promoter_chg_3y
        FROM companies GROUP BY 1
        ORDER BY CASE "cap_tier" WHEN 'Large' THEN 1 WHEN 'Mid' THEN 2
                                 WHEN 'Small' THEN 3 ELSE 4 END
    """)
    added = db.query("""
        SELECT "symbol", "name", "cap_tier", "fii_holding", "chg_fii_holding_3y"
        FROM companies WHERE "chg_fii_holding_3y" IS NOT NULL
        ORDER BY "chg_fii_holding_3y" DESC LIMIT 6
    """)
    cut = db.query("""
        SELECT "symbol", "name", "cap_tier", "fii_holding", "chg_fii_holding_3y"
        FROM companies WHERE "chg_fii_holding_3y" IS NOT NULL
        ORDER BY "chg_fii_holding_3y" ASC LIMIT 6
    """)
    return {"by_tier": tiers, "fii_added": added, "fii_cut": cut}


@router.get("/pulse/factors")
def pulse_factors():
    """Factor index membership, overlap, and whether members still qualify.

    Index constituents are fixed until the next rebalance, so a momentum-index
    member can sit well below its moving averages for months. That gap is the
    rebalance lag, and it is measurable.
    """
    factors = [r["column_name"] for r in db.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='companies' AND column_name LIKE 'is\\_%' ESCAPE '\\'"
    )]
    known = ["is_momentum", "is_alpha", "is_quality", "is_value",
             "is_low_volatility", "is_high_beta", "is_multifactor"]
    factors = [f for f in known if f in factors]

    rows = []
    for f in factors:
        r = db.query_one(f"""
            SELECT count(*) AS n,
              sum(CASE WHEN "above_ema_200" THEN 1 ELSE 0 END) AS above_ema200,
              sum(CASE WHEN "ema_stack_bullish" THEN 1 ELSE 0 END) AS stacked,
              round(median("perf_1y_pct"), 1) AS median_1y,
              round(median("pe_ratio"), 1) AS median_pe
            FROM companies WHERE "{f}"
        """) or {}
        if r.get("n"):
            r["factor"] = f.removeprefix("is_")
            r["pct_stacked"] = round(100 * (r["stacked"] or 0) / r["n"], 1)
            r["pct_above_ema200"] = round(100 * (r["above_ema200"] or 0) / r["n"], 1)
            rows.append(r)

    pairs = []
    for i, a in enumerate(factors):
        for b in factors[i + 1:]:
            n = (db.query_one(
                f'SELECT count(*) AS n FROM companies WHERE "{a}" AND "{b}"')
                 or {}).get("n", 0)
            if n:
                na = next((r["n"] for r in rows
                           if r["factor"] == a.removeprefix("is_")), 0)
                pairs.append({"a": a.removeprefix("is_"),
                              "b": b.removeprefix("is_"), "overlap": n,
                              "pct_of_a": round(100 * n / na, 1) if na else None})

    tiers = db.query("""
        SELECT "cap_tier" AS tier,
          sum(CASE WHEN "is_momentum" THEN 1 ELSE 0 END) AS momentum,
          sum(CASE WHEN "is_quality" THEN 1 ELSE 0 END) AS quality,
          sum(CASE WHEN "is_value" THEN 1 ELSE 0 END) AS value,
          sum(CASE WHEN "is_low_volatility" THEN 1 ELSE 0 END) AS low_vol
        FROM companies GROUP BY 1
        ORDER BY CASE "cap_tier" WHEN 'Large' THEN 1 WHEN 'Mid' THEN 2
                                 WHEN 'Small' THEN 3 ELSE 4 END
    """)
    return {"factors": rows,
            "overlaps": sorted(pairs, key=lambda p: -p["overlap"])[:8],
            "by_tier": tiers}


@router.get("/pulse/drawdown")
def pulse_drawdown():
    """Earnings drawdown against price drawdown, per company.

    Both axes are a distance from an all-time high -- one in profit, one in
    price. Companies far apart on the two are where the tape and the
    fundamentals disagree.

    The earnings axis is TTM against the highest reported financial year, so a
    company at a record sits slightly ABOVE zero rather than exactly at it.
    """
    pts = db.query("""
        SELECT "symbol", "cap_tier", "sector",
               "pat_ttm_vs_fy_peak_pct" AS earnings, "dist_ath_pct" AS price,
               "market_cap"
        FROM companies
        WHERE "pat_ttm_vs_fy_peak_pct" IS NOT NULL AND "dist_ath_pct" IS NOT NULL
          AND "pat_ttm_vs_fy_peak_pct" > -150
    """)
    quads = db.query_one("""
        SELECT
          sum(CASE WHEN "pat_ttm_vs_fy_peak_pct" > -10 AND "dist_ath_pct" > -20
                   THEN 1 ELSE 0 END) AS both_near_high,
          sum(CASE WHEN "pat_ttm_vs_fy_peak_pct" > -10 AND "dist_ath_pct" <= -20
                   THEN 1 ELSE 0 END) AS earnings_high_price_low,
          sum(CASE WHEN "pat_ttm_vs_fy_peak_pct" <= -10 AND "dist_ath_pct" > -20
                   THEN 1 ELSE 0 END) AS price_high_earnings_low,
          sum(CASE WHEN "pat_ttm_vs_fy_peak_pct" <= -10 AND "dist_ath_pct" <= -20
                   THEN 1 ELSE 0 END) AS both_low
        FROM companies
        WHERE "pat_ttm_vs_fy_peak_pct" IS NOT NULL AND "dist_ath_pct" IS NOT NULL
    """) or {}
    return {"points": pts, "quadrants": quads, "n": len(pts)}


@router.get("/movers")
def movers(field: str = Query("perf_1y_pct"), n: int = Query(10, ge=1, le=50),
           tier: str | None = None):
    """Top and bottom N on any numeric metric."""
    if field not in db.numeric_fields():
        raise HTTPException(422, f"'{field}' is not a numeric field")
    where, params = 'WHERE "%s" IS NOT NULL' % field, []
    if tier:
        where += ' AND "cap_tier" = ?'
        params.append(tier)
    cols = f'"symbol", "name", "sector", "cap_tier", "market_cap", "{field}"'
    top = db.query(f'SELECT {cols} FROM companies {where} '
                   f'ORDER BY "{field}" DESC LIMIT {n}', params)
    bottom = db.query(f'SELECT {cols} FROM companies {where} '
                      f'ORDER BY "{field}" ASC LIMIT {n}', params)
    return {"field": field, "tier": tier, "top": top, "bottom": bottom}
