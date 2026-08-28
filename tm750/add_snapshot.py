"""Add a snapshot from a set of supplied raw files.

    python -m tm750.add_snapshot path/to/*.csv path/to/*.xlsx
    python -m tm750.add_snapshot --date 2026-08-21 tradingview.csv screener.csv
    python -m tm750.add_snapshot --list

The same entry point backs the upload page, so there is one pipeline rather
than two implementations that drift apart.

Commit is atomic: the snapshot is built into a staging directory and only
moved into place once it has passed validation. A failed build therefore
leaves every existing snapshot exactly as it was.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from . import snapshots
from .config import CURATED, DAILY_SOURCES, EXPECTED_UNIVERSE, SOURCES
from .snapshots import SnapshotError


def rebuild_database() -> None:
    """Rebuild DuckDB across every committed snapshot.

    DuckDB refuses to open a file read-write while another connection holds it
    read-only, so any live API connections must be released first. The caller
    is responsible for that; from the CLI there are none.
    """
    from .build import _write_duckdb
    latest = snapshots.latest_snapshot()
    if latest:
        _write_duckdb(snapshots.snapshot_dir(latest))


def rebuild_all() -> list[str]:
    """Rebuild every held snapshot from its own archived raw files.

    Needed whenever the data layer changes shape -- a new column, a new
    catalog field. Older snapshots keep the catalog they were built with, and
    since the `catalog` table follows the latest snapshot, one stale day
    silently serves an outdated schema to the whole app.

    Each day is rebuilt from the files archived alongside it, so the result is
    identical to what that day would have produced under the current code.
    """
    held = snapshots.list_snapshots()
    if not held:
        raise SnapshotError("No snapshots to rebuild.")

    done = []
    for snap in held:
        archive = snapshots.archive_dir(snap)
        manifest = snapshots.manifest(snap) or {}
        supplied: dict[str, Path] = {}

        for key in SOURCES:
            info = (manifest.get("sources") or {}).get(key, {})
            origin = info.get("from_snapshot") or snap
            path = snapshots.archive_dir(origin) / info.get(
                "filename", SOURCES[key])
            if path.exists():
                supplied[key] = path

        if not supplied and archive.exists():
            supplied = classify(sorted(
                p for p in archive.iterdir() if p.is_file()))
        if not supplied:
            print(f"  ! {snap}: no archived files, skipped")
            continue

        print(f"\n  rebuilding {snap} from archive")
        add(supplied=supplied, snapshot_date=snap, replace=True,
            allow_duplicate=True)
        done.append(snap)

    return done


def classify(paths: list[Path]) -> dict[str, Path]:
    """Work out which source each supplied file is, by name.

    Files are identified by pattern rather than position, so the order they
    are given -- or dragged onto the upload page -- does not matter.
    """
    from .config import SOURCE_PATTERNS
    out: dict[str, Path] = {}
    unmatched: list[Path] = []

    for p in paths:
        p = Path(p)
        matched = None
        for key, patterns in SOURCE_PATTERNS.items():
            if key in out:
                continue
            if p.name == SOURCES[key] or any(
                    p.match(pat) or Path(p.name).match(pat) for pat in patterns):
                matched = key
                break
        if matched:
            out[matched] = p
        else:
            unmatched.append(p)

    if unmatched:
        raise SnapshotError(
            "Could not identify: " + ", ".join(u.name for u in unmatched)
            + ". Expected files matching " + ", ".join(
                f"{k}: {v[0]}" for k, v in SOURCE_PATTERNS.items()))
    return out


def add(paths: list[Path] | None = None, snapshot_date: str | None = None,
        allow_duplicate: bool = False, replace: bool = False,
        supplied: dict[str, Path] | None = None) -> dict:
    """Build and commit one snapshot. Returns its manifest."""
    files = supplied if supplied is not None else classify(list(paths or []))
    if not files:
        raise SnapshotError("No files supplied.")

    snap = snapshots.resolve_snapshot_date(
        {k: str(v.name) for k, v in files.items()}, snapshot_date)

    existing = snapshots.list_snapshots()
    if snap in existing and not replace:
        raise SnapshotError(
            f"Snapshot {snap} already exists. Re-run with replace to rebuild "
            f"it, or supply a different date.")

    resolved = snapshots.resolve_sources(files)

    stale = [k for k in DAILY_SOURCES if resolved[k]["carried_forward"]]
    if stale:
        print(f"  ! carrying forward daily source(s): {', '.join(stale)} "
              f"-- these normally change every day")

    if not allow_duplicate:
        dupe = snapshots.is_duplicate_upload(resolved)
        if dupe and dupe != snap:
            raise SnapshotError(
                f"These files are byte-identical to snapshot {dupe}. Adding "
                f"them again would create a day showing zero change and "
                f"distort day-over-day comparisons. Override if intended.")

    # ---- build once into staging, validate, then move into place
    #
    # Building to staging and moving is what makes the commit atomic: the
    # live partition is only touched after the new one is complete and has
    # passed validation, so a failed upload cannot leave a half-written day
    # where a good one used to be.
    staging = Path(tempfile.mkdtemp(prefix="tm750-stage-"))
    stage_raw = staging / "raw"
    stage_raw.mkdir()
    for key, info in resolved.items():
        shutil.copy2(info["path"], stage_raw / Path(info["path"]).name)
    per_source = {k: stage_raw for k in resolved}
    stage_out = staging / "out"

    print(f"\nBuilding snapshot {snap}")
    from .build import build
    # skip_duckdb: the database is rebuilt once at the end, across every
    # snapshot, rather than from inside a build that might not commit.
    result = build(write=True, snapshot_date=snap, per_source_dirs=per_source,
                   out_dir=stage_out, skip_duckdb=True)
    df = result["df"]

    if len(df) != EXPECTED_UNIVERSE:
        shutil.rmtree(staging, ignore_errors=True)
        raise SnapshotError(
            f"Build produced {len(df)} companies, expected {EXPECTED_UNIVERSE}. "
            f"Nothing was committed. Check the export covers the full "
            f"Nifty Total Market universe.")

    target = snapshots.snapshot_dir(snap)
    backup = None
    if target.exists():
        # Deliberately NOT named "snapshot_date=...": that pattern is the glob
        # every reader uses to discover snapshots, so a backup carrying it
        # would be counted as a real day and could be picked as "latest".
        backup = target.parent / f".backup_{snap}"
        shutil.rmtree(backup, ignore_errors=True)
        target.rename(backup)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage_out), str(target))
        sources = snapshots.archive_sources(snap, resolved)
        manifest = snapshots.write_manifest(snap, sources, {
            "universe": int(len(df)),
            "columns": int(df.shape[1]),
            "replaced": bool(backup),
        })
        rebuild_database()
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        if backup and backup.exists():
            backup.rename(target)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    if backup:
        shutil.rmtree(backup, ignore_errors=True)

    all_snaps = snapshots.list_snapshots()
    print(f"\n  committed {snap} -- {len(all_snaps)} snapshot(s) now held: "
          f"{', '.join(all_snaps)}")
    return manifest


# ------------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m tm750.add_snapshot",
        description="Add a daily snapshot from raw export files.")
    ap.add_argument("files", nargs="*", type=Path,
                    help="Raw files. Any subset; missing sources are carried "
                         "forward from the most recent snapshot that has them.")
    ap.add_argument("--date", help="Snapshot date (YYYY-MM-DD). Defaults to "
                                   "the date in the TradingView filename.")
    ap.add_argument("--replace", action="store_true",
                    help="Rebuild a date that already exists.")
    ap.add_argument("--allow-duplicate", action="store_true",
                    help="Accept files identical to an existing snapshot.")
    ap.add_argument("--list", action="store_true",
                    help="List snapshots and exit.")
    ap.add_argument("--delete", metavar="DATE", help="Delete a snapshot.")
    ap.add_argument("--rebuild-all", action="store_true",
                    help="Rebuild every held snapshot from its archived raw "
                         "files. Run after any change to the data layer.")
    args = ap.parse_args(argv)

    if args.list:
        rows = snapshots.describe()
        if not rows:
            print("No snapshots yet.")
            return 0
        print(f"{'date':12s} {'companies':>9s} {'cols':>5s}  {'size':>9s}  built")
        for r in rows:
            carried = (f"  (carried: {', '.join(r['carried_forward'])})"
                       if r["carried_forward"] else "")
            print(f"{r['snapshot_date']:12s} {str(r['universe'] or '-'):>9s} "
                  f"{str(r['columns'] or '-'):>5s} {r['size_kb']:>7.0f} KB  "
                  f"{r['built_at'] or '-'}{carried}")
        return 0

    if args.rebuild_all:
        done = rebuild_all()
        print(f"\nRebuilt {len(done)} snapshot(s): {', '.join(done)}")
        return 0

    if args.delete:
        snapshots.delete_snapshot(args.delete)
        print(f"Deleted {args.delete}. Remaining: "
              f"{', '.join(snapshots.list_snapshots())}")
        return 0

    if not args.files:
        ap.error("Supply at least one file, or use --list / --delete.")

    try:
        add(args.files, snapshot_date=args.date, replace=args.replace,
            allow_duplicate=args.allow_duplicate)
    except SnapshotError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
