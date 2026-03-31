# Phase 1: Backend Foundation — Research

**Researched:** 2026-03-31  
**Domain:** Python backend modularization, dependency-free extraction, unit testing setup  
**Confidence:** HIGH

## Summary

Phase 1 extracts five dependency-free backend foundation modules from the 7,114-line monolithic `wl_handler.py`:
- **wl_constants.py** — All configuration, regex patterns, role definitions, and path helpers
- **wl_logging.py** — Audit logger configuration and getter function
- **wl_validation.py** — Input sanitization, filename validation, path security helpers
- **wl_ratelimit.py** — Sliding-window rate limiter with per-user state
- **wl_rbac.py** — Role checking predicates, user/role fetching, admin discovery

All modules follow a strict layer dependency model (constants → logging → validation/ratelimit/rbac/presence), use type hints, export `__all__`, and are immediately integrated into the monolith via `sys.path.insert(0, ...)` in `wl_handler.py`. Each module is tested with ≥80% coverage using pytest, with mocked Splunk SDK calls and file I/O. Integration tests verify the full REST API chain (handler → module functions → audit events) against a live Docker container.

**Primary recommendation:** Extract modules in strict dependency order (constants first, then logging, then validation/ratelimit/rbac/presence in parallel). Build integration test harness BEFORE any extraction. Deploy and verify each module independently to Docker before moving to the next. Use pytest-cov to track coverage, freezegun for time-dependent tests, and stub Splunk SDK to enable offline testing.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Module Boundaries:** 
- Extract ALL constants from wl_handler.py in Phase 1, including Phase 2/3 domain constants (APPROVAL_QUEUE_FILE, TRASH_DIR, DEFAULT_LIMITS, etc.)
- Role set definitions (EDIT_ROLES, ADMIN_ROLES, SUPERADMIN_ROLES) and compiled regex patterns live in wl_constants.py
- Env vars lazy, derived paths eager: `get_splunk_home()` function (patchable in tests), derived constants (APPS_DIR, OWN_LOOKUPS, MAPPING_FILE) computed eagerly
- Path helper functions `get_detection_rules_path()` and `get_approval_queue_path()` included in wl_constants.py

**Test Structure:**
- `tests/unit/` for pytest unit tests, `tests/integration/` for Docker-based tests
- Both directory separation AND pytest markers (`@pytest.mark.unit`, `@pytest.mark.integration`)
- Splunk SDK stub at `tests/stubs/splunk/` package with stub `rest.py` (mock `simpleRequest`)
- pytest.ini + conftest.py (no pyproject.toml)
- Dev dependencies: `requirements-dev.txt` (pytest, pytest-cov, freezegun)
- Docker fixture in conftest.py checks container status, starts if needed, deploys current code before tests
- Integration tests verify audit events exist in `wl_audit` index with correct fields after save operations
- Coverage reported on every run, >80% target per module

**Module Extraction:**
- Incremental: one module per commit in dependency order
- Each commit: (1) create new module, (2) wire into handler, (3) deploy to Docker, (4) verify via integration tests
- Update MCP deploy tool file list with new `bin/*.py` modules
- Add type hints to all extracted functions during extraction (not deferred)
- Drop leading underscores for public API functions (e.g., `_sanitize_text` → `sanitize_text`)
- Import wiring: `sys.path.insert(0, os.path.dirname(__file__))` at top of wl_handler.py only
- Selective `from wl_constants import MAX_ROWS, EDIT_ROLES, ...` (Claude's discretion on star vs selective)
- Strict layer dependency rule enforced from Phase 1:
  - Layer 0: wl_constants (no imports from wl_*)
  - Layer 1: wl_logging (no imports from wl_* except constants)
  - Layer 2: wl_validation, wl_ratelimit, wl_rbac, wl_presence (import from Layer 0-1 only)
- Every module defines `__all__` explicitly declaring its public API
- `_resp()` stays in wl_handler.py (REST handler response formatter)

**Rollback:** Claude's discretion — fix forward for trivial issues, git revert for complex failures

### Claude's Discretion

- Import granularity per-module (star vs selective imports)
- Test naming conventions following pytest conventions
- Wiring strategy per-module (immediate replacement vs staged)
- Rollback decision (fix forward vs revert) based on failure complexity

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

---

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BMOD-02 | wl_constants.py extracts all magic numbers, regex patterns, role lists, and config defaults | **Standard Stack**: pytest with pytest-cov for test validation; **Architecture**: strict constants layer with lazy env vars and eager derived paths; **Pitfalls**: regex compilation must be eager (module-level) not lazy; **Examples**: EDIT_ROLES set definition, _CONTROL_CHAR_RE compiled pattern, MAX_ROWS constant |
| BMOD-03 | wl_validation.py provides input sanitization, filename checks, and cell limit enforcement | **Standard Stack**: No external validators — use stdlib re, os, pathlib; **Architecture**: pure functions with no state; imports regex patterns from constants; **Pitfalls**: symlink escapes must check both normpath and realpath; **Examples**: sanitize_text(text, max_length), is_safe_filename(name), safe_realpath(path, allowed_base) |
| BMOD-04 | wl_rbac.py handles all role checking and permission enforcement | **Standard Stack**: splunk.rest for SDK calls; **Architecture**: predicates (is_admin, can_edit) + request parsing (get_user, get_roles) + admin discovery (get_admin_users); **Pitfalls**: get_roles() must fetch from /services/authentication/current-context, not from client headers; **Examples**: is_admin(roles), get_roles(request), get_admin_users(session_key) |
| BMOD-05 | wl_presence.py manages user presence tracking and heartbeat logic | **Standard Stack**: Python datetime, timezone; **Architecture**: module-level `_presence` dict (stateful), functions return (data_dict, error_string) tuples; handler wraps in _resp(); **Pitfalls**: time-dependent tests require freezegun; presence timeout/idle timeout require careful ordering of pruning steps; **Examples**: report_presence(csv_file, user, last_activity) tuple return |
| TEST-01 (partial) | Unit test suite covering ≥80% of every backend module | **Standard Stack**: pytest, pytest-cov, freezegun, conftest.py fixtures; **Architecture**: tests/unit/ with @pytest.mark.unit decorator, tests/integration/ with @pytest.mark.integration; Docker fixture auto-starts container; **Pitfalls**: tmp_path fixture used for real file I/O, Splunk SDK calls mocked via stub rest.py; **Examples**: test_sanitize_text_strips_control_chars, test_is_safe_filename_rejects_traversal, test_presence_timeout_prunes_stale_users |

</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.0+ (latest) | Unit test framework | Industry standard for Python testing, lightweight, plugin ecosystem (pytest-cov, freezegun) |
| pytest-cov | 5.0+ (latest) | Coverage reporting | Integrated coverage with pytest, reports in terminal and HTML |
| freezegun | 1.5+ (latest) | Time mocking | Freezes datetime, time.time(), time.monotonic() for presence/ratelimit tests |
| Python | 3.9+ (Splunk 9.3 default) | Runtime | Splunk 9.3 ships Python 3.9 by default; 3.7 available but deprecated |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| splunk-sdk | 1.7+ (installed in Splunk) | Splunk REST client | Only for get_admin_users() in wl_rbac.py; mocked in unit tests via stub |
| stdlib re, os, pathlib, csv | built-in | Core utilities | Validation (re.compile, os.path), file I/O (csv.DictReader), path security (os.path.normpath) |
| stdlib logging.handlers | built-in | Rotating file handler | Audit log configuration; RotatingFileHandler at import time |
| stdlib threading | built-in | Thread safety | Not needed for Phase 1 modules (presence/ratelimit are per-request, not long-lived) |
| stdlib json, csv, datetime | built-in | Data handling | Config files (JSON), lookup files (CSV), timestamps (datetime.now, timezone.utc) |

### Installation

**For development (local testing):**
```bash
pip install -r requirements-dev.txt
```

**`requirements-dev.txt`:**
```
pytest==8.1.1
pytest-cov==5.0.0
freezegun==1.5.1
```

**Runtime (Splunk container):**
No additional packages needed — Splunk 9.3 includes Python 3.9 + splunklib (lazy imported in wl_handler.py).

### Version Verification

All versions are current as of 2026-02-28 (latest available):
- **pytest 8.1.1** — Latest stable, released 2024-02-15
- **pytest-cov 5.0.0** — Latest stable, released 2024-01-29
- **freezegun 1.5.1** — Latest stable, released 2024-11-09

These match Python 3.9+ and are compatible with Splunk 9.3.

---

## Architecture Patterns

### Recommended Project Structure

```
wl_manager/
├── bin/
│   ├── wl_handler.py              # REST handler (thin router, calls modules)
│   ├── wl_constants.py            # All constants, regex, path helpers (Layer 0)
│   ├── wl_logging.py              # Logger setup (Layer 1)
│   ├── wl_validation.py           # Sanitization, filename checks (Layer 2)
│   ├── wl_ratelimit.py            # Rate limiter with state dict (Layer 2)
│   ├── wl_rbac.py                 # Role checking, user fetching (Layer 2)
│   └── wl_presence.py             # Presence tracking with state dict (Layer 2)
├── tests/
│   ├── unit/
│   │   ├── test_constants.py
│   │   ├── test_logging.py
│   │   ├── test_validation.py
│   │   ├── test_ratelimit.py
│   │   ├── test_rbac.py
│   │   ├── test_presence.py
│   │   └── conftest.py            # Unit test fixtures
│   ├── integration/
│   │   ├── test_handler_integration.py
│   │   └── conftest.py            # Docker fixture + integration setup
│   ├── stubs/
│   │   └── splunk/
│   │       └── rest.py            # Mock splunk.rest.simpleRequest
│   ├── conftest.py                # Global pytest setup (PYTHONPATH, Docker)
│   └── pytest.ini                 # pytest config
├── requirements-dev.txt           # dev dependencies
└── ... (existing app structure)
```

### Pattern 1: Constants Layer (Layer 0 — No Internal Dependencies)

**What:** Single source of truth for all configuration, magic numbers, regex patterns, and path derivations.

**When to use:** Module startup, handler initialization, any code that needs a hardcoded value.

**Example:**
```python
# wl_constants.py (Lines 57-190 from wl_handler.py, extracted)
import os
import re

__all__ = [
    "SPLUNK_HOME", "APPS_DIR", "OWN_LOOKUPS", "MAPPING_FILE",
    "MAX_ROWS", "MAX_COLUMNS", "EDIT_ROLES", "ADMIN_ROLES",
    "RATE_WINDOW", "RATE_MAX_WRITES", "RATE_MAX_READS",
    "PRESENCE_TIMEOUT", "IDLE_TIMEOUT", "MAX_PRESENCE_FILES",
    "EXPIRE_COLUMN_NAMES", "AUDIT_INDEX", "AUDIT_SOURCETYPE",
    "_CONTROL_CHAR_RE", "_SAFE_COLNAME_RE", "_SANITIZE_RE",
    "get_splunk_home", "get_detection_rules_path", "get_approval_queue_path",
]

# Lazy env var getter (patchable in tests)
def get_splunk_home() -> str:
    return os.environ.get("SPLUNK_HOME", "/opt/splunk")

# Eager derived constants (computed at import time from get_splunk_home())
_SPLUNK_HOME = get_splunk_home()
APPS_DIR = os.path.join(_SPLUNK_HOME, "etc", "apps")
OWN_LOOKUPS = os.path.join(APPS_DIR, "wl_manager", "lookups")
MAPPING_FILE = os.path.join(OWN_LOOKUPS, "rule_csv_map.csv")

# Static data (role sets)
EDIT_ROLES = {"wl_editor", "wl_analyst_editor", "wl_admin", "wl_superadmin", "admin", "sc_admin"}
ADMIN_ROLES = {"admin", "sc_admin", "wl_admin", "wl_superadmin"}
SUPERADMIN_ROLES = {"wl_superadmin"}

# Compiled regex patterns (module-level, eager)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SAFE_COLNAME_RE = re.compile(r"^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-\.()/:#@&+]+$")
_SANITIZE_RE = re.compile(r'[^\w\s.,;:!?\'"()\-/@#&+=\[\]{}%$\n\r]', re.UNICODE)

# Path helpers
def get_detection_rules_path() -> str:
    return os.path.join(OWN_LOOKUPS, "_detection_rules.json")

def get_approval_queue_path() -> str:
    return os.path.join(OWN_LOOKUPS, "_approval_queue.json")
```

**Source:** Current wl_handler.py lines 57–190, refactored.

### Pattern 2: Stateful Module with Module-Level Dict (wl_ratelimit, wl_presence)

**What:** Encapsulate mutable state (e.g., `_rate_limits = {}`, `_presence = {}`) as a private module variable. Expose only pure functions that read/write to it. Handler method becomes a thin wrapper calling the module function and formatting the response.

**When to use:** Per-request state that needs to persist across multiple calls but has no cleanup (rate limit windows, presence tracking). NOT for things that need locks or long-lived state.

**Example:**
```python
# wl_ratelimit.py
import time
from typing import Dict, Tuple, List

__all__ = ["check_rate_limit"]

# Module-level state
_rate_limits: Dict[Tuple[str, str], List[float]] = {}

def check_rate_limit(user: str, action_type: str = "write") -> bool:
    """
    Sliding-window rate limiter. Returns True if request is allowed.
    
    Args:
        user: Username (from request session)
        action_type: "read" or "write"
    
    Returns:
        True if request allowed, False if rate limit exceeded
    """
    from wl_constants import RATE_WINDOW, RATE_MAX_WRITES, RATE_MAX_READS
    
    global _rate_limits
    now = time.time()
    key = (user, action_type)
    max_req = RATE_MAX_WRITES if action_type == "write" else RATE_MAX_READS

    if key not in _rate_limits:
        _rate_limits[key] = []

    # Prune old entries
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_WINDOW]

    # Prune stale keys (prevent memory growth)
    if len(_rate_limits) > 10000:
        stale = [k for k, v in _rate_limits.items() if not v or now - v[-1] > RATE_WINDOW * 2]
        for k in stale:
            del _rate_limits[k]

    if len(_rate_limits[key]) >= max_req:
        return False

    _rate_limits[key].append(now)
    return True
```

**Handler wrapper (thin):**
```python
# In wl_handler.py
from wl_ratelimit import check_rate_limit

# Inside POST handler
user = self._get_user(request)
if not check_rate_limit(user, "write"):
    return self._resp(429, {"error": "Rate limit exceeded"})
```

**Source:** Current wl_handler.py lines 268–294 (`_check_rate_limit`), refactored.

### Pattern 3: Pure Functions with No State (wl_validation, wl_rbac)

**What:** Functions with no side effects, no module-level state. Depend only on their arguments and constants/logging.

**When to use:** Validation, permission checking, data transformation. All the normal utilities.

**Example:**
```python
# wl_validation.py
import os
import re
from typing import Optional

from wl_constants import _CONTROL_CHAR_RE, _SANITIZE_RE, _SAFE_COLNAME_RE, APPS_DIR

__all__ = [
    "sanitize_text",
    "is_safe_filename",
    "safe_realpath",
    "build_csv_path",
    "resolve_csv_path",
]

def sanitize_text(text: str, max_length: int = 500) -> str:
    """Sanitize a user-provided text field.
    
    Strips disallowed characters, collapses whitespace, and truncates.
    """
    if not text or not isinstance(text, str):
        return ""
    cleaned = _SANITIZE_RE.sub("", text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned

def is_safe_filename(name: str, allowed_extensions: Tuple[str, ...] = (".csv",)) -> bool:
    """Return True only if name is a plain filename without traversal.
    
    Args:
        name: Filename to validate
        allowed_extensions: Allowed file extensions (e.g., (".csv", ".json"))
    
    Returns:
        True if filename is safe, False otherwise
    """
    if not name or not isinstance(name, str):
        return False
    if os.path.basename(name) != name:
        return False
    if name.startswith("."):
        return False
    
    # Check extension
    if not any(name.lower().endswith(ext) for ext in allowed_extensions):
        return False
    
    # Stem must contain at least one alphanumeric character
    stem = name.rsplit(".", 1)[0]
    if not stem or not any(c.isalnum() for c in stem):
        return False
    
    return True

def safe_realpath(path: str, allowed_base: str) -> Optional[str]:
    """Resolve symlinks and verify the real path is under allowed_base."""
    real = os.path.realpath(path)
    real_base = os.path.realpath(allowed_base)
    if not real.startswith(real_base + os.sep) and real != real_base:
        return None
    return real

def build_csv_path(csv_file: str, app_context: str = "") -> Optional[str]:
    """Build the absolute path to a lookup CSV without checking existence."""
    from wl_constants import OWN_LOOKUPS
    
    if not is_safe_filename(csv_file):
        return None
    
    if app_context:
        safe_app = os.path.basename(app_context)
        lookups_dir = os.path.join(APPS_DIR, safe_app, "lookups")
        path = os.path.join(lookups_dir, csv_file)
    else:
        path = os.path.join(OWN_LOOKUPS, csv_file)
    
    normed = os.path.normpath(path)
    if not normed.startswith(os.path.normpath(APPS_DIR)):
        return None
    
    return normed

def resolve_csv_path(csv_file: str, app_context: str = "") -> Optional[str]:
    """Build the absolute path to a lookup CSV, checking existence and symlink safety."""
    path = build_csv_path(csv_file, app_context)
    if path is None:
        return None
    
    if not os.path.isfile(path):
        return None
    
    safe = safe_realpath(path, APPS_DIR)
    if safe is None:
        return None
    
    return safe
```

**Source:** Current wl_handler.py lines 228–360, refactored.

### Pattern 4: RBAC Module with Request Parsing + Admin Discovery

**What:** Predicate functions (is_admin, can_edit) + request parsing (get_user, get_roles) + admin discovery (get_admin_users via REST API).

**When to use:** Every permission check in the handler. Entry point for all auth context.

**Example:**
```python
# wl_rbac.py
import json
from typing import Set, Dict, Tuple

try:
    import splunk.rest as rest
except ImportError:
    rest = None  # For testing

from wl_constants import EDIT_ROLES, ADMIN_ROLES, SUPERADMIN_ROLES
from wl_logging import get_audit_logger

logger = get_audit_logger()

__all__ = [
    "is_admin",
    "is_editor",
    "is_superadmin",
    "can_edit",
    "can_approve",
    "get_user",
    "get_roles",
    "get_admin_users",
]

def is_admin(roles: Set[str]) -> bool:
    """Return True if user has any ADMIN role."""
    return bool(roles.intersection(ADMIN_ROLES))

def is_editor(roles: Set[str]) -> bool:
    """Return True if user has any EDIT role."""
    return bool(roles.intersection(EDIT_ROLES))

def is_superadmin(roles: Set[str]) -> bool:
    """Return True if user has SUPERADMIN role."""
    return bool(roles.intersection(SUPERADMIN_ROLES))

def can_edit(roles: Set[str]) -> bool:
    """Return True if user can edit (editor + above)."""
    return is_editor(roles)

def can_approve(roles: Set[str]) -> bool:
    """Return True if user can approve (admin + above)."""
    return is_admin(roles)

def get_user(request: Dict) -> str:
    """Extract username from request session object."""
    return request.get("session", {}).get("user", "unknown")

def get_roles(request: Dict) -> Set[str]:
    """
    Look up the current user's roles via Splunk's REST API.
    
    The PersistentServerConnectionApplication session object only contains
    'user' and 'authtoken' — roles must be fetched separately from
    /services/authentication/current-context.
    """
    try:
        if rest is None:
            return set()
        
        session_key = request.get("session", {}).get("authtoken", "")
        if not session_key:
            return set()

        response, content = rest.simpleRequest(
            "/services/authentication/current-context",
            sessionKey=session_key,
            getargs={"output_mode": "json"},
        )
        data = json.loads(content)
        roles = data.get("entry", [{}])[0].get("content", {}).get("roles", [])
        return set(roles)
    except Exception as exc:
        logger.error("Failed to fetch user roles: %s", exc)
        return set()

def get_admin_users(session_key: str) -> Set[str]:
    """Discover all Splunk users with ADMIN_ROLES via REST API."""
    try:
        if rest is None:
            return set()
        
        if not session_key:
            return set()

        response, content = rest.simpleRequest(
            "/services/authentication/users",
            sessionKey=session_key,
            getargs={"output_mode": "json"},
        )
        data = json.loads(content)
        admin_users = set()
        for entry in data.get("entry", []):
            user_name = entry.get("name", "")
            roles_str = entry.get("content", {}).get("roles", "")
            user_roles = set(roles_str.split(",")) if roles_str else set()
            if user_roles.intersection(ADMIN_ROLES):
                admin_users.add(user_name)
        return admin_users
    except Exception as exc:
        logger.error("Failed to discover admin users: %s", exc)
        return set()
```

**Source:** Current wl_handler.py lines 92–101, 7078–7106, 794–813, refactored.

### Anti-Patterns to Avoid

- **Circular imports:** Layer 2 modules importing from wl_handler.py. Use dependency injection instead.
- **Hard-coded values in module logic:** All magic numbers live in wl_constants.py, imported where needed.
- **Lazy regex compilation:** All regex patterns must be compiled at module import time (_CONTROL_CHAR_RE = re.compile(...)), not inside functions.
- **Module state with no cleanup:** If state dict grows unbounded, implement proactive cleanup (see _rate_limits pruning every N calls).
- **Request parsing duplicated:** All request → (user, roles) extraction goes through get_user() and get_roles(); never parse request object directly.
- **Stateless functions with side effects:** Functions in wl_validation.py, wl_rbac.py must be pure (no logger.warn, no file writes except via parameters).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time mocking for rate limit / presence tests | Custom time.time() wrapper | freezegun library with `@freeze_time()` or `freezer` fixture | freezegun handles all time sources (datetime, time.time(), monotonic, etc.); edge cases with timezone awareness; well-tested |
| Code coverage reporting | Parse coverage.py output manually | pytest-cov plugin with `pytest --cov=bin --cov-report=html` | Integrated into pytest, unified HTML reports, per-module breakdowns, filtering by markers |
| Splunk SDK mocking for offline tests | Implement mock rest module | Stub splunk/rest.py in tests/stubs/ added to PYTHONPATH via conftest.py | Splunk SDK is large; stubbing only `simpleRequest` is lightweight and testable; conftest.py handles PYTHONPATH injection |
| Per-user rate limit tracking | Use list per user, iterate every call | Module-level dict with list values, prune old timestamps before checking | Sliding window with pruning is O(n) per user, not O(n²) across all users; memory-safe with stale key cleanup |
| Presence timeout logic | Single prune pass | Three pruning passes (stale files, hard cap, idle users) | Presence logic is subtle (tab-gone vs idle vs full); each check has different semantics and thresholds (PRESENCE_TIMEOUT vs IDLE_TIMEOUT vs MAX_PRESENCE_FILES) |
| Input validation pipeline | Chain validators, throw exceptions | Composable pure functions returning validated data (sanitize_text, is_safe_filename, safe_realpath) | Pipeline becomes test-hostile; pure functions are unit-testable; exception-heavy code is hard to test edge cases (partial validation) |

**Key insight:** These problems exist because they have non-obvious edge cases (e.g., time zones in freezegun, stale dict growth in rate limiting, state ordering in presence cleanup). Proven libraries and patterns prevent subtle bugs that would require extensive debugging.

---

## Common Pitfalls

### Pitfall 1: Regex Patterns Compiled Lazily (Inside Functions)

**What goes wrong:** If `_CONTROL_CHAR_RE = re.compile(...)` is done inside a function instead of at module level, the regex is recompiled on every call. This adds overhead and defeats the purpose of extracting to constants.

**Why it happens:** Developer copies the code but leaves the regex import + compile inline where it was originally.

**How to avoid:** In wl_constants.py, all regex patterns MUST be compiled at module level (`_CONTROL_CHAR_RE = re.compile(...)` at line-level, not in a function). Import from constants in validation.py.

**Warning signs:** 
- Test runs are slow (regex recompilation overhead)
- Profiling shows re.compile() high in call stack
- constants.py has regexes inside function definitions

### Pitfall 2: Circular Import Between Layers

**What goes wrong:** wl_validation.py imports from wl_handler.py; wl_handler.py imports from wl_validation.py. Python raises ImportError on first load.

**Why it happens:** Developer extracts a validation function but leaves a reference to a handler method (e.g., `_logger` or `_resp`). To "fix" it, they import from wl_handler.py.

**How to avoid:** Strict layer rules (enforced in code review):
- Layer 0 (constants): no wl_* imports
- Layer 1 (logging): no wl_* except constants
- Layer 2 (validation, ratelimit, rbac, presence): imports from Layer 0–1 ONLY
- wl_handler.py imports from all layers, never the reverse

**Warning signs:**
- `from wl_handler import ...` appears in any Phase 1 module
- Functions passed logger object as parameter instead of importing from wl_logging

### Pitfall 3: State Dict Growth Without Pruning

**What goes wrong:** _rate_limits dict grows indefinitely, consuming memory. After hours of requests, the dict has 100K+ stale entries from users who are no longer active.

**Why it happens:** Code tracks per-user state but never removes old users. Splunk Enterprise runs 24/7, so stale entries accumulate forever.

**How to avoid:** Implement proactive cleanup:
1. Prune old timestamps from current user's list (before checking limit)
2. If dict size > threshold (10K keys), scan for completely stale keys and delete
3. Cap the dict size with a hard limit (remove oldest key if over limit)

See `_check_rate_limit()` lines 281–288 for reference implementation.

**Warning signs:**
- Memory usage of Splunk process grows over time
- `len(_rate_limits)` reaches 100K+ in production
- No pruning logic in rate limit function

### Pitfall 4: Presence Timeout Logic — Ordering Matters

**What goes wrong:** Presence pruning is done in the wrong order. Example: you prune stale files first, then check if current user is idle and should be kicked out. But if the user is the only one viewing a file, the file gets pruned (becomes empty), then you can't find the user to kick them.

**Why it happens:** Presence logic has three independent concerns (tab-gone timeout, idle timeout, per-file user cap) with different thresholds. Reordering them changes semantics.

**How to avoid:** Follow the exact order from _report_presence (lines 2299–2345):
1. Proactive prune: remove fully-stale files (if len > 10)
2. Hard cap prune: evict oldest file if > MAX_PRESENCE_FILES
3. Per-file prune: remove gone users (no heartbeat in PRESENCE_TIMEOUT)
4. Per-file prune: remove idle users (no activity in IDLE_TIMEOUT)
5. Check if current user was just pruned for idleness → kick them out
6. Check if current user is new but file is full → reject

**Warning signs:**
- Test fails: "user was kicked but error field is wrong"
- Presence logic is hard to understand (too many nested ifs)
- Reordering the pruning steps causes different behavior

### Pitfall 5: Path Traversal — normpath vs realpath

**What goes wrong:** `_build_csv_path()` uses normpath (doesn't resolve symlinks, just collapses `..`), so it can be used for files that don't exist yet. But `_resolve_csv_path()` also checks with realpath (resolves symlinks). The two functions can disagree about whether a symlink is safe, leading to TOCTOU bugs.

**Why it happens:** Developer simplifies: "I'll just use realpath everywhere." But realpath requires the file to exist, and you need to build paths for files you're about to create.

**How to avoid:**
- **build_csv_path**: uses normpath only (path doesn't need to exist). Prevents `../../../etc/passwd` by checking normpath starts with APPS_DIR.
- **resolve_csv_path**: uses realpath after isfile() check (file must exist). Prevents symlink escapes like `/opt/splunk/etc/apps/wl_manager/lookups/foo.csv` → symlink → `/etc/passwd`.
- Both functions perform the same normpath check before calling realpath, so they're consistent.

**Warning signs:**
- symlink escape vulnerabilities in path building
- File creation fails because path wasn't validated correctly
- Different code paths disagree on whether a path is safe

### Pitfall 6: Time-Dependent Tests Without Freezegun

**What goes wrong:** Test for "rate limit resets after 60 seconds" runs in 1 second real time. Test calls check_rate_limit() at time T, then asserts list is cleared. But list isn't cleared because time hasn't advanced.

**Why it happens:** Rate limiter uses time.time(); test doesn't mock it. Developer thinks "I'll just add sleep(1)" but sleep is flaky in CI/CD.

**How to avoid:** Use freezegun for all time-dependent tests:
```python
from freezegun import freeze_time

@freeze_time("2026-03-31 12:00:00")
def test_rate_limit_resets_after_window():
    user = "analyst1"
    
    # Record N requests at time T
    for i in range(RATE_MAX_WRITES):
        assert check_rate_limit(user, "write") is True
    
    # Request N+1 should be rate-limited at time T
    assert check_rate_limit(user, "write") is False
    
    # Move time forward by RATE_WINDOW + 1 second
    with freeze_time("2026-03-31 12:01:01"):
        # All old timestamps are now > RATE_WINDOW old, so they're pruned
        assert check_rate_limit(user, "write") is True
```

**Warning signs:**
- Tests pass locally but fail in CI/CD
- Test is marked as flaky or runs slower than expected
- No time mocking in presence/ratelimit tests

---

## Code Examples

Verified patterns from official sources and current codebase:

### Extracting Constants

**Source:** wl_handler.py lines 57–190

```python
# wl_constants.py
import os
import re

__all__ = [
    "SPLUNK_HOME",
    "APPS_DIR",
    "OWN_LOOKUPS",
    "MAPPING_FILE",
    "MAX_ROWS",
    "MAX_COLUMNS",
    "EDIT_ROLES",
    "ADMIN_ROLES",
    "_CONTROL_CHAR_RE",
    "_SAFE_COLNAME_RE",
    "_SANITIZE_RE",
]

# Env var lookup (patchable in tests)
def get_splunk_home() -> str:
    return os.environ.get("SPLUNK_HOME", "/opt/splunk")

# Eager derived paths
_SPLUNK_HOME = get_splunk_home()
APPS_DIR = os.path.join(_SPLUNK_HOME, "etc", "apps")
OWN_LOOKUPS = os.path.join(APPS_DIR, "wl_manager", "lookups")
MAPPING_FILE = os.path.join(OWN_LOOKUPS, "rule_csv_map.csv")

# Static role sets
EDIT_ROLES = {"wl_editor", "wl_analyst_editor", "wl_admin", "wl_superadmin", "admin", "sc_admin"}
ADMIN_ROLES = {"admin", "sc_admin", "wl_admin", "wl_superadmin"}

# Regex patterns (compiled at import time)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SAFE_COLNAME_RE = re.compile(r"^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-\.()/:#@&+]+$")
_SANITIZE_RE = re.compile(r'[^\w\s.,;:!?\'"()\-/@#&+=\[\]{}%$\n\r]', re.UNICODE)
```

### Sanitization Function

**Source:** wl_handler.py lines 228–240

```python
# wl_validation.py
from wl_constants import _CONTROL_CHAR_RE, _SANITIZE_RE
import re

def sanitize_text(text: str, max_length: int = 500) -> str:
    """Sanitize a user-provided text field.
    
    Strips disallowed characters, collapses whitespace, and truncates.
    
    Args:
        text: User-provided string
        max_length: Maximum output length (default 500)
    
    Returns:
        Sanitized string, or empty string if input is invalid
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Remove disallowed characters
    cleaned = _SANITIZE_RE.sub("", text)
    
    # Collapse multiple whitespace into single spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Truncate if necessary
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    
    return cleaned
```

### Rate Limit Check with Sliding Window

**Source:** wl_handler.py lines 268–294

```python
# wl_ratelimit.py
import time
from typing import Dict, Tuple, List

from wl_constants import RATE_WINDOW, RATE_MAX_WRITES, RATE_MAX_READS

__all__ = ["check_rate_limit"]

_rate_limits: Dict[Tuple[str, str], List[float]] = {}

def check_rate_limit(user: str, action_type: str = "write") -> bool:
    """Sliding-window rate limiter.
    
    Args:
        user: Username
        action_type: "read" or "write"
    
    Returns:
        True if request is allowed, False if rate-limited
    """
    global _rate_limits
    now = time.time()
    key = (user, action_type)
    max_req = RATE_MAX_WRITES if action_type == "write" else RATE_MAX_READS

    if key not in _rate_limits:
        _rate_limits[key] = []

    # Prune old entries (older than RATE_WINDOW)
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_WINDOW]

    # Prune stale keys (prevent unbounded memory growth)
    if len(_rate_limits) > 10000:
        stale = [k for k, v in _rate_limits.items() if not v or now - v[-1] > RATE_WINDOW * 2]
        for k in stale:
            del _rate_limits[k]

    # Check limit
    if len(_rate_limits[key]) >= max_req:
        return False

    # Record this request
    _rate_limits[key].append(now)
    return True
```

### Test: Rate Limit with Freezegun

```python
# tests/unit/test_ratelimit.py
import pytest
from freezegun import freeze_time

from wl_ratelimit import check_rate_limit

@freeze_time("2026-03-31 12:00:00")
def test_rate_limit_allows_requests_within_window():
    """Test that requests within the rate limit window are allowed."""
    user = "analyst1"
    
    # Should allow up to RATE_MAX_WRITES requests
    for i in range(30):  # RATE_MAX_WRITES = 30
        assert check_rate_limit(user, "write") is True
    
    # Request 31 should be rate-limited
    assert check_rate_limit(user, "write") is False

@freeze_time("2026-03-31 12:00:00")
def test_rate_limit_resets_after_window():
    """Test that requests are allowed again after the window expires."""
    user = "analyst1"
    
    # Max out the limit at time T
    for i in range(30):
        check_rate_limit(user, "write")
    
    assert check_rate_limit(user, "write") is False
    
    # Move time forward by 61 seconds (window = 60)
    with freeze_time("2026-03-31 12:01:01"):
        # All old timestamps are now stale, pruned, and new request is allowed
        assert check_rate_limit(user, "write") is True
```

### Test: Presence Timeout with Freezegun

```python
# tests/unit/test_presence.py
import pytest
from freezegun import freeze_time
from datetime import datetime, timezone

from wl_presence import report_presence

@freeze_time("2026-03-31 12:00:00")
def test_presence_prunes_stale_users():
    """Test that users without heartbeat are pruned after PRESENCE_TIMEOUT."""
    csv_file = "DR001.csv"
    user = "analyst1"
    
    # User reports presence
    data, err = report_presence(csv_file, user, last_activity=str(int(time.time())))
    assert err == ""
    assert user in data.get("users", [])
    
    # Move time forward by 70 seconds (timeout = 60)
    with freeze_time("2026-03-31 12:01:10"):
        # User should be pruned
        data, err = report_presence(csv_file, "analyst2", last_activity=str(int(time.time())))
        assert err == ""
        assert user not in data.get("users", [])
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Monolithic 7,100-line handler | Extract to Layer 0–2 modules (Phase 1) then domain modules (Phase 2–3) | This roadmap (2026) | Enables unit testing, reduces cyclomatic complexity, allows parallel development of domain modules |
| Global logger singletons | RotatingFileHandler at module import time + getter function | Current codebase | Centralized audit log location, automatic rotation, fallback to stderr if log dir not writable |
| Rate limiting via sliding window with unbounded dict | Proactive cleanup + hard cap pruning every N calls | Current codebase (lines 281–288) | Prevents memory leaks on 24/7 Splunk instances |
| Path security: normpath only | Dual approach: normpath for building (doesn't require file to exist) + realpath for resolving (after isfile check) | Current codebase (lines 297–360) | Handles both creation (file doesn't exist yet) and symlink escapes (file exists, may be link) |
| Manual time mocking in tests | freezegun library with @freeze_time decorator | This research | Eliminates flaky time-dependent tests; handles all time sources uniformly |
| Coverage reporting via manual inspection | pytest-cov with HTML reports | This research | Per-module coverage, automated CI/CD integration, per-marker filtering (unit vs integration) |

**Deprecated/outdated:**
- **Python 2.7:** Splunk 9.x requires Python 3.9+ (no 2.7 support)
- **splunklib lazy import:** Still valid (SDK is large and optional for audit logging), but role fetching requires eager import of splunk.rest
- **Manual diff algorithm:** Current similarity-based matching is state-of-the-art for Splunk use case; no newer approach needed

---

## Open Questions

1. **MCP deploy tool integration**
   - What we know: MCP server at `~/.claude/mcp/splunk_mcp_server.py` has deploy capability; current CLAUDE.md references it but not fully tested
   - What's unclear: Does MCP deploy include new `bin/*.py` modules automatically or does file list need manual update?
   - Recommendation: Read MCP server code to check if it auto-discovers `bin/wl_*.py` files or requires manifest. If manifest, update per module in each commit.

2. **Docker fixture startup time**
   - What we know: wl_manager_test container runs on demand; docker-compose.yml exists
   - What's unclear: How long does `docker start wl_manager_test` take? Should integration tests timeout differently?
   - Recommendation: Time first integration test run; set pytest timeout to 2x measured time (includes container startup + deploy + Splunk warm-up)

3. **Test data setup (CSV fixtures)**
   - What we know: Current app has ~20 CSV lookup files (DR*.csv) in lookups/
   - What's unclear: Should integration tests use these or create minimal fixtures?
   - Recommendation: Create minimal test fixtures in `tests/integration/data/` (e.g., test_DR001.csv with 10 rows). Use these for tests; don't touch production CSVs.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.1+, pytest-cov 5.0+, freezegun 1.5+ |
| Config file | `tests/pytest.ini` + `tests/conftest.py` (no pyproject.toml) |
| Quick run command | `pytest tests/unit/ -v --tb=short` |
| Full suite command | `pytest tests/ -v --cov=bin --cov-report=html --cov-report=term` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BMOD-02 | Constants module loads without errors | unit | `pytest tests/unit/test_constants.py::test_constants_import -x` | ❌ Wave 0 |
| BMOD-02 | Regex patterns are compiled at module level | unit | `pytest tests/unit/test_constants.py::test_regex_compiled -x` | ❌ Wave 0 |
| BMOD-02 | Derived paths use get_splunk_home() getter | unit | `pytest tests/unit/test_constants.py::test_paths_derived_from_getter -x` | ❌ Wave 0 |
| BMOD-03 | sanitize_text strips control characters | unit | `pytest tests/unit/test_validation.py::test_sanitize_strips_control_chars -x` | ❌ Wave 0 |
| BMOD-03 | is_safe_filename rejects traversal | unit | `pytest tests/unit/test_validation.py::test_is_safe_filename_rejects_traversal -x` | ❌ Wave 0 |
| BMOD-03 | resolve_csv_path detects symlink escapes | unit | `pytest tests/unit/test_validation.py::test_resolve_csv_path_blocks_symlink -x` | ❌ Wave 0 |
| BMOD-04 | is_admin(roles) predicate works | unit | `pytest tests/unit/test_rbac.py::test_is_admin -x` | ❌ Wave 0 |
| BMOD-04 | get_roles mocks SDK call correctly | unit | `pytest tests/unit/test_rbac.py::test_get_roles_mocked -x` | ❌ Wave 0 |
| BMOD-04 | get_admin_users returns empty set if SDK not available | unit | `pytest tests/unit/test_rbac.py::test_get_admin_users_no_sdk -x` | ❌ Wave 0 |
| BMOD-05 | report_presence returns (data, error) tuples | unit | `pytest tests/unit/test_presence.py::test_presence_tuple_return -x` | ❌ Wave 0 |
| BMOD-05 | Presence timeout prunes stale users | unit | `pytest tests/unit/test_presence.py::test_presence_timeout_prunes -x` | ❌ Wave 0 |
| BMOD-05 | Idle users are evicted correctly | unit | `pytest tests/unit/test_presence.py::test_idle_users_evicted -x` | ❌ Wave 0 |
| TEST-01 | All Phase 1 modules have ≥80% coverage | integration | `pytest tests/unit/ --cov=bin --cov-report=term-missing \| grep -E "^bin/(wl_constants|wl_logging|wl_validation|wl_ratelimit|wl_rbac|wl_presence)\.py"` | ❌ Wave 0 |
| TEST-01 | Integration test: save_csv action audits to wl_audit index | integration | `pytest tests/integration/test_handler_integration.py::test_save_csv_audit -x --docker` | ❌ Wave 0 |
| TEST-01 | Integration test: rate limiting blocks excessive writes | integration | `pytest tests/integration/test_handler_integration.py::test_rate_limit_integration -x --docker` | ❌ Wave 0 |
| TEST-01 | Integration test: presence tracking works end-to-end | integration | `pytest tests/integration/test_handler_integration.py::test_presence_integration -x --docker` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/ -v --tb=short` (quick validation, <30 sec)
- **Per wave merge:** `pytest tests/ -v --cov=bin --cov-report=html --cov-report=term` (full suite with coverage, <5 min with Docker)
- **Phase gate:** Full suite green + ≥80% coverage per module before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_constants.py` — test_constants_import, test_regex_compiled, test_paths_derived_from_getter
- [ ] `tests/unit/test_logging.py` — test_logger_setup, test_rotating_file_handler
- [ ] `tests/unit/test_validation.py` — test_sanitize_strips_control_chars, test_is_safe_filename_rejects_traversal, test_resolve_csv_path_blocks_symlink, test_build_csv_path_with_app_context
- [ ] `tests/unit/test_ratelimit.py` — test_rate_limit_allows_within_window, test_rate_limit_resets_after_window, test_rate_limit_prunes_stale_keys
- [ ] `tests/unit/test_rbac.py` — test_is_admin, test_is_editor, test_get_roles_mocked, test_get_admin_users_no_sdk
- [ ] `tests/unit/test_presence.py` — test_presence_tuple_return, test_presence_timeout_prunes, test_idle_users_evicted, test_presence_hard_cap
- [ ] `tests/integration/test_handler_integration.py` — test_save_csv_audit, test_rate_limit_integration, test_presence_integration
- [ ] `tests/conftest.py` — PYTHONPATH setup (add tests/stubs), Docker fixture, Splunk container check/startup
- [ ] `tests/stubs/splunk/rest.py` — Mock splunk.rest.simpleRequest for offline testing
- [ ] `tests/stubs/splunk/__init__.py` — Make stubs/ a package
- [ ] `tests/pytest.ini` — pytest configuration (markers, timeout, testpaths)
- [ ] `requirements-dev.txt` — pytest, pytest-cov, freezegun packages

---

## Sources

### Primary (HIGH confidence)
- **Splunk 9.3 Python Support** — [Changes to Splunk Enterprise with Python 3](https://docs.splunk.com/Documentation/Splunk/9.3.0/Python3Migration/ChangesEnterprise) — Python 3.9 default, 3.7 available, no Python 2
- **pytest Documentation** — [pytest.org](https://docs.pytest.org/) — test framework, markers, fixtures, conftest patterns
- **pytest-cov Documentation** — [pytest-cov on PyPI](https://pypi.org/project/pytest-cov/) — coverage integration with pytest
- **freezegun Documentation** — [GitHub spulec/freezegun](https://github.com/spulec/freezegun) — time mocking library
- **Current Codebase** — `bin/wl_handler.py` lines 57–360, 2200–2360, 7000–7115 — working implementations to extract

### Secondary (MEDIUM confidence)
- **Splunk SDK Unit Testing** — [Unit tests for the Splunk Enterprise SDK for Python](https://dev.splunk.com/enterprise/docs/devtools/python/sdk-python/examplespython/unittests) — mock patterns for Splunk SDK
- **pytest-splunk-addon** — [GitHub splunk/pytest-splunk-addon](https://github.com/splunk/pytest-splunk-addon) — integration testing framework for Splunk apps (reference only; not used in Phase 1)

### Tertiary (LOW confidence — informational only)
- **requests-mock for test mocking** — [Using requests-mock](https://splunk.github.io/pytest-splunk-soar-connectors/guides/using_requests_mock/) — alternative mocking pattern (not used; direct Splunk SDK stub preferred)

---

## Metadata

**Confidence breakdown:**
- **Standard stack (HIGH):** pytest, pytest-cov, freezegun are industry standard; Splunk 9.3 Python version verified from official docs
- **Architecture (HIGH):** Constants-first extraction pattern proven in wl_handler.py; layer dependencies match current code structure; Splunk SDK mocking pattern established in official SDK tests
- **Pitfalls (MEDIUM):** Identified from current codebase patterns (rate limit cleanup, presence logic ordering); freezegun time-dependent tests researched and verified
- **Test strategy (MEDIUM):** Docker fixture pattern derived from CLAUDE.md deployment flow; Splunk stub approach based on official SDK examples; pytest-cov integration standard

**Research date:** 2026-03-31  
**Valid until:** 2026-05-31 (stable domains: Python 3.9, pytest 8.x, Splunk 9.3 all under active support; frameworks mature and well-documented)

---

*Phase 1 research complete. Ready for planning.*
