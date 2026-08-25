# tm750 — Nifty Total Market data layer

Canonical dataset for 750 NSE companies, built from four sources joined on ISIN.

## Build
```
python -m tm750.build     # raw -> curated Parquet + DuckDB + catalog
python -m pytest tests/   # 19 invariant tests
```

## Outputs (`data/curated/snapshot_date=YYYY-MM-DD/`)
| File | Contents |
|---|---|
| `companies.parquet` | 750 x 462 wide table |
| `profit_quarterly.parquet` | 181k rows, long format, 48 quarters |
| `profit_annual.parquet` | 61k rows, long format, 15 FY |
| `catalog.json` / `.csv` | Column registry — the keystone |
| `quality_report.json` | Coverage, conflicts, masking, history depth |
| `dropped_columns.csv` | Every removal with its reason |
| `../tm750.duckdb` | All four tables, queryable |

## Key decisions
- **Zeros in profit files are missing-data sentinels**, not zero profit. Converted to null. Negatives preserved (losses are real).
- **ROCE stored twice** (`roce`, `roce_screener`) — 15.4% median divergence is a formula difference, not noise.
- **Revenue and P/B are reconstructed** from per-share values; validated at 0.93% and 4.25% median error against reported subsets.
- **Finance sector metrics masked** — ROCE/ROIC/EV-EBITDA/current ratio are meaningless for 130 banks and NBFCs.
- **CAGR is null across sign changes** — no compound rate exists from a loss to a profit.
- **Low-coverage columns kept but non-screenable** — visible on the company card, barred from rankings.

## Adding a new snapshot
Drop the new CSV in `data/raw/`, update `SNAPSHOT_DATE` in `config.py`, rerun. Parquet partitions by date; DuckDB picks up all partitions.


---

# API (Task 6, backend)

```
uvicorn api.main:app --reload --port 8000
open http://localhost:8000/docs
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + row/column counts |
| `GET /meta/catalog` | 461 column specs — frontend bootstraps from this |
| `GET /meta/segments` | Columns grouped into 17 segments |
| `GET /meta/enums` | Distinct categoricals + 100 index flags for dropdowns |
| `GET /meta/quality` | Coverage, source conflicts, masking impact |
| `GET /meta/snapshots` | Available dates |
| `POST /screen` | Filter DSL → filtered, sorted, paginated rows |
| `GET /search?q=` | Type-ahead over symbol and name |
| `GET /companies/{symbol}` | Full card, grouped by segment, with percentile ranks |
| `GET /companies/{symbol}/history?freq=Q\|FY` | PAT series for charting |
| `POST /compare` | 2–6 companies, best-in-row resolved server-side |
| `GET /explore/{sector\|industry\|tier}` | Median metrics by group |
| `GET /explore/factors/overlap` | Factor-index intersection matrix |
| `GET /pulse` | Market breadth and headline stats |
| `GET /movers?field=&n=&tier=` | Top/bottom N on any numeric metric |

## Design guarantees
- **Injection-proof.** Every field is whitelist-checked against the catalog by Pydantic; every value is bound as a parameter. Unknown field → 422, never a query.
- **Sector masking at the API boundary**, not the UI. Finance rows return ROCE/ROIC/EV-EBITDA as null plus a `_masked_fields` list, so no consumer can accidentally rank banks on them.
- **Polarity from the catalog.** Compare's best-in-row needs no frontend knowledge of which metrics are good high vs good low.
- **Multi-snapshot ready.** Schema and endpoints already support it; the UI shows one.

Tests: `python -m pytest tests/` — 45 passing (19 data-layer invariants, 26 API contract).
