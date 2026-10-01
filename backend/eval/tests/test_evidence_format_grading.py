"""Strict grading of formatting and independently sourced financial calculations."""
import pytest
from backend.eval.numeric import numeric_match
from backend.eval.score_layers import _answer_fact

def test_reference_cli_accepts_versioned_review_but_rejects_unknown_schema(tmp_path):
    import json
    from backend.eval.score_layers import _reference
    path=tmp_path/'reference.json'
    for version in (1, 2):
        path.write_text(json.dumps({'schema_version':version,'documents':[],'items':[]}),encoding='utf-8')
        assert _reference(path)==([], {})
    path.write_text(json.dumps({'schema_version':999,'documents':[],'items':[]}),encoding='utf-8')
    with pytest.raises(ValueError,match='Unsupported reference schema'):
        _reference(path)

def test_colon_page_label_is_context_but_second_financial_value_is_not():
    assert numeric_match('8.125', '8.125 บาท\nปี: 2569\nหน้า: 12', expected_unit='บาท', expected_year=2569)
    assert not numeric_match('8.125', '8.125 บาท และ 12 บาท', expected_unit='บาท')

def test_secondary_currency_requires_independently_labeled_quantity():
    kwargs = dict(expected_unit='ล้านบาท', allowed_other_quantities=((20, 'ล้านดอลลาร์สหรัฐ'),))
    assert numeric_match(700, '20 ล้านดอลลาร์ สรอ. (เทียบเท่า 700 ล้านบาท)', **kwargs)
    for wrong in ('21 ล้านดอลลาร์ สรอ. (เทียบเท่า 700 ล้านบาท)', '-20 ล้านดอลลาร์ สรอ. (เทียบเท่า 700 ล้านบาท)',
                  '20 ดอลลาร์ สรอ. (เทียบเท่า 700 ล้านบาท)', '20 ล้านดอลลาร์ สรอ. (เทียบเท่า 700 พันบาท)',
                  '20 ล้านดอลลาร์ สรอ.'):
        assert not numeric_match(700, wrong, **kwargs)
    assert not numeric_match(700, '20 ล้านดอลลาร์ สรอ. (เทียบเท่า 700 ล้านบาท)', expected_unit='ล้านบาท')

def test_value_unit_evidence_card_retains_unit():
    assert numeric_match(137152,"137,152 ล้านบาท\nค่า: 137,152\nหน่วย: ล้านบาท",expected_unit="ล้านบาท")
    assert not numeric_match(137152,"137,152 ล้านบาท\nค่า: 137,152\nหน่วย: พันบาท",expected_unit="ล้านบาท")

def test_table_and_credit_stage_numbers_are_context_not_measures():
    assert numeric_match(3.23,"ตารางที่ 0 ปี 2568: 3.23%",expected_unit="%",expected_year=2568)
    assert numeric_match(44132,"ระดับที่ 3 ปี 2567: 44,132 ล้านบาท",expected_unit="ล้านบาท",expected_year=2567)
    assert not numeric_match(44132,"ระดับที่ 3 ล้านบาท และ 44,132 ล้านบาท",expected_unit="ล้านบาท")

@pytest.mark.parametrize("answer,correct", [
    ("ปี 2568 137,152 ล้านบาท; ปี 2567 148,004 ล้านบาท; 137,152 - 148,004 = -10,852 ล้านบาท",True),
    ("ปี 2568 137,152 ล้านบาท; ปี 2567 148,004 ล้านบาท; ลดลง 10,852 ล้านบาท",True),
    ("137,152 - 148,004 = 10,852 ล้านบาท",False),
    ("137,000 - 148,004 = -10,852 ล้านบาท",False),
    ("137,152 - 148,004 = -10,852 พันบาท",False),
    ("ปี 2566 137,152 ล้านบาท; ปี 2567 148,004 ล้านบาท; -10,852 ล้านบาท",False),
])
def test_calculation_only_accepts_reference_operands_correct_arithmetic_units_and_years(answer,correct):
    item={"answer_components":{"value":-10852,"unit":"ล้านบาท","supporting_values":[137152,148004],"comparison_years":[2568,2567]}}
    assert (_answer_fact(item,answer)[0]=="correct")==correct
