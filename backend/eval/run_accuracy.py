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
    _report_token_usage()


# Per-1M token prices for the hosted models we evaluate with, so a run can
# report what it actually cost instead of an estimate.
_PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.6-flash": (1.50, 7.50),
}


def _report_token_usage():
    """Print tokens + dollar cost when the run used a metered provider."""
    from backend.services import llm

    u = llm.usage
    if not u.get("calls"):
        return  # local model — nothing metered

    model = llm.settings.GEMINI_MODEL
    print(f"  provider/model : {llm.active_model()}")
    print(f"  LLM calls      : {u['calls']}")
    print(f"  input tokens   : {u['input_tokens']:,}")
    print(f"  output tokens  : {u['output_tokens']:,} (thinking {u['thinking_tokens']:,})")
    prices = _PRICES.get(model)
    if prices:
        cost = llm.usage_cost(*prices)
        print(f"  cost           : ${cost:.4f}  (~{cost * 35:.2f} THB)")
    else:
        print(f"  cost           : (no price on file for {model})")
    print()


# Below this many questions a category's pass rate carries no information, so
# it is reported as a smoke test rather than folded into the headline accuracy.
_MIN_N_FOR_RATE = 10


def _wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """95% confidence interval (percent) for k successes out of n.

    Wilson rather than the textbook normal interval, which misbehaves exactly
    where these categories live — near 100% and at small n.
    """
    import math
    if not n:
        return 0.0, 100.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half) * 100, min(1.0, centre + half) * 100


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
        lo, hi = _wilson(d["passed"], d["total"])
        extra = ""
        if d["timeout"] or d["error"]:
            extra = f"  ⏱{d['timeout']} ✖{d['error']} (of-finished {qual:.0f}%)"
        print(f"  {name:<20s} {d['passed']:>4d}/{d['total']:<4d} {strict:5.1f}%   "
              f"[{lo:5.1f} – {hi:5.1f}]{extra}")

    # A rate computed from a handful of questions is not a measurement: 2/2 is
    # consistent with a true accuracy anywhere above 34%. Report those paths as
    # smoke tests and keep them out of the headline number instead of letting
    # them read as "100%".
    measured = {c: d for c, d in by_cat.items() if d["total"] >= _MIN_N_FOR_RATE}
    smoke = {c: d for c, d in by_cat.items() if d["total"] < _MIN_N_FOR_RATE}
    m_pass = sum(d["passed"] for d in measured.values())
    m_total = sum(d["total"] for d in measured.values())
    m_to = sum(d["timeout"] for d in measured.values())
    m_err = sum(d["error"] for d in measured.values())

    print("\n" + "=" * 74)
    print("  ACCURACY BY CATEGORY (tool / reasoning style)")
    print("  strict = correct/total | [ ] = 95% confidence interval (Wilson)")
    print("=" * 74)
    for cat in sorted(measured):
        _line(cat, measured[cat])
    print("-" * 74)
    _line("OVERALL", {"passed": m_pass, "total": m_total,
                      "timeout": m_to, "error": m_err})
    print("=" * 74)
    if smoke:
        print(f"  smoke tests — n < {_MIN_N_FOR_RATE}, excluded from OVERALL "
              f"(too few questions for a rate):")
        for cat in sorted(smoke):
            d = smoke[cat]
            print(f"    {cat:<20s} {d['passed']}/{d['total']} passed")
        print("=" * 74)

    completed_total = m_total - m_to - m_err
    lo, hi = _wilson(m_pass, m_total)
    summary = {
        "overall": {
            "passed": m_pass, "total": m_total, "timeout": m_to, "error": m_err,
            "accuracy_strict": round(m_pass / m_total, 4) if m_total else 0,
            "accuracy_of_finished": round(m_pass / completed_total, 4) if completed_total else 0,
            "ci95": [round(lo, 2), round(hi, 2)],
            "excludes_smoke_tests": sorted(smoke),
        },
        "including_smoke_tests": {
            "passed": tp, "total": total,
            "accuracy_strict": round(tp / total, 4) if total else 0,
        },
        "by_category": {
            c: {**d,
                "accuracy_strict": round(d["passed"] / d["total"], 4) if d["total"] else 0,
                "accuracy_of_finished": (round(d["passed"] / (d["total"] - d["timeout"] - d["error"]), 4)
                                         if (d["total"] - d["timeout"] - d["error"]) else 0),
                "ci95": [round(x, 2) for x in _wilson(d["passed"], d["total"])],
                "smoke_test": d["total"] < _MIN_N_FOR_RATE}
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
