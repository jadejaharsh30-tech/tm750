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


def _quarter_at_ath(q: pd.DataFrame) -> pd.Series:
    """Latest quarter is the highest on record.

    Shared by summarise_quarterly and profit_at_ath so the two can never
    drift apart. A loss-making peak is not an all-time high in any useful
    sense, hence the peak > 0 requirement.
    """
    peak = q.max(axis=1)
    return (q["QL1"] >= peak) & q["QL1"].notna() & (peak > 0)


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
    out["pat_q_at_ath"] = _quarter_at_ath(q)

    # Rolling four-quarter sums across the whole history.
    #
    # DESCRIPTIVE ONLY -- these must never feed pat_both_at_ath. The record
    # test is TTM against the reported financial-year series (profit_at_ath),
    # not against synthetic windows that straddle year ends. The two disagree:
    # rolling windows reach back 12 years but can find a peak spanning two
    # part-years that no reported FY ever shows, while the FY series reaches
    # 15 years. Kept because the drawdown-from-rolling-peak reading is useful
    # in its own right, renamed so it cannot be mistaken for the verdict.
    ttm_series = {}
    for i in range(1, QTR_PERIODS - 2):
        window = [f"QL{j}" for j in range(i, i + 4)]
        ttm_series[f"T{i}"] = q[window].sum(axis=1, min_count=4)
    ttm_all = pd.DataFrame(ttm_series, index=q.index)
    ttm_peak = ttm_all.max(axis=1)
    out["pat_ttm_peak_rolling"] = ttm_peak
    out["pat_ttm_vs_peak_rolling_pct"] = ((ttm_now / ttm_peak.abs()) - 1) * 100
    out["pat_ttm_at_ath_rolling"] = (
        (ttm_now >= ttm_peak) & ttm_now.notna() & (ttm_peak > 0))
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


def profit_at_ath(q_df: pd.DataFrame, y_df: pd.DataFrame) -> pd.DataFrame:
    """The record test: TTM against reported financial years, and the latest
    quarter against every quarter on record.

    Two horizons, both of which must hold:

    1. TTM at ATH -- trailing twelve months (QL1+QL2+QL3+QL4, computed ONCE,
       not rolled) compared against the reported annual series FYL1..FYL15.
       The comparison series is therefore [TTM, FY1, FY2, ... FY15]: the live
       rolling year measured against every completed year the company has
       reported.

    2. Quarter at ATH -- QL1 against the highest of QL1..QL48.

    Why FY rather than rolling four-quarter windows: a reported financial year
    is a real, audited period the market prices off. A synthetic window
    spanning, say, Sep-24 to Jun-25 is not a period the company ever reported,
    and a peak found there is an artefact of the window, not a record the
    business set.

    The March case is intentional. When QL1 is the March quarter, QL1..QL4
    spans exactly the financial year, so TTM equals FY1 once that row lands.
    The >= comparison lets equality pass -- being level with FY1 is not a
    failure. It only fails if an EARLIER financial year beat it.

    Returns only the columns neither summarise_ function already produces, so
    the three merge without collision:
        pat_ttm_at_ath, pat_ttm_vs_fy_peak_pct, pat_both_at_ath
    """
    q_cols = [f"QL{i}" for i in range(1, QTR_PERIODS + 1)]
    y_cols = [f"FYL{i}" for i in range(1, FY_PERIODS + 1)]

    q = _nullify_sentinels(q_df, q_cols).set_index("isin")[q_cols]
    y = _nullify_sentinels(y_df, y_cols).set_index("isin")[y_cols]

    q = q[~q.index.duplicated(keep="first")]
    y = y[~y.index.duplicated(keep="first")]

    # A company in one feed but not the other still gets a row; its missing
    # half yields NaN, which falls through to False rather than to a verdict.
    idx = q.index.union(y.index)
    q = q.reindex(idx)
    y = y.reindex(idx)

    # Computed once. No rolling.
    ttm = q[["QL1", "QL2", "QL3", "QL4"]].sum(axis=1, min_count=4)
    fy_peak = y.max(axis=1)

    out = pd.DataFrame(index=idx)
    out["pat_ttm_vs_fy_peak_pct"] = ((ttm / fy_peak.abs()) - 1) * 100

    # Requires the peak itself to be positive: a company whose best-ever year
    # was a loss is not at a record.
    out["pat_ttm_at_ath"] = (ttm >= fy_peak) & ttm.notna() & (fy_peak > 0)
    out["pat_q_at_ath_"] = _quarter_at_ath(q)
    out["pat_both_at_ath"] = (out["pat_ttm_at_ath"].fillna(False)
                              & out["pat_q_at_ath_"].fillna(False))
    out = out.drop(columns=["pat_q_at_ath_"])

    out.index.name = "isin"
    return out.reset_index()
