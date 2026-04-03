/**
 * Whitelist Manager — Frontend Controller
 *
 * Features:
 *   1. Searchable detection rule dropdown
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
 *  12. Search/filter bar with instant filtering and text highlighting
 */

/*global require, Splunk */
require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "app/wl_manager/modules/wl_constants",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui",
    "app/wl_manager/modules/wl_debug",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils, C, REST, UI, Debug) {
    "use strict";

    // Activate debug interceptor (remove for production)
    Debug.init();

    // ── Module aliases (Option A: local vars, zero changes to usage sites) ──
    var restUrl  = REST.restUrl;
    var restGet  = REST.restGet;
    var restPost = REST.restPost;

    // ── UI module: message banner, daily limit msgs ──
    var showMsg          = UI.showMsg;
    var clearMsg         = UI.clearMsg;
    var formatDailyLimitMsg = UI.formatDailyLimitMsg;

    // ══════════════════════════════════════════════════════════════════
    // State
    // ══════════════════════════════════════════════════════════════════
    var currentHeaders  = [];
    var originalHeaders = [];
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
    var ROWS_PER_PAGE    = C.ROWS_PER_PAGE;
    var PAGE_SIZE_OPTIONS = C.PAGE_SIZE_OPTIONS;
    var MAX_ROWS         = C.MAX_ROWS;
    var MAX_COLUMNS      = C.MAX_COLUMNS;
    var MAX_CELL_CHARS   = C.MAX_CELL_CHARS;
    var selectedIdxSet   = {};      // tracks selected row indices across pages (key=idx, value=true)
    var expireColumn     = "";      // name of the expiration column (e.g. "Expires", "expiry", "termination_date")
    var searchQuery      = "";      // current search/filter text for the CSV table
    var versionsList     = [];      // available version snapshots from backend
    var loadedMtime      = null;    // file mtime when CSV was loaded/saved (for external change detection)
    var loadedPendingCount = 0;    // pending approval count when CSV was loaded (for lock-state polling)
    var changeCheckTimer = null;    // setInterval ID for external change polling
    var dragState        = null;    // { type: "row"|"column", ... } during drag operations
    var allColWidths     = {};      // { csvFileName: { headerName: widthPx } } in-memory cache
    var colWidths        = {};      // { headerName: widthPx } active column widths for current CSV
    var colWidthSaveTimer = null;   // debounce timer for saving column widths
    var resizeState      = null;    // { $th, header, startX, startWidth } during column resize
    var pendingApprovals = [];      // pending approval items for current CSV (from server)
    var csvLocked        = false;  // true when ANY pending approval exists — entire file locked
    var isAdmin          = false;  // true if current user has admin/sc_admin/wl_admin role
    var pendingBulkEditCount = 0;  // tracks unsaved Bulk Edit changes (for correct limit classification)

    // ══════════════════════════════════════════════════════════════════
    // CSV Import: Client-side parser, validator, preview renderer
    // ══════════════════════════════════════════════════════════════════
    var IMPORT_MAX_FILE_SIZE = C.IMPORT_MAX_FILE_SIZE;
    var IMPORT_PREVIEW_ROWS = C.IMPORT_PREVIEW_ROWS;
    var IMPORT_MAX_ERRORS = C.IMPORT_MAX_ERRORS;
    var IMPORT_MAX_WARN_EXAMPLES = C.IMPORT_MAX_WARN_EXAMPLES;
    var SAFE_COLNAME_RE = C.SAFE_COLNAME_RE;
    var EXPIRE_COLUMN_NAMES_LIST = C.EXPIRE_COLUMN_NAMES_LIST;
    var VALID_EXPIRE_RE = C.VALID_EXPIRE_RE;

    // RFC 4180-compliant CSV parser: handles quoted fields, embedded
    // commas, double-quote escaping, BOM, mixed line endings.
    function parseCSV(text) {
        var errors = [];
        // Strip UTF-8 BOM
        if (text.charCodeAt(0) === 0xFEFF) { text = text.substring(1); }

        // Check for binary content (null bytes in first 8KB)
        var checkLen = Math.min(text.length, 8192);
        for (var b = 0; b < checkLen; b++) {
            if (text.charCodeAt(b) === 0) {
                return { headers: [], rows: [], errors: ["File appears to be binary, not a text CSV."] };
            }
        }

        var rows = [];
        var row = [];
        var field = "";
        var inQuotes = false;
        var i = 0;
        var len = text.length;

        while (i < len) {
            var ch = text[i];
            if (inQuotes) {
                if (ch === '"') {
                    if (i + 1 < len && text[i + 1] === '"') {
                        field += '"';
                        i += 2;
                    } else {
                        inQuotes = false;
                        i++;
                    }
                } else {
                    field += ch;
                    i++;
                }
            } else {
                if (ch === '"') {
                    inQuotes = true;
                    i++;
                } else if (ch === ',') {
                    row.push(field);
                    field = "";
                    i++;
                } else if (ch === '\r') {
                    row.push(field);
                    field = "";
                    rows.push(row);
                    row = [];
                    i++;
                    if (i < len && text[i] === '\n') { i++; }
                } else if (ch === '\n') {
                    row.push(field);
                    field = "";
                    rows.push(row);
                    row = [];
                    i++;
                } else {
                    field += ch;
                    i++;
                }
            }
        }
        // Final field/row
        if (field || row.length > 0) {
            row.push(field);
            rows.push(row);
        }

        // Strip trailing empty rows
        while (rows.length > 0) {
            var last = rows[rows.length - 1];
            if (last.length === 1 && last[0] === "") { rows.pop(); }
            else { break; }
        }

        if (rows.length === 0) {
            return { headers: [], rows: [], errors: ["File is empty or contains no header row."] };
        }

        // First row = headers
        var headers = rows[0].map(function (h) { return h.trim(); });
        for (var hi = 0; hi < headers.length; hi++) {
            if (/\s/.test(headers[hi])) {
                errors.push("Column '" + headers[hi].substring(0, 30) +
                    "' contains spaces. Column names cannot have spaces — use underscores instead.");
            }
        }
        if (errors.length) {
            return { headers: headers, rows: [], errors: errors };
        }
        var dataRows = rows.slice(1);

        // Convert data rows from arrays to dicts, validate field counts
        var dictRows = [];
        for (var r = 0; r < dataRows.length; r++) {
            var arr = dataRows[r];
            if (arr.length > headers.length) {
                errors.push("Row " + (r + 1) + " has " + arr.length +
                    " fields but header has " + headers.length + " columns. CSV may be malformed.");
                continue;
            }
            var obj = {};
            for (var c = 0; c < headers.length; c++) {
                obj[headers[c]] = c < arr.length ? arr[c] : "";
            }
            dictRows.push(obj);
        }

        return { headers: headers, rows: dictRows, errors: errors };
    }

    // Full validation pipeline. Runs ALL checks to completion (no short-circuit).
    // Returns { errors: string[], warnings: object[] }
    function validateImportedCSV(filename, headers, rows) {
        var errors = [];
        var warnings = [];

        // --- Filename checks ---
        if (/[^a-zA-Z0-9_\-.]/.test(filename)) {
            errors.push("Filename contains invalid characters. Only letters, numbers, underscores, hyphens, and dots are allowed.");
        }
        if (filename.length > 100) {
            errors.push("Filename too long (" + filename.length + " chars, max 100).");
        }
        var stem = filename.replace(/\.csv$/i, "");
        if (stem && !/[a-zA-Z0-9]/.test(stem)) {
            errors.push("Filename must contain at least one letter or number.");
        }

        // --- Column count ---
        if (headers.length > MAX_COLUMNS) {
            errors.push("Too many columns: " + headers.length + " (max " + MAX_COLUMNS + ").");
        }

        // --- Row count ---
        if (rows.length > MAX_ROWS) {
            errors.push("Too many rows: " + rows.length + " (max " + MAX_ROWS + ").");
        }

        // --- Column name checks ---
        var seenCols = {};
        for (var ci = 0; ci < headers.length; ci++) {
            var h = headers[ci];
            if (!h || !h.trim()) {
                errors.push("Column header at position " + (ci + 1) + " is empty.");
                continue;
            }
            if (/\s/.test(h)) {
                errors.push("Column '" + _.escape(h.substring(0, 30)) +
                    "' contains spaces. Use underscores instead (e.g. 'src_ip').");
            }
            if (h.charAt(0) === "_") {
                errors.push("Column '" + _.escape(h.substring(0, 20)) + "' starts with underscore (reserved).");
            }
            if (!SAFE_COLNAME_RE.test(h)) {
                errors.push("Column '" + _.escape(h.substring(0, 20)) +
                    "' contains invalid characters. Must contain at least one letter or number. " +
                    "Only letters, numbers, and _-.()/:#@&+ allowed.");
            }
            if (h.length > 64) {
                errors.push("Column '" + _.escape(h.substring(0, 20)) + "...' is too long (" +
                    h.length + " chars, max 64).");
            }
            var hlc = h.toLowerCase();
            if (seenCols[hlc]) {
                errors.push("Duplicate column header: '" + _.escape(h) + "'");
            }
            seenCols[hlc] = true;
        }

        // --- Detect Expires column ---
        var expireCol = null;
        for (var ei = 0; ei < headers.length; ei++) {
            if (EXPIRE_COLUMN_NAMES_LIST.indexOf(headers[ei].toLowerCase()) !== -1) {
                expireCol = headers[ei];
                break;
            }
        }
        if (expireCol) {
            warnings.push({
                type: "expires_detected",
                message: "Column '" + _.escape(expireCol) + "' detected as expiration column. " +
                    "Values must be YYYY-MM-DD or YYYY-MM-DD HH:MM format."
            });
        }

        // --- Cell-level checks (only if row/col counts are within limits) ---
        var sanitizationIssues = [];
        var cellLengthErrors = [];
        var expireDateErrors = [];

        if (rows.length <= MAX_ROWS && headers.length <= MAX_COLUMNS) {
            for (var ri = 0; ri < rows.length; ri++) {
                for (var hi = 0; hi < headers.length; hi++) {
                    var col = headers[hi];
                    var val = rows[ri][col] || "";
                    if (typeof val !== "string") { val = String(val); }

                    // Cell length
                    if (val.length > MAX_CELL_CHARS && cellLengthErrors.length < IMPORT_MAX_ERRORS) {
                        cellLengthErrors.push("Cell in row " + (ri + 1) + ", column '" +
                            _.escape(col.substring(0, 20)) + "' exceeds " + MAX_CELL_CHARS + " characters.");
                    }

                    // Control chars / null bytes / embedded newlines
                    if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\t\n\r]/.test(val)) {
                        var issue = "Row " + (ri + 1) + ", column '" + _.escape(col.substring(0, 20)) + "': contains ";
                        if (/\x00/.test(val)) { issue += "null byte"; }
                        else if (/[\n\r]/.test(val)) { issue += "embedded newline"; }
                        else if (/\t/.test(val)) { issue += "tab character"; }
                        else { issue += "control character"; }
                        sanitizationIssues.push(issue);
                    }

                    // Expires date validation
                    if (expireCol && col === expireCol && val.trim() &&
                        expireDateErrors.length < 5) {
                        if (!VALID_EXPIRE_RE.test(val.trim())) {
                            expireDateErrors.push("row " + (ri + 1) + ": '" +
                                _.escape(val.trim().substring(0, 30)) + "'");
                        }
                    }
                }
            }
        }

        // Add cell length errors as blocking
        cellLengthErrors.forEach(function (e) { errors.push(e); });

        // Add expire date errors as blocking
        if (expireDateErrors.length > 0) {
            errors.push("Expiration column '" + _.escape(expireCol) + "': invalid dates in " +
                expireDateErrors.join(", ") + ". Expected YYYY-MM-DD or YYYY-MM-DD HH:MM.");
        }

        // Add sanitization as warning (non-blocking)
        if (sanitizationIssues.length > 0) {
            var examples = sanitizationIssues.slice(0, IMPORT_MAX_WARN_EXAMPLES);
            var moreCount = sanitizationIssues.length - examples.length;
            warnings.push({
                type: "sanitization",
                message: sanitizationIssues.length + " cell(s) contain control characters or " +
                    "embedded newlines that will be cleaned on import.",
                examples: examples,
                moreCount: moreCount
            });
        }

        // Cap errors display
        var totalErrors = errors.length;
        if (totalErrors > IMPORT_MAX_ERRORS) {
            errors = errors.slice(0, IMPORT_MAX_ERRORS);
            errors.push("...and " + (totalErrors - IMPORT_MAX_ERRORS) + " more error(s).");
        }

        return { errors: errors, warnings: warnings };
    }

    // Preview table renderer — first 10 rows, scrollable, read-only.
    function renderImportPreview(headers, rows, $container) {
        $container.empty();
        if (!rows.length) {
            $container.hide();
            return;
        }
        var previewRows = rows.slice(0, IMPORT_PREVIEW_ROWS);
        var summary = '<div class="wl-import-summary">Preview: ' +
            rows.length + ' row' + (rows.length !== 1 ? 's' : '') + ' &times; ' +
            headers.length + ' column' + (headers.length !== 1 ? 's' : '') +
            ' (showing first ' + Math.min(rows.length, IMPORT_PREVIEW_ROWS) + ')</div>';

        var tableHtml = '<div class="wl-import-preview-wrap"><table class="wl-import-preview-table"><thead><tr>';
        headers.forEach(function (h) {
            tableHtml += '<th>' + _.escape(h) + '</th>';
        });
        tableHtml += '</tr></thead><tbody>';
        previewRows.forEach(function (row) {
            tableHtml += '<tr>';
            headers.forEach(function (h) {
                var val = row[h] || "";
                var display = val.length > 50 ? val.substring(0, 50) + "\u2026" : val;
                tableHtml += '<td>' + _.escape(display) + '</td>';
            });
            tableHtml += '</tr>';
        });
        tableHtml += '</tbody></table></div>';

        $container.html(summary + tableHtml).show();
    }

    // Error/warning message renderer for import validation results.
    function renderImportMessages(errors, warnings, $container) {
        var html = "";
        errors.forEach(function (msg) {
            html += '<div class="wl-import-error-item">' + _.escape(msg) + '</div>';
        });
        warnings.forEach(function (w) {
            html += '<div class="wl-import-warning-item">' + _.escape(w.message) + '</div>';
            if (w.examples && w.examples.length > 0) {
                html += '<div class="wl-import-warning-examples">';
                w.examples.forEach(function (ex) {
                    html += '<div>&bull; ' + _.escape(ex) + '</div>';
                });
                if (w.moreCount > 0) {
                    html += '<div>...and ' + w.moreCount + ' more</div>';
                }
                html += '</div>';
            }
        });
        if (html) {
            $container.html(html).show();
        } else {
            $container.empty().hide();
        }
    }

    // ── Dark theme (module handles body class; WM adds panel class) ──
    if (UI.detectDarkTheme()) {
        $("#wl-dropdowns").closest(".dashboard-panel").addClass("wl-dark");
    }

    // ══════════════════════════════════════════════════════════════════
    // Detect admin role
    // ══════════════════════════════════════════════════════════════════
    (function detectAdminRole() {
        restGet({ action: "get_approval_queue" })
        .done(function () {
            isAdmin = true;
            // If CSV was already loaded & locked before this check completed,
            // re-render the approval bar now that we know user is admin
            if (pendingApprovals.length) {
                applyPendingHighlighting();
            }
        });
    })();

    // ══════════════════════════════════════════════════════════════════
    // DOM references
    // ══════════════════════════════════════════════════════════════════
    var $table       = $("#csv-table-container");
    var $msg         = $("#message-container");
    var $diff        = $("#diff-container");

    // Initialize UI module (message banner, char counter)
    UI.init($msg);
    var $ruleSearch  = $("#rule-search");
    var $ruleList    = $("#rule-list");
    // Replace native CSV <select> with custom dropdown
    var $csvSelectOrig = $("#csv-select");
    $csvSelectOrig.replaceWith(
        '<div id="csv-dropdown" class="wl-search-select" style="position:relative">' +
            '<div id="csv-display" class="wl-csv-display wl-disabled">' +
                '-- Select a Detection Rule first --</div>' +
            '<div id="csv-list" class="wl-dropdown-list"></div>' +
        '</div>'
    );
    var $csvDisplay = $("#csv-display");
    var $csvList    = $("#csv-list");
    var csvDisabled = true;
    // Add clear button to Detection Rule dropdown (built via JS to avoid Splunk stripping)
    var $ruleClear = $('<span class="wl-search-clear-btn wl-rule-clear-btn">\u00D7</span>');
    $("#rule-select").append($ruleClear);
    $ruleClear.hide();
    // Build revert dropdown via JS (Splunk SimpleXML strips empty divs)
    var $revertGroup = $(
        '<div class="wl-dropdown-group" id="wl-revert-group" style="display:none">' +
            '<label class="wl-dropdown-label">Revert to Version</label>' +
            '<select class="wl-select" id="wl-revert-select">' +
                '<option value="">-- No previous versions --</option>' +
            '</select>' +
        '</div>'
    );
    $("#wl-dropdowns").append($revertGroup);
    var $revertSelect = $revertGroup.find("#wl-revert-select");
    // Build search bar via JS (Splunk SimpleXML strips empty divs and buttons)
    var $searchGroup = $(
        '<div class="wl-dropdown-group" style="display:none">' +
            '<label class="wl-dropdown-label">Search</label>' +
            '<div class="wl-search-wrap">' +
                '<input type="text" class="wl-search-field" id="wl-search-input" ' +
                'placeholder="Filter rows..." autocomplete="off" />' +
                '<span class="wl-search-clear-btn" id="wl-search-clear">\u00D7</span>' +
            '</div>' +
        '</div>'
    );
    $("#wl-dropdowns").append($searchGroup);
    var $searchInput = $searchGroup.find("#wl-search-input");
    var $searchClear = $searchGroup.find("#wl-search-clear");
    // ══════════════════════════════════════════════════════════════════
    // Conflict handling (optimistic locking)
    // ══════════════════════════════════════════════════════════════════
    function handleSaveError(xhr, fallbackMsg) {
        var err = fallbackMsg || "Save failed.";
        try {
            var resp = JSON.parse(xhr.responseText);
            err = resp.error || err;
            // On 409 conflict, update mtime so external change modal
            // doesn't also fire, and offer to reload
            if (xhr.status === 409 && resp.current_mtime) {
                loadedMtime = resp.current_mtime;
            }
        } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
        // Escape server error to prevent XSS
        var safeErr = _.escape(err);
        if (xhr.status === 409) {
            showMsg(safeErr + ' <span class="wl-link" id="wl-conflict-reload">Click to reload.</span>', "error");
            $msg.off("click", "#wl-conflict-reload").on("click", "#wl-conflict-reload", function () {
                loadCsv(selectedCsv, selectedApp);
            });
        } else {
            showMsg(safeErr, "error");
        }
    }

    // showMsg, formatDailyLimitMsg → wl_ui.js module (aliased above)

    // ══════════════════════════════════════════════════════════════════
    // Searchable Detection Rule Dropdown
    // ══════════════════════════════════════════════════════════════════

    var canCreateRules = false;
    var canCreateCsv = false;
    var canDeleteRules = false;
    var canDeleteCsv = false;
    var reasonGates = {};

    function loadRules() {
        restGet({ action: "get_mapping" })
        .done(function (data) {
            mappingData = data.mapping || [];
            var perms = data.permissions || {};
            canCreateRules = !!perms.can_create_rules;
            canCreateCsv = !!perms.can_create_csv;
            canDeleteRules = !!perms.can_delete_rules;
            canDeleteCsv = !!perms.can_delete_csv;
            reasonGates = perms.reason_gates || {};
            var ruleSet = {};
            mappingData.forEach(function (m) {
                ruleSet[m.rule_name] = true;
            });
            // Merge registered rules (those without CSV mappings yet)
            (data.registered_rules || []).forEach(function (r) {
                ruleSet[r] = true;
            });
            allRules = Object.keys(ruleSet).sort();
            renderRuleList(allRules);

            // Auto-select rule + CSV from URL params (e.g. ?rule=DR102&csv=DR102_whitelist.csv)
            var urlParams = new URLSearchParams(window.location.search);
            var paramRule = urlParams.get("rule");
            var paramCsv = urlParams.get("csv");
            if (paramRule) {
                if (allRules.indexOf(paramRule) === -1) {
                    // Rule doesn't exist — show error
                    $table.html(
                        '<div class="wl-alert wl-alert-warning">' +
                            '<strong>Detection rule "' + _.escape(paramRule) +
                            '" was not found.</strong>' +
                            '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                                'It may have been removed or the link may be outdated.' +
                            '</span>' +
                            '<br><span class="btn btn-primary" id="wl-go-home" ' +
                                'style="margin-top:8px">Back to Whitelist Manager</span>' +
                        '</div>'
                    );
                } else {
                    selectRule(paramRule, paramCsv || undefined);
                    // Check if a specific CSV was requested but doesn't exist for this rule
                    if (paramCsv && selectedCsv !== paramCsv) {
                        showMsg(
                            'CSV file "' + _.escape(paramCsv) +
                            '" was not found for rule "' + _.escape(paramRule) +
                            '". Showing available CSV instead.', "warning");
                    }
                }
            }
        })
        .fail(function () {
            showMsg("Failed to load detection rules.", "error");
        });
    }

    var CREATE_RULE_SENTINEL = "__create_new_rule__";

    function renderRuleList(rules) {
        var createBtn = "";
        if (canCreateRules) {
            createBtn =
                '<div class="wl-dropdown-item wl-dropdown-create-rule" data-value="' +
                    CREATE_RULE_SENTINEL + '" style="border-bottom:1px solid var(--wl-border);' +
                    'font-style:italic;color:var(--wl-link)">' +
                    '+ Create new detection rule' +
                '</div>';
        }

        if (!rules.length) {
            $ruleList.html(
                createBtn +
                '<div class="wl-dropdown-no-match">No matching rules</div>'
            );
            return;
        }
        var html = createBtn;
        rules.forEach(function (rule) {
            var cls = "wl-dropdown-item";
            if (rule === selectedRule) { cls += " wl-selected"; }
            var removeSpan = canDeleteRules
                ? '<span class="wl-dropdown-remove" data-rule="' +
                  _.escape(rule) + '">remove</span>'
                : '';
            html += '<div class="' + cls + '" data-value="' + _.escape(rule) + '">' +
                    '<span>' + _.escape(rule) + '</span>' + removeSpan + '</div>';
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

    $ruleSearch.on("keydown", function (e) {
        if (e.which === 13) {
            e.preventDefault();
            var typed = $(this).val().trim();
            if (!typed) { return; }
            // If it matches an existing rule exactly, select that
            var exactMatch = allRules.filter(function (r) {
                return r.toLowerCase() === typed.toLowerCase();
            });
            if (exactMatch.length) {
                selectRule(exactMatch[0]);
            } else if (canCreateRules) {
                // Treat as a new/unmapped rule name
                selectRule(typed);
            } else {
                showMsg("Creating new detection rules is restricted to admins.", "error");
            }
            $ruleList.removeClass("wl-open");
        }
    });

    $(document).on("click", function (e) {
        if (!$(e.target).closest("#rule-select").length) {
            $ruleList.removeClass("wl-open");
        }
    });

    // Intercept "remove" click on rule items (before the item click)
    $ruleList.on("click", ".wl-dropdown-remove", function (e) {
        e.stopPropagation();
        var rule = $(this).data("rule");
        $ruleList.removeClass("wl-open");
        if (rule) { showRemoveModal("rule", rule); }
    });

    $ruleList.on("click", ".wl-dropdown-item", function () {
        var rule = $(this).data("value");
        $ruleList.removeClass("wl-open");
        if (rule === CREATE_RULE_SENTINEL) {
            showNewRuleModal();
            return;
        }
        selectRule(rule);
    });

    $ruleClear.on("click", function () {
        selectedRule = "";
        selectedCsv = "";
        selectedApp = "";
        $ruleSearch.val("");
        $ruleClear.hide();
        renderRuleList(allRules);
        $ruleList.removeClass("wl-open");
        csvDisabled = true;
        $csvDisplay.text("-- Select a Detection Rule first --").addClass("wl-disabled");
        $csvList.empty().removeClass("wl-open");
        updateUrlParams();
        stopChangeMonitoring();
        loadedMtime = null;
        loadedPendingCount = 0;
        $searchGroup.hide();
        $revertGroup.hide();
        clearUndo();
        pendingApprovals = [];
        $("#wl-approval-actions").remove();
        $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
        $diff.empty();
        clearMsg();
    });

    function filterRules(query) {
        if (!query || !query.trim()) { return allRules; }
        var q = query.trim().toLowerCase();
        return allRules.filter(function (r) {
            return r.toLowerCase().indexOf(q) !== -1;
        });
    }

    function selectRule(rule, preferCsv) {
        if (!rule) { return; }
        selectedRule = rule;
        selectedCsv = "";
        $ruleSearch.val(rule);
        $ruleClear.show();
        renderRuleList(allRules);
        clearUndo();
        pendingApprovals = [];
        $("#wl-approval-actions").remove();
        updateUrlParams();

        var csvEntries = mappingData.filter(function (m) {
            return m.rule_name === rule;
        });

        csvDisabled = false;
        $csvDisplay.removeClass("wl-disabled");

        if (!csvEntries.length) {
            $csvDisplay.text("No CSV files for this rule").addClass("wl-disabled");
            csvDisabled = true;
            selectedCsv = "";
            selectedApp = "";
            stopChangeMonitoring();
            loadedMtime = null;
            loadedPendingCount = 0;
            $searchGroup.hide();
            $revertGroup.hide();
            var noCsvHtml = '<div class="wl-alert wl-alert-warning">' +
                '<strong>No whitelisting exists for this detection rule.</strong>';
            if (canCreateCsv) {
                noCsvHtml +=
                    '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                        'Would you like to create a new CSV whitelist?' +
                    '</span>' +
                    '<br><span class="btn btn-primary" id="wl-create-csv-btn" ' +
                        'style="margin-top:8px">Create CSV</span>';
            } else {
                noCsvHtml +=
                    '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                        'Contact an administrator to create a CSV whitelist for this rule.' +
                    '</span>';
            }
            noCsvHtml += '</div>';
            $table.html(noCsvHtml);
            $diff.empty();
            return;
        }

        // Store entries for click handler
        $csvList.data("entries", csvEntries);

        // Render custom CSV dropdown items
        renderCsvList(csvEntries);

        var target = preferCsv || csvEntries[0].csv_file;
        selectCsvItem(target, csvEntries);
    }

    function renderCsvList(entries) {
        var html = "";
        if (canCreateCsv) {
            html += '<div class="wl-dropdown-item wl-dropdown-create-csv" ' +
                    'style="border-bottom:1px solid var(--wl-border);' +
                    'font-style:italic;color:var(--wl-link)">+ Create new CSV</div>';
        }
        entries.forEach(function (entry) {
            var cls = "wl-dropdown-item";
            if (entry.csv_file === selectedCsv) { cls += " wl-selected"; }
            var removeSpan = canDeleteCsv
                ? '<span class="wl-dropdown-remove wl-csv-remove" ' +
                  'data-csv="' + _.escape(entry.csv_file) + '" ' +
                  'data-rule="' + _.escape(entry.rule_name || selectedRule) +
                  '">remove</span>'
                : '';
            html += '<div class="' + cls + ' wl-csv-item" ' +
                    'data-csv="' + _.escape(entry.csv_file) + '" ' +
                    'data-app="' + _.escape(entry.app_context || "") + '">' +
                    '<span>' + _.escape(entry.csv_file) + '</span>' +
                    removeSpan + '</div>';
        });
        $csvList.html(html);
    }

    function selectCsvItem(csvFile, entries) {
        if (!entries) { entries = $csvList.data("entries") || []; }
        var entry = null;
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].csv_file === csvFile) { entry = entries[i]; break; }
        }
        if (!entry) { return; }
        $csvDisplay.text(entry.csv_file);
        $csvList.removeClass("wl-open");
        onCsvSelected(entry.csv_file, entry.app_context || "");
    }

    // CSV custom dropdown: open/close
    $csvDisplay.on("click", function () {
        if (csvDisabled) { return; }
        $csvList.toggleClass("wl-open");
    });
    $(document).on("click", function (e) {
        if (!$(e.target).closest("#csv-dropdown").length) {
            $csvList.removeClass("wl-open");
        }
    });
    // CSV item click
    $csvList.on("click", ".wl-csv-item", function (e) {
        if ($(e.target).hasClass("wl-csv-remove")) { return; }
        var csvFile = $(this).data("csv");
        var appCtx = $(this).data("app") || "";
        $csvDisplay.text(csvFile);
        $csvList.removeClass("wl-open");
        onCsvSelected(csvFile, appCtx);
    });
    // CSV "Create new CSV" click
    $csvList.on("click", ".wl-dropdown-create-csv", function () {
        $csvList.removeClass("wl-open");
        showCreateCsvModal(selectedRule);
    });
    // CSV "remove" click
    $csvList.on("click", ".wl-csv-remove", function (e) {
        e.stopPropagation();
        var csv = $(this).data("csv");
        var rule = $(this).data("rule") || selectedRule;
        $csvList.removeClass("wl-open");
        if (csv) { showRemoveModal("csv", csv, rule); }
    });

    // Keep the URL in sync with current selection (no page reload)
    function updateUrlParams() {
        var params = new URLSearchParams(window.location.search);
        if (selectedRule) { params.set("rule", selectedRule); } else { params.delete("rule"); }
        if (selectedCsv) { params.set("csv", selectedCsv); } else { params.delete("csv"); }
        var newUrl = window.location.pathname;
        var qs = params.toString();
        if (qs) { newUrl += "?" + qs; }
        window.history.replaceState(null, "", newUrl);
    }

    function onCsvSelected(csvFile, appCtx) {
        // Save current column widths before switching
        if (selectedCsv && Object.keys(colWidths).length) {
            allColWidths[selectedCsv] = $.extend({}, colWidths);
        }
        stopChangeMonitoring();
        loadedMtime = null;
        loadedPendingCount = 0;
        selectedCsv = csvFile || "";
        selectedApp = appCtx || "";
        colWidths = allColWidths[selectedCsv] ? $.extend({}, allColWidths[selectedCsv]) : {};
        clearUndo();
        updateUrlParams();
        // Update selected highlight in dropdown
        $csvList.find(".wl-csv-item").removeClass("wl-selected");
        $csvList.find(".wl-csv-item").filter(function () {
            return $(this).data("csv") === selectedCsv;
        }).addClass("wl-selected");
        if (selectedCsv) {
            loadCsv(selectedCsv, selectedApp);
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Create CSV for unmapped rules
    // ══════════════════════════════════════════════════════════════════

    $table.on("click", "#wl-create-csv-btn", function () {
        if (!selectedRule) { return; }
        showCreateCsvModal(selectedRule);
    });

    // "Back to Whitelist Manager" button on invalid URL param error
    $table.on("click", "#wl-go-home", function () {
        window.location.href = window.location.pathname;
    });

    // ══════════════════════════════════════════════════════════════════
    // Removal modal (rule or CSV)
    // ══════════════════════════════════════════════════════════════════

    function showRemoveModal(type, name, parentRule) {
        $(".wl-modal-overlay").remove();

        var isRule = (type === "rule");
        var title = isRule ? "Remove Detection Rule" : "Remove CSV File";

        // For rules, list affected CSVs
        var affectedCsvs = [];
        if (isRule) {
            mappingData.forEach(function (m) {
                if (m.rule_name === name) {
                    affectedCsvs.push(m.csv_file);
                }
            });
        } else {
            // For CSV removal, check if it's the last CSV for the rule
            var ruleCsvCount = 0;
            mappingData.forEach(function (m) {
                if (m.rule_name === (parentRule || selectedRule)) {
                    ruleCsvCount++;
                }
            });
            if (ruleCsvCount <= 1) {
                // This is the last CSV — warn that the rule will also be removed
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
            var ruleCsvs = mappingData.filter(function (m) {
                return m.rule_name === (parentRule || selectedRule);
            });
            if (ruleCsvs.length <= 1) {
                lastCsvWarning =
                    '<div style="margin-top:8px;padding:6px 10px;border-radius:4px;' +
                    'background:var(--wl-bg-warning,#fff3cd);color:#856404;font-size:12px">' +
                    'This is the only CSV for rule <strong>' +
                    _.escape(parentRule || selectedRule) +
                    '</strong>. Removing it will also remove the rule from the dropdown.' +
                    '</div>';
            }
            summaryHtml = '<div style="margin-bottom:12px;font-size:13px">' +
                '<strong>CSV:</strong> ' + _.escape(name) + '<br>' +
                '<strong>Rule:</strong> ' + _.escape(parentRule || selectedRule) +
                lastCsvWarning +
                '</div>';
        }

        var fileWord = isRule
            ? (affectedCsvs.length === 1 ? '1 CSV file' : affectedCsvs.length + ' CSV files')
            : 'the CSV file';

        var html =
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal" style="max-width:520px">' +
                '<h3 style="margin-top:0">' + title + '</h3>' +
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
                '<div style="display:flex;gap:8px;justify-content:flex-end">' +
                    '<span class="btn" id="wl-remove-confirm" ' +
                        'style="background:#e74c3c;color:#fff;cursor:pointer">Remove</span>' +
                    '<span class="btn" id="wl-remove-cancel" ' +
                        'style="cursor:pointer">Cancel</span>' +
                '</div>' +
            '</div></div>';

        $("body").append(html);

        // Focus the reason field
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
                    rule_name: parentRule || selectedRule,
                    removal_type: removalType,
                    comment: reason
                };
            }

            // Check reason gate for remove actions
            var gateKey = isRule ? "require_reason_rule_deletion" : "require_reason_csv_deletion";
            if (reasonGates[gateKey]) {
                // The comment already serves as the approval reason
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

                // If we removed the currently selected rule or its CSV, reset
                if (isRule && name === selectedRule) {
                    selectedRule = "";
                    selectedCsv = "";
                    selectedApp = "";
                    $ruleSearch.val("");
                    $ruleClear.hide();
                    csvDisabled = true;
                    $csvDisplay.text("-- Select a Detection Rule first --")
                        .addClass("wl-disabled");
                    $csvList.empty().removeClass("wl-open");
                    stopChangeMonitoring();
                    $searchGroup.hide();
                    $revertGroup.hide();
                    $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
                    $diff.empty();
                } else if (!isRule && name === selectedCsv) {
                    // CSV was removed — re-select the rule to refresh CSV list
                    selectedCsv = "";
                    selectedApp = "";
                    stopChangeMonitoring();
                    $searchGroup.hide();
                    $revertGroup.hide();
                    $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
                    $diff.empty();
                }

                // Reload mapping to refresh dropdowns
                loadRules();
                if (selectedRule && !isRule) {
                    // Re-select the rule to refresh CSV list
                    setTimeout(function () {
                        selectRule(selectedRule);
                    }, 500);
                }
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
                        '<span class="btn btn-primary" id="wl-new-rule-ok">Next</span> ' +
                        '<span class="btn" id="wl-new-rule-cancel">Cancel</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        // Force dark theme on modal inputs — Splunk overrides inline styles
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
            // Check if rule already exists locally
            var exists = allRules.some(function (r) {
                return r.toLowerCase() === name.toLowerCase();
            });
            if (exists) {
                $err.text("Rule '" + _.escape(name) + "' already exists. Select it from the dropdown instead.").show();
                return;
            }

            // Save to backend so it persists
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
                    allRules.push(name);
                    allRules.sort();
                    renderRuleList(allRules);
                    selectRule(name);
                    showMsg(
                        "Detection rule <strong>" + _.escape(name) +
                        "</strong> created. You can now attach a CSV whitelist.",
                        "info"
                    );
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

            if (reasonGates.require_reason_rule_creation) {
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

    // ── Approval reason popup (shared by all gated create/delete flows) ──
    function showApprovalReasonPopup(actionLabel, onSubmit) {
        $(".wl-approval-reason-overlay").remove();
        var html =
            '<div class="wl-modal-overlay wl-approval-reason-overlay">' +
                '<div class="wl-modal" style="max-width:440px">' +
                    '<h3 style="margin:0 0 8px">Approval Required</h3>' +
                    '<p style="margin:0 0 12px;font-size:13px;color:var(--wl-text-muted,#999)">' +
                        'This action requires admin approval. Please provide a reason for: ' +
                        '<strong>' + _.escape(actionLabel) + '</strong></p>' +
                    '<textarea id="wl-approval-reason-text" class="wl-input" ' +
                        'style="width:100%;height:80px;resize:vertical;font-size:13px" ' +
                        'placeholder="Reason for this request (required)" maxlength="500"></textarea>' +
                    '<div class="wl-char-counter" data-for="wl-approval-reason-text">0 / 500</div>' +
                    '<div id="wl-approval-reason-error" class="wl-msg-error" style="display:none;margin-top:6px"></div>' +
                    '<div class="wl-modal-actions" style="margin-top:12px">' +
                        '<span class="btn btn-primary" id="wl-approval-reason-ok">Submit Request</span> ' +
                        '<span class="btn" id="wl-approval-reason-cancel">Cancel</span>' +
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

    function showCreateCsvModal(ruleName) {
        $(".wl-modal-overlay").remove();

        // Suggest a filename based on rule name
        var safeName = ruleName.replace(/[^a-zA-Z0-9_\-]/g, "_");
        var suggestedFile = safeName + ".csv";

        // Fetch installed apps for the dropdown
        restGet({ action: "get_apps" }).done(function (appData) {
            var apps = (appData.apps || []);
            var defaultApp = appData.default_app || "wl_manager";

            // Build app dropdown options
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
                                    '<span class="btn wl-import-file-btn" id="wl-import-file-trigger">Choose File</span>' +
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
                            '<span class="btn btn-primary" id="wl-create-csv-ok">Create</span> ' +
                            '<span class="btn" id="wl-create-csv-cancel">Cancel</span>' +
                        '</div>' +
                    '</div>' +
                '</div>';

            var $modal = $(html);
            $("body").append($modal);

            // Force dark theme on modal inputs — Splunk overrides inline styles
            var darkBg = getComputedStyle(document.documentElement).getPropertyValue("--wl-bg-input").trim() || "#1a1c1e";
            var darkTxt = getComputedStyle(document.documentElement).getPropertyValue("--wl-text").trim() || "#e0e0e0";
            $modal.find(".wl-input").css({ "background-color": darkBg, "color": darkTxt });

            _bindCreateCsvEvents($modal, ruleName, defaultApp);

            // Click proxy: custom button triggers the hidden native file input
            $modal.on("click", "#wl-import-file-trigger", function () {
                $modal.find("#wl-import-file").trigger("click");
            });

            setTimeout(function () { $modal.find("#wl-import-file-trigger").focus(); }, 100);
        });
    }

    function _bindCreateCsvEvents($modal, ruleName, defaultApp) {

        // ── Import state ──
        var importedHeaders = null;  // null = manual mode, array = import mode
        var importedRows = null;     // null = manual mode, array = import mode

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

            // File size check
            if (file.size > IMPORT_MAX_FILE_SIZE) {
                var sizeMB = (file.size / (1024 * 1024)).toFixed(1);
                $err.text("File is too large (" + sizeMB + " MB). Maximum allowed is 2 MB.").show();
                resetImportMode();
                return;
            }

            // Extension check
            if (!file.name.toLowerCase().endsWith(".csv")) {
                $err.text("Only .csv files are accepted.").show();
                resetImportMode();
                return;
            }

            var reader = new FileReader();
            reader.onload = function (ev) {
                var text = ev.target.result;

                // Parse CSV
                var parsed = parseCSV(text);

                // If parser found structural errors, show them and stop
                if (parsed.errors.length > 0 && parsed.headers.length === 0) {
                    $err.text(parsed.errors[0]).show();
                    resetImportMode();
                    return;
                }

                // Validate
                var validation = validateImportedCSV(file.name, parsed.headers, parsed.rows);

                // Merge parser errors into validation errors
                parsed.errors.forEach(function (e) { validation.errors.unshift(e); });

                // Show messages
                renderImportMessages(validation.errors, validation.warnings, $msgs);

                // Enable/disable Create button
                if (validation.errors.length > 0) {
                    $modal.find("#wl-create-csv-ok").addClass("disabled");
                } else {
                    $modal.find("#wl-create-csv-ok").removeClass("disabled");
                }

                // Switch to import mode
                importedHeaders = parsed.headers;
                importedRows = parsed.rows;

                // Auto-populate filename (user can still edit)
                $modal.find("#wl-create-csv-name").val(file.name);

                // Show imported headers as read-only, hide manual input
                $modal.find("#wl-create-csv-headers-manual").hide();
                $modal.find("#wl-import-headers-text").text(parsed.headers.join(", "));
                $modal.find("#wl-create-csv-headers-imported").show();

                // Show file label and clear button
                $modal.find("#wl-import-file-label").text(file.name);
                $modal.find("#wl-import-clear").show();

                // Render preview (only if no blocking errors)
                if (validation.errors.length === 0) {
                    renderImportPreview(parsed.headers, parsed.rows, $preview);
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
            // Reset filename to suggested name
            var safeName = ruleName.replace(/[^a-zA-Z0-9_\-]/g, "_");
            $modal.find("#wl-create-csv-name").val(safeName + ".csv");
        });

        // ── Create button ──
        function validateAndCreate() {
            var csvName = $modal.find("#wl-create-csv-name").val().trim();
            var selectedApp = $modal.find("#wl-create-csv-app").val();
            var $err = $modal.find("#wl-create-csv-error");
            $err.hide();

            // ── Filename validation (shared by both modes) ──
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
                // ── IMPORT MODE ──
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
                // ── MANUAL MODE ──
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
                // Check for duplicates
                var seen = {};
                for (var i = 0; i < headers.length; i++) {
                    var lc = headers[i].toLowerCase();
                    if (seen[lc]) {
                        $err.text("Duplicate column header: '" + _.escape(headers[i]) + "'").show();
                        return;
                    }
                    seen[lc] = true;
                }
                // Check for spaces, underscore-prefix, invalid chars, and length
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

            // ── Reason gate: prompt for approval reason ──
            if (reasonGates.require_reason_csv_creation) {
                showApprovalReasonPopup("Create " + csvName, function (reason) {
                    payload.approval_reason = reason;
                    submitCreateCsv(payload, csvName, headers, selectedApp);
                });
                return;
            }

            submitCreateCsv(payload, csvName, headers, selectedApp);
        }

        function submitCreateCsv(payload, csvName, headers, selectedApp) {
            // Disable the button to prevent double-click
            $modal.find("#wl-create-csv-ok").addClass("disabled").text("Creating...");

            restPost(payload)
            .done(function (resp) {
                $modal.remove();
                if (resp.request_id) {
                    // Request was queued for approval
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
                // Reload mapping data and re-select the rule to show the new CSV
                restGet({ action: "get_mapping" })
                .done(function (data) {
                    mappingData = data.mapping || [];
                    var perms = data.permissions || {};
                    canCreateRules = !!perms.can_create_rules;
                    canCreateCsv = !!perms.can_create_csv;
                    var ruleSet = {};
                    mappingData.forEach(function (m) { ruleSet[m.rule_name] = true; });
                    (data.registered_rules || []).forEach(function (r) { ruleSet[r] = true; });
                    allRules = Object.keys(ruleSet).sort();
                    renderRuleList(allRules);
                    selectRule(ruleName, csvName);
                });
            })
            .fail(function (xhr) {
                var errMsg = "Failed to create CSV.";
                try {
                    var r = JSON.parse(xhr.responseText);
                    if (r.error) { errMsg = r.error; }
                } catch (ignored) {}
                $err.text(errMsg).show();
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

        // Show/hide cross-app warning when app selection changes
        $modal.on("change", "#wl-create-csv-app", function () {
            var sel = $(this).val();
            $modal.find("#wl-create-csv-app-warn").toggle(sel !== defaultApp);
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Table rendering
    // ══════════════════════════════════════════════════════════════════

    function renderTable(headers, rows) {
        currentHeaders  = headers;
        originalHeaders = headers.slice();
        currentRows    = rows.map(function (r) { return $.extend({}, r); });
        originalRows   = rows.map(function (r) { return $.extend({}, r); });
        currentPage    = 0;
        selectedIdxSet = {};
        searchQuery    = "";
        pendingBulkEditCount = 0; // Reset bulk edit tracking on fresh load
        // Restore persisted column widths for this CSV
        if (selectedCsv && allColWidths[selectedCsv]) {
            colWidths = $.extend({}, allColWidths[selectedCsv]);
        }
        $searchInput.val("");
        $searchGroup.show();
        refreshTable();
    }

    // ── Search helpers ──────────────────────────────────────────────
    function getFilteredRows() {
        // Pending approval filter takes priority
        if (pendingFilterActive && pendingFilterIndices) {
            var pfResults = [];
            for (var p = 0; p < pendingFilterIndices.length; p++) {
                var pi = pendingFilterIndices[p];
                if (pi < currentRows.length) {
                    pfResults.push({ idx: pi, row: currentRows[pi] });
                }
            }
            return pfResults;
        }
        if (!searchQuery) { return null; }
        var q = searchQuery.toLowerCase();
        var visibleHeaders = currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });
        var results = [];
        for (var i = 0; i < currentRows.length; i++) {
            var row = currentRows[i];
            for (var j = 0; j < visibleHeaders.length; j++) {
                var val = (row[visibleHeaders[j]] || "").toLowerCase();
                if (val.indexOf(q) !== -1) {
                    results.push({ idx: i, row: row });
                    break;
                }
            }
        }
        return results;
    }

    function clearSearch() {
        searchQuery = "";
        $searchInput.val("");
        currentPage = 0;
        refreshTable();
    }

    function autoResizeTextarea(el) {
        el.style.height = 'auto';
        el.style.height = el.scrollHeight + 'px';
        // Show scrollbar when content exceeds max-height (90px from CSS)
        el.style.overflow = el.scrollHeight > 90 ? 'auto' : 'hidden';
        // Equalize all textareas in the same row to match the tallest
        var $row = $(el).closest("tr");
        if ($row.length) {
            var maxH = 0;
            $row.find("textarea.wl-input").each(function () {
                var h = this.offsetHeight;
                if (h > maxH) maxH = h;
            });
            if (maxH > 0) {
                $row.find("textarea.wl-input").each(function () {
                    this.style.height = maxH + "px";
                });
            }
        }
    }

    function autoResizeAllTextareas() {
        $table.find("textarea.wl-input").each(function () {
            autoResizeTextarea(this);
        });
        // Equalize textarea heights within each row to the tallest one
        $table.find("tbody tr").each(function () {
            var maxH = 0;
            $(this).find("textarea.wl-input").each(function () {
                var h = this.offsetHeight;
                if (h > maxH) maxH = h;
            });
            if (maxH > 0) {
                $(this).find("textarea.wl-input").each(function () {
                    this.style.height = maxH + "px";
                });
            }
        });
    }

    function syncInputs() {
        $table.find("tbody tr").each(function () {
            var idx = $(this).data("idx");
            $(this).find(".wl-input").each(function () {
                // Skip Expires inputs — they display local time but
                // currentRows holds UTC.  Only the date picker updates them.
                if ($(this).hasClass("wl-expires-input")) { return; }
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
        var isSearching = !!searchQuery;

        // Visible headers (skip _ metadata columns)
        var visibleHeaders = currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });

        // Determine rows to display: filtered or all
        var filtered = getFilteredRows();
        var displayEntries; // array of {idx, row}
        if (filtered !== null) {
            displayEntries = filtered;
        } else {
            displayEntries = currentRows.map(function (r, i) {
                return { idx: i, row: r };
            });
        }

        var html = "";

        // Presence bar placeholder — always reserve space to prevent layout shift
        html += '<div id="wl-presence-bar" class="wl-presence-bar"></div>';

        // Search result count
        if (isSearching) {
            html += '<div class="wl-search-info">' + displayEntries.length +
                    ' of ' + currentRows.length + ' row(s) match</div>';
        }

        // Pagination over displayEntries
        var totalRows  = displayEntries.length;
        var totalPages = Math.max(1, Math.ceil(totalRows / ROWS_PER_PAGE));
        if (currentPage >= totalPages) { currentPage = totalPages - 1; }
        if (currentPage < 0) { currentPage = 0; }
        var startIdx = currentPage * ROWS_PER_PAGE;
        var endIdx   = Math.min(startIdx + ROWS_PER_PAGE, totalRows);
        var pageEntries = displayEntries.slice(startIdx, endIdx);

        html += '<div class="wl-table-scroll">';
        html += '<table class="wl-table">';

        html += "<thead><tr>";
        var allSelected = currentRows.length > 0 && Object.keys(selectedIdxSet).length === currentRows.length;
        html += '<th class="wl-col-check"><input type="checkbox" id="wl-check-all" title="Select all"' + (allSelected ? ' checked="checked"' : '') + ' /></th>';
        html += '<th class="wl-col-rownum">#</th>';
        visibleHeaders.forEach(function (h) {
            var widthStyle = colWidths[h] ? ' style="width:' + colWidths[h] + 'px;min-width:' + colWidths[h] + 'px;"' : '';
            html += '<th class="wl-col-draggable" data-col="' + _.escape(h) + '"' + widthStyle + '>';
            if (!csvLocked) {
                html += '<span class="wl-col-drag-handle" title="Drag to reorder">\u2630</span>';
            }
            html += '<span class="wl-col-header-text">' + _.escape(h) + '</span>';
            if (!csvLocked) {
                html += '<span class="wl-col-remove-btn" data-col="' + _.escape(h) +
                        '" title="Remove column">&times;</span>';
            }
            html += '<div class="wl-col-resize-handle"></div></th>';
        });
        html += '<th class="wl-col-actions">Actions</th>';
        html += "</tr></thead>";

        html += "<tbody>";
        pageEntries.forEach(function (entry) {
            html += buildRow(visibleHeaders, entry.row, entry.idx, hasExpires, now);
        });
        html += "</tbody></table></div>";

        // Pagination controls
        if (totalPages > 1) {
            html += '<div class="wl-pagination">';
            html += '<button class="btn btn-small" id="btn-page-first"' +
                    (currentPage === 0 ? ' disabled="disabled"' : '') +
                    '>&laquo; First</button> ';
            html += '<button class="btn btn-small" id="btn-page-prev"' +
                    (currentPage === 0 ? ' disabled="disabled"' : '') +
                    '>&#8249; Prev</button>';
            var colCount = visibleHeaders.length;
            var colWord = colCount === 1 ? 'column' : 'columns';
            var rowInfo = isSearching
                ? displayEntries.length + ' matching'
                : currentRows.length + ' rows';
            html += ' <span class="wl-page-info">Page ' +
                    (currentPage + 1) + ' of ' + totalPages +
                    ' (' + rowInfo + ' \u2013 ' + colCount + ' ' + colWord + ')</span> ';
            html += '<button class="btn btn-small" id="btn-page-next"' +
                    (currentPage >= totalPages - 1 ? ' disabled="disabled"' : '') +
                    '>Next &#8250;</button> ';
            html += '<button class="btn btn-small" id="btn-page-last"' +
                    (currentPage >= totalPages - 1 ? ' disabled="disabled"' : '') +
                    '>Last &raquo;</button>';
            html += ' <select id="wl-page-size" class="wl-page-size" title="Rows per page">';
            PAGE_SIZE_OPTIONS.forEach(function (n) {
                html += '<option value="' + n + '"' + (n === ROWS_PER_PAGE ? ' selected' : '') + '>' + n + ' per page</option>';
            });
            html += '</select>';
            html += '</div>';
        } else if (totalRows > PAGE_SIZE_OPTIONS[0]) {
            // Only one page but enough rows that the user might want to change page size
            html += '<div class="wl-pagination">';
            html += '<select id="wl-page-size" class="wl-page-size" title="Rows per page">';
            PAGE_SIZE_OPTIONS.forEach(function (n) {
                html += '<option value="' + n + '"' + (n === ROWS_PER_PAGE ? ' selected' : '') + '>' + n + ' per page</option>';
            });
            html += '</select>';
            html += '</div>';
        }

        // Action buttons
        html += '<div class="wl-buttons">';
        html += '<button class="btn btn-primary" id="btn-add-row">+ Add Row</button> ';
        html += '<button class="btn btn-primary" id="btn-add-col">+ Add Column</button> ';
        html += '<button class="btn btn-primary" id="btn-bulk-edit" disabled="disabled">Bulk Edit</button> ';
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
        autoResizeAllTextareas();
        applyPendingCssHighlighting();
    }

    function buildRow(visibleHeaders, row, idx, hasExpires, now) {
        // Check if row is expired
        var expired = false;
        if (hasExpires && expireColumn) {
            var expVal = (row[expireColumn] || "").trim();
            if (expVal) {
                var expDate = expVal.endsWith("UTC")
                    ? new Date(expVal.replace(" UTC", "Z").replace(" ", "T"))  // UTC suffix
                    : new Date(expVal);                                         // Legacy local
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
        if (csvLocked) {
            tooltip = ' title="Locked — pending approval"';
        } else if (row._added_by || row._added_at) {
            var parts = [];
            if (row._added_by) { parts.push("Added by: " + row._added_by); }
            if (row._added_at) { parts.push("Added at: " + row._added_at); }
            tooltip = ' title="' + _.escape(parts.join(" | ")) + '"';
        }

        var html = '<tr data-idx="' + idx + '"' + trClass + tooltip + '>';

        if (csvLocked) {
            // Full file lock: no checkbox, no drag, readonly cells, no Remove button
            html += '<td class="wl-col-check"></td>';
            html += '<td class="wl-col-rownum" data-idx="' + idx + '"><span class="wl-grip-icon" style="visibility:hidden">\u2630</span>' + (idx + 1) + '</td>';
        } else {
            html += '<td class="wl-col-check"><input type="checkbox" class="wl-row-check" data-idx="' + idx + '"' + (selectedIdxSet[idx] ? ' checked="checked"' : '') + ' /></td>';
            html += '<td class="wl-col-rownum wl-row-drag-handle" data-idx="' + idx + '" title="Drag to reorder"><span class="wl-grip-icon">\u2630</span>' + (idx + 1) + '</td>';
        }

        visibleHeaders.forEach(function (h) {
            var val = row[h] || "";
            var isExpires = (expireColumn && h === expireColumn);
            // Convert UTC Expires values to local time for display
            if (isExpires && val && val.endsWith("UTC")) {
                var utcDate = new Date(val.replace(" UTC", "Z").replace(" ", "T"));
                if (!isNaN(utcDate.getTime())) { val = formatLocalDateTime(utcDate); }
            }
            var matchClass = "";
            if (searchQuery && val) {
                var cellLower = val.toLowerCase();
                if (cellLower.indexOf(searchQuery.toLowerCase()) !== -1) {
                    matchClass = " wl-cell-match";
                }
            }
            var editedClass = "";
            if (idx < originalRows.length) {
                var origVal = originalRows[idx][h] || "";
                if ((row[h] || "") !== origVal) {
                    editedClass = " wl-cell-edited";
                }
            }
            var cellReadonly = csvLocked || isExpires;
            html +=
                "<td>" +
                '<textarea class="wl-input' +
                (isExpires ? ' wl-expires-input' : '') +
                matchClass + editedClass + '" rows="1" ' +
                'maxlength="' + MAX_CELL_CHARS + '" ' +
                'data-header="' + _.escape(h) + '"' +
                (cellReadonly ? ' readonly="readonly" tabindex="-1"' : '') +
                (isExpires && !csvLocked ? ' style="cursor:pointer"' : '') +
                '>' + _.escape(val) + '</textarea>' +
                "</td>";
        });

        if (csvLocked) {
            html += '<td class="wl-col-actions"></td>';
        } else {
            html +=
                '<td class="wl-col-actions">' +
                '<button class="btn btn-small btn-danger btn-rm" data-idx="' + idx + '">' +
                "Remove</button></td>";
        }
        html += "</tr>";
        return html;
    }

    // ══════════════════════════════════════════════════════════════════
    // Row-level undo for cell edits (Ctrl+Z support)
    // ══════════════════════════════════════════════════════════════════

    var editHistory = [];      // stack of {idx, header, oldValue, newValue}
    var MAX_EDIT_HISTORY = 50; // keep last 50 edits

    function trackCellEdit(idx, header, oldValue, newValue) {
        if (oldValue === newValue) { return; }
        editHistory.push({ idx: idx, header: header, oldValue: oldValue, newValue: newValue });
        if (editHistory.length > MAX_EDIT_HISTORY) {
            editHistory.shift();
        }
    }

    function undoCellEdit() {
        if (!editHistory.length) { return; }
        var edit = editHistory.pop();
        if (currentRows[edit.idx]) {
            currentRows[edit.idx][edit.header] = edit.oldValue;
            // Update input if visible on current page
            var $input = $table.find('tr[data-idx="' + edit.idx + '"] .wl-input[data-header="' + edit.header + '"]');
            if ($input.length) {
                $input.val(edit.oldValue).removeClass("wl-cell-edited");
            }
            showMsg("Undid edit: <strong>" + _.escape(edit.header) + "</strong> row " + (edit.idx + 1), "info");
        }
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
            if (csvLocked) { $(this).prop("checked", false); return; }
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
            if (csvLocked) { $(this).prop("checked", false); return; }
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
            if (csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            var selectedIdxs = Object.keys(selectedIdxSet).map(Number);
            if (!selectedIdxs.length) { return; }

            // Separate unsaved (newly added) rows from saved rows
            var savedIdxs = [];
            var unsavedIdxs = [];
            selectedIdxs.forEach(function (idx) {
                if (idx >= originalRows.length) {
                    unsavedIdxs.push(idx);
                } else {
                    savedIdxs.push(idx);
                }
            });

            // Remove unsaved rows immediately (they only exist locally)
            if (unsavedIdxs.length) {
                unsavedIdxs.sort(function (a, b) { return b - a; }); // descending
                unsavedIdxs.forEach(function (idx) {
                    currentRows.splice(idx, 1);
                    delete selectedIdxSet[idx];
                });
                // Re-index selectedIdxSet for saved rows that may have shifted
                var newSet = {};
                Object.keys(selectedIdxSet).forEach(function (k) {
                    var oldIdx = Number(k);
                    var shift = 0;
                    unsavedIdxs.forEach(function (removed) {
                        if (removed < oldIdx) { shift++; }
                    });
                    newSet[oldIdx - shift] = true;
                });
                selectedIdxSet = newSet;
                showMsg("Removed " + unsavedIdxs.length + " unsaved row(s) from the editor.", "info");
                refreshTable();
            }

            // If no saved rows remain to remove, we're done
            if (!savedIdxs.length) { return; }

            // Re-map savedIdxs to account for removed unsaved rows
            selectedIdxs = Object.keys(selectedIdxSet).map(Number);

            // Check approval gate before proceeding
            restPost({
                action: "check_approval_gate",
                gate_action: "bulk_row_removal",
                csv_file: selectedCsv,
                app_context: selectedApp,
                selected_count: selectedIdxs.length
            }).done(function (gateData) {
                if (gateData.requires_approval) {
                    // Approval required — submit for review instead of direct removal
                    showRemoveRowModal(
                        "Submit for Approval",
                        "Removing <strong>" + selectedIdxs.length + "</strong> row(s) requires admin approval.<br>" +
                            "Reason: " + _.escape(gateData.reason) + "<br><br>" +
                            "Your request will be submitted for review.",
                        function (reason) {
                            syncInputs();
                            submitApprovalRequest("bulk_row_removal", reason, selectedIdxs.slice(), null);
                        },
                        {
                            reasonLabel: "Reason for removal",
                            placeholder: "Why are these rows being removed?",
                            confirmText: "Submit",
                            confirmClass: "btn-primary"
                        }
                    );
                } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                    showMsg(formatDailyLimitMsg(gateData.daily_limit), "error");
                } else {
                    // Normal direct removal flow
                    showRemoveRowModal(
                        "Remove " + selectedIdxs.length + " Row" + (selectedIdxs.length > 1 ? "s" : ""),
                        "Remove <strong>" + selectedIdxs.length + "</strong> selected row(s)?<br><br>" +
                            "This action will be saved immediately and logged in the audit trail.",
                        function (reason) {
                            syncInputs();
                            var removedEntries = [];
                            selectedIdxs.sort(function (a, b) { return a - b; });
                            selectedIdxs.forEach(function (idx) {
                                removedEntries.push({
                                    row_number: idx + 1,
                                    row: $.extend({}, currentRows[idx])
                                });
                            });
                            var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
                            var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });
                            selectedIdxSet = {};
                            for (var i = selectedIdxs.length - 1; i >= 0; i--) {
                                currentRows.splice(selectedIdxs[i], 1);
                            }
                            refreshTable();
                            doSaveBulkRemoval(removedEntries, reason, prevRows, prevOriginal);
                        }
                    );
                }
            }).fail(function () {
                // Fail-closed: do not allow the action if gate check fails
                showMsg("Unable to verify approval gate. Please try again.", "error");
            });
        });

        $table.off("change.wl", ".wl-input").on("change.wl", ".wl-input", function () {
            var $el    = $(this);
            if ($el.hasClass("wl-expires-input")) { return; }
            var idx    = $el.closest("tr").data("idx");
            if (csvLocked) { $el.val(currentRows[idx][$el.data("header")] || ""); return; }
            var header = $el.data("header");
            if (currentRows[idx]) {
                var oldValue = currentRows[idx][header] || "";
                var newValue = $el.val();
                trackCellEdit(idx, header, oldValue, newValue);
                currentRows[idx][header] = newValue;
                if (oldValue !== newValue) {
                    $el.addClass("wl-cell-edited");
                }
            }
        });

        // Auto-resize textareas on input
        $table.off("input.wl", "textarea.wl-input").on("input.wl", "textarea.wl-input", function () {
            autoResizeTextarea(this);
        });

        // Prevent Enter key in textareas (CSV cells must not contain newlines)
        $table.off("keydown.wltextarea", "textarea.wl-input").on("keydown.wltextarea", "textarea.wl-input", function (e) {
            if (e.which === 13) { e.preventDefault(); }
        });

        // Strip newlines from pasted text and enforce character limit
        $table.off("paste.wl", "textarea.wl-input").on("paste.wl", "textarea.wl-input", function (e) {
            var self = this;
            setTimeout(function () {
                var cleaned = $(self).val().replace(/[\r\n\t]+/g, " ");
                if (cleaned.length > MAX_CELL_CHARS) {
                    cleaned = cleaned.substring(0, MAX_CELL_CHARS);
                    showMsg("Pasted text truncated to " + MAX_CELL_CHARS + " characters.", "warning");
                }
                $(self).val(cleaned);
                autoResizeTextarea(self);
            }, 0);
        });

        // Remove row with undo support
        $table.off("click.wl", ".btn-rm").on("click.wl", ".btn-rm", function () {
            var idx = $(this).data("idx");
            var row = currentRows[idx];
            if (!row) { return; }
            if (csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }

            // Unsaved row (added but not yet saved) — remove locally, no reason needed
            if (idx >= originalRows.length) {
                syncInputs();
                currentRows.splice(idx, 1);
                selectedIdxSet = {};
                refreshTable();
                showMsg("Unsaved row removed.", "info");
                return;
            }

            // Build a short summary of the row for the modal
            var visH = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var preview = visH.slice(0, 3).map(function (h) {
                return '<strong>' + _.escape(h) + '</strong>: ' + _.escape(row[h] || "");
            }).join(", ");
            if (visH.length > 3) { preview += " &hellip;"; }

            showRemoveRowModal(
                "Remove Row",
                "Remove row <strong>#" + (idx + 1) + "</strong>?<br>" +
                    '<span style="font-size:12px;color:var(--wl-text-secondary)">' + preview + '</span><br><br>' +
                    "This action will be saved immediately and logged in the audit trail.",
                function (reason) {
                    syncInputs();
                    var removedRow = $.extend({}, row);
                    var rowNumber = idx + 1;
                    var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
                    var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });
                    currentRows.splice(idx, 1);
                    selectedIdxSet = {}; // Clear selections — indices shifted after splice
                    refreshTable();
                    doSaveRemoval(removedRow, reason, rowNumber, prevRows, prevOriginal);
                }
            );
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
        $table.off("change.wl", "#wl-page-size").on("change.wl", "#wl-page-size", function () {
            syncInputs();
            var firstVisibleRow = currentPage * ROWS_PER_PAGE;
            ROWS_PER_PAGE = parseInt($(this).val(), 10) || 10;
            currentPage = Math.floor(firstVisibleRow / ROWS_PER_PAGE);
            refreshTable();
        });

        // Add row
        $table.off("click.wl", "#btn-add-row").on("click.wl", "#btn-add-row", function () {
            if (csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            if (currentRows.length >= MAX_ROWS) {
                showMsg(
                    "Row limit reached: maximum <strong>" + MAX_ROWS +
                    "</strong> rows allowed per CSV.",
                    "error"
                );
                return;
            }
            // Sync any in-progress edits before adding a new row, so data
            // typed into the previous row isn't lost when refreshTable redraws.
            syncInputs();
            if (searchQuery) {
                showSearchWarning(function () {
                    // User confirmed — clear search, add row
                    searchQuery = "";
                    var newRow = {};
                    currentHeaders.forEach(function (h) { newRow[h] = ""; });
                    currentRows.push(newRow);
                    currentPage = Math.ceil(currentRows.length / ROWS_PER_PAGE) - 1;
                    refreshTable();
                    $table.find("tbody tr:last input:first").focus();
                });
                return;
            }
            var newRow = {};
            currentHeaders.forEach(function (h) { newRow[h] = ""; });
            currentRows.push(newRow);
            currentPage = Math.ceil(currentRows.length / ROWS_PER_PAGE) - 1;
            refreshTable();
            $table.find("tbody tr:last input:first").focus();
        });

        // Add column
        $table.off("click.wl", "#btn-add-col").on("click.wl", "#btn-add-col", function () {
            if (csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            var visibleCount = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; }).length;
            if (visibleCount >= MAX_COLUMNS) {
                showMsg(
                    "Column limit reached: maximum <strong>" + MAX_COLUMNS +
                    "</strong> columns allowed per CSV.",
                    "error"
                );
                return;
            }
            if (searchQuery) {
                showSearchWarning(function () {
                    searchQuery = "";
                    showAddColumnModal(function (colName) { doSaveColumnAddition(colName); });
                });
                return;
            }
            showAddColumnModal(function (colName) { doSaveColumnAddition(colName); });
        });

        // Remove column (× button in header) — auto-saves immediately
        $table.off("click.wl", ".wl-col-remove-btn").on("click.wl", ".wl-col-remove-btn", function (e) {
            e.stopPropagation();
            var colName = $(this).data("col");
            if (!colName) { return; }
            if (searchQuery) {
                showSearchWarning(function () {
                    searchQuery = "";
                    doColumnRemoveWithGateCheck(colName);
                });
                return;
            }
            doColumnRemoveWithGateCheck(colName);
        });

        // Save
        $table.off("click.wl", "#btn-save").on("click.wl", "#btn-save", function () {
            doSave();
        });

        // Discard
        $table.off("click.wl", "#btn-discard").on("click.wl", "#btn-discard", function () {
            currentHeaders = originalHeaders.slice();
            currentRows = originalRows.map(function (r) { return $.extend({}, r); });
            searchQuery = "";
            $searchInput.val("");
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

        // Sync button state with selections that persist across pages
        updateRemoveSelectedBtn();

        // Drag-and-drop reordering
        bindDragEvents();

        // Column resize handles
        bindResizeEvents();
    }

    // ══════════════════════════════════════════════════════════════════
    // Column resize
    // ══════════════════════════════════════════════════════════════════

    function bindResizeEvents() {
        $table.off("mousedown.wlresize", ".wl-col-resize-handle")
              .on("mousedown.wlresize", ".wl-col-resize-handle", function (e) {
            e.preventDefault();
            e.stopPropagation();
            var $th = $(this).closest("th");
            var header = $th.data("col");
            resizeState = {
                $th: $th,
                header: header,
                startX: e.pageX,
                startWidth: $th.outerWidth()
            };
            $("body").addClass("wl-resizing");
        });

        $(document).off("mousemove.wlresize").on("mousemove.wlresize", function (e) {
            if (!resizeState) { return; }
            var newWidth = Math.min(300, Math.max(50, resizeState.startWidth + (e.pageX - resizeState.startX)));
            resizeState.$th.css({ width: newWidth, minWidth: newWidth });
            colWidths[resizeState.header] = newWidth;
        });

        $(document).off("mouseup.wlresize").on("mouseup.wlresize", function () {
            if (!resizeState) { return; }
            resizeState = null;
            $("body").removeClass("wl-resizing");
            // Persist widths for current CSV to memory + server (debounced)
            if (selectedCsv && Object.keys(colWidths).length) {
                allColWidths[selectedCsv] = $.extend({}, colWidths);
                clearTimeout(colWidthSaveTimer);
                colWidthSaveTimer = setTimeout(function () {
                    restPost({
                        action: "save_col_widths",
                        csv_file: selectedCsv,
                        app_context: selectedApp,
                        col_widths: colWidths
                    });
                }, 300);
            }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Drag-and-drop reordering
    // ══════════════════════════════════════════════════════════════════

    function bindDragEvents() {
        // Clean up any stale native DnD handlers from previous builds
        $table.off("dragstart.wl dragover.wl drop.wl dragend.wl dragleave.wl");
        $table.off("dragover.wlrow drop.wlrow dragover.wlcol drop.wlcol");

        // Prevent native DnD from interfering (browser may still try on text/images)
        $table.off("dragstart.wlblock")
              .on("dragstart.wlblock", ".wl-row-drag-handle, .wl-col-drag-handle", function (e) {
            e.preventDefault();
        });

        // ── Row drag (mouse-event based) ─────────────────────────
        $table.off("mousedown.wldrag", ".wl-row-drag-handle")
              .on("mousedown.wldrag", ".wl-row-drag-handle", function (e) {
            if (searchQuery) { return; }
            if (e.which !== 1) { return; }
            var fromIdx = $(this).data("idx");
            if (csvLocked) { return; }
            e.preventDefault();
            var $tr = $(this).closest("tr");
            var rowH = $tr.outerHeight();
            var startY = e.clientY;
            var startRect = $tr[0].getBoundingClientRect();

            // Snapshot all row positions before any transforms
            var rowItems = [];
            $table.find("tbody tr").each(function () {
                var rect = this.getBoundingClientRect();
                rowItems.push({
                    el: this,
                    idx: $(this).data("idx"),
                    midY: rect.top + rect.height / 2
                });
            });

            var started = false;

            function onMove(ev) {
                var deltaY = ev.clientY - startY;

                // Deadzone: don't start drag until 4px of movement
                if (!started) {
                    if (Math.abs(deltaY) < 4) { return; }
                    started = true;
                    $tr.addClass("wl-dragging");
                    $("body").addClass("wl-dragging-active");
                    dragState = { type: "row", fromIdx: fromIdx };
                }

                // Move dragged row with cursor (no CSS transition — class sets transition:none)
                $tr[0].style.transform = "translateY(" + deltaY + "px)";

                // Calculate dragged row's visual center
                var dragCenterY = startRect.top + startRect.height / 2 + deltaY;

                // Shift other rows to create a gap at the drop position
                rowItems.forEach(function (item) {
                    if (item.idx === fromIdx) { return; }
                    var shift = 0;
                    if (item.idx > fromIdx) {
                        // Row originally below: shift UP when dragged center passes it
                        if (dragCenterY > item.midY) { shift = -rowH; }
                    } else {
                        // Row originally above: shift DOWN when dragged center passes it
                        if (dragCenterY < item.midY) { shift = rowH; }
                    }
                    item.el.style.transform = shift ? "translateY(" + shift + "px)" : "";
                });
            }

            function onUp(ev) {
                $(document).off("mousemove.wldrag mouseup.wldrag");

                if (!started) { return; } // was just a click, not a drag

                // Calculate final position from which rows shifted
                var deltaY = ev.clientY - startY;
                var dragCenterY = startRect.top + startRect.height / 2 + deltaY;
                var shiftedUp = 0, shiftedDown = 0;
                rowItems.forEach(function (item) {
                    if (item.idx === fromIdx) { return; }
                    if (item.idx > fromIdx && dragCenterY > item.midY) { shiftedUp++; }
                    if (item.idx < fromIdx && dragCenterY < item.midY) { shiftedDown++; }
                });
                var toIdx = fromIdx + shiftedUp - shiftedDown;

                // Clear all transforms
                $table.find("tbody tr").each(function () {
                    this.style.transform = "";
                });
                $tr.removeClass("wl-dragging");
                $("body").removeClass("wl-dragging-active");
                dragState = null;

                if (fromIdx !== toIdx) {
                    doRowReorder(fromIdx, toIdx);
                }
            }

            $(document).on("mousemove.wldrag", onMove);
            $(document).on("mouseup.wldrag", onUp);
        });

        // ── Column drag (mouse-event based) ──────────────────────
        $table.off("mousedown.wldrag", ".wl-col-drag-handle")
              .on("mousedown.wldrag", ".wl-col-drag-handle", function (e) {
            if (searchQuery) { return; }
            if (e.which !== 1) { return; }
            var $handle = $(this);
            var $th = $handle.closest("th.wl-col-draggable");
            var fromCol = $th.data("col");
            if (csvLocked) { return; }
            e.preventDefault();
            e.stopPropagation(); // prevent rename click handler
            var colW = $th.outerWidth();
            var startX = e.clientX;

            var visibleHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var fromVisIdx = visibleHeaders.indexOf(fromCol);

            // Snapshot all draggable column positions
            var colItems = [];
            $table.find("thead th.wl-col-draggable").each(function (i) {
                var rect = this.getBoundingClientRect();
                colItems.push({
                    el: this,
                    visIdx: i,
                    col: $(this).data("col"),
                    midX: rect.left + rect.width / 2
                });
            });

            var started = false;
            var nthFrom = fromVisIdx + 3; // nth-child offset: 1-indexed + checkbox + rownum

            function onMove(ev) {
                var deltaX = ev.clientX - startX;

                if (!started) {
                    if (Math.abs(deltaX) < 4) { return; }
                    started = true;
                    $th.addClass("wl-dragging");
                    $("body").addClass("wl-dragging-active");
                    dragState = { type: "column", fromCol: fromCol };
                    // Remove CSS transition from dragged column cells (follow cursor instantly)
                    $table.find("thead th:nth-child(" + nthFrom + "), tbody td:nth-child(" + nthFrom + ")")
                          .css("transition", "none");
                }

                // Move dragged column cells with cursor
                var transformDragged = "translateX(" + deltaX + "px)";
                $table.find("thead th:nth-child(" + nthFrom + ")").css("transform", transformDragged);
                $table.find("tbody td:nth-child(" + nthFrom + ")").css("transform", transformDragged);

                // Calculate dragged column's visual center
                var dragCenterX = colItems[fromVisIdx].midX + deltaX;

                // Shift other columns
                colItems.forEach(function (item) {
                    if (item.visIdx === fromVisIdx) { return; }
                    var shift = 0;
                    if (item.visIdx > fromVisIdx) {
                        if (dragCenterX > item.midX) { shift = -colW; }
                    } else {
                        if (dragCenterX < item.midX) { shift = colW; }
                    }
                    var transformVal = shift ? "translateX(" + shift + "px)" : "";
                    var nthCol = item.visIdx + 3;
                    $table.find("thead th:nth-child(" + nthCol + ")").css("transform", transformVal);
                    $table.find("tbody td:nth-child(" + nthCol + ")").css("transform", transformVal);
                });
            }

            function onUp(ev) {
                $(document).off("mousemove.wldrag mouseup.wldrag");

                if (!started) { return; }

                // Calculate final position
                var deltaX = ev.clientX - startX;
                var dragCenterX = colItems[fromVisIdx].midX + deltaX;
                var shiftedLeft = 0, shiftedRight = 0;
                colItems.forEach(function (item) {
                    if (item.visIdx === fromVisIdx) { return; }
                    if (item.visIdx > fromVisIdx && dragCenterX > item.midX) { shiftedLeft++; }
                    if (item.visIdx < fromVisIdx && dragCenterX < item.midX) { shiftedRight++; }
                });
                var newVisIdx = fromVisIdx + shiftedLeft - shiftedRight;

                // Clear all transforms and inline transition overrides
                $table.find("thead th, tbody td").css({ transform: "", transition: "" });
                $th.removeClass("wl-dragging");
                $("body").removeClass("wl-dragging-active");
                dragState = null;

                if (newVisIdx !== fromVisIdx) {
                    var toCol = visibleHeaders[newVisIdx];
                    if (toCol && fromCol !== toCol) {
                        doColumnReorder(fromCol, toCol);
                    }
                }
            }

            $(document).on("mousemove.wldrag", onMove);
            $(document).on("mouseup.wldrag", onUp);
        });

        // ── Click to rename column header ────────────────────────────
        $table.off("click.wlrename", ".wl-col-header-text")
              .on("click.wlrename", ".wl-col-header-text", function (e) {
            e.stopPropagation();
            if (csvLocked) { return; }
            if (searchQuery) { showMsg("Clear search before renaming columns", "warning"); return; }
            var $span = $(this);
            var $th = $span.closest("th");
            var oldName = $th.data("col");

            // Record original th width as the minimum — column can grow but not shrink
            var origWidth = $th.outerWidth();
            $th.css({ minWidth: origWidth });

            // Hide drag handle and remove button to free space for input
            $th.find(".wl-col-drag-handle, .wl-col-remove-btn").hide();

            var $input = $('<input type="text" class="wl-col-rename-input">')
                .val(oldName)
                .attr("maxlength", 64);
            $span.replaceWith($input);
            $input.focus().select();

            // Hidden sizer span to measure text width as user types
            var $sizer = $('<span class="wl-col-rename-sizer"></span>')
                .css({ position: "absolute", visibility: "hidden", whiteSpace: "pre",
                       font: $input.css("font"), padding: $input.css("padding") })
                .appendTo($th);

            function autoGrow() {
                $sizer.text($input.val() || " ");
                // Add padding for the input border/padding + some breathing room
                var needed = $sizer.outerWidth() + 30;
                var newWidth = Math.max(origWidth, needed);
                $th.css({ width: newWidth, minWidth: newWidth });
            }
            $input.on("input.wlgrow", autoGrow);

            var committed = false;
            function finish(newName) {
                if (committed) return;
                committed = true;
                $sizer.remove();
                // Validate before replacing the input — revert to oldName on failure
                var validationError = null;
                if (newName && newName !== oldName) {
                    if (/\s/.test(newName)) { validationError = "Column name cannot contain spaces. Use underscores instead."; }
                    else if (newName.charAt(0) === "_") { validationError = "Column name cannot start with _"; }
                    else if (!/^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-.()\/:&#@+]+$/.test(newName)) { validationError = "Column name must contain at least one letter or number. Only letters, numbers, and _-.()/:#@&+ are allowed."; }
                    else if (currentHeaders.indexOf(newName) !== -1) { validationError = "Column '" + _.escape(newName) + "' already exists"; }
                }
                if (validationError) { newName = null; } // revert to oldName
                var displayName = newName || oldName;
                var $newSpan = $('<span class="wl-col-header-text">').text(displayName);
                $input.replaceWith($newSpan);
                // Restore drag handle and remove button
                $th.find(".wl-col-drag-handle, .wl-col-remove-btn").show();
                // Reset th width — let table layout recalculate
                $th.css({ width: "", minWidth: "" });
                if (validationError) { showMsg(validationError, "error"); return; }
                if (newName && newName !== oldName) {
                    doSaveColumnRename(oldName, newName);
                }
            }

            $input.on("keydown", function (ev) {
                if (ev.key === "Enter") { ev.preventDefault(); finish($.trim($input.val())); }
                if (ev.key === "Escape") { finish(null); }
            });
            $input.on("blur", function () { finish($.trim($input.val())); });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Reorder auto-save helpers
    // ══════════════════════════════════════════════════════════════════

    function doRowReorder(fromIdx, toIdx) {
        if (saving) { return; }
        syncInputs();

        // Discard any pending cell edits — reorder must be a pure positional save
        currentRows = originalRows.map(function (r) { return $.extend({}, r); });
        pendingBulkEditCount = 0;

        var fromPos = fromIdx + 1;
        var toPos = toIdx + 1;

        var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });

        var movedRow = currentRows.splice(fromIdx, 1)[0];
        currentRows.splice(toIdx, 0, movedRow);

        refreshTable();
        showMsg("Reordering row&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Row reorder",
            removal_reasons: [],
            row_reorder:     { from_position: fromPos, to_position: toPos },
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentRows = prevRows;
                originalRows = prevOriginal;
                refreshTable();
                return;
            }
            showMsg("Row moved from #" + fromPos + " to #" + toPos + ". Changes saved", "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            if (data.file_mtime) { loadedMtime = data.file_mtime; }
            refreshTable();
            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after row reorder.");
            currentRows = prevRows;
            originalRows = prevOriginal;
            refreshTable();
        });
    }

    function doColumnReorder(fromCol, toCol) {
        if (saving) { return; }
        syncInputs();

        // Discard any pending cell edits — reorder must be a pure positional save
        currentRows = originalRows.map(function (r) { return $.extend({}, r); });
        currentHeaders = originalHeaders.slice();
        pendingBulkEditCount = 0;

        var visibleHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var fromVisIdx = visibleHeaders.indexOf(fromCol);
        var toVisIdx   = visibleHeaders.indexOf(toCol);
        if (fromVisIdx === -1 || toVisIdx === -1) { return; }

        var fromPos = fromVisIdx + 1;
        var toPos   = toVisIdx + 1;

        var prevHeaders = currentHeaders.slice();
        var prevOrigHeaders = originalHeaders.slice();

        var fromActualIdx = currentHeaders.indexOf(fromCol);
        currentHeaders.splice(fromActualIdx, 1);
        var newToIdx = currentHeaders.indexOf(toCol);
        if (fromVisIdx < toVisIdx) {
            currentHeaders.splice(newToIdx + 1, 0, fromCol);
        } else {
            currentHeaders.splice(newToIdx, 0, fromCol);
        }

        refreshTable();
        showMsg("Reordering column&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Column reorder",
            removal_reasons: [],
            column_reorder:  { column: fromCol, from_position: fromPos, to_position: toPos },
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentHeaders = prevHeaders;
                originalHeaders = prevOrigHeaders;
                refreshTable();
                return;
            }
            showMsg("Column '" + _.escape(fromCol) + "' moved from #" + fromPos + " to #" + toPos + ". Changes saved", "success");
            originalHeaders = currentHeaders.slice();
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            if (data.file_mtime) { loadedMtime = data.file_mtime; }
            refreshTable();
            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after column reorder.");
            currentHeaders = prevHeaders;
            originalHeaders = prevOrigHeaders;
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Column rename auto-save
    // ══════════════════════════════════════════════════════════════════
    function doSaveColumnRename(oldName, newName) {
        if (saving) { return; }
        syncInputs();

        var snapHeaders = currentHeaders.slice();
        var snapRows = currentRows.map(function (r) { return $.extend({}, r); });

        var idx = currentHeaders.indexOf(oldName);
        if (idx === -1) { return; }
        currentHeaders[idx] = newName;

        currentRows.forEach(function (row) {
            row[newName] = row.hasOwnProperty(oldName) ? row[oldName] : "";
            delete row[oldName];
        });

        refreshTable();
        showMsg("Renaming column and saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Column rename",
            removal_reasons: [],
            column_renames:  [{ old_name: oldName, new_name: newName }],
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                currentHeaders = snapHeaders;
                currentRows = snapRows;
                refreshTable();
                showMsg(_.escape(data.error), "error");
                return;
            }
            loadedMtime = data.file_mtime || loadedMtime;
            originalHeaders = currentHeaders.slice();
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            if (colWidths[oldName]) {
                colWidths[newName] = colWidths[oldName];
                delete colWidths[oldName];
                allColWidths[selectedCsv] = $.extend({}, colWidths);
            }
            showMsg("Changes saved. Column renamed: '" + _.escape(oldName) + "' \u2192 '" + _.escape(newName) + "'", "success");
            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            currentHeaders = snapHeaders;
            currentRows = snapRows;
            refreshTable();
            handleSaveError(xhr, "Column rename failed");
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Search warning modal (shown when Add Row is clicked while searching)
    // ══════════════════════════════════════════════════════════════════
    function showSearchWarning(onConfirm) {
        // Remove existing modal if any
        $(".wl-modal-overlay").remove();

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Clear Search?</div>' +
                    '<div class="wl-modal-body">' +
                        'This action will clear your search results and show all rows.' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button class="btn btn-primary" id="wl-modal-ok">OK</button> ' +
                        '<button class="btn" id="wl-modal-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("click", "#wl-modal-ok", function () {
            $modal.remove();
            if (onConfirm) { onConfirm(); }
        });
        $modal.on("click", "#wl-modal-cancel", function () {
            $modal.remove();
        });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) {
                $modal.remove();
            }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Add Column modal & helper
    // ══════════════════════════════════════════════════════════════════

    function showAddColumnModal(onConfirm) {
        $(".wl-modal-overlay").remove();

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Add Column</div>' +
                    '<div class="wl-modal-body">' +
                        '<label class="wl-dp-label">Column name:</label>' +
                        '<input type="text" id="wl-new-col-name" class="wl-input" ' +
                            'placeholder="Enter column name" style="width:100%" maxlength="64" />' +
                        '<div id="wl-col-error" style="color:var(--wl-err-text);font-size:12px;margin-top:4px;display:none"></div>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<span class="btn btn-primary" id="wl-col-ok">Add</span> ' +
                        '<span class="btn" id="wl-col-cancel">Cancel</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        function validateAndSubmit() {
            var name = $modal.find("#wl-new-col-name").val().trim();
            var $err = $modal.find("#wl-col-error");
            var $inp = $modal.find("#wl-new-col-name");
            $err.hide();
            $inp.removeClass("wl-input-error");

            if (!name) {
                $inp.addClass("wl-input-error");
                $err.text("Column name cannot be empty.").show();
                return;
            }
            if (/\s/.test(name)) {
                $inp.addClass("wl-input-error");
                $err.text("Column name cannot contain spaces. Use underscores instead (e.g. 'src_ip').").show();
                return;
            }
            if (name.charAt(0) === "_") {
                $inp.addClass("wl-input-error");
                $err.text('Column names starting with "_" are reserved for internal use.').show();
                return;
            }
            if (!/^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-.()\/:&#@+]+$/.test(name)) {
                $inp.addClass("wl-input-error");
                $err.text("Column name must contain at least one letter or number. Only letters, numbers, and _-.()/:#@&+ are allowed.").show();
                return;
            }
            if (currentHeaders.indexOf(name) !== -1) {
                $inp.addClass("wl-input-error");
                $err.text('A column named "' + _.escape(name) + '" already exists.').show();
                return;
            }
            $modal.remove();
            if (onConfirm) { onConfirm(name); }
        }

        $modal.on("click", "#wl-col-ok", validateAndSubmit);
        $modal.on("click", "#wl-col-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
        $modal.on("keydown", "#wl-new-col-name", function (e) {
            if (e.which === 13) { e.preventDefault(); validateAndSubmit(); }
        });
        $modal.on("input", "#wl-new-col-name", function () {
            $(this).removeClass("wl-input-error");
            $modal.find("#wl-col-error").hide();
        });

        setTimeout(function () { $modal.find("#wl-new-col-name").focus(); }, 100);
    }

    function doSaveColumnAddition(colName) {
        syncInputs();

        // Snapshot state for undo
        var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });
        var prevHeaders = currentHeaders.slice();
        var prevOrigHeaders = originalHeaders.slice();

        // Insert before metadata columns (those starting with "_")
        var insertIdx = currentHeaders.length;
        for (var i = 0; i < currentHeaders.length; i++) {
            if (currentHeaders[i].charAt(0) === "_") { insertIdx = i; break; }
        }
        currentHeaders.splice(insertIdx, 0, colName);

        // Add empty value for the new column to all rows
        currentRows.forEach(function (row) { row[colName] = ""; });

        refreshTable();
        showMsg("Adding column and saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Column addition",
            removal_reasons: [],
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentHeaders = prevHeaders;
                originalHeaders = prevOrigHeaders;
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            showMsg('Column <strong>' + _.escape(colName) + '</strong> added and saved.', "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            if (data.file_mtime) { loadedMtime = data.file_mtime; }

            if (data.diff && data.diff.text_diff && data.diff.text_diff.length) {
                renderDiff(data.diff);
            }

            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after column addition.");
            currentHeaders = prevHeaders;
            originalHeaders = prevOrigHeaders;
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Remove Row modal (shared by single-row Remove and bulk Remove Selected)
    // ══════════════════════════════════════════════════════════════════

    function showRemoveRowModal(title, bodyHtml, onConfirm, opts) {
        $(".wl-modal-overlay").remove();

        // Allow callers to override labels for non-removal contexts
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
                        '<span class="btn ' + confirmClass + '" id="wl-rmrow-ok" style="opacity:0.5;pointer-events:none">' + _.escape(confirmText) + '</span> ' +
                        '<span class="btn" id="wl-rmrow-cancel">Cancel</span>' +
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

    // ══════════════════════════════════════════════════════════════════
    // ══════════════════════════════════════════════════════════════════
    // Approval workflow — gate checks and submission
    // ══════════════════════════════════════════════════════════════════

    function doColumnRemoveWithGateCheck(colName) {
        if (csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }
        restPost({
            action: "check_approval_gate",
            gate_action: "column_removal",
            csv_file: selectedCsv,
            app_context: selectedApp,
            column_name: colName
        }).done(function (gateData) {
            if (gateData.requires_approval) {
                showRemoveColumnModal(colName, function (reason) {
                    submitApprovalRequest("column_removal", reason, null, colName);
                });
            } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                showMsg(formatDailyLimitMsg(gateData.daily_limit), "error"
                );
            } else {
                showRemoveColumnModal(colName, function (reason) {
                    doSaveColumnRemoval(colName, reason);
                });
            }
        }).fail(function () {
            // Fallback to normal flow if gate check fails
            showRemoveColumnModal(colName, function (reason) {
                doSaveColumnRemoval(colName, reason);
            });
        });
    }

    function submitApprovalRequest(actionType, reason, rowIndices, colName) {
        syncInputs();

        var description = "";
        var highlight = {};
        var originalPayload = {};

        if (actionType === "bulk_row_removal") {
            description = reason || "Remove " + rowIndices.length + " selected rows";
            var visHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var rowKeys = rowIndices.map(function (idx) {
                return visHeaders.map(function (h) { return currentRows[idx][h] || ""; });
            });
            highlight = { type: "rows", row_keys: rowKeys, headers: visHeaders };

            var removedEntries = [];
            rowIndices.sort(function (a, b) { return a - b; });
            rowIndices.forEach(function (idx) {
                removedEntries.push({
                    row_number: idx + 1,
                    row: $.extend({}, currentRows[idx])
                });
            });
            var rowsCopy = currentRows.map(function (r) { return $.extend({}, r); });
            for (var i = rowIndices.length - 1; i >= 0; i--) {
                rowsCopy.splice(rowIndices[i], 1);
            }
            originalPayload = {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: rowsCopy,
                comment: "Bulk removal (" + rowIndices.length + " rows) - approved",
                removal_reasons: [],
                bulk_removal: removedEntries.map(function (e) {
                    return { row_number: e.row_number, row: e.row, reason: reason };
                })
            };
        } else if (actionType === "bulk_row_addition") {
            // The new rows are at the end of currentRows (beyond originalRows.length)
            var addedCount = Math.max(0, currentRows.length - originalRows.length);
            var visHeadersAdd = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var addedRowKeys = [];
            for (var ai = originalRows.length; ai < currentRows.length; ai++) {
                addedRowKeys.push(visHeadersAdd.map(function (h) { return currentRows[ai][h] || ""; }));
            }
            highlight = { type: "rows", row_keys: addedRowKeys, headers: visHeadersAdd };
            description = reason || "Add " + addedCount + " new rows";
            originalPayload = {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: currentRows.map(function (r) { return $.extend({}, r); }),
                comment: "Row addition (" + addedCount + " rows)",
                row_add_reason: reason || "",
                removal_reasons: []
            };
        } else if (actionType === "column_removal") {
            description = reason || "Remove column '" + colName + "'";
            highlight = { type: "column", column_name: colName };

            var headersCopy = currentHeaders.slice();
            var cidx = headersCopy.indexOf(colName);
            if (cidx !== -1) { headersCopy.splice(cidx, 1); }
            var rowsCopyCol = currentRows.map(function (r) {
                var copy = $.extend({}, r);
                delete copy[colName];
                return copy;
            });
            originalPayload = {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: headersCopy,
                rows: rowsCopyCol,
                comment: reason || "Column removal - approved",
                removal_reasons: [],
                column_removal_reasons: [{ column: colName, reason: reason }]
            };
        }

        showMsg("Submitting approval request&hellip;", "info");

        // Compute selected_count for daily limit validation
        var approvalCount = 1;
        if (actionType === "bulk_row_removal" && rowIndices) {
            approvalCount = rowIndices.length;
        } else if (actionType === "bulk_row_addition") {
            approvalCount = Math.max(0, currentRows.length - originalRows.length);
        } else if (actionType === "column_removal") {
            approvalCount = 1;
        }

        restPost({
            action: "submit_approval",
            approval_action_type: actionType,
            csv_file: selectedCsv,
            app_context: selectedApp,
            detection_rule: selectedRule || "",
            description: description,
            comment: reason || "",
            original_payload: originalPayload,
            expected_mtime: loadedMtime,
            pending_highlight: highlight,
            selected_count: approvalCount
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Your request has been submitted for approval. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            // Reload to show orange highlighting
            loadCsv(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit approval request.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function submitImportReplaceApproval(fileName, importHeaders, importRows) {
        var description = "Import Replace from " + fileName + " (" + importRows.length + " rows)";

        showMsg("Submitting import approval request&hellip;", "info");

        restPost({
            action: "submit_approval",
            approval_action_type: "csv_import_replace",
            csv_file: selectedCsv,
            app_context: selectedApp,
            detection_rule: selectedRule || "",
            description: description,
            original_payload: {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: importHeaders,
                rows: importRows,
                comment: "CSV import replace from " + fileName + " - approved",
                removal_reasons: []
            },
            expected_mtime: loadedMtime,
            pending_highlight: { type: "table" }
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Import Replace requires approval. Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            // Reload to show orange highlighting
            loadCsv(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit import approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function submitBulkEditApproval(col, val, rowIndices, changedCount, reason) {
        syncInputs();
        var visHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var rowKeys = rowIndices.map(function (idx) {
            return visHeaders.map(function (h) { return currentRows[idx][h] || ""; });
        });

        var displayVal = val.length > 100 ? val.substring(0, 100) + "..." : val;
        var description = "Bulk edit " + changedCount + " rows — set '" + col + "' to '" + displayVal + "'";

        showMsg("Submitting bulk edit approval request&hellip;", "info");

        restPost({
            action: "submit_approval",
            approval_action_type: "bulk_row_edit",
            csv_file: selectedCsv,
            app_context: selectedApp,
            detection_rule: selectedRule || "",
            description: description,
            original_payload: {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: currentRows,
                comment: reason || ("Bulk edit (" + changedCount + " rows) - approved"),
                bulk_edit_column: col,
                bulk_edit_value: val,
                _bulk_edit_count: changedCount
            },
            expected_mtime: loadedMtime,
            pending_highlight: { type: "rows", row_keys: rowKeys, headers: visHeaders },
            selected_count: changedCount
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Bulk edit requires approval. Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            loadCsv(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit bulk edit approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function submitInlineMultiEditApproval(changedCount, reason) {
        syncInputs();
        var autoDesc = "Inline edit of " + changedCount + " rows in " +
            (selectedCsv || "unknown CSV");

        showMsg("Submitting edit approval request&hellip;", "info");

        restPost({
            action: "submit_approval",
            approval_action_type: "bulk_row_edit",
            csv_file: selectedCsv,
            app_context: selectedApp,
            detection_rule: selectedRule || "",
            description: reason || autoDesc,
            comment: reason,
            original_payload: {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: currentRows,
                comment: reason || ("Inline multi-edit (" + changedCount + " rows) - approved"),
                _bulk_edit_count: changedCount
            },
            expected_mtime: loadedMtime,
            selected_count: changedCount
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Edit requires approval. Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            // Revert local edits since they're pending approval
            loadCsv(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit edit approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function buildLockedState() {
        csvLocked = pendingApprovals.length > 0;
    }

    /**
     * Re-apply amber CSS classes to rows/columns/table that triggered
     * the pending approval.  Safe to call after every refreshTable().
     */
    function applyPendingCssHighlighting() {
        if (!pendingApprovals.length) { return; }
        pendingApprovals.forEach(function (pa) {
            var hl = pa.pending_highlight || {};
            if (hl.type === "rows" && hl.row_keys) {
                var hlH = hl.headers || currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
                // Use counter (not set) to handle duplicate rows correctly
                var keyCounts = {};
                hl.row_keys.forEach(function (rk) {
                    var k = JSON.stringify(rk);
                    keyCounts[k] = (keyCounts[k] || 0) + 1;
                });
                $table.find("tbody tr").each(function () {
                    var idx = $(this).data("idx");
                    if (idx !== undefined && currentRows[idx]) {
                        var key = hlH.map(function (h) { return currentRows[idx][h] || ""; });
                        var k = JSON.stringify(key);
                        if (keyCounts[k] > 0) {
                            $(this).addClass("wl-pending-approval");
                            keyCounts[k]--;
                        }
                    }
                });
            } else if (hl.type === "column" && hl.column_name) {
                $table.find("th[data-col]").filter(function () {
                    return $(this).data("col") === hl.column_name;
                }).addClass("wl-pending-approval-header");
            } else if (hl.type === "table") {
                $table.find(".wl-table").addClass("wl-pending-approval-table");
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
     * Compute which currentRows indices are affected by a pending approval.
     * Uses counter-based matching for correct duplicate handling.
     */
    function getPendingRowIndices(pa) {
        var hl = pa.pending_highlight || {};
        if (hl.type !== "rows" || !hl.row_keys) return [];
        var hlH = hl.headers || currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var keyCounts = {};
        hl.row_keys.forEach(function (rk) {
            var k = JSON.stringify(rk);
            keyCounts[k] = (keyCounts[k] || 0) + 1;
        });
        var indices = [];
        for (var i = 0; i < currentRows.length; i++) {
            var key = hlH.map(function (h) { return currentRows[i][h] || ""; });
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
        if (!pendingApprovals.length) { return; }

        applyPendingCssHighlighting();

        // Lock all controls — entire CSV is locked
        $table.find("#btn-save").addClass("wl-btn-locked").prop("disabled", true);
        $table.find("#btn-add-row").addClass("wl-btn-locked").prop("disabled", true);
        $table.find("#btn-add-col").addClass("wl-btn-locked").prop("disabled", true);
        $table.find("#btn-remove-selected").addClass("wl-btn-locked").prop("disabled", true);
        $table.find(".wl-import-btn").addClass("wl-btn-locked");
        $table.find("#btn-import").prop("disabled", true);
        $revertSelect.prop("disabled", true);

        // Show lock banner
        var descriptions = pendingApprovals.map(function (pa) {
            return '<strong>' + _.escape(pa.action_type.replace(/_/g, " ")) + '</strong> by ' +
                   _.escape(pa.analyst) + ' (' + _.escape(pa.description) + ')';
        });
        showMsg(
            "This CSV is locked &mdash; " +
            (pendingApprovals.length > 1 ? "pending approvals" : "a pending approval") +
            " must be resolved before changes can be made. " +
            descriptions.join("; ") + ".",
            "warning"
        );

        // Approve / Reject / Cancel action bar
        // Shown for admins (approve/reject others, cancel own) and
        // non-admin analysts who own a pending request (cancel only)
        $("#wl-approval-actions").remove();
        getCurrentUser();
        var ownsAnyRequest = currentUser && pendingApprovals.some(function (pa) {
            return pa.analyst === currentUser;
        });
        if (isAdmin || ownsAnyRequest) {
            var barHtml = '<div id="wl-approval-actions" class="wl-approval-bar">';
            pendingApprovals.forEach(function (pa, paIdx) {
                var isSelfRequest = currentUser && pa.analyst === currentUser;
                // Non-admin users only see their own requests
                if (!isAdmin && !isSelfRequest) { return; }
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
            $table.before(barHtml);
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
            showApproveConfirmModal(requestId);
        });

        // ── Reject ───────────────────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-reject-btn")
            .on("click.wl", ".wl-reject-btn", function () {
            var requestId = $(this).data("id");
            showRejectReasonModal(requestId);
        });

        // ── Show Requested Rows filter ──────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-filter-requested")
            .on("click.wl", ".wl-filter-requested", function () {
            var idx = $(this).data("idx");
            var pa = pendingApprovals[idx];
            if (!pa) return;

            if (pendingFilterActive) {
                // Remove filter — show all rows
                pendingFilterActive = false;
                pendingFilterIndices = null;
                additionPreviewData = null;
                $("#wl-addition-preview").remove();
                $(this).text("Show Requested Rows");
                currentPage = 0;
                refreshTable();
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
                    showMsg("No matching rows found in current CSV.", "info");
                    return;
                }
                pendingFilterActive = true;
                pendingFilterIndices = matchedIndices;
                $(this).text("Show All Rows");
                currentPage = 0;
                refreshTable();
                applyPendingCssHighlighting();
            }
        });

        // ── Cancel own request ──────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-cancel-request-btn")
            .on("click.wl", ".wl-cancel-request-btn", function () {
            var requestId = $(this).data("id");
            showCancelRequestModal(requestId);
        });
    }

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
                        '<span class="btn" id="wl-inline-cancel-ok" ' +
                            'style="background:#f39c12;color:#fff;opacity:0.5;pointer-events:none">Cancel Request</span> ' +
                        '<span class="btn" id="wl-inline-cancel-dismiss">Close</span>' +
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
                    loadCsv(selectedCsv, selectedApp);
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
            showMsg("No row details available for this request.", "info");
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
            $table.before(html);
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
                        '<span class="btn btn-success" id="wl-approve-ok">Approve</span> ' +
                        '<span class="btn" id="wl-approve-cancel">Cancel</span>' +
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
                    loadCsv(selectedCsv, selectedApp);
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
                        '<span class="btn btn-danger" id="wl-inline-reject-ok" ' +
                            'style="opacity:0.5;pointer-events:none">Reject</span> ' +
                        '<span class="btn" id="wl-inline-reject-cancel">Cancel</span>' +
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
                    loadCsv(selectedCsv, selectedApp);
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

    // Remove Column modal & helper
    // ══════════════════════════════════════════════════════════════════

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
                        '<span class="btn btn-danger" id="wl-rmcol-ok" style="opacity:0.5;pointer-events:none">Remove</span> ' +
                        '<span class="btn" id="wl-rmcol-cancel">Cancel</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        // Enable Remove button only when reason is non-empty
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
            $modal.remove();
            if (onConfirm) { onConfirm(reason); }
        });
        $modal.on("click", "#wl-rmcol-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
    }

    function doSaveColumnRemoval(colName, reason) {
        syncInputs();

        // Prevent removing the last visible column
        var visibleCount = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; }).length;
        if (visibleCount <= 1) {
            showMsg("Cannot remove the last column.", "error");
            return;
        }

        // Snapshot state for undo
        var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });
        var prevHeaders = currentHeaders.slice();
        var prevOrigHeaders = originalHeaders.slice();

        // Remove from headers
        var idx = currentHeaders.indexOf(colName);
        if (idx !== -1) { currentHeaders.splice(idx, 1); }

        // Remove from all rows
        currentRows.forEach(function (row) { delete row[colName]; });

        refreshTable();
        showMsg("Removing column and saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         reason || "Column removal",
            removal_reasons: [],
            column_removal_reasons: [{ column: colName, reason: reason }],
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentHeaders = prevHeaders;
                originalHeaders = prevOrigHeaders;
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var msg = 'Column <strong>' + _.escape(colName) + '</strong> removed and saved.';
            if (diffInfo.edited_count > 0) {
                msg += " " + diffInfo.edited_count + " row(s) also edited.";
            }
            showMsg(msg, "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            if (data.file_mtime) { loadedMtime = data.file_mtime; }

            // Show undo bar for column removal
            showUndoBar(null, prevRows, prevOriginal, colName, prevHeaders, prevOrigHeaders);
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after column removal.");
            currentHeaders = prevHeaders;
            originalHeaders = prevOrigHeaders;
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Undo removal (10-second window)
    // ══════════════════════════════════════════════════════════════════

    function showUndoBar(removedRow, prevRows, prevOriginal, removedColName, prevHeaders, prevOrigHeaders) {
        clearUndo();

        var desc;
        if (removedColName) {
            desc = 'Column removed: <strong>' + _.escape(removedColName) + '</strong>';
        } else {
            var rowDesc = [];
            currentHeaders.forEach(function (h) {
                if (h.charAt(0) !== "_" && removedRow[h]) {
                    rowDesc.push(removedRow[h]);
                }
            });
            var descText = rowDesc.slice(0, 3).join(", ");
            if (rowDesc.length > 3) { descText += "..."; }
            desc = 'Row removed: <strong>' + _.escape(descText) + '</strong>';
        }

        undoState = {
            prevRows: prevRows,
            prevOriginal: prevOriginal,
            prevHeaders: prevHeaders || null,
            prevOrigHeaders: prevOrigHeaders || null
        };

        var $bar = $table.find("#wl-undo-bar");
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

        // Restore headers if this was a column removal undo
        if (undoState.prevHeaders) {
            currentHeaders = undoState.prevHeaders.slice();
        }

        var wasColumnUndo = !!undoState.prevHeaders;
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
            comment:         wasColumnUndo ? "Undo column removal" : "Undo row removal",
            removal_reasons: [],
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg("Removal undone and saved.", "success");
            reloadCsvQuiet();
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to undo removal.");
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
    // External change detection (poll file mtime every 5s)
    // ══════════════════════════════════════════════════════════════════

    function startChangeMonitoring() {
        stopChangeMonitoring();
        if (!selectedCsv || !loadedMtime) { return; }
        changeCheckTimer = setInterval(checkForExternalChanges, 5000);
    }

    function stopChangeMonitoring() {
        if (changeCheckTimer) { clearInterval(changeCheckTimer); changeCheckTimer = null; }
    }

    function checkForExternalChanges() {
        if (!selectedCsv || !loadedMtime || saving) { return; }
        restGet({
            action:   "check_csv_status",
            csv_file: selectedCsv,
            app:      selectedApp || ""
        })
        .done(function (data) {
            // Lock state changed — auto-reload (no modal needed)
            var newPending = data.pending_count !== undefined ? data.pending_count : 0;
            if (newPending !== loadedPendingCount) {
                loadCsv(selectedCsv, selectedApp);
                return;
            }
            // File content changed — show conflict modal
            if (data.file_mtime && data.file_mtime !== loadedMtime) {
                stopChangeMonitoring();
                showExternalChangeModal();
            }
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(selectedCsv);
            }
        });
    }

    function hasUnsavedChanges() {
        if (currentHeaders.length !== originalHeaders.length) { return true; }
        for (var i = 0; i < currentHeaders.length; i++) {
            if (currentHeaders[i] !== originalHeaders[i]) { return true; }
        }
        if (currentRows.length !== originalRows.length) { return true; }
        for (var r = 0; r < currentRows.length; r++) {
            for (var h = 0; h < currentHeaders.length; h++) {
                var hdr = currentHeaders[h];
                if ((currentRows[r][hdr] || "") !== (originalRows[r][hdr] || "")) { return true; }
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
                        'The file <strong>' + _.escape(selectedCsv) + '</strong> has been modified ' +
                        'outside of Whitelist Manager (possibly by another analyst or application).' +
                        warning +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<span class="btn btn-primary" id="wl-extchg-reload">Reload CSV</span> ' +
                        '<span class="btn" id="wl-extchg-keep">Keep editing</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("click", "#wl-extchg-reload", function () {
            $modal.remove();
            loadCsv(selectedCsv, selectedApp);
        });
        $modal.on("click", "#wl-extchg-keep", function () {
            $modal.remove();
            // Update mtime so prompt doesn't immediately reappear
            restGet({
                action:   "check_csv_status",
                csv_file: selectedCsv,
                app:      selectedApp || ""
            })
            .done(function (data) {
                loadedMtime = data.file_mtime || loadedMtime;
                startChangeMonitoring();
            });
        });
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

        restPost({
            action: "log_event",
            event_action: "csv_exported",
            csv_file: selectedCsv,
            detection_rule: selectedRule || "",
            app_context: selectedApp,
            status: "success",
            export_file: link.download,
            row_count: currentRows.length,
            comment: ""
        });
    }

    function csvEscape(val) {
        // Neutralize formula-dangerous prefixes to prevent CSV injection
        // when the exported file is opened in Excel / LibreOffice Calc.
        if (/^[=+\-@\t\r]/.test(val)) {
            val = "'" + val;
        }
        if (val.indexOf(",") !== -1 || val.indexOf('"') !== -1 || val.indexOf("\n") !== -1) {
            return '"' + val.replace(/"/g, '""') + '"';
        }
        return val;
    }

    // ══════════════════════════════════════════════════════════════════
    // Bulk Import (upload CSV to merge)
    // ══════════════════════════════════════════════════════════════════

    var MAX_IMPORT_SIZE = 5 * 1024 * 1024; // 5 MB

    // Column names treated as expiration dates (mirrors backend EXPIRE_COLUMN_NAMES)
    var EXPIRE_COLUMN_NAMES = ["expires", "expire", "expiration", "expiration_date",
                               "expiry", "termination", "termination_date"];

    /**
     * Validate date values in the expiration column of imported CSV rows.
     * Returns an array of {row, value} for invalid entries (max 10 reported).
     * Accepted formats: "YYYY-MM-DD HH:MM UTC", "YYYY-MM-DD HH:MM", "YYYY-MM-DD UTC", "YYYY-MM-DD".
     */
    function validateExpireDates(headers, rows) {
        var expCol = null;
        for (var i = 0; i < headers.length; i++) {
            if (EXPIRE_COLUMN_NAMES.indexOf(headers[i].toLowerCase()) !== -1) {
                expCol = headers[i];
                break;
            }
        }
        if (!expCol) { return []; }

        // Regex: YYYY-MM-DD (optional: space + HH:MM) (optional: space + UTC)
        var dateRe = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])( ([01]\d|2[0-3]):[0-5]\d)?( UTC)?$/;
        var invalid = [];
        for (var r = 0; r < rows.length; r++) {
            var val = (rows[r][expCol] || "").trim();
            if (!val) { continue; } // empty = permanent, OK
            if (!dateRe.test(val)) {
                invalid.push({ row: r + 1, value: val });
                if (invalid.length >= 10) { break; }
            }
        }
        return invalid;
    }

    function logImportEvent(fileName, status, comment, importedCount, headerCount, importMode, rowsBefore) {
        restPost({
            action: "log_event",
            event_action: "csv_imported",
            csv_file: selectedCsv,
            detection_rule: selectedRule || "",
            app_context: selectedApp,
            status: status,
            export_file: fileName,
            row_count_before: rowsBefore != null ? rowsBefore : currentRows.length,
            row_count_after: currentRows.length,
            header_count: headerCount,
            imported_row_count: importedCount,
            import_mode: importMode || "",
            comment: comment
        });
    }

    function importCsv(file) {
        if (csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }
        if (file.size > MAX_IMPORT_SIZE) {
            showMsg(
                "Import file too large: <strong>" + (file.size / 1024 / 1024).toFixed(1) +
                " MB</strong>. Maximum allowed is <strong>5 MB</strong>.",
                "error"
            );
            logImportEvent(file.name, "failure", "File too large (" + (file.size / 1024 / 1024).toFixed(1) + " MB)", 0, 0, "");
            return;
        }
        var reader = new FileReader();
        reader.onload = function (e) {
            var text = e.target.result;
            var parsed = parseCsvText(text);
            if (!parsed) {
                showMsg("Failed to parse CSV file.", "error");
                logImportEvent(file.name, "failure", "Failed to parse CSV file", 0, 0, "");
                return;
            }

            var importHeaders = parsed.headers;
            var importRows = parsed.rows;

            // Validate size limits (apply to both modes)
            if (importHeaders.length > MAX_COLUMNS) {
                showMsg(
                    "Import CSV has <strong>" + importHeaders.length +
                    "</strong> columns, maximum allowed is <strong>" + MAX_COLUMNS + "</strong>.",
                    "error"
                );
                logImportEvent(file.name, "failure", "Too many columns (" + importHeaders.length + ")", 0, importHeaders.length, "");
                return;
            }

            if (importRows.length > MAX_ROWS) {
                showMsg(
                    "Import file has <strong>" + importRows.length +
                    "</strong> rows, maximum allowed is <strong>" + MAX_ROWS + "</strong>.",
                    "error"
                );
                logImportEvent(file.name, "failure", "Row limit exceeded (" + importRows.length + " rows)", 0, importHeaders.length, "");
                return;
            }

            // Validate expiration date formats before allowing import
            var badDates = validateExpireDates(importHeaders, importRows);
            if (badDates.length) {
                var examples = badDates.slice(0, 5).map(function (b) {
                    return "Row " + b.row + ": <code>" + _.escape(b.value.substring(0, 60)) + "</code>";
                }).join("<br>");
                var moreMsg = badDates.length > 5 ? "<br>...and more" : "";
                showMsg(
                    "Import blocked — invalid date format in expiration column:<br>" +
                    examples + moreMsg +
                    "<br><br>Expected: <code>YYYY-MM-DD HH:MM UTC</code> or <code>YYYY-MM-DD</code>",
                    "error"
                );
                logImportEvent(file.name, "failure", "Invalid expiration dates in " + badDates.length + " row(s)", 0, importHeaders.length, "");
                return;
            }

            // Show modal to choose Replace or Merge
            showImportModeModal(file.name, importHeaders, importRows);
        };
        reader.readAsText(file);
    }

    function showImportModeModal(fileName, importHeaders, importRows) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Import CSV &mdash; ' + _.escape(fileName) + '</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>This file has <strong>' + importRows.length + '</strong> row(s) and <strong>' + importHeaders.length + '</strong> column(s).</p>' +
                        '<p>How would you like to import?</p>' +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button class="btn btn-danger" id="wl-import-replace">Replace</button> ' +
                        '<button class="btn btn-primary" id="wl-import-merge">Merge</button> ' +
                        '<button class="btn" id="wl-import-cancel">Cancel</button>' +
                    '</div>' +
                    '<div style="margin-top:10px;font-size:12px;color:var(--wl-muted);">' +
                        '<strong>Replace</strong> &mdash; Remove all current rows and columns, replace with imported data<br>' +
                        '<strong>Merge</strong> &mdash; Keep existing rows, add only new unique rows' +
                    '</div>' +
                '</div>' +
            '</div>'
        );
        $("body").append($modal);

        $modal.on("click", "#wl-import-replace", function () {
            $modal.remove();
            // Import Replace always requires approval
            submitImportReplaceApproval(fileName, importHeaders, importRows);
        });

        $modal.on("click", "#wl-import-merge", function () {
            $modal.remove();
            doImportMerge(fileName, importHeaders, importRows);
        });

        $modal.on("click", "#wl-import-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
    }

    function doImportReplace(fileName, importHeaders, importRows) {
        var rowsBefore = currentRows.length;

        // Full replacement: adopt imported headers and rows
        currentHeaders = importHeaders.slice();
        currentRows = importRows.map(function (r) { return $.extend({}, r); });

        refreshTable();
        showMsg(
            "Replaced with <strong>" + importRows.length + "</strong> row(s) from " +
            "<strong>" + _.escape(fileName) + "</strong>. " +
            "Review and click <strong>Save Changes</strong> to persist.",
            "success"
        );
        logImportEvent(fileName, "success", "", importRows.length, importHeaders.length, "replace", rowsBefore);
    }

    function doImportMerge(fileName, importHeaders, importRows) {
        var rowsBefore = currentRows.length;

        // Validate merge row limit (current + import combined)
        if (currentRows.length + importRows.length > MAX_ROWS) {
            showMsg(
                "Merge would result in <strong>" + (currentRows.length + importRows.length) +
                "</strong> rows, maximum allowed is <strong>" + MAX_ROWS +
                "</strong>. Current: " + currentRows.length + ", import: " + importRows.length + ".",
                "error"
            );
            logImportEvent(fileName, "failure", "Row limit exceeded on merge (" + (currentRows.length + importRows.length) + " rows)", 0, importHeaders.length, "merge", rowsBefore);
            return;
        }

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
            logImportEvent(fileName, "failure", "Missing columns: " + missingHeaders.join(", "), 0, importHeaders.length, "merge", rowsBefore);
            return;
        }

        // Merge: count how many unique rows would be added
        var existingKeys = {};
        var keyHeaders = currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_" && h !== "Comment" && h !== expireColumn;
        });
        currentRows.forEach(function (row) {
            var key = keyHeaders.map(function (h) { return row[h] || ""; }).join("||");
            existingKeys[key] = true;
        });

        var newUniqueRows = [];
        var tempKeys = $.extend({}, existingKeys);
        importRows.forEach(function (importRow) {
            var key = keyHeaders.map(function (h) { return importRow[h] || ""; }).join("||");
            if (!tempKeys[key]) {
                var newRow = {};
                currentHeaders.forEach(function (h) {
                    newRow[h] = importRow[h] || "";
                });
                newUniqueRows.push(newRow);
                tempKeys[key] = true;
            }
        });

        if (newUniqueRows.length === 0) {
            showMsg("No new rows to import (all rows already exist).", "info");
            logImportEvent(fileName, "success", "No new rows (all already exist)", 0, importHeaders.length, "merge", rowsBefore);
            return;
        }

        function applyMergeLocally() {
            newUniqueRows.forEach(function (row) { currentRows.push(row); });
            refreshTable();
            showMsg(
                "Merged <strong>" + newUniqueRows.length + "</strong> new row(s) from " +
                "<strong>" + _.escape(fileName) + "</strong>. " +
                "Review and click <strong>Save Changes</strong> to persist.",
                "success"
            );
            logImportEvent(fileName, "success", "", newUniqueRows.length, importHeaders.length, "merge", rowsBefore);
        }

        // Check approval gate for bulk additions
        restPost({
            action: "check_approval_gate",
            gate_action: "bulk_row_addition",
            csv_file: selectedCsv,
            app_context: selectedApp,
            selected_count: newUniqueRows.length
        }).done(function (gateData) {
            if (gateData.requires_approval) {
                showMsg(
                    "Import Merge would add <strong>" + newUniqueRows.length +
                    "</strong> row(s), which requires admin approval. " +
                    "Reason: " + _.escape(gateData.reason) + ".",
                    "error"
                );
                logImportEvent(fileName, "failure",
                    "Approval required: adding " + newUniqueRows.length + " rows",
                    0, importHeaders.length, "merge", rowsBefore);
            } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                showMsg(formatDailyLimitMsg(gateData.daily_limit), "error"
                );
                logImportEvent(fileName, "failure",
                    "Daily limit reached for row additions",
                    0, importHeaders.length, "merge", rowsBefore);
            } else {
                applyMergeLocally();
            }
        }).fail(function () {
            // Fail-closed: block merge if gate check fails
            showMsg("Unable to verify approval gate for import merge. Please try again.", "error");
        });
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

    function getAuditComment(callback) {
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
                return;
            }

            callback({ valid: true, comment: "" });
            return;
        }

        // Show styled modal for audit comment
        $(".wl-modal-overlay").remove();
        var html =
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal" style="max-width:480px">' +
                '<h3 style="margin-top:0">Audit Comment Required</h3>' +
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
                '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">' +
                    '<span class="btn btn-primary" id="wl-audit-comment-ok" ' +
                        'style="cursor:pointer">OK</span>' +
                    '<span class="btn" id="wl-audit-comment-cancel" ' +
                        'style="cursor:pointer">Cancel</span>' +
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
            if (comment.length > 500) {
                comment = comment.substring(0, 500);
                showMsg("Comment truncated to 500 characters.", "warning");
            }
            $(".wl-modal-overlay").remove();
            callback({ valid: true, comment: comment });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Version control — load versions and revert
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

    function renderVersionsDropdown() {
        $revertSelect.empty();

        if (!versionsList.length) {
            $revertSelect.append('<option value="">-- No previous versions --</option>');
            $revertSelect.prop("disabled", true);
            $revertGroup.show();
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
        $revertSelect.append(
            '<option value="" selected="selected">' +
            _.escape(versionLabel(current, true)) +
            '</option>'
        );

        // Previous versions (up to 5) — newest first
        var previous = versionsList.slice(0, versionsList.length - 1);
        for (var i = previous.length - 1; i >= 0; i--) {
            var v = previous[i];
            $revertSelect.append(
                '<option value="' + _.escape(v.filename) + '" ' +
                'data-display="' + _.escape(v.display) + '">' +
                _.escape(versionLabel(v, false)) +
                '</option>'
            );
        }
        $revertSelect.prop("disabled", !previous.length);
        $revertGroup.show();
    }

    $revertSelect.on("change", function () {
        var val = $(this).val();
        if (!val) { return; }
        if (csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            $(this).prop("selectedIndex", 0);
            return;
        }

        var $opt = $(this).find("option:selected");
        var versionDisplay = $opt.data("display") || "";

        showRevertModal(val, versionDisplay, function () {
            // Reset to first option so the same version can be selected again
            $revertSelect.prop("selectedIndex", 0);
        });
    });

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
                        '<span class="btn btn-primary" id="wl-revert-ok">OK</span> ' +
                        '<span class="btn" id="wl-revert-cancel">Cancel</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("click", "#wl-revert-ok", function () {
            var reason = $modal.find("#wl-revert-reason").val().trim();
            if (!reason) {
                $modal.find("#wl-revert-reason").addClass("wl-input-error");
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

    function doRevert(versionFilename, versionDisplay, reason) {
        if (saving) { return; }
        if (csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }
        saving = true;

        showMsg("Reverting to version " + _.escape(versionDisplay) + "&hellip;", "info");

        restPost({
            action:           "revert_csv",
            csv_file:         selectedCsv,
            app_context:      selectedApp,
            detection_rule:   selectedRule || "",
            version_filename: versionFilename,
            version_display:  versionDisplay,
            revert_reason:    reason,
            expected_mtime:   loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                saving = false;
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
                renderDiff(diffInfo);
            }

            // Reload the CSV from server to show reverted content
            reloadCsvQuiet(function () {
                saving = false;
            });
        })
        .fail(function (xhr) {
            saving = false;
            var err = "Failed to revert.";
            try {
                var resp = JSON.parse(xhr.responseText);
                err = resp.error || err;
                if (resp.requires_approval) {
                    // Auto-submit an approval request for the large revert
                    var desc = "Revert " + selectedCsv + " to version " + versionDisplay;
                    var changeParts = [];
                    if (resp.revert_row_changes) changeParts.push(resp.revert_row_changes + " row changes");
                    if (resp.revert_col_changes) changeParts.push(resp.revert_col_changes + " column changes");
                    if (changeParts.length) desc += " (" + changeParts.join(", ") + ")";

                    showMsg("Large revert requires approval. Submitting request&hellip;", "info");

                    restPost({
                        action: "submit_approval",
                        approval_action_type: "revert",
                        csv_file: selectedCsv,
                        app_context: selectedApp,
                        detection_rule: selectedRule || "",
                        description: desc,
                        original_payload: {
                            action: "revert_csv",
                            csv_file: selectedCsv,
                            app_context: selectedApp,
                            detection_rule: selectedRule || "",
                            version_filename: versionFilename,
                            version_display: versionDisplay,
                            revert_reason: reason
                        },
                        expected_mtime: loadedMtime,
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
                        loadCsv(selectedCsv, selectedApp);
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
            handleSaveError(xhr, "Failed to revert.");
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Load CSV content from REST
    // ══════════════════════════════════════════════════════════════════
    function loadCsv(csvFile, appContext) {
        clearMsg();
        $diff.empty();
        $("#wl-approval-actions").remove();
        $("#wl-addition-preview").remove();
        pendingFilterActive = false;
        pendingFilterIndices = null;
        additionPreviewData = null;
        $table.html('<p class="wl-muted">Loading CSV content&hellip;</p>');

        restGet({
            action:   "get_csv_content",
            csv_file: csvFile,
            app:      appContext || "",
            tz_offset: new Date().getTimezoneOffset()
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
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
            // Build locked state BEFORE rendering so buildRow() can check it
            pendingApprovals = data.pending_approvals || [];
            loadedPendingCount = pendingApprovals.length;
            buildLockedState();
            renderTable(data.headers || [], data.rows || []);
            loadVersions(csvFile, appContext);
            loadedMtime = data.file_mtime || null;
            startChangeMonitoring();
            // Apply pending approval CSS highlighting + banner
            if (pendingApprovals.length) {
                applyPendingHighlighting();
            }
            // Load server-side column widths
            restGet({ action: "get_col_widths", csv_file: csvFile, app: appContext || "" })
                .done(function (wdata) {
                    var w = wdata.col_widths || {};
                    if (Object.keys(w).length) {
                        colWidths = w;
                        allColWidths[selectedCsv] = $.extend({}, w);
                        $table.find("th.wl-col-draggable").each(function () {
                            var h = $(this).data("col");
                            if (colWidths[h]) {
                                $(this).css({ width: colWidths[h], minWidth: colWidths[h] });
                            }
                        });
                    }
                });
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(csvFile);
                return;
            }
            var err = "Failed to load CSV.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
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
                loadVersions(selectedCsv, selectedApp);
                if (data.file_mtime) { loadedMtime = data.file_mtime; }
                startChangeMonitoring();
            }
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(selectedCsv);
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
        if (csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }

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

        // ── Pre-save gate: estimate edits and additions to check limits ──
        var editedCount = 0;
        var addedCount = Math.max(0, currentRows.length - originalRows.length);
        visHeaders.forEach(function () {}); // reuse visHeaders from above
        var origKeySet = {};
        originalRows.forEach(function (row) {
            var key = visHeaders.map(function (h) { return row[h] || ""; }).join("||");
            origKeySet[key] = true;
        });
        currentRows.forEach(function (row, idx) {
            if (idx < originalRows.length) {
                var changed = visHeaders.some(function (h) {
                    return (row[h] || "") !== (originalRows[idx][h] || "");
                });
                if (changed) { editedCount++; }
            }
        });

        // If either inline edits or additions exceed thresholds, the backend
        // will block the save with a 403.  Show a clear frontend message first.
        function proceedWithSave() {
            getAuditComment(function (result) {
            if (!result) { return; }

            saving = true;
            $table.find("#btn-save").prop("disabled", true).text("Saving...");
            showMsg("Saving&hellip;", "info");

            var savePayload = {
                action:          "save_csv",
                csv_file:        selectedCsv,
                app_context:     selectedApp,
                detection_rule:  selectedRule || "",
                headers:         currentHeaders,
                rows:            currentRows,
                comment:         result.comment,
                removal_reasons: [],
                expected_mtime:  loadedMtime
            };
            // Include bulk edit marker so backend classifies edits correctly
            if (pendingBulkEditCount > 0) {
                savePayload._bulk_edit_count = pendingBulkEditCount;
            }
            restPost(savePayload)
            .done(function (data) {
                if (data.error) {
                    saving = false;
                    showMsg(_.escape(data.error), "error");
                    currentRows = originalRows.map(function (r) { return $.extend({}, r); });
                    refreshTable();
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
                    renderDiff(diffInfo);
                }

                // Clear search after successful save so all rows are visible
                searchQuery = "";

                // Reload CSV from server to pick up backend-stamped metadata
                // (e.g. _review_status=pending, _added_by, _added_at)
                reloadCsvQuiet(function () {
                    saving = false;
                });
            })
            .fail(function (xhr) {
                saving = false;
                pendingBulkEditCount = 0; // Reset on save failure
                handleSaveError(xhr, "Failed to save CSV.");
                currentRows = originalRows.map(function (r) { return $.extend({}, r); });
                currentHeaders = originalHeaders.slice();
                refreshTable();
            });
            }); // end getAuditComment callback
        }

        // Pre-save checks:
        //  - Bulk Edit edits   → check "bulk_row_edit" approval gate + daily limit
        //  - Inline row edits  → check "row_edit" daily limit (no approval gate)
        //  - Inline row adds   → check "bulk_row_addition" approval gate
        var needsGateCheck = false;
        var gateAction = "";
        var gateCount = 0;

        if (addedCount > 0) {
            // Row additions still use the approval gate for large batches
            needsGateCheck = true;
            gateAction = "bulk_row_addition";
            gateCount = addedCount;
        } else if (editedCount >= 2) {
            // 2+ row edits = bulk edit (matches server-side is_bulk_edit
            // = edited_count >= 2) — check bulk_row_edit gate + limit
            // regardless of whether the Bulk Edit button was used
            needsGateCheck = true;
            gateAction = "bulk_row_edit";
            gateCount = editedCount;
        } else if (editedCount > 0) {
            // Single inline edit — daily limit check only, no approval gate
            needsGateCheck = true;
            gateAction = "inline_row_edit";
            gateCount = editedCount;
        }

        if (needsGateCheck) {
            restPost({
                action: "check_approval_gate",
                gate_action: gateAction,
                csv_file: selectedCsv,
                app_context: selectedApp,
                selected_count: gateCount
            }).done(function (gateData) {
                if (gateData.requires_approval) {
                    // Show reason modal and submit for approval
                    var actionDesc = gateAction === "bulk_row_edit"
                        ? "Editing <strong>" + gateCount + "</strong> row(s)"
                        : "Adding <strong>" + gateCount + "</strong> row(s)";
                    showRemoveRowModal(
                        "Submit for Approval",
                        actionDesc + " requires admin approval.<br>" +
                            "Reason: " + _.escape(gateData.reason) + "<br><br>" +
                            "Your request will be submitted for review.",
                        function (reason) {
                            if (gateAction === "bulk_row_addition") {
                                submitApprovalRequest("bulk_row_addition", reason, null, null);
                            } else if (gateAction === "bulk_row_edit") {
                                // Submit full save payload for approval
                                // (inline multi-row edits don't have a single col/val)
                                submitInlineMultiEditApproval(gateCount, reason);
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
                    showMsg(formatDailyLimitMsg(gateData.daily_limit),
                        "error"
                    );
                } else {
                    proceedWithSave();
                }
            }).fail(function () {
                // Fail-closed: block save if gate check fails
                showMsg("Unable to verify approval gate. Please try again.", "error");
            });
        } else {
            proceedWithSave();
        }
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

        var rmPayload = {
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Row removal",
            removal_reasons: [{ row: removedRow, reason: reason, row_number: rowNumber }],
            expected_mtime:  loadedMtime
        };
        // If unsaved bulk edits are included in currentRows, mark them
        // so the backend classifies them as bulk_row_edit (not row_edit)
        if (pendingBulkEditCount > 0) {
            rmPayload._bulk_edit_count = pendingBulkEditCount;
        }
        restPost(rmPayload)
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var rmMsg = "Row removed and saved successfully.";
            if (diffInfo.edited_count > 0) {
                rmMsg = "Row removed and " + diffInfo.edited_count + " row(s) edited. Saved successfully.";
            }
            showMsg(rmMsg, "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            pendingBulkEditCount = 0; // Bulk edits (if any) were committed with the removal
            if (data.file_mtime) { loadedMtime = data.file_mtime; }
            refreshTable(); // Re-render to clear stale edit highlights

            // Show undo bar for 10 seconds
            showUndoBar(removedRow, prevRows, prevOriginal);
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            // Refresh version list
            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            pendingBulkEditCount = 0; // Reset on failure too (rows are restored)
            handleSaveError(xhr, "Failed to save after removal.");
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

        var bulkRmPayload = {
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Bulk removal (" + removedEntries.length + " rows)",
            removal_reasons: [],
            bulk_removal:    bulkRemoval,
            expected_mtime:  loadedMtime
        };
        if (pendingBulkEditCount > 0) {
            bulkRmPayload._bulk_edit_count = pendingBulkEditCount;
        }
        restPost(bulkRmPayload)
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var bulkMsg = removedEntries.length + " row(s) removed and saved successfully.";
            if (diffInfo.edited_count > 0) {
                bulkMsg = removedEntries.length + " row(s) removed and " + diffInfo.edited_count + " row(s) edited. Saved successfully.";
            }
            showMsg(bulkMsg, "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            pendingBulkEditCount = 0; // Bulk edits (if any) were committed with the removal
            if (data.file_mtime) { loadedMtime = data.file_mtime; }
            refreshTable(); // Re-render to clear stale edit highlights
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            // Refresh version list
            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            pendingBulkEditCount = 0; // Reset on failure too (rows are restored)
            handleSaveError(xhr, "Failed to save after bulk removal.");
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

        // ── Stats bar ────────────────────────────────────────────
        var stats = [];
        if (diff.added_count) stats.push(
            '<span style="color:var(--wl-diff-add)">+' + diff.added_count + ' added</span>');
        if (diff.removed_count) stats.push(
            '<span style="color:var(--wl-diff-rm)">&minus;' + diff.removed_count + ' removed</span>');
        if (diff.edited_count) stats.push(
            '<span style="color:var(--wl-accent,#2962ff)">' + diff.edited_count + ' edited</span>');
        if (diff.added_columns && diff.added_columns.length) stats.push(
            '<span style="color:var(--wl-diff-add)">+' + diff.added_columns.length + ' column(s)</span>');
        if (diff.removed_columns && diff.removed_columns.length) stats.push(
            '<span style="color:var(--wl-diff-rm)">&minus;' + diff.removed_columns.length + ' column(s)</span>');
        if (stats.length) {
            html += '<div style="margin-bottom:12px;font-size:13px">' + stats.join(' &nbsp;&bull;&nbsp; ') + '</div>';
        }

        // ── Column changes (badges) ──────────────────────────────
        if ((diff.added_columns && diff.added_columns.length) ||
            (diff.removed_columns && diff.removed_columns.length)) {
            html += '<div class="wl-diff-section"><h5>Column Changes</h5><div>';
            (diff.added_columns || []).forEach(function (col) {
                html += '<span class="wl-diff-col-badge wl-diff-col-add">+ ' + _.escape(col) + '</span>';
            });
            (diff.removed_columns || []).forEach(function (col) {
                html += '<span class="wl-diff-col-badge wl-diff-col-rm">&minus; ' + _.escape(col) + '</span>';
            });
            html += '</div></div>';
        }

        // ── Edited rows (side-by-side) ───────────────────────────
        var DIFF_MAX_ROWS = 10;     // show detail for first N edits
        var DIFF_MAX_COLS = 8;      // max columns per pane (key + changed + context)

        if (diff.edited && diff.edited.length) {
            var totalEdited = diff.edited.length;
            var showCount = Math.min(totalEdited, DIFF_MAX_ROWS);

            html += '<div class="wl-diff-section">';
            html += '<h5>Edited Rows (' + totalEdited + ')';
            if (totalEdited > showCount) {
                html += ' <span style="font-weight:normal;color:var(--wl-muted,#888)">' +
                    '— showing first ' + showCount + '</span>';
            }
            html += '</h5>';

            // Container for expandable rows
            html += '<div id="wl-diff-edited-detail">';

            diff.edited.slice(0, showCount).forEach(function (edit, idx) {
                var oldRow = edit.old_row || {};
                var newRow = edit.new_row || {};
                var changedFields = edit.changed_fields || [];
                var changes = {};
                changedFields.forEach(function (cf) {
                    changes[cf.field] = true;
                });
                var rowNum = edit.row_num || edit.old_row_num || (idx + 1);

                // Smart column selection: show key col + changed cols + context
                var allHeaders = [];
                var seen = {};
                [oldRow, newRow].forEach(function (r) {
                    Object.keys(r).forEach(function (k) {
                        if (!k.startsWith("_") && !seen[k]) {
                            seen[k] = true;
                            allHeaders.push(k);
                        }
                    });
                });

                var changedKeys = Object.keys(changes);
                var displayHeaders;
                var truncatedCols = false;

                if (allHeaders.length <= DIFF_MAX_COLS) {
                    // Few columns — show all
                    displayHeaders = allHeaders;
                } else {
                    // Many columns — show key column + changed columns + fill up to max
                    displayHeaders = [];
                    var keyCol = allHeaders[0]; // first column = identifier
                    displayHeaders.push(keyCol);
                    changedKeys.forEach(function (ck) {
                        if (ck !== keyCol && displayHeaders.length < DIFF_MAX_COLS) {
                            displayHeaders.push(ck);
                        }
                    });
                    // Fill remaining slots with unchanged columns for context
                    allHeaders.forEach(function (h) {
                        if (displayHeaders.indexOf(h) === -1 &&
                            displayHeaders.length < DIFF_MAX_COLS) {
                            displayHeaders.push(h);
                        }
                    });
                    truncatedCols = allHeaders.length > displayHeaders.length;
                }

                html += '<div class="wl-diff-sbs">';

                // Before pane
                html += '<div class="wl-diff-pane wl-diff-pane-before">';
                html += '<div class="wl-diff-pane-header">Before (Row ' + rowNum + ')';
                if (truncatedCols) {
                    html += ' <span style="font-weight:normal;font-size:11px;opacity:0.7">' +
                        '— ' + changedKeys.length + ' changed of ' +
                        allHeaders.length + ' columns</span>';
                }
                html += '</div>';
                html += '<table><thead><tr>';
                displayHeaders.forEach(function (h) {
                    html += '<th>' + _.escape(h) + '</th>';
                });
                html += '</tr></thead><tbody><tr>';
                displayHeaders.forEach(function (h) {
                    var cls = changes[h] ? ' class="wl-diff-cell-changed"' : '';
                    html += '<td' + cls + '>' + _.escape(oldRow[h] || '') + '</td>';
                });
                html += '</tr></tbody></table></div>';

                // After pane
                html += '<div class="wl-diff-pane wl-diff-pane-after">';
                html += '<div class="wl-diff-pane-header">After (Row ' + rowNum + ')';
                if (truncatedCols) {
                    html += ' <span style="font-weight:normal;font-size:11px;opacity:0.7">' +
                        '— ' + changedKeys.length + ' changed of ' +
                        allHeaders.length + ' columns</span>';
                }
                html += '</div>';
                html += '<table><thead><tr>';
                displayHeaders.forEach(function (h) {
                    html += '<th>' + _.escape(h) + '</th>';
                });
                html += '</tr></thead><tbody><tr>';
                displayHeaders.forEach(function (h) {
                    var cls = changes[h] ? ' class="wl-diff-cell-changed"' : '';
                    html += '<td' + cls + '>' + _.escape(newRow[h] || '') + '</td>';
                });
                html += '</tr></tbody></table></div>';

                html += '</div>'; // .wl-diff-sbs
            });

            html += '</div>'; // #wl-diff-edited-detail

            // Collapsed rows summary
            if (totalEdited > showCount) {
                var remaining = totalEdited - showCount;
                html += '<div id="wl-diff-edited-collapsed" style="margin-top:8px">';
                html += '<div style="padding:8px 12px;background:var(--wl-bg-row,#23272b);' +
                    'border:1px solid var(--wl-border,#444);border-radius:4px;font-size:12px;' +
                    'color:var(--wl-muted,#888)">';
                html += '<span id="wl-diff-expand-btn" style="cursor:pointer;' +
                    'color:var(--wl-accent,#2962ff);text-decoration:underline">' +
                    'Show ' + remaining + ' more edited row' +
                    (remaining > 1 ? 's' : '') + '</span>';
                html += ' (compact summary)';
                html += '</div>';
                // Pre-build compact summary for collapsed rows
                html += '<div id="wl-diff-edited-expanded" style="display:none;margin-top:6px">';
                html += '<table class="wl-table" style="font-size:11px;width:100%">';
                html += '<thead><tr><th>Row</th><th>Changed Fields</th><th>Before → After</th></tr></thead>';
                html += '<tbody>';
                diff.edited.slice(showCount).forEach(function (edit) {
                    var rn = edit.row_num || edit.old_row_num || "?";
                    html += '<tr><td>' + rn + '</td>';
                    var fieldChanges = (edit.changed_fields || []).map(function (cf) {
                        return _.escape(cf.field);
                    }).join(", ");
                    html += '<td>' + fieldChanges + '</td>';
                    var valueChanges = (edit.changed_fields || []).slice(0, 3).map(function (cf) {
                        return '<span style="color:var(--wl-diff-rm)">' +
                            _.escape((cf.before || "").substring(0, 30)) + '</span>' +
                            ' → <span style="color:var(--wl-diff-add)">' +
                            _.escape((cf.after || "").substring(0, 30)) + '</span>';
                    }).join("; ");
                    if ((edit.changed_fields || []).length > 3) {
                        valueChanges += " +" + ((edit.changed_fields || []).length - 3) + " more";
                    }
                    html += '<td>' + valueChanges + '</td></tr>';
                });
                html += '</tbody></table></div>';
                html += '</div>';
            }

            html += '</div>';
        }

        // ── Added rows ───────────────────────────────────────────
        if (diff.added && diff.added.length) {
            html += '<div class="wl-diff-section">';
            html += '<h5 style="color:var(--wl-diff-add)">Added Rows (' + diff.added.length + ')</h5>';
            html += '<ul class="wl-diff-row-list">';
            diff.added.forEach(function (row) {
                var parts = [];
                Object.keys(row).forEach(function (k) {
                    if (!k.startsWith("_") && row[k]) {
                        parts.push(_.escape(k) + ': ' + _.escape(row[k]));
                    }
                });
                html += '<li class="wl-diff-row-add">' + parts.join(' &nbsp;|&nbsp; ') + '</li>';
            });
            html += '</ul></div>';
        }

        // ── Removed rows ─────────────────────────────────────────
        if (diff.removed && diff.removed.length) {
            html += '<div class="wl-diff-section">';
            html += '<h5 style="color:var(--wl-diff-rm)">Removed Rows (' + diff.removed.length + ')</h5>';
            html += '<ul class="wl-diff-row-list">';
            diff.removed.forEach(function (row) {
                var parts = [];
                Object.keys(row).forEach(function (k) {
                    if (!k.startsWith("_") && row[k]) {
                        parts.push(_.escape(k) + ': ' + _.escape(row[k]));
                    }
                });
                html += '<li class="wl-diff-row-rm">' + parts.join(' &nbsp;|&nbsp; ') + '</li>';
            });
            html += '</ul></div>';
        }

        html += "</div>";
        $diff.html(html);

        // Expand handler for collapsed edited rows
        $("#wl-diff-expand-btn").on("click", function () {
            var $expanded = $("#wl-diff-edited-expanded");
            if ($expanded.is(":visible")) {
                $expanded.hide();
                $(this).text($(this).text().replace("Hide", "Show"));
            } else {
                $expanded.show();
                $(this).text($(this).text().replace("Show", "Hide"));
            }
        });
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

    function formatLocalDateTime(d) {
        return d.getFullYear() + "-" + padTwo(d.getMonth() + 1) + "-" + padTwo(d.getDate()) +
               " " + padTwo(d.getHours()) + ":" + padTwo(d.getMinutes());
    }

    function formatUTCDateTime(d) {
        return d.getUTCFullYear() + "-" + padTwo(d.getUTCMonth() + 1) + "-" + padTwo(d.getUTCDate()) +
               " " + padTwo(d.getUTCHours()) + ":" + padTwo(d.getUTCMinutes());
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
                    '<label class="wl-dp-label">Time (24h)</label>' +
                    '<input type="text" class="wl-dp-time" value="00:00" placeholder="HH:MM" maxlength="5" />' +
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

        // Apply button — convert local picker values to UTC for storage
        $datePicker.on("click", ".wl-dp-apply", function () {
            var d = $datePicker.find(".wl-dp-date").val();
            var t = ($datePicker.find(".wl-dp-time").val() || "00:00").trim();
            if (!d) { return; }
            // Validate 24h time format (HH:MM, 00:00–23:59)
            if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) {
                $datePicker.find(".wl-dp-time").css("border-color", "#e74c3c");
                return;
            }
            $datePicker.find(".wl-dp-time").css("border-color", "");
            if ($activeExpiresInput) {
                // Parse local date/time from picker
                var tp = t.split(":");
                var localDate = new Date(
                    parseInt(d.substr(0, 4), 10), parseInt(d.substr(5, 2), 10) - 1,
                    parseInt(d.substr(8, 2), 10), parseInt(tp[0], 10), parseInt(tp[1], 10)
                );
                // Store UTC in data model
                var utcStr = formatUTCDateTime(localDate) + " UTC";
                var idx = $activeExpiresInput.closest("tr").data("idx");
                var header = $activeExpiresInput.data("header");
                if (currentRows[idx]) { currentRows[idx][header] = utcStr; }
                // Display local time in the input
                $activeExpiresInput.val(d + " " + t);
            }
            closeDatePicker();
        });

        // Clear button (permanent — empty Expires)
        $datePicker.on("click", ".wl-dp-clear", function () {
            if ($activeExpiresInput) {
                var idx = $activeExpiresInput.closest("tr").data("idx");
                var header = $activeExpiresInput.data("header");
                if (currentRows[idx]) { currentRows[idx][header] = ""; }
                $activeExpiresInput.val("");
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

        // Read stored value from data model (may be UTC with Z suffix)
        var idx = $input.closest("tr").data("idx");
        var header = $input.data("header");
        var stored = (currentRows[idx] && currentRows[idx][header]) || "";
        stored = stored.trim();

        if (stored && stored.endsWith("UTC")) {
            // UTC value — convert to local for picker display
            var utcDate = new Date(stored.replace(" UTC", "Z").replace(" ", "T"));
            if (!isNaN(utcDate.getTime())) {
                $datePicker.find(".wl-dp-date").val(formatDateForPicker(utcDate));
                $datePicker.find(".wl-dp-time").val(padTwo(utcDate.getHours()) + ":" + padTwo(utcDate.getMinutes()));
            }
        } else if (/^\d{4}-\d{2}-\d{2}/.test(stored)) {
            // Legacy local value — use as-is
            var parts = stored.split(" ");
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
    // Search bar events (static DOM — not inside $table)
    // ══════════════════════════════════════════════════════════════════

    $searchInput.on("input", function () {
        syncInputs();
        searchQuery = $(this).val().trim();
        currentPage = 0;
        refreshTable();
    });

    $searchClear.on("click", function () {
        syncInputs();
        clearSearch();
    });

    // ══════════════════════════════════════════════════════════════════
    // Keyboard Shortcuts
    // ══════════════════════════════════════════════════════════════════

    $(document).on("keydown", function (e) {
        var isInput = $(e.target).is("input, textarea, select");

        // Ctrl+S / Cmd+S — Save Changes
        if ((e.ctrlKey || e.metaKey) && e.which === 83) {
            e.preventDefault();
            if (selectedCsv && !saving) {
                doSave();
            }
            return;
        }

        // Escape — close any open modal, date picker, or clear search
        if (e.which === 27 || e.key === "Escape") {
            if ($datePicker && $datePicker.css("display") !== "none") {
                e.preventDefault();
                e.stopPropagation();
                closeDatePicker();
                return;
            }
            if ($(".wl-modal-overlay").length) {
                e.preventDefault();
                e.stopPropagation();
                $(".wl-modal-overlay").last().remove();
                return;
            }
            if (searchQuery && $(e.target).is("#wl-search-input")) {
                e.preventDefault();
                e.stopPropagation();
                clearSearch();
                return;
            }
        }

        // Alt+Left / Alt+Right — pagination
        if (e.altKey && selectedCsv && currentHeaders.length) {
            var totalPages = Math.ceil(currentRows.length / ROWS_PER_PAGE);
            if (e.which === 37 || e.key === "ArrowLeft") {
                e.preventDefault();   // always block browser-back
                if (currentPage > 0) {
                    syncInputs();
                    currentPage--;
                    refreshTable();
                }
                return;
            }
            if (e.which === 39 || e.key === "ArrowRight") {
                e.preventDefault();   // always block browser-forward
                if (currentPage < totalPages - 1) {
                    syncInputs();
                    currentPage++;
                    refreshTable();
                }
                return;
            }
        }

        // Ctrl+Z — undo last cell edit (when not in an input)
        if ((e.ctrlKey || e.metaKey) && e.which === 90 && !e.shiftKey) {
            if (!isInput && editHistory.length > 0) {
                e.preventDefault();
                undoCellEdit();
            }
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // Bulk Edit Mode — apply same value to a column across selected rows
    // ══════════════════════════════════════════════════════════════════

    function showBulkEditModal() {
        var selectedCount = Object.keys(selectedIdxSet).length;
        if (selectedCount === 0) {
            showMsg("Select rows first using the checkboxes.", "warning");
            return;
        }

        $(".wl-modal-overlay").remove();

        var visibleHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
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
                        '<span class="btn btn-primary" id="wl-bulk-apply">Apply</span> ' +
                        '<span class="btn" id="wl-bulk-cancel">Cancel</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        // Toggle between text input and date picker based on column selection
        function updateBulkValueInput() {
            var col = $modal.find("#wl-bulk-col").val();
            var isExpires = (expireColumn && col === expireColumn);
            if (isExpires) {
                $modal.find("#wl-bulk-val, #wl-bulk-val-label").hide();
                $modal.find("#wl-bulk-expires-picker").show();
                // Default to now
                var now = new Date();
                $modal.find("#wl-bulk-dp-date").val(formatDateForPicker(now));
                $modal.find("#wl-bulk-dp-time").val(padTwo(now.getHours()) + ":" + padTwo(now.getMinutes()));
            } else {
                $modal.find("#wl-bulk-val, #wl-bulk-val-label").show();
                $modal.find("#wl-bulk-expires-picker").hide();
            }
        }
        $modal.on("change", "#wl-bulk-col", updateBulkValueInput);
        // Check initial selection
        updateBulkValueInput();

        // Date picker preset buttons
        $modal.on("click", ".wl-bulk-dp-preset", function () {
            var days = parseInt($(this).data("days"), 10);
            var future = new Date();
            future.setDate(future.getDate() + days);
            $modal.find("#wl-bulk-dp-date").val(formatDateForPicker(future));
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
            var isExpires = (expireColumn && col === expireColumn);

            if (isExpires) {
                // Build UTC value from date picker
                var d = $modal.find("#wl-bulk-dp-date").val();
                var t = ($modal.find("#wl-bulk-dp-time").val() || "00:00").trim();
                if (!d) {
                    // Empty date = clear expiration (permanent)
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

            syncInputs();

            // Count how many rows would actually change
            var selectedIdxs = Object.keys(selectedIdxSet).map(Number);
            var wouldChange = 0;
            selectedIdxs.forEach(function (idx) {
                if (currentRows[idx] && (currentRows[idx][col] || "") !== val) {
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
                    if (currentRows[idx]) {
                        var oldVal = currentRows[idx][col] || "";
                        if (oldVal !== val) {
                            trackCellEdit(idx, col, oldVal, val);
                            currentRows[idx][col] = val;
                            changedCount++;
                        }
                    }
                });
                // Track that these edits came from Bulk Edit so the save flow
                // classifies them as bulk_row_edit (not inline row_edit)
                pendingBulkEditCount += changedCount;
                $modal.remove();
                refreshTable();
                showMsg("Bulk edit: set <strong>" + _.escape(col) + "</strong> to &ldquo;" +
                        _.escape(val) + "&rdquo; on " + changedCount + " row(s). " +
                        "Click <strong>Save Changes</strong> to persist.", "success");
            }

            // Check approval gate
            restPost({
                action: "check_approval_gate",
                gate_action: "bulk_row_edit",
                csv_file: selectedCsv,
                app_context: selectedApp,
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
                            submitBulkEditApproval(col, val, selectedIdxs.slice(), wouldChange, reason);
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
                    showMsg(formatDailyLimitMsg(gateData.daily_limit), "error"
                    );
                } else {
                    applyBulkEditLocally();
                }
            }).fail(function () {
                // Gate check failed — block edit (fail-closed for security)
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
            var isExpires = (expireColumn && $modal.find("#wl-bulk-col").val() === expireColumn);
            if (isExpires) {
                $modal.find("#wl-bulk-dp-date").focus();
            } else {
                $modal.find("#wl-bulk-val").focus();
            }
        }, 100);
    }

    // ══════════════════════════════════════════════════════════════════
    // Export Audit Trail as CSV
    // ══════════════════════════════════════════════════════════════════

    function exportAuditCsv() {
        showMsg("Fetching audit data&hellip;", "info");

        // Mirror the Action Log panel query from audit.xml, filtered by current CSV/rule.
        // Escape SPL metacharacters to prevent search injection.
        function splEscape(val) {
            return val.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        }
        var filterParts = '';
        if (selectedCsv) filterParts += ' csv_file="' + splEscape(selectedCsv) + '"';
        if (selectedRule) filterParts += ' detection_rule="' + splEscape(selectedRule) + '"';
        var searchQuery = 'search index=wl_audit sourcetype=wl_audit' + filterParts + ' | head 10000' +
            ' | stats values(value{}) as value values(*) as * by action csv_file analyst timestamp' +
            ' | sort -timestamp' +
            ' | eval timestamp=strftime(timestamp, "%d-%m-%Y %H:%M:%S GMT%:::z")' +
            ' | eval action_label=case(' +
            '     action=="row_removed_multiple", "removed",' +
            '     action=="row_removed",          "removed",' +
            '     action=="auto_removed",         "auto removed",' +
            '     action=="row_edited",           "edited",' +
            '     action=="row_added",            "added",' +
            '     action=="revert",               "reverted",' +
            '     action=="column_removed",       "removed column",' +
            '     action=="column_added",         "added column",' +
            '     action=="row_reordered",        "reordered row",' +
            '     action=="column_reordered",     "reordered column",' +
            '     action=="column_renamed",       "renamed column",' +
            '     action=="audit_exported",       "exported audit",' +
            '     action=="csv_exported",         "exported CSV",' +
            '     action=="csv_imported",         "imported CSV"' +
            '   )' +
            ' | eval row_change_count=case(' +
            '     action=="row_removed_multiple", removed_row_count,' +
            '     action=="row_removed",          removed_row_count,' +
            '     action=="auto_removed",         removed_row_count,' +
            '     action=="row_edited",           edited_row_count,' +
            '     action=="row_added",            added_row_count,' +
            '     action=="row_reordered",        1' +
            '   )' +
            ' | eval column_change_count=case(' +
            '     action=="column_removed",       column_count,' +
            '     action=="column_added",         column_count,' +
            '     action=="column_reordered",     1,' +
            '     action=="column_renamed",       column_count' +
            '   )' +
            ' | eval col_names=mvjoin(\'columns{}\', ", ")' +
            ' | eval summary=case(' +
            '     action_label="reverted",' +
            '       "User ".analyst." ".action_label." ".csv_file." ".reverted_from_version." ".row_count_before." row(s) version to ".reverted_to_version." ".row_count_after." row(s) version (which became the latest in the record ".new_record_version.") at ".timestamp,' +
            '     action=="column_removed",' +
            '       "User ".analyst." ".action_label." ".col_names." from ".csv_file." (".column_change_count." column(s), detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="column_added",' +
            '       "User ".analyst." ".action_label." ".col_names." to ".csv_file." (".column_change_count." column(s), detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="row_reordered",' +
            '       "User ".analyst." ".action_label." in ".csv_file." from position #".row_number_before." to #".row_number_after." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="column_reordered",' +
            '       "User ".analyst." ".action_label." \'".column_name."\' in ".csv_file." from position #".column_number_before." to #".column_number_after." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="column_renamed",' +
            '       "User ".analyst." ".action_label." \'".column_renamed_before."\' to \'".column_renamed_after."\' in ".csv_file." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="audit_exported",' +
            '       "User ".analyst." ".if(status=="success","successfully","unsuccessfully")." exported ".export_file." audit file containing ".event_count." event(s) for ".csv_file." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="csv_exported",' +
            '       "User ".analyst." ".if(status=="success","successfully","unsuccessfully")." exported ".export_file." containing ".row_count." row(s) for ".csv_file." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="csv_imported",' +
            '       "User ".analyst." ".if(status=="success","successfully","unsuccessfully")." ".import_mode." ".export_file." into ".csv_file." (".imported_row_count." row(s), detection rule - ".detection_rule.") at ".timestamp,' +
            '     1==1,' +
            '       "User ".analyst." ".action_label." ".row_change_count." row(s) from ".csv_file." (detection rule - ".detection_rule.") at ".timestamp' +
            '   )' +
            ' | eval value=mvjoin(value, " | ")' +
            ' | table timestamp action analyst csv_file detection_rule comment row_remove_reason row_change_count column_change_count status export_file import_mode value summary';

        $.ajax({
            url: Splunk.util.make_url("/splunkd/__raw/services/search/jobs"),
            type: "POST",
            data: {
                search: searchQuery,
                output_mode: "json",
                exec_mode: "oneshot",
                count: 10000
            },
            dataType: "json"
        })
        .done(function (data) {
            var results = data.results || [];
            if (!results.length) {
                showMsg("No audit events found.", "info");
                return;
            }

            var headers = ["timestamp", "action", "analyst", "csv_file", "detection_rule",
                           "comment", "row_remove_reason", "row_change_count", "column_change_count",
                           "status", "export_file", "import_mode", "value", "summary"];
            var lines = [headers.map(csvEscape).join(",")];
            results.forEach(function (row) {
                var vals = headers.map(function (h) {
                    var v = row[h];
                    if (Array.isArray(v)) v = v.join(" | ");
                    return csvEscape(v || "");
                });
                lines.push(vals.join(","));
            });

            var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
            var link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            var exportName = "wl_audit_export_" +
                (selectedCsv ? selectedCsv.replace(/\.csv$/i, "") + "_" : "") +
                new Date().toISOString().slice(0, 10) + ".csv";
            link.download = exportName;
            link.click();
            URL.revokeObjectURL(link.href);

            showMsg("Exported <strong>" + results.length + "</strong> audit events" +
                (selectedCsv ? " for " + _.escape(selectedCsv) : "") + ".", "success");
            restPost({
                action: "log_event",
                event_action: "audit_exported",
                csv_file: selectedCsv || "",
                detection_rule: selectedRule || "",
                app_context: selectedApp,
                status: "success",
                export_file: link.download,
                event_count: results.length,
                comment: ""
            });
        })
        .fail(function () {
            showMsg("Failed to export audit data.", "error");
            restPost({
                action: "log_event",
                event_action: "audit_exported",
                csv_file: selectedCsv || "",
                detection_rule: selectedRule || "",
                app_context: selectedApp,
                status: "failure",
                export_file: "",
                event_count: 0,
                comment: "Search query failed"
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Real-time Collaboration Indicators (user presence)
    // ══════════════════════════════════════════════════════════════════

    var presenceTimer = null;
    var currentUser = "";
    var lastActivityTime = Date.now();
    var IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

    // Track user activity — any meaningful interaction resets the idle timer
    (function trackActivity() {
        var events = "click.wlactivity keydown.wlactivity input.wlactivity mousedown.wlactivity";
        $(document).off(events).on(events, function () {
            lastActivityTime = Date.now();
        });
    })();

    function getCurrentUser() {
        if (currentUser) { return; }
        try {
            // Splunk JS SDK provides the current user
            var currentUserModel = mvc.Components.getInstance("env");
            if (currentUserModel) {
                currentUser = currentUserModel.get("user") || "";
            }
        } catch (e) { /* ignore */ }

        // Fallback: extract from page
        if (!currentUser) {
            try {
                currentUser = $(".user-name").text().trim() || Splunk.util.getConfigValue("USERNAME") || "";
            } catch (e) { /* ignore */ }
        }
    }

    function startPresenceMonitoring() {
        stopPresenceMonitoring();
        if (!selectedCsv) { return; }
        getCurrentUser();
        reportPresence();
        presenceTimer = setInterval(reportPresence, 15000);
    }

    function stopPresenceMonitoring() {
        if (presenceTimer) { clearInterval(presenceTimer); presenceTimer = null; }
    }

    function reportPresence() {
        if (!selectedCsv || !currentUser) { return; }

        // Check if THIS user is idle — auto-kick locally
        var idleMs = Date.now() - lastActivityTime;
        if (idleMs >= IDLE_TIMEOUT_MS) {
            stopPresenceMonitoring();
            showPresenceFullModal(
                "You have been idle for 30 minutes and your session on this CSV has been released."
            );
            return;
        }

        restGet({
            action:        "report_presence",
            csv_file:      selectedCsv,
            app:           selectedApp || "",
            user:          currentUser,
            last_activity: Math.floor(lastActivityTime / 1000)
        })
        .done(function (data) {
            if (data.presence_full) {
                stopPresenceMonitoring();
                showPresenceFullModal(data.error || "Maximum number of simultaneous users reached for this CSV file.");
                return;
            }
            if (data.idle_kicked) {
                stopPresenceMonitoring();
                showPresenceFullModal(data.error || "You have been idle too long and your session was released.");
                return;
            }
            renderPresenceBar(data.active_users || []);
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(selectedCsv);
                return;
            }
            try {
                var data = JSON.parse(xhr.responseText);
                if (data.presence_full) {
                    stopPresenceMonitoring();
                    showPresenceFullModal(data.error || "Maximum number of simultaneous users reached for this CSV file.");
                }
            } catch (e) { /* ignore */ }
        });
    }

    function showPresenceFullModal(message) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">CSV Busy</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0;color:#e74c3c">' + _.escape(message) + '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn btn-primary" id="wl-presence-full-ok">OK</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        function dismiss() {
            $modal.remove();
            $(document).off("keydown.wlpresence");
            // Reset to initial state
            $ruleClear.trigger("click");
        }
        $modal.on("click", "#wl-presence-full-ok", dismiss);
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { dismiss(); }
        });
        $(document).off("keydown.wlpresence").on("keydown.wlpresence", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) { dismiss(); }
        });
    }

    function handleCsvRemoved(csvName) {
        stopChangeMonitoring();
        stopPresenceMonitoring();
        $(".wl-modal-overlay").remove();
        var displayName = csvName || selectedCsv || "This CSV";
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">CSV Removed</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0">' +
                        '<strong>' + _.escape(displayName) + '</strong> has been removed ' +
                        'by an administrator and is no longer available.' +
                    '</p>' +
                    '<p style="margin:8px 0 0;font-size:13px;color:var(--wl-muted-text,#999)">' +
                        'If this was unexpected, contact your admin. ' +
                        'Removed files can be restored from the Trash in the Control Panel.' +
                    '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn btn-primary" id="wl-csv-removed-ok">OK</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        function dismiss() {
            $modal.remove();
            $(document).off("keydown.wlcsvremoved");
            $ruleClear.trigger("click");
        }
        $modal.on("click", "#wl-csv-removed-ok", dismiss);
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { dismiss(); }
        });
        $(document).off("keydown.wlcsvremoved").on("keydown.wlcsvremoved", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) { dismiss(); }
        });
    }

    function renderPresenceBar(users) {
        var $bar = $table.find("#wl-presence-bar");
        if (!$bar.length) {
            $bar = $('<div id="wl-presence-bar" class="wl-presence-bar"></div>');
            $table.prepend($bar);
        }

        if (!users.length || (users.length === 1 && users[0] === currentUser)) {
            $bar.empty().removeClass("wl-presence-active");
            return;
        }

        var otherUsers = users.filter(function (u) { return u !== currentUser; });
        if (!otherUsers.length) {
            $bar.empty().removeClass("wl-presence-active");
            return;
        }

        var PRESENCE_SHOW_MAX = 5;
        var visible = otherUsers.slice(0, PRESENCE_SHOW_MAX);
        var hidden  = otherUsers.slice(PRESENCE_SHOW_MAX);

        var html = '<span style="margin-right:4px">Also viewing:</span>';
        visible.forEach(function (user) {
            html += '<span class="wl-presence-user">' +
                    '<span class="wl-presence-dot"></span>' +
                    _.escape(user) + '</span>';
        });
        if (hidden.length) {
            html += '<span class="wl-presence-toggle" ' +
                    'style="cursor:pointer;color:var(--wl-link,#5ba0d0);margin-left:4px;font-weight:600" ' +
                    'title="Click to show all">+' + hidden.length + ' more</span>';
            html += '<span class="wl-presence-hidden" style="display:none">';
            hidden.forEach(function (user) {
                html += '<span class="wl-presence-user">' +
                        '<span class="wl-presence-dot"></span>' +
                        _.escape(user) + '</span>';
            });
            html += '</span>';
        }
        $bar.html(html).addClass("wl-presence-active");
        $bar.find(".wl-presence-toggle").off("click").on("click", function () {
            var $hidden = $bar.find(".wl-presence-hidden");
            if ($hidden.is(":visible")) {
                $hidden.hide();
                $(this).text("+" + hidden.length + " more");
            } else {
                $hidden.show();
                $(this).text("show less");
            }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Add Bulk Edit and Audit Export buttons to table action bar
    // ══════════════════════════════════════════════════════════════════

    var origRefreshTable = refreshTable;
    refreshTable = function () {
        origRefreshTable();

        // Add Audit Export button in the right section
        var $rightSection = $table.find(".wl-buttons-right");
        if ($rightSection.length && !$table.find("#btn-audit-export").length) {
            $rightSection.prepend(
                '<button class="btn" id="btn-audit-export" title="Export audit trail as CSV">Export Audit</button> '
            );
        }

        // Update Bulk Edit button state based on selection
        updateBulkEditBtn();
    };

    function updateBulkEditBtn() {
        var checked = Object.keys(selectedIdxSet).length;
        $table.find("#btn-bulk-edit").prop("disabled", checked === 0);
    }

    // Bind Bulk Edit button
    $table.on("click.wl", "#btn-bulk-edit", function () {
        showBulkEditModal();
    });

    // Bind Audit Export button
    $table.on("click.wl", "#btn-audit-export", function () {
        exportAuditCsv();
    });

    // Update bulk edit button when checkboxes change
    var origUpdateRemoveSelectedBtn = updateRemoveSelectedBtn;
    updateRemoveSelectedBtn = function () {
        origUpdateRemoveSelectedBtn();
        updateBulkEditBtn();
    };

    // ══════════════════════════════════════════════════════════════════
    // Initialization
    // ══════════════════════════════════════════════════════════════════
    loadRules();

    // Auto-refresh when a create_csv or create_rule approval comes through
    // for the currently selected rule (so analyst doesn't need to reload).
    var _seenApprovalIds = {};
    var _notifFirstPoll = true;
    window.__wlNotifCallbacks = window.__wlNotifCallbacks || [];
    window.__wlNotifCallbacks.push(function (notifs) {
        if (_notifFirstPoll) {
            // Seed with all existing notifications so we only react to NEW ones
            notifs.forEach(function (n) { _seenApprovalIds[n.id] = true; });
            _notifFirstPoll = false;
            return;
        }
        var needsRefresh = false;
        var needsRuleRefresh = false;
        notifs.forEach(function (n) {
            if (_seenApprovalIds[n.id]) return;
            _seenApprovalIds[n.id] = true;
            if (n.type !== "approved" && n.type !== "cancelled") return;
            var extra = n.extra || {};
            var nRule = extra.detection_rule || "";
            var nCsv = extra.csv_file || "";
            // Refresh if the notification affects the currently viewed CSV/rule
            if (selectedCsv && nCsv === selectedCsv) {
                needsRefresh = true;
            } else if (selectedRule && nRule === selectedRule) {
                needsRefresh = true;
            }
            // Rule-level operations (create/remove rule) need full rule list refresh
            var ruleOps = ["create_rule", "remove_rule",
                           "create_csv", "remove_csv"];
            if (ruleOps.indexOf(extra.action_type || "") !== -1) {
                needsRuleRefresh = true;
            }
        });
        if (needsRefresh || needsRuleRefresh) {
            if (needsRuleRefresh) { loadRules(); }
            var ruleToRefresh = selectedRule;
            var csvToRefresh = selectedCsv;
            if (ruleToRefresh && csvToRefresh) {
                setTimeout(function () {
                    if (selectedRule === ruleToRefresh) {
                        loadCsv(csvToRefresh, selectedApp);
                    }
                }, 300);
            } else if (ruleToRefresh) {
                setTimeout(function () {
                    selectRule(ruleToRefresh);
                }, 500);
            }
        }
    });

    // Start presence monitoring whenever CSV is loaded
    var origLoadCsv = loadCsv;
    loadCsv = function (csvFile, appContext) {
        origLoadCsv(csvFile, appContext);
        startPresenceMonitoring();
    };

    // Stop presence on page unload
    $(window).on("beforeunload", function () {
        stopChangeMonitoring();
        stopPresenceMonitoring();
    });

});
