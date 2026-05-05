/**
 * wl_modals.js — Modal Dialogs Module
 *
 * All modal dialog UI extracted from the entry point. Covers three groups:
 *
 *   Group A  — Entity CRUD modals: showRemoveModal, showNewRuleModal,
 *              showApprovalReasonPopup, showCreateCsvModal
 *   Group B  — Generic prompt modals: showRemoveRowModal, showRemoveColumnModal
 *   Group C  — Approval action modals: showApproveConfirmModal,
 *              showRejectReasonModal, showCancelRequestModal
 *   Group D  — Bulk edit modal: showBulkEditModal
 *
 * Public API:
 *   init(config)                             — wire state proxy, DOM, callbacks
 *   showRemoveModal(type, name, parentRule)  — remove rule/CSV confirmation
 *   showNewRuleModal()                       — create new detection rule
 *   showApprovalReasonPopup(label, onSubmit) — approval reason dialog
 *   showCreateCsvModal(ruleName)             — create CSV with optional import
 *   showRemoveRowModal(title, body, onConfirm, opts) — row removal reason
 *   showRemoveColumnModal(colName, onConfirm) — column removal reason
 *   showApproveConfirmModal(requestId)       — approve request confirmation
 *   showRejectReasonModal(requestId)         — reject request with reason
 *   showCancelRequestModal(requestId)        — cancel own request with reason
 *   showBulkEditModal()                      — bulk edit selected rows
 */
define([
    "jquery",
    "underscore",
    "app/wl_manager/modules/wl_constants",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui",
    "app/wl_manager/modules/wl_csv_io",
    "app/wl_manager/modules/wl_datepicker"
], function ($, _, C, REST, UI, CsvIO, DatePicker) {
    "use strict";

    // ── Shared state proxy (set by init) ────────────────────────────
    var S = null;

    // ── Entry-point callbacks (set by init) ─────────────────────────
    var _actions = {};

    // ── Module aliases ──────────────────────────────────────────────
    var restGet  = REST.restGet;
    var restPost = REST.restPost;
    var showMsg  = UI.showMsg;
    var IMPORT_MAX_FILE_SIZE = C.IMPORT_MAX_FILE_SIZE;
    var MAX_CELL_CHARS       = C.MAX_CELL_CHARS;
    var formatDailyLimitMsg  = UI.formatDailyLimitMsg;

    // ══════════════════════════════════════════════════════════════════
    // Init
    // ══════════════════════════════════════════════════════════════════

    function init(config) {
        S        = config.state   || {};
        _actions = config.actions || {};
    }

    // ══════════════════════════════════════════════════════════════════
    // GROUP A: Entity CRUD Modals
    // ══════════════════════════════════════════════════════════════════

    // ── Remove Rule or CSV modal ────────────────────────────────────

    function showRemoveModal(type, name, parentRule) {
        $(".wl-modal-overlay").remove();

        var isRule = (type === "rule");
        var title = isRule ? "Remove Detection Rule" : "Remove CSV File";

        // For rules, list affected CSVs
        var affectedCsvs = [];
        if (isRule) {
            S.mappingData.forEach(function (m) {
                if (m.rule_name === name) {
                    affectedCsvs.push(m.csv_file);
                }
            });
        } else {
            // For CSV removal, check if it's the last CSV for the rule
            var ruleCsvCount = 0;
            S.mappingData.forEach(function (m) {
                if (m.rule_name === (parentRule || S.selectedRule)) {
                    ruleCsvCount++;
                }
            });
            if (ruleCsvCount <= 1) {
                title += " (Last CSV)";
            }
        }

        var summaryHtml = '';
        if (isRule) {
            summaryHtml = '<div style="margin-bottom:12px;font-size:13px">' +
                '<strong>Rule:</strong> ' + _.escape(name) + '<br>' +
                '<strong>CSV files (' + affectedCsvs.length + '):</strong> ' +
                (affectedCsvs.length
                    ? affectedCsvs.map(function (c) { return _.escape(c); }).join(', ')
                    : '<em>none</em>') +
                '</div>';
        } else {
            var lastCsvWarning = '';
            var ruleCsvs = S.mappingData.filter(function (m) {
                return m.rule_name === (parentRule || S.selectedRule);
            });
            if (ruleCsvs.length <= 1) {
                lastCsvWarning =
                    '<div style="margin-top:8px;padding:6px 10px;border-radius:4px;' +
                    'background:var(--wl-bg-warning,#fff3cd);color:#856404;font-size:12px">' +
                    'This is the only CSV for rule <strong>' +
                    _.escape(parentRule || S.selectedRule) +
                    '</strong>. Removing it will also remove the rule from the dropdown.' +
                    '</div>';
            }
            summaryHtml = '<div style="margin-bottom:12px;font-size:13px">' +
                '<strong>CSV:</strong> ' + _.escape(name) + '<br>' +
                '<strong>Rule:</strong> ' + _.escape(parentRule || S.selectedRule) +
                lastCsvWarning +
                '</div>';
        }

        var fileWord = isRule
            ? (affectedCsvs.length === 1 ? '1 CSV file' : affectedCsvs.length + ' CSV files')
            : 'the CSV file';

        var html =
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal" style="max-width:520px">' +
                '<div class="wl-modal-header">' + title + '</div>' +
                summaryHtml +
                '<div style="margin-bottom:12px">' +
                    '<label style="display:block;margin-bottom:8px;cursor:pointer">' +
                        '<input type="radio" name="wl-remove-type" value="unlink" checked ' +
                            'style="margin-right:6px" />' +
                        '<strong>Unlink</strong> — remove from mapping only ' +
                        '<span style="color:var(--wl-text-muted);font-size:12px">' +
                        '(files stay on disk)</span>' +
                    '</label>' +
                    '<label style="display:block;cursor:pointer">' +
                        '<input type="radio" name="wl-remove-type" value="permanent" ' +
                            'style="margin-right:6px" />' +
                        '<strong>Delete permanently</strong> — remove from mapping ' +
                        'and delete ' + fileWord + ' from disk ' +
                        '<span style="color:var(--wl-text-muted);font-size:12px">' +
                        '(version history kept as safety net)</span>' +
                    '</label>' +
                '</div>' +
                '<div style="margin-bottom:12px">' +
                    '<label style="display:block;margin-bottom:4px;font-weight:600;font-size:13px">' +
                        'Reason (required)</label>' +
                    '<textarea id="wl-remove-reason" rows="2" maxlength="500" ' +
                        'style="width:100%;box-sizing:border-box;font-family:inherit;' +
                        'font-size:13px;padding:6px 8px;border:1px solid var(--wl-border);' +
                        'border-radius:3px;background:var(--wl-bg-input);color:var(--wl-text);' +
                        'resize:vertical" placeholder="Why is this being removed?"></textarea>' +
                    '<div class="wl-char-counter" data-for="wl-remove-reason">0 / 500</div>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<button type="button" class="btn btn-danger" id="wl-remove-confirm">' +
                        'Remove</button>' +
                    '<button type="button" class="btn" id="wl-remove-cancel">' +
                        'Cancel</button>' +
                '</div>' +
            '</div></div>';

        $("body").append(html);

        setTimeout(function () { $("#wl-remove-reason").focus(); }, 100);

        // Cancel
        $(".wl-modal-overlay").on("click", "#wl-remove-cancel", function () {
            $(".wl-modal-overlay").remove();
        });
        $(".wl-modal-overlay").on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) {
                $(".wl-modal-overlay").remove();
            }
        });

        // Confirm
        $(".wl-modal-overlay").on("click", "#wl-remove-confirm", function () {
            var removalType = $("input[name='wl-remove-type']:checked").val();
            var reason = ($("#wl-remove-reason").val() || "").trim();
            if (!reason) {
                $("#wl-remove-reason").css("border-color", "#e74c3c").attr(
                    "placeholder", "A reason is required!");
                return;
            }
            if (C.NON_ASCII_RE.test(reason)) {
                $("#wl-remove-reason").css("border-color", "#e74c3c");
                showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }

            var $btn = $(this);
            $btn.text("Removing\u2026").css("pointer-events", "none");

            var payload;
            if (isRule) {
                payload = {
                    action: "remove_rule",
                    rule_name: name,
                    removal_type: removalType,
                    comment: reason
                };
            } else {
                payload = {
                    action: "remove_csv",
                    csv_file: name,
                    rule_name: parentRule || S.selectedRule,
                    removal_type: removalType,
                    comment: reason
                };
            }

            // Check reason gate for remove actions
            var gateKey = isRule ? "require_reason_rule_deletion" : "require_reason_csv_deletion";
            if (S.reasonGates[gateKey]) {
                payload.approval_reason = reason;
            }

            restPost(payload)
            .done(function (data) {
                $(".wl-modal-overlay").remove();
                if (data.error) {
                    showMsg(_.escape(data.error), "error");
                    return;
                }
                if (data.request_id) {
                    showMsg(
                        "Your request to remove <strong>" + _.escape(name) +
                        "</strong> has been submitted for admin approval.",
                        "info");
                    return;
                }
                showMsg(_.escape(data.message || "Removed successfully"), "success");

                // Delegate UI reset to entry point
                _actions.onEntityRemoved(isRule, name, parentRule);
            })
            .fail(function (xhr) {
                $(".wl-modal-overlay").remove();
                var errMsg = "Failed to remove";
                try {
                    errMsg = JSON.parse(xhr.responseText).error || errMsg;
                } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
                showMsg(_.escape(errMsg), "error");
            });
        });
    }

    // ── Create New Rule modal ───────────────────────────────────────

    function showNewRuleModal() {
        $(".wl-modal-overlay").remove();

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal" style="max-width:450px">' +
                    '<div class="wl-modal-header">Create New Detection Rule</div>' +
                    '<div class="wl-modal-body">' +
                        '<label class="wl-dp-label">Detection Rule Name:</label>' +
                        '<input type="text" id="wl-new-rule-name" class="wl-input" ' +
                            'placeholder="e.g. DR150_suspicious_activity" ' +
                            'autocomplete="off" style="width:100%" maxlength="100" />' +
                        '<div id="wl-new-rule-error" style="color:#ef9a9a;font-size:12px;margin-top:6px;display:none"></div>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-primary" id="wl-new-rule-ok">Next</button> ' +
                        '<button type="button" class="btn" id="wl-new-rule-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        // Force dark theme on modal inputs
        var darkBg = getComputedStyle(document.documentElement).getPropertyValue("--wl-bg-input").trim() || "#1a1c1e";
        var darkTxt = getComputedStyle(document.documentElement).getPropertyValue("--wl-text").trim() || "#e0e0e0";
        $modal.find(".wl-input").css({ "background-color": darkBg, "color": darkTxt });

        function validate() {
            var name = $modal.find("#wl-new-rule-name").val().trim();
            var $err = $modal.find("#wl-new-rule-error");
            $err.hide();

            if (!name) {
                $err.text("Detection rule name is required.").show();
                return;
            }
            if (/[^a-zA-Z0-9_\-. ]/.test(name)) {
                $err.text("Rule name can only contain letters, numbers, underscores, hyphens, dots, and spaces.").show();
                return;
            }
            if (!/[a-zA-Z0-9]/.test(name)) {
                $err.text("Rule name must contain at least one letter or number.").show();
                return;
            }
            var exists = S.allRules.some(function (r) {
                return r.toLowerCase() === name.toLowerCase();
            });
            if (exists) {
                $err.text("Rule '" + _.escape(name) + "' already exists. Select it from the dropdown instead.").show();
                return;
            }

            var createPayload = { action: "create_rule", detection_rule: name };

            function submitCreateRule(payload) {
                $modal.find("#wl-new-rule-ok").addClass("disabled").text("Creating...");
                restPost(payload)
                .done(function (resp) {
                    $modal.remove();
                    if (resp.request_id) {
                        showMsg(
                            "Your request to create rule <strong>" + _.escape(name) +
                            "</strong> has been submitted for admin approval.",
                            "info");
                        return;
                    }
                    _actions.onRuleCreated(name);
                })
                .fail(function (xhr) {
                    var errMsg = "Failed to create detection rule.";
                    try {
                        var r = JSON.parse(xhr.responseText);
                        if (r.error) { errMsg = r.error; }
                    } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
                    $err.text(errMsg).show();
                    $modal.find("#wl-new-rule-ok").removeClass("disabled").text("Next");
                });
            }

            if (S.reasonGates.require_reason_rule_creation) {
                showApprovalReasonPopup("Create rule '" + name + "'", function (reason) {
                    createPayload.approval_reason = reason;
                    submitCreateRule(createPayload);
                });
                return;
            }
            submitCreateRule(createPayload);
        }

        $modal.on("click", "#wl-new-rule-ok", validate);
        $modal.on("click", "#wl-new-rule-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
        $modal.on("keydown", "#wl-new-rule-name", function (e) {
            if (e.which === 13) { e.preventDefault(); validate(); }
        });

        setTimeout(function () { $modal.find("#wl-new-rule-name").focus(); }, 100);
    }

    // ── Approval reason popup (shared by gated create/delete flows) ─

    function showApprovalReasonPopup(actionLabel, onSubmit) {
        $(".wl-approval-reason-overlay").remove();
        var html =
            '<div class="wl-modal-overlay wl-approval-reason-overlay">' +
                '<div class="wl-modal" style="max-width:440px">' +
                    '<div class="wl-modal-header">Approval Required</div>' +
                    '<p style="margin:0 0 12px;font-size:13px;color:var(--wl-text-muted,#999)">' +
                        'This action requires admin approval. Please provide a reason for: ' +
                        '<strong>' + _.escape(actionLabel) + '</strong></p>' +
                    '<textarea id="wl-approval-reason-text" class="wl-input" ' +
                        'style="width:100%;height:80px;resize:vertical;font-size:13px" ' +
                        'placeholder="Reason for this request (required)" maxlength="500"></textarea>' +
                    '<div class="wl-char-counter" data-for="wl-approval-reason-text">0 / 500</div>' +
                    '<div id="wl-approval-reason-error" class="wl-msg-error" style="display:none;margin-top:6px"></div>' +
                    '<div class="wl-modal-actions" style="margin-top:12px">' +
                        '<button type="button" class="btn btn-primary" id="wl-approval-reason-ok">Submit Request</button> ' +
                        '<button type="button" class="btn" id="wl-approval-reason-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>';
        var $popup = $(html);
        $("body").append($popup);

        $popup.on("click", "#wl-approval-reason-ok", function () {
            var reason = $popup.find("#wl-approval-reason-text").val().trim();
            if (!reason) {
                $popup.find("#wl-approval-reason-error").text("A reason is required.").show();
                return;
            }
            if (C.NON_ASCII_RE.test(reason)) {
                $popup.find("#wl-approval-reason-error").text(C.ASCII_ERROR_MSG).show();
                return;
            }
            $popup.remove();
            onSubmit(reason);
        });
        $popup.on("click", "#wl-approval-reason-cancel", function () { $popup.remove(); });
        $popup.on("click", function (e) {
            if ($(e.target).hasClass("wl-approval-reason-overlay")) { $popup.remove(); }
        });
        $popup.on("keydown", function (e) {
            if (e.key === "Escape") { $popup.remove(); }
        });
        setTimeout(function () { $popup.find("#wl-approval-reason-text").focus(); }, 100);
    }

    // ── Create CSV modal ────────────────────────────────────────────

    function showCreateCsvModal(ruleName) {
        $(".wl-modal-overlay").remove();

        var safeName = ruleName.replace(/[^a-zA-Z0-9_\-]/g, "_");
        var suggestedFile = safeName + ".csv";

        restGet({ action: "get_apps" }).done(function (appData) {
            var apps = (appData.apps || []);
            var defaultApp = appData.default_app || "wl_manager";

            var appOptions = "";
            apps.forEach(function (a) {
                var sel = a.name === defaultApp ? " selected" : "";
                appOptions += '<option value="' + _.escape(a.name) + '"' + sel + '>' +
                    _.escape(a.name) + (a.has_lookups ? "" : " (no lookups/)") +
                    '</option>';
            });

            var html =
                '<div class="wl-modal-overlay">' +
                    '<div class="wl-modal" style="max-width:560px">' +
                        '<div class="wl-modal-header">Create CSV Whitelist</div>' +
                        '<div class="wl-modal-body">' +
                            '<p style="margin:0 0 12px 0;font-size:13px">Create a new CSV whitelist for <strong>' +
                                _.escape(ruleName) + '</strong>.</p>' +

                            '<div class="wl-import-section">' +
                                '<label>Import from CSV file</label>' +
                                '<div class="wl-import-file-row">' +
                                    '<input type="file" accept=".csv" id="wl-import-file" class="wl-import-file-hidden" />' +
                                    '<button type="button" class="btn wl-import-file-btn" id="wl-import-file-trigger">Choose File</button>' +
                                    '<span class="wl-import-file-name" id="wl-import-file-label">No file chosen</span>' +
                                    '<span class="wl-import-clear" id="wl-import-clear" style="display:none">Clear</span>' +
                                '</div>' +
                            '</div>' +

                            '<div class="wl-import-divider">or create manually</div>' +

                            '<label class="wl-dp-label">Target App:</label>' +
                            '<select id="wl-create-csv-app" class="wl-input" style="width:100%">' +
                                appOptions +
                            '</select>' +
                            '<div id="wl-create-csv-app-warn" class="wl-crossapp-warning" style="display:none">' +
                                '<strong>Warning:</strong> This CSV will be created inside another app\'s lookups/ directory. ' +
                                'Ensure you have the appropriate permissions and that this is intentional.' +
                            '</div>' +
                            '<label class="wl-dp-label" style="margin-top:10px">CSV File Name:</label>' +
                            '<input type="text" id="wl-create-csv-name" class="wl-input" ' +
                                'value="' + _.escape(suggestedFile) + '" ' +
                                'autocomplete="off" style="width:100%" maxlength="100" />' +
                            '<div id="wl-create-csv-headers-manual">' +
                                '<label class="wl-dp-label" style="margin-top:10px">Column Headers (comma-separated):</label>' +
                                '<input type="text" id="wl-create-csv-headers" class="wl-input" ' +
                                    'placeholder="e.g. user, src_ip, Comment, Expires" ' +
                                    'autocomplete="off" style="width:100%" maxlength="500" />' +
                            '</div>' +
                            '<div id="wl-create-csv-headers-imported" style="display:none">' +
                                '<label class="wl-dp-label" style="margin-top:10px">Column Headers (from imported file):</label>' +
                                '<div class="wl-import-headers-display" id="wl-import-headers-text"></div>' +
                            '</div>' +

                            '<div id="wl-import-messages" class="wl-import-messages" style="display:none"></div>' +
                            '<div id="wl-create-csv-error" style="color:#ef9a9a;font-size:12px;margin-top:6px;display:none"></div>' +
                            '<div id="wl-import-preview" style="display:none"></div>' +
                        '</div>' +
                        '<div class="wl-modal-actions">' +
                            '<button type="button" class="btn btn-primary" id="wl-create-csv-ok">Create</button> ' +
                            '<button type="button" class="btn" id="wl-create-csv-cancel">Cancel</button>' +
                        '</div>' +
                    '</div>' +
                '</div>';

            var $modal = $(html);
            $("body").append($modal);

            // Force dark theme on modal inputs
            var darkBg = getComputedStyle(document.documentElement).getPropertyValue("--wl-bg-input").trim() || "#1a1c1e";
            var darkTxt = getComputedStyle(document.documentElement).getPropertyValue("--wl-text").trim() || "#e0e0e0";
            $modal.find(".wl-input").css({ "background-color": darkBg, "color": darkTxt });

            _bindCreateCsvEvents($modal, ruleName, defaultApp);

            $modal.on("click", "#wl-import-file-trigger", function () {
                $modal.find("#wl-import-file").trigger("click");
            });

            setTimeout(function () { $modal.find("#wl-import-file-trigger").focus(); }, 100);
        });
    }

    function _bindCreateCsvEvents($modal, ruleName, defaultApp) {

        // ── Import state ──
        var importedHeaders = null;
        var importedRows = null;

        // ── File input handler ──
        $modal.on("change", "#wl-import-file", function (e) {
            var file = e.target.files && e.target.files[0];
            if (!file) return;

            var $err = $modal.find("#wl-create-csv-error");
            var $msgs = $modal.find("#wl-import-messages");
            var $preview = $modal.find("#wl-import-preview");
            $err.hide();
            $msgs.empty().hide();
            $preview.empty().hide();

            if (file.size > IMPORT_MAX_FILE_SIZE) {
                var sizeMB = (file.size / (1024 * 1024)).toFixed(1);
                $err.text("File is too large (" + sizeMB + " MB). Maximum allowed is 2 MB.").show();
                resetImportMode();
                return;
            }

            if (!file.name.toLowerCase().endsWith(".csv")) {
                $err.text("Only .csv files are accepted.").show();
                resetImportMode();
                return;
            }

            var reader = new FileReader();
            reader.onload = function (ev) {
                var text = ev.target.result;
                var parsed = CsvIO.parseCSV(text);

                if (parsed.errors.length > 0 && parsed.headers.length === 0) {
                    $err.text(parsed.errors[0]).show();
                    resetImportMode();
                    return;
                }

                var validation = CsvIO.validateImportedCSV(file.name, parsed.headers, parsed.rows);
                parsed.errors.forEach(function (e) { validation.errors.unshift(e); });

                CsvIO.renderImportMessages(validation.errors, validation.warnings, $msgs);

                if (validation.errors.length > 0) {
                    $modal.find("#wl-create-csv-ok").addClass("disabled");
                } else {
                    $modal.find("#wl-create-csv-ok").removeClass("disabled");
                }

                importedHeaders = parsed.headers;
                importedRows = parsed.rows;

                $modal.find("#wl-create-csv-name").val(file.name);
                $modal.find("#wl-create-csv-headers-manual").hide();
                $modal.find("#wl-import-headers-text").text(parsed.headers.join(", "));
                $modal.find("#wl-create-csv-headers-imported").show();
                $modal.find("#wl-import-file-label").text(file.name);
                $modal.find("#wl-import-clear").show();

                if (validation.errors.length === 0) {
                    CsvIO.renderImportPreview(parsed.headers, parsed.rows, $preview);
                }
            };

            reader.onerror = function () {
                $err.text("Failed to read file. Please try again.").show();
                resetImportMode();
            };

            reader.readAsText(file, "UTF-8");
        });

        // ── Clear import ──
        function resetImportMode() {
            importedHeaders = null;
            importedRows = null;
            $modal.find("#wl-import-file").val("");
            $modal.find("#wl-import-file-label").text("No file chosen");
            $modal.find("#wl-import-clear").hide();
            $modal.find("#wl-create-csv-headers-manual").show();
            $modal.find("#wl-create-csv-headers-imported").hide();
            $modal.find("#wl-import-messages").empty().hide();
            $modal.find("#wl-import-preview").empty().hide();
            $modal.find("#wl-create-csv-ok").removeClass("disabled").text("Create");
        }

        $modal.on("click", "#wl-import-clear", function () {
            resetImportMode();
            var safeName = ruleName.replace(/[^a-zA-Z0-9_\-]/g, "_");
            $modal.find("#wl-create-csv-name").val(safeName + ".csv");
        });

        // ── Create button ──
        function validateAndCreate() {
            var csvName = $modal.find("#wl-create-csv-name").val().trim();
            var selectedApp = $modal.find("#wl-create-csv-app").val();
            var $err = $modal.find("#wl-create-csv-error");
            $err.hide();

            if (!csvName) {
                $err.text("CSV file name is required.").show();
                return;
            }
            if (!csvName.toLowerCase().endsWith(".csv")) {
                csvName += ".csv";
            }
            if (/[^a-zA-Z0-9_\-.]/.test(csvName)) {
                $err.text("File name can only contain letters, numbers, underscores, hyphens, and dots.").show();
                return;
            }
            var csvStem = csvName.replace(/\.csv$/i, "");
            if (!/[a-zA-Z0-9]/.test(csvStem)) {
                $err.text("File name must contain at least one letter or number.").show();
                return;
            }

            var headers, payload;

            if (importedHeaders) {
                headers = importedHeaders;
                payload = {
                    action: "create_csv",
                    detection_rule: ruleName,
                    csv_file: csvName,
                    headers: headers,
                    app_context: selectedApp,
                    initial_rows: importedRows
                };
            } else {
                var headersStr = $modal.find("#wl-create-csv-headers").val().trim();
                if (!headersStr) {
                    $err.text("At least one column header is required.").show();
                    return;
                }
                headers = headersStr.split(",").map(function (h) { return h.trim(); }).filter(Boolean);
                if (!headers.length) {
                    $err.text("At least one non-empty column header is required.").show();
                    return;
                }
                var seen = {};
                for (var i = 0; i < headers.length; i++) {
                    var lc = headers[i].toLowerCase();
                    if (seen[lc]) {
                        $err.text("Duplicate column header: '" + _.escape(headers[i]) + "'").show();
                        return;
                    }
                    seen[lc] = true;
                }
                var safeColNameRe = /^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-.()\/:&#@+]+$/;
                for (var j = 0; j < headers.length; j++) {
                    if (/\s/.test(headers[j])) {
                        $err.text("Column '" + _.escape(headers[j].substring(0, 30)) +
                            "' cannot contain spaces. Use underscores instead (e.g. 'src_ip').").show();
                        return;
                    }
                    if (headers[j].charAt(0) === "_") {
                        $err.text('Column names starting with "_" are reserved.').show();
                        return;
                    }
                    if (!safeColNameRe.test(headers[j])) {
                        $err.text("Column '" + _.escape(headers[j].substring(0, 20)) +
                            "' is invalid. Must contain at least one letter or number. Only letters, numbers, and _-.()/:#@&+ are allowed.").show();
                        return;
                    }
                    if (headers[j].length > 64) {
                        $err.text("Column header '" + _.escape(headers[j].substring(0, 20)) +
                            "...' is too long (" + headers[j].length + " chars, max 64).").show();
                        return;
                    }
                }
                payload = {
                    action: "create_csv",
                    detection_rule: ruleName,
                    csv_file: csvName,
                    headers: headers,
                    app_context: selectedApp
                };
            }

            if (S.reasonGates.require_reason_csv_creation) {
                showApprovalReasonPopup("Create " + csvName, function (reason) {
                    payload.approval_reason = reason;
                    submitCreateCsv(payload, csvName, headers, selectedApp);
                });
                return;
            }

            submitCreateCsv(payload, csvName, headers, selectedApp);
        }

        function submitCreateCsv(payload, csvName, headers, selectedApp) {
            $modal.find("#wl-create-csv-ok").addClass("disabled").text("Creating...");

            restPost(payload)
            .done(function (resp) {
                $modal.remove();
                if (resp.request_id) {
                    showMsg(
                        "Your request to create CSV <strong>" + _.escape(csvName) +
                        "</strong> has been submitted for admin approval.",
                        "info"
                    );
                    return;
                }
                var appNote = selectedApp !== defaultApp
                    ? " in app <strong>" + _.escape(selectedApp) + "</strong>"
                    : "";
                var rowNote = importedRows && importedRows.length
                    ? " with " + importedRows.length + " imported row(s)"
                    : "";
                showMsg(
                    "CSV <strong>" + _.escape(csvName) + "</strong> created with " +
                    headers.length + " column(s)" + rowNote + " for <strong>" +
                    _.escape(ruleName) + "</strong>" + appNote + ".",
                    "info"
                );
                _actions.onCsvCreated(ruleName, csvName);
            })
            .fail(function (xhr) {
                var errMsg = "Failed to create CSV.";
                try {
                    var r = JSON.parse(xhr.responseText);
                    if (r.error) { errMsg = r.error; }
                } catch (ignored) {}
                $modal.find("#wl-create-csv-error").text(errMsg).show();
                $modal.find("#wl-create-csv-ok").removeClass("disabled").text("Create");
            });
        }

        $modal.on("click", "#wl-create-csv-ok", function () {
            if (!$(this).hasClass("disabled")) { validateAndCreate(); }
        });
        $modal.on("click", "#wl-create-csv-cancel", function () { $modal.remove(); });
        $modal.on("keydown", function (e) {
            if (e.key === "Escape") { $modal.remove(); }
        });

        $modal.on("change", "#wl-create-csv-app", function () {
            var sel = $(this).val();
            $modal.find("#wl-create-csv-app-warn").toggle(sel !== defaultApp);
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // GROUP B: Generic Prompt Modals
    // ══════════════════════════════════════════════════════════════════

    // ── Remove Row modal (single or bulk) ───────────────────────────

    function showRemoveRowModal(title, bodyHtml, onConfirm, opts) {
        $(".wl-modal-overlay").remove();

        var o = opts || {};
        var reasonLabel = o.reasonLabel || "Reason for removal";
        var placeholder = o.placeholder || "Why is this row being removed?";
        var confirmText = o.confirmText || "Remove";
        var confirmClass = o.confirmClass || "btn-danger";

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">' + title + '</div>' +
                    '<div class="wl-modal-body">' +
                        bodyHtml + '<br>' +
                        '<label class="wl-modal-label">' + reasonLabel + ' <span style="color:#e74c3c">*</span></label>' +
                        '<textarea id="wl-rmrow-reason" class="wl-modal-input" rows="2" ' +
                            'maxlength="500" placeholder="' + _.escape(placeholder) + '"></textarea>' +
                        '<div class="wl-char-counter" data-for="wl-rmrow-reason">0 / 500</div>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn ' + confirmClass + '" id="wl-rmrow-ok" style="opacity:0.5;pointer-events:none">' + _.escape(confirmText) + '</button> ' +
                        '<button type="button" class="btn" id="wl-rmrow-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("input", "#wl-rmrow-reason", function () {
            var hasReason = $.trim($(this).val()).length > 0;
            $modal.find("#wl-rmrow-ok").css({
                opacity: hasReason ? 1 : 0.5,
                "pointer-events": hasReason ? "auto" : "none"
            });
        });

        $modal.on("click", "#wl-rmrow-ok", function () {
            var reason = $.trim($modal.find("#wl-rmrow-reason").val());
            if (!reason) { return; }
            if (C.NON_ASCII_RE.test(reason)) {
                $modal.find("#wl-rmrow-reason").addClass("wl-input-error");
                showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }
            $modal.remove();
            if (onConfirm) { onConfirm(reason); }
        });
        $modal.on("click", "#wl-rmrow-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
        $modal.on("keydown", "#wl-rmrow-reason", function (e) {
            if (e.which === 13 && !e.shiftKey) {
                e.preventDefault();
                $modal.find("#wl-rmrow-ok").trigger("click");
            }
        });

        setTimeout(function () { $modal.find("#wl-rmrow-reason").focus(); }, 100);
    }

    // ── Remove Column modal ─────────────────────────────────────────

    function showRemoveColumnModal(colName, onConfirm) {
        $(".wl-modal-overlay").remove();

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Remove Column</div>' +
                    '<div class="wl-modal-body">' +
                        'Remove column <strong>' + _.escape(colName) + '</strong>?<br><br>' +
                        'This will delete this column and all its data from every row.<br><br>' +
                        '<label class="wl-modal-label">Reason for removal <span style="color:#e74c3c">*</span></label>' +
                        '<textarea id="wl-rmcol-reason" class="wl-modal-input" rows="2" ' +
                            'maxlength="500" placeholder="Why is this column being removed?"></textarea>' +
                        '<div class="wl-char-counter" data-for="wl-rmcol-reason">0 / 500</div>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-danger" id="wl-rmcol-ok" style="opacity:0.5;pointer-events:none">Remove</button> ' +
                        '<button type="button" class="btn" id="wl-rmcol-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("input", "#wl-rmcol-reason", function () {
            var hasReason = $.trim($(this).val()).length > 0;
            $modal.find("#wl-rmcol-ok").css({
                opacity: hasReason ? 1 : 0.5,
                "pointer-events": hasReason ? "auto" : "none"
            });
        });

        $modal.on("click", "#wl-rmcol-ok", function () {
            var reason = $.trim($modal.find("#wl-rmcol-reason").val());
            if (!reason) { return; }
            if (C.NON_ASCII_RE.test(reason)) {
                $modal.find("#wl-rmcol-reason").addClass("wl-input-error");
                showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }
            $modal.remove();
            if (onConfirm) { onConfirm(reason); }
        });
        $modal.on("click", "#wl-rmcol-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // GROUP C: Approval Action Modals
    // ══════════════════════════════════════════════════════════════════

    // ── Approve confirmation ────────────────────────────────────────

    function showApproveConfirmModal(requestId) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Approve Request</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>Approve this request? The action will be executed immediately.</p>' +
                        '<p>Request ID: <strong>' + _.escape(requestId) + '</strong></p>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-primary" id="wl-approve-ok">Approve</button> ' +
                        '<button type="button" class="btn" id="wl-approve-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>'
        );
        $("body").append($modal);

        $modal.on("click", "#wl-approve-ok", function () {
            $modal.remove();
            var $btn = $(".wl-approve-btn").filter(function () { return $(this).data("id") === requestId; });
            $btn.text("Approving\u2026").css("pointer-events", "none");
            restPost({
                action: "process_approval",
                request_id: requestId,
                decision: "approve"
            }).done(function (data) {
                if (data.error) {
                    showMsg(_.escape(data.error), "error");
                    $btn.text("Approve").css("pointer-events", "auto");
                } else {
                    showMsg(_.escape(data.message || "Request approved and executed."), "success");
                    _actions.reloadCsv();
                }
            }).fail(function (xhr) {
                var err = "Failed to process approval.";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
                showMsg(_.escape(err), "error");
                $btn.text("Approve").css("pointer-events", "auto");
            });
        });

        $modal.on("click", "#wl-approve-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
    }

    // ── Reject with reason ──────────────────────────────────────────

    function showRejectReasonModal(requestId) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Reject Request</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>Request ID: <strong>' + _.escape(requestId) + '</strong></p>' +
                        '<label class="wl-modal-label">Reason for rejection ' +
                            '<span style="color:#e74c3c">*</span></label>' +
                        '<textarea id="wl-inline-reject-reason" class="wl-modal-input" rows="3" ' +
                            'maxlength="500" placeholder="Why is this request being rejected?"></textarea>' +
                        '<div class="wl-char-counter" data-for="wl-inline-reject-reason">0 / 500</div>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-danger" id="wl-inline-reject-ok" ' +
                            'style="opacity:0.5;pointer-events:none">Reject</button> ' +
                        '<button type="button" class="btn" id="wl-inline-reject-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>'
        );
        $("body").append($modal);

        $modal.on("input", "#wl-inline-reject-reason", function () {
            var hasReason = $.trim($(this).val()).length > 0;
            $modal.find("#wl-inline-reject-ok").css({
                opacity: hasReason ? 1 : 0.5,
                "pointer-events": hasReason ? "auto" : "none"
            });
        });

        $modal.on("click", "#wl-inline-reject-ok", function () {
            var reason = $.trim($modal.find("#wl-inline-reject-reason").val());
            if (!reason) { return; }
            if (C.NON_ASCII_RE.test(reason)) {
                $modal.find("#wl-inline-reject-reason").addClass("wl-input-error");
                showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }
            $modal.remove();
            var $btn = $(".wl-reject-btn").filter(function () { return $(this).data("id") === requestId; });
            $btn.text("Rejecting\u2026").css("pointer-events", "none");
            restPost({
                action: "process_approval",
                request_id: requestId,
                decision: "reject",
                rejection_reason: reason
            }).done(function (data) {
                if (data.error) {
                    showMsg(_.escape(data.error), "error");
                    $btn.text("Reject").css("pointer-events", "auto");
                } else {
                    showMsg(_.escape(data.message || "Request rejected."), "success");
                    _actions.reloadCsv();
                }
            }).fail(function (xhr) {
                var err = "Failed to reject request.";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
                showMsg(_.escape(err), "error");
                $btn.text("Reject").css("pointer-events", "auto");
            });
        });

        $modal.on("click", "#wl-inline-reject-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });

        setTimeout(function () { $modal.find("#wl-inline-reject-reason").focus(); }, 100);
    }

    // ── Cancel own request ──────────────────────────────────────────

    function showCancelRequestModal(requestId) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Cancel Request</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>Request ID: <strong>' + _.escape(requestId) + '</strong></p>' +
                        '<label class="wl-modal-label">Reason for cancellation ' +
                            '<span style="color:#e74c3c">*</span></label>' +
                        '<textarea id="wl-inline-cancel-reason" class="wl-modal-input" rows="3" ' +
                            'maxlength="500" placeholder="Why are you cancelling this request?"></textarea>' +
                        '<div class="wl-char-counter" data-for="wl-inline-cancel-reason">0 / 500</div>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-warning" id="wl-inline-cancel-ok" ' +
                            'style="opacity:0.5;pointer-events:none">Cancel Request</button> ' +
                        '<button type="button" class="btn" id="wl-inline-cancel-dismiss">Close</button>' +
                    '</div>' +
                '</div>' +
            '</div>'
        );
        $("body").append($modal);

        $modal.on("input", "#wl-inline-cancel-reason", function () {
            var hasReason = $.trim($(this).val()).length > 0;
            $modal.find("#wl-inline-cancel-ok").css({
                opacity: hasReason ? 1 : 0.5,
                "pointer-events": hasReason ? "auto" : "none"
            });
        });

        $modal.on("click", "#wl-inline-cancel-ok", function () {
            var reason = $.trim($modal.find("#wl-inline-cancel-reason").val());
            if (!reason) { return; }
            if (C.NON_ASCII_RE.test(reason)) {
                $modal.find("#wl-inline-cancel-reason").addClass("wl-input-error");
                showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }
            $modal.remove();
            var $btn = $(".wl-cancel-request-btn").filter(function () { return $(this).data("id") === requestId; });
            $btn.text("Cancelling\u2026").css("pointer-events", "none");
            restPost({
                action: "cancel_request",
                request_id: requestId,
                cancellation_reason: reason
            }).done(function (data) {
                if (data.error) {
                    showMsg(_.escape(data.error), "error");
                    $btn.text("Cancel Request").css("pointer-events", "auto");
                } else {
                    showMsg(_.escape(data.message || "Request cancelled."), "success");
                    _actions.reloadCsv();
                }
            }).fail(function (xhr) {
                var err = "Failed to cancel request.";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
                showMsg(_.escape(err), "error");
                $btn.text("Cancel Request").css("pointer-events", "auto");
            });
        });

        $modal.on("click", "#wl-inline-cancel-dismiss", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });

        setTimeout(function () { $modal.find("#wl-inline-cancel-reason").focus(); }, 100);
    }

    // ══════════════════════════════════════════════════════════════════
    // GROUP D: Bulk Edit Modal
    // ══════════════════════════════════════════════════════════════════

    function showBulkEditModal() {
        var selectedCount = _actions.getSelectedCount();
        if (selectedCount === 0) {
            showMsg("Select rows first using the checkboxes.", "warning");
            return;
        }

        $(".wl-modal-overlay").remove();

        var visibleHeaders = S.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var colOptions = visibleHeaders.map(function (h) {
            return '<option value="' + _.escape(h) + '">' + _.escape(h) + '</option>';
        }).join("");

        var datePickerHtml =
            '<div id="wl-bulk-expires-picker" style="display:none">' +
                '<div class="wl-dp-presets" style="margin-bottom:6px">' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="7">7 Days</button>' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="30">30 Days</button>' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="182">6 Months</button>' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="365">1 Year</button>' +
                '</div>' +
                '<div style="display:flex;gap:8px;align-items:flex-end">' +
                    '<div style="flex:1">' +
                        '<label class="wl-dp-label">Date</label>' +
                        '<input type="date" id="wl-bulk-dp-date" class="wl-dp-date" style="width:100%" />' +
                    '</div>' +
                    '<div style="flex:0 0 80px">' +
                        '<label class="wl-dp-label">Time (24h)</label>' +
                        '<input type="text" id="wl-bulk-dp-time" class="wl-dp-time" value="00:00" ' +
                            'placeholder="HH:MM" maxlength="5" style="width:100%" />' +
                    '</div>' +
                '</div>' +
                '<button class="btn btn-small wl-bulk-dp-clear" style="margin-top:6px">Clear (Permanent)</button>' +
            '</div>';

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Bulk Edit</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>Apply the same value to <strong>' + selectedCount + '</strong> selected row(s).</p>' +
                        '<label class="wl-dp-label">Column:</label>' +
                        '<select id="wl-bulk-col" class="wl-select" style="width:100%;margin-bottom:8px">' +
                        colOptions + '</select>' +
                        '<label class="wl-dp-label" id="wl-bulk-val-label">New value:</label>' +
                        '<input type="text" id="wl-bulk-val" class="wl-input" ' +
                            'maxlength="' + MAX_CELL_CHARS + '" ' +
                            'placeholder="Value to apply" style="width:100%" />' +
                        datePickerHtml +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button type="button" class="btn btn-primary" id="wl-bulk-apply">Apply</button> ' +
                        '<button type="button" class="btn" id="wl-bulk-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        var padTwo            = DatePicker.padTwo;
        var formatDateForPkr  = DatePicker.formatDateForPicker;
        var formatUTCDateTime = DatePicker.formatUTCDateTime;

        // Toggle between text input and date picker based on column selection
        function updateBulkValueInput() {
            var col = $modal.find("#wl-bulk-col").val();
            var isExpires = (S.expireColumn && col === S.expireColumn);
            if (isExpires) {
                $modal.find("#wl-bulk-val, #wl-bulk-val-label").hide();
                $modal.find("#wl-bulk-expires-picker").show();
                var now = new Date();
                $modal.find("#wl-bulk-dp-date").val(formatDateForPkr(now));
                $modal.find("#wl-bulk-dp-time").val(padTwo(now.getHours()) + ":" + padTwo(now.getMinutes()));
            } else {
                $modal.find("#wl-bulk-val, #wl-bulk-val-label").show();
                $modal.find("#wl-bulk-expires-picker").hide();
            }
        }
        $modal.on("change", "#wl-bulk-col", updateBulkValueInput);
        updateBulkValueInput();

        // Date picker preset buttons
        $modal.on("click", ".wl-bulk-dp-preset", function () {
            var days = parseInt($(this).data("days"), 10);
            var future = new Date();
            future.setDate(future.getDate() + days);
            $modal.find("#wl-bulk-dp-date").val(formatDateForPkr(future));
            $modal.find("#wl-bulk-dp-time").val(padTwo(future.getHours()) + ":" + padTwo(future.getMinutes()));
        });

        // Clear button — set expiration to empty (permanent)
        $modal.on("click", ".wl-bulk-dp-clear", function () {
            $modal.find("#wl-bulk-dp-date").val("");
            $modal.find("#wl-bulk-dp-time").val("00:00");
        });

        $modal.on("click", "#wl-bulk-apply", function () {
            var col = $modal.find("#wl-bulk-col").val();
            var val;
            var isExpires = (S.expireColumn && col === S.expireColumn);

            if (isExpires) {
                var d = $modal.find("#wl-bulk-dp-date").val();
                var t = ($modal.find("#wl-bulk-dp-time").val() || "00:00").trim();
                if (!d) {
                    val = "";
                } else {
                    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) {
                        $modal.find("#wl-bulk-dp-time").css("border-color", "#e74c3c");
                        return;
                    }
                    $modal.find("#wl-bulk-dp-time").css("border-color", "");
                    var tp = t.split(":");
                    var localDate = new Date(
                        parseInt(d.substr(0, 4), 10), parseInt(d.substr(5, 2), 10) - 1,
                        parseInt(d.substr(8, 2), 10), parseInt(tp[0], 10), parseInt(tp[1], 10)
                    );
                    val = formatUTCDateTime(localDate) + " UTC";
                }
            } else {
                val = $modal.find("#wl-bulk-val").val();
            }

            if (!col) { return; }

            _actions.syncInputs();

            var selectedIdxs = _actions.getSelectedIndices();
            var wouldChange = 0;
            selectedIdxs.forEach(function (idx) {
                if (S.currentRows[idx] && (S.currentRows[idx][col] || "") !== val) {
                    wouldChange++;
                }
            });

            if (wouldChange === 0) {
                $modal.remove();
                showMsg("No changes — all selected rows already have that value.", "info");
                return;
            }

            function applyBulkEditLocally() {
                var changedCount = 0;
                selectedIdxs.forEach(function (idx) {
                    if (S.currentRows[idx]) {
                        var oldVal = S.currentRows[idx][col] || "";
                        if (oldVal !== val) {
                            _actions.trackCellEdit(idx, col, oldVal, val);
                            S.currentRows[idx][col] = val;
                            changedCount++;
                        }
                    }
                });
                S.pendingBulkEditCount += changedCount;
                $modal.remove();
                _actions.refreshTable();
                var editDesc;
                if (val === "" && S.expireColumn && col === S.expireColumn) {
                    editDesc = "Bulk edit: cleared <strong>" + _.escape(col) +
                               "</strong> (set to permanent) on " + changedCount + " row(s).";
                } else if (val === "") {
                    editDesc = "Bulk edit: cleared <strong>" + _.escape(col) +
                               "</strong> column on " + changedCount + " row(s).";
                } else {
                    editDesc = "Bulk edit: set <strong>" + _.escape(col) + "</strong> to &ldquo;" +
                               _.escape(val) + "&rdquo; on " + changedCount + " row(s).";
                }
                showMsg(editDesc + " Click <strong>Save Changes</strong> to persist.", "success");
            }

            // Check approval gate
            restPost({
                action: "check_approval_gate",
                gate_action: "bulk_row_edit",
                csv_file: S.selectedCsv,
                app_context: S.selectedApp,
                selected_count: wouldChange
            }).done(function (gateData) {
                if (gateData.requires_approval) {
                    $modal.remove();
                    showRemoveRowModal(
                        "Submit for Approval",
                        "Bulk editing <strong>" + wouldChange + "</strong> row(s) requires admin approval.<br>" +
                            "Reason: " + _.escape(gateData.reason) + "<br><br>" +
                            "Your request will be submitted for review.",
                        function (reason) {
                            _actions.submitBulkEditApproval(col, val, selectedIdxs.slice(), wouldChange, reason);
                        },
                        {
                            reasonLabel: "Reason for bulk edit",
                            placeholder: "Why are these rows being edited?",
                            confirmText: "Submit",
                            confirmClass: "btn-primary"
                        }
                    );
                } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                    $modal.remove();
                    showMsg(formatDailyLimitMsg(gateData.daily_limit), "error");
                } else {
                    applyBulkEditLocally();
                }
            }).fail(function () {
                $modal.remove();
                showMsg("Unable to verify approval gate. Please try again.", "error");
            });
        });

        $modal.on("click", "#wl-bulk-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
        $modal.on("keydown", "#wl-bulk-val, #wl-bulk-dp-time", function (e) {
            if (e.which === 13) { e.preventDefault(); $modal.find("#wl-bulk-apply").trigger("click"); }
        });

        setTimeout(function () {
            var isExpires = (S.expireColumn && $modal.find("#wl-bulk-col").val() === S.expireColumn);
            if (isExpires) {
                $modal.find("#wl-bulk-dp-date").focus();
            } else {
                $modal.find("#wl-bulk-val").focus();
            }
        }, 100);
    }

    // ══════════════════════════════════════════════════════════════════
    // Public API
    // ══════════════════════════════════════════════════════════════════

    return {
        init:                     init,
        // Group A: Entity CRUD
        showRemoveModal:          showRemoveModal,
        showNewRuleModal:         showNewRuleModal,
        showApprovalReasonPopup:  showApprovalReasonPopup,
        showCreateCsvModal:       showCreateCsvModal,
        // Group B: Generic prompts
        showRemoveRowModal:       showRemoveRowModal,
        showRemoveColumnModal:    showRemoveColumnModal,
        // Group C: Approval actions
        showApproveConfirmModal:  showApproveConfirmModal,
        showRejectReasonModal:    showRejectReasonModal,
        showCancelRequestModal:   showCancelRequestModal,
        // Group D: Bulk edit
        showBulkEditModal:        showBulkEditModal
    };
});
