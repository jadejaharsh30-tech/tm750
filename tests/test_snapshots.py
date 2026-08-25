"""Snapshot lifecycle contracts.

The whole point of multi-snapshot is that history accumulates without the
present changing meaning. These tests hold both halves of that: `companies`
stays latest-only, and `companies_history` spans everything.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from tm750 import snapshots


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def two_snapshots():
    """Comparison tests need history. A fresh install has one snapshot, which
    is a legitimate state -- these skip rather than fail there."""
    if len(snapshots.list_snapshots()) < 2:
        pytest.skip("needs at least two snapshots")


# ------------------------------------------------------------- filenames
@pytest.mark.parametrize("name,expected", [
    ("Total_Market_2026-08-20_tradingview.csv", "2026-08-20"),
    ("Total_Market_20260820_tradingview.csv", "2026-08-20"),
    ("export 2026_08_20.csv", "2026-08-20"),
    ("total-market-all-data.csv", None),
    ("Total_Market_2026-13-45_x.csv", None),   # not a real date
])
def test_date_inference_from_filename(name, expected):
    assert snapshots.infer_date(name) == expected


def test_files_are_classified_by_name_not_order():
    from tm750.add_snapshot import classify
    from pathlib import Path
    got = classify([
        Path("Yearly_Profit_Data.xlsx"),
        Path("Total_Market_2026-08-20_tradingview.csv"),
        Path("Qtr_Profit_Data.xlsx"),
        Path("total-market-all-data.csv"),
    ])
    assert set(got) == {"tradingview", "screener", "profit_q", "profit_y"}


def test_unrecognised_file_is_rejected_with_guidance():
    from tm750.add_snapshot import classify
    from tm750.snapshots import SnapshotError
    from pathlib import Path
    with pytest.raises(SnapshotError, match="Could not identify"):
        classify([Path("holiday-photos.csv")])


# ------------------------------------------------------ latest vs history
def test_companies_means_latest_only(client):
    """Every existing query says `companies` and means today. If history ever
    leaked into that table, every count in the app would silently multiply."""
    assert client.get("/health").json()["companies"] == 750


def test_history_spans_every_snapshot(client):
    """Holds at one snapshot as well as many -- the history table is the
    same shape either way, it just has fewer rows."""
    n = len(snapshots.list_snapshots())
    rows = client.get("/history/universe").json()["series"]
    assert len(rows) == n
    assert all(r["companies"] == 750 for r in rows)


def test_snapshot_dates_serialise_as_strings(client):
    """Hive partitioning types this column as DATE even though the parquet
    holds a string, and a date object cannot be JSON encoded."""
    r = client.get("/history/snapshots").json()
    for s in r["snapshots"]:
        assert isinstance(s["snapshot_date"], str)


# ------------------------------------------------------------ provenance
def test_manifest_records_where_every_source_came_from():
    """The first snapshot may predate the manifest system; every snapshot
    added through add_snapshot has one."""
    latest = snapshots.latest_snapshot()
    m = snapshots.manifest(latest)
    if not m:
        pytest.skip("snapshot predates manifests")
    assert set(m["sources"]) == {"tradingview", "screener", "profit_q",
                                 "profit_y"}
    for key, info in m["sources"].items():
        assert info["from_snapshot"], f"{key} has no provenance"
        assert "sha256" in info


def test_carried_forward_sources_point_at_an_earlier_snapshot():
    latest = snapshots.latest_snapshot()
    m = snapshots.manifest(latest)
    if not m:
        pytest.skip("snapshot predates manifests")
    for key, info in m["sources"].items():
        if info["carried_forward"]:
            assert info["from_snapshot"] < latest, key


# --------------------------------------------------------------- changes
def test_changes_join_on_isin_not_symbol(client, two_snapshots):
    """Symbols get renamed; ISINs do not. Joining on symbol would show a
    ticker change as one company leaving and another arriving."""
    r = client.get("/history/changes?metric=price&n=5").json()
    assert r["summary"]["compared"] == 750


def test_change_directions_account_for_everything(client, two_snapshots):
    s = client.get("/history/changes?metric=price&n=1").json()["summary"]
    assert s["up"] + s["down"] + s["flat"] == s["compared"]


def test_changes_rejects_non_numeric_metric(client):
    assert client.get("/history/changes?metric=sector").status_code == 422


def test_universe_changes_detects_a_stable_universe(client, two_snapshots):
    r = client.get("/history/universe-changes").json()
    assert r["stable"] is (not r["entered"] and not r["left"])


def test_screen_changes_partitions_into_entered_exited_held(client, two_snapshots):
    r = client.post("/history/screen-changes", json={
        "filters": [{"field": "roe", "op": "gte", "value": 15}]}).json()
    assert r["count_after"] == len(r["entered"]) + r["held_n"]
    assert r["count_before"] == len(r["exited"]) + r["held_n"]


# ------------------------------------------------------------- admin api
def test_admin_lists_snapshots_with_provenance(client):
    r = client.get("/admin/snapshots").json()
    assert r["n"] == len(snapshots.list_snapshots())
    assert r["latest"] == snapshots.latest_snapshot()


def test_cannot_delete_the_only_snapshot():
    """An app with no data is worse than an app with stale data."""
    from tm750.snapshots import SnapshotError
    held = snapshots.list_snapshots()
    if len(held) > 1:
        pytest.skip("more than one snapshot held")
    with pytest.raises(SnapshotError, match="only snapshot"):
        snapshots.delete_snapshot(held[0])


# ------------------------------------------------- discovery robustness
def test_backup_directories_are_not_discovered_as_snapshots(tmp_path,
                                                            monkeypatch):
    """A rebuild moves the old snapshot aside before committing the new one.
    If that backup were named with the `snapshot_date=` prefix it would match
    the discovery glob, be counted as a real day, and could be selected as
    'latest' -- serving a superseded catalog to the whole app."""
    from tm750 import snapshots as sm
    curated = tmp_path / "curated"
    for name in ["snapshot_date=2026-08-20", "snapshot_date=2026-08-21",
                 ".backup_2026-08-21", "snapshot_date=not-a-date"]:
        d = curated / name
        d.mkdir(parents=True)
        (d / "companies.parquet").write_bytes(b"")
    monkeypatch.setattr(sm, "CURATED", curated)
    assert sm.list_snapshots() == ["2026-08-20", "2026-08-21"]


def test_snapshot_dates_must_be_real_dates(tmp_path, monkeypatch):
    from tm750 import snapshots as sm
    curated = tmp_path / "curated"
    for name in ["snapshot_date=2026-13-99", "snapshot_date=2026-08-20"]:
        d = curated / name
        d.mkdir(parents=True)
        (d / "companies.parquet").write_bytes(b"")
    monkeypatch.setattr(sm, "CURATED", curated)
    assert sm.list_snapshots() == ["2026-08-20"]
