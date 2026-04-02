/**
 * wl_cp_usage.js — Analyst Usage Tracking Module
 *
 * Admin module for tracking and managing analyst edit daily limits:
 * - View current usage per analyst per action type
 * - Reset usage for selected analysts
 * - Reset usage for all analysts
 * - Auto-refresh every 10 seconds
 *
 * Module-local state: usageItems, currentPage, selectedRowIndices, pollingInterval
 * Public API: init(ctx), load(), startPolling(), stopPolling()
 */

define([
    'jquery',
    'underscore',
    'modules/wl_rest',
    'modules/wl_constants'
], function ($, _, REST, Constants) {
    'use strict';

    // ══════════════════════════════════════════════════════════════════
    // Module-local state
    // ══════════════════════════════════════════════════════════════════
    var ctx = null;
    var usageItems = [];
    var currentPage = 1;
    var totalAnalysts = 0;
    var selectedRowIndices = {};
    var pollingInterval = null;
    var $usageContent = null;

    var ITEMS_PER_PAGE = 20;
    var POLL_INTERVAL_MS = 10000;

    // ══════════════════════════════════════════════════════════════════
    // init(ctx) — Initialize module with context injection
    // ══════════════════════════════════════════════════════════════════
    function init(injectedCtx) {
        ctx = injectedCtx;

        if (!ctx.isAdmin) {
            console.error('wl_cp_usage: Admin access required');
            return Promise.reject(new Error('Admin access required'));
        }

        // Cache DOM reference
        $usageContent = $('#wl-cp-tab-usage');

        // Bind event handlers
        $(document).on('click.usage', '.wl-cp-usage-row-checkbox', function () {
            var idx = $(this).data('idx');
            if (selectedRowIndices[idx]) {
                delete selectedRowIndices[idx];
            } else {
                selectedRowIndices[idx] = true;
            }
            updateCheckboxState();
        });

        $(document).on('click.usage', '#wl-cp-usage-select-all', function () {
            var isChecked = $(this).prop('checked');
            var startIdx = (currentPage - 1) * ITEMS_PER_PAGE;
            var endIdx = Math.min(startIdx + ITEMS_PER_PAGE, usageItems.length);

            if (isChecked) {
                for (var i = startIdx; i < endIdx; i++) {
                    selectedRowIndices[i] = true;
                }
            } else {
                for (var i = startIdx; i < endIdx; i++) {
                    delete selectedRowIndices[i];
                }
            }
            updateCheckboxState();
        });

        $(document).on('click.usage', '#wl-cp-usage-reset-selected', function () {
            resetSelected();
        });

        $(document).on('click.usage', '#wl-cp-usage-reset-all', function () {
            resetAll();
        });

        $(document).on('click.usage', '.wl-cp-usage-prev', function () {
            if (currentPage > 1) {
                currentPage--;
                render();
            }
        });

        $(document).on('click.usage', '.wl-cp-usage-next', function () {
            var totalPages = Math.ceil(totalAnalysts / ITEMS_PER_PAGE);
            if (currentPage < totalPages) {
                currentPage++;
                render();
            }
        });

        return load();
    }

    // ══════════════════════════════════════════════════════════════════
    // load() — Fetch analyst usage data from backend
    // ══════════════════════════════════════════════════════════════════
    function load() {
        return REST.restGet('get_analyst_usage').done(function (data) {
            usageItems = data.items || [];
            totalAnalysts = usageItems.length;
            render();
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error loading usage data';
            ctx.showAlert('Error', msg, 'error');
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // render() — Display usage table with pagination
    // ══════════════════════════════════════════════════════════════════
    function render() {
        if (!$usageContent) return;

        var totalPages = Math.ceil(totalAnalysts / ITEMS_PER_PAGE);
        if (currentPage > totalPages && totalPages > 0) {
            currentPage = totalPages;
        }

        var startIdx = (currentPage - 1) * ITEMS_PER_PAGE;
        var endIdx = Math.min(startIdx + ITEMS_PER_PAGE, usageItems.length);
        var pageItems = usageItems.slice(startIdx, endIdx);

        var html = '<div class="wl-cp-usage-container" style="padding:16px">';

        // Title and description
        html += '<h3 style="margin:0 0 8px 0">Analyst Usage</h3>';
        html += '<p style="color:var(--wl-text-muted,#888);font-size:13px;margin:0 0 12px 0">' +
            'Current daily edit counts (resets at UTC boundaries). Auto-refreshes every 10 seconds.</p>';

        // Empty state
        if (usageItems.length === 0) {
            html += '<p style="color:var(--wl-text-muted,#888);padding:40px 20px;text-align:center">' +
                'No analyst activity recorded today</p>';
            html += '</div>';
            $usageContent.html(html);
            return;
        }

        // Search/filter (simple for Phase 2a)
        html += '<div style="margin-bottom:12px">' +
            '<input type="text" id="wl-cp-usage-search" placeholder="Filter by analyst..." ' +
            'style="width:100%;padding:8px;background:var(--wl-bg-input,#1a1c20);' +
            'color:var(--wl-text-primary,#e0e0e0);border:1px solid var(--wl-border,#444);' +
            'border-radius:4px;box-sizing:border-box" />' +
            '</div>';

        // Usage table
        html += '<table class="wl-cp-usage-table" style="width:100%;border-collapse:collapse">' +
            '<thead><tr style="border-bottom:1px solid var(--wl-border,#444)">' +
            '<th style="text-align:center;padding:8px">' +
            '<input type="checkbox" id="wl-cp-usage-select-all" style="cursor:pointer" /></th>' +
            '<th style="text-align:left;padding:8px">Analyst</th>' +
            '<th style="text-align:center;padding:8px">Edits Today</th>' +
            '<th style="text-align:center;padding:8px">Edits This Week</th>' +
            '<th style="text-align:center;padding:8px">Last Edit</th>' +
            '</tr></thead><tbody>';

        pageItems.forEach(function (item, pageIdx) {
            var absoluteIdx = startIdx + pageIdx;
            var isSelected = !!selectedRowIndices[absoluteIdx];

            html += '<tr class="wl-cp-usage-row" style="border-bottom:1px solid var(--wl-border,#333)">' +
                '<td style="text-align:center;padding:8px">' +
                '<input type="checkbox" class="wl-cp-usage-row-checkbox" data-idx="' + absoluteIdx +
                '" ' + (isSelected ? 'checked' : '') + ' style="cursor:pointer" /></td>' +
                '<td style="text-align:left;padding:8px">' + _.escape(item.analyst || '') + '</td>' +
                '<td style="text-align:center;padding:8px">' + (item.edits_today || 0) + '</td>' +
                '<td style="text-align:center;padding:8px">' + (item.edits_week || 0) + '</td>' +
                '<td style="text-align:center;padding:8px;font-size:12px">' +
                _.escape(item.last_edit_time || 'N/A') + '</td>' +
                '</tr>';
        });

        html += '</tbody></table>';

        // Pagination
        if (totalPages > 1) {
            html += '<div style="margin-top:12px;display:flex;align-items:center;gap:8px">' +
                '<span class="wl-cp-usage-prev btn btn-small' +
                (currentPage === 1 ? ' disabled" style="pointer-events:none;opacity:0.4' : '') +
                '">Previous</span>' +
                '<span style="font-size:12px;color:var(--wl-text-muted,#888)">' +
                'Page ' + currentPage + ' of ' + totalPages + ' (' + totalAnalysts + ' analysts)</span>' +
                '<span class="wl-cp-usage-next btn btn-small' +
                (currentPage >= totalPages ? ' disabled" style="pointer-events:none;opacity:0.4' : '') +
                '">Next</span>' +
                '</div>';
        }

        // Action buttons
        var selectedCount = Object.keys(selectedRowIndices).length;
        html += '<div style="margin-top:12px;display:flex;gap:8px">' +
            '<button id="wl-cp-usage-reset-selected" class="btn" ' +
            (selectedCount === 0 ? 'disabled style="opacity:0.5;pointer-events:none"' : 'style="cursor:pointer"') + '>' +
            'Reset Selected (' + selectedCount + ')</button>' +
            '<button id="wl-cp-usage-reset-all" class="btn btn-danger" style="cursor:pointer">' +
            'Reset All</button>' +
            '</div>';

        html += '</div>';
        $usageContent.html(html);
    }

    // ══════════════════════════════════════════════════════════════════
    // updateCheckboxState() — Update checkbox visibility and buttons
    // ══════════════════════════════════════════════════════════════════
    function updateCheckboxState() {
        var startIdx = (currentPage - 1) * ITEMS_PER_PAGE;
        var endIdx = Math.min(startIdx + ITEMS_PER_PAGE, usageItems.length);
        var pageCount = endIdx - startIdx;
        var pageSelectedCount = 0;

        for (var i = startIdx; i < endIdx; i++) {
            if (selectedRowIndices[i]) pageSelectedCount++;
        }

        // Update "Select All" checkbox state
        var $selectAll = $('#wl-cp-usage-select-all');
        if ($selectAll.length) {
            if (pageSelectedCount === 0) {
                $selectAll.prop('checked', false).prop('indeterminate', false);
            } else if (pageSelectedCount === pageCount) {
                $selectAll.prop('checked', true).prop('indeterminate', false);
            } else {
                $selectAll.prop('indeterminate', true);
            }
        }

        // Update row checkboxes
        $('.wl-cp-usage-row-checkbox').each(function () {
            var idx = $(this).data('idx');
            $(this).prop('checked', !!selectedRowIndices[idx]);
        });

        // Update "Reset Selected" button
        var selectedCount = Object.keys(selectedRowIndices).length;
        var $resetBtn = $('#wl-cp-usage-reset-selected');
        if ($resetBtn.length) {
            if (selectedCount === 0) {
                $resetBtn.prop('disabled', true).css('opacity', '0.5').css('pointer-events', 'none');
            } else {
                $resetBtn.prop('disabled', false).css('opacity', '1').css('pointer-events', 'auto');
                $resetBtn.text('Reset Selected (' + selectedCount + ')');
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // resetSelected() — Reset usage for selected analysts
    // ══════════════════════════════════════════════════════════════════
    function resetSelected() {
        var selectedCount = Object.keys(selectedRowIndices).length;
        if (selectedCount === 0) {
            ctx.showAlert('Info', 'No analysts selected', 'info');
            return;
        }

        var selectedAnalysts = [];
        Object.keys(selectedRowIndices).forEach(function (idx) {
            var item = usageItems[parseInt(idx, 10)];
            if (item) selectedAnalysts.push(item.analyst);
        });

        ctx.showConfirm('Reset Usage',
            'Reset daily edit counters for ' + selectedCount + ' analyst(s)? They will see counters reset immediately.',
            { okLabel: 'Reset', cancelLabel: 'Cancel' }
        ).then(function (confirmed) {
            if (!confirmed) return;

            REST.restPost('reset_daily_usage', { analysts: selectedAnalysts }).done(function (data) {
                ctx.showAlert('Success', 'Usage reset for ' + selectedCount + ' analyst(s)', 'success');
                selectedRowIndices = {};
                load();
            }).fail(function (xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error resetting usage';
                ctx.showAlert('Error', msg, 'error');
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // resetAll() — Reset usage for all analysts
    // ══════════════════════════════════════════════════════════════════
    function resetAll() {
        ctx.showConfirm('Reset All Usage',
            'Reset daily edit counters for all ' + totalAnalysts + ' analyst(s)? This cannot be undone.',
            { okLabel: 'Reset All', cancelLabel: 'Cancel' }
        ).then(function (confirmed) {
            if (!confirmed) return;

            REST.restPost('reset_daily_usage', { analysts: 'all' }).done(function (data) {
                ctx.showAlert('Success', 'Usage reset for all analysts', 'success');
                selectedRowIndices = {};
                load();
            }).fail(function (xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error resetting usage';
                ctx.showAlert('Error', msg, 'error');
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // startPolling() — Start auto-refresh polling
    // ══════════════════════════════════════════════════════════════════
    function startPolling() {
        stopPolling();
        pollingInterval = setInterval(function () {
            load();
        }, POLL_INTERVAL_MS);
    }

    // ══════════════════════════════════════════════════════════════════
    // stopPolling() — Stop auto-refresh polling
    // ══════════════════════════════════════════════════════════════════
    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Public API
    // ══════════════════════════════════════════════════════════════════
    return {
        init: init,
        load: load,
        startPolling: startPolling,
        stopPolling: stopPolling
    };
});
