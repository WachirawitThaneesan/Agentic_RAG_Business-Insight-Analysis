"""Regression tests for value-level OCR uncertainty decisions."""

import asyncio
from unittest.mock import AsyncMock

from pypdf import PdfWriter

import backend.routes.documents as documents

from backend.services.financial_quality import assess_table, parse_number, reconcile_retry
from backend.routes.documents import _assess_ocr_tables


HEADERS = ["รายการ", "2568", "2567", "การเปลี่ยนแปลง (จำนวน)", "การเปลี่ยนแปลง (%)"]


def test_accounting_numbers_and_placeholders():
    assert parse_number("(10,852)") == -10852
    assert parse_number("14.75") == 14.75
    assert parse_number("-") is None
    assert parse_number("6O,240") is None
    assert parse_number("20%3") is None


def test_correct_financial_row_passes_consistency_checks():
    table = {"headers": HEADERS, "rows": [["รายได้ที่มิใช่ดอกเบี้ย", "57,648", "50,240", "7,408", "14.75"]]}
    report = assess_table(table)
    assert report["status"] == "passed_checks"
    assert report["unresolved_rows"] == 0
    assert report["accepted_rows"] == table["rows"]


def test_wrong_ocr_digit_is_unresolved_not_silently_corrected():
    table = {"headers": HEADERS, "rows": [["รายได้ที่มิใช่ดอกเบี้ย", "57,648", "60,240", "7,408", "14.75"]]}
    report = assess_table(table)
    assert report["status"] == "unresolved"
    assert report["accepted_rows"] == []
    assert "reported_change_disagrees_with_years" in report["row_reports"][0]["reasons"]
    assert "reported_percent_disagrees_with_years" in report["row_reports"][0]["reasons"]


def test_second_known_misread_is_unresolved():
    table = {"headers": HEADERS, "rows": [["กำไรสุทธิ", "49,585", "49,604", "(39)", "(0.08)"]]}
    report = assess_table(table)
    assert report["unresolved_rows"] == 1
    assert report["accepted_rows"] == []


def test_identical_wrong_values_cannot_be_proven_correct_by_arithmetic():
    table = {"headers": HEADERS, "rows": [["กำไรต่อหุ้น", "20.83", "20.83", "-", "-"]]}
    report = assess_table(table)
    assert report["status"] == "unverified"
    assert report["unresolved_rows"] == 0


def test_chart_legend_pseudotable_is_quarantined():
    table = {
        "headers": ["รายการ", "31 ธ.ค. 2568", "31 ธ.ค. 2567", "column_4"],
        "rows": [["", "สินทรัพย์อื่น", "เงินสด", "หนี้สินอื่น"], ["", "ร้อยละ", "ร้อยละ", "ร้อยละ"]],
    }
    report = assess_table(table)
    assert report["chart_like"] is True
    assert report["unresolved_rows"] == 2
    assert report["accepted_rows"] == []


def test_numeric_row_with_no_label_is_unresolved():
    table = {"headers": HEADERS, "rows": [["", "58", "91", "(33)", "(36.84)"]]}
    report = assess_table(table)
    assert report["unresolved_rows"] == 1


def test_plain_table_is_unverified_not_automatically_rejected():
    table = {"headers": ["รายการ", "จำนวน"], "rows": [["พนักงาน", "3,200"]]}
    report = assess_table(table)
    assert report["status"] == "unverified"
    assert report["accepted_rows"] == table["rows"]


def test_single_year_spanning_header_does_not_reject_attendance_fraction():
    table = {"headers": ["director", "Compensation 2568", "total amount"],
             "rows": [["Director A", "4/4", "390,000"]]}
    report = assess_table(table)
    assert report["status"] == "unverified"
    assert report["unresolved_rows"] == 0


def test_percentage_point_change_is_not_treated_as_relative_growth():
    table = {"headers": HEADERS, "rows": [["อัตราผลตอบแทน (ร้อยละ)", "4.08", "4.58", "", "(0.50)"]]}
    report = assess_table(table)
    assert report["status"] == "passed_checks"
    assert report["unresolved_rows"] == 0


def test_ingestion_filter_keeps_raw_report_but_excludes_bad_row():
    table = {
        "page": 1,
        "table_name": "example_page_1_table_0",
        "headers": HEADERS,
        "rows": [
            ["รายได้ดอกเบี้ยสุทธิ", "137,152", "148,004", "(10,852)", "(7.33)"],
            ["รายได้ที่มิใช่ดอกเบี้ย", "57,648", "60,240", "7,408", "14.75"],
        ],
    }
    accepted, reports = _assess_ocr_tables([table])
    assert len(accepted) == 1
    assert accepted[0]["source_row_indices"] == [0]
    assert len(accepted[0]["rows"]) == 1
    assert "60,240" not in accepted[0]["csv_text"]
    assert reports[0]["unresolved_rows"] == 1
    assert reports[0]["row_reports"][1]["cells"][1]["value"] == "60,240"


def test_retry_can_replace_one_consistent_cell_but_not_multiple_changes():
    first = {"table_name": "report_page_1_table_0", "headers": HEADERS,
             "rows": [["รายได้", "57,648", "60,240", "7,408", "14.75"]]}
    fixed = {**first, "rows": [["รายได้", "57,648", "50,240", "7,408", "14.75"]]}
    merged, changes = reconcile_retry([first], [fixed])
    assert merged[0]["rows"] == fixed["rows"]
    assert changes[0]["first_value"] == "60,240"
    assert changes[0]["retry_value"] == "50,240"

    two_changes = {**first, "rows": [["รายได้", "57,648", "50,240", "7,408", "14.74"]]}
    merged, changes = reconcile_retry([first], [two_changes])
    assert merged[0]["rows"] == first["rows"]
    assert {change["status"] for change in changes} == {"ocr_passes_disagree_unresolved"}
    assert assess_table(merged[0])["unresolved_rows"] == 1


def test_unverified_value_disagreement_is_quarantined_not_silently_selected():
    first = {"table_name": "eps", "headers": ["metric", "2568", "2567"],
             "rows": [["EPS", "20.83", "20.83"]]}
    retry = {**first, "rows": [["EPS", "20.63", "20.83"]]}
    merged, changes = reconcile_retry([first], [retry])
    assert merged[0]["rows"] == first["rows"]
    assert changes[0]["status"] == "ocr_passes_disagree_unresolved"
    report = assess_table(merged[0])
    assert report["accepted_rows"] == []
    assert report["row_reports"][0]["reasons"] == ["ocr_passes_disagree"]
    accepted, reports = _assess_ocr_tables(merged, retry_changes=changes)
    assert accepted == []
    assert reports[0]["retry_changes"][0]["status"] == "ocr_passes_disagree_unresolved"


def test_contradictory_pdf_page_triggers_one_high_dpi_retry(monkeypatch, tmp_path):
    source = tmp_path / "one_page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as target:
        writer.write(target)
    first = {"page": 1, "title": "financial", "headers": HEADERS,
             "rows": [["revenue", "57,648", "60,240", "7,408", "14.75"]]}
    fixed = {**first, "rows": [["revenue", "57,648", "50,240", "7,408", "14.75"]]}
    retry = AsyncMock(return_value={"tables": [fixed], "raw_pages": [{"page": 1, "markdown": "retry"}]})
    monkeypatch.setattr(documents.settings, "PDF_QUALITY_REOCR_ENABLED", True)
    monkeypatch.setattr(documents.ocr_service, "extract_from_pdf_path", retry)

    merged, raw_retry, changes, note = asyncio.run(documents._retry_inconsistent_pdf_tables(
        str(source), "5Page_Test.pdf", 1, {"tables": [first]},
    ))
    assert note == "retried"
    assert raw_retry["raw_pages"][0]["markdown"] == "retry"
    assert merged[0]["rows"][0][2] == "50,240"
    assert len(changes) == 1
    assert retry.await_args.kwargs["render_dpi"] > documents.ocr_service.render_dpi


def test_consistent_pdf_page_does_not_spend_retry_call(monkeypatch):
    first = {"page": 1, "title": "financial", "headers": HEADERS,
             "rows": [["revenue", "57,648", "50,240", "7,408", "14.75"]]}
    retry = AsyncMock()
    monkeypatch.setattr(documents.settings, "PDF_QUALITY_REOCR_ENABLED", True)
    monkeypatch.setattr(documents.ocr_service, "extract_from_pdf_path", retry)
    _, _, changes, note = asyncio.run(documents._retry_inconsistent_pdf_tables(
        "not_read_when_unneeded.pdf", "report.pdf", 1, {"tables": [first]},
    ))
    assert note == "not_needed"
    assert changes == []
    retry.assert_not_awaited()


def test_raw_ocr_audit_artifacts_are_not_search_embeddings(monkeypatch):
    class CollectingSession:
        def __init__(self):
            self.added = []

        def add(self, item):
            self.added.append(item)

    db = CollectingSession()
    embedding = AsyncMock(side_effect=AssertionError("raw OCR should not be embedded"))
    monkeypatch.setattr(documents, "get_embedding", embedding)
    payload = {"text": "RAW_OCR_TABLE: wrong value 60,240", "metadata": {"source_kind": "raw_ocr_table"}}
    created = asyncio.run(documents._store_artifact_chunks(db, 1, [payload], 0))
    assert created == 1
    assert db.added[0].embedding is None
    embedding.assert_not_awaited()
