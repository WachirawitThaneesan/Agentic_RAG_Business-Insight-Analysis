"""Measure sequential full-PDF rasterization memory without OCR or model calls."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import statistics
import time
from pathlib import Path

import pymupdf

from scripts.benchmark_long_document import MemorySampler, working_set_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pdf = args.pdf.resolve(strict=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pdf.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    samples = []
    durations = []
    failures = []
    max_bitmap_bytes = 0
    scale = args.dpi / 72
    start = time.perf_counter()
    with MemorySampler() as memory, pymupdf.open(pdf) as doc:
        for index, page in enumerate(doc):
            page_start = time.perf_counter()
            try:
                bitmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                max_bitmap_bytes = max(max_bitmap_bytes, len(bitmap.samples))
                del bitmap
            except Exception as exc:
                failures.append({"page": index + 1, "error": f"{type(exc).__name__}: {exc}"})
            durations.append(time.perf_counter() - page_start)
            if (index + 1) % 25 == 0 or index + 1 == len(doc):
                gc.collect()
                samples.append({"page": index + 1,
                                "working_set_mb": round((working_set_bytes() or 0) / 1024**2, 1)})
        page_count = len(doc)
    result = {"pdf": str(pdf), "sha256": digest, "pages": page_count,
              "dpi": args.dpi, "rasterized_pages": page_count - len(failures),
              "failures": failures, "elapsed_seconds": round(time.perf_counter() - start, 2),
              "median_page_seconds": round(statistics.median(durations), 3),
              "p95_page_seconds": round(sorted(durations)[min(len(durations) - 1,
                                                       int(len(durations) * 0.95))], 3),
              "max_bitmap_mb": round(max_bitmap_bytes / 1024**2, 1),
              "peak_process_working_set_mb": round(memory.peak / 1024**2, 1),
              "working_set_samples": samples,
              "scope": "PDF rasterization only; excludes OCR, embeddings, databases, and LLMs"}
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("pages", "rasterized_pages",
                       "elapsed_seconds", "peak_process_working_set_mb", "failures")}, indent=2))


if __name__ == "__main__":
    main()
