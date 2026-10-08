from copy import deepcopy
import pytest
from backend.eval.contracts import classify_claim, actual_citation_metrics, numeric_fact_result, validate_numeric_label


def label():
    return {'company':'PTT','measure':'รายได้','value':'100','unit':'ล้านบาท',
        'year_be':2567,'year_kind':'event_or_performance','document':'PTT',
        'source_pdf_page':10,'source_sha256':'a'*64,
        'evidence_quote':'รายได้ปี 2567 100 ล้านบาท','review_status':'human_confirmed',
        'tolerance':0,'comparison_operator':'eq'}


def fact():
    return {k:v for k,v in label().items() if k in
        ('company','measure','value','unit','year_be','document','source_pdf_page','comparison_operator')}


def test_missing_quote_is_unverifiable_not_wrong():
    c={'text':'รายได้ 100 ล้านบาท','faithfulness':'supported','context_quote':'invented',
        'factual':'contradicted','reference_quote':''}
    before=deepcopy(c)
    result=classify_claim(c,context='รายได้ 100 ล้านบาท',reference='รายได้ 100 ล้านบาท')
    assert result['faithfulness']['state']=='quote_unverifiable'
    assert result['factual']['state']=='contradicted_ai_needs_review'
    assert c==before


def test_reference_support_does_not_prove_actual_context_support():
    c={'text':'รายได้ 100 ล้านบาท','faithfulness':'supported','context_quote':'รายได้ 100 ล้านบาท',
        'factual':'supported','reference_quote':'รายได้ 100 ล้านบาท'}
    result=classify_claim(c,context='รายได้ไม่ปรากฏ',reference='รายได้ 100 ล้านบาท')
    assert result['faithfulness']['reason']=='quote_present_in_reference_but_not_actual_context'
    assert result['factual']['state']=='supported_quote_verified'


def test_proposed_citations_cannot_be_used_as_actual_citations():
    result=actual_citation_metrics([{'text':'x','citations':[{'source_index':0}]}],
        [{'excerpt':'x'}],None)
    assert result['citation_link_precision'] is None
    assert result['n_actual_links'] is None


def test_unused_retrieved_sources_do_not_enter_actual_citation_denominator():
    result=actual_citation_metrics([{'text':'รายได้ 100 ล้านบาท'}],
        [{'excerpt':'รายได้ 100 ล้านบาท'}]+[{'excerpt':'unrelated'}]*9,
        [{'claim_index':0,'source_index':0}],support_decisions=[
            {'claim_index':0,'source_index':0,'verdict':'supported','quote':'รายได้ 100 ล้านบาท'}])
    assert result['citation_link_precision']==1
    assert result['citation_claim_recall']==1


def test_invalid_actual_link_fails_and_unknown_entailment_is_disclosed():
    result=actual_citation_metrics([{'text':'x'}],[{'excerpt':'x'}],
        [{'claim_index':0,'source_index':99},{'claim_index':0,'source_index':0}])
    assert result['links'][0]['state']=='invalid_claim_or_source_identifier'
    assert result['status']=='partial_entailment_audit'
    assert result['citation_link_precision'] is None
    assert result['citation_link_precision_lower_bound']==0


@pytest.mark.parametrize('key,value',[('value','-100'),('value','100000'),
    ('unit','บาท'),('unit','USD million'),('year_be',2566),
    ('company','PTTEP'),('measure','กำไร'),('source_pdf_page',11)])
def test_wrong_bound_numeric_fact_cannot_pass(key,value):
    actual=fact();actual[key]=value
    assert numeric_fact_result(label(),actual)['correct'] is False


def test_scale_conversion_and_frozen_rounding_policy():
    actual=fact();actual.update(value='.1',unit='พันล้านบาท')
    assert numeric_fact_result(label(),actual)['correct'] is True
    gold=label();gold.update(value='100.04',rounding_decimals=1)
    actual=fact();actual['value']='100.0'
    assert numeric_fact_result(gold,actual)['correct'] is True
    gold['rounding_decimals']=2
    assert numeric_fact_result(gold,actual)['correct'] is False


def test_missing_context_or_unreviewed_reference_is_not_zero_accuracy():
    actual=fact();actual.pop('measure')
    assert numeric_fact_result(label(),actual)['correct'] is None
    gold=label();gold['review_status']='provisional_ai'
    assert numeric_fact_result(gold,fact())['correct'] is None
    assert numeric_fact_result(gold,fact(),allow_provisional=True)['correct'] is True


def test_event_year_cannot_be_inferred_from_report_year():
    gold=label();gold['year_be']=None
    with pytest.raises(ValueError,match='explicit BE year'):validate_numeric_label(gold)


def test_visual_evidence_is_an_explicit_alternative_when_native_text_is_broken():
    gold=label();gold['evidence_quote']=''
    with pytest.raises(ValueError,match='native evidence'):validate_numeric_label(gold)
    gold.update(visual_evidence_transcript='รายได้ปี 2567 100 ล้านบาท',image_sha256='b'*64)
    assert validate_numeric_label(gold)['image_sha256']=='b'*64


def test_upper_bound_cannot_pass_as_an_exact_achieved_value():
    gold=label();gold['comparison_operator']='lte'
    assert numeric_fact_result(gold,fact())['correct'] is False
    actual=fact();actual['comparison_operator']='lte'
    assert numeric_fact_result(gold,actual)['correct'] is True


def test_range_requires_both_bounds_and_cannot_be_a_single_value():
    gold=label();gold.update(value='100',comparison_operator='range',range_min='100',range_max='120')
    assert numeric_fact_result(gold,fact())['correct'] is False
    actual=fact();actual.update(comparison_operator='range',range_min='100',range_max='120')
    assert numeric_fact_result(gold,actual)['correct'] is True
    actual['range_max']='130'
    assert numeric_fact_result(gold,actual)['correct'] is False
