"""Helpers for normalizing OCR tables into CSV- and SQL-friendly structures."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Any, Dict, List, Optional


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


def safe_table_name(value: str, fallback: str, max_len: int = 240) -> str:
    raw = _strip_markdown(value) or _strip_markdown(fallback) or "table"
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^\w\u0E00-\u0E7F\-\.\(\)]", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if len(raw) <= max_len:
        return raw or "table"

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    keep = max_len - len(digest) - 1
    return f"{raw[:keep].rstrip('_')}_{digest}"


def _infer_financial_investment_headers(
    raw_headers: List[str],
    rows: List[List[str]],
    max_cols: int,
) -> tuple[Optional[List[str]], List[List[str]]]:
    """Handle multi-row headers for the bank-investment table."""
    if max_cols != 5 or len(raw_headers) != 1 or not rows:
        return None, rows

    header_blob = _strip_markdown(raw_headers[0] or "")
    first_row = [_strip_markdown(cell) for cell in rows[0]]

    if not (
        "ชื่อบริษัท" in header_blob
        and "ประเภทธุรกิจ" in header_blob
        and "ธนาคาร" in header_blob
        and "ถือหุ้น" in header_blob
    ):
        return None, rows

    if not any("ชนิดหุ้น" in cell for cell in first_row) or not any("จำนวนหุ้น" in cell for cell in first_row):
        return None, rows

    headers = [
        "ชื่อบริษัท",
        "ประเภทธุรกิจ",
        "ชนิดหุ้น",
        "จำนวนหุ้น",
        "ธนาคารถือหุ้น (%)",
    ]
    return headers, rows[1:]


def _normalize_repeated_title(text: str) -> str:
    value = _strip_markdown(text or "")
    if not value:
        return ""

    half = len(value) // 2
    if len(value) % 2 == 0 and value[:half] == value[half:]:
        return value[:half]

    for separator in ("_", "-", " "):
        parts = [part.strip() for part in value.split(separator, 1)]
        if len(parts) == 2 and parts[0] and parts[0] == parts[1]:
            return parts[0]

    return value


def _repair_stored_financial_investment_table(
    table_name: str,
    headers: List[str],
    rows: List[List[str]],
) -> tuple[str, List[str], List[List[str]]]:
    normalized_title = _normalize_repeated_title(table_name)
    header_blob = _strip_markdown(headers[0] if headers else "")

    if not (
        "การลงทุนของธนาคารในบริษัทอื่น" in normalized_title
        or (
            "ชื่อบริษัท" in header_blob
            and "ประเภทธุรกิจ" in header_blob
            and "ถือหุ้น" in header_blob
        )
    ):
        return normalized_title or table_name, headers, rows

    if not rows:
        return normalized_title or table_name, headers, rows

    first_row = [_strip_markdown(cell) for cell in rows[0]]
    if not any("จำนวนหุ้น" in cell for cell in first_row):
        return normalized_title or table_name, headers, rows

    repaired_headers = [
        "ชื่อบริษัท",
        "ประเภทธุรกิจ",
        "ชนิดหุ้น",
        "จำนวนหุ้น",
        "ธนาคารถือหุ้น (%)",
    ]
    repaired_rows = [row[:5] + [""] * max(0, 5 - len(row)) for row in rows[1:]]
    return normalized_title or "การลงทุนของธนาคารในบริษัทอื่น", repaired_headers, repaired_rows


def _is_generated_column_header(header: str) -> bool:
    return bool(re.fullmatch(r"column_?\d+", str(header or "").strip().lower()))


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


def _parse_numeric(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text or text in {"-", "–", "—"}:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    text = text.replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None

    number = float(text)
    return -number if negative else number


def _format_numeric_like(template: Any, value: float) -> str:
    template_text = str(template or "").strip()
    decimals = 0
    if "." in template_text:
        decimals = len(template_text.rsplit(".", 1)[-1])

    rounded = round(value, decimals)
    if decimals == 0:
        return f"{int(round(rounded)):,}"

    return f"{rounded:,.{decimals}f}"


def _is_descriptor_header(header: str, index: int) -> bool:
    text = str(header or "").strip().lower()
    if not text:
        return False
    if _is_year_header(text) or _is_generated_column_header(text):
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


def _repair_shifted_liability_rows(
    section_rows: List[Dict[str, Any]],
    headers: List[str],
) -> List[Dict[str, Any]]:
    """Repair a common OCR shift in Thai financial statements.

    Typhoon sometimes merges:
    - "ตราสารหนี้ที่ออกและเงินกู้ยืม"
    - "ประมาณการหนี้สิน"
    into a single row label, then shifts the following labels upward by one row.

    When that happens we rebuild the block into:
    - ตราสารหนี้ที่ออกและเงินกู้ยืม
    - ประมาณการหนี้สิน
    - หนี้สินภาษีเงินได้รอตัดบัญชี
    - หนี้สินอื่น
    using the total row to derive the last one.
    """
    if len(section_rows) < 4 or not headers:
        return section_rows

    label_header = headers[0]
    year_headers = [header for header in headers[1:] if _is_year_header(header)]
    if not year_headers:
        return section_rows

    merged_index = next(
        (
            index
            for index, row in enumerate(section_rows)
            if "ตราสารหนี้ที่ออกและเงินกู้ยืม" in str(row.get(label_header, "")).strip()
            and "ประมาณการหนี้สิน" in str(row.get(label_header, "")).strip()
        ),
        None,
    )
    if merged_index is None or merged_index + 2 >= len(section_rows):
        return section_rows

    total_row_index = next(
        (
            index
            for index, row in enumerate(section_rows)
            if str(row.get(label_header, "")).strip() == "รวมหนี้สิน"
        ),
        None,
    )
    if total_row_index is None or total_row_index <= merged_index + 2:
        return section_rows

    next_label = str(section_rows[merged_index + 1].get(label_header, "")).strip()
    next_next_label = str(section_rows[merged_index + 2].get(label_header, "")).strip()
    if next_label != "หนี้สินภาษีเงินได้รอตัดบัญชี" or next_next_label != "หนี้สินอื่น":
        return section_rows

    prefix_rows = [dict(row) for row in section_rows[:merged_index]]
    merged_row = dict(section_rows[merged_index])
    provision_source = dict(section_rows[merged_index + 1])
    deferred_tax_source = dict(section_rows[merged_index + 2])
    between_rows = [dict(row) for row in section_rows[merged_index + 3:total_row_index]]
    total_and_suffix_rows = [dict(row) for row in section_rows[total_row_index:]]

    merged_row[label_header] = "ตราสารหนี้ที่ออกและเงินกู้ยืม"
    provision_source[label_header] = "ประมาณการหนี้สิน"
    deferred_tax_source[label_header] = "หนี้สินภาษีเงินได้รอตัดบัญชี"

    provisional_rows = prefix_rows + [merged_row, provision_source, deferred_tax_source] + between_rows
    total_row = total_and_suffix_rows[0]
    other_row = {header: "" for header in headers}
    other_row[label_header] = "หนี้สินอื่น"

    repaired_years = 0
    for year_header in year_headers:
        total_value = _parse_numeric(total_row.get(year_header, ""))
        if total_value is None:
            continue

        other_sum = 0.0
        valid_rows = 0
        for row in provisional_rows:
            value = _parse_numeric(row.get(year_header, ""))
            if value is None:
                continue
            other_sum += value
            valid_rows += 1

        if valid_rows < 3:
            continue

        derived_value = total_value - other_sum
        if derived_value <= 0:
            return section_rows

        other_row[year_header] = _format_numeric_like(deferred_tax_source.get(year_header, ""), derived_value)
        repaired_years += 1

    if repaired_years < max(2, len(year_headers) - 1):
        return section_rows

    return provisional_rows + [other_row] + total_and_suffix_rows


def _repair_total_derived_rows(
    section_rows: List[Dict[str, Any]],
    headers: List[str],
) -> List[Dict[str, Any]]:
    """Repair OCR-misread rows by recomputing them from a reliable total row.

    This is intentionally conservative. We only fix rows that:
    - belong to a section that has year-like columns
    - have a matching total row (for now: liabilities section -> "รวมหนี้สิน")
    - are clearly suspicious versus the derived value from the section total
    """
    if len(section_rows) < 3 or not headers:
        return section_rows

    label_header = headers[0]
    year_headers = [header for header in headers[1:] if _is_year_header(header)]
    if not year_headers:
        return section_rows

    total_row_index = next(
        (
            index
            for index, row in enumerate(section_rows)
            if str(row.get(label_header, "")).strip() == "รวมหนี้สิน"
        ),
        None,
    )
    if total_row_index is None or total_row_index < 1:
        return section_rows

    rows_before_total = section_rows[:total_row_index]
    suspicious_targets = [
        row
        for row in rows_before_total
        if str(row.get(label_header, "")).strip() in {"หนี้สินอื่น"}
    ]
    if not suspicious_targets:
        return section_rows

    repaired_rows = [dict(row) for row in section_rows]
    repaired_target_labels: set[str] = set()

    for target in suspicious_targets:
        target_label = str(target.get(label_header, "")).strip()
        target_index = next(
            (
                index
                for index, row in enumerate(repaired_rows[:total_row_index])
                if str(row.get(label_header, "")).strip() == target_label
            ),
            None,
        )
        if target_index is None:
            continue

        target_row = repaired_rows[target_index]
        total_row = repaired_rows[total_row_index]
        replacement_by_year: Dict[str, str] = {}
        changes = 0

        for year_header in year_headers:
            total_value = _parse_numeric(total_row.get(year_header, ""))
            current_value = _parse_numeric(target_row.get(year_header, ""))
            if total_value is None or current_value is None:
                continue

            other_sum = 0.0
            valid_other_rows = 0
            for index, other_row in enumerate(repaired_rows[:total_row_index]):
                if index == target_index:
                    continue
                other_value = _parse_numeric(other_row.get(year_header, ""))
                if other_value is None:
                    continue
                other_sum += other_value
                valid_other_rows += 1

            if valid_other_rows < 2:
                continue

            derived_value = total_value - other_sum
            if derived_value <= 0:
                continue

            ratio = abs(derived_value) / max(abs(current_value), 1.0)
            diff = abs(derived_value - current_value)

            # Conservative trigger:
            # OCR often drops one or two digits on these rows, making the value
            # dramatically smaller than what the section total implies.
            if ratio < 5 or diff < 10_000_000:
                continue

            replacement_by_year[year_header] = _format_numeric_like(target_row.get(year_header, ""), derived_value)
            changes += 1

        if changes >= max(2, len(year_headers) - 1):
            for year_header, replacement in replacement_by_year.items():
                target_row[year_header] = replacement
            repaired_target_labels.add(target_label)

    return repaired_rows if repaired_target_labels else section_rows


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


def _trim_empty_trailing_columns(headers: List[str], rows: List[List[str]]) -> tuple[List[str], List[List[str]]]:
    effective_headers = list(headers)
    effective_rows = [list(row) for row in rows]

    while len(effective_headers) > 2:
        last_index = len(effective_headers) - 1
        last_header = str(effective_headers[last_index] or "").strip()
        if not _is_generated_column_header(last_header):
            break
        if any(str((row[last_index] if last_index < len(row) else "") or "").strip() for row in effective_rows):
            break
        effective_headers.pop()
        effective_rows = [row[:len(effective_headers)] for row in effective_rows]

    return effective_headers, effective_rows


def _promote_year_row_into_headers(headers: List[str], rows: List[List[str]]) -> tuple[List[str], List[List[str]]]:
    if len(headers) < 4 or not rows:
        return headers, rows

    first_row = [str(cell or "").strip() for cell in rows[0]]
    generic_headers = sum(1 for header in headers[1:] if _is_generated_column_header(header) or _is_unit_token(header))
    year_candidates = [cell for cell in first_row if _is_year_header(cell)]

    if generic_headers < max(2, len(headers) - 2) or len(year_candidates) < 2:
        return headers, rows

    data_col_count = len(headers) - 1
    unique_years: List[str] = []
    for cell in first_row:
        if _is_year_header(cell) and cell not in unique_years:
            unique_years.append(cell)

    if len(unique_years) == data_col_count:
        resolved_years = unique_years
    elif len(unique_years) == data_col_count - 1:
        try:
            numeric_years = [int(year) for year in unique_years]
        except ValueError:
            return headers, rows
        if len(numeric_years) >= 2 and all(
            numeric_years[index] - numeric_years[index + 1] == 1 for index in range(len(numeric_years) - 1)
        ):
            resolved_years = unique_years + [str(numeric_years[-1] - 1)]
        else:
            return headers, rows
    else:
        return headers, rows

    promoted_headers = [headers[0], *resolved_years]
    promoted_rows = [row[:len(promoted_headers)] for row in rows[1:]]
    return promoted_headers, promoted_rows


def _repair_balance_sheet_totals(
    row_dicts: List[Dict[str, Any]],
    headers: List[str],
) -> List[Dict[str, Any]]:
    if len(row_dicts) < 6 or not headers:
        return row_dicts

    label_header = headers[0]
    year_headers = [header for header in headers[1:] if _is_year_header(header)]
    if len(year_headers) < 2:
        return row_dicts

    repaired_rows = [dict(row) for row in row_dicts]

    def _find_index(label: str) -> Optional[int]:
        return next(
            (
                index
                for index, row in enumerate(repaired_rows)
                if str(row.get(label_header, "")).strip() == label
            ),
            None,
        )

    liability_title_index = _find_index("หนี้สินและส่วนของเจ้าของ")
    other_liability_index = _find_index("หนี้สินอื่น")
    total_liability_index = _find_index("รวมหนี้สิน")
    total_equity_index = _find_index("รวมส่วนของเจ้าของ")
    grand_total_index = _find_index("รวมหนี้สินและส่วนของเจ้าของ")

    if None in {
        liability_title_index,
        other_liability_index,
        total_liability_index,
        total_equity_index,
        grand_total_index,
    }:
        return row_dicts

    if not (
        liability_title_index < other_liability_index < total_liability_index < total_equity_index < grand_total_index
    ):
        return row_dicts

    total_liability_row = repaired_rows[total_liability_index]
    total_equity_row = repaired_rows[total_equity_index]
    grand_total_row = repaired_rows[grand_total_index]
    recalculated_total_liability = False
    for year_header in year_headers:
        grand_total = _parse_numeric(grand_total_row.get(year_header, ""))
        total_equity = _parse_numeric(total_equity_row.get(year_header, ""))
        if grand_total is None or total_equity is None:
            continue
        total_liability = grand_total - total_equity
        if total_liability <= 0:
            continue
        total_liability_row[year_header] = _format_numeric_like(grand_total_row.get(year_header, ""), total_liability)
        recalculated_total_liability = True

    if not recalculated_total_liability:
        return row_dicts

    return repaired_rows if recalculated_total_liability else row_dicts


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
    title = _normalize_repeated_title(_strip_markdown(table.get("title") or "") or default_name)
    table_name = safe_table_name(_normalize_repeated_title(table.get("table_name") or title), default_name)

    clean_rows = [[_strip_markdown(cell) for cell in row] for row in raw_rows]
    max_cols = max([len(raw_headers)] + [len(row) for row in clean_rows] + [1])
    inferred_headers, clean_rows = _infer_financial_investment_headers(
        [_strip_markdown(h) for h in raw_headers],
        clean_rows,
        max_cols,
    )
    headers = inferred_headers or _normalize_headers([_strip_markdown(h) for h in raw_headers], max_cols)

    rows: List[List[str]] = []
    for row in clean_rows:
        padded = row[:max_cols] + [""] * max(0, max_cols - len(row))
        if any(cell.strip() for cell in padded):
            rows.append(padded)

    headers, rows = _trim_empty_trailing_columns(headers, rows)
    headers, rows = _promote_year_row_into_headers(headers, rows)
    title, headers, rows = _repair_stored_financial_investment_table(title, headers, rows)
    table_name = safe_table_name(_normalize_repeated_title(table_name), default_name)

    csv_text = table_to_csv(headers, rows) if rows else ""
    return {
        "title": title,
        "table_name": table_name,
        "headers": headers,
        "rows": rows,
        "csv_text": csv_text,
    }


def _merge_header_fragment_tables(tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge OCR header fragments back into the following body table.

    Some pages return a tiny first table that only contains the year header row,
    followed by the actual body table. This helper promotes those year cells back
    into the next table headers so the whole page behaves like a single table again.
    """
    merged: List[Dict[str, Any]] = []
    index = 0

    while index < len(tables):
        current = tables[index]
        nxt = tables[index + 1] if index + 1 < len(tables) else None

        if nxt and _should_merge_header_fragment(current, nxt):
            merged.append(_merge_header_fragment_pair(current, nxt))
            index += 2
            continue

        merged.append(current)
        index += 1

    return merged


def _should_merge_header_fragment(fragment: Dict[str, Any], body: Dict[str, Any]) -> bool:
    fragment_headers = fragment.get("headers") or []
    fragment_rows = fragment.get("rows") or []
    body_headers = body.get("headers") or []
    body_rows = body.get("rows") or []

    if len(fragment_rows) != 1 or not body_rows:
        return False
    if len(fragment_headers) != len(body_headers):
        return False

    row = fragment_rows[0]
    year_hits = sum(1 for cell in row[1:] if _is_year_header(cell))
    if year_hits < 2:
        return False

    fragment_generic_headers = sum(
        1
        for header in fragment_headers[1:]
        if _is_generated_column_header(header) or _is_unit_token(header)
    )
    body_generic_headers = sum(
        1 for header in body_headers[1:] if _is_generated_column_header(header)
    )
    return fragment_generic_headers >= 1 and body_generic_headers >= 1


def _merge_header_fragment_pair(fragment: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    headers = list(body.get("headers") or [])
    row = list((fragment.get("rows") or [[]])[0])
    fragment_headers = fragment.get("headers") or []

    if headers:
        headers[0] = headers[0] or fragment_headers[0] or "รายการ"

    for index in range(1, min(len(headers), len(row))):
        cell = str(row[index] or "").strip()
        if _is_year_header(cell):
            headers[index] = cell
        elif _is_unit_token(cell):
            headers[index] = cell

    merged_rows = list(body.get("rows") or [])
    return {
        "title": body.get("title") or fragment.get("title") or body.get("table_name") or fragment.get("table_name"),
        "table_name": body.get("table_name") or fragment.get("table_name"),
        "headers": headers,
        "rows": merged_rows,
        "csv_text": table_to_csv(headers, merged_rows) if merged_rows else "",
    }


def _combine_sections_into_single_table(
    table: Dict[str, Any],
    sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not sections:
        return []
    if len(sections) == 1:
        return sections

    first_headers = sections[0].get("headers") or []
    if not first_headers:
        return sections
    if any((section.get("headers") or []) != first_headers for section in sections[1:]):
        return sections

    combined_rows: List[List[str]] = []
    base_title = str(table.get("title") or table.get("table_name") or "").strip()

    for index, section in enumerate(sections):
        section_title = str(section.get("title") or "").strip()
        rows = list(section.get("rows") or [])
        if section_title and section_title != base_title:
            combined_rows.append([section_title, *([""] * (len(first_headers) - 1))])
        combined_rows.extend(rows)

    combined_title = base_title or str(sections[0].get("title") or sections[0].get("table_name") or "table")
    combined_table_name = safe_table_name(
        str(table.get("table_name") or combined_title),
        combined_title,
    )
    return [
        {
            "title": combined_title,
            "table_name": combined_table_name,
            "headers": first_headers,
            "rows": combined_rows,
            "csv_text": table_to_csv(first_headers, combined_rows),
        }
    ]


def split_normalized_table_into_sections(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    headers = list(table.get("headers") or [])
    rows = list(table.get("rows") or [])
    if not headers or not rows:
        return []

    label_header = headers[0]
    year_headers = [header for header in headers[1:] if _is_year_header(header)]
    value_headers = headers[1:]

    row_dicts = [dict(zip(headers, row)) for row in rows]
    row_dicts = _repair_balance_sheet_totals(row_dicts, headers)
    sections: List[Dict[str, Any]] = []
    current_title = table.get("title") or table.get("table_name") or "table"
    current_rows: List[Dict[str, Any]] = []

    def flush_section(title: str, section_rows: List[Dict[str, Any]]):
        if not section_rows:
            return

        effective_headers, section_rows = _collapse_sparse_footer_rows(section_rows, headers)
        section_rows = _repair_shifted_liability_rows(section_rows, effective_headers)
        section_rows = _repair_total_derived_rows(section_rows, effective_headers)

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

        section_table_name = safe_table_name(
            f"{table.get('table_name')}_{_strip_markdown(title)}" if title else str(table.get("table_name") or title),
            str(table.get("table_name") or title or "table"),
        )
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
    return _combine_sections_into_single_table(table, sections) or [table]


def normalize_ocr_tables(table_prefix: str, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, table in enumerate(tables):
        normalized_table = normalize_ocr_table(table, f"{table_prefix}_table_{index}")
        normalized.extend(split_normalized_table_into_sections(normalized_table))
    return _merge_header_fragment_tables(normalized)


def rebuild_structured_tables(
    table_name: str,
    headers: List[str],
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rebuilt_headers = list(headers or [])
    rebuilt_rows = [[row.get(header, "") for header in rebuilt_headers] for row in rows]
    rebuilt_headers, rebuilt_rows = _trim_empty_trailing_columns(rebuilt_headers, rebuilt_rows)
    rebuilt_headers, rebuilt_rows = _promote_year_row_into_headers(rebuilt_headers, rebuilt_rows)
    rebuilt_title, rebuilt_headers, rebuilt_rows = _repair_stored_financial_investment_table(
        table_name,
        rebuilt_headers,
        rebuilt_rows,
    )

    normalized_table = {
        "title": rebuilt_title,
        "table_name": safe_table_name(_normalize_repeated_title(table_name), rebuilt_title or table_name),
        "headers": rebuilt_headers,
        "rows": rebuilt_rows,
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
