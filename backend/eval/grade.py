"""Machine grading for the auto-generated golden set.

Each golden item has a ``grader`` block describing how to check the agent's
answer without a human:

  numeric        {value}                 – target number appears in the answer
  all_of         {values:[...]}          – every value present (num or text)
  any_of         {values:[...]}          – at least one present (value may be a
                                           list → that whole sub-list required)
  text_contains  {value}                 – normalised substring match
  llm_judge      {reference}             – Typhoon/local LLM judges correctness

Deterministic graders (everything except llm_judge) need no network and are
high-confidence. ``llm_judge`` is used only for prose/semantic answers.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_NUM_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


def _to_float(tok: str) -> Optional[float]:
    tok = tok.strip()
    neg = tok.startswith("(") and tok.endswith(")")
    tok = tok.strip("()").replace(",", "").replace("%", "")
    try:
        val = float(tok)
    except ValueError:
        return None
    return -val if neg else val


def _numbers_in(text: str) -> List[float]:
    out = []
    for m in _NUM_RE.findall(text or ""):
        v = _to_float(m)
        if v is not None:
            out.append(v)
    return out


# Thai financial values are reported in บาท / พันบาท / ล้านบาท, so the same value
# legitimately appears scaled by 1e3 or 1e6 (e.g. "52,460 พันบาท" == "52,460,000 บาท").
_SCALES = (1, 1e3, 1e6, 1e-3, 1e-6)


def _numeric_match(target: float, answer: str) -> bool:
    """True if *target* (or a unit-scaled equivalent) appears in the answer."""
    nums = _numbers_in(answer)
    for scale in _SCALES:
        t = target * scale
        tol = max(0.01, abs(t) * 0.005)
        for v in nums:
            if abs(v - t) <= tol or abs(abs(v) - abs(t)) <= tol:
                return True
    return False


def _norm_text(s: str) -> str:
    s = str(s or "").lower()
    s = re.sub(r"[\s,:;()\[\]\"'`.\-/%]+", "", s)
    return s


def _text_match(target: str, answer: str) -> bool:
    t = _norm_text(target)
    if not t:
        return False
    return t in _norm_text(answer)


def _value_present(value: Any, answer: str) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _numeric_match(float(value), answer)
    if isinstance(value, list):
        return all(_value_present(v, answer) for v in value)
    # string: try numeric first (e.g. year "2567"), then text
    fv = _to_float(str(value))
    if fv is not None and _numeric_match(fv, answer):
        return True
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
- ให้ "ผิด" (correct=false) เฉพาะเมื่อคำตอบ "ขัดแย้งกับเฉลย" ตอบผิดประเด็นชัดเจน ให้ตัวเลข/ชื่อผิด หรือบอกว่าไม่พบข้อมูล

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


def _judge_keyword(truth: str, answer: str) -> bool:
    """Last-resort fallback: token overlap between truth and answer."""
    t_tokens = set(re.findall(r"[ก-๙A-Za-z0-9]{2,}", str(truth)))
    a_tokens = set(re.findall(r"[ก-๙A-Za-z0-9]{2,}", str(answer)))
    if not t_tokens:
        return False
    return len(t_tokens & a_tokens) / len(t_tokens) >= 0.5


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------

def grade(item: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """Return {passed: bool, grader_type: str, confidence: 'high'|'medium'}."""
    g = item.get("grader", {})
    gtype = g.get("type")
    answer = answer or ""

    if gtype == "numeric":
        passed = _numeric_match(float(g["value"]), answer)
        conf = "high"
    elif gtype == "text_contains":
        passed = _text_match(str(g["value"]), answer)
        conf = "high"
    elif gtype == "all_of":
        passed = all(_value_present(v, answer) for v in g["values"])
        conf = "high"
    elif gtype == "any_of":
        passed = any(_value_present(v, answer) for v in g["values"])
        conf = "high"
    elif gtype == "llm_judge":
        verdict = _judge_typhoon(_JUDGE_PROMPT.format(
            question=item.get("question", ""),
            truth=item.get("ground_truth", ""),
            reference=g.get("reference", "")[:1200],
            answer=answer[:1500],
        ))
        if verdict is None:
            verdict = _judge_keyword(item.get("ground_truth", ""), answer)
            conf = "low"
        else:
            conf = "medium"
        passed = bool(verdict)
    else:
        return {"passed": False, "grader_type": gtype or "unknown", "confidence": "low"}

    return {"passed": bool(passed), "grader_type": gtype, "confidence": conf}
