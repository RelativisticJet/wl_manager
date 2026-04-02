/**
 * wl_table.js - Table Rendering & Editing Module
 *
 * Provides table rendering, inline cell editing, pagination, column operations,
 * drag-drop reordering, column resize, and undo support.
 *
 * Public API: init(), refreshTable(), syncInputs(), getSelectedRows(), undoLastEdit()
 *
 * State management:
 *   - Requires State.currentRows, State.currentHeaders
 *   - Maintains module-local: currentPage, ROWS_PER_PAGE, resizeState, dragState, colWidths
 *   - Listens to: state:currentRows, state:searchResults, state:csvFileSelected, state:csvLocked
 *   - Fires: wl:rowsEdited, wl:tableRefreshed, wl:rowRemovalRequested
 */

define([
    'modules/wl_constants',
    'modules/wl_state',
    'modules/wl_rest',
    'modules/wl_ui'
], function(Constants, State, REST, UI) {
    'use strict';

    var $table = null;
    var currentPage = 0;
    var ROWS_PER_PAGE = 10;
    var PAGE_SIZE_OPTIONS = [10, 20, 50];
    var MAX_ROWS = 5000;
    var MAX_COLUMNS = 100;
    var MAX_CELL_CHARS = 1000;
    var MAX_EDIT_HISTORY = 50;

    var selectedIdxSet = {};
    var resizeState = null;
    var dragState = null;
    var editHistory = [];
    var colWidths = {};
    var allColWidths = {};
    var colWidthSaveTimer = null;

    var currentHeaders = [];
    var currentRows = [];
    var originalRows = [];
    var expireColumn = "";

    /**
     * Initialize table module.
     * Bind to DOM elements and listen to State changes.
     */
    function init() {
        $table = $(Constants.SELECTORS.TABLE_CONTAINER);
        if (!$table.length) {
            console.warn('[wl_table] Table container not found in DOM');
            return;
        }

        // Listen to State changes
        State.on('state:currentRows', function(rows) {
            currentRows = rows || [];
            onCurrentRowsChanged();
        });

        State.on('state:currentHeaders', function(headers) {
            currentHeaders = headers || [];
        });

        State.on('state:originalRows', function(rows) {
            originalRows = rows || [];
        });

        State.on('state:csvFileSelected', function() {
            currentPage = 0;
            selectedIdxSet = {};
            editHistory = [];
            refreshTable();
        });

        State.on('state:expireColumn', function(col) {
            expireColumn = col || "";
        });

        // Initialize from State
        currentRows = State.get('currentRows') || [];
        currentHeaders = State.get('currentHeaders') || [];
        originalRows = State.get('originalRows') || [];
        expireColumn = State.get('expireColumn') || "";
    }

    /**
     * Refresh table display.
     * Must call syncInputs() first to capture unsaved edits.
     */
    function refreshTable() {
        syncInputs();

        if (!currentHeaders.length) {
            $table.html('<p class="wl-muted">This CSV file is empty.</p>');
            return;
        }

        var csvLocked = State.get('csvLocked') || false;
        var searchResults = State.get('searchResults') || currentRows;
        var hasExpires = !!expireColumn;
        var now = new Date();

        // Visible headers (skip _ metadata columns)
        var visibleHeaders = currentHeaders.filter(function(h) {
            return h.charAt(0) !== '_';
        });

        // Determine rows to display: search filtered or all
        var displayEntries = searchResults.map(function(row, i) {
            var origIdx = currentRows.indexOf(row);
            return { idx: origIdx !== -1 ? origIdx : i, row: row };
        });

        var html = "";

        // Presence bar placeholder
        html += '<div id="wl-presence-bar" class="wl-presence-bar"></div>';

        // Search result count
        if (searchResults.length < currentRows.length) {
            html += '<div class="wl-search-info">' + searchResults.length +
                    ' of ' + currentRows.length + ' row(s) match</div>';
        }

        // Pagination
        var totalRows = displayEntries.length;
        var totalPages = Math.max(1, Math.ceil(totalRows / ROWS_PER_PAGE));
        if (currentPage >= totalPages) { currentPage = totalPages - 1; }
        if (currentPage < 0) { currentPage = 0; }
        var startIdx = currentPage * ROWS_PER_PAGE;
        var endIdx = Math.min(startIdx + ROWS_PER_PAGE, totalRows);
        var pageEntries = displayEntries.slice(startIdx, endIdx);

        // Table
        html += '<div class="wl-table-scroll">';
        html += '<table class="wl-table">';

        html += "<thead><tr>";
        var allSelected = currentRows.length > 0 && Object.keys(selectedIdxSet).length === currentRows.length;
        html += '<th class="wl-col-check"><input type="checkbox" id="wl-check-all" title="Select all"' +
                (allSelected ? ' checked="checked"' : '') + ' /></th>';
        html += '<th class="wl-col-rownum">#</th>';
        visibleHeaders.forEach(function(h) {
            var widthStyle = colWidths[h] ? ' style="width:' + colWidths[h] + 'px;min-width:' + colWidths[h] + 'px;"' : '';
            html += '<th class="wl-col-draggable" data-col="' + _.escape(h) + '"' + widthStyle + '>';
            if (!csvLocked) {
                html += '<span class="wl-col-drag-handle" title="Drag to reorder">☰</span>';
            }
            html += '<span class="wl-col-header-text">' + _.escape(h) + '</span>';
            if (!csvLocked) {
                html += '<span class="wl-col-remove-btn" data-col="' + _.escape(h) + '" title="Remove column">&times;</span>';
            }
            html += '<div class="wl-col-resize-handle"></div></th>';
        });
        html += '<th class="wl-col-actions">Actions</th>';
        html += "</tr></thead>";

        html += "<tbody>";
        pageEntries.forEach(function(entry) {
            html += buildRow(visibleHeaders, entry.row, entry.idx, hasExpires, now, csvLocked);
        });
        html += "</tbody></table></div>";

        // Pagination controls
        if (totalPages > 1) {
            html += buildPaginationControls(totalPages, displayEntries.length, totalRows, visibleHeaders.length);
        } else if (totalRows > PAGE_SIZE_OPTIONS[0]) {
            html += buildPageSizeSelector();
        }

        // Action buttons
        html += buildActionButtons(csvLocked);

        // Undo bar placeholder
        html += '<div id="wl-undo-bar"></div>';

        $table.html(html);
        bindTableEvents(csvLocked);
        autoResizeAllTextareas();

        $(document).trigger('wl:tableRefreshed', {
            pageIndex: currentPage,
            pageSize: ROWS_PER_PAGE,
            totalRows: totalRows,
            displayedRows: pageEntries.length
        });
    }

    /**
     * Build a single row's HTML.
     */
    function buildRow(visibleHeaders, row, idx, hasExpires, now, csvLocked) {
        // Check if expired
        var expired = false;
        if (hasExpires && expireColumn) {
            var expVal = (row[expireColumn] || "").trim();
            if (expVal) {
                var expDate = expVal.endsWith("UTC")
                    ? new Date(expVal.replace(" UTC", "Z").replace(" ", "T"))
                    : new Date(expVal);
                if (!isNaN(expDate.getTime()) && expDate < now) {
                    expired = true;
                }
            }
        }

        var classes = [];
        if (expired) { classes.push("wl-row-expired"); }
        var trClass = classes.length ? ' class="' + classes.join(" ") + '"' : '';

        // Build tooltip
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
            html += '<td class="wl-col-check"></td>';
            html += '<td class="wl-col-rownum" data-idx="' + idx + '"><span class="wl-grip-icon" style="visibility:hidden">☰</span>' +
                    (idx + 1) + '</td>';
        } else {
            html += '<td class="wl-col-check"><input type="checkbox" class="wl-row-check" data-idx="' + idx + '"' +
                    (selectedIdxSet[idx] ? ' checked="checked"' : '') + ' /></td>';
            html += '<td class="wl-col-rownum wl-row-drag-handle" data-idx="' + idx + '" title="Drag to reorder">' +
                    '<span class="wl-grip-icon">☰</span>' + (idx + 1) + '</td>';
        }

        visibleHeaders.forEach(function(h) {
            var val = row[h] || "";
            var isExpires = (expireColumn && h === expireColumn);
            if (isExpires && val && val.endsWith("UTC")) {
                var utcDate = new Date(val.replace(" UTC", "Z").replace(" ", "T"));
                if (!isNaN(utcDate.getTime())) {
                    val = formatLocalDateTime(utcDate);
                }
            }
            var editedClass = "";
            if (idx < originalRows.length && originalRows[idx]) {
                var origVal = originalRows[idx][h] || "";
                if ((row[h] || "") !== origVal) {
                    editedClass = " wl-cell-edited";
                }
            }
            var cellReadonly = csvLocked || isExpires;
            html += "<td>" +
                    '<textarea class="wl-input' + (isExpires ? ' wl-expires-input' : '') + editedClass + '" ' +
                    'rows="1" maxlength="' + MAX_CELL_CHARS + '" ' +
                    'data-header="' + _.escape(h) + '"' +
                    (cellReadonly ? ' readonly="readonly" tabindex="-1"' : '') +
                    (isExpires && !csvLocked ? ' style="cursor:pointer"' : '') +
                    '>' + _.escape(val) + '</textarea></td>';
        });

        if (csvLocked) {
            html += '<td class="wl-col-actions"></td>';
        } else {
            html += '<td class="wl-col-actions">' +
                    '<button class="btn btn-small btn-danger btn-rm" data-idx="' + idx + '">Remove</button></td>';
        }
        html += "</tr>";
        return html;
    }

    /**
     * Build pagination controls.
     */
    function buildPaginationControls(totalPages, resultCount, totalRows, colCount) {
        var html = '<div class="wl-pagination">';
        html += '<button class="btn btn-small" id="btn-page-first"' +
                (currentPage === 0 ? ' disabled="disabled"' : '') +
                '>&laquo; First</button> ';
        html += '<button class="btn btn-small" id="btn-page-prev"' +
                (currentPage === 0 ? ' disabled="disabled"' : '') +
                '>&#8249; Prev</button>';
        var colWord = colCount === 1 ? 'column' : 'columns';
        var rowInfo = resultCount < totalRows ? resultCount + ' matching' : totalRows + ' rows';
        html += ' <span class="wl-page-info">Page ' +
                (currentPage + 1) + ' of ' + totalPages +
                ' (' + rowInfo + ' – ' + colCount + ' ' + colWord + ')</span> ';
        html += '<button class="btn btn-small" id="btn-page-next"' +
                (currentPage >= totalPages - 1 ? ' disabled="disabled"' : '') +
                '>Next &#8250;</button> ';
        html += '<button class="btn btn-small" id="btn-page-last"' +
                (currentPage >= totalPages - 1 ? ' disabled="disabled"' : '') +
                '>Last &raquo;</button>';
        html += ' <select id="wl-page-size" class="wl-page-size" title="Rows per page">';
        PAGE_SIZE_OPTIONS.forEach(function(n) {
            html += '<option value="' + n + '"' + (n === ROWS_PER_PAGE ? ' selected' : '') + '>' + n + ' per page</option>';
        });
        html += '</select></div>';
        return html;
    }

    /**
     * Build page size selector.
     */
    function buildPageSizeSelector() {
        var html = '<div class="wl-pagination">';
        html += '<select id="wl-page-size" class="wl-page-size" title="Rows per page">';
        PAGE_SIZE_OPTIONS.forEach(function(n) {
            html += '<option value="' + n + '"' + (n === ROWS_PER_PAGE ? ' selected' : '') + '>' + n + ' per page</option>';
        });
        html += '</select></div>';
        return html;
    }

    /**
     * Build action buttons.
     */
    function buildActionButtons(csvLocked) {
        var html = '<div class="wl-buttons">';
        html += '<button class="btn btn-primary" id="btn-add-row">+ Add Row</button> ';
        html += '<button class="btn btn-primary" id="btn-add-col">+ Add Column</button> ';
        html += '<button class="btn btn-primary" id="btn-bulk-edit" disabled="disabled">Bulk Edit</button> ';
        html += '<button class="btn btn-danger" id="btn-remove-selected" disabled="disabled">Remove Selected</button> ';
        html += '<button class="btn btn-success" id="btn-save">Save Changes</button> ';
        html += '<button class="btn" id="btn-discard">Discard Changes</button>';
        html += '<span class="wl-buttons-right">';
        html += '<button class="btn" id="btn-export" title="Download current CSV">Export CSV</button> ';
        html += '<label class="btn wl-import-btn" title="Upload CSV to merge rows">';
        html += 'Import CSV <input type="file" id="btn-import" accept=".csv" style="display:none" />';
        html += '</label></span></div>';
        return html;
    }

    /**
     * Sync unsaved input values into currentRows before refreshing table.
     * CRITICAL: refreshTable() calls this first.
     */
    function syncInputs() {
        $table.find("tbody tr").each(function() {
            var idx = $(this).data("idx");
            $(this).find(".wl-input").each(function() {
                // Skip Expires inputs — they display local time
                if ($(this).hasClass("wl-expires-input")) { return; }
                var header = $(this).data("header");
                if (currentRows[idx]) {
                    currentRows[idx][header] = $(this).val();
                }
            });
        });
    }

    /**
     * Get selected row indices.
     */
    function getSelectedRows() {
        return Object.keys(selectedIdxSet).map(function(k) { return Number(k); }).sort();
    }

    /**
     * Track cell edit in undo history.
     */
    function trackCellEdit(idx, header, oldValue, newValue) {
        if (oldValue === newValue) { return; }
        editHistory.push({ idx: idx, header: header, oldValue: oldValue, newValue: newValue });
        if (editHistory.length > MAX_EDIT_HISTORY) {
            editHistory.shift();
        }
    }

    /**
     * Undo last cell edit.
     */
    function undoLastEdit() {
        if (!editHistory.length) { return; }
        var edit = editHistory.pop();
        if (currentRows[edit.idx]) {
            currentRows[edit.idx][edit.header] = edit.oldValue;
            var $input = $table.find('tr[data-idx="' + edit.idx + '"] .wl-input[data-header="' + edit.header + '"]');
            if ($input.length) {
                $input.val(edit.oldValue).removeClass("wl-cell-edited");
            }
            UI.showMsg("Undid edit: <strong>" + _.escape(edit.header) + "</strong> row " + (edit.idx + 1), "info");
        }
    }

    /**
     * Bind all table event handlers.
     */
    function bindTableEvents(csvLocked) {
        // Select-all checkbox
        $table.off("change.wl", "#wl-check-all").on("change.wl", "#wl-check-all", function() {
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
        $table.off("change.wl", ".wl-row-check").on("change.wl", ".wl-row-check", function() {
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

        // Cell editing
        $table.off("change.wl", ".wl-input").on("change.wl", ".wl-input", function() {
            var $el = $(this);
            if ($el.hasClass("wl-expires-input")) { return; }
            var idx = $el.closest("tr").data("idx");
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

        // Auto-resize textareas
        $table.off("input.wl", "textarea.wl-input").on("input.wl", "textarea.wl-input", function() {
            autoResizeTextarea(this);
        });

        // Prevent newlines in textareas
        $table.off("keydown.wltextarea", "textarea.wl-input").on("keydown.wltextarea", "textarea.wl-input", function(e) {
            if (e.which === 13) { e.preventDefault(); }
        });

        // Paste handling
        $table.off("paste.wl", "textarea.wl-input").on("paste.wl", "textarea.wl-input", function(e) {
            var self = this;
            setTimeout(function() {
                var cleaned = $(self).val().replace(/[\r\n\t]+/g, " ");
                if (cleaned.length > MAX_CELL_CHARS) {
                    cleaned = cleaned.substring(0, MAX_CELL_CHARS);
                    UI.showMsg("Pasted text truncated to " + MAX_CELL_CHARS + " characters.", "warning");
                }
                $(self).val(cleaned);
                autoResizeTextarea(self);
            }, 0);
        });

        // Pagination
        $table.off("click.wl", "#btn-page-first").on("click.wl", "#btn-page-first", function() {
            if (currentPage > 0) { currentPage = 0; refreshTable(); }
        });
        $table.off("click.wl", "#btn-page-prev").on("click.wl", "#btn-page-prev", function() {
            if (currentPage > 0) { currentPage--; refreshTable(); }
        });
        $table.off("click.wl", "#btn-page-next").on("click.wl", "#btn-page-next", function() {
            syncInputs();
            var totalPages = Math.ceil(currentRows.length / ROWS_PER_PAGE);
            if (currentPage < totalPages - 1) { currentPage++; refreshTable(); }
        });
        $table.off("click.wl", "#btn-page-last").on("click.wl", "#btn-page-last", function() {
            syncInputs();
            var totalPages = Math.ceil(currentRows.length / ROWS_PER_PAGE);
            if (currentPage < totalPages - 1) { currentPage = totalPages - 1; refreshTable(); }
        });
        $table.off("change.wl", "#wl-page-size").on("change.wl", "#wl-page-size", function() {
            syncInputs();
            var firstVisibleRow = currentPage * ROWS_PER_PAGE;
            ROWS_PER_PAGE = parseInt($(this).val(), 10) || 10;
            currentPage = Math.floor(firstVisibleRow / ROWS_PER_PAGE);
            refreshTable();
        });

        // Add row button
        $table.off("click.wl", "#btn-add-row").on("click.wl", "#btn-add-row", function() {
            if (csvLocked) {
                UI.showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            if (currentRows.length >= MAX_ROWS) {
                UI.showMsg("Row limit reached: maximum <strong>" + MAX_ROWS + "</strong> rows allowed per CSV.", "error");
                return;
            }
            syncInputs();
            var newRow = {};
            currentHeaders.forEach(function(h) { newRow[h] = ""; });
            currentRows.push(newRow);
            State.set('currentRows', currentRows);
            currentPage = Math.ceil(currentRows.length / ROWS_PER_PAGE) - 1;
            refreshTable();
        });

        // Remove selected rows button
        $table.off("click.wl", "#btn-remove-selected").on("click.wl", "#btn-remove-selected", function() {
            if (csvLocked) {
                UI.showMsg("This CSV is locked by a pending approval request.", "error");
                return;
            }
            var selectedIdxs = Object.keys(selectedIdxSet).map(Number);
            if (!selectedIdxs.length) { return; }
            $(document).trigger('wl:rowRemovalRequested', { indices: selectedIdxs });
        });

        // Column resize
        bindResizeEvents();

        // Drag and drop
        bindDragEvents();

        updateRemoveSelectedBtn();
    }

    /**
     * Update "Remove Selected" button text and state.
     */
    function updateRemoveSelectedBtn() {
        var checked = Object.keys(selectedIdxSet).length;
        $table.find("#btn-remove-selected")
              .prop("disabled", checked === 0)
              .text(checked > 0 ? "Remove Selected (" + checked + ")" : "Remove Selected");
    }

    /**
     * Auto-resize a textarea to fit content.
     */
    function autoResizeTextarea(el) {
        el.style.height = 'auto';
        el.style.height = el.scrollHeight + 'px';
        el.style.overflow = el.scrollHeight > 90 ? 'auto' : 'hidden';
    }

    /**
     * Auto-resize all textareas in table.
     */
    function autoResizeAllTextareas() {
        $table.find("textarea.wl-input").each(function() {
            autoResizeTextarea(this);
        });
        $table.find("tbody tr").each(function() {
            var maxH = 0;
            $(this).find("textarea.wl-input").each(function() {
                var h = this.offsetHeight;
                if (h > maxH) maxH = h;
            });
            if (maxH > 0) {
                $(this).find("textarea.wl-input").each(function() {
                    this.style.height = maxH + "px";
                });
            }
        });
    }

    /**
     * Bind column resize events.
     */
    function bindResizeEvents() {
        $table.off("mousedown.wlresize", ".wl-col-resize-handle")
              .on("mousedown.wlresize", ".wl-col-resize-handle", function(e) {
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

        $(document).off("mousemove.wlresize").on("mousemove.wlresize", function(e) {
            if (!resizeState) { return; }
            var newWidth = Math.min(300, Math.max(50, resizeState.startWidth + (e.pageX - resizeState.startX)));
            resizeState.$th.css({ width: newWidth, minWidth: newWidth });
            colWidths[resizeState.header] = newWidth;
        });

        $(document).off("mouseup.wlresize").on("mouseup.wlresize", function() {
            if (!resizeState) { return; }
            resizeState = null;
            $("body").removeClass("wl-resizing");
            if (colWidths && Object.keys(colWidths).length) {
                clearTimeout(colWidthSaveTimer);
                colWidthSaveTimer = setTimeout(function() {
                    REST.restPost({
                        action: "save_col_widths",
                        col_widths: colWidths
                    });
                }, 300);
            }
        });
    }

    /**
     * Bind drag-and-drop reordering events.
     */
    function bindDragEvents() {
        // Prevent native drag
        $table.off("dragstart.wlblock")
              .on("dragstart.wlblock", ".wl-row-drag-handle, .wl-col-drag-handle", function(e) {
            e.preventDefault();
        });

        // Row reordering (simplified — full implementation in monolith)
        // Delegated to main controller for now
    }

    /**
     * Handler when currentRows change in State.
     */
    function onCurrentRowsChanged() {
        // Triggered when rows change externally — optionally refresh
    }

    /**
     * Format date to local datetime string.
     */
    function formatLocalDateTime(date) {
        var y = date.getFullYear();
        var m = String(date.getMonth() + 1).padStart(2, '0');
        var d = String(date.getDate()).padStart(2, '0');
        var h = String(date.getHours()).padStart(2, '0');
        var mi = String(date.getMinutes()).padStart(2, '0');
        return y + '-' + m + '-' + d + ' ' + h + ':' + mi;
    }

    // Public API
    return {
        init: init,
        refreshTable: refreshTable,
        syncInputs: syncInputs,
        getSelectedRows: getSelectedRows,
        undoLastEdit: undoLastEdit,
        // For entry point to manage full workflow
        buildRow: buildRow,
        trackCellEdit: trackCellEdit
    };
});
