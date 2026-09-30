"""Score exact table cells and chart evidence from cached OCR; makes no API calls.

Usage: .venv/Scripts/python scripts/score_ocr_cells.py --split all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.financial_quality import assess_table, parse_number  # noqa: E402
from backend.services.table_utils import normalize_ocr_tables  # noqa: E402

GOLD = ROOT / "TestFile" / "ocr_cell_gold.json"
MANIFEST = ROOT / "TestFile" / "selection_manifest.json"
CACHE = ROOT / "backend" / "eval" / "results" / "ocr_benchmark"


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _column_index(fact: dict, headers: list[str]) -> int:
    """Use the labeled column meaning when OCR providers emit different grids."""
    label = _compact(fact.get("column_label") or "")
    compact_headers = [_compact(header) for header in headers]
    year_match = re.search(r"25\d{2}", label)
    if year_match:
        year = year_match.group()
        candidates = [i for i, header in enumerate(compact_headers) if year in header]
        if "ร้อยละ" in label:
            candidates = [i for i in candidates if "ร้อยละ" in compact_headers[i]]
        elif "ล้านบาท" in label:
            candidates = [i for i in candidates if "ล้านบาท" in compact_headers[i]]
        elif "จำนวนเงิน" in label:
            candidates = [i for i in candidates if "จำนวน" in compact_headers[i] or "จํานวน" in compact_headers[i]]
        if len(candidates) == 1:
            return candidates[0]
    elif "กสิกรไทย" in label:
        candidates = [i for i, header in enumerate(compact_headers) if "กสิกรไทย" in header]
        if len(candidates) == 1:
            return candidates[0]
    elif "รวม" in label:
        candidates = [i for i, header in enumerate(compact_headers) if header == "รวม"]
        if len(candidates) == 1:
            return candidates[0]
    else:
        token = "ร้อยละ" if "ร้อยละ" in label else "จำนวน" if "จำนวน" in label else ""
        if token:
            candidates = [i for i, header in enumerate(compact_headers) if token in header]
            if len(candidates) == 1:
                return candidates[0]
    return int(fact["column_index"])


def score_table_fact(fact: dict, ocr_result: dict) -> dict:
    """A number in the wrong row or column is not a correct answer."""
    tables = normalize_ocr_tables(fact["excerpt_file"], ocr_result.get("tables", []))
    row_matches = []
    for table in tables:
        if fact.get("region") and table.get("region") != fact["region"]:
            continue
        report = assess_table(table)
        for index, row in enumerate(table.get("rows", [])):
            label = _compact(row[0] if row else "")
            target = _compact(fact["row_contains"])
            if (label == target if fact.get("row_equals") else target in label):
                column = _column_index(fact, table.get("headers") or [])
                if column >= len(row):
                    row_matches.append({"outcome": "missing_column"})
                    continue
                observed = str(row[column])
                expected_number = parse_number(fact["printed"])
                actual_number = parse_number(observed)
                correct = (
                    actual_number == expected_number if expected_number is not None
                    else _compact(observed) == _compact(fact["printed"])
                )
                row_status = report["row_reports"][index]["status"]
                row_matches.append({
                    "outcome": "correct" if correct else "wrong_value",
                    "observed": observed,
                    "row_status": row_status,
                    "unsafe_accepted": not correct and row_status != "unresolved",
                })
    if not row_matches:
        return {"outcome": "missing_row", "unsafe_accepted": False}
    return next((match for match in row_matches if match["outcome"] == "correct"), row_matches[0])


def score_chart_fact(fact: dict, ocr_result: dict) -> dict:
    """Chart extraction is not implemented: token presence is NOT fact accuracy."""
    raw = "\n".join(str(page.get("markdown") or "") for page in ocr_result.get("raw_pages", []))
    token = re.sub(r"\s+", "", fact["printed"])
    present = token in re.sub(r"\s+", "", raw)
    return {"outcome": "unresolved_chart_fact", "raw_token_present": present, "unsafe_accepted": False}


def _cache_path(fact: dict) -> Path:
    return CACHE / f"{Path(fact['excerpt_file']).stem}__page_{fact['excerpt_page']}.json"


def score_cached_fact(fact: dict, expected_hash: str) -> dict:
    path = _cache_path(fact)
    if not path.is_file():
        return {"outcome": "not_scored_cache_missing"}
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("input_sha256") != expected_hash:
        return {"outcome": "not_scored_hash_mismatch"}
    if stored.get("ocr_error"):
        return {"outcome": "ocr_failed", "error": stored["ocr_error"]}
    ocr = stored.get("ocr_result") or {}
    return (score_table_fact if fact["source_kind"] == "table_cell" else score_chart_fact)(fact, ocr)


def main(split: str) -> None:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    hashes = {item["excerpt_file"]: item["excerpt_sha256"] for item in manifest["documents"]}
    facts = [fact for fact in gold["facts"] if split == "all" or fact["split"] == split]
    scored = [(fact, score_cached_fact(fact, hashes[fact["excerpt_file"]])) for fact in facts]
    table = [(fact, result) for fact, result in scored if fact["source_kind"] == "table_cell"]
    charts = [(fact, result) for fact, result in scored if fact["source_kind"] == "chart_fact"]
    available = [result for _, result in table if not result["outcome"].startswith("not_scored")]
    correct = sum(result["outcome"] == "correct" for result in available)
    unsafe = sum(result.get("unsafe_accepted", False) for result in available)
    chart_tokens = sum(result.get("raw_token_present", False) for _, result in charts)
    print(f"Split: {split}; exact table cells: {correct}/{len(available)} scored ({len(table)} labeled).")
    print(f"Incorrect table cells still accepted by quality gate: {unsafe}.")
    print(f"Chart facts: {len(charts)} labeled; raw value token present for {chart_tokens}; category/value extraction not yet supported, so chart fact accuracy is unscored.")
    for fact, result in scored:
        print(f"  {fact['id']}: {result['outcome']}" + (f" (observed {result['observed']})" if "observed" in result else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("all", "development", "held_out"), default="all")
    main(parser.parse_args().split)
