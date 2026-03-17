"""Celery background tasks for document processing and scraping."""

import os
from celery import Celery
from backend.config import get_settings

settings = get_settings()

celery_app = Celery(
    "financial_agent",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Bangkok",
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(bind=True, name="process_document")
def process_document_task(self, document_id: int, filepath: str):
    """Background task: OCR → clean → chunk → embed → store.

    Used for large documents or batch processing.
    """
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    # For Celery tasks, we use synchronous operations
    self.update_state(state="PROCESSING", meta={"step": "Starting OCR..."})

    # Since Celery runs sync, we use asyncio.run for async functions
    async def _process():
        from backend.database import AsyncSessionLocal
        from backend.models import Document, Chunk, StructuredData
        from backend.services.embedding import get_embedding
        from backend.services.ocr import ocr_service
        from backend.services.table_utils import build_table_chunk_payloads, normalize_ocr_tables
        from backend.services.thai_cleaner import clean_thai_text
        from backend.services.chunker import chunk_document

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()

            if not doc:
                return {"error": "Document not found"}

            doc.status = "processing"
            await db.commit()

            try:
                with open(filepath, "rb") as f:
                    file_bytes = f.read()

                ext = filepath.rsplit(".", 1)[-1].lower()

                if ext == "pdf":
                    ocr_result = await ocr_service.extract_from_pdf(file_bytes)
                else:
                    ocr_result = await ocr_service.extract_from_image(file_bytes)

                text_blocks = ocr_result.get("text_blocks", [])
                tables = normalize_ocr_tables(doc.filename, ocr_result.get("tables", []))

                raw_text = "\n\n".join(text_blocks)
                cleaned_text = clean_thai_text(raw_text)
                table_chunk_payloads = build_table_chunk_payloads(doc.filename, tables)
                table_csv_text = "\n\n".join(
                    f"[TABLE] {table.get('table_name')}\n{table.get('csv_text')}"
                    for table in tables
                    if table.get("csv_text")
                ).strip()
                doc.raw_text = "\n\n".join(part for part in [cleaned_text, table_csv_text] if part).strip()

                for i, table in enumerate(tables):
                    headers = table.get("headers", [])
                    rows = table.get("rows", [])
                    for j, row in enumerate(rows):
                        row_dict = dict(zip(headers, row)) if headers else {"data": row}
                        sd = StructuredData(
                            document_id=doc.id,
                            table_name=table.get("table_name") or f"{doc.filename}_table_{i}",
                            headers=headers,
                            row_data=row_dict,
                            row_index=j,
                        )
                        db.add(sd)

                if cleaned_text.strip():
                    chunk_results = await chunk_document(cleaned_text)
                    for cr in chunk_results:
                        chunk = Chunk(
                            document_id=doc.id,
                            chunk_index=cr.chunk_index,
                            chunk_text=cr.text,
                            summary=cr.summary,
                            token_count=cr.token_count,
                            embedding=cr.embedding,
                            metadata_={"start_char": cr.start_char, "end_char": cr.end_char},
                        )
                        db.add(chunk)
                else:
                    chunk_results = []

                for offset, payload in enumerate(table_chunk_payloads):
                    chunk_text = (payload.get("text") or "").strip()
                    if not chunk_text:
                        continue

                    embedding = await get_embedding(chunk_text)
                    db.add(
                        Chunk(
                            document_id=doc.id,
                            chunk_index=len(chunk_results) + offset,
                            chunk_text=chunk_text,
                            summary="",
                            token_count=len(chunk_text.split()),
                            embedding=embedding,
                            metadata_={
                                "source_kind": "table_csv",
                                "table_name": payload.get("table_name"),
                                "table_title": payload.get("title"),
                                "headers": payload.get("headers", []),
                                "row_start": payload.get("row_start"),
                                "row_end": payload.get("row_end"),
                            },
                        )
                    )

                doc.status = "completed"
                await db.commit()
                return {"status": "completed", "chunks": len(chunk_results) + len(table_chunk_payloads)}

            except Exception as e:
                doc.status = "failed"
                doc.error_message = str(e)
                await db.commit()
                return {"status": "failed", "error": str(e)}

    return asyncio.run(_process())


@celery_app.task(bind=True, name="scrape_and_process")
def scrape_and_process_task(self, keyword: str, target_urls: list = None):
    """Background task: scrape → download → process each file."""
    import asyncio

    async def _scrape():
        from backend.services.scraper import scrape_by_keyword

        self.update_state(state="SCRAPING", meta={"step": f"Scraping for: {keyword}"})
        result = await scrape_by_keyword(keyword, target_urls)

        files = result.get("files", [])
        for i, filepath in enumerate(files):
            self.update_state(
                state="PROCESSING",
                meta={"step": f"Processing file {i+1}/{len(files)}"}
            )
            # Trigger document processing for each file
            process_document_task.delay(document_id=0, filepath=filepath)

        return result

    return asyncio.run(_scrape())
