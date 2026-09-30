"""Rescore saved Thai final predictions with a provisional evidence review.

The frozen v1 results and their original method lock are read-only inputs.
No model, OCR, database, or network call occurs here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from backend.eval.score_layers import _load_predictions, score_answers, score_search


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "TestFile" / "heldout_thai_final_reference_v1.json"
ADJUDICATION = ROOT / "TestFile" / "heldout_thai_final_adjudication_v2.json"
FROZEN = ROOT / "TestFile" / "step8_thai_final_results_v1"
GEMINI = ROOT / "TestFile" / "step8_thai_gemini_supplement_v1"
OUTPUT = ROOT / "TestFile" / "step8_thai_rescore_v2_provisional"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence_key(evidence: dict, documents: dict[str, dict]) -> tuple[str, int]:
    code = evidence["document"]
    page = int(evidence["source_pdf_page"])
    if code not in documents or not 1 <= page <= documents[code]["source_page_count"]:
        raise ValueError(f"Invalid original PDF evidence: {evidence}")
    return code, page


def adjudicated_reference(reference: dict, adjudication: dict) -> tuple[list[dict], dict]:
    """Apply the explicit review overlay without mutating the frozen labels."""
    if adjudication.get("schema_version") != 1:
        raise ValueError("Unsupported adjudication schema")
    items = copy.deepcopy(reference["items"])
    documents = {item["code"]: item for item in reference["documents"]}
    by_id = {item["id"]: item for item in items}
    for question_id, change in adjudication["changes"].items():
        if question_id not in by_id:
            raise ValueError(f"Unknown adjudication ID: {question_id}")
        if set(change) - {"alternate_evidence", "rounding_decimals", "rounding_mode", "reason"}:
            raise ValueError(f"Unexpected adjudication fields for {question_id}")
        item = by_id[question_id]
        primary = item.get("required_evidence") or [{
            "document": item["document"], "source_pdf_page": item["source_pdf_page"]}]
        _ = [_evidence_key(evidence, documents) for evidence in primary]
        alternatives = change.get("alternate_evidence", [])
        if alternatives:
            options = [primary]
            for evidence in alternatives:
                _evidence_key(evidence, documents)
                options.append([evidence])
            item["evidence_options"] = options
        if "rounding_decimals" in change:
            if change.get("rounding_mode") != "ROUND_HALF_UP":
                raise ValueError(f"Unsupported rounding mode for {question_id}")
            decimals = change["rounding_decimals"]
            if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 12:
                raise ValueError(f"Invalid rounding precision for {question_id}")
            item["answer_components"]["rounding_decimals"] = decimals
    return items, documents


def _changed_ids(original: dict, revised: dict) -> list[str]:
    old = {row["id"]: row for row in original["details"]}
    return [row["id"] for row in revised["details"] if any(
        row.get(field) != old[row["id"]].get(field)
        for field in ("fact_status", "reason", "citation_hit", "citation_recall",
                      "all_required_pages_cited", "hit_at_k", "recall_at_k", "ndcg_at_k",
                      "first_relevant_rank"))]


def run(output: Path) -> dict:
    reference = _read(REFERENCE)
    adjudication = _read(ADJUDICATION)
    if sha256(REFERENCE) != adjudication["base_reference_sha256"]:
        raise ValueError("Frozen v1 reference hash differs from adjudication overlay")
    items, documents = adjudicated_reference(reference, adjudication)
    frozen = _read(FROZEN / "metrics.json")
    gemini = _read(GEMINI / "metrics.json")

    search = {}
    answers = {}
    changed = {"search": {}, "answers": {}}
    input_files = [REFERENCE, ADJUDICATION, FROZEN / "metrics.json", GEMINI / "metrics.json"]
    for arm in ("bm25", "dense", "app_hybrid"):
        path = FROZEN / f"{arm}_predictions.json"
        search[arm] = score_search(items, documents, _load_predictions(path),
                                   k=5, page_space="source")
        changed["search"][arm] = _changed_ids(frozen["retrieval"][arm], search[arm])
        input_files.append(path)
    for arm, directory, original in (
        ("bm25_rag", FROZEN, frozen), ("app_agent", FROZEN, frozen),
        ("bm25_gemini", GEMINI, gemini), ("app_gemini", GEMINI, gemini),
    ):
        path = directory / f"{arm}_answers.json"
        answers[arm] = score_answers(items, documents, _load_predictions(path),
                                     page_space="source")
        changed["answers"][arm] = _changed_ids(original["answers"][arm], answers[arm])
        input_files.append(path)

    result = {
        "schema_version": 2,
        "classification": "post-run provisional rescore; not a new held-out model run",
        "review_status": adjudication["review_status"],
        "questions": len(items),
        "changed_question_ids": changed,
        "original_frozen_counts": {
            "search_hit_at_5": {arm: frozen["retrieval"][arm]["hit_at_k"] for arm in search},
            "answer_correct": {arm: (frozen if arm in frozen["answers"] else gemini)
                               ["answers"][arm]["n_correct"] for arm in answers},
        },
        "search": search,
        "answers": answers,
        "sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
                   for path in input_files + [ROOT / "backend/eval/numeric.py",
                                              ROOT / "backend/eval/score_layers.py",
                                              ROOT / "scripts/rescore_heldout_thai_v2.py"]},
    }
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "metrics.json"
    temporary = destination.with_suffix(".json.part")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(destination)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({
        "classification": result["classification"],
        "search_hit_at_5": {arm: row["hit_at_k"] for arm, row in result["search"].items()},
        "answer_correct": {arm: row["n_correct"] for arm, row in result["answers"].items()},
        "changed_question_ids": result["changed_question_ids"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
