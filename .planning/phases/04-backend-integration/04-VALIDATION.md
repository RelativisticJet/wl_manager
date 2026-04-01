---
phase: 4
slug: backend-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-01
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-cov |
| **Config file** | tests/pytest.ini |
| **Quick run command** | `cd c:/Users/PC/wl_manager && python -m pytest tests/unit/ -x -q` |
| **Full suite command** | `cd c:/Users/PC/wl_manager && python -m pytest tests/ -x -q --tb=short` |
| **Estimated runtime** | ~15 seconds (unit), ~45 seconds (full with integration) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/unit/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 0 | TEST-01 | unit | `python -m pytest tests/unit/test_replay.py -x -q` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 0 | TEST-02 | integration | `python -m pytest tests/integration/test_handler_dispatch.py -x -q` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | BMOD-01 | unit | `python -m pytest tests/unit/ -x -q` | ✅ | ⬜ pending |
| 04-02-02 | 02 | 1 | BMOD-01 | integration | `python -m pytest tests/integration/test_handler_dispatch.py -x -q` | ❌ W0 | ⬜ pending |
| 04-03-01 | 03 | 2 | BMOD-01 | unit | `python -m pytest tests/unit/ -x -q` | ✅ | ⬜ pending |
| 04-03-02 | 03 | 2 | TEST-02 | integration | `python -m pytest tests/integration/test_handler_actions.py -x -q` | ❌ W0 | ⬜ pending |
| 04-04-01 | 04 | 3 | BMOD-01, TEST-02 | integration | `python -m pytest tests/integration/ -x -q` | ✅ | ⬜ pending |
| 04-04-02 | 04 | 3 | TEST-02 | docker | `python -m pytest tests/integration/test_docker_actions.py -x -q -m docker` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_replay.py` — stubs for wl_replay.py module tests
- [ ] `tests/integration/test_handler_dispatch.py` — dispatch table completeness + RBAC matrix tests
- [ ] `tests/integration/test_handler_actions.py` — mock REST harness action tests
- [ ] `tests/integration/test_docker_actions.py` — Docker smoke tests for all actions

*Existing infrastructure (conftest.py, stubs, pytest.ini) covers unit test foundation from Phase 1.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full UI smoke test | BMOD-01 | Browser interaction needed | Load whitelist_manager, edit CSV, save, revert, approve — verify all features work |
| Audit dashboard queries | TEST-02 | Requires Splunk Web UI | Open audit.xml, verify all SPL queries return correct data after refactored actions |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
