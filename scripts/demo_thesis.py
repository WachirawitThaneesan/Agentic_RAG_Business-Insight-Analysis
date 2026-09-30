"""Replay selected held-out results beside verified original PDF evidence pages.

This is a presentation backup for an already completed benchmark, not a live
ingestion or answer-quality test. It refuses changed PDFs and missing results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _by_id(path: Path) -> dict[str, dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Run the held-out benchmark first: {path}")
    return {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("TestFile/heldout_reference_v1.json"))
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ids", nargs="+", default=["H01", "H07", "H14"])
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    documents = {row["code"]: row for row in manifest["documents"]}
    questions = {row["id"]: row for row in manifest["items"]}
    metrics = json.loads((args.results_dir / "metrics.json").read_text(encoding="utf-8"))
    if metrics.get("n_answers") != len(manifest["items"]):
        raise ValueError("Full held-out answer run is required before creating a demo")
    search = {method: _by_id(args.results_dir / f"{method}_predictions.json")
              for method in ("bm25", "dense", "app_hybrid")}
    answers = {method: _by_id(args.results_dir / f"{method}_answers.json")
               for method in ("bm25_rag", "app_agent")}
    scores = {method: {row["id"]: row for row in data["details"]}
              for method, data in metrics["answers"].items()}
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    rows = []
    for question_id in args.ids:
        if question_id not in questions:
            raise ValueError(f"Unknown held-out question: {question_id}")
        question = questions[question_id]
        document = documents[question["document"]]
        pdf_path = (args.corpus_dir / document["source_file"]).resolve(strict=True)
        if _sha256(pdf_path) != document["source_sha256"]:
            raise ValueError(f"PDF hash changed: {pdf_path}")
        page_number = question["source_pdf_page"]
        with pymupdf.open(pdf_path) as pdf:
            if len(pdf) != document["source_page_count"]:
                raise ValueError(f"PDF page count changed: {pdf_path}")
            pixmap = pdf[page_number - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            evidence_image = output / f"{question_id}_source_page_{page_number}.png"
            pixmap.save(evidence_image)
        rows.append({
            "id": question_id,
            "question": question["question_th"],
            "reference_answer": question["reference_answer"],
            "original_pdf": str(pdf_path),
            "source_pdf_page": page_number,
            "evidence_image": str(evidence_image),
            "retrieval_top5_pages": {
                method: [hit.get("source_pdf_page") for hit in predictions[question_id]["results"][:5]]
                for method, predictions in search.items()
            },
            "answers": {
                method: {"text": predictions[question_id]["answer"],
                         "source_pages": [citation.get("source_pdf_page")
                                          for citation in predictions[question_id].get("citations", [])],
                         "fact_status": scores[method][question_id]["fact_status"],
                         "citation_page_hit": scores[method][question_id]["citation_hit"]}
                for method, predictions in answers.items()
            },
        })
    summary = {"scope": "Saved held-out benchmark replay; no live model call",
               "overall_metrics": {method: {"hit_at_5": data["hit_at_k"],
                                            "ndcg_at_5": data["ndcg_at_k"]}
                                   for method, data in metrics["retrieval"].items()},
               "examples": rows}
    target = output / "demo_summary.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
