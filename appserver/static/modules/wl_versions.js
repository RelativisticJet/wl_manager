/**
 * wl_versions.js — Version Control & Revert Module
 *
 * Handles CSV version history: loading versions from backend, rendering
 * the revert dropdown, showing the revert reason modal, and executing
 * reverts (including auto-submission to approval queue for large reverts).
 *
 * Public API:
 *   init(config)                      — wire dependencies, DOM refs, state, callbacks
 *   loadVersions(csvFile, appContext) — fetch version list and render dropdown
 *   hide()                            — hide the revert dropdown (rule clear/switch)
 */
define([
    "jquery",
    "underscore",
    "app/wl_manager/modules/wl_constants",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui"
], function ($, _, C, REST, UI) {
    "use strict";

    // ── Shared state proxy (set by init) ────────────────────────────
    var S = null;

    // ── DOM references (set by init) ────────────────────────────────
    var _dom = {};      // { $revertSelect, $revertGroup }

    // ── Entry-point callbacks (set by init) ─────────────────────────
    var _actions = {};

    // ── Module aliases ──────────────────────────────────────────────
    var restGet  = REST.restGet;
    var restPost = REST.restPost;
    var showMsg  = UI.showMsg;

    // ── Module-internal state ───────────────────────────────────────
    var versionsList = [];

    // ══════════════════════════════════════════════════════════════════
    // Init
    // ══════════════════════════════════════════════════════════════════

    function init(config) {
        S        = config.state;
        _dom     = config.dom     || {};
        _actions = config.actions || {};

        // Bind revert dropdown change event
        _dom.$revertSelect.on("change", function () {
            var val = $(this).val();
            if (!val) { return; }
            if (S.csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                $(this).prop("selectedIndex", 0);
                return;
            }

            var $opt = $(this).find("option:selected");
            var versionDisplay = $opt.data("display") || "";

            showRevertModal(val, versionDisplay, function () {
                // Reset to first option so the same version can be selected again
                _dom.$revertSelect.prop("selectedIndex", 0);
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Load versions from backend
    // ══════════════════════════════════════════════════════════════════

    function loadVersions(csvFile, appContext) {
        restGet({
            action:   "get_versions",
            csv_file: csvFile,
            app:      appContext || ""
        })
        .done(function (data) {
            versionsList = data.versions || [];
            renderVersionsDropdown();
        })
        .fail(function () {
            versionsList = [];
            renderVersionsDropdown();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Render dropdown options
    // ══════════════════════════════════════════════════════════════════

    function renderVersionsDropdown() {
        _dom.$revertSelect.empty();

        if (!versionsList.length) {
            _dom.$revertSelect.append('<option value="">-- No previous versions --</option>');
            _dom.$revertSelect.prop("disabled", true);
            _dom.$revertGroup.show();
            return;
        }

        function versionLabel(v, isCurrent) {
            var rowWord = v.row_count === 1 ? "row" : "rows";
            var colWord = (v.col_count || 0) === 1 ? "column" : "columns";
            var parts = v.row_count + " " + rowWord;
            if (v.col_count && v.col_count > 0) {
                parts += " - " + v.col_count + " " + colWord;
            }
            if (isCurrent) {
                return v.display + " (current)";
            }
            return v.display + " (" + parts + " - " + v.analyst + ")";
        }

        // Latest version is the current state — show it as a non-selectable header
        var current = versionsList[versionsList.length - 1];
        _dom.$revertSelect.append(
            '<option value="" selected="selected">' +
            _.escape(versionLabel(current, true)) +
            '</option>'
        );

        // Previous versions (up to 5) — newest first
        var previous = versionsList.slice(0, versionsList.length - 1);
        for (var i = previous.length - 1; i >= 0; i--) {
            var v = previous[i];
            _dom.$revertSelect.append(
                '<option value="' + _.escape(v.filename) + '" ' +
                'data-display="' + _.escape(v.display) + '">' +
                _.escape(versionLabel(v, false)) +
                '</option>'
            );
        }
        _dom.$revertSelect.prop("disabled", !previous.length);
        _dom.$revertGroup.show();
    }

    // ══════════════════════════════════════════════════════════════════
    // Revert confirmation modal
    // ══════════════════════════════════════════════════════════════════

    function showRevertModal(versionFilename, versionDisplay, onClose) {
        $(".wl-modal-overlay").remove();

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Revert to Previous Version</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>This version of the lookup file will now be loaded. ' +
                        'Unsaved changes will be overridden.</p>' +
                        '<p>Reverting to: <strong>' + _.escape(versionDisplay) + '</strong></p>' +
                        '<label class="wl-dp-label">Please provide a reason why revert is used:</label>' +
                        '<textarea id="wl-revert-reason" class="wl-input" rows="3" ' +
                        'maxlength="500" placeholder="Reason for revert (required)" ' +
                        'style="width:100%;resize:vertical"></textarea>' +
                        '<div class="wl-char-counter" data-for="wl-revert-reason">0 / 500</div>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-primary" id="wl-revert-ok">OK</button> ' +
                        '<button type="button" class="btn" id="wl-revert-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("click", "#wl-revert-ok", function () {
            var $input = $modal.find("#wl-revert-reason");
            var reason = $input.val().trim();
            if (!reason) {
                $input.addClass("wl-input-error");
                return;
            }
            if (C.NON_ASCII_RE.test(reason)) {
                $input.addClass("wl-input-error");
                UI.showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }
            $modal.remove();
            doRevert(versionFilename, versionDisplay, reason);
        });

        $modal.on("click", "#wl-revert-cancel", function () {
            $modal.remove();
            if (onClose) { onClose(); }
        });

        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) {
                $modal.remove();
                if (onClose) { onClose(); }
            }
        });

        setTimeout(function () {
            $modal.find("#wl-revert-reason").focus();
        }, 100);
    }

    // ══════════════════════════════════════════════════════════════════
    // Execute revert (POST to backend, handle approval fallback)
    // ══════════════════════════════════════════════════════════════════

    function doRevert(versionFilename, versionDisplay, reason) {
        if (S.saving) { return; }
        if (S.csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }
        S.saving = true;

        showMsg("Reverting to version " + _.escape(versionDisplay) + "&hellip;", "info");

        restPost({
            action:           "revert_csv",
            csv_file:         S.selectedCsv,
            app_context:      S.selectedApp,
            detection_rule:   S.selectedRule || "",
            version_filename: versionFilename,
            version_display:  versionDisplay,
            revert_reason:    reason,
            expected_mtime:   S.loadedMtime,
            expected_content_hash: S.loadedContentHash
        })
        .done(function (data) {
            if (data.error) {
                S.saving = false;
                showMsg(_.escape(data.error), "error");
                return;
            }

            var revertMsg = "Reverted successfully to version " + _.escape(versionDisplay) + ".";
            var details = [];
            if (data.rows_before !== data.rows_after) {
                details.push("Rows: " + _.escape(String(data.rows_before)) + " &rarr; " + _.escape(String(data.rows_after)));
            }
            if (data.cols_before !== undefined && data.cols_before !== data.cols_after) {
                details.push("Columns: " + _.escape(String(data.cols_before)) + " &rarr; " + _.escape(String(data.cols_after)));
            }
            if (details.length) { revertMsg += "<br>" + details.join(" &nbsp;|&nbsp; "); }
            showMsg(revertMsg, "success");

            var diffInfo = data.diff || {};
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                _actions.renderDiff(diffInfo);
            }

            // Reload the CSV from server to show reverted content
            _actions.reloadCsvQuiet(function () {
                S.saving = false;
            });
        })
        .fail(function (xhr) {
            S.saving = false;
            var err = "Failed to revert.";
            try {
                var resp = JSON.parse(xhr.responseText);
                err = resp.error || err;
                if (resp.requires_approval) {
                    // Auto-submit an approval request for the large revert
                    var desc = "Revert " + S.selectedCsv + " to version " + versionDisplay;
                    var changeParts = [];
                    if (resp.revert_row_changes) changeParts.push(resp.revert_row_changes + " row changes");
                    if (resp.revert_col_changes) changeParts.push(resp.revert_col_changes + " column changes");
                    if (changeParts.length) desc += " (" + changeParts.join(", ") + ")";

                    showMsg("Large revert requires approval. Submitting request&hellip;", "info");

                    restPost({
                        action: "submit_approval",
                        approval_action_type: "revert",
                        csv_file: S.selectedCsv,
                        app_context: S.selectedApp,
                        detection_rule: S.selectedRule || "",
                        description: desc,
                        original_payload: {
                            action: "revert_csv",
                            csv_file: S.selectedCsv,
                            app_context: S.selectedApp,
                            detection_rule: S.selectedRule || "",
                            version_filename: versionFilename,
                            version_display: versionDisplay,
                            revert_reason: reason
                        },
                        expected_mtime: S.loadedMtime,
                        expected_content_hash: S.loadedContentHash,
                        pending_highlight: {
                            type: "revert",
                            version_filename: versionFilename,
                            version_display: versionDisplay
                        }
                    })
                    .done(function (data) {
                        if (data.error) {
                            showMsg(_.escape(data.error), "error");
                            return;
                        }
                        showMsg(
                            "Your revert request has been submitted for approval. " +
                            "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                            "success"
                        );
                        // Reload to show CSV lock status
                        _actions.loadCsv(S.selectedCsv, S.selectedApp);
                    })
                    .fail(function (xhr2) {
                        var err2 = "Failed to submit approval request.";
                        try { err2 = JSON.parse(xhr2.responseText).error || err2; }
                        catch (e2) { console.warn("wl_manager: failed to parse error response", e2); }
                        showMsg(_.escape(err2), "error");
                    });
                    return;
                }
            } catch (e) { console.warn("wl_manager: failed to parse revert response", e); }
            _actions.handleSaveError(xhr, "Failed to revert.");
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Hide dropdown (rule clear / rule switch)
    // ══════════════════════════════════════════════════════════════════

    function hide() {
        _dom.$revertGroup.hide();
    }

    // ── Public API ──────────────────────────────────────────────────
    return {
        init:         init,
        loadVersions: loadVersions,
        hide:         hide
    };
});
