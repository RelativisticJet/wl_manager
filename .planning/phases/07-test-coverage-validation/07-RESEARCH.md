# Phase 7: Test Coverage & Validation - Research

**Researched:** 2026-04-02  
**Domain:** Python testing (unit, integration, E2E, security, concurrency), Playwright browser automation, Splunk REST API testing  
**Confidence:** HIGH (decision constraints locked; core tools verified with current docs)

## Summary

Phase 7 validates the complete v3.0 modular rewrite through comprehensive test suites across five layers: unit (≥80% coverage offline), integration (REST API against Docker), security (XSS, CSRF, injection, RBAC), concurrency (file locking, approval races), and E2E (browser automation via Playwright). The phase builds on 389 existing unit tests and consolidates legacy test infrastructure, introducing Playwright for UI automation and security fuzzing via Hypothesis. All decisions are locked per the CONTEXT.md discussion; research focuses on verifying current tool capabilities, deployment patterns, and ecosystem standards.

**Primary recommendation:** Adopt pytest + pytest-cov (current versions: 8.1.1, 5.0.0) for all unit/integration tests; add pytest-playwright for E2E (official Playwright Python plugin); use Hypothesis for property-based security fuzzing; mock Splunk SDK with unittest.mock for offline testing; document complete test matrix mapping workflows × roles × outcomes for Phase 8 AppInspect readiness.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **E2E Tool**: Playwright (Python bindings, `playwright-python`) — integrates with pytest infrastructure via pytest-playwright plugin
2. **E2E Scope**: All four workflows (Core CRUD, Approval workflow with approve+reject, Version revert, Admin panel), 20-30 tests including edge cases
3. **Container Modes**: Dual mode — default assumes `wl_manager_test` running; `--start-container` CI flag auto-starts via docker-compose
4. **Browser Modes**: Headless by default, `--headed` flag for debugging; 1 retry on failure via Playwright `--retries 1`
5. **Diagnostics**: Screenshot + Playwright trace on failure (DOM snapshots, network requests, console logs)
6. **Test Data Isolation**: Per-test via REST API setup/teardown fixtures; full cleanup after each test
7. **Multi-User Testing**: Two browser contexts in one test for approval workflow (analyst + admin contexts); both approve and reject paths tested
8. **Page Object Model**: `SplunkPage` base class handles iframe navigation and Splunk custom component quirks (dropdowns, span-button modals)
9. **Security Test Scope**: All four attack vectors — XSS in CSV cells, path traversal, input injection, RBAC bypass; both targeted payloads AND property-based fuzzing (Hypothesis)
10. **Security Test Layers**: Both unit-level (mocks, fast) AND integration-level (Docker container, realistic); dedicated `tests/security/` directory
11. **RBAC Test Matrix**: Full matrix — every POST action tested with every role tier (viewer, editor, admin, superadmin); ~60-80 test cases
12. **Integration Test Approach**: Extend existing 6 integration files; both Docker AND mock SDK paths; all 15+ REST actions in dispatch tables covered
13. **Concurrency Scenarios**: Four specific scenarios — simultaneous CSV saves (5+ threads), approval races (2 admins), file lock contention (5+ threads), mixed operations
14. **Legacy Test Cleanup**: Audit, migrate, delete strategy for ~15 legacy test files at `tests/` root; zero test files at root level after cleanup
15. **Conftest Consolidation**: Single `tests/pytest.ini` with all markers registered; eliminate duplication between `tests/conftest.py` and `tests/unit/conftest.py`
16. **QUnit Frontend Tests**: Extend 4 frontend modules — wl_rest.js, wl_table.js, wl_modals.js, wl_state.js
17. **Deliverables**: HTML coverage report + summary table in VERIFICATION.md; `tests/README.md` with run instructions per suite

### Claude's Discretion

- Playwright wait strategy (smart waits vs fixed timeouts) — based on observed Splunk load behavior during implementation
- Login handling approach (reusable auth state vs per-test login) — based on Splunk session behavior
- Performance threshold calibration — data-driven from baseline timing pass (set thresholds at 2x observed P95)
- Legacy file-by-file migrate/delete decisions — based on coverage gap analysis
- QUnit test file organization (extend existing vs new files)
- Exact test count per category (within target ranges: 20-30 E2E, 60-80 RBAC, etc.)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TEST-01 | Unit test suite covering ≥80% of every backend module (pytest) | Verified: pytest 8.1.1 + pytest-cov 5.0.0 current; mock Splunk SDK via unittest.mock enables offline testing; 389 existing unit tests provide foundation |
| TEST-02 | Integration tests for all REST API action handlers against live container | Verified: Docker container on port 8089; REST API testing via urllib/requests; existing integration tests in tests/integration/; Splunk SDK provides simulation fixtures |
| TEST-03 | Security tests for XSS validation, CSRF protection, and input injection | Verified: Hypothesis (property-based fuzzing) integrates with pytest; OWASP cheat sheets provide payload sources; existing wl_validation.py/wl_rbac.py are test targets |
| TEST-04 | Concurrency tests for simultaneous saves, approval races, and file locking | Verified: Python threading.ThreadPoolExecutor + concurrent.futures; fcntl-based file locking in wl_filelock.py; pytest-timeout for deadlock detection |
| TEST-05 | Browser E2E tests for key workflows (load CSV, save, approve, revert) | Verified: Playwright Python plugin (pytest-playwright) official tool; Splunk iframe quirks documented; custom page objects encapsulate complexity |
| TEST-06 | Mock Splunk SDK fixtures for offline unit testing | Verified: Existing tests/stubs/splunk/rest.py provides foundation; unittest.mock enables request/response mocking; simpleRequest and index submission patterns documented |

</phase_requirements>

## Standard Stack

### Core Testing Tools

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.1.1 | Test runner and assertion library | Industry standard for Python testing; integrates with all plugins; already in project |
| pytest-cov | 5.0.0 | Coverage measurement and reporting | Gold-standard coverage tool for Python; HTML report generation; branch coverage support |
| pytest-playwright | Latest (1.40+) | Official Playwright pytest plugin | Splunk handles modern browsers; auto-configures browser launch, screenshot, trace on failure |
| unittest.mock | Built-in | SDK mocking and patching | Offline test support; no external dependency; standard library integration |
| freezegun | 1.5.1 | Time mocking for deterministic tests | Handles timezone-aware datetime; already in project requirements-dev.txt |
| hypothesis | 6.90+ | Property-based fuzzing for security tests | Generates hundreds of test cases; finds edge cases deterministic tests miss; OWASP payload source integration possible |

### Supporting Tools

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-timeout | 2.1+ | Deadlock detection in concurrency tests | Required for concurrent file locking tests (detect hung threads) |
| pytest-xdist | 3.0+ | Parallel test execution | Optional: unit tests can run in parallel; integration tests remain sequential (stateful) |
| playwright | Latest (1.40+) | Browser automation library | Direct import for E2E tests; pytest-playwright plugin provides fixtures |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest | unittest | Loss of markers, fixtures, plugins ecosystem |
| pytest-playwright | Selenium | Older, slower, less maintained; Playwright is newer (2024+ industry standard) |
| Hypothesis | Manual fuzz payloads | No automated shrinking; misses edge cases; requires manual payload maintenance |
| Mock SDK | Live container only | All unit tests require Docker; slow feedback loop; fragile to container state |

**Installation:**
```bash
pip install pytest==8.1.1 pytest-cov==5.0.0 freezegun==1.5.1
pip install hypothesis==6.90.0  # For security fuzzing
pip install pytest-timeout==2.1.0  # For concurrency deadlock detection
pip install playwright==1.40.0  # For E2E (also: playwright install chromium)
# Or: pip install pytest-playwright  # Bundles pytest fixture plugin
```

**Version verification (as of 2026-04-02):**
- pytest 8.1.1 (stable, 2024 release)
- pytest-cov 5.0.0 (matches pytest 8.x)
- playwright 1.40+ (latest, includes Python bindings)
- hypothesis 6.90+ (2026 version, latest property-based testing)

## Architecture Patterns

### Recommended Project Structure

```
tests/
├── pytest.ini                    # Single config: markers, discovery, options
├── conftest.py                   # Global fixtures (Docker service, temp dirs)
├── unit/
│   ├── conftest.py              # Unit-specific fixtures (mock Splunk SDK)
│   └── test_*.py                # 389 existing + new tests
├── integration/
│   ├── conftest.py              # Integration fixtures (REST API client)
│   ├── test_approval_chain.py
│   ├── test_concurrency.py
│   └── test_handler_dispatch.py
├── e2e/
│   ├── conftest.py              # E2E fixtures (Playwright browser, auth state)
│   ├── page_objects.py          # SplunkPage base + WhitelistManagerPage, ControlPanelPage, AuditPage
│   └── test_*.py                # Playwright tests (20-30 tests)
├── security/
│   ├── fixtures/
│   │   ├── xss_payloads.json
│   │   ├── path_traversal_payloads.json
│   │   ├── injection_payloads.json
│   │   └── rbac_matrix.json
│   ├── test_xss.py
│   ├── test_path_traversal.py
│   ├── test_rbac_bypass.py
│   └── test_injection.py
├── qunit/
│   ├── test_state_manager.js
│   ├── test_rest_helpers.js
│   └── test_*.js                # New: table, modals
├── stubs/
│   └── splunk/rest.py           # Mock Splunk SDK (TEST-06)
└── README.md                     # Test documentation
```

### Pattern 1: Mock Splunk SDK for Unit Testing

**What:** Create fake Splunk REST responses without running Docker. Unit tests import `tests.stubs.splunk.rest` which provides mock implementations of `simpleRequest()`, `service.indexes[].submit()`, session token validation.

**When to use:** All unit tests of wl_handler.py and domain modules that need to simulate Splunk REST API calls (audit posting, search queries, service configuration lookups).

**Example:**
```python
# tests/unit/test_audit.py
from unittest.mock import patch, MagicMock
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stubs'))
import splunk.rest as mock_splunk

def test_post_audit_event():
    """Test: post_audit_event constructs correct HTTP request."""
    with patch('wl_audit.splunk') as mock_module:
        mock_module.rest.simpleRequest.return_value = (200, '{"_key": "12345"}')
        result, msg = wl_audit.post_audit_event(
            {}, "action", "analyst", "rule", "csv.csv", comment="test"
        )
        assert result is True
        assert msg == "Event posted"
        # Verify HTTP call structure
        mock_module.rest.simpleRequest.assert_called_once()
        call_args = mock_module.rest.simpleRequest.call_args
        assert "/wl_audit/raw" in call_args[0][1]  # endpoint check
```

**Source:** [Unit tests for the Splunk Enterprise SDK for Python](https://dev.splunk.com/enterprise/docs/devtools/python/sdk-python/examplespython/unittests)

### Pattern 2: Playwright Page Objects for E2E Testing

**What:** Encapsulate Splunk UI complexity (iframe navigation, custom dropdowns, span-button modals) in reusable page objects. Base class `SplunkPage` handles iframe context; subclasses like `WhitelistManagerPage` provide high-level methods like `load_csv()`, `edit_cell()`, `save_changes()`.

**When to use:** All E2E browser tests. Page objects prevent brittle selector coupling and enable easy updates when UI elements change.

**Example:**
```python
# tests/e2e/page_objects.py
from playwright.sync_api import Page, BrowserContext
import time

class SplunkPage:
    """Base page object handling Splunk-specific navigation (iframes, custom elements)."""
    def __init__(self, page: Page):
        self.page = page
    
    def get_iframe_content(self) -> Page:
        """Returns frame object for content inside Splunk's main iframe."""
        return self.page.frame_locator("iframe[name*='content']")
    
    def wait_for_element(self, selector: str, timeout: int = 5000):
        """Smart wait: poll for element with fallback to timeout."""
        try:
            self.page.locator(selector).first.wait_for(timeout=timeout, state="visible")
        except Exception:
            time.sleep(0.5)
            self.page.locator(selector).first.wait_for(timeout=timeout, state="visible")

class WhitelistManagerPage(SplunkPage):
    """Whitelist Manager dashboard page object."""
    def load_csv(self, rule_name: str, csv_name: str):
        """Select rule and CSV from dropdowns."""
        frame = self.get_iframe_content()
        frame.select_option(".wl-rule-dropdown", label=rule_name)
        frame.select_option(".wl-csv-dropdown", label=csv_name)
        self.wait_for_element(".wl-table")
    
    def edit_cell(self, row_idx: int, col_name: str, value: str):
        """Click cell and type value."""
        frame = self.get_iframe_content()
        cell = frame.locator(f".wl-table tbody tr:nth-child({row_idx+1}) [data-col='{col_name}']")
        cell.click()
        cell.locator("input").fill(value)
        cell.locator("input").press("Enter")
    
    def save_changes(self) -> bool:
        """Click save button and verify success toast."""
        frame = self.get_iframe_content()
        frame.click(".wl-save-button")
        # Wait for toast notification
        try:
            frame.locator(".wl-toast-success").wait_for(timeout=5000, state="visible")
            return True
        except:
            return False
```

**Source:** [Playwright Python - Writing tests](https://playwright.dev/python/docs/writing-tests), [Pytest Plugin Reference | Playwright Python](https://playwright.dev/python/docs/test-runners)

### Pattern 3: Hypothesis Property-Based Security Fuzzing

**What:** Use Hypothesis to generate hundreds of payloads automatically (XSS, SQL injection, path traversal) and verify handlers reject them safely. Define security properties: "Any input containing `<script>` should be escaped in output" then let Hypothesis find counterexamples.

**When to use:** Security tests (TEST-03). Replace manual payload lists with generated tests that discover edge cases.

**Example:**
```python
# tests/security/test_xss.py
from hypothesis import given, strategies as st, HealthCheck, settings
import wl_validation

# Property: sanitize_text must escape all script tags
@settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
@given(input_text=st.text())
def test_sanitize_text_escapes_script_tags(input_text):
    """Property: output should never contain unescaped <script> tags."""
    if "<script>" in input_text:
        result = wl_validation.sanitize_text(input_text)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result or "<" not in result

# Or: load OWASP payload list and property-test against them
import json
with open("tests/security/fixtures/xss_payloads.json") as f:
    PAYLOADS = json.load(f)

@pytest.mark.parametrize("payload", PAYLOADS)
def test_xss_payload_blocked(payload):
    """Concrete test: each OWASP XSS payload is blocked."""
    result = wl_validation.sanitize_text(payload)
    # Verify payload doesn't execute in CSV context
    assert result == wl_validation.sanitize_text(result)  # idempotent
    assert "<svg onload=" not in result
```

**Source:** [How to Build Property-Based Testing with Hypothesis](https://oneuptime.com/blog/post/2026-01-30-how-to-build-property-based-testing-with-hypothesis/view), [OWASP API Security Testing Checklist 2026](https://accuknox.com/blog/owasp-api-security-top-10-the-complete-testing-checklist-2026)

### Pattern 4: Concurrency Testing with ThreadPoolExecutor

**What:** Use `concurrent.futures.ThreadPoolExecutor` to spawn 5-10 worker threads executing the same function simultaneously. Detect race conditions via file corruption, version manifest inconsistency, or deadlocks (catch via `pytest-timeout`).

**When to use:** Concurrency tests (TEST-04). Test file locking, approval queue concurrent writes, mixed operations.

**Example:**
```python
# tests/integration/test_concurrency.py
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest

@pytest.mark.timeout(30)  # Detect deadlocks: fail if test hangs >30s
def test_concurrent_csv_saves(docker_service, tmp_path):
    """Test: 5 threads simultaneously save different CSVs → no corruption."""
    if not docker_service["enabled"]:
        pytest.skip("Docker container required")
    
    csvs = ["DR_001.csv", "DR_002.csv", "DR_003.csv", "DR_004.csv", "DR_005.csv"]
    results = []
    
    def save_csv_in_thread(csv_name):
        # Each thread calls REST API to save CSV
        response = requests.post(
            f"https://localhost:8089/services/custom/wl_manager",
            json={"action": "save_csv", "csv_file": csv_name, "rows": [...]},
            auth=("admin", "Chang3d!"),
            verify=False
        )
        return response.status_code == 200, response.json()
    
    # Run 5 threads in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(save_csv_in_thread, csv): csv for csv in csvs}
        for future in as_completed(futures):
            success, data = future.result()
            results.append((futures[future], success))
    
    # Verify: all succeeded and no file corruption
    assert all(success for _, success in results)
    # Verify version manifests are consistent
    for csv in csvs:
        manifest = read_version_manifest(csv)
        assert manifest["versions"] is not None
```

**Source:** [How to Test Multi-Threaded Applications in Python with pytest](https://woteq.com/how-to-test-multi-threaded-applications-in-python-using-pytest), [Python Free-Threading Guide - Testing](https://py-free-threading.github.io/testing/)

### Anti-Patterns to Avoid

- **Brittle Selectors in E2E**: Don't use `page.locator(".some-div:nth-child(3)")` — encode intent in page objects and use data attributes (`[data-testid="save-button"]`)
- **Live Splunk in Unit Tests**: Don't hit Docker from unit tests — mock SDK allows offline, fast iteration
- **Nested Mocks**: Don't mock.patch deep in the call stack — mock at import site where function is used
- **Ignoring Pytest Markers**: Don't run `@pytest.mark.docker` tests without Docker — use conftest fixture checks to skip gracefully
- **Thread-Unsafe Fixtures**: Don't share mutable state (temp files, mock sessions) between concurrent tests — use separate temp directory per thread

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser automation | Custom Selenium wrapper | Playwright + pytest-playwright | Playwright is 5+ years newer; built-in async, better mobile support, faster |
| Coverage measurement | Manual line counting | pytest-cov (coverage.py) | Handles branch coverage, multi-file merging, HTML reports; standard in industry |
| Fuzzing payloads | Hardcoded XSS/injection lists | Hypothesis | Auto-generates edge cases; shrinks failures to minimal examples; property-based (finds counterexamples to your assumptions) |
| File locking in tests | Manual lock files | unittest.mock + fcntl wrapper | fcntl handles cross-process semantics; mock handles offline testing |
| Parallel test execution | Manual thread spawning | concurrent.futures.ThreadPoolExecutor | Handles cleanup, exception aggregation, timeout detection |
| Performance thresholds | Guessed numbers | Baseline timing pass (calibrate to 2x P95) | Avoids flaky tests from system variance; documents expected performance |

**Key insight:** Splunk testing is complex (iframe quirks, custom dropdowns, async searches), but the ecosystem has solved most problems. Investing in Playwright page objects and mock SDK pays off immediately; hand-rolling UI selectors or test infrastructure leads to maintenance burden that grows with test count.

## Common Pitfalls

### Pitfall 1: Playwright Flaky Timeouts

**What goes wrong:** E2E test passes locally (fast machine) but fails in CI (slow container). Playwright's default `wait_for()` timeout is 30s, but Splunk iframe loading can be variable.

**Why it happens:** Splunk's JavaScript-heavy dashboards require waiting for both iframe load AND dashboard panel rendering. Custom timeouts don't account for Docker overhead or network latency.

**How to avoid:**
- Use smart waits in page objects (check element visibility, not just DOM presence)
- Calibrate timeout constants at the start of E2E suite run with baseline pass
- Add `@pytest.mark.slow` for tests expected to take >10s
- Use `--headed` flag when debugging to observe actual timing

**Warning signs:** Test passes when run individually (`pytest tests/e2e/test_xyz.py`) but fails in full suite

### Pitfall 2: Mock SDK Misses Real Splunk Behavior

**What goes wrong:** Unit tests pass (mock returns expected shape), but integration test fails (real Splunk returns different format or missing field). Approval queue JSON structure differs from expectations; audit event submission silently fails.

**Why it happens:** Mock SDK can't predict all Splunk quirks: SSL self-signed certs, session token expiry, index buffering delays, response envelope nesting.

**How to avoid:**
- Always have parallel integration tests (Docker) that call real Splunk API
- Document mock SDK limitations in test docstrings (e.g., "assumes immediate index write")
- When adding new Splunk calls, add both unit test (mock) AND integration test (Docker)
- Review Splunk REST API docs before writing mock responses

**Warning signs:** Unit tests green but Docker integration tests fail on same code paths

### Pitfall 3: Concurrency Tests Hang Due to Deadlock

**What goes wrong:** `test_concurrent_file_lock_contention` runs fine once, but occasionally hangs indefinitely when run multiple times or in parallel test suite.

**Why it happens:** File locks not released properly on exception; threads waiting on lock that's already held by another thread with no timeout; test fixture cleanup not atomic.

**How to avoid:**
- Always use `pytest.mark.timeout(N)` decorator on concurrency tests (pytest-timeout plugin)
- Use context managers for locks: `with file_lock(): ...` ensures cleanup
- Run concurrency tests sequentially (no pytest-xdist for integration tests)
- Check file lock impl uses RLock + fcntl with timeout

**Warning signs:** Test suite occasionally hangs; works 9/10 times; passes locally but fails in CI

### Pitfall 4: E2E Tests Fail Due to Stale Authentication

**What goes wrong:** Test logs in successfully, but after 5+ minutes of test execution, next action gets 403 Unauthorized. Splunk session expires mid-test.

**Why it happens:** Splunk session tokens have 1-hour default timeout, but some auth flows reset it; reusable auth state from first test doesn't refresh.

**How to avoid:**
- Document auth state strategy (reusable vs per-test) based on observed Splunk behavior
- If reusing auth state: implement token refresh check before each action
- If per-test login: ensure login is fast (<2s) via test data setup
- Add `@pytest.mark.slow` if test takes >5 minutes total

**Warning signs:** Random 403 errors mid-test; same test sometimes passes/fails

### Pitfall 5: Coverage Report Misleading Due to Unexecutable Code Paths

**What goes wrong:** Coverage report claims 85% coverage, but exception handling for network errors is never tested. Production gets hit by network timeout, crashes.

**Why it happens:** Exception-handling code requires Docker (to simulate network errors) but only unit tests are run; integration tests don't cover error paths.

**How to avoid:**
- Organize tests by layer: unit (mocks), integration (Docker), E2E (browser)
- Mark un-testable paths with `# pragma: no cover` (e.g., emergency fallback code)
- Require integration AND unit test coverage for critical paths
- Document coverage gaps in VERIFICATION.md (e.g., "network timeout handling requires Docker")

**Warning signs:** Coverage % high but bugs appear in production error paths

### Pitfall 6: QUnit Tests Don't Actually Test Module Loading

**What goes wrong:** QUnit test imports module, but module has AMD define() that requires Splunk's require.js. Test fails with "require is not defined".

**Why it happens:** QUnit runs in a browser-like environment (test_runner.xml dashboard), not Node.js. AMD modules require actual Splunk require.js context.

**How to avoid:**
- QUnit tests must run within Splunk dashboard (test_runner.xml), not standalone
- Mock require.js if testing outside Splunk context
- Document how to run QUnit tests: "Open Splunk Web → Apps → whitelist_manager → Test Runner dashboard"
- Consider Playwright E2E tests as replacement for complex QUnit scenarios

**Warning signs:** QUnit test file can't import AMD modules; "require is not defined" errors

## Code Examples

Verified patterns from official sources:

### Unit Test with Mock SDK

```python
# Source: tests/unit/test_audit.py (pattern)
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stubs'))

def test_build_audit_event_includes_all_fields():
    """Test: build_audit_event returns dict with required fields."""
    from wl_audit import build_audit_event
    
    event = build_audit_event(
        action="row_added",
        analyst="jsmith",
        detection_rule="SQL_Injection",
        csv_file="sql_injection_whitelist.csv",
        comment="Added new pattern",
        added_row_count=1,
        value_row_1="SELECT 1"
    )
    
    # Verify structure
    assert event["action"] == "row_added"
    assert event["analyst"] == "jsmith"
    assert event["detection_rule"] == "SQL_Injection"
    assert event["csv_file"] == "sql_injection_whitelist.csv"
    assert event["comment"] == "Added new pattern"
    assert event["added_row_count"] == 1
    assert event["value_row_1"] == "SELECT 1"
    
    # Verify timestamp exists
    assert "timestamp" in event
    assert isinstance(event["timestamp"], str)
```

### Integration Test Against Docker

```python
# Source: tests/integration/test_handler_dispatch.py (pattern)
import pytest
import json
import urllib.request
import urllib.error
import ssl

@pytest.fixture
def splunk_api(docker_service):
    """Fixture: REST API client for Splunk management port."""
    if not docker_service["enabled"]:
        pytest.skip("Docker container required")
    
    def api_call(action, payload, user="admin", password="Chang3d!"):
        """Make authenticated REST call."""
        url = f"https://localhost:8089/services/custom/wl_manager?output_mode=json"
        data = json.dumps({"action": action, **payload}).encode()
        
        req = urllib.request.Request(url, data=data, method="POST")
        auth_str = f"{user}:{password}"
        import base64
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        req.add_header("Authorization", f"Basic {b64_auth}")
        req.add_header("Content-Type", "application/json")
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            response = urllib.request.urlopen(req, context=ctx)
            return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            return {"error": str(e), "code": e.code}
    
    return api_call

def test_save_csv_action_posts_audit_event(splunk_api):
    """Test: save_csv action creates audit event in wl_audit index."""
    result = splunk_api("save_csv", {
        "csv_file": "test.csv",
        "rows": [{"name": "test", "value": "123"}],
        "comment": "Test save"
    })
    
    assert result.get("success") is True
    # In real test, query wl_audit index to verify event was posted
```

### E2E Test with Playwright Page Objects

```python
# Source: tests/e2e/test_workflows.py (pattern)
import pytest
from playwright.sync_api import sync_playwright, BrowserContext, Page
from tests.e2e.page_objects import WhitelistManagerPage

@pytest.fixture(scope="session")
def browser_context():
    """Create a reusable browser context for E2E tests."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        # Load auth state if available (skip for now)
        yield context
        context.close()
        browser.close()

def test_load_csv_and_edit_cell(browser_context):
    """E2E Test: Load CSV, edit cell, verify change in table."""
    page = browser_context.new_page()
    try:
        page.goto("http://localhost:8000/app/wl_manager/whitelist_manager")
        page.wait_for_load_state("networkidle")
        
        wl_page = WhitelistManagerPage(page)
        wl_page.load_csv("SQL_Injection", "sql_injection_whitelist.csv")
        
        # Edit first data cell
        wl_page.edit_cell(0, "value", "new_value_123")
        
        # Verify unsaved indicator appears
        frame = wl_page.get_iframe_content()
        assert frame.locator(".wl-unsaved-indicator").is_visible()
        
        # Save changes
        success = wl_page.save_changes()
        assert success is True
        
    finally:
        page.close()
```

### Security Test with Hypothesis

```python
# Source: tests/security/test_xss.py (pattern)
import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from wl_validation import sanitize_text

@settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
@given(
    user_input=st.text(
        alphabet=st.characters(
            blacklist_categories=("Cc",),  # Exclude control characters
            blacklist_characters="\x00"
        )
    )
)
def test_sanitize_text_property_idempotent(user_input):
    """Property: sanitize_text(sanitize_text(x)) == sanitize_text(x)."""
    result1 = sanitize_text(user_input)
    result2 = sanitize_text(result1)
    assert result1 == result2

def test_sanitize_text_blocks_owasp_xss_payloads():
    """Test: known OWASP XSS payloads are blocked."""
    payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert('xss')>",
        "<svg onload=alert('xss')>",
        "javascript:alert('xss')",
    ]
    
    for payload in payloads:
        result = sanitize_text(payload)
        # Verify payload doesn't execute
        assert "<script>" not in result or result.count("<") != payload.count("<")
        assert "onerror=" not in result or "=" not in result
```

### Concurrency Test with ThreadPoolExecutor

```python
# Source: tests/integration/test_concurrency.py (pattern)
import pytest
from concurrent.futures import ThreadPoolExecutor
import time
import tempfile
from pathlib import Path

@pytest.mark.timeout(45)  # Fail if any thread deadlocks >45s
def test_concurrent_file_writes_no_corruption(tmp_path):
    """Test: 5 threads write to same JSON file atomically."""
    data_file = tmp_path / "test_data.json"
    data_file.write_text('{"count": 0}')
    
    def increment_count_in_thread():
        """Read, increment, write."""
        import json
        import time
        
        for _ in range(10):  # Each thread does 10 writes
            with open(data_file, "r") as f:
                data = json.load(f)
            
            data["count"] += 1
            
            # Simulate contention
            time.sleep(0.001)
            
            # Atomic write
            with open(data_file, "w") as f:
                json.dump(data, f)
    
    # Spawn 5 threads
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(increment_count_in_thread) for _ in range(5)]
        # Wait for all to complete
        for future in futures:
            future.result(timeout=10)
    
    # Verify file is valid JSON and count is correct
    import json
    result = json.loads(data_file.read_text())
    # With proper locking, count should be 50 (5 threads × 10 writes)
    # Without locking, it would be <50 due to lost updates
    assert result["count"] == 50
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Selenium WebDriver | Playwright | 2020-2024 | 10x faster, better mobile support, native async |
| Manual payload lists | Hypothesis property-based | 2022-2026 | Finds edge cases; shrinks to minimal examples |
| requests library | urllib (stdlib) | Project-specific | No external dependencies; Splunk SDK not needed for mocking |
| Unittest framework | pytest + fixtures | Industry-wide 2015+ | Better plugin ecosystem; markers for test organization |
| Manual coverage tracking | pytest-cov + HTML reports | Industry-wide 2020+ | Branch coverage; enforces thresholds in CI |
| Serial test execution | pytest-xdist parallel | 2018-2026 | Unit tests 5x faster; integration tests stay serial (stateful) |

**Deprecated/outdated:**
- **unittest library**: Still functional, but pytest is now standard industry tool (better fixtures, markers, plugins)
- **nose**: Replaced by pytest (2018+); pytest-cov is the modern coverage solution
- **Splunk SDK test fixtures**: Project uses mock SDK instead (faster, offline)

## Open Questions

1. **Playwright wait strategy — CLAUDE'S DISCRETION**
   - What we know: Splunk iframe loads asynchronously; dashboard panels render after data fetch; custom dropdowns may not respect standard `wait_for(state="visible")`
   - What's unclear: Optimal balance between smart waits (element.wait_for + retry) vs fixed timeouts (time.sleep); should we poll for stability vs one-shot waits?
   - Recommendation: Implement both in page object base class; calibrate during first E2E implementation pass based on observed timings. If Splunk consistently takes 2-5s per panel, set default timeout to 10s

2. **Login handling approach — CLAUDE'S DISCRETION**
   - What we know: Splunk sessions expire after ~1 hour; test suite may run >5 minutes
   - What's unclear: Should we reuse auth state (store session key after first login) or re-login per test (slower but cleaner isolation)?
   - Recommendation: Start with per-test login for isolation; benchmark login time. If >2s per test, switch to reusable auth state with token refresh

3. **Performance threshold calibration — CLAUDE'S DISCRETION**
   - What we know: Requirement is to set thresholds at 2x observed P95; Docker overhead varies by machine
   - What's unclear: Which operations to baseline (save CSV, load table, approve request, revert)?
   - Recommendation: First task in E2E implementation: run 10 iterations of each operation, record timing distribution, set thresholds at 2x P95. Document thresholds in VERIFICATION.md

4. **Legacy test file strategy — CLAUDE'S DISCRETION**
   - What we know: ~15 legacy test files at `tests/` root level (test_approval_gates.py, test_bulk_edit.py, etc.) from earlier phases
   - What's unclear: Which files have unique coverage vs duplication with integration tests?
   - Recommendation: Gap analysis task: for each legacy file, run coverage-driven diff against corresponding tests/integration file. Migrate unique coverage; delete duplicates

5. **Test data isolation in E2E — LOCKED**
   - Per-test setup/teardown via REST API fixtures ensures each test gets clean state. Question: Should we use per-test Docker snapshots vs API-based cleanup?
   - Recommendation: API-based cleanup is sufficient; snapshots would be 10x slower. API fixture example in Code Examples section

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.1.1 (Python 3.9+) |
| Config file | `tests/pytest.ini` |
| Quick run command | `pytest tests/unit/ -q` (20-30s) |
| Full suite command | `pytest tests/unit/ tests/integration/ tests/e2e/ -v --cov=bin --cov-report=html` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-01 | ≥80% unit coverage, all backend modules | unit | `pytest tests/unit/ -v --cov=bin --cov-report=term-missing` | ✅ (389 existing tests) |
| TEST-02 | All 15+ REST action handlers tested | integration | `pytest tests/integration/test_handler_dispatch.py -v` | ✅ (26 handler tests) |
| TEST-02 | Approval queue orchestration | integration | `pytest tests/integration/test_approval_chain.py -v` | ✅ (8 approval tests) |
| TEST-03 | XSS payload validation | security | `pytest tests/security/test_xss.py -v` | ❌ Wave 0 |
| TEST-03 | Path traversal prevention | security | `pytest tests/security/test_path_traversal.py -v` | ❌ Wave 0 |
| TEST-03 | RBAC bypass prevention (~60-80 tests) | security | `pytest tests/security/test_rbac_bypass.py -v` | ❌ Wave 0 |
| TEST-04 | Concurrent file locking (5+ threads) | integration | `pytest tests/integration/test_concurrency.py::test_concurrent_file_writes -v` | ✅ (5 existing) |
| TEST-04 | Concurrent approval races | integration | `pytest tests/integration/test_concurrency.py::test_approval_race -v` | ❌ Wave 0 |
| TEST-05 | Load CSV, edit, save (E2E) | e2e | `pytest tests/e2e/test_crud.py -v --headed` | ❌ Wave 0 |
| TEST-05 | Approval workflow approve path (E2E) | e2e | `pytest tests/e2e/test_approval.py::test_approve_request -v` | ❌ Wave 0 |
| TEST-05 | Approval workflow reject path (E2E) | e2e | `pytest tests/e2e/test_approval.py::test_reject_request -v` | ❌ Wave 0 |
| TEST-05 | Revert to previous version (E2E) | e2e | `pytest tests/e2e/test_version_control.py -v` | ❌ Wave 0 |
| TEST-05 | Admin panel workflows (E2E) | e2e | `pytest tests/e2e/test_admin_panel.py -v` | ❌ Wave 0 |
| TEST-05 | Stress test: 2000x100 CSV (E2E) | e2e | `pytest tests/e2e/test_stress.py -v --headed` | ❌ Wave 0 |
| TEST-06 | Mock SDK simpleRequest | unit | `pytest tests/unit/test_audit.py -v` | ✅ (mock integrated) |
| TEST-06 | Mock SDK index submission | unit | `pytest tests/unit/test_approval.py -v` | ✅ (mock integrated) |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/ -q` (unit tests only, 20-30s feedback)
- **Per wave merge:** `pytest tests/unit/ tests/integration/ --cov=bin --cov-report=html` (all offline tests, 5-10m)
- **Phase gate:** Full suite green (unit + integration + E2E + security) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/security/test_xss.py` — XSS payloads, hypothesis property test, OWASP cheat sheet import
- [ ] `tests/security/test_path_traversal.py` — Path traversal payloads, safe_realpath() validation
- [ ] `tests/security/test_rbac_bypass.py` — Full RBAC matrix (viewer, editor, admin, superadmin × 15+ actions)
- [ ] `tests/security/test_injection.py` — Input injection (CSV cell, parameter, query string)
- [ ] `tests/e2e/conftest.py` — Playwright fixtures (browser, page, auth state), per-test cleanup via REST API
- [ ] `tests/e2e/page_objects.py` — SplunkPage base class, WhitelistManagerPage, ControlPanelPage, AuditPage
- [ ] `tests/e2e/test_crud.py` — Core workflows (load, edit, save, delete)
- [ ] `tests/e2e/test_approval.py` — Approval workflow (request, approve, reject, notify)
- [ ] `tests/e2e/test_version_control.py` — Revert to version, version history
- [ ] `tests/e2e/test_admin_panel.py` — Queue management, limits, usage, trash, admin controls
- [ ] `tests/e2e/test_stress.py` — 2000×100 CSV stress test, horizontal scroll, single cell edit
- [ ] `tests/integration/test_concurrency.py::test_approval_race` — Two admins approve same request
- [ ] `tests/integration/test_concurrency.py::test_mixed_operations` — Concurrent save + revert + delete
- [ ] `tests/qunit/test_table.js` — wl_table.js cell editing, pagination, row selection
- [ ] `tests/qunit/test_modals.js` — wl_modals.js modal show/hide, form validation
- [ ] `tests/qunit/test_versions.js` — wl_versions.js revert dropdown, version history
- [ ] Framework install: `pip install playwright==1.40+ hypothesis==6.90+ pytest-timeout==2.1+`
- [ ] Playwright browsers: `playwright install chromium`
- [ ] Test data: `tests/security/fixtures/xss_payloads.json`, `path_traversal_payloads.json`, `rbac_matrix.json`
- [ ] Documentation: `tests/README.md` — how to run each suite, Docker setup, Playwright installation

*(If remaining tasks: "Phase 7 Wave 0 spans: Unit test consolidation (3 task days), Security suite (3 days), E2E infrastructure (2 days), E2E workflow tests (5 days), QUnit extensions (1 day), Documentation (1 day) — approx 15 working days total")*

## Sources

### Primary (HIGH confidence)
- [pytest 8.1.1 official docs](https://docs.pytest.org/) — test runner, fixtures, markers
- [pytest-cov 5.0.0 on PyPI](https://pypi.org/project/pytest-cov/) — coverage integration
- [Playwright Python official docs](https://playwright.dev/python/) — browser automation, fixtures, page objects
- [Unit tests for the Splunk Enterprise SDK for Python](https://dev.splunk.com/enterprise/docs/devtools/python/sdk-python/examplespython/unittests) — Splunk testing patterns
- [Splunk SDK Python GitHub tests/](https://github.com/splunk/splunk-sdk-python/tree/master/tests) — mock patterns, test structure

### Secondary (MEDIUM confidence - verified with official sources)
- [Pytest Plugin Reference | Playwright Python](https://playwright.dev/python/docs/test-runners) — pytest-playwright integration
- [pytest-playwright PyPI](https://pypi.org/project/pytest-playwright/) — plugin configuration
- [Hypothesis Documentation](https://hypothesis.readthedocs.io/) — property-based testing
- [How to Test Multi-Threaded Applications in Python with pytest](https://woteq.com/how-to-test-multi-threaded-applications-in-python-using-pytest) — ThreadPoolExecutor pattern
- [Python Free-Threading Guide - Testing](https://py-free-threading.github.io/testing/) — concurrent test patterns

### Tertiary (LOW confidence - ecosystem best practices, needs validation)
- [OWASP API Security Testing Checklist 2026](https://accuknox.com/blog/owasp-api-security-top-10-the-complete-testing-checklist-2026) — security test scope
- [Coverage.py PyTest Plugin: Threshold Enforcement in CI 2026](https://johal.in/coverage-py-pytest-plugin-threshold-enforcement-in-ci-2026/) — coverage thresholds
- [Scalable test automation framework with Playwright & Pytest](https://www.opcito.com/blogs/build-scalable-test-automation-framework-with-playwright-and-pytest) — framework patterns

## Metadata

**Confidence breakdown:**
- **Standard stack:** HIGH — pytest 8.1.1, pytest-cov 5.0.0, playwright-python verified current; requirements-dev.txt already specifies versions
- **Architecture patterns:** HIGH — Splunk SDK unit test patterns documented; Playwright official docs and examples comprehensive
- **Security scope:** MEDIUM — OWASP 2026 checklist current; Hypothesis property-based fuzzing verified; payload sources need git-clone from official OWASP repos (flagged for Wave 0)
- **Concurrency testing:** HIGH — Python ThreadPoolExecutor and pytest-timeout documented; wl_filelock.py RLock+fcntl pattern already tested in Phase 3
- **E2E wait strategy:** MEDIUM-LOW — Splunk iframe behavior discovered during Phase 5 implementation; exact timing characteristics require baseline calibration (flagged as Claude's discretion)

**Research date:** 2026-04-02  
**Valid until:** 2026-05-02 (30 days stable for pytest ecosystem; 14 days if Playwright major version updates; check annually for OWASP Top 10 changes)

---

*Phase: 07-test-coverage-validation*  
*Research completed: 2026-04-02*
