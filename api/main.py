"""tm750 API -- FastAPI over DuckDB.

Run:  uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .routers import admin, data, explore, history, meta, scanner
from tm750.scanner import store as scanner_store

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Single-threaded warm-up so no request ever races an empty cache.
    info = db.warm_caches()
    print(f"  tm750: {info['columns']} columns, {info['segments']} segments, "
          f"snapshot {db.snapshots()[-1]}")
    scanner_store.init_schema()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="tm750",
    description="Nifty Total Market — 750 companies, 462 columns.",
    version="0.1.0",
)

# Vite dev server. Tightened before any non-local deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta.router)
app.include_router(data.router)
app.include_router(explore.router)
app.include_router(history.router)
app.include_router(admin.router)
app.include_router(scanner.router)


@app.get("/health")
def health():
    n = db.query_one("SELECT count(*) AS n FROM companies")["n"]
    return {"status": "ok", "companies": n, "columns": len(db.catalog()),
            "snapshots": db.snapshots()}
