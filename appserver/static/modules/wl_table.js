/**
 * wl_table.js — Table Rendering, Editing & Interaction Module
 *
 * Handles CSV table display, inline cell editing, pagination, column resize,
 * drag-drop reordering (rows and columns), column rename, and row selection.
 *
 * Public API:
 *   init(config)        — wire dependencies, DOM refs, shared state, callbacks
 *   renderTable(h, r)   — load new CSV data into the table
 *   refreshTable()      — redraw the table from current state
 *   syncInputs()        — capture DOM input values into shared state
 *   undoCellEdit()      — undo the last cell edit
 *   getFilteredRows()   — return filtered row entries or null
 *   clearSearch()       — clear search and refresh
 *   getSelectedIndices()— return array of selected row indices
 *   getSelectedCount()  — return count of selected rows
 *   clearSelections()   — reset all checkbox selections
 *   resetPage()         — reset pagination to first page
 *
 * State management:
 *   Shared state is accessed via an ES5 getter/setter proxy object (S)
 *   passed at init time. Module-internal state (pagination, drag, resize,
 *   column widths, edit history) lives in module-local variables.
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
    var $table = null;
    var _dom = {};      // { $searchInput, $searchGroup, $diff }

    // ── Entry-point callbacks (set by init) ─────────────────────────
    var _actions = {};

    // ── After-refresh hook (entry point can inject post-render logic)
    var _onAfterRefresh = null;
    // ── Selection-changed hook (entry point updates Bulk Edit btn state)
    var _onSelectionChanged = null;

    // ── Module-internal state ───────────────────────────────────────
    var currentPage      = 0;
    var ROWS_PER_PAGE    = C.ROWS_PER_PAGE;
    var PAGE_SIZE_OPTIONS = C.PAGE_SIZE_OPTIONS;
    var selectedIdxSet   = {};
    var colWidths        = {};
    var allColWidths     = {};
    var colWidthSaveTimer = null;
    var resizeState      = null;
    var dragState        = null;
    var editHistory      = [];
    var MAX_EDIT_HISTORY = 50;

    // ── Module aliases ──────────────────────────────────────────────
    var showMsg          = UI.showMsg;
    var formatDailyLimitMsg = UI.formatDailyLimitMsg;
    var restPost         = REST.restPost;

    // ══════════════════════════════════════════════════════════════════
    // Init
    // ══════════════════════════════════════════════════════════════════

    function init(config) {
        $table          = config.$table;
        S               = config.state;
        _dom            = config.dom    || {};
        _actions        = config.actions || {};
        _onAfterRefresh = config.onAfterRefresh || null;
    }

    // ══════════════════════════════════════════════════════════════════
    // Table rendering entry point (called when a CSV file is loaded)
    // ══════════════════════════════════════════════════════════════════

    function renderTable(headers, rows) {
        S.currentHeaders  = headers;
        S.originalHeaders = headers.slice();
        S.currentRows     = rows.map(function (r) { return $.extend({}, r); });
        S.originalRows    = rows.map(function (r) { return $.extend({}, r); });
        currentPage       = 0;
        selectedIdxSet    = {};
        S.searchQuery     = "";
        S.pendingBulkEditCount = 0;
        // Restore persisted column widths for this CSV
        if (S.selectedCsv && allColWidths[S.selectedCsv]) {
            colWidths = $.extend({}, allColWidths[S.selectedCsv]);
        }
        _dom.$searchInput.val("");
        _dom.$searchGroup.show();
        refreshTable();
    }

    // ══════════════════════════════════════════════════════════════════
    // Search / filter helpers
    // ══════════════════════════════════════════════════════════════════

    function getFilteredRows() {
        // Pending approval filter takes priority
        if (S.pendingFilterActive && S.pendingFilterIndices) {
            var pfResults = [];
            for (var p = 0; p < S.pendingFilterIndices.length; p++) {
                var pi = S.pendingFilterIndices[p];
                if (pi < S.currentRows.length) {
                    pfResults.push({ idx: pi, row: S.currentRows[pi] });
                }
            }
            return pfResults;
        }
        if (!S.searchQuery) { return null; }
        var q = S.searchQuery.toLowerCase();
        var visibleHeaders = S.currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });
        var results = [];
        for (var i = 0; i < S.currentRows.length; i++) {
            var row = S.currentRows[i];
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
        S.searchQuery = "";
        _dom.$searchInput.val("");
        currentPage = 0;
        refreshTable();
    }

    // ══════════════════════════════════════════════════════════════════
    // Textarea auto-resize
    // ══════════════════════════════════════════════════════════════════

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

    // ══════════════════════════════════════════════════════════════════
    // Sync DOM inputs → shared state
    // ══════════════════════════════════════════════════════════════════

    function syncInputs() {
        $table.find("tbody tr").each(function () {
            var idx = $(this).data("idx");
            $(this).find(".wl-input").each(function () {
                // Skip Expires inputs — they display local time but
                // currentRows holds UTC.  Only the date picker updates them.
                if ($(this).hasClass("wl-expires-input")) { return; }
                var header = $(this).data("header");
                if (S.currentRows[idx]) {
                    S.currentRows[idx][header] = $(this).val();
                }
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Main table render
    // ══════════════════════════════════════════════════════════════════

    function refreshTable() {
        if (!S.currentHeaders.length) {
            $table.html('<p class="wl-muted">This CSV file is empty.</p>');
            return;
        }

        var hasExpires = !!S.expireColumn;
        var now = new Date();
        var isSearching = !!S.searchQuery;

        // Visible headers (skip _ metadata columns)
        var visibleHeaders = S.currentHeaders.filter(function (h) {
            return h.charAt(0) !== "_";
        });

        // Determine rows to display: filtered or all
        var filtered = getFilteredRows();
        var displayEntries; // array of {idx, row}
        if (filtered !== null) {
            displayEntries = filtered;
        } else {
            displayEntries = S.currentRows.map(function (r, i) {
                return { idx: i, row: r };
            });
        }

        var html = "";

        // Presence bar placeholder — always reserve space to prevent layout shift
        html += '<div id="wl-presence-bar" class="wl-presence-bar"></div>';

        // Search result count
        if (isSearching) {
            html += '<div class="wl-search-info">' + displayEntries.length +
                    ' of ' + S.currentRows.length + ' row(s) match</div>';
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
        var allSelected = S.currentRows.length > 0 && Object.keys(selectedIdxSet).length === S.currentRows.length;
        html += '<th class="wl-col-check"><input type="checkbox" id="wl-check-all" title="Select all"' + (allSelected ? ' checked="checked"' : '') + ' /></th>';
        html += '<th class="wl-col-rownum">#</th>';
        visibleHeaders.forEach(function (h) {
            var widthStyle = colWidths[h] ? ' style="width:' + colWidths[h] + 'px;min-width:' + colWidths[h] + 'px;"' : '';
            html += '<th class="wl-col-draggable" data-col="' + _.escape(h) + '"' + widthStyle + '>';
            if (!S.csvLocked) {
                html += '<span class="wl-col-drag-handle" title="Drag to reorder">\u2630</span>';
            }
            html += '<span class="wl-col-header-text">' + _.escape(h) + '</span>';
            if (!S.csvLocked) {
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
                : S.currentRows.length + ' rows';
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

        // Action buttons — disable editing controls when CSV is locked by pending approvals
        var lk = S.csvLocked;
        var lkCls = lk ? ' wl-btn-locked' : '';
        var lkAttr = lk ? ' disabled="disabled"' : '';
        html += '<div class="wl-buttons">';
        html += '<button class="btn btn-primary' + lkCls + '" id="btn-add-row"' + lkAttr + '>+ Add Row</button> ';
        html += '<button class="btn btn-primary' + lkCls + '" id="btn-add-col"' + lkAttr + '>+ Add Column</button> ';
        html += '<button class="btn btn-primary' + lkCls + '" id="btn-bulk-edit" disabled="disabled">Bulk Edit</button> ';
        html += '<button class="btn btn-danger' + lkCls + '" id="btn-remove-selected" disabled="disabled">Remove Selected</button> ';
        html += '<button class="btn btn-success' + lkCls + '" id="btn-save"' + lkAttr + '>Save Changes</button> ';
        html += '<button class="btn' + lkCls + '"             id="btn-discard"' + lkAttr + '>Discard Changes</button>';
        html += '<span class="wl-buttons-right">';
        html += '<button class="btn" id="btn-export" title="Download current CSV">Export CSV</button> ';
        html += '<label class="btn' + (lk ? ' wl-btn-locked' : '') + ' wl-import-btn" title="Upload CSV to merge rows">';
        html += 'Import CSV <input type="file" id="btn-import" accept=".csv"' + lkAttr + ' style="display:none" />';
        html += '</label>';
        html += '</span>';
        html += "</div>";

        // Undo bar placeholder
        html += '<div id="wl-undo-bar"></div>';

        $table.html(html);
        bindTableEvents();
        autoResizeAllTextareas();
        _actions.applyPendingCssHighlighting();

        // Fire after-refresh hook (entry point injects audit export btn, etc.)
        if (_onAfterRefresh) { _onAfterRefresh(); }
    }

    // ══════════════════════════════════════════════════════════════════
    // Build single table row HTML
    // ══════════════════════════════════════════════════════════════════

    function buildRow(visibleHeaders, row, idx, hasExpires, now) {
        // Check if row is expired
        var expired = false;
        if (hasExpires && S.expireColumn) {
            var expVal = (row[S.expireColumn] || "").trim();
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
        if (S.csvLocked) {
            tooltip = ' title="Locked — pending approval"';
        } else if (row._added_by || row._added_at) {
            var parts = [];
            if (row._added_by) { parts.push("Added by: " + row._added_by); }
            if (row._added_at) { parts.push("Added at: " + row._added_at); }
            tooltip = ' title="' + _.escape(parts.join(" | ")) + '"';
        }

        var html = '<tr data-idx="' + idx + '"' + trClass + tooltip + '>';

        if (S.csvLocked) {
            // Full file lock: no checkbox, no drag, readonly cells, no Remove button
            html += '<td class="wl-col-check"></td>';
            html += '<td class="wl-col-rownum" data-idx="' + idx + '"><span class="wl-grip-icon" style="visibility:hidden">\u2630</span>' + (idx + 1) + '</td>';
        } else {
            html += '<td class="wl-col-check"><input type="checkbox" class="wl-row-check" data-idx="' + idx + '"' + (selectedIdxSet[idx] ? ' checked="checked"' : '') + ' /></td>';
            html += '<td class="wl-col-rownum wl-row-drag-handle" data-idx="' + idx + '" title="Drag to reorder"><span class="wl-grip-icon">\u2630</span>' + (idx + 1) + '</td>';
        }

        visibleHeaders.forEach(function (h) {
            var val = row[h] || "";
            var isExpires = (S.expireColumn && h === S.expireColumn);
            // Convert UTC Expires values to local time for display
            if (isExpires && val && val.endsWith("UTC")) {
                var utcDate = new Date(val.replace(" UTC", "Z").replace(" ", "T"));
                if (!isNaN(utcDate.getTime())) { val = _actions.formatLocalDateTime(utcDate); }
            }
            var matchClass = "";
            if (S.searchQuery && val) {
                var cellLower = val.toLowerCase();
                if (cellLower.indexOf(S.searchQuery.toLowerCase()) !== -1) {
                    matchClass = " wl-cell-match";
                }
            }
            var editedClass = "";
            if (idx < S.originalRows.length) {
                var origVal = S.originalRows[idx][h] || "";
                if ((row[h] || "") !== origVal) {
                    editedClass = " wl-cell-edited";
                }
            }
            var cellReadonly = S.csvLocked || isExpires;
            html +=
                "<td>" +
                '<textarea class="wl-input' +
                (isExpires ? ' wl-expires-input' : '') +
                matchClass + editedClass + '" rows="1" ' +
                'maxlength="' + C.MAX_CELL_CHARS + '" ' +
                'data-header="' + _.escape(h) + '"' +
                (cellReadonly ? ' readonly="readonly" tabindex="-1"' : '') +
                (isExpires && !S.csvLocked ? ' style="cursor:pointer"' : '') +
                '>' + _.escape(val) + '</textarea>' +
                "</td>";
        });

        if (S.csvLocked) {
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
        if (S.currentRows[edit.idx]) {
            S.currentRows[edit.idx][edit.header] = edit.oldValue;
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
        if (_onSelectionChanged) { _onSelectionChanged(); }
    }

    function bindTableEvents() {
        // Select-all checkbox — selects ALL rows across all pages
        $table.off("change.wl", "#wl-check-all").on("change.wl", "#wl-check-all", function () {
            if (S.csvLocked) { $(this).prop("checked", false); return; }
            var checked = $(this).is(":checked");
            selectedIdxSet = {};
            if (checked) {
                for (var i = 0; i < S.currentRows.length; i++) {
                    selectedIdxSet[i] = true;
                }
            }
            $table.find(".wl-row-check").prop("checked", checked);
            updateRemoveSelectedBtn();
        });

        // Individual row checkboxes
        $table.off("change.wl", ".wl-row-check").on("change.wl", ".wl-row-check", function () {
            if (S.csvLocked) { $(this).prop("checked", false); return; }
            var idx = $(this).data("idx");
            if ($(this).is(":checked")) {
                selectedIdxSet[idx] = true;
            } else {
                delete selectedIdxSet[idx];
            }
            var totalSelected = Object.keys(selectedIdxSet).length;
            $table.find("#wl-check-all").prop("checked", totalSelected === S.currentRows.length);
            updateRemoveSelectedBtn();
        });

        // Bulk remove selected rows (across all pages)
        $table.off("click.wl", "#btn-remove-selected").on("click.wl", "#btn-remove-selected", function () {
            if (S.csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            var selectedIdxs = Object.keys(selectedIdxSet).map(Number);
            if (!selectedIdxs.length) { return; }

            // Separate unsaved (newly added) rows from saved rows
            var savedIdxs = [];
            var unsavedIdxs = [];
            selectedIdxs.forEach(function (idx) {
                if (idx >= S.originalRows.length) {
                    unsavedIdxs.push(idx);
                } else {
                    savedIdxs.push(idx);
                }
            });

            // Remove unsaved rows immediately (they only exist locally)
            if (unsavedIdxs.length) {
                unsavedIdxs.sort(function (a, b) { return b - a; }); // descending
                unsavedIdxs.forEach(function (idx) {
                    S.currentRows.splice(idx, 1);
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
                csv_file: S.selectedCsv,
                app_context: S.selectedApp,
                selected_count: selectedIdxs.length
            }).done(function (gateData) {
                if (gateData.requires_approval) {
                    // Approval required — submit for review instead of direct removal
                    _actions.showRemoveRowModal(
                        "Submit for Approval",
                        "Removing <strong>" + selectedIdxs.length + "</strong> row(s) requires admin approval.<br>" +
                            "Reason: " + _.escape(gateData.reason) + "<br><br>" +
                            "Your request will be submitted for review.",
                        function (reason) {
                            syncInputs();
                            _actions.submitApprovalRequest("bulk_row_removal", reason, selectedIdxs.slice(), null);
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
                    _actions.showRemoveRowModal(
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
                                    row: $.extend({}, S.currentRows[idx])
                                });
                            });
                            var prevRows = S.currentRows.map(function (r) { return $.extend({}, r); });
                            var prevOriginal = S.originalRows.map(function (r) { return $.extend({}, r); });
                            selectedIdxSet = {};
                            for (var i = selectedIdxs.length - 1; i >= 0; i--) {
                                S.currentRows.splice(selectedIdxs[i], 1);
                            }
                            refreshTable();
                            _actions.doSaveBulkRemoval(removedEntries, reason, prevRows, prevOriginal);
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
            if (S.csvLocked) { $el.val(S.currentRows[idx][$el.data("header")] || ""); return; }
            var header = $el.data("header");
            if (S.currentRows[idx]) {
                var newValue = $el.val();
                if (C.NON_ASCII_RE.test(newValue)) {
                    $el.addClass("wl-input-error");
                    showMsg(C.ASCII_ERROR_MSG, "error");
                    $el.val(S.currentRows[idx][header] || "");
                    return;
                }
                var oldValue = S.currentRows[idx][header] || "";
                trackCellEdit(idx, header, oldValue, newValue);
                S.currentRows[idx][header] = newValue;
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
                if (C.NON_ASCII_RE.test(cleaned)) {
                    $(self).addClass("wl-input-error");
                    showMsg(C.ASCII_ERROR_MSG, "error");
                    $(self).val("");
                    return;
                }
                if (cleaned.length > C.MAX_CELL_CHARS) {
                    cleaned = cleaned.substring(0, C.MAX_CELL_CHARS);
                    showMsg("Pasted text truncated to " + C.MAX_CELL_CHARS + " characters.", "warning");
                }
                $(self).val(cleaned);
                autoResizeTextarea(self);
            }, 0);
        });

        // Remove row with undo support
        $table.off("click.wl", ".btn-rm").on("click.wl", ".btn-rm", function () {
            var idx = $(this).data("idx");
            var row = S.currentRows[idx];
            if (!row) { return; }
            if (S.csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }

            // Unsaved row (added but not yet saved) — remove locally, no reason needed
            if (idx >= S.originalRows.length) {
                syncInputs();
                S.currentRows.splice(idx, 1);
                selectedIdxSet = {};
                refreshTable();
                showMsg("Unsaved row removed.", "info");
                return;
            }

            // Build a short summary of the row for the modal
            var visH = S.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var preview = visH.slice(0, 3).map(function (h) {
                return '<strong>' + _.escape(h) + '</strong>: ' + _.escape(row[h] || "");
            }).join(", ");
            if (visH.length > 3) { preview += " &hellip;"; }

            _actions.showRemoveRowModal(
                "Remove Row",
                "Remove row <strong>#" + (idx + 1) + "</strong>?<br>" +
                    '<span style="font-size:12px;color:var(--wl-text-secondary)">' + preview + '</span><br><br>' +
                    "You will have 10 seconds to undo before this is saved.",
                function (reason) {
                    syncInputs();
                    var removedRow = $.extend({}, row);
                    var rowNumber = idx + 1;
                    var prevRows = S.currentRows.map(function (r) { return $.extend({}, r); });
                    var prevOriginal = S.originalRows.map(function (r) { return $.extend({}, r); });
                    S.currentRows.splice(idx, 1);
                    selectedIdxSet = {}; // Clear selections — indices shifted after splice
                    refreshTable();
                    _actions.doSaveRemoval(removedRow, reason, rowNumber, prevRows, prevOriginal);
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
            var totalPages = Math.ceil(S.currentRows.length / ROWS_PER_PAGE);
            if (currentPage < totalPages - 1) { currentPage++; refreshTable(); }
        });
        $table.off("click.wl", "#btn-page-last").on("click.wl", "#btn-page-last", function () {
            syncInputs();
            var totalPages = Math.ceil(S.currentRows.length / ROWS_PER_PAGE);
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
            if (S.csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            if (S.currentRows.length >= C.MAX_ROWS) {
                showMsg(
                    "Row limit reached: maximum <strong>" + C.MAX_ROWS +
                    "</strong> rows allowed per CSV.",
                    "error"
                );
                return;
            }
            // Sync any in-progress edits before adding a new row, so data
            // typed into the previous row isn't lost when refreshTable redraws.
            syncInputs();
            if (S.searchQuery) {
                showSearchWarning(function () {
                    // User confirmed — clear search, add row
                    S.searchQuery = "";
                    var newRow = {};
                    S.currentHeaders.forEach(function (h) { newRow[h] = ""; });
                    S.currentRows.push(newRow);
                    currentPage = Math.ceil(S.currentRows.length / ROWS_PER_PAGE) - 1;
                    refreshTable();
                    $table.find("tbody tr:last input:first").focus();
                });
                return;
            }
            var newRow = {};
            S.currentHeaders.forEach(function (h) { newRow[h] = ""; });
            S.currentRows.push(newRow);
            currentPage = Math.ceil(S.currentRows.length / ROWS_PER_PAGE) - 1;
            refreshTable();
            $table.find("tbody tr:last input:first").focus();
        });

        // Add column
        $table.off("click.wl", "#btn-add-col").on("click.wl", "#btn-add-col", function () {
            if (S.csvLocked) {
                showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            var visibleCount = S.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; }).length;
            if (visibleCount >= C.MAX_COLUMNS) {
                showMsg(
                    "Column limit reached: maximum <strong>" + C.MAX_COLUMNS +
                    "</strong> columns allowed per CSV.",
                    "error"
                );
                return;
            }
            if (S.searchQuery) {
                showSearchWarning(function () {
                    S.searchQuery = "";
                    showAddColumnModal(function (colName) { _actions.doSaveColumnAddition(colName); });
                });
                return;
            }
            showAddColumnModal(function (colName) { _actions.doSaveColumnAddition(colName); });
        });

        // Remove column (× button in header) — auto-saves immediately
        $table.off("click.wl", ".wl-col-remove-btn").on("click.wl", ".wl-col-remove-btn", function (e) {
            e.stopPropagation();
            var colName = $(this).data("col");
            if (!colName) { return; }
            if (S.searchQuery) {
                showSearchWarning(function () {
                    S.searchQuery = "";
                    _actions.doColumnRemoveWithGateCheck(colName);
                });
                return;
            }
            _actions.doColumnRemoveWithGateCheck(colName);
        });

        // Save
        $table.off("click.wl", "#btn-save").on("click.wl", "#btn-save", function () {
            _actions.doSave();
        });

        // Discard
        $table.off("click.wl", "#btn-discard").on("click.wl", "#btn-discard", function () {
            if (S.csvLocked) { return; } // CSV locked by pending approval
            S.currentHeaders = S.originalHeaders.slice();
            S.currentRows = S.originalRows.map(function (r) { return $.extend({}, r); });
            S.searchQuery = "";
            _dom.$searchInput.val("");
            _actions.clearUndo();
            refreshTable();
            _dom.$diff.empty();
            showMsg("Changes discarded.", "info");
        });

        // Export CSV
        $table.off("click.wl", "#btn-export").on("click.wl", "#btn-export", function () {
            _actions.exportCsv();
        });

        // Import CSV
        $table.off("change.wl", "#btn-import").on("change.wl", "#btn-import", function (e) {
            var file = e.target.files[0];
            if (file) { _actions.importCsv(file); }
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
            if (S.selectedCsv && Object.keys(colWidths).length) {
                allColWidths[S.selectedCsv] = $.extend({}, colWidths);
                clearTimeout(colWidthSaveTimer);
                colWidthSaveTimer = setTimeout(function () {
                    restPost({
                        action: "save_col_widths",
                        csv_file: S.selectedCsv,
                        app_context: S.selectedApp,
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
            if (S.searchQuery) { return; }
            if (e.which !== 1) { return; }
            var fromIdx = $(this).data("idx");
            if (S.csvLocked) { return; }
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
            if (S.searchQuery) { return; }
            if (e.which !== 1) { return; }
            var $handle = $(this);
            var $th = $handle.closest("th.wl-col-draggable");
            var fromCol = $th.data("col");
            if (S.csvLocked) { return; }
            e.preventDefault();
            e.stopPropagation(); // prevent rename click handler
            var colW = $th.outerWidth();
            var startX = e.clientX;

            var visibleHeaders = S.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
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
            if (S.csvLocked) { return; }
            if (S.searchQuery) { showMsg("Clear search before renaming columns", "warning"); return; }
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
                    else if (S.currentHeaders.indexOf(newName) !== -1) { validationError = "Column '" + _.escape(newName) + "' already exists"; }
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
        if (S.saving) { return; }
        syncInputs();

        // Discard any pending cell edits — reorder must be a pure positional save
        S.currentRows = S.originalRows.map(function (r) { return $.extend({}, r); });
        S.pendingBulkEditCount = 0;

        var fromPos = fromIdx + 1;
        var toPos = toIdx + 1;

        var prevRows = S.currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = S.originalRows.map(function (r) { return $.extend({}, r); });

        var movedRow = S.currentRows.splice(fromIdx, 1)[0];
        S.currentRows.splice(toIdx, 0, movedRow);

        refreshTable();
        showMsg("Reordering row&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        S.selectedCsv,
            app_context:     S.selectedApp,
            detection_rule:  S.selectedRule || "",
            headers:         S.currentHeaders,
            rows:            S.currentRows,
            comment:         "Row reorder",
            removal_reasons: [],
            row_reorder:     { from_position: fromPos, to_position: toPos },
            expected_mtime:  S.loadedMtime,
            expected_content_hash: S.loadedContentHash
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                S.currentRows = prevRows;
                S.originalRows = prevOriginal;
                refreshTable();
                return;
            }
            showMsg("Row moved from #" + fromPos + " to #" + toPos + ". Changes saved", "success");
            S.originalRows = S.currentRows.map(function (r) { return $.extend({}, r); });
            if (data.file_mtime) { S.loadedMtime = data.file_mtime; }
            refreshTable();
            _actions.loadVersions(S.selectedCsv, S.selectedApp);
        })
        .fail(function (xhr) {
            _actions.handleSaveError(xhr, "Failed to save after row reorder.");
            S.currentRows = prevRows;
            S.originalRows = prevOriginal;
            refreshTable();
        });
    }

    function doColumnReorder(fromCol, toCol) {
        if (S.saving) { return; }
        syncInputs();

        // Discard any pending cell edits — reorder must be a pure positional save
        S.currentRows = S.originalRows.map(function (r) { return $.extend({}, r); });
        S.currentHeaders = S.originalHeaders.slice();
        S.pendingBulkEditCount = 0;

        var visibleHeaders = S.currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var fromVisIdx = visibleHeaders.indexOf(fromCol);
        var toVisIdx   = visibleHeaders.indexOf(toCol);
        if (fromVisIdx === -1 || toVisIdx === -1) { return; }

        var fromPos = fromVisIdx + 1;
        var toPos   = toVisIdx + 1;

        var prevHeaders = S.currentHeaders.slice();
        var prevOrigHeaders = S.originalHeaders.slice();

        var fromActualIdx = S.currentHeaders.indexOf(fromCol);
        S.currentHeaders.splice(fromActualIdx, 1);
        var newToIdx = S.currentHeaders.indexOf(toCol);
        if (fromVisIdx < toVisIdx) {
            S.currentHeaders.splice(newToIdx + 1, 0, fromCol);
        } else {
            S.currentHeaders.splice(newToIdx, 0, fromCol);
        }

        refreshTable();
        showMsg("Reordering column&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        S.selectedCsv,
            app_context:     S.selectedApp,
            detection_rule:  S.selectedRule || "",
            headers:         S.currentHeaders,
            rows:            S.currentRows,
            comment:         "Column reorder",
            removal_reasons: [],
            column_reorder:  { column: fromCol, from_position: fromPos, to_position: toPos },
            expected_mtime:  S.loadedMtime,
            expected_content_hash: S.loadedContentHash
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                S.currentHeaders = prevHeaders;
                S.originalHeaders = prevOrigHeaders;
                refreshTable();
                return;
            }
            showMsg("Column '" + _.escape(fromCol) + "' moved from #" + fromPos + " to #" + toPos + ". Changes saved", "success");
            S.originalHeaders = S.currentHeaders.slice();
            S.originalRows = S.currentRows.map(function (r) { return $.extend({}, r); });
            if (data.file_mtime) { S.loadedMtime = data.file_mtime; }
            refreshTable();
            _actions.loadVersions(S.selectedCsv, S.selectedApp);
        })
        .fail(function (xhr) {
            _actions.handleSaveError(xhr, "Failed to save after column reorder.");
            S.currentHeaders = prevHeaders;
            S.originalHeaders = prevOrigHeaders;
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Column rename auto-save
    // ══════════════════════════════════════════════════════════════════

    function doSaveColumnRename(oldName, newName) {
        if (S.saving) { return; }
        syncInputs();

        var snapHeaders = S.currentHeaders.slice();
        var snapRows = S.currentRows.map(function (r) { return $.extend({}, r); });

        var idx = S.currentHeaders.indexOf(oldName);
        if (idx === -1) { return; }
        S.currentHeaders[idx] = newName;

        S.currentRows.forEach(function (row) {
            row[newName] = row.hasOwnProperty(oldName) ? row[oldName] : "";
            delete row[oldName];
        });

        refreshTable();
        showMsg("Renaming column and saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        S.selectedCsv,
            app_context:     S.selectedApp,
            detection_rule:  S.selectedRule || "",
            headers:         S.currentHeaders,
            rows:            S.currentRows,
            comment:         "Column rename",
            removal_reasons: [],
            column_renames:  [{ old_name: oldName, new_name: newName }],
            expected_mtime:  S.loadedMtime,
            expected_content_hash: S.loadedContentHash
        })
        .done(function (data) {
            if (data.error) {
                S.currentHeaders = snapHeaders;
                S.currentRows = snapRows;
                refreshTable();
                showMsg(_.escape(data.error), "error");
                return;
            }
            S.loadedMtime = data.file_mtime || S.loadedMtime;
            S.originalHeaders = S.currentHeaders.slice();
            S.originalRows = S.currentRows.map(function (r) { return $.extend({}, r); });
            if (colWidths[oldName]) {
                colWidths[newName] = colWidths[oldName];
                delete colWidths[oldName];
                allColWidths[S.selectedCsv] = $.extend({}, colWidths);
            }
            showMsg("Changes saved. Column renamed: '" + _.escape(oldName) + "' \u2192 '" + _.escape(newName) + "'", "success");
            _actions.loadVersions(S.selectedCsv, S.selectedApp);
        })
        .fail(function (xhr) {
            S.currentHeaders = snapHeaders;
            S.currentRows = snapRows;
            refreshTable();
            _actions.handleSaveError(xhr, "Column rename failed");
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
    // Add Column modal
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
            if (S.currentHeaders.indexOf(name) !== -1) {
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

    // ══════════════════════════════════════════════════════════════════
    // Public API
    // ══════════════════════════════════════════════════════════════════

    return {
        init:               init,
        renderTable:        renderTable,
        refreshTable:       refreshTable,
        syncInputs:         syncInputs,
        undoCellEdit:       undoCellEdit,
        getFilteredRows:    getFilteredRows,
        clearSearch:        clearSearch,
        resetPage:          function () { currentPage = 0; },
        prevPage:           function () { if (currentPage > 0) { syncInputs(); currentPage--; refreshTable(); } },
        nextPage:           function () { var tp = Math.ceil(S.currentRows.length / ROWS_PER_PAGE); if (currentPage < tp - 1) { syncInputs(); currentPage++; refreshTable(); } },
        clearSelections:    function () { selectedIdxSet = {}; },
        getSelectedIndices: function () { return Object.keys(selectedIdxSet).map(Number); },
        getSelectedCount:   function () { return Object.keys(selectedIdxSet).length; },
        trackCellEdit:      trackCellEdit,
        hasEditHistory:     function () { return editHistory.length > 0; },
        applyColWidths:     function (w) {
            colWidths = w;
            if (S.selectedCsv) { allColWidths[S.selectedCsv] = $.extend({}, w); }
            $table.find("th.wl-col-draggable").each(function () {
                var h = $(this).data("col");
                if (colWidths[h]) { $(this).css({ width: colWidths[h], minWidth: colWidths[h] }); }
            });
        },
        setOnAfterRefresh:  function (fn) { _onAfterRefresh = fn; },
        setOnSelectionChanged: function (fn) { _onSelectionChanged = fn; }
    };
});
