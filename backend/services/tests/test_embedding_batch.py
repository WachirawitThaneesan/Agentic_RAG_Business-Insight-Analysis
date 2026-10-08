import json
import asyncio
import httpx
import pytest
from backend.services import embedding


def mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(embedding.httpx, 'AsyncClient',
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_batched_embeddings_keep_input_order_across_request_boundary(monkeypatch):
    calls = []
    def handle(request):
        payload = json.loads(request.content); calls.append(payload['input'])
        return httpx.Response(200, json={'embeddings': [[float(t), 1.0] for t in payload['input']]})
    mock_client(monkeypatch, handle)
    texts = [str(i) for i in range(25)]
    assert asyncio.run(embedding.get_embeddings_batch(texts)) == [[float(i), 1.0] for i in range(25)]
    assert [len(c) for c in calls] == [12, 12, 1]


def test_older_server_fallback_uses_same_model_and_text_order(monkeypatch):
    seen = []
    def handle(request):
        payload = json.loads(request.content); seen.append((request.url.path, payload))
        if request.url.path.endswith('/embed'):
            return httpx.Response(404)
        return httpx.Response(200, json={'embedding': [float(payload['prompt']), 1.0]})
    mock_client(monkeypatch, handle)
    assert asyncio.run(embedding.get_embeddings_batch(['1','2'])) == [[1.0,1.0],[2.0,1.0]]
    assert all(p['model'] == embedding.settings.EMBED_MODEL for _,p in seen)
    assert [p['prompt'] for path,p in seen if path.endswith('/embeddings')] == ['1','2']


@pytest.mark.parametrize('vectors', [[[1.0]], [[1.0],[2.0,3.0]], [[True],[2.0]]])
def test_incomplete_or_invalid_vectors_fail_instead_of_shifted_mapping(monkeypatch,vectors):
    mock_client(monkeypatch, lambda request: httpx.Response(200,json={'embeddings':vectors}))
    with pytest.raises(ValueError):
        asyncio.run(embedding.get_embeddings_batch(['one','two']))


def test_empty_batch_does_not_dispatch_and_server_failure_does_not_fallback(monkeypatch):
    seen=[]
    def handle(request):
        seen.append(request.url.path);return httpx.Response(500)
    mock_client(monkeypatch,handle)
    assert asyncio.run(embedding.get_embeddings_batch([])) == []
    assert not seen
    with pytest.raises(httpx.HTTPStatusError):asyncio.run(embedding.get_embedding('one'))
    assert seen == ['/api/embed']
