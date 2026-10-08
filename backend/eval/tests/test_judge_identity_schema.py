from scripts.evaluate_comprehensive import judge_schema
from google.genai import types


def test_numeric_rendered_claims_are_schema_enum_without_paraphrase():
    claims=['CPAXT สินทรัพย์ไม่มีตัวตน ปี 2567 เท่ากับ 10831 ล้านบาท', 'EGCO เป้าหมาย ปี 2573 เท่ากับ 30 ร้อยละ']
    schema=judge_schema({'captured_answer_claims':claims})
    emitted=schema['properties']['answer_claims']
    assert emitted['items']['properties']['text']['enum']==claims
    assert emitted['minItems']==emitted['maxItems']==2
    assert 'actual_citation_audit' in schema['required']
    types.GenerateContentConfig(response_schema=schema)


def test_captured_refusal_requires_no_answer_claims():
    schema=judge_schema({'captured_answer_claims':[]})
    emitted=schema['properties']['answer_claims']
    assert emitted['minItems']==emitted['maxItems']==0
    assert 'enum' not in emitted['items']['properties']['text']
    types.GenerateContentConfig(response_schema=schema)
