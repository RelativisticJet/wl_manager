# Phase 4: Backend Integration - Research

**Researched:** 2026-04-01  
**Domain:** REST handler refactoring, dispatch table architecture, approval replay orchestration  
**Confidence:** HIGH

## Summary

Phase 4 refactors wl_handler.py from a 5,909-line monolith (containing all business logic inline) into a thin REST router (~200 lines) that dispatches to the 16 domain modules extracted in Phases 1-3, plus a new wl_replay.py orchestration layer for approval queue execution. The refactoring is a pure structural rework with **zero functional or API contract changes** — every existing action continues to work identically.

**Primary recommendation:** Implement handler refactoring via dispatch tables with dict-based routing and _action_* methods; create wl_replay.py as a dedicated orchestration module (150 lines max per function per BMOD-13); integrate wl_approval and wl_replay sequentially via a call chain handler → approval → replay → domain modules; verify all ~15 REST actions with live Docker container testing after each wave of handler rewrites.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Dict dispatch tables** at class level using string method names resolved via `getattr(self, method_name)`
- **Separate GET_ACTIONS and POST_ACTIONS dispatch tables** with None as required_roles for no-RBAC actions
- **Handlers prefixed with `_action_`** (e.g., `_action_save_csv`) and called via shared `_dispatch()` method
- **Shared _dispatch()** handles: table lookup → auth check (reject "unknown" users for ALL actions) → RBAC check → handler call → access log
- **Router passes parsed query** to GET handlers; POST handlers receive payload directly
- **Handler functions receive** (self, request, payload/query, user, roles) and parse their own params
- **Structured access log** with JSON to rotating file: {type, action, user, method, status, duration_ms, payload_bytes, ts}
- **Standardized error responses** to {error: msg}; success responses include {success: true} only when no other data
- **New wl_replay.py module** (Layer 5): dedicated replay orchestration called by wl_approval on approval decision
- **Replay validates preconditions** (CSV exists, rule exists) before executing — per MEMORY.md lessons
- **Pipeline functions stay in their modules** (save_csv_pipeline in wl_csv.py, revert_csv_pipeline in wl_versions.py, etc.)
- **Fail-fast imports**: no try/except guards on internal module imports (except wl_trash → wl_approval for circular dep via lazy import)
- **One commit per wave** (not per handler): 3-6 commits total across handler rewrite

### Claude's Discretion

- Exact handler function implementation details within the pipeline pattern
- Number of waves and grouping of handler rewrites
- Integration test helper fixture design
- Whether wl_wrapper.py is merged into handler or deleted outright
- Exact line count for final handler (quality over size)

### Deferred Ideas (OUT OF SCOPE)

- Read/write lock semantics — deferred until performance data
- Custom exception hierarchy — standard Python exceptions sufficient
- Plugin/registration API for replay handlers — fixed set sufficient
- Performance profiling and optimization — Phase 4 is refactoring
- Frontend integration testing — deferred to Phase 5-7

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BMOD-01 | wl_handler.py split into thin REST router (~200 lines) that delegates to domain modules | Handler dispatch table pattern, router structure, 16 module integration points identified |
| TEST-01 | Unit test suite covering ≥80% of every backend module (partial) | Existing 40+ unit tests in tests/unit/; Phase 4 adds handler integration tests |
| TEST-02 | Integration tests for all REST API action handlers against live container | Docker test strategy, 15+ action handler coverage, parametrized RBAC matrix testing |

## Standard Stack

### Core Framework & Utilities
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.9+ | Backend runtime | Splunk 9.x ships Python 3 only |
| Splunk SDK (splunklib) | 1.7+ | REST API, session management | Official Splunk library for programmatic access |
| pytest | 7.0+ | Unit/integration test runner | Industry standard, Splunk-compatible, 40+ existing tests |
| freezegun | 1.2+ | Deterministic time mocking | Used in Phase 1-3 tests for timestamp control |
| unittest.mock | Built-in | Patch/MagicMock decorators | Standard Python mocking library |

### Handler Infrastructure (Splunk)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PersistentServerConnectionApplication | Splunk 9.3.1 | Base handler class | Required by Splunk; handle() is entry point |
| fcntl | Built-in (Unix) | File locking | Cross-process synchronization; no-op on Windows |
| json | Built-in | Request/response serialization | HTTP payloads in/out |
| logging.handlers.RotatingFileHandler | Built-in | Audit log rotation | 100 MB max, 10 backups |

### Testing Fixtures
| Tool | Purpose | Current Status |
|------|---------|-----------------|
| Docker Compose | Splunk 9.3.1 container (wl_manager_test) | Running; credentials: admin/Chang3d! |
| pytest-mock | @patch decorators for offline testing | Used in all existing unit tests |
| Docker test harness | Live container smoke tests | To be implemented in Phase 4 |
| REST client mock | Offline handler harness | To be implemented in Phase 4 |

## Architecture Patterns

### REST Router Pattern (Dispatch Table)

The handler uses a **class-level dispatch table** with string method names resolved via `getattr()`. This pattern is efficient (single per-request resolution, no per-instance rebuild) and separates routing logic from action handlers.

```python
# Source: Phase 4 design, wl_handler.py structure
class WhitelistHandler(PersistentServerConnectionApplication):
    # Dispatch tables map action_name -> (required_roles_set, method_name_string)
    GET_ACTIONS = {
        "get_rules": (None, "_action_get_rules"),
        "get_csvs": (None, "_action_get_csvs"),
        "get_csv_content": (None, "_action_get_csv_content"),
        # ... 12+ GET actions
    }
    
    POST_ACTIONS = {
        "save_csv": (EDIT_ROLES, "_action_save_csv"),
        "create_csv": (EDIT_ROLES, "_action_create_csv"),
        "save_col_widths": (None, "_action_save_col_widths"),
        "process_approval": (ADMIN_ROLES, "_action_process_approval"),
        # ... 12+ POST actions
    }
    
    def _dispatch(self, table, action, request, user, roles, payload=None, query=None):
        """Shared dispatch logic: auth check -> RBAC check -> call handler."""
        if user == "unknown":
            return self._resp(401, {"error": "Session expired"})
        
        if action not in table:
            return self._resp(400, {"error": f"Unknown action: {action}"})
        
        required_roles, method_name = table[action]
        if required_roles and not roles.intersection(required_roles):
            return self._resp(403, {"error": "Permission denied"})
        
        handler = getattr(self, method_name)
        return handler(request, payload or query, user, roles)
    
    def _action_save_csv(self, request, payload, user, roles):
        """Handler for save_csv action."""
        # Parse payload, call pipeline, handle errors
        pass
    
    def _action_process_approval(self, request, payload, user, roles):
        """Handler for process_approval — delegates to wl_approval/wl_replay."""
        # Call wl_approval.process_approval() which dispatches to wl_replay
        pass
```

### Layer 5: Approval Replay Orchestration

**wl_replay.py** (new module) executes approved actions by calling domain module pipelines. Replay is **distinct from approval queue management** — wl_approval handles queue CRUD, check_conflicts, auto-cancel; wl_replay executes approved actions.

```python
# Source: Phase 4 design, wl_replay.py module structure
from wl_csv import save_csv_pipeline, create_csv_pipeline
from wl_versions import revert_csv_pipeline
from wl_rules import create_rule_pipeline
from wl_trash import remove_csv_pipeline, remove_rule_pipeline
from wl_audit import post_audit_event

# Internal dispatch for replay actions
REPLAY_HANDLERS = {
    "save_csv": _execute_replay_save_csv,
    "add_row": _execute_replay_save_csv,  # Same pipeline
    "remove_rows": _execute_replay_save_csv,  # Same pipeline
    "create_csv": _execute_replay_create_csv,
    "create_rule": _execute_replay_create_rule,
    "delete_csv": _execute_replay_delete_csv,
    "delete_rule": _execute_replay_delete_rule,
    "revert_csv": _execute_replay_revert_csv,
}

def execute_approved_action(context, request_item):
    """
    Execute an approved action via domain module pipelines.
    
    Args:
        context: ReplayContext dict with {original_analyst, approving_admin, 
                 second_admin, is_dual_admin, request_id, action_type, session_key, approved_at}
        request_item: Approval queue entry (dict)
    
    Returns:
        {success: bool, message: str, data: dict, error: str, error_type: str}
    """
    action_type = request_item.get("action_type")
    if action_type not in REPLAY_HANDLERS:
        return {"success": False, "error": f"Unknown action type: {action_type}"}
    
    # Validate preconditions before executing
    csv_file = request_item.get("csv_file")
    detection_rule = request_item.get("detection_rule")
    
    if action_type in ["save_csv", "add_row", "remove_rows", "revert_csv"]:
        if not os.path.exists(csv_file):
            return {"success": False, "error": "CSV file no longer exists", "error_type": "missing_csv"}
    
    if action_type in ["create_rule", "delete_rule"]:
        if not detection_rule:
            return {"success": False, "error": "Detection rule not specified"}
    
    # Execute via replay handler
    handler = REPLAY_HANDLERS[action_type]
    return handler(context, request_item)

def _execute_replay_save_csv(context, request_item):
    """Execute save_csv/add_row/remove_rows via save_csv_pipeline."""
    payload = request_item.get("payload", {})
    csv_file = payload.get("csv_file")
    new_rows = payload.get("rows", [])
    
    try:
        success, message = save_csv_pipeline(csv_file, new_rows, expected_mtime=None)
        if not success:
            return {"success": False, "error": message}
        
        # Post audit event for this replay
        event = build_audit_event(
            action="replay_" + request_item.get("action_type"),
            analyst=context["original_analyst"],
            detection_rule=request_item.get("detection_rule", ""),
            csv_file=csv_file,
            comment=f"Replayed by admin {context['approving_admin']}"
        )
        post_audit_event(context["session_key"], event)
        
        return {"success": True, "message": "Action replayed successfully"}
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": "execution_error"}
```

### Handler Refactoring Waves

Phase 4 execution follows **3-6 waves**, each rewriting a cohort of related handlers:

1. **Wave 1: GET Actions** (10+ read-only handlers)
   - get_rules, get_csvs, get_csv_content, get_mapping, get_versions, check_csv_status, report_presence, get_col_widths, get_apps, check_daily_limit_status, get_pending_approvals, get_request_csv, get_notifications
   - Simple: parse query params, call domain modules, return response
   - No state changes; no approval gates

2. **Wave 2: Simple POST Actions** (5-6 stateless handlers)
   - save_col_widths, log_event, mark_notifications_read, cancel_request, save_as_default, reset_factory_defaults
   - Simple: validate input, update config/state, return success
   - No complex pipelines

3. **Wave 3: Complex POST Actions + Admin** (8+ handlers with pipelines and approval)
   - save_csv, create_csv, add_rule, delete_rule, add_rule_to_csv, remove_rule_from_csv, delete_csv, process_approval
   - Calls domain module pipelines (save_csv_pipeline, create_csv_pipeline, etc.)
   - Approval gate checks, limit enforcement
   - process_approval delegates to wl_approval → wl_replay

### Layered Error Handling

The handler follows a **fail-closed pattern** (return error rather than proceed partially):

```python
# Layered error handling in dispatch and handlers
def _action_save_csv(self, request, payload, user, roles):
    try:
        # Precondition checks
        csv_file = payload.get("csv_file")
        if not csv_file:
            return self._resp(400, {"error": "csv_file required"})
        
        # Domain operation (may raise ValueError, FileNotFoundError, IOError, PermissionError)
        success, message = save_csv_pipeline(csv_file, rows, expected_mtime)
        if not success:
            return self._resp(400, {"error": message})
        
        # Audit logging (non-blocking)
        try:
            post_audit_event(session_key, event)
        except Exception:
            _logger.exception("Failed to post audit event")  # Log but don't fail
        
        return self._resp(200, {"csv_file": csv_file, "success": True})
    
    except ValueError as e:
        return self._resp(400, {"error": str(e)})
    except FileNotFoundError as e:
        return self._resp(404, {"error": "CSV file not found"})
    except PermissionError as e:
        return self._resp(403, {"error": "Permission denied"})
    except IOError as e:
        return self._resp(500, {"error": "File I/O error"})
    except Exception as e:
        _logger.exception("Unhandled exception in _action_save_csv: %s", e)
        return self._resp(500, {"error": "An internal error occurred"})
```

### Module Dependency Graph

Phase 4 completes a **5-layer architecture** with explicit import ordering:

```
Layer 0: wl_constants (no imports from wl_*)
  ↓
Layer 1: wl_logging (no imports from wl_* except constants)
  ↓
Layer 2: wl_validation, wl_ratelimit, wl_rbac, wl_presence (import L0-1 only)
  ↓
Layer 3: wl_csv, wl_rules, wl_trash, wl_versions, wl_audit (import L0-2 + L3 peer)
  ↓
Layer 4: wl_filelock, wl_limits, wl_approval (import L0-3 + L4 peer)
  ↓
Layer 5: wl_replay (NEW — imports L0-4)
  ↓
Layer 0 (Handler): wl_handler.py (imports all L0-5 + external libraries)
```

**Special case — circular dependency resolution:**
- wl_trash needs wl_approval.cancel_conflicts() (to cancel on remove_rule)
- wl_approval needs wl_replay.execute_approved_action()
- **Solution:** wl_trash uses lazy import: `from wl_approval import cancel_conflicts` inside function, not at module level

### Module Consolidation

**wl_wrapper.py (362 lines):** This file is a duplicate wrapper layer. Per CONTEXT.md decision "wl_wrapper.py in scope — merge into handler or eliminate", the implementation will either:
1. Merge its functions into wl_handler.py if they provide reusable helpers
2. Delete it entirely if redundant

Current inspection shows wl_wrapper.py likely contains adapter functions — will be eliminated if its logic is already in handler or modules.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|------------|-------------|-----|
| REST dispatch routing | Custom if/elif chains | Class-level dispatch table with getattr() | Easier to extend, audit completeness, reduce BMOD-13 violations |
| Approval workflow execution | Inline handlers with approval checks | wl_approval + wl_replay two-layer split | Separates queue management from execution; enables replay testing in isolation |
| Pipeline orchestration for complex actions | Nested try/except/finally in handler | Domain module pipeline functions (save_csv_pipeline, revert_csv_pipeline) | Modules are testable, reusable, composable; handler stays thin |
| File locking for concurrent writes | Custom fcntl wrapper | wl_filelock.file_lock context manager | Already extracted, tested, handles Windows no-op |
| Audit event construction | Inline dicts in every handler | wl_audit.build_audit_event() | Consistent event schema, single source of truth |
| RBAC checks | Inline role.intersection() in handlers | wl_rbac predicates (is_admin, is_editor) + dispatch table | Centralized, testable, reduces duplication |

**Key insight:** The entire refactoring goal is to **eliminate hand-rolled inline logic** from the handler — everything should be a module import. If a handler is >30 lines, it's likely doing too much and should delegate to a pipeline function.

## Common Pitfalls

### Pitfall 1: Dispatch Table Incompleteness

**What goes wrong:** Handler has 15 actions but only 12 in dispatch tables; new actions added without updating tables; orphaned methods in handler never called.

**Why it happens:** Tables are defined once at class init; easy to forget updating both GET_ACTIONS and POST_ACTIONS.

**How to avoid:** 
1. Create **dispatch completeness test**: Verify all _action_* methods exist in tables; verify all table entries resolve to methods
2. Generate valid_actions list from table keys for frontend validation
3. Grep for all "action ==" checks in handler to find missing table entries

**Warning signs:** Frontend shows "unknown action" error; dead code warnings in linter; audit events missing for an action type.

**Verification in Phase 4:**
```python
def test_dispatch_table_completeness():
    """Verify no orphaned handlers or stale table entries."""
    handler = WhitelistHandler(None, None)
    
    # All table entries must have handlers
    for action, (roles, method_name) in {**handler.GET_ACTIONS, **handler.POST_ACTIONS}.items():
        assert hasattr(handler, method_name), f"Handler {method_name} not found for action {action}"
        assert callable(getattr(handler, method_name))
    
    # All _action_* methods must be in a table
    for attr_name in dir(handler):
        if attr_name.startswith("_action_"):
            found = False
            for action, (_, method_name) in {**handler.GET_ACTIONS, **handler.POST_ACTIONS}.items():
                if method_name == attr_name:
                    found = True
                    break
            assert found, f"Orphaned handler {attr_name} not in dispatch tables"
```

### Pitfall 2: Precondition Validation in Replay

**What goes wrong:** Approved action replayed but CSV file was deleted between approval and replay; handler crashes; audit trail is incomplete.

**Why it happens:** Time gap between submit and approval creates window for race conditions; state can change.

**How to avoid:**
1. **Validate preconditions in wl_replay before executing** — CSV exists, rule exists, mapping valid
2. **Return structured error dict** (not exception) with error_type field so handler can auto-cancel conflicting requests
3. **Replay must be idempotent** where possible — applying same edit twice should be safe

**Warning signs:** "File not found" exceptions during process_approval; audit events with partial data; approval queue enters invalid state.

**Per MEMORY.md lesson:** "Queued operations must re-validate preconditions at execution time — approval queue processes requests independently."

### Pitfall 3: Handler Function Size (BMOD-13)

**What goes wrong:** Handler method >100 lines combines logic that should be in modules; becomes hard to test, violates BMOD-13.

**Why it happens:** Easy to add "just one more check" before calling a pipeline; logic balloons gradually.

**How to avoid:**
1. **Handlers should be thin wrappers:** Parse input (5-10 lines), call domain pipeline (1-2 lines), handle error (5-10 lines), post audit (3-5 lines)
2. **Extract reusable helpers to modules** — don't duplicate in handler
3. **Each _action_* handler target: <40 lines** (leaves room for error handling)

**Warning signs:** cyclomatic complexity >15; code review flags "this function does too much".

### Pitfall 4: Backward Compatibility Break

**What goes wrong:** New handler response shape breaks audit.xml dashboard queries; frontend gets unexpected fields; existing audit events can't be parsed.

**Why it happens:** API contract is the stability boundary — frontend and dashboards depend on exact field names.

**How to avoid:**
1. **Freeze REST API shapes** — no new request/response fields without explicit plan
2. **Test backward compatibility:** Run existing audit.xml SPL queries post-refactoring
3. **Verify audit event schema hasn't changed** — test building old audit events still parses correctly

**Warning signs:** audit.xml searches return empty; frontend shows "undefined" in status; existing notification templates break.

### Pitfall 5: Circular Import in Modules

**What goes wrong:** wl_trash imports wl_approval at module level; wl_approval imports wl_replay; wl_replay imports wl_csv; import fails with circular dependency error.

**Why it happens:** Domain modules need each other for edge cases (trash needs to cancel pending requests).

**How to avoid:**
1. **Use lazy imports for circular deps:** Import inside function, not at module level
2. **Document the cycle** in module docstring with rationale
3. **Test import order:** Add import cycle detection test

**Warning signs:** "ImportError: cannot import name X" on module load; import statement commented out with "# TODO fix circular dep".

**Applied in Phase 4:** wl_trash.py has `from wl_approval import cancel_conflicts` inside remove_rule_pipeline() function, not at top level.

### Pitfall 6: RBAC Matrix Gaps

**What goes wrong:** Dispatch table correctly checks role X for action A, but a second call path to the same action bypasses the check (per MEMORY.md: "dual UI paths to same action must share validation").

**Why it happens:** Multiple handlers call same domain function; not all handlers have RBAC check.

**How to avoid:**
1. **Create RBAC matrix test:** Every action × every role combination, verify correct 403/200 response
2. **Parameterize test** to run all combinations automatically
3. **Document role requirements per action** in dispatch table comments

**Warning signs:** Inconsistent permission errors; analysts can do admin-only actions; audit events exist for actions that should be forbidden.

### Pitfall 7: Approval Replay Missing Audit Context

**What goes wrong:** Action approved and replayed, but audit event is missing original analyst name, original reason, or admin who approved.

**Why it happens:** wl_replay() calls domain pipelines directly; doesn't inject context.

**How to avoid:**
1. **Pass ReplayContext dict** to wl_replay with {original_analyst, approving_admin, second_admin, is_dual_admin, session_key}
2. **Replay posts audit event** with comment like "Replayed by admin jdoe on 2026-04-01"
3. **Store context in approval queue entry** so replay can retrieve it

**Warning signs:** Audit events for replayed actions missing analyst name; no way to trace who approved what; can't distinguish user action from replay.

## Code Examples

### Example 1: Dispatch Table with RBAC

```python
# Source: Phase 4 design, wl_handler.py class definition
class WhitelistHandler(PersistentServerConnectionApplication):
    """Splunk REST handler for Whitelist Manager."""
    
    # GET action dispatch table: action_name -> (required_roles, method_name)
    GET_ACTIONS = {
        "get_rules":                   (None,         "_action_get_rules"),
        "get_csvs":                    (None,         "_action_get_csvs"),
        "get_csv_content":             (None,         "_action_get_csv_content"),
        "get_mapping":                 (None,         "_action_get_mapping"),
        "get_versions":                (None,         "_action_get_versions"),
        "check_csv_status":            (None,         "_action_check_csv_status"),
        "report_presence":             (None,         "_action_report_presence"),
        "get_col_widths":              (None,         "_action_get_col_widths"),
        "get_apps":                    (None,         "_action_get_apps"),
        "check_daily_limit_status":    (None,         "_action_check_daily_limit_status"),
        "get_pending_approvals":       (None,         "_action_get_pending_approvals"),
        "get_request_csv":             (ADMIN_ROLES,  "_action_get_request_csv"),
        "get_notifications":           (None,         "_action_get_notifications"),
    }
    
    # POST action dispatch table: action_name -> (required_roles, method_name)
    POST_ACTIONS = {
        "save_col_widths":             (None,         "_action_save_col_widths"),
        "log_event":                   (EDIT_ROLES,   "_action_log_event"),
        "mark_notifications_read":     (None,         "_action_mark_notifications_read"),
        "submit_approval":             (EDIT_ROLES,   "_action_submit_approval"),
        "check_approval_gate":         (EDIT_ROLES,   "_action_check_approval_gate"),
        "cancel_request":              (EDIT_ROLES,   "_action_cancel_request"),
        "process_approval":            (ADMIN_ROLES,  "_action_process_approval"),
        "get_approval_queue":          (ADMIN_ROLES,  "_action_get_approval_queue"),
        "get_daily_limits":            (ADMIN_ROLES,  "_action_get_daily_limits"),
        "set_daily_limits":            (ADMIN_ROLES,  "_action_set_daily_limits"),
        "get_analyst_usage":           (ADMIN_ROLES,  "_action_get_analyst_usage"),
        "reset_daily_usage":           (ADMIN_ROLES,  "_action_reset_daily_usage"),
        "save_as_default":             (ADMIN_ROLES,  "_action_save_as_default"),
        "reset_factory_defaults":      (ADMIN_ROLES,  "_action_reset_factory_defaults"),
    }
```

### Example 2: Thin Handler Delegating to Pipeline

```python
# Source: Phase 4 design pattern for _action_save_csv
def _action_save_csv(self, request, payload, user, roles):
    """Save CSV rows, compute diff, write audit event."""
    csv_file = payload.get("csv_file", "").strip()
    new_rows = payload.get("rows", [])
    comment = payload.get("comment", "").strip()
    expected_mtime = payload.get("expected_mtime")
    
    # Input validation
    if not csv_file:
        return self._resp(400, {"error": "csv_file required"})
    if not isinstance(new_rows, list):
        return self._resp(400, {"error": "rows must be a list"})
    
    # Check daily limits before attempting operation
    ok, msg = check_analyst_limit(user, "save_csv")
    if not ok:
        return self._resp(429, {"error": msg})
    
    # Call pipeline (handles file locking, diff, versioning internally)
    success, message = save_csv_pipeline(csv_file, new_rows, expected_mtime)
    if not success:
        return self._resp(400, {"error": message})
    
    # Increment usage counter
    increment_daily_limit(user, "save_csv")
    
    # Post audit event
    event = build_audit_event(
        action="save_csv",
        analyst=user,
        detection_rule=_get_rule_for_csv(csv_file),
        csv_file=csv_file,
        comment=comment,
    )
    post_audit_event(request.get("session_key"), event)
    
    return self._resp(200, {"csv_file": csv_file, "success": True})
```

### Example 3: wl_replay Module Structure

```python
# Source: Phase 4 design, wl_replay.py (new module)
"""
Approval Replay Orchestration Layer

Executes approved actions by calling domain module pipelines.
Separates queue management (wl_approval) from execution (wl_replay).

Public API:
    execute_approved_action(context, request_item) -> dict
"""

import sys
import os
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wl_csv import save_csv_pipeline, create_csv_pipeline
from wl_versions import revert_csv_pipeline
from wl_rules import create_rule_pipeline
from wl_trash import remove_csv_pipeline, remove_rule_pipeline
from wl_audit import build_audit_event, post_audit_event
from wl_logging import get_audit_logger

__all__ = ["execute_approved_action"]

_logger = get_audit_logger()


def execute_approved_action(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute an approved request by calling its domain module pipeline.
    
    Args:
        context: ReplayContext dict with keys:
            - original_analyst (str): User who submitted the request
            - approving_admin (str): Admin who approved it
            - second_admin (str or None): Second admin for dual approval
            - is_dual_admin (bool): Whether dual approval was required
            - request_id (str): Unique request identifier
            - action_type (str): Type of action (save_csv, delete_rule, etc.)
            - session_key (str): Splunk session for audit posting
            - approved_at (str): ISO timestamp of approval
        
        request_item: Approval queue entry dict with keys:
            - request_id, action_type, analyst, timestamp
            - csv_file, detection_rule (if applicable)
            - payload: {headers, rows, csv_file, etc.}
    
    Returns:
        Result dict with keys:
        - success (bool): Whether operation succeeded
        - message (str): Human-readable status message
        - data (dict): Operation result data (csv_file, rows affected, etc.)
        - error (str or None): Error message if failed
        - error_type (str or None): Category of error (missing_csv, validation_error, etc.)
    """
    action_type = request_item.get("action_type", "")
    
    # Validate action type
    if action_type not in _REPLAY_HANDLERS:
        _logger.error("Unknown replay action type: %s (request_id=%s)", action_type, context.get("request_id"))
        return {
            "success": False,
            "error": f"Unknown action type: {action_type}",
            "error_type": "invalid_action_type",
        }
    
    # Dispatch to appropriate replay function
    handler_fn = _REPLAY_HANDLERS[action_type]
    try:
        return handler_fn(context, request_item)
    except Exception as e:
        _logger.exception("Replay execution failed for action %s (request_id=%s): %s",
                         action_type, context.get("request_id"), e)
        return {
            "success": False,
            "error": f"Execution failed: {str(e)[:100]}",
            "error_type": "execution_exception",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Replay action handlers — each calls domain module pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _replay_save_csv(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """Replay save_csv action via save_csv_pipeline."""
    csv_file = request_item.get("csv_file", "")
    payload = request_item.get("payload", {})
    rows = payload.get("rows", [])
    
    # Validate preconditions
    if not os.path.exists(csv_file):
        return {"success": False, "error": "CSV file no longer exists", "error_type": "missing_csv"}
    
    # Call pipeline
    success, message = save_csv_pipeline(csv_file, rows, expected_mtime=None)
    if not success:
        return {"success": False, "error": message, "error_type": "pipeline_error"}
    
    # Post audit event
    _post_replay_audit(context, request_item, "replay_save_csv")
    
    return {"success": True, "message": "CSV saved via replay", "data": {"csv_file": csv_file}}


def _replay_delete_csv(context: Dict[str, Any], request_item: Dict[str, Any]) -> Dict[str, Any]:
    """Replay delete_csv action via remove_csv_pipeline."""
    csv_file = request_item.get("csv_file", "")
    
    # Validate preconditions
    if not os.path.exists(csv_file):
        return {"success": False, "error": "CSV file no longer exists", "error_type": "missing_csv"}
    
    # Call pipeline
    success, message = remove_csv_pipeline(csv_file)
    if not success:
        return {"success": False, "error": message, "error_type": "pipeline_error"}
    
    # Post audit event
    _post_replay_audit(context, request_item, "replay_delete_csv")
    
    return {"success": True, "message": "CSV deleted via replay", "data": {"csv_file": csv_file}}


# Internal dispatch table
_REPLAY_HANDLERS = {
    "save_csv": _replay_save_csv,
    "add_row": _replay_save_csv,  # Same pipeline
    "remove_rows": _replay_save_csv,  # Same pipeline
    "create_csv": _replay_create_csv,
    "delete_csv": _replay_delete_csv,
    "create_rule": _replay_create_rule,
    "delete_rule": _replay_delete_rule,
    "revert_csv": _replay_revert_csv,
}


def _post_replay_audit(context: Dict[str, Any], request_item: Dict[str, Any], action: str) -> None:
    """Post an audit event for a replayed action."""
    try:
        event = build_audit_event(
            action=action,
            analyst=context.get("original_analyst", ""),
            detection_rule=request_item.get("detection_rule", ""),
            csv_file=request_item.get("csv_file", ""),
            comment=f"Replayed by admin {context.get('approving_admin')} "
                   f"(request {context.get('request_id')})",
        )
        post_audit_event(context.get("session_key"), event)
    except Exception as e:
        _logger.exception("Failed to post replay audit event: %s", e)
        # Non-blocking; continue even if audit fails
```

### Example 4: Integration Test for Dispatch Completeness

```python
# Source: Phase 4 testing strategy, tests/integration/test_handler_dispatch.py
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

from wl_handler import WhitelistHandler


class TestDispatchTableCompleteness:
    """Verify dispatch tables and handlers are synchronized."""
    
    def test_all_get_handlers_exist(self):
        """Every entry in GET_ACTIONS must have a corresponding handler method."""
        handler = WhitelistHandler(None, None)
        for action, (roles, method_name) in handler.GET_ACTIONS.items():
            assert hasattr(handler, method_name), \
                f"GET action '{action}' references non-existent method {method_name}"
            assert callable(getattr(handler, method_name)), \
                f"GET handler {method_name} for action '{action}' is not callable"
    
    def test_all_post_handlers_exist(self):
        """Every entry in POST_ACTIONS must have a corresponding handler method."""
        handler = WhitelistHandler(None, None)
        for action, (roles, method_name) in handler.POST_ACTIONS.items():
            assert hasattr(handler, method_name), \
                f"POST action '{action}' references non-existent method {method_name}"
            assert callable(getattr(handler, method_name)), \
                f"POST handler {method_name} for action '{action}' is not callable"
    
    def test_no_orphaned_handlers(self):
        """Every _action_* method must be in GET_ACTIONS or POST_ACTIONS."""
        handler = WhitelistHandler(None, None)
        all_actions = {**handler.GET_ACTIONS, **handler.POST_ACTIONS}
        
        for attr_name in dir(handler):
            if attr_name.startswith("_action_"):
                found = any(method_name == attr_name for _, method_name in all_actions.values())
                assert found, f"Handler method {attr_name} not registered in any dispatch table"
    
    @pytest.mark.parametrize("action", [
        "get_rules", "get_csvs", "get_csv_content", "get_mapping",
        "get_versions", "check_csv_status", "report_presence",
        "get_col_widths", "get_apps", "check_daily_limit_status",
        "get_pending_approvals", "get_request_csv", "get_notifications",
    ])
    def test_get_action_coverage(self, action):
        """Verify all expected GET actions are in the dispatch table."""
        handler = WhitelistHandler(None, None)
        assert action in handler.GET_ACTIONS, f"Missing GET action: {action}"
    
    @pytest.mark.parametrize("action", [
        "save_col_widths", "log_event", "mark_notifications_read",
        "submit_approval", "check_approval_gate", "cancel_request",
        "process_approval", "get_approval_queue", "get_daily_limits",
        "set_daily_limits", "get_analyst_usage", "reset_daily_usage",
        "save_as_default", "reset_factory_defaults",
    ])
    def test_post_action_coverage(self, action):
        """Verify all expected POST actions are in the dispatch table."""
        handler = WhitelistHandler(None, None)
        assert action in handler.POST_ACTIONS, f"Missing POST action: {action}"


class TestRBACEnforcement:
    """Verify RBAC checks in dispatch table."""
    
    def test_admin_only_actions(self):
        """Verify actions requiring ADMIN_ROLES are correctly marked."""
        handler = WhitelistHandler(None, None)
        admin_actions = [
            "process_approval", "get_approval_queue", "get_daily_limits",
            "set_daily_limits", "get_analyst_usage", "reset_daily_usage",
        ]
        for action in admin_actions:
            roles, _ = handler.POST_ACTIONS[action]
            assert roles is not None, f"Admin action {action} has None required_roles"
            assert "admin" in str(roles).lower(), f"Admin action {action} roles: {roles}"
    
    def test_editor_actions(self):
        """Verify actions requiring EDIT_ROLES are correctly marked."""
        handler = WhitelistHandler(None, None)
        editor_actions = ["submit_approval", "check_approval_gate", "cancel_request"]
        for action in editor_actions:
            roles, _ = handler.POST_ACTIONS[action]
            assert roles is not None, f"Editor action {action} has None required_roles"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Inline action handlers in wl_handler.py (~200 lines each) | Thin dispatch table routes to module pipelines | Phase 4 | Handler shrinks 5909→~200 lines; logic moves to tested modules |
| Inline CSV operations in handler | wl_csv.py with save_csv_pipeline(), compute_diff() (Phase 2) | Phase 2 | CSV logic reusable, testable, independent |
| Inline version control in handler | wl_versions.py with snapshot_version(), manifest management (Phase 2) | Phase 2 | Version snapshots atomic; manifest collision-safe |
| Inline approval queue CRUD in handler | wl_approval.py module with submit_approval(), process_approval() (Phase 3) | Phase 3 | Queue management separated from execution |
| N/A | wl_replay.py NEW — approval execution orchestration (Phase 4) | Phase 4 | Approval and replay decoupled; replay testable in isolation |
| Inline audit event construction | wl_audit.build_audit_event() + post_audit_event() (Phase 2) | Phase 2 | Consistent event schema; single source of truth |
| Inline RBAC checks scattered | wl_rbac.py predicates + dispatch table (Phase 1) | Phase 1 | Centralized RBAC; single policy change point |

## Open Questions

1. **wl_wrapper.py disposal**
   - What we know: 362-line file; likely duplicate wrapper layer
   - What's unclear: Is its logic already in handler or is it reusable?
   - Recommendation: Inspect during Phase 4 Wave 1; if redundant, delete; if reusable, merge functions into handler

2. **Approval replay latency impact**
   - What we know: process_approval now chains through wl_approval → wl_replay → domain modules (depth 4)
   - What's unclear: Will extra function call depth cause observable latency?
   - Recommendation: Benchmark 5 most common replay actions post-Phase 4; accept <10% regression; optimize if >10%

3. **Docker test harness implementation**
   - What we know: Tests exist (unit + integration); Docker container running with Splunk 9.3.1
   - What's unclear: Exact format for Docker smoke tests (REST harness vs raw curl vs pytest-splunk-sdk)
   - Recommendation: Use REST harness with @pytest.mark.docker marker; auto-skip if container unavailable; deploy all wl_*.py before test

4. **Handler function boundary (≤40 lines target)**
   - What we know: BMOD-13 requires <100 lines; Phase 4 targets ~40 lines per handler
   - What's unclear: Can all handlers hit 40 lines, or are some inherently complex?
   - Recommendation: Process_approval likely 40-50 lines (approval + replay dispatch); most others 20-30 lines

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.0+ (unit + integration); Docker container (smoke) |
| Config file | tests/pytest.ini (unit + integration); no config needed for Docker |
| Quick run command | `pytest tests/unit -v --tb=short` (~5s) |
| Full suite command | `pytest tests/ tests/integration/ -v` + Docker smoke tests (~60s) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BMOD-01 | Handler is thin router ~200 lines, all logic in modules | unit | `pytest tests/unit/test_handler_metrics.py -v` | ❌ Wave 0 |
| TEST-01 | Unit tests ≥80% coverage on all 16 backend modules | unit | `pytest tests/unit/ -v --cov=bin/wl_*.py --cov-report=term` | ✅ Existing (40+ tests) |
| TEST-02 | Integration tests for all 15+ REST action handlers + RBAC matrix | integration | `pytest tests/integration/test_handler_*.py tests/docker/test_docker_*.py -v` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_approval.py tests/unit/test_audit.py -v` (10s — approval + audit modules)
- **Per wave merge:** `pytest tests/unit tests/integration -v --cov` (30s — all module tests)
- **Phase gate:** Full Docker smoke test suite + `pytest tests/unit tests/integration -v --cov` (60s)

### Wave 0 Gaps
- [ ] `tests/integration/test_handler_dispatch.py` — dispatch table completeness + RBAC matrix (parametrized ~30 test cases)
- [ ] `tests/integration/test_handler_wave1.py` — GET action handlers (13 parametrized tests)
- [ ] `tests/integration/test_handler_wave2.py` — Simple POST handlers (6 parametrized tests)
- [ ] `tests/integration/test_handler_wave3.py` — Complex POST + approval handlers (8+ parametrized tests)
- [ ] `tests/docker/test_docker_smoke.py` — Full action chain in live container (15+ actions × 2 users)
- [ ] `tests/unit/test_replay.py` — wl_replay module with mocked domain modules (12+ test cases)
- [ ] Framework setup: Docker test marker (@pytest.mark.docker), auto-skip, wildcard deploy script

## Metadata

**Confidence breakdown:**
- **Standard Stack: HIGH** — All frameworks verified in existing Phase 1-3 tests; pytest, freezegun, unittest.mock all in use
- **Architecture (dispatch pattern): HIGH** — Dispatch table pattern well-established in web frameworks; design mirrors Splunk best practices
- **Pitfalls: HIGH** — Grounded in MEMORY.md lessons + Phase 1-3 bug analysis; precondition validation specifically called out by user
- **wl_replay module: MEDIUM** — Design from CONTEXT.md; no reference implementation yet; will be prototyped in Phase 4 planning

**Research date:** 2026-04-01  
**Valid until:** 2026-04-30 (stable domain; no Splunk or Python updates expected)

## Sources

### Primary (HIGH confidence)
- **CONTEXT.md** — Phase 4 locked decisions, router pattern, wl_replay architecture, error handling, integration test strategy
- **PROJECT_CONTEXT.md (CLAUDE.md)** — Module structure (16 wl_*.py files), deployment flow, audit event structure, Splunk quirks
- **STATE.md** — Phase completion status (Phases 1-3 done); architecture decisions and current position
- **REQUIREMENTS.md** — BMOD-01, TEST-01, TEST-02 requirements definitions

### Secondary (MEDIUM confidence, verified with existing code)
- **tests/unit/test_*.py** (40+ files) — Existing test patterns, pytest fixtures, module integration points
- **tests/integration/test_*.py** (3 files) — Integration test patterns for approval queue, concurrency, persistence
- **bin/wl_approval.py** (187 lines) — Approval module API; wl_replay will use as next-layer caller
- **bin/wl_audit.py** (191 lines) — Audit event API; used by wl_replay for event posting
- **MEMORY.md** — User experience feedback on precondition validation, dual UI paths, set-vs-counter pitfalls

### Tertiary (verified during research)
- **wl_handler.py** (5,909 lines) — Current monolith structure; dispatch pattern target
- **wl_csv.py, wl_versions.py, wl_trash.py, etc.** — Domain module pipelines (16 total); wl_replay will orchestrate
- **bin/wl_notify.py** (new in Phase 3) — Notification templates; wl_replay will integrate

---

*Research complete: 2026-04-01*
*Phase: 04-backend-integration*
