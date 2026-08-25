"""Admin: upload a day's raw files and commit a snapshot.

This shares the exact pipeline the CLI uses, so there is one implementation
rather than two that drift. Uploaded files land in a temp directory, are
classified by name, and are only committed once the build has validated.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from tm750 import add_snapshot, snapshots
from tm750.config import SOURCES
from tm750.ingest import IngestError
from tm750.snapshots import SnapshotError

from .. import db

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_BYTES = 60 * 1024 * 1024


@router.get("/snapshots")
def list_snapshots():
    rows = snapshots.describe()
    return {"snapshots": rows, "n": len(rows),
            "latest": rows[-1]["snapshot_date"] if rows else None,
            "expected_sources": SOURCES}


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...),
                 snapshot_date: str | None = Form(None),
                 replace: bool = Form(False),
                 allow_duplicate: bool = Form(False)):
    """Accept any subset of the four raw files and build a snapshot.

    Sources not supplied are carried forward from the most recent snapshot
    that had them, which is the normal case for the quarterly profit
    workbooks.
    """
    if not files:
        raise HTTPException(422, "No files received.")

    tmp = Path(tempfile.mkdtemp(prefix="tm750-upload-"))
    try:
        saved: list[Path] = []
        for f in files:
            if not f.filename:
                continue
            dest = tmp / Path(f.filename).name
            size = 0
            with open(dest, "wb") as out:
                while chunk := await f.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(
                            413, f"{f.filename} exceeds the 60 MB limit.")
                    out.write(chunk)
            saved.append(dest)

        if not saved:
            raise HTTPException(422, "No usable files received.")

        try:
            classified = add_snapshot.classify(saved)
        except SnapshotError as exc:
            raise HTTPException(422, str(exc)) from exc

        # The rebuild opens the database read-write, which DuckDB refuses
        # while our read-only connections are held. Release them first.
        db.close_all()
        try:
            manifest = add_snapshot.add(
                supplied=classified, snapshot_date=snapshot_date,
                replace=replace, allow_duplicate=allow_duplicate)
        except SnapshotError as exc:
            # A refusal here is a real answer -- duplicate files, an existing
            # date, a missing source with no history to carry forward.
            raise HTTPException(409, str(exc)) from exc
        except IngestError as exc:
            # A malformed export is the user's file, not our fault. 422 says
            # "fix the file", where 500 would say "the server is broken".
            raise HTTPException(
                422, f"{exc}. Nothing was committed.") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                500, f"Build failed, nothing was committed: {exc}") from exc

        db.reset_caches()
        return {"ok": True, "manifest": manifest,
                "snapshots": snapshots.list_snapshots()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.post("/preview")
async def preview(files: list[UploadFile] = File(...)):
    """Classify uploaded files and report what would happen, without building.

    Lets the upload page show which source each file was recognised as, what
    date it would take, and which sources would be carried forward -- before
    anything is committed.
    """
    tmp = Path(tempfile.mkdtemp(prefix="tm750-preview-"))
    try:
        saved = []
        for f in files:
            if not f.filename:
                continue
            dest = tmp / Path(f.filename).name
            with open(dest, "wb") as out:
                while chunk := await f.read(1 << 20):
                    out.write(chunk)
            saved.append(dest)

        try:
            classified = add_snapshot.classify(saved)
        except SnapshotError as exc:
            return {"ok": False, "error": str(exc),
                    "filenames": [p.name for p in saved]}

        date_ = snapshots.resolve_snapshot_date(
            {k: v.name for k, v in classified.items()})
        try:
            resolved = snapshots.resolve_sources(classified)
        except SnapshotError as exc:
            return {"ok": False, "error": str(exc), "snapshot_date": date_,
                    "recognised": {k: v.name for k, v in classified.items()}}

        dupe = snapshots.is_duplicate_upload(resolved)
        existing = snapshots.list_snapshots()
        return {
            "ok": True,
            "snapshot_date": date_,
            "already_exists": date_ in existing,
            "duplicate_of": dupe,
            "recognised": {k: v.name for k, v in classified.items()},
            "carried_forward": {
                k: v["from_snapshot"] for k, v in resolved.items()
                if v["carried_forward"]},
            "snapshots_held": len(existing),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.delete("/snapshots/{snapshot_date}")
def delete(snapshot_date: str):
    try:
        snapshots.delete_snapshot(snapshot_date)
    except SnapshotError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.close_all()
    add_snapshot.rebuild_database()
    db.reset_caches()
    return {"ok": True, "snapshots": snapshots.list_snapshots()}
