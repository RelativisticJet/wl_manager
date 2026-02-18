/**
 * Whitelist Manager — Frontend Controller
 *
 * This script powers the editable CSV table and diff display on the
 * "Whitelist Manager" dashboard. It:
 *
 *   1. Listens for token changes (rule_token, csv_token, app_token)
 *   2. Fetches CSV content from the Python REST handler
 *   3. Renders an editable HTML table with add/remove row buttons
 *   4. Sends save requests with the updated rows
 *   5. Displays a Git-style diff of added/removed rows after save
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
    // Token references
    // ══════════════════════════════════════════════════════════════════
    var defaultTokens   = mvc.Components.get("default");
    var submittedTokens = mvc.Components.get("submitted");

    // ══════════════════════════════════════════════════════════════════
    // State
    // ══════════════════════════════════════════════════════════════════
    var currentHeaders = [];
    var currentRows    = [];
    var originalRows   = [];

    // ══════════════════════════════════════════════════════════════════
    // DOM references
    // ══════════════════════════════════════════════════════════════════
    var $table = $("#csv-table-container");
    var $msg   = $("#message-container");
    var $diff  = $("#diff-container");

    // ══════════════════════════════════════════════════════════════════
    // REST helpers
    // ══════════════════════════════════════════════════════════════════
    function restUrl() {
        // Use Splunk Web's built-in proxy to reach splunkd REST API.
        // The /splunkd/__raw/ prefix routes through Splunk Web to the
        // management API, using the browser's session cookie for auth.
        return Splunk.util.make_url(
            "/splunkd/__raw/services/custom/wl_manager"
        );
    }

    function restGet(params) {
        params = params || {};
        params.output_mode = "json";
        return $.ajax({
            url:      restUrl(),
            type:     "GET",
            data:     params,
            dataType: "json"
        });
    }

    function restPost(payload) {
        return $.ajax({
            url:         restUrl() + "?output_mode=json",
            type:        "POST",
            contentType: "application/json",
            data:        JSON.stringify(payload),
            dataType:    "json"
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Messages
    // ══════════════════════════════════════════════════════════════════
    function showMsg(text, type) {
        var cls = {
            error:   "wl-alert wl-alert-error",
            success: "wl-alert wl-alert-success",
            info:    "wl-alert wl-alert-info",
            warning: "wl-alert wl-alert-warning"
        }[type || "info"] || "wl-alert wl-alert-info";

        $msg.html(
            '<div class="' + cls + '">' +
            '<span class="wl-alert-close">&times;</span>' +
            text +
            "</div>"
        );
    }

    $msg.on("click", ".wl-alert-close", function () {
        $(this).parent().fadeOut(200, function () { $(this).remove(); });
    });

    // ══════════════════════════════════════════════════════════════════
    // Table rendering
    // ══════════════════════════════════════════════════════════════════
    function renderTable(headers, rows) {
        currentHeaders = headers;
        currentRows    = rows.map(function (r) { return $.extend({}, r); });
        // Keep a deep copy for discard
        originalRows = rows.map(function (r) { return $.extend({}, r); });

        if (!headers.length) {
            $table.html('<p class="wl-muted">This CSV file is empty.</p>');
            return;
        }

        var html = '<table class="wl-table">';

        // ── thead ────────────────────────────────────────────────────
        html += "<thead><tr>";
        headers.forEach(function (h) {
            html += "<th>" + _.escape(h) + "</th>";
        });
        html += '<th class="wl-col-actions">Actions</th>';
        html += "</tr></thead>";

        // ── tbody ────────────────────────────────────────────────────
        html += "<tbody>";
        rows.forEach(function (row, idx) {
            html += buildRow(headers, row, idx);
        });
        html += "</tbody></table>";

        // ── buttons ──────────────────────────────────────────────────
        html += '<div class="wl-buttons">';
        html += '<button class="btn btn-primary" id="btn-add-row">+ Add Row</button> ';
        html += '<button class="btn btn-success" id="btn-save">Save Changes</button> ';
        html += '<button class="btn"             id="btn-discard">Discard Changes</button>';
        html += "</div>";

        $table.html(html);
        bindTableEvents();
    }

    function buildRow(headers, row, idx) {
        var html = '<tr data-idx="' + idx + '">';
        headers.forEach(function (h) {
            var val = row[h] || "";
            html +=
                "<td>" +
                '<input type="text" class="wl-input" ' +
                'data-header="' + _.escape(h) + '" ' +
                'value="' + _.escape(val) + '" />' +
                "</td>";
        });
        html +=
            '<td class="wl-col-actions">' +
            '<button class="btn btn-small btn-danger btn-rm" data-idx="' + idx + '">' +
            "Remove</button></td>";
        html += "</tr>";
        return html;
    }

    // ══════════════════════════════════════════════════════════════════
    // Table events
    // ══════════════════════════════════════════════════════════════════
    function bindTableEvents() {
        // Sync input → currentRows on change
        $table.off("change.wl", ".wl-input").on("change.wl", ".wl-input", function () {
            var $el    = $(this);
            var idx    = $el.closest("tr").data("idx");
            var header = $el.data("header");
            if (currentRows[idx]) {
                currentRows[idx][header] = $el.val();
            }
        });

        // Remove row
        $table.off("click.wl", ".btn-rm").on("click.wl", ".btn-rm", function () {
            var idx = $(this).data("idx");
            currentRows.splice(idx, 1);
            renderTable(currentHeaders, currentRows);
        });

        // Add row
        $table.off("click.wl", "#btn-add-row").on("click.wl", "#btn-add-row", function () {
            var newRow = {};
            currentHeaders.forEach(function (h) { newRow[h] = ""; });
            currentRows.push(newRow);
            renderTable(currentHeaders, currentRows);
            // Focus the first input of the new row
            $table.find("tbody tr:last input:first").focus();
        });

        // Save
        $table.off("click.wl", "#btn-save").on("click.wl", "#btn-save", function () {
            doSave();
        });

        // Discard
        $table.off("click.wl", "#btn-discard").on("click.wl", "#btn-discard", function () {
            currentRows = originalRows.map(function (r) { return $.extend({}, r); });
            renderTable(currentHeaders, currentRows);
            $diff.empty();
            showMsg("Changes discarded.", "info");
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Load CSV content from REST
    // ══════════════════════════════════════════════════════════════════
    function loadCsv(csvFile, appContext) {
        $msg.empty();
        $diff.empty();
        $table.html('<p class="wl-muted">Loading CSV content&hellip;</p>');

        restGet({
            action:   "get_csv_content",
            csv_file: csvFile,
            app:      appContext || ""
        })
        .done(function (data) {
            if (data.error) {
                showMsg(data.error, "error");
                $table.empty();
                return;
            }
            renderTable(data.headers || [], data.rows || []);
        })
        .fail(function (xhr) {
            var err = "Failed to load CSV.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { /* ignore */ }
            showMsg(err, "error");
            $table.empty();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save CSV via REST
    // ══════════════════════════════════════════════════════════════════
    function doSave() {
        // Flush any un-changed inputs
        $table.find("tbody tr").each(function (idx) {
            $(this).find(".wl-input").each(function () {
                var header = $(this).data("header");
                if (currentRows[idx]) {
                    currentRows[idx][header] = $(this).val();
                }
            });
        });

        var csvFile = defaultTokens.get("csv_token");
        var rule    = defaultTokens.get("rule_token");
        var appCtx  = defaultTokens.get("app_token") || "";

        if (!csvFile) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        // ── Require a comment for audit purposes ─────────────────────
        var comment = prompt(
            "Enter a comment describing this change (required for audit):",
            ""
        );
        if (comment === null) { return; }           // user cancelled
        if (!comment.trim()) {
            showMsg("A comment is required for audit purposes.", "warning");
            return;
        }

        showMsg("Saving&hellip;", "info");

        restPost({
            action:         "save_csv",
            csv_file:       csvFile,
            app_context:    appCtx,
            detection_rule: rule || "",
            headers:        currentHeaders,
            rows:           currentRows,
            comment:        comment.trim()
        })
        .done(function (data) {
            if (data.error) {
                showMsg(data.error, "error");
                return;
            }

            var diffInfo = data.diff || {};
            showMsg(
                "Saved successfully. " +
                "Added: <strong>" + (diffInfo.added_count || 0) + "</strong> row(s), " +
                "Removed: <strong>" + (diffInfo.removed_count || 0) + "</strong> row(s).",
                "success"
            );

            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            // Refresh original rows reference so Discard works correctly
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
        })
        .fail(function (xhr) {
            var err = "Failed to save CSV.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { /* ignore */ }
            showMsg(err, "error");
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Diff rendering (Git-style)
    // ══════════════════════════════════════════════════════════════════
    function renderDiff(diff) {
        var html = '<div class="wl-diff">';
        html += "<h4>Change Summary</h4>";

        // Added entries
        if (diff.added && diff.added.length) {
            html += '<div class="wl-diff-section wl-diff-added">';
            html += "<h5>Added (" + diff.added.length + " row" + (diff.added.length > 1 ? "s" : "") + ")</h5><ul>";
            diff.added.forEach(function (row) {
                html += "<li>" + _.escape(JSON.stringify(row)) + "</li>";
            });
            html += "</ul></div>";
        }

        // Removed entries
        if (diff.removed && diff.removed.length) {
            html += '<div class="wl-diff-section wl-diff-removed">';
            html += "<h5>Removed (" + diff.removed.length + " row" + (diff.removed.length > 1 ? "s" : "") + ")</h5><ul>";
            diff.removed.forEach(function (row) {
                html += "<li>" + _.escape(JSON.stringify(row)) + "</li>";
            });
            html += "</ul></div>";
        }

        // Unified diff
        if (diff.text_diff && diff.text_diff.length) {
            html += '<div class="wl-diff-section"><h5>Unified Diff</h5><pre class="wl-diff-pre">';
            diff.text_diff.forEach(function (line) {
                var cls = "";
                if (line.charAt(0) === "+" && line.charAt(1) !== "+") {
                    cls = "wl-diff-line-add";
                } else if (line.charAt(0) === "-" && line.charAt(1) !== "-") {
                    cls = "wl-diff-line-rm";
                } else if (line.charAt(0) === "@") {
                    cls = "wl-diff-line-info";
                }
                html += '<span class="' + cls + '">' + _.escape(line) + "</span>\n";
            });
            html += "</pre></div>";
        }

        html += "</div>";
        $diff.html(html);
    }

    // ══════════════════════════════════════════════════════════════════
    // Token listeners — react to dropdown changes
    // ══════════════════════════════════════════════════════════════════
    defaultTokens.on("change:csv_token", function (_model, value) {
        if (value) {
            // Small delay to let app_token resolve from the hidden search
            setTimeout(function () {
                var appCtx = defaultTokens.get("app_token") || "";
                loadCsv(value, appCtx);
            }, 300);
        } else {
            $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
            $diff.empty();
        }
    });

    // When rule changes and csv_error is set, clear the table
    defaultTokens.on("change:csv_error", function (_model, value) {
        if (value) {
            $table.empty();
            $diff.empty();
        }
    });

});
