"""Time and sample process memory for real local OCR on selected PDF pages."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pymupdf
import psutil


async def run(args) -> dict:
    os.environ.update({
        "OFFLINE_MODE": "true", "PRIVATE_DATA_DIR": str(args.private_dir.resolve()),
        "LOCAL_OCR_PYTHON": str(args.local_python.resolve()),
        "LOCAL_OCR_MODELS_DIR": str(args.models.resolve()),
        "LOCAL_OCR_EASYOCR_CACHE_DIR": str(args.easyocr_cache.resolve()),
    })
    from backend.config import get_settings
    get_settings.cache_clear()
    from backend.services.local_ocr import ocr_service

    stop = threading.Event()
    memory = {"parent_peak": 0, "worker_peak": 0, "combined_peak": 0,
              "child_pids": set()}
    parent_process = psutil.Process(os.getpid())

    def sample():
        while not stop.wait(0.3):
            try:
                parent = parent_process.memory_info().rss
                children = parent_process.children(recursive=True)
                child = sum(proc.memory_info().rss for proc in children if proc.is_running())
                memory["child_pids"].update(proc.pid for proc in children)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            memory["parent_peak"] = max(memory["parent_peak"], parent)
            memory["worker_peak"] = max(memory["worker_peak"], child)
            memory["combined_peak"] = max(memory["combined_peak"], parent + child)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    rows = []
    try:
        for page in args.pages:
            start = time.perf_counter()
            try:
                result = await ocr_service.extract_from_pdf_path(str(args.pdf), pages=[page])
                row = {"page": page, "seconds": round(time.perf_counter() - start, 2),
                       "status": "ok", "regions": len(result.get("raw_pages", [])),
                       "tables": len(result.get("tables", [])),
                       "text_chars": sum(len(text) for text in result.get("text_blocks", []))}
            except Exception as exc:
                row = {"page": page, "seconds": round(time.perf_counter() - start, 2),
                       "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        stop.set()
        monitor.join()
        ocr_service.close()

    with pymupdf.open(args.pdf) as pdf:
        total_pages = len(pdf)
    digest = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    return {"pdf": str(args.pdf), "sha256": digest, "total_pdf_pages": total_pages,
            "sampled_pages": rows,
            "peak_parent_mb": round(memory["parent_peak"] / 1024**2, 1),
            "peak_worker_mb": round(memory["worker_peak"] / 1024**2, 1),
            "peak_combined_mb": round(memory["combined_peak"] / 1024**2, 1),
            "observed_child_pids": sorted(memory["child_pids"]),
            "provider": "local Docling, full-page EasyOCR Thai/English, TableFormer accurate, CPU",
            "limitation": "Page sample only; does not measure full-report OCR completion or memory drift."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--local-python", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--easyocr-cache", type=Path, required=True)
    args = parser.parse_args()
    args.pdf = args.pdf.resolve(strict=True)
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(run(args))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"peak_combined_mb": result["peak_combined_mb"],
                      "sampled_pages": len(result["sampled_pages"])}, indent=2))


if __name__ == "__main__":
    main()
