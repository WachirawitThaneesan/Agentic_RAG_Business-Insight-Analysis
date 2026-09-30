"""Persistent Docling worker for private PDF pages (JSON lines over stdio)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from backend.services.offline_network import install_offline_network_guard

install_offline_network_guard()

MARKER = "__LOCAL_OCR_RESULT__"


def _converter():
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        EasyOcrOptions, OcrMode, PdfPipelineOptions, TableFormerMode,
        TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    models_dir = Path(os.environ["LOCAL_OCR_MODELS_DIR"])
    pipeline = PdfPipelineOptions(artifacts_path=models_dir)
    pipeline.accelerator_options = AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CPU)
    pipeline.do_ocr = True
    pipeline.ocr_options = EasyOcrOptions(
        lang=["th", "en"], mode=OcrMode.FULL_PAGE,
        use_gpu=False, download_enabled=False,
    )
    pipeline.do_table_structure = True
    pipeline.table_structure_options = TableStructureOptions(
        do_cell_matching=True, mode=TableFormerMode.ACCURATE,
    )
    pipeline.enable_remote_services = False
    pipeline.allow_external_plugins = False
    return DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline),
    })


def _convert(converter, filepath: str, page: int) -> dict:
    result = converter.convert(filepath, page_range=(page, page))
    doc = result.document
    if doc is None:
        raise RuntimeError(f"Docling returned no document for page {page}: {result.status}")

    tables = []
    for index, table in enumerate(doc.tables):
        grid = table.data.grid
        matrix = [[str(cell.text or "").strip() for cell in row] for row in grid]
        if len(matrix) < 2 or not any(cell for row in matrix[1:] for cell in row):
            continue
        tables.append({
            "page": page,
            "title": f"page_{page}_table_{index}",
            "headers": matrix[0],
            "rows": matrix[1:],
            "source_provider": "docling_local",
        })

    markdown = doc.export_to_markdown()
    text_blocks = [str(item.text).strip() for item in doc.texts if str(item.text or "").strip()]
    return {
        "raw_pages": [{"page": page, "region": "full", "markdown": markdown}],
        "pages": [{"page": page, "markdown": markdown,
                   "text_blocks": len(text_blocks), "tables": len(tables)}],
        "text_blocks": text_blocks,
        "tables": tables,
        "raw_tables": [dict(table) for table in tables],
        "table_extraction_warnings": [],
        "errors": [],
    }


def main() -> None:
    converter = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if converter is None:
                converter = _converter()
            payload = {"ok": True, "result": _convert(
                converter, request["filepath"], int(request["page"]),
            )}
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(MARKER + json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
