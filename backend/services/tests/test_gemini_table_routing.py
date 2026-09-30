"""The configured text/table providers must feed distinct, traceable content."""

from __future__ import annotations

import asyncio
import io
from unittest.mock import AsyncMock, patch

from PIL import Image

from backend.services.gemini_tables import _normalize_gemini_tables
from backend.services.ocr import TyphoonOCRService


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 120), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _gemini_table(page: int = 1) -> dict:
    return {"title": "รายได้ (หน่วย: ล้านบาท)", "headers": ["รายการ", "2568"],
            "rows": [["ธุรกิจการเงิน", "254.29"]], "page": page,
            "source_provider": "gemini", "region": "full"}


def test_gemini_json_preserves_row_column_and_unit():
    data = {"tables": [{"title": "รายได้", "unit": "ล้านบาท",
                        "columns": ["รายการ", "2568"],
                        "rows": [{"row_label": "ธุรกิจการเงิน", "values": ["254.29"]}]}]}
    tables = _normalize_gemini_tables(data, 5, {"region": "left"})
    assert tables[0]["headers"] == ["รายการ", "2568"]
    assert tables[0]["rows"] == [["ธุรกิจการเงิน", "254.29"]]
    assert tables[0]["page"] == 5
    assert tables[0]["region"] == "left"
    assert "ล้านบาท" in tables[0]["title"]
    assert tables[0]["unit"] == "ล้านบาท"


def test_gemini_json_quarantines_unequal_row_widths():
    data = {"tables": [{"columns": ["รายการ", "2568", "2567"], "rows": [
        {"row_label": "A", "values": ["1", "2"]},
        {"row_label": "B", "values": ["3"]},
    ]}]}
    tables = _normalize_gemini_tables(data, 1, {"region": "full"})
    assert tables[0]["rows"][0] == ["A", "1", "2"]
    assert tables[0]["rows"][1] == ["B [UNRESOLVED WIDTH]", "", ""]
    assert tables[0]["ambiguous_row_count"] == 1


def test_pdf_ocr_uses_typhoon_prose_and_gemini_table():
    service = TyphoonOCRService()
    service.api_key = "test"
    markdown = "คำอธิบายบริษัท\n<table><tr><th>รายการ</th><th>2568</th></tr><tr><td>ธุรกิจการเงิน</td><td>999</td></tr></table>"
    with patch("backend.services.ocr.settings.PDF_TABLE_OCR_PROVIDER", "gemini"), \
         patch.object(service, "_render_pdf_page_to_png", return_value=_png()), \
         patch("backend.services.ocr.plan_pdf_regions", return_value=[
             {"region": "full", "crop_box": [0, 0, 1, 1], "rotation": 0}]), \
         patch("backend.services.gemini_tables.image_has_table_hint", return_value=False), \
         patch.object(service, "_ocr_png_bytes_async", new_callable=AsyncMock, return_value=markdown), \
         patch("backend.services.gemini_tables.extract_tables_from_png", new_callable=AsyncMock,
               return_value=([_gemini_table(5)], {"input_tokens": 10, "output_tokens": 20})):
        result = asyncio.run(service.extract_from_pdf_path("unused.pdf", pages=[5]))
    assert result["tables"][0]["rows"] == [["ธุรกิจการเงิน", "254.29"]]
    assert "999" not in result["raw_pages"][0]["markdown"]
    assert "คำอธิบายบริษัท" in result["raw_pages"][0]["markdown"]
    assert result["gemini_table_usage"][0]["page"] == 5


def test_visual_table_can_be_recovered_after_typhoon_timeout():
    service = TyphoonOCRService()
    service.api_key = "test"
    with patch("backend.services.ocr.settings.PDF_TABLE_OCR_PROVIDER", "gemini"), \
         patch("backend.services.gemini_tables.image_has_table_hint", return_value=True), \
         patch.object(service, "_ocr_png_bytes_async", new_callable=AsyncMock,
                      side_effect=TimeoutError("text timed out")), \
         patch("backend.services.gemini_tables.extract_tables_from_png", new_callable=AsyncMock,
               return_value=([_gemini_table()], {"input_tokens": 10, "output_tokens": 20})):
        result = asyncio.run(service.extract_from_image(_png()))
    assert result["tables"][0]["source_provider"] == "gemini"
    assert result["typhoon_text_errors"]
    assert result["raw_pages"][0]["markdown"] == ""
