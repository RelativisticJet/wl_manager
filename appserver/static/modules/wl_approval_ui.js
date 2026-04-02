/**
 * wl_approval_ui.js - Approval Request & Queue Display Module
 *
 * Manages approval UI: showing approval needed modals, tracking queue status,
 * displaying approval indicators.
 *
 * Public API: init(), showApprovalNeeded(action, reason), updateApprovalStatus(), getQueueStatus()
 *
 * Events:
 *   - Listens: state:pendingApprovalCount, state:adminPendingCount, state:csvLocked
 *   - Fires: wl:approvalRequested, wl:approvalStatusUpdated
 */

define([
    'modules/wl_constants',
    'modules/wl_state',
    'modules/wl_rest',
    'modules/wl_ui'
], function(Constants, State, REST, UI) {
    'use strict';

    var pendingApprovalCount = 0;
    var adminPendingCount = 0;
    var csvLocked = false;
    var isAdmin = false;

    /**
     * Initialize approval UI module.
     */
    function init() {
        State.on('state:pendingApprovalCount', function(count) {
            pendingApprovalCount = count || 0;
            updateApprovalIndicator();
        });

        State.on('state:adminPendingCount', function(count) {
            adminPendingCount = count || 0;
            updateApprovalIndicator();
        });

        State.on('state:csvLocked', function(locked) {
            csvLocked = locked || false;
        });

        State.on('state:isAdmin', function(admin) {
            isAdmin = admin || false;
        });

        pendingApprovalCount = State.get('pendingApprovalCount') || 0;
        adminPendingCount = State.get('adminPendingCount') || 0;
        csvLocked = State.get('csvLocked') || false;
        isAdmin = State.get('isAdmin') || false;

        // Periodically refresh queue status
        setInterval(function() {
            updateApprovalStatus();
        }, 30000); // every 30 seconds
    }

    /**
     * Show modal indicating action requires approval.
     * Tells user the action is queued for admin review.
     *
     * @param {string} actionType - Action type (e.g., "bulk_row_removal")
     * @param {string} reason - Action reason
     * @param {object} options - {title, message, details}
     */
    function showApprovalNeeded(actionType, reason, options) {
        options = options || {};
        var title = options.title || "Approval Required";
        var message = options.message || "Your action requires admin approval and has been queued for review.";

        var html = '<div class="wl-modal-overlay">';
        html += '<div class="wl-modal">';
        html += '<h3>' + _.escape(title) + '</h3>';
        html += '<p>' + message + '</p>';
        if (reason) {
            html += '<div class="wl-approval-reason">';
            html += '<strong>Reason:</strong> ' + _.escape(reason);
            html += '</div>';
        }
        if (options.details) {
            html += '<div class="wl-approval-details">';
            html += options.details;
            html += '</div>';
        }
        html += '<p class="wl-approval-note">You will be notified when your request is approved or rejected.</p>';
        html += '<div class="wl-form-actions">';
        html += '<span class="wl-modal-btn wl-btn-primary">OK</span>';
        html += '</div></div></div>';

        var $overlay = $(html).appendTo('body');

        $overlay.find('.wl-btn-primary').on('click', function() {
            $overlay.remove();
        });

        $overlay.on('click', function(e) {
            if (e.target === this) { $overlay.remove(); }
        });

        $(document).trigger('wl:approvalRequested', {
            actionType: actionType,
            reason: reason
        });
    }

    /**
     * Update approval status indicator in UI.
     * Polls server for current queue status.
     */
    function updateApprovalStatus() {
        REST.restGet({
            action: "get_pending_approvals"
        }).done(function(data) {
            var pending = (data.pending || []).length;
            var adminPending = isAdmin ? (data.admin_pending || []).length : 0;

            State.set('pendingApprovalCount', pending);
            if (isAdmin) {
                State.set('adminPendingCount', adminPending);
            }

            $(document).trigger('wl:approvalStatusUpdated', {
                pendingCount: pending,
                adminPendingCount: adminPending
            });
        }).fail(function(xhr) {
            console.warn('[wl_approval_ui] Failed to fetch approval status:', xhr);
        });
    }

    /**
     * Update visual approval indicator in DOM.
     */
    function updateApprovalIndicator() {
        var $indicator = $('.wl-approval-indicator');
        if (!$indicator.length) { return; }

        if (pendingApprovalCount > 0) {
            $indicator.removeClass('wl-hidden');
            $indicator.find('.wl-pending-count').text(pendingApprovalCount);
        } else {
            $indicator.addClass('wl-hidden');
        }

        if (isAdmin && adminPendingCount > 0) {
            var $adminIndicator = $('.wl-admin-approval-indicator');
            if ($adminIndicator.length) {
                $adminIndicator.removeClass('wl-hidden');
                $adminIndicator.find('.wl-admin-pending-count').text(adminPendingCount);
            }
        }
    }

    /**
     * Get current queue status.
     */
    function getQueueStatus() {
        return {
            pendingCount: pendingApprovalCount,
            adminPendingCount: adminPendingCount,
            csvLocked: csvLocked
        };
    }

    /**
     * Format daily limit enforcement message for display.
     *
     * @param {object} limitData - {action, limit, used, remaining, resetTime}
     * @returns {string} Formatted message
     */
    function formatDailyLimitMsg(limitData) {
        if (!limitData) { return "Daily limit exceeded."; }
        if (!limitData.allowed) {
            var msg = "Daily limit reached for " + _.escape(limitData.action || "this action") + ". ";
            msg += "Used " + limitData.used + " of " + limitData.limit + " allowed today.";
            if (limitData.resetTime) {
                msg += " Resets at " + _.escape(limitData.resetTime) + ".";
            }
            return msg;
        }
        return "";
    }

    /**
     * Show daily limit warning (not an error, just informational).
     */
    function showDailyLimitWarning(limitData) {
        var msg = formatDailyLimitMsg(limitData);
        if (msg) {
            UI.showMsg(msg, "warning");
        }
    }

    // Public API
    return {
        init: init,
        showApprovalNeeded: showApprovalNeeded,
        updateApprovalStatus: updateApprovalStatus,
        getQueueStatus: getQueueStatus,
        formatDailyLimitMsg: formatDailyLimitMsg,
        showDailyLimitWarning: showDailyLimitWarning
    };
});
