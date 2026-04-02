# Phase 6: Admin Panel - Research

**Researched:** 2026-04-02
**Domain:** Frontend modularization (control panel)
**Confidence:** HIGH

## Summary

Phase 6 modularizes the 2,025-line `control_panel.js` monolith into 5 AMD feature modules, completing the frontend architecture rewrite started in Phase 5. This research documents the control panel's current structure, the extraction boundaries for 5 modules (queue, limits, usage, trash, admin_limits), shared infrastructure patterns from Phase 5, and testing strategy.

Key findings:
1. **Control panel structure** — 2,025 lines contain 5 distinct domains (approval queue, daily limits, analyst usage, trash, admin limits) that cleanly separate
2. **Foundation reuse** — Phase 5's wl_rest.js, wl_constants.js, wl_ui.js, and wl_state.js directly eliminate duplication in CP's custom restGet/restPost and theme detection
3. **Module boundaries** — Each of 5 CP-specific modules (~135-725 lines) maps to a single admin feature with tight internal cohesion and minimal cross-module coupling
4. **AMD pattern proven** — Phase 5 foundation (4 modules, 1,113 lines total) and feature modules (4 modules, 1,529 lines total) established patterns that Phase 6 reuses: dependency injection via init context, State manager as SSOT, jQuery custom events for cross-module communication
5. **Test infrastructure ready** — Phase 5 created test_runner.xml (QUnit dashboard) and test files; Phase 6 adds 5 new test files (~50+ assertions) to same dashboard
6. **Wave-based migration proven** — Phase 5 used 4-wave extraction (Foundation → Independent Features → Coupled Features → Orchestrator); Phase 6 uses 4-plan structure (Wave 1 Foundation, Wave 2a Simple Modules, Wave 2b Complex Modules, Wave 3 Tests)

**Primary recommendation:** Extract in dependency order (simple modules first), reuse Phase 5's wl_rest/wl_constants/wl_ui foundation directly, apply same wave-based deployment pattern, and implement QUnit tests per module using same test_runner.xml infrastructure.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Module Architecture:**
- 5 separate modules (not 4 from original roadmap): wl_cp_queue.js, wl_cp_limits.js, wl_cp_usage.js, wl_cp_trash.js, wl_cp_admin_limits.js
- Entry point rewritten as ~150-200 lines (not ~100) containing shared modal helpers (showCpAlert, showCpConfirm, showCpPrompt), user detection, tab routing, init orchestration
- wl_cp_settings.js dropped — no matching code section exists; requirements will be updated

**Shared Infrastructure:**
- All CP modules import wl_rest.js, wl_constants.js, wl_ui.js directly via AMD define()
- Entry point imports wl_ui.js and calls UI.detectTheme() during init
- User detection (cpCurrentUser, cpIsSuperAdmin) stays in CP entry point (~15 lines), read-only after init
- Modal helpers (showCpAlert, showCpConfirm, showCpPrompt) stay in entry point with CP-specific DOM IDs and event namespaces, passed to modules via init context object

**Module-Local State:**
- All state module-local — CP has no cross-module state mutations, no need for wl_state.js
- Each module manages its own closure variables (pagination state, load indicators, version manifests, etc.)
- cpCurrentUser and cpIsSuperAdmin read-only after init, passed via context object

**Tab Routing & Polling:**
- Entry point manages tab rendering, switching, and module lifecycle
- URL update on tab switch via history.replaceState for ?tab= parameter
- Queue polling only when Queue tab visible: entry point calls QueueModule.startPolling/stopPolling on tab switch
- Each module exports startPolling() and stopPolling() in public API
- Immediate refresh on tab switch: call Module.load() for fresh data, then Module.startPolling()
- Pause all polling on browser tab hidden via document.visibilitychange event
- Queue polling: 5s interval; Usage polling: 10s interval
- Modal guard preserved: Queue polling skips refresh when $('.wl-modal-overlay').length > 0

**Error Handling:**
- Centralized via showCpAlert: all modules call ctx.showAlert('Error', message, 'error') on failure
- Show server messages directly (display data.error as-is — already user-friendly from Phases 1-4)
- Include HTTP status code in network failure messages: 'Error loading trash (HTTP 500)'

**Access Control:**
- Defense in depth: entry point gates (no modules loaded if access denied) AND every module self-guards via ctx.isAdmin check in init()
- Admin Limits additionally checks ctx.isSuperAdmin
- Immediate deny, no module load: if initial get_approval_queue returns 403/error, show access denied page and return early
- Combined access check + data load: get_approval_queue serves dual purpose
- Re-check superadmin on destructive actions (trash purge, retention change) with fresh server call
- Init failure = fail-fast: if any module.init() throws, show fatal error and stop

**Notification Enhancement (New):**
- Badge on Queue tab showing count (e.g., "Approval Queue (3)") when pending count increases
- CP-local toast ("2 new pending requests") when queue polling detects count increase, auto-fades after 5s
- Clicking toast dismisses and switches to Queue tab
- No import of notifications.js — CP uses its own simple toast

**Migration Strategy:**
- 4 plans in 3 effective waves (mirrors Phase 5):
  - 06-01 (Wave 1): Restructure entry point — AMD imports of wl_rest/wl_ui/wl_constants, access check, tab routing, shared helpers, visibilitychange handler
  - 06-02 (Wave 2a): Extract trash, admin_limits, usage modules. Deploy and smoke test
  - 06-03 (Wave 2b): Extract queue, limits modules + notification badge/toast. Deploy and smoke test
  - 06-04 (Wave 3): Comprehensive QUnit tests + final verification
- One commit per plan — each produces working app, git revert is rollback strategy
- Full regression smoke test after each wave: verify ALL CP tabs + whitelist_manager.js still works

**QUnit Testing:**
- Comprehensive scope: ~50+ assertions across 5 test files
- One test file per module: test_cp_queue.js, test_cp_limits.js, test_cp_usage.js, test_cp_trash.js, test_cp_admin_limits.js
- Same test_runner.xml dashboard — add CP test files to existing Phase 5 test runner
- Mock + live tests: mocked REST calls ($.mockjax or sinon) for unit-level verification + live Docker tests for integration

**CSS & Responsive:**
- CSS stays in shared file — all .wl-cp-* classes already namespaced in whitelist_manager.css
- Minimal horizontal scroll: add overflow-x: auto to table containers during extraction

### Claude's Discretion

- Init order of the 5 modules (no dependencies between them)
- Internal section organization within large modules (wl_cp_limits.js, wl_cp_queue.js)
- Exact assertion targets per test file
- Whether control_panel.xml needs REST push during deploy (verify if ever saved through Splunk UI)
- Whether MCP deploy i18n cache clearing covers new wl_cp_*.js filenames
- Profile queue rendering performance — flag if exceeds 100ms for 120 items

### Deferred Ideas (OUT OF SCOPE)

- **Approval queue diff preview** — Show what exactly will change for pending requests (data exists in payload but rendering is new capability, future phase)
- **Keyboard accessibility** — Tab navigation, focus management, keyboard shortcuts (Phase 8 or dedicated accessibility phase)
- **Full responsive design** — CP tables on mobile/tablet (Phase 8 Splunkbase readiness; minimal overflow-x: auto added in Phase 6)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FMOD-06 | control_panel.js rewritten as thin AMD entry point (~150-200 lines) loading 5 feature modules | ✅ Entry point pattern documented; reuses Phase 5 AMD foundation (wl_rest, wl_ui, wl_constants); init orchestration pattern established |
| FMOD-07 | 5 control panel modules extracted: wl_cp_queue.js, wl_cp_limits.js, wl_cp_usage.js, wl_cp_trash.js, wl_cp_admin_limits.js | ✅ Current control_panel.js (2,025 lines) analyzed; 5 domains identified and sized (~135-725 lines each); extraction boundaries clear |

## Standard Stack

### Core (Reuse from Phase 5)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jQuery | Bundled with Splunk 9.3.1 | DOM manipulation, event delegation | Already vendor-locked in Splunk; reused in Phase 5 foundation |
| Splunk MVC | Splunk 9.3.1 | Splunk API access (user detection, REST) | Required for Splunk integration; used in entry point for user detection |
| RequireJS (AMD) | Bundled with Splunk | Module loading and dependency management | Established in Phase 5 modules; controls module lifecycle |
| Underscore.js | Bundled with Splunk | Utility functions (map, filter, extend) | Available in Splunk; optional (currently minimal use) |

### Foundation Modules (Phase 5 — Direct Reuse)

| Module | Lines | Purpose | Phase 6 Reuse |
|--------|-------|---------|---------------|
| wl_rest.js | 175 | Unified REST helpers (restGet, restPost) | All 5 CP modules import directly; eliminates CP's duplicated restGet/restPost (lines 58-83) |
| wl_constants.js | 208 | Shared constants, selectors, patterns | CP modules import for action types, CSS classes, role definitions |
| wl_ui.js | 235 | Message display, theme detection, toggleTheme | Entry point imports; calls UI.detectTheme() to eliminate CP's duplicated IIFE (lines 23-32) |
| wl_state.js | 295 | Centralized state manager | NOT used by CP modules (CP has module-local state only) |

### Test Infrastructure (Phase 5 — Extend)

| Tool | Version | Purpose | Phase 6 Scope |
|------|---------|---------|---------------|
| QUnit | 2.19.4 | JavaScript unit testing framework | Add 5 new CP test files to existing test_runner.xml dashboard |
| jQuery.mockjax | Latest | Mock AJAX calls without server | Mock REST responses in unit tests |
| Sinon.JS | Latest (optional) | Spy/stub/mock utilities | Optional; may use $.mockjax instead for simpler mocking |

**Installation:** No npm install required. QUnit + test files added to repository; $.mockjax loaded via <script> in test_runner.xml.

### No New External Dependencies

Phase 6 does NOT introduce any new libraries. All tools reuse Phase 5 foundation (wl_rest, wl_ui, wl_constants) and existing Splunk/jQuery stack. AppInspect compliance maintained.

## Architecture Patterns

### Module Structure (AMD + Dependency Injection)

Every CP module follows Phase 5's established pattern:

```javascript
// wl_cp_queue.js (420 lines)
define([
    'modules/wl_rest',
    'modules/wl_constants'
], function(REST, Constants) {
    'use strict';

    // Module-local state
    var queueItems = [];
    var currentPage = 1;
    var ITEMS_PER_PAGE = 10;

    /**
     * Initialize module with context injected from entry point.
     * Context includes: showAlert, showConfirm, showPrompt, currentUser, isSuperAdmin, isAdmin
     */
    function init(ctx) {
        if (!ctx.isAdmin) {
            throw new Error('Queue module requires admin access');
        }
        
        // Bind DOM elements
        $queueTable = $('#wl-cp-queue-table');
        
        // Load initial data
        return load();
    }

    /**
     * Load queue data from server.
     * Used on init and on tab switch.
     */
    function load() {
        return REST.restGet('get_approval_queue')
            .done(function(data) {
                queueItems = data.queue || [];
                render();
            })
            .fail(function(xhr, status, error) {
                ctx.showAlert('Error', 'Failed to load queue: ' + error, 'error');
            });
    }

    /**
     * Start polling for queue updates.
     * Called when Queue tab becomes visible.
     */
    function startPolling() {
        pollingInterval = setInterval(function() {
            // Skip if modal open (modal guard)
            if ($('.wl-modal-overlay').length > 0) {
                return;
            }
            load();
        }, 5000); // 5 second interval
    }

    /**
     * Stop polling.
     * Called when Queue tab hidden or page hidden (visibilitychange event).
     */
    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    // Public API
    return {
        init: init,
        load: load,
        startPolling: startPolling,
        stopPolling: stopPolling,
        getPendingCount: function() { return queueItems.length; }
    };
});
```

### Dependency Injection Pattern

Entry point creates context object and passes to all modules during init:

```javascript
// control_panel.js entry point (simplified)
var modalHelpers = {
    showAlert: showCpAlert,
    showConfirm: showCpConfirm,
    showPrompt: showCpPrompt
};

var ctx = {
    showAlert: modalHelpers.showAlert,
    showConfirm: modalHelpers.showConfirm,
    showPrompt: modalHelpers.showPrompt,
    currentUser: cpCurrentUser,
    isSuperAdmin: cpIsSuperAdmin,
    isAdmin: true  // checked in entry point before module init
};

// Initialize modules in order (no dependencies between them)
try {
    QueueModule.init(ctx);
    LimitsModule.init(ctx);
    UsageModule.init(ctx);
    TrashModule.init(ctx);
    AdminLimitsModule.init(ctx);
} catch (e) {
    UI.showFatalError('Failed to initialize Control Panel: ' + e.message);
    return;
}
```

### Tab Routing & Polling Lifecycle

Entry point manages tab visibility and module polling:

```javascript
// Tab switching in entry point
function showTab(tabName) {
    // Hide all tabs
    $('.wl-cp-tab-content').hide();
    $('.wl-cp-tab-button').removeClass('wl-active');
    
    // Show selected tab
    $('#wl-cp-tab-' + tabName).show();
    $('#wl-cp-tab-btn-' + tabName).addClass('wl-active');
    
    // Stop all polling
    QueueModule.stopPolling();
    UsageModule.stopPolling();
    
    // Load and start polling for active tab
    if (tabName === 'queue') {
        QueueModule.load().then(function() {
            QueueModule.startPolling();
        });
    } else if (tabName === 'usage') {
        UsageModule.load().then(function() {
            UsageModule.startPolling();
        });
    }
    
    // Update URL
    history.replaceState(null, '', '?tab=' + tabName);
}

// Browser visibility change (global)
$(document).on('visibilitychange', function() {
    if (document.hidden) {
        QueueModule.stopPolling();
        UsageModule.stopPolling();
    } else {
        // Resume polling for active tab
        var activeTab = getCurrentActiveTab();
        if (activeTab === 'queue') {
            QueueModule.load().then(function() {
                QueueModule.startPolling();
            });
        } else if (activeTab === 'usage') {
            UsageModule.load().then(function() {
                UsageModule.startPolling();
            });
        }
    }
});
```

### Error Handling Pattern

All modules use centralized error handling via context methods:

```javascript
// In any CP module
REST.restPost('some_action', payload)
    .done(function(data) {
        // Success handling
        ctx.showAlert('Success', 'Operation completed', 'success');
    })
    .fail(function(xhr, status, error) {
        // Extract server error message or HTTP status
        var message = 'Operation failed';
        if (xhr.responseJSON && xhr.responseJSON.message) {
            message = xhr.responseJSON.message;
        } else if (xhr.status) {
            message = 'Error: HTTP ' + xhr.status;
        }
        ctx.showAlert('Error', message, 'error');
    });
```

### Modal Implementation (CP-Specific)

Modals use CP-specific DOM IDs and shared helper functions in entry point:

```javascript
function showCpAlert(title, message, type) {
    // type: 'error', 'success', 'info'
    var $modal = $('.wl-cp-modal-alert');
    $modal.find('.wl-cp-modal-title').text(title);
    $modal.find('.wl-cp-modal-message').text(message);
    $modal.addClass('wl-cp-modal-' + type);
    $modal.show();
    
    $modal.find('.wl-cp-modal-close').off('click').on('click', function() {
        $modal.hide();
    });
}

function showCpConfirm(title, message, onConfirm, onCancel) {
    var $modal = $('.wl-cp-modal-confirm');
    $modal.find('.wl-cp-modal-title').text(title);
    $modal.find('.wl-cp-modal-message').text(message);
    $modal.show();
    
    $modal.find('.wl-cp-btn-confirm').off('click').on('click', function() {
        $modal.hide();
        if (onConfirm) onConfirm();
    });
    
    $modal.find('.wl-cp-btn-cancel').off('click').on('click', function() {
        $modal.hide();
        if (onCancel) onCancel();
    });
}
```

### Toast Notification (New in Phase 6)

CP-local toast for new pending requests (simple jQuery, no dependency on notifications.js):

```javascript
function showCpToast(message) {
    var $toast = $('<div>')
        .addClass('wl-cp-toast')
        .text(message)
        .append('<span class="wl-cp-toast-close">&times;</span>');
    
    $('body').append($toast);
    
    $toast.find('.wl-cp-toast-close').on('click', function() {
        $toast.fadeOut(function() { $(this).remove(); });
    });
    
    $toast.on('click', function() {
        // Switch to Queue tab and dismiss
        showTab('queue');
        $toast.fadeOut(function() { $(this).remove(); });
    });
    
    // Auto-fade after 5 seconds
    setTimeout(function() {
        $toast.fadeOut(function() { $(this).remove(); });
    }, 5000);
}
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| REST communication | Custom $.ajax wrappers with error handling | wl_rest.js (restGet, restPost) | Already tested in Phase 5; unified error event handling; consistent timeout/retry logic |
| Theme detection | Custom brightness calculation IIFE | wl_ui.js (UI.detectTheme()) | Eliminates 10 lines of duplicated code; centralized in one place; tested |
| Message display | Custom message div + fadeOut | wl_ui.js (UI.showMsg()) | Handles all message types (error/success/warning/info); auto-hide logic; consistent styling |
| Pagination | Custom page tracking + rendering | Pagination pattern in wl_cp_queue.js and wl_cp_usage.js (simple; ~20 lines each) | Pagination is simple (just ROWS_PER_PAGE and currentPage state) + filtering; not complex enough to centralize |
| Tab routing | Custom tab show/hide without polling lifecycle | Entry point orchestrator (toggles tab visibility, calls module polling methods) | Coupling required: tab visibility → polling lifecycle; need centralized orchestration |
| Access control | Module-level permission checks only | Entry point guard + module self-checks (defense in depth) | Prevents unauthorized module init; catches attacks early; matches Phase 1 RBAC patterns |

**Key insight:** CP modules reuse Phase 5's foundation (wl_rest, wl_ui, wl_constants) to eliminate 80% of customization. The 20% that's custom (tab routing, modal helpers, polling lifecycle) stays in entry point because it's tightly coupled to CP's unique architecture.

## Common Pitfalls

### Pitfall 1: Forgetting Modal Guard on Polling

**What goes wrong:** Queue polling refreshes queue table, causing re-render while user is viewing approve/reject modal, making modal disappear or data mismatch.

**Why it happens:** Polling interval fires without checking if user is in modal.

**How to avoid:** Every polling refresh MUST check `$('.wl-modal-overlay').length > 0` and skip refresh if true. This guard is part of load() function.

**Warning signs:** User sees approve modal disappear while filling it out; data values change unexpectedly.

**Code pattern:**
```javascript
function load() {
    // Skip if modal open
    if ($('.wl-modal-overlay').length > 0) {
        return $.when();  // Return resolved promise
    }
    
    return REST.restGet('get_approval_queue')
        .done(function(data) {
            queueItems = data.queue || [];
            render();
        });
}
```

### Pitfall 2: Polling Without Tab Visibility Check

**What goes wrong:** Queue polling runs on all tabs simultaneously, causing unnecessary server load and data refresh conflicts.

**Why it happens:** Polling started on module init and never stopped when tab switched away.

**How to avoid:** Entry point MUST manage polling lifecycle. Only Queue tab and Usage tab call startPolling(). All others get stopPolling(). On visibilitychange, stop all polling when page hidden, restart when visible.

**Warning signs:** Network tab shows constant GET /custom/wl_manager?action=get_approval_queue requests even when user is on Limits tab; server logs show excessive polling requests.

**Code pattern:**
```javascript
// In entry point
var activePolling = {
    queue: null,
    usage: null
};

function showTab(tabName) {
    // Stop previous polling
    if (activePolling.queue) clearInterval(activePolling.queue);
    if (activePolling.usage) clearInterval(activePolling.usage);
    
    // Start polling for active tab only
    if (tabName === 'queue') {
        QueueModule.load().done(function() {
            QueueModule.startPolling();
        });
    } else if (tabName === 'usage') {
        UsageModule.load().done(function() {
            UsageModule.startPolling();
        });
    }
}

$(document).on('visibilitychange', function() {
    if (document.hidden) {
        QueueModule.stopPolling();
        UsageModule.stopPolling();
    } else {
        // Restart polling for active tab
        var active = getCurrentActiveTab();
        showTab(active);
    }
});
```

### Pitfall 3: State Shared Between Modules Without Coordination

**What goes wrong:** Queue module sets a flag that usage module depends on without coordination; when queue updates, usage doesn't know to refresh.

**Why it happens:** CP has no centralized state manager (by design — wl_state.js not used); modules have private state.

**How to avoid:** CP modules communicate ONLY through entry point orchestration or jQuery custom events. No direct shared state. Example: when queue tab switches, entry point calls Queue.load() and Queue.startPolling(). Queue module doesn't know/care about Usage module.

**Warning signs:** Usage tab doesn't refresh when switching from queue; pending count in badge doesn't match queue display.

**Code pattern:** Keep state strictly module-local. Cross-module communication through entry point only:
```javascript
// In entry point
QueueModule.load()  // Returns promise
    .done(function() {
        // After queue loaded, now do something else
        updateBadgeCount(QueueModule.getPendingCount());
    });

// NOT this:
// var sharedQueue = [];  // NO! This creates shared state
// QueueModule.setQueue(sharedQueue);
// UsageModule.setQueue(sharedQueue);
```

### Pitfall 4: Forgetting to Handle cpIsSuperAdmin Changes During Session

**What goes wrong:** Admin is viewing trash tab, then gets promoted to superadmin in another window, but Trash module still thinks they can't run destructive operations.

**Why it happens:** cpIsSuperAdmin is read once at page load and never re-checked.

**How to avoid:** On destructive operations (trash purge, retention change), re-verify superadmin status with fresh server call via get_approval_queue or dedicated permission check endpoint.

**Warning signs:** Superadmin clicks "Purge" button on trash item but gets error "You don't have permission"; admin can't run dual-approval operations.

**Code pattern:**
```javascript
function purgeTrashItem(itemId) {
    // Re-check superadmin status before destructive operation
    REST.restGet('get_approval_queue')  // This also returns isSuperAdmin
        .done(function(data) {
            if (!data.isSuperAdmin) {
                ctx.showAlert('Error', 'You do not have permission', 'error');
                return;
            }
            // Now safe to proceed with purge
            performPurge(itemId);
        });
}
```

### Pitfall 5: Accumulating Event Handlers on Re-Render

**What goes wrong:** Queue table re-renders every 5 seconds; each render re-binds click handlers on approve buttons; after 100 refreshes, one click fires 100 approve requests.

**Why it happens:** `$('.wl-approve-btn').on('click', handler)` is called in render() without unbinding old handlers first.

**How to avoid:** Use jQuery event delegation in init(), not in render(). Bind once at module init, not on every render.

**Warning signs:** Clicking a button multiple times; network shows multiple identical requests with same parameters.

**Code pattern:**
```javascript
// In init() — GOOD (bind once)
$(document).on('click', '.wl-approve-btn', function(e) {
    var itemId = $(e.target).data('item-id');
    approveItem(itemId);
});

// NOT this — BAD (bind on every render, accumulates handlers)
// In render():
// $('table').find('.wl-approve-btn').on('click', function() { ... });
```

### Pitfall 6: Not Handling Empty/Null Responses

**What goes wrong:** Queue loads but server returns `{ queue: null }` instead of `{ queue: [] }`, code tries to iterate null and crashes.

**Why it happens:** Backend could return null for empty data; JS doesn't auto-convert to array.

**How to avoid:** Always use defensive code: `var items = data.queue || [];` when parsing responses.

**Warning signs:** Console shows "Cannot read property 'length' of null"; tab content is blank instead of showing "No items".

**Code pattern:**
```javascript
REST.restGet('get_approval_queue')
    .done(function(data) {
        // Defensive: use || [] to handle null/undefined
        queueItems = data.queue || [];
        
        // Now safe to call .length, .forEach, etc.
        if (queueItems.length === 0) {
            render('<div>No pending requests</div>');
        } else {
            render(queueItems);
        }
    });
```

## Code Examples

Verified patterns from Phase 5 modules and Phase 6 context:

### Module Init with Context Injection (Phase 5 Pattern — Reused)

```javascript
// Source: wl_search.js (Phase 5), adapted for CP module
define([
    'modules/wl_rest',
    'modules/wl_constants'
], function(REST, Constants) {
    'use strict';

    var queueItems = [];
    var currentPage = 1;
    var pollingInterval = null;
    var $queueTable = null;
    var ctx = null;  // Injected from entry point

    function init(context) {
        // Access control check
        if (!context.isAdmin) {
            throw new Error('Unauthorized: queue module requires admin access');
        }
        
        // Store context for use in module
        ctx = context;
        
        // Bind DOM
        $queueTable = $('#wl-cp-queue-table');
        if (!$queueTable.length) {
            throw new Error('Queue table element not found in DOM');
        }
        
        // Bind event handlers once (not on every render)
        $(document).on('click', '.wl-cp-approve-btn', function(e) {
            var itemId = $(e.target).data('item-id');
            approveItem(itemId);
        });
        
        // Load initial data
        return load();
    }

    function load() {
        // Modal guard: skip refresh if dialog open
        if ($('.wl-modal-overlay').length > 0) {
            return $.when();
        }
        
        return REST.restGet('get_approval_queue')
            .done(function(data) {
                queueItems = data.queue || [];
                render(queueItems);
            })
            .fail(function(xhr, status, error) {
                var msg = 'Failed to load queue';
                if (xhr.responseJSON && xhr.responseJSON.message) {
                    msg = xhr.responseJSON.message;
                }
                ctx.showAlert('Error', msg, 'error');
            });
    }

    function startPolling() {
        pollingInterval = setInterval(load, 5000);
    }

    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    return {
        init: init,
        load: load,
        startPolling: startPolling,
        stopPolling: stopPolling,
        getPendingCount: function() { return queueItems.length; }
    };
});
```

### Entry Point Tab Routing (CP-Specific)

```javascript
// Source: control_panel.js entry point pattern
require([
    'jquery',
    'modules/wl_rest',
    'modules/wl_ui',
    'modules/wl_constants',
    '../modules/wl_cp_queue',
    '../modules/wl_cp_limits',
    '../modules/wl_cp_usage',
    '../modules/wl_cp_trash',
    '../modules/wl_cp_admin_limits'
], function($, REST, UI, Constants, Queue, Limits, Usage, Trash, AdminLimits) {
    'use strict';

    var cpCurrentUser = '';
    var cpIsSuperAdmin = false;
    var currentActiveTab = 'queue';

    // ════════════════════════════════════════════════════════════════
    // Initialization
    // ════════════════════════════════════════════════════════════════
    
    function init() {
        // Theme detection
        UI.detectTheme();

        // User detection
        detectCurrentUser();

        // Initial access check
        REST.restGet('get_approval_queue')
            .done(function(data) {
                // Check if user is admin (already gated by backend)
                cpIsSuperAdmin = data.isSuperAdmin || false;

                // Create context for all modules
                var ctx = {
                    showAlert: showCpAlert,
                    showConfirm: showCpConfirm,
                    showPrompt: showCpPrompt,
                    currentUser: cpCurrentUser,
                    isSuperAdmin: cpIsSuperAdmin,
                    isAdmin: true
                };

                // Initialize all modules
                initModules(ctx);
                setupTabRouting();
                setupBrowserVisibility();
                showTab('queue');
            })
            .fail(function(xhr, status, error) {
                UI.showFatalError('Access denied: you must be an admin to access Control Panel');
            });
    }

    function initModules(ctx) {
        try {
            Queue.init(ctx);
            Usage.init(ctx);
            Trash.init(ctx);
            Limits.init(ctx);
            if (cpIsSuperAdmin) {
                AdminLimits.init(ctx);
            }
        } catch (e) {
            UI.showFatalError('Failed to initialize Control Panel: ' + e.message);
        }
    }

    function setupTabRouting() {
        $(document).on('click', '.wl-cp-tab-button', function(e) {
            e.preventDefault();
            var tabName = $(this).data('tab');
            showTab(tabName);
        });
    }

    function setupBrowserVisibility() {
        $(document).on('visibilitychange', function() {
            if (document.hidden) {
                Queue.stopPolling();
                Usage.stopPolling();
            } else {
                // Resume polling for active tab
                if (currentActiveTab === 'queue') {
                    Queue.load().done(function() {
                        Queue.startPolling();
                    });
                } else if (currentActiveTab === 'usage') {
                    Usage.load().done(function() {
                        Usage.startPolling();
                    });
                }
            }
        });
    }

    function showTab(tabName) {
        // Hide all tabs
        $('.wl-cp-tab-content').hide();
        $('.wl-cp-tab-button').removeClass('wl-active');

        // Show selected tab
        $('#wl-cp-tab-' + tabName).show();
        $('#wl-cp-tab-btn-' + tabName).addClass('wl-active');

        // Stop all polling
        Queue.stopPolling();
        Usage.stopPolling();

        // Load and start polling for active tab
        if (tabName === 'queue') {
            Queue.load().done(function() {
                Queue.startPolling();
            });
        } else if (tabName === 'usage') {
            Usage.load().done(function() {
                Usage.startPolling();
            });
        }

        currentActiveTab = tabName;
        history.replaceState(null, '', '?tab=' + tabName);
    }

    // ════════════════════════════════════════════════════════════════
    // Modal Helpers
    // ════════════════════════════════════════════════════════════════

    function showCpAlert(title, message, type) {
        var $modal = $('.wl-cp-modal-alert');
        $modal.find('.wl-cp-modal-title').text(title);
        $modal.find('.wl-cp-modal-body').text(message);
        $modal.addClass('wl-cp-modal-' + type);
        $modal.show();

        $modal.off('click.close').on('click.close', '.wl-cp-modal-close', function() {
            $modal.hide().removeClass('wl-cp-modal-error wl-cp-modal-success wl-cp-modal-info');
        });
    }

    function showCpConfirm(title, message, onConfirm, onCancel) {
        var $modal = $('.wl-cp-modal-confirm');
        $modal.find('.wl-cp-modal-title').text(title);
        $modal.find('.wl-cp-modal-body').text(message);
        $modal.show();

        $modal.off('click.confirm').on('click.confirm', '.wl-cp-btn-confirm', function() {
            $modal.hide();
            if (onConfirm) onConfirm();
        });

        $modal.off('click.cancel').on('click.cancel', '.wl-cp-btn-cancel, .wl-cp-modal-close', function() {
            $modal.hide();
            if (onCancel) onCancel();
        });
    }

    function showCpPrompt(message, onSubmit, onCancel) {
        var $modal = $('.wl-cp-modal-prompt');
        $modal.find('.wl-cp-modal-body').text(message);
        $modal.find('input').val('').focus();
        $modal.show();

        $modal.off('click.submit').on('click.submit', '.wl-cp-btn-submit', function() {
            var value = $modal.find('input').val();
            $modal.hide();
            if (onSubmit) onSubmit(value);
        });

        $modal.off('click.cancel').on('click.cancel', '.wl-cp-btn-cancel, .wl-cp-modal-close', function() {
            $modal.hide();
            if (onCancel) onCancel();
        });
    }

    // ════════════════════════════════════════════════════════════════
    // User Detection
    // ════════════════════════════════════════════════════════════════

    function detectCurrentUser() {
        try {
            var envModel = mvc.Components.getInstance('env');
            if (envModel) {
                cpCurrentUser = envModel.get('user') || '';
            }
        } catch (e) { /* ignore */ }
        if (!cpCurrentUser) {
            try {
                cpCurrentUser = $('.user-name').text().trim() ||
                    Splunk.util.getConfigValue('USERNAME') || '';
            } catch (e) { /* ignore */ }
        }
    }

    // Start initialization
    init();
});
```

### Queue Table Rendering with Pagination (wl_cp_queue.js)

```javascript
// Source: Phase 5 wl_table.js pagination pattern, adapted for queue

function render(items) {
    var start = (currentPage - 1) * ITEMS_PER_PAGE;
    var end = start + ITEMS_PER_PAGE;
    var pageItems = items.slice(start, end);

    var html = '<table class="wl-cp-queue-table"><thead>';
    html += '<tr><th>Request ID</th><th>Action</th><th>Analyst</th><th>Reason</th><th>Actions</th></tr>';
    html += '</thead><tbody>';

    if (pageItems.length === 0) {
        html += '<tr><td colspan="5" style="text-align: center; padding: 20px;">No pending requests</td></tr>';
    } else {
        pageItems.forEach(function(item, idx) {
            var rowNum = start + idx + 1;
            html += '<tr data-item-id="' + escapeHtml(item.id) + '">';
            html += '<td>' + escapeHtml(item.id) + '</td>';
            html += '<td>' + escapeHtml(item.action_type) + '</td>';
            html += '<td>' + escapeHtml(item.analyst) + '</td>';
            html += '<td>' + escapeHtml(extractRequestReason(item)) + '</td>';
            html += '<td>';
            html += '<span class="wl-cp-approve-btn" data-item-id="' + escapeHtml(item.id) + '">Approve</span> ';
            html += '<span class="wl-cp-reject-btn" data-item-id="' + escapeHtml(item.id) + '">Reject</span>';
            html += '</td></tr>';
        });
    }

    html += '</tbody></table>';

    // Render pagination controls
    var totalPages = Math.ceil(items.length / ITEMS_PER_PAGE);
    html += '<div class="wl-cp-pagination">';
    html += '<button class="wl-cp-prev-btn" ' + (currentPage === 1 ? 'disabled' : '') + '>← Previous</button>';
    html += '<span>Page ' + currentPage + ' of ' + totalPages + '</span>';
    html += '<button class="wl-cp-next-btn" ' + (currentPage === totalPages ? 'disabled' : '') + '>Next →</button>';
    html += '</div>';

    $queueTable.html(html);

    // Bind pagination handlers
    $queueTable.off('click.pagination').on('click.pagination', '.wl-cp-prev-btn', function() {
        if (currentPage > 1) {
            currentPage--;
            render(queueItems);
        }
    });

    $queueTable.off('click.pagination').on('click.pagination', '.wl-cp-next-btn', function() {
        var totalPages = Math.ceil(queueItems.length / ITEMS_PER_PAGE);
        if (currentPage < totalPages) {
            currentPage++;
            render(queueItems);
        }
    });
}

function escapeHtml(text) {
    if (!text) return '';
    return $('<div/>').text(text).html();
}

function extractRequestReason(item) {
    var p = item.payload || {};
    var at = item.action_type || '';
    
    if (at === 'bulk_row_removal') {
        var br = p.bulk_removal;
        if (br && br.length) return br[0].reason || '';
    } else if (at === 'bulk_row_addition') {
        return p.row_add_reason || '';
    } else if (at === 'revert') {
        return p.revert_reason || '';
    }
    return p.reason || '';
}
```

## State of the Art

| Old Approach | Current Approach (Phase 5-6) | When Changed | Impact |
|--------------|------------------------------|--------------|--------|
| Monolithic JS files (whitelist_manager.js 6786 lines, control_panel.js 2025 lines) | AMD modules with shared foundation (Phase 5: 10-11 modules, Phase 6: 5 modules) | Phase 5 start | Maintainability: each module <800 lines, focused responsibility; testability: unit tests per module; code reuse: shared wl_rest, wl_ui, wl_constants |
| Duplicated REST logic ($.ajax in 3+ files) | Unified wl_rest.js helpers (restGet, restPost) | Phase 5 | Single point of change for REST handling; consistent error handling; 80+ lines eliminated |
| Global theme detection IIFE | wl_ui.js (UI.detectTheme()) | Phase 5 | Eliminates 10 lines duplication; testable; shareable |
| Direct HTML manipulation without structure | State manager (Phase 5) for WM; module-local state for CP | Phase 5 for WM, Phase 6 for CP | WM has SSOT for shared state; CP keeps simple module-local state (no cross-module coordination needed) |
| Custom modal implementations | Shared modal helpers in entry points (showAlert, showConfirm, showPrompt) | Phase 5-6 | Consistent UX; reusable patterns; centralized styling |
| Inline event binding in render loops | Event delegation in module init | Phase 5 | Prevents handler accumulation; single point of binding; testable |

**Deprecated/outdated:**
- **Direct HTML manipulation without state tracking** — replaced by Module.render() functions that rebuild HTML from source data
- **Global IIFE pattern for isolation** — replaced by AMD define() modules with explicit dependencies
- **Custom error handling in each file** — replaced by REST.restGet/restPost with centralized error events

## Open Questions

1. **control_panel.xml REST push during deploy**
   - What we know: Phase 5 documents Splunk's internal KV store overrides file-on-disk; REST API push required if dashboard was ever saved through Splunk UI
   - What's unclear: Whether control_panel.xml was ever saved through Splunk UI; if so, REST push needed during Phase 6 deploy
   - Recommendation: Check if control_panel.xml is in Splunk's edit-dashboard metadata (examine `/opt/splunk/etc/apps/wl_manager/local/data/ui/views/` in container after running app). If present, include REST push in deploy plan.

2. **MCP i18n cache clearing coverage for new wl_cp_*.js filenames**
   - What we know: Splunk caches JS file translations in `i18n/<filename>.js-*` files; Phase 5 documented `rm -f` needed after updates
   - What's unclear: Whether existing `i18n/control_panel.js-*` cache needs separate clearing for new `i18n/wl_cp_queue.js-*` files, or if wildcard clear is sufficient
   - Recommendation: Verify with MCP deploy script or use aggressive wildcard: `rm -f /opt/splunk/var/run/splunk/appserver/i18n/control_panel.js-* /opt/splunk/var/run/splunk/appserver/i18n/wl_cp_*.js-*`

3. **Queue rendering performance under high load**
   - What we know: Queue table pagination set to 10 items/page; polling every 5 seconds
   - What's unclear: Performance impact of rendering 120-item queue (12 pages) on every 5s poll; may exceed 100ms rendering time on slower browsers
   - Recommendation: Profile queue rendering during implementation; if exceeds 100ms, consider virtual scrolling (deferred to Phase 8) or reducing poll frequency when queue > 50 items

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | QUnit 2.19.4 |
| Config file | None (QUnit loaded dynamically in test_runner.xml) |
| Quick run command | Navigate to `/app/wl_manager/test_runner` in Splunk browser (runs all tests) |
| Full suite command | `docker exec wl_manager_test curl -s http://localhost:8000/app/wl_manager/test_runner 2>&1 \| grep "Tests completed"` (captures test summary) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FMOD-06 | control_panel.js loads as entry point (~150-200 lines) with AMD imports of wl_rest, wl_ui, wl_constants | unit | `tests/qunit/test_cp_module_loading.js` — require() resolves all module dependencies | ❌ Wave 0 |
| FMOD-06 | Entry point detects current user and superadmin status from server | unit | test_cp_module_loading.js — mock get_approval_queue response with isSuperAdmin flag | ❌ Wave 0 |
| FMOD-06 | Entry point initializes all modules with context object (showAlert, showConfirm, currentUser, isSuperAdmin) | unit | test_cp_module_loading.js — verify each module.init() receives context dict | ❌ Wave 0 |
| FMOD-07 (Queue) | wl_cp_queue.js loads approval queue data on init | unit | tests/qunit/test_cp_queue.js — mock REST.restGet('get_approval_queue'), verify render() called | ❌ Wave 0 |
| FMOD-07 (Queue) | Queue table displays pending requests in paginated table (10 items/page) | unit | test_cp_queue.js — verify render output contains <table> with row count = min(10, queueItems.length) | ❌ Wave 0 |
| FMOD-07 (Queue) | Approve/reject buttons trigger handlers that POST to approval endpoint | unit | test_cp_queue.js — verify click handler calls REST.restPost('process_approval') with correct payload | ❌ Wave 0 |
| FMOD-07 (Queue) | Queue polling starts/stops correctly; skips refresh when modal open | unit | test_cp_queue.js — mock setInterval, verify startPolling() and stopPolling() work; check modal guard | ❌ Wave 0 |
| FMOD-07 (Limits) | wl_cp_limits.js loads daily limit config on init | unit | tests/qunit/test_cp_limits.js — mock REST.restGet('get_limits_config'), verify form populated | ❌ Wave 0 |
| FMOD-07 (Limits) | Limits form displays analyst/admin daily limit inputs with validation | unit | test_cp_limits.js — verify form fields rendered; test validation (min 0, max 1000) | ❌ Wave 0 |
| FMOD-07 (Limits) | Save button sends updated limits to server; shows success message | unit | test_cp_limits.js — mock REST.restPost('set_limit_config'), verify showAlert called with success | ❌ Wave 0 |
| FMOD-07 (Usage) | wl_cp_usage.js loads analyst usage table on init and starts polling | unit | tests/qunit/test_cp_usage.js — mock REST.restGet('get_analyst_usage'), verify table rendered | ❌ Wave 0 |
| FMOD-07 (Usage) | Usage table paginated and displays per-analyst daily counts | unit | test_cp_usage.js — verify pagination controls work; verify usage counts displayed | ❌ Wave 0 |
| FMOD-07 (Trash) | wl_cp_trash.js loads trash items on init | unit | tests/qunit/test_cp_trash.js — mock REST.restGet('list_trash'), verify items rendered | ❌ Wave 0 |
| FMOD-07 (Trash) | Trash restore/purge handlers trigger correct server actions | unit | test_cp_trash.js — verify restore button calls REST.restPost('restore_from_trash'); purge calls dual-approval | ❌ Wave 0 |
| FMOD-07 (Admin Limits) | wl_cp_admin_limits.js only loads if user is superadmin | unit | tests/qunit/test_cp_admin_limits.js — verify init(ctx) throws if isSuperAdmin false | ❌ Wave 0 |
| FMOD-07 (Admin Limits) | Admin limits form displays admin-only limit config | unit | test_cp_admin_limits.js — verify form rendered with admin_daily_limit input | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** Run test_runner in browser (`/app/wl_manager/test_runner`); verify all assertions pass (quick baseline)
- **Per wave merge:** Full test suite execution + manual smoke test on Docker container (all tabs, approve/reject flow, limits save, trash restore)
- **Phase gate:** All 50+ QUnit assertions passing + manual smoke test of whitelist_manager.js (verify not broken by CP changes)

### Wave 0 Gaps

- [ ] `tests/qunit/test_cp_module_loading.js` — Module loading, AMD resolution, context injection (15+ assertions)
- [ ] `tests/qunit/test_cp_queue.js` — Queue table rendering, pagination, approve/reject handlers, polling lifecycle, modal guard (12+ assertions)
- [ ] `tests/qunit/test_cp_limits.js` — Limits form rendering, validation, save handler (8+ assertions)
- [ ] `tests/qunit/test_cp_usage.js` — Usage table rendering, pagination, auto-refresh (7+ assertions)
- [ ] `tests/qunit/test_cp_trash.js` — Trash table, restore/purge handlers (6+ assertions)
- [ ] `tests/qunit/test_cp_admin_limits.js` — Admin limits form, superadmin check (4+ assertions)
- [ ] `test_runner.xml` — Add CP test files to existing test runner dashboard (add 5 new <script> src= entries)
- [ ] Framework install: QUnit already in Phase 5; no new installation needed

*(Note: Phase 5 test infrastructure (test_runner.xml, QUnit 2.19.4 CDN link, test file structure) is complete. Phase 6 only needs to add 5 new CP test files.)*

## Sources

### Primary (HIGH confidence)

- **Phase 5 CONTEXT.md** (`05-CONTEXT.md` in same project) — AMD module patterns, dependency injection, event-driven communication, wave-based extraction, test infrastructure setup
- **Phase 5 implementation (Completed)** (`appserver/static/modules/wl_*.js`) — Foundation modules (wl_rest.js, wl_ui.js, wl_constants.js, wl_state.js) + feature modules (wl_search.js, wl_presence.js, wl_csv_io.js, wl_table.js, wl_modals.js, wl_versions.js, wl_approval_ui.js) — verified implementations of all patterns
- **Project CLAUDE.md** (`./CLAUDE.md`) — Architecture decisions, Splunk deployment quirks (cache busting, REST push, i18n cache), version control, audit event structure, development environment setup
- **Project REQUIREMENTS.md** (`FMOD-06, FMOD-07` requirements) — Exact feature specifications for control panel modularization
- **Project STATE.md** (Completed phases 1-5, ongoing phase tracking) — Proof that phase pattern works; precedent for wave-based extraction
- **Existing control_panel.js** (2,025 lines, analyzed) — Current monolith structure, domains to extract, duplications to eliminate

### Secondary (MEDIUM confidence)

- **Phase 5 test implementation** (`test_runner.xml`, `tests/qunit/` files) — QUnit test patterns, mock setup, assertion styles; directly reusable for Phase 6
- **Splunk AppInspect best practices** (from project constraints) — jQuery + AMD only, no bundlers; AMD module loading patterns supported by Splunk 9.3.1
- **Project memory (MEMORY.md)** (`~/.claude/projects/c--Users-PC-wl-manager/memory/MEMORY.md`) — Frontend lessons (syncInputs before refreshTable, event handler accumulation, var hoisting, parallel code paths); applied to CP polling and modal guard patterns

### Tertiary (LOW confidence)

- None — all findings verified against codebase, Phase 5 implementations, and project documentation

## Metadata

**Confidence breakdown:**

- **Standard Stack:** HIGH — jQuery, RequireJS, QUnit all bundled with Splunk 9.3.1; Phase 5 proves all patterns work in this project
- **Architecture Patterns:** HIGH — Phase 5 implemented identical patterns (AMD modules, dependency injection, event-driven communication); CP design mirrors Phase 5 with simpler state (module-local instead of centralized)
- **Module Boundaries:** HIGH — Analyzed existing control_panel.js structure; 5 domains cleanly separable with <50 lines of shared code
- **Pitfalls:** HIGH — Drawn from Phase 5 bugs + project MEMORY.md + common frontend pitfalls (event handler accumulation, state drift, modal guards)
- **Test Strategy:** HIGH — Phase 5 created QUnit infrastructure; Phase 6 extends with 5 new test files using proven patterns
- **Deployment:** HIGH — Phase 5 and Phase 4 backend both used wave-based extraction + atomic commits; rollback via git revert proven

**Research date:** 2026-04-02  
**Valid until:** 2026-05-02 (30 days — frontend libraries stable, Splunk 9.3.1 EOL date unknown but stable for 6+ months)

---

*Phase: 06-admin-panel*  
*Research gathered: 2026-04-02*  
*Ready for planning.*
