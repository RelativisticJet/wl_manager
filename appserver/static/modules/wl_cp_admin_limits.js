/**
 * wl_cp_admin_limits.js — Admin Limits Configuration Module
 *
 * Superadmin-only module for managing system-wide admin action limits:
 * - View current and default limits for admin actions
 * - Save new limit values with change detection
 * - Reset to factory defaults
 *
 * Module-local state: loadedLimits, currentLimits, $form
 * Public API: init(ctx), load()
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
    var loadedLimits = {};
    var currentLimits = {};
    var $adminLimitsContent = null;

    // ══════════════════════════════════════════════════════════════════
    // init(ctx) — Initialize module with context injection
    // ══════════════════════════════════════════════════════════════════
    function init(injectedCtx) {
        ctx = injectedCtx;

        // Superadmin check — fail fast if not authorized
        if (!ctx.isSuperAdmin) {
            console.error('wl_cp_admin_limits: Superadmin access required');
            return Promise.reject(new Error('Superadmin access required'));
        }

        // Cache DOM reference
        $adminLimitsContent = $('#wl-cp-tab-admin');

        // Bind event handlers (delegated to document for future re-renders)
        $(document).on('click.adminlimits', '#wl-cp-admin-limits-save', function () {
            saveLimits();
        });

        $(document).on('click.adminlimits', '#wl-cp-admin-limits-reset', function () {
            resetDefaults();
        });

        $(document).on('change.adminlimits', '.wl-cp-admin-limit-input', function () {
            updateSaveButtonState();
        });

        return load();
    }

    // ══════════════════════════════════════════════════════════════════
    // load() — Fetch admin limits from backend
    // ══════════════════════════════════════════════════════════════════
    function load() {
        return REST.restGet('get_admin_limits').done(function (data) {
            loadedLimits = JSON.parse(JSON.stringify(data.limits || {}));
            currentLimits = JSON.parse(JSON.stringify(loadedLimits));
            render();
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error loading admin limits';
            ctx.showAlert('Error', msg, 'error');
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // render() — Display admin limits form
    // ══════════════════════════════════════════════════════════════════
    function render() {
        if (!$adminLimitsContent) return;

        var html = '<div class="wl-cp-admin-limits-form" style="padding:16px;max-width:600px">';

        // Title and description
        html += '<h3 style="margin:0 0 8px 0">Admin Limits</h3>';
        html += '<p style="color:var(--wl-text-muted,#888);font-size:13px;margin:0 0 16px 0">' +
            'Advanced configuration for admin-level action thresholds. Superadmin access required.</p>';

        // Form fields
        var fields = [
            { key: 'rule_deletion', label: 'Rule deletion limit',
              desc: 'Max rules per admin per period' },
            { key: 'csv_deletion', label: 'CSV deletion limit',
              desc: 'Max CSVs per admin per period' },
            { key: 'approval_count', label: 'Approval actions limit',
              desc: 'Max approvals per admin per period' },
            { key: 'limit_changes', label: 'Limit configuration changes',
              desc: 'Max times per admin per period' }
        ];

        html += '<div style="display:flex;flex-direction:column;gap:12px">';

        fields.forEach(function (field) {
            var value = currentLimits[field.key] || 0;
            html += '<div style="display:flex;flex-direction:column;gap:4px">' +
                '<label style="font-size:12px;font-weight:500;color:var(--wl-text-primary,#e0e0e0)">' +
                _.escape(field.label) + '</label>' +
                '<input type="number" class="wl-cp-admin-limit-input" ' +
                'data-key="' + field.key + '" value="' + value + '" ' +
                'style="width:100%;padding:8px;background:var(--wl-bg-input,#1a1c20);' +
                'color:var(--wl-text-primary,#e0e0e0);border:1px solid var(--wl-border,#444);' +
                'border-radius:4px;box-sizing:border-box" />' +
                '<span style="font-size:11px;color:var(--wl-text-muted,#888)">' +
                _.escape(field.desc) + ' (0 = disabled, -1 = unlimited)</span>' +
                '</div>';
        });

        html += '</div>';

        // Form buttons
        html += '<div style="margin-top:16px;display:flex;gap:8px">' +
            '<button id="wl-cp-admin-limits-save" class="btn btn-primary" style="cursor:pointer">' +
            'Save Admin Limits</button>' +
            '<button id="wl-cp-admin-limits-reset" class="btn" style="cursor:pointer">' +
            'Reset to Defaults</button>' +
            '</div>';

        html += '</div>';
        $adminLimitsContent.html(html);

        updateSaveButtonState();
    }

    // ══════════════════════════════════════════════════════════════════
    // updateSaveButtonState() — Enable/disable Save button based on changes
    // ══════════════════════════════════════════════════════════════════
    function updateSaveButtonState() {
        var hasChanges = false;

        $('.wl-cp-admin-limit-input').each(function () {
            var key = $(this).data('key');
            var value = parseInt($(this).val(), 10) || 0;
            if (value !== loadedLimits[key]) {
                hasChanges = true;
                return false; // break
            }
        });

        var $saveBtn = $('#wl-cp-admin-limits-save');
        if ($saveBtn.length) {
            if (hasChanges) {
                $saveBtn.prop('disabled', false).css('opacity', '1');
            } else {
                $saveBtn.prop('disabled', true).css('opacity', '0.5');
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // saveLimits() — Save limit values to backend
    // ══════════════════════════════════════════════════════════════════
    function saveLimits() {
        var newLimits = {};
        var hasChanges = false;

        $('.wl-cp-admin-limit-input').each(function () {
            var key = $(this).data('key');
            var value = parseInt($(this).val(), 10);

            if (isNaN(value)) {
                ctx.showAlert('Error', 'Invalid value for ' + key, 'error');
                hasChanges = false;
                return false; // break
            }

            if (value !== loadedLimits[key]) {
                newLimits[key] = value;
                hasChanges = true;
            }
        });

        if (!hasChanges) {
            ctx.showAlert('Info', 'No changes detected', 'info');
            return;
        }

        REST.restPost('set_admin_limits', { limits: newLimits }).done(function (data) {
            ctx.showAlert('Success', 'Admin limits updated', 'success');
            load();
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error saving limits';
            ctx.showAlert('Error', msg, 'error');
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // resetDefaults() — Reset limits to factory defaults
    // ══════════════════════════════════════════════════════════════════
    function resetDefaults() {
        ctx.showConfirm('Reset to Factory Defaults',
            'Restore admin limits to factory defaults? This cannot be undone.',
            { okLabel: 'Reset', cancelLabel: 'Cancel' }
        ).then(function (confirmed) {
            if (!confirmed) return;

            REST.restPost('reset_admin_limits', {}).done(function (data) {
                ctx.showAlert('Success', 'Admin limits reset to defaults', 'success');
                load();
            }).fail(function (xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Error resetting limits';
                ctx.showAlert('Error', msg, 'error');
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Public API
    // ══════════════════════════════════════════════════════════════════
    return {
        init: init,
        load: load
    };
});
