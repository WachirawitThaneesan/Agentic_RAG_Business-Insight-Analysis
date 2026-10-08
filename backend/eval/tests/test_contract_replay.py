from copy import deepcopy
import json
import pytest

from backend.eval.contract_replay import numeric_results, replay_answer, summarize_replay
from backend.eval.contract_replay import validate_reference_binding


def test_stale_audit_labels_cannot_be_replayed_against_a_corrected_bank():
    old = {'question_th': 'วิสัยทัศน์?', 'reference_answer': 'พันธกิจ',
           'document': 'PTT', 'source_pdf_page': 3}
    row = {'question': old['question_th'], 'reference': json.dumps(
        {k: v for k, v in old.items() if k != 'question_th'})+'\nNative PDF context'}
    validate_reference_binding(row, old)
    corrected = {**old, 'reference_answer': 'วิสัยทัศน์ที่ถูกต้อง'}
    with pytest.raises(ValueError, match='differs from frozen bank'):
        validate_reference_binding(row, corrected)
    with pytest.raises(ValueError, match='differs from frozen bank'):
        validate_reference_binding({**row, 'question': 'พันธกิจ?'}, old)


def fixture():
    text = 'รายได้ 100 ล้านบาท ปี 2567'
    raw = {'answer_claims': [{'text': text, 'faithfulness': 'supported',
        'context_quote': text, 'factual': 'supported', 'reference_quote': text,
        'relevant': True, 'citations': [{'source_index': 0, 'quote': text}]}],
        'reference_claims': [{'text': text, 'answer_covered': True,
                              'context_covered': True, 'context_quote': text}],
        'context_relevance': [{'context_index': 0, 'useful': True, 'quote': text}],
        'relevancy': {'score': 2}}
    row = {'id': 'Q1', 'key': 'Q1', 'answerable': True, 'answer': text,
           'context': text, 'reference': text, 'sources': [{'excerpt': text}],
           'numeric_reference': False, 'deterministic': {
               'page_citation_complete': True, 'prose_page_consistent': True,
               'empty_response': False, 'abstained': False}}
    record = {'answer': text, 'full_result': {'sources': deepcopy(row['sources'])}}
    return row, raw, record


def label():
    return {'id': 'Q1', 'quantity_index': 0, 'company': 'PTT', 'measure': 'รายได้',
        'value': 100, 'unit': 'ล้านบาท', 'year_be': 2567, 'year_kind': 'event_or_performance',
        'document': 'PTT', 'source_pdf_page': 10, 'source_sha256': 'a'*64,
        'evidence_quote': 'รายได้ 100 ล้านบาท ปี 2567', 'comparison_operator': 'eq',
        'review_status': 'provisional_ai_pdf_image'}


def test_missing_application_mapping_cannot_be_replaced_with_judge_links():
    row, raw, record = fixture()
    result = replay_answer(row, raw, record, [])
    assert result['n_judge_proposed_links_excluded'] == 1
    assert result['actual_citation']['citation_link_precision'] is None
    assert result['complete_answer_success'] is None
    assert result['human_confirmed'] is False


def test_numeric_labels_are_connected_without_filling_answer_from_gold():
    row, raw, record = fixture()
    before = deepcopy(record)
    result = replay_answer(row, raw, record, [label()], allow_provisional=True)
    assert result['numeric_required'] is True
    assert result['numeric'][0]['correct'] is None
    assert result['complete_gate']['numeric_tuple'] is None
    assert record == before
    s = summarize_replay([result], n_total=2, n_numeric_labels=101)
    assert s['numeric']['accuracy_measured_subset'] is None
    assert s['numeric']['tuple_evaluation_coverage'] == 0
    assert s['complete_answer_success']['n_unresolved'] == 2
    assert s['complete_answer_success']['rate_all'] is None
    assert s['complete_answer_success']['strict_lower_bound_all'] == 0


def test_numeric_fact_requires_provenance_and_answer_quote():
    gold = label()
    fact = deepcopy(gold)
    full = {'numeric_facts': [fact]}
    assert numeric_results([gold], full, gold['evidence_quote'], allow_provisional=True)[0]['correct'] is None
    fact.update(annotation_origin='independent_review', answer_quote='invented')
    assert numeric_results([gold], full, gold['evidence_quote'], allow_provisional=True)[0]['correct'] is None
    fact['answer_quote'] = gold['evidence_quote']
    assert numeric_results([gold], full, gold['evidence_quote'], allow_provisional=True)[0]['correct'] is True
    assert numeric_results([gold], full, gold['evidence_quote'])[0]['correct'] is None
    fact['year_be'] = 2566
    assert numeric_results([gold], full, gold['evidence_quote'], allow_provisional=True)[0]['correct'] is False


def test_conflicted_reference_is_unknown_even_when_answer_matches_frozen_tuple():
    gold = label()
    gold['blind_recheck_reference_conflict'] = True
    fact = {**deepcopy(gold), 'annotation_origin': 'independent_review',
            'answer_quote': gold['evidence_quote']}
    before = deepcopy(gold)
    result = numeric_results([gold], {'numeric_facts': [fact]},
                             gold['evidence_quote'], allow_provisional=True)[0]
    assert result['state'] == 'reference_conflict_pending'
    assert result['correct'] is None
    assert result['human_confirmed'] is False
    assert gold == before


def test_quote_unverifiable_remains_unknown_and_not_confirmed_wrong():
    row, raw, record = fixture()
    raw['answer_claims'][0]['context_quote'] = 'invented quote'
    result = replay_answer(row, raw, record, [])
    assert result['claims'][0]['faithfulness']['state'] == 'quote_unverifiable'
    assert result['complete_gate']['faithfulness'] is None
    s = summarize_replay([result], n_total=1, n_numeric_labels=0)
    assert s['claim_states']['faithfulness']['confirmed_wrong_claims'] is None
    assert s['claim_states']['faithfulness']['counts']['quote_unverifiable'] == 1


def test_aligned_actual_citations_need_separate_entailment_audit():
    row, raw, record = fixture()
    record['full_result'].update(answer_claims=[row['answer']],
                                claim_citations=[{'claim_index': 0, 'source_index': 0}])
    result = replay_answer(row, raw, record, [])
    assert result['actual_citation']['status'] == 'partial_entailment_audit'
    assert result['complete_answer_success'] is None
    result = replay_answer(row, raw, record, [], citation_support_decisions=[{
        'claim_index': 0, 'source_index': 0, 'verdict': 'supported', 'quote': row['answer']}])
    assert result['complete_answer_success'] is True
    record['full_result']['sources'][0]['excerpt'] = 'different source'
    result = replay_answer(row, raw, record, [], citation_support_decisions=[{
        'claim_index': 0, 'source_index': 0, 'verdict': 'supported', 'quote': row['answer']}])
    assert result['actual_citation']['citation_link_precision'] is None


def test_existing_failure_does_not_hide_missing_dimensions():
    row, raw, record = fixture()
    row['deterministic']['prose_page_consistent'] = False
    result = replay_answer(row, raw, record, [])
    assert result['complete_answer_success'] is None
    assert result['complete_answer_could_pass'] is False
    s = summarize_replay([result], n_total=1, n_numeric_labels=0)
    assert s['complete_answer_success']['upper_bound_given_observed_failures_ai_provisional'] == 0
