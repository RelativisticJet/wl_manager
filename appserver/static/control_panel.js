/**
 * Control Panel — Frontend Controller
 *
 * Admin-only page for managing:
 *   1. Approval queue (approve/reject pending requests)
 *   2. Daily limit configuration
 *   3. Per-analyst usage tracking
 */

/*global require, Splunk */
require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils) {
    "use strict";

    // ══════════════════════════════════════════════════════════════════
    // Dark theme detection (same as whitelist_manager.js)
    // ══════════════════════════════════════════════════════════════════
    (function detectDarkTheme() {
        var bg = window.getComputedStyle(document.body).backgroundColor;
        var m = bg.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (m) {
            var brightness = (parseInt(m[1]) + parseInt(m[2]) + parseInt(m[3])) / 3;
            if (brightness < 128) {
                $("body").addClass("wl-dark");
            }
        }
    })();

    // ══════════════════════════════════════════════════════════════════
    // Current user detection
    // ══════════════════════════════════════════════════════════════════
    var cpCurrentUser = "";
    var cpIsSuperAdmin = false;  // Set from get_approval_queue response

    (function detectCurrentUser() {
        try {
            var envModel = mvc.Components.getInstance("env");
            if (envModel) {
                cpCurrentUser = envModel.get("user") || "";
            }
        } catch (e) { /* ignore */ }
        if (!cpCurrentUser) {
            try {
                cpCurrentUser = $(".user-name").text().trim() ||
                    Splunk.util.getConfigValue("USERNAME") || "";
            } catch (e) { /* ignore */ }
        }
    })();

    // ══════════════════════════════════════════════════════════════════
    // REST helpers
    // ══════════════════════════════════════════════════════════════════
    function restUrl() {
        return Splunk.util.make_url(
            "/splunkd/__raw/services/custom/wl_manager"
        );
    }

    function restGet(params) {
        params = params || {};
        params.output_mode = "json";
        return $.ajax({
            url: restUrl(),
            type: "GET",
            data: params,
            dataType: "json"
        });
    }

    function restPost(payload) {
        return $.ajax({
            url: restUrl() + "?output_mode=json",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(payload),
            dataType: "json"
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Extract analyst reason from approval queue entry
    // ══════════════════════════════════════════════════════════════════
    function extractRequestReason(item) {
        var p = item.payload || {};
        var at = item.action_type || "";
        if (at === "bulk_row_removal") {
            var br = p.bulk_removal;
            if (br && br.length) return br[0].reason || "";
        } else if (at === "bulk_row_addition") {
            return p.row_add_reason || "";
        } else if (at === "column_removal") {
            var cr = p.column_removal_reasons;
            if (cr && cr.length) return cr[0].reason || "";
        } else if (at === "revert") {
            return p.revert_reason || "";
        }
        return "";
    }

    // ══════════════════════════════════════════════════════════════════
    // Styled modals (replaces browser alert/confirm)
    // ══════════════════════════════════════════════════════════════════
    function showCpAlert(title, message, type) {
        $(".wl-modal-overlay").remove();
        var msgColor = type === "error" ? "#e74c3c" : "#27ae60";
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">' + _.escape(title) + '</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0;color:' + msgColor + '">' + _.escape(message) + '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn btn-primary" id="wl-cp-alert-ok">OK</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        $modal.on("click", "#wl-cp-alert-ok", function () {
            $modal.remove();
            $(document).off("keydown.wlcpalert");
        });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) {
                $modal.remove();
                $(document).off("keydown.wlcpalert");
            }
        });
        $(document).off("keydown.wlcpalert").on("keydown.wlcpalert", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) {
                $modal.remove();
                $(document).off("keydown.wlcpalert");
            }
        });
    }

    function showCpConfirm(title, message, confirmLabel, onConfirm) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">' + _.escape(title) + '</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0">' + _.escape(message) + '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn btn-primary" id="wl-cp-confirm-ok">' +
                        _.escape(confirmLabel) + '</span> ' +
                    '<span class="btn" id="wl-cp-confirm-cancel">Cancel</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        $modal.on("click", "#wl-cp-confirm-ok", function () {
            $modal.remove();
            $(document).off("keydown.wlcpconfirm");
            if (onConfirm) { onConfirm(); }
        });
        $modal.on("click", "#wl-cp-confirm-cancel", function () {
            $modal.remove();
            $(document).off("keydown.wlcpconfirm");
        });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) {
                $modal.remove();
                $(document).off("keydown.wlcpconfirm");
            }
        });
        $(document).off("keydown.wlcpconfirm").on("keydown.wlcpconfirm", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) {
                $modal.remove();
                $(document).off("keydown.wlcpconfirm");
            }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Initialize
    // ══════════════════════════════════════════════════════════════════
    function showAccessDenied() {
        $("#wl-cp-loading").hide();
        $("#wl-cp-content").hide();
        var $panel = $("#wl-cp-loading").closest(".dashboard-panel");
        $panel.find(".wl-cp-denied").remove();
        $panel.append(
            '<div class="wl-cp-denied" style="text-align:center;padding:60px 20px">' +
            '<div style="font-size:48px;margin-bottom:16px;opacity:0.4">&#128274;</div>' +
            '<h2 style="margin:0 0 8px;font-size:22px;color:var(--wl-text,#ccc)">Access Denied</h2>' +
            '<p style="margin:0;font-size:14px;color:var(--wl-muted,#888)">' +
            'You do not have permission to view the Control Panel.<br>' +
            'This page is restricted to administrators.' +
            '</p></div>'
        );
    }

    restPost({ action: "get_approval_queue" })
    .done(function (data) {
        if (data.error) {
            showAccessDenied();
            return;
        }
        $("#wl-cp-loading").hide();
        $("#wl-cp-content").show();
        cpIsSuperAdmin = !!data.is_superadmin;
        initControlPanel(data.queue || []);
    })
    .fail(function (xhr) {
        // Distinguish authorization failure from transient errors.
        // 403 = access denied (user lacks admin role)
        // Anything else = network/server issue — don't lock out admins
        if (xhr && (xhr.status === 403 || xhr.status === 401)) {
            showAccessDenied();
        } else {
            $("#wl-cp-loading").html(
                '<div style="padding:20px;color:#ffc107;text-align:center;">' +
                '<p style="font-size:18px;font-weight:bold;">Error loading Control Panel</p>' +
                '<p>The server may be restarting or temporarily unavailable. ' +
                'Please try refreshing the page.</p>' +
                '<span class="wl-btn wl-btn-primary" style="margin-top:10px;' +
                'cursor:pointer;" onclick="location.reload()">Refresh</span></div>'
            );
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // Control Panel tabs and content
    // ══════════════════════════════════════════════════════════════════
    var queuePollTimer = null;
    var knownPendingCount = 0;

    function initControlPanel(queue) {
        renderTabs();
        renderApprovalQueue(queue);
        loadDailyLimits();
        startQueuePolling();
    }

    function startQueuePolling() {
        stopQueuePolling();
        queuePollTimer = setInterval(pollQueueChanges, 5000);
    }

    function stopQueuePolling() {
        if (queuePollTimer) { clearInterval(queuePollTimer); queuePollTimer = null; }
    }

    function pollQueueChanges() {
        // Skip if a modal is open (user is mid-action)
        if ($(".wl-modal-overlay").length) { return; }
        restPost({ action: "get_approval_queue" })
        .done(function (data) {
            var queue = data.queue || [];
            var newPending = queue.filter(function (q) { return q.status === "pending"; }).length;
            var newResolved = queue.filter(function (q) { return q.status !== "pending"; }).length;
            if (newPending !== allPending.length || newResolved !== allResolved.length) {
                renderApprovalQueue(queue);
            }
        });
    }

    function renderTabs() {
        var html =
            '<div class="wl-cp-tab-bar">' +
            '<span class="btn btn-primary wl-cp-tab" data-tab="queue">Approval Queue</span> ' +
            '<span class="btn wl-cp-tab" data-tab="usage">Analyst Usage</span> ' +
            '<span class="btn wl-cp-tab" data-tab="limits">Limits & Permissions</span> ' +
            '<span class="btn wl-cp-tab" data-tab="trash">Trash Management</span>';
        if (cpIsSuperAdmin) {
            html += ' <span class="btn wl-cp-tab" data-tab="admin-limits">Admin Limits</span>';
        }
        html += '</div>';
        $("#wl-cp-tabs").html(html);

        // Add trash and admin-limits containers if not present
        if (!$("#wl-cp-trash").length) {
            $("#wl-cp-content").append(
                '<div id="wl-cp-trash" style="display:none"></div>');
        }
        if (!$("#wl-cp-admin-limits").length) {
            $("#wl-cp-content").append(
                '<div id="wl-cp-admin-limits" style="display:none"></div>');
        }

        var allPanels = "#wl-cp-approval-queue, #wl-cp-daily-limits, " +
            "#wl-cp-analyst-usage, #wl-cp-trash, #wl-cp-admin-limits";

        function switchTab(tab) {
            $(".wl-cp-tab").removeClass("btn-primary");
            $(".wl-cp-tab[data-tab='" + tab + "']").addClass("btn-primary");
            $(allPanels).hide();
            if (typeof stopUsagePoll === "function") { stopUsagePoll(); }
            if (tab === "queue") { $("#wl-cp-approval-queue").show(); }
            if (tab === "limits") { $("#wl-cp-daily-limits").show(); }
            if (tab === "usage") {
                $("#wl-cp-analyst-usage").show();
                loadAnalystUsage();
            }
            if (tab === "trash") {
                $("#wl-cp-trash").show();
                loadTrash();
            }
            if (tab === "admin-limits") {
                $("#wl-cp-admin-limits").show();
                loadAdminLimits();
            }
        }

        $(".wl-cp-tab").on("click", function () {
            switchTab($(this).data("tab"));
        });

        // Support ?tab= from URL (e.g. notification redirect)
        var validTabs = ["queue", "limits", "usage", "trash"];
        if (cpIsSuperAdmin) { validTabs.push("admin-limits"); }
        var urlTab = new URLSearchParams(window.location.search).get("tab");
        if (urlTab && validTabs.indexOf(urlTab) !== -1) {
            switchTab(urlTab);
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Approval Queue
    // ══════════════════════════════════════════════════════════════════
    var PAGE_SIZE = 10;
    var allPending = [];
    var allResolved = [];
    var pendingPage = 0;
    var historyPage = 0;

    function renderApprovalQueue(queue) {
        allPending = queue.filter(function (q) { return q.status === "pending"; });
        allResolved = queue.filter(function (q) { return q.status !== "pending"; });
        pendingPage = 0;
        historyPage = 0;
        renderQueueHtml();
    }

    function renderQueueHtml() {
        var html = '';

        // ── Pending Requests ──
        var pendingTotal = allPending.length;
        var pendingPages = Math.max(1, Math.ceil(pendingTotal / PAGE_SIZE));
        if (pendingPage >= pendingPages) { pendingPage = pendingPages - 1; }
        var pendingStart = pendingPage * PAGE_SIZE;
        var pendingSlice = allPending.slice(pendingStart, pendingStart + PAGE_SIZE);

        html += '<h3 style="margin:12px 0 8px">Pending Requests (' + pendingTotal + '/20)</h3>';

        if (!pendingTotal) {
            html += '<p style="color:var(--wl-muted,#888)">No pending approval requests.</p>';
        } else {
            html += '<table class="wl-table"><thead><tr>' +
                '<th>Request ID</th><th>Timestamp</th><th>Analyst</th>' +
                '<th>Detection Rule</th><th>CSV File</th><th>Action</th>' +
                '<th>Analyst Reason</th><th>Actions</th>' +
                '</tr></thead><tbody>';
            pendingSlice.forEach(function (item) {
                var ts = new Date(item.timestamp * 1000);
                var tsStr = ts.toLocaleString();
                var isRuleOp = item.csv_file === "__rule_operation__";
                var csvDisplay = isRuleOp ? "N/A" : item.csv_file;
                var ruleDisplay = item.detection_rule || "";
                // Combine description with payload-extracted reason for full context
                var analystReason = item.description || extractRequestReason(item) || "";
                html += '<tr>' +
                    '<td style="font-size:11px;word-break:break-all">' + _.escape(item.request_id) + '</td>' +
                    '<td>' + _.escape(tsStr) + '</td>' +
                    '<td>' + _.escape(item.analyst) + '</td>' +
                    '<td>' + _.escape(ruleDisplay) + '</td>' +
                    '<td>' + _.escape(csvDisplay) + '</td>' +
                    '<td>' + _.escape(item.action_type.replace(/_/g, " ")) + '</td>' +
                    '<td class="wl-cp-reason-cell" title="' + _.escape(analystReason) + '">' + _.escape(analystReason) + '</td>' +
                    '<td style="white-space:nowrap">' +
                        (cpCurrentUser && item.analyst === cpCurrentUser
                            ? '<span class="btn btn-small wl-cp-cancel-btn" ' +
                                'data-id="' + _.escape(item.request_id) + '" ' +
                                'style="background:#f39c12;color:#fff;margin-right:4px">Cancel</span>'
                            : '<span class="btn btn-small wl-cp-approve-btn" ' +
                                'data-id="' + _.escape(item.request_id) + '" ' +
                                'data-dual="' + (item.is_dual_admin ? 'true' : 'false') + '" ' +
                                'style="background:#27ae60;color:#fff;margin-right:4px">Approve</span>' +
                              '<span class="btn btn-small wl-cp-reject-btn" ' +
                                'data-id="' + _.escape(item.request_id) + '" ' +
                                'data-dual="' + (item.is_dual_admin ? 'true' : 'false') + '" ' +
                                'style="background:#e74c3c;color:#fff;margin-right:4px">Reject</span>'
                        ) +
                        '<span class="btn btn-small wl-cp-download-btn" ' +
                            'data-csv="' + _.escape(item.csv_file) + '" ' +
                            'data-app="' + _.escape(item.app_context || "") + '" ' +
                            'data-request-id="' + _.escape(item.request_id) + '" ' +
                            'data-action-type="' + _.escape(item.action_type) + '"' +
                            '>Download CSV</span>' +
                    '</td></tr>';
            });
            html += '</tbody></table>';
            if (pendingPages > 1) {
                html += renderPagination(pendingPage, pendingPages, pendingTotal, "pending");
            }
        }

        // ── Recent History ──
        var historyTotal = allResolved.length;
        var historyPages = Math.max(1, Math.ceil(historyTotal / PAGE_SIZE));
        if (historyPage >= historyPages) { historyPage = historyPages - 1; }
        var historyStart = historyPage * PAGE_SIZE;
        var historySlice = allResolved.slice(historyStart, historyStart + PAGE_SIZE);

        html += '<h3 style="margin:20px 0 8px">Recent History (' + historyTotal + '/100)</h3>';
        if (historyTotal) {
            html += '<table class="wl-table"><thead><tr>' +
                '<th>Request ID</th><th>Timestamp</th><th>Analyst</th>' +
                '<th>Detection Rule</th><th>CSV File</th><th>Action</th>' +
                '<th>Analyst Reason</th><th>Admin Response</th>' +
                '<th>Status</th><th>Resolved By</th>' +
                '</tr></thead><tbody>';
            historySlice.forEach(function (item) {
                var ts = new Date(item.timestamp * 1000);
                var statusColor = item.status === "approved" ? "#27ae60" :
                                  item.status === "rejected" ? "#e74c3c" :
                                  item.status === "cancelled" ? "#f39c12" :
                                  item.status === "expired" ? "#f39c12" : "#888";
                var isRuleOp = item.csv_file === "__rule_operation__";
                var csvDisplay = isRuleOp ? "N/A" : item.csv_file;
                var ruleDisplay = item.detection_rule || "";
                var analystReason = item.description || extractRequestReason(item) || "";
                var adminResponse = item.rejection_reason || item.cancellation_reason ||
                                    item.admin_comment || "";
                html += '<tr>' +
                    '<td style="font-size:11px;word-break:break-all">' + _.escape(item.request_id) + '</td>' +
                    '<td>' + ts.toLocaleString() + '</td>' +
                    '<td>' + _.escape(item.analyst) + '</td>' +
                    '<td>' + _.escape(ruleDisplay) + '</td>' +
                    '<td>' + _.escape(csvDisplay) + '</td>' +
                    '<td>' + _.escape(item.action_type.replace(/_/g, " ")) + '</td>' +
                    '<td class="wl-cp-reason-cell" title="' + _.escape(analystReason) + '">' + _.escape(analystReason) + '</td>' +
                    '<td class="wl-cp-reason-cell" title="' + _.escape(adminResponse) + '">' + _.escape(adminResponse) + '</td>' +
                    '<td style="font-weight:600;color:' + statusColor + '">' +
                        _.escape(item.status) + '</td>' +
                    '<td>' + _.escape(item.resolved_by || "") + '</td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
            if (historyPages > 1) {
                html += renderPagination(historyPage, historyPages, historyTotal, "history");
            }
        } else {
            html += '<p style="color:var(--wl-muted,#888)">No resolved requests yet.</p>';
        }

        $("#wl-cp-approval-queue").html(html);
        bindApprovalActions();
        bindPagination();
    }

    function renderPagination(page, totalPages, totalItems, prefix) {
        var from = page * PAGE_SIZE + 1;
        var to = Math.min((page + 1) * PAGE_SIZE, totalItems);
        var prevDisabled = page === 0 ? "opacity:0.4;pointer-events:none;" : "";
        var nextDisabled = page >= totalPages - 1 ? "opacity:0.4;pointer-events:none;" : "";
        return '<div style="display:flex;align-items:center;gap:10px;margin:8px 0 4px">' +
            '<span class="btn btn-small wl-cp-page-prev" data-prefix="' + prefix + '" ' +
                'style="' + prevDisabled + '">&#9664; Prev</span>' +
            '<span style="color:var(--wl-muted,#888);font-size:13px">' +
                from + '–' + to + ' of ' + totalItems +
                ' &nbsp;(page ' + (page + 1) + ' of ' + totalPages + ')' +
            '</span>' +
            '<span class="btn btn-small wl-cp-page-next" data-prefix="' + prefix + '" ' +
                'style="' + nextDisabled + '">Next &#9654;</span>' +
            '</div>';
    }

    function bindPagination() {
        $(".wl-cp-page-prev").off("click").on("click", function () {
            var prefix = $(this).data("prefix");
            if (prefix === "pending" && pendingPage > 0) {
                pendingPage--;
                renderQueueHtml();
            } else if (prefix === "history" && historyPage > 0) {
                historyPage--;
                renderQueueHtml();
            }
        });
        $(".wl-cp-page-next").off("click").on("click", function () {
            var prefix = $(this).data("prefix");
            if (prefix === "pending") {
                var pendingPages = Math.ceil(allPending.length / PAGE_SIZE);
                if (pendingPage < pendingPages - 1) {
                    pendingPage++;
                    renderQueueHtml();
                }
            } else if (prefix === "history") {
                var historyPages = Math.ceil(allResolved.length / PAGE_SIZE);
                if (historyPage < historyPages - 1) {
                    historyPage++;
                    renderQueueHtml();
                }
            }
        });
    }

    function bindApprovalActions() {
        $(".wl-cp-approve-btn").off("click").on("click", function () {
            var requestId = $(this).data("id");
            var isDual = $(this).data("dual") === true || $(this).data("dual") === "true";
            var $btn = $(this);
            showCpConfirm("Approve Request",
                isDual ? "Approve this dual-admin request? The destructive action will be executed." :
                "Approve this request? The action will be executed immediately.",
                "Approve",
                function () {
                    $btn.text("Approving...").css("pointer-events", "none");
                    restPost({
                        action: isDual ? "process_dual_approval" : "process_approval",
                        request_id: requestId,
                        decision: "approve",
                        admin_comment: "Approved via Control Panel"
                    }).done(function (data) {
                        if (data.error) {
                            showCpAlert("Error", data.error, "error");
                        } else {
                            showCpAlert("Approved", data.message || "Request approved and executed.", "success");
                        }
                        refreshQueue();
                    }).fail(function (xhr) {
                        var err = "Failed to process approval.";
                        try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                        showCpAlert("Error", err, "error");
                        $btn.text("Approve").css("pointer-events", "auto");
                    });
                }
            );
        });

        $(".wl-cp-reject-btn").off("click").on("click", function () {
            var requestId = $(this).data("id");
            var isDual = $(this).data("dual") === true || $(this).data("dual") === "true";
            showRejectModal(requestId, isDual);
        });

        $(".wl-cp-download-btn").off("click").on("click", function () {
            var csvFile = $(this).data("csv");
            var appContext = $(this).data("app");
            var requestId = $(this).data("request-id");
            var actionType = $(this).data("action-type");

            // For create_csv / csv_import_replace, fetch data from request payload
            var needsRequestData = (
                actionType === "create_csv" || actionType === "csv_import_replace"
            );
            // Also use request data if csv_file is __rule_operation__ or N/A
            if (csvFile === "__rule_operation__" || csvFile === "N/A") {
                needsRequestData = true;
            }

            if (needsRequestData && requestId) {
                restGet({ action: "get_request_csv", request_id: requestId })
                .done(function (data) {
                    if (data.error) {
                        showCpAlert("Error", data.error, "error");
                        return;
                    }
                    var filename = data.csv_file || csvFile || "request_data.csv";
                    downloadCsvData(filename, data.headers || [], data.rows || []);
                })
                .fail(function (xhr) {
                    var err = "Failed to download CSV.";
                    try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                    showCpAlert("Error", err, "error");
                });
            } else {
                restGet({ action: "get_csv_content", csv_file: csvFile, app: appContext, tz_offset: 0 })
                .done(function (data) {
                    if (data.error) {
                        showCpAlert("Error", data.error, "error");
                        return;
                    }
                    downloadCsvData(csvFile, data.headers || [], data.rows || []);
                })
                .fail(function () {
                    showCpAlert("Error", "Failed to download CSV.", "error");
                });
            }
        });

        $(".wl-cp-cancel-btn").off("click").on("click", function () {
            var requestId = $(this).data("id");
            showCancelModal(requestId);
        });
    }

    function showCancelModal(requestId) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">Cancel Request</div>' +
                '<div class="wl-modal-body">' +
                    '<label class="wl-modal-label">Reason for cancellation ' +
                        '<span style="color:#e74c3c">*</span></label>' +
                    '<textarea id="wl-cancel-reason" class="wl-modal-input" rows="3" ' +
                        'maxlength="500" placeholder="Why are you cancelling this request?"></textarea>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn" id="wl-cancel-ok" ' +
                        'style="background:#f39c12;color:#fff;opacity:0.5;pointer-events:none">Cancel Request</span> ' +
                    '<span class="btn" id="wl-cancel-dismiss">Close</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);

        $modal.on("input", "#wl-cancel-reason", function () {
            var hasReason = $.trim($(this).val()).length > 0;
            $modal.find("#wl-cancel-ok").css({
                opacity: hasReason ? 1 : 0.5,
                "pointer-events": hasReason ? "auto" : "none"
            });
        });

        $modal.on("click", "#wl-cancel-ok", function () {
            var reason = $.trim($modal.find("#wl-cancel-reason").val());
            if (!reason) { return; }
            $modal.remove();
            restPost({
                action: "cancel_request",
                request_id: requestId,
                cancellation_reason: reason
            }).done(function (data) {
                if (data.error) {
                    showCpAlert("Error", data.error, "error");
                } else {
                    showCpAlert("Cancelled", data.message || "Request cancelled.", "success");
                }
                refreshQueue();
            }).fail(function (xhr) {
                var err = "Failed to cancel request.";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                showCpAlert("Error", err, "error");
            });
        });

        $modal.on("click", "#wl-cancel-dismiss", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
    }

    function showRejectModal(requestId, isDual) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">Reject Request</div>' +
                '<div class="wl-modal-body">' +
                    '<label class="wl-modal-label">Reason for rejection ' +
                        '<span style="color:#e74c3c">*</span></label>' +
                    '<textarea id="wl-reject-reason" class="wl-modal-input" rows="3" ' +
                        'maxlength="500" placeholder="Why is this request being rejected?"></textarea>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn btn-danger" id="wl-reject-ok" ' +
                        'style="opacity:0.5;pointer-events:none">Reject</span> ' +
                    '<span class="btn" id="wl-reject-cancel">Cancel</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);

        $modal.on("input", "#wl-reject-reason", function () {
            var hasReason = $.trim($(this).val()).length > 0;
            $modal.find("#wl-reject-ok").css({
                opacity: hasReason ? 1 : 0.5,
                "pointer-events": hasReason ? "auto" : "none"
            });
        });

        $modal.on("click", "#wl-reject-ok", function () {
            var reason = $.trim($modal.find("#wl-reject-reason").val());
            if (!reason) { return; }
            $modal.remove();
            restPost({
                action: isDual ? "process_dual_approval" : "process_approval",
                request_id: requestId,
                decision: "reject",
                rejection_reason: reason,
                admin_comment: reason
            }).done(function (data) {
                if (data.error) {
                    showCpAlert("Error", data.error, "error");
                } else {
                    showCpAlert("Rejected", data.message || "Request rejected.", "success");
                }
                refreshQueue();
            }).fail(function (xhr) {
                var err = "Failed to reject request.";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                showCpAlert("Error", err, "error");
            });
        });

        $modal.on("click", "#wl-reject-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
    }

    function refreshQueue() {
        restPost({ action: "get_approval_queue" })
        .done(function (data) {
            renderApprovalQueue(data.queue || []);
        });
    }

    function downloadCsvData(fileName, headers, rows) {
        var visHeaders = headers.filter(function (h) { return h.charAt(0) !== "_"; });
        var lines = [visHeaders.map(escapeCsvField).join(",")];
        rows.forEach(function (row) {
            var cells = visHeaders.map(function (h) {
                return escapeCsvField(row[h] || "");
            });
            lines.push(cells.join(","));
        });
        var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = fileName;
        link.click();
        URL.revokeObjectURL(link.href);
    }

    function escapeCsvField(val) {
        val = String(val);
        if (val.indexOf(",") >= 0 || val.indexOf('"') >= 0 || val.indexOf("\n") >= 0) {
            return '"' + val.replace(/"/g, '""') + '"';
        }
        return val;
    }

    // ══════════════════════════════════════════════════════════════════
    // Limits & Permissions
    // ══════════════════════════════════════════════════════════════════
    var loadedLimits = {};      // snapshot for no-change detection
    var defaultLimits = {};     // factory defaults from backend
    var customDefaults = null;  // company custom defaults (null if not set)

    function loadDailyLimits() {
        restPost({ action: "get_daily_limits" }).done(function (data) {
            defaultLimits = data.defaults || {};
            customDefaults = data.custom_defaults || null;
            renderDailyLimitsForm(data.limits || {}, data.change_history || []);
        });
    }

    function renderDailyLimitsForm(limits, changeHistory) {
        // Fields with optional inline approval thresholds.
        // thresholds[] are rendered on the right side of the same row.
        var fields = [
            { key: "row_addition", label: "Row Additions (per day)",
              info: "Maximum number of new rows an analyst can add across all CSVs per day. Covers manual Add Row and Import Merge.",
              thresholds: [
                  { key: "bulk_row_addition_threshold", unit: "rows",
                    info: "When an analyst tries to add this many rows or more in a single save, the action requires admin approval instead of executing immediately." }
              ] },
            { key: "row_removal", label: "Individual Row Removal (per day)",
              info: "Maximum individual rows an analyst can remove per day (single-row removals or small batches below the bulk threshold)." },
            { key: "bulk_row_removal", label: "Bulk Row Removal (per day)",
              info: "Maximum bulk removal operations per day. A bulk removal is when the analyst selects and removes multiple rows at once that meet or exceed the approval threshold.",
              thresholds: [
                  { key: "bulk_row_removal_threshold", unit: "rows",
                    info: "When an analyst tries to remove this many rows or more in a single operation, the action requires admin approval instead of executing immediately." }
              ] },
            { key: "row_edit", label: "Row Edits (per day)",
              info: "Maximum rows an analyst can edit per day via inline cell editing and the Save Changes button." },
            { key: "bulk_row_edit", label: "Bulk Row Edits (per day)",
              info: "Maximum total rows an analyst can edit via the Bulk Edit button per day. Each row changed in a bulk edit counts toward this limit.",
              thresholds: [
                  { key: "bulk_row_edit_threshold", unit: "rows",
                    info: "When an analyst tries to edit this many rows or more at once (via Bulk Edit or inline editing before Save), the action requires admin approval." }
              ] },
            { key: "row_reorder", label: "Row Reorders (per day)",
              info: "Maximum row drag-and-drop reorder operations an analyst can perform per day." },
            { key: "column_addition", label: "Column Additions (per day)",
              info: "Maximum new columns an analyst can add to CSV files per day." },
            { key: "column_removal", label: "Column Removal (per day)",
              info: "Maximum columns an analyst can remove per day. Columns with many non-empty cells may also require approval." },
            { key: "column_reorder", label: "Column Reorders (per day)",
              info: "Maximum column drag-and-drop reorder operations an analyst can perform per day." },
            { key: "revert", label: "Reverts (per day)",
              info: "Maximum CSV reverts per day. Reverts restore a previous version of the CSV. Large reverts that change many rows or columns may also require approval.",
              thresholds: [
                  { key: "revert_row_threshold", unit: "rows",
                    info: "When a revert changes this many rows or more, the action requires admin approval." },
                  { key: "revert_column_threshold", unit: "cols",
                    info: "When a revert changes this many columns or more (added or removed), the action requires admin approval." }
              ] },
        ];

        function buildInfoIcon(text) {
            return '<span class="wl-cp-info-icon" tabindex="0" ' +
                'style="display:inline-flex;align-items:center;justify-content:center;' +
                'width:18px;height:18px;border-radius:50%;background:var(--wl-border,#ccc);' +
                'color:var(--wl-text,#333);font-size:12px;font-weight:700;cursor:pointer;' +
                'flex-shrink:0;user-select:none;position:relative" ' +
                'data-info="' + _.escape(text) + '">i</span>';
        }

        var html = '<h3 style="margin:12px 0 8px">Analyst Daily Limit Configuration</h3>';
        html += '<div style="max-width:820px">';
        fields.forEach(function (f) {
            var val = limits[f.key] !== undefined ? limits[f.key] : 10;
            html += '<div style="margin-bottom:12px;display:flex;align-items:center;gap:10px">' +
                '<label style="min-width:240px;flex-shrink:0;font-weight:500">' + f.label + '</label>' +
                '<input type="number" class="wl-input wl-cp-limit-input" ' +
                    'data-key="' + f.key + '" value="' + val + '" ' +
                    'min="0" max="1000" style="width:120px;min-width:120px;text-align:center;box-sizing:border-box" />' +
                buildInfoIcon(f.info);

            // Inline approval thresholds
            if (f.thresholds && f.thresholds.length) {
                html += '<span style="border-left:1px solid var(--wl-border-light,#e0e0e0);' +
                    'padding-left:10px;margin-left:4px;display:inline-flex;align-items:center;' +
                    'gap:5px;font-size:12px;color:var(--wl-text-secondary,#555);' +
                    'white-space:nowrap">';
                html += '<span style="display:inline-block;min-width:76px">Approval &#8805;</span> ';
                f.thresholds.forEach(function (t, idx) {
                    var tVal = limits[t.key] !== undefined ? limits[t.key] : 3;
                    if (idx > 0) { html += ' or &#8805; '; }
                    html += '<input type="number" class="wl-input wl-cp-limit-input" ' +
                        'data-key="' + t.key + '" value="' + tVal + '" ' +
                        'min="1" max="1000" style="width:52px;text-align:center;' +
                        'padding:3px 4px;font-size:12px" /> ' +
                        t.unit + ' ' + buildInfoIcon(t.info);
                });
                html += '</span>';
            }

            html += '</div>';
        });

        // Reset Frequency dropdown + conditional schedule controls
        var curFreq = limits.reset_frequency || "daily";
        var curTime = limits.reset_time_utc || "00:00";
        var curTimeParts = curTime.split(":");
        var curHH = curTimeParts[0] || "00";
        var curMM = curTimeParts[1] || "00";
        var curDow = (typeof limits.reset_day_of_week === "number") ? limits.reset_day_of_week : 0;
        var curDom = (typeof limits.reset_day_of_month === "number") ? limits.reset_day_of_month : 1;
        var curMonth = (typeof limits.reset_month === "number") ? limits.reset_month : 1;
        var curDoy = (typeof limits.reset_day_of_year === "number") ? limits.reset_day_of_year : 1;
        // Build hour options (00-23)
        var hourOptsHtml = '';
        for (var h = 0; h < 24; h++) {
            var hStr = (h < 10 ? '0' : '') + h;
            hourOptsHtml += '<option value="' + hStr + '"' +
                (hStr === curHH ? ' selected' : '') + '>' + hStr + '</option>';
        }
        // Build minute options (5-min steps)
        var minOptsHtml = '';
        for (var m = 0; m < 60; m += 5) {
            var mStr = (m < 10 ? '0' : '') + m;
            minOptsHtml += '<option value="' + mStr + '"' +
                (mStr === curMM ? ' selected' : '') + '>' + mStr + '</option>';
        }
        // Day-of-week options (0=Monday..6=Sunday)
        var dowNames = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
        var dowOptsHtml = '';
        dowNames.forEach(function (name, idx) {
            dowOptsHtml += '<option value="' + idx + '"' +
                (idx === curDow ? ' selected' : '') + '>' + name + '</option>';
        });
        // Day-of-month options (1-31)
        var domOptsHtml = '';
        for (var d = 1; d <= 31; d++) {
            domOptsHtml += '<option value="' + d + '"' +
                (d === curDom ? ' selected' : '') + '>' + d + '</option>';
        }
        // Month options (1-12)
        var monthNames = ["January","February","March","April","May","June",
                          "July","August","September","October","November","December"];
        var monthOptsHtml = '';
        monthNames.forEach(function (name, idx) {
            var val = idx + 1;
            monthOptsHtml += '<option value="' + val + '"' +
                (val === curMonth ? ' selected' : '') + '>' + name + '</option>';
        });
        // Day-of-year options (1-31) for yearly
        var doyOptsHtml = '';
        for (var dy = 1; dy <= 31; dy++) {
            doyOptsHtml += '<option value="' + dy + '"' +
                (dy === curDoy ? ' selected' : '') + '>' + dy + '</option>';
        }
        var freqOptions = [
            { value: "never",   label: "Never" },
            { value: "daily",   label: "Daily" },
            { value: "weekly",  label: "Weekly" },
            { value: "monthly", label: "Monthly" },
            { value: "yearly",  label: "Yearly" }
        ];
        var freqOptsHtml = '';
        freqOptions.forEach(function (opt) {
            freqOptsHtml += '<option value="' + opt.value + '"' +
                (curFreq === opt.value ? ' selected' : '') + '>' +
                opt.label + '</option>';
        });
        var ss = 'text-align:center;padding:3px 2px;font-size:12px';
        // Helper: inline display for a given frequency
        function dIf(freq, target) {
            return freq === target ? "inline" : "none";
        }
        html += '<div style="margin-bottom:12px;display:flex;align-items:center;gap:10px">' +
            '<label style="min-width:240px;flex-shrink:0;font-weight:500">Counter Reset Frequency</label>' +
            '<select class="wl-input" id="wl-cp-freq" data-key="reset_frequency" ' +
                'style="width:120px;min-width:120px;text-align:center;box-sizing:border-box">' +
            freqOptsHtml +
            '</select>' +
            buildInfoIcon("How often analyst daily-limit counters reset to zero. " +
                "'Never' means counters accumulate permanently until manually reset by an admin.") +
            // Inline schedule controls (same line, after freq dropdown)
            '<span id="wl-cp-schedule-wrap" style="display:' +
                (curFreq === "never" ? "none" : "inline-flex") +
                ';align-items:center;gap:6px;border-left:1px solid var(--wl-border-light,#e0e0e0);' +
                'padding-left:10px;margin-left:2px;font-size:12px;' +
                'color:var(--wl-text-secondary,#555)">' +
                // Weekly: day-of-week
                '<select class="wl-input wl-cp-sched wl-cp-sched-weekly" id="wl-cp-reset-dow" ' +
                    'style="display:' + dIf(curFreq, "weekly") + ';' + ss + '">' +
                    dowOptsHtml + '</select>' +
                // Monthly: day-of-month
                '<select class="wl-input wl-cp-sched wl-cp-sched-monthly" id="wl-cp-reset-dom" ' +
                    'style="display:' + dIf(curFreq, "monthly") + ';width:50px;' + ss + '">' +
                    domOptsHtml + '</select>' +
                // Yearly: month + day
                '<select class="wl-input wl-cp-sched wl-cp-sched-yearly" id="wl-cp-reset-month" ' +
                    'style="display:' + dIf(curFreq, "yearly") + ';' + ss + '">' +
                    monthOptsHtml + '</select>' +
                '<select class="wl-input wl-cp-sched wl-cp-sched-yearly" id="wl-cp-reset-doy" ' +
                    'style="display:' + dIf(curFreq, "yearly") + ';width:50px;' + ss + '">' +
                    doyOptsHtml + '</select>' +
                // Time picker (all non-never)
                '<select class="wl-input" id="wl-cp-reset-hh" ' +
                    'style="width:42px;' + ss + '">' +
                    hourOptsHtml + '</select>' +
                '<span style="font-weight:600">:</span>' +
                '<select class="wl-input" id="wl-cp-reset-mm" ' +
                    'style="width:42px;' + ss + '">' +
                    minOptsHtml + '</select>' +
                '<span>UTC</span>' +
                buildInfoIcon("Daily: resets at this time every day. " +
                    "Weekly: resets at this time on the chosen weekday. " +
                    "Monthly: resets on the chosen day (clamped to last day for short months). " +
                    "Yearly: resets on the chosen date.") +
            '</span>' +
            '</div>';

        // Analyst permissions — 3-state dropdowns
        html += '<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--wl-border-light,#e0e0e0)">' +
            '<h4 style="margin:0 0 10px;font-size:14px;font-weight:600">Analyst Permissions</h4>';

        function permValue(allowKey, requireKey) {
            if (!limits[allowKey]) return "off";
            if (limits[requireKey]) return "on_approval";
            return "on";
        }

        function buildPermDropdown(id, allowKey, requireKey, labelText, infoText) {
            var val = permValue(allowKey, requireKey);
            var ss = 'class="wl-input wl-cp-perm-select" ' +
                'data-allow-key="' + allowKey + '" ' +
                'data-require-key="' + requireKey + '" ' +
                'style="width:200px;font-size:13px;padding:5px 8px;' +
                'border-radius:4px;cursor:pointer"';
            return '<div style="margin-bottom:12px;display:flex;align-items:center;gap:10px">' +
                '<label style="min-width:200px;flex-shrink:0;font-weight:500">' +
                    labelText + '</label>' +
                '<select id="' + id + '" ' + ss + '>' +
                    '<option value="off"' + (val === "off" ? ' selected' : '') + '>Off</option>' +
                    '<option value="on"' + (val === "on" ? ' selected' : '') + '>On</option>' +
                    '<option value="on_approval"' + (val === "on_approval" ? ' selected' : '') +
                        '>On, require approval</option>' +
                '</select>' +
                buildInfoIcon(infoText) +
                '</div>';
        }

        html += buildPermDropdown('wl-cp-perm-rule-creation',
            'allow_analyst_create_rules', 'require_reason_rule_creation',
            'Analyst Rule Creation',
            'Off: only admins can create rules. On: analysts can create rules freely. ' +
            'On, require approval: analysts must provide a reason and the request goes to the Approval Queue.');

        html += buildPermDropdown('wl-cp-perm-csv-creation',
            'allow_analyst_create_csv', 'require_reason_csv_creation',
            'Analyst CSV Creation',
            'Off: only admins can create CSVs. On: analysts can create CSVs freely. ' +
            'On, require approval: analysts must provide a reason and the request goes to the Approval Queue.');

        html += buildPermDropdown('wl-cp-perm-rule-deletion',
            'allow_analyst_delete_rules', 'require_reason_rule_deletion',
            'Analyst Rule Deletion',
            'Off: only admins can remove rules. On: analysts can remove rules freely. ' +
            'On, require approval: analysts must provide a reason and the request goes to the Approval Queue.');

        html += buildPermDropdown('wl-cp-perm-csv-deletion',
            'allow_analyst_delete_csv', 'require_reason_csv_deletion',
            'Analyst CSV Deletion',
            'Off: only admins can remove CSVs. On: analysts can remove CSVs freely. ' +
            'On, require approval: analysts must provide a reason and the request goes to the Approval Queue.');

        html += '</div>';

        // Buttons row
        html += '<div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">';
        html += '<span class="btn btn-primary" id="wl-cp-save-limits">Save Changes</span>';
        html += '<span class="btn" id="wl-cp-save-as-default" ' +
                'style="background:#3498db;color:#fff">Save as Default</span>';
        if (customDefaults) {
            html += '<span class="btn" id="wl-cp-reset-limits" ' +
                    'style="background:#e74c3c;color:#fff">Reset to Custom Defaults</span>';
            html += '<span class="btn" id="wl-cp-reset-factory" ' +
                    'style="background:#95a5a6;color:#fff">Reset to Factory Defaults</span>';
        } else {
            html += '<span class="btn" id="wl-cp-reset-limits" ' +
                    'style="background:#e74c3c;color:#fff">Reset to Defaults</span>';
        }
        html += '<span id="wl-cp-limits-msg" style="margin-left:8px;display:none"></span>';
        html += '</div>';
        html += '</div>';

        // Recent Limit Changes table
        html += renderLimitHistory(changeHistory);

        $("#wl-cp-daily-limits").html(html);

        // Snapshot loaded values for no-change detection
        loadedLimits = {};
        $(".wl-cp-limit-input").each(function () {
            loadedLimits[$(this).data("key")] = parseInt($(this).val(), 10) || 0;
        });
        $(".wl-cp-perm-select").each(function () {
            var val = $(this).val();
            var allowKey = $(this).data("allow-key");
            var requireKey = $(this).data("require-key");
            loadedLimits[allowKey] = (val === "on" || val === "on_approval");
            loadedLimits[requireKey] = (val === "on_approval");
        });
        loadedLimits.reset_frequency = $("#wl-cp-freq").val();
        loadedLimits.reset_time_utc = $("#wl-cp-reset-hh").val() + ":" + $("#wl-cp-reset-mm").val();
        loadedLimits.reset_day_of_week = parseInt($("#wl-cp-reset-dow").val(), 10) || 0;
        loadedLimits.reset_day_of_month = parseInt($("#wl-cp-reset-dom").val(), 10) || 1;
        loadedLimits.reset_month = parseInt($("#wl-cp-reset-month").val(), 10) || 1;
        loadedLimits.reset_day_of_year = parseInt($("#wl-cp-reset-doy").val(), 10) || 1;

        // Show/hide schedule controls based on frequency
        function updateScheduleVisibility(freq) {
            if (freq === "never") {
                $("#wl-cp-schedule-wrap").hide();
            } else {
                $("#wl-cp-schedule-wrap").css("display", "inline-flex");
            }
            // Hide all frequency-specific elements, then show the active ones
            $(".wl-cp-sched").hide();
            if (freq !== "never" && freq !== "daily") {
                $(".wl-cp-sched-" + freq).css("display", "inline");
            }
        }
        $("#wl-cp-freq").on("change", function () {
            updateScheduleVisibility($(this).val());
        });

        // Permission dropdown no longer needs a click handler —
        // the <select> value is read directly at save time.

        // Info icon click-to-toggle tooltip (appended to body with fixed positioning)
        var infoBubbleTimer = null;

        function closeInfoBubble() {
            if (infoBubbleTimer) { clearTimeout(infoBubbleTimer); infoBubbleTimer = null; }
            $(".wl-cp-info-bubble").remove();
        }

        $("#wl-cp-daily-limits").off("click.info").on("click.info", ".wl-cp-info-icon", function (e) {
            e.stopPropagation();
            var $icon = $(this);
            var wasOpen = $(".wl-cp-info-bubble").length &&
                          $(".wl-cp-info-bubble").data("owner") === $icon[0];

            closeInfoBubble();
            if (wasOpen) { return; }  // toggle off

            var text = $icon.data("info");
            var rect = $icon[0].getBoundingClientRect();
            var bubbleW = 280;
            var pad = 8;

            // Position below the icon, centered horizontally
            var left = rect.left + rect.width / 2 - bubbleW / 2;
            var top = rect.bottom + 8;

            // Clamp to viewport edges
            if (left < pad) { left = pad; }
            if (left + bubbleW > window.innerWidth - pad) {
                left = window.innerWidth - bubbleW - pad;
            }
            // If not enough room below, show above
            if (top + 80 > window.innerHeight) {
                top = rect.top - 8;  // will use transform to shift up
            }
            var showAbove = (rect.bottom + 80 > window.innerHeight);

            var isDark = $("body").hasClass("wl-dark");
            var bg    = isDark ? "#1a1c20" : "#fafafa";
            var bdr   = isDark ? "#444"    : "#ccc";
            var clr   = isDark ? "#e0e0e0" : "#333";
            var shd   = isDark ? "rgba(0,0,0,.5)" : "rgba(0,0,0,.15)";

            var $bubble = $(
                '<div class="wl-cp-info-bubble" style="' +
                    "position:fixed;z-index:10000;width:" + bubbleW + "px;" +
                    "left:" + left + "px;" +
                    (showAbove
                        ? "top:" + rect.top + "px;transform:translateY(-100%) translateY(-8px);"
                        : "top:" + top + "px;") +
                    "background:" + bg + ";border:1px solid " + bdr + ";" +
                    "border-radius:6px;padding:10px 14px;font-size:12px;font-weight:400;" +
                    "line-height:1.5;color:" + clr + ";" +
                    "white-space:normal;word-wrap:break-word;" +
                    "box-shadow:0 4px 16px " + shd + ';">' +
                    _.escape(text) +
                "</div>"
            );
            $bubble.data("owner", $icon[0]);
            $("body").append($bubble);

            // Auto-hide after 30 seconds with fade
            infoBubbleTimer = setTimeout(function () {
                $bubble.fadeOut(400, function () { $bubble.remove(); });
                infoBubbleTimer = null;
            }, 30000);
        });

        // Close bubble when clicking outside
        $(document).off("click.cpinfo").on("click.cpinfo", function () {
            closeInfoBubble();
        });

        $("#wl-cp-save-limits").on("click", function () {
            var newLimits = {};
            $(".wl-cp-limit-input").each(function () {
                newLimits[$(this).data("key")] = parseInt($(this).val(), 10) || 0;
            });
            $(".wl-cp-perm-select").each(function () {
                var val = $(this).val();
                var allowKey = $(this).data("allow-key");
                var requireKey = $(this).data("require-key");
                newLimits[allowKey] = (val === "on" || val === "on_approval");
                newLimits[requireKey] = (val === "on_approval");
            });
            newLimits.reset_frequency = $("#wl-cp-freq").val();
            newLimits.reset_time_utc = $("#wl-cp-reset-hh").val() + ":" + $("#wl-cp-reset-mm").val();
            newLimits.reset_day_of_week = parseInt($("#wl-cp-reset-dow").val(), 10) || 0;
            newLimits.reset_day_of_month = parseInt($("#wl-cp-reset-dom").val(), 10) || 1;
            newLimits.reset_month = parseInt($("#wl-cp-reset-month").val(), 10) || 1;
            newLimits.reset_day_of_year = parseInt($("#wl-cp-reset-doy").val(), 10) || 1;

            // Client-side no-change detection
            var STRING_DEFAULTS = {
                reset_frequency: "daily",
                reset_time_utc: "00:00"
            };
            var hasChanges = false;
            for (var k in newLimits) {
                if (STRING_DEFAULTS[k] !== undefined) {
                    if (newLimits[k] !== (loadedLimits[k] || STRING_DEFAULTS[k])) {
                        hasChanges = true;
                    }
                } else if (newLimits[k] !== (loadedLimits[k] !== undefined ? loadedLimits[k] : -1)) {
                    hasChanges = true;
                }
                if (hasChanges) { break; }
            }
            if (!hasChanges) {
                var $m = $("#wl-cp-limits-msg");
                $m.text("No changes made").css("color", "#f39c12").show();
                setTimeout(function () { $m.fadeOut(); }, 3000);
                return;
            }

            var $btn = $(this);
            $btn.text("Saving...").css("pointer-events", "none");
            restPost({ action: "set_daily_limits", limits: newLimits })
            .done(function (data) {
                if (data.error) {
                    showCpAlert("Error", data.error, "error");
                } else if (data.no_changes) {
                    var $m = $("#wl-cp-limits-msg");
                    $m.text("No changes made").css("color", "#f39c12").show();
                    setTimeout(function () { $m.fadeOut(); }, 3000);
                } else {
                    var $m = $("#wl-cp-limits-msg");
                    $m.text("Limits changed").css("color", "#27ae60").show();
                    setTimeout(function () { $m.fadeOut(); }, 3000);
                    // Update snapshot and refresh history
                    loadedLimits = newLimits;
                    $("#wl-cp-limit-history").replaceWith(
                        renderLimitHistory(data.change_history || []));
                }
                $btn.text("Save Changes").css("pointer-events", "auto");
            })
            .fail(function () {
                showCpAlert("Error", "Failed to save limits.", "error");
                $btn.text("Save Changes").css("pointer-events", "auto");
            });
        });

        // Reset to (Custom) Defaults button
        $("#wl-cp-reset-limits").on("click", function () {
            var target = customDefaults || defaultLimits;
            var targetLabel = customDefaults ? "custom defaults" : "defaults";
            var btnLabel = customDefaults ? "Reset to Custom Defaults" : "Reset to Defaults";

            // Check if already at target defaults
            var alreadyDefault = true;
            for (var dk in target) {
                if (loadedLimits[dk] !== undefined && loadedLimits[dk] !== target[dk]) {
                    alreadyDefault = false;
                    break;
                }
            }
            if (alreadyDefault) {
                var $m = $("#wl-cp-limits-msg");
                $m.text("Already at " + targetLabel).css("color", "#f39c12").show();
                setTimeout(function () { $m.fadeOut(); }, 3000);
                return;
            }

            showCpConfirm("Reset to Defaults",
                "This will reset all daily limits and approval thresholds " +
                "back to " + targetLabel + ". This action will be recorded " +
                "in the change history. Continue?",
                btnLabel,
                function () {
                    var $btn = $("#wl-cp-reset-limits");
                    $btn.text("Resetting...").css("pointer-events", "none");
                    restPost({ action: "reset_daily_limits" })
                    .done(function (data) {
                        if (data.error) {
                            showCpAlert("Error", data.error, "error");
                            $btn.text(btnLabel).css("pointer-events", "auto");
                        } else {
                            renderDailyLimitsForm(
                                data.limits || {},
                                data.change_history || []);
                            var $m = $("#wl-cp-limits-msg");
                            $m.text("Limits reset to " + targetLabel)
                                .css("color", "#27ae60").show();
                            setTimeout(function () { $m.fadeOut(); }, 3000);
                        }
                    })
                    .fail(function () {
                        showCpAlert("Error", "Failed to reset limits.", "error");
                        $btn.text(btnLabel).css("pointer-events", "auto");
                    });
                }
            );
        });

        // Reset to Factory Defaults button (only visible when custom defaults exist)
        $("#wl-cp-reset-factory").on("click", function () {
            var alreadyFactory = true;
            for (var dk in defaultLimits) {
                if (loadedLimits[dk] !== undefined && loadedLimits[dk] !== defaultLimits[dk]) {
                    alreadyFactory = false;
                    break;
                }
            }
            if (alreadyFactory && !customDefaults) {
                var $m = $("#wl-cp-limits-msg");
                $m.text("Already at factory defaults").css("color", "#f39c12").show();
                setTimeout(function () { $m.fadeOut(); }, 3000);
                return;
            }

            showCpConfirm("Reset to Factory Defaults",
                "This will reset all limits back to the original factory defaults " +
                "AND clear any saved custom defaults. Continue?",
                "Reset to Factory",
                function () {
                    var $btn = $("#wl-cp-reset-factory");
                    $btn.text("Resetting...").css("pointer-events", "none");
                    restPost({ action: "reset_factory_defaults" })
                    .done(function (data) {
                        if (data.error) {
                            showCpAlert("Error", data.error, "error");
                            $btn.text("Reset to Factory Defaults").css("pointer-events", "auto");
                        } else {
                            customDefaults = data.custom_defaults || null;
                            renderDailyLimitsForm(
                                data.limits || {},
                                data.change_history || []);
                            var $m = $("#wl-cp-limits-msg");
                            $m.text(data.message || "Reset to factory defaults")
                                .css("color", "#27ae60").show();
                            setTimeout(function () { $m.fadeOut(); }, 3000);
                        }
                    })
                    .fail(function () {
                        showCpAlert("Error", "Failed to reset to factory defaults.", "error");
                        $btn.text("Reset to Factory Defaults").css("pointer-events", "auto");
                    });
                }
            );
        });

        // Save as Default button
        $("#wl-cp-save-as-default").on("click", function () {
            showCpConfirm("Save as Default",
                "Save the current limits as your organization's custom defaults? " +
                "These will be used when any admin clicks 'Reset to Custom Defaults'.",
                "Save as Default",
                function () {
                    var $btn = $("#wl-cp-save-as-default");
                    $btn.text("Saving...").css("pointer-events", "none");
                    restPost({ action: "save_as_default" })
                    .done(function (data) {
                        if (data.error) {
                            showCpAlert("Error", data.error, "error");
                        } else {
                            customDefaults = data.custom_defaults || null;
                            // Re-render to show/hide conditional buttons
                            renderDailyLimitsForm(
                                data.limits || {},
                                data.change_history || []);
                            var $m = $("#wl-cp-limits-msg");
                            $m.text(data.message || "Saved as default")
                                .css("color", "#27ae60").show();
                            setTimeout(function () { $m.fadeOut(); }, 3000);
                        }
                        $btn.text("Save as Default").css("pointer-events", "auto");
                    })
                    .fail(function () {
                        showCpAlert("Error", "Failed to save as default.", "error");
                        $btn.text("Save as Default").css("pointer-events", "auto");
                    });
                }
            );
        });
    }

    // Human-readable label map for limit keys
    var LIMIT_LABELS = {
        row_addition: "Row Additions",
        row_removal: "Individual Row Removal",
        bulk_row_removal: "Bulk Row Removal",
        row_edit: "Row Edits",
        bulk_row_edit: "Bulk Row Edits",
        column_addition: "Column Additions",
        column_removal: "Column Removal",
        revert: "Reverts",
        reset_frequency: "Counter Reset Frequency",
        reset_time_utc: "Reset Time (UTC)",
        reset_day_of_week: "Reset Day of Week",
        reset_day_of_month: "Reset Day of Month",
        reset_month: "Reset Month",
        reset_day_of_year: "Reset Day (Yearly)",
        bulk_row_removal_threshold: "Bulk Removal Threshold",
        bulk_row_edit_threshold: "Bulk Edit Threshold",
        bulk_row_addition_threshold: "Bulk Addition Threshold",
        column_nonempty_threshold: "Column Non-empty Threshold",
        revert_row_threshold: "Revert Row Threshold",
        revert_column_threshold: "Revert Column Threshold",
        allow_analyst_create_rules: "Analyst Rule Creation",
        allow_analyst_create_csv: "Analyst CSV Creation",
        allow_analyst_delete_rules: "Analyst Rule Deletion",
        allow_analyst_delete_csv: "Analyst CSV Deletion",
        require_reason_rule_creation: "Require Approval (Rule Creation)",
        require_reason_csv_creation: "Require Approval (CSV Creation)",
        require_reason_rule_deletion: "Require Approval (Rule Deletion)",
        require_reason_csv_deletion: "Require Approval (CSV Deletion)",
        row_reorder: "Row Reorders",
        column_reorder: "Column Reorders"
    };

    function renderLimitHistory(history) {
        var html = '<div id="wl-cp-limit-history" style="margin-top:20px">';
        html += '<h3 style="margin:12px 0 8px">Recent Changes</h3>';

        if (!history || !history.length) {
            html += '<p style="color:var(--wl-text-muted,#888);font-size:13px">' +
                'No changes recorded yet.</p>';
        } else {
            html += '<table class="wl-table" style="font-size:13px"><thead><tr>' +
                '<th style="width:180px">Timestamp</th>' +
                '<th style="width:120px">Admin</th>' +
                '<th>Changes</th>' +
                '</tr></thead><tbody>';
            var BOOL_SETTINGS = {
                allow_analyst_create_rules: true,
                allow_analyst_create_csv: true,
                allow_analyst_delete_rules: true,
                allow_analyst_delete_csv: true,
                require_reason_rule_creation: true,
                require_reason_csv_creation: true,
                require_reason_rule_deletion: true,
                require_reason_csv_deletion: true
            };
            var DOW_NAMES = ["Monday","Tuesday","Wednesday","Thursday",
                             "Friday","Saturday","Sunday"];
            var MONTH_NAMES = ["","January","February","March","April","May",
                               "June","July","August","September","October",
                               "November","December"];
            history.forEach(function (entry) {
                var isReset = entry.reset === true;
                var changeDescs = (entry.changes || []).map(function (c) {
                    var label = LIMIT_LABELS[c.key] || c.key;
                    var oldStr = String(c.old);
                    var newStr = String(c["new"]);
                    if (BOOL_SETTINGS[c.key]) {
                        oldStr = c.old ? "Enabled" : "Disabled";
                        newStr = c["new"] ? "Enabled" : "Disabled";
                    } else if (c.key === "reset_day_of_week") {
                        oldStr = DOW_NAMES[c.old] || String(c.old);
                        newStr = DOW_NAMES[c["new"]] || String(c["new"]);
                    } else if (c.key === "reset_month") {
                        oldStr = MONTH_NAMES[c.old] || String(c.old);
                        newStr = MONTH_NAMES[c["new"]] || String(c["new"]);
                    }
                    return '<span style="white-space:nowrap">' +
                        _.escape(label) + ': ' +
                        '<span style="color:var(--wl-diff-rm,#c62828)">' +
                            _.escape(oldStr) + '</span>' +
                        ' &#8594; ' +
                        '<span style="color:var(--wl-diff-add,#2e7d32)">' +
                            _.escape(newStr) + '</span>' +
                        '</span>';
                });
                var isFactory = entry.factory === true;
                var badge = '';
                if (isFactory) {
                    badge = '<span style="display:inline-block;background:#95a5a6;color:#fff;' +
                        'font-size:10px;font-weight:600;padding:1px 6px;border-radius:3px;' +
                        'margin-right:6px">FACTORY</span>';
                } else if (isReset) {
                    badge = '<span style="display:inline-block;background:#e74c3c;color:#fff;' +
                        'font-size:10px;font-weight:600;padding:1px 6px;border-radius:3px;' +
                        'margin-right:6px">RESET</span>';
                }
                var localTs = entry.timestamp || "";
                if (localTs) {
                    var d = new Date(localTs.replace(" UTC", "Z"));
                    if (!isNaN(d.getTime())) { localTs = d.toLocaleString(); }
                }
                html += '<tr>' +
                    '<td>' + _.escape(localTs) + '</td>' +
                    '<td>' + _.escape(entry.admin || "") + '</td>' +
                    '<td>' + badge + changeDescs.join('<br>') + '</td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
        }
        html += '</div>';
        return html;
    }

    // ══════════════════════════════════════════════════════════════════
    // Analyst Usage (paginated — 10 per page, auto-refresh)
    // ══════════════════════════════════════════════════════════════════
    var USAGE_PER_PAGE = 10;
    var USAGE_POLL_MS = 10000;   // auto-refresh every 10 seconds
    var usagePage = 0;           // current zero-based page
    var cachedUsageData = {};    // stashed between page renders
    var cachedUsageDate = "";
    var cachedUsageLimits = {};
    var usagePollTimer = null;

    // Column definitions in requested order
    var USAGE_COLUMNS = [
        { key: "row_addition",      label: "Rows Added",         limitKey: "row_addition" },
        { key: "row_edit",          label: "Rows Edited",        limitKey: "row_edit" },
        { key: "bulk_row_edit",     label: "Bulk Rows Edited",   limitKey: "bulk_row_edit" },
        { key: "row_removal",       label: "Rows Removed",       limitKey: "row_removal" },
        { key: "bulk_row_removal",  label: "Bulk Rows Removed",  limitKey: "bulk_row_removal" },
        { key: "row_reorder",       label: "Rows Reordered",     limitKey: "row_reorder" },
        { key: "column_addition",   label: "Columns Added",      limitKey: "column_addition" },
        { key: "column_removal",    label: "Columns Removed",    limitKey: "column_removal" },
        { key: "column_reorder",    label: "Cols Reordered",     limitKey: "column_reorder" },
        { key: "revert",            label: "Reverted",           limitKey: "revert" }
    ];

    function usageCellHtml(count, limit) {
        var c = count || 0;
        if (limit === 0) {
            // Limit is 0 = unlimited
            return '<span>' + c + '</span>';
        }
        if (c >= limit) {
            return '<span style="color:#e74c3c;font-weight:600">' + c +
                '</span> <span style="display:inline-block;font-size:10px;padding:1px 5px;' +
                'border-radius:3px;background:#e74c3c;color:#fff;font-weight:600;' +
                'vertical-align:middle;margin-left:3px">LIMIT</span>';
        }
        return '<span>' + c + '</span>';
    }

    function loadAnalystUsage(preservePage) {
        restPost({ action: "get_analyst_usage" }).done(function (data) {
            cachedUsageData = data.all_analysts || {};
            cachedUsageDate = data.date || "today";
            cachedUsageLimits = data.limits || {};
            if (!preservePage) { usagePage = 0; }
            renderAnalystUsage();
        });
    }

    function startUsagePoll() {
        stopUsagePoll();
        usagePollTimer = setInterval(function () {
            // Only poll if the usage tab is visible
            if ($("#wl-cp-analyst-usage").is(":visible")) {
                loadAnalystUsage(true);
            }
        }, USAGE_POLL_MS);
    }

    function stopUsagePoll() {
        if (usagePollTimer) {
            clearInterval(usagePollTimer);
            usagePollTimer = null;
        }
    }

    function renderAnalystUsage() {
        var allAnalysts = cachedUsageData;
        var date = cachedUsageDate;
        var limits = cachedUsageLimits;
        var analysts = Object.keys(allAnalysts).sort();
        var totalPages = Math.max(1, Math.ceil(analysts.length / USAGE_PER_PAGE));
        if (usagePage >= totalPages) { usagePage = totalPages - 1; }
        if (usagePage < 0) { usagePage = 0; }

        var startIdx = usagePage * USAGE_PER_PAGE;
        var pageAnalysts = analysts.slice(startIdx, startIdx + USAGE_PER_PAGE);

        var html = '<h3 style="margin:12px 0 8px">Analyst Usage for ' +
                   _.escape(date) + '</h3>';

        if (!analysts.length) {
            html += '<p style="color:var(--wl-muted,#888)">No activity recorded today.</p>';
        } else {
            html += '<table class="wl-table"><thead><tr><th style="text-align:left">Analyst</th>';
            USAGE_COLUMNS.forEach(function (col) {
                html += '<th style="text-align:center">' + col.label + '</th>';
            });
            html += '<th style="text-align:center">Actions</th></tr></thead><tbody>';

            pageAnalysts.forEach(function (analyst) {
                var u = allAnalysts[analyst];
                html += '<tr><td style="text-align:left">' + _.escape(analyst) + '</td>';
                USAGE_COLUMNS.forEach(function (col) {
                    var count = u[col.key] || 0;
                    var limit = limits[col.limitKey];
                    if (limit === undefined) { limit = 0; }
                    html += '<td style="text-align:center">' + usageCellHtml(count, limit) + '</td>';
                });
                html += '<td style="text-align:center"><span class="btn btn-small wl-cp-reset-analyst" ' +
                    'data-analyst="' + _.escape(analyst) + '">Reset</span></td></tr>';
            });
            html += '</tbody></table>';

            // Pagination controls
            if (totalPages > 1) {
                html += '<div style="margin-top:6px;display:flex;align-items:center;gap:8px">';
                html += '<span class="btn btn-small' + (usagePage === 0 ? ' disabled" style="pointer-events:none;opacity:.4"' : '"') +
                    ' id="wl-cp-usage-prev">&laquo; Prev</span>';
                html += '<span style="font-size:13px;color:var(--wl-muted,#888)">' +
                    'Page ' + (usagePage + 1) + ' of ' + totalPages +
                    ' (' + analysts.length + ' analysts)</span>';
                html += '<span class="btn btn-small' + (usagePage >= totalPages - 1 ? ' disabled" style="pointer-events:none;opacity:.4"' : '"') +
                    ' id="wl-cp-usage-next">Next &raquo;</span>';
                html += '</div>';
            }
        }

        html += '<div style="margin-top:8px;display:flex;gap:8px;align-items:center">' +
            '<span class="btn" id="wl-cp-refresh-usage">Refresh</span>';
        if (analysts.length) {
            html += '<span class="btn" id="wl-cp-reset-all-usage" ' +
                'style="background:#e74c3c;color:#fff">Reset All</span>';
        }
        html += '<span style="font-size:11px;color:var(--wl-muted,#888);margin-left:8px">' +
            'Auto-refreshes every ' + (USAGE_POLL_MS / 1000) + 's</span>';
        html += '</div>';

        $("#wl-cp-analyst-usage").html(html);

        // Pagination click handlers
        $("#wl-cp-usage-prev").on("click", function () {
            if (usagePage > 0) { usagePage--; renderAnalystUsage(); }
        });
        $("#wl-cp-usage-next").on("click", function () {
            var tp = Math.ceil(Object.keys(cachedUsageData).length / USAGE_PER_PAGE);
            if (usagePage < tp - 1) { usagePage++; renderAnalystUsage(); }
        });

        $("#wl-cp-refresh-usage").on("click", function () { loadAnalystUsage(true); });

        $(".wl-cp-reset-analyst").on("click", function () {
            var analyst = $(this).data("analyst");
            showCpConfirm("Reset Usage",
                "Reset daily usage counters for " + analyst + "?",
                "Reset",
                function () {
                    restPost({ action: "reset_daily_usage", analyst: analyst })
                    .done(function (data) {
                        if (data.error) {
                            showCpAlert("Error", data.error, "error");
                        } else {
                            showCpAlert("Reset", data.message, "success");
                        }
                        loadAnalystUsage(true);
                    })
                    .fail(function () {
                        showCpAlert("Error", "Failed to reset usage.", "error");
                    });
                }
            );
        });

        $("#wl-cp-reset-all-usage").on("click", function () {
            showCpConfirm("Reset All Usage",
                "Reset daily usage counters for all analysts?",
                "Reset All",
                function () {
                    restPost({ action: "reset_daily_usage" })
                    .done(function (data) {
                        if (data.error) {
                            showCpAlert("Error", data.error, "error");
                        } else {
                            showCpAlert("Reset", data.message, "success");
                        }
                        loadAnalystUsage(true);
                    })
                    .fail(function () {
                        showCpAlert("Error", "Failed to reset usage.", "error");
                    });
                }
            );
        });

        // Start auto-refresh polling
        startUsagePoll();
    }

    // ══════════════════════════════════════════════════════════════════
    // Trash Management
    // ══════════════════════════════════════════════════════════════════

    function loadTrash() {
        restPost({ action: "list_trash" })
        .done(function (data) {
            if (data.error) {
                $("#wl-cp-trash").html(
                    '<p style="color:#dc3545;padding:16px">' +
                    _.escape(data.error) + '</p>');
                return;
            }
            renderTrashTable(data.trash || [], data.auto_purged || 0);
        })
        .fail(function () {
            $("#wl-cp-trash").html(
                '<p style="color:#dc3545;padding:16px">Error loading trash</p>');
        });
    }

    function renderTrashTable(items, autoPurged) {
        var html = '<h3 style="margin:8px 0 12px">Trash (' +
            items.length + ' items)</h3>';

        if (autoPurged > 0) {
            html += '<p style="color:var(--wl-muted,#888);font-size:12px;margin-bottom:8px">' +
                autoPurged + ' expired item(s) auto-purged.</p>';
        }

        // Trash config
        html += '<div style="margin-bottom:12px">';
        restPost({ action: "get_trash_config" }).done(function (cfg) {
            var days = (cfg.config || {}).retention_days || 30;
            var configHtml = '<span style="color:var(--wl-muted,#888);font-size:12px">' +
                'Retention period: <strong>' + days + ' days</strong>';
            if (cpIsSuperAdmin) {
                configHtml += ' &mdash; <span class="wl-link" id="wl-trash-change-retention" ' +
                    'style="cursor:pointer;color:var(--wl-accent,#2962ff)">Change</span>';
            }
            configHtml += '</span>';
            $("#wl-trash-config-display").html(configHtml);
        });
        html += '<span id="wl-trash-config-display"></span></div>';

        if (items.length === 0) {
            html += '<p style="color:var(--wl-muted,#888);padding:20px;text-align:center">' +
                'Trash is empty. Deleted rules and CSV files will appear here.</p>';
            $("#wl-cp-trash").html(html);
            return;
        }

        html += '<table class="wl-table" style="width:100%">' +
            '<thead><tr>' +
            '<th>Name</th><th>Type</th><th>Deleted By</th><th>Deleted At</th>' +
            '<th>Days Remaining</th><th>Reason</th><th>Actions</th>' +
            '</tr></thead><tbody>';

        items.forEach(function (item) {
            var tid = _.escape(item.trash_id || "");
            var daysLeft = item.days_remaining || 0;
            var daysClass = daysLeft <= 7 ? 'color:#dc3545;font-weight:bold' :
                daysLeft <= 14 ? 'color:#ffc107' : '';

            html += '<tr>' +
                '<td>' + _.escape(item.name || "") + '</td>' +
                '<td>' + _.escape(item.item_type || "") + '</td>' +
                '<td>' + _.escape(item.deleted_by || "") + '</td>' +
                '<td>' + _.escape(item.deleted_at_human || "") + '</td>' +
                '<td style="' + daysClass + '">' + daysLeft + '</td>' +
                '<td title="' + _.escape(item.comment || "") + '">' +
                _.escape((item.comment || "").substring(0, 60)) +
                (item.comment && item.comment.length > 60 ? "..." : "") + '</td>' +
                '<td>' +
                '<span class="wl-btn wl-btn-primary wl-trash-restore" ' +
                'data-trash-id="' + tid + '" style="cursor:pointer;margin-right:4px">' +
                'Restore</span>';

            if (cpIsSuperAdmin) {
                html += '<span class="wl-btn wl-btn-danger wl-trash-purge" ' +
                    'data-trash-id="' + tid + '" data-name="' +
                    _.escape(item.name || "") + '" style="cursor:pointer">' +
                    'Request Purge</span>';
            }
            html += '</td></tr>';
        });
        html += '</tbody></table>';
        $("#wl-cp-trash").html(html);

        // Restore handler
        $(".wl-trash-restore").on("click", function () {
            var trashId = $(this).data("trash-id");
            showCpConfirm("Restore from Trash",
                "Restore this item to its original location?",
                function () {
                    restPost({
                        action: "restore_from_trash",
                        trash_id: trashId,
                        comment: "Restored via Control Panel"
                    })
                    .done(function (d) {
                        if (d.success) {
                            showCpAlert("Restored", d.message, "success");
                            loadTrash();
                        } else {
                            showCpAlert("Error", d.error || d.message, "error");
                        }
                    })
                    .fail(function () {
                        showCpAlert("Error", "Failed to restore", "error");
                    });
                }
            );
        });

        // Purge handler (superadmin submits dual-approval request)
        $(".wl-trash-purge").on("click", function () {
            var trashId = $(this).data("trash-id");
            var name = $(this).data("name");
            showCpPrompt("Permanent Purge",
                "This will submit a dual-approval request to permanently " +
                "delete '" + _.escape(name) + "'. A second admin must approve. " +
                "Enter your reason:",
                function (reason) {
                    if (!reason || !reason.trim()) {
                        showCpAlert("Error", "A reason is required", "error");
                        return;
                    }
                    restPost({
                        action: "submit_dual_approval",
                        action_type: "admin_purge_trash",
                        trash_id: trashId,
                        comment: reason
                    })
                    .done(function (d) {
                        if (d.success) {
                            showCpAlert("Submitted",
                                "Dual-approval request submitted. A second " +
                                "admin must approve the purge.", "success");
                        } else {
                            showCpAlert("Error", d.error, "error");
                        }
                    })
                    .fail(function () {
                        showCpAlert("Error", "Failed to submit request", "error");
                    });
                }
            );
        });

        // Retention change handler
        $(document).off("click", "#wl-trash-change-retention").on("click",
            "#wl-trash-change-retention", function () {
            showCpPrompt("Set Trash Retention",
                "Enter new retention period in days (7-365). " +
                "Minimum 7 days ensures a recovery window:",
                function (val) {
                    var days = parseInt(val, 10);
                    if (isNaN(days) || days < 7 || days > 365) {
                        showCpAlert("Error",
                            "Must be a number between 7 and 365", "error");
                        return;
                    }
                    restPost({
                        action: "set_trash_retention",
                        retention_days: days,
                        comment: "Changed via Control Panel"
                    })
                    .done(function (d) {
                        if (d.success) {
                            showCpAlert("Updated", d.message, "success");
                            loadTrash();
                        } else {
                            showCpAlert("Error", d.error, "error");
                        }
                    });
                }
            );
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Admin Limits (superadmin-only)
    // ══════════════════════════════════════════════════════════════════

    function loadAdminLimits() {
        if (!cpIsSuperAdmin) {
            $("#wl-cp-admin-limits").html(
                '<p style="color:var(--wl-muted,#888);padding:20px">' +
                'Only super-admins can view and modify admin limits.</p>');
            return;
        }
        restPost({ action: "get_admin_limits" })
        .done(function (data) {
            if (data.error) {
                $("#wl-cp-admin-limits").html(
                    '<p style="color:#dc3545;padding:16px">' +
                    _.escape(data.error) + '</p>');
                return;
            }
            renderAdminLimitsForm(
                data.admin_limits || {},
                data.defaults || {});
        })
        .fail(function () {
            $("#wl-cp-admin-limits").html(
                '<p style="color:#dc3545;padding:16px">' +
                'Error loading admin limits</p>');
        });
    }

    function renderAdminLimitsForm(limits, defaults) {
        var fields = [
            {key: "rule_deletion", label: "Rule deletions per period",
             desc: "Max rules an admin can soft-delete per period"},
            {key: "csv_deletion", label: "CSV deletions per period",
             desc: "Max CSVs an admin can soft-delete per period"},
            {key: "approval_count", label: "Approvals per period",
             desc: "Max approval actions an admin can perform per period"},
            {key: "limit_changes", label: "Limit config changes per period",
             desc: "Max times an admin can change editor limits per period"},
        ];

        var html = '<h3 style="margin:8px 0 4px">Admin Daily Limits</h3>' +
            '<p style="color:var(--wl-muted,#888);font-size:12px;margin-bottom:12px">' +
            'These limits restrict admin actions. Super-admins are exempt. ' +
            'Set 0 for unlimited.</p>';

        html += '<table class="wl-table" style="width:auto;min-width:500px">' +
            '<thead><tr><th>Limit</th><th>Current</th><th>Default</th>' +
            '<th>New Value</th></tr></thead><tbody>';

        fields.forEach(function (f) {
            var cur = limits[f.key];
            var def = defaults[f.key];
            if (cur === undefined) cur = def;
            html += '<tr>' +
                '<td title="' + _.escape(f.desc) + '">' + _.escape(f.label) + '</td>' +
                '<td>' + cur + '</td>' +
                '<td style="color:var(--wl-muted,#888)">' + def + '</td>' +
                '<td><input type="number" class="wl-admin-limit-input" ' +
                'data-key="' + f.key + '" value="' + cur + '" ' +
                'min="0" max="9999" style="width:80px;padding:4px 8px;' +
                'background:var(--wl-bg-main,#1a1c1e);color:var(--wl-text,#e0e0e0);' +
                'border:1px solid var(--wl-border,#444);border-radius:4px"></td>' +
                '</tr>';
        });
        html += '</tbody></table>';

        html += '<div style="margin-top:12px">' +
            '<span class="wl-btn wl-btn-primary" id="wl-save-admin-limits" ' +
            'style="cursor:pointer">Save Admin Limits</span> ' +
            '<span class="wl-btn" id="wl-reset-admin-limits" ' +
            'style="cursor:pointer">Reset to Defaults</span></div>';

        $("#wl-cp-admin-limits").html(html);

        // Save handler
        $("#wl-save-admin-limits").on("click", function () {
            var newLimits = {};
            var changed = false;
            $(".wl-admin-limit-input").each(function () {
                var key = $(this).data("key");
                var val = parseInt($(this).val(), 10);
                if (!isNaN(val) && val !== limits[key]) {
                    newLimits[key] = val;
                    changed = true;
                }
            });
            if (!changed) {
                showCpAlert("No Changes", "No values were changed.", "info");
                return;
            }
            restPost({
                action: "set_admin_limits",
                limits: newLimits,
                comment: "Updated via Control Panel"
            })
            .done(function (d) {
                if (d.success) {
                    showCpAlert("Saved", "Admin limits updated.", "success");
                    loadAdminLimits();
                } else {
                    showCpAlert("Error", d.error, "error");
                }
            })
            .fail(function () {
                showCpAlert("Error", "Failed to save admin limits", "error");
            });
        });

        // Reset handler
        $("#wl-reset-admin-limits").on("click", function () {
            showCpConfirm("Reset Admin Limits",
                "Reset all admin limits to factory defaults?",
                function () {
                    restPost({
                        action: "set_admin_limits",
                        limits: defaults,
                        comment: "Reset to factory defaults"
                    })
                    .done(function (d) {
                        if (d.success) {
                            showCpAlert("Reset", "Admin limits reset to defaults.", "success");
                            loadAdminLimits();
                        } else {
                            showCpAlert("Error", d.error, "error");
                        }
                    });
                }
            );
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Prompt modal helper (for text input)
    // ══════════════════════════════════════════════════════════════════

    function showCpPrompt(title, message, onConfirm) {
        var html =
            '<div class="wl-modal-overlay" id="wl-cp-prompt-overlay" ' +
            'style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:10000;' +
            'display:flex;align-items:center;justify-content:center">' +
            '<div class="wl-modal" style="background:var(--wl-bg-main,#1a1c1e);' +
            'border:1px solid var(--wl-border,#444);border-radius:8px;padding:24px;' +
            'width:450px;max-width:90%">' +
            '<h3 style="margin:0 0 8px;color:var(--wl-text,#e0e0e0)">' +
            _.escape(title) + '</h3>' +
            '<p style="margin:0 0 12px;color:var(--wl-muted,#888)">' +
            _.escape(message) + '</p>' +
            '<input type="text" id="wl-cp-prompt-input" style="width:100%;padding:8px;' +
            'background:var(--wl-bg-row,#23272b);color:var(--wl-text,#e0e0e0);' +
            'border:1px solid var(--wl-border,#444);border-radius:4px;margin-bottom:12px;' +
            'box-sizing:border-box">' +
            '<div style="text-align:right">' +
            '<span class="wl-btn" id="wl-cp-prompt-cancel" style="cursor:pointer;margin-right:8px">' +
            'Cancel</span>' +
            '<span class="wl-btn wl-btn-primary" id="wl-cp-prompt-ok" style="cursor:pointer">' +
            'OK</span></div></div></div>';

        $("body").append(html);
        $("#wl-cp-prompt-input").focus();

        function close() {
            $("#wl-cp-prompt-overlay").remove();
        }

        $("#wl-cp-prompt-cancel").on("click", close);
        $("#wl-cp-prompt-ok").on("click", function () {
            var val = $("#wl-cp-prompt-input").val();
            close();
            onConfirm(val);
        });
        $("#wl-cp-prompt-input").on("keydown", function (e) {
            if (e.key === "Enter") {
                var val = $(this).val();
                close();
                onConfirm(val);
            }
            if (e.key === "Escape") { close(); }
        });
    }
});
