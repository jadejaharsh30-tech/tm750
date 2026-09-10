"""Central configuration for the tm750 data layer."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CURATED = ROOT / "data" / "curated"
EXTERNAL = ROOT / "data" / "external"
# Raw files are kept per snapshot so any day can be rebuilt from its own
# inputs, and so a file that was not re-uploaded can be carried forward.
ARCHIVE = ROOT / "data" / "archive"

# ---------------------------------------------------------------- sources
SOURCES = {
    "tradingview": "Total_Market_2026-08-20_tradingview.csv",
    "screener": "total-market-all-data.csv",
    "profit_q": "Qtr_Profit_Data.xlsx",
    "profit_y": "Yearly_Profit_Data.xlsx",
}

# The TradingView export carries its own date, so the filename varies daily.
# Each source is resolved by pattern rather than exact name, which also means
# a file the user renamed still resolves.
SOURCE_PATTERNS = {
    "tradingview": ["*tradingview*.csv", "Total_Market_*.csv"],
    "screener": ["*all-data*.csv", "*screener*.csv"],
    "profit_q": ["*Qtr*Profit*.xlsx", "*quarterly*profit*.xlsx"],
    "profit_y": ["*Yearly*Profit*.xlsx", "*annual*profit*.xlsx"],
}

# Which sources genuinely change day to day. The profit workbooks are
# quarterly, so a daily upload that omits them is normal, not an error --
# they are carried forward from the most recent snapshot that had them.
DAILY_SOURCES = ("tradingview", "screener")
CARRY_FORWARD_SOURCES = ("profit_q", "profit_y")

JOIN_KEY = "isin"
SNAPSHOT_DATE = "2026-08-20"
EXPECTED_UNIVERSE = 750

# ------------------------------------------------------- exclusion policy
# Columns dropped because coverage is too low to support honest analysis.
# Threshold: <15% of the universe.
MIN_COVERAGE_PCT = 15.0

# Kept, but barred from cross-sectional ranking / screener defaults.
# Coverage between MIN_COVERAGE_PCT and 50%.
FLAG_COVERAGE_PCT = 50.0

# Explicitly dropped regardless of coverage.
FORCE_DROP = {
    "Credit rating",  # 0/1589 populated in the Screener export
}

# Columns dropped as *source* fields but reconstructed in derive.py.
# Retained here purely for documentation / the quality report.
RECONSTRUCTED_INSTEAD = {
    "Net revenue, Trailing 12 months": "revenue_ttm",
    "Price to book ratio": "price_to_book",
}

# ------------------------------------------------------ source precedence
# Where TradingView and Screener both supply a field, which one wins.
# Fields listed as "both" are stored twice under distinct names because the
# two sources use materially different formulas.
PRECEDENCE = {
    "price": "tradingview",
    "market_cap": "tradingview",
    "pe_ratio": "tradingview",
    "dividend_yield": "tradingview",
    "roce": "both",  # 15.4% median divergence -> genuine formula difference
}

# ------------------------------------------------- profit-history handling
# Zeros in the profit files are missing-data sentinels (company not listed in
# that period), NOT reported zero profit. Negatives are present in the data,
# which confirms losses are encoded as negatives rather than zeros.
PROFIT_ZERO_IS_NULL = True
QTR_PERIODS = 48
FY_PERIODS = 15

# ------------------------------------------------------------ cap tiers
CAP_TIER_RULES = [
    ("Nifty 100", "Large"),
    ("Nifty MidCap 150", "Mid"),
    ("Nifty SmallCap 250", "Small"),
    ("Nifty MicroCap 250", "Micro"),
]
CAP_TIER_ORDER = ["Large", "Mid", "Small", "Micro"]
CAP_TIER_EXPECTED = {"Large": 100, "Mid": 150, "Small": 250, "Micro": 250}

# ------------------------------------------------------- sector handling
# Metrics that are structurally meaningless for banks / NBFCs / insurers.
# The dashboard masks these rather than silently ranking financials on them.
FINANCE_SECTOR = "Finance"
FINANCE_INVALID_METRICS = {
    "roce",
    "roce_screener",
    "roic",
    "ev_to_ebitda",
    "ev_to_ebit",
    "current_ratio",
    "quick_ratio",
    "inventory_turnover",
    "asset_turnover",
    "debt_to_equity",
    "debt_to_assets",
    "ebitda_margin",
    "gross_margin",
    "enterprise_value",
    "avg_roce_3y",
    "avg_roce_5y",
    "avg_roic_3y",
    "avg_roic_5y",
}

# ------------------------------------------------------------- segments
SEGMENTS = [
    "Overview",
    "Performance",
    "Trend & Momentum",
    "Technicals",
    "Forecasts",
    "Valuation",
    "Dividend",
    "Growth",
    "Profitability",
    "Income Statement",
    "Balance Sheet",
    "Cash Flow",
    "Per Share",
    "Ownership",
    "Index Membership",
    "History",
]

# Keyword -> segment. First match wins, so order matters.
SEGMENT_RULES: list[tuple[str, list[str]]] = [
    ("Index Membership", ["idx_", "is_", "cap_tier", "index_count",
                          "index_tags"]),
    ("Ownership", ["promoter", "pledge", "fii_", "dii_", "public_holding",
                   "shareholder", "free_float"]),
    ("Forecasts", ["analyst", "target_price", "estimate", "forward",
                   "upside_to_target", "rating_conflict"]),
    ("History", ["pat_", "qtrs_available", "fy_available", "profitable_",
                 "loss_qtrs", "loss_fy", "profit_streak"]),
    ("Cash Flow", ["cash_flow", "free_cash_flow", "capital_expenditures",
                   "operating_cash_flow"]),
    ("Trend & Momentum", ["perf_", "chg_", "momentum", "dist_", "above_",
                          "ema_", "sma_", "high_", "low_", "donchian",
                          "ichimoku", "rate_of_change", "beta_",
                          "pct_of_52w_range", "positive_windows",
                          "moving_average", "exponential_moving_average",
                          "simple_moving_average",
                          "down_from_52w", "up_from_52w", "price_up_",
                          "price_down_"]),
    ("Technicals", ["rsi", "bollinger", "awesome", "williams", "stochastic",
                    "directional", "adx", "money_flow", "macd", "pivot",
                    "technical_rating", "ma_rating", "volume_weighted",
                    "vwap", "vwma", "volatility", "atr_", "adr_"]),
    ("Dividend", ["dividend", "payout"]),
    ("Valuation", ["pe_", "_pe", "peg", "price_to", "enterprise_value",
                   "ev_to", "earnings_yield", "graham", "tobin",
                   "net_current_asset", "pbv", "historical_p"]),
    ("Growth", ["growth", "cagr"]),
    ("Profitability", ["margin", "roe", "roa", "roce", "roic", "rote", "rota",
                       "return_on", "piotroski", "sloan", "turnover",
                       "interest_coverage", "opm", "earning_power",
                       "selling_general", "research_and_development",
                       "rd_ratio", "sustainable", "interest_rate"]),
    ("Balance Sheet", ["total_assets", "total_current", "total_debt",
                       "total_equity", "total_liabilities", "long_term_debt",
                       "short_term_debt", "net_debt", "cash_and_equivalents",
                       "assets_to_equity", "debt_to", "equity_to_assets",
                       "cash_to_debt", "cash_ratio", "current_ratio",
                       "quick_ratio", "book_value"]),
    ("Income Statement", ["revenue", "net_income", "ebitda", "ebit",
                          "gross_profit", "operating_income", "eps",
                          "earnings_per_share", "sales", "net_profit"]),
    ("Per Share", ["per_share", "per_employee"]),
    ("Performance", ["price", "volume", "relative_volume"]),
    ("Overview", ["snapshot_date", "symbol", "name", "sector", "industry",
                  "market_cap",
                  "employees", "earnings_date", "isin", "shares",
                  "ipo", "sme", "code"]),
]

# Metrics where a HIGHER value is better / worse. Everything unlisted is
# treated as neutral (no colour polarity applied in the UI).
HIGHER_IS_BETTER = {
    "roe", "roa", "roce", "roce_screener", "roic", "rote", "rota",
    "gross_margin", "ebitda_margin", "operating_margin", "pretax_margin",
    "fcf_margin", "net_margin", "piotroski_f_score", "interest_coverage",
    "current_ratio", "quick_ratio", "cash_ratio", "dividend_yield",
    "earnings_yield", "free_float_pct", "revenue_growth_ttm_yoy",
    "net_income_growth_ttm_yoy", "ebitda_growth_ttm_yoy", "eps_growth_ttm_yoy",
    "upside_to_target_pct", "avg_roe_3y", "avg_roe_5y", "avg_roce_3y",
    "avg_roce_5y", "avg_roic_3y", "avg_roic_5y", "opm_5y", "opm_10y",
    "promoter_holding", "fii_holding", "dii_holding", "earning_power",
    "net_margin", "profit_growth_3y", "profit_growth_5y", "profit_growth_7y",
    "sales_growth_3y", "sales_growth_5y", "sales_growth_7y",
    "ebitda_growth_3y", "ebitda_growth_5y", "ebitda_growth_7y",
    "pat_cagr_3y", "pat_cagr_5y", "pat_cagr_7y", "pat_cagr_10y",
    "pat_cagr_15y", "pat_ttm_growth", "pat_yoy_q", "pat_qoq",
    "profit_streak_fy", "profit_streak_qtrs", "pat_growth_streak_fy",
    "profitable_fy", "profitable_qtrs", "positive_windows",
    "momentum_12_1", "momentum_per_beta", "perf_1y", "perf_3m", "perf_6m",
    "perf_1m", "perf_ytd", "cash_flow_from_operating_activities",
    "free_cash_flow", "gross_profit", "operating_income", "net_income",
    "revenue_ttm", "interest_coverage", "cash_to_debt",
}
LOWER_IS_BETTER = {
    "pe_ratio", "pe_ratio_screener", "peg_ratio", "price_to_sales",
    "price_to_book", "ev_to_ebitda", "ev_to_ebit", "debt_to_equity",
    "debt_to_assets", "debt_to_revenue", "net_debt", "sloan_ratio",
    "pledged_percentage", "volatility_1w", "volatility_1m", "atr_pct",
    "price_to_cash_flow", "pe_vs_own_5y", "pbv_vs_own_5y", "pe_vs_industry",
    "loss_qtrs", "loss_fy", "total_debt", "net_debt", "debt_to_capital",
    "debt_to_revenue", "assets_to_equity", "pe_forward_derived",
    "sloan", "beta_1y", "beta_3y", "beta_5y",
}

# --------------------------------------------------------------- helpers
_SNAKE_STRIP = re.compile(r"[^0-9a-z]+")


def to_snake(name: str) -> str:
    """Deterministic snake_case for arbitrary export column headers."""
    s = name.strip().lower()
    s = s.replace("%", " pct ").replace("&", " and ")
    s = _SNAKE_STRIP.sub("_", s)
    return s.strip("_")


# ---------------------------------------------------------------- groups
# Sub-groups within each segment, so a 90-column tab reads as six labelled
# ideas rather than one flat wall. Rules are ordered and first-match-wins
# within a segment, which matters: `pat_ttm_at_ath` is a record, not a TTM
# figure, so the record rule has to be evaluated first.
#
# This lives in the catalog rather than the frontend because the grid's
# column picker and the screener's field picker want exactly the same
# taxonomy, and three copies would drift.
GROUP_RULES: dict[str, list[tuple[str, list[str]]]] = {
    "Trend & Momentum": [
        ("Trend state", [r"^ema_stack", r"^above_(ema|sma)_", r"_stack_"]),
        ("Distance from highs & lows", [
            r"^dist_(52w|ath|6m|3m|20d)", r"^above_(52w_low|atl)",
            r"^pct_of_52w_range$", r"_from_52w_", r"^down_from_", r"^up_from_"]),
        ("Highs & lows", [r"^high_", r"^low_", r"^donchian_"]),
        ("Moving averages", [
            r"^ema_", r"^sma_", r"^exponential_moving_average",
            r"^simple_moving_average", r"^volume_weighted_moving_average",
            r"^ichimoku", r"^dist_(ema|sma)_"]),
        ("Momentum", [
            r"^momentum_", r"^rate_of_change", r"^moving_average_convergence",
            r"^positive_windows$"]),
        ("Returns", [r"^perf_", r"^chg_"]),
        ("Beta & risk", [r"^beta_"]),
        ("Price vs earnings", [r"^price_(up|down)_earnings"]),
    ],
    "Technicals": [
        ("Ratings", [r"_rating$"]),
        ("Trend strength", [r"^adx_", r"^directional_movement"]),
        ("Oscillators", [
            r"^rsi_", r"^stochastic", r"^williams", r"^awesome_oscillator",
            r"^money_flow"]),
        ("Volatility", [r"^atr_", r"^adr_", r"^volatility_"]),
        ("Bands & pivots", [
            r"^bollinger", r"^pivot_points", r"^volume_weighted_average_price"]),
    ],
    "Profitability": [
        ("Quality scores", [r"^piotroski", r"^sloan", r"^earning_power$"]),
        ("Returns on capital", [
            r"^ro[eaic]$", r"^roce", r"^roic", r"^return_on_", r"^avg_ro"]),
        ("Margins", [r"_margin", r"^opm_"]),
        ("Interest cover", [r"interest_coverage", r"^effective_interest"]),
        ("Efficiency", [
            r"_turnover", r"^rd_ratio$", r"^selling_general"]),
    ],
    "Balance Sheet": [
        ("Liquidity", [r"^(current|quick|cash)_ratio"]),
        ("Leverage", [
            r"^debt_to_", r"^total_debt_to_", r"^net_debt_to_",
            r"^assets_to_equity", r"^equity_to_assets", r"^cash_to_debt"]),
        ("Per share", [r"book_value_per_share"]),
        ("Balances", [r"^total_", r"^cash_and", r"_debt_annual$", r"^net_debt"]),
    ],
    "History": [
        # Unanchored `_at_ath` so descriptive variants such as
        # pat_ttm_at_ath_rolling still group as records. Anchored to the end
        # it would fall through to the `^pat_ttm` rule below and land under
        # "Trailing twelve months", which is the wrong shelf for a record.
        ("Records", [r"_at_ath", r"_peak", r"vs_peak"]),
        ("Trailing twelve months", [r"^pat_ttm"]),
        ("Quarterly", [
            r"_q$", r"_q_", r"^qtrs_", r"_qtrs$", r"_qtr_", r"^pat_yoy_q",
            r"^pat_qoq"]),
        ("Annual", [
            r"^fy_", r"_fy$", r"_fy_", r"^pat_fy", r"^pat_cagr"]),
    ],
    "Growth": [
        ("Compound rates", [r"_cagr_", r"_3y$", r"_5y$", r"_7y$", r"_10y$"]),
        ("Year on year", [r"_yoy", r"_growth"]),
    ],
    "Ownership": [
        ("Changes over time", [r"^chg_"]),
        ("Institutional", [r"^(fii|dii)_"]),
        ("Promoter", [r"^promoter", r"^pledged"]),
        ("Free float & public", [r"^free_float", r"^public_holding"]),
    ],
    "Valuation": [
        ("Versus own history", [
            r"_vs_own_", r"_vs_industry", r"^historical_", r"^industry_pe$"]),
        ("Earnings multiples", [r"^pe_", r"^peg_", r"earnings_yield"]),
        ("Asset multiples", [
            r"price_to_book", r"^tobin", r"^graham",
            r"^net_current_asset_value"]),
        ("Enterprise multiples", [r"^enterprise_value", r"^ev_"]),
        ("Sales & cash multiples", [r"price_to_(sales|cash)"]),
    ],
    "Cash Flow": [
        ("Free cash flow", [r"free_cash_flow"]),
        ("Capital expenditure", [r"^capital_expenditures"]),
        ("Per share", [r"_per_share"]),
        ("Statement lines", [r"^cash_flow_from"]),
    ],
    "Overview": [
        ("Identity", [
            r"^(symbol|name|sector|industry|isin|snapshot_date)$"]),
        ("Size", [
            r"^market_cap", r"^employees$", r"^shares_outstanding",
            r"^free_float", r"^enterprise_value"]),
        ("Key dates", [r"_date$"]),
    ],
    "Performance": [
        ("Price", [r"^price"]),
        ("Volume", [r"volume"]),
    ],
    "Income Statement": [
        ("Per share", [r"_per_share", r"^earnings_per_share"]),
        ("Per employee", [r"_per_employee"]),
        ("Statement lines", [
            r"^revenue", r"^ebitda", r"^ebit", r"^gross_profit",
            r"^net_income", r"^operating_income", r"^total_"]),
    ],
    "Dividend": [
        ("Yield", [r"yield"]),
        ("Payout & cover", [r"payout", r"coverage"]),
        ("Consistency", [r"^continuous_"]),
    ],
    "Forecasts": [
        ("Analyst view", [
            r"^analyst_rating$", r"^target_price", r"^upside_to_target"]),
        ("Estimates", [r"_estimate", r"^pe_forward"]),
        ("Rating conflicts", [r"^analyst_(bull|bear)"]),
    ],
    "Per Share": [
        ("Per share", [r"_per_share"]),
    ],
}

# Applied when a segment has no rules, or nothing matched.
DEFAULT_GROUP = "Other"


# ---------------------------------------------------------------- scanner
SCANNER_BATCH_SIZE = 50
RS_WINDOW = 211
RS_TOLERANCE = 0.9999
RS_BENCHMARK = "^CRSLDX"
DEAD_STATUSES = {"Delisted", "Suspended", "InActive", "Amalgamation"}
PROFIT_API_QUARTERLY = "https://script.google.com/macros/s/AKfycbyS3U6Z7htU-L3gl7Eqvt81ykCyvruZkLrDSw75tJcjcBYxs33k8PAGNTSxSMLQ7KLo/exec"   # paste your Apps Script URL
PROFIT_API_YEARLY = "https://script.google.com/macros/s/AKfycbwCvDTWq7-3wYC7ac7zP9YwqdCb8CGV2wtftqs-vQWfsWQgYPzBDl9qKkM5wBnOjg55tw/exec"      # paste your Apps Script URL
