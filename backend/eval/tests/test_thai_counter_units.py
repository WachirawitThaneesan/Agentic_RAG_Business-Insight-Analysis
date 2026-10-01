"""Regression cases from real public-PDF benchmark false negatives."""
import pytest
from backend.eval.numeric import numeric_match

@pytest.mark.parametrize("target,answer,unit", [
    (2800,"2,800 คัน","คัน"), (120,"120 สาขา","สาขา"), (4,"4 ประเภท","ประเภท"),
    (970,"โรงไฟฟ้าขนอมหน่วยที่ 4 มีกำลังผลิต 970 เมกะวัตต์","เมกะวัตต์"),
    (285050053.21,"285,050,053.21 กิโลวัตต์-ชั่วโมงต่อปี","กิโลวัตต์ชั่วโมงต่อปี"),
    (2593,"ภายในปี 2593","ปี"), (2593,"ภายในปี ค.ศ. 2050","ปี"),
    (100,"หน้า PDF 50: 100 ล้านบาท","ล้านบาท"),
])
def test_explicit_domain_units_and_context_identifiers(target,answer,unit):
    assert numeric_match(target,answer,expected_unit=unit)

@pytest.mark.parametrize("target,answer,unit", [
    (2800,"-2,800 คัน","คัน"), (2800,"2,800 สาขา","คัน"), (2800,"2,800,000 คัน","คัน"),
    (970,"970 กิโลวัตต์ชั่วโมง","เมกะวัตต์"), (970,"970 MWhr","เมกะวัตต์"),
    (2593,"ภายในปี 2594","ปี"), (2593,"ภายในปี 2593 หรือ 2594","ปี"),
    (100,"100 ล้านบาท หรือ 200 ล้านบาท","ล้านบาท"),
    (285050053.21,"285,050,053.21 กิโลวัตต์ชั่วโมง","กิโลวัตต์ชั่วโมงต่อปี"),
])
def test_domain_units_still_reject_wrong_sign_scale_dimension_or_conflict(target,answer,unit):
    assert not numeric_match(target,answer,expected_unit=unit)

def test_counter_keeps_year_binding_strict():
    assert numeric_match(2800,"ปี 2567 มี 2,800 คัน",expected_unit="คัน",expected_year=2567)
    assert not numeric_match(2800,"ปี 2566 มี 2,800 คัน",expected_unit="คัน",expected_year=2567)
