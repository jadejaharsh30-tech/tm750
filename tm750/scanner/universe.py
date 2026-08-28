"""Universe: the scan list, uploaded once from Excel and persisted.

Symbol -> ISIN resolution happens here, at upload, not on every scan.

Measured against a live 804-symbol list: 788 resolve automatically (NSE CODE
is populated on 3,322 feed rows with zero duplicates, so matches are
unambiguous). The residue is renames and corporate actions -- TATAMOTORS
demerged into TMCV/TMPV, PEL became PIRAMALFIN, SWANENERGY became SWANCORP --
which is precisely the class ISIN exists to survive. Those are mapped by hand,
once, and the mapping is preserved across re-uploads.
"""
from __future__ import annotations

import pandas as pd

from tm750.config import DEAD_STATUSES
from tm750.scanner import store

SYMBOL_HEADERS = ["symbol", "ticker", "nse code", "nsecode",
                  "original symbol", "tradingsymbol", "scrip", "code"]
EXCHANGE_HEADERS = ["exchange", "exchange found", "exch"]


class UniverseError(Exception):
    """Raised when an upload cannot be interpreted."""


def normalise(symbol: str | None) -> str | None:
    """Uppercase, strip, underscore -> hyphen.

    Yahoo and NSE disagree on the separator in names like M&M, and the
    underscore form appears in some exports. The price layer uses the same
    normalisation, so the two always agree on what a symbol is called.
    """
    if symbol is None:
        return None
    if isinstance(symbol, float) and pd.isna(symbol):
        return None
    s = str(symbol).strip().upper().replace("_", "-")
    return s or None


def _find(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for name in candidates:
        if name in lookup:
            return lookup[name]
    return None


def find_symbol_column(df: pd.DataFrame) -> str:
    col = _find(df, SYMBOL_HEADERS)
    if col is None:
        raise UniverseError(
            "No symbol column found. Expected one of: "
            f"{', '.join(SYMBOL_HEADERS)}. Got: {list(df.columns)}")
    return col


def _exchange(raw) -> str:
    """'NSE (India)' -> 'NSE'. Anything mentioning BSE -> 'BSE'."""
    return "BSE" if "BSE" in str(raw).upper() else "NSE"


def parse(df: pd.DataFrame, source_file: str) -> list[dict]:
    """Excel frame -> deduplicated universe rows. No resolution yet."""
    sym_col = find_symbol_column(df)
    exch_col = _find(df, EXCHANGE_HEADERS)

    seen: dict[str, dict] = {}
    for _, row in df.iterrows():
        sym = normalise(row[sym_col])
        if sym is None or sym in seen:
            continue
        seen[sym] = {
            "symbol": sym,
            "exchange": _exchange(row[exch_col]) if exch_col else "NSE",
            "source_file": source_file,
        }
    return list(seen.values())


def resolve(rows: list[dict], feed: pd.DataFrame) -> list[dict]:
    """Attach ISIN and accord code by NSE CODE lookup against the profit feed.

    Also auto-ignores names the feed reports as dead, which replaces the
    reference app's hardcoded BLACKLIST with something data-driven.
    """
    f = feed.copy()
    f.columns = [str(c).strip().upper() for c in f.columns]
    f["_nse"] = f["NSE CODE"].astype(str).str.strip().str.upper()
    f = f[(f["_nse"] != "") & (f["_nse"] != "NAN")]
    by_nse = f.drop_duplicates("_nse").set_index("_nse")

    out = []
    for r in rows:
        r = dict(r)
        if r["symbol"] in by_nse.index:
            hit = by_nse.loc[r["symbol"]]
            status = str(hit.get("TRADING STATUS", "Active"))
            dead = status in DEAD_STATUSES
            accord = hit.get("ACCORD CODE")
            r.update(
                isin=str(hit["ISIN"]),
                accord_code=str(accord) if accord is not None else None,
                resolution="auto",
                ignored=dead,
                ignore_reason=status.lower() if dead else None,
            )
        else:
            r.update(isin=None, accord_code=None, resolution="unresolved",
                     ignored=False, ignore_reason=None)
        out.append(r)
    return out


def save(rows: list[dict]) -> dict:
    """Merge, never wipe.

    Rows resolved by hand keep their ISIN; ignored flags survive. Nothing is
    deleted here -- removals are reported by diff_against_upload and confirmed
    separately, so a truncated Excel cannot silently shrink the universe.
    """
    cur = store.cursor()
    inserted = updated = 0
    for r in rows:
        existing = cur.execute(
            "SELECT isin, resolution, ignored FROM universe WHERE symbol = ?",
            [r["symbol"]]).fetchone()

        if existing is None:
            cur.execute(
                """INSERT INTO universe (symbol, exchange, isin, accord_code,
                       resolution, ignored, ignore_reason, source_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [r["symbol"], r["exchange"], r.get("isin"),
                 r.get("accord_code"), r.get("resolution", "unresolved"),
                 bool(r.get("ignored", False)), r.get("ignore_reason"),
                 r.get("source_file")])
            inserted += 1
            continue

        old_isin, old_res, old_ignored = existing
        manual = old_res == "manual"
        cur.execute(
            """UPDATE universe SET exchange = ?, isin = ?, accord_code = ?,
                   resolution = ?, ignored = ?, ignore_reason = ?,
                   source_file = ?
               WHERE symbol = ?""",
            [r["exchange"],
             old_isin if manual else (r.get("isin") or old_isin),
             r.get("accord_code"),
             "manual" if manual else r.get("resolution", old_res),
             bool(old_ignored) or bool(r.get("ignored", False)),
             r.get("ignore_reason"), r.get("source_file"), r["symbol"]])
        updated += 1

    return {"inserted": inserted, "updated": updated}


def set_manual_isin(symbol: str, isin: str) -> None:
    store.cursor().execute(
        "UPDATE universe SET isin = ?, resolution = 'manual' WHERE symbol = ?",
        [isin, symbol])


def diff_against_upload(symbols: list[str]) -> dict:
    """What is stored but absent from this upload. Reported, never acted on."""
    have = {r[0] for r in store.cursor().execute(
        "SELECT symbol FROM universe").fetchall()}
    return {"missing": sorted(have - set(symbols))}


def remove(symbols: list[str]) -> int:
    """Explicit removal, only after the operator confirms."""
    if not symbols:
        return 0
    placeholders = ",".join("?" * len(symbols))
    store.cursor().execute(
        f"DELETE FROM universe WHERE symbol IN ({placeholders})",
        list(symbols))
    return len(symbols)


def clear_all() -> int:
    """Wipe the entire universe. The nuclear option, for when an upload has
    gone wrong and a clean restart is worth more than preserving manual
    mappings.

    Scoped strictly to the universe table -- ATH prices and profit verdicts
    are untouched, since those are expensive to rebuild and unrelated to
    which symbols are currently in the scan list.
    """
    cur = store.cursor()
    n = cur.execute("SELECT count(*) FROM universe").fetchone()[0]
    cur.execute("DELETE FROM universe")
    return n


def unresolved() -> list[dict]:
    rows = store.cursor().execute(
        """SELECT symbol, exchange FROM universe
           WHERE resolution = 'unresolved' AND NOT ignored
           ORDER BY symbol""").fetchall()
    return [{"symbol": s, "exchange": e} for s, e in rows]


def active() -> list[dict]:
    rows = store.cursor().execute(
        """SELECT symbol, exchange, isin FROM universe
           WHERE NOT ignored ORDER BY symbol""").fetchall()
    return [{"symbol": s, "exchange": e, "isin": i} for s, e, i in rows]
