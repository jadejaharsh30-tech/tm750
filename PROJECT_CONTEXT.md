# PROJECT CONTEXT & RULES — tm750

## Core Goal

Building **tm750**: a general-purpose analytics platform covering the Nifty
Total Market 750 companies. NOT tied to any single trading strategy — a
broad research/screening tool. Owner is Harshraj, a quant research analyst,
working on Windows.

Stack: **FastAPI + DuckDB** backend, **React + Vite** frontend, plain CSS
(no Tailwind/component library). Four raw exports (TradingView CSV,
Screener.in CSV, quarterly + yearly profit Excel workbooks) are ingested
into one canonical dataset — currently **470 columns × 750 companies** —
and served through 9 frontend modules.

The platform is **multi-snapshot**: each day's upload adds a new dated
snapshot rather than overwriting, so the app can show history, trends, and
what changed between any two dates, not just today's numbers.

---

## Architecture

```
tm750/            Data layer: ingest, clean, derive, catalog, snapshots
  config.py         Column segment rules, GROUP_RULES (sub-taxonomy), constants
  catalog.py        Builds the column registry (label/unit/fmt/polarity/group)
  descriptions.py   One-line tooltip text per column (curated + generated)
  ingest.py         Reads the 4 raw sources, validates structure
  derive.py         Reconstructed/computed fields (revenue, P/B, momentum...)
  history.py        Profit history reshaping, ATH/trajectory metrics
  snapshots.py       Snapshot lifecycle: discovery, archiving, manifests
  add_snapshot.py    Orchestrator: atomic commit, carry-forward, CLI
  build.py           Full pipeline orchestrator + DuckDB writer

api/               FastAPI app
  db.py              Thread-local DuckDB connections, snapshot retargeting
  models.py          Filter DSL (Pydantic) + safe SQL compiler
  deps.py            `as_of` dependency — lets any endpoint view a past date
  routers/           meta, data, explore, history, admin

web/src/           React frontend
  api/client.js      Single fetch wrapper, retry, request dedup, as-of state
  lib/               catalog.jsx (provider), format.js (Indian number fmt)
  components/        ui.jsx, ErrorBoundary, RangeBars, DatapointSearch, Info
  modules/           Pulse, Grid, Company, Screener, Compare, Explorer,
                     Segment, Quality, Upload (+ modules/pulse/* sub-panels)

tests/             158 passing, 4 skip until a 2nd real snapshot exists
```

---

## Non-negotiable conventions

1. **ISIN is the join key**, never symbol. Tickers get renamed; ISIN doesn't.
2. `companies` table = **latest snapshot only**. `companies_history` = every
   snapshot. Never conflate them — this distinction is load-bearing
   throughout the API.
3. **Catalog-driven UI.** A column's label, unit, format, polarity,
   sub-group, and description all live in `tm750/catalog.py` +
   `descriptions.py` + `config.py` (`GROUP_RULES`). The frontend never
   hardcodes a column's meaning — it reads the catalog. Add a field there
   and it appears correctly everywhere (grid, screener, company page) with
   no frontend change.
4. **Sector masking** (ROCE/ROIC/leverage ratios meaningless for the 130
   financial companies) is applied **at the API**, not the UI — so no
   consumer can accidentally rank banks on inventory turnover.
5. **DuckDB connections are thread-local** (`api/db.py`). DuckDB connections
   are NOT thread-safe; sharing one across FastAPI's threadpool silently
   returns rows to the wrong caller. Never revert to a single shared
   connection.
6. **Snapshot commits are atomic**: build to staging → validate row count
   == 750 → move into place. A failed upload must never leave a
   half-written snapshot.
7. **After any data-layer schema change**, run:
   `python -m tm750.add_snapshot --rebuild-all`
   Older snapshots keep the catalog they were built with, and the
   `catalog` table follows the *latest* snapshot — so one stale day
   silently serves an outdated schema app-wide. This has caused real bugs.
8. **Windows / Device Guard**: always `python -m uvicorn api.main:app
   --reload --port 8000`, never bare `uvicorn.exe` — the generated
   executable is unsigned and gets blocked on managed machines.
9. **Numbers**: Indian digit grouping (₹4,51,712 Cr), crore units,
   tabular-nums CSS wherever figures appear.

---

## How Claude should work on this project

- **Verify claims by running them.** Backend behavior gets checked with a
  live TestClient against real data, not asserted from reading code. This
  has caught real bugs (thread-safety races, date serialization, stale
  schema shadowing, a backup-directory naming collision).
- **No zip unless asked, or a genuine multi-file build stage just
  finished.** For small fixes, give targeted edits/snippets to paste in.
  Don't burn a full repackage on a one-line question.
- **When something doesn't check out, say so plainly and correct course** —
  don't quietly patch over a wrong earlier claim.
- **Pick sensible defaults and proceed** rather than over-asking when the
  choice is clear; state the assumption and move.
- **Concrete over vague**: "146 of 750" not "a fair number." Tables for
  comparisons. Match the density of prior responses in this project.

---

## Current state — DONE

- Data layer: 4 raw sources → 470-column canonical dataset, 750 companies
- Backend: FastAPI + DuckDB, ~21 endpoints, filter DSL, injection-safe
- Frontend, all 9 modules built and verified:
  **Pulse** (6 tabs: Breadth, Earnings, Divergence, Valuation, Ownership,
  Factors — soon a 7th, "What changed"), **Grid** (6 named views + full
  column picker), **Company** (6 tabs, grouped datapoints, range bars,
  Ctrl/Cmd+K search), **Screener** (visual filter builder, presets,
  shareable URLs), **Compare**, **Explorer**, **Segment**
  (sector/industry/tier drill-down), **Data Quality**, **Upload**
- Static → dynamic: multi-snapshot upload, atomic commits, carry-forward
  for quarterly-only sources (profit workbooks), full provenance tracking
- History surfaced in UI: snapshot picker, Pulse "What changed" tab,
  company trend chart across snapshots, screener entered/exited tracking
- Sector / Industry / Cap tier pages (Segment module)
- Education layer: 468/470 columns have a one-line description (216
  hand-curated where the definition carries a real choice, 252
  pattern-generated where the name fully determines meaning); `i` tooltips
  throughout, portaled to avoid ancestor-overflow clipping
- Company page reorganized: catalog-driven concept groups (was flat tiles),
  hide-empty toggle, tiles/table density switch, all groups closed by
  default

## Current state — IN PROGRESS

**Task 3: price layer from yfinance OHLCV.**

User shared a first-draft SQLite DB (`market_data_yfinance.db`) plus fetch
scripts (`yahoo_bulk.py`, `daily_update.py`) as **reference material only**
— explicitly told not to build on it directly. The real files are coming
separately.

Findings from analyzing that first draft (informs the real build, don't
repeat the investigation):

- Symbol matching to the 750 works well once `_` vs `-` is normalized
  (747/750 matched; 3 genuinely missing — GRINDWELL, RATNAMANI, SANOFICONR).
- **Critical bug found and confirmed**: the script fetches with
  `auto_adjust=False` and stores only `Close`, never `Adj Close`. That
  means prices are permanently **unadjusted for splits**. A "resync" does
  **not** fix this — raw `Close` is correctly raw at every pull, there's
  nothing stale to refresh. Proven concretely: TRENT did a genuine 3-for-2
  split on 2026-01-01 (close dropped ₹4,279 → ₹2,865, almost exactly 2/3);
  the raw 5-year high of ₹8,235 is 50% above TradingView's split-adjusted
  ₹5,563. ~18–21 of 750 tickers affected this way.
- **Whatever real data arrives, split-adjustment must be handled
  explicitly** before any price-derived field is trusted — either by
  capturing `Adj Close`, fetching split events and back-adjusting, or
  detecting large clean-ratio single-day discontinuities and rescaling.
- Rough scope (from the catalog, not yet executed): **94 of 470 columns**
  are purely OHLCV-derivable (returns, highs/lows, moving averages,
  momentum, oscillators, volatility, beta — essentially the whole Trend +
  Technicals segment). ~18 columns need fundamentals alongside price
  (P/E, market cap, EV) and stay sourced as-is. 3 rating columns
  (`technical_rating`, `ma_rating`, `analyst_rating`) are TradingView-
  proprietary and not reproducible. All Screener.in price fields
  (`price_screener`, `*_52w_*_screener`) get dropped once yfinance
  replaces them, per explicit instruction.
- **A reconciliation gate is planned**: any recomputed field must be
  checked against TradingView's own value across all 750 before it's
  trusted or switched over — median error should be ~0%, and systematic
  divergence is a bug signal, not noise.

## Not started

- Price layer implementation (blocked on the user sharing final yfinance
  data — currently being gathered)
- **ATH Scanner** — named as the next task after the price layer lands, no
  spec yet
- Remaining UI polish (a few known minor items the user said aren't urgent)
- Infographic series (70:30 technical:fundamental ratio agreed early on,
  ~40 ideas catalogued) — parked indefinitely

---

## Known traps (do not rediscover these)

- **DuckDB connections shared across threads** silently cross-deliver rows
  between concurrent requests. Fixed via thread-local `.cursor()` per
  worker thread in `api/db.py`.
- **`overflow: hidden` on an ancestor silently clips absolutely-positioned
  tooltips/dropdowns** — the trigger highlights on hover but the popover
  never appears. Fixed for the `Info` tooltip via React portal to
  `document.body` with `position: fixed`, measured from the trigger's own
  bounding box.
- **A snapshot rebuild's backup directory must never match the
  `snapshot_date=*` discovery glob** — it was briefly named
  `snapshot_date=X.prev` and got counted as a real snapshot, corrupting
  which one was "latest." Renamed to `.backup_{date}`; discovery now also
  validates the suffix is a real ISO date.
- **The `catalog` DuckDB table tracks the latest snapshot, not the
  package's current schema.** Change `catalog.py`/`descriptions.py`, and
  older snapshots — plus any snapshot rebuilt before the change — will
  serve a stale catalog once they become "latest" again. Always
  `--rebuild-all` after a schema change.
- **`yfinance` with `auto_adjust=False` returns genuinely raw, permanently
  unadjusted prices** — not "stale until refreshed." Only `Adj Close`
  carries the split/dividend adjustment, and it must be explicitly
  captured, not assumed to come along for free.
