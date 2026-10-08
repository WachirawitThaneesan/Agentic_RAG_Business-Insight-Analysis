from copy import deepcopy

from backend.services.tests.test_answer_capture import fixture
from backend.services.answer_capture import finalize
from backend.eval.tests.test_contract_replay import label
from scripts.audit_numeric_identity import score


def test_semantic_identity_does_not_override_value_year_unit_page_or_mutate_annotations():
    result,event=fixture();full=finalize(result,[event]);original=deepcopy(full)
    gold={**label(), 'company':'ซีพีแอ็กซ์ตร้า','measure':'สินทรัพย์ไม่มีตัวตน',
          'document':'CPAXT','source_pdf_page':133,'value':10831}
    reference='ซีพีแอ็กซ์ตร้า สินทรัพย์ไม่มีตัวตน ปี 2567 จำนวน 10831 ล้านบาท'
    decision=dict(quantity_index=0,fact_index=0,company='same',measure='same',
                  company_quote='ซีพีแอ็กซ์ตร้า',measure_quote='สินทรัพย์ไม่มีตัวตน',reason='same source identity')
    registry=[dict(code='CPAXT',source_file='cpaxt.pdf')]
    assert score([gold],full,full['answer'],[decision],reference,registry)[0]['correct'] is True
    assert full==original
    for key,value in [('year_be',2566),('value',99999),('unit','พันบาท'),('source_pdf_page',13)]:
        changed={**gold,key:value}
        assert score([changed],full,full['answer'],[decision],reference,registry)[0]['correct'] is False


def test_unverifiable_identity_quote_cannot_certify_equivalence():
    result,event=fixture();full=finalize(result,[event])
    gold={**label(),'value':10831,'document':'CPAXT','source_pdf_page':133}
    decision=dict(quantity_index=0,fact_index=0,company='same',measure='same',
                  company_quote='invented company evidence',measure_quote='invented measure evidence',reason='')
    scored=score([gold],full,full['answer'],[decision],'reference',
        [dict(code='CPAXT',source_file='cpaxt.pdf')])[0]
    assert scored['correct'] is None
