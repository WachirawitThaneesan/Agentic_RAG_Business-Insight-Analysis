"""Regression checks for shared ingestion and traceable answer evidence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import duckdb
from sqlalchemy.dialects import postgresql

from backend.services import agent, document_jobs, duckdb_warehouse, rag, scraper


def test_scraped_pdf_uses_saved_upload_job(monkeypatch, tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4\nexample")
    destination = tmp_path / "saved" / "7.pdf"
    destination.parent.mkdir()

    class Session:
        doc = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def add(self, doc):
            self.doc = doc

        async def commit(self):
            if self.doc is not None:
                self.doc.id = 7

        async def refresh(self, _doc):
            pass

    session = Session()
    prepare = AsyncMock(return_value=2)
    monkeypatch.setattr(scraper, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(document_jobs, "saved_upload_path", lambda *_args: destination)
    monkeypatch.setattr(document_jobs, "prepare_pdf_job", prepare)

    result = asyncio.run(scraper._ingest_scraped_file(str(source), "https://example.org/report"))

    assert result["queued"] is True
    assert result["page_count"] == 2
    assert destination.read_bytes() == source.read_bytes()
    assert session.doc.source_url == "https://example.org/report"
    assert session.doc.status == "pending"
    prepare.assert_awaited_once_with(session, session.doc, destination)


def test_pdf_job_preparation_creates_page_checkpoints_before_queue(monkeypatch, tmp_path):
    path = tmp_path / "saved.pdf"
    path.write_bytes(b"sample")
    calls = []

    class Session:
        def add_all(self, pages):
            calls.append(("pages", list(pages)))

        async def commit(self):
            calls.append(("commit", None))

    from backend.services.ocr import ocr_service
    monkeypatch.setattr(ocr_service, "get_pdf_page_count", lambda _path: 3)
    monkeypatch.setattr(document_jobs, "enqueue_pdf_job", lambda doc_id: calls.append(("queue", doc_id)))
    count = asyncio.run(document_jobs.prepare_pdf_job(Session(), SimpleNamespace(id=7), path))
    assert count == 3
    assert [page.page_number for page in calls[0][1]] == [1, 2, 3]
    assert [call[0] for call in calls] == ["pages", "commit", "queue"]


def test_raw_ocr_and_quality_artifacts_are_not_answer_sources():
    for kind in ("raw_ocr_page", "raw_ocr_table", "raw_ocr_retry_page",
                 "table_quality", "table_partial", "table_extraction_warning"):
        assert not rag._is_answer_source(SimpleNamespace(metadata_={"source_kind": kind}))
    assert rag._is_answer_source(SimpleNamespace(metadata_={"source_kind": "table_csv"}))
    assert rag._is_answer_source(SimpleNamespace(metadata_={"page": 2}))


def test_search_does_not_return_legacy_embedded_raw_ocr(monkeypatch):
    raw = SimpleNamespace(id=1, chunk_text="Revenue 999", summary="", chunk_index=0,
                          document_id=7, metadata_={"source_kind": "raw_ocr_page", "page": 46})
    trusted = SimpleNamespace(id=2, chunk_text="Revenue 100", summary="", chunk_index=1,
                              document_id=7, metadata_={"source_kind": "table_csv", "page": 46})

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class Session:
        calls = 0
        statements = []

        async def execute(self, stmt):
            self.calls += 1
            self.statements.append(stmt)
            if self.calls == 1:
                rows = [(7, "report.pdf")]
            elif self.calls == 2:
                rows = [(raw, "report.pdf", 0.1), (trusted, "report.pdf", 0.2)]
            else:
                rows = [(raw, "report.pdf"), (trusted, "report.pdf")]
            return Result(rows)

    monkeypatch.setattr(rag, "get_embedding", AsyncMock(return_value=[0.0] * 1024))
    session = Session()
    results = asyncio.run(rag.vector_search("Revenue", session, top_k=5))
    assert [item["chunk_id"] for item in results] == [2]
    assert results[0]["page"] == 46
    for stmt in session.statements[1:]:
        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "document_pages.status" in sql
        assert any(value == "source_kind" for value in compiled.params.values())


def test_sql_evidence_requires_unambiguous_document_page(monkeypatch):
    conn = duckdb.connect(":memory:")
    duckdb_warehouse._init_schema(conn)
    monkeypatch.setattr(duckdb_warehouse, "_get_conn", lambda: conn)
    duckdb_warehouse.load_document_dim(7, "report.pdf", source_url="https://example.org/report")
    duckdb_warehouse.load_document_dim(8, "other.pdf")
    duckdb_warehouse.load_table_into_warehouse(
        7, "page_46_table_0", ["Item", "2568"], [["Revenue", "100"]],
        source_page=46, quality_status="unverified")
    duckdb_warehouse.load_table_into_warehouse(
        7, "shared", ["Item", "2568"], [["Ambiguous", "20"]], source_page=3)
    duckdb_warehouse.load_table_into_warehouse(
        8, "shared", ["Item", "2568"], [["Ambiguous", "20"]], source_page=2)

    evidence = duckdb_warehouse.resolve_result_evidence([
        {"document_id": 7, "table_name": "page_46_table_0", "row_label": "Revenue", "metric_year": "2568", "raw_value": "100"},
        {"table_name": "shared", "row_label": "Ambiguous"},
        {"row_label": "Aggregate", "numeric_value": 10},
        {"document_id": 7, "table_name": "page_46_table_0", "row_label": "Costs",
         "metric_year": "2568", "raw_value": "100"},
    ])

    assert len(evidence) == 1
    assert evidence[0]["document_id"] == 7
    assert evidence[0]["page"] == 46
    assert evidence[0]["column"] == "2568"
    assert evidence[0]["quality_status"] == "unverified"
    assert evidence[0]["evidence_status"] == "ocr_extracted_unverified"
    conn.close()


def test_warehouse_keeps_page_and_quality_on_new_table(monkeypatch):
    conn = duckdb.connect(":memory:")
    duckdb_warehouse._init_schema(conn)
    monkeypatch.setattr(duckdb_warehouse, "_get_conn", lambda: conn)
    duckdb_warehouse.load_document_dim(7, "report.pdf", source_url="https://example.org/report")
    duckdb_warehouse.load_table_into_warehouse(
        7, "report_page_46_table_0", ["Item", "2568"], [["Revenue", "100"]],
        source_page=46, quality_status="passed_checks",
    )
    result = duckdb_warehouse.execute_sql(
        "SELECT document_id, table_name, row_label, metric_year, raw_value FROM fact_financial_metrics"
    )
    assert result["row_count"] == 1
    evidence = duckdb_warehouse.resolve_result_evidence(result["rows"])
    assert evidence[0]["page"] == 46
    assert evidence[0]["quality_status"] == "passed_checks"
    assert evidence[0]["source_url"] == "https://example.org/report"
    conn.close()


def test_warehouse_cells_keep_gemini_row_column_unit_and_page(monkeypatch):
    conn = duckdb.connect(":memory:")
    duckdb_warehouse._init_schema(conn)
    monkeypatch.setattr(duckdb_warehouse, "_get_conn", lambda: conn)
    duckdb_warehouse.load_document_dim(9, "thai.pdf")
    duckdb_warehouse.load_table_into_warehouse(
        9, "p244_balance", ["รายการ", "2567", "2566"],
        [["หนี้สินรวม", "136,422,456", "120,000,000"]],
        source_page=244, quality_status="passed_checks", source_provider="gemini",
        unit="พันบาท", row_indices=[17])
    cell = conn.execute("""
        SELECT row_label, metric_year, raw_value, unit, source_page, row_index,
               quality_status, source_provider FROM fact_financial_metrics
        WHERE metric_year = '2567'
    """).fetchone()
    assert cell == ("หนี้สินรวม", "2567", "136,422,456", "พันบาท", 244, 17,
                    "passed_checks", "gemini")
    evidence = duckdb_warehouse.resolve_result_evidence([{
        "document_id": 9, "table_name": "p244_balance", "row_label": "หนี้สินรวม",
        "metric_year": "2567", "raw_value": "136,422,456"}])
    assert evidence[0]["page"] == 244
    assert evidence[0]["unit"] == "พันบาท"
    assert evidence[0]["row_index"] == 17
    assert not duckdb_warehouse.resolve_result_evidence([{
        "document_id": 9, "table_name": "p244_balance", "row_label": "สินทรัพย์รวม",
        "metric_year": "2567", "raw_value": "136,422,456"}])
    duckdb_warehouse.load_table_into_warehouse(
        9, "p45_holdings", ["บริษัท", "สัดส่วน (%)"], [["ไซยะบุรี เพาเวอร์", "12.50"]],
        source_page=45, source_provider="gemini", row_indices=[3])
    lookup = conn.execute("""
        SELECT row_label, col_name, col_value, unit, source_page, row_index
        FROM dim_table_rows WHERE table_name = 'p45_holdings'
    """).fetchone()
    assert lookup == ("ไซยะบุรี เพาเวอร์", "สัดส่วน (%)", "12.50", "%", 45, 3)
    conn.close()


def test_agent_sources_retain_page_and_cell_context():
    sql_sources = agent._extract_sources("sql_query", {
        "sql": "SELECT ...", "evidence": [{
            "document_id": 7, "filename": "report.pdf", "page": 46,
            "row_label": "Revenue", "column": "2568", "value": "100",
            "evidence_status": "ocr_extracted_unverified",
        }],
    })
    assert sql_sources[0]["page"] == 46
    assert sql_sources[0]["value"] == "100"

    vector_sources = agent._extract_sources("vector_search", {"chunks": [{
        "document_id": 7, "filename": "report.pdf", "page": 12,
        "text": "Relevant text", "source_kind": "semantic",
    }]})
    assert vector_sources[0]["document_id"] == 7
    assert vector_sources[0]["page"] == 12
