---
phase: 6
slug: admin-panel
status: revised
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-02
revised: 2026-04-02
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | QUnit (bundled with Splunk 9.3.1) |
| **Config file** | `default/data/ui/views/test_runner.xml` (Phase 5 created, updated Phase 6) |
| **Quick run command** | `Open http://localhost:8000/app/wl_manager/test_runner in browser` |
| **Full suite command** | `Open http://localhost:8000/app/wl_manager/test_runner in browser` |
| **Estimated runtime** | ~3 seconds |

---

## Sampling Rate

- **After every task commit:** Open test_runner dashboard, verify all green
- **After every plan wave:** Full QUnit suite must pass
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 3 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Test File | Status |
|---------|------|------|-------------|-----------|-------------------|-----------|--------|
| 06-01-01 | 01 | 1 | FMOD-06 | manual | Load control_panel.xml, verify tabs render | N/A | ⬜ pending |
| 06-02-01 | 02 | 2 | FMOD-06 | unit | QUnit: wl_cp_trash module loads and exports init/load | test_wl_cp_trash.js | ⬜ pending |
| 06-02-02 | 02 | 2 | FMOD-06 | unit | QUnit: wl_cp_usage module loads and exports init/load | test_wl_cp_usage.js | ⬜ pending |
| 06-02-03 | 02 | 2 | FMOD-06 | unit | QUnit: wl_cp_admin_limits module loads and exports init/load | test_wl_cp_admin_limits.js | ⬜ pending |
| 06-03-01 | 03 | 2 | FMOD-06 | unit | QUnit: wl_cp_queue module loads, renders pending table | test_wl_cp_queue.js | ⬜ pending |
| 06-03-02 | 03 | 2 | FMOD-06 | unit | QUnit: wl_cp_limits module loads, renders limit form | test_wl_cp_limits.js | ⬜ pending |
| 06-03-03 | 03 | 2 | FMOD-07 | unit | QUnit: notification badge updates on new pending count | test_wl_cp_queue.js | ⬜ pending |
| 06-04-01 | 04 | 3 | FMOD-06 | unit | QUnit: all 5 CP modules pass full test suite | all test_wl_cp_*.js | ⬜ pending |
| 06-04-02 | 04 | 3 | FMOD-07 | integration | QUnit: tab switching starts/stops correct module polling | all test_wl_cp_*.js | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements — COMPLETED

- [x] `appserver/static/tests/test_wl_cp_queue.js` — QUnit tests for queue module (created in 06-04)
- [x] `appserver/static/tests/test_wl_cp_limits.js` — QUnit tests for limits module (created in 06-04)
- [x] `appserver/static/tests/test_wl_cp_trash.js` — QUnit tests for trash module (created in 06-04)
- [x] `appserver/static/tests/test_wl_cp_usage.js` — QUnit tests for usage module (created in 06-04)
- [x] `appserver/static/tests/test_wl_cp_admin_limits.js` — QUnit tests for admin limits module (created in 06-04)

*Existing QUnit infrastructure from Phase 5 covers framework setup.*

**Resolution:** Checker issue resolved by Plan 06-04, which creates all 5 test files. Every automated `<verify>` command in Plans 02-03 now references existing test files.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Tab switching preserves state | FMOD-06 | Requires browser DOM interaction | Switch tabs rapidly, verify no data loss or polling errors |
| Polling pauses on hidden tab | FMOD-06 | Requires browser visibility API | Minimize browser, check network tab for paused requests |
| Modal blocks polling refresh | FMOD-06 | Requires visual inspection | Open approve modal, wait >5s, verify table doesn't re-render behind modal |
| Dark/light theme consistency | FMOD-06 | Requires visual comparison | Toggle theme, verify all CP modules render correctly in both |

---

## Nyquist Compliance Checklist

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
  - Plans 02-03 reference Wave 0 test files (created in Plan 04)
  - All 5 test files exist before execution begins
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
  - Every task has automated command or depends on Wave 0
- [x] Wave 0 covers all MISSING references
  - 5 test files created for 5 CP modules
- [x] No watch-mode flags
  - All test commands are one-shot (no --watch)
- [x] Feedback latency < 3s
  - QUnit runs in ~3 seconds
- [x] `nyquist_compliant: true` set in frontmatter
  - Updated in this revision

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 3s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ✅ COMPLIANT
