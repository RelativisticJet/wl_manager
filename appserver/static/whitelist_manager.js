/**
 * Whitelist Manager — Frontend Controller
 *
 * Features:
 *   1. Searchable detection rule dropdown (300+ rules)
 *   2. Editable CSV table with add/remove row buttons
 *   3. Comment column validation (required for audit)
 *   4. Auto-save on row removal with reason prompt
 *   5. 10-second Undo bar after row removal
 *   6. Bulk CSV import (upload) and export (download)
 *   7. Expiration date highlighting (yellow for expired rows)
 *   8. Row-level change history tooltips (added_by, added_at)
 *   9. Git-style diff display after save
 *  10. Auto-removal of expired rows with alert banner
 *  11. Date/time picker for Expires column with presets
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
    // State
    // ══════════════════════════════════════════════════════════════════
    var currentHeaders = [];
    var currentRows    = [];
    var originalRows   = [];
    var selectedRule    = "";
    var selectedCsv     = "";
    var selectedApp     = "";
    var allRules        = [];
    var mappingData     = [];
    var undoTimer       = null;     // timeout id for undo bar
    var undoState       = null;     // {row, reason, prevRows, prevOriginal}
    var saving           = false;   // debounce flag to prevent rapid saves
    var currentPage      = 0;       // zero-based page index for CSV table
    var ROWS_PER_PAGE    = 10;      // rows visible per page
    var selectedIdxSet   = {};      // tracks selected row indices across pages (key=idx, value=true)
    var expireColumn     = "";      // name of the expiration column (e.g. "Expires", "expiry", "termination_date")

    // ══════════════════════════════════════════════════════════════════
    // Dark theme detection
    // ══════════════════════════════════════════════════════════════════
    // Splunk loads separate CSS files for dark/light — no body class.
    // Detect by checking the computed background-color of <body>.
    (function detectDarkTheme() {
        var bg = window.getComputedStyle(document.body).backgroundColor;
        // Parse rgb(r,g,b) — if average brightness < 128 it's dark
        var m = bg.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (m) {
            var brightness = (parseInt(m[1]) + parseInt(m[2]) + parseInt(m[3])) / 3;
            if (brightness < 128) {
                $("#wl-dropdowns").closest(".dashboard-panel").addClass("wl-dark");
            }
        }
    })();

    // ══════════════════════════════════════════════════════════════════
    // DOM references
    // ══════════════════════════════════════════════════════════════════
    var $table      = $("#csv-table-container");
    var $msg        = $("#message-container");
    var $diff       = $("#diff-container");
    var $ruleSearch = $("#rule-search");
    var $ruleList   = $("#rule-list");
    var $csvSelect  = $("#csv-select");
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
    // Searchable Detection Rule Dropdown
    // ══════════════════════════════════════════════════════════════════

    function loadRules() {
        restGet({ action: "get_mapping" })
        .done(function (data) {
            mappingData = data.mapping || [];
            var ruleSet = {};
            mappingData.forEach(function (m) {
                ruleSet[m.rule_name] = true;
            });
            allRules = Object.keys(ruleSet).sort();
            renderRuleList(allRules);
        })
        .fail(function () {
            showMsg("Failed to load detection rules.", "error");
        });
    }

    function renderRuleList(rules) {
        if (!rules.length) {
            $ruleList.html('<div class="wl-dropdown-no-match">No matching rules</div>');
            return;
        }
        var html = "";
        rules.forEach(function (rule) {
            var cls = "wl-dropdown-item";
            if (rule === selectedRule) { cls += " wl-selected"; }
            html += '<div class="' + cls + '" data-value="' + _.escape(rule) + '">' +
                    _.escape(rule) + '</div>';
        });
        $ruleList.html(html);
    }

    $ruleSearch.on("focus", function () {
        $ruleList.addClass("wl-open");
        renderRuleList(filterRules($ruleSearch.val()));
    });

    $ruleSearch.on("input", function () {
        var filtered = filterRules($(this).val());
        renderRuleList(filtered);
        $ruleList.addClass("wl-open");
    });

    $(document).on("click", function (e) {
        if (!$(e.target).closest("#rule-select").length) {
            $ruleList.removeClass("wl-open");
        }
    });

    $ruleList.on("click", ".wl-dropdown-item", function () {
        var rule = $(this).data("value");
        selectRule(rule);
        $ruleList.removeClass("wl-open");
    });

    function filterRules(query) {
        if (!query || !query.trim()) { return allRules; }
        var q = query.trim().toLowerCase();
        return allRules.filter(function (r) {
            return r.toLowerCase().indexOf(q) !== -1;
        });
    }

    function selectRule(rule) {
        selectedRule = rule;
        $ruleSearch.val(rule);
        renderRuleList(allRules);
        clearUndo();

        var csvEntries = mappingData.filter(function (m) {
            return m.rule_name === rule;
        });

        $csvSelect.prop("disabled", false).empty();

        if (!csvEntries.length) {
            $csvSelect.append('<option value="">No CSV files for this rule</option>');
            $csvSelect.prop("disabled", true);
            selectedCsv = "";
            selectedApp = "";
            $table.html('<div class="wl-alert wl-alert-warning">' +
                        '<strong>No whitelisting exists for this detection rule.</strong></div>');
            $diff.empty();
            return;
        }

        csvEntries.forEach(function (entry) {
            $csvSelect.append(
                '<option value="' + _.escape(entry.csv_file) + '" ' +
                'data-app="' + _.escape(entry.app_context || "") + '">' +
                _.escape(entry.csv_file) +
                '</option>'
            );
        });

        $csvSelect.prop("selectedIndex", 0).trigger("change");
    }

    $csvSelect.on("change", function () {
        var val = $(this).val();
        var $opt = $(this).find("option:selected");
        selectedCsv = val || "";
        selectedApp = $opt.data("app") || "";
        clearUndo();
        if (selectedCsv) {
            loadCsv(selectedCsv, selectedApp);
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // Table rendering
    // ══════════════════════════════════════════════════════════════════

    function renderTable(headers, rows) {
        currentHeaders = headers;
        currentRows    = rows.map(function (r) { return $.extend({}, r); });
        originalRows   = rows.map(function (r) { return $.extend({}, r); });
        currentPage    = 0;
        selectedIdxSet = {};
        refreshTable();
    }

    function syncInputs() {
        $table.find("tbody tr").each(function () {
            var idx = $(this).data("idx");
            $(this).find(".wl-input").each(function () {
                var header = $(this).data("header");
                if (currentRows[idx]) {
                    currentRows[idx][header] = $(this).val();
                }
            });
        });
    }

    function refreshTable() {
        if (!currentHeaders.length) {
            $table.html('<p class="wl-muted">This CSV file is empty.</p>');
            return;
        }

        var hasExpires = !!expireColumn;
        var now = new Date();

        // Visible headers (skip _ metadata columns)
        var visibleHeaders = currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });

        // Pagination
        var totalRows  = currentRows.length;
        var totalPages = Math.max(1, Math.ceil(totalRows / ROWS_PER_PAGE));
        if (currentPage >= totalPages) { currentPage = totalPages - 1; }
        if (currentPage < 0) { currentPage = 0; }
        var startIdx = currentPage * ROWS_PER_PAGE;
        var endIdx   = Math.min(startIdx + ROWS_PER_PAGE, totalRows);
        var pageRows = currentRows.slice(startIdx, endIdx);

        var html = '<table class="wl-table">';

        html += "<thead><tr>";
        var allSelected = currentRows.length > 0 && Object.keys(selectedIdxSet).length === currentRows.length;
        html += '<th class="wl-col-check"><input type="checkbox" id="wl-check-all" title="Select all"' + (allSelected ? ' checked="checked"' : '') + ' /></th>';
        html += '<th class="wl-col-rownum">#</th>';
        visibleHeaders.forEach(function (h) {
            html += "<th>" + _.escape(h) + "</th>";
        });
        html += '<th class="wl-col-actions">Actions</th>';
        html += "</tr></thead>";

        html += "<tbody>";
        pageRows.forEach(function (row, i) {
            var realIdx = startIdx + i;
            html += buildRow(visibleHeaders, row, realIdx, hasExpires, now);
        });
        html += "</tbody></table>";

        // Pagination controls
        if (totalPages > 1) {
            html += '<div class="wl-pagination">';
            html += '<button class="btn btn-small" id="btn-page-first"' +
                    (currentPage === 0 ? ' disabled="disabled"' : '') +
                    '>&laquo; First</button> ';
            html += '<button class="btn btn-small" id="btn-page-prev"' +
                    (currentPage === 0 ? ' disabled="disabled"' : '') +
                    '>&#8249; Prev</button>';
            html += ' <span class="wl-page-info">Page ' +
                    (currentPage + 1) + ' of ' + totalPages +
                    ' (' + totalRows + ' rows)</span> ';
            html += '<button class="btn btn-small" id="btn-page-next"' +
                    (currentPage >= totalPages - 1 ? ' disabled="disabled"' : '') +
                    '>Next &#8250;</button> ';
            html += '<button class="btn btn-small" id="btn-page-last"' +
                    (currentPage >= totalPages - 1 ? ' disabled="disabled"' : '') +
                    '>Last &raquo;</button>';
            html += '</div>';
        }

        // Action buttons
        html += '<div class="wl-buttons">';
        html += '<button class="btn btn-primary" id="btn-add-row">+ Add Row</button> ';
        html += '<button class="btn btn-danger" id="btn-remove-selected" disabled="disabled">Remove Selected</button> ';
        html += '<button class="btn btn-success" id="btn-save">Save Changes</button> ';
        html += '<button class="btn"             id="btn-discard">Discard Changes</button>';
        html += '<span class="wl-buttons-right">';
        html += '<button class="btn" id="btn-export" title="Download current CSV">Export CSV</button> ';
        html += '<label class="btn wl-import-btn" title="Upload CSV to merge rows">';
        html += 'Import CSV <input type="file" id="btn-import" accept=".csv" style="display:none" />';
        html += '</label>';
        html += '</span>';
        html += "</div>";

        // Undo bar placeholder
        html += '<div id="wl-undo-bar"></div>';

        $table.html(html);
        bindTableEvents();
    }

    function buildRow(visibleHeaders, row, idx, hasExpires, now) {
        // Check if row is expired
        var expired = false;
        if (hasExpires && expireColumn) {
            var expVal = (row[expireColumn] || "").trim();
            if (expVal) {
                var expDate = new Date(expVal);
                if (!isNaN(expDate.getTime()) && expDate < now) {
                    expired = true;
                }
            }
        }

        var classes = [];
        if (expired) { classes.push("wl-row-expired"); }

        var trClass = classes.length ? ' class="' + classes.join(" ") + '"' : '';

        // Build tooltip from _added_by and _added_at metadata
        var tooltip = "";
        if (row._added_by || row._added_at) {
            var parts = [];
            if (row._added_by) { parts.push("Added by: " + row._added_by); }
            if (row._added_at) { parts.push("Added at: " + row._added_at); }
            tooltip = ' title="' + _.escape(parts.join(" | ")) + '"';
        }

        var html = '<tr data-idx="' + idx + '"' + trClass + tooltip + '>';
        html += '<td class="wl-col-check"><input type="checkbox" class="wl-row-check" data-idx="' + idx + '"' + (selectedIdxSet[idx] ? ' checked="checked"' : '') + ' /></td>';
        html += '<td class="wl-col-rownum">' + (idx + 1) + '</td>';
        visibleHeaders.forEach(function (h) {
            var val = row[h] || "";
            var isExpires = (expireColumn && h === expireColumn);
            html +=
                "<td>" +
                '<input type="text" class="wl-input' + (isExpires ? ' wl-expires-input' : '') + '" ' +
                'data-header="' + _.escape(h) + '" ' +
                'value="' + _.escape(val) + '"' +
                (isExpires ? ' readonly="readonly" style="cursor:pointer"' : '') +
                ' />' +
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
    function updateRemoveSelectedBtn() {
        var checked = Object.keys(selectedIdxSet).length;
        $table.find("#btn-remove-selected")
              .prop("disabled", checked === 0)
              .text(checked > 0 ? "Remove Selected (" + checked + ")" : "Remove Selected");
    }

    function bindTableEvents() {
        // Select-all checkbox — selects ALL rows across all pages
        $table.off("change.wl", "#wl-check-all").on("change.wl", "#wl-check-all", function () {
            var checked = $(this).is(":checked");
            selectedIdxSet = {};
            if (checked) {
                for (var i = 0; i < currentRows.length; i++) {
                    selectedIdxSet[i] = true;
                }
            }
            $table.find(".wl-row-check").prop("checked", checked);
            updateRemoveSelectedBtn();
        });

        // Individual row checkboxes
        $table.off("change.wl", ".wl-row-check").on("change.wl", ".wl-row-check", function () {
            var idx = $(this).data("idx");
            if ($(this).is(":checked")) {
                selectedIdxSet[idx] = true;
            } else {
                delete selectedIdxSet[idx];
            }
            var totalSelected = Object.keys(selectedIdxSet).length;
            $table.find("#wl-check-all").prop("checked", totalSelected === currentRows.length);
            updateRemoveSelectedBtn();
        });

        // Bulk remove selected rows (across all pages)
        $table.off("click.wl", "#btn-remove-selected").on("click.wl", "#btn-remove-selected", function () {
            var selectedIdxs = Object.keys(selectedIdxSet).map(Number);
            if (!selectedIdxs.length) { return; }

            var reason = prompt(
                "You are about to remove " + selectedIdxs.length + " row(s).\n" +
                "Why are these rows being removed?\n\n" +
                "(A reason is required)"
            );
            if (reason === null) { return; }
            if (!reason.trim()) {
                showMsg("A reason is required to remove rows.", "warning");
                return;
            }

            syncInputs();

            // Collect removed rows with their original 1-based row numbers
            var removedEntries = [];
            selectedIdxs.sort(function (a, b) { return a - b; });
            selectedIdxs.forEach(function (idx) {
                removedEntries.push({
                    row_number: idx + 1,  // 1-based for human-friendly numbering
                    row: $.extend({}, currentRows[idx])
                });
            });

            var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
            var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });

            // Remove from highest index first to avoid shifting
            selectedIdxSet = {};
            for (var i = selectedIdxs.length - 1; i >= 0; i--) {
                currentRows.splice(selectedIdxs[i], 1);
            }
            refreshTable();

            doSaveBulkRemoval(removedEntries, reason.trim(), prevRows, prevOriginal);
        });

        $table.off("change.wl", ".wl-input").on("change.wl", ".wl-input", function () {
            var $el    = $(this);
            var idx    = $el.closest("tr").data("idx");
            var header = $el.data("header");
            if (currentRows[idx]) {
                currentRows[idx][header] = $el.val();
            }
        });

        // Remove row with undo support
        $table.off("click.wl", ".btn-rm").on("click.wl", ".btn-rm", function () {
            var idx = $(this).data("idx");
            var row = currentRows[idx];
            if (!row) { return; }

            var reason = prompt(
                "You are about to remove 1 row.\n" +
                "Why is this row being removed?\n\n" +
                "(A reason is required)"
            );
            if (reason === null) { return; }
            if (!reason.trim()) {
                showMsg("A reason is required to remove a row.", "warning");
                return;
            }

            syncInputs();

            // Save state for undo
            var removedRow = $.extend({}, row);
            var rowNumber = idx + 1;  // 1-based for human-friendly numbering
            var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
            var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });

            currentRows.splice(idx, 1);
            refreshTable();

            doSaveRemoval(removedRow, reason.trim(), rowNumber, prevRows, prevOriginal);
        });

        // Pagination
        $table.off("click.wl", "#btn-page-first").on("click.wl", "#btn-page-first", function () {
            syncInputs();
            if (currentPage > 0) { currentPage = 0; refreshTable(); }
        });
        $table.off("click.wl", "#btn-page-prev").on("click.wl", "#btn-page-prev", function () {
            syncInputs();
            if (currentPage > 0) { currentPage--; refreshTable(); }
        });
        $table.off("click.wl", "#btn-page-next").on("click.wl", "#btn-page-next", function () {
            syncInputs();
            var totalPages = Math.ceil(currentRows.length / ROWS_PER_PAGE);
            if (currentPage < totalPages - 1) { currentPage++; refreshTable(); }
        });
        $table.off("click.wl", "#btn-page-last").on("click.wl", "#btn-page-last", function () {
            syncInputs();
            var totalPages = Math.ceil(currentRows.length / ROWS_PER_PAGE);
            if (currentPage < totalPages - 1) { currentPage = totalPages - 1; refreshTable(); }
        });

        // Add row
        $table.off("click.wl", "#btn-add-row").on("click.wl", "#btn-add-row", function () {
            var newRow = {};
            currentHeaders.forEach(function (h) { newRow[h] = ""; });
            currentRows.push(newRow);
            // Navigate to last page so the new row is visible
            currentPage = Math.ceil(currentRows.length / ROWS_PER_PAGE) - 1;
            refreshTable();
            $table.find("tbody tr:last input:first").focus();
        });

        // Save
        $table.off("click.wl", "#btn-save").on("click.wl", "#btn-save", function () {
            doSave();
        });

        // Discard
        $table.off("click.wl", "#btn-discard").on("click.wl", "#btn-discard", function () {
            currentRows = originalRows.map(function (r) { return $.extend({}, r); });
            clearUndo();
            refreshTable();
            $diff.empty();
            showMsg("Changes discarded.", "info");
        });

        // Export CSV
        $table.off("click.wl", "#btn-export").on("click.wl", "#btn-export", function () {
            exportCsv();
        });

        // Import CSV
        $table.off("change.wl", "#btn-import").on("change.wl", "#btn-import", function (e) {
            var file = e.target.files[0];
            if (file) { importCsv(file); }
            $(this).val("");  // reset so same file can be re-selected
        });

    }

    // ══════════════════════════════════════════════════════════════════
    // Undo removal (10-second window)
    // ══════════════════════════════════════════════════════════════════

    function showUndoBar(removedRow, prevRows, prevOriginal) {
        clearUndo();

        var rowDesc = [];
        currentHeaders.forEach(function (h) {
            if (h.charAt(0) !== "_" && removedRow[h]) {
                rowDesc.push(removedRow[h]);
            }
        });
        var desc = rowDesc.slice(0, 3).join(", ");
        if (rowDesc.length > 3) { desc += "..."; }

        undoState = {
            prevRows: prevRows,
            prevOriginal: prevOriginal
        };

        var $bar = $table.find("#wl-undo-bar");
        $bar.html(
            '<div class="wl-undo">' +
            '<span>Row removed: <strong>' + _.escape(desc) + '</strong></span> ' +
            '<button class="btn btn-small" id="btn-undo">Undo</button> ' +
            '<span class="wl-undo-countdown" id="undo-countdown">10s</span>' +
            '</div>'
        );

        var secondsLeft = 10;
        undoTimer = setInterval(function () {
            secondsLeft--;
            $bar.find("#undo-countdown").text(secondsLeft + "s");
            if (secondsLeft <= 0) {
                clearUndo();
            }
        }, 1000);

        $bar.off("click", "#btn-undo").on("click", "#btn-undo", function () {
            doUndo();
        });
    }

    function doUndo() {
        if (!undoState) { return; }

        // Restore rows to the state before removal
        currentRows = undoState.prevRows.map(function (r) { return $.extend({}, r); });

        clearUndo();
        showMsg("Saving undo&hellip;", "info");

        // Save the restored state back to the server
        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Undo row removal",
            removal_reasons: []
        })
        .done(function (data) {
            if (data.error) {
                showMsg(data.error, "error");
                return;
            }
            showMsg("Removal undone and saved.", "success");
            reloadCsvQuiet();
        })
        .fail(function (xhr) {
            var err = "Failed to undo removal.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { /* ignore */ }
            showMsg(err, "error");
        });
    }

    function clearUndo() {
        if (undoTimer) {
            clearInterval(undoTimer);
            undoTimer = null;
        }
        undoState = null;
        var $bar = $table.find("#wl-undo-bar");
        if ($bar.length) { $bar.empty(); }
    }

    // ══════════════════════════════════════════════════════════════════
    // Bulk Export (download current CSV)
    // ══════════════════════════════════════════════════════════════════

    function exportCsv() {
        syncInputs();

        // Build CSV string (exclude internal _ columns)
        var visibleHeaders = currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });

        var lines = [visibleHeaders.map(csvEscape).join(",")];
        currentRows.forEach(function (row) {
            var vals = visibleHeaders.map(function (h) {
                return csvEscape(row[h] || "");
            });
            lines.push(vals.join(","));
        });
        var csvText = lines.join("\n");

        // Trigger download
        var blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = selectedCsv || "whitelist_export.csv";
        link.click();
        URL.revokeObjectURL(link.href);
    }

    function csvEscape(val) {
        if (val.indexOf(",") !== -1 || val.indexOf('"') !== -1 || val.indexOf("\n") !== -1) {
            return '"' + val.replace(/"/g, '""') + '"';
        }
        return val;
    }

    // ══════════════════════════════════════════════════════════════════
    // Bulk Import (upload CSV to merge)
    // ══════════════════════════════════════════════════════════════════

    function importCsv(file) {
        var reader = new FileReader();
        reader.onload = function (e) {
            var text = e.target.result;
            var parsed = parseCsvText(text);
            if (!parsed) {
                showMsg("Failed to parse CSV file.", "error");
                return;
            }

            var importHeaders = parsed.headers;
            var importRows = parsed.rows;

            // Validate that import headers match (at minimum) existing headers
            var missingHeaders = [];
            currentHeaders.forEach(function (h) {
                if (h.charAt(0) !== "_" && importHeaders.indexOf(h) === -1) {
                    missingHeaders.push(h);
                }
            });

            if (missingHeaders.length) {
                showMsg(
                    "Import CSV is missing columns: <strong>" +
                    _.escape(missingHeaders.join(", ")) +
                    "</strong>. Cannot merge.",
                    "error"
                );
                return;
            }

            // Merge: add only rows that don't already exist
            var existingKeys = {};
            var keyHeaders = currentHeaders.filter(function (h) {
                return h.charAt(0) !== "_" && h !== "Comment" && h !== expireColumn;
            });
            currentRows.forEach(function (row) {
                var key = keyHeaders.map(function (h) { return row[h] || ""; }).join("||");
                existingKeys[key] = true;
            });

            var addedCount = 0;
            importRows.forEach(function (importRow) {
                var key = keyHeaders.map(function (h) { return importRow[h] || ""; }).join("||");
                if (!existingKeys[key]) {
                    // Map to our header structure
                    var newRow = {};
                    currentHeaders.forEach(function (h) {
                        newRow[h] = importRow[h] || "";
                    });
                    currentRows.push(newRow);
                    existingKeys[key] = true;
                    addedCount++;
                }
            });

            if (addedCount === 0) {
                showMsg("No new rows to import (all rows already exist).", "info");
            } else {
                refreshTable();
                showMsg(
                    "Imported <strong>" + addedCount + "</strong> new row(s). " +
                    "Review and click <strong>Save Changes</strong> to persist.",
                    "success"
                );
            }
        };
        reader.readAsText(file);
    }

    function parseCsvText(text) {
        var lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
        lines = lines.filter(function (l) { return l.trim() !== ""; });
        if (lines.length < 1) { return null; }

        var headers = parseCsvLine(lines[0]);
        var rows = [];
        for (var i = 1; i < lines.length; i++) {
            var vals = parseCsvLine(lines[i]);
            var row = {};
            headers.forEach(function (h, j) {
                row[h] = vals[j] || "";
            });
            rows.push(row);
        }
        return { headers: headers, rows: rows };
    }

    function parseCsvLine(line) {
        var result = [];
        var current = "";
        var inQuotes = false;
        for (var i = 0; i < line.length; i++) {
            var ch = line[i];
            if (inQuotes) {
                if (ch === '"' && i + 1 < line.length && line[i + 1] === '"') {
                    current += '"';
                    i++;
                } else if (ch === '"') {
                    inQuotes = false;
                } else {
                    current += ch;
                }
            } else {
                if (ch === '"') {
                    inQuotes = true;
                } else if (ch === ',') {
                    result.push(current);
                    current = "";
                } else {
                    current += ch;
                }
            }
        }
        result.push(current);
        return result;
    }

    // ══════════════════════════════════════════════════════════════════
    // Comment validation
    // ══════════════════════════════════════════════════════════════════

    function getAuditComment() {
        var hasCommentCol = currentHeaders.indexOf("Comment") !== -1;

        $table.find(".wl-input").removeClass("wl-input-error");

        if (hasCommentCol) {
            var emptyFound = false;
            $table.find("tbody tr").each(function () {
                $(this).find('.wl-input[data-header="Comment"]').each(function () {
                    if (!$(this).val().trim()) {
                        $(this).addClass("wl-input-error");
                        emptyFound = true;
                    }
                });
            });

            if (emptyFound) {
                showMsg("Comment field cannot be empty.", "error");
                return null;
            }

            return { valid: true, comment: "" };
        }

        var comment = prompt(
            "This CSV does not have a \"Comment\" column.\n" +
            "Please provide a reason for this change.\n" +
            "(This will be recorded in the audit trail only, not saved in the CSV.)"
        );
        if (comment === null) { return null; }
        if (!comment.trim()) {
            showMsg("A comment is required for audit purposes.", "warning");
            return null;
        }
        return { valid: true, comment: comment.trim() };
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
            app:      appContext || "",
            tz_offset: new Date().getTimezoneOffset()
        })
        .done(function (data) {
            if (data.error) {
                showMsg(data.error, "error");
                $table.empty();
                return;
            }
            expireColumn = data.expire_column || "";
            if (data.auto_removed_count && data.auto_removed_count > 0) {
                showMsg(
                    "<strong>" + data.auto_removed_count + " expired row(s)</strong> " +
                    "were automatically removed.",
                    "warning"
                );
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
    // Silent CSV reload (preserves messages, refreshes metadata)
    // ══════════════════════════════════════════════════════════════════
    function reloadCsvQuiet(callback) {
        if (!selectedCsv) {
            if (callback) { callback(); }
            return;
        }
        restGet({
            action:   "get_csv_content",
            csv_file: selectedCsv,
            app:      selectedApp || "",
            tz_offset: new Date().getTimezoneOffset()
        })
        .done(function (data) {
            if (!data.error) {
                expireColumn = data.expire_column || "";
                if (data.auto_removed_count && data.auto_removed_count > 0) {
                    showMsg(
                        "<strong>" + data.auto_removed_count + " expired row(s)</strong> " +
                        "were automatically removed.",
                        "warning"
                    );
                }
                renderTable(data.headers || [], data.rows || []);
            }
        })
        .always(function () {
            if (callback) { callback(); }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save CSV (full save — Save Changes button)
    // ══════════════════════════════════════════════════════════════════
    function doSave() {
        if (saving) { return; }

        syncInputs();

        // Remove completely empty rows before saving
        var visHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var beforeCount = currentRows.length;
        currentRows = currentRows.filter(function (row) {
            return visHeaders.some(function (h) { return (row[h] || "").trim() !== ""; });
        });
        if (currentRows.length < beforeCount) {
            refreshTable();
        }

        if (!selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        var result = getAuditComment();
        if (!result) { return; }

        saving = true;
        $table.find("#btn-save").prop("disabled", true).text("Saving...");
        showMsg("Saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         result.comment,
            removal_reasons: []
        })
        .done(function (data) {
            if (data.error) {
                saving = false;
                showMsg(data.error, "error");
                currentRows = originalRows.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            showMsg(
                "Saved successfully. " +
                "Added: <strong>" + (diffInfo.added_count || 0) + "</strong> row(s), " +
                "Removed: <strong>" + (diffInfo.removed_count || 0) + "</strong> row(s), " +
                "Edited: <strong>" + (diffInfo.edited_count || 0) + "</strong> row(s).",
                "success"
            );

            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            // Reload CSV from server to pick up backend-stamped metadata
            // (e.g. _review_status=pending, _added_by, _added_at)
            reloadCsvQuiet(function () {
                saving = false;
            });
        })
        .fail(function (xhr) {
            saving = false;
            var err = "Failed to save CSV.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { /* ignore */ }
            showMsg(err, "error");
            currentRows = originalRows.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save for row removal — auto-triggered, with undo support
    // ══════════════════════════════════════════════════════════════════
    function doSaveRemoval(removedRow, reason, rowNumber, prevRows, prevOriginal) {
        if (!selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        showMsg("Removing row and saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Row removal",
            removal_reasons: [{ row: removedRow, reason: reason, row_number: rowNumber }]
        })
        .done(function (data) {
            if (data.error) {
                showMsg(data.error, "error");
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            showMsg("Row removed and saved successfully.", "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });

            // Show undo bar for 10 seconds
            showUndoBar(removedRow, prevRows, prevOriginal);

            var diffInfo = data.diff || {};
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }
        })
        .fail(function (xhr) {
            var err = "Failed to save after removal.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { /* ignore */ }
            showMsg(err, "error");
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save for bulk removal — multiple rows at once
    // ══════════════════════════════════════════════════════════════════
    function doSaveBulkRemoval(removedEntries, reason, prevRows, prevOriginal) {
        if (!selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        showMsg("Removing " + removedEntries.length + " row(s) and saving&hellip;", "info");

        // Build bulk_removal payload with row numbers for audit
        var bulkRemoval = removedEntries.map(function (entry) {
            return {
                row_number: entry.row_number,
                row: entry.row,
                reason: reason
            };
        });

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Bulk removal (" + removedEntries.length + " rows)",
            removal_reasons: [],
            bulk_removal:    bulkRemoval
        })
        .done(function (data) {
            if (data.error) {
                showMsg(data.error, "error");
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            showMsg(removedEntries.length + " row(s) removed and saved successfully.", "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });

            var diffInfo = data.diff || {};
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }
        })
        .fail(function (xhr) {
            var err = "Failed to save after bulk removal.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { /* ignore */ }
            showMsg(err, "error");
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Diff rendering (Git-style)
    // ══════════════════════════════════════════════════════════════════
    function renderDiff(diff) {
        var html = '<div class="wl-diff">';
        html += "<h4>Change Summary</h4>";

        if (diff.added && diff.added.length) {
            html += '<div class="wl-diff-section wl-diff-added">';
            html += "<h5>Added (" + diff.added.length + " row" + (diff.added.length > 1 ? "s" : "") + ")</h5><ul>";
            diff.added.forEach(function (row) {
                html += "<li>" + _.escape(JSON.stringify(row)) + "</li>";
            });
            html += "</ul></div>";
        }

        if (diff.removed && diff.removed.length) {
            html += '<div class="wl-diff-section wl-diff-removed">';
            html += "<h5>Removed (" + diff.removed.length + " row" + (diff.removed.length > 1 ? "s" : "") + ")</h5><ul>";
            diff.removed.forEach(function (row) {
                html += "<li>" + _.escape(JSON.stringify(row)) + "</li>";
            });
            html += "</ul></div>";
        }

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
    // Date/Time Picker for Expires column
    // ══════════════════════════════════════════════════════════════════

    var $datePicker = null;
    var $activeExpiresInput = null;

    function padTwo(n) {
        return n < 10 ? "0" + n : "" + n;
    }

    function formatDateForPicker(d) {
        return d.getFullYear() + "-" + padTwo(d.getMonth() + 1) + "-" + padTwo(d.getDate());
    }

    function createDatePicker() {
        if ($datePicker) { return; }

        var html =
            '<div id="wl-date-picker" class="wl-date-picker">' +
                '<div class="wl-dp-header">Set Expiration</div>' +
                '<div class="wl-dp-presets">' +
                    '<button class="btn btn-small wl-dp-preset" data-days="7">7 Days</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="30">30 Days</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="182">6 Months</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="365">1 Year</button>' +
                '</div>' +
                '<div class="wl-dp-manual">' +
                    '<label class="wl-dp-label">Date</label>' +
                    '<input type="date" class="wl-dp-date" />' +
                    '<label class="wl-dp-label">Time</label>' +
                    '<input type="time" class="wl-dp-time" value="00:00" />' +
                '</div>' +
                '<div class="wl-dp-actions">' +
                    '<button class="btn btn-small btn-primary wl-dp-apply">Apply</button>' +
                    '<button class="btn btn-small wl-dp-clear">Clear (Permanent)</button>' +
                    '<button class="btn btn-small wl-dp-cancel">Cancel</button>' +
                '</div>' +
            '</div>';

        $datePicker = $(html);
        $("body").append($datePicker);

        // Preset buttons
        $datePicker.on("click", ".wl-dp-preset", function () {
            var days = parseInt($(this).data("days"), 10);
            var future = new Date();
            future.setDate(future.getDate() + days);
            $datePicker.find(".wl-dp-date").val(formatDateForPicker(future));
            $datePicker.find(".wl-dp-time").val(padTwo(future.getHours()) + ":" + padTwo(future.getMinutes()));
        });

        // Apply button
        $datePicker.on("click", ".wl-dp-apply", function () {
            var d = $datePicker.find(".wl-dp-date").val();
            var t = $datePicker.find(".wl-dp-time").val() || "00:00";
            if (!d) { return; }
            var formatted = d + " " + t;
            if ($activeExpiresInput) {
                $activeExpiresInput.val(formatted).trigger("change");
            }
            closeDatePicker();
        });

        // Clear button (permanent — empty Expires)
        $datePicker.on("click", ".wl-dp-clear", function () {
            if ($activeExpiresInput) {
                $activeExpiresInput.val("").trigger("change");
            }
            closeDatePicker();
        });

        // Cancel button
        $datePicker.on("click", ".wl-dp-cancel", function () {
            closeDatePicker();
        });
    }

    function showDatePicker($input) {
        createDatePicker();
        $activeExpiresInput = $input;

        // Pre-populate from current value
        var current = ($input.val() || "").trim();
        if (/^\d{4}-\d{2}-\d{2}/.test(current)) {
            var parts = current.split(" ");
            $datePicker.find(".wl-dp-date").val(parts[0] || "");
            $datePicker.find(".wl-dp-time").val(parts[1] || "00:00");
        } else {
            var now = new Date();
            $datePicker.find(".wl-dp-date").val(formatDateForPicker(now));
            $datePicker.find(".wl-dp-time").val(padTwo(now.getHours()) + ":" + padTwo(now.getMinutes()));
        }

        // Position below the input
        var offset = $input.offset();
        var inputHeight = $input.outerHeight();
        $datePicker.css({
            top: offset.top + inputHeight + 4,
            left: offset.left,
            display: "block"
        });
    }

    function closeDatePicker() {
        if ($datePicker) {
            $datePicker.css("display", "none");
        }
        $activeExpiresInput = null;
    }

    // Bind Expires cell click — delegated on $table
    $table.on("click.wl", ".wl-expires-input", function (e) {
        e.stopPropagation();
        showDatePicker($(this));
    });

    // Close picker when clicking outside
    $(document).on("click", function (e) {
        if ($datePicker && $datePicker.css("display") !== "none") {
            if (!$(e.target).closest("#wl-date-picker").length &&
                !$(e.target).closest(".wl-expires-input").length) {
                closeDatePicker();
            }
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // Initialization
    // ══════════════════════════════════════════════════════════════════
    loadRules();

});
