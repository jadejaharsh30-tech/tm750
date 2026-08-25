"""Snapshot lifecycle.

A snapshot is one day's view of the universe, built from whichever raw files
were supplied that day. Two things make this more than "run the build again":

1. **Carry-forward.** The profit workbooks are quarterly, so a daily upload
   normally omits them. Those sources are read from the most recent snapshot
   that did supply them, and the manifest records where each file came from --
   so you can always tell which day's profit data a given snapshot used.

2. **Atomic commit.** A build that fails validation must leave the previous
   snapshot untouched. Everything is written to a staging directory and moved
   into place only once it has passed, so a bad upload can never half-replace
   a good day.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from .config import (ARCHIVE, CARRY_FORWARD_SOURCES, CURATED, DAILY_SOURCES,
                     SOURCE_PATTERNS, SOURCES)

DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
ALL_SOURCES = tuple(SOURCES)


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be built or committed."""


# ------------------------------------------------------------- discovery
def list_snapshots() -> list[str]:
    """Every committed snapshot date, oldest first.

    The date is validated rather than trusted: a stray directory that happens
    to match the glob must not be served as a snapshot.
    """
    if not CURATED.exists():
        return []
    out = []
    for p in CURATED.glob("snapshot_date=*"):
        if not (p / "companies.parquet").exists():
            continue
        value = p.name.split("=", 1)[1]
        try:
            date.fromisoformat(value)
        except ValueError:
            continue
        out.append(value)
    return sorted(out)


def latest_snapshot() -> str | None:
    snaps = list_snapshots()
    return snaps[-1] if snaps else None


def snapshot_dir(snapshot_date: str) -> Path:
    return CURATED / f"snapshot_date={snapshot_date}"


def archive_dir(snapshot_date: str) -> Path:
    return ARCHIVE / snapshot_date


def manifest(snapshot_date: str) -> dict | None:
    p = snapshot_dir(snapshot_date) / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else None


# ------------------------------------------------------------------ date
def infer_date(filename: str) -> str | None:
    """Pull a snapshot date out of a filename.

    The TradingView export is named for the day it covers, which is a better
    default than "today" -- an export downloaded after midnight still belongs
    to the session it describes.
    """
    m = DATE_RE.search(Path(filename).name)
    if not m:
        return None
    try:
        y, mo, d = (int(x) for x in m.groups())
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def resolve_snapshot_date(files: dict[str, str] | None = None,
                          explicit: str | None = None) -> str:
    if explicit:
        try:
            date.fromisoformat(explicit)
        except ValueError as exc:
            raise SnapshotError(
                f"'{explicit}' is not a date in YYYY-MM-DD form.") from exc
        return explicit
    for key in ("tradingview", "screener"):
        name = (files or {}).get(key)
        if name and (found := infer_date(name)):
            return found
    return date.today().isoformat()


# -------------------------------------------------------- carry-forward
def resolve_sources(supplied: dict[str, Path]) -> dict[str, dict]:
    """Decide where each of the four sources comes from.

    Supplied files win. Anything missing is taken from the most recent
    snapshot that archived it. A daily source that has to be carried forward
    is allowed but reported, because a stale price file is a real problem in a
    way that a stale quarterly profit file is not.
    """
    resolved: dict[str, dict] = {}
    history = list(reversed(list_snapshots()))

    for key in ALL_SOURCES:
        if key in supplied and Path(supplied[key]).exists():
            resolved[key] = {"path": Path(supplied[key]),
                             "from_snapshot": None, "carried_forward": False}
            continue

        found = None
        for snap in history:
            d = archive_dir(snap)
            if not d.exists():
                continue
            hits = [p for pattern in SOURCE_PATTERNS.get(key, [])
                    for p in sorted(d.glob(pattern))]
            exact = d / SOURCES[key]
            if exact.exists():
                hits = [exact, *hits]
            if hits:
                found = {"path": hits[0], "from_snapshot": snap,
                         "carried_forward": True}
                break

        if not found:
            expected = SOURCES[key]
            raise SnapshotError(
                f"'{key}' was not supplied and no previous snapshot has it. "
                f"Upload {expected} (or a file matching "
                f"{SOURCE_PATTERNS.get(key, [])}) at least once.")
        resolved[key] = found

    return resolved


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def is_duplicate_upload(resolved: dict[str, dict]) -> str | None:
    """Return the snapshot date whose daily sources are byte-identical.

    Uploading the same TradingView export twice is a mistake worth catching:
    it would otherwise create a second snapshot showing zero change and
    quietly distort any day-over-day comparison.
    """
    fresh = {k: sha256(v["path"]) for k, v in resolved.items()
             if k in DAILY_SOURCES and not v["carried_forward"]}
    if not fresh:
        return None
    for snap in reversed(list_snapshots()):
        m = manifest(snap)
        if not m:
            continue
        prior = {k: v.get("sha256") for k, v in (m.get("sources") or {}).items()}
        if all(prior.get(k) == v for k, v in fresh.items()):
            return snap
    return None


# ------------------------------------------------------------- archiving
def archive_sources(snapshot_date: str, resolved: dict[str, dict]) -> dict:
    """Copy the raw inputs beside the snapshot and record their provenance."""
    dest = archive_dir(snapshot_date)
    dest.mkdir(parents=True, exist_ok=True)
    record: dict[str, dict] = {}

    for key, info in resolved.items():
        src = Path(info["path"])
        if info["carried_forward"]:
            # Not re-archived. The manifest points at the snapshot that has it,
            # so history stays one copy per distinct file rather than per day.
            record[key] = {
                "filename": src.name, "sha256": sha256(src),
                "from_snapshot": info["from_snapshot"], "carried_forward": True,
            }
            continue
        target = dest / src.name
        if src.resolve() != target.resolve():
            shutil.copy2(src, target)
        record[key] = {
            "filename": target.name, "sha256": sha256(target),
            "from_snapshot": snapshot_date, "carried_forward": False,
        }
    return record


def write_manifest(snapshot_date: str, sources: dict, extra: dict) -> dict:
    m = {
        "snapshot_date": snapshot_date,
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sources": sources,
        **extra,
    }
    (snapshot_dir(snapshot_date) / "manifest.json").write_text(
        json.dumps(m, indent=1, default=str))
    return m


# ---------------------------------------------------------------- delete
def delete_snapshot(snapshot_date: str, keep_archive: bool = True) -> None:
    if snapshot_date not in list_snapshots():
        raise SnapshotError(f"No snapshot for {snapshot_date}.")
    if len(list_snapshots()) == 1:
        raise SnapshotError(
            "Refusing to delete the only snapshot -- the app would have no "
            "data to serve.")
    shutil.rmtree(snapshot_dir(snapshot_date), ignore_errors=True)
    if not keep_archive:
        shutil.rmtree(archive_dir(snapshot_date), ignore_errors=True)


def describe() -> list[dict]:
    """Snapshot list with provenance, for the admin view."""
    out = []
    for snap in list_snapshots():
        m = manifest(snap) or {}
        carried = [k for k, v in (m.get("sources") or {}).items()
                   if v.get("carried_forward")]
        out.append({
            "snapshot_date": snap,
            "built_at": m.get("built_at"),
            "universe": m.get("universe"),
            "columns": m.get("columns"),
            "carried_forward": carried,
            "sources": m.get("sources", {}),
            "size_kb": round(sum(
                f.stat().st_size for f in snapshot_dir(snap).glob("*")) / 1024, 1),
        })
    return out
