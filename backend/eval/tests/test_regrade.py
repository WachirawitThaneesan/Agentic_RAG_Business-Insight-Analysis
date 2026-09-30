"""Old keyword-fallback passes must not survive deterministic regrading."""

import json
import sys

from backend.eval.regrade import main


def test_regrade_marks_old_low_confidence_judge_result_unscored(tmp_path, monkeypatch):
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps([{"id": 1, "grader": {"type": "llm_judge"}}]),
                      encoding="utf-8")
    run = tmp_path / "run.jsonl"
    run.write_text(json.dumps({"id": 1, "category": "text", "answer": "guess",
                               "passed": True, "grader_type": "llm_judge",
                               "confidence": "low"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["regrade", "--run", str(run),
                                   "--golden", str(golden)])
    main()
    output = tmp_path / "run_regraded.jsonl"
    verdict = json.loads(output.read_text(encoding="utf-8"))
    assert verdict["passed"] is False
    assert verdict["scored"] is False
