"""Audit labeled PDF pages and query terms for saved retrieval misses."""
from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path

import pymupdf

from backend.eval.comprehensive import quote_span
from backend.services.rag import _extract_keyword_terms
from backend.services.retrieval_rank import normalize_search_text
from scripts.evaluate_comprehensive import load, save, write_csv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--misses", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    bank, sources, misses = load(a.reference), load(a.sources), load(a.misses)
    byid = {q["id"]: q for q in bank["items"]}
    docs = {d["code"]: d for d in sources["documents"]}

    @lru_cache(maxsize=512)
    def page_text(code: str, page: int) -> str:
        with pymupdf.open(docs[code]["path"]) as pdf:
            return pdf[page - 1].get_text()

    rows = []
    for miss in misses:
        q = byid[miss["id"]]
        terms = _extract_keyword_terms(q["question_th"])
        seen = set()
        for option in q.get("evidence_options") or [[{"document": q["document"],
                                                       "source_pdf_page": q["source_pdf_page"]}]]:
            for source in option:
                code, page = source["document"], source["source_pdf_page"]
                if (code, page) in seen:
                    continue
                seen.add((code, page))
                text = page_text(code, page)
                low = normalize_search_text(text).casefold()
                matched = [term for term in terms if normalize_search_text(term).casefold() in low]
                reference_quote = q.get("reference_quote") or ""
                rows.append({"id": q["id"], "document": q["document"],
                             "labeled_document": code, "labeled_page": page,
                             "native_text_characters": len(text),
                             "query_terms": terms, "matched_terms": matched,
                             "term_coverage": len(matched) / len(terms) if terms else None,
                             "reference_quote_found_native": bool(quote_span(reference_quote, text))
                                if reference_quote else None,
                             "reference_quote": reference_quote,
                             "question": q["question_th"],
                             "diagnostic_cause": miss.get("diagnostic_cause")})
    save(a.output / "source_text_audit.json", rows)
    write_csv(a.output / "source_text_audit.csv", rows)
    save(a.output / "summary.json", {
        "n_missed_questions": len(misses), "n_labeled_pages_audited": len(rows),
        "n_native_pages_without_text": sum(r["native_text_characters"] == 0 for r in rows),
        "n_reference_quote_not_found": sum(r["reference_quote_found_native"] is False for r in rows),
        "mean_query_term_coverage": sum(r["term_coverage"] or 0 for r in rows) / len(rows),
        "limit": "Token presence in native text is not OCR/table accuracy or proof the labeled page answers the question."})


if __name__ == "__main__":
    main()
