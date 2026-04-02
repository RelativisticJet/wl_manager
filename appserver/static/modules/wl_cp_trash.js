/**
 * wl_cp_trash.js — Trash Management Module
 *
 * Provides trash table display and management for admins:
 * - View soft-deleted items (rules, CSVs) with expiration countdown
 * - Restore individual items from trash
 * - Purge individual items (superadmin)
 * - Adjust trash retention period (superadmin)
 *
 * Module-local state: trashItems, currentPage, totalTrash, pagination
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
    var trashItems = [];
    var currentPage = 1;
    var totalTrash = 0;
    var pollingInterval = null;
    var $trashContent = null;

    var ITEMS_PER_PAGE = 15;

    // ══════════════════════════════════════════════════════════════════
    // init(ctx) — Initialize module with context injection
    // ══════════════════════════════════════════════════════════════════
    function init(injectedCtx) {
        ctx = injectedCtx;

        if (!ctx.isAdmin) {
            console.error('wl_cp_trash: Admin access required');
            return Promise.reject(new Error('Admin access required'));
        }

        // Cache DOM reference
        $trashContent = $('#wl-cp-tab-trash');

        // Bind event handlers
        $(document).on('click.trash', '.wl-cp-trash-restore', function () {
            var trashId = $(this).data('trash-id');
            restoreItem(trashId);
        });

        $(document).on('click.trash', '.wl-cp-trash-purge', function () {
            var trashId = $(this).data('trash-id');
            var itemName = $(this).data('item-name');
            purgeItem(trashId, itemName);
        });

        $(document).on('click.trash', '.wl-cp-trash-purge-all', function () {
            purgeAll();
        });

        $(document).on('click.trash', '#wl-trash-change-retention', function () {
            updateRetention();
        });

        $(document).on('click.trash', '.wl-cp-trash-prev', function () {
            if (currentPage > 1) {
                currentPage--;
                render();
            }
        });

        $(document).on('click.trash', '.wl-cp-trash-next', function () {
            var totalPages = Math.ceil(totalTrash / ITEMS_PER_PAGE);
            if (currentPage < totalPages) {
                currentPage++;
                render();
            }
        });

        return load();
    }

    // ══════════════════════════════════════════════════════════════════
    // load() — Fetch trash items from backend
    // ══════════════════════════════════════════════════════════════════
    function load() {
        return REST.restGet('list_trash').done(function (data) {
            trashItems = data.items || [];
            totalTrash = data.total || 0;
            currentPage = 1; // Reset to first page on reload
            render();
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error loading trash';
            ctx.showAlert('Error', msg, 'error');
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // render() — Display trash table with pagination
    // ══════════════════════════════════════════════════════════════════
    function render() {
        if (!$trashContent) return;

        var totalPages = Math.ceil(totalTrash / ITEMS_PER_PAGE);
        if (currentPage > totalPages && totalPages > 0) {
            currentPage = totalPages;
        }

        var startIdx = (currentPage - 1) * ITEMS_PER_PAGE;
        var endIdx = Math.min(startIdx + ITEMS_PER_PAGE, trashItems.length);
        var pageItems = trashItems.slice(startIdx, endIdx);

        var html = '<div class="wl-cp-trash-container" style="padding:16px">';

        // Title and count
        html += '<h3 style="margin:0 0 12px 0">Trash Management</h3>';
        html += '<p style="color:var(--wl-text-muted,#888);font-size:13px;margin:0 0 12px 0">' +
            totalTrash + ' item(s) in trash</p>';

        // Retention setting (superadmin only)
        html += '<div style="margin-bottom:16px;padding:12px;background:var(--wl-bg-secondary,#1a1c20);' +
            'border-radius:4px">';
        html += '<div style="font-size:12px;color:var(--wl-text-muted,#888)">' +
            'Auto-purge retention: <strong id="wl-trash-retention-days">30</strong> days';
        if (ctx.isSuperAdmin) {
            html += ' <span id="wl-trash-change-retention" style="cursor:pointer;color:var(--wl-accent,#2962ff)">' +
                '(change)</span>';
        }
        html += '</div></div>';

        // Empty state
        if (trashItems.length === 0) {
            html += '<p style="color:var(--wl-text-muted,#888);padding:40px 20px;text-align:center">' +
                'Trash is empty</p>';
            html += '</div>';
            $trashContent.html(html);
            return;
        }

        // Trash table
        html += '<table class="wl-cp-trash-table" style="width:100%;border-collapse:collapse">' +
            '<thead><tr style="border-bottom:1px solid var(--wl-border,#444)">' +
            '<th style="text-align:left;padding:8px">Name</th>' +
            '<th style="text-align:left;padding:8px">Type</th>' +
            '<th style="text-align:left;padding:8px">Deleted By</th>' +
            '<th style="text-align:left;padding:8px">Deleted Date</th>' +
            '<th style="text-align:center;padding:8px">Days Left</th>' +
            '<th style="text-align:left;padding:8px">Actions</th>' +
            '</tr></thead><tbody>';

        pageItems.forEach(function (item) {
            var daysLeft = item.days_remaining || 0;
            var daysClass = daysLeft <= 7 ? 'color:#e74c3c;font-weight:600' :
                daysLeft <= 14 ? 'color:#ffc107;font-weight:600' : '';
            var trashId = _.escape(item.trash_id || '');
            var itemName = _.escape(item.name || '');

            html += '<tr class="wl-cp-trash-row" style="border-bottom:1px solid var(--wl-border,#333)">' +
                '<td style="padding:8px">' + itemName + '</td>' +
                '<td style="padding:8px">' + _.escape(item.item_type || '') + '</td>' +
                '<td style="padding:8px">' + _.escape(item.deleted_by || '') + '</td>' +
                '<td style="padding:8px">' + _.escape(item.deleted_at_human || '') + '</td>' +
                '<td style="text-align:center;padding:8px;' + daysClass + '">' + daysLeft + '</td>' +
                '<td style="padding:8px">' +
                '<span class="wl-cp-trash-restore btn btn-primary" data-trash-id="' + trashId +
                '" data-item-name="' + itemName + '" style="margin-right:4px;cursor:pointer">' +
                'Restore</span>';

            if (ctx.isSuperAdmin) {
                html += '<span class="wl-cp-trash-purge btn btn-danger" data-trash-id="' + trashId +
                    '" data-item-name="' + itemName + '" style="cursor:pointer">Purge</span>';
            }
            html += '</td></tr>';
        });

        html += '</tbody></table>';

        // Pagination
        if (totalPages > 1) {
            html += '<div style="margin-top:12px;display:flex;align-items:center;gap:8px">' +
                '<span class="wl-cp-trash-prev btn btn-small' +
                (currentPage === 1 ? ' disabled" style="pointer-events:none;opacity:0.4' : '') +
                '">Previous</span>' +
                '<span style="font-size:12px;color:var(--wl-text-muted,#888)">' +
                'Page ' + currentPage + ' of ' + totalPages + '</span>' +
                '<span class="wl-cp-trash-next btn btn-small' +
                (currentPage >= totalPages ? ' disabled" style="pointer-events:none;opacity:0.4' : '') +
                '">Next</span>';

            if (ctx.isSuperAdmin) {
                html += '<span class="wl-cp-trash-purge-all btn btn-danger" ' +
                    'style="margin-left:auto;cursor:pointer">Purge All</span>';
            }
            html += '</div>';
        } else if (ctx.isSuperAdmin && trashItems.length > 0) {
            html += '<div style="margin-top:12px">' +
                '<span class="wl-cp-trash-purge-all btn btn-danger" ' +
                'style="cursor:pointer">Purge All</span></div>';
        }

        html += '</div>';
        $trashContent.html(html);

        // Load current retention setting
        loadRetentionSetting();
    }

    // ══════════════════════════════════════════════════════════════════
    // restoreItem() — Restore item from trash
    // ══════════════════════════════════════════════════════════════════
    function restoreItem(trashId) {
        var item = trashItems.find(function (t) {
            return t.trash_id === trashId;
        });
        if (!item) return;

        ctx.showConfirm('Restore from Trash',
            'Restore ' + item.name + '? It will be restored to its original location.',
            { okLabel: 'Restore', cancelLabel: 'Cancel' }
        ).then(function (confirmed) {
            if (!confirmed) return;

            REST.restPost('restore_from_trash', { trash_id: trashId }).done(function (data) {
                ctx.showAlert('Success', 'Item restored from trash', 'success');
                load();
            }).fail(function (xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error restoring item';
                ctx.showAlert('Error', msg, 'error');
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // purgeItem() — Purge single item from trash (superadmin)
    // ══════════════════════════════════════════════════════════════════
    function purgeItem(trashId, itemName) {
        ctx.showConfirm('Purge from Trash',
            'Permanently delete ' + itemName + '? This cannot be undone.',
            { okLabel: 'Purge', cancelLabel: 'Cancel' }
        ).then(function (confirmed) {
            if (!confirmed) return;

            REST.restPost('purge_trash_item', { trash_id: trashId }).done(function (data) {
                ctx.showAlert('Success', 'Item permanently deleted', 'success');
                load();
            }).fail(function (xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error purging item';
                ctx.showAlert('Error', msg, 'error');
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // purgeAll() — Purge all items (superadmin only, requires dual approval)
    // ══════════════════════════════════════════════════════════════════
    function purgeAll() {
        ctx.showConfirm('Purge All Trash',
            'Permanently delete all ' + totalTrash + ' items? This cannot be undone and requires approval.',
            { okLabel: 'Purge All', cancelLabel: 'Cancel' }
        ).then(function (confirmed) {
            if (!confirmed) return;

            REST.restPost('purge_trash_all', {}).done(function (data) {
                ctx.showAlert('Success', 'All trash items purged (' + totalTrash + ' items)', 'success');
                load();
            }).fail(function (xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error purging trash';
                ctx.showAlert('Error', msg, 'error');
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // updateRetention() — Change trash retention period (superadmin)
    // ══════════════════════════════════════════════════════════════════
    function updateRetention() {
        ctx.showPrompt('Change Trash Retention',
            'Enter new retention period in days (7-365):',
            'Days'
        ).then(function (value) {
            if (value === null) return;

            var days = parseInt(value, 10);
            if (isNaN(days) || days < 7 || days > 365) {
                ctx.showAlert('Error', 'Must be a number between 7 and 365', 'error');
                return;
            }

            REST.restPost('set_trash_retention', { days: days }).done(function (data) {
                ctx.showAlert('Success', 'Retention period updated', 'success');
                loadRetentionSetting();
            }).fail(function (xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error updating retention';
                ctx.showAlert('Error', msg, 'error');
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // loadRetentionSetting() — Fetch and display current retention setting
    // ══════════════════════════════════════════════════════════════════
    function loadRetentionSetting() {
        REST.restGet('get_trash_config').done(function (data) {
            var days = (data.config && data.config.retention_days) || 30;
            $('#wl-trash-retention-days').text(days);
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // startPolling() — Start polling (stub — trash doesn't auto-refresh)
    // ══════════════════════════════════════════════════════════════════
    function startPolling() {
        // Trash doesn't auto-refresh; polling is a no-op
        // Kept for API consistency with other modules
    }

    // ══════════════════════════════════════════════════════════════════
    // stopPolling() — Stop polling (stub)
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
