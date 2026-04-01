---
phase: 5
slug: frontend-architecture
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | QUnit 2.19+ (vendored in app, excluded from production package) |
| **Config file** | None — QUnit runs standalone HTML or via Splunk dashboard |
| **Quick run command** | `open tests/qunit_runner.html` (browser) or reload `test_runner.xml` in Docker |
| **Full suite command** | Deploy to Docker, navigate to test_runner.xml dashboard, verify all 50+ assertions pass |
| **Estimated runtime** | ~5 seconds (unit/integration only, no network) |

---

## Sampling Rate

- **After every task commit:** Manual smoke test (load whitelist_manager.xml in Docker, verify core workflows: load CSV, edit row, save)
- **After every plan wave:** Run QUnit full suite (50+ assertions) + manual smoke test all critical paths
- **Before `/gsd:verify-work`:** Full QUnit suite must be green + manual smoke of all features
- **Max feedback latency:** ~5 seconds (QUnit suite)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | FMOD-02 | unit | `tests/qunit/test_constants.js`: verify exports exist | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | FMOD-04 | unit | `tests/qunit/test_state_manager.js`: ~20 assertions on get/set/on/isDirty/batch | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | FMOD-03 | unit | `tests/qunit/test_rest_helpers.js`: mock AJAX, verify calls, events | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 2 | FMOD-05 | integration | `tests/qunit/test_module_loading.js`: require each module, call init, verify return | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 3 | FMOD-05 | integration | `tests/qunit/test_module_loading.js`: table/modals/versions modules | ❌ W0 | ⬜ pending |
| 05-04-01 | 04 | 4 | FMOD-01 | integration | Manual: load whitelist_manager.xml, verify no console errors, all features work | ✅ whitelist_manager.xml | ⬜ pending |
| 05-04-02 | 04 | 4 | FMOD-08 | integration | Manual: verify notifications.js uses define(), imports wl_rest.js | ❌ W0 | ⬜ pending |
| 05-04-03 | 04 | 4 | TEST-05 | unit/integration | Deploy tests/qunit/ to Docker, open test_runner.xml, verify 50+ assertions PASS | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/qunit/test_state_manager.js` — ~20 assertions: state registration, get/set, validators, events, isDirty, batch, reset
- [ ] `tests/qunit/test_rest_helpers.js` — ~10 assertions: URL building, AJAX wrapping, error event firing
- [ ] `tests/qunit/test_module_loading.js` — ~15 assertions: AMD module loading order, init sequences, API contracts
- [ ] `tests/qunit/test_integration.js` — ~5 assertions: cross-module event workflows (remove requested → modal → save)
- [ ] `tests/qunit_runner.html` — Standalone QUnit test runner for local development
- [ ] `default/data/ui/views/test_runner.xml` — Splunk dashboard for automated Docker testing
- [ ] `appserver/static/modules/` directory — Created during Phase 5 implementation

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full dashboard loads with all features | FMOD-01 | Requires Splunk runtime + Docker + real AMD loader | Load whitelist_manager.xml in Docker, open DevTools, verify no errors, test load CSV → edit → save → revert |
| notifications.js AMD refactor | FMOD-08 | Requires Splunk MVC context for event system | Open notifications panel, verify badges update, check console for wl:notificationsUpdated events |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
