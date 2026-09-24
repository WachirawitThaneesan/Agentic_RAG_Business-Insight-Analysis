"""Document management API routes."""

import os
import re
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pypdf import PdfReader

from backend.database import get_db, AsyncSessionLocal
from backend.models import Document, DocumentPage, Chunk, StructuredData
from backend.services.embedding import get_embedding
from backend.services.ocr_artifacts import build_raw_ocr_chunk_payloads
from backend.services.ocr import ocr_service
from backend.services.table_utils import build_table_chunk_payloads, normalize_ocr_tables, rebuild_structured_tables, safe_table_name, table_to_csv
from backend.services.financial_quality import assess_table, reconcile_retry
from backend.services.thai_cleaner import clean_thai_text
from backend.services.chunker import chunk_document
from backend.config import get_settings
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _table_group_key(table_name: str) -> str:
    name = str(table_name or "untitled_table")
    match = re.match(r"^(.*?_table_\d+)_.*$", name)
    return match.group(1) if match else name


def _progress_message(page_num: int, page_count: int) -> str:
    return f"Processing page {page_num}/{page_count}"


def _summarize_page_error(error: str) -> str:
    message = str(error or "").strip()
    compact = re.sub(r"\s+", " ", message)
    if re.fullmatch(r"page\s+\d+\s*:", compact, flags=re.IGNORECASE):
        return "Unknown error from legacy upload"

    if "StringDataRightTruncationError" in compact and "character varying(500)" in compact:
        return "DB insert failed: table_name too long for structured_data.table_name"
    if "Request timed out" in compact or "Error code: 408" in compact:
        return "Typhoon OCR timeout (408)"
    if "500 Internal Server Error" in compact:
        return "Upstream service returned 500"
    return compact[:220] or "Unknown error (see server log)"


def _effective_document_status(doc: Document, pages: Optional[list[DocumentPage]] = None) -> str:
    if doc.status == "completed" and (
        any(page.status == "failed" for page in (pages or []))
        or re.search(r"Failed pages:\s*\d", str(doc.error_message or ""), flags=re.IGNORECASE)
    ):
        return "partial"
    return doc.status


def _warning_message(errors: list[str]) -> str:
    failed_pages = []
    reason_parts = []
    for error in errors:
        match = re.search(r"page\s+(\d+)", str(error), flags=re.IGNORECASE)
        if match:
            page = match.group(1)
            failed_pages.append(page)
            reason = re.sub(r"^page\s+\d+\s*:\s*", "", str(error), flags=re.IGNORECASE)
            reason_parts.append(f"{page}={_summarize_page_error(reason)}")

    failed_part = f"Failed pages: {', '.join(failed_pages)}" if failed_pages else ""
    reason_part = f"Failed page reasons: {'; '.join(reason_parts)}" if reason_parts else ""
    return "Page processing warnings: " + " | ".join(part for part in [failed_part, reason_part] if part)


def _extract_doc_runtime_info(doc: Document, pages: Optional[list[DocumentPage]] = None) -> dict:
    message = str(doc.error_message or "").strip()
    if pages:
        failed = [page for page in pages if page.status == "failed"]
        return {
            "progress_text": message if doc.status == "processing" else "",
            "failed_pages": [page.page_number for page in failed],
            "failed_page_reasons": {
                page.page_number: f"{page.error_stage or 'processing'}: {_summarize_page_error(page.error_message)}"
                for page in failed
            },
            "page_count": len(pages),
            "indexed_pages": sum(page.status == "indexed" for page in pages),
            "empty_pages": sum(page.status == "empty" for page in pages),
            "status_detail": message,
        }
    progress_text = ""
    failed_pages = []
    failed_page_reasons = {}

    progress_match = re.search(r"Processing page\s+(\d+)/(\d+)", message, flags=re.IGNORECASE)
    if progress_match:
        progress_text = f"หน้า {progress_match.group(1)}/{progress_match.group(2)}"

    failed_preview_match = re.search(r"Failed pages:\s*([0-9,\s]+)", message, flags=re.IGNORECASE)
    if failed_preview_match:
        failed_pages = [
            int(part.strip())
            for part in failed_preview_match.group(1).split(",")
            if part.strip().isdigit()
        ]

    failed_reason_match = re.search(r"Failed page reasons:\s*(.+)$", message, flags=re.IGNORECASE)
    if failed_reason_match:
        for part in failed_reason_match.group(1).split(";"):
            match = re.match(r"\s*(\d+)\s*=\s*(.+?)\s*$", part)
            if match:
                failed_page_reasons[int(match.group(1))] = _summarize_page_error(match.group(2))

    return {
        "progress_text": progress_text,
        "failed_pages": failed_pages,
        "failed_page_reasons": failed_page_reasons,
        "page_count": None,
        "indexed_pages": None,
        "empty_pages": None,
        "status_detail": message,
    }


def _page_error(exc: Exception) -> str:
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


async def _mark_page_failed(db: AsyncSession, doc_id: int, page_num: int, stage: str, exc: Exception) -> Document:
    await db.rollback()
    page = (await db.execute(
        select(DocumentPage).where(DocumentPage.document_id == doc_id, DocumentPage.page_number == page_num)
    )).scalar_one()
    page.status = "failed"
    page.error_stage = stage
    page.error_message = _page_error(exc)
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
    await db.commit()
    logger.exception("PDF page %d failed during %s: %s", page_num, stage, exc)
    return doc


def _add_raw_page_chunk(db: AsyncSession, document_id: int, filename: str, page_num: int, markdown: str, index: int) -> None:
    db.add(Chunk(
        document_id=document_id,
        chunk_index=index,
        chunk_text=f"RAW_OCR_PAGE: {filename} page {page_num}\n{markdown}",
        summary="",
        token_count=len(markdown.split()),
        embedding=None,
        metadata_={"source_kind": "raw_ocr_page", "page": page_num, "markdown": markdown},
    ))


async def _retry_inconsistent_pdf_tables(filepath: str, filename: str, page_num: int, ocr_result: dict):
    """Re-read only contradictory pages; never guess values from arithmetic."""
    primary_tables = normalize_ocr_tables(filename, ocr_result.get("tables", []))
    if not settings.PDF_QUALITY_REOCR_ENABLED:
        return primary_tables, None, [], "disabled"
    needs_retry = any(
        any(reason.startswith("reported_") for reason in row["reasons"])
        for table in primary_tables
        for row in assess_table(table)["row_reports"]
    )
    if not needs_retry:
        return primary_tables, None, [], "not_needed"

    retry_dpi = max(settings.PDF_QUALITY_REOCR_DPI, ocr_service.render_dpi + 50)
    try:
        with open(filepath, "rb") as source:
            page = PdfReader(source, strict=False).pages[page_num - 1]
            estimated_pixels = float(page.mediabox.width) * float(page.mediabox.height) * (retry_dpi / 72.0) ** 2
    except Exception as exc:
        logger.warning("Could not size PDF page %d for quality re-OCR: %s", page_num, exc)
        return primary_tables, None, [], f"retry_sizing_failed:{type(exc).__name__}"
    if estimated_pixels > 25_000_000:
        logger.info("Skipping high-DPI retry on oversized PDF page %d (%d estimated pixels)", page_num, estimated_pixels)
        return primary_tables, None, [], "page_too_large_for_retry"

    try:
        retry_result = await ocr_service.extract_from_pdf_path(
            filepath, filename=filename, pages=[page_num], render_dpi=retry_dpi,
        )
        retry_tables = normalize_ocr_tables(filename, retry_result.get("tables", []))
        merged, changes = reconcile_retry(primary_tables, retry_tables)
        return merged, retry_result, changes, "retried"
    except Exception as exc:
        logger.warning("Quality re-OCR failed on page %d; keeping first-pass values unresolved: %s", page_num, exc)
        return primary_tables, None, [], f"retry_failed:{type(exc).__name__}"


def _sync_tables_to_warehouse(document_id: int, filename: str, tables: list[dict]) -> None:
    if not tables:
        return
    from backend.services.duckdb_warehouse import load_document_dim, load_table_into_warehouse

    load_document_dim(document_id, filename)
    for table in tables:
        load_table_into_warehouse(
            document_id, table["table_name"], table["headers"], table["rows"],
            title=str(table.get("title") or ""),
        )


async def _store_table_chunks(
    db: AsyncSession,
    document_id: int,
    chunk_payloads,
    start_index: int,
) -> int:
    created = 0
    for offset, payload in enumerate(chunk_payloads):
        chunk_text = (payload.get("text") or "").strip()
        if not chunk_text:
            continue

        embedding = await get_embedding(chunk_text)
        db.add(
            Chunk(
                document_id=document_id,
                chunk_index=start_index + offset,
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
        created += 1

    return created


async def _store_artifact_chunks(
    db: AsyncSession,
    document_id: int,
    chunk_payloads,
    start_index: int,
) -> int:
    created = 0
    for offset, payload in enumerate(chunk_payloads):
        chunk_text = (payload.get("text") or "").strip()
        if not chunk_text:
            continue

        source_kind = (payload.get("metadata") or {}).get("source_kind", "")
        # Raw OCR is an audit artifact, not an answer source. Even short raw
        # tables can contain the very cells quarantined by the quality gate.
        if source_kind.startswith("raw_ocr"):
            embedding = None
        else:
            try:
                embedding = await get_embedding(chunk_text)
            except Exception as exc:
                logger.warning("Raw OCR artifact embedding failed: %s", exc)
                embedding = None
        db.add(
            Chunk(
                document_id=document_id,
                chunk_index=start_index + offset,
                chunk_text=chunk_text,
                summary=payload.get("summary", ""),
                token_count=len(chunk_text.split()),
                embedding=embedding,
                metadata_=payload.get("metadata", {}),
            )
        )
        created += 1

    return created


def _assess_ocr_tables(tables: list[dict], retry_changes: Optional[list[dict]] = None) -> tuple[list[dict], list[dict]]:
    """Keep contradictory rows out of structured search and the warehouse."""
    accepted_tables = []
    reports = []
    for table in tables:
        report = assess_table(table)
        stored_report = {key: value for key, value in report.items() if key != "accepted_rows"}
        stored_report["retry_changes"] = [
            change for change in (retry_changes or []) if change.get("table_name") == table.get("table_name")
        ]
        reports.append(stored_report)
        if not report["accepted_rows"]:
            continue
        accepted = dict(table)
        accepted["rows"] = report["accepted_rows"]
        accepted["csv_text"] = table_to_csv(accepted["headers"], accepted["rows"])
        accepted["source_row_indices"] = report["accepted_row_indices"]
        accepted_tables.append(accepted)
    return accepted_tables, reports


def _add_quality_chunks(db: AsyncSession, document_id: int, reports: list[dict], start_index: int) -> int:
    for offset, report in enumerate(reports):
        db.add(Chunk(
            document_id=document_id,
            chunk_index=start_index + offset,
            chunk_text=f"TABLE_QUALITY: {report.get('table_name')} status={report.get('status')}",
            summary="",
            token_count=0,
            embedding=None,
            metadata_={"source_kind": "table_quality", "report": report},
        ))
    return len(reports)


async def _store_semantic_chunks(
    db: AsyncSession,
    document_id: int,
    cleaned_text: str,
    start_index: int,
    generate_summaries: bool = True,
) -> int:
    if not cleaned_text.strip():
        return 0

    chunk_results = await chunk_document(cleaned_text, generate_summaries=generate_summaries)
    for offset, cr in enumerate(chunk_results):
        db.add(
            Chunk(
                document_id=document_id,
                chunk_index=start_index + offset,
                chunk_text=cr.text,
                summary=cr.summary,
                token_count=cr.token_count,
                embedding=cr.embedding,
                metadata_={
                    "start_char": cr.start_char,
                    "end_char": cr.end_char,
                },
            )
        )
    return len(chunk_results)


def _append_document_raw_text(document: Document, text: str) -> None:
    addition = (text or "").strip()
    if not addition:
        return

    existing = str(document.__dict__.get("raw_text") or "").strip()
    combined = f"{existing}\n\n{addition}".strip() if existing else addition
    document.raw_text = combined[:settings.DOCUMENT_RAW_TEXT_LIMIT_CHARS]


async def _ingest_ocr_batch(
    db: AsyncSession,
    document_id: int,
    doc: Document,
    filename: str,
    ocr_result,
    next_chunk_index: int,
    generate_summaries: bool,
    raw_page_limit: Optional[int],
    normalized_tables_override: Optional[list[dict]] = None,
    retry_result: Optional[dict] = None,
    retry_changes: Optional[list[dict]] = None,
):
    text_blocks = ocr_result.get("text_blocks", [])
    all_tables = normalized_tables_override if normalized_tables_override is not None else normalize_ocr_tables(filename, ocr_result.get("tables", []))
    tables, quality_reports = _assess_ocr_tables(all_tables, retry_changes=retry_changes)
    raw_ocr_chunk_payloads = build_raw_ocr_chunk_payloads(
        filename,
        ocr_result,
        max_pages=raw_page_limit,
    )

    raw_text = "\n\n".join(text_blocks)
    cleaned_text = clean_thai_text(raw_text)
    table_chunk_payloads = build_table_chunk_payloads(filename, tables)
    table_csv_text = "\n\n".join(
        f"[TABLE] {table.get('table_name')}\n{table.get('csv_text')}"
        for table in tables
        if table.get("csv_text")
    ).strip()
    _append_document_raw_text(doc, "\n\n".join(part for part in [cleaned_text, table_csv_text] if part).strip())

    for i, table in enumerate(tables):
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        tbl_name = safe_table_name(
            str(table.get("table_name") or table.get("title") or f"{filename}_table_{i}"),
            f"{filename}_table_{i}",
        )
        for j, row in enumerate(rows):
            row_dict = dict(zip(headers, row)) if headers else {"data": row}
            db.add(
                StructuredData(
                    document_id=document_id,
                    table_name=tbl_name,
                    headers=headers,
                    row_data=row_dict,
                    row_index=table.get("source_row_indices", [])[j] if table.get("source_row_indices") else j,
                )
            )

    semantic_chunks_created = await _store_semantic_chunks(
        db,
        document_id,
        cleaned_text,
        start_index=next_chunk_index,
        generate_summaries=generate_summaries,
    )
    next_chunk_index += semantic_chunks_created

    table_chunks_created = await _store_table_chunks(
        db,
        document_id,
        table_chunk_payloads,
        start_index=next_chunk_index,
    )
    next_chunk_index += table_chunks_created

    raw_ocr_chunks_created = await _store_artifact_chunks(
        db,
        document_id,
        raw_ocr_chunk_payloads,
        start_index=next_chunk_index,
    )
    next_chunk_index += raw_ocr_chunks_created

    quality_chunks_created = _add_quality_chunks(db, document_id, quality_reports, next_chunk_index)
    next_chunk_index += quality_chunks_created
    if retry_result:
        retry_markdown = str((retry_result.get("raw_pages") or [{}])[0].get("markdown") or "")
        db.add(Chunk(
            document_id=document_id,
            chunk_index=next_chunk_index,
            chunk_text=f"RAW_OCR_RETRY_PAGE: {filename}\n{retry_markdown}",
            summary="",
            token_count=len(retry_markdown.split()),
            embedding=None,
            metadata_={"source_kind": "raw_ocr_retry_page", "page": (retry_result.get("raw_pages") or [{}])[0].get("page"), "markdown": retry_markdown},
        ))
        next_chunk_index += 1

    return {
        "next_chunk_index": next_chunk_index,
        "text_blocks": len(text_blocks),
        "tables_extracted": len(all_tables),
        "tables_accepted": len(tables),
        "unresolved_rows": sum(report["unresolved_rows"] for report in quality_reports),
        "unverified_rows": sum(
            row["status"] == "unverified"
            for report in quality_reports for row in report["row_reports"]
        ),
        "semantic_chunks_created": semantic_chunks_created,
        "table_chunks_created": table_chunks_created,
        "raw_ocr_chunks_created": raw_ocr_chunks_created,
        "quality_chunks_created": quality_chunks_created,
        "raw_pages_stored": sum(
            1 for payload in raw_ocr_chunk_payloads if (payload.get("metadata") or {}).get("source_kind") == "raw_ocr_page"
        ),
        "tables": tables,
        "quality_reports": quality_reports,
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF or image, run OCR → clean → chunk → store pipeline."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Determine file type
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("pdf", "png", "jpg", "jpeg"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    file_bytes = await file.read()

    # Save file locally
    filepath = os.path.join(UPLOAD_DIR, file.filename)
    with open(filepath, "wb") as f:
        f.write(file_bytes)

    # Create document record
    doc = Document(filename=file.filename, doc_type=ext, status="processing")
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    doc_id = doc.id

    try:
        total_text_blocks = 0
        total_tables_extracted = 0
        total_unresolved_rows = 0
        total_unverified_rows = 0
        retried_pages = 0
        retry_attempts = 0
        next_chunk_index = 0
        stored_raw_pages = 0
        batch_errors = []

        # Step 1: OCR
        if ext == "pdf":
            page_count = ocr_service.get_pdf_page_count(filepath)
            use_large_file_mode = page_count >= settings.PDF_LARGE_FILE_PAGE_THRESHOLD
            db.add_all(
                DocumentPage(document_id=doc_id, page_number=page_num, status="pending")
                for page_num in range(1, page_count + 1)
            )
            await db.commit()

            for page_num in range(1, page_count + 1):
                raw_page_budget = None
                if settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT >= 0:
                    raw_page_budget = max(settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT - stored_raw_pages, 0)

                try:
                    doc.error_message = _progress_message(page_num, page_count)
                    page = (await db.execute(
                        select(DocumentPage).where(DocumentPage.document_id == doc_id, DocumentPage.page_number == page_num)
                    )).scalar_one()
                    page.status = "processing"
                    await db.commit()
                    # The OCR service renders this one PDF page and keeps its
                    # actual 1-based PDF index in every raw/table artifact.
                    ocr_result = await ocr_service.extract_from_pdf_path(
                        filepath, filename=file.filename, pages=[page_num],
                    )
                except Exception as page_error:
                    batch_errors.append(f"page {page_num}: {_page_error(page_error)}")
                    doc = await _mark_page_failed(db, doc_id, page_num, "ocr", page_error)
                    continue

                markdown = str((ocr_result.get("raw_pages") or [{}])[0].get("markdown") or "")
                try:
                    if raw_page_budget != 0:
                        _add_raw_page_chunk(db, doc_id, file.filename, page_num, markdown, next_chunk_index)
                        next_chunk_index += 1
                        stored_raw_pages += 1
                    page.status = "ocr_complete" if markdown.strip() else "empty"
                    await db.commit()
                except Exception as page_error:
                    if raw_page_budget != 0:
                        next_chunk_index -= 1
                        stored_raw_pages -= 1
                    batch_errors.append(f"page {page_num}: {_page_error(page_error)}")
                    doc = await _mark_page_failed(db, doc_id, page_num, "raw_storage", page_error)
                    continue

                if not markdown.strip():
                    continue

                if retry_attempts < max(settings.PDF_QUALITY_REOCR_MAX_PAGES, 0):
                    normalized_override, retry_result, retry_changes, retry_note = await _retry_inconsistent_pdf_tables(
                        filepath, file.filename, page_num, ocr_result,
                    )
                else:
                    normalized_override = normalize_ocr_tables(file.filename, ocr_result.get("tables", []))
                    retry_result, retry_changes, retry_note = None, [], "retry_budget_exhausted"
                if retry_note == "retried":
                    retried_pages += 1
                    retry_attempts += 1
                elif retry_note.startswith("retry_failed"):
                    retry_attempts += 1

                try:
                    batch_result = await _ingest_ocr_batch(
                        db,
                        doc_id,
                        doc,
                        file.filename,
                        ocr_result,
                        next_chunk_index=next_chunk_index,
                        generate_summaries=False,
                        raw_page_limit=0,
                        normalized_tables_override=normalized_override,
                        retry_result=retry_result,
                        retry_changes=retry_changes,
                    )
                    page.status = "indexed"
                    await db.commit()
                    next_chunk_index = batch_result["next_chunk_index"]
                    total_text_blocks += batch_result["text_blocks"]
                    total_tables_extracted += batch_result["tables_extracted"]
                    total_unresolved_rows += batch_result["unresolved_rows"]
                    total_unverified_rows += batch_result["unverified_rows"]
                except Exception as page_error:
                    batch_errors.append(f"page {page_num}: {_page_error(page_error)}")
                    doc = await _mark_page_failed(db, doc_id, page_num, "indexing", page_error)
                    continue

                try:
                    _sync_tables_to_warehouse(doc_id, file.filename, batch_result["tables"])
                except Exception as page_error:
                    batch_errors.append(f"page {page_num}: {_page_error(page_error)}")
                    doc = await _mark_page_failed(db, doc_id, page_num, "warehouse", page_error)

            all_pages = (await db.execute(
                select(DocumentPage).where(DocumentPage.document_id == doc_id)
            )).scalars().all()
            if not any(page.status in {"indexed", "empty"} for page in all_pages):
                raise RuntimeError("; ".join(batch_errors) or "No PDF pages could be processed")
        else:
            mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
            ocr_result = await ocr_service.extract_from_image(
                file_bytes,
                mime_map.get(ext, "image/png"),
                filename=file.filename,
            )
            batch_result = await _ingest_ocr_batch(
                db,
                doc_id,
                doc,
                file.filename,
                ocr_result,
                next_chunk_index=0,
                generate_summaries=True,
                raw_page_limit=None,
            )
            next_chunk_index = batch_result["next_chunk_index"]
            total_text_blocks = batch_result["text_blocks"]
            total_tables_extracted = batch_result["tables_extracted"]
            total_unresolved_rows = batch_result["unresolved_rows"]
            total_unverified_rows = batch_result["unverified_rows"]
            _sync_tables_to_warehouse(doc_id, file.filename, batch_result["tables"])

        empty_page_numbers = [page.page_number for page in all_pages if page.status == "empty"] if ext == "pdf" else []
        doc.status = "partial" if batch_errors or empty_page_numbers else "completed"
        details = []
        if batch_errors:
            details.append(_warning_message(batch_errors))
        if empty_page_numbers:
            details.append(f"OCR returned no text on pages: {', '.join(map(str, empty_page_numbers))}")
        if total_unresolved_rows:
            details.append(f"Data quality: {total_unresolved_rows} unresolved table rows excluded from structured search and warehouse")
        if total_unverified_rows:
            details.append(f"Data quality: {total_unverified_rows} table rows have no applicable numeric cross-check")
        doc.error_message = " | ".join(details) or None
        await db.commit()

        # --- Trigger knowledge graph build in the background (non-blocking) ---
        raw_text_for_graph = (doc.raw_text or "").strip()
        if doc.status == "completed" and raw_text_for_graph:
            try:
                from backend.tasks import build_graph_task
                build_graph_task.delay(doc_id=doc_id, text=raw_text_for_graph)
                logger.info("[graph] Queued build_graph_task for doc_id=%d", doc_id)
            except Exception as _graph_exc:
                logger.warning("[graph] Could not queue graph task (Celery may not be running): %s", _graph_exc)

        return {
            "id": doc_id,
            "filename": doc.filename,
            "status": doc.status,
            "failed_pages": [page.page_number for page in (await db.execute(
                select(DocumentPage).where(DocumentPage.document_id == doc_id, DocumentPage.status == "failed")
            )).scalars().all()] if ext == "pdf" else [],
            "text_blocks": total_text_blocks,
            "tables_extracted": total_tables_extracted,
            "unresolved_rows": total_unresolved_rows,
            "unverified_rows": total_unverified_rows,
            "retried_pages": retried_pages,
            "chunks_created": next_chunk_index,
            "large_file_mode": ext == "pdf" and locals().get("use_large_file_mode", False),
        }

    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        async with AsyncSessionLocal() as cleanup_db:
            result = await cleanup_db.execute(select(Document).where(Document.id == doc_id))
            failed_doc = result.scalar_one_or_none()
            if failed_doc:
                failed_doc.status = "failed"
                failed_doc.error_message = str(e)
                await cleanup_db.commit()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.get("")
async def list_documents(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List all documents with chunk/table counts."""
    result = await db.execute(
        select(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit)
    )
    docs = result.scalars().all()

    items = []
    for doc in docs:
        pages = (await db.execute(
            select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_number)
        )).scalars().all()
        # Count chunks
        chunk_count = await db.execute(
            select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
        )
        # Count structured rows
        table_count = await db.execute(
            select(func.count(StructuredData.id)).where(StructuredData.document_id == doc.id)
        )

        runtime_info = _extract_doc_runtime_info(doc, pages)
        items.append({
            "id": doc.id,
            "filename": doc.filename,
            "source_url": doc.source_url,
            "doc_type": doc.doc_type,
            "status": _effective_document_status(doc, pages),
            "progress_text": runtime_info["progress_text"],
            "failed_pages": runtime_info["failed_pages"],
            "failed_page_reasons": runtime_info["failed_page_reasons"],
            "status_detail": runtime_info["status_detail"],
            "page_count": runtime_info["page_count"],
            "indexed_pages": runtime_info["indexed_pages"],
            "empty_pages": runtime_info["empty_pages"],
            "chunk_count": chunk_count.scalar() or 0,
            "table_row_count": table_count.scalar() or 0,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        })

    return {"documents": items, "total": len(items)}


@router.get("/{doc_id}")
async def get_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Get document details with its chunks and tables."""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pages = (await db.execute(
        select(DocumentPage).where(DocumentPage.document_id == doc_id).order_by(DocumentPage.page_number)
    )).scalars().all()

    # Get chunks
    chunks_result = await db.execute(
        select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()

    # Get structured data
    sd_result = await db.execute(
        select(StructuredData).where(StructuredData.document_id == doc_id).order_by(StructuredData.id)
    )
    structured = sd_result.scalars().all()

    grouped_tables = {}
    for row in structured:
        table_name = _table_group_key(row.table_name or "untitled_table")
        bucket = grouped_tables.setdefault(
            table_name,
            {"headers": row.headers or [], "rows": []},
        )
        bucket["rows"].append(row.row_data or {})

    rebuilt_tables = []
    for table_name, payload in grouped_tables.items():
        rebuilt_tables.extend(
            rebuild_structured_tables(
                table_name,
                payload["headers"],
                payload["rows"],
            )
        )

    raw_ocr_pages = []
    raw_ocr_retry_pages = []
    raw_ocr_tables = []
    quality_reports = []
    for chunk in chunks:
        metadata = chunk.metadata_ or {}
        source_kind = metadata.get("source_kind")
        if source_kind == "raw_ocr_page":
            raw_ocr_pages.append(
                {
                    "page": metadata.get("page"),
                    "markdown": metadata.get("markdown", ""),
                    "chunk_index": chunk.chunk_index,
                }
            )
        elif source_kind == "raw_ocr_retry_page":
            raw_ocr_retry_pages.append({
                "page": metadata.get("page"),
                "markdown": metadata.get("markdown", ""),
                "chunk_index": chunk.chunk_index,
            })
        elif source_kind == "raw_ocr_table":
            raw_ocr_tables.append(
                {
                    "table_index": metadata.get("table_index"),
                    "page": metadata.get("page"),
                    "title": metadata.get("title"),
                    "headers": metadata.get("headers", []),
                    "rows": metadata.get("rows", []),
                    "csv_text": metadata.get("csv_text", ""),
                    "chunk_index": chunk.chunk_index,
                }
            )
        elif source_kind == "table_quality":
            quality_reports.append(metadata.get("report") or {})

    return {
        "id": doc.id,
        "filename": doc.filename,
        "source_url": doc.source_url,
        "doc_type": doc.doc_type,
        "status": _effective_document_status(doc, pages),
        "raw_text": doc.raw_text,
        "error_message": doc.error_message,
        "runtime_info": _extract_doc_runtime_info(doc, pages),
        "page_statuses": [
            {
                "page": page.page_number,
                "status": page.status,
                "error_stage": page.error_stage,
                "error_message": page.error_message,
            }
            for page in pages
        ],
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "chunks": [
            {
                "id": c.id,
                "chunk_index": c.chunk_index,
                "chunk_text": c.chunk_text,
                "summary": c.summary,
                "token_count": c.token_count,
                "metadata": c.metadata_,
            }
            for c in chunks
        ],
        "structured_data": [
            {
                "id": s.id,
                "table_name": s.table_name,
                "headers": s.headers,
                "row_data": s.row_data,
                "row_index": s.row_index,
            }
            for s in structured
        ],
        "structured_tables": rebuilt_tables,
        "raw_ocr_pages": raw_ocr_pages,
        "raw_ocr_retry_pages": raw_ocr_retry_pages,
        "raw_ocr_tables": raw_ocr_tables,
        "quality_reports": quality_reports,
        "quality_summary": {
            "unresolved_rows": sum(report.get("unresolved_rows", 0) for report in quality_reports),
            "unverified_rows": sum(
                row.get("status") == "unverified"
                for report in quality_reports for row in report.get("row_reports", [])
            ),
            "passed_check_rows": sum(report.get("passed_rows", 0) for report in quality_reports),
            "meaning": "passed_checks means internally consistent, not visually verified against the PDF",
        },
    }


@router.delete("/{doc_id}")
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a document and all associated data."""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    await db.delete(doc)
    await db.commit()
    try:
        from backend.services.duckdb_warehouse import delete_document_data
        delete_document_data(doc_id)
    except Exception as exc:
        logger.warning("Document %d was deleted from PostgreSQL but warehouse cleanup failed: %s", doc_id, exc)
        return {"status": "deleted_with_warehouse_warning", "id": doc_id, "warning": str(exc)}
    return {"status": "deleted", "id": doc_id}
