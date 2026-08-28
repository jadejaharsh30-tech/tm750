"""Data quality reporting.

The dataset has real gaps: nine columns died on coverage, two metrics are
reconstructions, one metric (ROCE) disagrees ~15% between sources, and the
deep profit history thins out for younger listings. None of that is a problem
so long as it is visible. This module makes it visible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def coverage_report(df: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    """Per-column coverage, joined to catalog metadata, worst first."""
    rows = [{
        "column": c,
        "non_null": int(df[c].notna().sum()),
        "coverage_pct": round(df[c].notna().sum() / len(df) * 100, 1),
    } for c in df.columns]
    rep = pd.DataFrame(rows).merge(
        catalog[["name", "segment", "source", "provenance", "screenable"]],
        left_on="column", right_on="name", how="left").drop(columns="name")
    return rep.sort_values("coverage_pct")


def segment_coverage(report: pd.DataFrame) -> pd.DataFrame:
    return (report.groupby("segment")
                  .agg(columns=("column", "size"),
                       median_coverage=("coverage_pct", "median"),
                       min_coverage=("coverage_pct", "min"))
                  .sort_values("median_coverage"))


def source_conflicts(df: pd.DataFrame) -> pd.DataFrame:
    """Quantify disagreement where both sources supply the same concept.

    Retained rather than silently resolved: a 15% median gap on ROCE is a
    formula difference, and any chart built on it inherits that choice.
    """
    pairs = [
        ("price", "price_screener", "Price"),
        ("pe_ratio", "pe_ratio_screener", "P/E"),
        ("dividend_yield", "dividend_yield_screener", "Dividend yield"),
        ("roce", "roce_screener", "ROCE"),
    ]
    rows = []
    for a, b, label in pairs:
        if a not in df or b not in df:
            continue
        x = df[[a, b]].dropna()
        if len(x) < 10:
            continue
        rel = ((x[a] / x[b].replace(0, np.nan) - 1) * 100).abs().dropna()
        rows.append({
            "concept": label,
            "tradingview_col": a,
            "screener_col": b,
            "n_overlap": len(x),
            "correlation": round(float(np.corrcoef(x[a], x[b])[0, 1]), 4),
            "median_abs_diff_pct": round(float(rel.median()), 2),
            "resolution": "both retained" if rel.median() > 5
                          else "tradingview primary",
        })
    return pd.DataFrame(rows)


def history_depth(df: pd.DataFrame) -> pd.DataFrame:
    """How far back the profit history actually reaches.

    Zeros were converted to nulls upstream, so these counts reflect genuine
    reported periods rather than sentinel padding.
    """
    rows = []
    if "qtrs_available" in df:
        q = df["qtrs_available"]
        rows.append({"series": "quarterly PAT", "max_periods": 48,
                     "median_available": float(q.median()),
                     "full_history_n": int((q == 48).sum()),
                     "under_half_n": int((q < 24).sum())})
    if "fy_available" in df:
        y = df["fy_available"]
        rows.append({"series": "annual PAT", "max_periods": 15,
                     "median_available": float(y.median()),
                     "full_history_n": int((y == 15).sum()),
                     "under_half_n": int((y < 8).sum())})
    return pd.DataFrame(rows)


def sector_masking_impact(df: pd.DataFrame, catalog: pd.DataFrame,
                          finance_sector: str = "Finance") -> dict:
    """How much data the finance-sector mask suppresses."""
    masked = catalog.loc[~catalog["finance_valid"], "name"].tolist()
    n_fin = int((df["sector"] == finance_sector).sum())
    return {
        "finance_companies": n_fin,
        "finance_pct_of_universe": round(n_fin / len(df) * 100, 1),
        "masked_metrics": len(masked),
        "masked_list": masked,
        "rationale": "ROCE, ROIC, EV/EBITDA, current ratio and inventory "
                     "turnover are structurally meaningless for banks, NBFCs "
                     "and insurers. Ranking them on these produces confident "
                     "nonsense, so the dashboard masks rather than ranks.",
    }


def build_report(df: pd.DataFrame, catalog: pd.DataFrame,
                 drop_ledger: pd.DataFrame,
                 reconstruction_checks: list[dict]) -> dict:
    cov = coverage_report(df, catalog)
    return {
        "universe": len(df),
        "columns_retained": df.shape[1],
        "columns_dropped": len(drop_ledger),
        "drop_reasons": drop_ledger["reason"].value_counts().to_dict()
                        if len(drop_ledger) else {},
        "fully_populated_columns": int((cov["coverage_pct"] == 100).sum()),
        "columns_below_50pct": int((cov["coverage_pct"] < 50).sum()),
        "non_screenable_columns": int((~cov["screenable"].fillna(True)).sum()),
        "segment_coverage": segment_coverage(cov).reset_index()
                            .to_dict("records"),
        "source_conflicts": source_conflicts(df).to_dict("records"),
        "history_depth": history_depth(df).to_dict("records"),
        "reconstruction_checks": reconstruction_checks,
        "sector_masking": sector_masking_impact(df, catalog),
    }
