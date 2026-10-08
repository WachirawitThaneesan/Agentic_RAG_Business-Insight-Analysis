from copy import deepcopy

import pytest

from backend.eval.comprehensive import deterministic_answer
from backend.services import answer_capture as capture
from backend.eval.contract_replay import numeric_results
from backend.eval.tests.test_contract_replay import label
from backend.eval.numeric import numeric_match, quantity_match
from scripts.evaluate_comprehensive import judge_schema
from google.genai import types
from scripts.evaluate_comprehensive import bind_judge_claim_indices,judge_payload
from backend.eval.comprehensive import quote_span


@pytest.mark.parametrize('unit,value,measure,operator', [
    ('บาทต่อเดือนต่อคัน', '12000', 'วงเงินซื้อก๊าซ', 'eq'),
    ('เปอร์เซ็นต์แรก', '5', 'อันดับ ESG', 'lte'),
    ('ร้อยละ', '80.07', 'สัดส่วนงบประมาณโครงการ', 'eq'),
    ('ล้านบาท', '100', 'งบประมาณ', 'approx'),
])
def test_explicit_compound_units_and_budget_nouns_bind(unit, value, measure, operator):
    payload = {'abstained': False, 'refusal_reason': '', 'claims': [{
        'text': '', 'source_indices': [0], 'numeric': dict(company='PTT',
        measure=measure, value=value, unit=unit, year_be=2567, document='p.pdf',
        source_pdf_page=94, source_index=0, comparison_operator=operator)}]}
    rendered = capture.render_claims(payload)
    sources = [{'filename': 'p.pdf', 'page': 94, 'excerpt': rendered['answer']}]
    context, blocks = capture.evidence_context(sources, [])
    full = capture.finalize({'answer': rendered['answer'], 'sources': sources}, [{
        'draft': rendered['answer'], 'payload': rendered, 'context': context,
        'blocks': blocks, 'origin': 'model_generation', 'prompt_sha256': None}])
    assert full['answer_capture']['status'] == 'captured'
    assert len(full['numeric_facts']) == 1
    assert capture.validate_binding(full, rendered['answer'])
    wrong = deepcopy(rendered['numeric_facts'][0])
    if unit == 'บาทต่อเดือนต่อคัน':
        wrong['unit'] = 'บาท'
        assert 'numeric_value_unit_not_bound' in capture.numeric_binding_errors(
            wrong, rendered['answer'], sources[0], {(0, 0)})


def test_page_metric_uses_only_bound_emitted_links_and_rejects_tampering():
    answer = 'PTT วิสัยทัศน์'
    sources = [{'filename': 'p.pdf', 'document_id': 1, 'page': 94, 'excerpt': answer},
               {'filename': 'p.pdf', 'document_id': 1, 'page': 95, 'excerpt': 'other'}]
    context, blocks = capture.evidence_context(sources, [])
    payload = dict(answer=answer, abstained=False, answer_claims=[answer],
                   claim_citations=[dict(claim_index=0, source_index=0)], numeric_facts=[])
    full = capture.finalize(dict(answer=answer, sources=sources), [dict(
        draft=answer, payload=payload, context=context, blocks=blocks,
        origin='model_generation', prompt_sha256=None)])
    item = dict(id='Q1', question_th='PTT vision', document='PTT', source_pdf_page=94,
                reference_answer=answer, answerable=True)
    documents = {'PTT': dict(code='PTT', source_file='p.pdf')}
    result = deterministic_answer(item, dict(answer=answer, full_result=full), documents)
    assert result['page_citation_complete'] is True
    assert result['page_citation_precision'] == 1
    full['claim_citations'][0]['source_index'] = 1
    result = deterministic_answer(item, dict(answer=answer, full_result=full), documents)
    assert result['page_citation_complete'] is False
    assert result['page_citation_recall'] == 0


def test_completely_captured_omission_is_wrong_but_missing_capture_is_unknown():
    answer = 'PTT มีนโยบายด้านสิ่งแวดล้อม'
    sources = [dict(filename='p.pdf', page=10, excerpt=answer)]
    context, blocks = capture.evidence_context(sources, [])
    payload = dict(answer=answer, abstained=False, answer_claims=[answer],
                   claim_citations=[dict(claim_index=0, source_index=0)], numeric_facts=[])
    full = capture.finalize(dict(answer=answer, sources=sources), [dict(
        draft=answer, payload=payload, context=context, blocks=blocks,
        origin='model_generation', prompt_sha256=None)])
    scored = numeric_results([label()], full, answer, allow_provisional=True)
    assert scored[0]['correct'] is False
    assert scored[0]['state'] == 'required_relation_not_emitted'
    del full['answer_capture']
    assert numeric_results([label()], full, answer, allow_provisional=True)[0]['correct'] is None


def test_unstructured_group_count_stays_an_annotation_error():
    answer = 'PTT แบ่งผู้มีส่วนได้ส่วนเสียเป็น 6 กลุ่ม'
    sources = [dict(filename='p.pdf', page=10, excerpt=answer)]
    context, blocks = capture.evidence_context(sources, [])
    payload = dict(answer=answer, abstained=False, render_contract='canonical-claims-v1',
        answer_claims=[answer], claim_citations=[dict(claim_index=0, source_index=0)], numeric_facts=[])
    full = capture.finalize(dict(answer=answer, sources=sources), [dict(
        draft=answer, payload=payload, context=context, blocks=blocks,
        origin='model_generation', prompt_sha256=None)])
    assert 'unannotated_numeric_quantity' in full['answer_capture']['errors']
    assert numeric_results([label()], full, answer, allow_provisional=True)[0]['correct'] is None


def test_numeric_parser_preserves_per_vehicle_and_rank_percentage_qualifiers():
    assert numeric_match(12000, '12000 บาทต่อเดือนต่อคัน', expected_unit='บาทต่อเดือนต่อคัน')
    assert not numeric_match(12000, '12000 บาทต่อเดือน', expected_unit='บาทต่อเดือนต่อคัน')
    assert not numeric_match(12000, '12000 บาทต่อเดือนต่อคัน', expected_unit='บาทต่อเดือน')
    assert numeric_match(5, '5 เปอร์เซ็นต์แรก', expected_unit='เปอร์เซ็นต์แรก')
    assert not numeric_match(5, '5 เปอร์เซ็นต์', expected_unit='เปอร์เซ็นต์แรก')


def test_real_nonempty_judge_schema_validates_through_sdk_nested_schema():
    schema = judge_schema(dict(captured_answer_claims=['PTT วิสัยทัศน์'],
        evidence_blocks=[dict(context_index=0), dict(context_index=1)],
        actual_claim_citations=[dict(claim_index=0, source_index=2)]))
    types.Schema.model_validate(schema)
    assert schema['properties']['context_relevance']['minItems'] == 2
    assert schema['properties']['actual_citation_audit']['maxItems'] == 1


def test_sara_am_pdf_font_artifact_maps_to_original_without_dropping_unknown_letters_or_values():
    quote='ส่วนสำคัญของกำลังผลิต 30 ร้อยละ'
    original='ส่วนสำ�คัญของกำ�ลังผลิต 30 ร้อยละ'
    assert quote_span(quote,original)['original']==original
    assert quote_span(quote,original.replace('30','-30')) is None
    assert quote_span(quote,'ส่วนส�ำคัญของกำลังผลิต 30 ร้อยละ') is None


def test_indexed_judge_cannot_reorder_or_change_captured_claims():
    row={'captured_answer_claims':['first','second'],'compact_judge_payload':True}
    raw={'answer_claims':[{'claim_index':0},{'claim_index':1}]}
    assert [c['text'] for c in bind_judge_claim_indices(raw,row)['answer_claims']]==['first','second']
    for claims in ([{'claim_index':1},{'claim_index':0}], [{'claim_index':0},{'claim_index':0}],
                   [{'claim_index':0,'text':'invented'},{'claim_index':1}]):
        with pytest.raises(ValueError):bind_judge_claim_indices({'answer_claims':claims},row)


def test_compact_payload_keeps_context_and_original_cited_source_indices():
    row=dict(question='q',answer='a',answerable=True,context='exact original context',
        reference='reference',sources=[dict(excerpt='uncited'),dict(excerpt='cited')],
        evidence_blocks=[dict(context_index=0,source_index=1,start=0,end=22,text='exact original context')],
        captured_answer_claims=['a'],actual_claim_citations=[dict(claim_index=0,source_index=1)],compact_judge_payload=True)
    payload=judge_payload(row)
    assert payload['ACTUAL_CONTEXT']==row['context']
    assert payload['SOURCES']==[dict(index=1,text='cited')]
    types.Schema.model_validate(judge_schema(row))
    assert 'claim_index' in judge_schema(row)['properties']['answer_claims']['items']['required']


def test_equipment_ids_in_measure_do_not_replace_the_actual_quantity():
    payload=dict(abstained=False,refusal_reason='',claims=[dict(text='',source_indices=[0],
        numeric=dict(company='PTT',measure='ลดก๊าซเรือนกระจกในโรงแยกก๊าซ หน่วยที่ 5, 6',
            value='190000',unit='ตันคาร์บอนไดออกไซด์เทียบเท่าต่อปี',year_be=2567,
            document='p.pdf',source_pdf_page=84,source_index=0,comparison_operator='approx'))])
    rendered=capture.render_claims(payload)
    source=dict(filename='p.pdf',page=84,excerpt=rendered['answer'])
    assert capture.numeric_binding_errors(rendered['numeric_facts'][0],rendered['answer'],source,{(0,0)})==[]
    wrong=deepcopy(rendered['numeric_facts'][0]);wrong['value']='5'
    assert capture.numeric_binding_errors(wrong,rendered['answer'],source,{(0,0)})


def test_bound_unit_fields_do_not_lose_compound_dimensions_or_periods():
    unit='ตันคาร์บอนไดออกไซด์เทียบเท่าต่อปี'
    assert quantity_match(190000,'190000',expected_unit=unit,actual_unit=unit)
    assert not quantity_match(190000,'190000',expected_unit=unit,actual_unit='ตันคาร์บอนไดออกไซด์เทียบเท่า')
    assert not quantity_match(190000,'-190000',expected_unit=unit,actual_unit=unit)
    assert quantity_match(100,100000000,expected_unit='ล้านบาท',actual_unit='บาท')
    assert not quantity_match(100,100,expected_unit='ล้านบาท',actual_unit='ล้านดอลลาร์สหรัฐ')
