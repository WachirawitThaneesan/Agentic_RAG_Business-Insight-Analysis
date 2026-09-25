"""Answer self-correction layer for the Agentic RAG loop.

This is the *answer-level* verifier — distinct from ``self_correction.py``,
which validates OCR **table** structure. After the ReAct agent drafts a
``Final Answer``, ``verify_answer`` asks a second LLM pass to judge whether the
answer is:

1. **Grounded** — every number / fact appears in the tool observations
   (no hallucinated figures), and
2. **Relevant** — it actually answers the user's question.

If the draft fails, the agent gets one chance to regenerate using the returned
critique. This is intentionally cheap (one extra LLM call) and fails *open*: any
error in verification returns ``verdict="pass"`` so a flaky judge never blocks a
real answer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.config import get_settings, ollama_extra_fields
from backend.services.llm import generate as llm_generate

settings = get_settings()
logger = logging.getLogger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)


@dataclass
class VerificationResult:
    """Outcome of one answer-verification pass."""

    verdict: str = "pass"          # "pass" | "fail"
    grounded: bool = True
    relevant: bool = True
    issues: List[str] = field(default_factory=list)
    critique: str = ""             # feedback fed back to the agent on retry

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


_VERIFY_PROMPT = """\
คุณคือผู้ตรวจสอบคุณภาพคำตอบของระบบวิเคราะห์ข้อมูลการเงินภาษาไทย
หน้าที่ของคุณคือตรวจว่าคำตอบด้านล่าง **อ้างอิงจากข้อมูล (Observations) ที่ระบบค้นมาได้จริง** หรือไม่ และ **ตอบตรงคำถาม** หรือไม่

เกณฑ์การตรวจ:
1. grounded = **ตัวเลขและข้อเท็จจริงที่เป็นคำตอบ** ต้องปรากฏอยู่ใน Observations ห้ามแต่งตัวเลขขึ้นเอง
2. relevant = คำตอบต้องตอบคำถามที่ถูกถามจริง ไม่ใช่ตอบเรื่องอื่น
- ถ้า Observations ว่างเปล่าหรือไม่มีข้อมูลเลย แต่คำตอบดันระบุตัวเลข/ข้อเท็จจริง ให้ถือว่า grounded = false

สิ่งที่ **ห้ามนับว่าไม่ grounded** (สำคัญมาก):
- **ปีหรือชื่อรายการที่มาจากคำถาม** — ระบบกรองข้อมูลด้วยปีอยู่แล้ว ผลลัพธ์จึงมักไม่พิมพ์ปีซ้ำ
  เช่น ถาม "สินทรัพย์รวม ปี 2567" แล้ว Observations มี "row_label=สินทรัพย์รวม, raw_value=2,620,074"
  การที่คำตอบเขียนว่า "ปี 2567 เท่ากับ 2,620,074" ถือว่า **grounded = true** เพราะปีมาจากคำถาม
- การจัดรูปแบบตัวเลขใหม่ ใส่เครื่องหมายจุลภาค หรือระบุหน่วยที่มีอยู่ใน Observations
- การเรียบเรียงถ้อยคำใหม่โดยความหมายเดิม

ให้ grounded = false เฉพาะเมื่อคำตอบมี **ตัวเลขหรือข้อเท็จจริงที่หาไม่ได้เลยใน Observations**

คำถาม:
{question}

ข้อมูลที่ระบบค้นมาได้ (Observations):
{observations}

คำตอบที่จะตรวจสอบ:
{answer}

ตอบกลับเป็น JSON เท่านั้น ห้ามมีข้อความอื่น:
{{"grounded": true/false, "relevant": true/false, "issues": ["ปัญหาที่พบ (ถ้ามี)"], "critique": "คำแนะนำสั้นๆ ว่าควรแก้คำตอบอย่างไรให้ถูกต้องตาม Observations"}}
JSON:"""


_NUM_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


def _nums(text: str) -> List[float]:
    out = []
    for tok in _NUM_RE.findall(text or ""):
        neg = tok.startswith("(") and tok.endswith(")")
        t = tok.strip("()").replace(",", "").replace("%", "")
        try:
            v = float(t)
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def _numeric_grounding_ok(answer: str, observations: str) -> bool:
    """Deterministic anti-hallucination check.

    Returns False only when the answer asserts significant numbers and *every*
    one of them is absent from the observations — a strong sign the model made
    them up. We allow unit-scaled equivalents (×/÷1e3, ×/÷1e6) and simple
    sums/differences of observation numbers, so legitimate unit conversions and
    year-over-year deltas are NOT flagged.
    """
    ans = [n for n in _nums(answer) if abs(n) >= 1000 and not (2400 <= n <= 2600)]
    if not ans:
        return True  # no significant numbers to verify
    obs = _nums(observations)
    if not obs:
        return True  # no data numbers to compare against — leave to caller/LLM

    allowed = set()
    for n in obs:
        allowed.update((n, n * 1e3, n / 1e3, n * 1e6, n / 1e6))
    # pairwise sums/differences cover computed deltas (compare questions)
    for i, a in enumerate(obs):
        for b in obs[i + 1:]:
            allowed.update((a + b, abs(a - b)))

    def grounded(x: float) -> bool:
        return any(abs(x - c) <= max(1.0, abs(c) * 0.01) for c in allowed)

    # Fail only if NONE of the answer's numbers are grounded.
    return any(grounded(x) for x in ans)


# --------------------------------------------------------------------------
# Answer focus: a single-value question answered with several candidate values
# --------------------------------------------------------------------------
# The SYSTEM_PROMPT has carried a "answer only what was asked" rule since
# Aug 15 and the agent still volunteers extra figures ("60% … Gartner คาดว่า
# 70%"), which the judge rightly fails. A standing prompt rule the model
# ignores is not made to work by rewording it — the check belongs in the loop,
# where a violation produces a concrete critique naming the competing values.
_PLURAL_MARKERS = ("บ้าง", "แต่ละ", "ทั้งหมด", "ประกอบด้วย", "ใดบ้าง", "อะไรบ้าง", "รายการใด")
_COMPARE_MARKERS = ("เปรียบเทียบ", "ผลต่าง", "เทียบกับ", "เพิ่มขึ้นหรือลดลง", "มากกว่าหรือน้อยกว่า")
_YEAR_RE = re.compile(r"(?:25|20)\d{2}")
_PCT_RE = re.compile(r"(?:ร้อยละ\s*|)(\d+(?:\.\d+)?)\s*(?:%|เปอร์เซ็นต์)|ร้อยละ\s*(\d+(?:\.\d+)?)")
_TH_MONTHS = (
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
)
_DATE_RE = re.compile(
    r"(\d{1,2})\s*(?:-\s*\d{1,2}\s*)?(" + "|".join(_TH_MONTHS) + r")\s*(?:พ\.ศ\.\s*)?((?:25|20)\d{2})?"
)
_HOW_MANY_RE = re.compile(r"กี่\s*([ก-๙A-Za-z]{2,12})")


def _percentages(text: str) -> List[float]:
    out = []
    for m in _PCT_RE.finditer(text or ""):
        raw = m.group(1) or m.group(2)
        if raw:
            out.append(float(raw))
    return out


def _years(text: str) -> List[int]:
    return [int(y) for y in _YEAR_RE.findall(text or "")]


def _dates(text: str) -> List[str]:
    return [
        f"{m.group(1)} {m.group(2)} {m.group(3) or ''}".strip()
        for m in _DATE_RE.finditer(text or "")
    ]


def _counts_of(text: str, classifier: str) -> List[float]:
    return [
        float(m.group(1))
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*" + re.escape(classifier), text or "")
    ]


def _classifier_counts(question: str, answer: str) -> tuple:
    """Values counted by the classifier a "กี่X" question asks for.

    Thai is unsegmented, so the regex capture after "กี่" runs into the next
    word ("กี่ประการในแผน…"); walk the prefix down until one appears in the
    answer after a number. Returns ``(classifier, values)``.
    """
    m = _HOW_MANY_RE.search(question)
    if not m:
        return None, []
    tail = m.group(1)
    for size in range(len(tail), 1, -1):
        classifier = tail[:size]
        values = _counts_of(answer, classifier)
        if values:
            return classifier, values
    return None, []


def _focus_violation(question: str, answer: str) -> Optional[str]:
    """Critique when a question asking for one value got several back.

    Deliberately narrow: it fires on 3 of 501 stored answers of the last full
    run, all three genuine contamination failures, and on none of the 458 that
    passed. Anything broader starts redrafting answers that were already right.
    """
    q, a = str(question or ""), str(answer or "")
    if not q or not a:
        return None
    # Questions that legitimately ask for a list, or for two sides of a compare.
    if any(w in q for w in _PLURAL_MARKERS) or any(w in q for w in _COMPARE_MARKERS):
        return None
    if len(set(_years(q))) >= 2:
        return None

    kind: Optional[str] = None
    values: List[Any] = []
    if "ร้อยละ" in q or "%" in q or "สัดส่วน" in q:
        kind, values = "ร้อยละ", _percentages(a)
    elif re.search(r"ปีใด|ปีไหน|ภายในปี|ในปีใด|เมื่อปีใด", q):
        asked = set(_years(q))          # a year the question names is not an extra
        kind, values = "ปี", [y for y in _years(a) if y not in asked]
    elif re.search(r"เมื่อใด|เมื่อไร|วันใด|วันที่เท่าใด|เมื่อวันที่ใด", q):
        kind, values = "วันที่", _dates(a)
    else:
        kind, values = _classifier_counts(q, a)
    if not kind:
        return None

    distinct = list(dict.fromkeys(values))
    if len(distinct) < 2:
        return None
    shown = ", ".join(str(v) for v in distinct[:4])
    return (
        f"คำถามถาม{kind}เพียงค่าเดียว แต่คำตอบเสนอหลายค่า ({shown}) "
        f"ให้เลือกค่าเดียวที่ตอบคำถามตรงที่สุดจาก Observation แล้วเขียน Final Answer ใหม่ "
        f"เป็นประโยคบอกเล่าสั้น ๆ ประโยคเดียวที่ระบุค่านั้น "
        f"ห้ามอธิบายเหตุผล ห้ามเทียบข้อดีข้อเสียของแต่ละค่า ห้ามกล่าวถึงค่าอื่น "
        f"และห้ามนำค่ามารวมหรือบวกกันเป็นค่าใหม่ "
        f"ถ้าลังเลระหว่างสองค่า ให้เลือกค่าที่ข้อความระบุเจาะจงที่สุดแล้วตอบไปเลย"
    )


def _parse_verdict_json(raw: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from the judge's reply."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


async def verify_answer(
    question: str,
    answer: str,
    observations: str,
) -> VerificationResult:
    """Judge whether *answer* is grounded in *observations* and on-topic.

    Fails **open**: any exception or unparseable judge output returns a passing
    result so verification can never block a legitimate answer.
    """
    answer = (answer or "").strip()
    observations = (observations or "").strip()

    # Nothing to check — let it through.
    if not answer:
        return VerificationResult(verdict="pass")

    # No observations at all but the answer asserts facts → treat as ungrounded
    # without spending an LLM call.
    if not observations:
        return VerificationResult(
            verdict="fail",
            grounded=False,
            issues=["ไม่มีข้อมูลจาก tool แต่คำตอบระบุข้อเท็จจริง"],
            critique="ไม่พบข้อมูลจากการค้นหา ควรเรียก tool เพื่อค้นหาข้อมูลก่อนตอบ",
        )

    # Deterministic numeric-grounding guard — catches invented figures before
    # spending an LLM call (allows unit-scaling and computed deltas).
    if not _numeric_grounding_ok(answer, observations):
        return VerificationResult(
            verdict="fail",
            grounded=False,
            issues=["ตัวเลขในคำตอบไม่ปรากฏในข้อมูลที่ค้นมา (อาจแต่งขึ้นเอง)"],
            critique=(
                "ให้ใช้เฉพาะตัวเลขที่ปรากฏใน Observation เท่านั้น ห้ามแต่งตัวเลขเอง "
                "ถ้าไม่พบตัวเลขที่ต้องการใน Observation ให้ตอบว่าไม่พบข้อมูลในเอกสาร"
            ),
        )

    # Answer-focus guard — deterministic, so it costs no LLM call. A right
    # answer carrying an extra wrong figure grades as wrong, and the judge is
    # correct to fail it; ask for the one value the question wanted instead.
    focus_critique = _focus_violation(question, answer)
    if focus_critique:
        return VerificationResult(
            verdict="fail",
            relevant=False,
            issues=["คำตอบเสนอหลายค่าให้คำถามที่ต้องการค่าเดียว"],
            critique=focus_critique,
        )

    prompt = _VERIFY_PROMPT.format(
        question=question,
        observations=observations[:6000],
        answer=answer[:3000],
    )

    try:
        raw = await llm_generate(prompt, temperature=0.0, max_tokens=400)
    except Exception as exc:
        logger.warning("Answer verification call failed (failing open): %s", exc)
        return VerificationResult(verdict="pass")

    parsed = _parse_verdict_json(raw)
    if parsed is None:
        logger.warning("Could not parse verifier output (failing open): %s", raw[:200])
        return VerificationResult(verdict="pass")

    grounded = bool(parsed.get("grounded", True))
    relevant = bool(parsed.get("relevant", True))
    issues = parsed.get("issues") or []
    if isinstance(issues, str):
        issues = [issues]
    critique = str(parsed.get("critique", "")).strip()

    verdict = "pass" if (grounded and relevant) else "fail"
    logger.info(
        "Answer verification: verdict=%s grounded=%s relevant=%s",
        verdict, grounded, relevant,
    )

    return VerificationResult(
        verdict=verdict,
        grounded=grounded,
        relevant=relevant,
        issues=[str(i) for i in issues],
        critique=critique,
    )
