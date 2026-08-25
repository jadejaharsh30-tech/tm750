"""Concurrency contract.

A DuckDB connection is not thread-safe, and FastAPI runs sync endpoints in a
threadpool. Sharing one connection across that pool interleaves in-flight
queries and returns rows to the wrong caller -- which surfaces as endpoints
that work on one page load and fail on the next, with no pattern.

These tests hold that fix in place.
"""
from __future__ import annotations

import concurrent.futures as cf

import pytest
from fastapi.testclient import TestClient

from api.main import app

PATHS = [
    "/health", "/pulse", "/meta/catalog", "/meta/segments", "/meta/snapshots",
    "/meta/enums", "/meta/quality", "/search?q=cup", "/search?q=tcs",
    "/companies/TCS", "/companies/HDFCBANK", "/companies/RELIANCE",
    "/companies/TCS/history?freq=FY", "/movers?field=perf_1y_pct&n=6",
    "/explore/tier", "/explore/sector", "/explore/factors/overlap",
]


@pytest.fixture(scope="module")
def client():
    # The context manager runs lifespan, which warms the caches.
    with TestClient(app) as c:
        yield c


def _hammer(client, paths, workers=24):
    errors = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(client.get, p): p for p in paths}
        for fut in cf.as_completed(futures):
            path = futures[fut]
            try:
                res = fut.result()
                if res.status_code != 200:
                    errors.append(f"{path} -> {res.status_code}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path} -> {type(exc).__name__}: {exc}")
    return errors


def test_concurrent_reads_all_succeed(client):
    errors = _hammer(client, PATHS * 8)
    assert not errors, f"{len(errors)} of {len(PATHS) * 8} failed: {errors[:5]}"


def test_concurrent_screens_all_succeed(client):
    bodies = [
        {"filters": [{"field": "cap_tier", "op": "eq", "value": t}], "limit": 50}
        for t in ["Large", "Mid", "Small", "Micro"]
    ] * 10
    errors = []
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        futures = [ex.submit(client.post, "/screen", json=b) for b in bodies]
        for fut in cf.as_completed(futures):
            try:
                res = fut.result()
                if res.status_code != 200:
                    errors.append(res.status_code)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
    assert not errors, f"{len(errors)} screen calls failed: {errors[:5]}"


def test_concurrent_results_are_not_crossed(client):
    """The dangerous failure is not an error -- it is one request receiving
    another's rows. Each symbol must come back as itself, every time."""
    symbols = ["TCS", "INFY", "WIPRO", "RELIANCE", "HDFCBANK", "ITC"] * 12
    mismatches = []
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        futures = {ex.submit(client.get, f"/companies/{s}"): s for s in symbols}
        for fut, want in futures.items():
            got = fut.result().json().get("symbol")
            if got != want:
                mismatches.append(f"asked {want}, got {got}")
    assert not mismatches, f"crossed responses: {mismatches[:5]}"


def test_catalog_stays_intact_under_load(client):
    """A corrupted read memoised into lru_cache would poison every later
    request for the life of the process. Verify shape holds after a burst."""
    _hammer(client, PATHS * 4)
    cat = client.get("/meta/catalog").json()
    # Pinned to the table rather than a literal, so adding a column is not a
    # test failure -- but a catalog that silently loses columns still is.
    n_cols = client.get("/health").json()["columns"]
    assert cat["n"] == n_cols > 400
    assert all({"name", "segment", "unit", "fmt", "polarity", "finance_valid"}
               <= set(c) for c in cat["columns"])
