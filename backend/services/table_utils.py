"""Helpers for normalizing OCR tables into CSV- and SQL-friendly structures."""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List


def _strip_markdown(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"[*_`#]+", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _normalize_headers(headers: List[str], column_count: int) -> List[str]:
    normalized: List[str] = []
    seen: Dict[str, int] = {}

    for index in range(column_count):
        raw = headers[index] if index < len(headers) else ""
        header = _strip_markdown(raw)

        if not header:
            header = "รายการ" if index == 0 else f"column_{index + 1}"

        count = seen.get(header, 0)
        seen[header] = count + 1
        if count:
            header = f"{header}_{count + 1}"

        normalized.append(header)

    return normalized


def _is_year_header(header: str) -> bool:
    return bool(re.fullmatch(r"(?:25|20)\d{2}", str(header or "").strip()))


def _is_unit_token(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.fullmatch(r"\([^)]{1,15}\)", text):
        return True
    return text in {"%", "บาท", "ล้านบาท"}


def _is_section_title_row(row: Dict[str, Any], label_header: str, value_headers: List[str]) -> bool:
    label = str(row.get(label_header, "")).strip()
    if not label:
        return False
    return not any(str(row.get(header, "")).strip() for header in value_headers)


def _looks_numeric(value: str) -> bool:
    text = str(value or "").strip().replace(",", "")
    return bool(text and re.fullmatch(r"-?\d+(?:\.\d+)?", text))


def _is_descriptor_header(header: str, index: int) -> bool:
    text = str(header or "").strip().lower()
    if not text:
        return False
    if _is_year_header(text) or text.startswith("column_"):
        return False
    if index == 0:
        return True

    descriptor_tokens = (
        "ลำดับ",
        "รายชื่อ",
        "ชื่อ",
        "บริษัท",
        "หน่วย",
        "หมายเหตุ",
    )
    return any(token in text for token in descriptor_tokens)


def _leading_descriptor_column_count(headers: List[str]) -> int:
    if not headers:
        return 0

    count = 1
    for index, header in enumerate(headers[1:], start=1):
        if _is_descriptor_header(header, index):
            count += 1
            continue
        break
    return count


def _collapse_sparse_footer_rows(
    section_rows: List[Dict[str, Any]],
    headers: List[str],
) -> tuple[List[str], List[Dict[str, Any]]]:
    """Merge OCR-broken footer totals that were split into one value per row.

    Some rotated tables come back with a proper body, followed by a suffix of rows
    where only the last placeholder column is populated, one numeric value at a time.
    Those rows are usually fragments of a single footer/total row, so we right-align
    them back into one row.
    """
    if len(section_rows) < 3 or not headers:
        return headers, section_rows

    last_header = headers[-1]
    trailing_rows: List[Dict[str, Any]] = []

    for row in reversed(section_rows):
        non_empty = [(header, str(row.get(header, "")).strip()) for header in headers if str(row.get(header, "")).strip()]
        if len(non_empty) != 1:
            break

        header, value = non_empty[0]
        if header != last_header or not _looks_numeric(value):
            break

        trailing_rows.append(row)

    trailing_rows.reverse()
    if len(trailing_rows) < 3:
        return headers, section_rows

    values = [str(row.get(last_header, "")).strip() for row in trailing_rows]
    descriptor_count = _leading_descriptor_column_count(headers)
    effective_headers = list(headers)
    while len(values) > len(effective_headers) - descriptor_count:
        effective_headers.append(f"column_{len(effective_headers) + 1}")

    start_index = descriptor_count
    if start_index < 0 or start_index + len(values) > len(effective_headers):
        return headers, section_rows

    merged_row = {header: "" for header in effective_headers}
    for offset, value in enumerate(values):
        merged_row[effective_headers[start_index + offset]] = value

    return effective_headers, section_rows[: len(section_rows) - len(trailing_rows)] + [merged_row]


def table_to_csv(headers: List[str], rows: List[List[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().strip()


def normalize_ocr_table(table: Dict[str, Any], default_name: str) -> Dict[str, Any]:
    raw_headers = table.get("headers") or []
    raw_rows = table.get("rows") or []
    title = _strip_markdown(table.get("title") or "") or default_name

    clean_rows = [[_strip_markdown(cell) for cell in row] for row in raw_rows]
    max_cols = max([len(raw_headers)] + [len(row) for row in clean_rows] + [1])
    headers = _normalize_headers([_strip_markdown(h) for h in raw_headers], max_cols)

    rows: List[List[str]] = []
    for row in clean_rows:
        padded = row[:max_cols] + [""] * max(0, max_cols - len(row))
        if any(cell.strip() for cell in padded):
            rows.append(padded)

    csv_text = table_to_csv(headers, rows) if rows else ""
    return {
        "title": title,
        "table_name": title,
        "headers": headers,
        "rows": rows,
        "csv_text": csv_text,
    }


def split_normalized_table_into_sections(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    headers = list(table.get("headers") or [])
    rows = list(table.get("rows") or [])
    if not headers or not rows:
        return []

    label_header = headers[0]
    year_headers = [header for header in headers[1:] if _is_year_header(header)]
    value_headers = headers[1:]

    row_dicts = [dict(zip(headers, row)) for row in rows]
    sections: List[Dict[str, Any]] = []
    current_title = table.get("title") or table.get("table_name") or "table"
    current_rows: List[Dict[str, Any]] = []

    def flush_section(title: str, section_rows: List[Dict[str, Any]]):
        if not section_rows:
            return

        effective_headers, section_rows = _collapse_sparse_footer_rows(section_rows, headers)

        has_unit_column = (
            bool(year_headers)
            and any(_is_unit_token(row.get(year_headers[0], "")) for row in section_rows)
            and len(effective_headers) >= len(year_headers) + 2
        )

        if has_unit_column:
            section_headers = [label_header, "หน่วย", *year_headers]
            normalized_rows = []
            for row in section_rows:
                raw_values = [row.get(header, "") for header in effective_headers]
                padded = raw_values + [""] * max(0, len(section_headers) - len(raw_values))
                normalized_rows.append(padded[:len(section_headers)])
        else:
            section_headers = [label_header, *year_headers] if year_headers else effective_headers
            normalized_rows = []
            for row in section_rows:
                normalized_rows.append([row.get(header, "") for header in section_headers])

        section_table_name = f"{table.get('table_name')}_{_strip_markdown(title)}" if title else table.get("table_name")
        sections.append(
            {
                "title": title,
                "table_name": section_table_name,
                "headers": section_headers,
                "rows": normalized_rows,
                "csv_text": table_to_csv(section_headers, normalized_rows),
            }
        )

    for row in row_dicts:
        if _is_section_title_row(row, label_header, value_headers):
            flush_section(current_title, current_rows)
            current_title = str(row.get(label_header, "")).strip() or current_title
            current_rows = []
            continue
        current_rows.append(row)

    flush_section(current_title, current_rows)
    return sections or [table]


def normalize_ocr_tables(table_prefix: str, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, table in enumerate(tables):
        normalized_table = normalize_ocr_table(table, f"{table_prefix}_table_{index}")
        normalized.extend(split_normalized_table_into_sections(normalized_table))
    return normalized


def rebuild_structured_tables(
    table_name: str,
    headers: List[str],
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    normalized_table = {
        "title": table_name,
        "table_name": table_name,
        "headers": headers,
        "rows": [[row.get(header, "") for header in headers] for row in rows],
        "csv_text": "",
    }
    return split_normalized_table_into_sections(normalized_table)


def build_table_chunk_payloads(
    table_prefix: str,
    tables: List[Dict[str, Any]],
    max_rows_per_chunk: int = 25,
) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []

    for index, table in enumerate(tables):
        headers = table["headers"]
        rows = table["rows"]
        if not headers or not rows:
            continue

        table_name = table.get("table_name") or f"{table_prefix}_table_{index}"
        title = table.get("title") or table_name

        for row_start in range(0, len(rows), max_rows_per_chunk):
            row_end = min(row_start + max_rows_per_chunk, len(rows))
            batch_rows = rows[row_start:row_end]
            csv_text = table_to_csv(headers, batch_rows)
            text = (
                f"TABLE_NAME: {table_name}\n"
                f"TABLE_TITLE: {title}\n"
                f"COLUMNS: {', '.join(headers)}\n"
                "CSV:\n"
                f"{csv_text}"
            )
            payloads.append(
                {
                    "table_name": table_name,
                    "title": title,
                    "headers": headers,
                    "row_start": row_start,
                    "row_end": row_end - 1,
                    "csv_text": csv_text,
                    "text": text,
                }
            )

    return payloads
