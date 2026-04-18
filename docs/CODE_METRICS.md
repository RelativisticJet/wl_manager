# Code Quality Metrics — Build 546

## Executive Summary

Whitelist Manager uses a modular architecture with 19 Python backend modules and 13 JavaScript frontend modules. This report documents code quality metrics, test coverage, and known areas for improvement.

## Quality Thresholds

| Metric | Threshold | Purpose |
|--------|-----------|---------|
| Cyclomatic Complexity | < 15 per module | Maintainability |
| Function Size | < 100 lines | Testability |
| Module Size | < 1000 LOC | Single responsibility |
| Test Coverage | >= 80% | Regression prevention |

## Python Modules (19 files, 11,865 LOC)

| Module | LOC | CC Avg | Grade | Coverage |
|--------|-----|--------|-------|----------|
| wl_handler | 5,223 | 7.8 | B | 0.0% |
| wl_csv | 1,069 | 12.0 | C | 51.9% |
| wl_trash | 765 | 6.1 | B | 63.8% |
| wl_versions | 643 | 11.0 | C | 41.8% |
| wl_approval | 620 | 5.1 | B | 83.3% |
| wl_rules | 538 | 7.9 | B | 75.4% |
| wl_replay | 508 | 7.7 | B | 18.2% |
| wl_limits | 474 | 4.3 | A | 90.2% |
| wl_constants | 463 | 1.0 | A | 100.0% |
| wl_notify | 238 | 4.8 | A | 86.5% |
| wl_expiration_cleanup | 212 | 4.7 | A | 0.0% |
| wl_validation | 202 | 5.2 | B | 93.4% |
| wl_audit | 191 | 7.0 | B | 83.6% |
| wl_rbac | 169 | 3.2 | A | 98.6% |
| wl_expiring_soon | 163 | 10.7 | C | 0.0% |
| wl_presence | 160 | 7.2 | B | 100.0% |
| wl_filelock | 104 | 12.0 | C | 91.5% |
| wl_ratelimit | 66 | 6.0 | B | 86.4% |
| wl_logging | 57 | 2.0 | A | 100.0% |

**Grade Scale:** A = CC 1-5, B = CC 6-10, C = CC 11-15, D = CC 16-20, F = CC 21+

## JavaScript Modules (18 files, 10,345 LOC)

| File | LOC | Type |
|------|-----|------|
| control_panel.js | 2,012 | Entry point (admin panel) |
| wl_table.js | 1,537 | AMD module |
| wl_modals.js | 1,320 | AMD module |
| wl_csv_io.js | 1,177 | AMD module |
| wl_save.js | 1,023 | AMD module |
| wl_approval_ui.js | 631 | AMD module |
| whitelist_manager.js | 517 | Entry point (main editor) |
| wl_nav.js | 457 | AMD module |
| notifications.js | 327 | Entry point (all views) |
| wl_versions.js | 333 | AMD module |
| wl_diff.js | 277 | AMD module |
| wl_presence.js | 241 | AMD module |
| wl_datepicker.js | 178 | AMD module |
| wl_ui.js | 129 | AMD module |
| application.js | 52 | Entry point |
| audit_trail.js | 51 | Entry point |
| wl_rest.js | 43 | AMD module |
| wl_constants.js | 40 | AMD module |

## Test Coverage

**Overall: 32.4% (threshold: 80%) — BELOW TARGET**

| Module | Coverage | Status |
|--------|----------|--------|
| wl_constants | 100.0% | PASS |
| wl_logging | 100.0% | PASS |
| wl_presence | 100.0% | PASS |
| wl_rbac | 98.6% | PASS |
| wl_validation | 93.4% | PASS |
| wl_filelock | 91.5% | PASS |
| wl_limits | 90.2% | PASS |
| wl_notify | 86.5% | PASS |
| wl_ratelimit | 86.4% | PASS |
| wl_audit | 83.6% | PASS |
| wl_approval | 83.3% | PASS |
| wl_rules | 75.4% | Below threshold |
| wl_trash | 63.8% | Below threshold |
| wl_csv | 51.9% | Below threshold |
| wl_versions | 41.8% | Below threshold |
| wl_replay | 18.2% | Below threshold |
| wl_expiration_cleanup | 0.0% | No tests |
| wl_expiring_soon | 0.0% | No tests |
| wl_handler | 0.0% | No tests |

**E2E test suite:** 103 tests across 5 suites (modularization, 3 role-based, security bypass) — 103/103 PASS.

## Quality Gate Violations

1. `wl_handler.py`: 5,223 lines > 1,000 threshold
2. `wl_csv.py`: 1,069 lines > 1,000 threshold
3. Overall coverage 32.4% < 80% threshold

## Improvement Priorities

| Priority | Action | Impact |
|----------|--------|--------|
| HIGH | Add unit tests for `wl_handler.py` action wrappers | Largest coverage gap |
| HIGH | Add tests for `wl_replay.py` (18.2%) | Approval replay is critical path |
| MEDIUM | Increase `wl_csv.py` coverage (51.9%) | Core data operations |
| MEDIUM | Add tests for `wl_versions.py` (41.8%) | Version control reliability |
| LOW | Split `wl_handler.py` into per-domain action modules | Maintainability |
| LOW | Modularize `control_panel.js` (same pattern as main editor) | Frontend consistency |

## Security Audit Status

Build 546 includes fixes from a comprehensive security review:
- Error messages no longer leak internal file paths
- Approval gate checks properly exempt admins
- API enumeration via `valid_actions` removed
- `selected_count` type coercion hardened against string bypass
- `self.sessionKey` crash fixed (5 call sites)
- Optimistic locking gap fixed (no-change save response)
- Debug module and `console.log` removed from production code

See [docs/SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md) for the full threat model.
