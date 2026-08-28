"""Metadata endpoints. The frontend bootstraps entirely from these."""
from __future__ import annotations

from fastapi import APIRouter

from .. import db

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/catalog")
def get_catalog():
    """Full column registry -- drives grid columns, formatting and filters."""
    return {"n": len(db.catalog()), "columns": db.catalog()}


@router.get("/segments")
def get_segments():
    """Columns grouped into the 16 segments, for column-group toggles."""
    return {"segments": db.segments()}


@router.get("/snapshots")
def get_snapshots():
    snaps = db.snapshots()
    return {"snapshots": snaps, "latest": snaps[-1] if snaps else None,
            "multi_snapshot": len(snaps) > 1}


@router.get("/quality")
def get_quality():
    """Coverage, source conflicts, masking impact and history depth."""
    return db.quality_report()


@router.get("/enums")
def get_enums():
    """Distinct values for categorical fields -- populates screener dropdowns."""
    fields = ["sector", "industry", "cap_tier", "analyst_rating",
              "technical_rating", "ma_rating"]
    out = {}
    for f in fields:
        rows = db.query(
            f'SELECT "{f}" AS v, count(*) AS n FROM companies '
            f'WHERE "{f}" IS NOT NULL GROUP BY 1 ORDER BY n DESC'
        )
        out[f] = [{"value": r["v"], "count": r["n"]} for r in rows]
    idx = db.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='companies' AND column_name LIKE 'idx\\_%' ESCAPE '\\'"
    )
    out["index_memberships"] = sorted(r["column_name"] for r in idx)
    return out
