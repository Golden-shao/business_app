"""A small, single-tenant gateway. All mutable shared state lives in Redis."""
import hashlib
import hmac
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    admin_token: str = Field(min_length=16)
    gateway_token: str = Field(min_length=16)
    redis_url: str = 'redis://localhost:6379/0'
    provider: Literal['mock', 'openai-compatible'] = 'mock'
    upstream_base_url: str = 'https://api.openai.com/v1'
    upstream_api_key: str = ''
    upstream_model: str = ''
    rate_limit_per_minute: int = Field(default=30, ge=1, le=10000)
    cache_ttl_seconds: int = Field(default=60, ge=0, le=3600)
    cors_origins: list[str] = ['http://localhost:7357']

    @model_validator(mode='after')
    def validate_provider(self):
        if hmac.compare_digest(self.admin_token, self.gateway_token):
            raise ValueError('ADMIN_TOKEN and GATEWAY_TOKEN must differ')
        if self.provider == 'openai-compatible':
            if not self.upstream_api_key or not self.upstream_model:
                raise ValueError('Real providers require UPSTREAM_API_KEY and UPSTREAM_MODEL')
            if not self.upstream_base_url.startswith('https://'):
                raise ValueError('Real providers require an HTTPS upstream URL')
        return self


class Message(BaseModel):
    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1, max_length=12000)


class Completion(BaseModel):
    model: Literal['gateway-default'] = 'gateway-default'
    messages: list[Message] = Field(min_length=1, max_length=20)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=256, ge=1, le=2048)
    stream: Literal[False] = False


bearer = HTTPBearer(auto_error=False)
LIMIT_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return {n, redis.call('TTL', KEYS[1])}
"""


def create_app(settings: Settings | None = None, store=None, upstream=None):
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store or Redis.from_url(config.redis_url, decode_responses=True,
                                                 socket_connect_timeout=2, socket_timeout=2)
        app.state.upstream = upstream or httpx.AsyncClient(timeout=30, follow_redirects=False)
        yield
        if store is None:
            await app.state.store.aclose()
        if upstream is None:
            await app.state.upstream.aclose()

    app = FastAPI(title='ModelJetty AI Gateway', version='0.1.1', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins,
                       allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type', 'X-Harbor-Client'],
                       expose_headers=['X-Cache', 'X-Request-ID', 'Retry-After'])

    def auth(expected):
        async def check(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
            if not credentials or not hmac.compare_digest(credentials.credentials.encode(), expected.encode()):
                raise HTTPException(401, 'Invalid access token', headers={'WWW-Authenticate': 'Bearer'})
        return check

    admin = auth(config.admin_token)
    client = auth(config.gateway_token)

    @app.middleware('http')
    async def size_limit(request, call_next):
        if request.method == 'POST':
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return JSONResponse({'detail': 'Request body exceeds 64 KiB'}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith(('/api/', '/v1/')):
            response.headers['Cache-Control'] = 'no-store'
        if request_id := getattr(request.state, 'request_id', None):
            response.headers['X-Request-ID'] = request_id
        return response

    @app.exception_handler(RedisError)
    async def redis_unavailable(request, exc):
        return JSONResponse({'detail': 'Shared state unavailable; retry shortly'}, status_code=503)

    @app.get('/health/live')
    async def live():
        return {'status': 'alive'}

    @app.get('/health/ready')
    async def ready(request: Request):
        await request.app.state.store.ping()
        return {'status': 'ready'}

    async def record(redis, request_id, code, elapsed, cached, source):
        event = {'id': request_id, 'time': int(time.time()), 'status': code,
                 'latency_ms': elapsed, 'cached': cached, 'provider': config.provider,
                 'served_by': os.getenv('HOSTNAME', 'local'), 'source': source}
        # No prompts, replies, API keys or token values are stored in request logs.
        async with redis.pipeline(transaction=True) as pipe:
            pipe.hincrby('harbor:stats', 'requests', 1)
            pipe.hincrby('harbor:stats', 'errors' if code >= 400 else 'successes', 1)
            pipe.hincrby('harbor:stats', 'latency_ms', elapsed)
            pipe.hincrby('harbor:stats', 'cache_hits', int(cached))
            pipe.lpush('harbor:requests', json.dumps(event))
            pipe.ltrim('harbor:requests', 0, 99)
            await pipe.execute()

    async def complete(body, request, response):
        redis = request.app.state.store
        started = time.monotonic()
        request_id = 'chatcmpl-' + uuid.uuid4().hex
        request.state.request_id = request_id
        source = ('api' if request.url.path.startswith('/v1/') else
                  'app' if request.headers.get('X-Harbor-Client') == 'flutter' else 'web')
        code, cached = 200, False
        try:
            count, retry = await redis.eval(LIMIT_SCRIPT, 1, 'harbor:rate:single-tenant')
            if count > config.rate_limit_per_minute:
                raise HTTPException(429, 'Rate limit exceeded', headers={'Retry-After': str(max(1, retry))})
            serialized = body.model_dump_json()
            # Provider/model included to prevent reuse across provider configuration changes.
            scope = config.provider + config.upstream_base_url + config.upstream_model + config.upstream_api_key + serialized
            cache_key = 'harbor:cache:' + hashlib.sha256(scope.encode()).hexdigest()
            value = await redis.get(cache_key) if config.cache_ttl_seconds else None
            if value:
                result, cached = json.loads(value), True
            elif config.provider == 'mock':
                prompt = next((m.content for m in reversed(body.messages) if m.role == 'user'), '')
                result = {'object': 'chat.completion', 'model': body.model,
                          'choices': [{'index': 0, 'message': {'role': 'assistant',
                          'content': '【本地模拟回复，无真实模型调用】\n已收到：' + prompt[:500] +
                          '\n\n请求已通过网关，可在网站或 App 刷新查看共享记录。'}, 'finish_reason': 'stop'}]}
            else:
                payload = body.model_dump()
                payload['model'] = config.upstream_model
                try:
                    res = await request.app.state.upstream.post(
                        config.upstream_base_url.rstrip('/') + '/chat/completions',
                        headers={'Authorization': 'Bearer ' + config.upstream_api_key}, json=payload)
                    res.raise_for_status()
                    result = res.json()
                    if not isinstance(result.get('choices'), list) or not result['choices']:
                        raise ValueError('Missing completion choices')
                except (httpx.HTTPError, ValueError, AttributeError):
                    raise HTTPException(502, 'Upstream request failed') from None
                result['model'] = body.model
            if not cached and config.cache_ttl_seconds:
                await redis.set(cache_key, json.dumps(result), ex=config.cache_ttl_seconds)
            result.update(id=request_id, created=int(time.time()))
            response.headers['X-Request-ID'] = request_id
            response.headers['X-Cache'] = 'HIT' if cached else 'MISS'
            return result
        except HTTPException as exc:
            code = exc.status_code
            raise
        finally:
            await record(redis, request_id, code, round((time.monotonic() - started) * 1000), cached, source)

    @app.post('/v1/chat/completions', dependencies=[Depends(client)])
    async def completions(body: Completion, request: Request, response: Response):
        return await complete(body, request, response)

    @app.post('/api/playground', dependencies=[Depends(admin)])
    async def playground(body: Completion, request: Request, response: Response):
        return await complete(body, request, response)

    @app.get('/v1/models', dependencies=[Depends(client)])
    async def models():
        return {'object': 'list', 'data': [{'id': 'gateway-default', 'object': 'model', 'owned_by': 'harbor'}]}

    @app.get('/api/overview', dependencies=[Depends(admin)])
    async def overview(request: Request):
        redis = request.app.state.store
        await redis.ping()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.hgetall('harbor:stats')
            pipe.lrange('harbor:requests', 0, 19)
            stats, events = await pipe.execute()
        values = {k: int(v) for k, v in stats.items()}
        total = values.get('requests', 0)
        return {'version': '0.1.1', 'provider': config.provider, 'served_by': os.getenv('HOSTNAME', 'local'),
                'rate_limit_per_minute': config.rate_limit_per_minute, 'cache_ttl_seconds': config.cache_ttl_seconds,
                'stats': {'requests': total, 'errors': values.get('errors', 0),
                          'cache_hits': values.get('cache_hits', 0),
                          'average_latency_ms': round(values.get('latency_ms', 0) / total) if total else 0},
                'recent_requests': [json.loads(e) for e in events]}

    @app.get('/metrics', dependencies=[Depends(admin)])
    async def metrics(request: Request):
        values = await request.app.state.store.hgetall('harbor:stats')
        lines = []
        for key in ['requests', 'errors', 'cache_hits']:
            name = f'harbor_{key}_total'
            lines.extend([f'# TYPE {name} counter', f'{name} {int(values.get(key, 0))}'])
        return Response('\n'.join(lines) + '\n', media_type='text/plain; version=0.0.4')

    website = Path(__file__).resolve().parents[2] / 'site'
    if website.is_dir():
        app.mount('/', StaticFiles(directory=website, html=True), name='website')
    return app
