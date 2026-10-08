import asyncio
import json
from types import SimpleNamespace

import pytest
from google.genai import types

from backend.services import answer_capture as capture, llm


def test_schema_separates_requested_entity_from_issuer_and_measure():
    schema = types.Schema.model_validate(capture.SCHEMA)
    numeric = schema.properties['claims'].items.properties['numeric']
    assert 'entity' in numeric.required and 'company' not in numeric.properties
    assert 'subject owning' in numeric.properties['entity'].description
    assert numeric.properties['document'].description is None
    assert numeric.properties['unit'].description is None
    fact = dict(entity='โรงไฟฟ้าตัวอย่าง', measure='ความพร้อมในการเดินเครื่อง', value=98.5,
                unit='ร้อยละ', year_be=2567, document='issuer.pdf', source_pdf_page=10,
                source_index=0, comparison_operator='eq')
    raw = dict(abstained=False, refusal_reason='', claims=[dict(text='', source_indices=[0], numeric=fact)])
    answer, data = capture.decode(json.dumps(raw, ensure_ascii=False))
    assert answer.startswith('โรงไฟฟ้าตัวอย่าง')
    assert data['numeric_facts'][0]['company'] == fact['entity']
    fact['company'] = 'บริษัทเจ้าของรายงาน'
    assert capture.decode(json.dumps(raw))[1] is None


def test_answer_reasoning_override_does_not_change_default_dispatch(monkeypatch):
    configs = []

    async def response(**kwargs):
        configs.append(kwargs['config'])
        return SimpleNamespace(text='{}', usage_metadata=None)

    async def no_wait():
        return None

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=response)))
    throttle = SimpleNamespace(wait=no_wait, relax=lambda: None)
    monkeypatch.setattr(llm, '_get_genai_client', lambda: client)
    monkeypatch.setattr(llm, '_get_throttle', lambda: throttle)
    monkeypatch.setattr(llm.settings, 'GEMINI_THINKING_BUDGET', 0)
    asyncio.run(llm._generate_gemini('answer', 0, 4096, thinking_budget=1024))
    asyncio.run(llm._generate_gemini('planning', 0, 2000))
    assert configs[0].thinking_config.thinking_budget == 1024
    assert configs[0].thinking_config.include_thoughts is False
    assert configs[1].thinking_config.thinking_budget == 0
