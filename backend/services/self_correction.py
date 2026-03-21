"""Self-correction and validation layer for OCR table results.

After Typhoon OCR produces a table, this module checks structural
integrity (column counts, data-type regex) and optionally retries
OCR on problematic sub-regions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CellIssue:
    """Describes a single problematic cell."""

    row_index: int
    col_index: int
    issue_type: str  # "column_count", "invalid_number", "invalid_date", "empty_row"
    detail: str = ""


@dataclass
class ValidationReport:
    """Summary of all issues found in one table."""

    issues: List[CellIssue] = field(default_factory=list)
    confidence_score: float = 1.0
    column_count_ok: bool = True
    row_count: int = 0
    empty_row_indices: List[int] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0

    @property
    def needs_retry(self) -> bool:
        return self.confidence_score < 0.7 or not self.column_count_ok


@dataclass
class ValidatedTable:
    """Table data after validation and optional self-correction."""

    headers: List[str]
    rows: List[List[str]]
    report: ValidationReport
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Regex patterns for Thai documents
# ---------------------------------------------------------------------------

# Standard number: optional sign, digits with commas, optional decimals
RE_NUMBER = re.compile(r"^[+-]?\d[\d,]*\.?\d*$")

# Number in parentheses (negative in accounting format)
RE_ACCOUNTING_NEG = re.compile(r"^\(\d[\d,]*\.?\d*\)$")

# Percentage
RE_PERCENT = re.compile(r"^[+-]?\d[\d,]*\.?\d*\s*%$")

# Thai date patterns (short month abbreviations)
_THAI_MONTHS = (
    r"ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|"
    r"ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\."
)
RE_THAI_DATE = re.compile(
    rf"^\d{{1,2}}\s*({_THAI_MONTHS})\s*\d{{2,4}}$"
)

# Full Thai month names
_THAI_MONTHS_FULL = (
    r"มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|"
    r"กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม"
)
RE_THAI_DATE_FULL = re.compile(
    rf"^\d{{1,2}}\s*({_THAI_MONTHS_FULL})\s*\d{{2,4}}$"
)

# Placeholder/dash values
RE_PLACEHOLDER = re.compile(r"^[-–—\.]{1,3}$")

# Year (Thai Buddhist Era or CE)
RE_YEAR = re.compile(r"^(?:25|20)\d{2}$")

# Unit tokens that OCR often misplaces into year columns
RE_UNIT_TOKEN = re.compile(
    r"^\(?(%|บาท|ล้านบาท|พันบาท|ล้าน|พัน|ร้อย|หุ้น|ราย|เท่า|ครั้ง)\)?$"
)


def _is_unit_token(value: str) -> bool:
    """Check if a cell value is a unit indicator like (%), (บาท), etc."""
    text = str(value or "").strip()
    if not text:
        return False
    if RE_UNIT_TOKEN.match(text):
        return True
    # Also match parenthesised short units: (%), (บาท), (ล้านบาท)
    if re.fullmatch(r"\([^)]{1,15}\)", text):
        inner = text[1:-1].strip()
        return bool(RE_UNIT_TOKEN.match(inner) or inner in {"%", "บาท", "ล้านบาท"})
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_table(
    headers: List[str],
    rows: List[List[str]],
) -> ValidationReport:
    """Run structural and content validation on the parsed table.

    Checks performed:
    1. Column count consistency
    2. Completely empty rows
    3. Regex checks on cells that should be numeric or date-like
    """
    report = ValidationReport(row_count=len(rows))
    expected_cols = len(headers)

    for row_idx, row in enumerate(rows):
        # --- Column count ---
        if len(row) != expected_cols:
            report.column_count_ok = False
            report.issues.append(CellIssue(
                row_index=row_idx,
                col_index=-1,
                issue_type="column_count",
                detail=f"expected {expected_cols} cols, got {len(row)}",
            ))

        # --- Empty row ---
        if all(not str(cell or "").strip() for cell in row):
            report.empty_row_indices.append(row_idx)
            report.issues.append(CellIssue(
                row_index=row_idx,
                col_index=-1,
                issue_type="empty_row",
                detail="entire row is empty",
            ))
            continue

        # --- Cell-level checks ---
        for col_idx, cell in enumerate(row):
            value = str(cell or "").strip()
            if not value or RE_PLACEHOLDER.match(value):
                continue

            # If header suggests numeric, check that the cell is valid
            if col_idx < len(headers):
                header = str(headers[col_idx] or "").strip()
                if _header_suggests_numeric(header) and not _is_valid_numeric_cell(value):
                    report.issues.append(CellIssue(
                        row_index=row_idx,
                        col_index=col_idx,
                        issue_type="invalid_number",
                        detail=f"'{value}' doesn't match numeric pattern under header '{header}'",
                    ))

    # --- Confidence score ---
    total_cells = max(len(rows) * expected_cols, 1)
    issue_cells = len([i for i in report.issues if i.issue_type != "empty_row"])
    report.confidence_score = max(0.0, 1.0 - (issue_cells / total_cells) * 2)

    return report


async def validate_and_correct(
    headers: List[str],
    rows: List[List[str]],
    original_image: Optional[Image.Image],
    table_bbox: Optional[Any],
    ocr_fn: Optional[Callable] = None,
    max_retries: int = 2,
    output_format: str = "markdown",
) -> ValidatedTable:
    """Validate the table and optionally retry OCR on problematic regions.

    Parameters
    ----------
    headers, rows : list
        Parsed table data from the first OCR pass.
    original_image : PIL.Image, optional
        The original (pre-cropped) table image, needed for sub-image retry.
    table_bbox : BoundingBox, optional
        If the table was cropped, coordinates within the original page.
    ocr_fn : callable, optional
        An async function ``(image_bytes, mime_type) -> parsed_table_dict``
        used for re-OCR.  If *None*, no retry is attempted.
    max_retries : int
        Maximum number of sub-image re-OCR attempts.
    output_format : str
        ``"markdown"`` or ``"json"`` — passed to the OCR prompt builder.
    """
    # Fix unit column shift BEFORE validation (the most impactful repair)
    headers, rows = _repair_unit_column_shift(headers, rows)

    report = validate_table(headers, rows)

    # Fix trivially repairable issues
    headers, rows = _fix_column_counts(headers, rows)
    rows = _remove_empty_rows(rows)

    if report.is_valid or ocr_fn is None or original_image is None:
        return ValidatedTable(
            headers=headers,
            rows=rows,
            report=report,
            retry_count=0,
        )

    # Attempt sub-image retry for rows with issues
    retry_count = 0
    for attempt in range(max_retries):
        problem_rows = _identify_problem_row_ranges(report, rows)
        if not problem_rows:
            break

        retried_any = False
        for row_start, row_end in problem_rows:
            sub_image = _crop_row_region(
                original_image, rows, row_start, row_end,
            )
            if sub_image is None:
                continue

            try:
                import io
                buf = io.BytesIO()
                sub_image.save(buf, format="PNG")
                ocr_result = await ocr_fn(buf.getvalue(), "image/png")

                new_rows = ocr_result.get("rows", [])
                if not new_rows:
                    continue

                # Replace the problematic rows if the new result looks better
                new_report = validate_table(headers, new_rows)
                if new_report.confidence_score > report.confidence_score:
                    rows[row_start:row_end + 1] = new_rows
                    retried_any = True
                    retry_count += 1
            except Exception as exc:
                logger.warning("Sub-image OCR retry failed: %s", exc)

        if not retried_any:
            break

        # Re-validate after corrections
        report = validate_table(headers, rows)
        if report.is_valid:
            break

    return ValidatedTable(
        headers=headers,
        rows=rows,
        report=report,
        retry_count=retry_count,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header_suggests_numeric(header: str) -> bool:
    """Heuristic: does the header name imply numeric values?"""
    if RE_YEAR.match(header):
        return True
    numeric_keywords = (
        "จำนวน", "ยอด", "รวม", "บาท", "ล้าน", "พัน", "ร้อย",
        "อัตรา", "ดอกเบี้ย", "กำไร", "ขาดทุน", "สินทรัพย์",
        "หนี้สิน", "%", "amount", "total", "sum", "value",
    )
    lower = header.lower()
    return any(kw in lower for kw in numeric_keywords)


def _is_valid_numeric_cell(value: str) -> bool:
    """Check if a cell value is a valid number (including accounting negative)."""
    return bool(
        RE_NUMBER.match(value)
        or RE_ACCOUNTING_NEG.match(value)
        or RE_PERCENT.match(value)
        or RE_PLACEHOLDER.match(value)
    )


def _repair_unit_column_shift(
    headers: List[str],
    rows: List[List[str]],
) -> Tuple[List[str], List[List[str]]]:
    """Detect and repair rows where a unit token (%, บาท) landed in a year column.

    Pattern detected (OCR output):
        Headers:  [รายการ, 2567, 2566, 2565, 2564, 2563]
        Bad row:  [ผลตอบแทนฯ, (%), 1.10, 1.22, 1.20, 1.32]
                                ^^^ unit token occupies the first year column

    Repair strategy — insert a dedicated "หน่วย" column:
        Headers:  [รายการ, หน่วย, 2567, 2566, 2565, 2564, 2563]
        Fixed:    [ผลตอบแทนฯ, (%), 1.10, 1.22, 1.20, 1.32, ]
        Normal:   [รายได้ดอกเบี้ย, , 156538, 139251, ...]
    """
    if len(headers) < 3:
        return headers, rows

    # Identify which header columns are year-like (expected to hold numbers)
    year_col_indices = [
        i for i, h in enumerate(headers)
        if RE_YEAR.match(str(h or "").strip())
    ]
    if not year_col_indices:
        return headers, rows

    first_year_col = year_col_indices[0]

    # Check if ANY row has a unit token in the first year column
    has_unit_rows = any(
        first_year_col < len(row) and _is_unit_token(str(row[first_year_col] or "").strip())
        for row in rows
    )
    if not has_unit_rows:
        return headers, rows

    # --- Insert a "หน่วย" column into headers ---
    new_headers = (
        headers[:first_year_col]
        + ["หน่วย"]
        + headers[first_year_col:]
    )

    # --- Repair each row ---
    repaired_rows: List[List[str]] = []
    for row in rows:
        row = list(row)  # copy

        if first_year_col < len(row):
            cell_val = str(row[first_year_col] or "").strip()

            if _is_unit_token(cell_val):
                # This row HAS a unit token — it's already in the right
                # position (between label cols and year cols) after we
                # inserted the "หน่วย" header.  We just need to ensure
                # the row length matches the new header count.
                # The row is: [label, (%), val1, val2, val3, val4]
                # New headers: [label, หน่วย, 2567, 2566, 2565, 2564, 2563]
                # Row already aligns naturally after header insertion.
                pass
            else:
                # This row does NOT have a unit token — insert an empty
                # cell at the unit column position so values stay aligned.
                row = (
                    row[:first_year_col]
                    + [""]
                    + row[first_year_col:]
                )

        # Pad or trim to match new header count
        while len(row) < len(new_headers):
            row.append("")
        row = row[:len(new_headers)]

        repaired_rows.append(row)

    logger.info(
        "Repaired unit column shift: added หน่วย column, %d rows affected",
        sum(1 for r in repaired_rows if str(r[first_year_col] or "").strip()),
    )

    return new_headers, repaired_rows


def _fix_column_counts(
    headers: List[str],
    rows: List[List[str]],
) -> Tuple[List[str], List[List[str]]]:
    """Pad or truncate rows to match the header column count."""
    expected = len(headers)
    fixed: List[List[str]] = []
    for row in rows:
        if len(row) < expected:
            row = row + [""] * (expected - len(row))
        elif len(row) > expected:
            row = row[:expected]
        fixed.append(row)
    return headers, fixed


def _remove_empty_rows(rows: List[List[str]]) -> List[List[str]]:
    """Drop rows where every cell is empty."""
    return [row for row in rows if any(str(cell or "").strip() for cell in row)]


def _identify_problem_row_ranges(
    report: ValidationReport,
    rows: List[List[str]],
) -> List[Tuple[int, int]]:
    """Group consecutive problematic rows into (start, end) ranges."""
    problem_indices = sorted(set(
        issue.row_index
        for issue in report.issues
        if issue.row_index >= 0 and issue.issue_type not in ("empty_row",)
    ))

    if not problem_indices:
        return []

    ranges: List[Tuple[int, int]] = []
    start = problem_indices[0]
    end = start

    for idx in problem_indices[1:]:
        if idx <= end + 2:  # merge close rows
            end = idx
        else:
            ranges.append((start, min(end, len(rows) - 1)))
            start = idx
            end = idx

    ranges.append((start, min(end, len(rows) - 1)))
    return ranges


def _crop_row_region(
    image: Image.Image,
    rows: List[List[str]],
    row_start: int,
    row_end: int,
) -> Optional[Image.Image]:
    """Estimate the row region in the image and crop it.

    This is a rough heuristic: assume rows are evenly spaced vertically.
    """
    if not rows:
        return None

    img_w, img_h = image.size
    total_rows = len(rows)
    row_height = img_h / max(total_rows + 1, 1)  # +1 for the header

    y0 = int((row_start + 1) * row_height)  # +1 to skip header
    y1 = int((row_end + 2) * row_height)

    # Clamp
    y0 = max(0, y0 - int(row_height * 0.2))
    y1 = min(img_h, y1 + int(row_height * 0.2))

    if y1 <= y0:
        return None

    return image.crop((0, y0, img_w, y1))
