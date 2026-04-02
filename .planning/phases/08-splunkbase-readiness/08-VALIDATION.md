---
phase: 8
slug: splunkbase-readiness
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with unittest.mock, pytest-cov, custom Docker fixtures (conftest.py) |
| **Config file** | tests/pytest.ini |
| **Quick run command** | `bash scripts/validate.sh && pytest tests/unit -v` |
| **Full suite command** | `pytest tests/ -v && splunk-appinspect inspect dist/*.spl && radon cc bin/ -a` |
| **Estimated runtime** | ~5 minutes (full suite with Docker + AppInspect) |

---

## Sampling Rate

- **After every task commit:** Run `bash scripts/validate.sh && pytest tests/unit -v`
- **After every plan wave:** Run `pytest tests/ -v && splunk-appinspect inspect dist/*.spl && radon cc bin/ -a`
- **Before `/gsd:verify-work`:** Full AppInspect + all metrics checks + backward compat tests must pass
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | PUBL-01 | integration | `splunk-appinspect inspect dist/*.spl` | ✅ (scripts/validate.sh) | ⬜ pending |
| 08-01-02 | 01 | 1 | PUBL-01 | integration | `splunk-appinspect inspect dist/*.spl --included-tags cloud` | ❌ W0 | ⬜ pending |
| 08-02-01 | 02 | 1 | PUBL-02 | manual | Generate docs/SECURITY_ARCHITECTURE.md | ❌ W0 | ⬜ pending |
| 08-02-02 | 02 | 1 | PUBL-02 | manual | Review for STRIDE/DREAD tables | ❌ W0 | ⬜ pending |
| 08-03-01 | 03 | 1 | PUBL-03 | manual | Hand-author docs/api/openapi.yaml | ❌ W0 | ⬜ pending |
| 08-03-02 | 03 | 1 | PUBL-03 | manual | Review for examples per action | ❌ W0 | ⬜ pending |
| 08-04-01 | 04 | 2 | PUBL-04 | integration | `pytest tests/integration/test_backward_compat_audit.py -v` | ❌ W0 | ⬜ pending |
| 08-04-02 | 04 | 2 | PUBL-04 | integration | `pytest tests/integration/test_backward_compat_versions.py -v` | ❌ W0 | ⬜ pending |
| 08-04-03 | 04 | 2 | PUBL-04 | integration | `pytest tests/integration/test_backward_compat_approval.py -v` | ❌ W0 | ⬜ pending |
| 08-04-04 | 04 | 2 | PUBL-04 | integration | `bash scripts/test_upgrade_path.sh` | ❌ W0 | ⬜ pending |
| 08-05-01 | 05 | 2 | PUBL-05 | unit | `radon cc bin/ -a --fail-under F:15` | ❌ W0 | ⬜ pending |
| 08-05-02 | 05 | 2 | PUBL-05 | unit | `escomplex appserver/static/**/*.js` | ❌ W0 | ⬜ pending |
| 08-05-03 | 05 | 2 | PUBL-05 | unit | `pytest tests/ --cov=bin --cov-fail-under=80` | ✅ (Phase 7) | ⬜ pending |
| 08-05-04 | 05 | 2 | PUBL-05 | unit | `python scripts/metrics_collector.py --gate` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/integration/test_backward_compat_audit.py` -- Golden v2.0 audit event injection test
- [ ] `tests/integration/test_backward_compat_versions.py` -- v2.0 version manifest fixture test
- [ ] `tests/integration/test_backward_compat_approval.py` -- v2.0 approval queue replay test
- [ ] `scripts/test_upgrade_path.sh` -- End-to-end Docker upgrade v2.0 to v3.0
- [ ] `scripts/verify_appinspect.sh` -- AppInspect validation wrapper (standard + cloud tag sets)
- [ ] `scripts/metrics_collector.py` -- Radon + escomplex analysis with threshold enforcement
- [ ] `docs/SECURITY_ARCHITECTURE.md` -- Two-part STRIDE/DREAD threat model + mitigated vulnerabilities
- [ ] `docs/api/openapi.yaml` -- OpenAPI 3.0 manual specification for all REST actions
- [ ] `docs/BACKWARD_COMPAT.md` -- Backward compatibility test matrix and results
- [ ] `docs/APPINSPECT_NOTES.md` -- AppInspect warnings log
- [ ] `CODE_METRICS.md` (root) -- Summary metrics report
- [ ] Makefile targets: `appinspect`, `metrics`, `backward-compat-test`
- [ ] `app.manifest` -- Complete fields (author, releaseDate, license)
- [ ] `README.md` -- Rewrite for Splunkbase audience
- [ ] `about.xml` -- In-app About dashboard

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Security architecture covers STRIDE/DREAD | PUBL-02 | Document content quality | Review docs/SECURITY_ARCHITECTURE.md for completeness of threat model tables, RBAC matrix, data flow diagrams |
| OpenAPI spec matches all REST actions | PUBL-03 | Schema accuracy vs code | Compare openapi.yaml operations against GET_ACTIONS/POST_ACTIONS in wl_handler.py |
| README is Splunkbase-ready | PUBL-01 | Content quality | Review README.md for feature highlights, screenshots, installation steps, requirements |
| Screenshots capture current UI | PUBL-01 | Visual verification | View docs/screenshots/ images, verify they match current Docker container UI |
| CHANGELOG covers v3.0 rewrite | PUBL-01 | Content completeness | Review CHANGELOG.md for all 8 phase summaries |

*All other behaviors have automated verification via AppInspect, pytest, or metrics scripts.*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
