import asyncio
import json
from unittest.mock import AsyncMock

from backend.services import agent, rag
from backend.services.query_router import RouteDecision


def test_unforced_real_tool_result_uses_native_schema_and_ignores_planner_observation(monkeypatch):
    monkeypatch.setattr(rag, 'try_direct_structured_answer', AsyncMock(return_value=None))
    monkeypatch.setattr(agent, 'route_query', lambda _:RouteDecision('vector_search','low',{}))
    monkeypatch.setattr(agent, '_available_tools', AsyncMock(return_value={'vector_search','sql_query'}))
    planner=AsyncMock(return_value='Thought: plan\nAction: {"tool":"vector_search","query":"actual query"}\nObservation: invented 999 ล้านบาท\nFinal Answer: {"claims":[]}')
    monkeypatch.setattr(agent,'_call_llm',planner)
    tools=AsyncMock(return_value={'success':True,'observation':'ACTUAL SOURCE qualitative fact',
        'data':{'chunks':[{'filename':'actual.pdf','document_id':1,'page':7,'text':'ACTUAL SOURCE qualitative fact'}]}})
    monkeypatch.setattr(agent,'_execute_tool',tools)
    generated=AsyncMock(return_value=json.dumps({'abstained':False,'refusal_reason':'','claims':[
        {'text':'ACTUAL SOURCE qualitative fact','source_indices':[0],'numeric':None}]}))
    monkeypatch.setattr(agent,'llm_generate',generated)
    result=asyncio.run(agent.agent_query('อธิบายข้อเท็จจริง',object()))
    assert result['answer']=='ACTUAL SOURCE qualitative fact'
    assert result['answer_capture']['status']=='captured'
    assert tools.call_count==planner.call_count==generated.call_count==1
    assert generated.call_args.kwargs['response_mime_type']=='application/json'
    assert 'invented 999' not in generated.call_args.args[0]
    assert 'ACTUAL SOURCE' in result['evidence_context']


def test_full_usd_abbreviation_is_bound_without_losing_currency_or_scale():
    from backend.services.answer_capture import _value_unit_in_quote, Decimal
    assert _value_unit_in_quote(Decimal('1.15'),'ล้านดอลลาร์ สรอ.','1.15 ล้านดอลลาร์ สรอ.')
    assert not _value_unit_in_quote(Decimal('1.15'),'ดอลลาร์ สรอ.','1.15 ล้านดอลลาร์ สรอ.')
    assert not _value_unit_in_quote(Decimal('1.15'),'ล้านดอลลาร์','1.15 ล้านดอลลาร์ สรอ.')
