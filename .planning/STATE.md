# State: Whitelist Manager v3.0 Modular Rewrite

**Date:** 2026-03-31  
**Project:** Whitelist Manager for Splunk Enterprise Security  
**Milestone:** v3.0 Modular Rewrite

---

## Project Reference

**Core Value:**
SOC analysts can safely edit detection-rule whitelists with full audit trail — and the codebase itself is maintainable, testable, and ready for Splunkbase publication.

**Current Focus:**
Full architectural rewrite from monolithic architecture (7,078-line backend, 6,786-line frontend) to modular architecture with comprehensive test coverage and AppInspect compliance.

**Key Constraints:**
- Must stay within Splunk ecosystem (jQuery + AMD/RequireJS)
- API contract must not change (audit.xml and existing events depend on current shapes)
- Each phase must produce a working app (zero downtime)
- Python 3 only (Splunk 9.x)

---

## Current Position

**Phase:** Pre-Phase 1 (roadmap just created)  
**Status:** Awaiting roadmap approval and handoff to /gsd:plan-phase  
**Progress:** 0/28 requirements implemented

**Roadmap Status:**
- Roadmap creation: COMPLETE
- Phase 1 planning: PENDING
- Phase 2–8 planning: NOT STARTED

---

## Roadmap Overview

**Total Phases:** 8  
**Requirements Mapped:** 28/28 ✓  
**No orphaned requirements:** ✓

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 1 | Backend Foundation | BMOD-02, BMOD-03, BMOD-04, BMOD-05, TEST-01(p) | Not started |
| 2 | Backend Core Domain | BMOD-01, BMOD-06, BMOD-07, BMOD-08, BMOD-09, BMOD-10, + | Not started |
| 3 | Backend Orchestration | BMOD-11, BMOD-12, BMOD-13(p), BMOD-14(p), BMOD-15(p), TEST-01(p), TEST-04(p) | Not started |
| 4 | Backend Integration | BMOD-01, TEST-01(p), TEST-02 | Not started |
| 5 | Frontend Architecture | FMOD-01, FMOD-02, FMOD-03, FMOD-04, FMOD-05, FMOD-08, TEST-05(p) | Not started |
| 6 | Admin Panel | FMOD-06, FMOD-07 | Not started |
| 7 | Test Coverage & Validation | TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06 | Not started |
| 8 | Splunkbase Readiness | PUBL-01, PUBL-02, PUBL-03, PUBL-04, PUBL-05 | Not started |

---

## Decision Log

**2026-03-31: Roadmap Creation**
- Adopted dependency-first phase ordering from research/SUMMARY.md
- Foundation modules (Phase 1) → Core domain (Phase 2) → Orchestration (Phase 3) → Router (Phase 4) → Frontend (Phases 5-6) → Tests (Phase 7) → Splunkbase (Phase 8)
- Rationale: Allows unit testing of each layer independently before integration
- Backward compatibility maintained throughout: REST API contract frozen, no audit event shape changes
- Each phase includes its own test suite (not batched at end)

**2026-03-31: Traceability Structure**
- 28 v1 requirements mapped 1:1 to phases (no duplicates, no orphans)
- Test requirements (TEST-01 through TEST-06) distributed across execution phases, with Phase 7 as validation sweep
- Publishing requirements (PUBL-01 through PUBL-05) consolidated in Phase 8 (final readiness)

---

## Architecture Decisions

**Backend Modularization:**
- Extract modules in dependency order: constants → validation → RBAC → presence → then CSV → versions → audit → rules → trash → limits → approval
- Each module focused on single responsibility; file locking remains per-module (don't centralize)
- Use `sys.path.insert()` in wl_handler.py to enable inter-module imports; no package subdirectories (Splunk `bin/` limitation)

**Frontend Modularization:**
- AMD modules with single state manager (wl_state.js) as SSOT for all shared state
- All features communicate via jQuery event delegation (no direct cross-module function calls)
- Shared REST helpers in wl_rest.js used by all JS files (eliminates 6x duplication)
- whitelist_manager.js and control_panel.js rewritten as thin entry points that require feature modules

**API Contract Frozen:**
- No changes to REST endpoint shapes (get_csv, save_csv, process_approval, etc.)
- Existing audit events continue to parse correctly
- Version manifests and approval queues remain forward-compatible

---

## Performance Metrics

| Metric | Baseline (v2.0) | Target (v3.0) | Status |
|--------|-----------------|---------------|--------|
| Backend file size | 7,078 lines | <200 lines (handler) + 12 modules | TBD |
| Frontend file size | 6,786 lines (main) + 2,025 (control) | ~100 lines (main) + ~100 lines (control) + 12 modules | TBD |
| Test coverage | 0% | ≥80% per module | TBD |
| Cyclomatic complexity | >28 (in _save_csv_inner, _process_approval_inner) | <15 all modules | TBD |
| Avg function size | ~300 lines (handlers) | <100 lines | TBD |

---

## Accumulated Context

**Key Lessons from Audit:**
- Code quality audit identified 43 findings (12 high, 18 medium, 13 low) — all maintainability, none security-related
- Security audits passed: APPROVED (security reviewer), Grade A (OWASP), READY (contract auditor)
- Concurrency audit identified 2 high-severity issues (now fixed with RLock + file lock)

**Critical Pitfalls to Avoid:**
1. Circular imports in backend modules — mitigated by constants-first architecture
2. File locking semantics change when extracted to wl_csv.py — ensure per-module file locks remain
3. Frontend state mutations outside state manager — enforce single SSOT via wl_state.js
4. API contract drift — freeze request/response shapes; don't add fields unless backward-compatible
5. Audit event parsing breaks — validate backward compatibility in Phase 8 with existing audit.xml queries

**Research Flags (Phase-Specific):**
- **Phase 1–2:** Verify file locking behavior when extracted; test on Windows (no fcntl)
- **Phase 3:** Concurrency testing for approval races; auto-cancellation correctness
- **Phase 5:** AMD module loading order under slow network; state manager singleton persistence
- **Phase 7:** Mock Splunk SDK patterns; ensure tests run offline without container

---

## Blockers & Risks

**None currently identified.** Roadmap derived from completed research; all architecture decisions documented; no external dependencies blocking Phase 1 start.

---

## Next Steps

1. **Phase 1 Planning:** Run `/gsd:plan-phase 1` to decompose Phase 1 into executable plans
2. **Backend Foundation Implementation:** Extract 5 foundation modules with unit tests
3. **Incremental Deployment:** Deploy Phase 1 to Docker container; verify all features still work
4. **Phase 2 Planning:** Once Phase 1 complete, plan Phase 2 core domain modules

---

## Session Continuity

**Roadmap Status:** CREATED 2026-03-31  
**Files Written:**
- `.planning/ROADMAP.md` — Phase structure, goals, success criteria
- `.planning/STATE.md` — This file
- `.planning/REQUIREMENTS.md` — Updated traceability section

**Ready for:** Approval and handoff to `/gsd:plan-phase 1`

