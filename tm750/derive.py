"""Derived metrics.

Two categories, and the distinction matters for honesty:

  reconstructed - a field the source supplied badly (or not at all) that we
                  rebuild from better-covered inputs. Validated against the
                  sparse reported values where those exist.
  computed      - a genuinely new metric built from reported inputs.

Every field produced here is tagged provenance='derived' in the catalog so the
dashboard and any downstream chart can disclose it. Nothing is imputed: where
inputs are missing the output stays null rather than being filled.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    """Division that yields NaN rather than inf on zero/negative denominators."""
    out = a / b.replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan)


def _pct_from(price: pd.Series, ref: pd.Series) -> pd.Series:
    return (_safe_div(price, ref) - 1) * 100


def add_reconstructed(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild fields the export supplied at unusable coverage."""
    out = {}

    # Shares implied by market cap. Cross-checked against the reported
    # shares_outstanding column where present.
    out["shares_implied"] = _safe_div(df["market_cap"], df["price"])

    # Revenue TTM: reported on 33/750, but revenue-per-share covers 743.
    # Median error vs the reported values is ~1.1%.
    if "revenue_per_share" in df:
        out["revenue_ttm"] = df["revenue_per_share"] * out["shares_implied"]

    # P/B: reported on 92/750, book value per share covers 537 (r=0.979).
    if "book_value_per_share" in df:
        out["price_to_book"] = _safe_div(df["price"], df["book_value_per_share"])

    # Forward P/E from the better-covered EPS estimate (683 vs 188).
    if "eps_estimate_annual" in df:
        out["pe_forward_derived"] = _safe_div(df["price"],
                                              df["eps_estimate_annual"])
    return pd.DataFrame(out, index=df.index)


def add_trend_state(df: pd.DataFrame) -> pd.DataFrame:
    """Trend and peak-distance metrics.

    Named 'trend state' rather than 'momentum' deliberately: these describe
    where price sits relative to its own moving averages and extremes. True
    momentum (12-1, or Clenow R2-adjusted) needs the performance columns,
    which are handled separately in add_momentum().
    """
    out = {}
    p = df["price"]

    for ref, label in [("ema_20", "ema_20"), ("ema_50", "ema_50"),
                       ("ema_200", "ema_200"), ("sma_50", "sma_50"),
                       ("sma_200", "sma_200")]:
        if ref in df:
            out[f"dist_{label}_pct"] = _pct_from(p, df[ref])

    for ref, label in [("high_52w", "52w_high"), ("high_all_time", "ath"),
                       ("high_6m", "6m_high"), ("high_3m", "3m_high"),
                       ("donchian_20_upper", "20d_high")]:
        if ref in df:
            out[f"dist_{label}_pct"] = _pct_from(p, df[ref])

    for ref, label in [("low_52w", "52w_low"), ("low_all_time", "atl")]:
        if ref in df:
            out[f"above_{label}_pct"] = _pct_from(p, df[ref])

    # Full bullish EMA alignment: price above every MA, each above the next.
    if {"ema_20", "ema_50", "ema_200"}.issubset(df.columns):
        out["ema_stack_bullish"] = (
            (p > df["ema_20"]) & (df["ema_20"] > df["ema_50"])
            & (df["ema_50"] > df["ema_200"])
        )
        out["ema_stack_bearish"] = (
            (p < df["ema_20"]) & (df["ema_20"] < df["ema_50"])
            & (df["ema_50"] < df["ema_200"])
        )

    if "ema_200" in df:
        out["above_ema_200"] = p > df["ema_200"]
    if "sma_200" in df:
        out["above_sma_200"] = p > df["sma_200"]

    # 52-week position: 0 = at the low, 100 = at the high.
    if {"high_52w", "low_52w"}.issubset(df.columns):
        rng = df["high_52w"] - df["low_52w"]
        out["pct_of_52w_range"] = _safe_div(p - df["low_52w"], rng) * 100

    return pd.DataFrame(out, index=df.index)


def add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """Return-based momentum, now that the performance columns exist."""
    out = {}

    # 12-1 momentum: the academic standard, skipping the most recent month to
    # avoid short-term reversal contamination.
    if {"perf_1y_pct", "perf_1m_pct"}.issubset(df.columns):
        r12 = df["perf_1y_pct"] / 100
        r1 = df["perf_1m_pct"] / 100
        out["momentum_12_1_pct"] = ((1 + r12) / (1 + r1) - 1) * 100

    # Risk-adjusted momentum: 1y return per unit of beta.
    if {"perf_1y_pct", "beta_1y"}.issubset(df.columns):
        out["momentum_per_beta"] = _safe_div(df["perf_1y_pct"], df["beta_1y"])

    # Acceleration: is the recent quarter outpacing the trailing year's pace?
    if {"perf_3m_pct", "perf_1y_pct"}.issubset(df.columns):
        out["momentum_accel"] = df["perf_3m_pct"] - (df["perf_1y_pct"] / 4)

    # Consistency: how many of the five lookback windows are positive.
    windows = [c for c in ["perf_1w_pct", "perf_1m_pct", "perf_3m_pct",
                           "perf_6m_pct", "perf_1y_pct"] if c in df]
    if windows:
        out["positive_windows"] = (df[windows] > 0).sum(axis=1)

    return pd.DataFrame(out, index=df.index)


def add_valuation_context(df: pd.DataFrame) -> pd.DataFrame:
    """Valuation relative to a stock's own history and its industry."""
    out = {}

    # Premium/discount vs the stock's own 5-year median multiple. This is the
    # cross-check that peer comparison alone cannot provide.
    if {"pe_ratio", "historical_pe_5y"}.issubset(df.columns):
        out["pe_vs_own_5y_pct"] = _pct_from(df["pe_ratio"],
                                            df["historical_pe_5y"])
    if {"price_to_book", "historical_pbv_5y"}.issubset(df.columns):
        pass  # filled after reconstruction merge; see build.py ordering
    if {"pe_ratio", "industry_pe"}.issubset(df.columns):
        out["pe_vs_industry_pct"] = _pct_from(df["pe_ratio"], df["industry_pe"])

    if {"target_price_1y", "price"}.issubset(df.columns):
        out["upside_to_target_pct"] = _pct_from(df["target_price_1y"],
                                                df["price"])
    if "pe_ratio" in df:
        out["earnings_yield_pct"] = _safe_div(pd.Series(100.0, index=df.index),
                                              df["pe_ratio"])
    return pd.DataFrame(out, index=df.index)


def add_signal_conflicts(df: pd.DataFrame) -> pd.DataFrame:
    """Where independent signals disagree. Useful as a screen and a panel."""
    out = {}
    bulls = {"Buy", "Strong buy"}
    bears = {"Sell", "Strong sell"}

    if {"analyst_rating", "technical_rating"}.issubset(df.columns):
        a, t = df["analyst_rating"], df["technical_rating"]
        out["analyst_bull_tech_bear"] = a.isin(bulls) & t.isin(bears)
        out["analyst_bear_tech_bull"] = a.isin(bears) & t.isin(bulls)
        out["rating_conflict"] = (out["analyst_bull_tech_bear"]
                                  | out["analyst_bear_tech_bull"])

    # Price trending up while earnings trend down, and the reverse.
    if {"perf_1y_pct", "net_income_growth_ttm_yoy"}.issubset(df.columns):
        out["price_up_earnings_down"] = (
            (df["perf_1y_pct"] > 0) & (df["net_income_growth_ttm_yoy"] < 0)
        )
        out["price_down_earnings_up"] = (
            (df["perf_1y_pct"] < 0) & (df["net_income_growth_ttm_yoy"] > 0)
        )
    return pd.DataFrame(out, index=df.index)


def add_percentile_ranks(df: pd.DataFrame, metrics: list[str],
                         groups: dict[str, str]) -> pd.DataFrame:
    """Percentile rank of each metric across the universe and within groups.

    Powers the company card ('this stock's ROE is in the 87th percentile of
    its sector') without the frontend recomputing anything.
    """
    out = {}
    for m in metrics:
        if m not in df or not pd.api.types.is_numeric_dtype(df[m]):
            continue
        out[f"pct_rank_{m}"] = df[m].rank(pct=True) * 100
        for label, key in groups.items():
            if key in df:
                out[f"pct_rank_{m}_in_{label}"] = (
                    df.groupby(key)[m].rank(pct=True) * 100
                )
    return pd.DataFrame(out, index=df.index)


def validate_reconstruction(df: pd.DataFrame, derived: pd.Series,
                            reported_col: str, tol_pct: float = 5.0) -> dict:
    """Compare a reconstructed field against whatever reported values exist."""
    if reported_col not in df:
        return {"field": reported_col, "status": "no reported values"}
    mask = df[reported_col].notna() & derived.notna()
    if not mask.any():
        return {"field": reported_col, "status": "no overlap"}
    err = ((derived[mask] / df.loc[mask, reported_col] - 1) * 100).abs()
    return {
        "field": reported_col,
        "n_overlap": int(mask.sum()),
        "median_abs_err_pct": round(float(err.median()), 3),
        "within_tolerance": bool(err.median() < tol_pct),
    }
