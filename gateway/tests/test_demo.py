import json

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from test_gateway import ADMIN_HEADERS, ADMIN, CLIENT, app, settings

BODY = {'messages': [{'role': 'user', 'content': 'private visitor message 123'}]}


def test_demo_is_opt_in_and_rejects_real_provider_configuration():
    with TestClient(app()) as client:
        assert client.get('/api/public-config').json() == {'public_demo_enabled': False}
        assert client.post('/api/demo/session').status_code != 200
    with pytest.raises(ValidationError, match='mock provider') as error:
        settings(public_demo_enabled=True, provider='openai-compatible',
                 upstream_api_key='fake-upstream-key', upstream_model='example')
    assert all(secret not in str(error.value) for secret in [ADMIN, CLIENT, 'fake-upstream-key'])


def test_guest_isolation_and_private_auth_boundaries():
    server = fakeredis.FakeServer()
    with TestClient(app(server, public_demo_enabled=True)) as a, TestClient(app(server, public_demo_enabled=True)) as b:
        assert a.get('/api/demo/overview').status_code == 401
        assert a.post('/api/demo/session').status_code == b.post('/api/demo/session').status_code == 200
        result = a.post('/api/demo/playground', json=BODY)
        assert result.status_code == 200
        assert result.headers['x-cache'] == 'MISS'
        assert '模拟演示' in result.json()['choices'][0]['message']['content']
        assert a.get('/api/demo/overview').json()['stats']['requests'] == 1
        assert b.get('/api/demo/overview').json()['stats']['requests'] == 0
        assert a.get('/api/overview').status_code == 401
        assert a.post('/v1/chat/completions', json=BODY).status_code == 401
        assert a.get('/api/overview', headers=ADMIN_HEADERS).json()['stats']['requests'] == 0
        store = fakeredis.FakeRedis(server=server, decode_responses=True)
        for key in store.scan_iter(match='modeljetty:demo:*'):
            assert 0 < store.ttl(key) <= 900
            value = store.get(key) if store.type(key) == 'string' else store.lrange(key, 0, -1)
            assert BODY['messages'][0]['content'] not in json.dumps(value)
            assert ADMIN not in json.dumps(value) and CLIENT not in json.dumps(value)


def test_cookie_expiry_disconnect_and_cross_origin_protection():
    server = fakeredis.FakeServer()
    with TestClient(app(server, public_demo_enabled=True), base_url='https://preview.test') as client:
        assert client.post('/api/demo/session', headers={'Origin': 'https://attacker.test'}).status_code == 403
        response = client.post('/api/demo/session', headers={'Origin': 'https://preview.test'})
        cookie = response.headers['set-cookie'].lower()
        assert all(flag in cookie for flag in ['httponly', 'secure', 'samesite=strict', 'max-age=900'])
        assert client.post('/api/demo/playground', json=BODY).status_code == 200
        assert client.delete('/api/demo/session').status_code == 200
        assert client.get('/api/demo/overview').status_code == 401
        store = fakeredis.FakeRedis(server=server, decode_responses=True)
        assert not list(store.scan_iter(match='modeljetty:demo:session:*'))
        client.post('/api/demo/session')
        for key in store.scan_iter(match='modeljetty:demo:session:*'):
            store.delete(key)
        assert client.get('/api/demo/overview').status_code == 401


def test_visitor_quota_does_not_call_upstream():
    class ForbiddenUpstream:
        async def post(self, *args, **kwargs):
            raise AssertionError('Public demo must never call an upstream')

    with TestClient(app(public_demo_enabled=True, upstream=ForbiddenUpstream())) as client:
        client.post('/api/demo/session')
        for _ in range(5):
            assert client.post('/api/demo/playground', json=BODY).status_code == 200
        limited = client.post('/api/demo/playground', json=BODY)
        assert limited.status_code == 429 and int(limited.headers['retry-after']) > 0
        assert client.get('/api/demo/overview').json()['stats']['requests'] == 5


def test_session_creation_and_global_work_are_bounded():
    server = fakeredis.FakeServer()
    with TestClient(app(server, public_demo_enabled=True)) as client:
        for _ in range(5):
            assert client.post('/api/demo/session').status_code == 200
        assert client.post('/api/demo/session').status_code == 429
        store = fakeredis.FakeRedis(server=server, decode_responses=True)
        store.set('modeljetty:demo:request-global', '30', ex=60)
        assert client.post('/api/demo/playground', json=BODY).status_code == 429
        assert client.get('/api/demo/overview').json()['stats']['requests'] == 0
        assert 0 < store.ttl('modeljetty:demo:request-global') <= 60
        client.cookies.set('modeljetty_demo', 'f' * 43, path='/api/demo')
        assert client.get('/api/demo/overview').status_code == 401


def test_rejected_visitor_does_not_consume_other_visitors_capacity():
    server = fakeredis.FakeServer()
    store = fakeredis.FakeRedis(server=server, decode_responses=True)
    with TestClient(app(server, public_demo_enabled=True), client=('198.51.100.1', 1234)) as a, \
         TestClient(app(server, public_demo_enabled=True), client=('198.51.100.2', 1234)) as b:
        for _ in range(5):
            assert a.post('/api/demo/session').status_code == 200
        for _ in range(100):
            assert a.post('/api/demo/session').status_code == 429
        assert int(store.get('modeljetty:demo:session-global')) == 5
        assert b.post('/api/demo/session').status_code == 200
        for _ in range(5):
            assert a.post('/api/demo/playground', json=BODY).status_code == 200
        for _ in range(40):
            assert a.post('/api/demo/playground', json=BODY).status_code == 429
        assert int(store.get('modeljetty:demo:request-global')) == 5
        assert b.post('/api/demo/playground', json=BODY).status_code == 200
        assert int(store.get('modeljetty:demo:request-global')) == 6
