import asyncio
from unittest.mock import AsyncMock

from backend.services import rag
from backend.services.tools import VectorSearchTool


def test_keyword_only_evidence_does_not_require_or_invent_cosine_similarity(monkeypatch):
    monkeypatch.setattr(rag,'vector_search',AsyncMock(return_value=[dict(
        text='Actual public report evidence',filename='report.pdf',page=1,
        chunk_index=0,source_kind='semantic',similarity=None)]))
    result=asyncio.run(VectorSearchTool().execute('question',session=object()))
    assert result.success
    assert 'sim=N/A' in result.summary
    assert result.data['chunks'][0]['similarity'] is None
    assert 'Actual public report evidence' in result.summary
