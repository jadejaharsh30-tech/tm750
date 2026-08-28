"""One-command health check for the whole tm750 install.

    python verify.py

Checks environment, raw files, the built dataset and the API, and prints a
plain pass/fail line for each so a failure points at the step that broke.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PASS, FAIL, WARN = "  [PASS]", "  [FAIL]", "  [WARN]"
results: list[bool] = []


def check(label: str, ok: bool, detail: str = "", fatal: bool = False) -> bool:
    print(f"{PASS if ok else FAIL} {label}" + (f" -- {detail}" if detail else ""))
    results.append(ok)
    if fatal and not ok:
        print("\nStopping: this step must pass before the rest can run.")
        sys.exit(1)
    return ok


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * 58}")


# ------------------------------------------------------------ 1. python
section("1. ENVIRONMENT")
v = sys.version_info
check(f"Python {v.major}.{v.minor}.{v.micro}", v >= (3, 10),
      "need 3.10 or newer", fatal=True)
if v >= (3, 14):
    print(f"{WARN} Python 3.14+ -- all dependencies have cp314 wheels, but if "
          "pip tries to\n         BUILD anything from source, your pins are "
          "too loose. Rerun with:\n         pip install -r requirements.txt "
          "--only-binary=:all:")

missing = []
for mod in ("pandas", "duckdb", "pyarrow", "openpyxl", "fastapi", "uvicorn"):
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)
check("dependencies installed", not missing,
      f"missing: {', '.join(missing)}" if missing else "", fatal=True)

if v >= (3, 14):
    import duckdb as _d
    import pyarrow as _pa
    ok_d = tuple(int(x) for x in _d.__version__.split(".")[:3]) >= (1, 4, 3)
    ok_p = int(_pa.__version__.split(".")[0]) >= 25
    check("duckdb >= 1.4.3 (needed for 3.14)", ok_d, _d.__version__)
    check("pyarrow >= 25 (needed for 3.14)", ok_p, _pa.__version__)

# ------------------------------------------------------------- 2. files
section("2. RAW DATA")
from tm750.config import RAW, SOURCES  # noqa: E402

for name, fn in SOURCES.items():
    p = RAW / fn
    check(f"{name:12s} {fn}", p.exists(),
          "not found" if not p.exists() else f"{p.stat().st_size / 1024:.0f} KB")

if not all(results[-4:]):
    print("\nPut the four raw files in data/raw/ with exactly these names, "
          "then rerun.")
    sys.exit(1)

# ------------------------------------------------------------- 3. build
section("3. BUILT DATASET")
from tm750.config import CURATED  # noqa: E402

db_file = CURATED / "tm750.duckdb"
if not db_file.exists():
    print("  no database found -- building now (takes ~20s)...\n")
    from tm750.build import build
    build()
    print()

check("tm750.duckdb exists", db_file.exists(),
      "" if db_file.exists() else "run: python -m tm750.build", fatal=True)

import duckdb  # noqa: E402

con = duckdb.connect(str(db_file), read_only=True)
n = con.execute("SELECT count(*) FROM companies").fetchone()[0]
check("750 companies", n == 750, f"got {n}")

cols = len(con.execute("SELECT * FROM companies LIMIT 0").description)
check("full column set", cols > 400, f"{cols} columns")

tiers = dict(con.execute(
    "SELECT cap_tier, count(*) FROM companies GROUP BY 1").fetchall())
check("cap tiers 100/150/250/250",
      tiers == {"Large": 100, "Mid": 150, "Small": 250, "Micro": 250},
      str(tiers))

cat = con.execute("SELECT count(*) FROM catalog").fetchone()[0]
check("catalog populated", cat == cols, f"{cat} specs for {cols} columns")

q = con.execute("SELECT count(*) FROM profit_quarterly").fetchone()[0]
y = con.execute("SELECT count(*) FROM profit_annual").fetchone()[0]
check("profit history loaded", q > 100_000 and y > 40_000,
      f"{q:,} quarterly / {y:,} annual rows")

zeros = con.execute(
    "SELECT count(*) FROM companies WHERE pat_latest_q = 0").fetchone()[0]
losses = con.execute(
    "SELECT count(*) FROM companies WHERE pat_latest_q < 0").fetchone()[0]
check("profit sentinels handled", zeros == 0 and losses > 0,
      f"{zeros} zeros, {losses} genuine losses preserved")
con.close()

# --------------------------------------------------------------- 4. api
section("4. API")
try:
    from fastapi.testclient import TestClient

    from api.main import app
    c = TestClient(app)

    h = c.get("/health").json()
    check("GET /health", h["status"] == "ok", f"{h['companies']} companies")

    cat = c.get("/meta/catalog").json()
    check("GET /meta/catalog", cat["n"] > 400, f"{cat['n']} columns")

    s = c.post("/screen", json={
        "filters": [{"field": "cap_tier", "op": "eq", "value": "Large"}],
        "limit": 5}).json()
    check("POST /screen", s["total"] == 100, f"{s['total']} large caps")

    bad = c.post("/screen", json={"filters": [
        {"field": "pe_ratio; DROP TABLE companies", "op": "gt", "value": 1}]})
    still = c.get("/health").json()["companies"]
    check("injection rejected", bad.status_code == 422 and still == 750,
          f"status {bad.status_code}, table intact")

    bank = c.get("/companies/HDFCBANK").json()
    check("finance masking", "roce" in bank["masked_fields"],
          f"{len(bank['masked_fields'])} fields masked")

    p = c.get("/pulse").json()
    check("GET /pulse", 0 <= p["breadth"]["pct_above_ema200"] <= 100,
          f"{p['breadth']['pct_above_ema200']}% above EMA200")

    cm = c.post("/compare", json={"symbols": ["TCS", "INFY", "WIPRO"],
                                  "segments": ["Valuation"]}).json()
    pe = next(m for m in cm["metrics"]["Valuation"] if m["name"] == "pe_ratio")
    check("POST /compare", pe["best_index"] is not None,
          f"best P/E: {cm['symbols'][pe['best_index']]}")

except Exception as exc:  # noqa: BLE001
    check("API import/run", False, f"{type(exc).__name__}: {exc}")

# ------------------------------------------------------------ summary
section("SUMMARY")
ok, total = sum(results), len(results)
print(f"  {ok}/{total} checks passed")
if ok == total:
    print("\n  Everything works. Start the server with:")
    print("    uvicorn api.main:app --reload --port 8000")
    print("  then open http://localhost:8000/docs")
else:
    print("\n  Fix the [FAIL] lines above, then rerun: python verify.py")
sys.exit(0 if ok == total else 1)
