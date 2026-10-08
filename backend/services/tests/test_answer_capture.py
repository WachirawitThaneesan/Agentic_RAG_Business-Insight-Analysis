import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

from backend.services import answer_capture as capture, agent


def fixture():
    answer = 'CPAXT สินทรัพย์ไม่มีตัวตน ปี 2567 เท่ากับ 10,831 ล้านบาท (PDF หน้า 133)'
    sources = [{'filename': 'cpaxt.pdf', 'document_id': 1, 'page': 133,
                'excerpt': answer}, {'filename': 'other.pdf', 'page': 5, 'excerpt': 'อื่น'}]
    context, blocks = capture.evidence_context(sources, [])
    fact = {'company': 'CPAXT', 'measure': 'สินทรัพย์ไม่มีตัวตน', 'year_be': 2567,
            'value': 10831, 'unit': 'ล้านบาท', 'document': 'cpaxt.pdf',
            'source_pdf_page': 133, 'comparison_operator': 'eq',
            'answer_quote': answer, 'claim_index': 0, 'source_index': 0}
    payload = {'answer': answer, 'answer_claims': [answer],
               'claim_citations': [{'claim_index': 0, 'source_index': 0}], 'numeric_facts': [fact]}
    event = {'draft': answer, 'payload': payload, 'context': context,
             'blocks': blocks, 'origin': 'model_generation', 'prompt_sha256': 'p'}
    return {'answer': answer, 'sources': sources}, event


def test_only_emitted_citation_is_captured_and_numeric_tuple_binds_answer():
    result, event = fixture()
    full = capture.finalize(result, [event])
    assert full['answer_capture']['status'] == 'captured'
    assert len(full['claim_citations']) == 1
    assert full['claim_citations'][0]['source_index'] == 0
    assert full['numeric_facts'][0]['year_be'] == 2567
    assert capture.validate_binding(full, result['answer'])
    full['numeric_facts'][0]['year_be'] = 2566
    assert not capture.validate_binding(full, result['answer'])
    assert 'source_id' not in result['sources'][0]


@pytest.mark.parametrize('field,value', [
    ('company', 'PTT'), ('measure', 'รายได้'), ('year_be', 2566), ('year_be', None),
    ('unit', 'บาท'), ('unit', 'พันบาท'), ('value', -10831), ('value', 10831000),
    ('source_pdf_page', 13), ('document', 'other.pdf'), ('comparison_operator', 'lte'),
    ('answer_quote', 'invented'), ('source_index', True)])
def test_wrong_numeric_binding_is_excluded(field, value):
    result, event = fixture()
    event['payload']['numeric_facts'][0][field] = value
    full = capture.finalize(result, [event])
    assert full['numeric_facts'] == []
    assert full['answer_capture']['errors']


def test_missing_fields_are_not_filled_from_evidence():
    result, event = fixture()
    del event['payload']['numeric_facts'][0]['company']
    full = capture.finalize(result, [event])
    assert full['numeric_facts'] == []
    assert 'numeric_company_not_in_answer' in full['answer_capture']['errors']


@pytest.mark.parametrize('answer', ['ไม่พบหลักฐานในหน้าเอกสารที่รองรับตัวเลขในคำตอบ', 'คำตอบใหม่', ''])
def test_guard_change_discards_draft_annotations(answer):
    result, event = fixture()
    result['answer'] = answer
    full = capture.finalize(result, [event])
    assert full['answer_capture']['status'] == 'discarded_after_answer_guard'
    assert full['answer_claims'] is full['numeric_facts'] is full['claim_citations'] is None


def test_known_guard_ocr_suffix_keeps_bound_annotations():
    result, event = fixture()
    result['answer'] += ' (ค่าถอดจาก OCR; ยังไม่ตรวจเทียบ PDF)'
    full = capture.finalize(result, [event])
    assert full['answer_capture']['claims_cover_answer'] is True


def test_citations_to_unseen_or_boolean_source_indices_rejected():
    result, event = fixture()
    event['blocks'] = event['blocks'][:1]
    event['payload']['claim_citations'] += [{'claim_index': 0, 'source_index': 1},
                                           {'claim_index': True, 'source_index': 0}]
    full = capture.finalize(result, [event])
    assert len(full['claim_citations']) == 1
    assert len(full['answer_capture']['errors']) == 2


def test_truncated_page_blocks_keep_exact_spans_and_no_tail_sources():
    sources = [{'filename': 'a.pdf', 'page': i, 'excerpt': str(i)*12000,
                'context_kind': 'page'} for i in range(1, 5)]
    context, blocks = capture.evidence_context(sources, [])
    assert len(context) == 16000
    assert [b['source_index'] for b in blocks] == [0, 1]
    assert all(context[b['start']:b['end']] == b['text'] for b in blocks)
    assert blocks[-1]['end'] == len(context)


def test_claims_not_in_answer_and_missing_claim_coverage_remain_errors():
    result, event = fixture()
    event['payload']['answer_claims'] = ['invented']
    assert capture.finalize(result, [event])['answer_claims'] is None
    result, event = fixture()
    event['payload']['answer_claims'] = ['CPAXT']
    full = capture.finalize(result, [event])
    assert full['answer_capture']['claims_cover_answer'] is False
    assert 'answer_has_unannotated_text' in full['answer_capture']['errors']


def test_public_agent_emits_structured_generation_and_restores_context(monkeypatch):
    result, event = fixture()
    async def inner(question, session):
        answer = await agent._answer_from_observations(question, ['observations'], result['sources'])
        return {'answer': answer, 'sources': result['sources']}
    monkeypatch.setattr(agent, '_agent_query', inner)
    model = AsyncMock(return_value=json.dumps(event['payload'], ensure_ascii=False))
    monkeypatch.setattr(agent, 'llm_generate', model)
    full = asyncio.run(agent.agent_query('สินทรัพย์ไม่มีตัวตนเท่าไร', object()))
    assert full['answer_capture']['status'] == 'captured'
    assert full['answer_claims'] == [result['answer']]
    assert model.call_count == 1
    assert capture.CURRENT.get() is None
    assert '[source_index=0]' in model.call_args.args[0]


def test_public_agent_replaces_rejected_draft_with_actual_guard_refusal(monkeypatch):
    result, event = fixture()
    event['payload']['answer'] = event['draft'].replace('10,831', '99,999')
    event['payload']['answer_claims'] = [event['payload']['answer']]
    async def inner(question, session):
        answer = await agent._answer_from_observations(question, ['observations'], result['sources'])
        return {'answer': answer, 'sources': result['sources']}
    monkeypatch.setattr(agent, '_agent_query', inner)
    monkeypatch.setattr(agent, 'llm_generate', AsyncMock(return_value=json.dumps(event['payload'], ensure_ascii=False)))
    full = asyncio.run(agent.agent_query('สินทรัพย์ไม่มีตัวตนเท่าไร', object()))
    assert full['answer_capture']['status'] == 'captured'
    assert full['answer_capture']['origin'] == 'application_guard_refusal'
    assert full['abstained'] is True
    assert full['claim_citations'] == full['numeric_facts'] == []
    assert '99,999' not in full['answer']


def test_context_restores_after_exception_and_concurrent_requests(monkeypatch):
    async def fail(question, session):
        raise RuntimeError('cancel')
    monkeypatch.setattr(agent, '_agent_query', fail)
    with pytest.raises(RuntimeError):
        asyncio.run(agent.agent_query('q', object()))
    assert capture.CURRENT.get() is None
    async def inner(question, session):
        await asyncio.sleep(0)
        capture.record_generation(question, None, '', [])
        return {'answer': question, 'sources': []}
    monkeypatch.setattr(agent, '_agent_query', inner)
    async def run():
        return await asyncio.gather(agent.agent_query('one', None), agent.agent_query('two', None))
    full = asyncio.run(run())
    assert [r['answer_capture']['draft_sha256'] for r in full] == [capture.digest('one'), capture.digest('two')]


def test_prefix_percentage_and_citation_bound_page_are_supported():
    result, event = fixture()
    answer = 'CPAXT สัดส่วนสินค้า ปี 2567 ประมาณร้อยละ 16.0'
    result['answer'] = event['draft'] = answer
    event['payload'].update(answer=answer, answer_claims=[answer])
    fact = event['payload']['numeric_facts'][0]
    fact.update(answer_quote=answer, measure='สัดส่วนสินค้า', value=16.0, unit='%', comparison_operator='approx')
    full = capture.finalize(result, [event])
    assert len(full['numeric_facts']) == 1
    assert full['numeric_facts'][0]['source_pdf_page'] == 133
    # The emitted claim citation is the page binding; no page is filled from gold.
    event['payload']['claim_citations'] = []
    assert capture.finalize(result, [event])['numeric_facts'] == []


def test_explicit_wrong_prose_page_does_not_pass_through_a_correct_link():
    result, event = fixture()
    answer = result['answer'].replace('หน้า 133', 'หน้า 13')
    result['answer'] = event['draft'] = answer
    event['payload'].update(answer=answer, answer_claims=[answer])
    event['payload']['numeric_facts'][0]['answer_quote'] = answer
    assert capture.finalize(result, [event])['numeric_facts'] == []


def test_machine_schema_requires_binding_fields_and_refusal_has_no_claims():
    from google.genai import types
    config = types.GenerateContentConfig(response_mime_type='application/json', response_schema=capture.SCHEMA)
    assert config.response_schema is not None
    required = capture.SCHEMA['properties']['claims']['items']['properties']['numeric']['required']
    assert {'source_index', 'entity', 'measure', 'year_be', 'value', 'unit', 'document', 'source_pdf_page'} <= set(required)
    result, event = fixture()
    event['payload']['abstained'] = True
    full = capture.finalize(result, [event])
    assert full['answer_claims'] is None
    assert 'abstention_has_factual_annotations' in full['answer_capture']['errors']


def canonical_fixture():
    result, event = fixture()
    fact = event['payload']['numeric_facts'][0]
    return result, event, {'render_contract': 'canonical-claims-v1', 'abstained': False,
        'refusal_reason': '', 'claims': [{'text': '', 'source_indices': [0],
            'numeric': {k:v for k,v in fact.items() if k not in ('answer_quote', 'claim_index')}}]}


def test_incomplete_canonical_json_is_not_shown_as_answer():
    answer, payload = capture.decode(json.dumps({'claims': [], 'refusal_reason': ''}))
    assert payload is None and '{' not in answer


def test_application_renderer_does_not_require_model_to_echo_constant():
    result, event, raw = canonical_fixture()
    del raw['render_contract']
    answer, payload = capture.decode(json.dumps(raw, ensure_ascii=False))
    result['answer'] = answer; event.update(draft=answer, payload=payload)
    full = capture.finalize(result, [event])
    assert full['answer_capture']['status'] == 'captured'
    assert full['answer_capture']['render_contract'] == 'canonical-claims-v1'
    assert str(full['numeric_facts'][0]['value']) == '10831'
    assert len(full['claim_citations']) == 1


def test_application_guard_records_actual_refusal_without_fact_or_link(monkeypatch):
    result, _ = fixture()
    result['answer'] = 'ไม่พบหลักฐานในหน้าเอกสารที่รองรับตัวเลขในคำตอบ'
    monkeypatch.setattr(agent, '_agent_query', AsyncMock(return_value=result))
    full = asyncio.run(agent.agent_query('test', None))
    assert full['answer_capture']['origin'] == 'application_guard_refusal'
    assert full['abstained'] is True
    assert full['answer_claims'] == full['claim_citations'] == full['numeric_facts'] == []
    assert full['answer_capture']['claims_cover_answer'] is True
    assert capture.validate_binding(full, full['answer'])


def test_canonical_numeric_render_binds_emitted_relation_without_quote_copy():
    result, event, raw = canonical_fixture()
    answer, payload = capture.decode(json.dumps(raw, ensure_ascii=False))
    result['answer'] = answer; event.update(draft=answer, payload=payload)
    full = capture.finalize(result, [event])
    assert full['answer_capture']['status'] == 'captured'
    assert full['answer_capture']['claims_cover_answer'] is True
    assert answer.startswith(full['numeric_facts'][0]['answer_quote'])
    assert capture.validate_binding(full, answer)
    assert full['numeric_facts'][0]['value'] == 10831
    assert capture.validate_binding(full, answer)


def test_canonical_render_cannot_silently_drop_conflicting_numeric_prose():
    _, _, raw = canonical_fixture()
    raw['claims'][0]['text'] = 'CPAXT รายได้ ปี 2566 เท่ากับ 999 บาท'
    _, payload = capture.decode(json.dumps(raw, ensure_ascii=False))
    assert payload is None


def test_canonical_render_does_not_create_unemitted_citations():
    result, event, raw = canonical_fixture()
    raw['claims'][0]['source_indices'] = []
    answer, payload = capture.decode(json.dumps(raw, ensure_ascii=False))
    result['answer'] = answer; event.update(draft=answer, payload=payload)
    full = capture.finalize(result, [event])
    assert full['claim_citations'] == [] and full['numeric_facts'] == []
    assert 'numeric_citation_not_declared' in full['answer_capture']['errors']


def test_canonical_wrong_source_page_is_still_rejected():
    result, event, raw = canonical_fixture()
    raw['claims'][0]['numeric']['source_pdf_page'] = 13
    answer, payload = capture.decode(json.dumps(raw, ensure_ascii=False))
    result['answer'] = answer; event.update(draft=answer, payload=payload)
    full = capture.finalize(result, [event])
    assert full['numeric_facts'] == []
    assert 'numeric_page_not_bound' in full['answer_capture']['errors']


def test_canonical_qualitative_duration_cannot_hide_missing_numeric_tuple():
    result,event,raw=canonical_fixture()
    raw['claims'][0].update(text='CPAXT กำหนดให้รายงานครั้งแรกภายใน 30 วัน',numeric=None)
    answer,payload=capture.decode(json.dumps(raw,ensure_ascii=False))
    result['answer']=answer;event.update(draft=answer,payload=payload)
    full=capture.finalize(result,[event])
    assert 'unannotated_numeric_quantity' in full['answer_capture']['errors']


def test_report_year_and_calendar_date_are_not_unannotated_amounts():
    result,event,raw=canonical_fixture()
    raw['claims'][0].update(text='CPAXT ประกาศนโยบายเมื่อวันที่ 31 ธันวาคม 2567',numeric=None)
    answer,payload=capture.decode(json.dumps(raw,ensure_ascii=False))
    result['answer']=answer;event.update(draft=answer,payload=payload)
    full=capture.finalize(result,[event])
    assert full['answer_capture']['errors']==[]


def test_expanded_context_keeps_later_source_verbatim_with_stable_index():
    sources=[{'filename':'first.pdf','page':1,'context_kind':'page','excerpt':'ต้นหน้า '+('ก'*11900)},
             {'filename':'second.pdf','page':2,'context_kind':'page','excerpt':'ต้นหน้า '+('ข'*9000)+' REQUIRED RELATION'}]
    before,_=capture.evidence_context(sources,[])
    expanded,blocks=capture.evidence_context(sources,[],max_chars=32000)
    assert 'REQUIRED RELATION' not in before and 'REQUIRED RELATION' in expanded
    assert blocks[-1]['source_index']==1 and len(expanded)<=32000
    assert capture.validate_evidence_blocks(expanded,blocks)==blocks


def test_exact_cell_capture_uses_selected_source_and_explicit_issuer_mention():
    data = {'lookup_kind': 'exact_measure', 'evidence': [
        {'filename': 'cpaxtra_2567_th.pdf', 'document_id': 2, 'page': 133,
         'row_label': 'สินทรัพย์รวม', 'column': '2567', 'value': '42,567', 'unit': 'ล้านบาท'},
        {'filename': 'other.pdf', 'document_id': 3, 'page': 140,
         'row_label': 'สินทรัพย์รวม', 'column': '2567', 'value': '99,999', 'unit': 'ล้านบาท'}]}
    events = []; token = capture.CURRENT.set(events)
    try:
        answer = agent._exact_cell_answer(data, 'CPAXT สินทรัพย์รวมปี 2567 เท่าไร')
    finally:
        capture.CURRENT.reset(token)
    full = capture.finalize({'answer': answer, 'sources': agent._extract_sources('sql_query', data)}, events)
    assert full['answer_capture']['origin'] == 'deterministic_exact_cell'
    assert full['numeric_facts'][0]['company'] == 'CPAXT'
    assert full['numeric_facts'][0]['value'] == '42567'
    assert len(full['claim_citations']) == 1
    assert full['claim_citations'][0]['source_index'] == 0


def test_source_block_identity_tampering_and_legacy_capture_binding():
    result, event = fixture()
    full = capture.finalize(result, [event])
    full['evidence_blocks'][0]['source_index'] = 1
    assert not capture.validate_binding(full, full['answer'])
    full = capture.finalize(result, [event])
    full['answer_capture']['version'] = 'application-answer-capture-v1'
    full['answer_capture']['annotations_sha256'] = capture.annotation_digest(full, 'application-answer-capture-v1')
    del full['answer_capture']['evidence_blocks_sha256']
    assert capture.validate_binding(full, full['answer'])


@pytest.mark.parametrize('description', [
    'CPAXT รายได้ ปี 2567 มี 10,831 ล้านบาท และกำไร 99 ล้านบาท (PDF หน้า 133)',
    'CPAXT รายได้ ปี 2567 มี 10,831 ล้านบาท และกำไร 10,831 ล้านบาท (PDF หน้า 133)',
    'CPAXT รายได้ ตามรายงานปี 2567 เกิดในปี 2566 มี 10,831 ล้านบาท (PDF หน้า 133)',
    'CPAXT รายได้ 10,831 ล้านบาท รวม 2567 ล้านบาท (PDF หน้า 133)'])
def test_cross_quantity_or_multiple_year_quote_is_unresolved(description):
    result, event = fixture()
    result['answer'] = event['draft'] = description
    event['payload']['answer_claims'] = [description]
    event['payload']['numeric_facts'][0].update(answer_quote=description, measure='รายได้')
    full = capture.finalize(result, [event])
    assert full['numeric_facts'] == []


@pytest.mark.parametrize('word,operator', [('ไม่เกิน', 'lte'), ('ไม่สูงกว่า', 'lte'),
                                          ('ไม่น้อยกว่า', 'gte'), ('ไม่ต่ำกว่า', 'gte'),
                                          ('น้อยกว่า', 'lt'), ('มากกว่า', 'gt'), ('ประมาณ', 'approx')])
def test_comparator_and_single_quantity_binding(word, operator):
    result, event = fixture()
    answer = f'CPAXT รายได้ ปี 2567 {word} 10,831 ล้านบาท (PDF หน้า 133)'
    result['answer'] = event['draft'] = answer
    event['payload']['answer_claims'] = [answer]
    event['payload']['numeric_facts'][0].update(answer_quote=answer, measure='รายได้', comparison_operator=operator)
    assert len(capture.finalize(result, [event])['numeric_facts']) == 1


def test_range_preserves_both_bounds_and_explicit_unit():
    result, event = fixture()
    answer = 'CPAXT รายได้ ปี 2567 ระหว่าง 10 ถึง 20 ล้านบาท (PDF หน้า 133)'
    result['answer'] = event['draft'] = answer
    event['payload']['answer_claims'] = [answer]
    event['payload']['numeric_facts'][0].update(answer_quote=answer, measure='รายได้', value=10,
        range_min=10, range_max=20, comparison_operator='range')
    assert len(capture.finalize(result, [event])['numeric_facts']) == 1
    event['payload']['numeric_facts'][0]['range_max'] = 30
    assert capture.finalize(result, [event])['numeric_facts'] == []


def test_calendar_day_does_not_become_a_second_answer_quantity():
    result, event = fixture()
    answer = 'ณ วันที่ 31 ธันวาคม ปี 2567 CPAXT สาขารวม 175 สาขา (PDF หน้า 133)'
    result['answer'] = event['draft'] = answer
    event['payload']['answer_claims'] = [answer]
    event['payload']['numeric_facts'][0].update(answer_quote=answer, measure='สาขารวม', value=175, unit='สาขา')
    assert len(capture.finalize(result, [event])['numeric_facts']) == 1
