"""One-line descriptions for every column, for in-app tooltips.

Two sources, and the catalog records which is which:

- **curated** -- written by hand, for anything where the definition carries a
  real choice (which ROCE formula, which momentum window, which P/E).
- **generated** -- built from a pattern, for the formulaic families where the
  name fully determines the meaning (`perf_3m_pct`, `dist_ema_50_pct`,
  `idx_*` membership). These are safe to generate precisely because there is
  no judgement in them.

Anything left over gets no description rather than a guessed one. A tooltip
that is confidently wrong is worse than a tooltip that is absent.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------- curated
CURATED: dict[str, str] = {
    # -- identity & size
    "symbol": "NSE trading symbol.",
    "name": "Registered company name.",
    "isin": "International Securities Identification Number. Stable across "
            "ticker renames, so it is the key used to join snapshots.",
    "sector": "Sector classification from TradingView.",
    "industry": "Industry classification, a finer split than sector.",
    "cap_tier": "Size bucket by market cap rank: Large 1-100, Mid 101-250, "
                "Small 251-500, Micro 501-750.",
    "market_cap": "Share price times shares outstanding.",
    "snapshot_date": "The date this row's data was exported.",
    "employees": "Reported headcount.",
    "shares_outstanding": "Total shares issued.",
    "free_float": "Shares available to trade, excluding locked-in holdings.",
    "free_float_pct": "Share of total equity that trades freely.",

    # -- price & performance
    "price": "Last traded price.",
    "price_screener": "Last traded price as reported by Screener.in. Kept "
                      "separately from TradingView's price so the two sources "
                      "can be compared rather than silently merged.",
    "volume_1_day": "Shares traded in the latest session.",
    "relative_volume_1_day": "Latest session's volume against its own recent "
                             "average. Above 1 means unusually active.",
    "volume_weighted_average_price_1_day": "Average price weighted by volume "
                                           "over the session.",

    # -- valuation
    "pe_ratio": "Price divided by trailing twelve-month earnings per share. "
                "Null where earnings are negative.",
    "pe_ratio_screener": "P/E as computed by Screener.in. Differs from "
                         "TradingView's mainly in the earnings period used.",
    "peg_ratio": "P/E divided by earnings growth. Below 1 suggests the "
                 "multiple is low relative to the growth rate.",
    "price_to_book": "Price divided by book value per share. Reconstructed "
                     "from price and book value per share, as the reported "
                     "column was too sparse to use.",
    "price_to_sales": "Market cap divided by trailing twelve-month revenue.",
    "earnings_yield_pct": "Earnings per share as a percentage of price. The "
                          "inverse of P/E, and defined where P/E is not.",
    "enterprise_value": "Market cap plus net debt: what it would cost to buy "
                        "the whole business.",
    "pe_vs_own_5y_pct": "Current P/E against this company's own five-year "
                        "median. Negative means cheaper than its own history.",
    "pbv_vs_own_5y_pct": "Current price-to-book against its own five-year "
                         "median.",
    "pe_vs_industry_pct": "Current P/E against the industry P/E.",
    "industry_pe": "Median P/E of this company's industry.",
    "historical_pe_5y": "This company's own median P/E over five years.",
    "historical_pbv_5y": "This company's own median price-to-book over five "
                         "years.",
    "graham_number": "Square root of 22.5 x EPS x book value per share. A "
                     "rough conservative fair-value benchmark.",
    "tobins_q": "Market value divided by asset replacement cost.",

    # -- profitability
    "roe": "Net income as a percentage of shareholder equity.",
    "roa": "Net income as a percentage of total assets.",
    "roce": "Return on capital employed, from TradingView. Not meaningful for "
            "banks and NBFCs, so it is withheld for them.",
    "roce_screener": "Return on capital employed as computed by Screener.in. "
                     "Diverges from TradingView's by around 15% at the median "
                     "because the two use different capital bases -- both are "
                     "kept rather than one being silently chosen.",
    "roic": "Return on invested capital: after-tax operating profit over "
            "invested capital.",
    "piotroski_f_score": "Nine accounting tests of financial strength, scored "
                         "0-9. Higher is stronger.",
    "sloan_ratio_pct_annual": "Accruals as a share of assets. Large positive "
                              "or negative values suggest earnings are driven "
                              "by accounting rather than cash.",
    "earning_power": "Operating earnings relative to assets, independent of "
                     "leverage and tax.",
    "gross_margin_pct_trailing_12_months": "Gross profit as a percentage of "
                                           "revenue, trailing twelve months.",
    "operating_margin_pct_annual": "Operating profit as a percentage of "
                                   "revenue, latest financial year.",
    "ebitda_margin_pct_trailing_12_months": "EBITDA as a percentage of "
                                            "revenue, trailing twelve months.",
    "pretax_margin_pct_trailing_12_months": "Profit before tax as a percentage "
                                            "of revenue.",
    "opm_5y": "Average operating margin over five years.",
    "opm_10y": "Average operating margin over ten years.",
    "asset_turnover_annual": "Revenue divided by total assets: how much sales "
                             "each rupee of assets produces.",
    "inventory_turnover_annual": "Cost of goods sold divided by inventory. "
                                 "Not meaningful for financial companies.",
    "total_receivables_turnover_annual": "Revenue divided by receivables.",
    "interest_coverage_trailing_12_months": "Operating profit divided by "
                                            "interest expense. Below 1 means "
                                            "profit does not cover interest.",
    "rd_ratio": "Research and development spend as a share of revenue.",

    # -- balance sheet
    "debt_to_equity": "Total debt divided by shareholder equity.",
    "current_ratio_annual": "Current assets over current liabilities. Below 1 "
                            "means short-term obligations exceed short-term "
                            "assets.",
    "quick_ratio_annual": "Current ratio excluding inventory.",
    "cash_ratio_annual": "Cash and equivalents over current liabilities.",
    "net_debt_annual": "Total debt minus cash and equivalents.",
    "net_debt_to_ebitda_ratio_annual": "Years of EBITDA needed to repay net "
                                       "debt.",
    "cash_to_debt_ratio_annual": "Cash and equivalents over total debt.",
    "book_value_per_share": "Shareholder equity divided by shares outstanding.",
    "tangible_book_value_per_share_annual": "Book value per share excluding "
                                            "intangibles and goodwill.",

    # -- growth & history
    "revenue_ttm": "Revenue over the trailing twelve months. Reconstructed "
                   "from revenue per share and implied share count; median "
                   "error against reported values is under 1%.",
    "revenue_growth_ttm_yoy": "Trailing twelve-month revenue against the same "
                              "period a year earlier.",
    "net_income_growth_ttm_yoy": "Trailing twelve-month net income against the "
                                 "same period a year earlier.",
    "pat_ttm": "Profit after tax over the trailing twelve months, summed from "
               "the last four reported quarters.",
    "pat_ttm_reported": "Trailing twelve-month profit as reported in the "
                        "source file, rather than summed from quarters.",
    "pat_latest_q": "Profit after tax in the most recent reported quarter.",
    "pat_yoy_q_pct": "Latest quarter's profit against the same quarter a year "
                     "earlier. Year-on-year rather than sequential, so "
                     "seasonality does not distort it.",
    "pat_qoq_pct": "Latest quarter's profit against the quarter before. "
                   "Sequential, so seasonal businesses will swing.",
    "pat_qtr_volatility": "Standard deviation of quarterly profit relative to "
                          "its mean.",
    "profit_streak_qtrs": "Consecutive recent quarters with positive profit.",
    "profit_streak_fy": "Consecutive recent financial years with positive "
                        "profit.",
    "pat_growth_streak_fy": "Consecutive years of rising annual profit.",
    "profitable_qtrs": "Quarters with positive profit, of those available.",
    "loss_qtrs": "Quarters with negative profit, of those available.",
    "profitable_fy": "Financial years with positive profit, of those "
                     "available.",
    "loss_fy": "Financial years with negative profit, of those available.",
    "qtrs_available": "Quarters of profit history held for this company, out "
                      "of a possible 48.",
    "fy_available": "Financial years of profit history held, out of a "
                    "possible 15.",
    "pat_ttm_at_ath": "Trailing twelve-month profit is the highest across "
                      "every rolling four-quarter window on record. The "
                      "rolling-year measure, so it updates each quarter.",
    "pat_q_at_ath": "The latest single quarter is the highest on record. "
                    "Noisier than the TTM measure, which absorbs seasonality.",
    "pat_fy_at_ath": "The latest reported financial year is the highest on "
                     "record. Reference only: it updates once a year and can "
                     "describe a period that closed up to four quarters ago.",
    "pat_both_at_ath": "Trailing twelve-month and latest-quarter profit are "
                       "both at record highs -- a record year that is still "
                       "setting records, rather than one already rolling over.",
    "pat_ttm_vs_peak_pct": "Trailing twelve-month profit against its own peak. "
                           "An earnings drawdown, directly analogous to a "
                           "price drawdown.",
    "pat_vs_peak_pct": "Latest annual profit against its own best year.",
    "pat_q_vs_peak_pct": "Latest quarter against the best quarter on record.",

    # -- trend & momentum
    "momentum_12_1_pct": "Twelve-month return excluding the most recent month. "
                         "The standard academic momentum measure: the recent "
                         "month is dropped because it tends to mean-revert.",
    "momentum_per_beta": "12-1 momentum divided by beta -- momentum earned per "
                         "unit of market risk.",
    "momentum_accel": "Whether momentum is building or fading, comparing the "
                      "recent pace against the twelve-month pace.",
    "positive_windows": "How many of the measured return windows are positive. "
                        "A consistency measure rather than a magnitude one.",
    "ema_stack_bullish": "Price above the 20-day EMA, which is above the 50, "
                         "which is above the 200. A fully aligned uptrend.",
    "ema_stack_bearish": "The reverse alignment: each moving average below the "
                         "next, a fully aligned downtrend.",
    "above_ema_200": "Price is above its 200-day exponential moving average.",
    "above_sma_200": "Price is above its 200-day simple moving average.",
    "pct_of_52w_range": "Where price sits between its 52-week low and high. "
                        "0 is at the low, 100 at the high.",
    "beta_1y": "Sensitivity to the market over one year. Above 1 means it "
               "moves more than the market.",
    "price_up_earnings_down": "Price has risen while earnings have fallen.",
    "price_down_earnings_up": "Price has fallen while earnings have risen.",

    # -- technicals
    "rsi_14": "Relative strength index over 14 days, 0-100. Above 70 is "
              "conventionally overbought, below 30 oversold.",
    "adx_14": "Average directional index: trend strength regardless of "
              "direction. Above 25 suggests a genuine trend.",
    "atr_pct": "Average true range as a percentage of price -- typical daily "
               "movement.",
    "adr_pct": "Average daily range as a percentage of price.",
    "volatility_1w": "Realised volatility over one week.",
    "volatility_1m": "Realised volatility over one month.",
    "technical_rating": "TradingView's summary rating from its full indicator "
                        "set.",
    "ma_rating": "TradingView's rating from moving averages alone.",
    "money_flow_index_14_1_day": "Volume-weighted RSI over 14 days.",

    # -- ownership
    "promoter_holding": "Share held by promoters -- the founding or "
                        "controlling group.",
    "pledged_percentage": "Share of promoter holding pledged as loan "
                          "collateral. High values are a governance risk.",
    "fii_holding": "Share held by foreign institutional investors.",
    "dii_holding": "Share held by domestic institutional investors.",
    "public_holding": "Share held by retail and other non-institutional "
                      "investors.",
    "chg_promoter_holding_3y": "Change in promoter holding over three years, "
                               "in percentage points.",
    "chg_fii_holding_3y": "Change in foreign institutional holding over three "
                          "years, in percentage points.",
    "chg_dii_holding_3y": "Change in domestic institutional holding over three "
                          "years, in percentage points.",

    # -- dividend & forecasts
    "dividend_yield": "Annual dividend as a percentage of price.",
    "dividend_payout_ratio_pct_annual": "Share of earnings paid as dividends.",
    "continuous_dividend_growth": "Consecutive years of rising dividends.",
    "continuous_dividend_payout": "Consecutive years of paying a dividend.",
    "analyst_rating": "Consensus sell-side recommendation.",
    "target_price_1y": "Consensus twelve-month price target.",
    "upside_to_target_pct": "Distance from current price to the consensus "
                            "target.",
    "pe_forward": "Price divided by forecast earnings per share.",
    "analyst_bull_tech_bear": "Analysts rate it a buy while the technical "
                              "rating is a sell -- the two disagree.",
    "analyst_bear_tech_bull": "Analysts rate it a sell while the technical "
                              "rating is a buy.",
    "rating_conflict": "Analyst and technical ratings point in opposite "
                       "directions.",
    "upcoming_earnings_date": "Next scheduled results date.",
    "recent_earnings_date": "Most recent results date.",
    "ipo_date": "Date the company listed.",
    "bse_code": "BSE scrip code.",
    "nse_code": "NSE symbol as used by Screener.in.",
    "industry_group_screener": "Industry grouping from Screener.in, which "
                               "differs from TradingView's classification.",
    "market_cap_cr_screener": "Market cap in crore as reported by "
                              "Screener.in.",
    "num_shareholders": "Reported number of shareholders.",
    "shares_implied": "Share count implied by market cap divided by price. "
                      "Used to reconstruct totals from per-share figures.",

    # -- statement lines
    "revenue_per_share": "Trailing twelve-month revenue divided by shares "
                         "outstanding.",
    "net_income_ttm": "Net income over the trailing twelve months.",
    "ebitda_trailing_12_months": "Earnings before interest, tax, depreciation "
                                 "and amortisation, trailing twelve months.",
    "gross_profit_trailing_12_months": "Revenue less cost of goods sold.",
    "operating_income_trailing_12_months": "Profit from operations before "
                                           "interest and tax.",
    "earnings_per_share_diluted_trailing_12_months": "Earnings per share on a "
                                                     "fully diluted basis.",
    "earnings_per_share_reported_annual": "Earnings per share as reported for "
                                          "the latest financial year.",
    "net_profit_latest_qtr": "Net profit in the latest quarter, from "
                             "Screener.in.",
    "sales_latest_qtr": "Sales in the latest quarter, from Screener.in.",

    # -- cash flow
    "cash_flow_from_operating_activities_annual": "Cash generated by the core "
                                                  "business.",
    "cash_flow_from_investing_activities_annual": "Cash spent on or raised "
                                                  "from investments and "
                                                  "assets.",
    "cash_flow_from_financing_activities_annual": "Cash from borrowing, "
                                                  "repayment, issuance and "
                                                  "dividends.",
    "free_cash_flow_annual": "Operating cash flow less capital expenditure.",
    "capital_expenditures_annual": "Spend on property, plant and equipment.",
    "free_cash_flow_margin_pct_annual": "Free cash flow as a percentage of "
                                        "revenue.",

    # -- balance sheet lines
    "total_assets_annual": "Everything the company owns.",
    "total_liabilities_annual": "Everything the company owes.",
    "total_equity_annual": "Assets less liabilities: the shareholders' claim.",
    "total_debt_annual": "Short-term plus long-term borrowings.",
    "long_term_debt_annual": "Borrowings due beyond one year.",
    "short_term_debt_annual": "Borrowings due within one year.",
    "cash_and_equivalents_annual": "Cash and instruments readily convertible "
                                   "to cash.",
    "total_current_assets_annual": "Assets expected to convert to cash within "
                                   "a year.",
    "total_current_liabilities_annual": "Obligations due within a year.",
    "assets_to_equity_ratio_annual": "Total assets over equity. A leverage "
                                     "multiplier: higher means more of the "
                                     "asset base is funded by liabilities.",
    "debt_to_assets_ratio_annual": "Total debt as a share of total assets.",
    "equity_to_assets_ratio_annual": "Equity as a share of total assets.",
    "debt_to_revenue_ratio_annual": "Total debt relative to annual revenue.",
    "total_debt_to_capital_annual": "Debt as a share of total capital, debt "
                                    "plus equity.",

    # -- profitability extras
    "return_on_tangible_equity_pct_annual": "Return on equity excluding "
                                            "intangibles and goodwill.",
    "return_on_tangible_assets_pct_annual": "Return on assets excluding "
                                            "intangibles and goodwill.",
    "return_on_total_capital_pct_annual": "Return on debt plus equity "
                                          "combined.",
    "ebitda_interest_coverage_annual": "EBITDA divided by interest expense.",
    "effective_interest_rate_on_debt_pct_annual": "Interest expense as a "
                                                  "percentage of total debt.",
    "selling_general_and_admin_expenses_ratio_trailing_12_months":
        "Overheads as a share of revenue.",

    # -- growth extras
    "sustainable_growth_rate_annual": "Growth the company could fund from "
                                      "retained earnings alone, without new "
                                      "debt or equity.",
    "qtr_profit_growth_yoy": "Latest quarter's profit against the same quarter "
                             "a year earlier, from Screener.in.",
    "qtr_sales_growth_yoy": "Latest quarter's sales against the same quarter a "
                            "year earlier, from Screener.in.",

    # -- history extras
    "pat_ttm_prev": "Trailing twelve-month profit for the previous "
                    "four-quarter window, used as the growth base.",
    "pat_ttm_growth_pct": "Trailing twelve-month profit against the previous "
                          "twelve months.",
    "pat_ttm_peak": "Highest trailing twelve-month profit across every rolling "
                    "four-quarter window on record.",
    "pat_peak_q": "Highest single quarter of profit on record.",
    "pat_peak_fy": "Highest financial year of profit on record.",
    "pat_fy1": "Profit after tax in the latest reported financial year.",
    "profitable_qtr_pct": "Share of available quarters that were profitable.",
    "profitable_fy_pct": "Share of available financial years that were "
                         "profitable.",

    # -- valuation extras
    "enterprise_value_to_ebitda_ratio_trailing_12_months":
        "Enterprise value divided by EBITDA. Capital-structure neutral, so it "
        "compares across different debt levels better than P/E. Not "
        "meaningful for financial companies.",
    "enterprise_value_to_ebit_ratio_trailing_12_months":
        "Enterprise value divided by operating profit.",
    "net_current_asset_value_per_share_annual":
        "Current assets less all liabilities, per share. A liquidation-style "
        "floor value.",
    "working_capital_per_share_annual": "Current assets less current "
                                        "liabilities, per share.",
    "dividends_per_share_annual": "Dividend paid per share for the year.",
    "cash_dividend_coverage_ratio_annual": "How many times cash flow covers "
                                           "the dividend.",
    "dividend_yield_screener": "Dividend yield as reported by Screener.in.",
    "eps_estimate_annual": "Consensus forecast earnings per share.",
    "revenue_estimate_annual": "Consensus forecast revenue.",
    "pe_forward_derived": "Price divided by consensus forecast earnings per "
                          "share, computed here rather than reported.",

    # -- technicals extras
    "donchian_20_upper": "Highest high over the last 20 sessions.",
    "donchian_20_lower": "Lowest low over the last 20 sessions.",
    "bollinger_bands_20_1_day_upper": "Two standard deviations above the "
                                      "20-day moving average.",
    "bollinger_bands_20_1_day_lower": "Two standard deviations below the "
                                      "20-day moving average.",
    "ichimoku_cloud_9_26_52_26_1_day_base_line": "Ichimoku base line: midpoint "
                                                 "of the 26-period high and "
                                                 "low.",
    "moving_average_convergence_divergence_12_26_1_day_level":
        "MACD line: the 12-day EMA minus the 26-day EMA.",
    "momentum_10_1_day": "Price change over the last 10 sessions.",
    "rate_of_change_9_1_day": "Percentage price change over 9 sessions.",
    "volume_weighted_moving_average_20_1_day": "20-day moving average weighted "
                                               "by volume.",
    "directional_movement_index_14_1_day_positive": "Strength of upward price "
                                                    "movement over 14 days.",
    "directional_movement_index_14_1_day_negative": "Strength of downward "
                                                    "price movement over 14 "
                                                    "days.",
    "pivot_points_classic_1_day_p": "Classic pivot point: the session's "
                                    "reference level.",
    "pivot_points_fibonacci_1_day_r1": "First Fibonacci resistance level.",
    "pivot_points_fibonacci_1_day_s1": "First Fibonacci support level.",
    "stochastic_14_1_3_1_day_pct_k": "Stochastic oscillator %K over 14 days.",
    "stochastic_rsi_3_3_14_14_1_day_k": "Stochastic applied to RSI rather than "
                                        "price.",
    "awesome_oscillator_1_day": "Difference between 5- and 34-period midpoint "
                                "moving averages.",
    "awesome_oscillator_1_week": "Awesome oscillator on weekly bars.",
    "williams_percent_range_14_1_day": "Williams %R over 14 days, -100 to 0. "
                                       "Near 0 is near the period high.",
    "williams_percent_range_14_1_week": "Williams %R on weekly bars.",
    "high_all_time": "Highest price on record.",
    "low_all_time": "Lowest price on record.",
    "down_from_52w_high_screener": "Distance below the 52-week high, from "
                                   "Screener.in.",
    "up_from_52w_low_screener": "Distance above the 52-week low, from "
                                "Screener.in.",
    "earnings_yield_pct_trailing_12_months": "Trailing twelve-month earnings "
                                             "as a percentage of price.",
    "graham_s_number_annual": "Square root of 22.5 x EPS x book value per "
                              "share -- a conservative fair-value benchmark.",
    "tobin_s_q_approximate_annual": "Market value divided by approximate asset "
                                    "replacement cost.",
    "dividend_yield_pct_annual": "Annual dividend as a percentage of price.",
    "index_tags": "Raw index-membership string from the source export, before "
                  "it was parsed into individual membership flags.",
    "index_count": "How many NSE indices this company belongs to.",
}

# ------------------------------------------------------------- generated
_WINDOW = {
    "1d": "one day", "1w": "one week", "1m": "one month", "3m": "three months",
    "6m": "six months", "ytd": "the year to date", "1y": "one year",
    "3y": "three years", "5y": "five years", "7y": "seven years",
    "10y": "ten years", "15y": "fifteen years", "20d": "twenty days",
    "all": "the full available history", "52w": "52 weeks",
}


def _window(tok: str) -> str | None:
    return _WINDOW.get(tok.lower())


_RULES: list[tuple[str, object]] = [
    (r"^perf_(\w+)_pct$",
     lambda m: (f"Price return over {_window(m.group(1))}."
                if _window(m.group(1)) else None)),
    (r"^chg_(\w+)_pct$",
     lambda m: (f"Price change over {_window(m.group(1))}."
                if _window(m.group(1)) else None)),
    (r"^high_(\w+)$",
     lambda m: (f"Highest price over {_window(m.group(1))}."
                if _window(m.group(1)) else None)),
    (r"^low_(\w+)$",
     lambda m: (f"Lowest price over {_window(m.group(1))}."
                if _window(m.group(1)) else None)),
    (r"^dist_(52w_high|ath)_pct$",
     lambda m: ("Distance below the 52-week high, as a percentage."
                if m.group(1) == "52w_high"
                else "Distance below the all-time high, as a percentage.")),
    (r"^dist_(\w+?)_high_pct$",
     lambda m: (f"Distance below the {_window(m.group(1))} high."
                if _window(m.group(1)) else None)),
    (r"^dist_(ema|sma)_(\d+)_pct$",
     lambda m: f"Distance from the {m.group(2)}-day "
               f"{'exponential' if m.group(1) == 'ema' else 'simple'} moving "
               f"average, as a percentage of price."),
    (r"^above_52w_low_pct$",
     lambda m: "How far price has risen above its 52-week low."),
    (r"^above_atl_pct$",
     lambda m: "How far price has risen above its all-time low."),
    (r"^(ema|sma)_(\d+)$",
     lambda m: f"{m.group(2)}-day "
               f"{'exponential' if m.group(1) == 'ema' else 'simple'} moving "
               f"average of price."),
    (r"^(exponential|simple)_moving_average_(\d+)_1_day$",
     lambda m: f"{m.group(2)}-day {m.group(1)} moving average of price."),
    (r"^avg_(roe|roce|roic)_(\d)y$",
     lambda m: f"Average {m.group(1).upper()} over "
               f"{_window(m.group(2) + 'y')}."),
    (r"^pat_cagr_(\d+)y_pct$",
     lambda m: f"Compound annual growth in profit after tax over "
               f"{_window(m.group(1) + 'y')}. Null where either endpoint is "
               f"non-positive, since a compound rate across a sign change is "
               f"undefined."),
    (r"^idx_(\w+)$",
     lambda m: "Member of this NSE index. Constituents are fixed until the "
               "next scheduled rebalance."),
    (r"^is_(\w+)$",
     lambda m: f"Member of at least one NSE "
               f"{m.group(1).replace('_', ' ')} factor index."),
    (r"^pct_rank_(\w+?)_in_sector$",
     lambda m: "Percentile rank within its own sector, 0-100. Polarity is not "
               "applied: a high P/E percentile means expensive, not good."),
    (r"^pct_rank_(\w+?)_in_tier$",
     lambda m: "Percentile rank within its own cap tier, 0-100."),
    (r"^pct_rank_(\w+)$",
     lambda m: "Percentile rank across all 750 companies, 0-100."),
    (r"^(\w+?)_growth_pct_(ttm|annual)_yoy$",
     lambda m: f"Growth in {m.group(1).replace('_', ' ')} "
               f"({'trailing twelve months' if m.group(2) == 'ttm' else 'latest financial year'}) "
               f"against the same period a year earlier."),
    (r"^(sales|profit|ebitda)_growth_(\d+)y$",
     lambda m: (f"Compound annual growth in {m.group(1)} over "
                f"{_window(m.group(2) + 'y')}, from Screener.in."
                if _window(m.group(2) + "y") else None)),
    (r"^(\w+?)_per_employee_annual$",
     lambda m: f"{m.group(1).replace('_', ' ').capitalize()} divided by "
               f"headcount."),
    (r"^(\w+?)_per_share(?:_annual|_trailing_12_months)?$",
     lambda m: f"{m.group(1).replace('_', ' ').capitalize()} divided by shares "
               f"outstanding."),
    (r"^chg_(promoter|fii|dii)_holding$",
     lambda m: f"Change in {m.group(1).upper() if m.group(1) != 'promoter' else 'promoter'} "
               f"holding since the previous reported period, in percentage "
               f"points."),
    (r"^beta_(\d)y$",
     lambda m: f"Sensitivity to the market measured over "
               f"{_window(m.group(1) + 'y')}. Above 1 means it moves more "
               f"than the market."),
]


def describe(name: str) -> tuple[str, str]:
    """Return (description, source). Source is curated, generated, or none."""
    if name in CURATED:
        return CURATED[name], "curated"
    for pattern, fn in _RULES:
        m = re.match(pattern, name)
        if m:
            text = fn(m)
            if text:
                return text, "generated"
    return "", "none"
