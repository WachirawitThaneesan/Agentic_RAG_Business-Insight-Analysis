"""Turn exact model-call traces into auditable context and resource records."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from backend.eval.comprehensive import quote_span
from scripts.evaluate_comprehensive import load, save, write_csv


def exact_evidence_context(prompt: str) -> str | None:
    for start, end in (("หลักฐาน:\n", "\n\nคำตอบ"), ("Evidence:\n", "\n\nAnswer:")):
        if start in prompt and end in prompt:
            return prompt.split(start, 1)[1].split(end, 1)[0]
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    bank = load(a.reference)
    byid = {q["id"]: q for q in bank["items"]}
    nested = load(a.run / "model_call_traces.json")
    answers = {r["id"]: r for r in load(a.run / "app_gemini_answers.json")}
    flat, audit = [], []
    for record in nested:
        qid = record["id"]
        contexts = []
        for call in record["calls"]:
            flat.append({"id": qid, "arm": "app_gemini", **call})
            context = exact_evidence_context(call["prompt"])
            if context is not None:
                contexts.append(context)
        answer = answers[qid]
        source_pages = {int(s["page"]) for s in answer["full_result"].get("sources", [])
                        if s.get("page") is not None}
        # A page number in prose is a location declaration, not a claim-level
        # citation link. The latter remains N/A until captured by the app.
        prose_pages = {int(x) for x in re.findall(r"(?:PDF\s*)?หน้า(?:เอกสาร)?(?:ที่)?\s*(\d+)",
                                                answer.get("answer") or "")}
        ref_quote = byid[qid].get("reference_quote") or ""
        audit.append({"id": qid, "document": byid[qid]["document"],
                      "n_model_calls": len(record["calls"]),
                      "n_sdk_attempts": record["provider_attempts"],
                      "n_generation_contexts": len(contexts),
                      "context_characters": [len(c) for c in contexts],
                      "reference_quote_in_any_exact_context":
                          any(bool(quote_span(ref_quote, c)) for c in contexts) if ref_quote else None,
                      "answer": answer.get("answer") or "",
                      "returned_source_pages": sorted(source_pages),
                      "prose_pdf_pages": sorted(prose_pages),
                      "prose_page_matches_returned_source":
                          bool(prose_pages) and prose_pages <= source_pages,
                      "claim_citation_link_status": "not_measured_no_emitted_claim_link_mapping"})
    save(a.output / "generation_trace.json", flat)
    save(a.output / "answer_context_audit.json", audit)
    write_csv(a.output / "answer_context_audit.csv", audit)
    save(a.output / "summary.json", {
        "n_answers": len(audit),
        "n_logical_model_calls": len(flat),
        "n_sdk_attempts": sum(len(c["attempts"]) for c in flat),
        "n_calls_without_reported_token_usage": sum(c.get("input_tokens") is None for c in flat),
        "reported_input_tokens": sum(c.get("input_tokens") or 0 for c in flat),
        "reported_output_tokens": sum(c.get("output_tokens") or 0 for c in flat),
        "model_call_elapsed_seconds": sum(c.get("elapsed_seconds") or 0 for c in flat),
        "n_questions_with_exact_generation_context": sum(bool(r["n_generation_contexts"]) for r in audit),
        "n_reference_quotes_in_any_context": sum(r["reference_quote_in_any_exact_context"] is True for r in audit),
        "n_answer_prose_page_matches_returned_source": sum(r["prose_page_matches_returned_source"] for r in audit),
        "context_metric_limit": "Quote-in-prompt is a proxy; does not validate table row/year/unit relationships or all required claims.",
        "citation_metric_limit": "A prose page matching a returned source is not claim-level citation correctness."})


if __name__ == "__main__":
    main()
