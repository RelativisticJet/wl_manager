"""Playwright E2E test fixtures for Whitelist Manager.

Browser selection: set WL_E2E_BROWSER to "chromium" (default),
"firefox", or "webkit". The fixtures honor this env var via
getattr(playwright, browser_name). Mirrors the JS-side helper in
lib_helpers.cjs; both must stay in sync if a new browser is added.
"""
import os
import pytest
import time
from typing import Dict, Any
from playwright.sync_api import sync_playwright, Page


def _resolve_browser_engine(playwright):
    """Return the playwright browser engine matching WL_E2E_BROWSER.

    Defaults to chromium. Raises ValueError on unknown values rather
    than silently falling back, so a typo doesn't produce
    "tests pass on chromium when you thought you were on firefox".
    """
    name = os.environ.get("WL_E2E_BROWSER", "chromium").lower()
    if name not in ("chromium", "firefox", "webkit"):
        raise ValueError(
            f"WL_E2E_BROWSER={name!r} not recognized. "
            f"Valid: chromium, firefox, webkit."
        )
    return getattr(playwright, name)


@pytest.fixture(scope="session")
def browser_context_args():
    """Playwright browser configuration for all E2E tests."""
    return {
        "base_url": "http://localhost:8000",
        "ignore_https_errors": True,  # Splunk uses self-signed certs
    }


@pytest.fixture(scope="function")
def browser():
    """Provide Playwright browser with authenticated Splunk context."""
    playwright = sync_playwright().start()
    engine = _resolve_browser_engine(playwright)
    # `--disable-web-resources` is a Chromium-only flag. Firefox and
    # WebKit reject it. Apply only when the engine is chromium.
    launch_args = ['--disable-web-resources'] if engine is playwright.chromium else []
    browser_instance = engine.launch(
        headless=True,
        args=launch_args,
    )
    context = browser_instance.new_context(
        base_url="http://localhost:8000",
        ignore_https_errors=True
    )
    page = context.new_page()

    # Login to Splunk.
    # Selector note: Splunk's login form submits via <input type="submit">,
    # NOT <button>. The prior 'button:has-text("Sign in")' selector never
    # matched, so every test using this fixture silently fell through to a
    # login-page DOM and timed out on app-level locators. Fixed 2026-05-24
    # during the playwright 1.40 → 1.60 baseline (PR #13). The bug was
    # invisible because Python E2E was never CI-gated; only test_wl_save.py
    # passed (it defines its own inline login flow with the right selector).
    try:
        page.goto("http://localhost:8000/en-US/account/login", wait_until="networkidle")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "Chang3d!")
        page.click('input[type="submit"]')
        page.wait_for_url("**/en-US/**", timeout=15000)
    except Exception as e:
        print(f"Login failed: {e}")

    yield page

    context.close()
    browser_instance.close()
    playwright.stop()


@pytest.fixture(scope="function")
def admin_browser():
    """Provide a second browser instance for admin user in multi-user tests."""
    playwright = sync_playwright().start()
    engine = _resolve_browser_engine(playwright)
    # `--disable-web-resources` is a Chromium-only flag. Firefox and
    # WebKit reject it. Apply only when the engine is chromium.
    launch_args = ['--disable-web-resources'] if engine is playwright.chromium else []
    browser_instance = engine.launch(
        headless=True,
        args=launch_args,
    )
    context = browser_instance.new_context(
        base_url="http://localhost:8000",
        ignore_https_errors=True
    )
    page = context.new_page()

    # Login as admin (same user, but separate browser session).
    # See selector note on the `browser` fixture above — same fix.
    try:
        page.goto("http://localhost:8000/en-US/account/login", wait_until="networkidle")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "Chang3d!")
        page.click('input[type="submit"]')
        page.wait_for_url("**/en-US/**", timeout=15000)
    except Exception as e:
        print(f"Admin login failed: {e}")

    yield page

    context.close()
    browser_instance.close()
    playwright.stop()


@pytest.fixture(scope="function")
def rest_client():
    """Provide REST API client for test data setup/teardown."""
    import requests
    from requests.auth import HTTPBasicAuth
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    base_url = "https://localhost:8089/servicesNS/nobody/wl_manager/custom/wl_manager"
    auth = HTTPBasicAuth("admin", "Chang3d!")

    class RestClient:
        def get_action(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
            """Execute GET action via REST API."""
            url = f"{base_url}?action={action}"
            try:
                resp = requests.get(url, params=params, auth=auth, verify=False, timeout=10)
                return resp.json()
            except Exception as e:
                print(f"GET {action} failed: {e}")
                return {"success": False, "error": str(e)}

        def post_action(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
            """Execute POST action via REST API."""
            url = f"{base_url}?action={action}"
            try:
                resp = requests.post(url, json=data, auth=auth, verify=False, timeout=10)
                return resp.json()
            except Exception as e:
                print(f"POST {action} failed: {e}")
                return {"success": False, "error": str(e)}

        def search_audit(self, query: str) -> list:
            """Search audit index and return matching events."""
            search_url = "https://localhost:8089/services/search/jobs"
            auth_local = ("admin", "Chang3d!")
            try:
                # Create search job
                resp = requests.post(
                    search_url,
                    data={"search": f"index=wl_audit {query}"},
                    auth=auth_local,
                    verify=False,
                    timeout=10
                )
                job_id = resp.json()['sid']

                # Poll for results
                results_url = f"{search_url}/{job_id}/results"
                for _ in range(30):  # 30 second timeout
                    resp = requests.get(
                        results_url,
                        params={"output_mode": "json"},
                        auth=auth_local,
                        verify=False,
                        timeout=10
                    )
                    data = resp.json()
                    if data['results']:
                        return data['results']
                    time.sleep(1)
                return []
            except Exception as e:
                print(f"Audit search failed: {e}")
                return []

    return RestClient()
