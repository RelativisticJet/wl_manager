# Phase 5: Frontend Architecture - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract `whitelist_manager.js` (6,786 lines) into ~10-11 AMD modules with a centralized state manager (`wl_state.js`), shared REST helpers (`wl_rest.js`), and a UI utilities module (`wl_ui.js`). Rewrite `notifications.js` as AMD module using shared REST helpers. Rewrite `whitelist_manager.js` as thin entry point (~100 lines) that requires feature modules and orchestrates cross-module workflows. Module count is flexible — extract what makes sense, don't force a target number.

</domain>

<decisions>
## Implementation Decisions

### State Management (wl_state.js)

- **Getter/setter + events**: `State.get(key)`, `State.set(key, val)` — setters fire jQuery custom events (`state:keyName`) so listeners react automatically
- **Central registry**: All shared state keys registered in `wl_state.js` with defaults and validators. Single source of truth for what shared state exists
- **Throw on unknown key**: `State.get('typo')` throws `TypeError`. All valid keys must be registered via internal `_register()`. Fail-fast, consistent with backend convention
- **Full validation**: `State.set()` enforces type/invariant validators per key. Validation failure throws `TypeError` — fail-fast, never silently accept bad state
- **Cross-module state only**: Only state accessed by 2+ modules goes in `wl_state.js`. Module-internal state (dragState, resizeState, msgTimer, currentPage, searchQuery) stays local to its module
- **`State.reset()` method**: Single call clears all shared state to registered defaults. Fires `'state:reset'` event so modules clear local state too. Called on CSV switch
- **`State.batch()` method**: Applies multiple key updates atomically, fires events only after all keys are set. Prevents intermediate renders when loading CSV data
- **`State.isDirty()` computed property**: Compares `currentRows` vs `originalRows`. Auto-fires `'state:dirty'` event when dirty status changes (on any currentRows/originalRows mutation). Save button subscribes once
- **No event namespacing**: Flat events only — `State.on('currentRows', fn)`, `State.on('reset', fn)`. No wildcard or group subscriptions
- **Undo stays module-local**: `undoState` and `undoTimer` stay in `wl_table.js`. Table handles snapshot/restore internally, only calls `State.set('currentRows', restoredRows)` on undo
- **Debug API**: Expose `window.__wlState` (behind `window.__wlDebug` flag) with `get()` and `dump()` for console debugging during development

### Module Boundaries

- **Strict layer dependency**: Foundation (wl_constants, wl_state, wl_rest, wl_ui) can't depend on feature modules. Feature modules depend on foundation but NEVER on each other. Cross-feature communication goes through State events or `wl:*` custom events
- **Return object API**: Each module returns `{init, publicFn1, publicFn2}` via AMD `define()`. Clean contracts, no global namespace pollution
- **Each module binds own DOM events**: No centralized `wl_events.js`. Table binds table events, search binds search events, etc. Events co-located with handlers
- **Flexible module count**: Don't force 12 modules. Extract what makes sense. `wl_events.js` eliminated (absorbed). `wl_theme.js` absorbed into `wl_ui.js`. Actual count ~10-11
- **Straddling functions → orchestrator**: Cross-module workflows (save, load CSV, revert) stay in entry point as thin orchestrators that call module APIs in sequence. No business logic in orchestrator
- **wl_csv_io.js is single module**: Both import (parser, validator, preview) and export in one module (~300 lines). Not worth splitting
- **wl_table.js accepts large size**: ~1500-2000 lines is acceptable. Table rendering, cell editing, pagination, column resize, drag-drop, date picker, undo bar, row selection, textarea char counter — all tightly coupled to table DOM. Well-structured with clear internal sections
- **Pagination in wl_table.js**: `currentPage`, `ROWS_PER_PAGE`, page navigation are module-local state. Only used by table
- **Column resize + drag-drop in wl_table.js**: `resizeState`, `dragState`, `colWidths` are table-specific DOM interactions
- **Date picker in wl_table.js**: Activated by clicking Expires column cell. Table-specific UI flow
- **formatDailyLimitMsg in wl_approval_ui.js**: Daily limit message formatting is part of approval gate flow domain
- **Theme toggle in wl_ui.js**: Dark/light theme detection and toggle (~30 lines) grouped with other UI utilities
- **Textarea maxlength counter in wl_table.js**: Cell editing DOM interaction, co-located with other cell editing logic

### Module Communication

- **State events + entry point wiring**: Modules emit intent via `wl:*` custom events on `$(document)`. Entry point listens and orchestrates cross-module flows. Example: `wl_table` fires `'wl:removeRequested'`, entry point catches it and calls `WlModals.showRemoveDialog()`
- **`wl:` prefix for custom events**: All custom inter-module events use `'wl:actionName'` format. State events use `'state:keyName'`. Clear separation from jQuery/Splunk/native DOM events
- **Centralized error handler in wl_rest.js**: Default `.fail()` handler fires `'wl:restError'` event. Entry point listens and shows error via `WlUI.showMsg()`. Modules can override per-call `.fail()` for special cases (e.g., 409 conflict handling)
- **notifications.js → AMD module**: Rewritten with `define()`, imports `wl_rest.js`. Replaces `window.__wlNotifCallbacks` with `'wl:notificationsUpdated'` event on document
- **Ordered init, fail-fast**: Entry point calls `module.init()` in dependency order (state → rest → ui → features). Any init throw catches to `showFatalError()`. No partial initialization
- **showMsg/messages → wl_ui.js**: Dedicated utility module for UI feedback: `showMsg`, `showFatalError`. Listens to `'wl:showMsg'` events. Any module can trigger messages without importing wl_ui

### Module Placement (Orchestrator)

- **URL parameter handling** (?rule=X&csv=Y) → entry point orchestrator
- **External change polling** (changeCheckTimer) → entry point orchestrator (triggers full CSV reload cascade)
- **Rule dropdown placement** → Claude's discretion (based on coupling analysis)
- **Admin role detection** → Claude's discretion (entry point or REST module startup)
- **Conflict handling (409)** → Claude's discretion (entry point save orchestrator vs wl_rest status hooks)
- **Event bus** (`$(document)` vs `$({})`) → Claude's discretion

### Migration Strategy

- **Wave-based extraction**: 4 waves matching Phase 4 backend pattern:
  - Wave 1: Foundation — `wl_constants.js`, `wl_state.js`, `wl_rest.js`, `wl_ui.js`
  - Wave 2: Independent features — `wl_search.js`, `wl_presence.js`, `wl_csv_io.js`
  - Wave 3: Coupled features — `wl_table.js`, `wl_modals.js`, `wl_versions.js`, `wl_approval_ui.js`
  - Wave 4: Orchestrator cleanup — slim entry point to ~100 lines, wire all events
- **Keep inline until extracted**: After each wave, entry point still contains unextracted code. Each wave moves code out and shrinks it. Always have working code
- **One commit per wave**: 4 commits for 4 waves. Each commit is a working app. Git revert is the rollback strategy
- **Manual smoke + QUnit tests**: After each wave: (1) deploy to Docker, (2) manual smoke test of critical paths, (3) QUnit tests for state manager and module APIs
- **QUnit in tests/qunit/ + test dashboard**: QUnit test files in `tests/qunit/test_*.js`. Hidden Splunk dashboard (`test_runner.xml`) loads QUnit + tests. Phase 5 scope: ~4 test files, ~50 assertions. Full E2E deferred to Phase 7
- **QUnit bundled in app**: Include QUnit library in app (vendored). Excluded from production package
- **Flat modules/ directory**: All modules in `appserver/static/modules/`. No subfolders needed for ~10 files
- **No XML dashboard changes**: AMD modules loaded via `require()`/`define()` inside entry point. Splunk's RequireJS handles discovery
- **RequireJS paths** → Claude's discretion (relative vs require.config)
- **Deploy modules/ via wildcard**: Copy entire `modules/` directory to container. Prevents version mismatch
- **Build number bump only for caching**: Continue existing pattern — bump app.conf build + clear i18n cache + restart. No per-file versioning
- **Git revert + redeploy as rollback**: Same as Phase 4. No feature flags or dual-mode fallback

### Safety Enforcement

- **`refreshTable()` auto-calls `syncInputs()`**: Structural enforcement of the MEMORY.md lesson. syncInputs() is always the first line of refreshTable(). No caller can forget. Double-sync is idempotent

### Claude's Discretion

- AMD path configuration (relative imports vs require.config)
- Event bus implementation (`$(document)` vs dedicated `$({})` emitter)
- Detection rule dropdown module placement (entry point vs dedicated module)
- Admin role detection placement (entry point init vs REST module startup)
- Conflict handling placement (orchestrator vs wl_rest status hooks)
- QUnit library sourcing (vendored location)
- Deploy tool updates (MCP server file list vs wildcard-only)
- Internal section organization within large modules (wl_table.js)
- Exact module count if extraction reveals better boundaries

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Frontend source (primary refactoring target)
- `appserver/static/whitelist_manager.js` — 6,786-line monolith to be split into AMD modules; contains all state, rendering, events, modals, REST calls
- `appserver/static/notifications.js` — 325-line standalone script to be rewritten as AMD module using wl_rest.js
- `appserver/static/whitelist_manager.css` — Styles with `wl-` prefix convention (no changes needed, but modules must follow prefix)

### Backend API (frozen contract)
- `bin/wl_handler.py` — REST handler with GET_ACTIONS/POST_ACTIONS dispatch tables. Frontend modules call these via wl_rest.js
- `CLAUDE.md` §"Key Architecture Decisions" — API contract, audit event structure, deployment flow

### Project constraints
- `.planning/PROJECT.md` §"Constraints" — jQuery + AMD only, no npm/bundlers, AppInspect compliance
- `.planning/REQUIREMENTS.md` §"Frontend Modularization" — FMOD-01 through FMOD-08 requirements
- `.planning/ROADMAP.md` §"Phase 5" — Success criteria, requirement mapping

### Prior phase context
- `.planning/phases/04-backend-integration/04-CONTEXT.md` — Backend dispatch pattern, error handling convention, migration safety approach (wave-based extraction pattern reused here)

### Codebase conventions
- `.planning/codebase/CONVENTIONS.md` — JS naming (camelCase functions, wl- CSS prefix), AMD require pattern, error handling patterns, Splunk REST call format
- `.planning/codebase/STACK.md` — jQuery, underscore, Splunk MVC, RequireJS (AMD)

### Bug pattern memory
- `~/.claude/projects/c--Users-PC-wl-manager/memory/MEMORY.md` — Critical: "Always syncInputs() before refreshTable()", "Apply same fix to ALL parallel code paths", "var hoisting causing silent undefined in init code"

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **jQuery event delegation**: `$(document).on('event', '.selector', handler)` pattern used extensively — reuse for `wl:*` custom events
- **`window.__wlNotifCallbacks`**: Existing cross-file callback pattern in notifications.js — will be replaced by `wl:notificationsUpdated` event
- **`Splunk.util.make_url()`**: URL builder for REST endpoints — moves into `wl_rest.js`
- **IIFE pattern**: Current module isolation via `require([...], function(...) { ... })` — transitions to AMD `define()` for feature modules

### Established Patterns
- **REST calls**: `$.ajax()` with `contentType: "application/json"`, `output_mode=json` — standardized in `wl_rest.js`
- **Error responses**: Backend returns `{error: "message"}` — `wl_rest.js` parses and fires `wl:restError`
- **CSS namespace**: All classes prefixed `wl-` — new modules follow same convention
- **4-space indentation, semicolons, `"use strict"`**: JS conventions from CONVENTIONS.md
- **State as closure vars**: Current pattern of ~40 `var` declarations at top of IIFE — migrated to `State.register()` for shared state, local `var` for module-private state

### Integration Points
- **SimpleXML dashboard**: `whitelist_manager.xml` loads entry point JS; no changes needed for AMD modules
- **app.conf build number**: Cache busting for all static assets; bump + i18n cache clear + restart
- **control_panel.js**: Phase 6 scope, but will consume `wl_rest.js` from Phase 5. Must not break during Phase 5 changes
- **notifications.js**: Rewritten in Phase 5 to use `wl_rest.js` and event-based communication

</code_context>

<specifics>
## Specific Ideas

- Wave-based extraction mirrors Phase 4 backend approach — proven pattern for this project
- `State.isDirty()` with auto-fired events prevents scattered dirty-checking logic (currently duplicated in save button, navigation, close-tab handlers)
- `refreshTable()` structurally calling `syncInputs()` first eliminates an entire class of bugs documented in MEMORY.md
- Full state validation with TypeError throws catches programming errors early during the migration (when modules are being wired up)
- `wl_ui.js` as the message/theme utility module keeps all non-domain UI concerns together, preventing showMsg from being scattered across modules

</specifics>

<deferred>
## Deferred Ideas

- control_panel.js modularization — Phase 6
- Browser E2E tests — Phase 7
- Performance profiling of AMD module loading — Phase 7/8 if needed
- Read/write lock semantics for state (concurrent tab scenarios) — not needed for current use case
- State persistence across page navigations (localStorage) — not needed, each page load is a fresh session
- `wl_events.js` as centralized event registry — eliminated, each module binds own events
- `wl_theme.js` as standalone — absorbed into `wl_ui.js`
- Pagination as standalone `wl_pagination.js` — absorbed into `wl_table.js`

</deferred>

---

*Phase: 05-frontend-architecture*
*Context gathered: 2026-04-02*
