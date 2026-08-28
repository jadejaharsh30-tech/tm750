"""The column catalog -- the keystone of the whole platform.

One entry per surviving column, carrying everything any consumer needs to
render or reason about it: segment, source, provenance, coverage, unit,
format, polarity and sector applicability.

Built by rules rather than hand-written so it stays correct as columns change.
Four consumers depend on it, and without a single source of truth this logic
gets reimplemented four times and drifts:

  - dashboard grid  : column-group toggles, display labels, number formatting
  - screener        : which widget to render, which fields to expose
  - compare view    : best-in-row highlighting needs polarity
  - infographics    : axis labels, units, colour direction
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from .descriptions import describe
from .config import (DEFAULT_GROUP, GROUP_RULES,
                     FINANCE_INVALID_METRICS, FLAG_COVERAGE_PCT,
                     HIGHER_IS_BETTER, LOWER_IS_BETTER, SEGMENT_RULES)


@dataclass
class ColumnSpec:
    name: str
    label: str
    segment: str
    group: str             # sub-group within the segment, for UI structure
    description: str       # one-line tooltip text
    description_source: str  # curated | generated | none
    source: str            # tradingview | screener | profit_history | derived
    provenance: str        # reported | derived | reconstructed
    dtype: str
    coverage_pct: float
    unit: str              # pct | inr | ratio | count | date | text | bool
    fmt: str               # how the UI should render it
    polarity: str          # higher_better | lower_better | neutral
    finance_valid: bool    # False -> mask for banks/NBFCs
    screenable: bool       # False -> excluded from screener + rankings
    notes: str = ""
    flags: list[str] = field(default_factory=list)


# ------------------------------------------------------------ inference
_PCT_HINTS = ("_pct", "pct_", "yield", "margin", "growth", "return_on",
              "roe", "roa", "roce", "roic", "holding", "opm", "free_float")
_INR_HINTS = ("price", "market_cap", "revenue", "income", "profit", "ebitda",
              "debt", "assets", "equity", "cash", "per_share", "target",
              "high_", "low_", "sma_", "ema_", "pat_")
_COUNT_HINTS = ("employees", "shares", "count", "num_", "qtrs", "streak",
                "windows", "_fy")


def _matches(keyword: str, name: str, label: str) -> bool:
    """Token-aware keyword match.

    Naive substring matching produced real misfilings: 'low_' matched inside
    'cash_flow_', routing every cash-flow column into Trend & Momentum. A
    keyword ending in '_' must therefore start a token, not appear mid-token.
    """
    tokens = set(re.split(r"[^a-z0-9]+", f"{name.lower()} {label.lower()}"))
    if keyword.endswith("_"):
        stem = keyword.rstrip("_")
        return any(t == stem or t.startswith(stem) and t[len(stem):].isdigit()
                   for t in tokens) or f" {keyword}" in f" {name.lower()}" \
                   or name.lower().startswith(keyword)
    if keyword.startswith("_"):
        return name.lower().endswith(keyword)
    if "_" in keyword or " " in keyword:
        return keyword in name.lower() or keyword.replace("_", " ") in label.lower()
    return keyword in tokens


def infer_segment(name: str, label: str) -> str:
    if name.startswith(("idx_", "is_")) or name in (
            "cap_tier", "index_count", "index_tags"):
        return "Index Membership"
    if name.startswith("pct_rank_"):
        return "Percentile Ranks"
    for segment, keywords in SEGMENT_RULES:
        if any(_matches(k, name, label) for k in keywords):
            return segment
    return "Overview"


def infer_unit(name: str, series: pd.Series) -> str:
    n = name.lower()
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_datetime64_any_dtype(series) or n.endswith("_date"):
        return "date"
    if not pd.api.types.is_numeric_dtype(series):
        return "text"
    if any(h in n for h in _PCT_HINTS):
        return "pct"
    if any(h in n for h in _COUNT_HINTS):
        return "count"
    if any(h in n for h in _INR_HINTS):
        return "inr"
    return "ratio"


def infer_format(unit: str, name: str) -> str:
    if unit == "pct":
        return "0.1f%"
    if unit == "inr":
        return "cr" if any(h in name for h in
                           ("market_cap", "revenue", "income", "profit",
                            "ebitda", "debt", "assets", "equity", "pat_")) \
                    else "0.2f"
    if unit == "count":
        return "0,0"
    if unit == "ratio":
        return "0.2f"
    return "text"


_POLARITY_SUFFIXES = ("_pct", "_ttm", "_annual", "_trailing_12_months",
                      "_pct_annual", "_pct_ttm", "_ratio", "_yoy",
                      "_pct_annual_yoy", "_pct_ttm_yoy")


def _polarity_variants(name: str) -> list[str]:
    """Candidate keys for a polarity lookup.

    Column names carry suffixes the polarity lists do not ('earnings_yield_pct'
    vs 'earnings_yield'), so strip them progressively rather than requiring an
    exact match -- otherwise best-in-row highlighting silently goes neutral.
    """
    base = name.removeprefix("pct_rank_").split("_in_")[0]
    out = [name, base]
    for cand in (name, base):
        prev = None
        while cand != prev:
            prev = cand
            for suf in sorted(_POLARITY_SUFFIXES, key=len, reverse=True):
                if cand.endswith(suf):
                    cand = cand[: -len(suf)]
                    out.append(cand)
                    break
    return out


def infer_group(name: str, segment: str) -> str:
    """Sub-group within a segment. First matching rule wins, so rule order
    inside a segment encodes precedence -- see GROUP_RULES."""
    for group, patterns in GROUP_RULES.get(segment, []):
        for pat in patterns:
            if re.search(pat, name):
                return group
    return DEFAULT_GROUP


def infer_polarity(name: str) -> str:
    for cand in _polarity_variants(name):
        if cand in HIGHER_IS_BETTER:
            return "higher_better"
        if cand in LOWER_IS_BETTER:
            return "lower_better"
    return "neutral"


def prettify(name: str) -> str:
    special = {
        "pe": "P/E", "peg": "PEG", "pb": "P/B", "pbv": "P/BV", "roe": "ROE",
        "roa": "ROA", "roce": "ROCE", "roic": "ROIC", "ebitda": "EBITDA",
        "ttm": "TTM", "yoy": "YoY", "ytd": "YTD", "eps": "EPS", "fii": "FII",
        "dii": "DII", "sme": "SME", "isin": "ISIN", "nse": "NSE", "bse": "BSE",
        "atr": "ATR", "adx": "ADX", "rsi": "RSI", "ema": "EMA", "sma": "SMA",
        "ath": "ATH", "atl": "ATL", "pat": "PAT", "cagr": "CAGR",
        "opm": "OPM", "ipo": "IPO", "pct": "%", "ma": "MA", "ev": "EV",
    }
    parts = [special.get(p, p.capitalize()) for p in name.split("_")]
    return " ".join(parts)


def build_catalog(df: pd.DataFrame, source_map: dict[str, str],
                  provenance_map: dict[str, str],
                  notes_map: dict[str, str] | None = None) -> list[ColumnSpec]:
    notes_map = notes_map or {}
    n = len(df)
    specs: list[ColumnSpec] = []

    for col in df.columns:
        s = df[col]
        cov = round(s.notna().sum() / n * 100, 1)
        label = prettify(col)
        unit = infer_unit(col, s)
        flags: list[str] = []

        screenable = True
        if cov < FLAG_COVERAGE_PCT:
            screenable = False
            flags.append(f"low_coverage_{cov:.0f}pct")
        if unit in ("text", "date"):
            screenable = False
        if col.startswith("idx_"):
            screenable = True
            flags.append("index_membership")

        prov = provenance_map.get(col, "reported")
        if prov != "reported":
            flags.append(prov)

        seg = infer_segment(col, label)
        desc, desc_src = describe(col)
        specs.append(ColumnSpec(
            name=col,
            label=label,
            segment=seg,
            group=infer_group(col, seg),
            description=desc,
            description_source=desc_src,
            source=source_map.get(col, "derived"),
            provenance=prov,
            dtype=str(s.dtype),
            coverage_pct=cov,
            unit=unit,
            fmt=infer_format(unit, col),
            polarity=infer_polarity(col),
            finance_valid=col not in FINANCE_INVALID_METRICS,
            screenable=screenable,
            notes=notes_map.get(col, ""),
            flags=flags,
        ))
    return specs


def to_frame(specs: list[ColumnSpec]) -> pd.DataFrame:
    return pd.DataFrame([asdict(s) for s in specs])


def save(specs: list[ColumnSpec], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "n_columns": len(specs),
        "columns": [asdict(s) for s in specs],
    }
    path.write_text(json.dumps(payload, indent=1))


def summary(specs: list[ColumnSpec]) -> pd.DataFrame:
    df = to_frame(specs)
    return (df.groupby("segment")
              .agg(columns=("name", "size"),
                   screenable=("screenable", "sum"),
                   median_coverage=("coverage_pct", "median"))
              .sort_values("columns", ascending=False))
