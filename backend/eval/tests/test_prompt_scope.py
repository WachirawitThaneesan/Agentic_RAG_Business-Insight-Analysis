from copy import deepcopy
import pytest

from backend.eval.comprehensive import validate_judgment
from scripts.evaluate_comprehensive import contexts, prompt_blocks, judge_payload
from backend.services.answer_capture import evidence_context, finalize


def judgment():
    return {'answer_claims': [], 'reference_claims': [],
            'context_relevance': [{'context_index': 0, 'useful': True, 'quote': 'VISIBLE'}],
            'relevancy': {'score': 0}}


def test_context_denominator_is_prompt_blocks_not_returned_registry():
    sources = [{'excerpt': 'NOT SENT'}, {'excerpt': 'VISIBLE'}, {'excerpt': 'OTHER'}]
    blocks = [{'context_index': 0, 'source_index': 1, 'text': 'VISIBLE'}]
    result = validate_judgment(judgment(), context='VISIBLE', sources=sources,
                               reference='', evidence_blocks=blocks)
    assert len(result['context_relevance']) == 1
    assert result['context_relevance'][0]['useful'] is True


def test_quote_in_returned_source_but_not_exact_prompt_block_cannot_support_usefulness():
    j = judgment(); j['context_relevance'][0]['quote'] = 'NOT SENT'
    result = validate_judgment(j, context='VISIBLE', sources=[{'excerpt': 'NOT SENT'}],
                               reference='', evidence_blocks=[{'text': 'VISIBLE'}])
    assert result['context_relevance'][0]['useful'] is False


def test_all_and_only_prompt_blocks_must_be_judged():
    with pytest.raises(ValueError, match='all supplied contexts'):
        validate_judgment(judgment(), context='VISIBLE', sources=[], reference='',
                          evidence_blocks=[{'text': 'VISIBLE'}, {'text': 'SECOND'}])
    j = judgment(); j['context_relevance'][0]['context_index'] = 1
    with pytest.raises(ValueError, match='context_index'):
        validate_judgment(j, context='VISIBLE', sources=[{}, {}], reference='',
                          evidence_blocks=[{'text': 'VISIBLE'}])


def test_historical_exact_blocks_preserve_prompt_tail_and_never_expand_from_sources():
    text = '[a.pdf PDF page 1]\nVISIBLE\n\n[a.pdf PDF page 2]\nTRUNCATED'
    record = {'full_result': {'sources': [{'excerpt': 'FULL PAGE DIFFERENT'}]}}
    trace = [{'id': 'Q', 'arm': 'app', 'prompt': 'หลักฐาน:\n'+text+'\n\nคำตอบ:'}]
    context, sources, provenance = contexts(record, trace, 'Q', 'app')
    blocks = prompt_blocks(context)
    assert [b['text'] for b in blocks] == ['[a.pdf PDF page 1]\nVISIBLE', '[a.pdf PDF page 2]\nTRUNCATED']
    assert provenance == 'captured_generation_prompt'
    assert sources == record['full_result']['sources']
    assert all('DIFFERENT' not in b['text'] for b in blocks)


def test_returned_sources_without_capture_are_context_unavailable():
    context, sources, provenance = contexts({'full_result': {'sources': [{'excerpt': 'X'}]}}, [], 'Q', 'app')
    assert context == '' and sources and provenance == 'context_unavailable'


def test_application_spans_and_hashes_are_validated():
    sources = [{'filename': 'a.pdf', 'page': 1, 'excerpt': 'VISIBLE'}]
    context, blocks = evidence_context(sources, [])
    event = {'draft': 'A', 'payload': {'answer_claims': ['A'], 'claim_citations': [], 'numeric_facts': []},
             'context': context, 'blocks': blocks, 'origin': 'model_generation', 'prompt_sha256': None}
    full = finalize({'answer': 'A', 'sources': sources}, [event])
    assert contexts({'answer': 'A', 'full_result': full}, [], 'Q', 'app')[0] == context
    assert prompt_blocks(context, full) == blocks
    full['evidence_blocks'][0]['end'] -= 1
    with pytest.raises(ValueError, match='evidence block span'):
        prompt_blocks(context, full)
    full['evidence_context'] += 'changed'
    with pytest.raises(ValueError, match='binding mismatch'):
        contexts({'answer': 'A', 'full_result': full}, [], 'Q', 'app')


def test_judge_cannot_invent_a_different_decomposition_for_actual_app_citations():
    j = judgment(); j['answer_claims'] = []
    with pytest.raises(ValueError, match='claim identities'):
        validate_judgment(j, context='VISIBLE', sources=[], reference='', evidence_blocks=[{'text': 'VISIBLE'}],
                          captured_claims=['Actual app claim'])


def test_refusal_phrase_and_company_no_data_fact_are_distinct():
    from backend.eval.comprehensive import is_abstention
    assert is_abstention('หลักฐานที่ให้มาไม่มีข้อมูลเกี่ยวกับ SROI ปี 2567')
    assert not is_abstention('บริษัทไม่มีข้อมูลการละเมิดสิทธิมนุษยชนในปี 2567')
