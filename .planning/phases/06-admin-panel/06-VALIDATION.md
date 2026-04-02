---
phase: 6
slug: admin-panel
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | QUnit (bundled with Splunk 9.3.1) |
| **Config file** | `default/data/ui/views/test_runner.xml` (Phase 5 created) |
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

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | FMOD-06 | manual | Load control_panel.xml, verify tabs render | N/A | ⬜ pending |
| 06-02-01 | 02 | 2 | FMOD-06 | unit | QUnit: wl_cp_trash module loads and exports init/load | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 2 | FMOD-06 | unit | QUnit: wl_cp_usage module loads and exports init/load | ❌ W0 | ⬜ pending |
| 06-02-03 | 02 | 2 | FMOD-06 | unit | QUnit: wl_cp_admin_limits module loads and exports init/load | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 3 | FMOD-06 | unit | QUnit: wl_cp_queue module loads, renders pending table | ❌ W0 | ⬜ pending |
| 06-03-02 | 03 | 3 | FMOD-06 | unit | QUnit: wl_cp_limits module loads, renders limit form | ❌ W0 | ⬜ pending |
| 06-03-03 | 03 | 3 | FMOD-07 | unit | QUnit: notification badge updates on new pending count | ❌ W0 | ⬜ pending |
| 06-04-01 | 04 | 4 | FMOD-06 | unit | QUnit: all 5 CP modules pass full test suite | ❌ W0 | ⬜ pending |
| 06-04-02 | 04 | 4 | FMOD-07 | integration | QUnit: tab switching starts/stops correct module polling | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `appserver/static/tests/test_wl_cp_queue.js` — QUnit stubs for queue module
- [ ] `appserver/static/tests/test_wl_cp_limits.js` — QUnit stubs for limits module
- [ ] `appserver/static/tests/test_wl_cp_trash.js` — QUnit stubs for trash module
- [ ] `appserver/static/tests/test_wl_cp_usage.js` — QUnit stubs for usage module
- [ ] `appserver/static/tests/test_wl_cp_admin_limits.js` — QUnit stubs for admin limits module

*Existing QUnit infrastructure from Phase 5 covers framework setup.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Tab switching preserves state | FMOD-06 | Requires browser DOM interaction | Switch tabs rapidly, verify no data loss or polling errors |
| Polling pauses on hidden tab | FMOD-06 | Requires browser visibility API | Minimize browser, check network tab for paused requests |
| Modal blocks polling refresh | FMOD-06 | Requires visual inspection | Open approve modal, wait >5s, verify table doesn't re-render behind modal |
| Dark/light theme consistency | FMOD-06 | Requires visual comparison | Toggle theme, verify all CP modules render correctly in both |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 3s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
