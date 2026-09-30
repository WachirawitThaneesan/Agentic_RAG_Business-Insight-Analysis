"""Regression cases for the selectively ported eval-accuracy-bge-m3 fixes."""
import asyncio
from unittest.mock import AsyncMock

from backend.services import agent, rag, tools
from backend.services.answer_verifier import _focus_violation
from backend.services.query_router import RouteDecision


def test_excerpt_keeps_late_answer_despite_early_repeated_terms():
    phrase = "เป้าหมายการลดการปล่อยคาร์บอน"
    text = "รายงานคาร์บอน " * 75 + "x" * 1800 + phrase + " เท่ากับ 60% " + "y" * 900
    excerpt = tools._focus_excerpt(text, ["คาร์บอน", "ลด", "เป้าหมาย"], 700,
                                   head=100, question=phrase + "เท่าไร")
    assert phrase in excerpt and "60%" in excerpt
    assert "รายงาน" in excerpt


def test_focus_does_not_change_comparison_or_equivalent_years():
    assert _focus_violation("เป้าหมายคิดเป็นร้อยละเท่าไร", "60% และ Gartner คาดว่า 70%")
    assert not _focus_violation("เปรียบเทียบสัดส่วนสองบริษัท", "60% และ 70%")
    assert not _focus_violation("เปิดเมื่อปีใด", "เปิดปี 2567 (ค.ศ. 2024)")
    assert not _focus_violation("ลดจากร้อยละเท่าไรเป็นเท่าไร", "จาก 70% เป็น 60%")
    assert _focus_violation("มีรถกี่คัน", "2,800 คัน และ 3,800 คัน")
    assert _focus_violation("คิดเป็นร้อยละเท่าไร", "-60% หรือ 60%")
    assert _focus_violation("เป้าหมายลดคาร์บอนคิดเป็นร้อยละเท่าไร", "60% และ 70%")


def test_refusal_detector_does_not_treat_negative_fact_as_missing_data():
    assert agent._is_non_answer("ไม่พบข้อมูลในตาราง")
    assert not agent._is_non_answer("ไม่พบการทุจริตตามรายงาน")


def setup_agent(monkeypatch, available):
    monkeypatch.setattr(agent.settings, "OFFLINE_MODE", False)
    monkeypatch.setattr(rag, "try_direct_structured_answer", AsyncMock(return_value=None))
    monkeypatch.setattr(agent, "route_query", lambda _: RouteDecision(
        suggested_tool="sql_query", confidence="high", scores={}))
    monkeypatch.setattr(agent, "_available_tools", AsyncMock(return_value=available))


def test_near_miss_sql_refusal_sweeps_once_and_preserves_citation(monkeypatch):
    setup_agent(monkeypatch, {"sql_query", "vector_search"})
    search = AsyncMock(side_effect=[
        {"success": True, "observation": "ตารางรายการอื่น", "data": {"evidence": [
            {"page": 3, "row_label": "อื่น", "value": "50"}]}},
        {"success": True, "observation": "เป้าหมายลดคาร์บอน 60% PDF หน้า 9", "data": {
            "chunks": [{"page": 9, "text": "เป้าหมายลดคาร์บอน 60%", "document_id": 1}]}},
    ])
    monkeypatch.setattr(agent, "_execute_tool", search)
    generate = AsyncMock(side_effect=["ไม่พบข้อมูลในตาราง", "เป้าหมายลดคาร์บอน 60% (PDF หน้า 9)"])
    monkeypatch.setattr(agent, "llm_generate", generate)
    result = asyncio.run(agent.agent_query("เป้าหมายลดคาร์บอนคิดเป็นร้อยละเท่าไร", object()))
    assert "60%" in result["answer"]
    assert search.call_count == generate.call_count == 2
    assert search.call_args_list[-1].args[0] == "vector_search"
    assert result["sources"][-1]["page"] == 9


def test_unavailable_vector_is_never_offered_as_last_resort(monkeypatch):
    setup_agent(monkeypatch, {"sql_query"})
    search = AsyncMock(return_value={"success": True, "observation": "รายการอื่น", "data": {
        "evidence": [{"page": 3, "value": "50"}]}})
    monkeypatch.setattr(agent, "_execute_tool", search)
    monkeypatch.setattr(agent, "llm_generate", AsyncMock(return_value="ไม่พบข้อมูล"))
    result = asyncio.run(agent.agent_query("เป้าหมายเท่าไร", object()))
    assert "ไม่พบ" in result["answer"] and search.call_count == 1


def test_focus_retry_is_bounded_and_cannot_return_ambiguous_answer(monkeypatch):
    generate = AsyncMock(return_value="60% และ 70%")
    monkeypatch.setattr(agent, "llm_generate", generate)
    answer = asyncio.run(agent._answer_from_observations(
        "เป้าหมายคิดเป็นร้อยละเท่าไร", ["60% และ 70%"],
        [{"page": 9, "excerpt": "60% และ 70%"}]))
    assert generate.call_count == 2
    assert "หลักฐาน" in answer and "60%" not in answer
