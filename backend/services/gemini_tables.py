"""Read table cells with Gemini while Typhoon supplies ordinary page text."""

from __future__ import annotations

import asyncio
import io
from typing import Any

import cv2
import numpy as np
from PIL import Image

from backend.config import get_settings
from backend.services.table_detector import detect_tables


def image_has_table_hint(png_bytes: bytes) -> bool:
    """Cheap visual backup when Typhoon cannot identify a table itself."""
    with Image.open(io.BytesIO(png_bytes)) as source:
        preview = source.convert("RGB")
        preview.thumbnail((1400, 1400))
    return bool(detect_tables(preview, backend="opencv").bboxes)


def _is_dense_matrix(png_bytes: bytes) -> bool:
    """Require many long vertical rules before using a partial-width fallback."""
    with Image.open(io.BytesIO(png_bytes)) as source:
        gray = np.asarray(source.convert("L"))
    height = gray.shape[0]
    ink = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(height // 12, 30))),
    )
    long_rule_columns = (vertical.sum(axis=0) / 255) > height * 0.35
    groups = np.diff(np.r_[False, long_rule_columns, False].astype(int))
    return int(np.count_nonzero(groups == 1)) >= 25


def _main_content_bottom(png_bytes: bytes) -> float | None:
    """Find a large blank footer so a malformed table response can be retried."""
    with Image.open(io.BytesIO(png_bytes)) as source:
        gray = np.asarray(source.convert("L"))
    ink_per_row = (gray < 180).sum(axis=1)
    total = int(ink_per_row.sum())
    if not total:
        return None
    bottom = int(np.searchsorted(np.cumsum(ink_per_row), total * 0.985))
    ratio = min(1.0, (bottom + gray.shape[0] * 0.06) / gray.shape[0])
    return ratio if ratio < 0.85 else None


def _normalize_gemini_tables(data: dict[str, Any], page: int, region: dict) -> list[dict]:
    raw_tables = data.get("tables")
    if not isinstance(raw_tables, list):
        raise ValueError("Gemini table response has no tables list")
    tables = []
    for index, raw in enumerate(raw_tables):
        if not isinstance(raw, dict):
            raise ValueError(f"Gemini table {index} is not an object")
        columns = raw.get("columns") or []
        raw_rows = raw.get("rows") or []
        if not isinstance(columns, list) or not isinstance(raw_rows, list):
            raise ValueError(f"Gemini table {index} has malformed columns or rows")
        if not raw_rows:
            continue
        if any(not isinstance(row, dict) or not isinstance(row.get("values"), list) for row in raw_rows):
            raise ValueError(f"Gemini table {index} has malformed rows")
        widths = {len(row["values"]) for row in raw_rows}
        value_width = max(widths)
        headers = [str(column or "").strip() for column in columns]
        if len(headers) == value_width:
            headers.insert(0, "รายการ")
        elif len(headers) != value_width + 1:
            raise ValueError(f"Gemini table {index} header width differs from its rows")
        rows = []
        ambiguous_rows = 0
        for row in raw_rows:
            label = str(row.get("row_label") or "").strip()
            if len(row["values"]) != value_width:
                # Missing cells can occur in the middle. Padding values on the
                # right would silently assign them to the wrong columns.
                rows.append([f"{label} [UNRESOLVED WIDTH]", *([""] * value_width)])
                ambiguous_rows += 1
            else:
                rows.append([label, *(str(value if value is not None else "").strip()
                                      for value in row["values"])])
        title = str(raw.get("title") or f"table_{index}").strip()
        unit = str(raw.get("unit") or "").strip()
        if unit.startswith("หน่วย:"):
            unit = unit.removeprefix("หน่วย:").strip()
        if unit and unit not in title:
            title = f"{title} (หน่วย: {unit})"
        tables.append({
            "title": title,
            "unit": unit,
            "headers": headers,
            "rows": rows,
            "page": page,
            "source_provider": "gemini",
            "ambiguous_row_count": ambiguous_rows,
            **{key: region[key] for key in ("region", "crop_box", "rotation") if key in region},
        })
    return tables


async def extract_tables_from_png(
    png_bytes: bytes, *, page: int, region: dict,
) -> tuple[list[dict], dict[str, int]]:
    """Return table structures and token usage, raising on failed extraction."""
    from backend.scripts.reocr_tables import _read_page
    from backend.services.llm import _get_genai_client

    settings = get_settings()
    if settings.OFFLINE_MODE:
        raise RuntimeError("Gemini table extraction is disabled in OFFLINE_MODE")
    client = _get_genai_client()
    if _is_dense_matrix(png_bytes):
        # Sending a hundred-column director matrix in one request produced
        # malformed JSON and even a wrong first-column position. Keep only the
        # readable left edge and make the lost coverage explicit.
        with Image.open(io.BytesIO(png_bytes)) as source:
            left = source.convert("RGB").crop((0, 0, int(source.width * 0.2), source.height))
        with io.BytesIO() as buffer:
            left.save(buffer, format="PNG")
            left_png = buffer.getvalue()
        data = await asyncio.to_thread(_read_page, client, settings.GEMINI_MODEL, left_png)
        if data.get("_error"):
            raise RuntimeError(f"Gemini dense-table extraction failed: {data['_error']}")
        partial_region = dict(region)
        box = region.get("crop_box")
        if isinstance(box, list) and len(box) == 4:
            partial_region["crop_box"] = [box[0], box[1], box[0] + 0.2 * (box[2] - box[0]), box[3]]
        tables = _normalize_gemini_tables(data, page, partial_region)
        for table in tables:
            table["title"] += " [PARTIAL: left 20% of region]"
            table["partial_extraction"] = True
        tokens = data.get("_tokens") or (0, 0)
        return tables, {"input_tokens": int(tokens[0]), "output_tokens": int(tokens[1])}
    data = await asyncio.to_thread(_read_page, client, settings.GEMINI_MODEL, png_bytes)
    input_tokens, output_tokens = data.get("_tokens") or (0, 0)
    try:
        if data.get("_error"):
            raise ValueError(f"Gemini table extraction failed: {data['_error']}")
        tables = _normalize_gemini_tables(data, page, region)
    except ValueError:
        # Very wide matrices can exceed the JSON budget; other pages can fail
        # because a large blank footer leaves the table too small in the full
        # image. Retry a clearly labeled crop, never the original Typhoon cells.
        dense = _is_dense_matrix(png_bytes)
        bottom = None if dense else _main_content_bottom(png_bytes)
        if not dense and bottom is None:
            raise
        with Image.open(io.BytesIO(png_bytes)) as source:
            if dense:
                cropped = source.convert("RGB").crop((0, 0, int(source.width * 0.2), source.height))
            else:
                cropped = source.convert("RGB").crop((0, 0, source.width, int(source.height * bottom)))
        with io.BytesIO() as buffer:
            cropped.save(buffer, format="PNG")
            crop_png = buffer.getvalue()
        partial = await asyncio.to_thread(_read_page, client, settings.GEMINI_MODEL, crop_png)
        if partial.get("_error"):
            raise RuntimeError(f"Gemini partial table extraction failed: {partial['_error']}")
        partial_region = dict(region)
        box = region.get("crop_box")
        if isinstance(box, list) and len(box) == 4:
            partial_region["crop_box"] = (
                [box[0], box[1], box[0] + 0.2 * (box[2] - box[0]), box[3]] if dense
                else [box[0], box[1], box[2], box[1] + bottom * (box[3] - box[1])]
            )
        tables = _normalize_gemini_tables(partial, page, partial_region)
        if not tables:
            raise RuntimeError("Gemini partial table extraction returned no tables")
        for table in tables:
            table["title"] += (
                " [PARTIAL: left 20% of region]" if dense
                else " [PARTIAL: upper content crop]"
            )
            table["partial_extraction"] = True
        p_in, p_out = partial.get("_tokens") or (0, 0)
        input_tokens += p_in
        output_tokens += p_out
    return tables, {"input_tokens": int(input_tokens), "output_tokens": int(output_tokens)}
