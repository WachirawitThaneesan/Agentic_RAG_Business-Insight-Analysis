"""Run local OCR across a full PDF with per-page checkpoints and memory samples.

This measures recognition throughput, failures, and process-tree RSS. It does
not index the output or measure upload, retrieval, or answer accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
import pymupdf


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


async def run(args: argparse.Namespace) -> dict:
    pdf_path = args.pdf.resolve(strict=True)
    with pymupdf.open(pdf_path) as source:
        page_count = len(source)
    source_hash = _sha256(pdf_path)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        record = json.loads(output.read_text(encoding="utf-8"))
        if record.get("source_sha256") != source_hash or record.get("page_count") != page_count:
            raise ValueError("Existing checkpoint belongs to a different PDF")
    else:
        record = {"source_file": pdf_path.name, "source_sha256": source_hash,
                  "page_count": page_count, "provider": "local Docling/EasyOCR Thai-English",
                  "mode": "full-page local OCR, no cloud fallback",
                  "pages": {}, "runs": []}
        _save(output, record)

    os.environ.update({
        "OFFLINE_MODE": "true",
        "PRIVATE_DATA_DIR": str(args.private_dir.resolve()),
        "LOCAL_OCR_PYTHON": str(args.local_python.resolve(strict=True)),
        "LOCAL_OCR_MODELS_DIR": str(args.models.resolve(strict=True)),
        "LOCAL_OCR_EASYOCR_CACHE_DIR": str(args.easyocr_cache.resolve(strict=True)),
    })
    from backend.config import get_settings

    get_settings.cache_clear()
    from backend.services.local_ocr import ocr_service

    parent = psutil.Process(os.getpid())
    stop = threading.Event()
    memory = {"parent_peak": 0, "worker_peak": 0, "combined_peak": 0}

    def sample() -> None:
        while not stop.wait(0.5):
            try:
                parent_rss = parent.memory_info().rss
                worker_rss = sum(child.memory_info().rss for child in parent.children(recursive=True)
                                 if child.is_running())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            memory["parent_peak"] = max(memory["parent_peak"], parent_rss)
            memory["worker_peak"] = max(memory["worker_peak"], worker_rss)
            memory["combined_peak"] = max(memory["combined_peak"], parent_rss + worker_rss)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    phase = {"started_utc": datetime.now(timezone.utc).isoformat(),
             "pages_attempted": 0, "seconds": None}
    phase_start = time.perf_counter()
    record["runs"].append(phase)
    _save(output, record)
    try:
        for page in range(1, page_count + 1):
            if str(page) in record["pages"] and not (
                    args.retry_failed and record["pages"][str(page)]["status"] == "failed"):
                continue
            if args.max_new_pages and phase["pages_attempted"] >= args.max_new_pages:
                break
            started = time.perf_counter()
            try:
                result = await ocr_service.extract_from_pdf_path(str(pdf_path), pages=[page])
                chars = sum(len(value) for value in result.get("text_blocks", []))
                tables = len(result.get("tables", []))
                status = "ok" if chars or tables else "empty"
                row = {"status": status, "seconds": round(time.perf_counter() - started, 2),
                       "text_chars": chars, "tables": tables,
                       "regions": len(result.get("raw_pages", []))}
            except Exception as exc:
                row = {"status": "failed", "seconds": round(time.perf_counter() - started, 2),
                       "error": f"{type(exc).__name__}: {exc}"[:300]}
                status = "failed"
            try:
                row["process_tree_mb_after"] = round((parent.memory_info().rss + sum(
                    child.memory_info().rss for child in parent.children(recursive=True)
                    if child.is_running())) / 1024**2, 1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            record["pages"][str(page)] = row
            phase["pages_attempted"] += 1
            phase["seconds"] = round(time.perf_counter() - phase_start, 2)
            phase["peak_parent_mb"] = round(memory["parent_peak"] / 1024**2, 1)
            phase["peak_worker_mb"] = round(memory["worker_peak"] / 1024**2, 1)
            phase["peak_combined_mb"] = round(memory["combined_peak"] / 1024**2, 1)
            _save(output, record)
            print(f"Page {page}/{page_count}: {status} in {row['seconds']}s", flush=True)
    finally:
        stop.set()
        monitor.join()
        ocr_service.close()
        phase["finished_utc"] = datetime.now(timezone.utc).isoformat()
        phase["seconds"] = round(time.perf_counter() - phase_start, 2)
        phase["peak_parent_mb"] = round(memory["parent_peak"] / 1024**2, 1)
        phase["peak_worker_mb"] = round(memory["worker_peak"] / 1024**2, 1)
        phase["peak_combined_mb"] = round(memory["combined_peak"] / 1024**2, 1)
        record["all_pages_attempted"] = len(record["pages"]) == page_count
        record["complete"] = record["all_pages_attempted"] and all(
            row["status"] != "failed" for row in record["pages"].values())
        _save(output, record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--local-python", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--easyocr-cache", type=Path, required=True)
    parser.add_argument("--max-new-pages", type=int, default=0,
                        help="Optional bounded pilot; rerun without it to resume all pages")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if args.max_new_pages < 0:
        parser.error("--max-new-pages cannot be negative")
    result = asyncio.run(run(args))
    print(json.dumps({"pages_recorded": len(result["pages"]), "page_count": result["page_count"],
                      "complete": result["complete"]}, indent=2))


if __name__ == "__main__":
    main()
