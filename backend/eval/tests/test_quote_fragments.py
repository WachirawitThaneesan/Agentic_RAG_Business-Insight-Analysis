import pytest
from scripts.evidence_quote_fragments import fragments,resolve
from scripts.evaluate_comprehensive import judge_payload,judge_schema,bind_judge_claim_indices
from google.genai import types


def row():
    return dict(question='q',answer='claim',answerable=True,context='actual supporting original text',reference='independent original reference',
        sources=[dict(excerpt='source one'),dict(excerpt='source two')],captured_answer_claims=['claim'],
        actual_claim_citations=[dict(claim_index=0,source_index=1)],compact_judge_payload=True,fragment_quotes=True,
        evidence_blocks=[dict(context_index=0,source_index=1,start=0,end=31,text='actual supporting original text')])


def raw():
    return dict(answer_claims=[dict(claim_index=0,faithfulness='supported',factual='supported',context_fragment_id='C0',reference_fragment_id='R0',relevant=True,citations=[])],
        reference_claims=[],context_relevance=[dict(context_index=0,useful=True,context_fragment_id='C0')],
        actual_citation_audit=[dict(claim_index=0,source_index=1,verdict='supported',source_fragment_id='S1_0')],relevancy={'score':2})


def test_model_selected_quotes_are_exact_original_spans_not_inferred_claims():
    r=row();d=bind_judge_claim_indices(raw(),r)
    assert d['answer_claims'][0]['text']=='claim'
    assert d['answer_claims'][0]['context_quote']==r['context']
    assert d['actual_citation_audit'][0]['quote']=='source two'
    types.Schema.model_validate(judge_schema(r))
    assert judge_payload(r)['ACTUAL_CONTEXT']['fragments'][0]['text']==r['context']


def test_fragments_cover_whole_text_and_preserve_numbers_signs_and_units():
    text='-100 ล้านบาท ปี 2567 '*100;parts=fragments(text,'C')
    covered=set()
    for part in parts:
        assert part['text']==text[part['start']:part['end']]
        covered.update(range(part['start'],part['end']))
    assert covered==set(range(len(text)))


def test_invented_or_other_source_fragment_cannot_become_a_citation():
    d=raw();d['actual_citation_audit'][0]['source_fragment_id']='S0_0'
    with pytest.raises(ValueError):resolve(d,row())
    d=raw();d['answer_claims'][0]['context_fragment_id']='C900'
    with pytest.raises(ValueError):resolve(d,row())
