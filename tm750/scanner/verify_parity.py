"""Verify Scanner and the main pipeline agree on every shared company.

Deliberately NOT a pytest test. conftest.py redirects every test in this
suite to a throwaway database so pytest can never touch production data --
which means a pytest test can never READ production data either, on purpose.
This script is the other side of that: it opens both real databases
explicitly, read-only, and reports whether the "one implementation" claim
actually holds on your live data, not just in isolated unit tests.

Run:
    python -m tm750.scanner.verify_parity

Both connections are read-only. Nothing here can modify either database.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb


def _connect_ro(path: Path, label: str) -> duckdb.DuckDBPyConnection | None:
    if not path.exists():
        print(f"  [skip] {label}: {path} does not exist")
        return None
    try:
        return duckdb.connect(str(path), read_only=True)
    except Exception as exc:
        print(f"  [skip] {label}: could not open read-only -- {exc}")
        return None


def main() -> int:
    scanner_path = Path("data/curated/scanner.duckdb")
    main_path = Path("data/curated/tm750.duckdb")

    print("Scanner / main pipeline profit-verdict parity check")
    print(f"  scanner : {scanner_path.resolve()}")
    print(f"  main    : {main_path.resolve()}")
    print()

    scon = _connect_ro(scanner_path, "scanner.duckdb")
    mcon = _connect_ro(main_path, "tm750.duckdb")
    if scon is None or mcon is None:
        print("Cannot run the comparison -- see above.")
        return 1

    try:
        scanner_rows = scon.execute(
            "SELECT isin, pat_both_at_ath FROM profit").fetchall()
    except Exception as exc:
        print(f"  [skip] scanner.duckdb has no 'profit' table yet -- {exc}")
        print("  Run 'Fetch latest profit data' in the Universe tab first.")
        return 1

    try:
        main_rows = mcon.execute(
            "SELECT isin, pat_both_at_ath FROM companies").fetchall()
    except Exception as exc:
        print(f"  [skip] tm750.duckdb has no 'companies' table yet -- {exc}")
        print("  Run 'python -m tm750.add_snapshot --rebuild-all' first.")
        return 1

    if not scanner_rows:
        print("  [skip] scanner profit table is empty.")
        return 1
    if not main_rows:
        print("  [skip] main companies table is empty.")
        return 1

    scanner = {isin: bool(flag) for isin, flag in scanner_rows}
    main = {isin: bool(flag) for isin, flag in main_rows}
    shared = set(scanner) & set(main)

    print(f"  scanner profit rows : {len(scanner)}")
    print(f"  main companies rows : {len(main)}")
    print(f"  shared ISINs        : {len(shared)}")
    print()

    if not shared:
        print("  [skip] no ISIN overlap between the two databases yet.")
        return 1

    mismatched = sorted(i for i in shared if scanner[i] != main[i])

    if not mismatched:
        print(f"PASS -- all {len(shared)} shared companies agree.")
        print("Scanner and the main pipeline give identical profit "
              "verdicts for every company both sides know about.")
        return 0

    print(f"FAIL -- {len(mismatched)} of {len(shared)} shared companies "
          "disagree:")
    for isin in mismatched[:20]:
        print(f"    {isin}: scanner={scanner[isin]}  main={main[isin]}")
    if len(mismatched) > 20:
        print(f"    ... and {len(mismatched) - 20} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
