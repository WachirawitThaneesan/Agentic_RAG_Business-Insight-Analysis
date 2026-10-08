"""Single-process, restart-resumable PDF ingestion queue.

The API owns DuckDB, so PDF jobs run in its process rather than a competing
Celery process. Page checkpoints in PostgreSQL survive API restarts.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Document, DocumentPage

logger = logging.getLogger(__name__)
_jobs: dict[int, asyncio.Task] = {}
_one_writer = asyncio.Semaphore(1)


def saved_upload_path(document_id: int, extension: str) -> Path:
    from backend.routes.documents import UPLOAD_DIR
    return Path(UPLOAD_DIR) / f"{document_id}.{extension.lower()}"


def is_pdf_job_active(document_id: int) -> bool:
    task = _jobs.get(document_id)
    return task is not None and not task.done()


def enqueue_pdf_job(document_id: int) -> bool:
    if is_pdf_job_active(document_id):
        return False
    task = asyncio.create_task(_run_pdf_job(document_id), name=f"pdf-ingest-{document_id}")
    _jobs[document_id] = task
    task.add_done_callback(lambda completed: _jobs.pop(document_id, None) if _jobs.get(document_id) is completed else None)
    return True


async def prepare_pdf_job(db, doc: Document, path: Path) -> int:
    """Validate a saved PDF and create the same durable page checkpoints for every origin."""
    from backend.services.ocr import ocr_service
    from backend.services.source_provenance import bind_saved_source

    bind_saved_source(doc,path)

    page_count = ocr_service.get_pdf_page_count(str(path))
    if page_count < 1:
        raise ValueError("PDF has no pages")
    db.add_all(
        DocumentPage(document_id=doc.id, page_number=number, status="pending")
        for number in range(1, page_count + 1)
    )
    await db.commit()
    enqueue_pdf_job(doc.id)
    return page_count


async def _run_pdf_job(document_id: int) -> None:
    async with _one_writer:
        async with AsyncSessionLocal() as db:
            doc = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
            if not doc or doc.doc_type != "pdf":
                return
            path = saved_upload_path(document_id, "pdf")
            if not path.is_file():
                doc.status = "failed"
                doc.error_message = "Saved upload file is missing; cannot resume"
                await db.commit()
                return
            try:
                from backend.routes.documents import _process_saved_document
                await _process_saved_document(doc, str(path), "pdf", db)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background PDF job %d failed", document_id)


async def resume_interrupted_pdf_jobs() -> int:
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document).where(
            Document.doc_type == "pdf", Document.status.in_(["pending", "processing"]),
        ))).scalars().all()
        count = 0
        for doc in docs:
            if not saved_upload_path(doc.id, "pdf").is_file():
                doc.status = "failed"
                doc.error_message = "Saved upload file is missing; cannot resume"
            elif enqueue_pdf_job(doc.id):
                count += 1
        await db.commit()
        return count


async def stop_pdf_jobs() -> None:
    tasks = list(_jobs.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def cancel_pdf_job(document_id: int) -> None:
    task = _jobs.get(document_id)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
