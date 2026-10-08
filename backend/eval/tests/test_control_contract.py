from copy import deepcopy
from backend.eval.contract_replay import replay_answer, summarize_replay
from backend.eval.comprehensive import deterministic_answer
from backend.services import answer_capture as capture


def control(answer='หลักฐานไม่เพียงพอ',claimed=False):
    payload=dict(answer=answer,abstained=not claimed,answer_claims=[answer] if claimed else [],
        claim_citations=[],numeric_facts=[])
    full=capture.finalize(dict(answer=answer,sources=[]),[dict(draft=answer,payload=payload,
        context='',blocks=[],origin='model_generation',prompt_sha256=None)])
    item=dict(id='C1',document='PTT',source_pdf_page=1,reference_answer='',answerable=False)
    record=dict(answer=answer,full_result=full)
    row=dict(id='C1',key='C1',answer=answer,answerable=False,context='',reference='',sources=[],
        evidence_blocks=[],numeric_reference=False,deterministic=deterministic_answer(item,record,{}))
    raw=dict(answer_claims=[],reference_claims=[],context_relevance=[],actual_citation_audit=[],relevancy={'score':2})
    return row,raw,record


def test_correct_control_has_no_inapplicable_missing_dimensions():
    row,raw,record=control()
    r=replay_answer(row,raw,record,[],allow_provisional=True)
    assert r['complete_answer_success'] is True
    assert r['missing_dimensions']==[]
    s=summarize_replay([r],n_total=2,n_numeric_labels=0,n_total_answerable=1)
    assert s['unanswerable_abstention_success']['rate_all']==1
    assert s['answerable_complete_success']['rate_all'] is None


def test_refusal_with_an_asserted_quantity_does_not_pass_control():
    row,raw,record=control('หลักฐานไม่เพียงพอ แต่รายได้เท่ากับ 100 ล้านบาท')
    assert replay_answer(row,raw,record,[],allow_provisional=True)['complete_answer_success'] is False


def test_answerable_refusal_is_a_known_failure_not_missing_precision():
    row,raw,record=control()
    row['answerable']=True
    row['deterministic'].update(page_citation_complete=False,prose_page_consistent=True)
    raw['reference_claims']=[dict(text='required fact',answer_covered=False,context_covered=False,context_quote='')]
    r=replay_answer(row,raw,record,[],allow_provisional=True)
    assert r['complete_answer_success'] is False
    assert 'faithfulness' not in r['missing_dimensions']
