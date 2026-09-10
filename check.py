import duckdb
import pandas as pd
from tm750 import history
from tm750.scanner import universe

# ---- EDIT THESE TWO PATHS ----
EXCEL = r"D:\Desktop\StockTrackerApp\ATH_Results.xlsx"
FEED_DB = r"C:\Users\ASUS\Desktop\Profit API\Database Workflow\Profit API\financial_data.duckdb"
# ------------------------------

print("=" * 60)
print("1. history.summarise_quarterly output columns")
print("=" * 60)
row = {"isin": "INE000A01001"}
for i in range(1, 49):
    row[f"QL{i}"] = 0.0
for i, v in enumerate([100.0, 90.0, 80.0, 70.0], start=1):
    row[f"QL{i}"] = v

out = history.summarise_quarterly(pd.DataFrame([row]))
print(sorted(out.columns.tolist()))
print()
print(out[["isin", "qtrs_available", "pat_ttm", "pat_ttm_at_ath",
           "pat_q_at_ath"]].to_dict("records"))

print()
print("=" * 60)
print("2. Universe resolution against the real feed")
print("=" * 60)
df = pd.read_excel(EXCEL)
rows = universe.parse(df, source_file="ATH_Results.xlsx")

feed = duckdb.connect(FEED_DB, read_only=True) \
             .execute("SELECT * FROM yearly").fetchdf()
resolved = universe.resolve(rows, feed)

unres = [r["symbol"] for r in resolved if r["resolution"] == "unresolved"]
dead = [r["symbol"] for r in resolved if r["ignored"]]

print(f"universe      : {len(resolved)}")
print(f"resolved      : {len(resolved) - len(unres)}")
print(f"unresolved    : {len(unres)}")
print(f"auto-ignored  : {len(dead)}")
print()
print("unresolved symbols:", unres)