"""Price layer.

Adjustment policy, the single most important rule in this module:

    yfinance never adjusts anything for us.

Every call is auto_adjust=False, actions=True -- raw OHLC plus the corporate
action columns, in one request. Split factors are applied here; dividend
adjustment is never applied at all, because an all-time high is a price
record, not a total-return record.

Why this matters, measured on the reference app: it seeds full history with
auto_adjust=False but daily-updates with auto_adjust=True. Two adjustment
bases writing into one 'ATH Price' cell. Its two ATH stores overlap on 754
symbols and agree within 0.01% on only 147 of them, median drift +1.06%, with
split artefacts at the tails (V2RETAIL -90.0%, ANGELONE -89.8%).
"""
from __future__ import annotations

import time
from datetime import date as _date

import pandas as pd

from tm750.scanner import store

SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


# --------------------------------------------------------------- split math
def split_factors(splits: pd.Series) -> pd.Series:
    """Cumulative product of every split ratio dated strictly AFTER each bar.

    A bar priced before a 2-for-1 needs dividing by 2 to be expressed in
    today's shares. The bar on the ex-date is already quoted in new shares, so
    its own ratio must be excluded -- hence the shift.
    """
    ratios = splits.replace(0, 1.0).fillna(1.0).astype(float)
    reverse_cum = ratios[::-1].cumprod()[::-1]
    return reverse_cum.shift(-1).fillna(1.0)


def adjust_highs(high: pd.Series, splits: pd.Series) -> pd.Series:
    """Raw highs -> current-share terms."""
    return high / split_factors(splits)


def ath_from_history(df: pd.DataFrame) -> tuple[float | None, object | None]:
    """Lifetime high and its date, split-adjusted.

    Replaces the monthly-scan-then-drill-into-the-month hybrid in the
    reference app, which exists only because that app keeps no price history.
    With the full series in hand, idxmax gives the date for free -- and the
    fallback-to-month-start branch disappears with it.
    """
    if df is None or df.empty or "High" not in df:
        return None, None
    splits = (df["Stock Splits"] if "Stock Splits" in df
              else pd.Series(0.0, index=df.index))
    adj = adjust_highs(df["High"], splits).dropna()
    if adj.empty:
        return None, None
    when = adj.idxmax()
    return float(adj.max()), when.date() if hasattr(when, "date") else when


# ------------------------------------------------------------ yfinance I/O
def yf_symbol(symbol: str, exchange: str = "NSE") -> str:
    return f"{symbol}{SUFFIX.get(exchange, '.NS')}"


def download_batch(tickers: list[str], period: str = "5d",
                   interval: str = "1d", retries: int = 3) -> pd.DataFrame:
    """Batch download. Unadjusted, with actions, always.

    period='5d' rather than '1d' so a previous close exists after weekends and
    holidays -- the green-candle test needs two closes.
    """
    import yfinance as yf

    backoff = [2, 5, 10]
    for attempt in range(retries):
        try:
            data = yf.download(tickers, period=period, interval=interval,
                               auto_adjust=False, actions=True,
                               progress=False, timeout=30)
            if data is not None and not data.empty:
                return data
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(backoff[attempt])
    return pd.DataFrame()


def extract(data: pd.DataFrame, ticker: str, field: str) -> pd.Series | None:
    """Pull one field for one ticker regardless of column orientation.

    yfinance has shipped both (field, ticker) and (ticker, field) MultiIndex
    layouts across versions, and flat columns for a single ticker. A symbol
    that fails partway through a batch download can appear PARTIALLY in the
    column index -- present under one field (e.g. Volume) but absent under
    another (e.g. High) -- so membership is checked on the EXACT (field,
    ticker) pair, never on the two index levels independently. Checking them
    independently can both pass even when that specific column does not
    exist, which is precisely what took the scanner down on AKZOINDIA: a bare
    KeyError from data['High']['AKZOINDIA.NS'] when AKZOINDIA only appeared
    under a different field.
    """
    if data is None or data.empty:
        return None
    cols = data.columns
    if isinstance(cols, pd.MultiIndex):
        if (field, ticker) in cols:
            return data[(field, ticker)]
        if (ticker, field) in cols:
            return data[(ticker, field)]
        return None
    return data[field] if field in cols else None


def full_history(ticker: str, retries: int = 3) -> pd.DataFrame:
    """Complete daily history for seeding. Unadjusted, with actions."""
    import yfinance as yf

    backoff = [2, 5, 10]
    for attempt in range(retries):
        try:
            df = yf.Ticker(ticker).history(
                period="max", interval="1d", auto_adjust=False, actions=True)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(backoff[attempt])
    return pd.DataFrame()


# ------------------------------------------------------------ ATH store ops
def _log(symbol, old_price, new_price, old_date, new_date, source, note=None):
    store.cursor().execute(
        """INSERT INTO ath_events
               (symbol, event_date, old_price, new_price, old_date, new_date,
                source, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [symbol, new_date or _date.today().isoformat(), old_price, new_price,
         old_date, new_date, source, note])


def promote(symbols: list[str], event_date: str | None = None) -> int:
    """EOD Sync: today's confirmed high becomes tomorrow's trigger.

    Only where today_ath actually exceeds the stored trigger, which makes a
    second run a no-op rather than a corruption. today_ath is then cleared
    GLOBALLY, not just for promoted names -- otherwise an unpromoted hit
    carries a stale intraday value into tomorrow's comparison.
    """
    when = event_date or _date.today().isoformat()
    cur = store.cursor()
    rows = []
    if symbols:
        placeholders = ",".join("?" * len(symbols))
        rows = cur.execute(
            f"""SELECT symbol, ath_price, ath_date, today_ath FROM ath
                WHERE symbol IN ({placeholders})
                  AND today_ath IS NOT NULL
                  AND today_ath > COALESCE(ath_price, 0)""",
            list(symbols)).fetchall()

    for symbol, old_price, old_date, today in rows:
        cur.execute(
            """UPDATE ath SET ath_price = ?, ath_date = ?,
                   last_updated = current_timestamp
               WHERE symbol = ?""", [today, when, symbol])
        _log(symbol, old_price, today,
             old_date.isoformat() if old_date else None, when, "sync")

    cur.execute("UPDATE ath SET today_ath = NULL")
    return len(rows)


def apply_split(symbol: str, ratio: float, split_date: str) -> float | None:
    """Rescale the stored trigger rather than re-deriving it, and record that
    this split has now been accounted for.

    Re-deriving from a fresh yfinance pull is what produced the reference
    app's divergence: one number, two write paths, two adjustment bases.

    last_split_check is bumped to split_date (never moved backwards) so the
    SAME split -- which a 5-day lookback window keeps re-including for
    several days after it actually happened -- is recognised as already
    handled on every later scan. This is the piece an earlier version of this
    fix was missing: it compared against ath_date, which this function never
    updated, so nothing recorded that a repair had already happened, and
    every subsequent scan halved the price again (the TDPOWERSYS bug).
    """
    if not ratio or ratio <= 0:
        return None
    cur = store.cursor()
    row = cur.execute(
        "SELECT ath_price, ath_date, last_split_check FROM ath "
        "WHERE symbol = ?", [symbol]).fetchone()
    if row is None or row[0] is None:
        return None
    old_price, old_date, prev_check = row
    new_price = old_price / ratio

    new_check = split_date
    if prev_check is not None and str(prev_check) > split_date:
        new_check = str(prev_check)

    cur.execute(
        """UPDATE ath SET ath_price = ?, last_split_check = ?,
               last_updated = current_timestamp
           WHERE symbol = ?""", [new_price, new_check, symbol])
    iso_old = old_date.isoformat() if old_date else None
    _log(symbol, old_price, new_price, iso_old, split_date, "split",
         f"split ratio {ratio}")
    return new_price


def clear_all(wipe_events: bool = False) -> dict:
    """Wipe every stored ATH price and trigger, for a full clean re-seed
    under corrected logic. Recovery path for a correctness bug that may have
    touched an unknown number of symbols -- exactly the TDPOWERSYS case,
    where the repeated-halving bug could have fired on ANY symbol whose
    price window happened to contain a split, on any scan run since this
    feature first shipped, not just the one symbol that happened to be
    checked.

    ath_events is preserved by default. It is a historical record of what
    actually happened, bug included, which has real diagnostic value -- pass
    wipe_events=True for a fully blank slate instead.

    Universe and profit data are untouched. This is scoped strictly to
    price/ATH state, which is the only thing this class of bug could have
    corrupted.
    """
    cur = store.cursor()
    n = cur.execute("SELECT count(*) FROM ath").fetchone()[0]
    cur.execute("DELETE FROM ath")
    events_cleared = 0
    if wipe_events:
        events_cleared = cur.execute(
            "SELECT count(*) FROM ath_events").fetchone()[0]
        cur.execute("DELETE FROM ath_events")
    return {"ath_rows": n, "events_cleared": events_cleared}


def suspected_repeat_halvings() -> list[dict]:
    """Symbols with 2+ logged split-repair events -- a strong signal of the
    repeated-halving bug, since a genuinely correct split only ever needs
    repairing once.

    This is a LOWER BOUND, not a complete list: a symbol caught by the bug on
    only a single scan run before being noticed would show just one event,
    indistinguishable here from a legitimate one-time repair. Useful for
    gauging how many symbols were affected; not a substitute for a full
    re-seed if certainty matters.
    """
    rows = store.cursor().execute(
        """SELECT symbol, count(*) AS n
           FROM ath_events WHERE source = 'split'
           GROUP BY symbol HAVING count(*) >= 2
           ORDER BY n DESC, symbol""").fetchall()
    return [{"symbol": s, "split_events": n} for s, n in rows]


def manual_edit(symbol: str, price: float, date: str) -> None:
    """Operator override from Manage Database. Always logged.

    Also bumps last_split_check to today: a human setting a specific price is
    asserting it is correct as of now, so a split already reflected in
    market data by today must not be auto-applied on top of it at the next
    scan -- exactly the trap that made recovering TDPOWERSYS by hand keep
    getting undone by the very next run, before this fix.
    """
    cur = store.cursor()
    row = cur.execute(
        "SELECT ath_price, ath_date FROM ath WHERE symbol = ?",
        [symbol]).fetchone()
    old_price, old_date = row if row else (None, None)
    today = _date.today().isoformat()
    cur.execute(
        """INSERT INTO ath (symbol, ath_price, ath_date, last_split_check,
               last_updated)
           VALUES (?, ?, ?, ?, current_timestamp)
           ON CONFLICT (symbol) DO UPDATE SET
               ath_price = excluded.ath_price,
               ath_date = excluded.ath_date,
               last_split_check = excluded.last_split_check,
               last_updated = now()""",
        [symbol, price, date, today])
    _log(symbol, old_price, price,
         old_date.isoformat() if old_date else None, date, "manual")


def seed(symbol: str, exchange: str = "NSE") -> tuple[float | None, object]:
    """Establish a lifetime high for a symbol that has none.

    Full history already incorporates every split up to the most recent bar
    fetched, so last_split_check is set to that bar's date -- a split
    detected on a later scan is genuinely new; anything up to today is
    already baked into the price.
    """
    df = full_history(yf_symbol(symbol, exchange))
    price, when = ath_from_history(df)
    if price is None:
        return None, None
    iso = when.isoformat() if hasattr(when, "isoformat") else str(when)

    last_bar = df.index.max()
    checked = (last_bar.date().isoformat() if hasattr(last_bar, "date")
              else str(last_bar))

    store.cursor().execute(
        """INSERT INTO ath (symbol, ath_price, ath_date, last_split_check,
               last_updated)
           VALUES (?, ?, ?, ?, current_timestamp)
           ON CONFLICT (symbol) DO UPDATE SET
               ath_price = excluded.ath_price,
               ath_date = excluded.ath_date,
               last_split_check = excluded.last_split_check,
               last_updated = now()""",
        [symbol, price, iso, checked])
    _log(symbol, None, price, None, iso, "seed")
    return price, when
