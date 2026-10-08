from copy import deepcopy
from backend.eval.contract_replay import numeric_results
from backend.eval.tests.test_contract_replay import label
from backend.services.tests.test_answer_capture import fixture
from backend.services.answer_capture import finalize


def test_filename_identity_is_resolved_by_document_registry_without_gold_annotations():
    result, event = fixture()
    full = finalize(result, [event])
    original = deepcopy(full)
    gold = {**label(), 'company': 'CPAXT', 'measure': 'สินทรัพย์ไม่มีตัวตน',
            'value': 10831, 'document': 'CPAXT', 'source_pdf_page': 133}
    scored = numeric_results([gold], full, full['answer'], allow_provisional=True,
                             document_registry=[{'code': 'CPAXT', 'source_file': 'cpaxt.pdf'}])
    assert scored[0]['correct'] is True
    assert full == original


def test_single_bound_wrong_company_is_scored_wrong_instead_of_missing():
    result, event = fixture()
    full = finalize(result, [event])
    scored = numeric_results([label()], full, full['answer'], allow_provisional=True)
    assert scored[0]['correct'] is False
    assert scored[0]['checks']['company'] is False


def test_changed_numeric_annotations_cannot_be_used_with_old_answer_binding():
    result, event = fixture()
    full = finalize(result, [event])
    full['numeric_facts'][0]['value'] = 100
    scored = numeric_results([label()], full, full['answer'], allow_provisional=True)
    assert scored[0]['correct'] is None
    assert scored[0]['state'] == 'application_capture_binding_mismatch'


def test_explicit_bound_refusal_is_wrong_for_required_quantity():
    result, event = fixture()
    answer = 'หลักฐานไม่เพียงพอ'
    result['answer'] = event['draft'] = answer
    event['payload'] = {'answer': answer, 'abstained': True, 'answer_claims': [],
                        'claim_citations': [], 'numeric_facts': []}
    full = finalize(result, [event])
    scored = numeric_results([label()], full, answer, allow_provisional=True)
    assert scored[0]['correct'] is False
    assert scored[0]['state'] == 'explicit_abstention_on_required_quantity'
    full['answer'] = 'different refusal'
    assert numeric_results([label()], full, full['answer'], allow_provisional=True)[0]['correct'] is None
