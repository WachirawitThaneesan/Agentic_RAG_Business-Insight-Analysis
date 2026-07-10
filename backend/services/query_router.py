"""Deterministic query router for tool selection.

The ReAct agent used to decide *which* tool to call purely from free-text LLM
output, which is unreliable with a local model (e.g. it would reach for
``tavily_search`` or ``graph_search`` on questions that are plainly answerable
from the SQL warehouse). This module adds a cheap keyword-based classifier that
suggests the right tool up front. The agent still runs a full ReAct loop — the
suggestion is injected as a strong hint, not a hard override — so genuinely
hybrid questions can still branch.

``route_query`` returns the suggested tool, a confidence score, and the keyword
scores per tool (useful for logging / evaluation).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Keyword signals per tool. Weights favour specific/unambiguous terms.
# ---------------------------------------------------------------------------

# Structured / numeric / tabular lookups -> DuckDB SQL
_SQL_TERMS: Dict[str, int] = {
    # magnitudes & comparisons
    "เท่าไร": 3, "เท่าไหร่": 3, "กี่": 3, "จำนวน": 2, "อัตรา": 2, "ร้อยละ": 2,
    "สูงสุด": 3, "ต่ำสุด": 3, "มากที่สุด": 3, "น้อยที่สุด": 3, "อันดับ": 3,
    "เพิ่มขึ้น": 2, "ลดลง": 2, "เปรียบเทียบ": 2, "รวมกัน": 2,
    # financial metrics
    "roa": 4, "roe": 4, "npl": 4, "eps": 4, "สินทรัพย์": 3, "หนี้สิน": 3,
    "กำไร": 3, "ขาดทุน": 3, "รายได้": 3, "เงินกองทุน": 3, "งบการเงิน": 3,
    "ทุนจดทะเบียน": 3, "ทุนชำระ": 3,
    # investment / holdings tables
    "จำนวนหุ้น": 4, "ถือหุ้น": 3, "สัดส่วน": 3, "ลงทุน": 3, "ประเภทธุรกิจ": 3,
    "บริษัทใด": 3, "บริษัทอะไร": 3, "บริษัทใดบ้าง": 3, "กี่บริษัท": 4,
}

# Qualitative / narrative content -> pgvector semantic search
_VECTOR_TERMS: Dict[str, int] = {
    "นโยบาย": 3, "กลยุทธ์": 3, "มาตรการ": 3, "โครงการ": 3, "แนวทาง": 2,
    "esg": 4, "ความยั่งยืน": 3, "วิสัยทัศน์": 3, "พันธกิจ": 3, "บทบาท": 2,
    "หน้าที่": 2, "อธิบาย": 2, "สาเหตุ": 2, "ทำไม": 2, "เพราะเหตุใด": 3,
    "อย่างไร": 2, "ปัจจัยความเสี่ยง": 3, "ความเสี่ยง": 2, "รางวัล": 2,
    "หลักการ": 2, "แผนงาน": 2, "การกำกับดูแล": 2,
}

# Entity relationships / graph questions -> knowledge graph
_GRAPH_TERMS: Dict[str, int] = {
    "ความสัมพันธ์ระหว่าง": 5, "ความสัมพันธ์": 3, "เชื่อมโยง": 3,
    "ใครเป็นเจ้าของ": 5, "เป็นเจ้าของ": 3, "โครงสร้างผู้ถือหุ้น": 4,
    "โครงสร้างการถือหุ้น": 4, "บริษัทในเครือ": 3, "กลุ่มบริษัท": 2,
    "ดำรงตำแหน่ง": 3, "เป็นกรรมการใน": 4, "นั่งเป็นกรรมการ": 4,
}

# Explicit "go to the internet" signals -> web search
_WEB_TERMS: Dict[str, int] = {
    "ข่าว": 3, "ล่าสุด": 2, "ปัจจุบัน": 1, "ค้นอินเทอร์เน็ต": 5,
    "ค้นเว็บ": 5, "ค้นหาในเว็บ": 5, "ราคาหุ้นวันนี้": 5,
}

_YEAR_RE = re.compile(r"\b(?:25|20)\d{2}\b")


@dataclass
class RouteDecision:
    """Result of routing a question to a tool."""

    suggested_tool: Optional[str] = None
    confidence: str = "low"          # "low" | "medium" | "high"
    scores: Dict[str, int] = field(default_factory=dict)
    reason: str = ""


def _score(text: str, terms: Dict[str, int]) -> int:
    return sum(weight for kw, weight in terms.items() if kw in text)


def route_query(question: str) -> RouteDecision:
    """Classify *question* and suggest the best first tool.

    Returns a :class:`RouteDecision`. ``suggested_tool`` is ``None`` when no
    signal is strong enough to bias the agent (it then decides freely).
    """
    q = (question or "").lower()

    sql = _score(q, _SQL_TERMS)
    vector = _score(q, _VECTOR_TERMS)
    graph = _score(q, _GRAPH_TERMS)
    web = _score(q, _WEB_TERMS)

    # A concrete Thai/CE year is a strong signal for tabular financial data.
    if _YEAR_RE.search(question or ""):
        sql += 2

    scores = {"sql_query": sql, "vector_search": vector,
              "graph_search": graph, "tavily_search": web}

    # Hybrid: strong signals for BOTH numbers and narrative -> multi_hop.
    if sql >= 4 and vector >= 4:
        return RouteDecision(
            suggested_tool="multi_hop",
            confidence="high",
            scores=scores,
            reason="both structured and qualitative signals present",
        )

    best_tool = max(scores, key=scores.get)
    best_score = scores[best_tool]

    if best_score == 0:
        return RouteDecision(suggested_tool=None, confidence="low",
                             scores=scores, reason="no strong keyword signal")

    # Confidence from margin over the runner-up.
    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - (ordered[1] if len(ordered) > 1 else 0)
    if best_score >= 5 and margin >= 3:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return RouteDecision(
        suggested_tool=best_tool,
        confidence=confidence,
        scores=scores,
        reason=f"top score {best_score} ({best_tool}), margin {margin}",
    )
