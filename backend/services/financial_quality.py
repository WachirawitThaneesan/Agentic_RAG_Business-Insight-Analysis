"""Conservative, explainable checks for OCR-extracted financial tables.

Passing these checks is not proof that a value matches the PDF. A failed check
means that the involved row must not be treated as a trusted numeric fact.
The original OCR is retained separately for inspection and retry.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


_YEAR = re.compile(r"(?<!\d)(?:25|20)\d{2}(?!\d)")
_NUMBER = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$")
_EMPTY = {"", "-", "–", "—", "n/a", "na"}


def parse_number(value: Any) -> Decimal | None:
    """Parse a printed financial number without guessing damaged OCR glyphs."""
    text = str(value if value is not None else "").strip().replace("\u00a0", "")
    if text.casefold() in _EMPTY:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    if not _NUMBER.fullmatch(text):
        return None
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None
    return -number if negative else number


def _printed_number(value: Any) -> bool:
    text = str(value if value is not None else "").strip()
    return text.casefold() not in _EMPTY


def _roles(headers: list[str]) -> tuple[list[int], int | None, int | None]:
    years = [index for index, header in enumerate(headers) if _YEAR.search(str(header or ""))]
    change = None
    percent = None
    for index, header in enumerate(headers):
        label = re.sub(r"\s+", " ", str(header or "")).casefold()
        is_percent = "%" in label or "ร้อยละ" in label or "percent" in label
        is_change = any(token in label for token in ("เปลี่ยนแปลง", "เพิ่ม (ลด)", "change", "variance"))
        if is_change and is_percent:
            percent = index
        elif is_change and index not in years:
            change = index
        elif is_percent and index not in years and percent is None:
            percent = index
    return years, change, percent


def _chart_like(headers: list[str], rows: list[list[str]]) -> bool:
    """Reject tiny OCR pseudo-tables made from figure legends, not all charts."""
    if len(rows) > 3 or len(headers) < 3:
        return False
    if any(parse_number(cell) is not None for row in rows for cell in row[1:]):
        return False
    return all(not str(row[0] if row else "").strip() for row in rows)


def assess_table(table: dict[str, Any]) -> dict[str, Any]:
    """Return per-row/cell reasons and the rows eligible for provisional use.

    A numeric mismatch quarantines the entire row: the equation identifies a
    contradiction, but cannot establish which cell was misread. Rows without a
    valid applicable relationship are explicitly marked ``unverified``.
    """
    headers = [str(header or "") for header in table.get("headers", [])]
    rows = [[str(cell if cell is not None else "") for cell in row] for row in table.get("rows", [])]
    years, change_col, percent_col = _roles(headers)
    chart_like = _chart_like(headers, rows)
    retry_disagreements = table.get("retry_disagreements") or []
    row_reports: list[dict[str, Any]] = []
    accepted_rows: list[list[str]] = []
    accepted_row_indices: list[int] = []

    for row_index, row in enumerate(rows):
        reasons: list[str] = []
        checked_columns: set[int] = set()
        problem_columns: set[int] = set()
        numeric_columns = [i for i, cell in enumerate(row[1:], 1) if parse_number(cell) is not None]

        disputed_columns = {
            int(item["column"]) for item in retry_disagreements
            if item.get("row_index") == row_index and isinstance(item.get("column"), int)
        }
        if disputed_columns:
            reasons.append("ocr_passes_disagree")
            problem_columns.update(disputed_columns)

        if chart_like:
            reasons.append("figure_legend_misread_as_table")
            problem_columns.update(numeric_columns)
        if len(row) != len(headers):
            reasons.append("column_count_mismatch")
            problem_columns.update(numeric_columns)
        if not str(row[0] if row else "").strip() and numeric_columns:
            reasons.append("numeric_row_without_label")
            problem_columns.update(numeric_columns)

        # A lone year can be a spanning header above categorical subcolumns
        # (e.g. board-meeting attendance "4/4"), not a numeric value column.
        candidate_columns = list(years) if len(years) == 2 else []
        if len(years) == 2 and change_col is not None:
            candidate_columns.append(change_col)
        if len(years) == 2 and percent_col is not None:
            candidate_columns.append(percent_col)
        for column in set(candidate_columns):
            if column < len(row) and _printed_number(row[column]) and parse_number(row[column]) is None:
                reasons.append(f"invalid_numeric_cell:{column}")
                problem_columns.add(column)

        # Only infer current/prior from an unambiguous two-year comparison.
        if len(years) == 2 and all(i < len(row) for i in years):
            current = parse_number(row[years[0]])
            prior = parse_number(row[years[1]])
            if current is not None and prior is not None:
                difference = current - prior
                if change_col is not None and change_col < len(row):
                    reported_change = parse_number(row[change_col])
                    if reported_change is not None:
                        involved = {years[0], years[1], change_col}
                        checked_columns.update(involved)
                        # Rounded displayed amounts may differ by one unit.
                        tolerance = Decimal("1") if all(v == v.to_integral_value() for v in (current, prior, reported_change)) else Decimal("0.02")
                        if abs(difference - reported_change) > tolerance:
                            reasons.append("reported_change_disagrees_with_years")
                            problem_columns.update(involved)
                if percent_col is not None and percent_col < len(row) and prior != 0:
                    reported_percent = parse_number(row[percent_col])
                    if reported_percent is not None:
                        involved = {years[0], years[1], percent_col}
                        checked_columns.update(involved)
                        label = str(row[0] if row else "").casefold()
                        percentage_point_row = any(token in label for token in ("ร้อยละ", "%", "ratio", "rate"))
                        expected_percent = difference if percentage_point_row else difference * 100 / abs(prior)
                        # A percentage-valued row reports a point change,
                        # while an amount row reports a relative change.
                        tolerance = Decimal("0.02") if percentage_point_row else Decimal("0.15")
                        if abs(expected_percent - reported_percent) > tolerance:
                            reasons.append("reported_percent_disagrees_with_years")
                            problem_columns.update(involved)

        status = "unresolved" if reasons else "passed_checks" if checked_columns else "unverified"
        cells = []
        for column, value in enumerate(row):
            if column == 0:
                continue
            cell_status = "unresolved" if status == "unresolved" else "passed_checks" if column in checked_columns else "unverified"
            cells.append({"column": column, "value": value, "status": cell_status})
        row_reports.append({
            "row_index": row_index,
            "status": status,
            "reasons": reasons,
            "problem_columns": sorted(problem_columns),
            "cells": cells,
        })
        if status != "unresolved":
            accepted_rows.append(row)
            accepted_row_indices.append(row_index)

    unresolved = sum(row["status"] == "unresolved" for row in row_reports)
    passed = sum(row["status"] == "passed_checks" for row in row_reports)
    return {
        "page": table.get("page"),
        "table_name": table.get("table_name"),
        "status": "unresolved" if unresolved else "passed_checks" if passed else "unverified",
        "chart_like": chart_like,
        "row_reports": row_reports,
        "accepted_rows": accepted_rows,
        "accepted_row_indices": accepted_row_indices,
        "unresolved_rows": unresolved,
        "passed_rows": passed,
    }


def reconcile_retry(primary_tables: list[dict], retry_tables: list[dict]) -> tuple[list[dict], list[dict]]:
    """Use a single high-DPI correction only when the same row passes checks.

    Both OCR passes must have identical table structure and row labels. The
    changed cell is still OCR-derived, not visually verified ground truth.
    Other numeric disagreements quarantine their rows for structured use.
    """
    if len(primary_tables) != len(retry_tables):
        return primary_tables, []
    merged_tables = []
    changes = []
    for first, second in zip(primary_tables, retry_tables):
        merged = dict(first)
        first_rows = [list(row) for row in first.get("rows", [])]
        second_rows = [list(row) for row in second.get("rows", [])]
        if first.get("headers") != second.get("headers") or len(first_rows) != len(second_rows):
            merged_tables.append(merged)
            continue
        first_report = assess_table(first)
        disagreements = []
        for index, row_report in enumerate(first_report["row_reports"]):
            before = first_rows[index]
            after = second_rows[index]
            if len(before) != len(after) or not before or before[0].strip() != after[0].strip():
                continue
            changed = [col for col in range(1, len(before)) if before[col].strip() != after[col].strip()]
            numeric_changes = [col for col in changed if parse_number(before[col]) is not None or parse_number(after[col]) is not None]
            if not numeric_changes:
                continue
            has_contradiction = any(reason.startswith("reported_") for reason in row_report["reasons"])
            if has_contradiction and len(changed) == 1 and changed[0] in row_report["problem_columns"]:
                candidate = {"headers": first["headers"], "rows": [after]}
                if assess_table(candidate)["row_reports"][0]["status"] == "passed_checks":
                    first_rows[index] = after
                    changes.append({
                        "table_name": first.get("table_name"),
                        "row_index": index,
                        "column": changed[0],
                        "first_value": before[changed[0]],
                        "retry_value": after[changed[0]],
                        "status": "retry_consistent_not_source_verified",
                    })
                    continue
            for column in numeric_changes:
                disagreement = {
                    "table_name": first.get("table_name"),
                    "row_index": index,
                    "column": column,
                    "first_value": before[column],
                    "retry_value": after[column],
                    "status": "ocr_passes_disagree_unresolved",
                }
                disagreements.append(disagreement)
                changes.append(disagreement)
        merged["rows"] = first_rows
        if disagreements:
            merged["retry_disagreements"] = disagreements
        merged_tables.append(merged)
    return merged_tables, changes
