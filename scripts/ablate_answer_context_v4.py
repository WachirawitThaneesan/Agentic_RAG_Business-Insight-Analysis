"""Compare saved actual prompt context with a new policy on identical sources."""
from __future__ import annotations

import argparse
from pathlib import Path

from backend.eval.comprehensive import quote_span
from backend.services.agent import _answer_context
from backend.services.rag import _extract_keyword_terms
from backend.services.tools import _focus_excerpt
from scripts.audit_answer_traces_v4 import exact_evidence_context
from scripts.evaluate_comprehensive import load, save, write_csv


def candidate_context(sources, question, policy):
    blocks = []
    seen = set()
    for source in sources:
        if source.get('page') is None and not source.get('url'):
            continue
        excerpt = str(source.get('excerpt') or '')
        if not excerpt:
            continue
        block = f"[{source.get('filename')} PDF page {source.get('page')}]\n{excerpt[:12000]}"
        if block not in seen:
            seen.add(block)
            blocks.append((source, block))
    if not blocks:
        return _answer_context(sources, [])
    available = 16000 - 16 * len(blocks)
    if policy == 'uniform' or len(blocks) < 3:
        budgets = [available // len(blocks)] * len(blocks)
    else:
        first = min(6500, available // 2)
        second = min(3000, (available - first) // 2)
        later = max(200, (available - first - second) // (len(blocks) - 2))
        budgets = [first, second] + [later] * (len(blocks) - 2)
    terms = _extract_keyword_terms(question)
    selected = []
    for index, ((source, block), per_source) in enumerate(zip(blocks, budgets)):
        if source.get('context_kind') != 'page' or '\n' not in block:
            selected.append(block[:per_source])
            continue
        header, body = block.split('\n', 1)
        budget = max(200, per_source - len(header) - 1)
        if policy == 'first_two' and index < 2:
            content = body[:budget]
        else:
            content = _focus_excerpt(body, terms, budget,
                                     head=min(400 if policy == 'uniform' else 200, budget // 5),
                                     question=question)
        selected.append(header + '\n' + content)
    return '\n\n'.join(selected)[:16000]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--policy", choices=['uniform', 'first_two'], default='first_two')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    bank = load(a.reference)
    byid = {q["id"]: q for q in bank["items"]}
    traces = {r["id"]: r for r in load(a.run / "model_call_traces.json")}
    rows = []
    for answer in load(a.run / "app_gemini_answers.json"):
        qid = answer["id"]
        question = byid[qid]["question_th"]
        calls = traces[qid]["calls"]
        old_contexts = [context for call in calls
                        if (context := exact_evidence_context(call["prompt"])) is not None]
        if not old_contexts:
            continue
        sources = answer["full_result"].get("sources") or []
        context = candidate_context(sources, question, a.policy)
        quote = byid[qid].get("reference_quote") or ""
        rows.append({"id": qid, "document": byid[qid]["document"],
                     "reference_quote": quote,
                     "old_quote_present": any(bool(quote_span(quote, c)) for c in old_contexts) if quote else None,
                     "new_quote_present": bool(quote_span(quote, context)) if quote else None,
                     "old_context_chars": len(old_contexts[-1]),
                     "new_context_chars": len(context),
                     "source_count": len(sources),
                     "old_context": old_contexts[-1],
                     "new_context": context})
    save(a.output / "per_question.json", rows)
    write_csv(a.output / "summary_per_question.csv", [{k:v for k,v in r.items()
               if k not in ("old_context", "new_context")} for r in rows])
    save(a.output / "summary.json", {
        "candidate_policy": a.policy,
        "n_paired_contexts": len(rows),
        "old_reference_quote_present": sum(r["old_quote_present"] is True for r in rows),
        "new_reference_quote_present": sum(r["new_quote_present"] is True for r in rows),
        "gained": [r["id"] for r in rows if r["old_quote_present"] is False and r["new_quote_present"] is True],
        "lost": [r["id"] for r in rows if r["old_quote_present"] is True and r["new_quote_present"] is False],
        "comparison_scope": "Same returned source list, exact old prompt versus new deterministic context rendering. No regenerated answer yet.",
        "metric_limit": "Verbatim quote presence is a proxy, not claim-level context recall or table tuple correctness."})


if __name__ == "__main__":
    main()
