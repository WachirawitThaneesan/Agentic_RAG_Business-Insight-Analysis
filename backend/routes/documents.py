"""Document management API routes."""

import os
import re
import asyncio
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, or_, select, func
from pypdf import PdfReader

from backend.database import get_db, AsyncSessionLocal
from backend.models import Document, DocumentPage, Chunk, StructuredData
from backend.services.embedding import get_embedding
from backend.services.ocr_artifacts import build_raw_ocr_chunk_payloads
from backend.services.ocr import ocr_service
from backend.services.table_utils import build_table_chunk_payloads, normalize_ocr_tables, rebuild_structured_tables, safe_table_name, table_to_csv
from backend.services.retrieval_rank import normalize_search_text
from backend.services.financial_quality import assess_table, reconcile_retry
from backend.services.thai_cleaner import clean_thai_text
from backend.services.chunker import chunk_document
from backend.config import get_settings
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

router = APIRouter()

UPLOAD_DIR = (
    os.path.join(settings.PRIVATE_DATA_DIR, "uploads") if settings.OFFLINE_MODE
    else os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
)
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
    try:
        from backend.services.duckdb_warehouse import delete_page_tables
        delete_page_tables(doc_id, page_num)
    except Exception:
        logger.exception("Could not purge warehouse tables for failed PDF page %d", page_num)
    logger.exception("PDF page %d failed during %s: %s", page_num, stage, exc)
    return doc


async def _clear_page_artifacts(db: AsyncSession, doc_id: int, page_num: int) -> None:
    """Remove an interrupted page before retrying it, preventing duplicate rows."""
    await db.execute(delete(Chunk).where(
        Chunk.document_id == doc_id,
        Chunk.metadata_["page"].as_integer() == page_num,
    ))
    await db.execute(delete(StructuredData).where(
        StructuredData.document_id == doc_id,
        or_(
            StructuredData.source_page == page_num,
            StructuredData.table_name.contains(f"page_{page_num}_table_", autoescape=True),
        ),
    ))
    await db.commit()
    from backend.services.duckdb_warehouse import delete_page_tables
    delete_page_tables(doc_id, page_num)


def _add_raw_page_chunk(db: AsyncSession, document_id: int, filename: str, page_num: int, raw_page: dict, index: int, source_sha256: str | None = None) -> None:
    markdown = str(raw_page.get("markdown") or "")
    metadata = {"source_kind": "raw_ocr_page", "page": page_num, "markdown": markdown}
    metadata.update({key: raw_page[key] for key in ("region", "crop_box", "rotation", "provider_markdown") if key in raw_page})
    if source_sha256:
        metadata['source_sha256'] = source_sha256
    db.add(Chunk(
        document_id=document_id,
        chunk_index=index,
        chunk_text=f"RAW_OCR_PAGE: {filename} page {page_num}\n{markdown}",
        summary="",
        token_count=len(markdown.split()),
        embedding=None,
        metadata_=metadata,
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


def _sync_tables_to_warehouse(document_id: int, filename: str, tables: list[dict], source_url: str = "", source_sha256: str | None = None) -> None:
    if not tables:
        return
    from backend.services.duckdb_warehouse import load_document_dim, load_table_into_warehouse

    load_document_dim(document_id, filename, source_url=source_url or "", source_sha256=source_sha256)
    for table in tables:
        load_table_into_warehouse(
            document_id, table["table_name"], table["headers"], table["rows"],
            title=str(table.get("title") or ""),
            source_page=table.get("page"),
            quality_status=table.get("quality_status", "unknown"),
            source_provider=table.get("source_provider"),
            unit=table.get("unit"),
            row_indices=table.get("source_row_indices"),
        )


async def _store_table_chunks(
    db: AsyncSession,
    document_id: int,
    chunk_payloads,
    start_index: int,
    page_number: int | None = None,
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
                    "source_provider": payload.get("source_provider"),
                    "unit": payload.get("unit"),
                    "partial_extraction": payload.get("partial_extraction", False),
                    "ambiguous_row_count": payload.get("ambiguous_row_count", 0),
                    **{key: payload[key] for key in ("region", "crop_box", "rotation", "header_source_page", "header_repairs") if key in payload},
                    "row_start": payload.get("row_start"),
                    "row_end": payload.get("row_end"),
                    "page": page_number,
                    "quality_status": payload.get("quality_status", "unverified"),
                    "search_text": normalize_search_text(chunk_text),
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
    page_number: int | None = None,
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
                metadata_={**(payload.get("metadata") or {}), "page": page_number},
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
        accepted["quality_status"] = (
            "passed_checks" if all(
                report["row_reports"][index]["status"] == "passed_checks"
                for index in report["accepted_row_indices"]
            ) else "unverified"
        )
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
            metadata_={"source_kind": "table_quality", "page": report.get("page"), "report": report},
        ))
    return len(reports)


async def _store_semantic_chunks(
    db: AsyncSession,
    document_id: int,
    cleaned_text: str,
    start_index: int,
    generate_summaries: bool = True,
    page_number: int | None = None,
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
                    "source_kind": "semantic",
                    "end_char": cr.end_char,
                    "page": page_number,
                    "search_text": normalize_search_text(cr.text),
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
    page_chunk_start=next_chunk_index
    text_blocks = ocr_result.get("text_blocks", [])
    page_number = (ocr_result.get("raw_pages") or [{}])[0].get("page")
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
                    source_page=page_number,
                    unit=table.get("unit"),
                    source_provider=table.get("source_provider"),
                    source_sha256=getattr(doc,'source_sha256',None),
                    quality_status=table.get("quality_status", "unknown"),
                )
            )

    semantic_chunks_created = await _store_semantic_chunks(
        db,
        document_id,
        cleaned_text,
        start_index=next_chunk_index,
        generate_summaries=generate_summaries,
        page_number=page_number,
    )
    next_chunk_index += semantic_chunks_created

    table_chunks_created = await _store_table_chunks(
        db,
        document_id,
        table_chunk_payloads,
        start_index=next_chunk_index,
        page_number=page_number,
    )
    next_chunk_index += table_chunks_created

    raw_ocr_chunks_created = await _store_artifact_chunks(
        db,
        document_id,
        raw_ocr_chunk_payloads,
        start_index=next_chunk_index,
        page_number=page_number,
    )
    next_chunk_index += raw_ocr_chunks_created

    quality_chunks_created = _add_quality_chunks(db, document_id, quality_reports, next_chunk_index)
    next_chunk_index += quality_chunks_created
    for warning in ocr_result.get("table_extraction_warnings") or []:
        db.add(Chunk(
            document_id=document_id,
            chunk_index=next_chunk_index,
            chunk_text=f"TABLE_EXTRACTION_WARNING: {filename} page {warning.get('page')}",
            summary="",
            token_count=0,
            embedding=None,
            metadata_={"source_kind": "table_extraction_warning", "page": warning.get("page"),
                       "warning": warning},
        ))
        next_chunk_index += 1
    for partial in ocr_result.get("tables") or []:
        if not partial.get("partial_extraction"):
            continue
        db.add(Chunk(
            document_id=document_id,
            chunk_index=next_chunk_index,
            chunk_text=f"TABLE_PARTIAL: {filename} page {partial.get('page')}",
            summary="",
            token_count=0,
            embedding=None,
            metadata_={"source_kind": "table_partial", "page": partial.get("page"),
                       "title": partial.get("title"), "region": partial.get("region")},
        ))
        next_chunk_index += 1
    if retry_result:
        for region in retry_result.get("raw_pages") or []:
            retry_markdown = str(region.get("markdown") or "")
            db.add(Chunk(
                document_id=document_id,
                chunk_index=next_chunk_index,
                chunk_text=f"RAW_OCR_RETRY_PAGE: {filename}\n{retry_markdown}",
                summary="",
                token_count=len(retry_markdown.split()),
                embedding=None,
                metadata_={"source_kind": "raw_ocr_retry_page", **region},
            ))
            next_chunk_index += 1

    if getattr(doc,'source_sha256',None):
        await db.flush()
        page_chunks=(await db.execute(select(Chunk).where(Chunk.document_id==document_id,
            Chunk.chunk_index>=page_chunk_start))).scalars().all()
        for stored_chunk in page_chunks:
            stored_chunk.metadata_={**(stored_chunk.metadata_ or {}), 'source_sha256':doc.source_sha256}
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


async def _process_saved_document(
    doc: Document, filepath: str, ext: str, db: AsyncSession, file_bytes: bytes | None = None,
):
    """One ingestion path used by HTTP (images) and resumable PDF jobs."""
    doc_id = doc.id

    try:
        from backend.services.source_provenance import bind_saved_source
        bind_saved_source(doc,filepath)
        total_text_blocks = 0
        total_tables_extracted = 0
        total_unresolved_rows = 0
        total_unverified_rows = 0
        retried_pages = 0
        retry_attempts = 0
        next_chunk_index = 0
        stored_raw_pages = 0
        batch_errors = []
        table_warnings = []
        partial_table_pages = set()

        # Step 1: OCR
        if ext == "pdf":
            page_count = ocr_service.get_pdf_page_count(filepath)
            use_large_file_mode = page_count >= settings.PDF_LARGE_FILE_PAGE_THRESHOLD
            existing_pages = (await db.execute(
                select(DocumentPage).where(DocumentPage.document_id == doc_id).order_by(DocumentPage.page_number)
            )).scalars().all()
            if not existing_pages:
                db.add_all(
                    DocumentPage(document_id=doc_id, page_number=page_num, status="pending")
                    for page_num in range(1, page_count + 1)
                )
                await db.commit()
                existing_pages = (await db.execute(
                    select(DocumentPage).where(DocumentPage.document_id == doc_id).order_by(DocumentPage.page_number)
                )).scalars().all()
            if len(existing_pages) != page_count:
                raise RuntimeError("Saved page checkpoint count differs from the PDF page count")
            next_chunk_index = (await db.execute(
                select(func.coalesce(func.max(Chunk.chunk_index), -1)).where(Chunk.document_id == doc_id)
            )).scalar_one() + 1
            stored_raw_pages = sum(page.status in {"indexed", "ocr_complete", "empty"} for page in existing_pages)
            doc.status = "processing"
            await db.commit()

            for page_num in range(1, page_count + 1):
                page = existing_pages[page_num - 1]
                if page.status in {"indexed", "empty"}:
                    continue
                await _clear_page_artifacts(db, doc_id, page_num)
                raw_page_budget = None
                if settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT >= 0:
                    raw_page_budget = max(settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT - stored_raw_pages, 0)

                try:
                    doc.error_message = _progress_message(page_num, page_count)
                    page.status = "processing"
                    page.error_stage = None
                    page.error_message = None
                    await db.commit()
                    # The OCR service renders this one PDF page and keeps its
                    # actual 1-based PDF index in every raw/table artifact.
                    ocr_result = await ocr_service.extract_from_pdf_path(
                        filepath, filename=doc.filename, pages=[page_num],
                    )
                    table_warnings.extend(ocr_result.get("table_extraction_warnings") or [])
                except Exception as page_error:
                    batch_errors.append(f"page {page_num}: {_page_error(page_error)}")
                    doc = await _mark_page_failed(db, doc_id, page_num, "ocr", page_error)
                    continue

                raw_regions = ocr_result.get("raw_pages") or []
                has_markdown = bool(ocr_result.get("tables")) or any(
                    str(region.get("markdown") or "").strip() for region in raw_regions
                )
                original_chunk_index = next_chunk_index
                try:
                    if raw_page_budget != 0:
                        for region in raw_regions:
                            _add_raw_page_chunk(db, doc_id, doc.filename, page_num, region, next_chunk_index, getattr(doc,'source_sha256',None))
                            next_chunk_index += 1
                        stored_raw_pages += 1
                    page.status = "ocr_complete" if has_markdown else "empty"
                    await db.commit()
                except Exception as page_error:
                    if raw_page_budget != 0:
                        next_chunk_index = original_chunk_index
                        stored_raw_pages -= 1
                    batch_errors.append(f"page {page_num}: {_page_error(page_error)}")
                    doc = await _mark_page_failed(db, doc_id, page_num, "raw_storage", page_error)
                    continue

                if not has_markdown:
                    continue

                if retry_attempts < max(settings.PDF_QUALITY_REOCR_MAX_PAGES, 0):
                    normalized_override, retry_result, retry_changes, retry_note = await _retry_inconsistent_pdf_tables(
                        filepath, doc.filename, page_num, ocr_result,
                    )
                else:
                    normalized_override = normalize_ocr_tables(doc.filename, ocr_result.get("tables", []))
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
                        doc.filename,
                        ocr_result,
                        next_chunk_index=next_chunk_index,
                        generate_summaries=False,
                        raw_page_limit=0,
                        normalized_tables_override=normalized_override,
                        retry_result=retry_result,
                        retry_changes=retry_changes,
                    )
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
                    _sync_tables_to_warehouse(doc_id, doc.filename, batch_result["tables"], doc.source_url or "", getattr(doc,'source_sha256',None))
                    page.status = "indexed"
                    await db.commit()
                except Exception as page_error:
                    batch_errors.append(f"page {page_num}: {_page_error(page_error)}")
                    doc = await _mark_page_failed(db, doc_id, page_num, "warehouse", page_error)

            all_pages = (await db.execute(
                select(DocumentPage).where(DocumentPage.document_id == doc_id)
            )).scalars().all()
            if not any(page.status in {"indexed", "empty"} for page in all_pages):
                raise RuntimeError("; ".join(batch_errors) or "No PDF pages could be processed")
            # A resumed run skips completed pages. Summarize persisted quality
            # reports so the final document warning still covers those pages.
            stored_quality_metadata = (await db.execute(select(Chunk.metadata_).where(
                Chunk.document_id == doc_id,
                Chunk.metadata_["source_kind"].as_string() == "table_quality",
            ))).scalars().all()
            stored_quality_reports = [
                metadata.get("report") or {} for metadata in stored_quality_metadata if metadata
            ]
            stored_table_warnings = (await db.execute(select(Chunk.metadata_).where(
                Chunk.document_id == doc_id,
                Chunk.metadata_["source_kind"].as_string() == "table_extraction_warning",
            ))).scalars().all()
            table_warnings = [metadata.get("warning") or {} for metadata in stored_table_warnings if metadata]
            stored_partial_tables = (await db.execute(select(Chunk.metadata_).where(
                Chunk.document_id == doc_id,
                Chunk.metadata_["source_kind"].as_string() == "table_partial",
            ))).scalars().all()
            partial_table_pages = {
                int(metadata["page"]) for metadata in stored_partial_tables
                if metadata and metadata.get("page") is not None
            }
            total_unresolved_rows = sum(report.get("unresolved_rows", 0) for report in stored_quality_reports)
            total_unverified_rows = sum(
                row.get("status") == "unverified"
                for report in stored_quality_reports for row in report.get("row_reports", [])
            )
            batch_errors = [
                f"page {page.page_number}: {page.error_message or 'Unknown error'}"
                for page in all_pages if page.status == "failed"
            ]
        else:
            if file_bytes is None:
                with open(filepath, "rb") as source:
                    file_bytes = source.read()
            mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
            ocr_result = await ocr_service.extract_from_image(
                file_bytes,
                mime_map.get(ext, "image/png"),
                filename=doc.filename,
            )
            table_warnings.extend(ocr_result.get("table_extraction_warnings") or [])
            partial_table_pages.update(
                int(table["page"]) for table in ocr_result.get("tables") or []
                if table.get("partial_extraction") and table.get("page") is not None
            )
            batch_result = await _ingest_ocr_batch(
                db,
                doc_id,
                doc,
                doc.filename,
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
            _sync_tables_to_warehouse(doc_id, doc.filename, batch_result["tables"], doc.source_url or "", getattr(doc,'source_sha256',None))

        empty_page_numbers = [page.page_number for page in all_pages if page.status == "empty"] if ext == "pdf" else []
        doc.status = (
            "partial" if batch_errors or empty_page_numbers or table_warnings or partial_table_pages
            else "completed"
        )
        details = []
        if batch_errors:
            details.append(_warning_message(batch_errors))
        if empty_page_numbers:
            details.append(f"OCR returned no text on pages: {', '.join(map(str, empty_page_numbers))}")
        if table_warnings:
            details.append(
                "Table extraction unresolved on pages: "
                + ", ".join(str(item.get("page")) for item in table_warnings)
            )
        if partial_table_pages:
            details.append(
                "Partial table extraction on pages: "
                + ", ".join(map(str, sorted(partial_table_pages)))
            )
        if total_unresolved_rows:
            details.append(f"Data quality: {total_unresolved_rows} unresolved table rows excluded from structured search and warehouse")
        if total_unverified_rows:
            details.append(f"Data quality: {total_unverified_rows} table rows have no applicable numeric cross-check")
        doc.error_message = " | ".join(details) or None
        await db.commit()

        # --- Trigger knowledge graph build in the background (non-blocking) ---
        raw_text_for_graph = (doc.raw_text or "").strip()
        if settings.GRAPH_BUILD_ENABLED and doc.status == "completed" and raw_text_for_graph:
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
        raise


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Stream an upload to a unique file and queue PDF OCR outside the request."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    filename = os.path.basename(file.filename)[:500]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {"pdf", "png", "jpg", "jpeg"}:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    from backend.services.document_jobs import prepare_pdf_job, saved_upload_path
    doc = Document(filename=filename, doc_type=ext, status="pending")
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    filepath = saved_upload_path(doc.id, ext)
    bytes_saved = 0
    try:
        with open(filepath, "wb") as target:
            while chunk := await file.read(1024 * 1024):
                bytes_saved += len(chunk)
                if bytes_saved > settings.MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")
                target.write(chunk)
        if not bytes_saved:
            raise HTTPException(status_code=400, detail="Empty upload")

        if ext == "pdf":
            try:
                page_count = await prepare_pdf_job(db, doc, filepath)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid PDF: {exc}") from exc
            return {"id": doc.id, "filename": filename, "status": "pending", "page_count": page_count, "queued": True}

        return await _process_saved_document(doc, str(filepath), ext, db)
    except HTTPException:
        if filepath.is_file():
            filepath.unlink()
        await db.delete(doc)
        await db.commit()
        raise


@router.post("/{doc_id}/resume")
async def resume_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Retry failed/interrupted pages; already indexed pages remain untouched."""
    from backend.services.document_jobs import enqueue_pdf_job, is_pdf_job_active, saved_upload_path
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.doc_type != "pdf":
        raise HTTPException(status_code=400, detail="Only PDF jobs can be resumed")
    if not saved_upload_path(doc_id, "pdf").is_file():
        raise HTTPException(status_code=409, detail="Saved PDF is missing")
    if doc.status == "completed":
        raise HTTPException(status_code=409, detail="Document is already complete")
    if is_pdf_job_active(doc_id):
        return {"id": doc_id, "status": doc.status, "queued": False}
    doc.status = "pending"
    await db.commit()
    queued = enqueue_pdf_job(doc_id)
    return {"id": doc_id, "status": "pending", "queued": queued}


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

    from backend.services.stored_table_evidence import rebuild_page_tables
    rebuilt_tables = rebuild_page_tables(structured, chunks)

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
                "source_page": s.source_page,
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


@router.get("/{doc_id}/pages")
async def list_document_pages(
    doc_id: int, skip: int = 0, limit: int = 25, db: AsyncSession = Depends(get_db),
):
    """Small page-status window; never ships every page's OCR to the browser."""
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    skip = max(skip, 0)
    limit = min(max(limit, 1), 50)
    total = (await db.execute(select(func.count(DocumentPage.id)).where(DocumentPage.document_id == doc_id))).scalar_one()
    pages = (await db.execute(select(DocumentPage).where(
        DocumentPage.document_id == doc_id,
    ).order_by(DocumentPage.page_number).offset(skip).limit(limit))).scalars().all()
    return {
        "document_id": doc_id, "filename": doc.filename, "status": doc.status,
        "total": total, "skip": skip, "limit": limit,
        "pages": [{"page": page.page_number, "status": page.status,
                   "error_stage": page.error_stage, "error_message": page.error_message} for page in pages],
    }


@router.get("/{doc_id}/pages/{page_number}")
async def get_document_page(doc_id: int, page_number: int, db: AsyncSession = Depends(get_db)):
    """Only one selected page's raw OCR, parsed tables, and final stored rows."""
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    page = (await db.execute(select(DocumentPage).where(
        DocumentPage.document_id == doc_id, DocumentPage.page_number == page_number,
    ))).scalar_one_or_none()
    if not doc or not page:
        raise HTTPException(status_code=404, detail="Document page not found")
    chunks = (await db.execute(select(Chunk).where(
        Chunk.document_id == doc_id, Chunk.metadata_["page"].as_integer() == page_number,
    ).order_by(Chunk.chunk_index))).scalars().all()
    raw_pages = []
    retry_pages = []
    raw_tables = []
    quality_reports = []
    for chunk in chunks:
        metadata = chunk.metadata_ or {}
        kind = metadata.get("source_kind")
        if kind in {"raw_ocr_page", "raw_ocr_retry_page"}:
            item = {key: metadata[key] for key in ("page", "region", "crop_box", "rotation", "markdown", "provider_markdown") if key in metadata}
            (raw_pages if kind == "raw_ocr_page" else retry_pages).append(item)
        elif kind == "table_quality":
            quality_reports.append(metadata.get("report") or {})
        elif kind == "raw_ocr_table":
            raw_tables.append({key: value for key, value in metadata.items() if key != "source_kind"})

    try:
        # Gemini tables were intentionally removed from the Typhoon prose.
        # Re-parsing prose alone cannot recover the recorded Gemini output.
        parsed = ({"raw_tables": raw_tables} if raw_tables else
                  ocr_service._parse_markdown_pages(raw_pages) if raw_pages else {"raw_tables": []})
    except Exception as exc:
        logger.warning("Could not parse stored raw OCR for document %d page %d: %s", doc_id, page_number, exc)
        parsed = {"raw_tables": []}
    rows = (await db.execute(select(StructuredData).where(
        StructuredData.document_id == doc_id,
        or_(
            StructuredData.source_page == page_number,
            StructuredData.table_name.contains(f"page_{page_number}_table_", autoescape=True),
        ),
    ).order_by(StructuredData.id))).scalars().all()
    from backend.services.stored_table_evidence import rebuild_page_tables
    structured_tables = rebuild_page_tables(rows, chunks)
    return {
        "document_id": doc_id, "filename": doc.filename, "page": page_number,
        "status": page.status, "error_stage": page.error_stage, "error_message": page.error_message,
        "raw_ocr_pages": raw_pages, "raw_ocr_retry_pages": retry_pages,
        "raw_ocr_tables": parsed.get("raw_tables", []),
        "quality_reports": quality_reports, "structured_tables": structured_tables,
        "image_url": f"/api/documents/{doc_id}/pages/{page_number}/image",
    }


@router.get("/{doc_id}/pages/{page_number}/image")
async def get_document_page_image(
    doc_id: int, page_number: int, dpi: int = 110, db: AsyncSession = Depends(get_db),
):
    """Render one PDF page on demand; never pre-render a whole report."""
    from backend.services.document_jobs import saved_upload_path
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc or doc.doc_type != "pdf":
        raise HTTPException(status_code=404, detail="PDF not found")
    if dpi < 72 or dpi > 150:
        raise HTTPException(status_code=400, detail="dpi must be between 72 and 150")
    path = saved_upload_path(doc_id, "pdf")
    if not path.is_file():
        path = os.path.join(UPLOAD_DIR, os.path.basename(doc.filename))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Saved PDF is unavailable")
    count = await asyncio.to_thread(ocr_service.get_pdf_page_count, str(path))
    if page_number < 1 or page_number > count:
        raise HTTPException(status_code=404, detail="PDF page not found")
    with open(path, "rb") as source:
        pdf_page = PdfReader(source, strict=False).pages[page_number - 1]
        estimated_pixels = float(pdf_page.mediabox.width) * float(pdf_page.mediabox.height) * (dpi / 72.0) ** 2
    if estimated_pixels > 4_000_000:
        raise HTTPException(status_code=413, detail="Page is too large for the preview resolution")
    from backend.services.pdf_render import render_pdf_page
    png = await asyncio.to_thread(render_pdf_page, str(path), page_number, dpi)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.delete("/{doc_id}")
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a document and all associated data."""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    from backend.services.document_jobs import cancel_pdf_job, saved_upload_path
    await cancel_pdf_job(doc_id)
    await db.delete(doc)
    await db.commit()
    saved_path = saved_upload_path(doc_id, doc.doc_type or "pdf")
    if saved_path.is_file():
        saved_path.unlink()
    try:
        from backend.services.duckdb_warehouse import delete_document_data
        delete_document_data(doc_id)
    except Exception as exc:
        logger.warning("Document %d was deleted from PostgreSQL but warehouse cleanup failed: %s", doc_id, exc)
        return {"status": "deleted_with_warehouse_warning", "id": doc_id, "warning": str(exc)}
    return {"status": "deleted", "id": doc_id}
