"""Pipeline orchestrator: raw sources -> curated Parquet + DuckDB + catalog.

Run with:  python -m tm750.build
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import catalog as cat
from . import clean, derive, history, index_flags, ingest, quality
from .config import CURATED, EXPECTED_UNIVERSE, SNAPSHOT_DATE


def _section(title: str) -> None:
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


def build(write: bool = True, snapshot_date: str | None = None,
          per_source_dirs: dict | None = None, raw_dir=None,
          out_dir=None, skip_duckdb: bool = False) -> dict:
    """Build one snapshot.

    `snapshot_date` defaults to the configured constant so existing callers
    and the test suite behave exactly as before. `per_source_dirs` lets each
    source come from a different place, which is how a daily upload that
    omits the quarterly workbooks still builds.
    """
    snap = snapshot_date or SNAPSHOT_DATE
    _section("1. INGEST")
    src = ingest.load_all(raw_dir=raw_dir, per_source_dirs=per_source_dirs)
    cov = ingest.check_coverage(src)
    for r in cov.to_dict("records"):
        flag = "OK" if r["matched"] == r["of"] else "PARTIAL"
        print(f"  [{flag}] {r['source']:10s} {r['matched']}/{r['of']} "
              f"({r['pct']}%)")
        if r["unmatched_symbols"]:
            print(f"        unmatched: {r['unmatched_symbols']}")

    _section("2. CLEAN")
    tv = src["tradingview"]
    tv, ledger = clean.drop_dead_columns(tv, EXPECTED_UNIVERSE)
    print(f"  dropped {len(ledger)} columns:")
    for reason, grp in ledger.groupby("reason"):
        print(f"    {reason:14s} {len(grp):3d}")
    tv = clean.normalise_names(tv, clean.RENAMES)
    print(f"  tradingview -> {tv.shape[1]} columns")

    sc = src["screener"].drop(columns=list(clean.SCREENER_DROP),
                              errors="ignore")
    sc = clean.normalise_names(sc, clean.SCREENER_RENAMES)
    print(f"  screener    -> {sc.shape[1]} columns")

    _section("3. INDEX FLAGS")
    flags, all_tags = index_flags.build_flags(tv)
    index_flags.validate_tiers(flags["cap_tier"])
    print(f"  parsed {len(all_tags)} distinct index memberships")
    print(f"  cap tiers: {flags['cap_tier'].value_counts().to_dict()}")
    print(f"  factor/ownership rollups: "
          f"{sum(c.startswith('is_') for c in flags.columns)}")

    _section("4. PROFIT HISTORY")
    q_sum = history.summarise_quarterly(src["profit_q"])
    y_sum = history.summarise_yearly(src["profit_y"])
    q_long = history.reshape_quarterly(src["profit_q"])
    y_long = history.reshape_yearly(src["profit_y"])
    print(f"  quarterly: {len(q_sum)} companies, {len(q_long)} periods (long)")
    print(f"  annual   : {len(y_sum)} companies, {len(y_long)} periods (long)")

    _section("5. MERGE")
    df = tv.join(flags)
    df = df.merge(sc, on="isin", how="left", suffixes=("", "_sc"))
    df = df.merge(q_sum, on="isin", how="left")
    df = df.merge(y_sum, on="isin", how="left")

    # Both horizons at a record simultaneously.
    #
    # The pair is TTM and the latest quarter, not annual and TTM. Reported
    # annual PAT only moves once a year, so for up to four quarters it
    # describes a period that has already closed; TTM is the rolling-year
    # figure that actually updates, and the two coincide only at financial
    # year end. TTM is therefore the yearly truth here, and the latest quarter
    # is the short horizon confirming the trend has not just rolled over.
    df["pat_both_at_ath"] = (df["pat_ttm_at_ath"].fillna(False)
                             & df["pat_q_at_ath"].fillna(False))
    assert len(df) == EXPECTED_UNIVERSE, f"row count drifted: {len(df)}"
    # DuckDB derives this from the Hive partition path when reading the
    # parquet, so it must exist in the catalog or the two disagree by one.
    df.insert(0, "snapshot_date", snap)
    print(f"  merged -> {df.shape[0]} rows x {df.shape[1]} columns")

    _section("6. DERIVE")
    recon = derive.add_reconstructed(df)
    checks = [
        derive.validate_reconstruction(src["tradingview"], recon["revenue_ttm"],
                                       "Net revenue, Trailing 12 months"),
        derive.validate_reconstruction(src["tradingview"],
                                       recon["price_to_book"],
                                       "Price to book ratio"),
    ]
    for c in checks:
        if "median_abs_err_pct" in c:
            ok = "PASS" if c["within_tolerance"] else "REVIEW"
            print(f"  [{ok}] {c['field'][:40]:40s} "
                  f"n={c['n_overlap']:3d} err={c['median_abs_err_pct']}%")
    df = pd.concat([df, recon], axis=1)

    parts = [derive.add_trend_state(df), derive.add_momentum(df),
             derive.add_valuation_context(df), derive.add_signal_conflicts(df)]
    df = pd.concat([df] + parts, axis=1)

    # P/BV vs own history needs the reconstructed P/B, so it runs last.
    if {"price_to_book", "historical_pbv_5y"}.issubset(df.columns):
        pbv = pd.DataFrame({"pbv_vs_own_5y_pct": (
            df["price_to_book"] / df["historical_pbv_5y"].replace(0, pd.NA) - 1
        ) * 100})
        df = pd.concat([df, pbv], axis=1)

    derived_names = set().union(*[set(p.columns) for p in parts]) \
                         | set(recon.columns) | {"pbv_vs_own_5y_pct"}
    print(f"  added {len(derived_names)} derived columns")

    rank_metrics = [m for m in [
        "pe_ratio", "peg_ratio", "price_to_book", "roe", "roce", "roic",
        "dividend_yield", "revenue_growth_ttm_yoy",
        "net_income_growth_ttm_yoy", "perf_1y_pct", "perf_3m_pct",
        "momentum_12_1_pct", "dist_52w_high_pct", "rsi_14",
        "promoter_holding", "fii_holding", "piotroski_f_score",
    ] if m in df.columns]
    ranks = derive.add_percentile_ranks(
        df, rank_metrics, {"sector": "sector", "tier": "cap_tier"})
    df = pd.concat([df, ranks], axis=1)
    print(f"  added {ranks.shape[1]} percentile-rank columns "
          f"({len(rank_metrics)} metrics x universe/sector/tier)")

    _section("7. CATALOG")
    source_map = {}
    for c in df.columns:
        if c in derived_names or c.startswith("pct_rank_"):
            source_map[c] = "derived"
        elif c in set(sc.columns):
            source_map[c] = "screener"
        elif c in set(q_sum.columns) | set(y_sum.columns):
            source_map[c] = "profit_history"
        elif c.startswith(("idx_", "is_", "cap_tier", "index_count")):
            source_map[c] = "derived"
        else:
            source_map[c] = "tradingview"

    prov_map = {c: "derived" for c in df.columns
                if source_map[c] == "derived"}
    for c in ("revenue_ttm", "price_to_book", "pe_forward_derived"):
        if c in df:
            prov_map[c] = "reconstructed"

    notes = {
        "roce": "TradingView formula. Diverges ~15% from roce_screener.",
        "roce_screener": "Screener formula. Retained separately; the gap is "
                         "a definition difference, not noise.",
        "revenue_ttm": "Reconstructed: revenue_per_share x implied shares. "
                       "Median error 1.1% vs 33 reported values.",
        "price_to_book": "Reconstructed: price / book_value_per_share. "
                         "r=0.979 vs 92 reported values.",
        "pe_forward": "Only 25% populated. Excluded from screener and "
                      "rankings; use pe_forward_derived instead.",
        "momentum_12_1_pct": "12-month return excluding the most recent "
                             "month, to avoid short-term reversal.",
        "pat_cagr_15y_pct": "Null where either endpoint is non-positive; a "
                            "compound rate across a sign change is undefined.",
        "snapshot_date": "As-of date of this snapshot. Also derived by DuckDB "
                         "from the Hive partition path.",
        "pat_ttm_at_ath": "Trailing-twelve-month PAT is at its highest across "
                          "all rolling 4-quarter windows in the available "
                          "history. Requires the peak itself to be positive.",
        "pat_q_at_ath": "Latest single quarter is the highest on record. Noisier "
                        "than the TTM measure, which absorbs seasonality.",
        "pat_both_at_ath": "Trailing-twelve-month AND latest-quarter PAT are "
                           "both at record highs. TTM is the rolling-year "
                           "measure that updates each quarter; reported annual "
                           "PAT moves only once a year and can describe a "
                           "period closed up to four quarters ago.",
        "pat_fy_at_ath": "Latest reported financial year PAT is the highest on "
                         "record. Reference only -- it updates once a year, so "
                         "pat_ttm_at_ath is the current rolling-year measure.",
    }
    specs = cat.build_catalog(df, source_map, prov_map, notes)
    print(cat.summary(specs).to_string())
    print(f"\n  total: {len(specs)} columns | "
          f"screenable: {sum(s.screenable for s in specs)}")

    _section("8. QUALITY")
    cat_df = cat.to_frame(specs)
    report = quality.build_report(df, cat_df, ledger, checks)
    print(f"  fully populated : {report['fully_populated_columns']}")
    print(f"  below 50%       : {report['columns_below_50pct']}")
    print(f"  non-screenable  : {report['non_screenable_columns']}")
    print("\n  source conflicts:")
    for c in report["source_conflicts"]:
        print(f"    {c['concept']:16s} corr={c['correlation']:.4f} "
              f"diff={c['median_abs_diff_pct']:5.2f}%  -> {c['resolution']}")
    print("\n  history depth:")
    for h in report["history_depth"]:
        print(f"    {h['series']:16s} median {h['median_available']:.0f} "
              f"periods | full {h['full_history_n']} | "
              f"thin (<half) {h['under_half_n']}")

    if write:
        _section("9. WRITE")
        out = Path(out_dir) if out_dir else CURATED / f"snapshot_date={snap}"
        out.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out / "companies.parquet", index=False)
        q_long.to_parquet(out / "profit_quarterly.parquet", index=False)
        y_long.to_parquet(out / "profit_annual.parquet", index=False)
        ledger.to_csv(out / "dropped_columns.csv", index=False)
        cat.save(specs, out / "catalog.json")
        cat_df.to_csv(out / "catalog.csv", index=False)
        (out / "quality_report.json").write_text(
            json.dumps(report, indent=1, default=str))
        for f in sorted(out.iterdir()):
            print(f"  {f.name:28s} {f.stat().st_size/1024:8.1f} KB")
        if not skip_duckdb:
            _write_duckdb(out)

    return {"df": df, "catalog": specs, "report": report,
            "q_long": q_long, "y_long": y_long}


def _write_duckdb(out: Path) -> None:
    """Rebuild the database across every committed snapshot.

    `companies` always means the latest snapshot, so all existing queries and
    endpoints keep their meaning as history accumulates. `companies_history`
    is the full series, opted into explicitly. Getting this the other way
    round would silently multiply every count by the number of snapshots.
    """
    try:
        import duckdb
    except ImportError:
        print("  [skip] duckdb not installed")
        return

    from .snapshots import list_snapshots
    snaps = list_snapshots()
    if not snaps:
        snaps = [out.name.split("=", 1)[1]]
    latest = snaps[-1]

    db = CURATED / "tm750.duckdb"
    con = duckdb.connect(str(db))

    def glob_for(fn: str) -> str:
        return str(CURATED / "snapshot_date=*" / fn).replace("\\", "/")

    # Full history. hive_partitioning derives snapshot_date from the path.
    for name, fn in [("companies_history", "companies.parquet"),
                     ("profit_quarterly_history", "profit_quarterly.parquet"),
                     ("profit_annual_history", "profit_annual.parquet")]:
        con.execute(
            f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_parquet("
            f"'{glob_for(fn)}', hive_partitioning=1, union_by_name=1)")

    # Latest-only, which is what every existing query means by these names.
    for name, src in [("companies", "companies_history"),
                      ("profit_quarterly", "profit_quarterly_history"),
                      ("profit_annual", "profit_annual_history")]:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {src} "
                    f"WHERE snapshot_date = '{latest}'")

    # Catalog follows the latest snapshot: it describes the current schema.
    cat_path = str(CURATED / f"snapshot_date={latest}" / "catalog.csv")
    con.execute("CREATE OR REPLACE TABLE catalog AS "
                f"SELECT * FROM read_csv_auto('{cat_path}')")

    con.execute("CREATE OR REPLACE TABLE snapshots AS "
                "SELECT snapshot_date, count(*) AS companies "
                "FROM companies_history GROUP BY 1 ORDER BY 1")

    n = con.execute("SELECT count(*) FROM companies").fetchone()[0]
    tot = con.execute("SELECT count(*) FROM companies_history").fetchone()[0]
    con.close()
    print(f"  tm750.duckdb                 {len(snaps)} snapshot(s), "
          f"{n} companies latest, {tot} rows total")


if __name__ == "__main__":
    build()
