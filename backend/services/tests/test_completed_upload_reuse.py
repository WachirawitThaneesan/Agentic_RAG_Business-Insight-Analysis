"""Completed reuse must not hide missing, modified, or unfinished source pages."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.routes import documents
from backend.services.source_provenance import saved_source_hash


def test_reuse_verifies_saved_bytes_and_complete_page_sequence(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, 'UPLOAD_DIR', str(tmp_path))
    incoming = tmp_path / 'incoming.pdf'
    incoming.write_bytes(b'original PDF bytes')
    saved = tmp_path / '10.pdf'
    saved.write_bytes(incoming.read_bytes())
    existing = SimpleNamespace(id=10, filename='same.pdf', status='completed',
                               source_sha256=saved_source_hash(incoming))
    pages = [SimpleNamespace(page_number=i, status='indexed') for i in (1, 2)]
    def result(items):
        return SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:items))
    def session():
        return SimpleNamespace(execute=AsyncMock(side_effect=[result([existing]), result(pages)]))
    monkeypatch.setattr(documents.ocr_service, 'get_pdf_page_count', lambda path:2)
    assert asyncio.run(documents._verified_completed_upload(session(), 'same.pdf', incoming)) == (existing, 2)
    pages[1].status = 'failed'
    assert asyncio.run(documents._verified_completed_upload(session(), 'same.pdf', incoming)) is None
    pages[1].status = 'indexed'
    pages[1].page_number = 3
    assert asyncio.run(documents._verified_completed_upload(session(), 'same.pdf', incoming)) is None
    pages[1].page_number = 2
    saved.write_bytes(b'modified source')
    db = SimpleNamespace(execute=AsyncMock(return_value=result([existing])))
    assert asyncio.run(documents._verified_completed_upload(db, 'same.pdf', incoming)) is None
    assert db.execute.await_count == 1
    saved.unlink()
    assert asyncio.run(documents._verified_completed_upload(db, 'same.pdf', incoming)) is None


def test_reuse_query_requires_same_filename_hash_and_completed_pdf(tmp_path):
    incoming = tmp_path / 'incoming.pdf'
    incoming.write_bytes(b'original bytes')
    result = SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[]))
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    assert asyncio.run(documents._verified_completed_upload(db, 'same.pdf', incoming)) is None
    query = db.execute.call_args.args[0]
    parameters = query.compile().params
    assert 'same.pdf' in parameters.values()
    assert saved_source_hash(incoming) in parameters.values()
    assert 'completed' in parameters.values() and 'pdf' in parameters.values()
