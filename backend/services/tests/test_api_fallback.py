"""Unknown API URLs must not masquerade as successful HTML responses."""
import httpx
import asyncio


def test_unknown_api_returns_json_404_and_frontend_still_loads():
    asyncio.run(_exercise_routes())


async def _exercise_routes():
    from backend.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url='http://test') as client:
        for path in ['/api/does-not-exist', '/api', '/api/documents/']:
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json()['detail'] == 'API route not found'
        frontend = await client.get('/some-client-route')
        assert frontend.status_code == 200
        assert 'text/html' in frontend.headers['content-type']
        health = await client.get('/api/health')
        assert health.status_code == 200
        assert health.json()['status'] == 'ok'
