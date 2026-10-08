from copy import deepcopy
import pytest
from backend.eval.comprehensive import validate_judgment
from backend.eval.contracts import actual_citation_metrics


def fixture():
    quote='CPAXT รายได้ ปี 2567 เท่ากับ 100 ล้านบาท'
    sources=[{'excerpt':quote}, {'excerpt':'EGCO รายได้ ปี 2567 เท่ากับ 100 ล้านบาท'}]
    raw={'answer_claims':[{'text':quote,'faithfulness':'supported','factual':'supported',
          'context_quote':quote,'reference_quote':quote,'relevant':True,'citations':[]}],
         'reference_claims':[{'text':quote,'answer_covered':True,'context_covered':True,'context_quote':quote}],
         'context_relevance':[{'context_index':0,'useful':True,'quote':quote},
                             {'context_index':1,'useful':False,'quote':''}],
         'relevancy':{'score':2}, 'actual_citation_audit':[
            {'claim_index':0,'source_index':0,'verdict':'supported','quote':quote}]}
    return quote,sources,raw,[{'claim_index':0,'source_index':0}]


def validate(raw,sources,quote,links):
    return validate_judgment(raw,context=quote,sources=sources,reference=quote,actual_citations=links)


def test_judge_cannot_turn_uncited_returned_source_into_actual_citation():
    quote,sources,raw,links=fixture()
    raw['actual_citation_audit'].append({'claim_index':0,'source_index':1,'verdict':'supported','quote':sources[1]['excerpt']})
    with pytest.raises(ValueError,match='unemitted'):
        validate(raw,sources,quote,links)


def test_missing_or_duplicate_actual_pair_cannot_silently_improve_precision():
    quote,sources,raw,links=fixture()
    for decisions in ([],raw['actual_citation_audit']*2):
        candidate=deepcopy(raw);candidate['actual_citation_audit']=decisions
        with pytest.raises(ValueError):validate(candidate,sources,quote,links)


def test_invented_supported_quote_remains_unresolved_in_contract_score():
    quote,sources,raw,links=fixture()
    raw['actual_citation_audit'][0]['quote']='CPAXT invented quote with no supporting source'
    validated=validate(raw,sources,quote,links)
    score=actual_citation_metrics(validated['answer_claims'],sources,links,
                                 support_decisions=validated['actual_citation_audit'])
    assert score['citation_link_precision'] is None and score['n_unresolved_links']==1


def test_explicitly_unsupported_actual_link_is_measured_failure():
    quote,sources,raw,links=fixture()
    raw['actual_citation_audit'][0].update(verdict='insufficient',quote='')
    validated=validate(raw,sources,quote,links)
    score=actual_citation_metrics(validated['answer_claims'],sources,links,
                                 support_decisions=validated['actual_citation_audit'])
    assert score['citation_link_precision']==0 and score['n_unresolved_links']==0
