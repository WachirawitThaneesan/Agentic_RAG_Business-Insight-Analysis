"""High-fidelity table extraction pipeline.

Orchestrates: Detect → Preprocess → OCR → Validate → Normalise.

Usage::

    from backend.services.table_extractor import extract_tables_high_fidelity

    tables = await extract_tables_high_fidelity(
        image_bytes, "report.png", "image/png",
    )
    for t in tables:
        print(t.csv_text)
"""

from __future__ import annotations

import csv
import io
import logging
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PIL import Image

from backend.config import get_settings
from backend.services.image_preprocessor import PreprocessConfig, preprocess_for_ocr
from backend.services.self_correction import ValidatedTable, validate_and_correct
from backend.services.structured_prompts import build_table_extraction_prompt
from backend.services.table_detector import BoundingBox, DetectionResult, crop_tables, detect_tables
from backend.services.thai_postprocessor import normalize_thai_table

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ExtractedTable:
    """Result of the full extraction pipeline for a single table."""

    headers: List[str]
    rows: List[List[str]]
    csv_text: str
    confidence_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_tables_high_fidelity(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    *,
    detector_backend: Optional[str] = None,
    target_dpi: int = 0,
    max_retries: int = 0,
    confidence_threshold: float = 0.0,
    output_format: str = "markdown",
) -> List[ExtractedTable]:
    """Full pipeline: detect → preprocess → OCR → validate → normalise.

    Parameters
    ----------
    file_bytes : bytes
        Raw image or PDF bytes.
    filename, mime_type : str
        Used to determine how to decode the file.
    detector_backend : str, optional
        Override ``TABLE_DETECTOR_BACKEND`` from settings.
    target_dpi : int
        Override ``TABLE_PREPROCESS_TARGET_DPI``. 0 = use setting.
    max_retries : int
        Override ``TABLE_SELF_CORRECTION_MAX_RETRIES``. 0 = use setting.
    confidence_threshold : float
        Override ``TABLE_CONFIDENCE_THRESHOLD``. 0 = use setting.
    output_format : str
        ``"markdown"`` or ``"json"`` — controls the Typhoon prompt.

    Returns
    -------
    list[ExtractedTable]
        One entry per detected table.
    """
    # Resolve settings
    backend = detector_backend or getattr(settings, "TABLE_DETECTOR_BACKEND", "opencv")
    dpi = target_dpi or getattr(settings, "TABLE_PREPROCESS_TARGET_DPI", 300)
    retries = max_retries or getattr(settings, "TABLE_SELF_CORRECTION_MAX_RETRIES", 2)
    conf_thresh = confidence_threshold or getattr(settings, "TABLE_CONFIDENCE_THRESHOLD", 0.7)

    # ---- Step 0: Load image(s) ----
    pages = _load_pages(file_bytes, filename, mime_type)
    all_tables: List[ExtractedTable] = []

    for page_idx, page_image in enumerate(pages):
        page_tables = await _process_single_page(
            page_image=page_image,
            page_num=page_idx + 1,
            backend=backend,
            dpi=dpi,
            retries=retries,
            conf_thresh=conf_thresh,
            output_format=output_format,
            filename=filename,
        )
        all_tables.extend(page_tables)

    return all_tables


async def extract_table_from_image(
    image: Image.Image,
    *,
    output_format: str = "markdown",
) -> List[ExtractedTable]:
    """Convenience wrapper for a single PIL Image."""
    backend = getattr(settings, "TABLE_DETECTOR_BACKEND", "opencv")
    dpi = getattr(settings, "TABLE_PREPROCESS_TARGET_DPI", 300)
    retries = getattr(settings, "TABLE_SELF_CORRECTION_MAX_RETRIES", 2)
    conf_thresh = getattr(settings, "TABLE_CONFIDENCE_THRESHOLD", 0.7)

    return await _process_single_page(
        page_image=image,
        page_num=1,
        backend=backend,
        dpi=dpi,
        retries=retries,
        conf_thresh=conf_thresh,
        output_format=output_format,
        filename="direct_image",
    )


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

async def _process_single_page(
    page_image: Image.Image,
    page_num: int,
    backend: str,
    dpi: int,
    retries: int,
    conf_thresh: float,
    output_format: str,
    filename: str,
) -> List[ExtractedTable]:
    """Run the full pipeline on a single page / image."""

    # ---- Stage 1: Detect tables ----
    detection = detect_tables(
        page_image,
        backend=backend,
        confidence_threshold=conf_thresh,
    )
    table_crops = crop_tables(page_image, detection)

    # If no tables detected, return empty (don't force full page text into a table)
    if not table_crops:
        logger.info("No tables detected on page %d; skipping table extraction", page_num)
        return []

    results: List[ExtractedTable] = []
    preprocess_config = PreprocessConfig(target_dpi=dpi)

    for table_idx, (crop, bbox) in enumerate(zip(table_crops, detection.bboxes)):
        # ---- Stage 2: Preprocess ----
        preprocessed = preprocess_for_ocr(crop, config=preprocess_config)

        # ---- Stage 3: OCR ----
        ocr_result = await _run_typhoon_ocr(preprocessed, output_format)
        headers = ocr_result.get("headers", [])
        rows = ocr_result.get("rows", [])

        if not headers and not rows:
            logger.warning(
                "No table data from OCR on page %d, table %d", page_num, table_idx,
            )
            continue

        # ---- Stage 4: Validate & self-correct ----
        async def _retry_ocr(img_bytes: bytes, mime: str) -> Dict[str, Any]:
            img = Image.open(io.BytesIO(img_bytes))
            preprocessed_retry = preprocess_for_ocr(img, config=preprocess_config)
            return await _run_typhoon_ocr(preprocessed_retry, output_format)

        validated = await validate_and_correct(
            headers=headers,
            rows=rows,
            original_image=crop,
            table_bbox=bbox,
            ocr_fn=_retry_ocr,
            max_retries=retries,
            output_format=output_format,
        )

        # ---- Stage 5: Thai normalisation ----
        normalised = normalize_thai_table(validated.headers, validated.rows)

        # Build CSV
        csv_text = _build_csv(normalised.headers, normalised.rows)

        results.append(ExtractedTable(
            headers=normalised.headers,
            rows=normalised.rows,
            csv_text=csv_text,
            confidence_score=validated.report.confidence_score,
            metadata={
                "page": page_num,
                "table_index": table_idx,
                "bbox": {"x0": bbox.x0, "y0": bbox.y0, "x1": bbox.x1, "y1": bbox.y1},
                "detector_backend": backend,
                "detector_confidence": bbox.confidence,
                "retry_count": validated.retry_count,
                "corrections_applied": normalised.corrections_applied,
                "validation_issues": len(validated.report.issues),
            },
        ))

    return results


# ---------------------------------------------------------------------------
# OCR integration
# ---------------------------------------------------------------------------

async def _run_typhoon_ocr(
    image: Image.Image,
    output_format: str = "markdown",
) -> Dict[str, Any]:
    """Send a preprocessed image to Typhoon OCR and parse the result.

    This wraps the existing ``TyphoonOCRService`` but attaches structured
    prompts.  The raw Typhoon SDK does not support custom system prompts
    directly, so we feed the image through the standard endpoint and
    parse the Markdown/JSON output ourselves.
    """
    import asyncio
    import os

    from backend.services.ocr import TyphoonOCRService

    service = TyphoonOCRService()

    # Save preprocessed image to a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        image.save(tmp, format="PNG")
        tmp_path = tmp.name

    try:
        markdown = await asyncio.to_thread(service._ocr_single_page, tmp_path, 1)
        parsed = service._parse_markdown_pages([{"page": 1, "markdown": markdown}])

        tables = parsed.get("tables", [])
        if tables:
            first = tables[0]
            return {
                "headers": first.get("headers", []),
                "rows": first.get("rows", []),
                "all_tables": tables,
            }

        # Fallback: try extracting from text
        return {"headers": [], "rows": [], "all_tables": []}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_pages(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
) -> List[Image.Image]:
    """Load file bytes as a list of PIL Images (one per page)."""
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return _pdf_to_images(file_bytes)
    else:
        return [Image.open(io.BytesIO(file_bytes)).convert("RGB")]


def _pdf_to_images(pdf_bytes: bytes) -> List[Image.Image]:
    """Convert each PDF page to a PIL Image."""
    try:
        import fitz  # PyMuPDF
        import io
        from PIL import Image
        
        images = []
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        zoom_matrix = fitz.Matrix(300 / 72, 300 / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=zoom_matrix)
            img_data = pix.tobytes("png")
            images.append(Image.open(io.BytesIO(img_data)).convert("RGB"))
        doc.close()
        return images
    except ImportError:
        pass

    # Fallback: use pypdf to extract the first embedded image per page
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    images: List[Image.Image] = []

    for page in reader.pages:
        if "/XObject" in (page.get("/Resources") or {}):
            x_objects = page["/Resources"]["/XObject"].get_object()
            for obj_name in x_objects:
                obj = x_objects[obj_name].get_object()
                if obj.get("/Subtype") == "/Image":
                    try:
                        data = obj.get_data()
                        img = Image.open(io.BytesIO(data)).convert("RGB")
                        images.append(img)
                        break
                    except Exception:
                        continue

    return images if images else []


def _build_csv(headers: List[str], rows: List[List[str]]) -> str:
    """Build a CSV string from headers and rows."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    if headers:
        writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().strip()
