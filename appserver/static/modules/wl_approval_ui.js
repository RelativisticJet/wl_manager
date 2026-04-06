define([
  'jquery',
  'underscore',
  '../app/wl_rest',
  '../app/wl_ui'
], function($, _, Rest, UI) {

  // ============================================================
  // MODULE-LEVEL PRIVATE STATE
  // ============================================================
  // These will be set by init() from the entry point state proxies
  var _state = {};  // Will receive: currentRows, currentHeaders, selectedCsv, selectedApp, selectedRule, loadedMtime, originalRows, pendingApprovals, isAdmin
  var _$table = null;
  var _$revertSelect = null;
  var _actions = {};  // Will receive callbacks: showMsg, syncInputs, refreshTable, showApproveConfirmModal, showRejectReasonModal, showCancelRequestModal, getCurrentUser, getUsername, resetPage, loadCsv, restPost

  // Private module state
  var additionPreviewPage = 0;
  var additionPreviewData = null; // { headers, rowKeys }
  var PREVIEW_PAGE_SIZE = 10;
  var pendingFilterActive = false;
  var pendingFilterIndices = null;

  // ============================================================
  // EXTRACTED APPROVAL FUNCTIONS (with _state and _actions proxies)
  // ============================================================

function submitApprovalRequest(actionType, reason, rowIndices, colName) {
        _actions.syncInputs();

        var description = "";
        var highlight = {};
        var originalPayload = {};

        if (actionType === "bulk_row_removal") {
            description = reason || "Remove " + rowIndices.length + " selected rows";
            var visHeaders = _state.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var rowKeys = rowIndices.map(function (idx) {
                return visHeaders.map(function (h) { return _state.currentRows[idx][h] || ""; });
            });
            highlight = { type: "rows", row_keys: rowKeys, headers: visHeaders };

            var removedEntries = [];
            rowIndices.sort(function (a, b) { return a - b; });
            rowIndices.forEach(function (idx) {
                removedEntries.push({
                    row_number: idx + 1,
                    row: $.extend({}, _state.currentRows[idx])
                });
            });
            var rowsCopy = _state.currentRows.map(function (r) { return $.extend({}, r); });
            for (var i = rowIndices.length - 1; i >= 0; i--) {
                rowsCopy.splice(rowIndices[i], 1);
            }
            originalPayload = {
                action: "save_csv",
                csv_file: _state.selectedCsv,
                app_context: _state.selectedApp,
                detection_rule: _state.selectedRule || "",
                headers: _state.currentHeaders,
                rows: rowsCopy,
                comment: "Bulk removal (" + rowIndices.length + " rows) - approved",
                removal_reasons: [],
                bulk_removal: removedEntries.map(function (e) {
                    return { row_number: e.row_number, row: e.row, reason: reason };
                })
            };
        } else if (actionType === "bulk_row_addition") {
            // The new rows are at the end of _state.currentRows (beyond _state.originalRows.length)
            var addedCount = Math.max(0, _state.currentRows.length - _state.originalRows.length);
            var visHeadersAdd = _state.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var addedRowKeys = [];
            for (var ai = _state.originalRows.length; ai < _state.currentRows.length; ai++) {
                addedRowKeys.push(visHeadersAdd.map(function (h) { return _state.currentRows[ai][h] || ""; }));
            }
            highlight = { type: "rows", row_keys: addedRowKeys, headers: visHeadersAdd };
            description = reason || "Add " + addedCount + " new rows";
            originalPayload = {
                action: "save_csv",
                csv_file: _state.selectedCsv,
                app_context: _state.selectedApp,
                detection_rule: _state.selectedRule || "",
                headers: _state.currentHeaders,
                rows: _state.currentRows.map(function (r) { return $.extend({}, r); }),
                comment: "Row addition (" + addedCount + " rows)",
                row_add_reason: reason || "",
                removal_reasons: []
            };
        } else if (actionType === "column_removal") {
            description = reason || "Remove column '" + colName + "'";
            highlight = { type: "column", column_name: colName };

            var headersCopy = _state.currentHeaders.slice();
            var cidx = headersCopy.indexOf(colName);
            if (cidx !== -1) { headersCopy.splice(cidx, 1); }
            var rowsCopyCol = _state.currentRows.map(function (r) {
                var copy = $.extend({}, r);
                delete copy[colName];
                return copy;
            });
            originalPayload = {
                action: "save_csv",
                csv_file: _state.selectedCsv,
                app_context: _state.selectedApp,
                detection_rule: _state.selectedRule || "",
                headers: headersCopy,
                rows: rowsCopyCol,
                comment: reason || "Column removal - approved",
                removal_reasons: [],
                column_removal_reasons: [{ column: colName, reason: reason }]
            };
        }

        _actions.showMsg("Submitting approval request&hellip;", "info");

        // Compute selected_count for daily limit validation
        var approvalCount = 1;
        if (actionType === "bulk_row_removal" && rowIndices) {
            approvalCount = rowIndices.length;
        } else if (actionType === "bulk_row_addition") {
            approvalCount = Math.max(0, _state.currentRows.length - _state.originalRows.length);
        } else if (actionType === "column_removal") {
            approvalCount = 1;
        }

        _actions.restPost({
            action: "submit_approval",
            approval_action_type: actionType,
            csv_file: _state.selectedCsv,
            app_context: _state.selectedApp,
            detection_rule: _state.selectedRule || "",
            description: description,
            comment: reason || "",
            original_payload: originalPayload,
            expected_mtime: _state.loadedMtime,
            pending_highlight: highlight,
            selected_count: approvalCount
        })
        .done(function (data) {
            if (data.error) {
                _actions.showMsg(_.escape(data.error), "error");
                return;
            }
            _actions.showMsg(
                "Your request has been submitted for approval. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            // Reload to show orange highlighting
            _actions.loadCsv(_state.selectedCsv, _state.selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit approval request.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            _actions.showMsg(_.escape(err), "error");
        });
}

function submitBulkEditApproval(col, val, rowIndices, changedCount, reason) {
        _actions.syncInputs();
        var visHeaders = _state.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var rowKeys = rowIndices.map(function (idx) {
            return visHeaders.map(function (h) { return _state.currentRows[idx][h] || ""; });
        });

        var displayVal = val.length > 100 ? val.substring(0, 100) + "..." : val;
        var description = "Bulk edit " + changedCount + " rows — set '" + col + "' to '" + displayVal + "'";

        _actions.showMsg("Submitting bulk edit approval request&hellip;", "info");

        _actions.restPost({
            action: "submit_approval",
            approval_action_type: "bulk_row_edit",
            csv_file: _state.selectedCsv,
            app_context: _state.selectedApp,
            detection_rule: _state.selectedRule || "",
            description: description,
            original_payload: {
                action: "save_csv",
                csv_file: _state.selectedCsv,
                app_context: _state.selectedApp,
                detection_rule: _state.selectedRule || "",
                headers: _state.currentHeaders,
                rows: _state.currentRows,
                comment: reason || ("Bulk edit (" + changedCount + " rows) - approved"),
                bulk_edit_column: col,
                bulk_edit_value: val,
                _bulk_edit_count: changedCount
            },
            expected_mtime: _state.loadedMtime,
            pending_highlight: { type: "rows", row_keys: rowKeys, headers: visHeaders },
            selected_count: changedCount
        })
        .done(function (data) {
            if (data.error) {
                _actions.showMsg(_.escape(data.error), "error");
                return;
            }
            _actions.showMsg(
                "Bulk edit requires approval. Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            _actions.loadCsv(_state.selectedCsv, _state.selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit bulk edit approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            _actions.showMsg(_.escape(err), "error");
        });
}

function submitInlineMultiEditApproval(changedCount, reason) {
        _actions.syncInputs();
        var autoDesc = "Inline edit of " + changedCount + " rows in " +
            (_state.selectedCsv || "unknown CSV");

        _actions.showMsg("Submitting edit approval request&hellip;", "info");

        _actions.restPost({
            action: "submit_approval",
            approval_action_type: "bulk_row_edit",
            csv_file: _state.selectedCsv,
            app_context: _state.selectedApp,
            detection_rule: _state.selectedRule || "",
            description: reason || autoDesc,
            comment: reason,
            original_payload: {
                action: "save_csv",
                csv_file: _state.selectedCsv,
                app_context: _state.selectedApp,
                detection_rule: _state.selectedRule || "",
                headers: _state.currentHeaders,
                rows: _state.currentRows,
                comment: reason || ("Inline multi-edit (" + changedCount + " rows) - approved"),
                _bulk_edit_count: changedCount
            },
            expected_mtime: _state.loadedMtime,
            selected_count: changedCount
        })
        .done(function (data) {
            if (data.error) {
                _actions.showMsg(_.escape(data.error), "error");
                return;
            }
            _actions.showMsg(
                "Edit requires approval. Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            // Revert local edits since they're pending approval
            _actions.loadCsv(_state.selectedCsv, _state.selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit edit approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            _actions.showMsg(_.escape(err), "error");
        });
}

function buildLockedState() {
        csvLocked = _state.pendingApprovals.length > 0;
}

/**
 * Re-apply amber CSS classes to rows/columns/table that triggered
 * the pending approval.  Safe to call after every _actions.refreshTable().
 */
function applyPendingCssHighlighting() {
        if (!_state.pendingApprovals.length) { return; }
        _state.pendingApprovals.forEach(function (pa) {
            var hl = pa.pending_highlight || {};
            if (hl.type === "rows" && hl.row_keys) {
                var hlH = hl.headers || _state.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
                // Use counter (not set) to handle duplicate rows correctly
                var keyCounts = {};
                hl.row_keys.forEach(function (rk) {
                    var k = JSON.stringify(rk);
                    keyCounts[k] = (keyCounts[k] || 0) + 1;
                });
                _$table.find("tbody tr").each(function () {
                    var idx = $(this).data("idx");
                    if (idx !== undefined && _state.currentRows[idx]) {
                        var key = hlH.map(function (h) { return _state.currentRows[idx][h] || ""; });
                        var k = JSON.stringify(key);
                        if (keyCounts[k] > 0) {
                            $(this).addClass("wl-pending-approval");
                            keyCounts[k]--;
                        }
                    }
                });
            } else if (hl.type === "column" && hl.column_name) {
                _$table.find("th[data-col]").filter(function () {
                    return $(this).data("col") === hl.column_name;
                }).addClass("wl-pending-approval-header");
            } else if (hl.type === "table") {
                _$table.find(".wl-table").addClass("wl-pending-approval-table");
            }
        });
}

/**
 * Extract the analyst reason from a pending approval entry.
 */
function extractApprovalReason(pa) {
        var payload = pa.payload || {};
        var at = pa.action_type || "";
        if (at === "bulk_row_removal") {
            var br = payload.bulk_removal;
            if (br && br.length) return br[0].reason || "";
        } else if (at === "bulk_row_addition") {
            return payload.row_add_reason || "";
        } else if (at === "column_removal") {
            var cr = payload.column_removal_reasons;
            if (cr && cr.length) return cr[0].reason || "";
        } else if (at === "revert") {
            return payload.revert_reason || "";
        }
        return "";
}

/**
 * Compute which _state.currentRows indices are affected by a pending approval.
 * Uses counter-based matching for correct duplicate handling.
 */
function getPendingRowIndices(pa) {
        var hl = pa.pending_highlight || {};
        if (hl.type !== "rows" || !hl.row_keys) return [];
        var hlH = hl.headers || _state.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var keyCounts = {};
        hl.row_keys.forEach(function (rk) {
            var k = JSON.stringify(rk);
            keyCounts[k] = (keyCounts[k] || 0) + 1;
        });
        var indices = [];
        for (var i = 0; i < _state.currentRows.length; i++) {
            var key = hlH.map(function (h) { return _state.currentRows[i][h] || ""; });
            var k = JSON.stringify(key);
            if (keyCounts[k] > 0) {
                indices.push(i);
                keyCounts[k]--;
            }
        }
        return indices;
}

var pendingFilterActive = false;  // tracks whether we're filtering to show only requested rows
var pendingFilterIndices = null;  // array of row indices when filter is active

function applyPendingHighlighting() {
        buildLockedState();
        if (!_state.pendingApprovals.length) { return; }

        applyPendingCssHighlighting();

        // Lock all controls — entire CSV is locked
        _$table.find("#btn-save").addClass("wl-btn-locked").prop("disabled", true);
        _$table.find("#btn-add-row").addClass("wl-btn-locked").prop("disabled", true);
        _$table.find("#btn-add-col").addClass("wl-btn-locked").prop("disabled", true);
        _$table.find("#btn-remove-selected").addClass("wl-btn-locked").prop("disabled", true);
        _$table.find(".wl-import-btn").addClass("wl-btn-locked");
        _$table.find("#btn-import").prop("disabled", true);
        $revertSelect.prop("disabled", true);

        // Show lock banner
        var descriptions = _state.pendingApprovals.map(function (pa) {
            return '<strong>' + _.escape(pa.action_type.replace(/_/g, " ")) + '</strong> by ' +
                   _.escape(pa.analyst) + ' (' + _.escape(pa.description) + ')';
        });
        _actions.showMsg(
            "This CSV is locked &mdash; " +
            (_state.pendingApprovals.length > 1 ? "pending approvals" : "a pending approval") +
            " must be resolved before changes can be made. " +
            descriptions.join("; ") + ".",
            "warning"
        );

        // Approve / Reject / Cancel action bar
        // Shown for admins (approve/reject others, cancel own) and
        // non-admin analysts who own a pending request (cancel only)
        $("#wl-approval-actions").remove();
        _actions.getCurrentUser();
        var currentUser = _actions.getUsername();
        var ownsAnyRequest = currentUser && _state.pendingApprovals.some(function (pa) {
            return pa.analyst === currentUser;
        });
        if (_state.isAdmin || ownsAnyRequest) {
            var barHtml = '<div id="wl-approval-actions" class="wl-approval-bar">';
            _state.pendingApprovals.forEach(function (pa, paIdx) {
                var isSelfRequest = currentUser && pa.analyst === currentUser;
                // Non-admin users only see their own requests
                if (!_state.isAdmin && !isSelfRequest) { return; }
                var reason = extractApprovalReason(pa);
                var hl = pa.pending_highlight || {};
                var hasRowHighlight = (hl.type === "rows" && hl.row_keys && hl.row_keys.length > 0);
                // Use comment (user's typed reason) or description, avoid duplication
                var displayReason = pa.comment || pa.description || "";
                var descTitle = pa.action_type.replace(/_/g, " ") +
                    ' by ' + pa.analyst + ' — ' + displayReason;
                barHtml +=
                    '<div class="wl-approval-item">' +
                        '<span class="wl-approval-desc" title="' + _.escape(descTitle) + '">' +
                            '<strong>' + _.escape(pa.action_type.replace(/_/g, " ")) + '</strong>' +
                            ' by ' + _.escape(pa.analyst) +
                            ' &mdash; ' + _.escape(displayReason) +
                        '</span>' +
                        (isSelfRequest
                            ? '<span class="btn btn-warning wl-cancel-request-btn" data-id="' +
                                _.escape(pa.request_id) + '" style="background:#f39c12;color:#fff">Cancel Request</span>'
                            : '<span class="btn btn-success wl-approve-btn" data-id="' +
                                _.escape(pa.request_id) + '">Approve</span>' +
                              '<span class="btn btn-danger wl-reject-btn" data-id="' +
                                _.escape(pa.request_id) + '">Reject</span>'
                        ) +
                        (hasRowHighlight
                            ? '<span class="btn btn-small wl-filter-requested" data-idx="' + paIdx +
                              '" style="margin-left:8px;cursor:pointer">Show Requested Rows</span>'
                            : '') +
                    '</div>';
            });
            barHtml += '</div>';
            _$table.before(barHtml);
            bindApprovalActions();
        }
}

// ══════════════════════════════════════════════════════════════════
// Admin Approve / Reject actions (inline on CSV editor)
// ══════════════════════════════════════════════════════════════════

function bindApprovalActions() {
        // ── Approve ──────────────────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-approve-btn")
            .on("click.wl", ".wl-approve-btn", function () {
            var requestId = $(this).data("id");
            _actions.showApproveConfirmModal(requestId);
        });

        // ── Reject ───────────────────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-reject-btn")
            .on("click.wl", ".wl-reject-btn", function () {
            var requestId = $(this).data("id");
            _actions.showRejectReasonModal(requestId);
        });

        // ── Show Requested Rows filter ──────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-filter-requested")
            .on("click.wl", ".wl-filter-requested", function () {
            var idx = $(this).data("idx");
            var pa = _state.pendingApprovals[idx];
            if (!pa) return;

            if (pendingFilterActive) {
                // Remove filter — show all rows
                pendingFilterActive = false;
                pendingFilterIndices = null;
                additionPreviewData = null;
                $("#wl-addition-preview").remove();
                $(this).text("Show Requested Rows");
                _actions.resetPage();
                _actions.refreshTable();
                applyPendingCssHighlighting();
            } else if (pa.action_type === "bulk_row_addition") {
                // For additions, rows don't exist in CSV yet —
                // show a read-only preview from the stored payload
                pendingFilterActive = true;
                $(this).text("Show All Rows");
                showAdditionPreview(pa);
            } else {
                // For removals/edits, filter the existing table
                var matchedIndices = getPendingRowIndices(pa);
                if (!matchedIndices.length) {
                    _actions.showMsg("No matching rows found in current CSV.", "info");
                    return;
                }
                pendingFilterActive = true;
                pendingFilterIndices = matchedIndices;
                $(this).text("Show All Rows");
                _actions.resetPage();
                _actions.refreshTable();
                applyPendingCssHighlighting();
            }
        });

        // ── Cancel own request ──────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-cancel-request-btn")
            .on("click.wl", ".wl-cancel-request-btn", function () {
            var requestId = $(this).data("id");
            _actions.showCancelRequestModal(requestId);
        });
}

// (showCancelRequestModal → extracted to modules/wl_modals.js)

/**
 * Show a read-only preview table of rows requested to be added.
 * These rows exist in the stored payload but not yet in the CSV.
 */
var additionPreviewPage = 0;
var additionPreviewData = null; // { headers, rowKeys }
var PREVIEW_PAGE_SIZE = 10;

function showAdditionPreview(pa) {
        var hl = pa.pending_highlight || {};
        additionPreviewData = {
            headers: hl.headers || [],
            rowKeys: hl.row_keys || []
        };
        if (!additionPreviewData.headers.length || !additionPreviewData.rowKeys.length) {
            _actions.showMsg("No row details available for this request.", "info");
            return;
        }
        additionPreviewPage = 0;
        renderAdditionPreview();
}

function renderAdditionPreview() {
        $("#wl-addition-preview").remove();
        if (!additionPreviewData) return;
        var headers = additionPreviewData.headers;
        var rowKeys = additionPreviewData.rowKeys;
        var total = rowKeys.length;
        var totalPages = Math.max(1, Math.ceil(total / PREVIEW_PAGE_SIZE));
        if (additionPreviewPage >= totalPages) additionPreviewPage = totalPages - 1;
        var start = additionPreviewPage * PREVIEW_PAGE_SIZE;
        var end = Math.min(start + PREVIEW_PAGE_SIZE, total);
        var pageSlice = rowKeys.slice(start, end);

        var html = '<div id="wl-addition-preview" class="wl-addition-preview">' +
            '<h4 style="margin:0 0 8px">Rows requested to be added (' + total + ')</h4>' +
            '<div style="overflow:auto">' +
            '<table class="wl-table" style="font-size:12px">' +
            '<thead><tr><th>#</th>';
        headers.forEach(function (h) {
            html += '<th>' + _.escape(h) + '</th>';
        });
        html += '</tr></thead><tbody>';
        pageSlice.forEach(function (rk, i) {
            html += '<tr class="wl-pending-approval"><td>' + (start + i + 1) + '</td>';
            if (Array.isArray(rk)) {
                rk.forEach(function (v) {
                    html += '<td title="' + _.escape(v) + '">' + _.escape(v) + '</td>';
                });
            } else {
                html += '<td colspan="' + headers.length + '">' + _.escape(JSON.stringify(rk)) + '</td>';
            }
            html += '</tr>';
        });
        html += '</tbody></table></div>';

        // Pagination controls
        if (totalPages > 1) {
            html += '<div style="margin-top:8px;display:flex;align-items:center;gap:8px">';
            html += '<span class="btn btn-small wl-preview-prev"' +
                (additionPreviewPage <= 0 ? ' style="opacity:0.4;pointer-events:none"' : '') +
                '>&laquo; Prev</span>';
            html += '<span style="font-size:12px">Page ' + (additionPreviewPage + 1) + ' of ' +
                totalPages + ' (' + total + ' rows)</span>';
            html += '<span class="btn btn-small wl-preview-next"' +
                (additionPreviewPage >= totalPages - 1 ? ' style="opacity:0.4;pointer-events:none"' : '') +
                '>Next &raquo;</span>';
            html += '</div>';
        }
        html += '</div>';

        var $bar = $("#wl-approval-actions");
        if ($bar.length) {
            $bar.after(html);
        } else {
            _$table.before(html);
        }

        // Bind pagination
        $("#wl-addition-preview").off("click", ".wl-preview-prev").on("click", ".wl-preview-prev", function () {
            if (additionPreviewPage > 0) {
                additionPreviewPage--;
                renderAdditionPreview();
            }
        });
        $("#wl-addition-preview").off("click", ".wl-preview-next").on("click", ".wl-preview-next", function () {
            var totalPages = Math.ceil(additionPreviewData.rowKeys.length / PREVIEW_PAGE_SIZE);
            if (additionPreviewPage < totalPages - 1) {
                additionPreviewPage++;
                renderAdditionPreview();
            }
        });
}


  // ============================================================
  // MODULE PUBLIC API
  // ============================================================

  return {

    init: function(options) {
      _state = options.state || {};
      _$table = options.$table || null;
      _$revertSelect = options.$revertSelect || null;
      _actions = options.actions || {};
    },

    // Approval submission functions
    submitApprovalRequest: submitApprovalRequest,
    submitBulkEditApproval: submitBulkEditApproval,
    submitInlineMultiEditApproval: submitInlineMultiEditApproval,

    // State management
    buildLockedState: buildLockedState,

    // Highlighting and filtering
    applyPendingCssHighlighting: applyPendingCssHighlighting,
    applyPendingHighlighting: applyPendingHighlighting,
    getPendingRowIndices: getPendingRowIndices,

    // Utility functions
    extractApprovalReason: extractApprovalReason,
    bindApprovalActions: bindApprovalActions,

    // Preview functions
    showAdditionPreview: showAdditionPreview,
    renderAdditionPreview: renderAdditionPreview,

    // State accessors for filter flags
    getPendingFilterActive: function() { return pendingFilterActive; },
    setPendingFilterActive: function(val) { pendingFilterActive = val; },
    getPendingFilterIndices: function() { return pendingFilterIndices; },
    setPendingFilterIndices: function(val) { pendingFilterIndices = val; },
    getAdditionPreviewPage: function() { return additionPreviewPage; },
    setAdditionPreviewPage: function(val) { additionPreviewPage = val; }
  };
});
