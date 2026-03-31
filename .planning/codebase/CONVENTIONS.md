# Coding Conventions

**Analysis Date:** 2026-03-31

## Naming Patterns

**Files:**
- Python: `lowercase_with_underscores.py` (e.g., `wl_handler.py`, `wl_expiration_cleanup.py`)
- JavaScript: `camelCase.js` (e.g., `whitelist_manager.js`, `control_panel.js`, `notifications.js`)
- CSS: `camelCase.css` with all class selectors prefixed with `wl-` namespace (e.g., `.wl-dropdown-list`, `.wl-modal-overlay`)
- Shell scripts: `lowercase_with_underscores.sh` (e.g., `validate.sh`, `package.sh`)
- Config files: Splunk `.conf` format (e.g., `app.conf`, `restmap.conf`, `authorize.conf`)

**Functions:**
- Python: `_lowercase_with_leading_underscore()` for private helpers (e.g., `_sanitize_text()`, `_compute_diff()`, `_check_rate_limit()`)
- Python: public functions rare, mostly private utilities. Main handler class is `WhitelistHandler`
- JavaScript: `camelCase()` for functions (e.g., `parseCSV()`, `validateImportedCSV()`, `restPost()`, `showMsg()`)
- JavaScript: IIFE (Immediately Invoked Function Expression) pattern for module initialization and namespace isolation

**Variables:**
- Python: `lowercase_with_underscores` (e.g., `csv_file`, `user_roles`, `pending_count`)
- Python: Global state prefixed with `_` (e.g., `_logger`, `_presence`, `_rate_limits`)
- Python: Constants in `UPPER_CASE` (e.g., `MAX_ROWS`, `EDIT_ROLES`, `APPROVAL_QUEUE_FILE`)
- JavaScript: `camelCase` (e.g., `currentHeaders`, `selectedRule`, `msgTimer`, `csvLocked`)
- JavaScript: Global/state variables with clear prefixes indicating scope (e.g., `currentPage`, `undoState`, `pendingApprovals`)

**Types/Classes:**
- Python: Class names `PascalCase` (e.g., `WhitelistHandler` extends `PersistentServerConnectionApplication`)
- JavaScript: No formal class syntax used; functions return state objects or are IIFE closures
- Constants for enumerations use uppercase (e.g., `EDIT_ROLES = {"wl_editor", "wl_analyst_editor", ...}`)

## Code Style

**Formatting:**
- Python: 4-space indentation (PEP 8 compliant)
- JavaScript: 4-space indentation, semicolons required, `"use strict";` at module top
- CSS: 4-space indentation, one property per line
- No enforced linter (eslint/prettier/flake8) visible in config; validates with manual scripts

**Linting:**
- Python: `validate.sh` script runs `python -c "compile(...)"` for syntax checking
- JavaScript: No automated linting tool, relies on convention following
- XML: Validated via `xml.etree.ElementTree` in validation script at `scripts/validate.sh`
- CSS: No automated linting; follows convention-based review

## Import Organization

**Python order:**
1. Standard library imports (`os`, `sys`, `json`, `csv`, `datetime`, etc.)
2. Try-except wrapped optional imports (`try: import fcntl except ImportError`)
3. Third-party imports (Splunk SDK: `from splunk.persistconn.application import ...`)
4. Local imports (none—single handler file design)

Example from `bin/wl_handler.py` (lines 23-51):
```python
import os
import sys
import json
# ... standard lib ...
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows — file locking unavailable
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timedelta, timezone

from splunk.persistconn.application import PersistentServerConnectionApplication
```

**JavaScript:**
All imports via Splunk's AMD loader (`require()`):
```javascript
require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils) {
    "use strict";
    // module code
});
```

**Path aliases:** None; relative imports used in tests (e.g., `sys.path.insert(0, os.path.join(...))`). Tests directly exec function source to avoid Splunk dependency issues.

## Error Handling

**Patterns:**
- Python: Broad try-except blocks wrapping entire operations, logs to `_logger`, returns error in response dict
- Python: Exception types caught explicitly: `(json.JSONDecodeError, OSError)`, `(ValueError, TypeError)`, general `Exception as exc`
- Python: Logging via `_logger.error()`, `_logger.warning()`, structured with format string + args
- JavaScript: Try-catch blocks in critical sections (e.g., user detection IIFE), silent fail with `.fail()` callbacks on AJAX
- JavaScript: AJAX always provides `.done()` and `.fail()` handlers; `.fail()` often silent or logs to console

Example from `bin/wl_handler.py` (lines 1902-1929):
```python
def handle(self, in_string):
    try:
        request = json.loads(in_string)
        # ... validation ...
        if method == "GET":
            return self._handle_get(request)
        elif method == "POST":
            return self._handle_post(request)
        else:
            return self._resp(405, {"error": "Method not allowed"})
    except Exception as exc:
        _logger.error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
        return self._resp(500, {"error": "An internal error occurred."})
```

Example from `appserver/static/control_panel.js` (lines 40-53):
```javascript
(function detectCurrentUser() {
    try {
        var envModel = mvc.Components.getInstance("env");
        if (envModel) {
            cpCurrentUser = envModel.get("user") || "";
        }
    } catch (e) { /* ignore */ }
    if (!cpCurrentUser) {
        try {
            cpCurrentUser = $(".user-name").text().trim() || ...;
        } catch (e) { /* ignore */ }
    }
})();
```

**Response structure (Python):**
All handler endpoints return a dict via `_resp(status_code, body_dict)`:
```python
def _resp(status, body):
    return {
        "status": status,
        "headers": {"Content-Type": "application/json"},
        "payload": json.dumps(body, default=str),
    }
```

**Error response format:**
```json
{ "error": "Human-readable error message" }
```
Or specific error types (e.g., `"daily_limit_exceeded"`, `"rate_limit_exceeded"`, `"permission_denied"`).

## Logging

**Framework:** Python's standard `logging` module with `RotatingFileHandler`

**Patterns:**
- Initialized at module load (lines 194-208 in `wl_handler.py`):
  - Attempts file handler to `AUDIT_LOG = /opt/splunk/var/log/splunk/wl_manager_audit.log`
  - Falls back to `StreamHandler(sys.stderr)` if directory not writable
  - Prefix: `"%(message)s"` format (audit events as structured JSON in `_raw`)

- Usage: `_logger.error(msg, *args)`, `_logger.warning(msg, *args)`
  - Arguments passed separately for safe formatting: `_logger.error("Error: %s\n%s", exc, traceback.format_exc())`
  - Never f-strings in logging (prevents late binding)

- Audit events written as JSON to log via `_logger.info()`:
  ```python
  event = {
      "timestamp": ..., "action": "save_csv", "analyst": user,
      "detection_rule": rule, "csv_file": csv, "added_count": ...,
      # ... diff data ...
  }
  _logger.info(json.dumps(event))
  ```

**JavaScript:**
- No formal logging framework; uses `console.log()` / `console.error()` for debug
- Production errors logged via audit search results in test suite only
- No client-side persistent logs

## Comments

**When to Comment:**
- Complex algorithms (e.g., `_compute_diff()` has nested helper functions with docstrings)
- Security decisions (e.g., "Symlink protection: ensure path stays under apps directory")
- Non-obvious workarounds (e.g., "MSYS_NO_PATHCONV=1 required for Git Bash on Windows")
- State machines (e.g., "state: `pending`, `approved`, `rejected`, `expired`, `cancelled`")
- Constants with domain meaning (e.g., comments on EXPIRE_COLUMN_NAMES)

**JSDoc/TSDoc:**
- Python docstrings (triple quotes) on public functions and module headers
- Example from `wl_handler.py` (lines 1-21):
  ```python
  """
  Whitelist Manager — Splunk REST Handler (the "wrapper").
  
  This is the server-side core of the application. It intercepts every CSV
  read/write, computes a structured diff (like Git), and writes an audit
  event to both a Splunk index and a rotating log file.
  
  Endpoint registered in restmap.conf:
      GET  /custom/wl_manager/wl_handler?action=<action>&...
      POST /custom/wl_manager/wl_handler   { "action": "save_csv", ... }
  
  GET actions:
      get_rules        — list all detection rule names
      get_csvs         — list CSV files for a given rule
      ...
  """
  ```

- JavaScript block comments at function level when purpose is non-obvious:
  ```javascript
  /**
   * CSV Import: Client-side parser, validator, preview renderer
   */
  // ... related functions grouped under comment ...
  ```

## Function Design

**Size:** 
- Python private helpers typically 10-50 lines; larger functions broken into helpers
- Python handler methods like `_handle_post()` ~500 lines (large by convention, handles multiple action types)
- JavaScript functions 20-100 lines; IIFE modules group related functions

**Parameters:**
- Python: Functions take explicit parameters; rare use of `**kwargs`
- Python: Defaults used sparingly (e.g., `_sanitize_text(text, max_length=500)`)
- JavaScript: No formal typing; functions check `typeof` or existence (e.g., `data || {}`)

**Return Values:**
- Python: Single dict or tuple for multiple values (e.g., `(headers, rows)` from `_read_csv()`)
- Python: All handler responses via `_resp(status, body)` which returns dict
- JavaScript: Functions often return void, relying on state mutation; AJAX handlers use promise chaining `.done()` / `.fail()`

## Module Design

**Exports (Python):**
- `wl_handler.py`: Single class `WhitelistHandler(PersistentServerConnectionApplication)` registered via Splunk's `restmap.conf`
- All utility functions prefixed with `_` (private); no public function exports

**Exports (JavaScript):**
- Each `require()` block is a closure; no explicit exports
- State shared via `window.__wlNotifCallbacks` (notifications.js) for inter-module messaging
- DOM mutations and event handlers within IIFE

**Barrel Files:** None used; single monolithic handler (`wl_handler.py` ~6800 lines) contains all backend logic

## Security Conventions

**Input Sanitization:**
- Regex-based stripping: `_SANITIZE_RE.sub("", text)` removes disallowed characters (lines 224, 234)
- Filename validation: `_safe_filename()` checks extension, traversal, alphanumeric content
- Path traversal prevention: `_safe_realpath()` and `os.path.normpath()` checks against base directories
- Column name whitelist: `_SAFE_COLNAME_RE` enforces allowed characters (letters, numbers, `-._()/#:@&+`)

**RBAC:**
- Roles checked via `self._get_roles(request)` intersection with `EDIT_ROLES`, `ADMIN_ROLES`, `SUPERADMIN_ROLES` constants
- Every POST requires role check; errors return 403 Forbidden
- Approval gate thresholds read from config, never client-provided

**Rate Limiting:**
- Sliding window per (user, action_type): 30 writes / 60 sec, 120 reads / 60 sec
- Memory pruning to prevent unbounded growth (lines 284-287)
- Returns 429 Too Many Requests when exceeded

## Validation Patterns

**CSV Validation (`whitelist_manager.js` lines 195-338):**
- Multi-stage: filename check → column count → row count → column names → cell content
- **No short-circuit:** runs ALL checks to completion, collects errors
- Returns `{ errors: string[], warnings: object[] }` with severity levels
- Warnings (non-blocking): control characters, suspicious but valid dates
- Errors (blocking): missing headers, duplicates, oversized content

**Backend Validation (`wl_handler.py`):**
- Per-action: checks before diff, before write, before audit
- Checks: max row/column/cell limits, filename validity, role permissions, rate limits, daily limits
- Returns 400 Bad Request with error dict on validation failure

## Data Structures

**Python:**
- `dict` for JSON payloads, config, audit events
- `list[dict]` for CSV rows (`[{"user": "alice", "ip": "10.0.0.1"}, ...]`)
- `set` for RBAC roles (`EDIT_ROLES = {"admin", "sc_admin", ...}`)
- `Counter` (multiset) for counting occurrences safely with duplicates

**JavaScript:**
- Plain object `{}` for state and response data
- Array `[]` for CSV rows and filtered results
- Bitmask-style boolean tracking: `selectedIdxSet = { idx: true, ...}` for sparse selection across pagination

**CSV Format:**
- Standard RFC 4180: headers in first row, UTF-8 with optional BOM
- No embedded newlines; control characters sanitized
- Column names: no spaces (use underscores), no `_` prefix (reserved), max 64 chars, case-insensitive duplicate detection

## Splunk-Specific Patterns

**REST Handler:**
- Extends `PersistentServerConnectionApplication` from `splunk.persistconn.application`
- Single endpoint `/custom/wl_manager` handles all GET/POST actions via `action` parameter
- Request/response via dict with `method`, `payload` (JSON string), `user`, `roles` fields

**JavaScript REST calls:**
- Via Splunk's `mvc/utils` and jQuery AJAX
- URL: `Splunk.util.make_url("/splunkd/__raw/services/custom/wl_manager")`
- Payload: `JSON.stringify(payload)` with `contentType: "application/json"`
- Always set `output_mode: "json"` in URL params

**App Configuration:**
- `app.conf`: version, build number (bumped on every JS/CSS change)
- `restmap.conf`: endpoint registration, authentication requirement
- `authorize.conf`: role definitions (`wl_editor`, `wl_admin`, `wl_superadmin`)
- `props.conf`: `TRUNCATE = 0` for wl_audit sourcetype (large events)

---

*Convention analysis: 2026-03-31*
