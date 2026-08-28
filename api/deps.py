"""Request-scoped dependencies."""
from __future__ import annotations

from fastapi import HTTPException, Query

from . import db


def as_of(snapshot: str | None = Query(
        None, description="View the data as of a past snapshot date "
                          "(YYYY-MM-DD). Defaults to the latest.")):
    """Point this request at a past snapshot.

    Validated against the set of snapshots actually held, so an unknown date
    is a 422 rather than a silently empty result -- and so the value is safe
    to embed in the retargeted query.
    """
    if snapshot:
        known = db.snapshots()
        if snapshot not in known:
            raise HTTPException(
                422, f"No snapshot for {snapshot}. Held: {', '.join(known)}.")
    db.set_snapshot(snapshot)
    try:
        yield snapshot
    finally:
        # Threads are reused across requests, so this must always be cleared
        # or the next request on this thread inherits the date.
        db.set_snapshot(None)
