import asyncio
from unittest.mock import AsyncMock
from backend.services import chunker


def test_summaries_embeddings_and_source_offsets_keep_the_same_chunk_binding(monkeypatch):
    parts=['第一 Thai fact','Second Thai fact']
    monkeypatch.setattr(chunker,'semantic_split',AsyncMock(return_value=parts))
    summary=AsyncMock(side_effect=['summary one','summary two'])
    embeddings=AsyncMock(return_value=[[1.0,0.0],[0.0,1.0]])
    monkeypatch.setattr(chunker,'generate_chunk_summary',summary)
    monkeypatch.setattr(chunker,'get_embeddings_batch',embeddings)
    result=asyncio.run(chunker.chunk_document('source'))
    embeddings.assert_awaited_once_with(['summary one\n'+parts[0],'summary two\n'+parts[1]])
    assert [(r.text,r.summary,r.embedding) for r in result]==[(parts[0],'summary one',[1.0,0.0]),(parts[1],'summary two',[0.0,1.0])]
    assert [(r.start_char,r.end_char) for r in result]==[(0,len(parts[0])),(len(parts[0])+1,len(parts[0])+1+len(parts[1]))]


def test_summary_disabled_does_not_generate_or_mix_summary_text(monkeypatch):
    monkeypatch.setattr(chunker,'semantic_split',AsyncMock(return_value=['one','two']))
    summary=AsyncMock();embeddings=AsyncMock(return_value=[[1.0],[2.0]])
    monkeypatch.setattr(chunker,'generate_chunk_summary',summary)
    monkeypatch.setattr(chunker,'get_embeddings_batch',embeddings)
    result=asyncio.run(chunker.chunk_document('source',generate_summaries=False))
    summary.assert_not_awaited();embeddings.assert_awaited_once_with(['one','two'])
    assert [r.summary for r in result]==['','']
