"""Column-level cleaning: drop the dead weight, normalise the names.

Three classes of removal, each recorded with a reason so the quality report
can explain every dropped column rather than leaving a silent gap:

  1. currency  - '- Currency' columns, all INR, zero information
  2. duplicate - '.1' suffixed re-exports identical to their base column
  3. coverage  - populated on <15% of the universe
"""
from __future__ import annotations

import pandas as pd

from .config import (FORCE_DROP, MIN_COVERAGE_PCT, RECONSTRUCTED_INSTEAD,
                     to_snake)

# Explicit renames where the automatic snake_case would be unwieldy or
# ambiguous. Everything not listed falls through to to_snake().
RENAMES = {
    "Symbol": "symbol",
    "Description": "name",
    "Sector": "sector",
    "Industry": "industry",
    "Index": "index_tags",
    "Market capitalization": "market_cap",
    "Price": "price",
    "Price change %, 1 day": "chg_1d_pct",
    "Price change %, 1 week": "chg_1w_pct",
    "Price change %, 1 month": "chg_1m_pct",
    "Performance %, 1 week": "perf_1w_pct",
    "Performance %, 1 month": "perf_1m_pct",
    "Performance %, 3 months": "perf_3m_pct",
    "Performance %, 6 months": "perf_6m_pct",
    "Performance %, Year to date": "perf_ytd_pct",
    "Performance %, 1 year": "perf_1y_pct",
    "Performance %, 5 years": "perf_5y_pct",
    "Performance %, 10 years": "perf_10y_pct",
    "Performance %, All Time": "perf_all_pct",
    "High, 52 weeks": "high_52w",
    "Low, 52 weeks": "low_52w",
    "High, All Time": "high_all_time",
    "Low, All Time": "low_all_time",
    "High, 6 months": "high_6m",
    "Low, 6 months": "low_6m",
    "High, 3 months": "high_3m",
    "Low, 3 months": "low_3m",
    "High, 1 month": "high_1m",
    "Low, 1 month": "low_1m",
    "Beta, 1 year": "beta_1y",
    "Beta, 3 years": "beta_3y",
    "Beta, 5 years": "beta_5y",
    "Volatility, 1 week": "volatility_1w",
    "Volatility, 1 month": "volatility_1m",
    "Relative strength index, 14, 1 day": "rsi_14",
    "Average directional index, 14, 1 day": "adx_14",
    "Average true range %, 14, 1 day": "atr_pct",
    "Average daily range %": "adr_pct",
    "Total common shares outstanding": "shares_outstanding",
    "Price to earnings ratio": "pe_ratio",
    "Price to sales ratio": "price_to_sales",
    "Price to earning to growth, Trailing 12 months": "peg_ratio",
    "Return on equity %, Annual": "roe",
    "Return on assets %, Annual": "roa",
    "Return on capital employed %, Annual": "roce",
    "Return on invested capital %, Annual": "roic",
    "Piotroski F-score, Annual": "piotroski_f_score",
    "Debt to equity ratio, Annual": "debt_to_equity",
    "Dividend yield %, Trailing 12 months": "dividend_yield",
    "Analyst rating": "analyst_rating",
    "Target price, 1 year": "target_price_1y",
    "Technical rating, 1 day": "technical_rating",
    "Moving averages rating, 1 day": "ma_rating",
    "Number of employees, Annual": "employees",
    "Free float %": "free_float_pct",
    "Revenue per share, Trailing 12 months": "revenue_per_share",
    "Book value per share, Annual": "book_value_per_share",
    "Net income, Trailing 12 months": "net_income_ttm",
    "Revenue growth %, TTM YoY": "revenue_growth_ttm_yoy",
    "Net income growth %, TTM YoY": "net_income_growth_ttm_yoy",
    "Exponential moving average, 20, 1 day": "ema_20",
    "Exponential moving average, 50, 1 day": "ema_50",
    "Exponential moving average, 200, 1 day": "ema_200",
    "Simple moving average, 50, 1 day": "sma_50",
    "Simple moving average, 200, 1 day": "sma_200",
    "Donchian channels, 20, 1 day, Upper": "donchian_20_upper",
    "Donchian channels, 20, 1 day, Lower": "donchian_20_lower",
    "Recent earnings date": "recent_earnings_date",
    "Upcoming earnings date": "upcoming_earnings_date",
    "IPO offer date": "ipo_date",
    "Earnings per share estimate, Annual": "eps_estimate_annual",
    "Price to earnings ratio forward": "pe_forward",
    "Research and development ratio, Annual": "rd_ratio",
}

# Screener columns kept under distinct names to avoid colliding with the
# TradingView field of the same concept.
SCREENER_RENAMES = {
    "Price to Earning": "pe_ratio_screener",
    "Return on capital employed": "roce_screener",
    "Dividend yield": "dividend_yield_screener",
    "Current Price": "price_screener",
    "Market Capitalization": "market_cap_cr_screener",
    "Promoter holding": "promoter_holding",
    "Pledged percentage": "pledged_percentage",
    "Change in promoter holding": "chg_promoter_holding",
    "Change in promoter holding 3Years": "chg_promoter_holding_3y",
    "FII holding": "fii_holding",
    "Change in FII holding": "chg_fii_holding",
    "Change in FII holding 3Years": "chg_fii_holding_3y",
    "DII holding": "dii_holding",
    "Change in DII holding": "chg_dii_holding",
    "Change in DII holding 3Years": "chg_dii_holding_3y",
    "Public holding": "public_holding",
    "Number of Shareholders": "num_shareholders",
    "Industry PE": "industry_pe",
    "Historical PE 5Years": "historical_pe_5y",
    "Historical PBV 5Years": "historical_pbv_5y",
    "OPM 5Year": "opm_5y",
    "OPM 10Year": "opm_10y",
    "Sales growth 3Years": "sales_growth_3y",
    "Sales growth 5Years": "sales_growth_5y",
    "Sales growth 7Years": "sales_growth_7y",
    "Profit growth 3Years": "profit_growth_3y",
    "Profit growth 5Years": "profit_growth_5y",
    "Profit growth 7Years": "profit_growth_7y",
    "EBIDT growth 3Years": "ebitda_growth_3y",
    "EBIDT growth 5Years": "ebitda_growth_5y",
    "EBIDT growth 7Years": "ebitda_growth_7y",
    "Average return on equity 3Years": "avg_roe_3y",
    "Average return on equity 5Years": "avg_roe_5y",
    "Average return on capital employed 3Years": "avg_roce_3y",
    "Average return on capital employed 5Years": "avg_roce_5y",
    "Average return on invested capital 3Years": "avg_roic_3y",
    "Average return on invested capital 5Years": "avg_roic_5y",
    "Earning Power": "earning_power",
    "Is SME": "is_sme",
    "Net Profit latest quarter": "net_profit_latest_qtr",
    "Sales latest quarter": "sales_latest_qtr",
    "YOY Quarterly profit growth": "qtr_profit_growth_yoy",
    "YOY Quarterly sales growth": "qtr_sales_growth_yoy",
    "Down from 52w high": "down_from_52w_high_screener",
    "Up from 52w low": "up_from_52w_low_screener",
    "Industry Group": "industry_group_screener",
    "NSE Code": "nse_code",
    "BSE Code": "bse_code",
}

# Screener fields deliberately not carried forward: either superseded by the
# TradingView equivalent (higher as-of consistency) or structurally redundant.
SCREENER_DROP = {
    "Name", "Industry", "Is not SME", "52w Index", "From 52w high",
    "Number of equity shares", "Unpledged promoter holding", "Credit rating",
    "TTM Result Date", "Last annual result date", "Last result date",
}


def drop_dead_columns(df: pd.DataFrame, universe_n: int
                      ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove currency, duplicate and low-coverage columns.

    Returns the trimmed frame plus a ledger of what was removed and why.
    """
    ledger: list[dict] = []
    drop: list[str] = []

    for col in df.columns:
        if col.endswith("- Currency"):
            drop.append(col)
            ledger.append({"column": col, "reason": "currency",
                           "detail": "all values INR"})
            continue

        if col.endswith(".1"):
            base = col[:-2]
            identical = (base in df.columns and
                         df[col].astype(str).equals(df[base].astype(str)))
            drop.append(col)
            ledger.append({
                "column": col, "reason": "duplicate",
                "detail": f"re-export of '{base}'"
                          f"{'' if identical else ' (values differ; base kept)'}",
            })
            continue

        if col in FORCE_DROP:
            drop.append(col)
            ledger.append({"column": col, "reason": "empty",
                           "detail": "no populated values"})
            continue

        pct = df[col].notna().sum() / universe_n * 100
        if pct < MIN_COVERAGE_PCT:
            note = RECONSTRUCTED_INSTEAD.get(col)
            drop.append(col)
            ledger.append({
                "column": col, "reason": "low_coverage",
                "detail": f"{pct:.1f}% populated"
                          + (f"; reconstructed as '{note}'" if note else ""),
            })

    return df.drop(columns=drop), pd.DataFrame(ledger)


def normalise_names(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Apply explicit renames, then snake_case whatever is left."""
    out = df.rename(columns=mapping)
    residual = {c: to_snake(c) for c in out.columns
                if c not in mapping.values() and c != "isin"}
    out = out.rename(columns=residual)

    dupes = out.columns[out.columns.duplicated()].tolist()
    if dupes:
        raise ValueError(f"name collision after normalisation: {dupes}")
    return out
