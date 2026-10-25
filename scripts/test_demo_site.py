"""Exercise a visitor's first request, isolation, expiry and reconnect without credentials."""
import threading
import time

import fakeredis.aioredis
from playwright.sync_api import expect, sync_playwright
import uvicorn

from app.main import Settings, create_app


def main():
    config = Settings(_env_file=None, admin_token='fake-admin-demo-browser-1234',
                      gateway_token='fake-client-demo-browser-5678', public_demo_enabled=True)
    app = create_app(config, store=fakeredis.aioredis.FakeRedis(decode_responses=True))
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8766,
                                         log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError('Demo browser server failed to start')
            time.sleep(0.05)
        else:
            raise RuntimeError('Demo browser server startup timed out')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            first = browser.new_context()
            second = browser.new_context()
            page = first.new_page()
            other = second.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            for tab in [page, other]:
                tab.goto('http://127.0.0.1:8766')
                expect(tab.locator('#demo-entry')).to_be_visible()
                tab.locator('#try-demo').click()
                expect(tab.locator('#connection-status')).to_have_text('免费演示已连接')
                expect(tab.locator('#token')).to_have_value('')
                expect(tab.locator('#requests-count')).to_have_text('0')
            page.locator('#prompt').fill('visitor one example')
            page.locator('#send').click()
            expect(page.locator('#response')).to_contain_text('visitor one example')
            expect(page.locator('#requests-count')).to_have_text('1')
            other.locator('#refresh').click()
            expect(other.locator('#requests-count')).to_have_text('0')
            expect(other.locator('#request-rows')).not_to_contain_text('demo-')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            # Complete cleanup before a new session can replace its cookie.
            page.locator('#disconnect').click()
            page.locator('#try-demo').click()
            expect(page.locator('#connection-status')).to_have_text('免费演示已连接')
            expect(page.locator('#requests-count')).to_have_text('0')
            first.clear_cookies()
            page.locator('#refresh').click()
            expect(page.locator('#error')).to_contain_text('演示已过期')
            expect(page.locator('#send')).to_be_disabled()
            assert not errors
            browser.close()
        print('PASS: credential-free first request, browser isolation, reconnect, expiry and mobile layout')
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
