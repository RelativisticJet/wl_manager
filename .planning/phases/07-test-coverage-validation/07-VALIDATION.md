---
phase: 7
slug: test-coverage-validation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-cov 7.1.0 + playwright-python + hypothesis |
| **Config file** | tests/pytest.ini |
| **Quick run command** | `python -m pytest tests/unit/ -q --tb=short` |
| **Full suite command** | `python -m pytest tests/ -q --tb=short --cov=bin/ --cov-report=term-missing` |
| **Estimated runtime** | ~120 seconds (unit: ~2s, integration: ~30s, e2e: ~60s, security: ~30s) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/unit/ -q --tb=short`
- **After every plan wave:** Run `python -m pytest tests/ -q --tb=short --cov=bin/`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | TEST-01 | unit | `python -m pytest tests/unit/test_limits.py -q` | ✅ | ⬜ pending |
| 07-01-02 | 01 | 1 | TEST-06 | unit | `python -m pytest tests/unit/ -q --cov=bin/` | ✅ | ⬜ pending |
| 07-01-03 | 01 | 1 | TEST-01 | unit | `python -m pytest tests/unit/ -q` | ✅ | ⬜ pending |
| 07-02-01 | 02 | 2 | TEST-02 | integration | `python -m pytest tests/integration/ -q -m docker` | ✅ | ⬜ pending |
| 07-02-02 | 02 | 2 | TEST-04 | integration | `python -m pytest tests/integration/test_concurrency.py -q` | ✅ | ⬜ pending |
| 07-03-01 | 03 | 2 | TEST-03 | security | `python -m pytest tests/security/ -q` | ❌ W0 | ⬜ pending |
| 07-04-01 | 04 | 3 | TEST-05 | e2e | `python -m pytest tests/e2e/ -q --headed` | ❌ W0 | ⬜ pending |
| 07-05-01 | 05 | 3 | TEST-05 | qunit | Manual: load test_runner.xml in Splunk | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/security/__init__.py` — security test package
- [ ] `tests/security/conftest.py` — security test fixtures
- [ ] `tests/security/fixtures/` — OWASP payload data files
- [ ] `tests/e2e/__init__.py` — e2e test package
- [ ] `tests/e2e/conftest.py` — Playwright fixtures (browser, page, auth state)
- [ ] `tests/e2e/pages/` — Page object model classes
- [ ] `requirements-dev.txt` update — add playwright, hypothesis, pytest-playwright
- [ ] `tests/pytest.ini` update — register new markers (docker, slow, crud, approval, revert, admin, stress, security)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| QUnit tests pass in Splunk browser | TEST-05 | QUnit runs inside Splunk dashboard, not CLI | Load test_runner.xml dashboard, verify all QUnit assertions pass |
| Splunk theme toggle doesn't break UI | TEST-05 | Visual verification of CSS rendering | Toggle dark/light theme in Splunk, verify no layout breaks |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
