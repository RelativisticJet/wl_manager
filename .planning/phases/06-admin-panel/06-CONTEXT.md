# Phase 6: Admin Panel - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Modularize `control_panel.js` (2,025 lines) into 5 AMD feature modules, rewriting it as a thin entry point (~150-200 lines). Completing frontend architecture. Zero functional change to existing admin panel features, with one small enhancement: notification badge + toast for new pending requests.

</domain>

<decisions>
## Implementation Decisions

### Module Boundaries

- **5 separate modules** (not 4 from original roadmap):
  - `wl_cp_queue.js` (~420 lines) — Approval queue: pending/history tables, pagination, approve/reject/cancel handlers, CSV download, `extractRequestReason()` helper
  - `wl_cp_limits.js` (~725 lines) — Limits & Permissions: field definitions, form rendering, validation, save/reset, change history, info tooltip logic (kept module-local)
  - `wl_cp_usage.js` (~190 lines) — Analyst Usage: paginated usage table, auto-refresh polling (10s), per-analyst and bulk reset handlers, USAGE_COLUMNS definition
  - `wl_cp_trash.js` (~180 lines) — Trash Management: trash table, restore handler, purge (dual-approval) handler, retention change handler
  - `wl_cp_admin_limits.js` (~135 lines) — Admin Limits (superadmin-only): admin limit form, save/reset handlers
- **`wl_cp_settings.js` dropped** — No matching code section exists. Roadmap/requirements to be updated
- **Entry point ~150-200 lines** (not ~100) — Contains shared modal helpers (showCpAlert, showCpConfirm, showCpPrompt), user detection, tab routing, init orchestration. Acceptable size for 90% reduction from 2,025 lines
- **`wl_cp_` prefix** for all CP-specific modules. Distinguishes from shared `wl_*` foundation modules at a glance
- **Pagination duplicated per module** — Queue and Usage each have their own pagination (~20 lines each). Simple code, slightly different state vars — not worth sharing
- **CSV download stays in wl_cp_queue.js** — Single-use feature tightly coupled to queue item context
- **wl_cp_limits.js stays as single large module** (~725 lines) — Cohesive single-form feature. Phase 5 accepted wl_table.js at ~650 lines for similar reasoning
- **All approve/reject/cancel handlers stay in wl_cp_queue.js** — Core queue actions tightly coupled to queue rendering and data attributes
- **Cross-CP imports allowed if needed** — No hard restriction, but expected pattern is leaf modules importing only foundation modules

### Shared Infrastructure Reuse

- **wl_rest.js via AMD import** — Each CP module does `define(['modules/wl_rest'], function(REST) { ... })`. Direct import, no entry point middleman. This is the whole point of FMOD-03
- **wl_ui.js for theme detection** — CP entry point imports wl_ui.js and calls `UI.detectTheme()` during init. Eliminates duplicated dark theme detection IIFE
- **wl_constants.js for shared constants** — Action type strings, CSS class patterns imported from shared constants. CP-specific constants (PAGE_SIZE, USAGE_PER_PAGE) stay module-local
- **User detection stays in CP entry point** — `cpCurrentUser` and `cpIsSuperAdmin` are CP-specific, read-only after init (~15 lines). No reuse needed
- **Modal helpers stay in entry point** — `showCpAlert`, `showCpConfirm`, `showCpPrompt` use CP-specific DOM IDs and event namespaces. Passed to modules via init context object
- **Info tooltips stay in wl_cp_limits.js** — Only limits uses them. YAGNI for sharing
- **`extractRequestReason()` stays in wl_cp_queue.js** — Queue-domain-specific data extraction helper

### Dependency Injection

- **Init context object** — Entry point passes context during init: `Module.init({ showAlert, showConfirm, showPrompt, currentUser, isSuperAdmin, isAdmin })`. Clean injection, modules stay testable
- **AMD imports for foundation** — Modules import `wl_rest`, `wl_constants`, `wl_ui` directly via AMD `define()`. No indirection through entry point
- **Splunk SDK loaded by entry point** — Entry point's `require()` loads jQuery, underscore, splunkjs/mvc, simplexml/ready!. CP modules only declare custom module dependencies in `define()`. jQuery and underscore are AMD globals already available

### State Management

- **All state module-local** — CP has no cross-module state mutations. No need for wl_state.js. Each module manages its own closure variables
- **cpCurrentUser and cpIsSuperAdmin** — Read-only after init, passed via context object. Never change during page session
- **Snapshot comparison for limits save** — wl_cp_limits.js keeps `loadedLimits` snapshot for no-change detection. Shows "No changes detected" instead of submitting no-op saves

### Tab Routing & Polling

- **Entry point manages tabs** — Tab rendering, switching, and module lifecycle orchestration all in entry point. ~80 lines of tab logic
- **URL update on tab switch** — `history.replaceState` updates `?tab=` parameter when user manually switches tabs. Page refresh keeps user on current tab
- **Queue polling only when Queue tab is visible** — Changed from always-on. Entry point calls `QueueModule.startPolling()` / `QueueModule.stopPolling()` during tab switch
- **Each module exports start/stop polling** — `Module.startPolling()` and `Module.stopPolling()` in public API. Entry point manages lifecycle during tab switch
- **Immediate refresh on tab switch** — When switching to a tab: call `Module.load()` for fresh data, then `Module.startPolling()`. No stale data wait
- **Pause all polling on browser tab hidden** — `document.visibilitychange` event. When page hidden, stop all active polling. When visible again, refresh active CP tab data and resume polling
- **Modal guard preserved** — Queue polling skips refresh when a modal is open (`$('.wl-modal-overlay').length`). Prevents disorienting re-render during approve/reject confirmation
- **Polling intervals**: Queue 5s, Usage 10s. Only active tab polls. Minimal server load

### Error Handling

- **Centralized via showCpAlert** — All modules call `ctx.showAlert('Error', message, 'error')` on failure. Consistent UX across tabs
- **Show server messages directly** — Display `data.error` as-is. Server error messages are already user-friendly (written in Phases 1-4)
- **Include HTTP status code** in network failure messages — Show `'Error loading trash (HTTP 500)'` for `.fail()` callbacks. Helpful for SOC admins who are technical

### Access Control

- **Defense in depth everywhere** — Entry point gates (no modules loaded if access denied) AND every module self-guards via `ctx.isAdmin` check in `init()`. Admin Limits additionally checks `ctx.isSuperAdmin`
- **Immediate deny, no module load** — If initial get_approval_queue call returns 403/error, show access denied page and return early. AMD modules never loaded for unauthorized users
- **Combined access check + data load** — `get_approval_queue` serves dual purpose: check access AND load queue data. No extra roundtrip
- **Re-check superadmin on destructive actions** — For trash purge and retention change, re-verify superadmin status with a fresh server call. Protects against role changes during long-lived sessions
- **Init failure = fail-fast** — If any module.init() throws, show fatal error and stop. No partial CP initialization

### Notification Enhancement (New)

- **Badge on Queue tab** — Show count badge (e.g., "Approval Queue (3)") when pending count increases. Admin sees new requests arrived even from other tabs. Updated by queue polling data
- **CP-local toast for new requests** — Brief toast ("2 new pending requests") when queue polling detects count increase. Auto-fades after 5 seconds. Clicking dismisses and switches to Queue tab
- **No import of notifications.js** — CP uses its own simple toast. notifications.js is analyst-facing, not admin-facing

### Migration Strategy

- **4 plans in 3 effective waves** (mirrors Phase 5 pattern):
  - **06-01 (Wave 1 Foundation):** Restructure entry point — AMD imports of wl_rest/wl_ui/wl_constants, access check, tab routing, shared helpers, visibilitychange handler
  - **06-02 (Wave 2a Simple Modules):** Extract trash, admin_limits, usage modules. Deploy and smoke test
  - **06-03 (Wave 2b Complex Modules):** Extract queue, limits modules + notification badge/toast. Deploy and smoke test
  - **06-04 (Wave 3 Tests):** Comprehensive QUnit tests + final verification
- **One commit per plan** — Each plan produces a working app. Git revert is the rollback strategy
- **Full regression smoke test** — After each wave: verify ALL CP tabs + whitelist_manager.js still works. Since CP modules share wl_rest.js with WM, changes could affect WM

### QUnit Testing

- **Comprehensive scope** — ~50+ assertions across 5 test files. Test rendering output, event handlers, pagination, modal interactions
- **One test file per module** — test_cp_queue.js, test_cp_limits.js, test_cp_usage.js, test_cp_trash.js, test_cp_admin_limits.js
- **Same test_runner.xml** — Add CP test files to existing Phase 5 test runner dashboard. One place to run all frontend tests
- **Mock + live tests** — Mocked REST calls ($.mockjax or sinon) for unit-level verification + live Docker container tests for integration. Both test suites

### CSS & Responsive

- **CSS stays in shared file** — All .wl-cp-* classes already namespaced in whitelist_manager.css. Not worth extracting ~50-80 lines
- **Minimal horizontal scroll** — Add `overflow-x: auto` to table containers during extraction. One CSS property, prevents broken layout on narrow screens without responsive redesign

### Claude's Discretion

- Init order of the 5 modules (no dependencies between them)
- Internal section organization within large modules (wl_cp_limits.js)
- Exact assertion targets per test file
- Whether control_panel.xml needs REST push during deploy (verify if ever saved through Splunk UI)
- Whether MCP deploy i18n cache clearing covers new wl_cp_*.js filenames
- Profile queue rendering performance — flag if it exceeds 100ms for 120 items

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Frontend source (primary refactoring target)
- `appserver/static/control_panel.js` — 2,025-line monolith to be split into 5 AMD modules
- `appserver/static/whitelist_manager.css` — Shared styles with `.wl-cp-*` prefix for CP-specific classes

### Phase 5 foundation modules (reuse targets)
- `appserver/static/modules/wl_rest.js` — Shared REST helpers to replace CP's duplicated restGet/restPost
- `appserver/static/modules/wl_ui.js` — UI utilities including theme detection to replace CP's duplicated dark theme IIFE
- `appserver/static/modules/wl_constants.js` — Shared constants (action types, CSS classes) to import in CP modules
- `appserver/static/modules/wl_state.js` — State manager reference (NOT used by CP, but understand its patterns)

### Phase 5 context (patterns to follow)
- `.planning/phases/05-frontend-architecture/05-CONTEXT.md` — AMD module patterns, wave-based extraction strategy, event conventions, all established in Phase 5 and reused here

### Backend API (frozen contract)
- `bin/wl_handler.py` — REST handler with GET_ACTIONS/POST_ACTIONS dispatch tables. CP modules call these via wl_rest.js

### Dashboard
- `default/data/ui/views/control_panel.xml` — CP dashboard. Verify if REST push needed during deploy (may have been saved through Splunk UI)

### Project constraints
- `.planning/PROJECT.md` §"Constraints" — jQuery + AMD only, no npm/bundlers, AppInspect compliance
- `.planning/REQUIREMENTS.md` §"Frontend Modularization" — FMOD-06 and FMOD-07 (to be updated to 5 modules)
- `.planning/ROADMAP.md` §"Phase 6" — Success criteria (to be updated during planning)

### Bug pattern memory
- `~/.claude/projects/c--Users-PC-wl-manager/memory/MEMORY.md` — Critical lessons for frontend work: syncInputs before refreshTable, apply same fix to ALL parallel code paths, var hoisting, dual data stores

### QUnit infrastructure
- `tests/qunit/test_module_loading.js` — Phase 5 QUnit tests (pattern reference)
- `tests/qunit/test_state_transitions.js` — Phase 5 QUnit tests (pattern reference)
- `default/data/ui/views/test_runner.xml` — Hidden QUnit test runner dashboard (add CP tests here)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **wl_rest.js** (175 lines): Unified REST helpers — direct replacement for CP's duplicated restGet/restPost (lines 58-83)
- **wl_ui.js** (235 lines): Theme detection via detectDarkTheme() — direct replacement for CP's duplicated IIFE (lines 23-32)
- **wl_constants.js** (208 lines): Shared constants for action types and CSS class patterns
- **AMD define() pattern**: All Phase 5 modules follow `define(['deps'], function(Dep) { return {init, ...}; })` — same pattern for CP modules
- **jQuery custom events**: `wl:*` prefix convention established in Phase 5 for inter-module events

### Established Patterns
- **Init context injection**: Phase 5 modules receive shared dependencies via init(config) pattern
- **Module public API**: `return {init, publicFn1, publicFn2}` via AMD define() — clean contracts
- **Wave-based extraction**: Proven in Phases 4 and 5 — foundation first, features second, tests third
- **Fail-fast on init error**: Phase 5 catches init throws and calls showFatalError()
- **`wl_cp_` prefix convention**: All CP-specific CSS classes already use `.wl-cp-*` — JS modules follow same naming

### Integration Points
- **control_panel.xml** dashboard loads control_panel.js entry point via `<script>` in HTML panel
- **app.conf build number**: Cache busting for all static assets — same bump + i18n cache clear + restart pattern
- **modules/ directory**: CP modules coexist with WM modules in flat directory. Wildcard copy for deploy
- **test_runner.xml**: Add CP QUnit test files to existing test runner dashboard

</code_context>

<specifics>
## Specific Ideas

- 4-plan structure mirrors Phase 5's 4-plan approach — proven pattern for this project
- Defense-in-depth access control: entry point gates + module self-guards + server-side re-verification on destructive operations
- Queue tab badge + toast notification is a small UX enhancement within modularization scope — data already available from polling
- Clicking toast notification dismisses it AND switches to Queue tab — dual purpose interaction
- `history.replaceState` for tab URL — modern UX, no page reload, refresh-friendly
- `document.visibilitychange` for polling lifecycle — prevents unnecessary server load when admin switches browser tabs

</specifics>

<deferred>
## Deferred Ideas

- **Approval queue diff preview** — Show what exactly will change (rows added/removed/edited) for pending requests. Data exists in payload but rendering is a new feature capability. Future phase
- **Keyboard accessibility** — Tab navigation, focus management, keyboard shortcuts for approve/reject. Important for production quality. Phase 8 or dedicated accessibility phase
- **Full responsive design** — CP tables on mobile/tablet. Phase 8 (Splunkbase readiness). Minimal `overflow-x: auto` added in Phase 6

</deferred>

---

*Phase: 06-admin-panel*
*Context gathered: 2026-04-02*
