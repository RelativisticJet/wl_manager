/**
 * Approval Queue Module — AMD
 *
 * Manages the approval queue tab: pending requests, request history,
 * approve/reject/cancel handlers, polling, and CSV download.
 *
 * Exports: init, load, startPolling, stopPolling, getPendingCount
 */

define([
    'jquery',
    'modules/wl_rest',
    'modules/wl_constants'
], function($, REST, Constants) {
    'use strict';

    // Module-local state
    var queueItems = [];
    var currentPage = 1;
    var totalPending = 0;
    var pendingCount = 0;
    var pollingInterval = null;
    var showingHistory = false;
    var searchText = "";
    var searchTimeout = null;
    var ITEMS_PER_PAGE = 10;
    var $queueContent = null;
    var ctx = null;

    function init(context) {
        ctx = context;
        if (!ctx.isAdmin) {
            return Promise.reject("Access denied: admin role required");
        }

        $queueContent = $("#wl-cp-tab-queue");
        if (!$queueContent.length) {
            return Promise.reject("Queue tab container not found");
        }

        // Bind event handlers
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-approve-btn", approveClick);
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-reject-btn", rejectClick);
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-cancel-btn", cancelClick);
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-history-toggle", toggleHistoryClick);
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-download-csv-btn", downloadClick);
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-queue-page-prev", prevPageClick);
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-queue-page-next", nextPageClick);
        $(document).off("input.wlqueue").on("input.wlqueue", ".wl-cp-queue-search", searchInput);
        $(document).off("click.wlqueue").on("click.wlqueue", ".wl-cp-queue-search-clear", clearSearchClick);

        return load();
    }

    function load() {
        // Modal guard: skip if modal is open
        if ($(".wl-modal-overlay").length > 0) {
            return Promise.resolve();
        }

        return REST.restGet({ action: "get_approval_queue" }).done(function(data) {
            queueItems = data.queue || [];
            totalPending = queueItems.filter(function(q) { return q.status === "pending"; }).length;
            render();
        }).fail(function(xhr) {
            var err = "Error loading queue";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
            ctx.showAlert("Error", err);
        });
    }

    function render() {
        var html = '';

        // Heading
        html += '<h3 style="margin:12px 0 4px;font-size:18px;font-weight:600">Approval Queue</h3>';
        html += '<p style="margin:0 0 12px;font-size:14px;color:var(--wl-muted,#888)">Pending requests and approval history</p>';

        // Search bar
        html += '<div style="margin-bottom:12px;display:flex;gap:8px">' +
            '<input type="text" class="wl-cp-queue-search" placeholder="Filter by rule, CSV, or analyst…" ' +
                'value="' + _.escape(searchText) + '" style="flex:1;padding:8px;border:1px solid var(--wl-border,#ddd);border-radius:4px">' +
            '<span class="wl-cp-queue-search-clear btn" style="' +
                (searchText ? '' : 'display:none;') +
                'cursor:pointer;padding:8px 12px;">Clear</span>' +
            '<span class="btn btn-primary wl-cp-download-csv-btn" style="cursor:pointer;padding:8px 12px;">Download Queue CSV</span>' +
            '</div>';

        // Pending requests
        var filtered = filterQueue();
        var totalFiltered = filtered.length;
        var totalPages = Math.max(1, Math.ceil(totalFiltered / ITEMS_PER_PAGE));
        if (currentPage > totalPages) currentPage = totalPages;

        var pageStart = (currentPage - 1) * ITEMS_PER_PAGE;
        var pageEnd = pageStart + ITEMS_PER_PAGE;
        var pageItems = filtered.slice(pageStart, pageEnd);

        html += '<h4 style="margin:8px 0">Pending Requests (' + totalFiltered + ')</h4>';

        if (!pageItems.length) {
            html += '<p style="color:var(--wl-muted,#888);font-size:13px">No pending approvals' +
                (searchText ? ' matching "' + _.escape(searchText) + '"' : '') + '</p>';
        } else {
            html += '<table class="wl-table" style="width:100%;border-collapse:collapse">' +
                '<thead><tr>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Rule</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">CSV</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Type</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Analyst</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd);max-width:200px">Reason</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Submitted</th>' +
                '<th style="text-align:center;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Actions</th>' +
                '</tr></thead><tbody>';

            pageItems.forEach(function(item) {
                var ruleDisplay = item.detection_rule || "(new rule)";
                var csvDisplay = item.csv_file === "__rule_operation__" ? "N/A" : (item.csv_file || "");
                var typeDisplay = item.action_type ? item.action_type.replace(/_/g, " ") : "";
                var analystName = item.analyst || "";
                var reason = extractReason(item);
                var tsStr = formatTimestamp(item.timestamp);
                var isOwn = ctx.currentUser && item.analyst === ctx.currentUser;

                html += '<tr style="border-bottom:1px solid var(--wl-border-light,#f0f0f0);hover:background-color:rgba(0,0,255,0.05)">' +
                    '<td style="padding:8px">' + _.escape(ruleDisplay) + '</td>' +
                    '<td style="padding:8px">' + _.escape(csvDisplay) + '</td>' +
                    '<td style="padding:8px"><span style="background:#e3f2fd;color:#1976d2;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:600">Pending</span></td>' +
                    '<td style="padding:8px">' + _.escape(analystName) + '</td>' +
                    '<td style="padding:8px;max-width:200px;white-space:normal;word-wrap:break-word;color:var(--wl-text-secondary,#555)">' + _.escape(reason) + '</td>' +
                    '<td style="padding:8px;font-size:12px;color:var(--wl-muted,#888)">' + tsStr + '</td>' +
                    '<td style="padding:8px;text-align:center;white-space:nowrap">';

                if (isOwn) {
                    html += '<span class="btn btn-small wl-cp-cancel-btn" data-id="' + _.escape(item.request_id) + '" ' +
                        'style="background:#f39c12;color:#fff;cursor:pointer;padding:4px 8px;font-size:12px;border-radius:3px;margin:0 2px">Cancel</span>';
                } else {
                    html += '<span class="btn btn-small wl-cp-approve-btn" data-id="' + _.escape(item.request_id) + '" ' +
                        'style="background:#27ae60;color:#fff;cursor:pointer;padding:4px 8px;font-size:12px;border-radius:3px;margin:0 2px">Approve</span>' +
                        '<span class="btn btn-small wl-cp-reject-btn" data-id="' + _.escape(item.request_id) + '" ' +
                        'style="background:#e74c3c;color:#fff;cursor:pointer;padding:4px 8px;font-size:12px;border-radius:3px;margin:0 2px">Reject</span>';
                }

                html += '</td></tr>';
            });

            html += '</tbody></table>';

            // Pagination
            if (totalPages > 1) {
                var from = pageStart + 1;
                var to = Math.min(pageEnd, totalFiltered);
                var prevDisabled = currentPage === 1;
                var nextDisabled = currentPage >= totalPages;

                html += '<div style="display:flex;align-items:center;gap:10px;margin:8px 0">' +
                    '<span class="btn btn-small wl-cp-queue-page-prev" style="' +
                        (prevDisabled ? 'opacity:0.4;pointer-events:none;' : 'cursor:pointer;') + '">« Prev</span>' +
                    '<span style="color:var(--wl-muted,#888);font-size:13px">' + from + '–' + to + ' of ' + totalFiltered +
                        ' (page ' + currentPage + ' of ' + totalPages + ')</span>' +
                    '<span class="btn btn-small wl-cp-queue-page-next" style="' +
                        (nextDisabled ? 'opacity:0.4;pointer-events:none;' : 'cursor:pointer;') + '">Next »</span>' +
                    '</div>';
            }
        }

        // History section
        var historyItems = queueItems.filter(function(q) { return q.status !== "pending"; });
        html += '<div style="margin-top:20px">';
        html += '<h4 style="margin:8px 0;cursor:pointer" class="wl-cp-history-toggle" style="cursor:pointer">' +
            (showingHistory ? '▼' : '▶') + ' Request History (' + historyItems.length + ')</h4>';

        if (showingHistory && historyItems.length) {
            html += '<table class="wl-table" style="width:100%;border-collapse:collapse;margin-top:8px">' +
                '<thead><tr>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Rule</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">CSV</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Analyst</th>' +
                '<th style="text-align:left;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Submitted</th>' +
                '<th style="text-align:center;padding:8px;border-bottom:2px solid var(--wl-border,#ddd)">Status</th>' +
                '</tr></thead><tbody>';

            historyItems.slice(0, 50).forEach(function(item) {
                var ruleDisplay = item.detection_rule || "(new rule)";
                var csvDisplay = item.csv_file === "__rule_operation__" ? "N/A" : (item.csv_file || "");
                var statusColor = item.status === "approved" ? "#27ae60" :
                                  item.status === "rejected" ? "#e74c3c" :
                                  item.status === "cancelled" ? "#f39c12" : "#888";
                var tsStr = formatTimestamp(item.timestamp);

                html += '<tr style="border-bottom:1px solid var(--wl-border-light,#f0f0f0)">' +
                    '<td style="padding:8px">' + _.escape(ruleDisplay) + '</td>' +
                    '<td style="padding:8px">' + _.escape(csvDisplay) + '</td>' +
                    '<td style="padding:8px">' + _.escape(item.analyst || "") + '</td>' +
                    '<td style="padding:8px;font-size:12px;color:var(--wl-muted,#888)">' + tsStr + '</td>' +
                    '<td style="padding:8px;text-align:center;font-weight:600;color:' + statusColor + '">' +
                        _.escape(item.status || "") + '</td>' +
                    '</tr>';
            });

            html += '</tbody></table>';
        }
        html += '</div>';

        $queueContent.html(html);
    }

    function filterQueue() {
        if (!searchText) return queueItems;
        var needle = searchText.toLowerCase();
        return queueItems.filter(function(item) {
            var rule = (item.detection_rule || "").toLowerCase();
            var csv = (item.csv_file || "").toLowerCase();
            var analyst = (item.analyst || "").toLowerCase();
            return rule.indexOf(needle) >= 0 || csv.indexOf(needle) >= 0 || analyst.indexOf(needle) >= 0;
        });
    }

    function extractReason(item) {
        var reason = item.comment || item.description || "";
        if (!reason && item.payload) {
            var p = item.payload;
            var at = item.action_type || "";
            if (at === "bulk_row_removal") {
                var br = p.bulk_removal;
                if (br && br.length) reason = br[0].reason || "";
            } else if (at === "bulk_row_addition") {
                reason = p.row_add_reason || "";
            }
        }
        return reason;
    }

    function formatTimestamp(ts) {
        if (!ts) return "";
        var d = new Date(ts * 1000);
        return d.toLocaleString();
    }

    function approveClick() {
        var requestId = $(this).data("id");
        var request = findRequest(requestId);
        if (!request) {
            ctx.showAlert("Error", "Request not found");
            return;
        }

        var summary = "Approve " + _.escape(request.detection_rule || "(new rule)") +
                      " [" + _.escape(request.action_type) + "]?";
        ctx.showConfirm("Approve Request", summary, { okLabel: "Approve" }).then(function(confirmed) {
            if (!confirmed) return;

            var $btn = $(".wl-cp-approve-btn[data-id='" + requestId + "']");
            $btn.text("Approving...").css("pointer-events", "none");

            REST.restPost({
                action: "process_approval",
                request_id: requestId,
                decision: "approve"
            }).done(function(data) {
                if (data.error) {
                    ctx.showAlert("Error", data.error);
                    $btn.text("Approve").css("pointer-events", "auto");
                } else {
                    ctx.showAlert("Success", "Request approved");
                    load();
                }
            }).fail(function(xhr) {
                var err = "Failed to approve request";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                ctx.showAlert("Error", err);
                $btn.text("Approve").css("pointer-events", "auto");
            });
        });
    }

    function rejectClick() {
        var requestId = $(this).data("id");
        var request = findRequest(requestId);
        if (!request) {
            ctx.showAlert("Error", "Request not found");
            return;
        }

        ctx.showConfirm("Reject Request", "Reject this request? The analyst will be notified.",
            { okLabel: "Reject" }).then(function(confirmed) {
            if (!confirmed) return;

            var $btn = $(".wl-cp-reject-btn[data-id='" + requestId + "']");
            $btn.text("Rejecting...").css("pointer-events", "none");

            REST.restPost({
                action: "process_approval",
                request_id: requestId,
                decision: "reject"
            }).done(function(data) {
                if (data.error) {
                    ctx.showAlert("Error", data.error);
                    $btn.text("Reject").css("pointer-events", "auto");
                } else {
                    ctx.showAlert("Success", "Request rejected");
                    load();
                }
            }).fail(function(xhr) {
                var err = "Failed to reject request";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                ctx.showAlert("Error", err);
                $btn.text("Reject").css("pointer-events", "auto");
            });
        });
    }

    function cancelClick() {
        var requestId = $(this).data("id");
        var request = findRequest(requestId);
        if (!request) {
            ctx.showAlert("Error", "Request not found");
            return;
        }

        ctx.showConfirm("Cancel Request", "Cancel this request? This action cannot be undone.",
            { okLabel: "Cancel" }).then(function(confirmed) {
            if (!confirmed) return;

            var $btn = $(".wl-cp-cancel-btn[data-id='" + requestId + "']");
            $btn.text("Cancelling...").css("pointer-events", "none");

            REST.restPost({
                action: "cancel_request",
                request_id: requestId
            }).done(function(data) {
                if (data.error) {
                    ctx.showAlert("Error", data.error);
                    $btn.text("Cancel").css("pointer-events", "auto");
                } else {
                    ctx.showAlert("Success", "Request cancelled");
                    load();
                }
            }).fail(function(xhr) {
                var err = "Failed to cancel request";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                ctx.showAlert("Error", err);
                $btn.text("Cancel").css("pointer-events", "auto");
            });
        });
    }

    function toggleHistoryClick() {
        showingHistory = !showingHistory;
        render();
    }

    function searchInput() {
        var text = $(this).val();
        if (searchTimeout) clearTimeout(searchTimeout);
        searchTimeout = setTimeout(function() {
            searchText = text;
            currentPage = 1;
            render();
        }, 300);
    }

    function clearSearchClick() {
        searchText = "";
        currentPage = 1;
        $(".wl-cp-queue-search").val("");
        render();
    }

    function downloadClick() {
        var rows = [];
        queueItems.forEach(function(item) {
            rows.push({
                Rule: item.detection_rule || "(new rule)",
                CSV: item.csv_file === "__rule_operation__" ? "N/A" : (item.csv_file || ""),
                Type: item.action_type || "",
                Analyst: item.analyst || "",
                Reason: extractReason(item),
                Submitted: formatTimestamp(item.timestamp),
                Status: item.status || ""
            });
        });

        var headers = ["Rule", "CSV", "Type", "Analyst", "Reason", "Submitted", "Status"];
        var csv = headers.map(escapeCsvField).join(",") + "\n";
        rows.forEach(function(row) {
            csv += headers.map(function(h) { return escapeCsvField(row[h] || ""); }).join(",") + "\n";
        });

        var blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "queue-" + new Date().getTime() + ".csv";
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

    function prevPageClick() {
        if (currentPage > 1) {
            currentPage--;
            render();
        }
    }

    function nextPageClick() {
        var filtered = filterQueue();
        var totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
        if (currentPage < totalPages) {
            currentPage++;
            render();
        }
    }

    function findRequest(id) {
        for (var i = 0; i < queueItems.length; i++) {
            if (queueItems[i].request_id === id) {
                return queueItems[i];
            }
        }
        return null;
    }

    function startPolling() {
        stopPolling();
        pollingInterval = setInterval(function() {
            // Modal guard
            if ($(".wl-modal-overlay").length > 0) return;

            load().done(function() {
                var newCount = queueItems.filter(function(q) { return q.status === "pending"; }).length;
                if (newCount > pendingCount) {
                    $(document).trigger("wl:newPendingRequests", { newCount: newCount, prevCount: pendingCount });
                }
                pendingCount = newCount;
            });
        }, 5000);
    }

    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    function getPendingCount() {
        return pendingCount;
    }

    return {
        init: init,
        load: load,
        startPolling: startPolling,
        stopPolling: stopPolling,
        getPendingCount: getPendingCount
    };
});
