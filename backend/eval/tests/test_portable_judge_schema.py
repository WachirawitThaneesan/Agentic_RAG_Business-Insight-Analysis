import asyncio

import pytest
from google.genai import types

from scripts.evaluate_comprehensive import bind_judge_claim_indices, judge, judge_schema


def test_portable_dispatch_schema_keeps_exact_claim_validation():
    row = dict(captured_answer_claims=['claim']*13, compact_judge_payload=True,
               portable_judge_schema=True, evidence_blocks=[], actual_claim_citations=[])
    schema = judge_schema(row)
    assert 'maxItems' not in schema['properties']['answer_claims']
    types.Schema.model_validate(schema)
    with pytest.raises(ValueError, match='every captured claim'):
        bind_judge_claim_indices({'answer_claims': [{'claim_index': i} for i in range(12)]}, row)


def test_provider_error_is_retained_instead_of_becoming_empty_json_error(tmp_path, monkeypatch):
    from backend.services import llm

    class DispatchError(Exception):
        code = 400

    async def reject(*args, **kwargs):
        raise DispatchError('response_schema rejected before generation')

    monkeypatch.setattr(llm, '_generate_gemini', reject)
    row = dict(key='frozen', question='question', answer='answer', answerable=True,
               context='context', reference='reference', sources=[], evidence_blocks=[])
    result = asyncio.run(judge(row, tmp_path))
    assert result['judgment'] is None
    assert len(result['dispatch_errors']) == 2
    assert result['dispatch_errors'][0]['code'] == 400
    assert 'response_schema rejected' in result['last_validation_error']
    assert result['raw_outputs'] == ['', '']
