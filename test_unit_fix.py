"""Verify the unit-token year-shift fix in duckdb_warehouse."""
from backend.services.duckdb_warehouse import _load_year_based_table, _get_conn, _extract_unit_token
import json

# Simulate: headers [label, 2567, 2566, 2565, 2564, 2563]
# Row with (%): ["ROA", "(%)", "1.10", "1.22", "1.20", "1.32"]
# Row without:  ["assets", "2620074", "2708296", "2636951", "2499109", "2609374"]

headers = ["label", "2567", "2566", "2565", "2564", "2563"]
rows = [
    ["assets", "2620074", "2708296", "2636951", "2499109", "2609374"],
    ["ROA", "(%)", "1.10", "1.22", "1.20", "1.32"],
    ["EPS", "(บาท)", "4.04", "4.48", "4.18", "4.59"],
    ["ROE", "(%)", "7.81", "9.28", "9.33", "11.17"],
]

year_cols = [(1, "2567"), (2, "2566"), (3, "2565"), (4, "2564"), (5, "2563")]

conn = _get_conn()

# Clean up any test data first
conn.execute("DELETE FROM fact_financial_metrics WHERE document_id = 99999")

# Load the test data
count = _load_year_based_table(
    conn, 99999, "test_verify", headers, rows,
    label_col=0, year_cols=year_cols, unit_col=None
)

# Query back
result = conn.execute(
    "SELECT row_label, metric_year, raw_value, unit FROM fact_financial_metrics "
    "WHERE document_id = 99999 ORDER BY row_label, metric_year"
).fetchall()

print(f"Records inserted: {count}")
print(f"{'ROW_LABEL':<20} {'YEAR':<8} {'VALUE':<12} {'UNIT'}")
print("-" * 60)

errors = []
for row_label, year, value, unit in result:
    print(f"{row_label:<20} {year:<8} {value:<12} {unit}")
    # Check that (%) never appears as a raw_value
    if _extract_unit_token(value):
        errors.append(f"ERROR: Unit token '{value}' stored as data for {row_label} {year}")

# Expected mappings for ROA row: 
# 2567=1.10, 2566=1.22, 2565=1.20, 2564=1.32 (shifted from original positions)
expected = {
    ("ROA", "2567"): "1.10",
    ("ROA", "2566"): "1.22",
    ("ROA", "2565"): "1.20",
    ("ROA", "2564"): "1.32",
    ("assets", "2567"): "2620074",
    ("assets", "2566"): "2708296",
    ("assets", "2565"): "2636951",
    ("assets", "2564"): "2499109",
    ("assets", "2563"): "2609374",
}

result_dict = {(r[0], r[1]): r[2] for r in result}
for key, exp_val in expected.items():
    actual = result_dict.get(key, "MISSING")
    if actual != exp_val:
        errors.append(f"MISMATCH: {key} expected '{exp_val}' got '{actual}'")

# Cleanup
conn.execute("DELETE FROM fact_financial_metrics WHERE document_id = 99999")

print()
if errors:
    for e in errors:
        print(e)
    print("FAILED!")
else:
    print("ALL CHECKS PASSED!")
