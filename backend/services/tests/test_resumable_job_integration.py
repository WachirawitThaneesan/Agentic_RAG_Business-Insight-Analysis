"""Opt-in live PostgreSQL/DuckDB resume test with fake OCR and cleanup.

Run with RUN_LIVE_DB_TEST=1 and DUCKDB_PATH set to a separate test file.
No Typhoon API calls are made. Local PDFs supply only their page counts;
their content is neither indexed nor copied.
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, func

from backend.database import AsyncSessionLocal, engine, init_db
from backend.models import Chunk, Document, DocumentPage, StructuredData
from backend.routes import documents
from backend.services import document_jobs
from backend.services import scraper
from backend.services.duckdb_warehouse import close_warehouse, delete_document_data


@pytest.mark.skipif(os.environ.get("RUN_LIVE_DB_TEST") != "1", reason="opt-in live database test")
@pytest.mark.parametrize("failed_page", [None, 3])
def test_scraped_pdf_uses_upload_page_job_and_preserves_source_url(failed_page):
    source = Path(__file__).resolve().parents[3] / "TestFile" / "5Page_Test.pdf"
    assert source.is_file()

    async def scenario():
        await init_db()
        doc_id = None

        async def fake_ocr(_path, filename, pages, **_kwargs):
            page = pages[0]
            if page == failed_page:
                raise TimeoutError("synthetic OCR failure")
            return {
                "raw_pages": [{"page": page, "markdown": "<table>test</table>"}],
                "text_blocks": [],
                "tables": [{"page": page, "title": "Test", "headers": ["Item", "2025"],
                            "rows": [[f"Revenue page {page}", "100"]]}],
            }

        async def fake_embedding(_text):
            return [0.0] * 1024

        try:
            with patch.object(documents.ocr_service, "extract_from_pdf_path", side_effect=fake_ocr), \
                 patch.object(documents, "get_embedding", side_effect=fake_embedding), \
                 patch("backend.tasks.build_graph_task.delay", return_value=None):
                registered = await scraper._ingest_scraped_file(str(source), "https://example.org/report")
                assert registered["queued"] is True
                assert registered["page_count"] == 5
                doc_id = registered["document_id"]
                await document_jobs._jobs[doc_id]

            async with AsyncSessionLocal() as db:
                doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                pages = (await db.execute(select(DocumentPage).where(
                    DocumentPage.document_id == doc_id
                ))).scalars().all()
                assert doc.source_url == "https://example.org/report"
                assert doc.status == ("partial" if failed_page else "completed")
                assert len(pages) == 5
                assert [page.page_number for page in pages if page.status == "failed"] == (
                    [failed_page] if failed_page else []
                )
                assert all(page.status == "indexed" for page in pages if page.page_number != failed_page)
        finally:
            if doc_id is not None:
                await document_jobs.cancel_pdf_job(doc_id)
                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
                    if doc:
                        await db.delete(doc)
                        await db.commit()
                delete_document_data(doc_id)
                saved = document_jobs.saved_upload_path(doc_id, "pdf")
                if saved.is_file():
                    saved.unlink()
            close_warehouse()
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(os.environ.get("RUN_LIVE_DB_TEST") != "1", reason="opt-in live database test")
@pytest.mark.parametrize("filename,page_count,failed_page", [
    ("5Page_Test.pdf", 5, 3),
    ("y2025-onereport-th_selected50.pdf", 50, 27),
])
def test_failed_page_retries_without_duplicate_rows(filename, page_count, failed_page):
    source = Path(__file__).resolve().parents[3] / "TestFile" / filename
    assert source.is_file()

    async def scenario():
        await init_db()
        doc_id = None
        attempts = {}

        async def fake_ocr(_path, filename, pages, **_kwargs):
            page = pages[0]
            attempts[page] = attempts.get(page, 0) + 1
            if page == failed_page and attempts[page] == 1:
                raise TimeoutError("synthetic page failure")
            return {
                "raw_pages": [{"page": page, "markdown": "<table>test</table>"}],
                "text_blocks": [],
                "tables": [{"page": page, "title": "Test", "headers": ["Item", "2025"],
                            "rows": [[f"Revenue page {page}", "100"]]}],
            }

        async def fake_embedding(_text):
            return [0.0] * 1024

        try:
            async with AsyncSessionLocal() as db:
                doc = Document(filename="codex_resumable_integration.pdf", doc_type="pdf", status="pending")
                db.add(doc)
                await db.commit()
                await db.refresh(doc)
                doc_id = doc.id

            with patch.object(documents.ocr_service, "extract_from_pdf_path", side_effect=fake_ocr), \
                 patch.object(documents, "get_embedding", side_effect=fake_embedding), \
                 patch("backend.tasks.build_graph_task.delay", return_value=None):
                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                    first = await documents._process_saved_document(doc, str(source), "pdf", db)
                assert first["status"] == "partial"
                assert first["failed_pages"] == [failed_page]

                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                    second = await documents._process_saved_document(doc, str(source), "pdf", db)
                    pages = (await db.execute(select(DocumentPage).where(DocumentPage.document_id == doc_id))).scalars().all()
                    rows = (await db.execute(select(StructuredData).where(StructuredData.document_id == doc_id))).scalars().all()
                    raw_count = (await db.execute(select(func.count(Chunk.id)).where(
                        Chunk.document_id == doc_id,
                        Chunk.metadata_["source_kind"].as_string() == "raw_ocr_page",
                    ))).scalar_one()
                assert second["status"] == "completed"
                assert len(pages) == page_count and all(page.status == "indexed" for page in pages)
                assert len(rows) == page_count and {row.source_page for row in rows} == set(range(1, page_count + 1))
                assert raw_count == page_count
                assert attempts == {page: 2 if page == failed_page else 1 for page in range(1, page_count + 1)}
        finally:
            if doc_id is not None:
                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
                    if doc:
                        await db.delete(doc)
                        await db.commit()
                delete_document_data(doc_id)
            close_warehouse()
            # Parameterized cases use separate asyncio.run() loops; asyncpg's
            # pooled connections must not be reused from a closed loop.
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(os.environ.get("RUN_LIVE_DB_TEST") != "1", reason="opt-in live database test")
def test_fifty_page_interruption_resumes_from_persisted_checkpoint():
    source = Path(__file__).resolve().parents[3] / "TestFile" / "y2025-onereport-th_selected50.pdf"
    assert source.is_file()

    async def scenario():
        await init_db()
        doc_id = None
        attempts = {}

        async def fake_ocr(_path, filename, pages, **_kwargs):
            page = pages[0]
            attempts[page] = attempts.get(page, 0) + 1
            if page == 27 and attempts[page] == 1:
                raise asyncio.CancelledError("synthetic API shutdown")
            return {
                "raw_pages": [{"page": page, "markdown": f"Page {page} content"}],
                "text_blocks": [], "tables": [],
            }

        async def fake_embedding(_text):
            return [0.0] * 1024

        try:
            async with AsyncSessionLocal() as db:
                doc = Document(filename="codex_restart_integration.pdf", doc_type="pdf", status="pending")
                db.add(doc)
                await db.commit()
                await db.refresh(doc)
                doc_id = doc.id

            with patch.object(documents.ocr_service, "extract_from_pdf_path", side_effect=fake_ocr), \
                 patch.object(documents, "get_embedding", side_effect=fake_embedding), \
                 patch.object(document_jobs, "saved_upload_path", return_value=source), \
                 patch("backend.tasks.build_graph_task.delay", return_value=None):
                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                    with pytest.raises(asyncio.CancelledError):
                        await documents._process_saved_document(doc, str(source), "pdf", db)

                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                    pages = (await db.execute(select(DocumentPage).where(
                        DocumentPage.document_id == doc_id,
                    ).order_by(DocumentPage.page_number))).scalars().all()
                    assert doc.status == "processing"
                    assert [page.page_number for page in pages if page.status == "indexed"] == list(range(1, 27))
                    assert pages[26].status == "processing"

                # This is the same entry point used by a newly started API job.
                await document_jobs._run_pdf_job(doc_id)

                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                    pages = (await db.execute(select(DocumentPage).where(
                        DocumentPage.document_id == doc_id,
                    ))).scalars().all()
                    raw_count = (await db.execute(select(func.count(Chunk.id)).where(
                        Chunk.document_id == doc_id,
                        Chunk.metadata_["source_kind"].as_string() == "raw_ocr_page",
                    ))).scalar_one()
                assert doc.status == "completed"
                assert len(pages) == 50 and all(page.status == "indexed" for page in pages)
                assert raw_count == 50
                assert attempts == {page: 2 if page == 27 else 1 for page in range(1, 51)}
        finally:
            if doc_id is not None:
                async with AsyncSessionLocal() as db:
                    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
                    if doc:
                        await db.delete(doc)
                        await db.commit()
                delete_document_data(doc_id)
            close_warehouse()
            await engine.dispose()

    asyncio.run(scenario())
