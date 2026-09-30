"""Rescore saved Thai predictions after the conservative AI PDF recheck.

This is a separate output from the frozen v1 and provisional v2 scores.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import rescore_heldout_thai_v2 as scorer


ROOT = Path(__file__).resolve().parents[1]
ADJUDICATION = ROOT / "TestFile" / "heldout_thai_final_adjudication_v3_ai_review.json"
OUTPUT = ROOT / "TestFile" / "step8_thai_rescore_v3_ai_review"


def main() -> None:
    scorer.ADJUDICATION = ADJUDICATION
    result = scorer.run(OUTPUT)
    result["classification"] = (
        "post-run conservative AI PDF adjudication; no independent human sign-off or new model run"
    )
    result["sha256"]["scripts/rescore_heldout_thai_ai_review_v3.py"] = hashlib.sha256(
        Path(__file__).read_bytes()).hexdigest()
    destination = OUTPUT / "metrics.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "review_status": result["review_status"],
        "search_hit_at_5": {arm: score["hit_at_k"] for arm, score in result["search"].items()},
        "answer_correct": {arm: score["n_correct"] for arm, score in result["answers"].items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
