"""Agent must use available data and refuse unsupported financial numbers."""

import asyncio
from unittest.mock import AsyncMock

import duckdb

from backend.services import agent, duckdb_warehouse, tools
from backend.services.query_router import RouteDecision


def test_be_calendar_conversion_does_not_authorize_converted_quantity():
    sources = [{'page': 90, 'excerpt': 'เป้าหมายปี 2030 เพิ่มสัดส่วนพลังงานหมุนเวียน 30%'}]
    correct = 'เป้าหมายปี 2573 เพิ่มสัดส่วนพลังงานหมุนเวียน 30% (PDF หน้า 90)'
    assert agent._grounded_answer(correct, 'เป้าหมายเท่าใด', sources) == correct
    wrong = 'เป้าหมายเพิ่มสัดส่วนพลังงานหมุนเวียน 2573% (PDF หน้า 90)'
    assert agent._grounded_answer(wrong, 'เป้าหมายเท่าใด', sources) == 'ไม่พบหลักฐานในหน้าเอกสารที่รองรับตัวเลขในคำตอบ'


def test_numeric_answer_requires_same_signed_value_and_page():
    sources = [{"page": 244, "value": "(100)", "column": "2567",
                "row_label": "หนี้สินรวม", "unit": "พันบาท"}]
    question = "หนี้สินรวมปี 2567 เท่าไร"
    assert agent._grounded_answer("(100) พันบาท", question, sources) == "(100) พันบาท"
    assert "ไม่พบหลักฐาน" in agent._grounded_answer("100 พันบาท", question, sources)
    assert "ไม่พบหลักฐาน" in agent._grounded_answer("100,000 พันบาท", question, sources)
    assert "หน่วย" in agent._grounded_answer("(100) ล้านบาท", question, sources)
    assert "ไม่พบหลักฐาน" in agent._grounded_answer("(100) พันบาท", question,
                                                       [{**sources[0], "page": None}])


def test_derived_difference_requires_same_financial_measure():
    cells = [
        {"page": 46, "document_id": 1, "table_name": "income", "row_label": "กำไรสุทธิ",
         "column": "2567", "value": "120", "unit": "ล้านบาท"},
        {"page": 46, "document_id": 1, "table_name": "income", "row_label": "กำไรสุทธิ",
         "column": "2566", "value": "100", "unit": "ล้านบาท"},
    ]
    question = "กำไรสุทธิเปลี่ยนจากปี 2566 เป็น 2567 เท่าไร"
    assert agent._grounded_answer("เพิ่มขึ้น 20 ล้านบาท", question, cells) == "เพิ่มขึ้น 20 ล้านบาท"
    cells[1]["row_label"] = "กำไรขั้นต้น"
    assert "ไม่พบหลักฐาน" in agent._grounded_answer("เพิ่มขึ้น 20 ล้านบาท", question, cells)


def test_exact_sql_measure_blocks_nearby_wrong_row_value():
    sources = [
        {"type": "sql", "page": 46, "row_label": "หนี้สินรวม", "column": "2567",
         "value": "100", "unit": "พันบาท"},
        {"type": "sql", "page": 46, "row_label": "หนี้สินตามสัญญาเช่า", "column": "2567",
         "value": "200", "unit": "พันบาท"},
    ]
    question = "หนี้สินรวมปี 2567 เท่าไร"
    assert "ไม่พบหลักฐาน" in agent._grounded_answer("200 พันบาท", question, sources)
    assert agent._grounded_answer("100 พันบาท", question, sources) == "100 พันบาท"


def test_sql_tool_skips_llm_when_warehouse_has_no_cells(monkeypatch):
    conn = duckdb.connect(":memory:")
    duckdb_warehouse._init_schema(conn)
    monkeypatch.setattr(duckdb_warehouse, "_get_conn", lambda: conn)
    llm = AsyncMock(side_effect=AssertionError("LLM should not be called"))
    monkeypatch.setattr(tools, "llm_generate", llm)
    result = asyncio.run(tools.SQLTool().execute("สินทรัพย์รวมปี 2567"))
    assert not result.success
    assert "No structured table cells" in result.error
    assert not llm.called
    assert not duckdb_warehouse.warehouse_capabilities()["wide_view"]
    conn.close()


def test_agent_prompt_only_offers_populated_tools():
    prompt = agent._prompt_with_available_tools({"vector_search"})
    assert "- vector_search:" in prompt
    assert "- sql_query:" not in prompt
    assert "ให้ใช้ sql_query" not in prompt
    assert "- graph_search:" not in prompt


def test_unresolved_sql_source_does_not_generate_an_answer(monkeypatch):
    model = AsyncMock(side_effect=AssertionError("No evidence, no answer model call"))
    monkeypatch.setattr(agent, "llm_generate", model)
    answer = asyncio.run(agent._answer_from_observations(
        "กำไรเท่าไร", ["SQL returned 1 row"],
        [{"type": "sql", "page": None, "row_count": 1}]))
    assert "ไม่พบหลักฐาน" in answer
    assert not model.called


def test_multi_hop_limits_distinct_subqueries(monkeypatch):
    tool = tools.MultiHopTool()
    monkeypatch.setattr(tool, "_decompose", AsyncMock(return_value=[
        {"question": "กำไรปี 2567", "tool": "sql_query"},
        {"question": "กำไรปี 2567", "tool": "sql_query"},
        {"question": "นโยบายสิ่งแวดล้อม", "tool": "vector_search"},
        {"question": "อีกเรื่อง", "tool": "vector_search"},
    ]))
    sql = AsyncMock(return_value=tools.ToolResult(tool_name="sql_query", summary="SQL"))
    vector = AsyncMock(return_value=tools.ToolResult(tool_name="vector_search", summary="text"))
    monkeypatch.setattr(tool._sql_tool, "execute", sql)
    monkeypatch.setattr(tool._vector_tool, "execute", vector)
    result = asyncio.run(tool.execute("คำถามผสม", session=object()))
    assert len(result.data["sub_results"]) == 2
    assert sql.call_count == vector.call_count == 1


def test_sql_generation_rejects_missing_pivot_view(monkeypatch):
    conn = duckdb.connect(":memory:")
    duckdb_warehouse._init_schema(conn)
    monkeypatch.setattr(duckdb_warehouse, "_get_conn", lambda: conn)
    monkeypatch.setattr(tools, "llm_generate", AsyncMock(
        return_value="SELECT * FROM v_table_rows_wide"))
    sql = asyncio.run(tools.SQLTool()._generate_sql("ถือหุ้นเท่าไร", "schema"))
    assert sql == ""
    conn.close()


def test_forced_tool_answers_with_one_generation_and_no_repeated_search(monkeypatch):
    monkeypatch.setattr(agent.settings, "OFFLINE_MODE", False)
    monkeypatch.setattr(agent, "route_query", lambda _: RouteDecision(
        suggested_tool="vector_search", confidence="high", scores={}))
    monkeypatch.setattr(agent, "_available_tools", AsyncMock(return_value={"vector_search"}))
    search = AsyncMock(return_value={
        "success": True, "observation": "รายงาน PDF page 18: รถขนส่ง 2,800 คัน",
        "data": {"chunks": [{"page": 18, "document_id": 1, "filename": "thai.pdf",
                             "text": "รถขนส่ง 2,800 คัน"}]},
    })
    monkeypatch.setattr(agent, "_execute_tool", search)
    import json
    answer = 'มีรถขนส่ง 2,800 คัน (PDF หน้า 18)'
    generate = AsyncMock(return_value=json.dumps({'answer': answer, 'abstained': False,
        'answer_claims': [answer], 'claim_citations': [{'claim_index': 0, 'source_index': 0}],
        'numeric_facts': []}, ensure_ascii=False))
    monkeypatch.setattr(agent, "llm_generate", generate)
    result = asyncio.run(agent.agent_query("มีรถขนส่งกี่คัน", object()))
    assert "2,800" in result["answer"]
    assert search.call_count == 1
    assert generate.call_count == 1


def test_sql_answer_uses_exact_cell_with_two_mocked_model_calls(monkeypatch):
    conn = duckdb.connect(":memory:")
    duckdb_warehouse._init_schema(conn)
    monkeypatch.setattr(duckdb_warehouse, "_get_conn", lambda: conn)
    duckdb_warehouse.load_document_dim(12, "egco.pdf")
    duckdb_warehouse.load_table_into_warehouse(
        12, "p244_liabilities", ["รายการ", "2567"],
        [["หนี้สินรวม", "136,422,456"]], source_page=244,
        unit="พันบาท", source_provider="gemini")
    monkeypatch.setattr(agent.settings, "OFFLINE_MODE", False)
    monkeypatch.setattr(agent, "route_query", lambda _: RouteDecision(
        suggested_tool="sql_query", confidence="high", scores={}))
    monkeypatch.setattr(agent, "_available_tools", AsyncMock(return_value={"sql_query"}))
    sql_model = AsyncMock(return_value=(
        "SELECT document_id, table_name, row_label, metric_year, raw_value, unit "
        "FROM fact_financial_metrics WHERE row_label = 'หนี้สินรวม' AND metric_year = '2567'"))
    import json
    answer = 'หนี้สินรวมปี 2567 คือ 136,422,456 พันบาท (PDF หน้า 244)'
    answer_model = AsyncMock(return_value=json.dumps({'answer': answer, 'abstained': False,
        'answer_claims': [answer], 'claim_citations': [{'claim_index': 0, 'source_index': 0}],
        'numeric_facts': []}, ensure_ascii=False))
    monkeypatch.setattr(tools, "llm_generate", sql_model)
    monkeypatch.setattr(agent, "llm_generate", answer_model)
    result = asyncio.run(agent.agent_query("หนี้สินรวมปี 2567 เท่าไร", object()))
    assert "136,422,456" in result["answer"]
    assert result["sources"][0]["page"] == 244
    assert result["sources"][0]["row_label"] == "หนี้สินรวม"
    assert sql_model.call_count == 1
    assert answer_model.call_count == 1
    conn.close()
