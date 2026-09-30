"""Re-grade a saved accuracy run WITHOUT re-running the agent.

Uses the current ``grade.py`` logic on the answers already captured in the
JSONL. Semantic (``llm_judge``) verdicts are kept from the original run to avoid
re-spending Typhoon calls; all deterministic graders are recomputed.

Usage:
    python -m backend.eval.regrade --run backend/eval/results/accuracy_full.jsonl \
        --golden backend/eval/golden_auto.json
"""
from __future__ import annotations

import argparse
import json

from backend.eval.grade import grade
from backend.eval.run_accuracy import summarize


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="backend/eval/results/accuracy_full.jsonl")
    ap.add_argument("--golden", default="backend/eval/golden_auto.json")
    args = ap.parse_args()

    golden = {it["id"]: it for it in json.load(open(args.golden, encoding="utf-8"))}
    rows = [json.loads(l) for l in open(args.run, encoding="utf-8")]

    out = args.run.replace(".jsonl", "_regraded.jsonl")
    changed = 0
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            item = golden.get(r["id"])
            # Old low-confidence semantic verdicts came from keyword overlap
            # when the judge failed. They cannot be treated as measured passes.
            if r.get("grader_type") == "llm_judge" and r.get("confidence") == "low":
                if r.get("passed"):
                    changed += 1
                r["passed"] = False
                r["scored"] = False
            # Keep actual semantic-judge verdicts (would re-call Typhoon).
            elif item and r.get("grader_type") != "llm_judge":
                v = grade(item, r.get("answer", ""))
                if v["passed"] != r["passed"]:
                    changed += 1
                r["passed"] = v["passed"]
                r["grader_type"] = v["grader_type"]
                r["confidence"] = v["confidence"]
                r["scored"] = v.get("scored", True)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Re-graded {len(rows)} rows ({changed} verdicts changed) -> {out}\n")
    summarize(out)


if __name__ == "__main__":
    main()
