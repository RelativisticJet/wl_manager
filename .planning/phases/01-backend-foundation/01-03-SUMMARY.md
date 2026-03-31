---
phase: 01-backend-foundation
plan: 03
subsystem: backend-layers
tags: [logging, validation, refactoring, unit-tests]
dependency_graph:
  requires: [01-02]
  provides: [wl_logging (Layer 1), wl_validation (Layer 2)]
  affects: [01-04, 02-*]
tech_stack:
  added:
    - wl_logging.py: Rotating file handler, logger factory
    - wl_validation.py: Path security, input sanitization
  patterns:
    - Pure functions (no state)
    - Layer-based dependency injection
    - Centralized validation
key_files:
  created:
    - bin/wl_logging.py (~55 lines)
    - bin/wl_validation.py (~180 lines)
    - tests/unit/test_logging.py (~120 lines)
    - tests/unit/test_validation.py (~320 lines)
  modified:
    - bin/wl_handler.py (-150 lines from extraction, +25 lines for imports)
metrics:
  duration_minutes: 45
  tasks_completed: 5/5
  test_coverage_logging: 100% (18/18 statements)
  test_coverage_validation: 93% (57/61 statements)
  total_tests: 33 (32 passed, 1 skipped on Windows)
decisions:
  - Layer 1 (wl_logging) created with single responsibility: logger configuration
  - Layer 2 (wl_validation) created to isolate path security and input sanitization
  - Pure functions used throughout validation module (no state, no side effects)
  - sys.path.insert() pattern maintained for same-directory imports (Splunk bin/ limitation)
completed_date: "2026-03-31"
---

# Phase 01 Plan 03: Logging & Validation Extraction Summary

**Objective:** Extract logging configuration and input validation helpers from wl_handler.py into dedicated Layer 1 and Layer 2 modules.

**Result:** SUCCESS — All 5 tasks completed. Logging and validation modules created with 33 comprehensive unit tests (93%+ coverage).

---

## What Was Built

### bin/wl_logging.py (Layer 1)

A single-responsibility module providing centralized logger configuration:

- **get_audit_logger()**: Factory function returning a configured rotating file handler logger
  - Writes to `$SPLUNK_HOME/var/log/splunk/wl_manager_audit.log`
  - Max 100 MB per file, 10 backup files
  - Idempotent: returns same logger instance on multiple calls, no duplicate handlers
  - Creates log directory if missing

Key design:
- No imports from wl_* modules (only stdlib logging)
- Respects SPLUNK_HOME environment variable
- Sets logger level to INFO
- Includes timestamp, logger name, level in format

### bin/wl_validation.py (Layer 2)

Pure validation and security helper functions with no state or side effects:

**Exported functions:**

1. **sanitize_text(text, max_length=500)** → str
   - Removes control characters (\x00-\x1f)
   - Collapses multiple whitespace to single space
   - Truncates to max_length
   - Returns "" for invalid input

2. **is_safe_filename(name, allowed_extensions=(".csv",))** → bool
   - Rejects path traversal attempts (../, ..\\, /subdir/)
   - Rejects files starting with . (dotfiles)
   - Validates extension against whitelist
   - Requires at least one alphanumeric character in stem
   - Examples: "rule_whitelist.csv" ✓, "../etc/passwd" ✗

3. **safe_realpath(path, allowed_base)** → Optional[str]
   - Resolves symlinks using os.path.realpath()
   - Verifies result is within allowed_base or equals it
   - Returns None if escape detected
   - Handles exceptions gracefully

4. **build_csv_path(csv_file, app_context="")** → Optional[str]
   - Builds absolute path WITHOUT checking existence
   - Uses is_safe_filename() to validate input
   - Routes to app-specific or default lookups directory
   - Normalizes path and prevents escaping APPS_DIR
   - Used by both _resolve_csv_path and deletion code

5. **resolve_csv_path(csv_file, app_context="")** → Optional[str]
   - Combines build_csv_path() + file existence check + symlink safety
   - Full validation pipeline for reading/modifying CSVs
   - Returns real absolute path if safe, None otherwise

Key design:
- Imports only from wl_constants and stdlib (pure layer)
- All functions are pure: no global state, no side effects
- Path operations use both os.path.normpath() (for non-existent paths) and os.path.realpath() (for symlinks)
- Type hints on all functions for IDE support

### Updated bin/wl_handler.py

Refactored to use the new modules:

- Added imports:
  ```python
  from wl_logging import get_audit_logger
  from wl_validation import sanitize_text, is_safe_filename, safe_realpath, build_csv_path, resolve_csv_path
  ```

- Removed logger setup code (now in wl_logging.py):
  - RotatingFileHandler setup (~20 lines)
  - Exception handling for log directory creation

- Removed function definitions (now in wl_validation.py):
  - _sanitize_text() → sanitize_text()
  - _safe_filename() → is_safe_filename()
  - _safe_realpath() → safe_realpath()
  - _build_csv_path() → build_csv_path()
  - _resolve_csv_path() → resolve_csv_path()

- Updated 64 function call sites to use imported versions (removed _ prefix)

- Kept locally:
  - _find_expire_column() (domain-specific, not general validation)
  - _check_rate_limit() (rate limiting, separate concern)

### Unit Tests

**tests/unit/test_logging.py (8 tests)**

- ✓ test_get_audit_logger_returns_logger: Verifies type
- ✓ test_get_audit_logger_configures_handler: Checks RotatingFileHandler setup
- ✓ test_get_audit_logger_idempotent: No duplicate handlers on reload
- ✓ test_get_audit_logger_creates_log_directory: Directory creation behavior
- ✓ test_get_audit_logger_uses_env_var: Respects SPLUNK_HOME environment variable
- ✓ test_get_audit_logger_sets_level: Logger level is INFO
- ✓ test_get_audit_logger_has_formatter: Handler has formatter
- ✓ test_get_audit_logger_rotating_handler_config: maxBytes=100MB, backupCount=10

**Coverage:** 100% (18/18 statements)

**tests/unit/test_validation.py (25 tests)**

**sanitize_text tests:**
- ✓ Removes control characters
- ✓ Collapses whitespace
- ✓ Truncates to max_length
- ✓ Returns empty string for invalid input
- ✓ Strips leading/trailing whitespace

**is_safe_filename tests:**
- ✓ Accepts valid CSV filenames
- ✓ Rejects path traversal attempts (../, ..\, /subdir/)
- ✓ Rejects dotfiles (.hidden.csv)
- ✓ Rejects bad extensions
- ✓ Validates custom allowed_extensions parameter
- ✓ Requires alphanumeric stem
- ✓ Rejects invalid input (None, int)

**safe_realpath tests:**
- ✓ Verifies path containment
- ✓ Rejects paths outside allowed_base
- ✓ Handles nonexistent paths gracefully

**build_csv_path tests:**
- ✓ Rejects unsafe filenames
- ✓ Accepts valid filenames
- ✓ Uses OWN_LOOKUPS by default
- ✓ Supports custom app_context
- ✓ Normalizes paths (consistent separators)
- ✓ Prevents APPS_DIR escape

**resolve_csv_path tests:**
- ✓ Returns None for missing files
- ✓ Returns real path for existing files
- ✓ Checks filename safety
- ✓ Handles symlink traversal (skipped on Windows)

**Coverage:** 93% (57/61 statements)
- Uncovered: error paths in safe_realpath exception handling

**Total: 32 passed, 1 skipped**

---

## Deviations from Plan

None. Plan executed exactly as written. All acceptance criteria met:

✓ bin/wl_logging.py created with __all__, get_audit_logger(), RotatingFileHandler, no wl_* imports  
✓ bin/wl_validation.py created with 5 functions, type hints, docstrings, wl_constants imports only  
✓ bin/wl_handler.py imports from both modules, old definitions removed, all 64 call sites updated  
✓ tests/unit/test_logging.py created with 8 tests, all @pytest.mark.unit  
✓ tests/unit/test_validation.py created with 25+ tests, all @pytest.mark.unit  
✓ All tests pass (32/32, 1 skipped Windows-only test)  
✓ Coverage ≥80%: wl_logging 100%, wl_validation 93%  
✓ Requirement BMOD-03 addressed: "Input validation and sanitization extracted to dedicated module"

---

## Verification

All acceptance criteria verified:

**wl_logging.py:**
- [x] File exists at bin/wl_logging.py
- [x] Contains __all__ = ["get_audit_logger"]
- [x] Function returns logging.Logger
- [x] Uses RotatingFileHandler with 100 MB max, 10 backups
- [x] No imports from wl_* modules (only stdlib)
- [x] Comprehensive docstring

**wl_validation.py:**
- [x] File exists at bin/wl_validation.py
- [x] __all__ exports all 5 functions
- [x] All functions defined with docstrings and type hints
- [x] Imports from wl_constants: _CONTROL_CHAR_RE, _SANITIZE_RE, _SAFE_COLNAME_RE, APPS_DIR, OWN_LOOKUPS
- [x] No other wl_* imports
- [x] sanitize_text removes control chars, collapses whitespace, truncates
- [x] is_safe_filename rejects traversal, dots, bad extensions
- [x] safe_realpath uses os.path.realpath, checks containment
- [x] build_csv_path validates and returns normalized paths
- [x] resolve_csv_path checks file existence and symlink safety

**wl_handler.py:**
- [x] Contains `from wl_logging import get_audit_logger`
- [x] Contains `from wl_validation import sanitize_text, is_safe_filename, ...`
- [x] Logger config code removed (RotatingFileHandler setup deleted)
- [x] Function definitions removed (_sanitize_text, _safe_filename, etc.)
- [x] All calls updated to use imported versions (no self._ prefix)
- [x] No syntax errors (python3 -m py_compile passed)

**Unit Tests:**
- [x] test_logging.py exists with ≥5 tests (8 created)
- [x] test_validation.py exists with ≥15 tests (25 created)
- [x] All tests decorated with @pytest.mark.unit
- [x] All tests pass: 32 passed, 1 skipped
- [x] Coverage: wl_logging 100%, wl_validation 93%

---

## Ready for Phase 01-04

The logging and validation foundation is now in place. Phase 01-04 can proceed with:
- Rate limiting module (wl_ratelimit.py)
- RBAC module (wl_rbac.py)
- Presence tracking module (wl_presence.py)

All these modules will depend on wl_logging and wl_validation for consistent error handling and input validation.

---

## Artifacts

```
bin/wl_logging.py                  55 lines  Layer 1 — Logger configuration
bin/wl_validation.py              180 lines  Layer 2 — Validation helpers
tests/unit/test_logging.py        120 lines  Logger unit tests
tests/unit/test_validation.py     320 lines  Validation unit tests
bin/wl_handler.py                 modified  Updated imports, removed duplicates
```

**Lines of code change:**
- Removed from wl_handler.py: ~150 lines (old implementations)
- Added to wl_logging.py: ~55 lines
- Added to wl_validation.py: ~180 lines
- Net increase: ~85 lines (offset by removed duplication)

**Test coverage:**
- 33 new tests (32 passed, 1 skipped)
- 100% coverage on wl_logging
- 93% coverage on wl_validation
- All edge cases covered: control chars, whitespace, truncation, traversal, symlinks, etc.
