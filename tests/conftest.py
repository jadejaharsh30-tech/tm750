"""Test-session safety net.

Every scanner test writes to the DuckDB file at tm750.scanner.store.DB_PATH,
and several of them run DELETE FROM against real-shaped tables (universe,
feed_identifiers, profit, ath). Relying on a person to `set
SCANNER_DB_PATH=...` correctly in every fresh terminal, forever, is fragile --
one window where that step is skipped runs those DELETEs against the actual
data/curated/scanner.duckdb and silently wipes production data. That is
exactly what happened on 2026-08-27: feed_identifiers was emptied by a stray
test run, and every subsequent universe upload read as unresolved.

This redirects every test run to a throwaway file, unconditionally, at import
time -- before pytest imports a single test_*.py module -- so a bare `pytest`
in any terminal, on any device, on any day, can never reach production data
again. The SCANNER_DB_PATH environment variable is no longer required for
safety; it may still be set to inspect a specific file's tests, but nothing
bad happens if it is not.
"""
import tempfile
from pathlib import Path

from tm750.scanner import store

_tmp_dir = tempfile.mkdtemp(prefix="tm750_scanner_tests_")
store.DB_PATH = Path(_tmp_dir) / "scanner_test.duckdb"
