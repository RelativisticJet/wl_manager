/**
 * Whitelist Manager — Diff Renderer Module
 *
 * Renders git-style diffs showing added, removed, and edited rows.
 * Pure rendering function — no side effects beyond DOM updates.
 */

define(["jquery", "underscore"], function ($, _) {
    "use strict";

    // ══════════════════════════════════════════════════════════════════
    // Constants
    // ══════════════════════════════════════════════════════════════════
    var DIFF_MAX_ROWS = 10;     // show detail for first N edits
    var DIFF_MAX_COLS = 8;      // max columns per pane (key + changed + context)

    // ══════════════════════════════════════════════════════════════════
    // Private state
    // ══════════════════════════════════════════════════════════════════
    var $diff = null;

    // ══════════════════════════════════════════════════════════════════
    // Module initialization
    // ══════════════════════════════════════════════════════════════════
    function init(options) {
        $diff = options.$diff;
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
    // Public API
    // ══════════════════════════════════════════════════════════════════
    return {
        init: init,
        renderDiff: renderDiff
    };
});
