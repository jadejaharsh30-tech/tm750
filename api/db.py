"""DuckDB access layer.

One read-only connection, opened once. The catalog is loaded into memory at
startup and used to validate every incoming request, so an unknown column
never reaches SQL.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CURATED = ROOT / "data" / "curated"
DB_PATH = CURATED / "tm750.duckdb"

_lock = threading.Lock()
_root: duckdb.DuckDBPyConnection | None = None
_local = threading.local()

# Bumped whenever the database is rebuilt. Worker threads hold their own
# connections, so they cannot be closed from here -- instead each one checks
# the generation it was opened at and reopens if it has fallen behind. Without
# this the app keeps serving the previous snapshot after an upload.
_generation = 0


def _root_connection() -> duckdb.DuckDBPyConnection:
    """The one connection that owns the database file."""
    global _root
    if _root is None:
        with _lock:
            if _root is None:
                if not DB_PATH.exists():
                    raise FileNotFoundError(
                        f"{DB_PATH} not found. Run `python -m tm750.build` first."
                    )
                _root = duckdb.connect(str(DB_PATH), read_only=True)
    return _root


def connect() -> duckdb.DuckDBPyConnection:
    """A connection private to the calling thread.

    A DuckDB connection is NOT thread-safe: cursor state is per-connection, so
    sharing one across FastAPI's threadpool interleaves in-flight queries and
    delivers rows to the wrong caller. `.cursor()` returns an independent
    connection against the same database, which is the supported way to read
    concurrently. Each worker thread gets one and keeps it.
    """
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "gen", -1) != _generation:
        con = _root_connection().cursor()
        _local.con = con
        _local.gen = _generation
    return con


# The snapshot a request is reading. Set per-request by the `as_of` dependency
# and read inside query(). Thread-local because sync endpoints run in
# FastAPI's threadpool, one request per thread.
_active = threading.local()

_COMPANIES_RE = re.compile(r"\bFROM\s+companies\b(?!_)", re.IGNORECASE)


def set_snapshot(snapshot: str | None) -> None:
    _active.snapshot = snapshot


def current_snapshot() -> str | None:
    return getattr(_active, "snapshot", None)


def _retarget(sql: str) -> str:
    """Point `FROM companies` at a past snapshot when one is selected.

    Rewriting here rather than in each of the ~35 queries means a query can
    never be missed and silently keep serving today's numbers while the rest
    of the page shows a past date. The negative lookahead protects
    `companies_history`, which must never be retargeted.
    """
    snap = current_snapshot()
    if not snap:
        return sql
    # snap is whitelist-checked against known snapshots before being set.
    src = (f"(SELECT * FROM companies_history "
           f"WHERE snapshot_date = '{snap}')")
    return _COMPANIES_RE.sub(f"FROM {src}", sql)


def _jsonable(v: Any) -> Any:
    """DuckDB returns date/datetime/Decimal objects that json cannot encode.

    Hive partitioning in particular types `snapshot_date` as DATE even though
    the parquet stores a string, so this is not hypothetical -- without it
    every response carrying that column raises at serialisation time.
    """
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def query(sql: str, params: list[Any] | None = None) -> list[dict]:
    """Parameterised query returning JSON-safe records."""
    cur = connect().execute(_retarget(sql), params or [])
    cols = [d[0] for d in cur.description]
    return [{c: _jsonable(v) for c, v in zip(cols, row)}
            for row in cur.fetchall()]


def query_one(sql: str, params: list[Any] | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def close_all() -> None:
    """Release every connection so the file can be opened read-write.

    DuckDB will not open a database read-write while a read-only connection is
    held, so a snapshot rebuild has to happen with the API's connections shut.
    Bumping the generation makes worker threads reopen on their next query
    rather than reusing a closed handle.
    """
    global _root, _generation
    with _lock:
        if _root is not None:
            try:
                _root.close()
            except Exception:  # noqa: BLE001
                pass
        _root = None
        _generation += 1


def reset_caches() -> dict:
    """Drop every cached read and reopen the database.

    Called after a snapshot is added or removed. The lru_caches memoise the
    catalog and snapshot list, so without clearing them the app would keep
    describing the previous build indefinitely.
    """
    for fn in (catalog, catalog_index, valid_fields, screenable_fields,
               numeric_fields, finance_masked_fields, segments, snapshots,
               quality_report):
        fn.cache_clear()
    close_all()
    return warm_caches()


def warm_caches() -> dict:
    """Populate every lru_cache once, on a single thread, before serving.

    Without this the first concurrent burst can race inside the caches and a
    corrupted read gets memoised for the life of the process -- which looks
    like a permanent, unexplainable failure until uvicorn is restarted.
    """
    catalog(); catalog_index(); valid_fields(); screenable_fields()
    numeric_fields(); finance_masked_fields(); segments(); snapshots()
    quality_report()
    return {"columns": len(catalog()), "segments": len(segments()),
            "snapshots": len(snapshots())}


# ---------------------------------------------------------------- catalog
@lru_cache(maxsize=1)
def catalog() -> list[dict]:
    """Column registry. Every API request validates against this."""
    return query("SELECT * FROM catalog ORDER BY segment, name")


@lru_cache(maxsize=1)
def catalog_index() -> dict[str, dict]:
    return {c["name"]: c for c in catalog()}


@lru_cache(maxsize=1)
def valid_fields() -> frozenset[str]:
    return frozenset(catalog_index())


@lru_cache(maxsize=1)
def screenable_fields() -> frozenset[str]:
    return frozenset(c["name"] for c in catalog() if c["screenable"])


@lru_cache(maxsize=1)
def numeric_fields() -> frozenset[str]:
    return frozenset(c["name"] for c in catalog()
                     if c["unit"] in ("pct", "inr", "ratio", "count"))


@lru_cache(maxsize=1)
def finance_masked_fields() -> frozenset[str]:
    """Metrics meaningless for banks/NBFCs. Masked server-side so no
    consumer can forget and rank financials on inventory turnover."""
    return frozenset(c["name"] for c in catalog() if not c["finance_valid"])


@lru_cache(maxsize=1)
def segments() -> list[dict]:
    """Segment -> columns, for the frontend's column-group toggles."""
    out: dict[str, list[dict]] = {}
    for c in catalog():
        out.setdefault(c["segment"], []).append({
            "name": c["name"], "label": c["label"], "unit": c["unit"],
            "group": c.get("group", "Other"),
            "description": c.get("description", ""),
            "description_source": c.get("description_source", "none"),
            "fmt": c["fmt"], "polarity": c["polarity"],
            "coverage_pct": c["coverage_pct"], "screenable": c["screenable"],
            "provenance": c["provenance"], "finance_valid": c["finance_valid"],
        })
    return [{"segment": k, "n": len(v), "columns": v} for k, v in out.items()]


# -------------------------------------------------------------- snapshots
@lru_cache(maxsize=1)
def snapshots() -> list[str]:
    """Available snapshot dates. Single-element today; the schema and API
    already support more so adding one is a rebuild, not a migration."""
    return sorted(p.name.split("=")[1] for p in CURATED.glob("snapshot_date=*"))


@lru_cache(maxsize=1)
def quality_report() -> dict:
    date = snapshots()[-1]
    path = CURATED / f"snapshot_date={date}" / "quality_report.json"
    return json.loads(path.read_text()) if path.exists() else {}


def apply_finance_mask(rows: list[dict], sector_field: str = "sector"
                       ) -> list[dict]:
    """Null out structurally invalid metrics for financial companies.

    Applied at the API boundary rather than in the UI: a bank's ROCE is not a
    small number, it is a meaningless one, and any consumer that ranks on it
    produces confident nonsense.
    """
    masked = finance_masked_fields()
    out = []
    for r in rows:
        if r.get(sector_field) == "Finance":
            hit = [f for f in masked if f in r and r[f] is not None]
            for f in hit:
                r[f] = None
            r["_masked_fields"] = hit
        else:
            r["_masked_fields"] = []
        out.append(r)
    return out
