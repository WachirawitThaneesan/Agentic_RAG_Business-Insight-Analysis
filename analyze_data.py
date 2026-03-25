import json
from collections import defaultdict

with open("query_all.txt", "r", encoding="utf-8") as f:
    data = json.load(f)

# Find rows where raw_value contains unit tokens
problematic = []
for row in data.get("rows", []):
    rv = row.get("raw_value", "")
    if rv in ["(%)", "%", "(บาท)", "บาท", "(ล้านบาท)", "(พันบาท)", "(เท่า)", "(หุ้น)"]:
        problematic.append(row)

if problematic:
    print("UNIT TOKENS STILL IN DATA:")
    for p in problematic:
        print(f'  {p["row_label"]} | {p["metric_year"]} | {p["raw_value"]} | {p["unit"]}')
else:
    print("No unit tokens found in raw_value - GOOD!")

print()
print(f'Total rows: {len(data.get("rows", []))}')

# Group by row_label to see shift patterns
by_label = defaultdict(list)
for row in data.get("rows", []):
    by_label[row["row_label"]].append((row["metric_year"], row["raw_value"], row.get("unit", "")))

for label in sorted(by_label.keys()):
    entries = sorted(by_label[label])
    years_str = ", ".join(f"{y}={v}" for y, v, u in entries)
    unit = entries[0][2] if entries else ""
    print(f"{label} [{unit}]: {years_str}")
