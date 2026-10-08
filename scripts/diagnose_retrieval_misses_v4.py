"""Classify every baseline retrieval miss using saved, page-aware rankings."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from scripts.evaluate_comprehensive import load, save, write_csv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--paired", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    rows = load(a.paired)
    baseline_misses = []
    current_misses = []
    regressions = []
    for row in rows:
        if row["candidate_union_has_evidence"] == 0:
            cause = "outside_first_50_keyword_and_dense_pages_or_unindexed"
        elif row["keyword_first_rank"] is not None and row["keyword_first_rank"] <= 5:
            cause = "keyword_top5_present"
        elif row["semantic_first_rank"] is not None and row["semantic_first_rank"] <= 5:
            cause = "dense_top5_present_but_keyword_displaced"
        else:
            cause = "candidate_present_below_top5_in_both_arms"
        annotated = {**row, "diagnostic_cause": cause,
                     "cause_scope": "rank evidence only; verify actual PDF/index for root cause"}
        if not row["baseline_hit5"]:
            baseline_misses.append(annotated)
        if not row["candidate_hit5"]:
            current_misses.append(annotated)
        if row["baseline_hit5"] and not row["candidate_hit5"]:
            regressions.append(annotated)
    for name, part in (("baseline_125", baseline_misses),
                       ("candidate_misses", current_misses),
                       ("regressions", regressions)):
        save(a.output / f"{name}.json", part)
        write_csv(a.output / f"{name}.csv", part)
    save(a.output / "summary.json", {
        "n_baseline_misses": len(baseline_misses),
        "n_candidate_misses": len(current_misses),
        "n_regressions": len(regressions),
        "baseline_cause_counts": dict(Counter(r["diagnostic_cause"] for r in baseline_misses)),
        "candidate_cause_counts": dict(Counter(r["diagnostic_cause"] for r in current_misses)),
        "candidate_misses_by_document": dict(Counter(r["document"] for r in current_misses)),
        "classification_limit": "Saved top-50 pages per arm. No determination of source-text correctness, OCR, or exact indexing for pages outside union."
    })


if __name__ == "__main__":
    main()
