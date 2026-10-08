import hashlib
from types import SimpleNamespace

import duckdb
import pytest

from backend.services.source_provenance import bind_saved_source
from backend.services.agent import _extract_sources
from backend.services import duckdb_warehouse as warehouse


def test_modified_or_missing_upload_rejected_before_reuse(tmp_path):
    path = tmp_path / 'saved.pdf'
    path.write_bytes(b'original PDF bytes')
    document = SimpleNamespace(source_sha256=None)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert bind_saved_source(document, path) == expected
    path.write_bytes(b'different PDF bytes')
    with pytest.raises(ValueError, match='differs'):
        bind_saved_source(document, path)
    assert document.source_sha256 == expected
    path.unlink()
    with pytest.raises(ValueError, match='differs'):
        bind_saved_source(document, path)
    assert bind_saved_source(SimpleNamespace(source_sha256=None), path) is None


def test_sql_cell_and_vector_sources_retain_saved_upload_hash(monkeypatch):
    conn = duckdb.connect(':memory:')
    warehouse._init_schema(conn)
    monkeypatch.setattr(warehouse, '_get_conn', lambda: conn)
    source_hash = 'a' * 64
    warehouse.load_document_dim(7, 'saved.pdf', source_sha256=source_hash)
    warehouse.load_document_dim(7, 'saved.pdf')
    warehouse.load_table_into_warehouse(7, 'assets', ['รายการ', '2567'],
        [['สินทรัพย์', '123']], unit='ล้านบาท', source_page=3, source_provider='gemini')
    evidence = warehouse.resolve_result_evidence([{
        'document_id': 7, 'table_name': 'assets', 'row_label': 'สินทรัพย์',
        'metric_year': '2567', 'raw_value': '123'}])
    assert evidence[0]['source_sha256'] == source_hash
    assert _extract_sources('sql_query', {'evidence': evidence})[0]['source_sha256'] == source_hash
    assert _extract_sources('vector_search', {'chunks': [{
        'filename': 'saved.pdf', 'source_sha256': source_hash, 'page': 3}]})[0]['source_sha256'] == source_hash
    conn.close()
