"""Scanner persistence.

Deliberately a separate DuckDB file from tm750.duckdb. api/db.py holds that
one read-only, and DuckDB refuses to open a file read-write while a read-only
connection exists -- which is why close_all() exists there for rebuilds. The
scanner writes on every scan, edit and sync, so sharing the file would mean
tearing down the API's connections continuously.

Connection model mirrors api/db.py: one root connection, a .cursor() per
worker thread. DuckDB connections are not thread-safe; cursors taken off a
single root connection are.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

DB_PATH = Path(os.environ.get("SCANNER_DB_PATH", "data/curated/scanner.duckdb"))

_root: duckdb.DuckDBPyConnection | None = None
_local = threading.local()
_lock = threading.Lock()

# Bumped by close_all(). A worker thread holding a cursor from a previous
# generation would otherwise keep using a closed connection -- the same trap
# api/db.py solves the same way.
_generation = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    symbol        VARCHAR PRIMARY KEY,
    exchange      VARCHAR DEFAULT 'NSE',
    isin          VARCHAR,
    accord_code   VARCHAR,
    resolution    VARCHAR DEFAULT 'unresolved',
    ignored       BOOLEAN DEFAULT FALSE,
    ignore_reason VARCHAR,
    source_file   VARCHAR,
    added_at      TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS ath (
    symbol           VARCHAR PRIMARY KEY,
    ath_price        DOUBLE,
    ath_date         DATE,
    today_ath        DOUBLE,
    last_split_check DATE,
    last_updated     TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS ath_events_seq;

CREATE TABLE IF NOT EXISTS ath_events (
    id         BIGINT PRIMARY KEY DEFAULT nextval('ath_events_seq'),
    symbol     VARCHAR,
    event_date DATE,
    old_price  DOUBLE,
    new_price  DOUBLE,
    old_date   DATE,
    new_date   DATE,
    source     VARCHAR,
    note       VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS profit (
    isin            VARCHAR PRIMARY KEY,
    pat_ttm_at_ath  BOOLEAN,
    pat_q_at_ath    BOOLEAN,
    pat_both_at_ath BOOLEAN,
    qtrs_available  INTEGER,
    pat_ttm         DOUBLE,
    pat_fy_peak     DOUBLE,
    pat_latest_q    DOUBLE,
    pat_peak_q      DOUBLE,
    fetched_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feed_identifiers (
    nse_code       VARCHAR,
    isin           VARCHAR,
    accord_code    VARCHAR,
    company_name   VARCHAR,
    trading_status VARCHAR
);

CREATE TABLE IF NOT EXISTS result_dates (
    symbol      VARCHAR PRIMARY KEY,
    result_date DATE,
    status      VARCHAR,
    checked_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scan_results (
    symbol             VARCHAR PRIMARY KEY,
    new_ath_price      DOUBLE,
    trigger_price      DOUBLE,
    green_candle       VARCHAR,
    close_gt_ath       VARCHAR,
    ath_outperformance VARCHAR,
    current_rs         DOUBLE,
    ath_rs             DOUBLE,
    profit_state       VARCHAR,
    profit_stale       BOOLEAN,
    result_date        DATE,
    stop_loss          DOUBLE,
    scanned_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scan_status (
    id           INTEGER PRIMARY KEY,
    is_running   BOOLEAN DEFAULT FALSE,
    progress     INTEGER DEFAULT 0,
    total        INTEGER DEFAULT 0,
    message      VARCHAR DEFAULT 'Idle',
    last_updated TIMESTAMP
);
"""

_SEED_STATUS = """
INSERT INTO scan_status (id, is_running, progress, total, message)
SELECT 1, FALSE, 0, 0, 'Idle'
WHERE NOT EXISTS (SELECT 1 FROM scan_status WHERE id = 1)
"""


def connect() -> duckdb.DuckDBPyConnection:
    """Thread-local cursor off a single root connection."""
    global _root
    if _root is None:
        with _lock:
            if _root is None:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                _root = duckdb.connect(str(DB_PATH))
    cur = getattr(_local, "cur", None)
    if cur is None or getattr(_local, "gen", -1) != _generation:
        cur = _root.cursor()
        _local.cur = cur
        _local.gen = _generation
    return cur


def cursor() -> duckdb.DuckDBPyConnection:
    return connect()


def init_schema() -> None:
    """Safe to call on every start -- all DDL is IF NOT EXISTS."""
    cur = connect()
    for stmt in filter(str.strip, SCHEMA.split(";")):
        cur.execute(stmt)
    cur.execute(_SEED_STATUS)
    _migrate(cur)


def _migrate(cur) -> None:
    """Additive schema changes for databases created before a column existed.

    CREATE TABLE IF NOT EXISTS does nothing to an already-existing table with
    an older shape -- a genuinely new column needs an explicit ALTER, or an
    existing installation's ath table would silently lack last_split_check
    forever and the split-repair fix would have no column to write to.
    """
    try:
        cur.execute(
            "ALTER TABLE ath ADD COLUMN IF NOT EXISTS "
            "last_split_check DATE")
    except Exception:
        pass


def close_all() -> None:
    """Drop every connection. Used by tests and on shutdown."""
    global _root, _generation
    with _lock:
        if _root is not None:
            _root.close()
            _root = None
        _generation += 1
    _local.__dict__.pop("cur", None)
    _local.__dict__.pop("gen", None)
