import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import BackgroundTasks
from backend.routes import query
from backend.services import evaluation
from backend.services.answer_capture import finalize
from backend.services.tests.test_answer_capture import fixture


def test_query_route_logs_exact_prompt_blocks_and_actual_capture(monkeypatch):
    result, event = fixture()
    full = finalize(result, [event])
    monkeypatch.setattr(query, 'agent_query', AsyncMock(return_value=full))
    save = AsyncMock()
    monkeypatch.setattr(query, 'save_qa_log', save)
    background = BackgroundTasks()
    returned = asyncio.run(query.query_agent(query.QueryRequest(question='Q'), background, object()))
    asyncio.run(background())
    assert returned is full
    assert save.call_args.kwargs['full_result'] is full
    assert save.call_args.kwargs['contexts'] == [b['text'] for b in event['blocks']]
    assert save.call_args.kwargs['contexts'] != [s['excerpt'] for s in full['sources']]


def test_history_persists_annotations_without_gold_or_extra_inference(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, 'settings', SimpleNamespace(OFFLINE_MODE=True, PRIVATE_DATA_DIR=str(tmp_path)))
    result, event = fixture()
    full = finalize(result, [event])
    asyncio.run(evaluation.save_qa_log('Q', full['answer'], [b['text'] for b in event['blocks']], full_result=full))
    log = json.loads((tmp_path/'qa_history.json').read_text(encoding='utf-8'))
    assert log[0]['full_result'] == full
    assert log[0]['ground_truth'] == ''


def test_missing_capture_does_not_log_returned_sources_as_prompt_context():
    assert evaluation._contexts_from_agent_result({'sources': [{'text': 'RETURNED', 'sql': 'SELECT 1'}],
                                                 'reasoning_trace': [{'observation': 'TRUNCATED'}]}) == []
