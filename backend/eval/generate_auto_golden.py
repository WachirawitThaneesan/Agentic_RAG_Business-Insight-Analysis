"""Auto-generate a golden evaluation set straight from the ingested data.

The idea: instead of hand-labelling questions, we *derive* questions whose
answers are already known because they come directly from the warehouse / vector
store. This lets us estimate how much of the answerable question-space the agent
gets right, across every retrieval path (tool) the agent has.

Six categories are produced, one per reasoning style / tool:

  structured_sql      – single fact lookup   → sql_query      (exact numeric GT)
  hybrid_superlative  – max-over-years        → sql_query/multi_hop (computed GT)
  hybrid_compare      – year-over-year delta  → sql_query/multi_hop (computed GT)
  structured_eav      – attribute lookup      → sql_query (EAV)  (exact GT)
  semantic_vector     – prose comprehension   → vector_search   (LLM-judged GT)
  graph               – entity relationship   → graph_search    (keyword GT)

Each item carries a machine-checkable ``grader`` block so scoring needs no
human in the loop (see ``grade.py``).

Usage:
    python -m backend.eval.generate_auto_golden --out backend/eval/golden_auto.json
"""
from __future__ import annotations

import truststore  # noqa: E402  – use OS cert store (corporate proxy SSL)
truststore.inject_into_ssl()

import argparse
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import duckdb

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# ---- How many questions per category (edit to scale coverage vs runtime) ----
N = {
    "structured_sql": 24,
    "hybrid_superlative": 18,
    "hybrid_compare": 18,
    "structured_eav": 22,
    "semantic_vector": 16,
    "graph": 2,
}

YEARS = ["2563", "2564", "2565", "2566", "2567"]

# Clean label = mostly Thai/latin/num + a few punctuation, sensible length.
_CLEAN_LABEL = re.compile(r"^[ก-๙A-Za-z0-9 ()\.\-/,%’๑]+$")

# Labels too vague to make a self-contained question out of.
_VAGUE_LABELS = {"อื่น ๆ", "อื่นๆ", "รวม", "รวมทั้งสิ้น", "หัก", "บวก", "2. อื่น ๆ"}

# Strip an OCR row-number prefix like "12. " from an entity name.
_NUM_PREFIX = re.compile(r"^\s*\d+\.\s*")


def _clean_unit(unit: str) -> str:
    """Drop OCR-garbage units that are actually numbers (e.g. unit='1,812,888')."""
    u = (unit or "").strip()
    if not u or re.fullmatch(r"[\d.,()\- ]+", u):
        return ""
    return u


def _pick_spread(items: list, k: int) -> list:
    """Deterministically pick *k* evenly-spaced items (reproducible, no RNG)."""
    if k >= len(items):
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def _is_clean_label(label: str) -> bool:
    label = (label or "").strip()
    if not (4 <= len(label) <= 55):
        return False
    if label in _VAGUE_LABELS or _NUM_PREFIX.sub("", label) in _VAGUE_LABELS:
        return False
    if re.fullmatch(r"[\d\.,()\- ]+", label):  # pure number/garbage
        return False
    if not _CLEAN_LABEL.match(label):
        return False
    return True


# ---------------------------------------------------------------------------
# fact_financial_metrics → structured_sql / hybrid_superlative / hybrid_compare
# ---------------------------------------------------------------------------

def _load_fact(con) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Return {label: {year: {raw, num, unit}}} for clean, one-row-per-year labels."""
    rows = con.execute(
        "SELECT row_label, metric_year, raw_value, numeric_value, unit "
        "FROM fact_financial_metrics WHERE numeric_value IS NOT NULL"
    ).fetchall()

    by_label: Dict[str, Dict[str, list]] = {}
    for label, year, raw, num, unit in rows:
        by_label.setdefault(label, {}).setdefault(year, []).append((raw, num, unit))

    clean: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for label, years in by_label.items():
        if not _is_clean_label(label):
            continue
        # one unambiguous value per year only
        if any(len(v) != 1 for v in years.values()):
            continue
        if len(years) < 3:
            continue
        clean[label] = {
            y: {"raw": v[0][0], "num": v[0][1], "unit": _clean_unit(v[0][2])}
            for y, v in years.items()
        }
    return clean


def gen_structured_sql(fact: Dict[str, Dict[str, Dict[str, Any]]]) -> List[dict]:
    out = []
    labels = _pick_spread(sorted(fact), N["structured_sql"])
    for label in labels:
        years = fact[label]
        # prefer the most recent year available for this metric
        year = max(years)
        cell = years[year]
        unit = cell["unit"] or ""
        out.append({
            "category": "structured_sql",
            "question": f"{label} ปี {year} มีค่าเท่ากับเท่าไร?",
            "ground_truth": f"{cell['raw']}{(' ' + unit) if unit else ''}".strip(),
            "grader": {"type": "numeric", "value": cell["num"]},
            "note": "fact_financial_metrics single lookup",
        })
    return out


def gen_hybrid_superlative(fact) -> List[dict]:
    out = []
    # metrics present in >=4 years make the strongest superlative questions
    cands = sorted(l for l, y in fact.items() if len(y) >= 4)
    for label in _pick_spread(cands, N["hybrid_superlative"]):
        years = fact[label]
        best_year, best = max(years.items(), key=lambda kv: kv[1]["num"])
        unit = best["unit"] or ""
        out.append({
            "category": "hybrid_superlative",
            "question": f"ในช่วงปี 2563 ถึง 2567 ปีใดที่ {label} สูงที่สุด และมีค่าเท่าไร?",
            "ground_truth": f"ปี {best_year} ที่ {best['raw']}{(' ' + unit) if unit else ''}".strip(),
            "grader": {"type": "all_of", "values": [best_year, best["num"]]},
            "note": "max over years (needs aggregation/reasoning)",
        })
    return out


def gen_hybrid_compare(fact) -> List[dict]:
    out = []
    cands = sorted(l for l, y in fact.items()
                   if "2567" in y and "2566" in y)
    for label in _pick_spread(cands, N["hybrid_compare"]):
        y = fact[label]
        v1, v2 = y["2567"]["num"], y["2566"]["num"]
        diff = round(v1 - v2, 4)
        out.append({
            "category": "hybrid_compare",
            "question": f"{label} ปี 2567 เปลี่ยนแปลงจากปี 2566 เป็นจำนวนเท่าไร?",
            "ground_truth": f"ต่างกัน {abs(diff):,.2f} (ปี 2567 = {y['2567']['raw']}, ปี 2566 = {y['2566']['raw']})",
            # accept either the computed delta OR both source values quoted
            "grader": {"type": "any_of", "values": [abs(diff), [v1, v2]]},
            "note": "year-over-year delta",
        })
    return out


# ---------------------------------------------------------------------------
# dim_table_rows → structured_eav
# ---------------------------------------------------------------------------

_ENTITY_HINT = re.compile(r"บริษัท|ธนาคาร|จำกัด|Bank|PLC|กองทุน|ประกัน|หลักทรัพย์")

_EAV_ATTRS = {
    "จำนวนหุ้น": "{e} ที่ธนาคารถือ มีจำนวนกี่หุ้น?",
    "ประเภทธุรกิจ": "{e} ประกอบธุรกิจประเภทใด?",
    "ธนาคารถือหุ้น (%)": "ธนาคารถือหุ้นใน {e} คิดเป็นร้อยละเท่าไร?",
}


def gen_structured_eav(con) -> List[dict]:
    # rows where the row_label itself is a named entity and attr is meaningful
    rows = con.execute(
        "SELECT row_label, col_name, col_value, col_value_num, table_name "
        "FROM dim_table_rows "
        "WHERE col_value <> '' AND col_name IN ('จำนวนหุ้น','ประเภทธุรกิจ','ธนาคารถือหุ้น (%)')"
    ).fetchall()

    cand = []
    seen = set()
    for row_label, col_name, col_value, col_num, table in rows:
        e = (row_label or "").strip()
        if not _ENTITY_HINT.search(e) or not (8 <= len(e) <= 60):
            continue
        key = (e, col_name)
        if key in seen:
            continue
        seen.add(key)
        cand.append((e, col_name, col_value, col_num))

    out = []
    for e, col_name, col_value, col_num in _pick_spread(cand, N["structured_eav"]):
        e_disp = _NUM_PREFIX.sub("", e).strip()  # drop OCR "12. " prefix in the question
        q = _EAV_ATTRS[col_name].format(e=e_disp)
        if col_num is not None:
            grader = {"type": "numeric", "value": col_num}
        else:
            grader = {"type": "text_contains", "value": col_value}
        out.append({
            "category": "structured_eav",
            "question": q,
            "ground_truth": col_value,
            "grader": grader,
            "note": f"dim_table_rows EAV lookup ({col_name})",
        })
    return out


# ---------------------------------------------------------------------------
# graph → graph_search
# ---------------------------------------------------------------------------

def gen_graph() -> List[dict]:
    items = [
        {
            "category": "graph",
            "question": "ผู้ถือหุ้นรายใหญ่ที่สุดของธนาคารกรุงศรีอยุธยาคือใคร?",
            "ground_truth": "MUFG (MUFG Bank, Ltd.)",
            "grader": {"type": "text_contains", "value": "MUFG"},
            "note": "knowledge graph ownership edge",
        },
        {
            "category": "graph",
            "question": "MUFG มีความสัมพันธ์อย่างไรกับธนาคารกรุงศรีอยุธยา?",
            "ground_truth": "MUFG เป็นผู้ถือหุ้น/เจ้าของรายใหญ่ของกรุงศรี (ownership)",
            "grader": {"type": "text_contains", "value": "ถือหุ้น"},
            "note": "knowledge graph relationship",
        },
    ]
    return items[: N["graph"]]


# ---------------------------------------------------------------------------
# chunks (Postgres) → semantic_vector  (questions synthesised by Typhoon)
# ---------------------------------------------------------------------------

_SYNTH_PROMPT = """\
ต่อไปนี้คือข้อความจากเอกสาร กรุณาสร้างคำถาม 1 ข้อที่ผู้อ่านทั่วไปอาจถาม
โดยคำถามต้อง "ตอบได้จากข้อความนี้เท่านั้น" และมีคำตอบที่ชัดเจน กระชับ

ข้อความ:
\"\"\"{chunk}\"\"\"

ตอบกลับเป็น JSON เท่านั้น รูปแบบ:
{{"question": "<คำถามภาษาไทย>", "answer": "<คำตอบสั้นๆ ที่ถูกต้องจากข้อความ>"}}
JSON:"""


def _typhoon_chat(prompt: str) -> Optional[str]:
    import httpx
    base = (settings.TYPHOON_OCR_ENDPOINT or "https://api.opentyphoon.ai/v1/ocr").replace("/ocr", "")
    try:
        with httpx.Client(timeout=90.0) as client:
            r = client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {settings.TYPHOON_API_KEY}"},
                json={
                    "model": "typhoon-v2.5-30b-a3b-instruct",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 400,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("Typhoon synth failed: %s", exc)
        return None


def _load_prose_chunks(limit: int) -> List[str]:
    import psycopg2
    con = psycopg2.connect(settings.DATABASE_URL_SYNC)
    con.set_client_encoding("UTF8")
    cur = con.cursor()
    # prose with a concrete fact (a digit) tends to yield checkable questions
    cur.execute(
        "SELECT chunk_text FROM chunks "
        "WHERE length(chunk_text) BETWEEN 250 AND 900 AND chunk_text ~ '[0-9]' "
        "ORDER BY id"
    )
    rows = [r[0] for r in cur.fetchall()]
    con.close()
    return _pick_spread(rows, limit)


def gen_semantic_vector() -> List[dict]:
    out = []
    chunks = _load_prose_chunks(N["semantic_vector"] * 2)  # oversample; some fail
    for chunk in chunks:
        if len(out) >= N["semantic_vector"]:
            break
        raw = _typhoon_chat(_SYNTH_PROMPT.format(chunk=chunk[:1500]))
        if not raw:
            continue
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            continue
        try:
            qa = json.loads(m.group())
        except json.JSONDecodeError:
            continue
        q, a = qa.get("question", "").strip(), qa.get("answer", "").strip()
        if not q or not a:
            continue
        out.append({
            "category": "semantic_vector",
            "question": q,
            "ground_truth": a,
            "grader": {"type": "llm_judge", "reference": chunk[:1200]},
            "note": "prose comprehension (Typhoon-synthesised, LLM-judged)",
        })
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backend/eval/golden_auto.json")
    ap.add_argument("--no-semantic", action="store_true",
                    help="skip Typhoon-based semantic generation (offline/quota)")
    args = ap.parse_args()

    con = duckdb.connect(settings.DUCKDB_PATH, read_only=True)
    fact = _load_fact(con)
    logger.info("Loaded %d clean fact metrics", len(fact))

    items: List[dict] = []
    items += gen_structured_sql(fact)
    items += gen_hybrid_superlative(fact)
    items += gen_hybrid_compare(fact)
    items += gen_structured_eav(con)
    items += gen_graph()
    con.close()

    if not args.no_semantic:
        logger.info("Synthesising semantic questions via Typhoon...")
        items += gen_semantic_vector()

    # stamp ids
    for i, it in enumerate(items):
        it["id"] = i

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    from collections import Counter
    by_cat = Counter(it["category"] for it in items)
    logger.info("Wrote %d questions to %s", len(items), args.out)
    for cat, c in by_cat.items():
        logger.info("   %-20s %d", cat, c)


if __name__ == "__main__":
    main()
