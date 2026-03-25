"""Test the normalization fix — simulates what happens when OCR re-processes a document."""
from backend.services.table_utils import split_normalized_table_into_sections
import json

# Simulate OCR output: 6 columns (OCR missed the unit column)
# This is what Typhoon OCR produces from the PDF
table = {
    "title": "งบการเงินรวม",
    "table_name": "งบการเงินรวม",
    "headers": ["รายการ", "2567", "2566", "2565", "2564", "2563"],
    "rows": [
        # Normal rows (no unit token)
        ["สินทรัพย์รวม", "2,620,074", "2,768,296", "2,636,951", "2,499,109", "2,609,374"],
        ["กำไรสุทธิ (ส่วนที่เป็นของธนาคาร)", "29,700", "32,929", "30,713", "33,794", "23,040"],
        # Section title
        ["**อัตราส่วนทางการเงิน**", "", "", "", "", ""],
        # Rows WITH unit token in first year column
        ["ผลตอบแทนต่อสินทรัพย์ (ROA)", "(%)", "1.10", "1.22", "1.20", "0.93"],
        ["ผลตอบแทนต่อส่วนของเจ้าของ (ROE)", "(%)", "7.81", "9.28", "9.33", "8.25"],
        ["กำไรสุทธิต่อหุ้น", "(บาท)", "4.04", "4.48", "4.18", "3.13"],
        ["มูลค่าตามบัญชีต่อหุ้น", "(บาท)", "53.81", "50.50", "46.48", "39.31"],
    ],
    "csv_text": "",
}

sections = split_normalized_table_into_sections(table)

for sec in sections:
    print(f"=== Section: {sec['title']} ===")
    print(f"Headers: {sec['headers']}")
    has_unit = "หน่วย" in sec["headers"]
    for row in sec["rows"]:
        row_dict = dict(zip(sec["headers"], row))
        label = row_dict.get("รายการ", "")
        if not label.strip():
            continue
        parts = [f"{label}"]
        if has_unit:
            parts.append(f"  unit={row_dict.get('หน่วย', '')}")
        for y in ["2567", "2566", "2565", "2564", "2563"]:
            if y in row_dict:
                parts.append(f"  {y}={row_dict[y]}")
        print(" | ".join(parts))
    print()
