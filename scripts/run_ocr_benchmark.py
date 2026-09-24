"""Run the small visual-label OCR benchmark without uploading to the app.

Examples:
  .venv/Scripts/python scripts/run_ocr_benchmark.py --max-pages 3
  .venv/Scripts/python scripts/run_ocr_benchmark.py --score-only

Typhoon calls can use API credits. Results are cached under the ignored
backend/eval/results/ocr_benchmark directory; rerunning skips cached pages.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.financial_quality import assess_table, parse_number  # noqa: E402
from backend.services.ocr import ocr_service  # noqa: E402
from backend.services.table_utils import normalize_ocr_tables  # noqa: E402


GOLD = ROOT / "TestFile" / "ocr_benchmark_gold.json"
RESULTS = ROOT / "backend" / "eval" / "results" / "ocr_benchmark"
NUMBER_TOKEN = re.compile(r"(?<![\w])\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?%?(?![\w])")


def _result_path(page: dict) -> Path:
    return RESULTS / f"{Path(page['excerpt_file']).stem}__page_{page['excerpt_page']}.json"


def _numbers_in_text(text: str) -> set[Decimal]:
    numbers = set()
    for match in NUMBER_TOKEN.finditer(text):
        value = parse_number(match.group())
        if value is not None:
            numbers.add(value)
    return numbers


def _numbers_in_tables(tables: list[dict]) -> set[Decimal]:
    return {
        number
        for table in tables
        for row in table.get("rows", [])
        for cell in row[1:]
        if (number := parse_number(cell)) is not None
    }


def _assessed_tables(result: dict, filename: str) -> tuple[list[dict], list[dict], list[dict]]:
    parsed = normalize_ocr_tables(filename, result.get("tables", []))
    accepted = []
    reports = []
    for table in parsed:
        report = assess_table(table)
        reports.append(report)
        if report["accepted_rows"]:
            accepted.append({**table, "rows": report["accepted_rows"]})
    return parsed, accepted, reports


async def _run_page(page: dict) -> dict:
    filename = Path(page["excerpt_file"]).name
    pdf = ROOT / "TestFile" / filename
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    result = await ocr_service.extract_from_pdf_path(str(pdf), filename=filename, pages=[page["excerpt_page"]])
    return {
        "schema_version": 1,
        "excerpt_file": filename,
        "excerpt_page": page["excerpt_page"],
        "input_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "ocr_model": ocr_service.model,
        "render_dpi": ocr_service.render_dpi,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "ocr_result": result,
    }


def _score_page(page: dict, result: dict) -> dict:
    ocr = result.get("ocr_result") or {"raw_pages": [], "tables": []}
    markdown = "\n".join(str(item.get("markdown") or "") for item in ocr.get("raw_pages", []))
    prompt_echo = markdown.startswith("Extract all text from the image.") and "Formatting Rules:" in markdown[:1200]
    if prompt_echo:
        ocr = {"raw_pages": [], "tables": []}
    parsed, accepted, reports = _assessed_tables(ocr, page["excerpt_file"])
    raw_text = "\n".join(str(item.get("markdown") or "") for item in ocr.get("raw_pages", []))
    raw_numbers = _numbers_in_text(raw_text)
    parsed_numbers = _numbers_in_tables(parsed)
    accepted_numbers = _numbers_in_tables(accepted)
    anchors = []
    for printed in page.get("numeric_anchors", []):
        number = parse_number(printed)
        anchors.append({
            "printed": printed,
            "raw_ocr": number in raw_numbers,
            "parsed_table": number in parsed_numbers,
            "accepted_table": number in accepted_numbers,
        })
    table_found = bool(ocr.get("tables"))
    return {
        "file": page["excerpt_file"],
        "page": page["excerpt_page"],
        "role": page["role"],
        "ocr_error": result.get("ocr_error") or ("prompt_echo" if prompt_echo else None),
        "expected_table": page["expected_table"],
        "table_found": table_found,
        "table_detection_correct": table_found == page["expected_table"],
        "unresolved_rows": sum(report["unresolved_rows"] for report in reports),
        "unverified_rows": sum(row["status"] == "unverified" for report in reports for row in report["row_reports"]),
        "anchors": anchors,
    }


def _print_summary(scores: list[dict], total_pages: int) -> None:
    anchors = [anchor for score in scores for anchor in score["anchors"]]
    print(f"Scored {len(scores)}/{total_pages} labeled pages; {len(anchors)} visually checked numeric anchors.")
    if not scores:
        return
    correct = sum(score["table_detection_correct"] for score in scores)
    print(f"Table-presence decisions: {correct}/{len(scores)} correct.")
    print(f"OCR failures or invalid responses: {sum(bool(score['ocr_error']) for score in scores)}/{len(scores)}.")
    if anchors:
        for field, label in (("raw_ocr", "Raw OCR token recall"), ("parsed_table", "Parsed-table token recall"), ("accepted_table", "Post-gate table token recall")):
            print(f"{label}: {sum(anchor[field] for anchor in anchors)}/{len(anchors)}")
    print(f"Rows quarantined: {sum(score['unresolved_rows'] for score in scores)}; rows labeled unverified: {sum(score['unverified_rows'] for score in scores)}")
    for score in scores:
        misses = [anchor["printed"] for anchor in score["anchors"] if not anchor["raw_ocr"]]
        table_error = " TABLE_PRESENCE_MISMATCH" if not score["table_detection_correct"] else ""
        ocr_error = f" OCR_FAILED={score['ocr_error']}" if score["ocr_error"] else ""
        print(f"  {score['file']} p{score['page']}: {score['role']}{table_error}{ocr_error}; unresolved={score['unresolved_rows']}; missing anchors={misses}")
    print("These are page/table-presence and numeric-token measures, not full cell accuracy or proof that accepted values match the PDF.")


async def _main(args: argparse.Namespace) -> None:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    pages = gold["pages"]
    selected = pages[:args.max_pages] if args.max_pages else pages
    ocr_service.page_timeout_seconds = args.page_timeout
    RESULTS.mkdir(parents=True, exist_ok=True)
    scores = []
    for page in selected:
        path = _result_path(page)
        if path.is_file():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored.get("ocr_error") and args.retry_errors and not args.score_only:
                stored = None
        elif args.score_only:
            continue
        else:
            stored = None
        if stored is None:
            print(f"OCR {page['excerpt_file']} physical page {page['excerpt_page']} ...", flush=True)
            try:
                stored = await _run_page(page)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                print(f"  OCR failed: {error}", flush=True)
                stored = {"schema_version": 1, "excerpt_file": page["excerpt_file"],
                          "excerpt_page": page["excerpt_page"], "ocr_error": error,
                          "created_utc": datetime.now(timezone.utc).isoformat()}
            path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        scores.append(_score_page(page, stored))
    _print_summary(scores, len(pages))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, help="Run only the first N labeled pages (pilot)")
    parser.add_argument("--score-only", action="store_true", help="Do not make Typhoon OCR calls")
    parser.add_argument("--page-timeout", type=float, default=120.0, help="Wall-clock seconds per page for this benchmark (default: 120)")
    parser.add_argument("--retry-errors", action="store_true", help="Retry previously failed pages")
    asyncio.run(_main(parser.parse_args()))
