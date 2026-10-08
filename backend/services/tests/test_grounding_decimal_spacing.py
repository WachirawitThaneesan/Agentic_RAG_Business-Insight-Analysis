from copy import deepcopy

import pytest

from backend.services.agent import _grounded_answer, _numbers


@pytest.mark.parametrize('excerpt,value', [
    ('ค่าเฉลี่ยความพร้อมในการเดินเครื่อง ร้อยละ 99.\n\n31', '99.31'),
    ('งบประมาณในรูปแบบโครงการ ร้อยละ 80. 07', '80.07'),
    ('มูลค่า (1,066.\n38) ล้านบาท', '-1066.38'),
])
def test_quantity_anchored_split_decimal_does_not_cause_false_refusal(excerpt, value):
    sources = [dict(filename='example.pdf', page=43, excerpt=excerpt)]
    original = deepcopy(sources)
    answer = f'บริษัท ค่าที่ถาม เท่ากับ {value} (PDF หน้า 43)'
    assert _grounded_answer(answer, 'ค่าที่ถามเท่าใด', sources) == answer
    assert sources == original


@pytest.mark.parametrize('answer_value', ['98.31', '-99.31', '9931'])
def test_split_decimal_still_rejects_changed_value_sign_or_scale(answer_value):
    sources = [dict(page=43, excerpt='ค่าเฉลี่ย ร้อยละ 99.\n\n31')]
    answer = f'ค่าที่ถาม {answer_value} (PDF หน้า 43)'
    assert _grounded_answer(answer, 'ค่าที่ถามเท่าใด', sources).startswith('ไม่พบหลักฐาน')


def test_section_numbers_and_other_source_blocks_are_not_joined():
    assert 99.31 not in _numbers('หัวข้อ 99.\n\n31 รายการ')
    assert 1.2 not in _numbers('รายการสินค้า\n1. 2 บาท\n2. 5 บาท')
    sources = [dict(page=1, excerpt='ร้อยละ 99.'), dict(page=2, excerpt='31 รายการ')]
    assert _grounded_answer('ค่า 99.31 (PDF หน้า 1)', 'ค่าเท่าใด', sources).startswith('ไม่พบหลักฐาน')


def test_split_negative_decimal_does_not_support_positive_value():
    assert -1066.38 in _numbers('มูลค่า (1,066.\n38) ล้านบาท')
    assert 1066.38 not in _numbers('มูลค่า (1,066.\n38) ล้านบาท')
