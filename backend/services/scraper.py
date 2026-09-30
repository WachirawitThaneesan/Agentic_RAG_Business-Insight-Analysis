"""
Web scraper service — calls pw_worker.py in a separate process
to avoid Uvicorn event-loop conflicts on Windows.
"""

import os
import sys
import re
import json
import logging
import time
import asyncio
import subprocess
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Document, Chunk
from backend.config import get_settings
from backend.services.chunker import chunk_document
from backend.services.thai_cleaner import clean_thai_text
from backend.services.pdf_discovery import CrawlLimits, discover_public_pdfs, download_public_pdfs

settings = get_settings()
logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "scrape_output")
OUTPUT_DIR = os.path.abspath(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Run as a module so absolute backend imports work on Windows too.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PYTHON_EXE = sys.executable
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
    env["PYTHONPATH"] = REPO_ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    cmd = [PYTHON_EXE, "-u", "-m", "backend.services.pw_worker",
           command, json.dumps(args, ensure_ascii=False)]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=REPO_ROOT,
        )
        stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.warning("pw_worker timed out (%ss)", timeout_sec)
        return None
    except Exception as e:
        logger.warning("pw_worker failed to start: %s", e)
        return None

    # Decode output safely
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if proc.returncode != 0:
        logger.warning("pw_worker [%s] exit code %s: %s", command, proc.returncode, stderr[-500:])
        return None

    marker = "__PW_RESULT__"
    if marker in stdout:
        json_str = stdout.split(marker, 1)[1].strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("pw_worker JSON parse error: %s; %s", e, json_str[:300])
            return None
    else:
        logger.warning("pw_worker result marker missing; stdout=%s stderr=%s",
                       stdout[:300], stderr[:300])
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
    """Register a downloaded file through the upload ingestion path."""
    from pathlib import Path
    import shutil
    from backend.services.document_jobs import prepare_pdf_job, saved_upload_path
    from backend.routes.documents import _process_saved_document

    source = Path(filepath)
    if not source.is_file():
        return {"error": f"File not found: {filepath}", "source_kind": "scraped_file"}

    ext = source.suffix.lower().lstrip(".")
    if ext not in {"pdf", "png", "jpg", "jpeg"}:
        return {"error": f"Unsupported scraped file type: {ext}", "source_kind": "scraped_file"}
    size = source.stat().st_size
    if not size or size > settings.MAX_UPLOAD_BYTES:
        return {"error": "Scraped file is empty or exceeds configured size limit",
                "source_kind": "scraped_file", "filepath": filepath}

    filename = source.name[:500]
    doc_id = None
    try:
        async with AsyncSessionLocal() as db:
            doc = Document(filename=filename, doc_type=ext,
                           source_url=(source_url or None), status="pending")
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            doc_id = doc.id
            saved_path = saved_upload_path(doc_id, ext)
            await asyncio.to_thread(shutil.copyfile, source, saved_path)

            if ext == "pdf":
                page_count = await prepare_pdf_job(db, doc, saved_path)
                return {
                    "document_id": doc_id, "filename": filename, "doc_type": ext,
                    "status": "pending", "queued": True, "page_count": page_count,
                    "chunks_created": 0, "tables_extracted": 0,
                    "source_kind": "scraped_file", "filepath": filepath,
                }

            result = await _process_saved_document(doc, str(saved_path), ext, db)
            return {
                "document_id": doc_id, "filename": filename, "doc_type": ext,
                "status": result["status"], "chunks_created": result["chunks_created"],
                "tables_extracted": result["tables_extracted"],
                "source_kind": "scraped_file", "filepath": filepath,
            }
    except Exception as exc:
        logger.exception("Failed to register scraped file %s", filepath)
        if doc_id is not None:
            try:
                async with AsyncSessionLocal() as failure_db:
                    failed_doc = (await failure_db.execute(
                        select(Document).where(Document.id == doc_id)
                    )).scalar_one_or_none()
                    if failed_doc:
                        failed_doc.status = "failed"
                        failed_doc.error_message = str(exc) or type(exc).__name__
                        await failure_db.commit()
            except Exception:
                logger.exception("Could not mark scraped document %s failed", doc_id)
        return {"error": str(exc), "document_id": doc_id,
                "source_kind": "scraped_file", "filepath": filepath}

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

    file_details = {item.get("path"): item for item in result.get("file_details", []) if item.get("path")}
    for filepath in result.get("files", []):
        detail = file_details.get(filepath, {})
        file_doc = await _ingest_scraped_file(filepath, source_url=detail.get("download_url") or url)
        if file_doc.get("error"):
            errors.append(file_doc["error"])
        else:
            file_doc.update({key: detail.get(key) for key in
                             ("download_url", "discovery_page", "downloaded_at", "sha256")
                             if detail.get(key)})
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
    file_details = {item.get("path"): item for item in result.get("file_details", []) if item.get("path")}
    for file_index, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
        file_kind = "PDF" if ext == "pdf" else "รูปภาพ"
        yield {
            "status": "processing",
            "message": f"📄 [{file_index}/{len(files)}] กำลังบันทึก {file_kind} '{filename}'..."
        }

        detail = file_details.get(filepath, {})
        file_doc = await _ingest_scraped_file(filepath, source_url=detail.get("download_url") or url)
        if file_doc.get("error"):
            errors.append(file_doc["error"])
            yield {
                "status": "warning",
                "message": f"⚠️ OCR/นำเข้าไฟล์ '{filename}' ไม่สำเร็จ: {file_doc['error']}"
            }
        else:
            file_doc.update({key: detail.get(key) for key in
                             ("download_url", "discovery_page", "downloaded_at", "sha256")
                             if detail.get(key)})
            ingested_docs.append(file_doc)
            if file_doc.get("queued"):
                message = (
                    f"📋 จัดคิว OCR '{filename}' แล้ว ({file_doc.get('page_count', 0)} หน้า); "
                    "ตรวจสถานะและหน้าที่ล้มเหลวใน Documents"
                )
            else:
                message = (
                    f"✅ นำเข้าไฟล์ '{filename}' เสร็จแล้ว "
                    f"({file_doc.get('chunks_created', 0)} chunks, {file_doc.get('tables_extracted', 0)} tables)"
                )
            yield {
                "status": "processing",
                "message": message,
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
            f"🧠 ลงทะเบียน {len(ingested_docs)} เอกสาร; "
            f"PDF ที่จัดคิว {sum(bool(doc.get('queued')) for doc in ingested_docs)} ไฟล์กำลังประมวลผลเบื้องหลัง"
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


def _browser_report_links(url: str) -> list[dict]:
    result = _run_pw_worker("extract_links", {"url": url}, timeout_sec=55)
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError((result or {}).get("error", "Browser link extraction failed")
                           if isinstance(result, dict) else "Browser link extraction failed")
    return result.get("links", [])


async def discover_url(
    url: str, *, max_pages: int = 20, max_depth: int = 2,
    max_pdfs: int = 20, max_seconds: float = 90,
    browser_fallback: bool = True,
) -> Dict[str, Any]:
    """Find verified public PDF links without downloading or ingesting them."""
    if settings.OFFLINE_MODE:
        raise RuntimeError("Public website discovery is disabled in OFFLINE_MODE")
    limits = CrawlLimits(max_pages=max(1, min(max_pages, 100)),
                         max_depth=max(0, min(max_depth, 4)),
                         max_pdfs=max(1, min(max_pdfs, 100)),
                         max_seconds=max(5, min(max_seconds, 300)))
    return await asyncio.to_thread(
        discover_public_pdfs, url, limits,
        _browser_report_links if browser_fallback else None,
    )


async def scrape_url(
    url: str,
    download_pdfs: bool = True,
    download_images: bool = False,
    max_files: int = 20,
    save_folder: str = "",
) -> Dict[str, Any]:
    """Collect report PDFs with HTTP first; use Playwright for requested images."""
    if settings.OFFLINE_MODE:
        raise RuntimeError("Public website collection is disabled in OFFLINE_MODE")
    max_files = max(0, min(max_files, 100))
    if download_images:
        result = await asyncio.to_thread(
            _run_pw_worker, "scrape_url",
            {"url": url, "max_files": max_files if download_pdfs else 0,
             "save_folder": save_folder},
        )
        if not isinstance(result, dict):
            return {"success": False, "error": "Playwright worker failed", "files": [],
                    "images": [], "page_text": "", "links_found": [], "url": url}
        return await _ingest_scraped_result(url, result)

    discovery = await discover_url(url, max_pdfs=max_files, browser_fallback=True)
    folder = save_folder or os.path.join(
        OUTPUT_DIR, f"{_safe_folder_name(urlparse(url).netloc)}_{time.strftime('%Y%m%d_%H%M%S')}",
    )
    download = (
        await asyncio.to_thread(download_public_pdfs, discovery, folder,
                                max_files, settings.MAX_UPLOAD_BYTES)
        if download_pdfs else {"files": [], "file_details": [], "manifest_path": ""}
    )
    result = {
        "success": bool(discovery["visited_pages"] or discovery["pdfs"]),
        "url": url, "folder": folder, "page_text": discovery.get("page_text", ""),
        "files": download["files"], "file_details": download["file_details"],
        "images": [], "links_found": discovery["pdfs"], "discovery": discovery,
        "manifest_path": download["manifest_path"],
        "files_downloaded": sum(item["status"] == "downloaded" for item in download["file_details"]),
        "files_duplicate": sum(item["status"] == "duplicate" for item in download["file_details"]),
        "files_failed": sum(item["status"] == "failed" for item in download["file_details"]),
    }
    return await _ingest_scraped_result(url, result)


async def scrape_by_keyword(
    keyword: str,
    max_sites: int = 3,
    max_files_per_site: int = 10,
):
    """Use the browser for search, then crawl each result with plain HTTP first."""
    yield {"status": "searching", "message": f"🔍 กำลังค้นหา keyword '{keyword}' ใน Google..."}
    found = await fetch_google_search_results(keyword, max_results=max(1, min(max_sites, 10)))
    urls = [item.get("url", "") for item in found if item.get("url")]
    if not urls:
        yield {"status": "done", "result": {
            "keyword": keyword, "urls_scraped": 0, "urls": [], "total_files": 0,
            "total_images": 0, "files": [], "results": [
                {"success": False, "error": "ไม่พบผลลัพธ์จาก Google หรือเกิดข้อผิดพลาดในการค้นหา"}],
        }}
        return

    yield {"status": "found", "message": f"🌐 พบ {len(urls)} เว็บไซต์ กำลังนำเข้าข้อมูลสู่ระบบ..."}
    results = []
    for idx, source_url in enumerate(urls, 1):
        domain = _safe_folder_name(urlparse(source_url).netloc)
        yield {"status": "scraping", "message": f"🧭 [เว็บ {idx}/{len(urls)}] ค้นหา PDF จาก {domain}..."}
        try:
            result = await scrape_url(source_url, max_files=max_files_per_site,
                                      download_images=False)
        except Exception as exc:
            result = {"success": False, "url": source_url, "files": [], "images": [],
                      "error": str(exc)}
        results.append(result)
        yield {"status": "processing", "message": (
            f"[เว็บ {idx}/{len(urls)}] พบ PDF ที่ดาวน์โหลดได้ {len(result.get('files', []))} ไฟล์"
        )}

    yield {"status": "done", "result": {
        "keyword": keyword, "urls_scraped": len(urls), "urls": urls,
        "total_files": sum(len(r.get("files", [])) for r in results),
        "total_images": 0,
        "files": [path for r in results for path in r.get("files", [])],
        "results": results,
    }}
