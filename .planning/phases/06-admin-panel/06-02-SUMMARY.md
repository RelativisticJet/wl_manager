---
phase: 06-admin-panel
plan: 02
subsystem: Control Panel Module Extraction
tags:
  - modular-refactoring
  - AMD-modules
  - Wave-2a
dependency_graph:
  provides:
    - wl_cp_trash.js (trash management module)
    - wl_cp_admin_limits.js (superadmin config module)
    - wl_cp_usage.js (analyst tracking module)
    - Updated control_panel.js with module wiring
  requires:
    - Phase 5 modules (wl_rest.js, wl_ui.js, wl_constants.js)
  affects:
    - control_panel.js entry point
    - Tab routing and polling lifecycle
tech_stack:
  added:
    - AMD module pattern for feature extraction
    - Context injection for cross-module communication
    - Module-local state via closures
  patterns:
    - init(ctx) initialization with error handling
    - load() promise-based data fetching
    - startPolling/stopPolling lifecycle methods
key_files:
  created:
    - appserver/static/modules/wl_cp_trash.js (339 lines)
    - appserver/static/modules/wl_cp_admin_limits.js (221 lines)
    - appserver/static/modules/wl_cp_usage.js (341 lines)
  modified:
    - appserver/static/control_panel.js (added require, init, tab routing, visibility handler)
    - default/app.conf (build bump to 489)
decisions: []
metrics:
  total_modules_created: 3
  total_lines_added: 901 (modules) + 122 (entry point)
  completed_date: 2026-04-02T11:57:41Z
  build_number: 489
---

# Phase 6 Plan 2: Trash, Admin Limits, and Usage Module Extraction

Simple modular extraction of 3 independent admin features from control_panel.js monolith.

## Summary

Extracted 3 simpler feature modules (trash, admin limits, usage) using AMD pattern with context injection. Each module manages its own state and provides public API (init, load, startPolling, stopPolling). Wired into control_panel.js entry point with proper tab routing, polling lifecycle, and browser visibility handling.

## Task Completion

### Task 1: Extract wl_cp_trash.js module ✓
**Commit:** 2dc507b

Created 339-line AMD module for trash management:
- Trash table display with pagination (15 items/page)
- Restore item handler with confirmation
- Purge item handler (superadmin)
- Purge all handler (superadmin, dual-approval)
- Retention period change handler (superadmin)
- Module-local state: trashItems, currentPage, totalTrash

Public API:
```javascript
{
    init(ctx),        // Initialize with context injection
    load(),          // Fetch trash items from backend
    startPolling(),  // No-op stub for API consistency
    stopPolling()    // Stop polling (no-op)
}
```

### Task 2: Extract wl_cp_admin_limits.js module ✓
**Commit:** 9d64905

Created 221-line AMD module for superadmin limit configuration:
- Superadmin-only access control (fail-fast in init)
- Form rendering with current/default values
- Change detection (Save button enables only on changes)
- Save with validation (integer check)
- Reset to factory defaults with confirmation
- Module-local state: loadedLimits, currentLimits

Public API:
```javascript
{
    init(ctx),  // Superadmin check + initialization
    load()      // Fetch limits from backend
}
```

No polling (no startPolling/stopPolling) since limits are static until changed by user.

### Task 3: Extract wl_cp_usage.js module ✓
**Commit:** 1302e67

Created 341-line AMD module for analyst usage tracking:
- Usage table display with pagination (20 items/page)
- Row selection with "Select All" checkbox
- Reset selected analysts handler
- Reset all analysts handler with confirmation
- Auto-refresh polling (10-second interval)
- Module-local state: usageItems, currentPage, selectedRowIndices, pollingInterval

Public API:
```javascript
{
    init(ctx),       // Initialize with context injection
    load(),         // Fetch usage data
    startPolling(), // Start 10s auto-refresh interval
    stopPolling()   // Stop polling interval
}
```

### Task 4: Wire Wave 2a modules into control_panel.js ✓
**Commit:** 9aa2281

Updated control_panel.js entry point:
- Added 3 new modules to require() statement (~10 lines)
- Store modules in window scope: `window.TrashModule`, `window.AdminLimitsModule`, `window.UsageModule`
- Initialize all 3 modules with context injection after modal helpers ready
- Updated `showTab()` logic to handle new tabs (usage, trash, admin):
  - Usage tab: load() then startPolling()
  - Trash tab: load() only (no polling)
  - Admin tab: load() only (no polling)
- Updated browser visibility handler: pause usage polling when page hidden, resume when visible

Tab routing matrix:
| Tab | Module | Load | Polling |
|-----|--------|------|---------|
| queue | QueueModule | Yes | Yes (existing) |
| limits | LimitsModule | No | No (existing) |
| usage | UsageModule | Yes | Yes (new) |
| trash | TrashModule | Yes | No (new) |
| admin | AdminLimitsModule | Yes | No (new) |

### Task 5: Bump build number and cache bust ✓
**Commit:** 3a9c860

Incremented build number in default/app.conf from 488 to 489:
- Forces Splunk to clear JS/CSS caches on next restart
- Ensures 3 new modules are loaded fresh

## Verification Results

✓ All 3 module files exist: `wl_cp_trash.js`, `wl_cp_admin_limits.js`, `wl_cp_usage.js`

✓ All 3 modules have correct AMD structure: `define([...], function(...) { ... })`

✓ control_panel.js imports all 3 modules in require() array

✓ control_panel.js initializes all 3 modules with context injection

✓ control_panel.js tab routing includes load/polling calls for each module

✓ Browser visibility handler properly manages usage polling

✓ Build number incremented to 489

## Module Structure Compliance

All modules follow Phase 5 extraction pattern:

1. **AMD define()** with explicit dependencies (jquery, underscore, wl_rest, wl_constants)
2. **Module-local state** via closure variables (no shared state between modules)
3. **init(ctx)** function with:
   - Context injection from entry point
   - DOM reference caching
   - Event handler binding (delegated for re-renders)
   - Initial data load via load()
   - Error handling (fail-fast for superadmin checks)
4. **load()** function returning Promise via REST calls
5. **startPolling/stopPolling** (stubs for modules without polling)
6. **Public API** object with 3-4 exported functions

## Deviations from Plan

None - plan executed exactly as written.

## Testing Strategy

Wave 2a extraction focused on code organization. Functional testing deferred to Wave 3 (06-04-PLAN.md):
- Manual smoke tests: access each tab, verify table rendering, verify data refresh
- Tab navigation: verify switching between tabs works smoothly
- Polling: verify usage tab auto-refreshes when visible
- Visibility: verify polling stops when page hidden
- Browser storage: verify modules persist between tab switches

## Ready for Next Phase

Wave 2a complete. Wave 2b (06-03-PLAN.md) will extract Queue and Limits modules (more complex, with inter-dependencies and approval workflow integration). This plan established the modular pattern and context injection mechanism needed for Wave 2b.

## File Manifest

**Created:**
- appserver/static/modules/wl_cp_trash.js (339 lines, 11KB)
- appserver/static/modules/wl_cp_admin_limits.js (221 lines, 8KB)
- appserver/static/modules/wl_cp_usage.js (341 lines, 13KB)

**Modified:**
- appserver/static/control_panel.js (+122 lines, updated require/init/tab routing)
- default/app.conf (build: 488 → 489)

**Total extraction:** 901 lines of feature code + 122 lines of entry point wiring
