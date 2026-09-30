"""Regression cases for signed, year-bound, explicit-unit answer grading."""

import pytest

from backend.eval.grade import grade
from backend.eval.numeric import numeric_match


@pytest.mark.parametrize("answer", [
    "-100 ล้านบาท", "− 100 ล้านบาท", "100000 ล้านบาท", "0.0001 ล้านบาท",
    "100 พันบาท", "100%", "ปี 2567: 100 ล้านบาท",
    "ปี 2568: 100 ล้านบาท หรือ 200 ล้านบาท",
])
def test_numeric_rejects_wrong_sign_scale_unit_year_or_conflict(answer):
    assert not numeric_match(100, answer, expected_unit="ล้านบาท", expected_year=2568)


@pytest.mark.parametrize("answer", [
    "100 ล้านบาท", "100,000,000 บาท", "0.1 พันล้านบาท", "ปี 2568: 100 ล้านบาท",
    "ปี 2568 100 ล้านบาท; ปี 2567 90 ล้านบาท",
    "หน้า 30: ปี 2568 100 ล้านบาท",
])
def test_numeric_accepts_explicit_equivalence_and_context(answer):
    assert numeric_match(100, answer, expected_unit="ล้านบาท", expected_year=2568)


def test_parentheses_are_negative_and_unitless_reference_does_not_certify_units():
    assert numeric_match(-1719943, "(1,719,943)", expected_year=2567)
    assert not numeric_match(-1719943, "1,719,943", expected_year=2567)
    assert not numeric_match(100, "100 ล้านบาท")


def test_chart_count_can_include_labeled_total_and_age_range():
    assert numeric_match(4, "41–50 ปี มี 4 คนจาก 9 คน", expected_unit="คน",
                         allowed_other_values=(9,))
    assert not numeric_match(4, "41–50 ปี มี 5 คนจาก 9 คน", expected_unit="คน",
                             allowed_other_values=(9,))


def test_thai_calendar_dates_do_not_compete_with_the_answer_value():
    assert numeric_match(90000, "ณ 31 ธันวาคม 2568 เงินสดเท่ากับ 90,000 พันบาท",
                         expected_unit="พันบาท", expected_year=2568)
    assert numeric_match("29473.68",
                         "ค่าบริการต่อเดือน 29,473.68 บาท (1 พ.ย. 2567 - 30 ต.ค. 2569)",
                         expected_unit="บาทต่อเดือน")
    assert not numeric_match(90000, "ณ 31 ธันวาคม 2567 เงินสดเท่ากับ 90,000 พันบาท",
                             expected_unit="พันบาท", expected_year=2568)
    assert not numeric_match("29473.68", "ค่าบริการต่อเดือน -29,473.68 บาท",
                             expected_unit="บาทต่อเดือน")


def test_legacy_numeric_grader_uses_reference_unit_and_question_year():
    item = {"question": "ปี 2568 รายได้เท่าไร?", "ground_truth": "100 ล้านบาท",
            "grader": {"type": "numeric", "value": 100}}
    assert grade(item, "100 ล้านบาท")["passed"]
    for answer in ("-100 ล้านบาท", "100000 ล้านบาท", "100 พันบาท",
                   "ปี 2567: 100 ล้านบาท"):
        assert not grade(item, answer)["passed"]


def test_numeric_grader_uses_explicit_question_unit():
    item = {"question": "รายได้เท่าไร (ล้านบาท)?", "ground_truth": "100",
            "grader": {"type": "numeric", "value": 100}}
    assert grade(item, "100 ล้านบาท")["passed"]
    assert not grade(item, "100 พันบาท")["passed"]


def test_semantic_judge_outage_is_unscored_but_empty_answer_is_failure(monkeypatch):
    monkeypatch.setattr("backend.eval.grade._judge_typhoon", lambda prompt: None)
    item = {"question": "What is the activity?", "ground_truth": "Blood donation",
            "grader": {"type": "llm_judge", "reference": ""}}
    assert grade(item, "A blood donation event")["scored"] is False
    assert grade(item, "")["scored"] is True
    assert grade(item, "")["passed"] is False


def test_all_of_binds_numeric_fact_to_explicit_year_label():
    item = {"ground_truth": "ปี 2568 100 ล้านบาท; ปี 2567 90 ล้านบาท",
            "grader": {"type": "all_of", "values": ["2568", 100]}}
    assert grade(item, "ปี 2568 100 ล้านบาท; ปี 2567 90 ล้านบาท")["passed"]
    assert not grade(item, "ปี 2568 90 ล้านบาท; ปี 2567 100 ล้านบาท")["passed"]


def test_us_dollar_scales_do_not_cross_currencies_or_years():
    assert numeric_match(60922, "$60,922 million", expected_unit="USD million",
                         expected_year=2024)
    assert numeric_match(60922, "$60.922 billion", expected_unit="USD million",
                         expected_year=2024)
    assert numeric_match(60922, "60,922 USD million", expected_unit="USD million")
    assert not numeric_match(60922, "60,922 ล้านบาท", expected_unit="USD million")
    assert not numeric_match(60922, "$60,922 million in 2023",
                             expected_unit="USD million", expected_year=2024)
    assert not numeric_match(60922, "-60,922 USD million", expected_unit="USD million")
    assert not numeric_match(60922, "$60,922", expected_unit="USD million")


def test_people_scale_requires_an_explicit_unit():
    assert numeric_match(244, "244 million people", expected_unit="million people")
    assert numeric_match(244, "244,000,000 people", expected_unit="million people")
    assert not numeric_match(244, "244 people", expected_unit="million people")
    assert not numeric_match(244, "244", expected_unit="million people")
    assert not numeric_match(244, "244 million", expected_unit="million people")


def test_thai_report_units_preserve_currency_count_and_scale():
    assert numeric_match(262, "262 พันล้านดอลลาร์สหรัฐ", expected_unit="USD billion")
    assert numeric_match(87.5, "87,500,000 หมายเลข", expected_unit="ล้านหมายเลข")
    assert numeric_match(35.5, "35.5 ล้านคน", expected_unit="million people")
    assert numeric_match(-984, "(984) ล้านบาท", expected_unit="ล้านบาท")
    assert not numeric_match(262, "262 พันล้านบาท", expected_unit="USD billion")
    assert not numeric_match(87.5, "87.5 ล้านรายการ", expected_unit="ล้านหมายเลข")
    assert not numeric_match(35.5, "35.5 คน", expected_unit="million people")
    assert not numeric_match(-984, "984 ล้านบาท", expected_unit="ล้านบาท")
    assert numeric_match(-1.6, "การลงทุนภาคเอกชนลดลง 1.6%", expected_unit="%")
    assert numeric_match(-1.6, "หดตัวร้อยละ 1.6", expected_unit="%")
    assert not numeric_match(1.6, "การลงทุนภาคเอกชนลดลง 1.6%", expected_unit="%")


def test_thai_score_and_ordinal_year_units():
    assert numeric_match(85, "85 คะแนนจากเต็ม 100 คะแนน", expected_unit="คะแนน",
                         allowed_other_values=(100,))
    assert numeric_match(85, "85/100 คะแนน", expected_unit="คะแนน",
                         allowed_other_values=(100,))
    assert not numeric_match(85, "80 คะแนนจากเต็ม 100 คะแนน", expected_unit="คะแนน",
                             allowed_other_values=(100,))
    assert numeric_match(9, "ได้รับคัดเลือกเป็นปีที่ 9", expected_unit="ปี")
    assert numeric_match(9, "ติดต่อกัน 9 ปี", expected_unit="ปี")
    assert not numeric_match(9, "ได้รับคัดเลือกเป็นปีที่ 8", expected_unit="ปี")


def test_generation_label_is_context_not_a_competing_answer():
    answer = "ในปี 2567 ธุรกิจ Gen 2 ของ SCBX คิดเป็นสัดส่วนร้อยละ 16 ของรายได้รวม"
    assert numeric_match(16, answer, expected_unit="%", expected_year=2567)
    assert not numeric_match(16, answer.replace("16", "17"),
                             expected_unit="%", expected_year=2567)
    assert not numeric_match(16, "Gen 2% และ 16%", expected_unit="%")


def test_declared_one_decimal_rounding_accepts_equivalent_scale_only():
    assert numeric_match("5.0", "4,984,894 พันบาท", expected_unit="พันล้านบาท",
                         rounding_decimals=1)
    assert not numeric_match("5.0", "4,984,894 พันบาท", expected_unit="พันล้านบาท")
    for answer in ("4,949,000 พันบาท", "5,050,000 พันบาท", "-4,984,894 พันบาท",
                   "4,984,894 ล้านบาท", "ปี 2566 4,984,894 พันบาท"):
        assert not numeric_match("5.0", answer, expected_unit="พันล้านบาท",
                                 expected_year=2567, rounding_decimals=1)
