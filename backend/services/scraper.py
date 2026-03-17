"""
Web scraper service — calls pw_worker.py in a separate process
to avoid Uvicorn event-loop conflicts on Windows.
"""

import os
import sys
import re
import json
import time
import asyncio
import subprocess
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from backend.database import AsyncSessionLocal
from backend.models import Document, Chunk, StructuredData
from backend.config import get_settings
from backend.services.chunker import chunk_document
from backend.services.embedding import get_embedding
from backend.services.ocr_artifacts import build_raw_ocr_chunk_payloads
from backend.services.ocr import ocr_service
from backend.services.table_utils import build_table_chunk_payloads, normalize_ocr_tables
from backend.services.thai_cleaner import clean_thai_text

settings = get_settings()

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "scrape_output")
OUTPUT_DIR = os.path.abspath(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Path to the worker script
PW_WORKER = os.path.join(os.path.dirname(__file__), "pw_worker.py")
PYTHON_EXE = sys.executable
IMAGE_MIME_MAP = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def _safe_folder_name(name: str, max_len: int = 40) -> str:
    name = re.sub(r'[\\/*?"<>|:]', '', name or '')
    name = re.sub(r'\s+', '_', name).strip('_')
    return name[:max_len] or "site"


def _run_pw_worker(command: str, args: dict, timeout_sec: int = 300) -> Any:
    """Run pw_worker.py in a subprocess and return the parsed JSON result."""
    # Force UTF-8 encoding in the child process
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONLEGACYWINDOWSSTDIO"] = "0"

    cmd = [PYTHON_EXE, "-u", PW_WORKER, command, json.dumps(args, ensure_ascii=False)]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        print(f"⚠️ pw_worker timed out ({timeout_sec}s)")
        return None
    except Exception as e:
        print(f"⚠️ pw_worker failed to start: {e}")
        return None

    # Decode output safely
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if proc.returncode != 0:
        print(f"⚠️ pw_worker [{command}] exit code {proc.returncode}")
        print(f"   stderr: {stderr[-500:]}")
        return None

    marker = "__PW_RESULT__"
    if marker in stdout:
        json_str = stdout.split(marker, 1)[1].strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parse error: {e}")
            print(f"   json_str: {json_str[:300]}")
            return None
    else:
        print(f"⚠️ No result marker in worker output")
        print(f"   stdout: {stdout[:300]}")
        print(f"   stderr: {stderr[:300]}")
        return None


def _extract_text_for_ingestion(result: Dict[str, Any]) -> str:
    page_text = (result.get("page_text") or "").strip()
    content_path = result.get("content_path") or ""
    if content_path and os.path.exists(content_path):
        try:
            with open(content_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            separator = "=" * 60
            if separator in content:
                content = content.split(separator, 1)[1].strip()
            if len(content) > len(page_text):
                page_text = content
        except Exception:
            pass
    return page_text


async def _store_structured_tables(
    db,
    document_id: int,
    table_prefix: str,
    tables: List[Dict[str, Any]],
) -> None:
    for i, table in enumerate(tables):
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        for j, row in enumerate(rows):
            row_dict = dict(zip(headers, row)) if headers else {"data": row}
            db.add(
                StructuredData(
                    document_id=document_id,
                    table_name=table.get("table_name") or f"{table_prefix}_table_{i}",
                    headers=headers,
                    row_data=row_dict,
                    row_index=j,
                )
            )


async def _store_chunks(db, document_id: int, cleaned_text: str, generate_summaries: bool = True, start_index: int = 0) -> int:
    if not cleaned_text.strip():
        return 0

    chunk_results = await chunk_document(cleaned_text, generate_summaries=generate_summaries)
    for cr in chunk_results:
        db.add(
            Chunk(
                document_id=document_id,
                chunk_index=start_index + cr.chunk_index,
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


async def _store_prebuilt_chunks(
    db,
    document_id: int,
    chunk_payloads: List[Dict[str, Any]],
    start_index: int = 0,
) -> int:
    created = 0

    for offset, payload in enumerate(chunk_payloads):
        chunk_text = (payload.get("text") or "").strip()
        if not chunk_text:
            continue

        try:
            embedding = await get_embedding(chunk_text)
        except Exception as exc:
            if (payload.get("metadata") or {}).get("source_kind", "").startswith("raw_ocr"):
                print(f"⚠️ Raw OCR artifact embedding failed: {exc}")
                embedding = None
            else:
                raise
        metadata = {
            "source_kind": "table_csv",
            "table_name": payload.get("table_name"),
            "table_title": payload.get("title"),
            "headers": payload.get("headers", []),
            "row_start": payload.get("row_start"),
            "row_end": payload.get("row_end"),
        }
        metadata.update(payload.get("metadata", {}))
        db.add(
            Chunk(
                document_id=document_id,
                chunk_index=start_index + offset,
                chunk_text=chunk_text,
                summary=payload.get("summary", ""),
                token_count=len(chunk_text.split()),
                embedding=embedding,
                metadata_=metadata,
            )
        )
        created += 1

    return created


async def _ingest_web_text_document(url: str, page_text: str) -> Dict[str, Any]:
    cleaned_text = clean_thai_text(page_text)
    if not cleaned_text:
        return {}

    try:
        async with AsyncSessionLocal() as db:
            doc = Document(
                filename=_safe_folder_name(urlparse(url).netloc) + ".txt",
                doc_type="web_scrape",
                source_url=url,
                raw_text=cleaned_text,
                status="processing"
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)

            chunks_created = await _store_chunks(db, doc.id, cleaned_text)

            doc.status = "completed"
            await db.commit()

            return {
                "document_id": doc.id,
                "filename": doc.filename,
                "doc_type": doc.doc_type,
                "chunks_created": chunks_created,
                "tables_extracted": 0,
                "source_kind": "web_text",
            }
    except Exception as e:
        print(f"⚠️ Failed to ingest scraped content into RAG: {e}")
        return {"error": str(e), "source_kind": "web_text"}


async def _ingest_scraped_file(filepath: str, source_url: str = "") -> Dict[str, Any]:
    if not filepath or not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}", "source_kind": "scraped_file"}

    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    if ext not in ("pdf", "png", "jpg", "jpeg"):
        return {"error": f"Unsupported scraped file type: {ext}", "source_kind": "scraped_file"}

    filename = os.path.basename(filepath)

    try:
        async with AsyncSessionLocal() as db:
            doc = Document(
                filename=filename,
                doc_type=ext,
                source_url=source_url or None,
                status="processing",
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            doc_id = doc.id

            chunks_created = 0
            total_text_blocks = 0
            total_tables = 0
            stored_raw_pages = 0
            batch_errors = []

            if ext == "pdf":
                page_count = ocr_service.get_pdf_page_count(filepath)
                use_large_file_mode = page_count >= settings.PDF_LARGE_FILE_PAGE_THRESHOLD

                if use_large_file_mode:
                    for batch_start in range(1, page_count + 1, settings.PDF_OCR_BATCH_SIZE):
                        batch_end = min(batch_start + settings.PDF_OCR_BATCH_SIZE - 1, page_count)
                        batch_pages = list(range(batch_start, batch_end + 1))
                        raw_page_budget = None
                        if settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT >= 0:
                            raw_page_budget = max(settings.PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT - stored_raw_pages, 0)

                        try:
                            ocr_result = await ocr_service.extract_from_pdf_path(
                                filepath,
                                filename=filename,
                                pages=batch_pages,
                            )
                            text_blocks = ocr_result.get("text_blocks", [])
                            tables = normalize_ocr_tables(filename, ocr_result.get("tables", []))
                            raw_ocr_chunk_payloads = build_raw_ocr_chunk_payloads(
                                filename,
                                ocr_result,
                                max_pages=raw_page_budget,
                            )
                            cleaned_text = clean_thai_text("\n\n".join(text_blocks))
                            table_chunk_payloads = build_table_chunk_payloads(filename, tables)
                            table_csv_text = "\n\n".join(
                                f"[TABLE] {table.get('table_name')}\n{table.get('csv_text')}"
                                for table in tables
                                if table.get("csv_text")
                            ).strip()
                            _append_document_raw_text(
                                doc,
                                "\n\n".join(part for part in [cleaned_text, table_csv_text] if part).strip(),
                            )

                            await _store_structured_tables(db, doc_id, filename, tables)
                            chunks_created += await _store_chunks(
                                db,
                                doc_id,
                                cleaned_text,
                                generate_summaries=settings.PDF_LARGE_FILE_GENERATE_SUMMARIES,
                                start_index=chunks_created,
                            )
                            chunks_created += await _store_prebuilt_chunks(
                                db,
                                doc_id,
                                table_chunk_payloads,
                                start_index=chunks_created,
                            )
                            chunks_created += await _store_prebuilt_chunks(
                                db,
                                doc_id,
                                raw_ocr_chunk_payloads,
                                start_index=chunks_created,
                            )
                            total_text_blocks += len(text_blocks)
                            total_tables += len(tables)
                            stored_raw_pages += sum(
                                1 for payload in raw_ocr_chunk_payloads if (payload.get("metadata") or {}).get("source_kind") == "raw_ocr_page"
                            )
                            await db.commit()
                        except Exception as batch_error:
                            batch_errors.append(f"pages {batch_start}-{batch_end}: {batch_error}")
                            await db.rollback()
                            result = await db.execute(select(Document).where(Document.id == doc_id))
                            doc = result.scalar_one()
                else:
                    with open(filepath, "rb") as f:
                        file_bytes = f.read()
                    ocr_result = await ocr_service.extract_from_pdf(file_bytes, filename=filename)
                    text_blocks = ocr_result.get("text_blocks", [])
                    tables = normalize_ocr_tables(filename, ocr_result.get("tables", []))
                    raw_ocr_chunk_payloads = build_raw_ocr_chunk_payloads(filename, ocr_result)
                    cleaned_text = clean_thai_text("\n\n".join(text_blocks))
                    table_chunk_payloads = build_table_chunk_payloads(filename, tables)
                    table_csv_text = "\n\n".join(
                        f"[TABLE] {table.get('table_name')}\n{table.get('csv_text')}"
                        for table in tables
                        if table.get("csv_text")
                    ).strip()
                    _append_document_raw_text(
                        doc,
                        "\n\n".join(part for part in [cleaned_text, table_csv_text] if part).strip(),
                    )

                    await _store_structured_tables(db, doc_id, filename, tables)
                    chunks_created += await _store_chunks(db, doc_id, cleaned_text, start_index=chunks_created)
                    chunks_created += await _store_prebuilt_chunks(
                        db,
                        doc_id,
                        table_chunk_payloads,
                        start_index=chunks_created,
                    )
                    chunks_created += await _store_prebuilt_chunks(
                        db,
                        doc_id,
                        raw_ocr_chunk_payloads,
                        start_index=chunks_created,
                    )
                    total_text_blocks = len(text_blocks)
                    total_tables = len(tables)
            else:
                with open(filepath, "rb") as f:
                    file_bytes = f.read()
                ocr_result = await ocr_service.extract_from_image(
                    file_bytes,
                    IMAGE_MIME_MAP.get(ext, "image/png"),
                    filename=filename,
                )
                text_blocks = ocr_result.get("text_blocks", [])
                tables = normalize_ocr_tables(filename, ocr_result.get("tables", []))
                raw_ocr_chunk_payloads = build_raw_ocr_chunk_payloads(filename, ocr_result)
                cleaned_text = clean_thai_text("\n\n".join(text_blocks))
                table_chunk_payloads = build_table_chunk_payloads(filename, tables)
                table_csv_text = "\n\n".join(
                    f"[TABLE] {table.get('table_name')}\n{table.get('csv_text')}"
                    for table in tables
                    if table.get("csv_text")
                ).strip()
                _append_document_raw_text(
                    doc,
                    "\n\n".join(part for part in [cleaned_text, table_csv_text] if part).strip(),
                )

                await _store_structured_tables(db, doc_id, filename, tables)
                chunks_created += await _store_chunks(db, doc_id, cleaned_text, start_index=chunks_created)
                chunks_created += await _store_prebuilt_chunks(
                    db,
                    doc_id,
                    table_chunk_payloads,
                    start_index=chunks_created,
                )
                chunks_created += await _store_prebuilt_chunks(
                    db,
                    doc_id,
                    raw_ocr_chunk_payloads,
                    start_index=chunks_created,
                )
                total_text_blocks = len(text_blocks)
                total_tables = len(tables)

            doc.status = "completed"
            if batch_errors:
                doc.error_message = "Partial OCR warnings: " + "; ".join(batch_errors[:10])
            await db.commit()

            return {
                "document_id": doc.id,
                "filename": filename,
                "doc_type": ext,
                "chunks_created": chunks_created,
                "tables_extracted": total_tables,
                "text_blocks": total_text_blocks,
                "source_kind": "scraped_file",
                "filepath": filepath,
            }
    except Exception as e:
        print(f"⚠️ Failed to OCR/ingest scraped file {filepath}: {e}")
        return {"error": str(e), "source_kind": "scraped_file", "filepath": filepath}


async def _ingest_scraped_result(url: str, result: Dict[str, Any]) -> Dict[str, Any]:
    ingested_docs = []
    errors = []

    page_text = _extract_text_for_ingestion(result)
    if page_text:
        web_doc = await _ingest_web_text_document(url, page_text)
        if web_doc.get("error"):
            errors.append(web_doc["error"])
        elif web_doc:
            ingested_docs.append(web_doc)

    for filepath in result.get("files", []):
        file_doc = await _ingest_scraped_file(filepath, source_url=url)
        if file_doc.get("error"):
            errors.append(file_doc["error"])
        else:
            ingested_docs.append(file_doc)

    if ingested_docs:
        result["rag_documents"] = ingested_docs
        result["rag_document_ids"] = [doc["document_id"] for doc in ingested_docs if doc.get("document_id")]
        result["rag_chunks_created"] = sum(doc.get("chunks_created", 0) for doc in ingested_docs)
        result["rag_document_id"] = result["rag_document_ids"][0] if result["rag_document_ids"] else None

    if errors:
        result["rag_error"] = "; ".join(errors)

    return result


async def _ingest_scraped_result_with_progress(url: str, result: Dict[str, Any]):
    ingested_docs = []
    errors = []

    page_text = _extract_text_for_ingestion(result)
    if page_text:
        yield {
            "status": "processing",
            "message": "📝 กำลังทำความสะอาดข้อความจากหน้าเว็บและเตรียมแบ่ง chunk..."
        }
        web_doc = await _ingest_web_text_document(url, page_text)
        if web_doc.get("error"):
            errors.append(web_doc["error"])
            yield {
                "status": "warning",
                "message": f"⚠️ นำเข้าข้อความหน้าเว็บไม่สำเร็จ: {web_doc['error']}"
            }
        elif web_doc:
            ingested_docs.append(web_doc)
            yield {
                "status": "processing",
                "message": f"✅ นำเข้าข้อความหน้าเว็บเสร็จแล้ว ({web_doc.get('chunks_created', 0)} chunks)"
            }

    files = result.get("files", [])
    for file_index, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
        file_kind = "PDF" if ext == "pdf" else "รูปภาพ"
        yield {
            "status": "ocr",
            "message": f"📄 [{file_index}/{len(files)}] กำลัง OCR {file_kind} '{filename}'..."
        }

        file_doc = await _ingest_scraped_file(filepath, source_url=url)
        if file_doc.get("error"):
            errors.append(file_doc["error"])
            yield {
                "status": "warning",
                "message": f"⚠️ OCR/นำเข้าไฟล์ '{filename}' ไม่สำเร็จ: {file_doc['error']}"
            }
        else:
            ingested_docs.append(file_doc)
            yield {
                "status": "processing",
                "message": (
                    f"✅ นำเข้าไฟล์ '{filename}' เสร็จแล้ว "
                    f"({file_doc.get('chunks_created', 0)} chunks, {file_doc.get('tables_extracted', 0)} tables)"
                )
            }

    if ingested_docs:
        result["rag_documents"] = ingested_docs
        result["rag_document_ids"] = [doc["document_id"] for doc in ingested_docs if doc.get("document_id")]
        result["rag_chunks_created"] = sum(doc.get("chunks_created", 0) for doc in ingested_docs)
        result["rag_document_id"] = result["rag_document_ids"][0] if result["rag_document_ids"] else None

    if errors:
        result["rag_error"] = "; ".join(errors)

    yield {
        "status": "processing",
        "message": (
            f"🧠 สรุปการนำเข้าเสร็จแล้ว: {len(ingested_docs)} เอกสาร, "
            f"{result.get('rag_chunks_created', 0)} chunks"
        )
    }



# ============================================================
# Async wrappers for FastAPI
# ============================================================
async def fetch_google_search_results(keyword: str, max_results: int = 3) -> List[Dict[str, str]]:
    """Search Google via Playwright subprocess."""
    result = await asyncio.to_thread(
        _run_pw_worker,
        "google_search",
        {"keyword": keyword, "max_results": max_results},
    )
    return result if isinstance(result, list) else []


async def scrape_url(
    url: str,
    download_pdfs: bool = True,
    download_images: bool = True,
    max_files: int = 20,
    save_folder: str = "",
) -> Dict[str, Any]:
    """Scrape a URL via Playwright subprocess."""
    result = await asyncio.to_thread(
        _run_pw_worker,
        "scrape_url",
        {"url": url, "max_files": max_files, "save_folder": save_folder},
    )
    if result is None:
        return {
            "success": False,
            "error": "Playwright worker failed — check terminal for details",
            "files": [],
            "images": [],
            "page_text": "",
            "links_found": [],
            "url": url,
        }

    return await _ingest_scraped_result(url, result)


async def scrape_by_keyword(
    keyword: str,
    max_sites: int = 3,
    max_files_per_site: int = 10,
):
    """Search Google for keyword, follow top N links, and scrape them (Async Generator)."""
    yield {"status": "searching", "message": f"🔍 กำลังค้นหา keyword '{keyword}' ใน Google..."}
    yield {"status": "scraping", "message": f"🧭 ใช้ browser session เดียวค้นหาและดึงข้อมูลสูงสุด {max_sites} เว็บ..."}

    worker_result = await asyncio.to_thread(
        _run_pw_worker,
        "scrape_by_keyword",
        {
            "keyword": keyword,
            "max_sites": max_sites,
            "max_files_per_site": max_files_per_site,
        },
        max(300, 180 * max_sites),
    )

    if not isinstance(worker_result, dict):
        yield {
            "status": "done",
            "result": {
                "keyword": keyword,
                "output_folder": "",
                "urls_scraped": 0,
                "urls": [],
                "total_files": 0,
                "total_images": 0,
                "files": [],
                "results": [{"success": False, "error": "Playwright worker failed — check terminal for details"}],
            }
        }
        return

    results = worker_result.get("results", [])
    urls = worker_result.get("urls", [])

    if not urls:
        yield {
            "status": "done",
            "result": {
                "keyword": keyword,
                "output_folder": worker_result.get("output_folder", ""),
                "urls_scraped": 0,
                "urls": [],
                "total_files": 0,
                "total_images": 0,
                "files": [],
                "results": [{"success": False, "error": "ไม่พบผลลัพธ์จาก Google หรือเกิดข้อผิดพลาดในการค้นหา"}],
            }
        }
        return

    yield {"status": "found", "message": f"🌐 พบ {len(urls)} เว็บไซต์ กำลังนำเข้าข้อมูลสู่ระบบ..."}

    for idx, result in enumerate(results, 1):
        source_url = result.get("source_url") or result.get("url") or ""
        domain = _safe_folder_name(urlparse(source_url).netloc) if source_url else f"site_{idx}"
        yield {"status": "ingesting", "message": f"🧠 [เว็บ {idx}/{len(results)}] เริ่มนำเข้าข้อมูลจาก {domain} สู่ระบบ RAG..."}
        async for progress in _ingest_scraped_result_with_progress(source_url, result):
            yield {
                "status": progress.get("status", "processing"),
                "message": f"[เว็บ {idx}/{len(results)}] {progress.get('message', '')}"
            }

    worker_result["results"] = results
    worker_result["total_files"] = sum(len(r.get("files", [])) for r in results)
    worker_result["total_images"] = sum(len(r.get("images", [])) for r in results)
    worker_result["files"] = [path for r in results for path in r.get("files", [])]

    yield {"status": "done", "result": worker_result}
