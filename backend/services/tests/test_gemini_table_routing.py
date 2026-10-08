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


def test_empty_audit_status_tier_keeps_values_dates_and_statement_scope():
    raw = {'tables':[{'columns':['2566 งบรวม','2566 ตรวจสอบ','2567 งบรวม','2567 ตรวจสอบ'],
        'rows':[{'row_label':'เงินสด (ล้านบาท)','values':['10','','20','']},
                {'row_label':'สินทรัพย์ (ล้านบาท)','values':['30','','40','']}]}]}
    table = _normalize_gemini_tables(raw, 7, {'region':'full'})[0]
    assert table['headers'] == ['รายการ','2566 งบรวม ตรวจสอบ','2567 งบรวม ตรวจสอบ']
    assert table['rows'] == [['เงินสด (ล้านบาท)','10','20'],['สินทรัพย์ (ล้านบาท)','30','40']]
    assert len(table['header_repairs']) == 2
    assert raw['tables'][0]['rows'][0]['values'] == ['10','','20','']


def test_nonempty_status_different_date_and_real_statement_columns_are_not_collapsed():
    for columns, values in [(['2566 งบรวม','2566 ตรวจสอบ'],['10','5']),
                            (['2566 งบรวม','2567 ตรวจสอบ'],['10','']),
                            (['2566 งบรวม','2566 งบเฉพาะกิจการ'],['10',''])]:
        raw={'tables':[{'columns':columns,'rows':[{'row_label':'เงินสด','values':values}]}]}
        table=_normalize_gemini_tables(raw,7,{'region':'full'})[0]
        assert table['rows']==[['เงินสด',*values]] and 'header_repairs' not in table


def test_actual_gemini_sdk_request_uses_complete_structured_table_schema():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from backend.scripts.reocr_tables import _read_page_once, TABLE_RESPONSE_SCHEMA
    model = Mock(return_value=SimpleNamespace(text='{"tables":[]}', usage_metadata=None))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=model))
    result = _read_page_once(client, 'configured-model', _png())
    assert result['tables'] == []
    config = model.call_args.kwargs['config']
    assert config.response_schema == TABLE_RESPONSE_SCHEMA
    assert config.response_mime_type == 'application/json'
    assert config.temperature == 0


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
