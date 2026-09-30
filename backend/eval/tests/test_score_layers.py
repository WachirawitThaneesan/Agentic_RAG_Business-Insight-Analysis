"""Each evaluation layer uses its own denominator and verifiable evidence."""

from backend.eval.score_layers import REFERENCE, _reference, score_answers, score_search


DOCUMENTS = {"D": {"code": "D", "source_file": "original.pdf",
                    "excerpt_file": "sample.pdf"}}
ITEMS = [
    {"id": "Q1", "document": "D", "source_pdf_page": 46,
     "excerpt_page": 5, "reference_answer": "100 ล้านบาท",
     "answer_components": {"value": "100", "unit": "ล้านบาท", "year_be": 2568},
     "question_th": "ปี 2568 เท่าไร?"},
    {"id": "Q2", "document": "D", "source_pdf_page": 47,
     "excerpt_page": 6, "reference_answer": "World Blood Donor Day",
     "answer_components": {}, "question_th": "What is the event?"},
]


def test_search_metrics_require_ranked_correct_document_and_page():
    predictions = {"Q1": {"results": [
        {"document": "D", "source_pdf_page": 47},
        {"filename": "original.pdf", "source_pdf_page": 46},
    ]}, "Q2": {"results": [{"document": "D", "source_pdf_page": 47}]}}
    result = score_search(ITEMS, DOCUMENTS, predictions, k=2)
    assert result["hit_at_k"] == 1
    assert result["recall_at_k"] == 1
    assert 0 < result["ndcg_at_k"] < 1
    assert result["n_missing_predictions"] == 0


def test_search_rejects_unlocatable_and_wrong_document():
    predictions = {"Q1": {"results": [
        {"document": "D"},
        {"document": "OTHER", "filename": "original.pdf", "source_pdf_page": 46},
    ]}}
    result = score_search(ITEMS[:1], DOCUMENTS, predictions, k=2)
    assert result["hit_at_k"] == 0
    assert result["n_unlocatable_results_top_k"] == 2


def test_search_maps_excerpt_page_to_original_page():
    predictions = {"Q1": {"results": [
        {"filename": "sample.pdf", "page": 5},
    ]}}
    result = score_search(ITEMS[:1], DOCUMENTS, predictions,
                          page_space="excerpt")
    assert result["hit_at_k"] == 1


def test_answer_fact_and_citation_are_separate():
    predictions = {"Q1": {"answer": "100 ล้านบาท", "citations": [
        {"document": "D", "source_pdf_page": 47}]},
        "Q2": {"answer": "World Blood Donor Day", "citations": [
            {"document": "D", "source_pdf_page": 47}]}}
    result = score_answers(ITEMS, DOCUMENTS, predictions)
    assert result["fact_accuracy_determined"] == 1
    assert result["citation_page_hit_rate"] == .5


def test_paraphrase_needs_review_not_automatic_failure_or_pass():
    result = score_answers(ITEMS[1:], DOCUMENTS,
                           {"Q2": {"answer": "The event is World Blood Donor Day."}})
    assert result["n_needs_review"] == 1
    assert result["fact_accuracy_determined"] is None


def test_wrong_unit_is_incorrect_and_missing_unit_requires_review():
    wrong = score_answers(ITEMS[:1], DOCUMENTS,
                          {"Q1": {"answer": "100 พันบาท"}})
    missing = score_answers(ITEMS[:1], DOCUMENTS,
                            {"Q1": {"answer": "100"}})
    assert wrong["n_incorrect"] == 1
    assert missing["n_needs_review"] == 1


def test_exact_reference_answers_and_pages_score_as_oracle():
    items, documents = _reference(REFERENCE)
    predictions = {item["id"]: {
        "answer": item["reference_answer"],
        "citations": [{"document": item["document"],
                       "source_pdf_page": item["source_pdf_page"]}],
        "results": [{"document": item["document"],
                     "source_pdf_page": item["source_pdf_page"]}],
    } for item in items}
    assert score_answers(items, documents, predictions)["n_correct"] == len(items)
    assert score_search(items, documents, predictions)["hit_at_k"] == 1


def test_alternate_evidence_page_supports_search_and_citation():
    item = {**ITEMS[0], "evidence_options": [
        [{"document": "D", "source_pdf_page": 46}],
        [{"document": "D", "source_pdf_page": 80}],
    ]}
    predicted = {"Q1": {"answer": "100 ล้านบาท",
                        "results": [{"document": "D", "source_pdf_page": 80}],
                        "citations": [{"document": "D", "source_pdf_page": 80}]}}
    search = score_search([item], DOCUMENTS, predicted)
    answer = score_answers([item], DOCUMENTS, predicted)
    assert search["hit_at_k"] == 1
    assert search["ndcg_at_k"] == 1
    assert answer["n_correct"] == 1
    assert answer["citation_all_required_rate"] == 1


def test_multi_page_evidence_option_requires_both_pages_for_full_citation():
    item = {**ITEMS[0], "evidence_options": [
        [{"document": "D", "source_pdf_page": 46},
         {"document": "D", "source_pdf_page": 47}],
        [{"document": "D", "source_pdf_page": 80}],
    ]}
    partial = {"Q1": {"answer": "100 ล้านบาท",
                      "citations": [{"document": "D", "source_pdf_page": 46}]}}
    assert score_answers([item], DOCUMENTS, partial)["citation_all_required_rate"] == 0
    alternate = {"Q1": {"answer": "100 ล้านบาท",
                        "citations": [{"document": "D", "source_pdf_page": 80}]}}
    assert score_answers([item], DOCUMENTS, alternate)["citation_all_required_rate"] == 1


def test_rounding_is_only_used_when_reference_declares_it():
    item = {**ITEMS[0], "answer_components": {
        "value": "5.0", "unit": "พันล้านบาท", "year_be": 2567,
        "rounding_decimals": 1,
    }}
    prediction = {"Q1": {"answer": "4,984,894 พันบาท"}}
    assert score_answers([item], DOCUMENTS, prediction)["n_correct"] == 1
    original = {**item, "answer_components": {**item["answer_components"]}}
    original["answer_components"].pop("rounding_decimals")
    assert score_answers([original], DOCUMENTS, prediction)["n_correct"] == 0
