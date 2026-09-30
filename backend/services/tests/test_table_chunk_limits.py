"""Keep wide financial tables below the local embedding payload limit."""

from backend.services.table_utils import build_table_chunk_payloads


def test_wide_table_chunks_preserve_every_row_under_embedding_limit():
    rows = [[f"ยอดคงเหลือ {i}", *(f"{i * 1000 + j:,}" for j in range(18))]
            for i in range(30)]
    table = {"title": "งบการเปลี่ยนแปลงส่วนของเจ้าของ", "table_name": "equity",
             "headers": ["รายการ", *(f"คอลัมน์ {j}" for j in range(18))], "rows": rows}
    chunks = build_table_chunk_payloads("report.pdf", [table])
    assert len(chunks) > 1
    assert all(len(chunk["text"]) <= 2400 for chunk in chunks)
    assert [index for chunk in chunks for index in range(chunk["row_start"], chunk["row_end"] + 1)] == list(range(30))
    assert sum(chunk["text"].count("ยอดคงเหลือ") for chunk in chunks) == 30
