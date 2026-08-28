"""Load the four raw sources and validate them before anything else runs.

Every loader returns a frame keyed on a normalised `isin` column so the
downstream merge never has to guess. Validation failures raise loudly here
rather than producing a silently wrong dataset three modules later.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import EXPECTED_UNIVERSE, RAW, SOURCE_PATTERNS, SOURCES


class IngestError(RuntimeError):
    """Raised when a raw source fails a structural expectation."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise IngestError(msg)


def resolve_source(key: str, raw_dir: Path | None = None) -> Path:
    """Find a source file by pattern rather than exact name.

    The TradingView export embeds its own date, so the filename changes every
    day; matching on a pattern also means a file the user renamed still
    resolves. The exact configured name is tried first so an unchanged setup
    behaves identically.
    """
    d = Path(raw_dir) if raw_dir else RAW
    exact = d / SOURCES[key]
    if exact.exists():
        return exact
    for pattern in SOURCE_PATTERNS.get(key, []):
        hits = sorted(d.glob(pattern))
        if hits:
            # Newest wins if a directory somehow holds two exports.
            return max(hits, key=lambda p: p.stat().st_mtime)
    raise IngestError(
        f"No file for '{key}' in {d}. Expected {SOURCES[key]} or one of "
        f"{SOURCE_PATTERNS.get(key, [])}.")


def load_tradingview(raw_dir: Path | None = None) -> pd.DataFrame:
    """Base universe. Defines which 750 companies exist."""
    df = pd.read_csv(resolve_source("tradingview", raw_dir))
    _require(len(df) == EXPECTED_UNIVERSE,
             f"tradingview: expected {EXPECTED_UNIVERSE} rows, got {len(df)}")
    _require("ISIN" in df.columns, "tradingview: ISIN column missing")
    _require(df["ISIN"].notna().all(), "tradingview: null ISIN present")
    _require(df["ISIN"].is_unique, "tradingview: duplicate ISIN")

    # Every '- Currency' column must be INR before we are entitled to drop it.
    cur_cols = [c for c in df.columns if c.endswith("- Currency")]
    non_inr = {
        c: sorted(set(df[c].dropna()) - {"INR"})
        for c in cur_cols
        if set(df[c].dropna()) - {"INR"}
    }
    _require(not non_inr, f"tradingview: non-INR currency values found: {non_inr}")

    df = df.rename(columns={"ISIN": "isin"})
    return df


def load_screener(raw_dir: Path | None = None) -> pd.DataFrame:
    """Screener.in bulk export. Wider than the universe; filtered on join."""
    df = pd.read_csv(resolve_source("screener", raw_dir))
    _require("ISIN Code" in df.columns, "screener: ISIN Code column missing")
    df = df.rename(columns={"ISIN Code": "isin"})
    before = len(df)
    df = df.drop_duplicates("isin", keep="first")
    if len(df) < before:
        print(f"  [screener] dropped {before - len(df)} duplicate ISIN rows")
    return df


def _load_profit(path, prefix: str, n_periods: int,
                 extra: list[str] | None = None) -> pd.DataFrame:
    """Shared loader for the wide quarterly / annual profit exports."""
    path = Path(path)
    filename = path.name
    df = pd.read_excel(path)
    _require("ISIN" in df.columns, f"{filename}: ISIN column missing")
    cols = [f"{prefix}{i}" for i in range(1, n_periods + 1)]
    missing = [c for c in cols if c not in df.columns]
    _require(not missing, f"{filename}: missing period columns {missing[:5]}")
    keep = ["ISIN"] + (extra or []) + cols
    df = df[keep].rename(columns={"ISIN": "isin"})
    return df.drop_duplicates("isin", keep="first")


def load_profit_quarterly(raw_dir: Path | None = None) -> pd.DataFrame:
    """48 quarters of PAT. QL1 is the most recent period (verified r=0.983
    against Screener's 'Net Profit latest quarter')."""
    from .config import QTR_PERIODS
    return _load_profit(resolve_source("profit_q", raw_dir), "QL", QTR_PERIODS)


def load_profit_yearly(raw_dir: Path | None = None) -> pd.DataFrame:
    """15 financial years of PAT plus TTM. FYL1 is the most recent year."""
    from .config import FY_PERIODS
    return _load_profit(resolve_source("profit_y", raw_dir), "FYL", FY_PERIODS,
                        extra=["TTM"])


def load_all(raw_dir: Path | None = None,
             per_source_dirs: dict[str, Path] | None = None
             ) -> dict[str, pd.DataFrame]:
    """Load all four sources.

    `per_source_dirs` lets each source come from a different directory, which
    is how a daily upload that omits the quarterly profit workbooks still
    builds: those two are read from the snapshot that last supplied them.
    """
    d = per_source_dirs or {}
    print("Ingesting raw sources...")
    out = {
        "tradingview": load_tradingview(d.get("tradingview", raw_dir)),
        "screener": load_screener(d.get("screener", raw_dir)),
        "profit_q": load_profit_quarterly(d.get("profit_q", raw_dir)),
        "profit_y": load_profit_yearly(d.get("profit_y", raw_dir)),
    }
    for name, df in out.items():
        print(f"  [{name:12s}] {df.shape[0]:5d} rows x {df.shape[1]:3d} cols")
    return out


def check_coverage(sources: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Report how many of the 750 base companies each secondary source covers.

    Any company that fails to match is surfaced by name rather than silently
    carrying nulls through the pipeline.
    """
    base = sources["tradingview"][["isin", "Symbol", "Description"]]
    rows = []
    for name in ("screener", "profit_q", "profit_y"):
        have = set(sources[name]["isin"])
        matched = base["isin"].isin(have)
        missing = base.loc[~matched, "Symbol"].tolist()
        rows.append({
            "source": name,
            "matched": int(matched.sum()),
            "of": len(base),
            "pct": round(matched.mean() * 100, 2),
            "unmatched_symbols": missing,
        })
    return pd.DataFrame(rows)
