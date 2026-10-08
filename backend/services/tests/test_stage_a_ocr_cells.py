"""A correct number must retain the source row, year, group, scale and page."""
from copy import deepcopy
import pytest
from scripts.evaluate_gemini_ocr_stage_a import score_fact


def fixture():
    fact = {'physical_page': 7, 'row_token': 'เงินสด', 'column_tokens': ['2567', 'งบรวม', 'ตรวจสอบ'],
            'value': '19,461', 'unit': 'ล้านบาท', 'scope_tokens': []}
    tables = [{'page': 7, 'title': 'งบแสดงฐานะการเงิน', 'unit': 'บาท (THB)',
        'headers': ['รายการ', '31 ธ.ค. 2567 งบรวม ตรวจสอบ'],
        'rows': [['เงินสด (ล้านบาท)', '19461']]}]
    return fact, tables


def test_exact_relation_and_row_scale_override():
    fact, tables = fixture()
    assert score_fact(fact, tables)['correct'] is True


@pytest.mark.parametrize('mutate', [
    lambda t: t[0].update(page=8),
    lambda t: t[0].update(headers=['รายการ', '2566 งบรวม ตรวจสอบ']),
    lambda t: t[0].update(headers=['รายการ', '2567 งบเฉพาะกิจการ ตรวจสอบ']),
    lambda t: t[0].update(rows=[['เงินสด (บาท)', '19461']]),
    lambda t: t[0].update(rows=[['เงินสด (ล้านบาท)', '-19461']]),
    lambda t: t[0].update(rows=[['รายได้ (ล้านบาท)', '19461']]),
    lambda t: t.extend(deepcopy(t)),
    lambda t: t[0].update(headers=['รายการ', '2567 งบรวม', '2567 ตรวจสอบ'],
                         rows=[['เงินสด (ล้านบาท)', '19461', '']]),
])
def test_correct_number_in_wrong_relation_never_passes(mutate):
    fact, tables = fixture()
    mutate(tables)
    assert score_fact(fact, tables)['correct'] is False


def test_continuation_year_requires_original_header_page_binding():
    fact, tables = fixture()
    fact['header_source_page'] = 6
    assert score_fact(fact, tables)['checks']['source_header_available'] is False
    tables[0]['header_source_page'] = 6
    assert score_fact(fact, tables)['correct'] is True


def test_unit_column_preserves_nonfinancial_scale():
    fact, tables = fixture()
    fact.update(unit='ร้อยละ', value='(83.39)')
    tables[0].update(headers=['รายการ', 'หน่วย', '2567 งบรวม ตรวจสอบ'],
                    rows=[['เงินสด', 'ร้อยละ', '(83.39)']])
    assert score_fact(fact, tables)['correct'] is True
