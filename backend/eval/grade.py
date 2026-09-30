"""Machine grading for the auto-generated golden set.

Each golden item has a ``grader`` block describing how to check the agent's
answer without a human:

  numeric        {value, unit?, year?}   – signed value with verified unit/year
  all_of         {values:[...]}          – every value present (num or text)
  any_of         {values:[...]}          – at least one present (value may be a
                                           list → that whole sub-list required)
  text_contains  {value}                 – normalised substring match
  llm_judge      {reference}             – Typhoon/local LLM judges correctness

Deterministic graders need no network. ``llm_judge`` is used only for prose;
an unavailable judge is unscored rather than silently accepted by overlap.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.config import get_settings
from backend.eval.numeric import (
    decimal_value, infer_unit, mentions_in, numeric_match, question_unit, single_year,
    year_matches, years_in,
)

settings = get_settings()
logger = logging.getLogger(__name__)

_NUMERIC_LITERAL = re.compile(r"^\(?[-−]?\d[\d,]*(?:\.\d+)?\)?$")
_YEAR_LITERAL = re.compile(r"^(?:ปี\s*)?(?:25\d{2}|20\d{2})$")


def _norm_text(s: str) -> str:
    s = str(s or "").lower()
    s = re.sub(r"[\s,:;()\[\]\"'`.\-/%]+", "", s)
    return s


def _text_match(target: str, answer: str) -> bool:
    t = _norm_text(target)
    if not t:
        return False
    a = _norm_text(answer)
    if t in a:
        return True
    return _near_match(t, a)


# Ground truths are lifted from OCR'd pages, so some carry scanning artefacts
# (e.g. "ธุรกิจนับสนุน" for "ธุรกิจสนับสนุน"). An answer that spells the word
# correctly is not wrong, so allow a character or two of drift on long targets.
# The threshold stays high and short targets are excluded, because a loose
# match here would silently manufacture passes.
_NEAR_MATCH_MIN_LEN = 8
_NEAR_MATCH_RATIO = 0.92


def _near_match(target: str, answer: str) -> bool:
    if len(target) < _NEAR_MATCH_MIN_LEN or not answer:
        return False
    from difflib import SequenceMatcher

    # Anchor on the longest shared run, then line the answer up so that run sits
    # where it does in the target. Sliding a fixed window instead would need the
    # offset to land exactly, which it rarely does when the answer has a prefix.
    sm = SequenceMatcher(None, target, answer)
    block = sm.find_longest_match(0, len(target), 0, len(answer))
    # A short shared run means these are different strings that merely share a
    # common word — not a scanning artefact of the same phrase.
    if block.size < len(target) // 2:
        return False
    start = max(0, block.b - block.a)
    chunk = answer[start:start + len(target)]
    return SequenceMatcher(None, target, chunk).ratio() >= _NEAR_MATCH_RATIO


def _value_present(value: Any, answer: str, reference: str = "",
                   expected_year: int | None = None) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        unit = infer_unit(reference, value)
        return numeric_match(value, answer, expected_unit=unit,
                             expected_year=expected_year or single_year(reference))
    if isinstance(value, list):
        return all(_value_present(v, answer, reference, expected_year) for v in value)
    # A year is a contextual label, never a unit-scaled financial value.
    literal = str(value).strip()
    if _YEAR_LITERAL.fullmatch(literal):
        return year_matches(int(re.search(r"\d{4}", literal).group()), answer)
    if _NUMERIC_LITERAL.fullmatch(literal):
        number = decimal_value(literal.strip("()").replace("−", "-"))
        if literal.startswith("(") or literal.startswith("-") or literal.startswith("−"):
            number = -abs(number)
        return numeric_match(number, answer, expected_unit=infer_unit(reference, number),
                             expected_year=expected_year or single_year(reference))
    return _text_match(str(value), answer)


# ---------------------------------------------------------------------------
# LLM judge (semantic answers)
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """\
คุณคือผู้ตรวจข้อสอบ ให้ตัดสินว่า "คำตอบของระบบ" ถูกต้องหรือไม่

หลักการตัดสิน (สำคัญมาก):
- ยึด "เฉลย" (ground truth) เป็นเกณฑ์หลักในการตัดสินความถูกต้อง
- ให้ "ถูก" (correct=true) ถ้าคำตอบของระบบ "สื่อความหมายตรงกับเฉลย" หรือครอบคลุมสาระสำคัญของเฉลย
  แม้จะใช้ถ้อยคำต่างกัน เรียบเรียงใหม่ ให้รายละเอียดมากกว่า หรือดึงข้อมูลจากส่วนอื่นของเอกสารก็ตาม
- "ข้อความต้นฉบับ" เป็นเพียงบริบทเสริม ไม่ต้องบังคับว่าคำตอบต้องมาจากต้นฉบับนี้เท่านั้น
- **ตัวเลขค่าเดียวกันที่เขียนคนละรูปแบบ ถือว่าตรงกัน** เช่น
  "ร้อยละ 60" = "60%" = "60 เปอร์เซ็นต์" | "103,934 ล้านบาท" = "103934 ล้านบาท"
  | "ปี 2567" = "ปี ค.ศ. 2024" — ให้ดูที่ค่า ไม่ใช่วิธีเขียน
- เครื่องหมายบวก/ลบ ปี หน่วย และขนาดต้องตรงกัน การแปลง พันบาท/ล้านบาท/บาท
  ทำได้เฉพาะเมื่อคำตอบระบุหน่วยที่รองรับการแปลงอย่างชัดเจน
- **ห้ามตัดสินว่าผิดเพราะคำตอบ "มีมากกว่า" เฉลย** เฉลยเป็นเกณฑ์ขั้นต่ำ ไม่ใช่รายการที่ครบถ้วน
  ถ้าคำตอบครอบคลุมสาระของเฉลยครบแล้ว แต่เพิ่มประเด็น/หัวข้อ/รายละเอียดอื่นที่ไม่ขัดแย้งกัน
  ให้ถือว่า "ถูก" (correct=true) เสมอ
- ให้ "ผิด" (correct=false) เฉพาะเมื่อคำตอบ "ขัดแย้งกับเฉลย" ตอบผิดประเด็นชัดเจน ให้ตัวเลข/ชื่อผิด
  หรือบอกว่าไม่พบข้อมูล/ไม่สามารถระบุได้ ทั้งที่เฉลยมีคำตอบ

คำถาม: {question}
เฉลย (ground truth): {truth}
บริบทเสริม: {reference}
คำตอบของระบบ: {answer}

ตอบบรรทัดแรกเป็น JSON: {{"correct": true/false, "reason": "สั้นๆ"}}
JSON:"""


def _judge_typhoon(prompt: str) -> Optional[bool]:
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
                    "temperature": 0.0,
                    "max_tokens": 512,
                },
            )
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("Typhoon judge failed: %s", exc)
        return None
    # Parse the boolean directly — robust even if the JSON reason is truncated.
    m = re.search(r'"correct"\s*:\s*(true|false)', txt, re.IGNORECASE)
    if m:
        return m.group(1).lower() == "true"
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if m:
        try:
            import json
            return bool(json.loads(m.group()).get("correct"))
        except Exception:
            return None
    return None


def _single_numeric_reference(truth: str) -> tuple | None:
    """Guard LLM judgments when the reference has one explicit numeric fact."""
    year_spans = {(start, end) for start, end, _ in years_in(truth)}
    values = [m for m in mentions_in(truth) if (m.start, m.end) not in year_spans]
    if len(values) != 1 or not values[0].unit:
        return None
    return values[0].value, values[0].unit


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------

def grade(item: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """Return a verdict with ``scored=False`` when a judge is unavailable."""
    g = item.get("grader", {})
    gtype = g.get("type")
    answer = answer or ""

    if gtype == "numeric":
        unit = (g.get("unit") or infer_unit(item.get("ground_truth", ""), g["value"])
                or question_unit(item.get("question", "")))
        year = g.get("year") or single_year(item.get("ground_truth", ""))
        if year is None:
            year = single_year(item.get("question", ""))
        passed = numeric_match(g["value"], answer, expected_unit=unit,
                               expected_year=year, tolerance=g.get("tolerance", 0))
        conf = "high"
    elif gtype == "text_contains":
        passed = _text_match(str(g["value"]), answer)
        conf = "high"
    elif gtype == "all_of":
        year_labels = {int(re.search(r"\d{4}", str(v)).group()) for v in g["values"]
                       if isinstance(v, str) and _YEAR_LITERAL.fullmatch(v.strip())}
        year = next(iter(year_labels)) if len(year_labels) == 1 else None
        passed = all(_value_present(v, answer, item.get("ground_truth", ""), year)
                     for v in g["values"])
        conf = "high"
    elif gtype == "any_of":
        passed = any(_value_present(v, answer, item.get("ground_truth", "")) for v in g["values"])
        conf = "high"
    elif gtype == "llm_judge":
        if not answer.strip():
            return {"passed": False, "grader_type": gtype, "confidence": "high", "scored": True}
        constraint = _single_numeric_reference(item.get("ground_truth", ""))
        if constraint and not numeric_match(constraint[0], answer,
                                            expected_unit=constraint[1],
                                            expected_year=single_year(item.get("ground_truth", ""))):
            return {"passed": False, "grader_type": gtype, "confidence": "high", "scored": True}
        verdict = _judge_typhoon(_JUDGE_PROMPT.format(
            question=item.get("question", ""),
            truth=item.get("ground_truth", ""),
            reference=g.get("reference", "")[:1200],
            answer=answer[:1500],
        ))
        if verdict is None:
            return {"passed": False, "grader_type": gtype, "confidence": "low", "scored": False}
        else:
            conf = "medium"
        passed = bool(verdict)
    else:
        return {"passed": False, "grader_type": gtype or "unknown", "confidence": "low", "scored": False}

    return {"passed": bool(passed), "grader_type": gtype, "confidence": conf, "scored": True}
