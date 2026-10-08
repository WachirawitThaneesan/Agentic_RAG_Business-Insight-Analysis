import copy
import math
import pytest
from backend.eval.comprehensive import (page_metrics, deterministic_answer,
    claim_metrics, validate_judgment, wilson, aggregate, is_abstention,quote_span)

DOCS = {'D': {'source_file': 'original.pdf', 'excerpt_file': 'original.pdf'}}
ITEM = {'id': 'Q', 'document': 'D', 'source_pdf_page': 10,
        'question_th': 'รายได้ปี 2567 เท่าไร?', 'reference_answer': '100 ล้านบาท',
        'answer_components': {'value': '100', 'unit': 'ล้านบาท', 'year_be': 2567}}
def hit(p):
    return {'filename': 'original.pdf', 'source_pdf_page': p}

def test_rank_math_and_duplicates():
    result = page_metrics(ITEM, [hit(1), hit(10), hit(10)], DOCS, k=5)
    assert result['precision'] == .2
    assert result['recall'] == 1
    assert result['mrr'] == .5
    assert result['map'] == .5
    assert result['ndcg'] == pytest.approx(1/math.log2(3))
    assert result['duplicate_slots'] == 1

def test_multi_page_hit_is_not_recall():
    item = {**ITEM, 'required_evidence': [
        {'document': 'D', 'source_pdf_page': p} for p in (10, 11)]}
    result = page_metrics(item, [hit(10)], DOCS)
    assert result['hit'] == 1 and result['recall'] == .5
    assert result['complete_evidence'] == 0

def test_valid_alternate_and_depth():
    item = {**ITEM, 'evidence_options': [[{'document': 'D', 'source_pdf_page': p}]
                                      for p in (10, 11)]}
    result = page_metrics(item, [hit(11)], DOCS)
    assert result['recall'] == 1
    assert result['map'] == .5  # union qrels denominator
    assert page_metrics(item, [], DOCS, k=10, depth=5)['status'] == 'not_measured'

def test_missing_hits_are_measured_zero():
    assert page_metrics(ITEM, [], DOCS)['recall'] == 0


def test_prose_requiring_review_has_no_deterministic_accuracy():
    item={**ITEM,'answer_components':{},'reference_answer':'ใช้พลังงานหมุนเวียน'}
    row=deterministic_answer(item,{'answer':'บริษัทเลือกเพิ่มการใช้พลังงานสะอาด','citations':[hit(10)]},DOCS)
    assert row['fact_status']=='needs_review' and row['strict_correct'] is None


def test_unavailable_financial_scope_allows_calendar_explanation():
    row=deterministic_answer({**ITEM,'answerable':False},{'answer':'ไม่พบข้อมูลปี 2566 มีเพียงรายงานปี 2567'},DOCS)
    assert row['expected_abstention_correct']


def test_unavailable_financial_scope_cannot_pass_by_refusing_then_giving_value():
    row=deterministic_answer({**ITEM,'answerable':False},{'answer':'ไม่พบข้อมูลปี 2566 แต่ปี 2567 มีกำไร 100 ล้านบาท'},DOCS)
    assert row['abstained'] and not row['expected_abstention_correct']

def test_multiple_required_quantities_cannot_pass_with_one_only():
    item={**ITEM,'answer_components':{'multiple_quantities':[
        {'value':'100','unit':'ล้านบาท','year_be':2567},
        {'value':'20','unit':'%','year_be':2567}]}}
    assert deterministic_answer(item,{'answer':'ปี 2567 100 ล้านบาท และ 20%','citations':[hit(10)]},DOCS)['fact_status']=='correct'
    assert deterministic_answer(item,{'answer':'ปี 2567 100 ล้านบาท','citations':[hit(10)]},DOCS)['fact_status']=='incorrect'

def test_prose_citation_mismatch_fails_despite_source_membership():
    row = deterministic_answer(ITEM, {'answer': 'ปี 2567 100 ล้านบาท (PDF หน้า 11)',
                                      'citations': [hit(10)]}, DOCS)
    assert row['fact_status'] == 'correct'
    assert row['page_citation_complete']
    assert not row['strict_correct']

@pytest.mark.parametrize('suffix',['หน้า PDF: 10','หน้า: 10','PDF p.10',''])
def test_valid_page_formats_and_ui_sources(suffix):
    row = deterministic_answer(ITEM, {'answer':'ปี 2567 100 ล้านบาท '+suffix,
                                      'citations':[hit(10)]},DOCS)
    assert row['strict_correct']

@pytest.mark.parametrize('answer', ['ปี 2567 -100 ล้านบาท (PDF หน้า 10)',
    'ปี 2566 100 ล้านบาท (PDF หน้า 10)', 'ปี 2567 100 บาท (PDF หน้า 10)',
    'ปี 2567 100000 ล้านบาท (PDF หน้า 10)'])
def test_strict_wrong_numeric_context(answer):
    assert not deterministic_answer(ITEM, {'answer': answer, 'citations': [hit(10)]}, DOCS)['strict_correct']

def sample():
    return {'answer_claims': [{'text': 'รายได้ 100 ล้านบาท', 'faithfulness': 'supported',
        'context_quote': 'รายได้ 100 ล้านบาท', 'factual': 'supported',
        'reference_quote': 'รายได้ 100 ล้านบาท', 'relevant': True,
        'citations': [{'source_index': 0, 'quote': 'รายได้ 100 ล้านบาท'}]}],
        'reference_claims': [{'text': 'รายได้ 100 ล้านบาท', 'answer_covered': True,
            'context_covered': True, 'context_quote': 'รายได้ 100 ล้านบาท'}],
        'context_relevance': [{'context_index': 0, 'useful': True, 'quote': 'รายได้ 100 ล้านบาท'}],
        'relevancy': {'score': 2, 'reason': 'direct'}}


def test_quote_from_context_does_not_cite_a_contradicted_claim():
    data=sample();data['answer_claims'][0]['faithfulness']='contradicted'
    result=validate_judgment(data,context='รายได้ 100 ล้านบาท',reference='รายได้ 100 ล้านบาท',sources=[{'excerpt':'รายได้ 100 ล้านบาท'}])
    assert not result['answer_claims'][0]['citations']
    assert claim_metrics(result)['citation_claim_recall']==0

def test_claim_scores_and_empty_are_not_perfect():
    j = validate_judgment(sample(), context='รายได้ 100 ล้านบาท',
        sources=[{'excerpt': 'รายได้ 100 ล้านบาท'}], reference='รายได้ 100 ล้านบาท')
    assert claim_metrics(j)['faithfulness'] == 1
    j['answer_claims'] = []
    assert claim_metrics(j)['faithfulness'] is None
    assert claim_metrics(j)['citation_claim_recall'] is None

def test_fabricated_quote_rejected():
    j = validate_judgment(sample(), context='ไม่มีตัวเลข',
        sources=[{'excerpt': 'ไม่มีตัวเลข'}], reference='ไม่มีตัวเลข')
    scores = claim_metrics(j)
    assert scores['faithfulness'] == 0
    assert scores['factual_precision'] == 0
    assert scores['citation_claim_recall'] == 0

def test_quote_normalization_keeps_original_and_never_changes_quantity():
    raw='รายได้้ ปี 2567\n100 ล้าน บาท'
    span=quote_span('รายได้ ปี 2567 100 ล้านบาท',raw)
    assert span and span['original']==raw
    assert span['matching']=='mapped_font_whitespace_normalization'
    assert quote_span('รายได้ ปี 2567 -100 ล้านบาท',raw) is None
    assert quote_span('รายได้ ปี 2567 100000 ล้านบาท',raw) is None

def test_incomplete_context_judgment_rejected():
    j = sample(); j['context_relevance'] = []
    with pytest.raises(ValueError):
        validate_judgment(j, context='', sources=[{'excerpt': 'x'}], reference='')


@pytest.mark.parametrize('replacement',[{'text_content':'missing required key'}, {'text':''}])
def test_reference_claim_requires_nonempty_text_before_it_can_be_scored(replacement):
    j=sample();j['reference_claims'][0].pop('text');j['reference_claims'][0].update(replacement)
    with pytest.raises(ValueError,match='reference claim'):
        validate_judgment(j,context='รายได้ 100 ล้านบาท',reference='รายได้ 100 ล้านบาท',sources=[{'excerpt':'รายได้ 100 ล้านบาท'}])

def test_abstention_and_null_denominators():
    assert is_abstention('ไม่พบหลักฐานเพียงพอ')
    assert not is_abstention('100 ล้านบาท')
    assert deterministic_answer({'answerable': False}, {'answer': ''}, DOCS)['strict_correct'] is False
    assert aggregate([{'x': None}, {'x': .5}])['x'] == {'mean': .5, 'n_measured': 1, 'n_total': 2}
    assert wilson(0, 0) is None
    assert wilson(10, 10)[1] == pytest.approx(1)


def test_narrative_reference_includes_required_continuation_page(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    import fitz
    from scripts.evaluate_comprehensive import reference_text
    class PDF:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def __getitem__(self, i):
            return SimpleNamespace(get_text=lambda: ['เริ่มประโยค ผู้', 'รับเหมา และผู้ให้บริการ'][i])
    monkeypatch.setattr(fitz, 'open', lambda path: PDF())
    monkeypatch.setattr(Path, 'is_file', lambda path: True)
    item={'document':'X','source_pdf_page':1,'reference_answer':'ผู้รับเหมา และผู้ให้บริการ',
          'required_evidence':[{'document':'X','source_pdf_page':1}, {'document':'X','source_pdf_page':2}]}
    text=reference_text(item, {'X':{'source_file':'fixture.pdf'}}, Path('fixtures'))
    assert 'เริ่มประโยค ผู้' in text and 'รับเหมา และผู้ให้บริการ' in text
    assert 'physical page 2' in text
