/**
 * wl_save.js — Save pipeline, undo system, external change detection
 *
 * Extracted from whitelist_manager.js (Wave 3, Step 7).
 *
 * Functions:
 *   Save:     doSave, doSaveRemoval, doSaveBulkRemoval,
 *             doSaveColumnAddition, doSaveColumnRemoval
 *   RowUndo:  showRowRemovalUndoBar, undoRowRemoval, commitPendingRowRemoval
 *   ColUndo:  showColumnRemovalUndoBar, undoColumnRemoval, commitPendingColumnRemoval
 *   Shared:   clearUndo
 *   Detect:   startChangeMonitoring, stopChangeMonitoring,
 *             checkForExternalChanges, hasUnsavedChanges, showExternalChangeModal
 *   Support:  handleSaveError, getAuditComment
 *   Load:     loadCsv, reloadCsvQuiet
 *   Gate:     doColumnRemoveWithGateCheck
 */
define([
    "jquery",
    "underscore",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui",
    "app/wl_manager/modules/wl_constants"
], function ($, _, REST, UI, C) {
    "use strict";

    var restGet  = REST.restGet;
    var restPost = REST.restPost;
    var showMsg  = UI.showMsg;
    var clearMsg = UI.clearMsg;
    var formatDailyLimitMsg = UI.formatDailyLimitMsg;

    // Module-private refs (set by init)
    var _state   = null;
    var _$table  = null;
    var _$msg    = null;
    var _actions = null;

    // Module-private state
    var undoTimer       = null;
    var undoState       = null;
    var changeCheckTimer = null;
    var pendingColRemoval = null; // { colName, reason, prevRows, prevOriginal, prevHeaders, prevOrigHeaders }
    var pendingRowRemoval = null; // { removedRow, reason, rowNumber, prevRows, prevOriginal }

    // ══════════════════════════════════════════════════════════════════
    // Conflict handling (optimistic locking)
    // ══════════════════════════════════════════════════════════════════
    function handleSaveError(xhr, fallbackMsg) {
        var err = fallbackMsg || "Save failed.";
        try {
            var resp = JSON.parse(xhr.responseText);
            err = resp.error || err;
            if (xhr.status === 409 && resp.current_mtime) {
                _state.loadedMtime = resp.current_mtime;
            }
            if (xhr.status === 409 && typeof resp.current_content_hash === "string" && resp.current_content_hash) {
                _state.loadedContentHash = resp.current_content_hash;
            }
        } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
        var safeErr = _.escape(err);
        if (xhr.status === 409) {
            showMsg(safeErr + ' <span class="wl-link" id="wl-conflict-reload">Click to reload.</span>', "error");
            _$msg.off("click", "#wl-conflict-reload").on("click", "#wl-conflict-reload", function () {
                loadCsv(_state.selectedCsv, _state.selectedApp);
            });
        } else {
            showMsg(safeErr, "error");
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Column addition save
    // ══════════════════════════════════════════════════════════════════
    function doSaveColumnAddition(colName) {
        _actions.syncInputs();

        var prevRows = _state.currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = _state.originalRows.map(function (r) { return $.extend({}, r); });
        var prevHeaders = _state.currentHeaders.slice();
        var prevOrigHeaders = _state.originalHeaders.slice();

        var insertIdx = _state.currentHeaders.length;
        for (var i = 0; i < _state.currentHeaders.length; i++) {
            if (_state.currentHeaders[i].charAt(0) === "_") { insertIdx = i; break; }
        }
        _state.currentHeaders.splice(insertIdx, 0, colName);

        _state.currentRows.forEach(function (row) { row[colName] = ""; });

        _actions.refreshTable();
        showMsg("Adding column and saving&hellip;", "info");

        _state.saving = true;
        restPost({
            action:          "save_csv",
            csv_file:        _state.selectedCsv,
            app_context:     _state.selectedApp,
            detection_rule:  _state.selectedRule || "",
            headers:         _state.currentHeaders,
            rows:            _state.currentRows,
            comment:         "Column addition",
            removal_reasons: [],
            expected_mtime:  _state.loadedMtime,
            expected_content_hash: _state.loadedContentHash
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                _state.currentHeaders = prevHeaders;
                _state.originalHeaders = prevOrigHeaders;
                _state.currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                _state.originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                _actions.refreshTable();
                return;
            }

            showMsg('Column <strong>' + _.escape(colName) + '</strong> added and saved.', "success");
            _state.originalRows = _state.currentRows.map(function (r) { return $.extend({}, r); });
            _state.originalHeaders = _state.currentHeaders.slice();
            if (data.file_mtime) { _state.loadedMtime = data.file_mtime; }
            if (typeof data.content_hash === "string" && data.content_hash) { _state.loadedContentHash = data.content_hash; }

            if (data.diff && data.diff.text_diff && data.diff.text_diff.length) {
                _actions.renderDiff(data.diff);
            }

            _actions.loadVersions(_state.selectedCsv, _state.selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after column addition.");
            _state.currentHeaders = prevHeaders;
            _state.originalHeaders = prevOrigHeaders;
            _state.currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            _state.originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            _actions.refreshTable();
        })
        .always(function () { _state.saving = false; });
    }

    // ══════════════════════════════════════════════════════════════════
    // Column removal (local + deferred save with undo)
    // ══════════════════════════════════════════════════════════════════
    function doSaveColumnRemoval(colName, reason) {
        _actions.syncInputs();

        var visibleCount = _state.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; }).length;
        if (visibleCount <= 1) {
            showMsg("Cannot remove the last column.", "error");
            return;
        }

        var prevRows = _state.currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = _state.originalRows.map(function (r) { return $.extend({}, r); });
        var prevHeaders = _state.currentHeaders.slice();
        var prevOrigHeaders = _state.originalHeaders.slice();

        var idx = _state.currentHeaders.indexOf(colName);
        if (idx !== -1) { _state.currentHeaders.splice(idx, 1); }
        _state.currentRows.forEach(function (row) { delete row[colName]; });

        _actions.refreshTable();

        pendingColRemoval = {
            colName: colName, reason: reason,
            prevRows: prevRows, prevOriginal: prevOriginal,
            prevHeaders: prevHeaders, prevOrigHeaders: prevOrigHeaders
        };
        showColumnRemovalUndoBar(colName);
    }

    function showColumnRemovalUndoBar(colName) {
        // Clear timer + row-undo state, but NOT pendingColRemoval (just set by caller)
        if (undoTimer) { clearInterval(undoTimer); undoTimer = null; }
        undoState = null;
        var $bar = _$table.find("#wl-undo-bar");
        if ($bar.length) { $bar.empty(); }

        var desc = 'Column removed: <strong>' + _.escape(colName) +
                   '</strong> — auto-saves when countdown ends';

        $bar.html(
            '<div class="wl-undo">' +
            '<span>' + desc + '</span> ' +
            '<button class="btn btn-small" id="btn-undo">Undo</button> ' +
            '<span class="wl-undo-countdown" id="undo-countdown">10s</span>' +
            '</div>'
        );

        var secondsLeft = 10;
        undoTimer = setInterval(function () {
            secondsLeft--;
            $bar.find("#undo-countdown").text(secondsLeft + "s");
            if (secondsLeft <= 0) {
                clearInterval(undoTimer);
                undoTimer = null;
                $bar.empty();
                commitPendingColumnRemoval();
            }
        }, 1000);

        // Delegate on _$table so handler survives table re-renders
        _$table.off("click", "#btn-undo").on("click", "#btn-undo", function () {
            undoColumnRemoval();
        });
    }

    function undoColumnRemoval() {
        if (!pendingColRemoval) { return; }
        _state.currentHeaders = pendingColRemoval.prevHeaders.slice();
        _state.currentRows = pendingColRemoval.prevRows.map(function (r) { return $.extend({}, r); });
        pendingColRemoval = null;
        clearUndo();
        _actions.refreshTable();
        showMsg("Column removal undone.", "info");
    }

    function commitPendingColumnRemoval() {
        if (!pendingColRemoval) { return; }
        var pcr = pendingColRemoval;
        pendingColRemoval = null;

        showMsg("Saving column removal&hellip;", "info");

        _state.saving = true;
        restPost({
            action:          "save_csv",
            csv_file:        _state.selectedCsv,
            app_context:     _state.selectedApp,
            detection_rule:  _state.selectedRule || "",
            headers:         _state.currentHeaders,
            rows:            _state.currentRows,
            comment:         pcr.reason || "Column removal",
            removal_reasons: [],
            column_removal_reasons: [{ column: pcr.colName, reason: pcr.reason }],
            expected_mtime:  _state.loadedMtime,
            expected_content_hash: _state.loadedContentHash
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                _state.currentHeaders = pcr.prevHeaders;
                _state.originalHeaders = pcr.prevOrigHeaders;
                _state.currentRows = pcr.prevRows.map(function (r) { return $.extend({}, r); });
                _state.originalRows = pcr.prevOriginal.map(function (r) { return $.extend({}, r); });
                _actions.refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var msg = 'Column <strong>' + _.escape(pcr.colName) + '</strong> removed and saved.';
            if (diffInfo.edited_count > 0) {
                msg += " " + diffInfo.edited_count + " row(s) also edited.";
            }
            showMsg(msg, "success");
            _state.originalRows = _state.currentRows.map(function (r) { return $.extend({}, r); });
            _state.originalHeaders = _state.currentHeaders.slice();
            if (data.file_mtime) { _state.loadedMtime = data.file_mtime; }
            if (typeof data.content_hash === "string" && data.content_hash) { _state.loadedContentHash = data.content_hash; }
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                _actions.renderDiff(diffInfo);
            }
            _actions.loadVersions(_state.selectedCsv, _state.selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after column removal.");
            _state.currentHeaders = pcr.prevHeaders;
            _state.originalHeaders = pcr.prevOrigHeaders;
            _state.currentRows = pcr.prevRows.map(function (r) { return $.extend({}, r); });
            _state.originalRows = pcr.prevOriginal.map(function (r) { return $.extend({}, r); });
            _actions.refreshTable();
        })
        .always(function () { _state.saving = false; });
    }

    // ══════════════════════════════════════════════════════════════════
    // clearUndo — cancels any pending undo timer and state
    // ══════════════════════════════════════════════════════════════════
    function clearUndo() {
        if (undoTimer) {
            clearInterval(undoTimer);
            undoTimer = null;
        }
        undoState = null;
        pendingColRemoval = null;
        pendingRowRemoval = null;
        var $bar = _$table.find("#wl-undo-bar");
        if ($bar.length) { $bar.empty(); }
    }

    // ══════════════════════════════════════════════════════════════════
    // External change detection (poll file mtime every 5s)
    // ══════════════════════════════════════════════════════════════════
    function startChangeMonitoring() {
        stopChangeMonitoring();
        if (!_state.selectedCsv || !_state.loadedMtime) { return; }
        changeCheckTimer = setInterval(checkForExternalChanges, 5000);
    }

    function stopChangeMonitoring() {
        if (changeCheckTimer) { clearInterval(changeCheckTimer); changeCheckTimer = null; }
    }

    function checkForExternalChanges() {
        if (!_state.selectedCsv || !_state.loadedMtime || _state.saving) { return; }
        restGet({
            action:   "check_csv_status",
            csv_file: _state.selectedCsv,
            app:      _state.selectedApp || ""
        })
        .done(function (data) {
            var newPending = data.pending_count !== undefined ? data.pending_count : 0;
            if (newPending !== _state.loadedPendingCount) {
                loadCsv(_state.selectedCsv, _state.selectedApp);
                return;
            }
            // mtime change OR content-hash change both trigger the
            // external-change modal. Hash catches attackers that
            // preserve mtime via `cp -p` / `touch -r` or that modify
            // the file via SPL / another app while honest tools
            // bump mtime as expected.
            var mtimeChanged = data.file_mtime !== undefined
                && data.file_mtime !== null
                && data.file_mtime !== _state.loadedMtime;
            var hashChanged = typeof data.content_hash === "string"
                && data.content_hash
                && _state.loadedContentHash
                && data.content_hash !== _state.loadedContentHash;
            if (mtimeChanged || hashChanged) {
                stopChangeMonitoring();
                showExternalChangeModal();
            }
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                _actions.handleCsvRemoved(_state.selectedCsv);
            }
        });
    }

    function hasUnsavedChanges() {
        if (_state.currentHeaders.length !== _state.originalHeaders.length) { return true; }
        for (var i = 0; i < _state.currentHeaders.length; i++) {
            if (_state.currentHeaders[i] !== _state.originalHeaders[i]) { return true; }
        }
        if (_state.currentRows.length !== _state.originalRows.length) { return true; }
        for (var r = 0; r < _state.currentRows.length; r++) {
            for (var h = 0; h < _state.currentHeaders.length; h++) {
                var hdr = _state.currentHeaders[h];
                if ((_state.currentRows[r][hdr] || "") !== (_state.originalRows[r][hdr] || "")) { return true; }
            }
        }
        return false;
    }

    function showExternalChangeModal() {
        $(".wl-modal-overlay").remove();

        var unsaved = hasUnsavedChanges();
        var warning = unsaved
            ? '<p style="color:var(--wl-warn-text,#e65100);margin-top:8px">' +
              '<strong>Warning:</strong> You have unsaved changes that will be lost if you reload.</p>'
            : '';

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">CSV File Changed Externally</div>' +
                    '<div class="wl-modal-body">' +
                        'The file <strong>' + _.escape(_state.selectedCsv) + '</strong> has been modified ' +
                        'outside of Whitelist Manager (possibly by another analyst or application).' +
                        warning +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-primary" id="wl-extchg-reload">Reload CSV</button> ' +
                        '<button type="button" class="btn" id="wl-extchg-keep">Keep editing</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("click", "#wl-extchg-reload", function () {
            $modal.remove();
            loadCsv(_state.selectedCsv, _state.selectedApp);
        });
        $modal.on("click", "#wl-extchg-keep", function () {
            $modal.remove();
            restGet({
                action:   "check_csv_status",
                csv_file: _state.selectedCsv,
                app:      _state.selectedApp || ""
            })
            .done(function (data) {
                if (data.file_mtime !== undefined && data.file_mtime !== null) {
                    _state.loadedMtime = data.file_mtime;
                }
                if (typeof data.content_hash === "string" && data.content_hash) {
                    _state.loadedContentHash = data.content_hash;
                }
                startChangeMonitoring();
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Comment validation
    // ══════════════════════════════════════════════════════════════════
    function getAuditComment(callback) {
        var hasCommentCol = _state.currentHeaders.indexOf("Comment") !== -1;

        _$table.find(".wl-input").removeClass("wl-input-error");

        if (hasCommentCol) {
            var emptyFound = false;
            _$table.find("tbody tr").each(function () {
                $(this).find('.wl-input[data-header="Comment"]').each(function () {
                    if (!$(this).val().trim()) {
                        $(this).addClass("wl-input-error");
                        emptyFound = true;
                    }
                });
            });

            if (emptyFound) {
                showMsg("Comment field cannot be empty.", "error");
                return;
            }

            callback({ valid: true, comment: "" });
            return;
        }

        $(".wl-modal-overlay").remove();
        var html =
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal" style="max-width:480px">' +
                '<div class="wl-modal-header">Audit Comment Required</div>' +
                '<p style="font-size:13px;color:var(--wl-text-secondary,#888);margin:0 0 12px">' +
                    'This CSV does not have a "Comment" column.<br>' +
                    'Please provide a reason for this change (max 500 chars).<br>' +
                    '<em>This will be recorded in the audit trail only, not saved in the CSV.</em>' +
                '</p>' +
                '<textarea id="wl-audit-comment-input" rows="3" maxlength="500" ' +
                    'style="width:100%;box-sizing:border-box;font-family:inherit;' +
                    'font-size:13px;padding:6px 8px;border:1px solid var(--wl-border);' +
                    'border-radius:3px;background:var(--wl-bg-input);color:var(--wl-text);' +
                    'resize:vertical" placeholder="Reason for this change\u2026"></textarea>' +
                '<div class="wl-char-counter" data-for="wl-audit-comment-input">0 / 500</div>' +
                '<div class="wl-modal-actions" style="margin-top:12px">' +
                    '<button type="button" class="btn btn-primary" id="wl-audit-comment-ok">' +
                        'OK</button>' +
                    '<button type="button" class="btn" id="wl-audit-comment-cancel">' +
                        'Cancel</button>' +
                '</div>' +
            '</div></div>';

        $("body").append(html);
        setTimeout(function () { $("#wl-audit-comment-input").focus(); }, 100);

        $(".wl-modal-overlay").on("click", "#wl-audit-comment-cancel", function () {
            $(".wl-modal-overlay").remove();
        });
        $(".wl-modal-overlay").on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) {
                $(".wl-modal-overlay").remove();
            }
        });
        $(".wl-modal-overlay").on("click", "#wl-audit-comment-ok", function () {
            var comment = ($("#wl-audit-comment-input").val() || "").trim();
            if (!comment) {
                $("#wl-audit-comment-input").css("border-color", "#e74c3c")
                    .attr("placeholder", "A reason is required!");
                return;
            }
            if (C.NON_ASCII_RE.test(comment)) {
                $("#wl-audit-comment-input").css("border-color", "#e74c3c");
                showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }
            if (comment.length > 500) {
                comment = comment.substring(0, 500);
                showMsg("Comment truncated to 500 characters.", "warning");
            }
            $(".wl-modal-overlay").remove();
            callback({ valid: true, comment: comment });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save CSV (full save - Save Changes button)
    // ══════════════════════════════════════════════════════════════════
    function doSave() {
        if (_state.saving) { return; }
        if (_state.csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }

        _actions.syncInputs();

        var visHeaders = _state.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var beforeCount = _state.currentRows.length;
        _state.currentRows = _state.currentRows.filter(function (row) {
            return visHeaders.some(function (h) { return (row[h] || "").trim() !== ""; });
        });
        if (_state.currentRows.length < beforeCount) {
            _actions.refreshTable();
        }

        if (!_state.selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        var editedCount = 0;
        var addedCount = Math.max(0, _state.currentRows.length - _state.originalRows.length);
        var origKeySet = {};
        _state.originalRows.forEach(function (row) {
            var key = visHeaders.map(function (h) { return row[h] || ""; }).join("||");
            origKeySet[key] = true;
        });
        _state.currentRows.forEach(function (row, idx) {
            if (idx < _state.originalRows.length) {
                var changed = visHeaders.some(function (h) {
                    return (row[h] || "") !== (_state.originalRows[idx][h] || "");
                });
                if (changed) { editedCount++; }
            }
        });

        function proceedWithSave() {
            getAuditComment(function (result) {
            if (!result) { return; }

            _state.saving = true;
            _$table.find("#btn-save").prop("disabled", true).text("Saving...");
            showMsg("Saving&hellip;", "info");

            var savePayload = {
                action:          "save_csv",
                csv_file:        _state.selectedCsv,
                app_context:     _state.selectedApp,
                detection_rule:  _state.selectedRule || "",
                headers:         _state.currentHeaders,
                rows:            _state.currentRows,
                comment:         result.comment,
                removal_reasons: [],
                expected_mtime:  _state.loadedMtime,
            expected_content_hash: _state.loadedContentHash
            };
            if (_state.pendingBulkEditCount > 0) {
                savePayload._bulk_edit_count = _state.pendingBulkEditCount;
            }
            if (pendingColRemoval) {
                savePayload.column_removal_reasons = [{
                    column: pendingColRemoval.colName,
                    reason: pendingColRemoval.reason
                }];
                pendingColRemoval = null;
                clearUndo();
            }
            if (pendingRowRemoval) {
                savePayload.removal_reasons = [{
                    row: pendingRowRemoval.removedRow,
                    reason: pendingRowRemoval.reason,
                    row_number: pendingRowRemoval.rowNumber
                }];
                pendingRowRemoval = null;
                clearUndo();
            }
            restPost(savePayload)
            .done(function (data) {
                if (data.error) {
                    _state.saving = false;
                    showMsg(_.escape(data.error), "error");
                    _state.currentRows = _state.originalRows.map(function (r) { return $.extend({}, r); });
                    _actions.refreshTable();
                    return;
                }

                var diffInfo = data.diff || {};
                var totalRowChanges = (diffInfo.added_count || 0) +
                                      (diffInfo.removed_count || 0) +
                                      (diffInfo.edited_count || 0);
                var colsAdded   = (diffInfo.added_columns   || []).length;
                var colsRemoved = (diffInfo.removed_columns || []).length;

                if (totalRowChanges > 0 || colsAdded > 0 || colsRemoved > 0) {
                    var parts = [];
                    if (diffInfo.added_count)   { parts.push("Added: <strong>" + diffInfo.added_count + "</strong> row(s)"); }
                    if (diffInfo.removed_count) { parts.push("Removed: <strong>" + diffInfo.removed_count + "</strong> row(s)"); }
                    if (diffInfo.edited_count)  { parts.push("Edited: <strong>" + diffInfo.edited_count + "</strong> row(s)"); }
                    if (colsAdded)   { parts.push("Columns added: <strong>" + colsAdded + "</strong>"); }
                    if (colsRemoved) { parts.push("Columns removed: <strong>" + colsRemoved + "</strong>"); }
                    showMsg("Saved successfully. " + parts.join(", ") + ".", "success");
                } else {
                    showMsg("No changes detected.", "info");
                }

                if (diffInfo.text_diff && diffInfo.text_diff.length) {
                    _actions.renderDiff(diffInfo);
                }

                _state.searchQuery = "";

                reloadCsvQuiet(function () {
                    _state.saving = false;
                });
            })
            .fail(function (xhr) {
                _state.saving = false;
                _state.pendingBulkEditCount = 0;
                handleSaveError(xhr, "Failed to save CSV.");
                _state.currentRows = _state.originalRows.map(function (r) { return $.extend({}, r); });
                _state.currentHeaders = _state.originalHeaders.slice();
                _actions.refreshTable();
            });
            }); // end getAuditComment callback
        }

        var needsGateCheck = false;
        var gateAction = "";
        var gateCount = 0;

        if (addedCount > 0) {
            needsGateCheck = true;
            gateAction = "bulk_row_addition";
            gateCount = addedCount;
        } else if (editedCount >= 2) {
            needsGateCheck = true;
            gateAction = "bulk_row_edit";
            gateCount = editedCount;
        } else if (editedCount > 0) {
            needsGateCheck = true;
            gateAction = "inline_row_edit";
            gateCount = editedCount;
        }

        if (needsGateCheck) {
            restPost({
                action: "check_approval_gate",
                gate_action: gateAction,
                csv_file: _state.selectedCsv,
                app_context: _state.selectedApp,
                selected_count: gateCount
            }).done(function (gateData) {
                if (gateData.requires_approval) {
                    var actionDesc = gateAction === "bulk_row_edit"
                        ? "Editing <strong>" + gateCount + "</strong> row(s)"
                        : "Adding <strong>" + gateCount + "</strong> row(s)";
                    _actions.showRemoveRowModal(
                        "Submit for Approval",
                        actionDesc + " requires admin approval.<br>" +
                            "Reason: " + _.escape(gateData.reason) + "<br><br>" +
                            "Your request will be submitted for review.",
                        function (reason) {
                            if (gateAction === "bulk_row_addition") {
                                _actions.submitApprovalRequest("bulk_row_addition", reason, null, null);
                            } else if (gateAction === "bulk_row_edit") {
                                _actions.submitInlineMultiEditApproval(gateCount, reason);
                            }
                        },
                        {
                            reasonLabel: gateAction === "bulk_row_edit" ? "Reason for bulk edit" : "Reason for adding rows",
                            placeholder: gateAction === "bulk_row_edit" ? "Why are these rows being edited?" : "Why are these rows being added?",
                            confirmText: "Submit",
                            confirmClass: "btn-primary"
                        }
                    );
                } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                    showMsg(formatDailyLimitMsg(gateData.daily_limit), "error");
                } else {
                    proceedWithSave();
                }
            }).fail(function () {
                showMsg("Unable to verify approval gate. Please try again.", "error");
            });
        } else {
            proceedWithSave();
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Row removal — LOCAL for 10 seconds, auto-saves after countdown
    // (Same pattern as column removal: no server call during undo window)
    // ══════════════════════════════════════════════════════════════════
    function doSaveRemoval(removedRow, reason, rowNumber, prevRows, prevOriginal) {
        if (!_state.selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        // Row already spliced from currentRows by caller (wl_table.js)
        pendingRowRemoval = {
            removedRow: removedRow,
            reason: reason,
            rowNumber: rowNumber,
            prevRows: prevRows,
            prevOriginal: prevOriginal
        };

        showRowRemovalUndoBar(removedRow);
    }

    function showRowRemovalUndoBar(removedRow) {
        // Clear any previous timer + column undo, but NOT pendingRowRemoval (just set by caller)
        if (undoTimer) { clearInterval(undoTimer); undoTimer = null; }
        undoState = null;
        pendingColRemoval = null;
        var $bar = _$table.find("#wl-undo-bar");
        if ($bar.length) { $bar.empty(); }

        var rowDesc = [];
        _state.currentHeaders.forEach(function (h) {
            if (h.charAt(0) !== "_" && removedRow[h]) {
                rowDesc.push(removedRow[h]);
            }
        });
        var descText = rowDesc.slice(0, 3).join(", ");
        if (rowDesc.length > 3) { descText += "..."; }
        var desc = 'Row removed: <strong>' + _.escape(descText) +
                   '</strong> — auto-saves when countdown ends';

        $bar.html(
            '<div class="wl-undo">' +
            '<span>' + desc + '</span> ' +
            '<button class="btn btn-small" id="btn-undo">Undo</button> ' +
            '<span class="wl-undo-countdown" id="undo-countdown">10s</span>' +
            '</div>'
        );

        var secondsLeft = 10;
        undoTimer = setInterval(function () {
            secondsLeft--;
            $bar.find("#undo-countdown").text(secondsLeft + "s");
            if (secondsLeft <= 0) {
                clearInterval(undoTimer);
                undoTimer = null;
                $bar.empty();
                commitPendingRowRemoval();
            }
        }, 1000);

        // Delegate on _$table so handler survives table re-renders
        _$table.off("click", "#btn-undo").on("click", "#btn-undo", function () {
            undoRowRemoval();
        });
    }

    function undoRowRemoval() {
        if (!pendingRowRemoval) { return; }
        _state.currentRows = pendingRowRemoval.prevRows.map(function (r) { return $.extend({}, r); });
        pendingRowRemoval = null;
        if (undoTimer) { clearInterval(undoTimer); undoTimer = null; }
        undoState = null;
        var $bar = _$table.find("#wl-undo-bar");
        if ($bar.length) { $bar.empty(); }
        _actions.refreshTable();
        showMsg("Row removal undone.", "info");
    }

    function commitPendingRowRemoval() {
        if (!pendingRowRemoval) { return; }
        var prr = pendingRowRemoval;
        pendingRowRemoval = null;

        showMsg("Saving row removal&hellip;", "info");

        var rmPayload = {
            action:          "save_csv",
            csv_file:        _state.selectedCsv,
            app_context:     _state.selectedApp,
            detection_rule:  _state.selectedRule || "",
            headers:         _state.currentHeaders,
            rows:            _state.currentRows,
            comment:         "Row removal",
            removal_reasons: [{ row: prr.removedRow, reason: prr.reason, row_number: prr.rowNumber }],
            expected_mtime:  _state.loadedMtime,
            expected_content_hash: _state.loadedContentHash
        };
        if (_state.pendingBulkEditCount > 0) {
            rmPayload._bulk_edit_count = _state.pendingBulkEditCount;
        }
        _state.saving = true;
        restPost(rmPayload)
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                _state.currentRows = prr.prevRows.map(function (r) { return $.extend({}, r); });
                _state.originalRows = prr.prevOriginal.map(function (r) { return $.extend({}, r); });
                _actions.refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var rmMsg = "Row removed and saved successfully.";
            if (diffInfo.edited_count > 0) {
                rmMsg = "Row removed and " + diffInfo.edited_count + " row(s) edited. Saved successfully.";
            }
            showMsg(rmMsg, "success");
            _state.originalRows = _state.currentRows.map(function (r) { return $.extend({}, r); });
            _state.originalHeaders = _state.currentHeaders.slice();
            _state.pendingBulkEditCount = 0;
            if (data.file_mtime) { _state.loadedMtime = data.file_mtime; }
            if (typeof data.content_hash === "string" && data.content_hash) { _state.loadedContentHash = data.content_hash; }
            _actions.refreshTable();

            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                _actions.renderDiff(diffInfo);
            }

            _actions.loadVersions(_state.selectedCsv, _state.selectedApp);
        })
        .fail(function (xhr) {
            _state.pendingBulkEditCount = 0;
            handleSaveError(xhr, "Failed to save after removal.");
            _state.currentRows = prr.prevRows.map(function (r) { return $.extend({}, r); });
            _state.originalRows = prr.prevOriginal.map(function (r) { return $.extend({}, r); });
            _actions.refreshTable();
        })
        .always(function () { _state.saving = false; });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save for bulk removal - multiple rows at once
    // ══════════════════════════════════════════════════════════════════
    function doSaveBulkRemoval(removedEntries, reason, prevRows, prevOriginal) {
        if (!_state.selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        showMsg("Removing " + removedEntries.length + " row(s) and saving&hellip;", "info");

        var bulkRemoval = removedEntries.map(function (entry) {
            return {
                row_number: entry.row_number,
                row: entry.row,
                reason: reason
            };
        });

        var bulkRmPayload = {
            action:          "save_csv",
            csv_file:        _state.selectedCsv,
            app_context:     _state.selectedApp,
            detection_rule:  _state.selectedRule || "",
            headers:         _state.currentHeaders,
            rows:            _state.currentRows,
            comment:         "Bulk removal (" + removedEntries.length + " rows)",
            removal_reasons: [],
            bulk_removal:    bulkRemoval,
            expected_mtime:  _state.loadedMtime,
            expected_content_hash: _state.loadedContentHash
        };
        if (_state.pendingBulkEditCount > 0) {
            bulkRmPayload._bulk_edit_count = _state.pendingBulkEditCount;
        }
        _state.saving = true;
        restPost(bulkRmPayload)
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                _state.currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                _state.originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                _actions.refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var bulkMsg = removedEntries.length + " row(s) removed and saved successfully.";
            if (diffInfo.edited_count > 0) {
                bulkMsg = removedEntries.length + " row(s) removed and " + diffInfo.edited_count + " row(s) edited. Saved successfully.";
            }
            showMsg(bulkMsg, "success");
            _state.originalRows = _state.currentRows.map(function (r) { return $.extend({}, r); });
            _state.originalHeaders = _state.currentHeaders.slice();
            _state.pendingBulkEditCount = 0;
            if (data.file_mtime) { _state.loadedMtime = data.file_mtime; }
            if (typeof data.content_hash === "string" && data.content_hash) { _state.loadedContentHash = data.content_hash; }
            _actions.refreshTable();
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                _actions.renderDiff(diffInfo);
            }

            _actions.loadVersions(_state.selectedCsv, _state.selectedApp);
        })
        .fail(function (xhr) {
            _state.pendingBulkEditCount = 0;
            handleSaveError(xhr, "Failed to save after bulk removal.");
            _state.currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            _state.originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            _actions.refreshTable();
        })
        .always(function () { _state.saving = false; });
    }

    // ══════════════════════════════════════════════════════════════════
    // Load CSV content from REST
    // ══════════════════════════════════════════════════════════════════
    function loadCsv(csvFile, appContext) {
        clearMsg();
        _actions.$diff.empty();
        $("#wl-approval-actions").remove();
        $("#wl-addition-preview").remove();
        _state.pendingFilterActive = false;
        _state.pendingFilterIndices = null;
        _$table.html('<p class="wl-muted">Loading CSV content&hellip;</p>');

        restGet({
            action:   "get_csv_content",
            csv_file: csvFile,
            app:      appContext || "",
            tz_offset: new Date().getTimezoneOffset()
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                _$table.empty();
                return;
            }
            _state.expireColumn = data.expire_column || "";
            var autoRemoved = parseInt(data.auto_removed_count, 10);
            if (autoRemoved > 0) {
                showMsg(
                    "<strong>" + autoRemoved + " expired row(s)</strong> " +
                    "were automatically removed.",
                    "warning"
                );
            }
            _state.pendingApprovals = data.pending_approvals || [];
            _state.loadedPendingCount = _state.pendingApprovals.length;
            _actions.buildLockedState();
            _actions.renderTable(data.headers || [], data.rows || []);
            _actions.loadVersions(csvFile, appContext);
            _state.loadedMtime = (data.file_mtime !== undefined && data.file_mtime !== null) ? data.file_mtime : null;
            _state.loadedContentHash = (typeof data.content_hash === "string" && data.content_hash) ? data.content_hash : null;
            startChangeMonitoring();
            _actions.startPresenceMonitoring();
            if (_state.pendingApprovals.length) {
                _actions.applyPendingHighlighting();
            }
            restGet({ action: "get_col_widths", csv_file: csvFile, app: appContext || "" })
                .done(function (wdata) {
                    var w = wdata.col_widths || {};
                    if (Object.keys(w).length) {
                        _actions.applyColWidths(w);
                    }
                });
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                _actions.handleCsvRemoved(csvFile);
                return;
            }
            var err = "Failed to load CSV.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
            _$table.empty();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Silent CSV reload (preserves messages, refreshes metadata)
    // ══════════════════════════════════════════════════════════════════
    function reloadCsvQuiet(callback) {
        if (!_state.selectedCsv) {
            if (callback) { callback(); }
            return;
        }
        restGet({
            action:   "get_csv_content",
            csv_file: _state.selectedCsv,
            app:      _state.selectedApp || "",
            tz_offset: new Date().getTimezoneOffset()
        })
        .done(function (data) {
            if (!data.error) {
                _state.expireColumn = data.expire_column || "";
                var autoRemoved = parseInt(data.auto_removed_count, 10);
                if (autoRemoved > 0) {
                    showMsg(
                        "<strong>" + autoRemoved + " expired row(s)</strong> " +
                        "were automatically removed.",
                        "warning"
                    );
                }
                _actions.renderTable(data.headers || [], data.rows || []);
                _actions.loadVersions(_state.selectedCsv, _state.selectedApp);
                if (data.file_mtime !== undefined && data.file_mtime !== null) { _state.loadedMtime = data.file_mtime; }
                if (typeof data.content_hash === "string" && data.content_hash) { _state.loadedContentHash = data.content_hash; }
                startChangeMonitoring();
            }
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                _actions.handleCsvRemoved(_state.selectedCsv);
            }
        })
        .always(function () {
            if (callback) { callback(); }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Column removal with approval gate check
    // ══════════════════════════════════════════════════════════════════
    function doColumnRemoveWithGateCheck(colName) {
        if (_state.csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }
        restPost({
            action: "check_approval_gate",
            gate_action: "column_removal",
            csv_file: _state.selectedCsv,
            app_context: _state.selectedApp,
            column_name: colName
        }).done(function (gateData) {
            if (gateData.requires_approval) {
                _actions.showRemoveColumnModal(colName, function (reason) {
                    _actions.submitApprovalRequest("column_removal", reason, null, colName);
                });
            } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                showMsg(formatDailyLimitMsg(gateData.daily_limit), "error");
            } else {
                _actions.showRemoveColumnModal(colName, function (reason) {
                    doSaveColumnRemoval(colName, reason);
                });
            }
        }).fail(function () {
            showMsg("Unable to verify approval requirements. Please try again.", "error");
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Public API
    // ══════════════════════════════════════════════════════════════════
    return {
        init: function (opts) {
            _$table  = opts.$table;
            _$msg    = opts.$msg;
            _state   = opts.state;
            _actions = opts.actions;
        },
        doSave:                doSave,
        doSaveRemoval:         doSaveRemoval,
        doSaveBulkRemoval:     doSaveBulkRemoval,
        doSaveColumnAddition:  doSaveColumnAddition,
        doSaveColumnRemoval:   doSaveColumnRemoval,
        doColumnRemoveWithGateCheck: doColumnRemoveWithGateCheck,
        loadCsv:               loadCsv,
        reloadCsvQuiet:        reloadCsvQuiet,
        handleSaveError:       handleSaveError,
        clearUndo:             clearUndo,
        startChangeMonitoring: startChangeMonitoring,
        stopChangeMonitoring:  stopChangeMonitoring,
        hasUnsavedChanges:     hasUnsavedChanges
    };
});
