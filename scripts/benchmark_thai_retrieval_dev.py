"""Compare Thai retrieval variants on the exposed 20-question diagnostic set.

All layout regions are derived from every page of both source PDFs before
scoring. No gold page or answer is used when building the retrieval index.
This is development evidence, never an untouched held-out thesis result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from backend.eval.score_layers import _load_predictions, score_search
from backend.services.retrieval_rank import (
    bm25_rank, mentioned_document_ids, normalize_search_text,
)
from scripts.benchmark_heldout import _corpus
from scripts.rescore_heldout_thai_v2 import adjudicated_reference


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "TestFile/heldout_thai_final_reference_v1.json"
ADJUDICATION = ROOT / "TestFile/heldout_thai_final_adjudication_v3_ai_review.json"
FROZEN = ROOT / "TestFile/step8_thai_final_results_v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(inner, outer) -> bool:
    return (inner[0] >= outer[0] - 1 and inner[1] >= outer[1] - 1
            and inner[2] <= outer[2] + 1 and inner[3] <= outer[3] + 1
            and (outer[2] - outer[0]) * (outer[3] - outer[1]) >
            1.3 * (inner[2] - inner[0]) * (inner[3] - inner[1]))


def _layout_index(reference: dict, corpus_dir: Path) -> tuple[list[dict], list[dict]]:
    """Index each detected region and row with its physical source PDF page."""
    regions: list[dict] = []
    table_rows: list[dict] = []
    for doc in reference["documents"]:
        with pymupdf.open(corpus_dir / doc["source_file"]) as pdf:
            for page_number, page in enumerate(pdf, start=1):
                blocks = page.get_text("blocks")
                tables = page.find_tables().tables
                for table_index, table in enumerate(tables):
                    rows = table.extract()
                    if len(rows) >= 2 and max(map(len, rows)) >= 2:
                        header_i = max(range(min(4, len(rows))), key=lambda i: sum(
                            bool(re.fullmatch(r"(?:25|20)\d{2}", str(cell or "").strip()))
                            for cell in rows[i]))
                        headers = [normalize_search_text(str(x or "")).strip()
                                   for x in rows[header_i]]
                        title = normalize_search_text(" ".join(str(x or "")
                                                       for x in rows[0]))[:180]
                        for row_index, raw in enumerate(rows[header_i + 1:],
                                                        start=header_i + 1):
                            cells = [normalize_search_text(str(cell or "")).replace("\n", " ").strip()
                                     for cell in raw]
                            if len(cells) < 2 or not cells[0] or not any(cells[1:]):
                                continue
                            pairs = [f"{headers[i]}: {cell}" if i < len(headers) and headers[i]
                                     else cell for i, cell in enumerate(cells[1:], start=1) if cell]
                            table_rows.append({
                                "document": doc["code"], "filename": doc["source_file"],
                                "source_pdf_page": page_number,
                                "text": f"{title} | {cells[0]} | " + " | ".join(pairs),
                                "table_index": table_index, "row_index": row_index,
                            })

                    box = table.bbox
                    if any(i != table_index and _inside(box, other.bbox)
                           for i, other in enumerate(tables)):
                        continue
                    cells = [normalize_search_text(str(cell or ""))
                             for row in rows for cell in row if str(cell or "").strip()]
                    content = " ".join(cells)
                    if not content or not re.search(r"[ก-๙A-Za-z0-9]", content):
                        continue
                    captions = []
                    for block in blocks:
                        bx0, by0, bx1, by1, raw = block[:5]
                        overlap = min(box[2], bx1) - max(box[0] - 85, bx0)
                        if overlap < 10 or by0 < box[1] - 65 or by1 > box[1] + 5:
                            continue
                        cleaned = normalize_search_text(raw).replace("\n", " ").strip()
                        if 3 <= len(cleaned) <= 220 and re.search(r"[ก-๙A-Za-z]", cleaned):
                            captions.append((abs(box[1] - by1), cleaned))
                    caption = min(captions, default=(0, ""))[1]
                    regions.append({
                        "document": doc["code"], "filename": doc["source_file"],
                        "source_pdf_page": page_number, "table_index": table_index,
                        "caption": caption,
                        "text": f"{caption} | {content[:1700]}".strip(" |"),
                    })
    return regions, table_rows


def _predictions(items: list[dict], documents: list[dict], rows: list[dict],
                 *, company_scope: bool = False, strict_year: bool = False) -> dict[str, dict]:
    known = [(i, doc["source_file"]) for i, doc in enumerate(documents)]
    result = {}
    for item in items:
        candidates = rows
        if company_scope:
            ids = mentioned_document_ids(item["question_th"], known)
            if ids:
                codes = {documents[i]["code"] for i in ids}
                candidates = [row for row in candidates if row["document"] in codes]
        if strict_year:
            match = re.search(r"(?:25|20)\d{2}", item["question_th"])
            if match:
                candidates = [row for row in candidates if match.group() in row["text"]]
        seen = set()
        hits = []
        for row in bm25_rank(item["question_th"], candidates):
            key = (row["document"], row["source_pdf_page"])
            if key in seen:
                continue
            seen.add(key)
            hits.append({"document": key[0], "filename": row["filename"],
                         "source_pdf_page": key[1]})
            if len(hits) == 10:
                break
        result[item["id"]] = {"id": item["id"], "results": hits}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app-run", type=Path, help="New app retrieval-only run directory")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    adjudication = json.loads(ADJUDICATION.read_text(encoding="utf-8"))
    if _sha256(REFERENCE) != adjudication["base_reference_sha256"]:
        raise ValueError("Reference differs from the v3 adjudication overlay")
    items, document_map = adjudicated_reference(reference, adjudication)
    corpus_dir = args.corpus_dir.resolve()
    chunks = _corpus(reference, corpus_dir)
    regions, table_rows = _layout_index(reference, corpus_dir)
    variants = {
        "normalized_bm25": _predictions(items, reference["documents"], chunks),
        "normalized_bm25_company": _predictions(
            items, reference["documents"], chunks, company_scope=True),
        "normalized_bm25_company_strict_year": _predictions(
            items, reference["documents"], chunks, company_scope=True, strict_year=True),
        "page_layout_regions_company": _predictions(
            items, reference["documents"], regions, company_scope=True),
        "page_table_rows_company": _predictions(
            items, reference["documents"], table_rows, company_scope=True),
    }
    for name in ("bm25", "dense", "app_hybrid"):
        variants[f"frozen_{name}"] = _load_predictions(FROZEN / f"{name}_predictions.json")
    if args.app_run:
        variants["new_app_search"] = _load_predictions(
            args.app_run / "app_hybrid_predictions.json")
    scores = {name: score_search(items, document_map, predictions,
                                 k=5, page_space="source")
              for name, predictions in variants.items()}
    for name, predictions in variants.items():
        if not name.startswith("frozen_"):
            (output / f"{name}_predictions.json").write_text(
                json.dumps(list(predictions.values()), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")

    timings = None
    if args.app_run and (args.app_run / "metrics.json").is_file():
        app_metrics = json.loads((args.app_run / "metrics.json").read_text(encoding="utf-8"))
        seconds = [row["retrieval_seconds"] for row in app_metrics["timings"]]
        timings = {"n_questions": len(seconds), "median_seconds": statistics.median(seconds),
                   "max_seconds": max(seconds), "sum_seconds": sum(seconds)}
    result = {
        "classification": "exposed 20-question Thai development set; no final held-out inference",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_mode": "selectable PDF text, no OCR or answer generation",
        "source_documents": [doc["source_file"] for doc in reference["documents"]],
        "counts": {"pages": sum(doc["source_page_count"] for doc in reference["documents"]),
                   "original_chunks": len(chunks), "layout_regions": len(regions),
                   "table_rows": len(table_rows), "questions": len(items)},
        "methods": {
            "company_scope": "only when an issuer explicitly matches a filename alias; unknown names keep all documents",
            "strict_year": "experimental hard filter on first mentioned year; not deployed",
            "layout": "PyMuPDF table boxes plus nearby caption on every source page; diagnostic only",
            "scoring": "v3 AI-reviewed alternate evidence options, physical PDF page Hit@5",
        },
        "scores": scores,
        "app_retrieval_timing": timings,
        "sha256": {
            "reference": _sha256(REFERENCE), "adjudication": _sha256(ADJUDICATION),
            "script": _sha256(Path(__file__)),
            "backend/services/rag.py": _sha256(ROOT / "backend/services/rag.py"),
            "backend/services/retrieval_rank.py": _sha256(
                ROOT / "backend/services/retrieval_rank.py"),
            "backend/services/tools.py": _sha256(ROOT / "backend/services/tools.py"),
            "scripts/benchmark_heldout.py": _sha256(ROOT / "scripts/benchmark_heldout.py"),
            **{doc["source_file"]: _sha256(corpus_dir / doc["source_file"])
               for doc in reference["documents"]},
            **({"new_app_predictions": _sha256(args.app_run / "app_hybrid_predictions.json")}
               if args.app_run else {}),
        },
    }
    (output / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": result["counts"],
                      "hit_at_5": {name: round(score["hit_at_k"] * len(items))
                                   for name, score in scores.items()}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
