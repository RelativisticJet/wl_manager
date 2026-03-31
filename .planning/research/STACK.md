# Technology Stack: Quality-Focused Rewrite

**Project:** Whitelist Manager v3.0 — Modular Rewrite for Splunkbase  
**Researched:** 2026-03-31  
**Constraint:** Must remain within Splunk ecosystem (jQuery + AMD, no external frameworks)

---

## Recommended Stack

### Core Framework

| Technology | Version | Purpose | Why |
|---|---|---|---|
| **Splunk Web** | 8.2+ | Dashboard framework | Official; bundled with Splunk; no build required |
| **jQuery** | 1.12+ (Splunk-bundled) | DOM manipulation | Splunk includes it; AMD-compatible |
| **RequireJS (AMD)** | 2.x (Splunk-bundled) | Module system | Native to Splunk; required for Splunkbase compliance |
| **SimpleXML** | Splunk 8.2+ | Dashboard markup | Splunk standard; no alternatives |

### Backend

| Technology | Version | Purpose | Why |
|---|---|---|---|
| **Python** | 3.9+ | REST handler | Splunk 9.x ships Python 3; standard for custom handlers |
| **Splunk SDK** | 1.6.22+ | REST API client (optional) | Fallback to urllib if not available; keeps dependencies minimal |
| **stdlib (urllib, json, csv, threading)** | Built-in | Core I/O and concurrency | Zero external dependencies; stable |

### Data Storage

| Technology | Version | Purpose | Why |
|---|---|---|---|
| **CSV files** | RFC 4180 | Whitelist lookup tables | Splunk convention; no database migration needed |
| **JSON** | RFC 7158 | Version manifests, approval queue, presence tracker | Human-readable; matches existing state structure |
| **File locking** | `fcntl` (Linux) / `msvcrt` (Windows) | Concurrent write protection | Stdlib; proven in current code |

### Testing & Validation

| Technology | Version | Purpose | Why |
|---|---|---|---|
| **pytest** | 7.0+ | Test framework | Standard for Python projects; integrates with Splunk container |
| **unittest** | Built-in | Unit test base class | Already used in current test suite |
| **unittest.mock** | Built-in | Mocking Splunk SDK | Zero external deps for unit tests; runs offline |
| **Docker Compose** | 1.29+ | Dev/test environment | Current setup works; no alternatives needed |
| **Splunk Docker image** | 9.3.1 | Integration test target | Official; matches production |
| **Playwright (optional)** | Latest | Browser E2E testing | Lightweight; for critical UI workflows only |

### Packaging & Validation

| Technology | Version | Purpose | Why |
|---|---|---|---|
| **tar.gz** | Standard | .spl app format | Splunk standard; no alternatives |
| **AppInspect** | Latest | Static validation | Splunk's own tool; required for Splunkbase |
| **bash** | 4.0+ | Deployment scripts | Standard in CI/CD; works with `docker exec` |

---

## Part 1: Python Module Imports in Splunk Apps

### How Splunk Loads Python Handlers

When Splunk starts a `persist` handler (registered in `restmap.conf`), it:

1. Sets `$SPLUNK_HOME/etc/apps/<app_name>/bin` in `sys.path`
2. Imports the handler class directly: `from wl_handler import WhitelistHandler`
3. Instantiates and calls handler methods on every REST request

**Critical detail:** The app's `bin/` directory is added to `sys.path`, so any `.py` file in `bin/` can be imported by name.

### Modular Import Patterns for bin/ Directory

#### Pattern 1: Relative Imports (Recommended)

**File structure:**
```
bin/
  wl_handler.py          # Main handler (imports from submodules)
  wl_csv.py              # CSV operations
  wl_versions.py         # Version control
  wl_approval.py         # Approval workflow
  wl_rbac.py             # Role checking
  wl_audit.py            # Audit events
  wl_validation.py       # Input validation
  wl_constants.py        # Magic numbers and config
```

**In `wl_handler.py`:**
```python
# Relative imports from the same directory
from wl_csv import read_csv, compute_diff
from wl_versions import load_versions, save_version
from wl_approval import submit_approval, process_approval
from wl_rbac import check_user_role
from wl_audit import post_audit_event
from wl_validation import validate_cell, sanitize_filename
from wl_constants import MAX_ROWS, MAX_COLUMNS, EDIT_ROLES

class WhitelistHandler(PersistentServerConnectionApplication):
    def _handle_post(self, request):
        # Use imported functions
        rows = read_csv(csv_path)
        diff = compute_diff(old_rows, new_rows)
        if check_user_role(request, EDIT_ROLES):
            save_version(csv_path, rows)
```

**In `wl_csv.py`:**
```python
# Can also import from other modules
from wl_validation import validate_cell, sanitize_filename
from wl_constants import MAX_ROWS, MAX_COLUMNS

def read_csv(path):
    # Implementation
    pass
```

**Why this works:** Splunk adds `bin/` to `sys.path`, so `from wl_csv import X` resolves to `bin/wl_csv.py`. No sys.path manipulation needed.

#### Pattern 2: Absolute Package Imports (Alternative)

If you want true package structure:
```
bin/
  wl_manager/
    __init__.py          # Empty, marks directory as package
    handler.py           # Main handler
    csv.py               # CSV operations
    versions.py          # Version control
    constants.py         # Magic numbers
  wl_handler.py          # Thin wrapper that imports from wl_manager
```

**In `wl_handler.py` (wrapper):**
```python
from wl_manager.handler import WhitelistHandler
```

**In `wl_manager/handler.py`:**
```python
from wl_manager.csv import read_csv
from wl_manager.versions import load_versions

class WhitelistHandler(PersistentServerConnectionApplication):
    pass
```

**Recommendation:** Use Pattern 1 (flat relative imports) for initial modularization — simpler, fewer files. Migrate to Pattern 2 only if module count exceeds 15.

### Module Dependency Graph

**Leaf modules (no internal dependencies):**
```
wl_constants.py    — Define all magic numbers, config, defaults
wl_validation.py   — Input sanitization, cell/filename/row validation
```

**Mid-level modules (depend on leaves only):**
```
wl_csv.py          — Depends on: wl_constants, wl_validation
wl_versions.py     — Depends on: wl_constants
wl_rbac.py         — Depends on: wl_constants
wl_trash.py        — Depends on: wl_constants
wl_presence.py     — Depends on: wl_constants
```

**High-level modules (can depend on mid-level):**
```
wl_audit.py        — Depends on: wl_constants
wl_limits.py       — Depends on: wl_constants, wl_rbac
wl_approval.py     — Depends on: wl_csv, wl_versions, wl_audit, wl_limits, wl_rbac
```

**Handler (orchestrator, imports everything):**
```
wl_handler.py      — Depends on: all modules above
    └─ class WhitelistHandler(PersistentServerConnectionApplication)
```

**Principle:** Leaf-to-root ordering prevents circular imports. If module A needs module B, B must not need A.

### Testing Python Modules (Unit Tests)

Unit tests run **outside** the Splunk container, with mocked Splunk dependencies.

```python
# tests/test_csv.py
import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Mock Splunk imports BEFORE importing wl_csv
sys.modules['splunk'] = MagicMock()
sys.modules['splunk.persistconn'] = MagicMock()
sys.modules['splunk.rest'] = MagicMock()

# Now import the module (will not fail on missing Splunk SDK)
from wl_csv import read_csv, compute_diff

class TestComputeDiff(unittest.TestCase):
    def test_added_rows(self):
        old = [{"name": "alice"}]
        new = [{"name": "alice"}, {"name": "bob"}]
        diff = compute_diff(old, new)
        self.assertEqual(len(diff["added"]), 1)

    def test_removed_rows(self):
        old = [{"name": "alice"}, {"name": "bob"}]
        new = [{"name": "alice"}]
        diff = compute_diff(old, new)
        self.assertEqual(len(diff["removed"]), 1)

if __name__ == "__main__":
    unittest.main()
```

Run locally: `python -m pytest tests/test_csv.py -v` (no Splunk instance needed).

---

## Part 2: Frontend AMD/RequireJS Module Loading

### How Splunk Loads JavaScript Modules

Splunk ships **RequireJS** (AMD loader) in `$SPLUNK_HOME/share/splunk/modules/`. When a view (SimpleXML) loads:

1. View includes `splunkjs/mvc/simplexml/ready!`
2. This bootstraps RequireJS with Splunk's module config
3. Your code calls `require([...], function(...) {})`
4. RequireJS resolves each module ID to a file path

**Module ID → File path mapping:**
- `jquery` → `$SPLUNK_HOME/share/splunk/modules/jquery.js`
- `underscore` → `$SPLUNK_HOME/share/splunk/modules/underscore.js`
- Custom: `app/wl_manager/wl_rest` → `$SPLUNK_HOME/etc/apps/wl_manager/appserver/static/wl_rest.js`

### Defining AMD Modules

#### Single Export Pattern

**File: `appserver/static/modules/wl_rest.js`**

```javascript
/**
 * REST helper module — shared across all whitelist_manager pages
 */
define(function(require, exports, module) {
    var $ = require('jquery');
    var _ = require('underscore');

    var restGet = function(params) {
        params.output_mode = "json";
        return $.ajax({
            url: "/splunkd/__raw/services/custom/wl_manager",
            type: "GET",
            data: params,
            dataType: "json"
        });
    };

    var restPost = function(data) {
        return $.ajax({
            url: "/splunkd/__raw/services/custom/wl_manager?output_mode=json",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(data),
            dataType: "json"
        });
    };

    return {
        restGet: restGet,
        restPost: restPost
    };
});
```

**Usage in `whitelist_manager.js`:**

```javascript
require([
    "jquery",
    "app/wl_manager/wl_rest",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "splunkjs/mvc/simplexml/ready!"
], function ($, wlRest, mvc, utils) {
    
    wlRest.restGet({action: "get_rules"})
        .done(function(response) {
            console.log(response);
        });
});
```

**Key points:**
- Module ID = relative path under `appserver/static/` without `.js`
- `app/wl_manager/wl_rest` maps to `appserver/static/wl_rest.js`
- Splunk auto-prefixes module paths with `app/wl_manager/`

#### Nested Module Dependencies

**File: `appserver/static/modules/wl_modals.js`**

```javascript
define(function(require, exports, module) {
    var wlRest = require("./wl_rest");
    var $ = require("jquery");

    exports.showAddRowModal = function() {
        return wlRest.restPost({action: "validate_row", ...});
    };
});
```

### Recommended Frontend Module Structure

```
appserver/static/
  whitelist_manager.js          # Main entry point (100 lines)
  control_panel.js              # Admin panel entry
  notifications.js              # Notification system entry
  modules/
    wl_constants.js             # Magic numbers, selectors, config
    wl_rest.js                  # Shared REST helpers
    wl_state.js                 # State management
    wl_table.js                 # Table rendering + inline editing
    wl_search.js                # Search/filter functionality
    wl_modals.js                # Modal dialogs
    wl_versions.js              # Version dropdown + revert UI
    wl_approval_ui.js           # Approval gate checks + submission
    wl_events.js                # Event binding + delegation
    wl_theme.js                 # Dark/light theme toggle
    wl_presence.js              # Presence tracking UI
    wl_csv_io.js                # CSV import/export
  modules_cp/
    wl_cp_queue.js              # Approval queue management
    wl_cp_limits.js             # Daily limits management
    wl_cp_trash.js              # Trash management
    wl_cp_settings.js           # Admin settings
```

### Best Practices for AMD Modules

| Practice | Why | Example |
|----------|-----|---------|
| **One module per file** | Clarity, testability | `wl_rest.js`, `wl_table.js` |
| **Use require() inside define()** | Lazy loading, handles deps | `var $ = require('jquery');` |
| **Return public API only** | Encapsulation | `return { restGet, restPost }` |
| **Prefix custom module IDs** | Avoid conflicts | `app/wl_manager/wl_rest` |

---

## Part 3: Testing Frameworks

### Unit Testing (Python)

**Framework:** `unittest` + `unittest.mock` (standard library)

Run locally without Splunk: `python -m pytest tests/test_csv.py -v`

### Integration Testing (REST API)

**Framework:** `unittest` + `urllib` (standard library) + live Splunk instance

Run against Docker container: `python -m pytest tests/test_integration_save_csv.py -v`

### E2E Testing (Optional, Browser)

**Framework:** Playwright/Selenium (optional, for critical workflows)

Run with headless browser: `python -m pytest tests/test_e2e_save_workflow.py -v`

### Testing Summary

| Tier | Framework | Speed | Purpose |
|------|-----------|-------|---------|
| **Unit** | unittest + mock | <1s/test | Business logic in isolation |
| **Integration** | unittest + urllib | 5-10s/test | REST API contract with live Splunk |
| **E2E** | Playwright (optional) | 30-60s/test | Critical user workflows |

---

## Part 4: AppInspect Rules for Modular Apps

### Critical Python Rules

| Rule | Applies To | Requirement |
|------|-----------|-------------|
| `python_code_patterns_rest_handler_naming` | `bin/wl_handler.py` | Handler class must be named `WhitelistHandler` |
| `python_code_patterns_modular_imports` | All `bin/*.py` files | Can import from `bin/` (no sys.path hacks) |
| `private_code_no_hardcoded_passwords` | All `.py` files | No passwords, API keys in source code |
| `python_version_consistency` | `restmap.conf` | If Python 3, set `python.version = python3` |

### Critical JavaScript Rules

| Rule | Applies To | Requirement |
|------|-----------|-------------|
| `javascript_code_patterns_no_dangerous_functions` | All `.js` files | No dangerous code generation |
| `javascript_code_patterns_no_dom_globals` | All modules | Don't pollute global scope |
| `prohibited_plugins_check` | All `.js` files | Use proper AMD requires |

### File Structure Rules

| Rule | Requirement |
|------|-------------|
| **No `__pycache__` in package** | Add to `.gitignore`: `__pycache__/` |
| **No test files in `bin/`** | Tests go in separate `tests/` directory |
| **`appserver/static/` versioning** | Bump `build` in `app.conf` when JS/CSS changes |

### Modular Structure That Passes AppInspect

```
wl_manager/
  bin/
    wl_handler.py              # REST handler (imports others)
    wl_csv.py                  # CSV operations
    wl_versions.py             # Version control
    wl_approval.py             # Approval workflow
    wl_rbac.py                 # Role checking
    wl_audit.py                # Audit events
    wl_validation.py           # Input validation
    wl_constants.py            # All magic numbers

  appserver/
    static/
      whitelist_manager.js     # Entry point
      control_panel.js         # Admin panel
      modules/
        wl_rest.js             # REST helpers
        wl_table.js            # Table rendering
        wl_constants.js        # Frontend constants

  tests/                       # Separate directory (NOT in bin/)
    test_csv.py                # Unit tests
    test_approval.py           # Unit tests
    test_integration_base.py   # Integration tests

  default/
    app.conf                   # Metadata
    restmap.conf               # Register handler
    authorize.conf             # Custom roles
    indexes.conf               # wl_audit index
    data/ui/views/
      whitelist_manager.xml    # Main dashboard
      control_panel.xml        # Admin panel
```

**Why this passes AppInspect:**
- All Python modules in `bin/` (not scattered)
- Handler class named `WhitelistHandler`
- No test files in `bin/` (separate `tests/` directory)
- No hardcoded passwords in `wl_constants.py`
- Roles follow `wl_*` namespace convention
- AMD modules in `appserver/static/modules/`

---

## Part 5: Validation & Deployment Checklist

### Pre-Commit Checks

**Python modules:**
```bash
python -m py_compile bin/*.py
python -m pytest tests/test_csv.py -v
```

**JavaScript modules:**
```bash
node -c appserver/static/whitelist_manager.js
```

### AppInspect Validation

```bash
./splunk-appinspect/bin/appinspect inspect wl_manager
```

Expected: "Should Pass" (no errors).

### Deployment to Container

```bash
MSYS_NO_PATHCONV=1 docker cp bin/wl_csv.py wl_manager_test:/opt/splunk/etc/apps/wl_manager/bin/
MSYS_NO_PATHCONV=1 docker cp appserver/static/modules/wl_rest.js wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/modules/

# Bump build number in app.conf
# Restart Splunk
```

---

## Summary: Modularization-Focused Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Backend language** | Python 3 | 3.9+ | REST handler, modular business logic |
| **Backend modules** | Python + relative imports | 3.9+ | Modularize wl_handler.py into focused modules |
| **Frontend language** | JavaScript (ES5) | — | UI controllers, client-side logic |
| **Frontend modules** | AMD/RequireJS | Bundled with Splunk | Modularize JS into reusable components |
| **Frontend libs** | jQuery, Underscore, Splunk MVC | Bundled | DOM, utilities, REST client |
| **REST framework** | splunk.persistconn | Bundled | Handler base class |
| **Unit testing** | unittest + unittest.mock | Stdlib | Isolated logic testing (offline) |
| **Integration testing** | unittest + urllib | Stdlib | API contract testing (Docker) |
| **E2E testing** | Playwright (optional) | Latest | Browser automation (critical paths) |
| **Validation** | AppInspect | Latest | Pre-submission compliance |
| **Deployment** | Docker (dev), native Splunk (prod) | 9.3.1 | Test and production |

**Key principle:** Zero external dependencies beyond Splunk-bundled libraries. All testing uses standard library. No build tools, no npm, no bundlers.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|---|---|---|---|
| **Frontend framework** | jQuery + AMD | React, Vue, Preact | AppInspect rejects non-AMD modules; breaks Splunk's lazy-loading |
| **Module system** | RequireJS (AMD) | ES6 modules | Splunk doesn't support; would need build step |
| **Build tool** | None (static assets) | Webpack, Vite | AppInspect rejects bundled code; Splunk expects source files |
| **Backend runtime** | Python 3.9+ | Python 2.7, Node.js | Splunk 9.x only ships Python 3; Node.js not standard in Splunk |
| **Database** | CSV + file locking | PostgreSQL, SQLite | CSV scales to typical whitelist sizes; no infra overhead |
| **REST client** | urllib (stdlib) | requests, httpx | Splunk bundles urllib; no external deps needed |
| **Testing framework** | pytest | Nose2, unittest2 | pytest is standard now; better plugin ecosystem |
| **CI/CD** | GitHub Actions | Jenkins, GitLab CI | Free tier sufficient for open-source Splunk app |

---

## Version Compatibility Matrix

| Splunk Version | Python | jQuery | AMD | Status |
|---|---|---|---|---|
| 8.2 LTS | 2.7 + 3.7 | 1.11 | 2.1 | Supported (Python 3 paths) |
| 9.0 | 3.8 | 1.12 | 2.3 | Supported |
| 9.1 | 3.9 | 1.12 | 2.3 | Supported |
| 9.2 | 3.9 | 1.12 | 2.3 | Supported |
| 9.3 | 3.11 | 1.12 | 2.3 | Supported (current test env) |
| 9.4 | 3.11 | 1.12 | 2.3 | Likely supported (not tested) |

**Recommendation:** Test on 9.2+ (all ship Python 3 only).

---

## Confidence Assessment

| Area | Confidence | Reasoning |
|------|------------|-----------|
| **Python imports in Splunk apps** | HIGH | Modularization via relative imports is Splunk standard |
| **AMD/RequireJS module definition** | HIGH | Splunk bundles RequireJS; existing controls use require() |
| **Testing frameworks** | HIGH | Integration tests exist; unittest is stdlib |
| **AppInspect rules** | MEDIUM-HIGH | Rules align with current codebase practices |
| **Circular import prevention** | HIGH | Leaf-to-root ordering prevents cycles |

---

## Gaps & Open Questions

1. **Official AppInspect rules:** Exact list of ~100 validation rules not fully documented. Will run tool on first pass and document findings.

2. **Module count performance:** Large count (~15-20 modules) may impact startup time. Phase 5 should benchmark.

3. **Windows file locking:** Current code uses `fcntl` (Linux only). Phase 1 should verify `msvcrt` behavior.

---

*Stack research completed: 2026-03-31*  
*Ready for Phase 1 implementation planning*
