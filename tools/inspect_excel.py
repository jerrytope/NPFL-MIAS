import pandas as pd
import json
import sys

path = r"plans/NPFL ALL-TIME DATABASE.xlsx"
try:
    df = pd.read_excel(path, sheet_name=0)
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)

cols = list(df.columns)
sample = df.head(10).fillna("").to_dict(orient='records')
output = {"columns": cols, "sample": sample, "rows": len(df)}
print(json.dumps(output, ensure_ascii=False))
