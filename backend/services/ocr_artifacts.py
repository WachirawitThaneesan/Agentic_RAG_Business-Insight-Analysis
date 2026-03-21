"""Helpers for persisting raw OCR artifacts alongside normalized tables."""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List


def _table_to_csv(headers: List[str], rows: List[List[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if headers:
        writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().strip()


def build_raw_ocr_chunk_payloads(
    filename: str,
    ocr_result: Dict[str, Any],
    max_pages: int | None = None,
) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []

    raw_pages = ocr_result.get("raw_pages", []) or []
    if max_pages is not None:
        raw_pages = raw_pages[:max_pages]

    for page in raw_pages:
        markdown = str(page.get("markdown") or "").strip()
        if not markdown:
            continue
        page_num = page.get("page")
        payloads.append(
            {
                "text": f"RAW_OCR_PAGE: {filename} page {page_num}\n{markdown}",
                "summary": "",
                "metadata": {
                    "source_kind": "raw_ocr_page",
                    "page": page_num,
                    "markdown": markdown,
                },
            }
        )

    raw_tables = ocr_result.get("raw_tables")
    if raw_tables is None:
        raw_tables = ocr_result.get("tables", []) or []

    for index, table in enumerate(raw_tables):
        headers = [str(header or "").strip() for header in (table.get("headers") or [])]
        rows = [[str(cell or "").strip() for cell in row] for row in (table.get("rows") or [])]
        csv_text = _table_to_csv(headers, rows)
        if not csv_text:
            continue
        title = str(table.get("title") or f"{filename}_raw_table_{index}").strip()
        page_num = table.get("page")
        payloads.append(
            {
                "text": (
                    f"RAW_OCR_TABLE: {title}\n"
                    f"RAW_PAGE: {page_num}\n"
                    f"RAW_HEADERS: {', '.join(headers)}\n"
                    f"RAW_CSV:\n{csv_text}"
                ),
                "summary": "",
                "metadata": {
                    "source_kind": "raw_ocr_table",
                    "table_index": index,
                    "page": page_num,
                    "title": title,
                    "headers": headers,
                    "rows": rows,
                    "csv_text": csv_text,
                },
            }
        )

    return payloads
