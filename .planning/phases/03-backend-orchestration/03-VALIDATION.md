---
phase: 3
slug: backend-orchestration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-01
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | tests/conftest.py (shared fixtures) |
| **Quick run command** | `python -m pytest tests/unit/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/unit/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | BMOD-11 | unit | `python -m pytest tests/unit/test_limits.py -v` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | TEST-01 | unit | `python -m pytest tests/unit/test_limits.py -v` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | BMOD-11 | integration | `python -m pytest tests/unit/test_limits.py tests/integration/ -v` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | BMOD-12 | unit | `python -m pytest tests/unit/test_approval.py -v` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | TEST-01 | unit | `python -m pytest tests/unit/test_approval.py -v` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | BMOD-12 | integration | `python -m pytest tests/integration/test_approval_chain.py -v` | ❌ W0 | ⬜ pending |
| 03-02-04 | 02 | 2 | TEST-04 | integration | `python -m pytest tests/integration/test_concurrency.py -v` | ❌ W0 | ⬜ pending |
| 03-02-05 | 02 | 2 | BMOD-13 | unit | `python -m pytest tests/ -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_limits.py` — stubs for BMOD-11 (daily limits tracking, reset, enforcement)
- [ ] `tests/unit/test_approval.py` — stubs for BMOD-12 (queue CRUD, conflict resolution, submission)
- [ ] `tests/integration/test_approval_chain.py` — stubs for approval sequence flows
- [ ] `tests/integration/test_concurrency.py` — stubs for TEST-04 (5+ thread scenarios)
- [ ] `tests/conftest.py` — shared fixtures (temp dirs, mock session_key, mock time)

*Test framework (pytest) already installed from Phase 2.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Approval UI flow (submit → admin sees → approve/reject) | BMOD-12 | Requires Splunk Web UI interaction | 1. Log in as analyst 2. Edit CSV rows exceeding threshold 3. Verify approval prompt 4. Log in as admin 5. Approve/reject 6. Verify audit trail |
| Notification display in Splunk UI | BMOD-12 | Requires Splunk notification panel | Verify admin sees pending approval notification after analyst submits |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
