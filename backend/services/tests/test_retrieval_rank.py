"""Thai evidence matching and page coverage regressions."""

from backend.services.retrieval_rank import (
    bm25_rank, matched_document_aliases, mentioned_document_ids,
    normalize_search_text, unique_pages, without_document_aliases,
)
from backend.services.tools import _focus_excerpt


def test_normalization_repairs_pdf_font_artifacts_without_erasing_acronyms():
    assert normalize_search_text("สิินทรััพย์์รวม") == "สินทรัพย์รวม"
    assert normalize_search_text("หนี้Qสินและดอกเบี้Ěยเฉลี่Pย") == "หนี้สินและดอกเบี้ยเฉลี่ย"
    assert normalize_search_text("กำไรEBITDAปี 2567 NIM SCBX") == "กำไรEBITDAปี 2567 NIM SCBX"


def test_company_scope_requires_an_explicit_distinctive_name():
    documents = [(1, "scbx_annual_report_2567_th.pdf"),
                 (2, "thai_union_one_report_2567_th.pdf")]
    assert mentioned_document_ids("สินทรัพย์รวม SCBX ปี 2567", documents) == {1}
    assert mentioned_document_ids("เงินปันผลของไทยยูเนี่ยน ปี 2567", documents) == {2}
    # Prior-year comparison values live in the current report.
    assert mentioned_document_ids("SCBX ปี 2566 ไม่ใช่ 2567", documents) == {1}
    assert mentioned_document_ids("สินทรัพย์รวมปี 2567", documents) is None


def test_issuer_scope_does_not_make_the_company_name_dominate_evidence_ranking():
    documents = [(1, "cpaxtra_2567_th.pdf"), (2, "egco_2567_th.pdf")]
    scoped, aliases = matched_document_aliases(
        "ค่าใช้จ่ายวิจัยและพัฒนาของซีพี แอ็กซ์ตร้าในปี 2567", documents)
    assert scoped == {1}
    ranking_query = without_document_aliases(
        "ค่าใช้จ่ายวิจัยและพัฒนาของซีพี แอ็กซ์ตร้าในปี 2567", aliases)
    assert "แอ็กซ์ตร้า" not in ranking_query
    rows = [
        {"document_id": 1, "page": 40, "text": "ซีพี แอ็กซ์ตร้า ซีพี แอ็กซ์ตร้า ซีพี แอ็กซ์ตร้า"},
        {"document_id": 1, "page": 33, "text": "ค่าใช้จ่ายวิจัยและพัฒนา ปี 2567 1,451 ล้านบาท"},
    ]
    assert bm25_rank(ranking_query, rows)[0]["page"] == 33
    assert mentioned_document_ids("หนี้สินรวมของเอ็กโกปี 2567", documents) == {2}


def test_bm25_matches_corrupted_thai_table_label_and_keeps_source_text():
    rows = [
        {"document_id": 1, "page": 19, "text": "สิินทรััพย์์รวม 2567 3,487"},
        {"document_id": 1, "page": 20, "text": "เงิินปัันผลต่่อหุ้�น 2567 10.44"},
    ]
    ranked = bm25_rank("SCBX มีสินทรัพย์รวมปี 2567 เท่าไร", rows)
    assert ranked[0]["page"] == 19
    assert ranked[0]["text"] == rows[0]["text"]


def test_unique_pages_retains_best_chunk_and_more_page_coverage():
    rows = [
        {"document_id": 1, "page": 19, "chunk_id": 1},
        {"document_id": 1, "page": 19, "chunk_id": 2},
        {"document_id": 1, "page": 20, "chunk_id": 3},
    ]
    assert [row["chunk_id"] for row in unique_pages(rows)] == [1, 3]


def test_focus_excerpt_preserves_deep_thai_evidence_with_font_artifacts():
    target = "สิินทรััพย์์รวม ปี 2567 เท่ากับ 3,487 พันล้านบาท"
    page = "Report heading\n" + ("unrelated narrative\n" * 170) + target + "\n" + ("other text\n" * 100)
    excerpt = _focus_excerpt(page, ["สินทรัพย์", "2567"], budget=850, head=100)
    assert excerpt.startswith("Report heading")
    assert target in excerpt
