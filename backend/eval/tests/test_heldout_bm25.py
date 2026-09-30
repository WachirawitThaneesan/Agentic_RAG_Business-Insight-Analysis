from scripts.benchmark_heldout import BM25


def test_bm25_does_not_return_zero_score_pages():
    index = BM25(["annual revenue was 42", "staff worked remotely"])
    assert index.rank("unmatched phrase", 5) == []
    assert index.rank("revenue", 5) == [0]


def test_thai_word_segmentation_can_match_a_word_inside_a_sentence():
    texts = ["บริษัทมีกำไรสุทธิปี 2567", "ไม่มีตัวเลข"]
    assert BM25(texts).rank("กำไรสุทธิ", 5) == []
    assert BM25(texts, thai_words=True).rank("กำไรสุทธิ", 5) == [0]
