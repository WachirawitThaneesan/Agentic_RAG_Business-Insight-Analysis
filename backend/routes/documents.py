"""Document management API routes."""

import os
import re
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.database import get_db, AsyncSessionLocal
from backend.models import Document, Chunk, StructuredData
from backend.services.embedding import get_embedding
from backend.services.ocr_artifacts import build_raw_ocr_chunk_payloads
from backend.services.ocr import ocr_service
from backend.services.table_utils import build_table_chunk_payloads, normalize_ocr_tables, rebuild_structured_tables, safe_table_name
from backend.services.thai_cleaner import clean_thai_text
from backend.services.chunker import chunk_document
from backend.config import get_settings

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

    if "StringDataRightTruncationError" in compact and "character varying(500)" in compact:
        return "DB insert failed: table_name too long for structured_data.table_name"
    if "Request timed out" in compact or "Error code: 408" in compact:
        return "Typhoon OCR timeout (408)"
    if "500 Internal Server Error" in compact:
        return "Upstream service returned 500"
    return compact[:220]


def _warning_message(errors: list[str]) -> str:
    failed_pages = []
    reason_parts = []
    for error in errors:
        match = re.search(r"page\s+(\d+)", str(error), flags=re.IGNORECASE)
        if match:
            page = match.group(1)
            failed_pages.append(page)
            reason_parts.append(f"{page}={_summarize_page_error(error)}")

    failed_part = f"Failed pages: {', '.join(failed_pages)}" if failed_pages else ""
    reason_part = f"Failed page reasons: {'; '.join(reason_parts)}" if reason_parts else ""
    return "Partial OCR warnings: " + " | ".join(part for part in [failed_part, reason_part] if part)


def _extract_doc_runtime_info(doc: Document) -> dict:
    message = str(doc.error_message or "").strip()
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
                failed_page_reasons[int(match.group(1))] = match.group(2)

    return {
        "progress_text": progress_text,
        "failed_pages": failed_pages,
        "failed_page_reasons": failed_page_reasons,
        "status_detail": message,
    }


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
        if source_kind.startswith("raw_ocr") and len(chunk_text) > settings.RAW_OCR_ARTIFACT_EMBED_MAX_CHARS:
            embedding = None
        else:
            try:
                embedding = await get_embedding(chunk_text)
            except Exception as exc:
                print(f"⚠️ Raw OCR artifact embedding failed: {exc}")
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
):
    text_blocks = ocr_result.get("text_blocks", [])
    tables = normalize_ocr_tables(filename, ocr_result.get("tables", []))
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
                    row_index=j,
                )
            )

        # Sync to DuckDB warehouse
        try:
            from backend.services.duckdb_warehouse import (
                load_document_dim,
                load_table_into_warehouse,
            )
            load_document_dim(document_id, filename)
            load_table_into_warehouse(
                document_id, tbl_name, headers, rows,
                title=str(table.get("title", "")),
            )
        except Exception as ddb_exc:
            print(f"⚠️ DuckDB sync failed for {tbl_name}: {ddb_exc}")

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

    return {
        "next_chunk_index": next_chunk_index,
        "text_blocks": len(text_blocks),
        "tables_extracted": len(tables),
        "semantic_chunks_created": semantic_chunks_created,
        "table_chunks_created": table_chunks_created,
        "raw_ocr_chunks_created": raw_ocr_chunks_created,
        "raw_pages_stored": sum(
            1 for payload in raw_ocr_chunk_payloads if (payload.get("metadata") or {}).get("source_kind") == "raw_ocr_page"
        ),
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
        next_chunk_index = 0
        stored_raw_pages = 0
        batch_errors = []

        # Step 1: OCR
        if ext == "pdf":
            page_count = ocr_service.get_pdf_page_count(filepath)
            use_large_file_mode = page_count >= settings.PDF_LARGE_FILE_PAGE_THRESHOLD

            for page_num in range(1, page_count + 1):
                raw_page_budget = None
                if settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT >= 0:
                    raw_page_budget = max(settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT - stored_raw_pages, 0)

                try:
                    doc.error_message = _progress_message(page_num, page_count)
                    await db.commit()
                    
                    import fitz  # PyMuPDF
                    
                    # Load page with PyMuPDF
                    doc_fitz = fitz.open(filepath)
                    page_fitz = doc_fitz.load_page(page_num - 1)  # 0-indexed
                    
                    # Always render the PDF page to PNG and OCR that page image.
                    zoom = 300 / 72  # 300 DPI 
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page_fitz.get_pixmap(matrix=mat)
                    img_data = pix.tobytes("png")
                    ocr_result = await ocr_service.extract_from_image(
                        img_data,
                        mime_type="image/png",
                        filename=f"page_{page_num}.png",
                    )
                    
                    doc_fitz.close()

                    batch_result = await _ingest_ocr_batch(
                        db,
                        doc_id,
                        doc,
                        file.filename,
                        ocr_result,
                        next_chunk_index=next_chunk_index,
                        generate_summaries=False if use_large_file_mode else True,
                        raw_page_limit=raw_page_budget,
                    )
                    next_chunk_index = batch_result["next_chunk_index"]
                    total_text_blocks += batch_result["text_blocks"]
                    total_tables_extracted += batch_result["tables_extracted"]
                    stored_raw_pages += batch_result["raw_pages_stored"]
                    await db.commit()
                except Exception as page_error:
                    batch_errors.append(f"page {page_num}: {page_error}")
                    await db.rollback()
                    result = await db.execute(select(Document).where(Document.id == doc_id))
                    doc = result.scalar_one()

            if next_chunk_index == 0:
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

        doc.status = "completed"
        if batch_errors:
            doc.error_message = _warning_message(batch_errors)
        else:
            doc.error_message = None
        await db.commit()

        return {
            "id": doc_id,
            "filename": doc.filename,
            "status": "completed",
            "text_blocks": total_text_blocks,
            "tables_extracted": total_tables_extracted,
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
        # Count chunks
        chunk_count = await db.execute(
            select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
        )
        # Count structured rows
        table_count = await db.execute(
            select(func.count(StructuredData.id)).where(StructuredData.document_id == doc.id)
        )

        runtime_info = _extract_doc_runtime_info(doc)
        items.append({
            "id": doc.id,
            "filename": doc.filename,
            "source_url": doc.source_url,
            "doc_type": doc.doc_type,
            "status": doc.status,
            "progress_text": runtime_info["progress_text"],
            "failed_pages": runtime_info["failed_pages"],
            "failed_page_reasons": runtime_info["failed_page_reasons"],
            "status_detail": runtime_info["status_detail"],
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
    raw_ocr_tables = []
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

    return {
        "id": doc.id,
        "filename": doc.filename,
        "source_url": doc.source_url,
        "doc_type": doc.doc_type,
        "status": doc.status,
        "raw_text": doc.raw_text,
        "error_message": doc.error_message,
        "runtime_info": _extract_doc_runtime_info(doc),
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
        "raw_ocr_tables": raw_ocr_tables,
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
    return {"status": "deleted", "id": doc_id}
