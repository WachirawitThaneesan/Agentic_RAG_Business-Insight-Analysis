"""Small, fixed page-ranking ablation over saved keyword/dense candidates.

All arms use exactly the same candidate union and the same locked page qrels.
This is a diagnostic experiment; no result here is a held-out test.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.eval.comprehensive import page_metrics
from scripts.evaluate_comprehensive import load, save


def page_key(hit):
    return (hit.get("filename"), hit.get("source_pdf_page"))


def rrf(keyword, dense, keyword_weight: float, dense_weight: float = 1.0):
    pages = {}
    scores = {}
    for arm, weight in ((keyword, keyword_weight), (dense, dense_weight)):
        for rank, hit in enumerate(arm, start=1):
            key = page_key(hit)
            pages.setdefault(key, hit)
            scores[key] = scores.get(key, 0) + weight / (60 + rank)
    order = sorted(pages, key=lambda key: (-scores[key], key))
    return [pages[key] for key in order]


def reserved_slots(keyword, dense, lexical_slots: int):
    result = []
    seen = set()
    for hit in keyword[:lexical_slots]:
        key = page_key(hit)
        if key not in seen:
            seen.add(key)
            result.append(hit)
    for hit in dense:
        key = page_key(hit)
        if key not in seen:
            seen.add(key)
            result.append(hit)
        if len(result) >= 5:
            break
    return result[:5]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    bank = load(a.reference)
    records = load(a.candidate)
    byid = {q["id"]: q for q in bank["items"]}
    docs = {d["code"]: d for d in bank["documents"]}
    weights = [0, 0.25, 0.5, 1, 2, 4, 8, 1000000]
    arm_names = [f"rrf_kw_{weight}" for weight in weights] + ["keyword4_dense1", "keyword3_dense2"]
    rows = []
    traces = []
    for record in records:
        q = byid[record["id"]]
        debug = record.get("ranking_debug") or {}
        keyword = debug.get("keyword_pages") or []
        dense = debug.get("semantic_pages") or []
        if not keyword and not dense:
            raise ValueError(f"Missing candidates for {record['id']}")
        union = list({page_key(h): h for h in [*keyword, *dense]}.values())
        oracle = page_metrics(q, union, docs, k=len(union))
        for arm in arm_names:
            if arm.startswith("rrf_kw_"):
                ranking = rrf(keyword, dense, float(arm.removeprefix("rrf_kw_")))[:5]
            else:
                ranking = reserved_slots(keyword, dense, 4 if arm == "keyword4_dense1" else 3)
            result = page_metrics(q, ranking, docs, k=5)
            rows.append({"id": q["id"], "document": q["document"],
                         "arm": arm, "hit5": result["hit"],
                         "recall5": result["recall"], "ndcg5": result["ndcg"],
                         "mrr5": result["mrr"], "union_hit50": oracle["hit"]})
            traces.append({"id": q["id"], "arm": arm,
                           "top5": ranking, "hit5": result["hit"]})
    summary = []
    for arm in arm_names:
        subset = [r for r in rows if r["arm"] == arm]
        summary.append({"arm": arm, "n": len(subset),
                        "hits5": sum(r["hit5"] for r in subset),
                        "hit5": sum(r["hit5"] for r in subset) / len(subset),
                        "mean_recall5": sum(r["recall5"] for r in subset) / len(subset),
                        "mean_ndcg5": sum(r["ndcg5"] for r in subset) / len(subset),
                        "mean_mrr5": sum(r["mrr5"] for r in subset) / len(subset),
                        "union_hits50": sum(r["union_hit50"] for r in subset)})
    save(a.output / "summary.json", {"arms": summary, "diagnostic_only": True,
          "same_candidate_union": True, "candidate_depth_per_arm": 50})
    save(a.output / "per_question.json", rows)
    save(a.output / "ranking_traces.json", traces)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
