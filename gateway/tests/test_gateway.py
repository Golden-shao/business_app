import concurrent.futures
import json

import fakeredis
import fakeredis.aioredis
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app

ADMIN = 'admin-test-credentials-1234'
CLIENT = 'client-test-credentials-5678'
ADMIN_HEADERS = {'Authorization': f'Bearer {ADMIN}'}
CLIENT_HEADERS = {'Authorization': f'Bearer {CLIENT}'}
BODY = {'model': 'gateway-default', 'messages': [{'role': 'user', 'content': 'hello harbor'}]}


def settings(**kwargs):
    return Settings(_env_file=None, admin_token=ADMIN, gateway_token=CLIENT, **kwargs)


def app(server=None, upstream=None, **kwargs):
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    return create_app(settings(**kwargs), store=redis, upstream=upstream)


def test_auth_roles_and_public_probes():
    with TestClient(app()) as client:
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').status_code == 200
        assert client.get('/api/overview').status_code == 401
        assert client.get('/api/overview', headers=CLIENT_HEADERS).status_code == 401
        assert client.post('/v1/chat/completions', headers=ADMIN_HEADERS, json=BODY).status_code == 401
        assert client.get('/v1/models', headers=CLIENT_HEADERS).json()['data'][0]['id'] == 'gateway-default'


def test_mock_cache_and_shared_state_across_replicas():
    server = fakeredis.FakeServer()
    with TestClient(app(server)) as first, TestClient(app(server)) as second:
        a = first.post('/v1/chat/completions', headers=CLIENT_HEADERS, json=BODY)
        b = second.post('/api/playground', headers=ADMIN_HEADERS, json=BODY)
        assert a.status_code == b.status_code == 200
        assert a.headers['x-cache'] == 'MISS'
        assert b.headers['x-cache'] == 'HIT'
        assert a.json()['id'] != b.json()['id']
        assert '模拟' in b.json()['choices'][0]['message']['content']
        summary = second.get('/api/overview', headers=ADMIN_HEADERS).json()
        assert summary['stats']['requests'] == 2
        assert summary['stats']['cache_hits'] == 1
        assert len(summary['recent_requests']) == 2
        assert 'hello harbor' not in json.dumps(summary)
        assert ADMIN not in json.dumps(summary)
        metrics = first.get('/metrics', headers=ADMIN_HEADERS)
        assert 'harbor_requests_total 2' in metrics.text


def test_rate_limit_is_shared_and_retry_after_is_present():
    server = fakeredis.FakeServer()
    with TestClient(app(server, rate_limit_per_minute=1)) as first, TestClient(app(server, rate_limit_per_minute=1)) as second:
        assert first.post('/v1/chat/completions', headers=CLIENT_HEADERS, json=BODY).status_code == 200
        denied = second.post('/api/playground', headers=ADMIN_HEADERS, json=BODY)
        assert denied.status_code == 429
        assert 1 <= int(denied.headers['retry-after']) <= 60
        summary = first.get('/api/overview', headers=ADMIN_HEADERS).json()
        assert summary['stats']['errors'] == 1
        assert summary['recent_requests'][0]['id'] == denied.headers['x-request-id']


def test_concurrent_rate_limit_is_atomic():
    with TestClient(app(rate_limit_per_minute=3)) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            codes = list(executor.map(lambda _: client.post('/v1/chat/completions', headers=CLIENT_HEADERS, json=BODY).status_code, range(12)))
        assert codes.count(200) == 3
        assert codes.count(429) == 9


def test_invalid_streaming_model_and_oversized_payload():
    with TestClient(app()) as client:
        for override in [{'stream': True}, {'model': 'unknown'}, {'messages': []}]:
            assert client.post('/v1/chat/completions', headers=CLIENT_HEADERS, json={**BODY, **override}).status_code == 422
        assert client.post('/v1/chat/completions', headers=CLIENT_HEADERS, content='x' * 65537).status_code == 413


def test_redis_outage_fails_closed_but_liveness_survives():
    server = fakeredis.FakeServer()
    with TestClient(app(server)) as client:
        server.connected = False
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').status_code == 503
        assert client.post('/v1/chat/completions', headers=CLIENT_HEADERS, json=BODY).status_code == 503


@pytest.mark.parametrize('status', [200, 401, 500])
def test_real_provider_mapping_and_errors_are_sanitized(status):
    def handler(request):
        assert request.url == 'https://provider.example/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer upstream-secret'
        assert json.loads(request.content)['model'] == 'real-model'
        if status != 200:
            return httpx.Response(status, json={'error': 'sensitive upstream detail'})
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': 'real reply'}}]})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with TestClient(app(upstream=upstream, provider='openai-compatible', upstream_base_url='https://provider.example/v1',
                        upstream_api_key='upstream-secret', upstream_model='real-model')) as client:
        response = client.post('/v1/chat/completions', headers=CLIENT_HEADERS, json=BODY)
        if status == 200:
            assert response.status_code == 200
            assert response.json()['model'] == 'gateway-default'
            assert response.json()['choices'][0]['message']['content'] == 'real reply'
        else:
            assert response.status_code == 502
            assert 'sensitive' not in response.text
            assert 'upstream-secret' not in response.text


def test_website_and_cors():
    with TestClient(app()) as client:
        assert 'ModelJetty' in client.get('/').text
        assert client.get('/app.js').status_code == 200
        allowed = client.options('/api/overview', headers={'Origin': 'http://localhost:7357',
                                  'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'Authorization'})
        assert allowed.headers['access-control-allow-origin'] == 'http://localhost:7357'
        denied = client.options('/api/overview', headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'GET'})
        assert 'access-control-allow-origin' not in denied.headers


def test_client_source_is_bounded_and_does_not_change_cache_scope():
    with TestClient(app()) as client:
        for path, extra in [('/api/playground', {}),
                            ('/api/playground', {'X-Harbor-Client': 'flutter'}),
                            ('/v1/chat/completions', {'X-Harbor-Client': 'flutter'})]:
            headers = CLIENT_HEADERS if path.startswith('/v1/') else ADMIN_HEADERS
            response = client.post(path, headers={**headers, **extra}, json=BODY)
            assert response.status_code == 200
        summary = client.get('/api/overview', headers=ADMIN_HEADERS).json()
        assert [r['source'] for r in summary['recent_requests']] == ['api', 'app', 'web']
        assert summary['stats']['cache_hits'] == 2
        client.post('/api/playground', headers={**ADMIN_HEADERS, 'X-Harbor-Client': '<script>'}, json=BODY)
        assert client.get('/api/overview', headers=ADMIN_HEADERS).json()['recent_requests'][0]['source'] == 'web'


def test_flutter_can_read_rate_limit_headers_across_origins():
    with TestClient(app(rate_limit_per_minute=1)) as client:
        headers = {**ADMIN_HEADERS, 'Origin': 'http://localhost:7357', 'X-Harbor-Client': 'flutter'}
        preflight = client.options('/api/playground', headers={
            'Origin': 'http://localhost:7357', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Authorization, Content-Type, X-Harbor-Client'})
        assert preflight.status_code == 200
        client.post('/api/playground', headers=headers, json=BODY)
        limited = client.post('/api/playground', headers=headers, json=BODY)
        assert limited.status_code == 429
        assert 'Retry-After' in limited.headers['access-control-expose-headers']
        assert limited.headers['x-request-id']
