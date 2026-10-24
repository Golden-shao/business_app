"""Isolated browser acceptance checks; uses fake Redis and a mock model only.

PYTHONPATH=gateway python scripts/test_site.py
Set CHROME_EXECUTABLE to use an existing Linux Chrome installation.
"""
import os
from pathlib import Path
import threading
import time

import fakeredis.aioredis
import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

from app.main import Settings, create_app

ADMIN = 'ui-test-admin-token-12345'
CLIENT = 'ui-test-client-token-12345'
BASE = 'http://127.0.0.1:8765'


def check_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get('CHROME_EXECUTABLE'), headless=True,
            args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors, reads, posts = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: reads.append(request.url) if request.url.endswith('/api/overview') else None)
        page.on('request', lambda request: posts.append(request.url) if request.url.endswith('/api/playground') else None)
        page.clock.install()
        page.goto(BASE)
        expect(page.locator('#send')).to_be_disabled()
        page.locator('#token').fill(ADMIN)
        page.locator('#connection-form button[type=submit]').click()
        expect(page.locator('#connection-status')).to_have_text('网关已连接')
        expect(page.locator('#guide-connect')).to_have_class('done')
        for _ in range(2):
            page.locator('#send').click()
            expect(page.locator('#send')).to_be_enabled()
        expect(page.locator('#response-meta')).to_contain_text('CACHE HIT')
        expect(page.locator('#request-rows')).to_contain_text('网站')
        expect(page.locator('#response-id')).to_contain_text('chatcmpl-')

        # An independent caller must appear without pressing Refresh.
        response = httpx.post(BASE + '/v1/chat/completions',
                              headers={'Authorization': 'Bearer ' + CLIENT},
                              json={'messages': [{'role': 'user', 'content': 'external client'}]})
        assert response.status_code == 200
        page.clock.fast_forward(6000)
        expect(page.locator('#requests-count')).to_have_text('3')
        expect(page.locator('#request-rows')).to_contain_text('API')
        expect(page.locator('#guide-linked')).to_have_class('done')
        page.locator('#request-rows details').first.locator('summary').click()
        expect(page.locator('#request-rows code').first).to_have_text(response.json()['id'])
        if artifact_dir := os.environ.get('HARBOR_TEST_ARTIFACT_DIR'):
            Path(artifact_dir).mkdir(parents=True, exist_ok=True)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(Path(artifact_dir) / 'product-desktop.png'), full_page=True)

        # Visibility and the user switch both stop polling, but never resend a POST.
        page.locator('#auto-sync').uncheck()
        before = len(reads)
        page.clock.fast_forward(20000)
        assert len(reads) == before
        page.locator('#auto-sync').check()
        page.evaluate("Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange'))")
        page.clock.fast_forward(20000)
        assert len(reads) == before
        page.evaluate("Object.defineProperty(document, 'hidden', {configurable: true, get: () => false}); document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#connection-status')).to_have_text('网关已连接')

        # A proxy can return HTML for 429/503; the UI must still guide recovery.
        page.route('**/api/playground', lambda route: route.fulfill(
            status=429, body='<html>limited</html>',
            headers={'Retry-After': '2', 'X-Request-ID': 'ui-limited-request'}))
        page.locator('#send').click()
        expect(page.locator('#playground-error')).to_contain_text('ui-limited-request')
        expect(page.locator('#send')).to_be_disabled()
        attempts = len(posts)
        page.clock.fast_forward(3000)
        expect(page.locator('#send')).to_be_enabled()
        assert len(posts) == attempts
        page.unroute('**/api/playground')
        page.route('**/api/overview', lambda route: route.fulfill(status=503, body='<html>unavailable</html>'))
        page.locator('#refresh').click()
        expect(page.locator('#connection-status')).to_contain_text('上次数据')
        expect(page.locator('#error')).to_contain_text('Redis')
        page.unroute('**/api/overview')
        page.locator('#refresh').click()
        expect(page.locator('#connection-status')).to_have_text('网关已连接')

        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#disconnect').click()
        expect(page.locator('#token')).to_have_value('')
        expect(page.locator('#send')).to_be_disabled()
        before = len(reads)
        page.clock.fast_forward(20000)
        assert len(reads) == before
        page.locator('#token').fill('incorrect-admin-token-1234')
        page.locator('#connection-form button[type=submit]').click()
        expect(page.locator('#error')).to_contain_text('ADMIN_TOKEN')
        expect(page.locator('#requests-count')).to_have_text('—')
        assert not errors, errors
        browser.close()


def main():
    config = Settings(_env_file=None, admin_token=ADMIN, gateway_token=CLIENT,
                      provider='mock', rate_limit_per_minute=1000)
    app = create_app(config, store=fakeredis.aioredis.FakeRedis(decode_responses=True))
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8765, log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError('Browser test server could not start; check port 8765')
            time.sleep(0.05)
        else:
            raise RuntimeError('Browser test server startup timed out')
        check_browser()
        print('PASS: onboarding, automatic linkage, pause/resume, cooldown, failure recovery, request IDs, mobile layout')
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
