"""Turn the comma-joined `Index` string into structured, queryable columns.

This is the highest-leverage transformation in the layer. A single text field
carries ~100 index memberships; unpacked, it yields the cap-tier split, factor
tags, thematic baskets and ownership groupings without any external data.
"""
from __future__ import annotations

import pandas as pd

from .config import CAP_TIER_EXPECTED, CAP_TIER_RULES, to_snake

# ---------------------------------------------------------------- groupings
FACTOR_INDICES = {
    "momentum": [
        "Nifty 500 Momentum 50", "Nifty 200 Momentum 30",
        "Nifty MidCap 150 Momentum 50",
        "Nifty Smallcap 250 Momentum Quality 100",
        "Nifty MidSmallcap 400 Momentum Quality 100",
        "Nifty 500 Multicap Momentum Quality 50",
    ],
    "alpha": ["Nifty Alpha 50", "Nifty 100 Alpha 30", "Nifty 200 Alpha 30"],
    "quality": ["Nifty 100 Quality 30", "Nifty MidCap 150 Quality 50",
                "Nifty Smallcap 250 Quality 50", "Nifty 200 Quality 30"],
    "value": ["Nifty 50 Value 20", "Nifty 500 Value 50",
              "Nifty MidCap 150 Value 50"],
    "low_volatility": ["Nifty 100 Low Volatility 30",
                       "Nifty Low Volatility 50",
                       "Nifty Alpha Low-Volatility 30"],
    "high_beta": ["Nifty High Beta 50"],
    "multifactor": ["Nifty 500 Multifactor MQVLv 50",
                    "Nifty Alpha Quality Value Low-Volatility 30",
                    "Nifty Alpha Quality Low-Volatility 30"],
}

OWNERSHIP_INDICES = {
    "cpse": ["Nifty CPSE"],
    "psu_bank": ["Nifty PSU Bank"],
    "pse": ["Nifty PSE"],
    "mnc": ["Nifty MNC"],
    "tata_group": ["Nifty Tata Group 25% Cap"],
    "top_corporate_groups": ["Nifty Top 5 Corporate Groups (MAATR)"],
}


def parse_tags(value: object) -> list[str]:
    """Split the raw Index cell into clean individual membership tags."""
    if pd.isna(value):
        return []
    return [t.strip() for t in str(value).split(",") if t.strip()]


def assign_cap_tier(tags: list[str]) -> str:
    """Cap tier from index membership.

    Order matters: Nifty 100 constituents also appear in broader indices, so
    the most restrictive tier is checked first.
    """
    for tag, tier in CAP_TIER_RULES:
        if tag in tags:
            return tier
    return "Unclassified"


def build_flags(df: pd.DataFrame, col: str = "index_tags") -> pd.DataFrame:
    """Expand tags into cap tier, per-index booleans and group rollups."""
    tag_lists = df[col].apply(parse_tags)

    out = pd.DataFrame(index=df.index)
    out["cap_tier"] = tag_lists.apply(assign_cap_tier)
    out["index_count"] = tag_lists.apply(len)

    all_tags = sorted({t for tags in tag_lists for t in tags})
    flags = {
        f"idx_{to_snake(tag)}": tag_lists.apply(lambda ts, t=tag: t in ts)
        for tag in all_tags
    }
    out = pd.concat([out, pd.DataFrame(flags, index=df.index)], axis=1)

    rollups = {}
    for group, members in {**FACTOR_INDICES, **OWNERSHIP_INDICES}.items():
        rollups[f"is_{group}"] = tag_lists.apply(
            lambda ts, m=members: any(x in ts for x in m)
        )
    out = pd.concat([out, pd.DataFrame(rollups, index=df.index)], axis=1)

    out["is_any_factor"] = out[[f"is_{g}" for g in FACTOR_INDICES]].any(axis=1)
    return out, all_tags


def validate_tiers(tiers: pd.Series) -> None:
    """Cap tiers must land on exactly 100 / 150 / 250 / 250."""
    counts = tiers.value_counts().to_dict()
    for tier, expected in CAP_TIER_EXPECTED.items():
        got = counts.get(tier, 0)
        if got != expected:
            raise ValueError(
                f"cap tier '{tier}': expected {expected}, got {got}. "
                "Index membership rules may have changed upstream."
            )
    unclassified = counts.get("Unclassified", 0)
    if unclassified:
        raise ValueError(f"{unclassified} companies fell outside all cap tiers")
