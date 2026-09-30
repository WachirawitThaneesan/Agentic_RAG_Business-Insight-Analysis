"""Crash and resume a real long PDF job across separate Python processes.

The original PDF pages and ingestion/database path are real. OCR is replaced
with selectable PDF text and embeddings with fixed vectors so this isolates
durable checkpoints from model time, accuracy, and cloud services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import psutil
import pymupdf
from sqlalchemy.engine import make_url

from scripts.benchmark_long_document import _create_test_db, _drop_test_db, sha256


async def _worker(phase: str, pdf: Path, interrupt_at: int, state: Path) -> None:
    from sqlalchemy import select

    from backend.database import AsyncSessionLocal, engine, init_db
    from backend.models import Document, DocumentPage
    from backend.routes import documents
    from backend.services import chunker, document_jobs
    from backend.services.duckdb_warehouse import close_warehouse

    await init_db()
    pdf_handle = pymupdf.open(pdf)
    attempts = state / "attempts.txt"

    async def text_backed_ocr(_path, filename, pages, **_kwargs):
        page = pages[0]
        with attempts.open("a", encoding="ascii") as stream:
            stream.write(f"{page}\n")
            stream.flush()
        if phase == "crash" and page == interrupt_at:
            os._exit(88)
        text = pdf_handle[page - 1].get_text().strip()
        return {"raw_pages": [{"page": page, "markdown": text}],
                "text_blocks": [text] if text else [], "tables": [],
                "table_extraction_warnings": []}

    async def fake_embedding(_text):
        return [0.0] * 1024

    async def fake_batch(texts):
        return [[0.0] * 1024 for _ in texts]

    try:
        with patch.object(documents.ocr_service, "extract_from_pdf_path", side_effect=text_backed_ocr), \
             patch.object(documents, "get_embedding", side_effect=fake_embedding), \
             patch.object(chunker, "get_embedding", side_effect=fake_embedding), \
             patch.object(chunker, "get_embeddings_batch", side_effect=fake_batch), \
             patch.object(document_jobs, "saved_upload_path", return_value=pdf):
            if phase == "crash":
                async with AsyncSessionLocal() as db:
                    doc = Document(filename=pdf.name, doc_type="pdf", status="pending")
                    db.add(doc)
                    await db.commit()
                    await db.refresh(doc)
                    (state / "document_id.txt").write_text(str(doc.id), encoding="ascii")
                    await documents._process_saved_document(doc, str(pdf), "pdf", db)
                raise AssertionError("The injected process exit was not reached")

            doc_id = int((state / "document_id.txt").read_text(encoding="ascii"))
            async with AsyncSessionLocal() as db:
                before = (await db.execute(select(DocumentPage.status).where(
                    DocumentPage.document_id == doc_id
                ).order_by(DocumentPage.page_number))).scalars().all()
            if sum(status in {"indexed", "empty"} for status in before) != interrupt_at - 1:
                raise AssertionError("Checkpoint before process restart is incomplete")
            if before[interrupt_at - 1] != "processing":
                raise AssertionError("The interrupted page was not persisted as processing")
            queued = await document_jobs.resume_interrupted_pdf_jobs()
            if queued != 1:
                raise AssertionError(f"Expected one resumed job, got {queued}")
            await document_jobs._jobs[doc_id]
            async with AsyncSessionLocal() as db:
                doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
                after = (await db.execute(select(DocumentPage.status).where(
                    DocumentPage.document_id == doc_id
                ).order_by(DocumentPage.page_number))).scalars().all()
            if doc.status not in {"completed", "partial"} or any(
                status not in {"indexed", "empty"} for status in after
            ):
                raise AssertionError(f"Resume did not finish: {doc.status}")
            (state / "resume.json").write_text(json.dumps({
                "document_status": doc.status, "queued": queued,
                "indexed_before": before.count("indexed"),
                "processed_before": sum(status in {"indexed", "empty"} for status in before),
                "indexed_after": after.count("indexed"),
                "empty_pages": [i + 1 for i, status in enumerate(after) if status == "empty"],
                "page_count": len(after),
            }, indent=2), encoding="utf-8")
    finally:
        pdf_handle.close()
        await document_jobs.stop_pdf_jobs()
        close_warehouse()
        await engine.dispose()


def _run_phase(phase: str, pdf: Path, interrupt_at: int, state: Path,
               env: dict[str, str]) -> dict:
    command = [sys.executable, "-m", "scripts.benchmark_process_restart", "--phase", phase,
               "--pdf", str(pdf), "--interrupt-at", str(interrupt_at), "--state", str(state)]
    log = state / f"{phase}.log"
    start = time.perf_counter()
    peak = 0
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1],
                                   env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        while process.poll() is None:
            try:
                root = psutil.Process(process.pid)
                family = [root, *root.children(recursive=True)]
                peak = max(peak, sum(member.memory_info().rss for member in family
                                     if member.is_running()))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(0.2)
        code = process.wait()
    return {"exit_code": code, "seconds": round(time.perf_counter() - start, 2),
            "peak_process_tree_rss_mb": round(peak / 1024**2, 1), "log": str(log)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--interrupt-at", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--phase", choices=("crash", "resume"))
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()
    pdf = args.pdf.resolve(strict=True)
    with pymupdf.open(pdf) as source:
        pages = len(source)
    if not 200 <= pages <= 500 or not 1 < args.interrupt_at < pages:
        raise ValueError("Expected a 200-500-page PDF and an interior interruption page")

    if args.phase:
        if not args.state:
            raise ValueError("Worker phase requires --state")
        asyncio.run(_worker(args.phase, pdf, args.interrupt_at, args.state.resolve()))
        return

    if args.output is None:
        raise ValueError("Parent benchmark requires --output")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    state = output.parent / f"{output.stem}.state-{os.getpid()}"
    state.mkdir(exist_ok=False)
    from backend.config import get_settings

    base_url = get_settings().DATABASE_URL
    db_name = f"ragdb_step8_crash_{os.getpid()}"
    if not re.fullmatch(r"[a-z0-9_]+", db_name):
        raise ValueError("Unsafe generated database name")
    url = make_url(base_url).set(database=db_name)
    env = os.environ.copy()
    env.update({"DATABASE_URL": url.render_as_string(hide_password=False),
                "DATABASE_URL_SYNC": url.set(drivername="postgresql").render_as_string(hide_password=False),
                "DUCKDB_PATH": str(state / "warehouse.duckdb"),
                "GRAPH_BUILD_ENABLED": "false", "PYTHONIOENCODING": "utf-8"})
    asyncio.run(_create_test_db(base_url, db_name))
    try:
        crashed = _run_phase("crash", pdf, args.interrupt_at, state, env)
        if crashed["exit_code"] != 88:
            raise AssertionError(f"Crash phase did not exit at the injected page: {crashed}")
        resumed = _run_phase("resume", pdf, args.interrupt_at, state, env)
        if resumed["exit_code"] != 0:
            raise AssertionError(f"Resume phase failed: {resumed}")
        attempts = Counter(int(line) for line in (state / "attempts.txt").read_text(
            encoding="ascii").splitlines())
        expected = {page: 2 if page == args.interrupt_at else 1
                    for page in range(1, pages + 1)}
        if attempts != expected:
            raise AssertionError("Page attempts were skipped or duplicated across restart")
        details = json.loads((state / "resume.json").read_text(encoding="utf-8"))
        if details["page_count"] != pages:
            raise AssertionError("The resumed PDF has an unexpected page count")
        result = {"pdf": pdf.name, "sha256": sha256(pdf), "pages": pages,
                  "interrupted_page": args.interrupt_at, "crash": crashed,
                  "resume": resumed, "page_status": details,
                  "attempts_interrupted_page": 2, "attempts_other_pages": "once",
                  "ocr_mode": "deterministic text-backed stub from original PDF pages",
                  "embedding_mode": "fixed 1024-dimensional vectors; no model calls",
                  "restart_mode": "abrupt os._exit(88), then a fresh Python process"}
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        asyncio.run(_drop_test_db(base_url, db_name))


if __name__ == "__main__":
    main()
