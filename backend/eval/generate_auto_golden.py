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
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# ---- How many questions per category (edit to scale coverage vs runtime) ----
# Sized against what the data can actually supply, not an even split. Measured
# ceilings after the table re-OCR and the ambiguity filter (2026-08-02):
# structured_sql 787 (metric x year pairs), hybrid_compare 180,
# semantic_vector 837, structured_eav 78, hybrid_superlative 31 (needs >=4
# years of one metric) and graph 2 (the knowledge graph really is three nodes
# and one edge).
#
# The last two are taken whole because they are the ceiling. At n=36 and n=2 a
# category rate is indicative, not measured -- 2/2 correct is consistent with a
# true accuracy anywhere above 34%, so report graph as a worked example rather
# than a percentage.
N = {
    "structured_sql": 150,
    "hybrid_superlative": 31,   # ceiling
    "hybrid_compare": 100,
    "structured_eav": 78,       # ceiling
    "semantic_vector": 150,
    "graph": 2,                 # ceiling
}

YEARS = ["2563", "2564", "2565", "2566", "2567"]

# Clean label = mostly Thai/latin/num + a few punctuation, sensible length.
_CLEAN_LABEL = re.compile(r"^[ก-๙A-Za-z0-9 ()\.\-/,%’๑]+$")

# Labels too vague to make a self-contained question out of.
_VAGUE_LABELS = {"อื่น ๆ", "อื่นๆ", "รวม", "รวมทั้งสิ้น", "หัก", "บวก", "2. อื่น ๆ"}

# Strip an OCR row-number prefix like "12. " from an entity name.
_NUM_PREFIX = re.compile(r"^\s*\d+\.\s*")

# Trailing footnote markers the report attaches to entity names ("… Plc.1/").
_FOOTNOTE = re.compile(r"\s*\d+\s*/\s*$")

# How many distinct values one (label, year) may carry across the warehouse and
# still make a fair question. Above this, naming the table is not enough to
# single out an answer (see the note in _load_fact).
_MAX_VALUES_PER_LABEL_YEAR = 2


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

# Table names carry the page tag the re-OCR loader adds, and a band suffix that
# says which statement the column belongs to.
_PAGE_TAG = re.compile(r"^\s*\[p\d+\]\s*")


# A context only earns its place if it tells the reader *which* table is meant.
# OCR often names a table after its unit annotation ("(หน่วยพันบาท)"), which
# every financial table shares — as a disambiguator it is worse than nothing,
# because the question looks answerable while still having several right answers.
_UNIT_ONLY = re.compile(r"^[()\s]*(หน่วย|unit)\s*[:：]?\s*(ล้าน|พัน|ร้อยละ|บาท|%)")


def _table_context(table_name: str) -> str:
    """A short human phrase identifying a table, or '' if its name is unusable."""
    name = _PAGE_TAG.sub("", str(table_name or "")).strip()
    if _UNIT_ONLY.match(name):
        return ""
    # Re-OCR'd headers carry line-break spaces mid-word ("มูลค่า ยุติธรรมถือ
    # ตามยอด คงเหลือ"). As a question context that garble is unanswerable — the
    # agent cannot match it against anything. Thai needs no spaces, so collapse
    # any space between two Thai characters and keep the rest.
    name = re.sub(r"(?<=[ก-๙])\s+(?=[ก-๙])", "", name)
    # The band ("… — งบการเงินรวม") is what actually disambiguates two copies of
    # the same metric, so prefer it over the long table title.
    if "—" in name:
        band = name.rsplit("—", 1)[1].strip()
        if 3 <= len(band) <= 40:
            return band
    if not (4 <= len(name) <= 40):
        return ""
    if re.fullmatch(r"[\d.,()\-\s]+", name) or not _CLEAN_LABEL.match(name):
        return ""
    return name


def _load_fact(con) -> Dict[Any, Dict[str, Dict[str, Any]]]:
    """Return {(table, label): {year: {raw, num, unit, label, context}}}.

    Keying on the label alone conflates metrics that legitimately differ: the
    report states most figures twice, once consolidated and once bank-only, so
    "เงินให้กู้ยืม 2567" has two correct values. The old key saw that as an
    ambiguous duplicate and dropped both — discarding 165 of 303 metrics once
    the statements were split into their own tables. Keying on the source table
    keeps them apart, and ``context`` lets the question name which one it wants.
    """
    rows = con.execute(
        "SELECT table_name, row_label, metric_year, raw_value, numeric_value, unit "
        "FROM fact_financial_metrics WHERE numeric_value IS NOT NULL"
    ).fetchall()

    grouped: Dict[Any, Dict[str, list]] = {}
    values_per_ly: Dict[Any, set] = {}
    for table, label, year, raw, num, unit in rows:
        grouped.setdefault((table, label), {}).setdefault(year, []).append((raw, num, unit))
        values_per_ly.setdefault((label, year), set()).add(num)

    # A label appearing in several tables needs its table named in the question,
    # or the question has more than one right answer.
    tables_per_label: Dict[str, set] = {}
    for table, label in grouped:
        tables_per_label.setdefault(label, set()).add(table)

    clean: Dict[Any, Dict[str, Dict[str, Any]]] = {}
    for (table, label), years in grouped.items():
        if not _is_clean_label(label):
            continue
        if any(len(v) != 1 for v in years.values()):
            continue
        context = ""
        if len(tables_per_label.get(label, ())) > 1:
            context = _table_context(table)
            if not context:
                continue  # ambiguous and we cannot say which table — unusable
        # Naming the band is not always enough to single out one value: the
        # report repeats a label like "มูลค่าตามบัญชีขั้นต้น (GCA)" across
        # several similarly-named classification tables. Measured on run 13, a
        # question whose (label, year) has one or two values in the warehouse
        # scores 92-97%; at three or more it collapses to 47-56%, because the
        # agent retrieves a *different but equally valid* figure. Those are
        # unanswerable as posed, so drop the year rather than score them.
        usable = {
            y: v for y, v in years.items()
            if len(values_per_ly.get((label, y), ())) <= _MAX_VALUES_PER_LABEL_YEAR
        }
        if len(usable) < 2:
            continue
        clean[(table, label)] = {
            y: {"raw": v[0][0], "num": v[0][1], "unit": _clean_unit(v[0][2]),
                "label": label, "context": context,
                "nvals": len(values_per_ly.get((label, y), ()))}
            for y, v in usable.items()
        }
    return clean


def _phrase(years: Dict[str, Dict[str, Any]]) -> Tuple[str, str]:
    """Return (metric phrase for a question, plain label) for a fact entry."""
    cell = next(iter(years.values()))
    label, context = cell["label"], cell["context"]
    return (f"{label} ({context})" if context else label), label


def gen_structured_sql(fact: Dict[str, Dict[str, Dict[str, Any]]]) -> List[dict]:
    out = []
    # Every (metric, year) pair is a distinct answerable question, so sample the
    # pairs rather than one arbitrary year per metric: 81 metrics -> 283 pairs.
    # Interleaving by year keeps a spread sample from clustering on recent years
    # (the metrics are sorted, so _pick_spread already spreads across labels).
    pairs = [
        (key, year)
        for year in YEARS
        for key in sorted(fact, key=lambda k: (k[1], k[0]))
        if year in fact[key]
    ]
    for key, year in _pick_spread(pairs, N["structured_sql"]):
        cell = fact[key][year]
        unit = cell["unit"] or ""
        phrase, _ = _phrase(fact[key])
        out.append({
            "category": "structured_sql",
            "question": f"{phrase} ปี {year} มีค่าเท่ากับเท่าไร?",
            "ground_truth": f"{cell['raw']}{(' ' + unit) if unit else ''}".strip(),
            "grader": {"type": "numeric", "value": cell["num"]},
            "note": "fact_financial_metrics single lookup",
        })
    return out


def gen_hybrid_superlative(fact) -> List[dict]:
    out = []
    # metrics present in >=4 years make the strongest superlative questions
    # Same uniqueness rule as hybrid_compare, for a stronger reason: a max-over-
    # years question mixes every year into one comparison, so a single ambiguous
    # year silently changes which year "wins" (run 14's ส่วนของเจ้าของ failure —
    # the agent's max came from the other table carrying the same label).
    cands = sorted(
        (k for k, y in fact.items()
         if len(y) >= 4 and all(c["nvals"] == 1 for c in y.values())),
        key=lambda k: (k[1], k[0]),
    )
    for key in _pick_spread(cands, N["hybrid_superlative"]):
        years = fact[key]
        best_year, best = max(years.items(), key=lambda kv: kv[1]["num"])
        unit = best["unit"] or ""
        phrase, _ = _phrase(years)
        out.append({
            "category": "hybrid_superlative",
            "question": f"ในช่วงปี 2563 ถึง 2567 ปีใดที่ {phrase} สูงที่สุด และมีค่าเท่าไร?",
            "ground_truth": f"ปี {best_year} ที่ {best['raw']}{(' ' + unit) if unit else ''}".strip(),
            "grader": {"type": "all_of", "values": [best_year, best["num"]]},
            "note": "max over years (needs aggregation/reasoning)",
        })
    return out


def gen_hybrid_compare(fact) -> List[dict]:
    out = []
    # A delta needs the right figure on *both* sides, so ambiguity multiplies:
    # on run 13, compare questions scored 92% where each year had a single value
    # in the warehouse but 77% where either year had two, against 97% for the
    # single-year lookups. Require both sides to be unique.
    cands = sorted(
        (k for k, y in fact.items()
         if "2567" in y and "2566" in y
         and y["2567"]["nvals"] == 1 and y["2566"]["nvals"] == 1),
        key=lambda k: (k[1], k[0]),
    )
    # Identical values on both sides are almost always one OCR-duplicated row
    # (run 14: "ตั๋วแลกเงิน (รวม)" = 1 in both years), and a delta of 0 is a
    # hazardous grading target besides — skip rather than ask "how much did
    # nothing change".
    cands = [k for k in cands if fact[k]["2567"]["num"] != fact[k]["2566"]["num"]]
    for key in _pick_spread(cands, N["hybrid_compare"]):
        y = fact[key]
        v1, v2 = y["2567"]["num"], y["2566"]["num"]
        diff = round(v1 - v2, 4)
        phrase, _ = _phrase(y)
        out.append({
            "category": "hybrid_compare",
            "question": f"{phrase} ปี 2567 เปลี่ยนแปลงจากปี 2566 เป็นจำนวนเท่าไร?",
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
_PERSON_HINT = re.compile(
    r"^\s*\d*\.?\s*(นาย|นาง|นางสาว|ดร\.|ม\.ล\.|ม\.ร\.ว\.|พล\.|ศ\.|รศ\.|ผศ\.)"
)

# Board attendance is recorded as "11/12" (attended / held).
_MEETING_COL = "จำนวนครั้งที่เข้าร่วมประชุม / จำนวนครั้งที่มีการจัดประชุม"
_ATTENDANCE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")

# col_name -> (entity kind, question template). The entity kind decides which
# row_labels are usable: a company table is keyed by company name, the board
# tables by person name, and mixing the two filters yields nothing.
#
# Only columns whose header the extractor read correctly AND whose row_label is
# a real entity can become a question. Several other named columns look usable
# but are not: 'รายชื่อบริษัทที่เกี่ยวข้อง' has bare row numbers for labels (no
# entity to ask about), 'ชื่อ - นามสกุลตำแหน่ง' is two columns merged into one
# header, and 'เปลี่ยนแปลง (ร้อยละ)' holds absolute amounts rather than the
# percentages its header promises — questions from it would have wrong answers.
#
# 'ตำแหน่ง' is excluded for a subtler reason: 32 of its 41 values are the bare
# word "กรรมการ", which is a substring of the other values ("ประธานกรรมการ")
# and of any natural phrasing of the question. Every answer would pass, so the
# column inflates the score instead of measuring anything.
_EAV_ATTRS = {
    "จำนวนหุ้น": ("company", "{e} ที่ธนาคารถือ มีจำนวนกี่หุ้น?"),
    "ประเภทธุรกิจ": ("company", "{e} ประกอบธุรกิจประเภทใด?"),
    "ธนาคารถือหุ้น (%)": ("company", "ธนาคารถือหุ้นใน {e} คิดเป็นร้อยละเท่าไร?"),
    _MEETING_COL: (
        "person",
        "{e} เข้าร่วมประชุมคณะกรรมการกี่ครั้ง จากการประชุมทั้งหมดกี่ครั้ง?",
    ),
}


def _norm_col(name: str) -> str:
    """Collapse header spelling variants to one key.

    Reading the same table twice yields cosmetically different headers —
    'ธนาคารถือหุ้น (%)' vs 'ธนาคาร ถือหุ้น (%)', 'จำนวนหุ้น' vs 'จำนวนหุ้น:'.
    Matching literally silently drops the variants, and the dropped rows look
    identical to rows that were never extracted.
    """
    return re.sub(r"[\s:：]+", "", str(name or ""))


_EAV_BY_NORM = {_norm_col(k): (k, v) for k, v in _EAV_ATTRS.items()}
# The board-attendance header is truncated to varying lengths by the extractor,
# so match it by prefix rather than equality.
_MEETING_NORM = _norm_col("จำนวนครั้งที่เข้าร่วมประชุม")


def _match_attr(col_name: str):
    """Return (canonical col_name, (kind, template)) for a header, or None."""
    n = _norm_col(col_name)
    if n in _EAV_BY_NORM:
        return _EAV_BY_NORM[n]
    if n.startswith(_MEETING_NORM) or n == _norm_col("จำนวนครั้ง"):
        return _MEETING_COL, _EAV_ATTRS[_MEETING_COL]
    return None


def gen_structured_eav(con) -> List[dict]:
    # rows where the row_label itself is a named entity and attr is meaningful
    rows = con.execute(
        "SELECT row_label, col_name, col_value, col_value_num "
        "FROM dim_table_rows WHERE col_value <> ''"
    ).fetchall()

    cand = []
    seen = set()
    for row_label, col_name_raw, col_value, col_num in rows:
        matched = _match_attr(col_name_raw)
        if not matched:
            continue
        col_name, (kind, _tpl) = matched
        e = (row_label or "").strip()
        hit = _ENTITY_HINT.search(e) if kind == "company" else _PERSON_HINT.match(e)
        if not hit or not (8 <= len(e) <= 60):
            continue
        # Dedupe on the displayed name: the same director appears as both
        # "นายวิรัช …" and "1. นายวิรัช …" across tables, and the same company
        # as both "Hattha Bank PLC." and "Hattha Bank Plc.1/" (a footnote
        # marker) — which produced two questions about one entity with two
        # different official answers, so either reply scored wrong on one.
        e_disp = _FOOTNOTE.sub("", _NUM_PREFIX.sub("", e)).strip()
        key = (_norm_col(e_disp).lower(), col_name)
        if key in seen:
            continue
        seen.add(key)
        cand.append((e_disp, col_name, col_value, col_num))

    out = []
    for e_disp, col_name, col_value, col_num in _pick_spread(cand, N["structured_eav"]):
        q = _EAV_ATTRS[col_name][1].format(e=e_disp)
        attend = _ATTENDANCE.match(col_value or "")
        if attend:
            # "11/12" — require both halves, so "12 ครั้ง" alone does not pass
            grader = {"type": "all_of",
                      "values": [int(attend.group(1)), int(attend.group(2))]}
        elif col_num is not None:
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
            # The ground truth offers three wordings, so accept any of them --
            # checking only "ถือหุ้น" failed a correct answer that said "เจ้าของ".
            "grader": {"type": "any_of", "values": ["ถือหุ้น", "เจ้าของ", "ownership"]},
            "note": "knowledge graph relationship",
        },
    ]
    return items[: N["graph"]]


# ---------------------------------------------------------------------------
# chunks (Postgres) → semantic_vector  (questions synthesised by Typhoon)
# ---------------------------------------------------------------------------

# Questions that point back into their source ("according to the text…") are
# unanswerable once separated from it. Matched against synthesised questions.
_DEIXIS = re.compile(
    r"ตามข้อความ|ในข้อความ|ข้อความนี้|ข้อความข้างต้น|ตามที่กล่าว|จากข้อความ"
    r"|ในเอกสาร|ของเอกสาร|เอกสารนี้|ในบทความ|ย่อหน้า|ส่วนใดของ|หน้าที่\s*\d+"
    r"|ในตารางนี้|คอลัมน์"
)

_SYNTH_PROMPT = """\
ต่อไปนี้คือข้อความจากเอกสาร กรุณาสร้างคำถาม 1 ข้อที่ผู้อ่านทั่วไปอาจถาม
โดยคำถามต้อง "ตอบได้จากข้อความนี้เท่านั้น" และมีคำตอบที่ชัดเจน กระชับ

ข้อความ:
\"\"\"{chunk}\"\"\"

กฎของคำตอบ (สำคัญมาก เพราะคำตอบนี้จะถูกใช้เป็นเฉลยที่ตรวจแบบตรงตัว):
1. **คัดลอกตัวเลขจากข้อความมาทั้งตัว ห้ามตัดทศนิยมหรือปัดเศษ**
   ถ้าข้อความว่า "ร้อยละ 0.125" เฉลยต้องเป็น "ร้อยละ 0.125" ไม่ใช่ "ร้อยละ 0"
   ถ้าข้อความว่า "35.5 ล้านคน" เฉลยต้องเป็น "35.5 ล้านคน" ไม่ใช่ "35"
2. ใส่หน่วยกำกับด้วยถ้าข้อความมี (ล้านบาท / ล้านคน / ร้อยละ / ครั้ง)
3. **เฉลยต้องตอบสิ่งที่คำถามถามจริงๆ** ถ้าถามว่า "บริษัทใดได้รับรางวัล"
   เฉลยต้องเป็นชื่อบริษัท ไม่ใช่ชื่อผู้มอบรางวัล
4. **คำถามต้องยืนได้ด้วยตัวเอง** ผู้ตอบไม่เห็นข้อความนี้ — ห้ามใช้คำว่า
   "ตามข้อความ" "ในเอกสารนี้" "ส่วนใดของเอกสาร" "หน้าที่ X" หรืออ้างตำแหน่งในเอกสาร
   และห้ามถามสิ่งที่มีหลายคำตอบในเอกสาร (เช่น งานที่จัดหลายปี แล้วถามว่า "จัดปีใด")
5. ถ้าข้อความไม่มีคำตอบที่ชัดเจนพอ ให้ตอบ {{"question": "", "answer": ""}}

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


def _is_tabular(text: str) -> bool:
    """True when a chunk is a serialised table rather than prose.

    Those chunks produce questions like "ใครเป็นบุคคลที่มีค่าในคอลัมน์
    '31 ธันวาคม 2567' เป็น '1,000'?" — a reverse cell lookup dressed as a
    reading-comprehension question. Semantic search is the wrong instrument for
    it (the cell has no distinguishing prose to match), and the structured
    categories already cover that ground properly, so such a question measures
    nothing except which tool the router happened to pick.
    """
    t = str(text or "")
    if "CSV:" in t or "TABLE_NAME:" in t or t.count("---") >= 2:
        return True
    if sum(l.count("|") for l in t.splitlines()) >= 6:
        return True
    digits = sum(c.isdigit() for c in t)
    return digits / max(len(t), 1) > 0.18


def _load_prose_chunks() -> List[str]:
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
    rows = [r[0] for r in cur.fetchall() if not _is_tabular(r[0])]
    con.close()
    return rows


def gen_semantic_vector() -> List[dict]:
    """Synthesise questions from prose chunks spread across the whole corpus.

    The oversample has to be a *reserve*, not a longer queue. Taking 2N chunks
    and stopping at N successes silently restricted every previous run to the
    first half of the corpus by chunk id -- synthesis almost never fails, so
    the loop always stopped halfway. Draw the N primary chunks spread across
    the full pool, and only fall back to the reserve when one fails.
    """
    n = N["semantic_vector"]
    rows = _load_prose_chunks()
    primary = _pick_spread(list(range(len(rows))), n)
    used = set(primary)
    reserve = _pick_spread([i for i in range(len(rows)) if i not in used], n)

    out = []
    for i in list(primary) + list(reserve):
        if len(out) >= n:
            break
        chunk = rows[i]
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
        # Degenerate pairs are unjudgeable: an empty answer has nothing to grade
        # against, and a paragraph-length one is a summary, not a fact.
        if len(q) < 10 or not (2 <= len(a) <= 200):
            continue
        # Belt to the prompt's braces: a question that points back into the
        # chunk ("ตามข้อความ…", "ส่วนใดของเอกสาร") is unanswerable for an agent
        # that retrieves by meaning — it cannot know which text is meant. The
        # previous filter missed bare "ตามข้อความ" (no "นี้"), which leaked 9
        # such questions into run 14.
        if _DEIXIS.search(q):
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
