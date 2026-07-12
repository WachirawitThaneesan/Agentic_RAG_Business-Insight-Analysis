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
1. grounded = ตัวเลข ชื่อบริษัท ปี และข้อเท็จจริงทุกอย่างในคำตอบ ต้องปรากฏอยู่ใน Observations เท่านั้น ห้ามมีตัวเลขหรือข้อมูลที่แต่งขึ้นเอง
2. relevant = คำตอบต้องตอบคำถามที่ถูกถามจริง ไม่ใช่ตอบเรื่องอื่น
- ถ้า Observations ว่างเปล่าหรือไม่มีข้อมูลเลย แต่คำตอบดันระบุตัวเลข/ข้อเท็จจริง ให้ถือว่า grounded = false

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

    prompt = _VERIFY_PROMPT.format(
        question=question,
        observations=observations[:6000],
        answer=answer[:3000],
    )

    try:
        async with httpx.AsyncClient(timeout=180.0, limits=HTTP_LIMITS) as client:
            resp = await client.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json={
                    "model": settings.OLLAMA_LLM_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 400},
                    **ollama_extra_fields(),
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()
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
