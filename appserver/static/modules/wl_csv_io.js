/**
 * wl_csv_io.js — CSV parsing, validation, import, and export
 *
 * Module 8 of the Whitelist Manager modularization.
 * Handles: RFC 4180 CSV parsing, import validation, import preview/messages,
 *          CSV export with injection protection, import flow (merge/replace),
 *          and import approval submission.
 */
define([
    "jquery",
    "underscore",
    "app/wl_manager/modules/wl_constants",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui"
], function ($, _, C, REST, UI) {
    "use strict";

    // ── Constants ────────────────────────────────────────────────────────
    var MAX_ROWS       = C.MAX_ROWS;
    var MAX_COLUMNS    = C.MAX_COLUMNS;
    var MAX_CELL_CHARS = C.MAX_CELL_CHARS;
    var IMPORT_PREVIEW_ROWS    = C.IMPORT_PREVIEW_ROWS;
    var IMPORT_MAX_ERRORS      = C.IMPORT_MAX_ERRORS;
    var IMPORT_MAX_WARN_EXAMPLES = C.IMPORT_MAX_WARN_EXAMPLES;
    var SAFE_COLNAME_RE        = C.SAFE_COLNAME_RE;
    var EXPIRE_COLUMN_NAMES_LIST = C.EXPIRE_COLUMN_NAMES_LIST;
    var VALID_EXPIRE_RE        = C.VALID_EXPIRE_RE;
    var NON_ASCII_RE           = C.NON_ASCII_RE;

    var MAX_IMPORT_SIZE = 5 * 1024 * 1024; // 5 MB

    // Column names treated as expiration dates (mirrors backend EXPIRE_COLUMN_NAMES)
    var EXPIRE_COLUMN_NAMES = ["expires", "expire", "expiration", "expiration_date",
                               "expiry", "termination", "termination_date"];

    // ── Module shortcuts (from deps) ─────────────────────────────────────
    var restPost           = REST.restPost;
    var showMsg            = UI.showMsg;
    var formatDailyLimitMsg = UI.formatDailyLimitMsg;

    // ── State proxy + callbacks (set by init) ────────────────────────────
    var S        = {};   // state proxy (getter/setter to entry-point vars)
    var _actions = {};   // callbacks: syncInputs, refreshTable, loadCsv

    // ══════════════════════════════════════════════════════════════════════
    // RFC 4180-compliant CSV parser
    // ══════════════════════════════════════════════════════════════════════

    // Handles quoted fields, embedded commas, double-quote escaping,
    // BOM, mixed line endings.
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
                errors.push("Line " + (r + 2) + " (data row " + (r + 1) + ") has " + arr.length +
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

    // ══════════════════════════════════════════════════════════════════════
    // Import validation pipeline
    // ══════════════════════════════════════════════════════════════════════

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
        var nonAsciiErrors = [];

        if (rows.length <= MAX_ROWS && headers.length <= MAX_COLUMNS) {
            for (var ri = 0; ri < rows.length; ri++) {
                for (var hi2 = 0; hi2 < headers.length; hi2++) {
                    var col = headers[hi2];
                    var val = rows[ri][col] || "";
                    if (typeof val !== "string") { val = String(val); }

                    // Cell length
                    if (val.length > MAX_CELL_CHARS && cellLengthErrors.length < IMPORT_MAX_ERRORS) {
                        cellLengthErrors.push("Line " + (ri + 2) + " (data row " + (ri + 1) + "), column '" +
                            _.escape(col.substring(0, 20)) + "' exceeds " + MAX_CELL_CHARS + " characters.");
                    }

                    // Control chars / null bytes / embedded newlines
                    if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\t\n\r]/.test(val)) {
                        var issue = "Line " + (ri + 2) + " (data row " + (ri + 1) + "), column '" + _.escape(col.substring(0, 20)) + "': contains ";
                        if (/\x00/.test(val)) { issue += "null byte"; }
                        else if (/[\n\r]/.test(val)) { issue += "embedded newline"; }
                        else if (/\t/.test(val)) { issue += "tab character"; }
                        else { issue += "control character"; }
                        sanitizationIssues.push(issue);
                    }

                    // Non-ASCII characters
                    if (NON_ASCII_RE.test(val) && nonAsciiErrors.length < IMPORT_MAX_ERRORS) {
                        nonAsciiErrors.push("Line " + (ri + 2) + " (data row " + (ri + 1) + "), column '" +
                            _.escape(col.substring(0, 20)) + "': contains non-ASCII characters.");
                    }

                    // Expires date validation
                    if (expireCol && col === expireCol && val.trim() &&
                        expireDateErrors.length < 5) {
                        if (!VALID_EXPIRE_RE.test(val.trim())) {
                            expireDateErrors.push("line " + (ri + 2) + " (data row " + (ri + 1) + "): '" +
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

        // Add non-ASCII errors as blocking
        nonAsciiErrors.forEach(function (e) { errors.push(e); });

        // Detect encoding-corrupted cells (e.g. ???? from Excel ANSI save)
        if (rows.length <= MAX_ROWS && headers.length <= MAX_COLUMNS) {
            for (var qi = 0; qi < rows.length && errors.length < IMPORT_MAX_ERRORS; qi++) {
                for (var qj = 0; qj < headers.length; qj++) {
                    var qval = (rows[qi][headers[qj]] || "").trim();
                    if (qval.length > 0 && /^[?\s]+$/.test(qval)) {
                        errors.push("Line " + (qi + 2) + " (data row " + (qi + 1) +
                            "), column '" + _.escape(headers[qj].substring(0, 20)) +
                            "': value '" + _.escape(qval.substring(0, 20)) +
                            "' appears to be encoding corruption (only ? characters).");
                        break;
                    }
                }
            }
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

    // ══════════════════════════════════════════════════════════════════════
    // Import preview & message renderers
    // ══════════════════════════════════════════════════════════════════════

    // Preview table — first N rows, scrollable, read-only.
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

    // ══════════════════════════════════════════════════════════════════════
    // CSV Export
    // ══════════════════════════════════════════════════════════════════════

    // Neutralize formula-dangerous prefixes (CSV injection protection)
    function csvEscape(val) {
        if (/^[=+\-@\t\r]/.test(val)) {
            val = "'" + val;
        }
        if (val.indexOf(",") !== -1 || val.indexOf('"') !== -1 || val.indexOf("\n") !== -1) {
            return '"' + val.replace(/"/g, '""') + '"';
        }
        return val;
    }

    function exportCsv() {
        _actions.syncInputs();

        // Build CSV string (exclude internal _ columns)
        var visibleHeaders = S.currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });

        var lines = [visibleHeaders.map(csvEscape).join(",")];
        S.currentRows.forEach(function (row) {
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
        link.download = S.selectedCsv || "whitelist_export.csv";
        link.click();
        URL.revokeObjectURL(link.href);

        restPost({
            action: "log_event",
            event_action: "csv_exported",
            csv_file: S.selectedCsv,
            detection_rule: S.selectedRule || "",
            app_context: S.selectedApp,
            status: "success",
            export_file: link.download,
            row_count: S.currentRows.length,
            comment: ""
        });
    }

    // ══════════════════════════════════════════════════════════════════════
    // CSV Import
    // ══════════════════════════════════════════════════════════════════════

    function validateExpireDates(headers, rows) {
        var expCol = null;
        for (var i = 0; i < headers.length; i++) {
            if (EXPIRE_COLUMN_NAMES.indexOf(headers[i].trim().toLowerCase()) !== -1) {
                expCol = headers[i];
                break;
            }
        }
        if (!expCol) { return { invalid: [], expired: [] }; }

        // Regex: YYYY-MM-DD (optional: space + HH:MM) (optional: space + UTC)
        var dateRe = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])( ([01]\d|2[0-3]):[0-5]\d)?( UTC)?$/;
        var now = new Date();
        var invalid = [];
        var expired = [];
        var expiredCount = 0;
        for (var r = 0; r < rows.length; r++) {
            var val = (rows[r][expCol] || "").trim();
            if (!val) { continue; } // empty = permanent, OK
            if (!dateRe.test(val)) {
                invalid.push({ row: r + 1, line: r + 2, value: val });
                if (invalid.length >= 10) { break; }
            } else {
                // Valid format — check if expired
                var datePart = val.substring(0, 10); // YYYY-MM-DD
                var expDate = new Date(datePart + "T23:59:59");
                if (expDate < now) {
                    expiredCount++;
                    // Keep first 5 examples for display, skip the rest
                    if (expired.length < 5) {
                        expired.push({ row: r + 1, line: r + 2, value: val });
                    }
                }
            }
        }
        return { invalid: invalid, expired: expired, expiredCount: expiredCount };
    }

    function logImportEvent(fileName, status, comment, importedCount, headerCount, importMode, rowsBefore) {
        restPost({
            action: "log_event",
            event_action: "csv_imported",
            csv_file: S.selectedCsv,
            detection_rule: S.selectedRule || "",
            app_context: S.selectedApp,
            status: status,
            export_file: fileName,
            row_count_before: rowsBefore != null ? rowsBefore : S.currentRows.length,
            row_count_after: S.currentRows.length,
            header_count: headerCount,
            imported_row_count: importedCount,
            import_mode: importMode || "",
            comment: comment
        });
    }

    function importCsv(file) {
        if (S.csvLocked) {
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
        // Phase 1: Read as raw bytes to detect non-ASCII BEFORE text decoding.
        // FileReader.readAsText() silently converts non-ASCII bytes to '?',
        // making them invisible to post-decode validation.
        var rawReader = new FileReader();
        rawReader.onload = function (e) {
            var bytes = new Uint8Array(e.target.result);

            // Scan raw bytes for non-ASCII (anything > 0x7F)
            var nonAsciiLines = [];
            var lineNum = 1;  // 1-based (header = line 1)
            for (var i = 0; i < bytes.length && nonAsciiLines.length < 5; i++) {
                if (bytes[i] === 0x0A) { lineNum++; continue; }
                if (bytes[i] === 0x0D) { continue; }  // skip CR
                if (bytes[i] > 0x7F) {
                    // Skip UTF-8 BOM at start (EF BB BF)
                    if (i <= 2 && bytes[0] === 0xEF && bytes[1] === 0xBB && bytes[2] === 0xBF) {
                        i = 2; // skip BOM bytes
                        continue;
                    }
                    nonAsciiLines.push("Line " + lineNum + " (byte position " + i +
                        ", value 0x" + bytes[i].toString(16).toUpperCase() + ")");
                    // Skip to next line to avoid flooding
                    while (i < bytes.length && bytes[i] !== 0x0A) { i++; }
                }
            }
            if (nonAsciiLines.length) {
                showMsg(
                    "Import blocked — non-ASCII characters detected in the file:<br>" +
                    nonAsciiLines.join("<br>") +
                    (nonAsciiLines.length >= 5 ? "<br>...and possibly more" : "") +
                    "<br><br>Only ASCII characters are allowed. " +
                    "If your CSV was saved from Excel, re-save as <strong>CSV UTF-8</strong> " +
                    "and remove any non-Latin characters.",
                    "error"
                );
                logImportEvent(file.name, "failure", "Non-ASCII bytes in " + nonAsciiLines.length + " line(s)", 0, 0, "");
                return;
            }

            // Phase 2: Bytes are clean — now decode as text and continue validation
            var text = new TextDecoder("utf-8").decode(bytes);
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

            // Detect encoding-corrupted cells (e.g. Excel ANSI save destroying Cyrillic → ????)
            var corruptCells = [];
            for (var qi = 0; qi < importRows.length && corruptCells.length < 5; qi++) {
                for (var qj = 0; qj < importHeaders.length; qj++) {
                    var qval = (importRows[qi][importHeaders[qj]] || "").trim();
                    if (qval.length > 0 && /^[?\s]+$/.test(qval)) {
                        corruptCells.push("Line " + (qi + 2) + " (data row " + (qi + 1) +
                            "), column '" + _.escape(importHeaders[qj].substring(0, 20)) +
                            "': value is <code>" + _.escape(qval.substring(0, 20)) + "</code>");
                        break;
                    }
                }
            }
            if (corruptCells.length) {
                showMsg(
                    "Import blocked — cells containing only <code>?</code> characters detected " +
                    "(likely encoding corruption):<br>" +
                    corruptCells.join("<br>") +
                    (corruptCells.length >= 5 ? "<br>...and possibly more" : "") +
                    "<br><br>This usually means the CSV was saved from Excel as " +
                    "<strong>CSV (Comma delimited)</strong> instead of " +
                    "<strong>CSV UTF-8 (Comma delimited)</strong>, which destroys non-Latin characters." +
                    "<br>Please re-save the file in Excel using <strong>File → Save As → CSV UTF-8</strong>.",
                    "error"
                );
                logImportEvent(file.name, "failure", "Encoding-corrupted cells in " + corruptCells.length + " row(s)", 0, importHeaders.length, "");
                return;
            }

            // Validate expiration date formats before allowing import
            var dateResult = validateExpireDates(importHeaders, importRows);
            if (dateResult.invalid.length) {
                var examples = dateResult.invalid.slice(0, 5).map(function (b) {
                    return "Line " + b.line + " (data row " + b.row + "): <code>" + _.escape(b.value.substring(0, 60)) + "</code>";
                }).join("<br>");
                var moreMsg = dateResult.invalid.length > 5 ? "<br>...and " + (dateResult.invalid.length - 5) + " more" : "";
                showMsg(
                    "Import blocked — invalid date format in expiration column:<br>" +
                    examples + moreMsg +
                    "<br><br>Expected: <code>YYYY-MM-DD HH:MM UTC</code> or <code>YYYY-MM-DD</code>" +
                    "<br><small>Line numbers match your CSV editor (line 1 = header row).</small>",
                    "error"
                );
                logImportEvent(file.name, "failure", "Invalid expiration dates in " + dateResult.invalid.length + " row(s)", 0, importHeaders.length, "");
                return;
            }

            // Show modal to choose Replace or Merge
            showImportModeModal(file.name, importHeaders, importRows, {
                rows: dateResult.expired,
                count: dateResult.expiredCount
            });
        };
        rawReader.readAsArrayBuffer(file);
    }

    function showImportModeModal(fileName, importHeaders, importRows, expiredInfo) {
        $(".wl-modal-overlay").remove();

        // Build expired-date warning HTML (if any)
        var expiredHtml = "";
        var expiredRows = (expiredInfo && expiredInfo.rows) || [];
        var expiredTotal = (expiredInfo && expiredInfo.count) || 0;
        if (expiredTotal > 0) {
            var expExamples = expiredRows.map(function (e) {
                return "Line " + e.line + " (data row " + e.row + "): <code>" +
                    _.escape(e.value) + "</code>";
            }).join("<br>");
            var expMore = expiredTotal > expiredRows.length
                ? "<br>...and " + (expiredTotal - expiredRows.length) + " more"
                : "";
            expiredHtml =
                '<div class="wl-import-expired-warning">' +
                    '<strong>&#9888; ' + expiredTotal + ' row' +
                    (expiredTotal !== 1 ? 's have' : ' has') +
                    ' expired date' + (expiredTotal !== 1 ? 's' : '') +
                    ' and will be auto-removed after import:</strong><br>' +
                    expExamples + expMore +
                    '<br><small>' +
                    'These rows will be saved but removed when the CSV is next loaded.' +
                    '</small>' +
                '</div>';
        }

        var $modal = $(
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Import CSV &mdash; ' + _.escape(fileName) + '</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>This file has <strong>' + importRows.length + '</strong> row(s) and <strong>' + importHeaders.length + '</strong> column(s).</p>' +
                        expiredHtml +
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

    function submitImportReplaceApproval(fileName, importHeaders, importRows) {
        var description = "Import Replace from " + fileName + " (" + importRows.length + " rows)";

        showMsg("Submitting import approval request&hellip;", "info");

        restPost({
            action: "submit_approval",
            approval_action_type: "csv_import_replace",
            csv_file: S.selectedCsv,
            app_context: S.selectedApp,
            detection_rule: S.selectedRule || "",
            description: description,
            original_payload: {
                action: "save_csv",
                csv_file: S.selectedCsv,
                app_context: S.selectedApp,
                detection_rule: S.selectedRule || "",
                headers: importHeaders,
                rows: importRows,
                comment: "CSV import replace from " + fileName + " - approved",
                removal_reasons: []
            },
            expected_mtime: S.loadedMtime,
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
            _actions.loadCsv(S.selectedCsv, S.selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit import approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function submitImportMergeApproval(fileName, mergedHeaders, mergedRows, newUniqueRows) {
        var newRowCount = newUniqueRows.length;
        var description = "Import Merge from " + fileName + " (+" + newRowCount + " rows, " + mergedRows.length + " total)";

        // Build row_keys for the new rows — backend replay uses these to
        // identify which rows in the stored payload are "new" vs "existing".
        var visHeaders = mergedHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });
        var rowKeys = newUniqueRows.map(function (row) {
            return visHeaders.map(function (h) { return row[h] || ""; });
        });

        showMsg("Submitting import merge approval request&hellip;", "info");

        restPost({
            action: "submit_approval",
            approval_action_type: "bulk_row_addition",
            csv_file: S.selectedCsv,
            app_context: S.selectedApp,
            detection_rule: S.selectedRule || "",
            description: description,
            original_payload: {
                action: "save_csv",
                csv_file: S.selectedCsv,
                app_context: S.selectedApp,
                detection_rule: S.selectedRule || "",
                headers: mergedHeaders,
                rows: mergedRows,
                comment: "CSV import merge from " + fileName + " - approved",
                removal_reasons: []
            },
            expected_mtime: S.loadedMtime,
            pending_highlight: { type: "rows", row_keys: rowKeys, headers: visHeaders },
            selected_count: newRowCount
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Import Merge requires approval (+" + newRowCount + " rows). Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            _actions.loadCsv(S.selectedCsv, S.selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit import merge approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function doImportReplace(fileName, importHeaders, importRows) {
        var rowsBefore = S.currentRows.length;

        // Full replacement: adopt imported headers and rows
        S.currentHeaders = importHeaders.slice();
        S.currentRows = importRows.map(function (r) { return $.extend({}, r); });

        _actions.refreshTable();
        showMsg(
            "Replaced with <strong>" + importRows.length + "</strong> row(s) from " +
            "<strong>" + _.escape(fileName) + "</strong>. " +
            "Review and click <strong>Save Changes</strong> to persist.",
            "success"
        );
        logImportEvent(fileName, "success", "", importRows.length, importHeaders.length, "replace", rowsBefore);
    }

    function doImportMerge(fileName, importHeaders, importRows) {
        var rowsBefore = S.currentRows.length;

        // Validate merge row limit (current + import combined)
        if (S.currentRows.length + importRows.length > MAX_ROWS) {
            showMsg(
                "Merge would result in <strong>" + (S.currentRows.length + importRows.length) +
                "</strong> rows, maximum allowed is <strong>" + MAX_ROWS +
                "</strong>. Current: " + S.currentRows.length + ", import: " + importRows.length + ".",
                "error"
            );
            logImportEvent(fileName, "failure", "Row limit exceeded on merge (" + (S.currentRows.length + importRows.length) + " rows)", 0, importHeaders.length, "merge", rowsBefore);
            return;
        }

        // Validate that import headers match (at minimum) existing headers
        var missingHeaders = [];
        S.currentHeaders.forEach(function (h) {
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
        var keyHeaders = S.currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_" && h !== "Comment" && h !== S.expireColumn;
        });
        S.currentRows.forEach(function (row) {
            var key = keyHeaders.map(function (h) { return row[h] || ""; }).join("||");
            existingKeys[key] = true;
        });

        var newUniqueRows = [];
        var tempKeys = $.extend({}, existingKeys);
        importRows.forEach(function (importRow) {
            var key = keyHeaders.map(function (h) { return importRow[h] || ""; }).join("||");
            if (!tempKeys[key]) {
                var newRow = {};
                S.currentHeaders.forEach(function (h) {
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
            newUniqueRows.forEach(function (row) { S.currentRows.push(row); });
            _actions.refreshTable();
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
            csv_file: S.selectedCsv,
            app_context: S.selectedApp,
            selected_count: newUniqueRows.length
        }).done(function (gateData) {
            if (gateData.requires_approval) {
                // Submit for admin approval with the merged result
                var mergedRows = S.currentRows.slice();
                newUniqueRows.forEach(function (row) {
                    mergedRows.push($.extend({}, row));
                });
                submitImportMergeApproval(fileName, S.currentHeaders.slice(), mergedRows, newUniqueRows);
                logImportEvent(fileName, "pending",
                    "Submitted for approval: adding " + newUniqueRows.length + " rows",
                    newUniqueRows.length, importHeaders.length, "merge", rowsBefore);
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

    // ══════════════════════════════════════════════════════════════════════
    // Simple CSV parser (for import flow — line-based, not RFC 4180)
    // ══════════════════════════════════════════════════════════════════════

    function parseCsvText(text) {
        // Strip UTF-8 BOM (Excel saves CSV with BOM)
        if (text.charCodeAt(0) === 0xFEFF) { text = text.substring(1); }
        var lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
        lines = lines.filter(function (l) { return l.trim() !== ""; });
        if (lines.length < 1) { return null; }

        var headers = parseCsvLine(lines[0]).map(function (h) { return h.trim(); });
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

    // ══════════════════════════════════════════════════════════════════════
    // Public API
    // ══════════════════════════════════════════════════════════════════════

    return {
        init: function (opts) {
            S        = opts.state;
            _actions = opts.actions;
        },

        // Used by wl_modals (create CSV from file upload)
        parseCSV:             parseCSV,
        validateImportedCSV:  validateImportedCSV,
        renderImportPreview:  renderImportPreview,
        renderImportMessages: renderImportMessages,

        // Used by entry point (toolbar buttons)
        exportCsv:  exportCsv,
        importCsv:  importCsv,

        // Used by entry point (audit export)
        csvEscape:  csvEscape,

        // Used by approved import-replace replay
        doImportReplace: doImportReplace
    };
});
