"""Exercise real 200-500 page PDF checkpoints with text-backed, local fake OCR.

This isolates queue/restart/storage behavior. It does NOT measure OCR accuracy or
full OCR throughput. It creates and later drops an isolated PostgreSQL database.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from unittest.mock import patch

import asyncpg
import pymupdf
from sqlalchemy.engine import make_url


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def working_set_bytes(pid: int | None = None) -> int | None:
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    current_process = ctypes.windll.kernel32.GetCurrentProcess
    current_process.restype = ctypes.c_void_p
    open_process = ctypes.windll.kernel32.OpenProcess
    open_process.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    open_process.restype = ctypes.c_void_p
    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    memory_info.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    memory_info.restype = ctypes.c_int
    handle = open_process(0x0410, 0, pid) if pid is not None else current_process()
    if not handle:
        return None
    try:
        ok = memory_info(handle, ctypes.byref(counters), counters.cb)
    finally:
        if pid is not None:
            close_handle(handle)
    return int(counters.WorkingSetSize) if ok else None


class MemorySampler:
    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(0.2):
            value = working_set_bytes()
            if value:
                self.peak = max(self.peak, value)

    def __enter__(self):
        self.peak = working_set_bytes() or 0
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self._stop.set()
        self._thread.join()


async def _admin_connect(base_url: str):
    url = make_url(base_url).set(database="postgres")
    return await asyncpg.connect(
        host=url.host, port=url.port or 5432, user=url.username,
        password=url.password, database=url.database,
    )


async def _create_test_db(base_url: str, name: str) -> None:
    conn = await _admin_connect(base_url)
    try:
        if await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
            raise RuntimeError(f"Refusing to reuse existing test database: {name}")
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_test_db(base_url: str, name: str) -> None:
    conn = await _admin_connect(base_url)
    try:
        await conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def run_test(pdf: Path, interrupt_at: int, output: Path, db_name: str) -> dict:
    from backend.config import get_settings

    base_url = get_settings().DATABASE_URL
    await _create_test_db(base_url, db_name)
    db_url = make_url(base_url).set(database=db_name)
    os.environ["DATABASE_URL"] = db_url.render_as_string(hide_password=False)
    os.environ["DATABASE_URL_SYNC"] = db_url.set(drivername="postgresql").render_as_string(hide_password=False)
    os.environ["DUCKDB_PATH"] = str(output.with_suffix(".duckdb"))
    os.environ["GRAPH_BUILD_ENABLED"] = "false"
    get_settings.cache_clear()

    from backend.database import AsyncSessionLocal, engine, init_db
    from backend.models import Chunk, Document, DocumentPage
    from backend.routes import documents
    from backend.services import chunker, document_jobs
    from backend.services.duckdb_warehouse import close_warehouse
    from sqlalchemy import func, select

    await init_db()
    with pymupdf.open(pdf) as source:
        total_pages = len(source)
    if not 200 <= total_pages <= 500:
        raise ValueError(f"Expected 200-500 PDF pages; got {total_pages}")
    if not 1 < interrupt_at < total_pages:
        raise ValueError("Interrupt page must be inside the PDF")

    attempts: dict[int, int] = {}
    should_interrupt = True
    pdf_handle = pymupdf.open(pdf)

    async def text_backed_ocr(_path, filename, pages, **_kwargs):
        nonlocal should_interrupt
        page = pages[0]
        attempts[page] = attempts.get(page, 0) + 1
        if page == interrupt_at and should_interrupt:
            should_interrupt = False
            raise asyncio.CancelledError("controlled restart at page checkpoint")
        text = pdf_handle[page - 1].get_text().strip()
        return {"raw_pages": [{"page": page, "markdown": text}],
                "text_blocks": [text] if text else [], "tables": [],
                "table_extraction_warnings": []}

    async def fake_embedding(_text):
        return [0.0] * 1024

    async def fake_batch(texts):
        return [[0.0] * 1024 for _ in texts]

    doc_id = None
    try:
        async with AsyncSessionLocal() as db:
            doc = Document(filename=pdf.name, doc_type="pdf", status="pending")
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            doc_id = doc.id

        start = time.perf_counter()
        with MemorySampler() as memory, \
             patch.object(documents.ocr_service, "extract_from_pdf_path", side_effect=text_backed_ocr), \
             patch.object(documents, "get_embedding", side_effect=fake_embedding), \
             patch.object(chunker, "get_embedding", side_effect=fake_embedding), \
             patch.object(chunker, "get_embeddings_batch", side_effect=fake_batch), \
             patch.object(document_jobs, "saved_upload_path", return_value=pdf):
            async with AsyncSessionLocal() as db:
                doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                try:
                    await documents._process_saved_document(doc, str(pdf), "pdf", db)
                    raise AssertionError("Controlled interruption did not occur")
                except asyncio.CancelledError:
                    pass

            interrupted_seconds = time.perf_counter() - start
            async with AsyncSessionLocal() as db:
                statuses = (await db.execute(select(DocumentPage.status).where(
                    DocumentPage.document_id == doc_id).order_by(DocumentPage.page_number)
                )).scalars().all()
            indexed_before = sum(status == "indexed" for status in statuses)
            processed_before = sum(status in {"indexed", "empty"} for status in statuses)
            if processed_before != interrupt_at - 1 or statuses[interrupt_at - 1] != "processing":
                raise AssertionError(
                    f"Persisted checkpoint differs at page {interrupt_at}: "
                    f"indexed={indexed_before}, processed={processed_before}, "
                    f"interrupted_status={statuses[interrupt_at - 1]}"
                )

            resume_start = time.perf_counter()
            queued = await document_jobs.resume_interrupted_pdf_jobs()
            if queued != 1:
                raise AssertionError(f"Expected one resumed job, got {queued}")
            await document_jobs._jobs[doc_id]
            resume_seconds = time.perf_counter() - resume_start

        async with AsyncSessionLocal() as db:
            doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
            statuses = (await db.execute(select(DocumentPage.status).where(
                DocumentPage.document_id == doc_id).order_by(DocumentPage.page_number)
            )).scalars().all()
            semantic_chunks = (await db.execute(select(func.count(Chunk.id)).where(
                Chunk.document_id == doc_id,
                Chunk.metadata_["source_kind"].as_string().is_(None),
            ))).scalar_one()
            raw_chunks = (await db.execute(select(func.count(Chunk.id)).where(
                Chunk.document_id == doc_id,
                Chunk.metadata_["source_kind"].as_string() == "raw_ocr_page",
            ))).scalar_one()

        empty = [i + 1 for i, status in enumerate(statuses) if status == "empty"]
        if doc.status not in {"completed", "partial"} or any(
            status not in {"indexed", "empty"} for status in statuses
        ):
            raise AssertionError(f"Long document did not finish: {doc.status}")
        if attempts != {page: 2 if page == interrupt_at else 1
                        for page in range(1, total_pages + 1)}:
            raise AssertionError("Pages were duplicated or skipped on resume")

        return {"pdf": str(pdf), "sha256": sha256(pdf), "bytes": pdf.stat().st_size,
                "pages": total_pages, "interrupted_page": interrupt_at,
                "indexed_before_restart": indexed_before,
                "processed_before_restart": processed_before,
                "indexed_after_restart": statuses.count("indexed"),
                "empty_pages": empty, "semantic_chunks": semantic_chunks,
                "raw_page_chunks": raw_chunks,
                "attempts_interrupted_page": attempts[interrupt_at],
                "attempts_other_pages": "once",
                "seconds_before_restart": round(interrupted_seconds, 2),
                "seconds_after_restart": round(resume_seconds, 2),
                "peak_process_working_set_mb": round(memory.peak / 1024**2, 1)
                if memory.peak else None,
                "ocr_mode": "deterministic text-backed stub from real PDF pages",
                "embedding_mode": "fixed 1024-dimensional vectors; no model calls"}
    finally:
        pdf_handle.close()
        await document_jobs.stop_pdf_jobs()
        close_warehouse()
        await engine.dispose()
        await _drop_test_db(base_url, db_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--interrupt-at", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pdf = args.pdf.resolve(strict=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    db_name = f"ragdb_step8_{os.getpid()}"
    if not re.fullmatch(r"[a-z0-9_]+", db_name):
        raise ValueError("Unsafe test database name")
    result = asyncio.run(run_test(pdf, args.interrupt_at, output, db_name))
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
