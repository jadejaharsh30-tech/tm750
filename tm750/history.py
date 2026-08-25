"""Profit history: wide-to-long reshape plus derived trajectory metrics.

Critical handling note: zeros in these exports are missing-data sentinels
(the company was not listed in that period), NOT reported zero profit.
Confirmed by the presence of negatives elsewhere in the same columns --
44 companies show a negative most-recent quarter, so losses are encoded as
negatives and zero genuinely means 'no data'. Treating zeros as real would
manufacture false losses and corrupt every growth calculation downstream.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FY_PERIODS, PROFIT_ZERO_IS_NULL, QTR_PERIODS


def _nullify_sentinels(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if not PROFIT_ZERO_IS_NULL:
        return df
    out = df.copy()
    out[cols] = out[cols].replace(0, np.nan)
    return out


def reshape_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    """QL1..QL48 -> long. QL1 is the most recent quarter (verified r=0.983
    against Screener's reported latest-quarter profit)."""
    cols = [f"QL{i}" for i in range(1, QTR_PERIODS + 1)]
    df = _nullify_sentinels(df, cols)
    long = df.melt(id_vars="isin", value_vars=cols,
                   var_name="period", value_name="pat")
    long["periods_ago"] = long["period"].str.removeprefix("QL").astype(int) - 1
    long["freq"] = "Q"
    return long.dropna(subset=["pat"]).sort_values(["isin", "periods_ago"])


def reshape_yearly(df: pd.DataFrame) -> pd.DataFrame:
    """FYL1..FYL15 -> long. FYL1 is the most recent financial year."""
    cols = [f"FYL{i}" for i in range(1, FY_PERIODS + 1)]
    df = _nullify_sentinels(df, cols + ["TTM"])
    long = df.melt(id_vars="isin", value_vars=cols,
                   var_name="period", value_name="pat")
    long["periods_ago"] = long["period"].str.removeprefix("FYL").astype(int) - 1
    long["freq"] = "FY"
    return long.dropna(subset=["pat"]).sort_values(["isin", "periods_ago"])


def _cagr(latest: pd.Series, earliest: pd.Series, years: float) -> pd.Series:
    """CAGR, defined only where both endpoints are positive.

    Growth rates across a sign change are mathematically meaningless -- a swing
    from -50 to +100 has no compound rate. Those cases return NaN rather than
    a fabricated number.
    """
    valid = (latest > 0) & (earliest > 0)
    out = pd.Series(np.nan, index=latest.index, dtype=float)
    out[valid] = ((latest[valid] / earliest[valid]) ** (1 / years) - 1) * 100
    return out


def summarise_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    """Per-company quarterly trajectory metrics."""
    cols = [f"QL{i}" for i in range(1, QTR_PERIODS + 1)]
    d = _nullify_sentinels(df, cols).set_index("isin")
    q = d[cols]

    out = pd.DataFrame(index=q.index)
    out["qtrs_available"] = q.notna().sum(axis=1)
    out["pat_latest_q"] = q["QL1"]

    # YoY: current quarter vs the same quarter last year (4 back).
    out["pat_yoy_q_pct"] = ((q["QL1"] / q["QL5"].abs()) - 1) * 100
    out["pat_qoq_pct"] = ((q["QL1"] / q["QL2"].abs()) - 1) * 100

    # Trailing four-quarter sums, current vs prior year.
    ttm_now = q[["QL1", "QL2", "QL3", "QL4"]].sum(axis=1, min_count=4)
    ttm_prev = q[["QL5", "QL6", "QL7", "QL8"]].sum(axis=1, min_count=4)
    out["pat_ttm"] = ttm_now
    out["pat_ttm_prev"] = ttm_prev
    out["pat_ttm_growth_pct"] = ((ttm_now / ttm_prev.abs()) - 1) * 100

    # Consistency and stability across the full available history.
    out["profitable_qtrs"] = (q > 0).sum(axis=1)
    out["loss_qtrs"] = (q < 0).sum(axis=1)
    out["profitable_qtr_pct"] = (out["profitable_qtrs"]
                                 / out["qtrs_available"] * 100)
    out["pat_qtr_volatility"] = q.std(axis=1) / q.mean(axis=1).abs() * 100

    # Consecutive profitable quarters from the most recent backwards.
    streak = pd.Series(0, index=q.index, dtype=int)
    alive = pd.Series(True, index=q.index)
    for c in cols:
        pos = (q[c] > 0) & alive
        streak += pos.astype(int)
        alive &= pos
    out["profit_streak_qtrs"] = streak

    # Peak single quarter, and how far the latest sits below it.
    q_peak = q.max(axis=1)
    out["pat_peak_q"] = q_peak
    out["pat_q_vs_peak_pct"] = ((q["QL1"] / q_peak.abs()) - 1) * 100
    out["pat_q_at_ath"] = (q["QL1"] >= q_peak) & q["QL1"].notna() & (q_peak > 0)

    # Rolling four-quarter sums across the whole history. TTM profit at an
    # all-time high is a cleaner signal than a single quarter, which carries
    # whatever seasonality the business happens to have.
    ttm_series = {}
    for i in range(1, QTR_PERIODS - 2):
        window = [f"QL{j}" for j in range(i, i + 4)]
        ttm_series[f"T{i}"] = q[window].sum(axis=1, min_count=4)
    ttm_all = pd.DataFrame(ttm_series, index=q.index)
    ttm_peak = ttm_all.max(axis=1)
    out["pat_ttm_peak"] = ttm_peak
    out["pat_ttm_vs_peak_pct"] = ((ttm_now / ttm_peak.abs()) - 1) * 100
    out["pat_ttm_at_ath"] = (ttm_now >= ttm_peak) & ttm_now.notna() & (ttm_peak > 0)
    return out.reset_index()


def summarise_yearly(df: pd.DataFrame) -> pd.DataFrame:
    """Per-company annual trajectory metrics, including long-horizon CAGRs."""
    cols = [f"FYL{i}" for i in range(1, FY_PERIODS + 1)]
    d = _nullify_sentinels(df, cols + ["TTM"]).set_index("isin")
    y = d[cols]

    out = pd.DataFrame(index=y.index)
    out["fy_available"] = y.notna().sum(axis=1)
    out["pat_ttm_reported"] = d["TTM"]
    out["pat_fy1"] = y["FYL1"]

    for n in (3, 5, 7, 10, 15):
        col = f"FYL{n}"
        if col in y:
            out[f"pat_cagr_{n}y_pct"] = _cagr(y["FYL1"], y[col], n - 1)

    out["profitable_fy"] = (y > 0).sum(axis=1)
    out["loss_fy"] = (y < 0).sum(axis=1)
    out["profitable_fy_pct"] = out["profitable_fy"] / out["fy_available"] * 100

    # Peak PAT and how far the latest year sits below it -- an earnings
    # drawdown, directly analogous to a price drawdown.
    peak = y.max(axis=1)
    out["pat_peak_fy"] = peak
    out["pat_vs_peak_pct"] = ((y["FYL1"] / peak.abs()) - 1) * 100
    # A loss-making peak is not an all-time high in any useful sense, so
    # require the peak itself to be positive.
    out["pat_fy_at_ath"] = (y["FYL1"] >= peak) & y["FYL1"].notna() & (peak > 0)

    streak = pd.Series(0, index=y.index, dtype=int)
    alive = pd.Series(True, index=y.index)
    for c in cols:
        pos = (y[c] > 0) & alive
        streak += pos.astype(int)
        alive &= pos
    out["profit_streak_fy"] = streak

    # Consecutive years of PAT growth from the most recent backwards.
    g_streak = pd.Series(0, index=y.index, dtype=int)
    alive = pd.Series(True, index=y.index)
    for i in range(1, FY_PERIODS):
        grew = (y[f"FYL{i}"] > y[f"FYL{i+1}"]) & alive
        g_streak += grew.astype(int)
        alive &= grew
    out["pat_growth_streak_fy"] = g_streak
    return out.reset_index()
