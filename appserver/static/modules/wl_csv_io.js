/**
 * wl_csv_io.js - CSV Import/Export Module
 *
 * Handles CSV import and export operations with validation and preview.
 * Export: Downloads current rows as CSV file
 * Import: File picker, parse, validate headers, show preview, update state
 *
 * Public API: init(), exportCSV(), importCSV(), parseCSV(text), validateCSV(data)
 *
 * Events:
 *   - Fires: wl:csvImported — {rowCount, filename} on successful import
 */

define([
    'modules/wl_constants',
    'modules/wl_state',
    'modules/wl_ui'
], function(Constants, State, UI) {
    'use strict';

    var MAX_IMPORT_SIZE = 5 * 1024 * 1024; // 5 MB
    var MAX_ROWS = 5000;
    var MAX_COLUMNS = 100;

    // Column names treated as expiration dates (from backend EXPIRE_COLUMN_NAMES)
    var EXPIRE_COLUMN_NAMES = [
        'expires', 'expire', 'expiration', 'expiration_date',
        'expiry', 'termination', 'termination_date'
    ];

    /**
     * Initialize CSV I/O module.
     * Register required state keys.
     */
    function init() {
        State.register('importedRowsPreview', null);
    }

    /**
     * Export current rows as downloadable CSV file.
     * Filename: {detection_rule}_{csv_file}_{timestamp}.csv
     * Excludes internal _ prefixed columns.
     */
    function exportCSV() {
        var currentRows = State.get('currentRows') || [];
        var currentHeaders = State.get('currentHeaders') || [];
        var selectedRule = State.get('selectedRule') || '';
        var selectedCsv = State.get('csvFileSelected') || 'whitelist_export';

        // Filter out internal _ columns
        var visibleHeaders = currentHeaders.filter(function(h) {
            return h && h.charAt(0) !== '_';
        });

        if (!visibleHeaders.length) {
            UI.showMsg('No columns to export.', 'warning');
            return;
        }

        // Build CSV text
        var lines = [visibleHeaders.map(csvEscape).join(',')];
        currentRows.forEach(function(row) {
            var vals = visibleHeaders.map(function(h) {
                return csvEscape((row[h] || '').toString());
            });
            lines.push(vals.join(','));
        });

        var csvText = lines.join('\n');

        // Trigger browser download
        var timestamp = new Date().toISOString().replace(/[:.]/g, '-').substring(0, 19);
        var filename = selectedRule + '_' + selectedCsv + '_' + timestamp + '.csv';

        var blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
        var link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);

        UI.showMsg('CSV exported: ' + filename, 'success');

        // Fire custom event
        $(document).trigger('wl:csvExported', {
            filename: filename,
            rowCount: currentRows.length,
            columnCount: visibleHeaders.length
        });
    }

    /**
     * Show file picker and import CSV file.
     * Validates headers, shows preview modal, updates state on confirm.
     */
    function importCSV() {
        var currentHeaders = State.get('currentHeaders') || [];
        var csvLocked = State.get('csvLocked') || false;

        if (csvLocked) {
            UI.showMsg('This CSV is locked by a pending approval request.', 'error');
            return;
        }

        if (!currentHeaders.length) {
            UI.showMsg('Load a CSV first before importing.', 'error');
            return;
        }

        // Create file input element
        var $fileInput = $('<input type="file" accept=".csv" style="display:none">');
        $fileInput.on('change', function() {
            var file = this.files[0];
            if (file) {
                importFile(file, currentHeaders);
            }
        });

        document.body.appendChild($fileInput);
        $fileInput.click();
        document.body.removeChild($fileInput);
    }

    /**
     * Parse CSV text file.
     * Returns {headers: [], rows: []} or null on error.
     * Handles quoted fields and embedded newlines per RFC 4180.
     *
     * @param {string} text - Raw CSV text
     * @return {Object|null} Parsed CSV or null
     */
    function parseCSV(text) {
        if (!text) {
            return null;
        }

        // Check for binary content
        if (/[\x00-\x08\x0B-\x0C\x0E-\x1F]/.test(text.substring(0, 512))) {
            return null;
        }

        var lines = [];
        var currentLine = '';
        var inQuotes = false;

        // Split into lines handling quoted newlines
        for (var i = 0; i < text.length; i++) {
            var ch = text[i];

            if (ch === '"') {
                inQuotes = !inQuotes;
                currentLine += ch;
            } else if ((ch === '\n' || ch === '\r') && !inQuotes) {
                if (currentLine) {
                    lines.push(currentLine);
                    currentLine = '';
                }
                if (ch === '\r' && text[i + 1] === '\n') {
                    i++; // Skip \n after \r
                }
            } else {
                currentLine += ch;
            }
        }

        if (currentLine) {
            lines.push(currentLine);
        }

        if (!lines.length) {
            return null;
        }

        // Parse header row
        var headers = parseCSVLine(lines[0]);
        if (!headers || !headers.length) {
            return null;
        }

        // Parse data rows
        var rows = [];
        for (var r = 1; r < lines.length; r++) {
            var values = parseCSVLine(lines[r]);
            if (values) {
                var row = {};
                for (var c = 0; c < headers.length; c++) {
                    row[headers[c]] = values[c] || '';
                }
                rows.push(row);
            }
        }

        return {
            headers: headers,
            rows: rows
        };
    }

    /**
     * Parse single CSV line.
     * Handles quoted fields and escaped quotes.
     *
     * @param {string} line - CSV line
     * @return {Array} Parsed fields
     */
    function parseCSVLine(line) {
        var fields = [];
        var field = '';
        var inQuotes = false;

        for (var i = 0; i < line.length; i++) {
            var ch = line[i];

            if (ch === '"') {
                if (inQuotes && line[i + 1] === '"') {
                    field += '"';
                    i++; // Skip next quote
                } else {
                    inQuotes = !inQuotes;
                }
            } else if (ch === ',' && !inQuotes) {
                fields.push(field.trim());
                field = '';
            } else {
                field += ch;
            }
        }

        fields.push(field.trim());
        return fields;
    }

    /**
     * Validate imported CSV headers match current CSV.
     * Returns {valid: boolean, errors: [], warnings: []}
     *
     * @param {Array} importedHeaders - Headers from imported CSV
     * @param {Array} currentHeaders - Current CSV headers
     * @return {Object} Validation result
     */
    function validateCSV(importedHeaders, currentHeaders) {
        var result = {
            valid: true,
            errors: [],
            warnings: []
        };

        if (!importedHeaders || !importedHeaders.length) {
            result.valid = false;
            result.errors.push('Imported CSV has no headers.');
            return result;
        }

        if (importedHeaders.length !== currentHeaders.length) {
            result.errors.push(
                'Column count mismatch: imported has ' + importedHeaders.length +
                ' columns, current CSV has ' + currentHeaders.length + '.'
            );
        }

        // Check for header mismatches
        for (var i = 0; i < Math.min(importedHeaders.length, currentHeaders.length); i++) {
            if (importedHeaders[i] !== currentHeaders[i]) {
                result.errors.push(
                    'Column ' + (i + 1) + ' mismatch: imported "' + importedHeaders[i] +
                    '" vs current "' + currentHeaders[i] + '".'
                );
            }
        }

        if (result.errors.length) {
            result.valid = false;
        }

        return result;
    }

    // ═══════════════════════════════════════════════════════════════
    // Helper Functions
    // ═══════════════════════════════════════════════════════════════

    /**
     * CSV escape: quote fields with special chars, escape internal quotes.
     * Also prevents CSV injection by prefixing formula-dangerous chars.
     *
     * @param {string} val - Field value
     * @return {string} Escaped value
     */
    function csvEscape(val) {
        if (!val) {
            return '';
        }

        // Neutralize formula-dangerous prefixes (CSV injection prevention)
        if (/^[=+\-@\t\r]/.test(val)) {
            val = "'" + val;
        }

        // Quote if contains comma, quote, or newline
        if (val.indexOf(',') !== -1 || val.indexOf('"') !== -1 || val.indexOf('\n') !== -1) {
            return '"' + val.replace(/"/g, '""') + '"';
        }

        return val;
    }

    /**
     * Import file from file picker.
     * Validates size, parses, validates headers, shows preview modal.
     *
     * @param {File} file - File object from input
     * @param {Array} currentHeaders - Current CSV headers
     */
    function importFile(file, currentHeaders) {
        if (file.size > MAX_IMPORT_SIZE) {
            UI.showMsg(
                'Import file too large: <strong>' + (file.size / 1024 / 1024).toFixed(1) +
                ' MB</strong>. Maximum allowed is <strong>5 MB</strong>.',
                'error'
            );
            return;
        }

        var reader = new FileReader();
        reader.onload = function(e) {
            var text = e.target.result;
            var parsed = parseCSV(text);

            if (!parsed) {
                UI.showMsg('Failed to parse CSV file.', 'error');
                return;
            }

            var importHeaders = parsed.headers;
            var importRows = parsed.rows;

            // Validate size limits
            if (importHeaders.length > MAX_COLUMNS) {
                UI.showMsg(
                    'Import CSV has <strong>' + importHeaders.length +
                    '</strong> columns, maximum allowed is <strong>' + MAX_COLUMNS + '</strong>.',
                    'error'
                );
                return;
            }

            if (importRows.length > MAX_ROWS) {
                UI.showMsg(
                    'Import file has <strong>' + importRows.length +
                    '</strong> rows, maximum allowed is <strong>' + MAX_ROWS + '</strong>.',
                    'error'
                );
                return;
            }

            // Validate headers match current CSV
            var validation = validateCSV(importHeaders, currentHeaders);
            if (!validation.valid) {
                var errorMsg = validation.errors.join('<br>');
                UI.showMsg('Import validation failed:<br>' + errorMsg, 'error');
                return;
            }

            // Show preview modal
            showImportPreviewModal(file.name, importHeaders, importRows);
        };

        reader.readAsText(file);
    }

    /**
     * Show import preview modal and let user confirm.
     *
     * @param {string} filename - Imported filename
     * @param {Array} importHeaders - Import CSV headers
     * @param {Array} importRows - Import CSV rows
     */
    function showImportPreviewModal(filename, importHeaders, importRows) {
        $(".wl-modal-overlay").remove();

        var previewRows = importRows.slice(0, 5);
        var previewHtml = '<table style="width:100%;border-collapse:collapse;">' +
            '<thead><tr style="border-bottom:1px solid #ccc;">';

        importHeaders.forEach(function(h) {
            previewHtml += '<th style="padding:8px;text-align:left;font-weight:bold;">' +
                _.escape(h) + '</th>';
        });

        previewHtml += '</tr></thead><tbody>';

        previewRows.forEach(function(row) {
            previewHtml += '<tr style="border-bottom:1px solid #eee;">';
            importHeaders.forEach(function(h) {
                previewHtml += '<td style="padding:8px;">' +
                    _.escape((row[h] || '').substring(0, 50)) + '</td>';
            });
            previewHtml += '</tr>';
        });

        previewHtml += '</tbody></table>';

        var $modal = $(
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal" style="max-width:90%;max-height:80vh;overflow:auto;">' +
                    '<div class="wl-modal-header">Import CSV — ' + _.escape(filename) + '</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>Preview: <strong>' + importRows.length + '</strong> rows, ' +
                        '<strong>' + importHeaders.length + '</strong> columns</p>' +
                        previewHtml +
                        (importRows.length > 5 ? '<p style="color:#666;font-size:12px;">...and ' +
                            (importRows.length - 5) + ' more rows</p>' : '') +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<button class="btn btn-primary" id="wl-import-confirm">Import</button> ' +
                        '<button class="btn" id="wl-import-cancel">Cancel</button>' +
                    '</div>' +
                '</div>' +
            '</div>'
        );

        $('body').append($modal);

        $modal.on('click', '#wl-import-confirm', function() {
            $modal.remove();
            confirmImport(filename, importRows);
        });

        $modal.on('click', '#wl-import-cancel', function() {
            $modal.remove();
        });
    }

    /**
     * Confirm and apply import: update state with imported rows.
     *
     * @param {string} filename - Imported filename
     * @param {Array} importRows - Imported row data
     */
    function confirmImport(filename, importRows) {
        State.set('currentRows', importRows);
        State.set('importedRowsPreview', null);

        UI.showMsg('Imported ' + importRows.length + ' rows from ' + filename, 'success');

        $(document).trigger('wl:csvImported', {
            filename: filename,
            rowCount: importRows.length
        });
    }

    // Public API
    return {
        init: init,
        exportCSV: exportCSV,
        importCSV: importCSV,
        parseCSV: parseCSV,
        validateCSV: validateCSV
    };
});
