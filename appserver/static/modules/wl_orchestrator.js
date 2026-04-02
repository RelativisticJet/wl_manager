/**
 * wl_orchestrator.js — Cross-module workflow orchestration
 *
 * Coordinates complex workflows that span multiple feature modules:
 * - Save CSV (with approval gate checking and conflict resolution)
 * - Load CSV (with all dependencies: versions, column widths, etc.)
 * - Revert to version
 * - Approval request submission
 *
 * Each workflow:
 * 1. Validates preconditions
 * 2. Calls feature module APIs in sequence
 * 3. Updates State with results
 * 4. Handles errors and conflict resolution
 * 5. Fires 'wl:*Completed' events for interested listeners
 */

define([
    "jquery",
    "modules/wl_constants",
    "modules/wl_state",
    "modules/wl_rest",
    "modules/wl_ui",
    "modules/wl_table",
    "modules/wl_versions",
    "modules/wl_approval_ui",
    "modules/wl_modals",
    "modules/wl_csv_io"
], function ($, Constants, State, REST, UI, Table, Versions, ApprovalUI, Modals, CsvIO) {
    "use strict";

    /**
     * Orchestrator module — coordinates cross-module workflows
     */
    var Orchestrator = {

        /**
         * Initialize orchestrator (wire event handlers)
         */
        init: function () {
            // Set up any persistent event listeners if needed
            // Most workflows are triggered on-demand from entry point
        },

        /**
         * Orchestrate CSV save workflow
         *
         * Flow:
         * 1. Sync any pending input changes (Table.syncInputs)
         * 2. Check if bulk edit/addition (>= 2 edits or > 0 additions)
         * 3. Call approval gate check if needed
         * 4. If approval required, show modal and submit for approval
         * 5. If no approval needed, get comment and proceed with save
         * 6. POST save_csv to backend
         * 7. On success, reload CSV and versions
         * 8. Fire 'wl:csvSaved' event
         * 9. On 409 conflict, show conflict modal
         *
         * @param {object} options - {skipGateCheck: boolean, reason: string}
         * @param {function} callback - (success, data) => void
         */
        orchestrateSaveCSV: function (options, callback) {
            options = options || {};
            callback = callback || function () {};

            // Preconditions
            var selectedCsv = State.get('csvFileSelected');
            var selectedRule = State.get('detectionRuleSelected');
            var currentRows = State.get('currentRows');
            var originalRows = State.get('originalRows');
            var currentHeaders = State.get('currentHeaders');
            var originalHeaders = State.get('originalHeaders');

            if (!selectedCsv) {
                UI.showMsg("No CSV file selected.", "error");
                callback(false, { error: "No CSV selected" });
                return;
            }

            // Sync table inputs to capture any pending changes
            Table.syncInputs();

            // Recalculate edited/added counts after sync
            var visHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var editedCount = 0;
            var addedCount = Math.max(0, currentRows.length - originalRows.length);

            originalRows.forEach(function (origRow, idx) {
                if (idx < currentRows.length) {
                    var changed = visHeaders.some(function (h) {
                        return (currentRows[idx][h] || "") !== (origRow[h] || "");
                    });
                    if (changed) { editedCount++; }
                }
            });

            // Determine if approval gate is needed
            var needsGate = false;
            var gateAction = "";
            var gateCount = 0;

            if (addedCount > 0) {
                needsGate = true;
                gateAction = "bulk_row_addition";
                gateCount = addedCount;
            } else if (editedCount >= 2) {
                needsGate = true;
                gateAction = "bulk_row_edit";
                gateCount = editedCount;
            }

            // Helper: proceed with save after validation and reason collection
            var proceedWithSave = function (reason) {
                var savePayload = {
                    action: "save_csv",
                    csv_file: selectedCsv,
                    app_context: State.get('appContext') || "",
                    detection_rule: selectedRule || "",
                    headers: currentHeaders,
                    rows: currentRows,
                    comment: reason || "Changes saved",
                    removal_reasons: [],
                    expected_mtime: State.get('loadedMtime')
                };

                UI.showMsg("Saving...", "info");

                REST.restPost(savePayload)
                    .done(function (data) {
                        if (data.error) {
                            UI.showMsg(_.escape(data.error), "error");
                            callback(false, data);
                            return;
                        }

                        // Update State: mark rows as saved
                        State.set('originalRows', currentRows.map(function (r) { return $.extend({}, r); }));
                        State.set('originalHeaders', currentHeaders.slice());
                        State.set('loadedMtime', data.file_mtime || State.get('loadedMtime'));

                        // Show success message with diff summary
                        var diffInfo = data.diff || {};
                        var parts = [];
                        if (diffInfo.added_count) { parts.push("Added: " + diffInfo.added_count + " row(s)"); }
                        if (diffInfo.removed_count) { parts.push("Removed: " + diffInfo.removed_count + " row(s)"); }
                        if (diffInfo.edited_count) { parts.push("Edited: " + diffInfo.edited_count + " row(s)"); }
                        UI.showMsg("Saved successfully. " + parts.join(", ") + ".", "success");

                        // Reload CSV to get backend-stamped metadata
                        Orchestrator.orchestrateLoadCSV(selectedCsv, State.get('appContext'), function () {
                            // Fire completion event
                            $(document).trigger('wl:csvSaved', [data]);
                            callback(true, data);
                        });
                    })
                    .fail(function (xhr) {
                        if (xhr.status === 409) {
                            // Conflict: file changed externally
                            var conflictData = {};
                            try { conflictData = JSON.parse(xhr.responseText); } catch (e) {}
                            if (conflictData.current_mtime) {
                                State.set('loadedMtime', conflictData.current_mtime);
                            }
                            UI.showMsg("File changed externally. Click to reload.", "error");
                            callback(false, { error: "Conflict (409)", status: 409 });
                        } else {
                            UI.showMsg("Failed to save CSV.", "error");
                            callback(false, { error: xhr.statusText });
                        }
                    });
            };

            // Gate check or proceed directly
            if (needsGate) {
                REST.restPost({
                    action: "check_approval_gate",
                    gate_action: gateAction,
                    csv_file: selectedCsv,
                    app_context: State.get('appContext') || "",
                    selected_count: gateCount
                }).done(function (gateData) {
                    if (gateData.requires_approval) {
                        // Show approval modal
                        var actionDesc = gateAction === "bulk_row_edit"
                            ? "Editing " + gateCount + " row(s)"
                            : "Adding " + gateCount + " row(s)";
                        ApprovalUI.showApprovalNeeded(
                            gateAction,
                            "Reason for " + actionDesc.toLowerCase(),
                            {
                                onSubmit: function (reason) {
                                    // Submit for approval (don't save yet)
                                    Orchestrator.orchestrateApprovalProcess(gateAction, reason, {
                                        gateCount: gateCount,
                                        payload: { gateAction: gateAction, gateCount: gateCount }
                                    }, callback);
                                }
                            }
                        );
                    } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                        // Daily limit exceeded
                        UI.showMsg(ApprovalUI.formatDailyLimitMsg(gateData.daily_limit), "error");
                        callback(false, { error: "Daily limit exceeded" });
                    } else {
                        // No gate needed, proceed with save
                        proceedWithSave(options.reason || "Changes saved");
                    }
                }).fail(function () {
                    UI.showMsg("Unable to verify approval gate. Please try again.", "error");
                    callback(false, { error: "Gate check failed" });
                });
            } else {
                // No gate needed, proceed directly
                proceedWithSave(options.reason || "Changes saved");
            }
        },

        /**
         * Orchestrate CSV load workflow
         *
         * Flow:
         * 1. Fetch CSV content from backend
         * 2. Update State with headers and rows
         * 3. Load versions via Versions module
         * 4. Load column widths
         * 5. Load approval queue status
         * 6. Refresh table display via Table module
         * 7. Fire 'wl:csvLoaded' event
         *
         * @param {string} csvFile - CSV filename to load
         * @param {string} appContext - App context (optional)
         * @param {function} callback - (success) => void
         */
        orchestrateLoadCSV: function (csvFile, appContext, callback) {
            callback = callback || function () {};

            UI.showMsg("Loading CSV...", "info");

            REST.restGet({
                action: "get_csv_content",
                csv_file: csvFile,
                app: appContext || "",
                tz_offset: new Date().getTimezoneOffset()
            })
            .done(function (data) {
                if (data.error) {
                    UI.showMsg(_.escape(data.error), "error");
                    callback(false);
                    return;
                }

                // Update State with loaded data
                State.batch({
                    currentHeaders: data.headers || [],
                    originalHeaders: data.headers || [],
                    currentRows: data.rows || [],
                    originalRows: data.rows || [],
                    csvFileSelected: csvFile,
                    appContext: appContext || "",
                    loadedMtime: data.file_mtime || null,
                    expireColumn: data.expire_column || ""
                });

                // Show auto-removed warning if applicable
                if (data.auto_removed_count && data.auto_removed_count > 0) {
                    UI.showMsg(
                        "<strong>" + data.auto_removed_count + " expired row(s)</strong> were automatically removed.",
                        "warning"
                    );
                }

                // Load versions (last 5 + current)
                Versions.loadVersions(csvFile, appContext);

                // Load column widths
                REST.restGet({
                    action: "get_col_widths",
                    csv_file: csvFile,
                    app: appContext || ""
                }).done(function (widthData) {
                    if (widthData.col_widths) {
                        State.set('columnWidths', widthData.col_widths);
                    }
                });

                // Load approval queue
                ApprovalUI.updateApprovalStatus();

                // Refresh table display
                Table.refreshTable();

                UI.showMsg("CSV loaded successfully.", "success");
                $(document).trigger('wl:csvLoaded', [csvFile]);
                callback(true);
            })
            .fail(function (xhr) {
                if (xhr.status === 404) {
                    UI.showMsg("CSV file not found.", "error");
                } else {
                    UI.showMsg("Failed to load CSV.", "error");
                }
                callback(false);
            });
        },

        /**
         * Orchestrate version revert workflow
         *
         * Flow:
         * 1. Get revert reason from modal
         * 2. Call Versions.revertToVersion(versionId)
         * 3. Reload CSV with reverted content
         * 4. Refresh table
         * 5. Fire 'wl:versionReverted' event
         *
         * @param {string} versionId - Version identifier
         * @param {function} callback - (success) => void
         */
        orchestrateRevertCSV: function (versionId, callback) {
            callback = callback || function () {};

            // Version module handles revert UI and logic
            Versions.revertToVersion(versionId, function (success) {
                if (success) {
                    // Reload CSV to refresh display
                    var csvFile = State.get('csvFileSelected');
                    var appContext = State.get('appContext');
                    Orchestrator.orchestrateLoadCSV(csvFile, appContext, function () {
                        $(document).trigger('wl:versionReverted', [versionId]);
                        callback(true);
                    });
                } else {
                    callback(false);
                }
            });
        },

        /**
         * Orchestrate approval request submission
         *
         * Flow:
         * 1. Validate action type and reason
         * 2. Build approval request payload
         * 3. POST to backend
         * 4. Show confirmation modal
         * 5. Lock CSV pending approval
         * 6. Fire 'wl:approvalSubmitted' event
         *
         * @param {string} actionType - Action requiring approval (bulk_row_edit, bulk_row_addition, etc.)
         * @param {string} reason - Reason for request
         * @param {object} options - {gateCount, payload, ...}
         * @param {function} callback - (success) => void
         */
        orchestrateApprovalProcess: function (actionType, reason, options, callback) {
            options = options || {};
            callback = callback || function () {};

            if (!actionType || !reason) {
                UI.showMsg("Approval reason required.", "error");
                callback(false);
                return;
            }

            var selectedCsv = State.get('csvFileSelected');
            var selectedRule = State.get('detectionRuleSelected');

            UI.showMsg("Submitting for approval...", "info");

            REST.restPost({
                action: "submit_approval",
                action_type: actionType,
                reason: reason,
                csv_file: selectedCsv,
                detection_rule: selectedRule || "",
                app_context: State.get('appContext') || ""
            })
            .done(function (data) {
                if (data.error) {
                    UI.showMsg(_.escape(data.error), "error");
                    callback(false, data);
                    return;
                }

                // Lock CSV pending approval
                State.set('csvLocked', true);
                UI.showMsg(
                    "Request submitted for approval. Admins will review and respond.",
                    "success"
                );

                // Update approval status
                ApprovalUI.updateApprovalStatus();

                $(document).trigger('wl:approvalSubmitted', [data]);
                callback(true, data);
            })
            .fail(function (xhr) {
                UI.showMsg("Failed to submit approval request.", "error");
                callback(false, { error: xhr.statusText });
            });
        }

    };

    return Orchestrator;
});
