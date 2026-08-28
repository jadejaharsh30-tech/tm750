"""Scanner store: its own file, its own connections, thread-safe."""
from __future__ import annotations

import concurrent.futures as cf

from tm750.scanner import store


def test_scanner_db_is_a_separate_file():
    """Sharing tm750.duckdb would fight api/db.py's read-only handle."""
    assert store.DB_PATH.name.endswith(".duckdb")
    assert "tm750.duckdb" not in str(store.DB_PATH)


def test_schema_creates_every_table():
    store.init_schema()
    got = {r[0] for r in store.cursor().execute(
        "SELECT table_name FROM duckdb_tables()").fetchall()}
    assert {"universe", "ath", "ath_events", "profit", "result_dates",
            "feed_identifiers", "scan_results", "scan_status"} <= got


def test_init_schema_is_idempotent():
    """Called on every app start; must not wipe data."""
    store.init_schema()
    store.cursor().execute(
        "INSERT INTO universe (symbol, exchange) VALUES ('TESTCO', 'NSE')")
    store.init_schema()
    n = store.cursor().execute(
        "SELECT count(*) FROM universe WHERE symbol='TESTCO'").fetchone()[0]
    assert n == 1
    store.cursor().execute("DELETE FROM universe WHERE symbol='TESTCO'")


def test_status_row_is_seeded_exactly_once():
    store.init_schema()
    store.init_schema()
    n = store.cursor().execute(
        "SELECT count(*) FROM scan_status").fetchone()[0]
    assert n == 1


def test_each_thread_gets_its_own_cursor():
    """One shared connection across threads corrupts result sets under load."""
    store.init_schema()

    def query(_):
        return store.cursor().execute("SELECT 42").fetchone()[0]

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        assert list(ex.map(query, range(40))) == [42] * 40


def test_close_all_invalidates_cursors_in_other_threads():
    """Without a generation counter a worker keeps using a closed connection."""
    store.init_schema()

    def query(_):
        return store.cursor().execute("SELECT 1").fetchone()[0]

    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(query, range(8)))
        store.close_all()
        assert list(ex.map(query, range(8))) == [1] * 8


# --------------------------------------------------------------- migration
def test_migration_adds_the_column_to_a_database_created_before_it_existed():
    """The user's live database predates last_split_check. CREATE TABLE IF
    NOT EXISTS does nothing to an already-existing table, so this must be an
    explicit ALTER -- and it must not lose the row already there."""
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "old_schema.duckdb"
    store.close_all()
    old_path = store.DB_PATH
    try:
        store.DB_PATH = tmp
        cur = store.connect()
        cur.execute("""
            CREATE TABLE ath (
                symbol VARCHAR PRIMARY KEY, ath_price DOUBLE,
                ath_date DATE, today_ath DOUBLE, last_updated TIMESTAMP)
        """)
        cur.execute(
            "INSERT INTO ath VALUES ('OLDROW', 100.0, DATE '2020-01-01', "
            "NULL, NULL)")

        store.init_schema()

        cols = {r[1] for r in cur.execute(
            "PRAGMA table_info('ath')").fetchall()}
        assert "last_split_check" in cols

        row = cur.execute(
            "SELECT symbol, ath_price FROM ath WHERE symbol='OLDROW'"
        ).fetchone()
        assert row == ("OLDROW", 100.0)
    finally:
        store.close_all()
        store.DB_PATH = old_path
