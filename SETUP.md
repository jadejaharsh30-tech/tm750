# Setup — run this from a clean machine

## 0. Python version

**3.12 or 3.13 is the safest choice.** 3.14 works — every dependency now ships
cp314 wheels — but if pip resolves to an older release it will try to compile
DuckDB or pyarrow from source and fail with confusing C++ errors. The version
floors in `requirements.txt` prevent that. If you are on 3.14 and pip starts
"Building wheel for duckdb", stop it and run:

```
pip install -r requirements.txt --only-binary=:all:
```

That forces pip to use prebuilt wheels only, so a resolution problem fails
fast and legibly instead of grinding through a doomed compile.

## 1. Install Python 3.10+
Windows: python.org → **tick "Add Python to PATH"** during install.
Mac: `brew install python@3.12` (or python.org installer).
Check: `python --version` (Windows) / `python3 --version` (Mac/Linux).

## 2. Unzip and enter the folder
```
cd tm750
```
You should see: `tm750/  api/  tests/  data/  verify.py  requirements.txt`

## 3. Virtual environment (recommended, avoids polluting system Python)
```
# Windows
python -m venv .venv
.venv\Scripts\activate

# Mac / Linux
python3 -m venv .venv
source .venv/bin/activate
```
Your prompt should now start with `(.venv)`.

## 4. Install dependencies
```
pip install -r requirements.txt
```
Takes 1–2 minutes.

## 5. Verify everything
```
python verify.py
```
Builds the dataset on first run (~20s), then runs 20 checks.
Expect: `20/20 checks passed`.

## 6. Run the test suite
```
python -m pytest tests/ -q
```
Expect: `45 passed`.

## 7. Start the API
```
uvicorn api.main:app --reload --port 8000
```
Open **http://localhost:8000/docs** — interactive Swagger UI, every endpoint
runnable from the browser via "Try it out".

Leave this terminal running. Ctrl+C to stop.

---

## Things worth trying in /docs

**GET /pulse** — market breadth and headline stats. No parameters.

**GET /companies/{symbol}** — try `TCS`, then `HDFCBANK` and look at
`masked_fields` (banks get ROCE/ROIC nulled).

**POST /screen** — paste this into the request body:
```json
{"filters": [{"field": "cap_tier", "op": "in", "value": ["Small","Micro"]},
             {"field": "pe_ratio", "op": "between", "value": [5, 25]},
             {"field": "ema_stack_bullish", "op": "eq", "value": true},
             {"field": "roe", "op": "gte", "value": 15}],
 "sort": [{"field": "momentum_12_1_pct", "dir": "desc"}],
 "columns": ["symbol","name","cap_tier","pe_ratio","roe","perf_1y_pct","momentum_12_1_pct"],
 "limit": 10}
```
Should return 9 companies out of 750.

**Try breaking it** — change the first field to
`"cap_tier; DROP TABLE companies"`. You should get a 422, and `/health` should
still report 750 companies afterwards.

**GET /explore/tier** — median metrics by cap tier.

**GET /explore/factors/overlap** — how much the Nifty factor indices intersect.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'python' is not recognized` | Python not on PATH. Reinstall with the PATH box ticked, or use `py` instead on Windows. |
| `No module named tm750` | You're in the wrong folder. `cd` into the one containing `verify.py`. |
| `execution of scripts is disabled` (Windows venv) | Run PowerShell as admin: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use Command Prompt instead of PowerShell. |
| `Port 8000 is in use` | `uvicorn api.main:app --reload --port 8001` |
| pip starts "Building wheel for duckdb/pyarrow" | You're on a Python version without prebuilt wheels for the resolved release. `pip install -r requirements.txt --only-binary=:all:` |
| verify.py fails at RAW DATA | The four files must be in `data/raw/` with the exact names listed in the error. |
| Want to rebuild from scratch | Delete `data/curated/`, run `python verify.py` again. |


---

# Frontend

Needs **two terminals**: the API in one, the web app in the other.

## Terminal 1 — API
```
python -m uvicorn api.main:app --reload --port 8000
```
Use `python -m uvicorn`, not `uvicorn` directly — on managed Windows machines
the generated `uvicorn.exe` is unsigned and gets blocked by Device Guard.

## Terminal 2 — web app
```
cd web
npm install        # first time only, ~1 min
npm run dev
```
Open **http://localhost:5173**

Vite proxies `/api` to port 8000, so the browser stays on one origin and CORS
never comes up. If the API is not running, the app says so and tells you the
command to start it.

Requires **Node 18+** (`node --version`). Get it from nodejs.org if missing.

## If pages load intermittently

They shouldn't any more. If they ever do again, the first thing to check is
whether the uvicorn terminal shows a traceback — that is the real error; the
browser only ever sees the symptom.

## Daily update

The app is now multi-snapshot: each upload adds a day, nothing is overwritten.

**From the app:** open the **Upload** tab, drop the day's files, check the
preview, commit. Any subset is valid — missing sources carry forward from the
last snapshot that had them, so a normal daily upload is just the TradingView
export.

**From the terminal:**
```
python -m tm750.add_snapshot path/to/Total_Market_2026-08-21_tradingview.csv
python -m tm750.add_snapshot --list
python -m tm750.add_snapshot --delete 2026-08-21
```

```
python -m tm750.add_snapshot --rebuild-all
```
**Run `--rebuild-all` after any change to the data layer.** Older snapshots
keep the catalog they were built with, and the `catalog` table follows the
latest snapshot — so one stale day silently serves an outdated schema to the
whole app. This rebuilds every held snapshot from its own archived raw files.

The snapshot date comes from the TradingView filename; override with `--date`.
Both paths share one pipeline. Commits are atomic — a build that fails
validation leaves every existing snapshot untouched.

## What's built so far

| Module | Status |
|---|---|
| Pulse | Built — six tabs: Breadth, Earnings, Divergence, Valuation, Ownership, Factors |
| Grid | Built — six named views, tier filter, density toggle, full column picker |
| Company | Built — six tabs, metric tiles, profit history, percentile ranks |
| Screener | Built — visual filter builder over all 444 screenable columns, five presets, shareable URLs |
| Compare | Built — 2-6 companies, ranked by biggest difference, best-in-row from catalog polarity |
| Explorer | Built — any metric by sector, industry or cap tier |
| Data quality | Built — what was dropped, reconstructed, disputed between sources, and masked |
| Sectors | Built — drill into any sector, industry or cap tier; ranks are within-group |
| Upload | Built — drag files, preview, commit; snapshot history and provenance |

Once two or more snapshots are held, these appear:
- **Snapshot picker** in the nav — view the whole app as of any past date
- **Pulse → What changed** — movers, entries and exits between snapshots
- **Company → trend chart** across snapshots
- **Screener** — what newly matches, and what dropped out

## Notes
- Theme toggle is top-right; the choice persists.
- Click any grid row, mover, or search result to open that company.
- Grid opens on **named views** — Momentum, Trend, Value, Quality, Growth,
  Ownership — each answering a question rather than listing fields. The
  **Columns** button still opens the full 462-column picker when you need it.
- **Compact / Roomy** toggles row height. Tier buttons filter to one cap tier.
- Click any grid column header to sort; click again to reverse.
- **Screener**: presets across the top, or **+ Filter** to search all 444
  screenable fields. Operators offered match the field's type. The URL updates
  as you build, so a screen is a link you can send someone.
- **Pulse** tabs load on first open, so landing on the page costs two requests
  rather than eight.
- **Compare** opens seeded with whichever company you were last viewing.
  Default view ranks metrics by how far apart the companies actually are.
- **Explorer** ranks sector / industry / cap tier on any of 20 metrics.
- **Data quality** documents the 72 dropped columns, the two reconstructed
  fields and their measured error, the four source disagreements, and the
  nine metrics masked for financial companies.
- **Company page**: six tabs, each split into concept groups. **Ctrl/Cmd+K**
  searches all 301 datapoints and jumps to one. Toggle **Hide empty** and
  **tiles/table**. Range bars for 52-week and all-time sit on Snapshot.
- Small **i** markers give a one-line definition, read from the catalog so a
  label means the same thing everywhere it appears.
- Hairlines under numbers are **percentile ranks** — where that value sits in
  the universe. On the company card they show universe and sector side by side.
