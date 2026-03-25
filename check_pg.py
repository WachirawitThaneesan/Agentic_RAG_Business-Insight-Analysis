"""Check what raw data is stored in PostgreSQL structured_data for % rows."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(".")))

import json

async def check():
    from backend.database import AsyncSessionLocal
    from backend.models import StructuredData
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(StructuredData.table_name, StructuredData.headers, StructuredData.row_data, StructuredData.row_index)
            .order_by(StructuredData.table_name, StructuredData.row_index)
        )
        rows = result.all()

        with open("pg_data_check.txt", "w", encoding="utf-8") as f:
            for table_name, headers, row_data, row_index in rows:
                if row_data and isinstance(row_data, dict):
                    values_str = json.dumps(row_data, ensure_ascii=False)
                    if "(%)" in values_str or "(บาท)" in values_str or "ROA" in values_str or "ROE" in values_str or "ต่อหุ้น" in values_str:
                        f.write(f"\n=== {table_name} row #{row_index} ===\n")
                        f.write(f"Headers ({len(headers)}): {json.dumps(headers, ensure_ascii=False)}\n")
                        f.write(f"Row data ({len(row_data)} keys): {json.dumps(row_data, ensure_ascii=False, indent=2)}\n")

asyncio.run(check())
print("Done - see pg_data_check.txt")
