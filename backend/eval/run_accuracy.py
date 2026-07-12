"""Run the live agent over the auto golden set and measure answer accuracy.

For every golden question we call the *real* ``agent_query`` pipeline (same code
the app uses), grade the answer with ``grade.py``, and record the result. Output
is written incrementally to a JSONL file so a long run can be interrupted and
**resumed** — already-answered question ids are skipped on restart.

At the end it prints overall accuracy and a per-category breakdown, and writes a
summary JSON next to the JSONL.

Usage:
    python -m backend.eval.run_accuracy --golden backend/eval/golden_auto.json \
        --out backend/eval/results/accuracy_run.jsonl [--limit N]
"""
from __future__ import annotations

import truststore  # noqa: E402  – use OS cert store (corporate proxy SSL)
truststore.inject_into_ssl()

import argparse
import asyncio
import json
import logging
import os
import time
from collections import defaultdict

from backend.eval.grade import grade

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("run_accuracy")
logger.setLevel(logging.INFO)


def _load_done(out_path: str) -> set:
    done = set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["id"])
                except Exception:
                    pass
    return done


async def run(golden_path: str, out_path: str, limit: int | None, timeout: float):
    from backend.database import AsyncSessionLocal
    from backend.services.agent import agent_query

    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)
    if limit:
        golden = golden[:limit]

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    done = _load_done(out_path)
    todo = [g for g in golden if g["id"] not in done]
    logger.info("Golden: %d total | %d already done | %d to run",
                len(golden), len(done), len(todo))

    for i, item in enumerate(todo, 1):
            q = item["question"]
            t0 = time.time()
            try:
                # fresh session per question — a cancelled/timed-out query can't
                # leave a poisoned session for the next one.
                async with AsyncSessionLocal() as session:
                    result = await asyncio.wait_for(agent_query(q, session), timeout=timeout)
                answer = result.get("answer", "")
                method = result.get("method", "?")
            except asyncio.TimeoutError:
                answer, method = "", "timeout"
                logger.warning("agent_query TIMEOUT (>%ss) on id=%s", int(timeout), item["id"])
            except Exception as exc:
                answer, method = "", "error"
                logger.warning("agent_query error on id=%s: %s", item["id"], exc)

            verdict = grade(item, answer)
            dt = time.time() - t0

            rec = {
                "id": item["id"],
                "category": item["category"],
                "question": q,
                "ground_truth": item.get("ground_truth", ""),
                "answer": answer,
                "method": method,
                "passed": verdict["passed"],
                "grader_type": verdict["grader_type"],
                "confidence": verdict["confidence"],
                "seconds": round(dt, 1),
            }
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            mark = "✅" if verdict["passed"] else "❌"
            logger.info("[%d/%d] %s %-18s %4.0fs | %s",
                        i, len(todo), mark, item["category"], dt, q[:60])

    summarize(out_path)


def summarize(out_path: str):
    rows = []
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    if not rows:
        logger.info("No results yet.")
        return

    # cat -> {passed, total, timeout, error}
    by_cat: dict = defaultdict(lambda: {"passed": 0, "total": 0, "timeout": 0, "error": 0})
    for r in rows:
        c = by_cat[r["category"]]
        c["total"] += 1
        if r["passed"]:
            c["passed"] += 1
        if r.get("method") == "timeout":
            c["timeout"] += 1
        elif r.get("method") == "error":
            c["error"] += 1

    def _agg(key):
        return sum(c[key] for c in by_cat.values())
    total = _agg("total"); tp = _agg("passed")
    tto = _agg("timeout"); ter = _agg("error")

    # "completed" = questions the agent actually finished (not cut off by the
    # per-question time budget / crash). Two views: strict (real-world, slowness
    # counts against you) and answer-quality (only among finished questions).
    def _line(name, d):
        completed = d["total"] - d["timeout"] - d["error"]
        strict = 100 * d["passed"] / d["total"] if d["total"] else 0
        qual = 100 * d["passed"] / completed if completed else 0
        extra = ""
        if d["timeout"] or d["error"]:
            extra = f"  (⏱{d['timeout']} ✖{d['error']} | of-finished {qual:4.0f}%)"
        print(f"  {name:<20s} {d['passed']:>3d}/{d['total']:<3d} {strict:5.1f}%{extra}")

    print("\n" + "=" * 66)
    print("  ACCURACY BY CATEGORY (tool / reasoning style)")
    print("  strict = correct/total | ⏱ = timed out | ✖ = crashed")
    print("=" * 66)
    for cat in sorted(by_cat):
        _line(cat, by_cat[cat])
    print("-" * 66)
    _line("OVERALL", {"passed": tp, "total": total, "timeout": tto, "error": ter})
    print("=" * 66)

    completed_total = total - tto - ter
    summary = {
        "overall": {
            "passed": tp, "total": total, "timeout": tto, "error": ter,
            "accuracy_strict": round(tp / total, 4) if total else 0,
            "accuracy_of_finished": round(tp / completed_total, 4) if completed_total else 0,
        },
        "by_category": {
            c: {**d,
                "accuracy_strict": round(d["passed"] / d["total"], 4) if d["total"] else 0,
                "accuracy_of_finished": (round(d["passed"] / (d["total"] - d["timeout"] - d["error"]), 4)
                                         if (d["total"] - d["timeout"] - d["error"]) else 0)}
            for c, d in by_cat.items()
        },
    }
    spath = out_path.replace(".jsonl", "_summary.json")
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  summary → {spath}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="backend/eval/golden_auto.json")
    ap.add_argument("--out", default="backend/eval/results/accuracy_run.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=240.0,
                    help="per-question wall-clock budget (s); slower = counted as fail")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    if args.summary_only:
        summarize(args.out)
        return
    asyncio.run(run(args.golden, args.out, args.limit, args.timeout))


if __name__ == "__main__":
    main()
