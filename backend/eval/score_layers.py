"""Separate, offline evaluation of OCR cells, search evidence, and answers.

Use the original-PDF reference set for search/answers and the existing exact
cell gold for cached OCR. No model or API call occurs in this module.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from backend.eval.numeric import mentions_in, numeric_match, single_year, years_in


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "TestFile" / "reference_pages_v1.json"


def _load_predictions(path: Path) -> dict[str, dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        payload = json.loads(text)
        records = payload["items"] if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Predictions must be a JSON array, JSONL, or object with items")
    by_id = {}
    for record in records:
        rid = str(record["id"])
        if rid in by_id:
            raise ValueError(f"Duplicate prediction id: {rid}")
        by_id[rid] = record
    return by_id


def _reference(path: Path) -> tuple[list[dict], dict[str, dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") not in (1, 2):
        raise ValueError("Unsupported reference schema")
    documents = {d["code"]: d for d in payload["documents"]}
    items = payload["items"]
    if len({x["id"] for x in items}) != len(items):
        raise ValueError("Duplicate reference id")
    return items, documents


def _same_document(hit: dict, code: str, documents: dict[str, dict]) -> bool:
    if hit.get("document") and hit["document"] != code:
        return False
    filename = hit.get("filename") or hit.get("source_file") or hit.get("excerpt_file")
    doc = documents[code]
    if filename:
        basename = str(filename).replace("\\", "/").split("/")[-1].casefold()
        if basename not in {doc["source_file"].casefold(), doc["excerpt_file"].casefold()}:
            return False
    return bool(hit.get("document") == code or filename)


def _page(hit: dict, page_space: str | None) -> tuple[str, int] | None:
    if hit.get("source_pdf_page") is not None:
        return "source", int(hit["source_pdf_page"])
    if hit.get("excerpt_page") is not None:
        return "excerpt", int(hit["excerpt_page"])
    if hit.get("page") is not None:
        space = hit.get("page_space") or page_space
        if space in ("source", "excerpt"):
            return space, int(hit["page"])
    return None


def _evidence_key(hit: dict, documents: dict[str, dict], page_space: str | None) -> tuple[str, int] | None:
    page = _page(hit, page_space)
    if page is None:
        return None
    for code in documents:
        if _same_document(hit, code, documents):
            doc = documents[code]
            if page[0] == "source":
                return code, page[1]
            # Convert excerpt physical page to source physical page using the
            # reference map in the caller; only labeled pages are needed here.
            return code, -page[1]
    return None


def _required_keys(item: dict) -> set[tuple[str, int]]:
    required = item.get("required_evidence")
    if required:
        return {(x["document"], int(x["source_pdf_page"])) for x in required}
    return {(item["document"], int(item["source_pdf_page"]))}


def _evidence_options(item: dict) -> list[set[tuple[str, int]]]:
    """Each option is a complete set of pages that can support the fact."""
    options = item.get("evidence_options")
    if options is None:
        return [_required_keys(item)]
    if not isinstance(options, list) or not options:
        raise ValueError(f"evidence_options must be a nonempty list for {item['id']}")
    parsed = []
    for option in options:
        if not isinstance(option, list) or not option:
            raise ValueError(f"Each evidence option needs at least one page for {item['id']}")
        parsed.append({(x["document"], int(x["source_pdf_page"])) for x in option})
    return parsed


def _hit_key(hit: dict, items: list[dict], documents: dict[str, dict],
             page_space: str | None) -> tuple[str, int] | None:
    key = _evidence_key(hit, documents, page_space)
    if key is None or key[1] >= 0:
        return key
    ep = -key[1]
    mapping = {(x["document"], int(x["excerpt_page"])): int(x["source_pdf_page"]) for x in items}
    source = mapping.get((key[0], ep))
    return (key[0], source) if source is not None else key


def score_search(items: list[dict], documents: dict[str, dict],
                 predictions: dict[str, dict], *, k: int = 5,
                 page_space: str | None = None) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    details = []
    for item in items:
        predicted = predictions.get(item["id"], {})
        results = predicted.get("results") or []
        if not isinstance(results, list):
            raise ValueError(f"results must be a list for {item['id']}")
        options = _evidence_options(item)
        ranked_keys = []
        unlocatable = 0
        for rank, hit in enumerate(results[:k], 1):
            key = _hit_key(hit, items, documents, page_space)
            if key is None:
                unlocatable += 1
            ranked_keys.append(key)
        option_scores = []
        for required in options:
            found = set()
            dcg = 0.0
            first_rank = None
            for rank, key in enumerate(ranked_keys, 1):
                if key in required and key not in found:
                    found.add(key)
                    dcg += 1 / math.log2(rank + 1)
                    if first_rank is None:
                        first_rank = rank
            ideal = sum(1 / math.log2(rank + 1) for rank in range(
                1, min(k, len(required)) + 1))
            option_scores.append((bool(found), len(found) / len(required),
                                  dcg / ideal if ideal else 0, first_rank))
        best = max(option_scores, key=lambda row: (row[1], row[2]))
        details.append({"id": item["id"], "hit_at_k": best[0],
                        "recall_at_k": best[1],
                        "ndcg_at_k": best[2],
                        "first_relevant_rank": best[3],
                        "unlocatable_top_k": unlocatable,
                        "missing_prediction": item["id"] not in predictions})
    n = len(details)
    return {"layer": "search", "k": k, "n_questions": n,
            "n_missing_predictions": sum(x["missing_prediction"] for x in details),
            "n_unlocatable_results_top_k": sum(x["unlocatable_top_k"] for x in details),
            "hit_at_k": sum(x["hit_at_k"] for x in details) / n if n else None,
            "recall_at_k": sum(x["recall_at_k"] for x in details) / n if n else None,
            "ndcg_at_k": sum(x["ndcg_at_k"] for x in details) / n if n else None,
            "details": details}


def _norm(text: str) -> str:
    return re.sub(r"[^\wก-๙]+", "", str(text or "").casefold())


def _answer_fact(item: dict, answer: str) -> tuple[str, str]:
    if not answer.strip():
        return "incorrect", "empty_answer"
    components = item.get("answer_components") or {}
    if "value" in components:
        year = components.get("year_be")
        if year is None and components.get("date"):
            year = int(str(components["date"])[:4])
        supporting_values = tuple(components.get("supporting_values") or ())
        if "total" in components:
            supporting_values += (components["total"],)
        comparison_years = components.get("comparison_years")
        if comparison_years:
            stated_years = {y for _, _, y in years_in(answer)}
            if stated_years - set(comparison_years):
                return "incorrect", "wrong_comparison_year"
            year = None
        correct = numeric_match(components["value"], answer,
                                expected_unit=components.get("unit"), expected_year=year,
                                allowed_other_values=supporting_values,
                                allowed_other_quantities=tuple((q['value'], q['unit']) for q in components.get('supporting_quantities', [])),
                                rounding_decimals=components.get("rounding_decimals"))
        if correct:
            return "correct", "numeric_fact"
        # A bare correct number needs review because its unit is unverified.
        if (components.get("unit") and not any(m.unit for m in mentions_in(answer))
                and numeric_match(components["value"], answer, expected_year=year,
                                  allowed_other_values=(components["total"],) if "total" in components else ())):
            return "needs_review", "missing_or_ambiguous_unit"
        return "incorrect", "wrong_number_sign_year_unit_or_scale"
    if "count" in components and "percent" in components:
        count_ok = numeric_match(components["count"], answer,
                                 expected_unit=components["count_unit"],
                                 expected_year=components.get("year_be"))
        percent_ok = numeric_match(components["percent"], answer,
                                   expected_unit=components["percent_unit"],
                                   expected_year=components.get("year_be"))
        return ("correct", "count_and_percent") if count_ok and percent_ok else (
            "incorrect", "wrong_count_or_percent")
    expected = _norm(item["reference_answer"])
    actual = _norm(answer)
    target_year = single_year(item.get("question_th", ""))
    if target_year is not None and years_in(answer) and target_year not in {
        year for _, _, year in years_in(answer)
    }:
        return "incorrect", "wrong_year"
    if expected and expected == actual:
        return "correct", "exact_short_text_match"
    return "needs_review", "semantic_wording_requires_review"


def score_answers(items: list[dict], documents: dict[str, dict],
                  predictions: dict[str, dict], *, page_space: str | None = None) -> dict:
    details = []
    for item in items:
        predicted = predictions.get(item["id"], {})
        status, reason = _answer_fact(item, str(predicted.get("answer") or ""))
        citations = predicted.get("citations") or []
        if not isinstance(citations, list):
            raise ValueError(f"citations must be a list for {item['id']}")
        options = _evidence_options(item)
        cited = {_hit_key(cite, items, documents, page_space) for cite in citations}
        citation_recall = max(len(required & cited) / len(required) for required in options)
        citation_hit = citation_recall > 0
        details.append({"id": item["id"], "fact_status": status, "reason": reason,
                        "citation_hit": citation_hit,
                        "citation_recall": citation_recall,
                        "all_required_pages_cited": citation_recall == 1,
                        "citation_status": "correct_page" if citation_hit else (
                            "wrong_or_unlocatable_page" if citations else "missing"),
                        "missing_prediction": item["id"] not in predictions})
    n = len(details)
    determined = [x for x in details if x["fact_status"] != "needs_review"]
    correct = sum(x["fact_status"] == "correct" for x in details)
    return {"layer": "answers", "n_questions": n,
            "n_correct": correct,
            "n_incorrect": sum(x["fact_status"] == "incorrect" for x in details),
            "n_needs_review": n - len(determined),
            "n_missing_predictions": sum(x["missing_prediction"] for x in details),
            "fact_accuracy_determined": correct / len(determined) if determined else None,
            "fact_accuracy_strict_lower_bound": correct / n if n else None,
            "citation_page_hit_rate": sum(x["citation_hit"] for x in details) / n if n else None,
            "citation_page_recall": sum(x["citation_recall"] for x in details) / n if n else None,
            "citation_all_required_rate": sum(x["all_required_pages_cited"] for x in details) / n if n else None,
            "unsupported_abstention_rate": None,
            "details": details}


def score_ocr_cache() -> dict:
    from scripts.score_ocr_cells import GOLD, MANIFEST, score_cached_fact

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    hashes = {d["excerpt_file"]: d["excerpt_sha256"] for d in manifest["documents"]}
    details = []
    for fact in gold["facts"]:
        result = score_cached_fact(fact, hashes[fact["excerpt_file"]])
        details.append({"id": fact["id"], "kind": fact["source_kind"], **result})
    cells = [x for x in details if x["kind"] == "table_cell"]
    charts = [x for x in details if x["kind"] == "chart_fact"]
    scored = [x for x in cells if not x["outcome"].startswith("not_scored")]
    correct = sum(x["outcome"] == "correct" for x in scored)
    return {"layer": "ocr_tables", "benchmark": "TestFile/ocr_cell_gold.json",
            "n_labeled_cells": len(cells), "n_scored_cells": len(scored),
            "n_correct_cells": correct,
            "cell_accuracy": correct / len(scored) if scored else None,
            "n_ocr_failures": sum(x["outcome"] == "ocr_failed" for x in scored),
            "n_unsafe_accepted": sum(bool(x.get("unsafe_accepted")) for x in scored),
            "n_chart_facts_labeled": len(charts),
            "n_chart_facts_unresolved": sum(x["outcome"] == "unresolved_chart_fact" for x in charts),
            "chart_fact_accuracy": None, "details": details}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="layer", required=True)
    ocr = sub.add_parser("ocr-cache", help="Score cached OCR against exact table-cell labels")
    ocr.add_argument("--out", type=Path)
    for name in ("search", "answers"):
        command = sub.add_parser(name)
        command.add_argument("--reference", type=Path, default=REFERENCE)
        command.add_argument("--predictions", type=Path, required=True)
        command.add_argument("--page-space", choices=("source", "excerpt"))
        command.add_argument("--out", type=Path)
        if name == "search":
            command.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    if args.layer == "ocr-cache":
        result = score_ocr_cache()
    else:
        items, documents = _reference(args.reference)
        predictions = _load_predictions(args.predictions)
        unknown = sorted(set(predictions) - {item["id"] for item in items})
        if unknown:
            raise ValueError(f"Unknown prediction IDs: {unknown[:5]}")
        if args.layer == "search":
            result = score_search(items, documents, predictions, k=args.k,
                                  page_space=args.page_space)
        else:
            result = score_answers(items, documents, predictions,
                                   page_space=args.page_space)
        result["reference"] = str(args.reference)
    result["schema_version"] = 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
