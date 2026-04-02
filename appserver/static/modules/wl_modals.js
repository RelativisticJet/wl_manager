/**
 * wl_modals.js - Modal Dialogs Module
 *
 * Provides modal dialogs for add/remove/edit row operations.
 *
 * Public API: init(), showAddRowModal(callback), showRemoveModal(rows, callback), showEditModal(rowIndex, fields, callback)
 *
 * Events:
 *   - Listens: state:currentRows, state:currentHeaders, state:csvLocked
 *   - Fires: wl:rowAdded, wl:rowRemoved, wl:rowEdited
 */

define([
    'modules/wl_constants',
    'modules/wl_state',
    'modules/wl_rest',
    'modules/wl_ui'
], function(Constants, State, REST, UI) {
    'use strict';

    var currentRows = [];
    var currentHeaders = [];
    var csvLocked = false;

    var MIN_REASON_LENGTH = 5;
    var MAX_REASON_LENGTH = 500;

    /**
     * Initialize modals module.
     */
    function init() {
        State.on('state:currentRows', function(rows) {
            currentRows = rows || [];
        });
        State.on('state:currentHeaders', function(headers) {
            currentHeaders = headers || [];
        });
        State.on('state:csvLocked', function(locked) {
            csvLocked = locked || false;
        });

        currentRows = State.get('currentRows') || [];
        currentHeaders = State.get('currentHeaders') || [];
        csvLocked = State.get('csvLocked') || false;
    }

    /**
     * Show modal to add a new row.
     * Form has input fields for each column, validation enforced.
     *
     * @param {function} callback - Called with new row data on submit
     */
    function showAddRowModal(callback) {
        if (csvLocked) {
            UI.showMsg("CSV is locked by a pending approval request.", "error");
            return;
        }

        var visibleHeaders = currentHeaders.filter(function(h) {
            return h.charAt(0) !== '_';
        });

        var html = '<div class="wl-modal-overlay">';
        html += '<div class="wl-modal">';
        html += '<h3>Add New Row</h3>';
        html += '<form id="wl-add-row-form">';
        visibleHeaders.forEach(function(h) {
            html += '<div class="wl-form-group">';
            html += '<label for="wl-add-field-' + _.escape(h) + '">' + _.escape(h) + '</label>';
            html += '<textarea id="wl-add-field-' + _.escape(h) + '" class="wl-modal-input" ' +
                    'data-header="' + _.escape(h) + '" maxlength="1000" rows="2" placeholder="Enter value"></textarea>';
            html += '</div>';
        });
        html += '<div class="wl-form-actions">';
        html += '<span class="wl-modal-btn wl-btn-cancel">Cancel</span> ';
        html += '<span class="wl-modal-btn wl-btn-primary">Add Row</span>';
        html += '</div></form></div></div>';

        var $overlay = $(html).appendTo('body');
        var $form = $overlay.find('#wl-add-row-form');

        $overlay.find('.wl-btn-cancel').on('click', function() {
            $overlay.remove();
        });

        $form.on('submit', function(e) {
            e.preventDefault();
            var newRow = {};
            var valid = true;

            $form.find('.wl-modal-input').each(function() {
                var header = $(this).data('header');
                var val = $(this).val().trim();
                newRow[header] = val;
            });

            // Validation: all required fields non-empty (optional — adjust as needed)
            if (!valid) {
                UI.showMsg("Please fill in required fields.", "error");
                return;
            }

            $overlay.remove();
            if (callback) { callback(newRow); }

            $(document).trigger('wl:rowAdded', newRow);
        });

        $overlay.find('.wl-btn-primary').on('click', function() {
            $form.submit();
        });

        // Close on overlay click
        $overlay.on('click', function(e) {
            if (e.target === this) { $overlay.remove(); }
        });
    }

    /**
     * Show modal to remove one or more rows.
     * Requires a reason (5+ chars).
     *
     * @param {array} rowIndices - Indices to remove
     * @param {function} callback - Called with reason on confirm
     */
    function showRemoveModal(rowIndices, callback) {
        if (csvLocked) {
            UI.showMsg("CSV is locked by a pending approval request.", "error");
            return;
        }

        var count = rowIndices ? rowIndices.length : 1;
        var title = count === 1 ? "Remove Row" : "Remove " + count + " Rows";
        var msg = count === 1
            ? "Remove this row? This action will be saved immediately and logged in the audit trail."
            : "Remove <strong>" + count + "</strong> selected row(s)? This action will be saved immediately and logged in the audit trail.";

        var html = '<div class="wl-modal-overlay">';
        html += '<div class="wl-modal">';
        html += '<h3>' + title + '</h3>';
        html += '<p>' + msg + '</p>';
        html += '<form id="wl-remove-form">';
        html += '<div class="wl-form-group">';
        html += '<label for="wl-remove-reason">Reason for removal (required)</label>';
        html += '<textarea id="wl-remove-reason" class="wl-modal-input" maxlength="' + MAX_REASON_LENGTH + '" ' +
                'rows="3" placeholder="Why are you removing this row?"></textarea>';
        html += '<span class="wl-form-help">Min ' + MIN_REASON_LENGTH + ' chars</span>';
        html += '</div>';
        html += '<div class="wl-form-actions">';
        html += '<span class="wl-modal-btn wl-btn-cancel">Cancel</span> ';
        html += '<span class="wl-modal-btn wl-btn-danger">Remove</span>';
        html += '</div></form></div></div>';

        var $overlay = $(html).appendTo('body');
        var $form = $overlay.find('#wl-remove-form');
        var $reason = $overlay.find('#wl-remove-reason');

        $overlay.find('.wl-btn-cancel').on('click', function() {
            $overlay.remove();
        });

        $form.on('submit', function(e) {
            e.preventDefault();
            var reason = $reason.val().trim();
            if (reason.length < MIN_REASON_LENGTH) {
                UI.showMsg("Reason must be at least " + MIN_REASON_LENGTH + " characters.", "error");
                return;
            }
            $overlay.remove();
            if (callback) { callback(reason); }
            $(document).trigger('wl:rowRemoved', { indices: rowIndices, reason: reason });
        });

        $overlay.find('.wl-btn-danger').on('click', function() {
            $form.submit();
        });

        $overlay.on('click', function(e) {
            if (e.target === this) { $overlay.remove(); }
        });

        $reason.focus();
    }

    /**
     * Show modal to edit a single row's fields.
     *
     * @param {number} rowIndex - Row index to edit
     * @param {object} callback - Called with updated row on submit
     */
    function showEditModal(rowIndex, callback) {
        if (csvLocked) {
            UI.showMsg("CSV is locked by a pending approval request.", "error");
            return;
        }

        if (rowIndex < 0 || rowIndex >= currentRows.length) {
            UI.showMsg("Row not found.", "error");
            return;
        }

        var row = currentRows[rowIndex];
        var visibleHeaders = currentHeaders.filter(function(h) {
            return h.charAt(0) !== '_';
        });

        var html = '<div class="wl-modal-overlay">';
        html += '<div class="wl-modal">';
        html += '<h3>Edit Row #' + (rowIndex + 1) + '</h3>';
        html += '<form id="wl-edit-row-form">';
        visibleHeaders.forEach(function(h) {
            var val = row[h] || "";
            html += '<div class="wl-form-group">';
            html += '<label for="wl-edit-field-' + _.escape(h) + '">' + _.escape(h) + '</label>';
            html += '<textarea id="wl-edit-field-' + _.escape(h) + '" class="wl-modal-input" ' +
                    'data-header="' + _.escape(h) + '" maxlength="1000" rows="2">' + _.escape(val) + '</textarea>';
            html += '</div>';
        });
        html += '<div class="wl-form-actions">';
        html += '<span class="wl-modal-btn wl-btn-cancel">Cancel</span> ';
        html += '<span class="wl-modal-btn wl-btn-primary">Save</span>';
        html += '</div></form></div></div>';

        var $overlay = $(html).appendTo('body');
        var $form = $overlay.find('#wl-edit-row-form');

        $overlay.find('.wl-btn-cancel').on('click', function() {
            $overlay.remove();
        });

        $form.on('submit', function(e) {
            e.preventDefault();
            var updatedRow = $.extend({}, row);

            $form.find('.wl-modal-input').each(function() {
                var header = $(this).data('header');
                var val = $(this).val();
                updatedRow[header] = val;
            });

            $overlay.remove();
            if (callback) { callback(updatedRow); }
            $(document).trigger('wl:rowEdited', { index: rowIndex, row: updatedRow });
        });

        $overlay.find('.wl-btn-primary').on('click', function() {
            $form.submit();
        });

        $overlay.on('click', function(e) {
            if (e.target === this) { $overlay.remove(); }
        });
    }

    /**
     * Show generic confirmation modal with custom title and message.
     * Used for approval flows, etc.
     *
     * @param {string} title - Modal title
     * @param {string} message - Modal message (HTML)
     * @param {object} options - {confirmText, cancelText, confirmClass, onConfirm, onCancel}
     */
    function showConfirmModal(title, message, options) {
        options = options || {};
        var confirmText = options.confirmText || "Confirm";
        var cancelText = options.cancelText || "Cancel";
        var confirmClass = options.confirmClass || "wl-btn-primary";
        var onConfirm = options.onConfirm || function() {};
        var onCancel = options.onCancel || function() {};

        var html = '<div class="wl-modal-overlay">';
        html += '<div class="wl-modal">';
        html += '<h3>' + _.escape(title) + '</h3>';
        html += '<p>' + message + '</p>';
        html += '<div class="wl-form-actions">';
        html += '<span class="wl-modal-btn wl-btn-cancel">' + _.escape(cancelText) + '</span> ';
        html += '<span class="wl-modal-btn ' + confirmClass + '">' + _.escape(confirmText) + '</span>';
        html += '</div></div></div>';

        var $overlay = $(html).appendTo('body');

        $overlay.find('.wl-btn-cancel').on('click', function() {
            $overlay.remove();
            onCancel();
        });

        $overlay.find('.' + confirmClass).on('click', function() {
            $overlay.remove();
            onConfirm();
        });

        $overlay.on('click', function(e) {
            if (e.target === this) { $overlay.remove(); onCancel(); }
        });
    }

    // Public API
    return {
        init: init,
        showAddRowModal: showAddRowModal,
        showRemoveModal: showRemoveModal,
        showEditModal: showEditModal,
        showConfirmModal: showConfirmModal
    };
});
