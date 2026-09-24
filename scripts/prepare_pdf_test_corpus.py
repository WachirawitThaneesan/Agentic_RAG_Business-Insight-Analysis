"""Create reproducible, visually varied PDF excerpts for OCR testing.

The source PDFs are read-only. Each output page retains its original PDF page
content, and selection_manifest.json maps excerpt pages to physical source pages.
This is a sampling corpus, not a ground-truth OCR answer set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pymupdf
from pypdf import PdfReader, PdfWriter


FINANCIAL_TERMS = (
    "งบการเงิน", "สินทรัพย์", "หนี้สิน", "กำไร", "รายได้", "กระแสเงินสด",
    "ส่วนของผู้ถือหุ้น", "ผลการดำเนินงาน", "หมายเหตุประกอบงบ", "ตาราง",
    "financial statements", "assets", "liabilities", "profit", "revenue",
    "cash flows", "shareholders", "operating results", "notes to the",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def page_features(page: pymupdf.Page) -> dict:
    # Embedded text is used only to choose diverse pages, never as OCR truth.
    text = page.get_text("text")
    lower = text.casefold()
    return {
        "text_chars": len(text),
        "number_tokens": len(re.findall(r"\d[\d,.]*", text)),
        "financial_terms": sum(lower.count(term) for term in FINANCIAL_TERMS),
        "images": len(page.get_images(full=False)),
        "drawings": len(page.get_drawings()),
    }


def pick_pages(features: list[dict], requested: int) -> tuple[list[int], dict[int, str]]:
    page_count = len(features)
    if page_count <= requested:
        return list(range(page_count)), {i: "all_pages" for i in range(page_count)}

    # Five distinct page roles per stratum spreads the sample across the whole
    # report while including figures, dense numbers, and ordinary narrative.
    if requested % 5:
        raise ValueError("--pages-per-file must be divisible by 5")
    strata = requested // 5
    chosen: dict[int, str] = {}
    for band in range(strata):
        start = band * page_count // strata
        stop = (band + 1) * page_count // strata
        candidates = list(range(start, stop))
        center = (start + stop - 1) / 2

        def select(reason: str, scorer) -> None:
            remaining = [i for i in candidates if i not in chosen]
            if not remaining:
                return
            best = max(remaining, key=lambda i: (scorer(i), -abs(i - center), -i))
            chosen[best] = reason

        if band == 0:
            chosen[0] = "opening_page"

        select("financial_topic", lambda i: 8 * features[i]["financial_terms"] + features[i]["number_tokens"])
        select("number_dense", lambda i: features[i]["number_tokens"] + min(features[i]["drawings"], 100) / 10)
        select("visual_or_chart_candidate", lambda i: 40 * features[i]["images"] + min(features[i]["drawings"], 500) / 5 - features[i]["text_chars"] / 1000)
        if band != 0:
            select("narrative", lambda i: min(features[i]["text_chars"], 8000) - 3 * features[i]["number_tokens"])
        select("middle_of_section", lambda i: -abs(i - center))

    if len(chosen) != requested:
        raise RuntimeError(f"Selected {len(chosen)} pages, expected {requested}")
    return sorted(chosen), chosen


def prepare_one(source_path: Path, output_dir: Path, requested: int) -> dict:
    source_path = source_path.resolve(strict=True)
    output_path = output_dir / f"{source_path.stem}_selected{requested}.pdf"
    temp_path = output_dir / f".{source_path.stem}_selected{requested}.tmp.pdf"
    if output_path.exists() or temp_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output_path}")

    with pymupdf.open(source_path) as source:
        features = [page_features(source[i]) for i in range(len(source))]
        indices, reasons = pick_pages(features, requested)
        source_reader = PdfReader(str(source_path), strict=False)
        if len(source_reader.pages) != len(source):
            raise RuntimeError(f"Page-count disagreement while reading {source_path}")
        excerpt_writer = PdfWriter()
        for index in indices:
            excerpt_writer.add_page(source_reader.pages[index])
        with temp_path.open("xb") as target:
            excerpt_writer.write(target)

        with pymupdf.open(temp_path) as check:
            if len(check) != len(indices):
                raise RuntimeError(f"Wrong page count in {temp_path}")
            for excerpt_index, source_index in enumerate(indices):
                if check[excerpt_index].rect != source[source_index].rect:
                    raise RuntimeError(f"Page geometry changed at excerpt page {excerpt_index + 1}")

    temp_path.rename(output_path)
    return {
        "source_file": source_path.name,
        "source_sha256": sha256_file(source_path),
        "source_page_count": len(features),
        "excerpt_file": output_path.name,
        "excerpt_sha256": sha256_file(output_path),
        "excerpt_page_count": len(indices),
        "pages": [
            {
                "excerpt_page": excerpt_index + 1,
                "source_pdf_page": source_index + 1,
                "selection_reason": reasons[source_index],
                **features[source_index],
            }
            for excerpt_index, source_index in enumerate(indices)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--pages-per-file", type=int, default=50)
    args = parser.parse_args()
    if args.pages_per_file <= 0:
        parser.error("--pages-per-file must be positive")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "selection_manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing manifest: {manifest_path}")
    report = {
        "purpose": "Representative OCR testing, not human-verified ground truth",
        "page_numbering": "1-based physical PDF pages; printed page numbers may differ",
        "selection": "Five page roles in each of ten position strata per report; deterministic",
        "documents": [prepare_one(source, output_dir, args.pages_per_file) for source in args.sources],
    }
    with manifest_path.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    for document in report["documents"]:
        print(f"{document['excerpt_file']}: {document['excerpt_page_count']} / {document['source_page_count']} pages")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
