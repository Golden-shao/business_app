"""Opt-in mock-only visitor experience, isolated from private gateway state."""
import hashlib
import json
import secrets
import time
import uuid

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Literal

COOKIE = 'modeljetty_demo'
TTL = 900
PREFIX = 'modeljetty:demo:'
WINDOW = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return {n, redis.call('TTL', KEYS[1])}
"""


class DemoMessage(BaseModel):
    role: Literal['user']
    content: str = Field(min_length=1, max_length=2000)


class DemoPrompt(BaseModel):
    model: Literal['gateway-default'] = 'gateway-default'
    messages: list[DemoMessage] = Field(min_length=1, max_length=1)


async def limit(store, key, maximum):
    count, retry = await store.eval(WINDOW, 1, PREFIX + key)
    if count > maximum:
        raise HTTPException(429, 'Demo capacity reached', headers={'Retry-After': str(max(1, retry))})


def register_demo(app):
    def same_origin(request):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Use the same-origin demo website')

    async def session(request):
        token = request.cookies.get(COOKIE, '')
        if not 32 <= len(token) <= 64:
            raise HTTPException(401, 'Start a new demo session')
        digest = hashlib.sha256(token.encode()).hexdigest()
        remaining = await request.app.state.store.ttl(PREFIX + 'session:' + digest)
        if remaining <= 0:
            raise HTTPException(401, 'Demo session expired')
        return PREFIX + digest + ':', remaining

    @app.post('/api/demo/session')
    async def start(request: Request, response: Response):
        same_origin(request)
        store = request.app.state.store
        ip = request.client.host if request.client else 'unknown'
        await limit(store, 'session-global', 100)
        await limit(store, 'session-ip:' + hashlib.sha256(ip.encode()).hexdigest(), 5)
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        await store.set(PREFIX + 'session:' + digest, '1', ex=TTL)
        response.set_cookie(COOKIE, token, max_age=TTL, httponly=True,
                            secure=request.url.scheme == 'https', samesite='strict', path='/api/demo')
        response.headers['Cache-Control'] = 'no-store'
        return {'provider': 'mock', 'expires_in': TTL}

    @app.get('/api/demo/overview')
    async def overview(request: Request, response: Response):
        prefix, remaining = await session(request)
        store = request.app.state.store
        async with store.pipeline(transaction=True) as pipe:
            pipe.get(prefix + 'count')
            pipe.lrange(prefix + 'events', 0, 19)
            count, events = await pipe.execute()
        response.headers['Cache-Control'] = 'no-store'
        return {'version': '0.1.1', 'provider': 'mock', 'public_demo': True,
                'expires_in': remaining, 'rate_limit_per_minute': 5, 'cache_ttl_seconds': 0,
                'stats': {'requests': int(count or 0), 'errors': 0, 'cache_hits': 0, 'average_latency_ms': 0},
                'recent_requests': [json.loads(event) for event in events]}

    @app.post('/api/demo/playground')
    async def playground(body: DemoPrompt, request: Request, response: Response):
        same_origin(request)
        prefix, remaining = await session(request)
        store = request.app.state.store
        await limit(store, 'request-global', 30)
        await limit(store, prefix.removeprefix(PREFIX) + 'rate', 5)
        request_id = 'demo-' + uuid.uuid4().hex
        event = {'id': request_id, 'time': int(time.time()), 'status': 200, 'latency_ms': 0,
                 'cached': False, 'provider': 'mock', 'served_by': 'public-demo', 'source': 'web'}
        # Only metadata is stored. No private stats, prompts, replies, cache, or upstream client.
        async with store.pipeline(transaction=True) as pipe:
            pipe.incr(prefix + 'count')
            pipe.expire(prefix + 'count', remaining)
            pipe.lpush(prefix + 'events', json.dumps(event))
            pipe.ltrim(prefix + 'events', 0, 19)
            pipe.expire(prefix + 'events', remaining)
            await pipe.execute()
        response.headers.update({'X-Request-ID': request_id, 'X-Cache': 'MISS', 'Cache-Control': 'no-store'})
        return {'id': request_id, 'object': 'chat.completion', 'model': body.model,
                'choices': [{'index': 0, 'message': {'role': 'assistant',
                    'content': '【免费模拟演示 · 没有调用真实模型】\n已收到：' + body.messages[0].content[:500]
                    + '\n\n你已完成一次网关请求。下方记录只属于当前浏览器，不保存消息正文。'},
                    'finish_reason': 'stop'}]}

    @app.delete('/api/demo/session')
    async def end(request: Request, response: Response):
        same_origin(request)
        prefix, _ = await session(request)
        digest = prefix.removeprefix(PREFIX).removesuffix(':')
        await request.app.state.store.delete(PREFIX + 'session:' + digest, prefix + 'count',
                                             prefix + 'events', prefix + 'rate')
        response.delete_cookie(COOKIE, path='/api/demo', secure=request.url.scheme == 'https',
                               httponly=True, samesite='strict')
        return {'disconnected': True}
