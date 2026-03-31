---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-31T21:22:05.476Z"
progress:
  total_phases: 8
  completed_phases: 1
  total_plans: 8
  completed_plans: 5
---

# State: Whitelist Manager v3.0 Modular Rewrite

**Date:** 2026-03-31  
**Project:** Whitelist Manager for Splunk Enterprise Security  
**Milestone:** v3.0 Modular Rewrite

---

## Project Reference

**Core Value:**
SOC analysts can safely edit detection-rule whitelists with full audit trail — and the codebase itself is maintainable, testable, and ready for Splunkbase publication.

**Current Focus:**
Phase 02 — backend-core-domain

**Key Constraints:**

- Must stay within Splunk ecosystem (jQuery + AMD/RequireJS)
- API contract must not change (audit.xml and existing events depend on current shapes)
- Each phase must produce a working app (zero downtime)
- Python 3 only (Splunk 9.x)

---

## Current Position

Phase: 02 (backend-core-domain) — EXECUTING
Plan: 2 of 4 (Plan 01 Complete ✓)

## Roadmap Overview

**Total Phases:** 8  
**Requirements Mapped:** 28/28 ✓  
**No orphaned requirements:** ✓

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 1 | Backend Foundation | BMOD-02, BMOD-03, BMOD-04, BMOD-05, TEST-01(p) | COMPLETE ✓ |
| 2 | Backend Core Domain | BMOD-01, BMOD-06, BMOD-07, BMOD-08, BMOD-09, BMOD-10, + | IN PROGRESS (02-01 COMPLETE ✓) |
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

**2026-03-31: Plan 01-02 Completion (Constants Layer)**

- Extracted 80+ constants from wl_handler.py into wl_constants.py (Layer 0)
- Used sys.path.insert() pattern for same-directory imports (Splunk bin/ limitation)
- Created 33 unit tests covering constants, regex patterns, role definitions (100% pass)
- Updated wl_handler.py to import from wl_constants (134 lines removed, zero functional changes)
- Requirement BMOD-02 fulfilled: "Layer 0 constants, regex patterns, role definitions"
- Ready for Phase 01-03: Validation & RBAC extraction

**2026-03-31: Plan 01-03 Completion (Logging & Validation Layer)**

- Extracted logging configuration into wl_logging.py (Layer 1)
  - Single-responsibility module providing get_audit_logger() factory function
  - RotatingFileHandler with 100 MB max, 10 backups
  - Idempotent: no duplicate handlers on module reload
  - 100% test coverage (8 tests)
- Extracted validation helpers into wl_validation.py (Layer 2)
  - 5 pure functions: sanitize_text, is_safe_filename, safe_realpath, build_csv_path, resolve_csv_path
  - 93% test coverage (25 tests)
  - No state or side effects
  - Path security: prevents traversal, symlink escape, file access validation
- Updated wl_handler.py: imports from both modules, 150 lines of duplication removed
- All 64 call sites updated to use imported versions
- Requirement BMOD-03 fulfilled: "Input validation extracted to dedicated module"
- Total: 33 new tests (32 passed, 1 skipped)
- Ready for Phase 01-04: Rate limiting, RBAC, presence tracking

**2026-03-31: Plan 01-04 Completion (Layer 2 Utility Modules)**

- Extracted three Layer 2 utility modules from wl_handler.py
  - **wl_ratelimit.py** (66 lines): Sliding-window rate limiter with per-user, per-action-type tracking
    - Automatic pruning of timestamps outside RATE_WINDOW
    - Stale-key cleanup when dict exceeds 10,000 entries
    - 86% coverage (11 tests)
  - **wl_rbac.py** (169 lines): Role-based access control predicates and user discovery
    - 8 functions: is_admin, is_editor, is_superadmin, can_approve, can_approve_own_requests, get_user, get_roles, get_admin_users
    - Lazy import of splunk.rest for offline testing support
    - 99% coverage (17 tests)
  - **wl_presence.py** (157 lines): User presence tracking with per-CSV state dictionaries
    - Idle-minutes calculation, automatic cleanup of stale users
    - Per-CSV isolation, per-file and per-user limits
    - 100% coverage (30+ tests)
- Updated wl_handler.py: Removed ~150 lines, updated to import and use Layer 2 modules
- Comprehensive unit test suite: 62 tests, 97% overall coverage
  - All tests pass offline (no Splunk SDK required)
  - Proper mocking of time-dependent code and Splunk REST API
  - Test isolation via module-level state reset functions
- Requirements BMOD-04, BMOD-05, TEST-01 fulfilled
- Phase 01-backend-foundation is COMPLETE ✓

**2026-03-31: Plan 02-01 Completion (Layer 3 CSV Module)**

- Extracted CSV operations into wl_csv.py (Layer 3, 451 lines)
  - **read_csv()**: Parse CSV file with proper encoding handling (UTF-8-sig BOM stripping)
  - **write_csv()**: Atomic write with temp file → rename pattern
  - **compute_diff()**: Similarity-based diff engine with Counter (multiset) for duplicates, reverse iteration for append-only rows, >50% field threshold for edit pairing
  - **get_expire_column()**: Find Expires column (case-insensitive)
  - **remove_expired_rows()**: Purge rows with past expiration dates (UTC and legacy local time support)
  - **get_column_widths()**: Read column width metadata (side-car JSON)
  - **set_column_widths()**: Write column width metadata
- Extracted 7 functions, removed ~260 lines from wl_handler.py (net -256 after imports)
- Unit test coverage: 37 tests, 95% code coverage
  - 100% coverage on all functions: read, write, diff, expiration, columns
  - Edge cases: duplicate detection, metadata filtering, timezone offsets, O(n²) guards
- Integrated into wl_handler.py with 50+ call sites updated, all old _prefixed functions removed
- Requirements BMOD-06 and TEST-01 fulfilled
- No deviations from plan; all success criteria met

**2026-03-31: Plan 02-02 Completion (Layer 3 Rules & Trash Modules)**

- Extracted wl_rules.py (4 functions): Detection rules registry and rule-to-CSV mapping operations
  - **read_rules_registry()**: Read list of detection rule names
  - **write_rules_registry()**: Atomic write of rules JSON
  - **read_csv_mapping()**: Parse rule_csv_map.csv to dict
  - **get_rule_csv_file()**: Lookup single rule's CSV file
  - Decision: Silent failures for reads (return empty list/dict), exceptions for writes
- Extracted wl_trash.py (8 functions): Soft-delete, restore, purge, retention operations
  - **move_to_trash()**: Deterministic IDs (name__type__timestamp) prevent storage bloat from repeated delete→restore→delete
  - **list_trash()**: List items sorted by timestamp (newest first)
  - **restore_from_trash()**: Restore item and update config
  - **purge_trash_item()**: Permanently delete item
  - **auto_cleanup_trash()**: Purge items older than retention period
  - **get_trash_dir()**, **read_trash_config()**, **write_trash_config()**
  - Decision: Extracted helper functions into public API for approval queue reuse
- Unit test coverage: 39 tests (20 for wl_rules, 19 for wl_trash), 100% pass rate
- Integrated into wl_handler.py: removed ~420 lines of internal function definitions
- All type hints added to public functions for IDE support
- Requirements BMOD-09, BMOD-10, TEST-01 fulfilled

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
