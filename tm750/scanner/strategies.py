"""The four strategies.

Rules are carried over verbatim from the running app's scanner_engine so both
systems produce the same verdicts on the same day. The 211-session window and
the 0.9999 tolerance are its tested constants, not guesses.

Pure functions over series and scalars -- no I/O, no database, so every branch
is testable without a network.
"""
from __future__ import annotations

import pandas as pd

from tm750.config import RS_TOLERANCE, RS_WINDOW


def green_candle(today_close: float | None, prev_close: float | None) -> str:
    """Today closed at or above yesterday. Flat counts as green."""
    if today_close is None or prev_close is None:
        return "N/A"
    return "Y" if today_close >= prev_close else "N"


def close_gt_ath(today_close: float | None,
                 trigger_price: float | None) -> str:
    """Cleared the old high on a closing basis, not merely intraday.

    Strictly greater. Note that after EOD Sync the trigger equals today's
    high, so this can never return Y on a same-day re-scan -- close <= high
    always. That is correct post-sync state rather than a dead strategy, and
    the UI banners it so it is never mistaken for a bug.
    """
    if today_close is None or trigger_price is None:
        return "N/A"
    return "Y" if today_close > trigger_price else "N"


def relative_strength(stock_close: pd.Series | None,
                      index_close: pd.Series | None,
                      window: int = RS_WINDOW,
                      tolerance: float = RS_TOLERANCE) -> dict:
    """Fixed-anchor relative strength against the benchmark.

    The stock/index ratio, re-based to 100 at the start of the window. Y when
    today's anchored value sits within 0.01% of the window maximum -- relative
    strength is also making a high, not just absolute price.

    Insufficient history returns N/A rather than N: a recent listing has not
    failed the test, it has not been given it.
    """
    blank = {"ath_outperformance": "N/A", "current_rs": None, "ath_rs": None}
    if stock_close is None or index_close is None:
        return blank

    joined = pd.concat([stock_close.rename("s"), index_close.rename("i")],
                       axis=1).dropna()
    if len(joined) < window:
        return blank

    tail = joined.iloc[-window:]
    ratio = tail["s"] / tail["i"]
    anchor = ratio.iloc[0]
    if anchor == 0 or pd.isna(anchor):
        return blank

    anchored = ratio / anchor * 100
    current = float(anchored.iloc[-1])
    peak = float(anchored.max())
    return {
        "ath_outperformance": "Y" if current >= peak * tolerance else "N",
        "current_rs": round(current, 2),
        "ath_rs": round(peak, 2),
    }
