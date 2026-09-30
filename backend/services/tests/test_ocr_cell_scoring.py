"""Exact-cell scoring must reject right numbers in wrong locations."""

from scripts.score_ocr_cells import score_chart_fact, score_table_fact


def _fact(column: int = 1) -> dict:
    return {
        "excerpt_file": "synthetic.pdf",
        "row_contains": "Revenue",
        "column_index": column,
        "printed": "100",
    }


def _ocr(rows: list[list[str]]) -> dict:
    return {"tables": [{"page": 1, "title": "Financial", "headers": ["Item", "2025", "2024"], "rows": rows}]}


def test_exact_cell_accepts_correct_row_and_column():
    assert score_table_fact(_fact(), _ocr([["Revenue", "100", "90"]]))["outcome"] == "correct"


def test_number_elsewhere_on_page_is_not_a_correct_cell():
    result = score_table_fact(_fact(), _ocr([["Revenue", "90", "100"]]))
    assert result["outcome"] == "wrong_value"
    assert result["unsafe_accepted"] is True


def test_missing_row_is_different_from_wrong_value():
    assert score_table_fact(_fact(), _ocr([["Cost", "100", "90"]]))["outcome"] == "missing_row"


def test_exact_row_and_region_prevent_cross_page_half_false_positive():
    fact = {**_fact(), "row_contains": "Opening", "row_equals": True, "region": "left"}
    ocr = {"tables": [
        {"page": 1, "region": "left", "headers": ["Item", "Total"], "rows": [["Opening adjusted", "100"], ["Opening", "90"]]},
        {"page": 1, "region": "right", "headers": ["Item", "Total"], "rows": [["Opening", "100"]]},
    ]}
    result = score_table_fact(fact, ocr)
    assert result["outcome"] == "wrong_value"
    assert result["observed"] == "90"


def test_chart_raw_token_does_not_claim_fact_accuracy():
    fact = {"printed": "24,143"}
    result = score_chart_fact(fact, {"raw_pages": [{"markdown": "ปี 2568 24,143"}]})
    assert result["raw_token_present"] is True
    assert result["outcome"] == "unresolved_chart_fact"


def test_exact_text_cell_requires_correct_person_and_position():
    fact = {**_fact(), "row_contains": "นางกอบกาญจน์ วัฒนวรางกูร", "printed": "ประธานกรรมการ"}
    ocr = {"tables": [{"page": 1, "headers": ["รายชื่อ", "ตำแหน่ง"], "rows": [
        ["นางกอบกาญจน์ วัฒนวรางกูร", "ประธานกรรมการ"],
        ["นางสาวสุจิตพรรณ ล่ำซำ", "รองประธานกรรมการ"],
    ]}]}
    assert score_table_fact(fact, ocr)["outcome"] == "correct"
    wrong = {"tables": [{"page": 1, "headers": ["รายชื่อ", "ตำแหน่ง"], "rows": [
        ["นางกอบกาญจน์ วัฒนวรางกูร", "รองประธานกรรมการ"],
        ["นางสาวสุจิตพรรณ ล่ำซำ", "ประธานกรรมการ"],
    ]}]}
    assert score_table_fact(fact, wrong)["outcome"] == "wrong_value"
