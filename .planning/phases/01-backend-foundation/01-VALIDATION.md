---
phase: 1
slug: backend-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-31
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.1+ with pytest-cov 5.0+ |
| **Config file** | `tests/pytest.ini` (Wave 0 installs) |
| **Quick run command** | `python -m pytest tests/unit/ -x -q` |
| **Full suite command** | `python -m pytest tests/ --cov=bin --cov-report=term-missing` |
| **Estimated runtime** | ~5 seconds (unit only), ~30 seconds (full with integration) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/unit/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ --cov=bin --cov-report=term-missing`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | TEST-01 | infra | `python -m pytest --version` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | BMOD-02 | unit | `python -m pytest tests/unit/test_constants.py -x -q` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | BMOD-03 | unit | `python -m pytest tests/unit/test_validation.py -x -q` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 1 | BMOD-04 | unit | `python -m pytest tests/unit/test_rbac.py -x -q` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 1 | BMOD-05 | unit | `python -m pytest tests/unit/test_presence.py -x -q` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 2 | BMOD-02+ | integration | `python -m pytest tests/integration/ -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/__init__.py` — package init
- [ ] `tests/integration/__init__.py` — package init
- [ ] `tests/conftest.py` — shared fixtures (Splunk SDK stubs, temp file helpers)
- [ ] `tests/stubs/rest.py` — Splunk REST stub for import compatibility
- [ ] `tests/pytest.ini` — pytest configuration with markers
- [ ] `pip install pytest pytest-cov freezegun` — test framework install

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| App loads in Splunk UI | BMOD-02 | Requires running Splunk instance | Load `http://localhost:8000/app/wl_manager/whitelist_manager`, verify CSV editor works |
| No API contract change | BMOD-02 | End-to-end REST behavior | Save/revert CSV via UI, verify audit events in `index=wl_audit` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
