"""Regression tests for PDF page provenance and malformed OCR tables."""

from __future__ import annotations

import io
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import duckdb
from PIL import Image

from backend.services.ocr import TyphoonOCRService
from backend.services.table_utils import normalize_ocr_tables
from backend.services import duckdb_warehouse
from backend.routes.documents import _effective_document_status, _extract_doc_runtime_info


FINANCIAL_HTML = """
<table><tr><th rowspan="2"><th colspan="2">ปี 2567<th colspan="2">การเปลี่ยนแปลง</th></th></th></tr>
<tr><td>(ปรับปรุงใหม่)</td><td>เพิ่ม (ลด)</td><td>ร้อยละ</td></tr>
<tr><td>รายได้ดอกเบี้ยสุทธิ</td><td>137,152</td><td>148,004</td><td>(10,852)</td><td>(7.33)</td></tr>
</table>
"""


def _parse_financial(page: int = 1):
    service = TyphoonOCRService()
    markdown = f"สรุปผลการดำเนินงาน ปี 2568\n\n{FINANCIAL_HTML}"
    result = service._parse_markdown_pages([{"page": page, "markdown": markdown}])
    return result, normalize_ocr_tables("report.pdf", result["tables"])


def test_malformed_financial_html_preserves_all_columns_and_page():
    result, tables = _parse_financial(page=7)
    assert result["raw_pages"][0]["page"] == 7
    assert result["raw_tables"][0]["page"] == 7
    assert len(tables) == 1
    assert tables[0]["page"] == 7
    assert tables[0]["headers"] == [
        "รายการ", "2568", "2567", "การเปลี่ยนแปลง (จำนวน)", "การเปลี่ยนแปลง (%)",
    ]
    assert tables[0]["rows"][0] == [
        "รายได้ดอกเบี้ยสุทธิ", "137,152", "148,004", "(10,852)", "(7.33)",
    ]


def test_same_title_on_different_pages_has_distinct_table_names():
    _, first = _parse_financial(page=1)
    _, second = _parse_financial(page=2)
    assert first[0]["table_name"] != second[0]["table_name"]
    assert "page_1_table_0" in first[0]["table_name"]
    assert "page_2_table_0" in second[0]["table_name"]


def test_multiple_header_rows_preserve_wide_table():
    service = TyphoonOCRService()
    markdown = (
        "<table><tr><th rowspan='2'>ระยะเวลา<th colspan='2'>เงินรับฝาก</th></tr>"
        "<tr><td>31 ธ.ค. 2568</td><td>ร้อยละ</td></tr>"
        "<tr><td>≤ 1 ปี</td><td>2,785,465</td><td>97.72</td></tr></table>"
    )
    result = service._parse_markdown_pages([{"page": 3, "markdown": markdown}])
    tables = normalize_ocr_tables("report.pdf", result["tables"])
    assert tables[0]["headers"] == ["ระยะเวลา", "31 ธ.ค. 2568", "ร้อยละ"]
    assert tables[0]["rows"] == [["≤ 1 ปี", "2,785,465", "97.72"]]


def test_image_ocr_accepts_pdf_page_number():
    service = TyphoonOCRService()
    service.api_key = "test-key"
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
    with patch.object(service, "_ocr_png_bytes_async", new_callable=AsyncMock, return_value="Page text"):
        result = asyncio.run(service.extract_from_image(buffer.getvalue(), page_number=9))
    assert result["raw_pages"] == [{"page": 9, "markdown": "Page text"}]


def test_pdf_page_has_wall_clock_deadline():
    service = TyphoonOCRService()
    service.api_key = "test-key"
    service.page_timeout_seconds = 0.01

    async def stall(_png):
        await asyncio.sleep(1)
        return "never returned"

    with patch.object(service, "_render_pdf_page_to_png", return_value=b"png"), patch.object(service, "_ocr_png_bytes_async", side_effect=stall):
        try:
            asyncio.run(service.extract_from_pdf_path("dummy.pdf", pages=[1]))
        except TimeoutError:
            pass
        else:
            raise AssertionError("stalled page OCR did not time out")


def test_prompt_echo_is_not_treated_as_document_text():
    service = TyphoonOCRService()
    echoed = "Extract all text from the image.\nFormatting Rules:\n- Tables: Render tables using HTML."
    try:
        service._validate_markdown(echoed)
    except RuntimeError as exc:
        assert "echoed the instruction prompt" in str(exc)
    else:
        raise AssertionError("prompt echo was accepted as OCR text")


def test_financial_tables_load_as_facts_without_overwriting(monkeypatch):
    conn = duckdb.connect(":memory:")
    duckdb_warehouse._init_schema(conn)
    monkeypatch.setattr(duckdb_warehouse, "_get_conn", lambda: conn)
    try:
        _, first = _parse_financial(page=1)
        _, second = _parse_financial(page=2)
        for table in [first[0], second[0]]:
            duckdb_warehouse.load_table_into_warehouse(
                99, table["table_name"], table["headers"], table["rows"], title=table["title"],
            )
        facts = conn.execute(
            "SELECT table_name, metric_year, numeric_value FROM fact_financial_metrics "
            "WHERE document_id = 99 ORDER BY table_name, metric_year"
        ).fetchall()
        assert len(facts) == 4
        assert {fact[1] for fact in facts} == {"2568", "2567"}
        assert {fact[2] for fact in facts} == {137152.0, 148004.0}
        duckdb_warehouse.delete_document_data(99)
        assert conn.execute("SELECT COUNT(*) FROM fact_financial_metrics WHERE document_id = 99").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM dim_tables WHERE document_id = 99").fetchone()[0] == 0
    finally:
        conn.close()


def test_page_status_and_legacy_warning_are_not_reported_complete():
    legacy = SimpleNamespace(status="completed", error_message="Partial OCR warnings: Failed pages: 3, 4 | Failed page reasons: 3=page 3:; 4=page 4:")
    assert _effective_document_status(legacy) == "partial"

    current = SimpleNamespace(status="completed", error_message=None)
    pages = [
        SimpleNamespace(page_number=1, status="indexed", error_stage=None, error_message=None),
        SimpleNamespace(page_number=2, status="failed", error_stage="indexing", error_message="UnicodeEncodeError"),
    ]
    assert _effective_document_status(current, pages) == "partial"
    runtime = _extract_doc_runtime_info(current, pages)
    assert runtime["failed_pages"] == [2]
    assert runtime["failed_page_reasons"][2] == "indexing: UnicodeEncodeError"
