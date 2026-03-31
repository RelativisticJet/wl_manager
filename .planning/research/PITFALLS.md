# Splunk App Rewrite Pitfalls

**Project:** Whitelist Manager v3.0 — Modular Rewrite
**Domain:** Splunk Enterprise Security — CSV Whitelist Management App
**Researched:** 2026-03-31
**Sources:** Codebase analysis (CONCERNS.md, CONVENTIONS.md), user lessons learned (MEMORY.md), Splunk architecture documentation

## Executive Summary

Splunk app rewrites fail most often due to module loading order mistakes (AMD circular dependencies, Python import path bugs), AppInspect rejections on file structure, and incomplete migration of existing data (version manifests, approval queue state). This app compounds the risk because it has complex state machinery (approval queue with threading, version control snapshots, file-based locking) that must remain consistent across all code paths.

**Critical insight:** The current app works perfectly from a security standpoint but is architecturally fragile. The rewrite must preserve ALL existing data structures and API contracts while splitting logic into separate modules. Any refactoring of core algorithms (diff engine, approval replay) risks introducing subtle bugs that only surface under concurrent load.

## Critical Pitfalls

### Pitfall 1: AMD Circular Module Dependencies

**What goes wrong:** 
- Frontend split into modules (wl_rest.js, wl_table.js, wl_approval_ui.js, etc.) where module A requires module B, and module B requires module A or a common dependency that creates a cycle.
- RequireJS detects cycles and loads only the first definition; modules waiting for their dependencies to load will receive `undefined`.
- Example: `wl_approval_ui.js` needs `restGet()` from `wl_rest.js`, while `wl_rest.js` needs `showMsg()` from `wl_approval_ui.js` for error display.

**Why it happens:**
- When modularizing a monolithic JS file, you naturally extract helpers that cross-reference each other.
- AMD requires explicitly listed dependencies in the `require([...])` array. Missing or circular dependencies are silent failures at runtime.
- Splunk's jQuery + AMD environment doesn't support dynamic imports or module.exports; everything is static dependency declaration upfront.

**Consequences:**
- Module fails to initialize; dependent code gets `undefined` and throws on property access (e.g., `Cannot read property 'restGet' of undefined`).
- Errors surface randomly during page load, sometimes after a hard browser refresh, sometimes only in production.
- Splunk app caches JavaScript aggressively; bug may only appear after bumping the `build` number in `app.conf` AND restarting Splunk AND hard-refresh (Ctrl+Shift+R).

**Prevention:**
1. **Dependency audit before modularization** — Create a dependency graph of all functions (inputs, outputs, cross-module calls) before splitting. Identify all cycles.
2. **Break cycles with dependency inversion** — Move common functionality to a `wl_shared.js` or `wl_events.js` module that both dependers can safely require without creating cycles.
3. **No bidirectional dependencies** — If module A requires B, then B must NEVER require A. If B needs something from A, that must be provided via callbacks or event emitters.
4. **Test module load order** — In a test HTML file, manually list all `require()` calls in the same order as `whitelist_manager.js` AMD block. Verify all modules initialize without errors.
5. **Use clear module responsibilities** — Define what each module exports (functions, state, handlers). If you find a module needs something that depends on it, redesign the boundary.

**Detection:**
- Browser console errors: `ReferenceError: [name] is not defined` or `Cannot read property of undefined` on page load.
- Module never initializes: check RequireJS require.js logs (verbose mode) or add `console.log("Module X loaded")` at each module's top level.
- Sporadic failures after bumping build number suggest caching issues (different from circular deps, but often happens together).

---

### Pitfall 2: AMD Module Load Order Timing Issues

**What goes wrong:**
- Modules load asynchronously. If module A assumes module B's state is initialized, but B hasn't finished initializing yet, A gets stale or undefined data.
- Example: `whitelist_manager.js` (entry point) requires modules in order: `wl_state`, `wl_table`, `wl_modals`. If `wl_state` hasn't finished exporting its state object when `wl_table` tries to read `currentRows`, it fails.
- jQuery and Splunk's `mvc/ready!` ensure the DOM and Splunk MVC are ready, but custom modules don't have that guarantee.

**Why it happens:**
- RequireJS loads modules in dependency order, but the entry point (`whitelist_manager.js`) completes its require block as soon as the callback fires. If nested modules use async operations (AJAX, timers), they may not be "ready" yet.
- Splunk's AMD doesn't provide a "all modules ready" hook. Each module must initialize synchronously in the require callback.

**Consequences:**
- Race condition: 90% of the time, the app works. 10% of the time, on slower machines or with network lag, a module is undefined.
- Intermittent bugs are hard to debug and reproduce.
- Bug may only surface under specific conditions: slow server, cold JavaScript cache, heavy CPU load.

**Prevention:**
1. **Synchronous initialization only** — Modules must complete all initialization in their require callback. No deferred initialization via timers or async operations.
2. **Explicit state export from each module** — Each module should export its state object synchronously so dependents can read it immediately.
3. **Central state registry** — Instead of modules reading each other's state, have a central `wl_state.js` that ALL modules read from and write to. This decouples module dependencies.
4. **Self-tests in each module** — Add a test block at the bottom of each module that runs after initialization: `if (typeof module !== 'undefined' && module.exports) { /* run tests */ }`. This catches initialization failures immediately.
5. **Mandatory initialization guard** — Each module should export a `isReady` flag that is set to `true` only after all setup is complete. Dependent modules can assert `wl_table.isReady === true`.

**Detection:**
- Intermittent `undefined is not an object` errors in browser console that don't reproduce consistently.
- Application works fine in development but fails in production (usually due to network latency or server load).
- Add a startup phase that calls `isReady` on all modules; if any are `false`, display an error banner.

---

### Pitfall 3: Python Module Import Path Failures in Splunk's bin/ Directory

**What goes wrong:**
- When splitting `wl_handler.py` (7,078 lines) into modules (wl_csv.py, wl_rbac.py, wl_approval.py, etc.), you need to import those modules from the REST handler.
- Splunk's Python environment doesn't automatically add `/opt/splunk/etc/apps/wl_manager/bin/` to `sys.path`. Splunk's REST framework uses a custom loader that restricts where modules can be imported from.
- Relative imports fail: `from . import wl_csv` raises `ImportError: attempted relative import in non-package`.
- Absolute imports fail: `import wl_csv` fails if the bin directory isn't in `sys.path`.

**Why it happens:**
- Splunk's REST handler framework executes the handler file directly, not as a package. Python treats it as a script, not a module, so relative imports don't work.
- The `sys.path` that Splunk sets up includes the Splunk Python library directories but typically NOT the app's bin directory.
- Different Splunk versions may have different import behaviors. What works in Splunk 9.0 may fail in 9.1 after a patch.

**Consequences:**
- REST endpoint fails with HTTP 500 and logs `ImportError: No module named 'wl_csv'`.
- App doesn't load at all; users see a blank page or "Connection failed" error.
- Issue only surfaces when the app is deployed, not during development (if you have a separate test environment with different PYTHONPATH).

**Prevention:**
1. **Explicit sys.path setup** — At the top of `wl_handler.py`, add:
   ```python
   import sys
   import os
   _app_bin = os.path.dirname(os.path.abspath(__file__))
   if _app_bin not in sys.path:
       sys.path.insert(0, _app_bin)
   ```
   This ensures the bin directory is in the import path before any local imports.

2. **Package structure** — Create an empty `__init__.py` in the bin directory to make it a proper Python package:
   ```bash
   touch /opt/splunk/etc/apps/wl_manager/bin/__init__.py
   ```
   Then use relative imports: `from . import wl_csv` or `from .wl_csv import read_csv`.

3. **Test imports in isolation** — Before deploying, verify imports work:
   ```python
   python -c "import sys; sys.path.insert(0, 'bin'); from wl_csv import read_csv; print('OK')"
   ```

4. **Never rely on PYTHONPATH env var** — Splunk may run with different environment variables than your terminal. Always modify `sys.path` in code.

5. **Version ALL imports and list in docs** — Document exactly which modules are imported and when. If a module is optional (e.g., `fcntl` on Windows), use try-except:
   ```python
   try:
       from wl_approval import ApprovalQueue
   except ImportError as e:
       _logger.error("Failed to import approval module: %s", e)
       raise
   ```

**Detection:**
- Splunk logs show `ImportError: No module named 'wl_...'` in `/opt/splunk/var/log/splunk/splunkd.log`.
- REST endpoint returns HTTP 500 with generic "Internal Server Error" (exception details are in logs, not the response).
- Test by calling the endpoint: `curl -k -u admin:password https://localhost:8089/servicesNS/nobody/wl_manager/...`.

---

### Pitfall 4: Python Global State and File Locking in Modular Code

**What goes wrong:**
- Current `wl_handler.py` uses global state: `_approval_queue_lock` (threading.RLock), `_presence` (dict), `_rate_limits` (dict), `_detection_rules_modify()` context manager.
- When split into modules, these globals must be initialized in ONE place and shared across all modules. If each module initializes its own locks, concurrent access will use different locks and race conditions re-emerge.
- Example: `wl_approval.py` uses `_approval_queue_lock` for mutual exclusion. If `wl_handler.py` has its own `_approval_queue_lock` and `wl_approval.py` creates another with the same name, they're different objects and provide no actual exclusion.

**Why it happens:**
- Developers assume a lock named `_approval_queue_lock` in module A and another in module B are the same lock. They're not; they're separate Python objects.
- Module initialization order matters. If `wl_approval.py` is imported before `wl_handler.py` initializes the global lock, the wrong lock is used.
- Threading bugs are the hardest to reproduce. A lock might work fine in single-threaded tests but fail under concurrent load in production.

**Consequences:**
- Approval queue corruption: two admins approve the same item simultaneously, creating duplicate audit events or leaving the queue in an inconsistent state.
- File lock failures: two analysts edit the same CSV simultaneously, both see stale mtime values, both writes succeed, later data is lost.
- Race condition severity scales with app usage. A rarely-used feature may never trigger the bug. Heavy usage exposes it immediately.

**Prevention:**
1. **Centralize all global state in one module** — Create `wl_globals.py` that initializes ALL locks, caches, and shared state:
   ```python
   # wl_globals.py
   import threading
   
   _approval_queue_lock = threading.RLock()
   _presence = {}
   _rate_limits = {}
   
   def get_approval_lock():
       return _approval_queue_lock
   ```
   Import this module in `wl_handler.py` and all other modules:
   ```python
   from wl_globals import get_approval_lock
   lock = get_approval_lock()
   ```

2. **Document thread safety explicitly** — Add a comment to each module that uses locks:
   ```python
   """
   wl_approval.py — Approval Queue Management
   
   Thread safety: This module requires approval_queue_lock (from wl_globals).
   All functions that access _approval_queue must acquire the lock first.
   See _approval_queue_lock context manager in wl_handler.py.
   """
   ```

3. **Test with concurrent writes** — Add a stress test that spawns 10 threads, each writing to the same CSV 100 times:
   ```python
   def test_concurrent_csv_writes():
       import threading
       def write_csv(idx):
           for i in range(100):
               wl_csv.save_csv(...)
       threads = [threading.Thread(target=write_csv, args=(i,)) for i in range(10)]
       for t in threads:
           t.start()
       for t in threads:
           t.join()
       # Verify CSV is not corrupted
   ```

4. **Code review checklist** — When reviewing any module that uses file I/O or shared state, ask: "Is this protected by a lock? Is the lock the shared global lock, not a local one?"

**Detection:**
- Approval queue has duplicate entries or entries in inconsistent states (pending but also in approved list).
- CSV file is corrupted or contains partial writes from competing saves.
- Errors only happen under load; single-threaded tests pass.
- Splunk logs show `IOError: [Errno 11] Resource temporarily unavailable` (lock acquisition timeout on Linux).

---

### Pitfall 5: AppInspect Failures on Modular File Structure

**What goes wrong:**
- AppInspect (Splunk's static app validator) has specific rules about file structure, naming, and content.
- Common failures:
  - **File placement:** `.py` files in the wrong directory (must be `bin/` for REST handlers, or the file won't be loaded).
  - **Naming conventions:** Module names like `wl_csv.py` are fine, but files like `wl-csv.py` (hyphen instead of underscore) confuse the importer and AppInspect.
  - **Python syntax:** If any `.py` file has syntax errors, AppInspect fails the entire app.
  - **Missing dependencies:** If `wl_handler.py` imports `wl_csv` but that file isn't included in the app package, AppInspect flags a missing dependency.
  - **Hardcoded paths:** If code references `/opt/splunk/` paths directly, AppInspect warns about portability.
  - **Splunk SDK usage:** If modules use old Splunk SDK APIs (e.g., `splunklib.client.Service`), AppInspect may reject as deprecated.

**Why it happens:**
- Developers split code without verifying that all imports are resolvable. A function in `wl_approval.py` references a class from `wl_csv.py`, but the import statement is missing.
- File rename during refactoring: `old_module.py` → `new_module.py`, but import statements still reference the old name.
- Splunk version differences: A function available in Splunk 9.0 might be deprecated in 9.1. AppInspect may reject it.

**Consequences:**
- App upload to Splunkbase fails; manual Splunk deployment works (because Splunk is more lenient than AppInspect).
- Partial feature degradation: some modules load, others fail silently. Users see incomplete UI or missing functionality.
- Validation happens late in the pipeline. You discover AppInspect failures only when attempting to publish, not during development.

**Prevention:**
1. **Run AppInspect locally during development** — Before every merge to main, run:
   ```bash
   /opt/splunk/bin/splunk show-encrypted --value 'YOUR_SPLUNK_PASSWORD' > /tmp/pwd.txt
   /opt/splunk/bin/splunk cmd splunkd rfs -- list-files --pattern="*.py" > /tmp/py_files.txt
   
   # Or use the Python AppInspect package:
   pip install splunk-appinspect
   appinspect validate --included-tags cloud ~/wl_manager/
   ```

2. **Strict linting in CI/CD** — Add a pre-commit hook that runs Python's compile check on all `.py` files:
   ```bash
   for f in bin/*.py; do
       python3 -m py_compile "$f" || exit 1
   done
   ```

3. **Module import audit** — Create a script that traces all imports:
   ```python
   import ast
   import os
   
   for root, dirs, files in os.walk('bin'):
       for file in files:
           if file.endswith('.py'):
               path = os.path.join(root, file)
               with open(path) as f:
                   tree = ast.parse(f.read())
               for node in ast.walk(tree):
                   if isinstance(node, ast.Import):
                       for alias in node.names:
                           if alias.name.startswith('wl_'):
                               # Check that the module exists
                               mod_file = os.path.join('bin', alias.name.replace('.', '/') + '.py')
                               if not os.path.exists(mod_file):
                                   print(f"ERROR: {path} imports {alias.name} but {mod_file} not found")
   ```

4. **Naming consistency** — Enforce naming rules:
   - Files: `lowercase_with_underscores.py` (never hyphens)
   - Classes: `PascalCase`
   - Functions: `lowercase_with_underscores()` for public, `_lowercase_with_underscore()` for private
   - Constants: `UPPER_CASE`

5. **Configuration file updates** — When adding modules, ensure `restmap.conf` still points to the correct handler and `props.conf`/`transforms.conf` reference the right sourcetype names.

**Detection:**
- AppInspect report lists "Python syntax errors" or "Missing dependencies".
- `app.conf` references non-existent views or dashboards.
- REST endpoint URL in `restmap.conf` points to a handler that doesn't exist or has the wrong name.
- Import errors in Splunk logs after deployment to a new Splunk instance.

---

## Moderate Pitfalls

### Pitfall 6: Optimistic Locking Parse Failures in Modular Code

**What goes wrong:**
- Current code validates `expected_mtime` to prevent concurrent edit conflicts. If parsing fails and the exception is silently caught, the app proceeds without the protection.
- When splitting into modules, this validation logic might end up in `wl_csv.py` while the save logic is in `wl_handler.py`. If modules don't share the validation result, one module might proceed unprotected.

**Prevention:**
- Any security-relevant value (mtime, user role, approval status) must fail the entire operation if parsing fails, never silently proceed.
- Use explicit `is None` checks, not truthy/falsy tests:
  ```python
  mtime = parse_mtime(expected_mtime_str)
  if mtime is None:
      return _resp(400, {"error": "Invalid mtime format"})
  ```
- Never silently use a default value for security-relevant fields.

---

### Pitfall 7: Approval Queue Replay State Machine Fragility

**What goes wrong:**
- Approval queue stores pending requests. When admin approves a request, the handler replays the original action (save CSV, create rule, etc.). If state changes between request submission and approval, the replay operates on stale assumptions.
- Example: Analyst A requests "Create rule 'DR_NEW'". While pending, analyst B creates and then deletes rule 'DR_NEW'. Admin approves A's request. The replay tries to create a rule that already exists (and was already deleted), potentially recreating stale data.

**Prevention:**
- Before replaying ANY queued action, re-validate all preconditions:
  ```python
  def replay_request(request):
      action = request['action']
      if action == 'create_rule':
          rule = request['rule_name']
          if rule_exists(rule):
              return error("Rule already exists")  # Fail gracefully
          create_rule(rule)
      elif action == 'save_csv':
          rule = request['detection_rule']
          csv = request['csv_file']
          if not rule_exists(rule):
              return error("Rule no longer exists")  # Fail gracefully
          save_csv(rule, csv, request['data'])
  ```
- Never assume state hasn't changed between submission and approval.
- Log the precondition check result in the audit event so analysts know why an approval didn't proceed as expected.

---

### Pitfall 8: Version Manifest Consistency Under Concurrent Saves

**What goes wrong:**
- Current version control: when saving a CSV, create a snapshot in `lookups/_versions/`, update the manifest JSON file.
- If two saves happen concurrently without file locking, both may read the same manifest, append to it independently, and the last write wins. Version entries get lost or duplicated.

**Prevention:**
- All manifest updates must be atomic. Read-then-write is not atomic:
  ```python
  # WRONG — race condition
  manifest = json.load(open(manifest_file))
  manifest['versions'].append(new_version)
  json.dump(manifest, open(manifest_file, 'w'))
  
  # CORRECT — atomic with lock
  with _manifest_lock:
      with open(manifest_file, 'r') as f:
          manifest = json.load(f)
      manifest['versions'].append(new_version)
      with open(manifest_file, 'w') as f:
          json.dump(manifest, f)
  ```
- File locking must protect both the version snapshot file AND the manifest file.

---

### Pitfall 9: Presence Tracking Data Accumulation

**What goes wrong:**
- Presence tracking stores `{user: last_activity_timestamp}` to show who's editing. Without cleanup, stale entries accumulate indefinitely.
- After weeks of usage, the presence dict grows to 10K+ entries, causing memory pressure and slow lookups.

**Prevention:**
- Implement a pruning function that removes entries older than N hours (e.g., 24 hours):
  ```python
  def prune_stale_presence(max_age_hours=24):
      cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
      global _presence
      _presence = {u: t for u, t in _presence.items() if t > cutoff}
  ```
- Call this on every presence update or on a scheduled basis.

---

### Pitfall 10: Daily Limit Reset Edge Cases

**What goes wrong:**
- Daily limits reset at midnight UTC (or local time, depending on implementation). Edge cases:
  - User A is in UTC-5, user B is in UTC+9. The same calendar day means different UTC times.
  - Time zone changes due to DST (daylight saving time) shift the boundary.
  - Scheduled reset at 2am UTC might miss if Splunk is restarted at 1:50am, preventing reset from running.

**Prevention:**
- Always use UTC for comparisons; convert to user's local time only for display.
- Use explicit date boundaries, not time-based windows:
  ```python
  from datetime import date, timezone, datetime
  
  def is_new_day(user):
      today_utc = date.today()
      last_action_date = USAGE_DB.get(user, {}).get('date')
      return last_action_date != today_utc
  ```
- Test with artificial date changes:
  ```python
  import unittest
  from unittest.mock import patch
  
  def test_daily_limit_reset_midnight():
      with patch('datetime.date.today') as mock_date:
          mock_date.return_value = date(2026, 1, 1)
          usage = get_user_daily_usage('analyst')
          assert usage == 0
          
          mock_date.return_value = date(2026, 1, 2)
          usage = get_user_daily_usage('analyst')
          assert usage == 0  # Should reset
  ```

---

## Minor Pitfalls

### Pitfall 11: Module Initialization Order Dependencies

**What goes wrong:**
- If module B initializes before module A, but B depends on A being initialized first, you get undefined state.
- Example: `wl_constants.py` must load before `wl_validation.py` so that validation regex patterns are available.

**Prevention:**
- Use explicit import statements at the top of each module in the order they must initialize.
- Add assertions in each module:
  ```python
  from wl_constants import MAX_ROW_SIZE
  assert MAX_ROW_SIZE > 0, "wl_constants not initialized"
  ```

---

### Pitfall 12: Frontend State Sync Before Mutations

**What goes wrong:**
- Current code requires calling `syncInputs()` before `refreshTable()` to capture user edits from DOM inputs into the `currentRows` state variable. If a developer forgets to sync, edits are lost.

**Prevention:**
- Make `syncInputs()` mandatory by having `refreshTable()` call it automatically:
  ```javascript
  function refreshTable() {
      syncInputs();  // Auto-sync before redrawing
      // ... render table ...
  }
  ```
- Or use a proxy to enforce sync before any state read.

---

### Pitfall 13: Splunk JavaScript Cache Invalidation

**What goes wrong:**
- Splunk caches `whitelist_manager.js` aggressively. You bump the `build` number in `app.conf`, but the browser or Splunk still serves the old cached version.
- Developer: "I changed the code but it's not taking effect!"

**Prevention:**
- After every JavaScript change:
  1. Bump `build` number in `app.conf`
  2. Delete i18n cache: `rm -f /opt/splunk/var/run/splunk/appserver/i18n/*.js-*`
  3. Restart Splunk
  4. Hard refresh in browser (Ctrl+Shift+R)
- Document this in deployment docs so future maintainers know the exact steps.

---

### Pitfall 14: Python 2 vs Python 3 Incompatibilities

**What goes wrong:**
- Some Splunk versions ship Python 2, others Python 3. If you write Python 3-only code (f-strings, type hints, etc.), it fails on Python 2.
- Conversely, if you assume Python 2 (unicode handling, print statements), it fails on Python 3.

**Prevention:**
- Explicitly target Python 3 only. In `app.conf`:
  ```
  [install]
  state = enabled
  python.version = 3
  ```
- Use:
  - `str` and `bytes` explicitly (don't rely on implicit coercion)
  - Type hints: `def read_csv(filepath: str) -> List[Dict[str, str]]`
  - f-strings: `msg = f"User {user} edited {rule}"`
- Test with `python3 -m py_compile bin/*.py` to catch syntax errors.

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|-----------------|------------|
| 1-2 | Backend Module Split | Python import path failures, file locking not shared across modules | Early explicit import test; create `wl_globals.py` first, test imports before writing business logic |
| 2-3 | Frontend AMD Modules | Circular dependencies, load order timing issues | Dependency audit before splitting; create `wl_shared.js` for common functions; test with manual require order |
| 3-4 | Version Migration | Existing version manifests incompatible with new schema | Backward-compatible version manifest schema; test with old manifests from production |
| 4-5 | Approval Queue Replay | Stale state operations, precondition gaps | Add precondition validation in replay logic; extensive concurrent approval testing |
| 5 | AppInspect | File structure, naming, syntax errors | Run local AppInspect on every commit; strict pre-commit linting |
| 5 | Testing | Concurrent write failures only in production | Thread stress tests; file lock validation under load |

---

## Risks by Severity

### High Severity (Core Function Broken)
- **Python import path failures** → App doesn't load at all
- **AMD circular dependencies** → Frontend doesn't initialize
- **File locking not shared** → Data corruption under concurrent load
- **Approval replay without precondition validation** → Silent stale state operations

### Medium Severity (Features Broken or Unreliable)
- **AppInspect failures** → Can't publish to Splunkbase
- **Concurrent save race conditions** → Version manifest inconsistency, lost edits
- **Module initialization order** → Intermittent "undefined" errors
- **Optimistic locking parse failure** → Concurrent edit protection disabled

### Low Severity (Operational Issues)
- **Presence tracking accumulation** → Slow lookups after weeks
- **Daily limit edge cases** → Occasional incorrect limits around midnight
- **Splunk JS cache** → Confusing UX ("I changed it but it didn't take effect")

---

## Validation Checklist Before Shipping Each Phase

- [ ] All Python `.py` files in `bin/` compile without syntax errors: `python3 -m py_compile bin/*.py`
- [ ] All imports are resolvable: run custom import audit script
- [ ] All file locking uses shared global locks, not local ones
- [ ] Approval queue replay includes full precondition validation
- [ ] Frontend modules load in order without undefined dependencies
- [ ] No AMD circular dependencies: run dependency graph analysis
- [ ] All JavaScript modules export required functions synchronously
- [ ] Build number in `app.conf` bumped; Splunk restarted; browser cache cleared
- [ ] Local AppInspect passes all checks (if targeting Splunkbase)
- [ ] Concurrent write stress test runs successfully
- [ ] Approval queue stress test (10 concurrent approvals) passes
- [ ] Version manifests from production can still be read by new code

---

## Sources

- Current codebase analysis: CONCERNS.md (technical debt + known bugs), CONVENTIONS.md (naming + patterns)
- Lessons learned: MEMORY.md (user feedback on past bugs and mitigations)
- Splunk architecture: CLAUDE.md (REST handler, AMD loader, caching behavior)
- Splunk Python documentation: REST handler guide, import path documentation
- RequireJS documentation: circular dependency warnings, load order guarantees
- AppInspect rules: cloud app certification requirements, file structure validation

---

*Analysis completed 2026-03-31*
