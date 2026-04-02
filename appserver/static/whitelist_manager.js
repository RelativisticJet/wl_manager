/**
 * Whitelist Manager for Splunk — Frontend Entry Point
 *
 * Thin orchestration layer that:
 * 1. Requires all foundation and feature modules in dependency order
 * 2. Initializes modules in correct sequence
 * 3. Handles URL parameter parsing (rule, csv)
 * 4. Wires cross-module event listeners
 * 5. Delegates all business logic to modules and orchestrator
 *
 * All complex workflows (save, load, revert, approval) are handled by
 * wl_orchestrator.js, which coordinates feature modules.
 *
 * This file should remain ~100 lines — only initialization and basic wiring.
 */

/*global require, Splunk */
require([
    // Splunk framework
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "splunkjs/mvc/simplexml/ready!",

    // Wave 1: Foundation layer
    "modules/wl_constants",
    "modules/wl_state",
    "modules/wl_rest",
    "modules/wl_ui",

    // Wave 2: Independent feature modules
    "modules/wl_search",
    "modules/wl_presence",
    "modules/wl_csv_io",

    // Wave 2.5: Coupled feature modules
    "modules/wl_table",
    "modules/wl_modals",
    "modules/wl_versions",
    "modules/wl_approval_ui",

    // Wave 3: Orchestrator
    "modules/wl_orchestrator"

], function ($, _, mvc, utils,
    Constants, State, REST, UI,
    Search, Presence, CsvIO,
    Table, Modals, Versions, ApprovalUI,
    Orchestrator) {
    "use strict";

    try {
        // ══════════════════════════════════════════════════════════════════
        // 1. Initialize State Manager with all application state keys
        // ══════════════════════════════════════════════════════════════════
        State.register('detectionRuleSelected', "", null);
        State.register('csvFileSelected', "", null);
        State.register('appContext', "", null);
        State.register('currentHeaders', [], null);
        State.register('originalHeaders', [], null);
        State.register('currentRows', [], null);
        State.register('originalRows', [], null);
        State.register('expireColumn', "", null);
        State.register('loadedMtime', null, null);
        State.register('csvLocked', false, null);
        State.register('columnWidths', {}, null);
        State.register('pendingApprovalCount', 0, null);

        // ══════════════════════════════════════════════════════════════════
        // 2. Initialize UI with theme detection
        // ══════════════════════════════════════════════════════════════════
        UI.init();

        // ══════════════════════════════════════════════════════════════════
        // 3. Initialize feature modules
        // ══════════════════════════════════════════════════════════════════
        Table.init();
        Modals.init();
        Versions.init();
        ApprovalUI.init();
        Presence.init();
        CsvIO.init();
        Search.init();
        Orchestrator.init();

        // ══════════════════════════════════════════════════════════════════
        // 4. Parse URL parameters and load initial CSV if specified
        // ══════════════════════════════════════════════════════════════════
        (function parseUrlParams() {
            var params = new URLSearchParams(window.location.search);
            var rule = params.get('rule') || params.get('detection_rule') || "";
            var csv = params.get('csv') || params.get('csv_file') || "";
            var app = params.get('app') || params.get('app_context') || "";

            if (rule) {
                State.set('detectionRuleSelected', rule);
            }
            if (csv && rule) {
                State.set('csvFileSelected', csv);
                State.set('appContext', app);
                // Load CSV with all dependencies
                Orchestrator.orchestrateLoadCSV(csv, app, function (success) {
                    if (!success) {
                        UI.showMsg("Failed to load initial CSV.", "error");
                    }
                });
            }
        })();

        // ══════════════════════════════════════════════════════════════════
        // 5. Wire save button → orchestrator
        // ══════════════════════════════════════════════════════════════════
        $(document).on("click", ".wl-save-btn", function () {
            if (State.get('csvLocked')) {
                UI.showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            Orchestrator.orchestrateSaveCSV({}, function (success, data) {
                if (success) {
                    // Success feedback already shown by orchestrator
                } else {
                    // Error feedback already shown by orchestrator
                }
            });
        });

        // ══════════════════════════════════════════════════════════════════
        // 6. Wire revert button → orchestrator
        // ══════════════════════════════════════════════════════════════════
        $(document).on("change", "#wl-revert-select", function () {
            var versionId = $(this).val();
            if (!versionId) return;
            $(this).val(""); // Reset dropdown
            Orchestrator.orchestrateRevertCSV(versionId, function (success) {
                if (!success) {
                    UI.showMsg("Failed to revert to version.", "error");
                }
            });
        });

        // ══════════════════════════════════════════════════════════════════
        // 7. Listen for State changes and update UI
        // ══════════════════════════════════════════════════════════════════
        State.on('state:csvLocked', function (event, oldVal, newVal) {
            if (newVal) {
                UI.showMsg("CSV locked pending approval.", "warning");
            }
        });

        State.on('state:currentRows', function (event, oldVal, newVal) {
            Table.refreshTable();
        });

        // ══════════════════════════════════════════════════════════════════
        // 8. Error handling: catch any module init errors
        // ══════════════════════════════════════════════════════════════════
    } catch (err) {
        console.error("Fatal error initializing Whitelist Manager:", err);
        UI.showFatalError(
            "Failed to initialize application. Check browser console for details."
        );
    }

    // ══════════════════════════════════════════════════════════════════
    // === ALL BUSINESS LOGIC MOVED TO FEATURE MODULES AND ORCHESTRATOR ===
    // ══════════════════════════════════════════════════════════════════
});
