import pandas as pd
from tm750 import history

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