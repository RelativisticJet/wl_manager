/**
 * wl_versions.js - Version History & Revert Module
 *
 * Manages version history display and revert functionality.
 *
 * Public API: init(), loadVersions(), showVersionDropdown(), revertToVersion(versionId), getVersionHistory()
 *
 * Events:
 *   - Listens: state:csvFileSelected, state:selectedCsv
 *   - Fires: wl:csvReverted, wl:versionsLoaded
 */

define([
    'modules/wl_constants',
    'modules/wl_state',
    'modules/wl_rest',
    'modules/wl_ui'
], function(Constants, State, REST, UI) {
    'use strict';

    var versions = [];
    var selectedCsv = "";
    var selectedApp = "";
    var currentRowCount = 0;

    /**
     * Initialize versions module.
     */
    function init() {
        State.on('state:csvFileSelected', function() {
            selectedCsv = State.get('selectedCsv') || "";
            selectedApp = State.get('selectedApp') || "";
            if (selectedCsv) {
                loadVersions();
            }
        });

        State.on('state:selectedCsv', function(csv) {
            selectedCsv = csv || "";
            if (selectedCsv) {
                loadVersions();
            }
        });

        State.on('state:currentRows', function(rows) {
            currentRowCount = (rows || []).length;
        });

        selectedCsv = State.get('selectedCsv') || "";
        selectedApp = State.get('selectedApp') || "";
        currentRowCount = (State.get('currentRows') || []).length;
    }

    /**
     * Load version history from server.
     */
    function loadVersions() {
        if (!selectedCsv) { return; }

        REST.restGet({
            action: "get_versions",
            csv_file: selectedCsv,
            app_context: selectedApp
        }).done(function(data) {
            versions = data.versions || [];
            $(document).trigger('wl:versionsLoaded', {
                csv: selectedCsv,
                versions: versions
            });
        }).fail(function(xhr) {
            console.warn('[wl_versions] Failed to load versions:', xhr);
            versions = [];
        });
    }

    /**
     * Show version history dropdown.
     * Displays "Current" at top (non-selectable) plus last 5 previous versions.
     * Format: "24-02-2026 12:37:16 (42 rows, by admin)"
     */
    function showVersionDropdown() {
        if (!versions || !versions.length) {
            UI.showMsg("No version history available for this CSV.", "info");
            return;
        }

        var html = '<div class="wl-modal-overlay">';
        html += '<div class="wl-modal wl-versions-modal">';
        html += '<h3>Version History</h3>';
        html += '<div class="wl-versions-list">';

        // Current version at top
        html += '<div class="wl-version-entry wl-version-current">';
        html += '<span class="wl-version-label">Current</span> ';
        html += '<span class="wl-version-info">(' + currentRowCount + ' rows)</span>';
        html += '</div>';

        // Previous versions (last 5)
        var displayed = 0;
        for (var i = 0; i < versions.length && displayed < 5; i++) {
            var v = versions[i];
            var timestamp = v.timestamp || v.id;
            var author = v.author || "unknown";
            var rowCount = v.row_count || 0;
            var label = timestamp + ' (' + rowCount + ' rows, by ' + author + ')';

            html += '<div class="wl-version-entry" data-version-id="' + _.escape(v.id) + '">';
            html += '<span class="wl-version-label">' + _.escape(label) + '</span>';
            html += '</div>';
            displayed++;
        }

        html += '</div>';
        html += '<div class="wl-form-actions">';
        html += '<span class="wl-modal-btn wl-btn-cancel">Cancel</span>';
        html += '</div></div></div>';

        var $overlay = $(html).appendTo('body');

        $overlay.find('.wl-version-entry:not(.wl-version-current)').on('click', function() {
            var versionId = $(this).data('version-id');
            $overlay.remove();
            showRevertConfirm(versionId);
        });

        $overlay.find('.wl-btn-cancel').on('click', function() {
            $overlay.remove();
        });

        $overlay.on('click', function(e) {
            if (e.target === this) { $overlay.remove(); }
        });
    }

    /**
     * Show confirmation before revert with reason required.
     */
    function showRevertConfirm(versionId) {
        var version = versions.find(function(v) { return v.id === versionId; });
        if (!version) {
            UI.showMsg("Version not found.", "error");
            return;
        }

        var timestamp = version.timestamp || version.id;
        var html = '<div class="wl-modal-overlay">';
        html += '<div class="wl-modal">';
        html += '<h3>Revert to Version</h3>';
        html += '<p>Revert to version <strong>' + _.escape(timestamp) + '</strong>?</p>';
        html += '<p>This will restore the CSV to its state at that time and create a new version snapshot.</p>';
        html += '<form id="wl-revert-form">';
        html += '<div class="wl-form-group">';
        html += '<label for="wl-revert-reason">Reason for revert (required)</label>';
        html += '<textarea id="wl-revert-reason" class="wl-modal-input" maxlength="500" rows="3" ' +
                'placeholder="Why are you reverting to this version?"></textarea>';
        html += '<span class="wl-form-help">Min 5 chars</span>';
        html += '</div>';
        html += '<div class="wl-form-actions">';
        html += '<span class="wl-modal-btn wl-btn-cancel">Cancel</span> ';
        html += '<span class="wl-modal-btn wl-btn-danger">Revert</span>';
        html += '</div></form></div></div>';

        var $overlay = $(html).appendTo('body');
        var $form = $overlay.find('#wl-revert-form');
        var $reason = $overlay.find('#wl-revert-reason');

        $overlay.find('.wl-btn-cancel').on('click', function() {
            $overlay.remove();
        });

        $form.on('submit', function(e) {
            e.preventDefault();
            var reason = $reason.val().trim();
            if (reason.length < 5) {
                UI.showMsg("Reason must be at least 5 characters.", "error");
                return;
            }
            $overlay.remove();
            revertToVersion(versionId, reason);
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
     * Revert CSV to specified version.
     */
    function revertToVersion(versionId, reason) {
        if (!selectedCsv || !versionId) {
            UI.showMsg("Missing CSV or version ID.", "error");
            return;
        }

        UI.showMsg("Reverting to version&hellip;", "info");

        REST.restPost({
            action: "revert_csv",
            csv_file: selectedCsv,
            app_context: selectedApp,
            version_id: versionId,
            reason: reason
        }).done(function(data) {
            if (data.error) {
                UI.showMsg(_.escape(data.error), "error");
                return;
            }
            UI.showMsg("Reverted to version " + _.escape(versionId), "success");

            // Update State with reverted data
            if (data.headers && data.rows) {
                State.set('currentHeaders', data.headers);
                State.set('currentRows', data.rows);
                State.set('originalRows', data.rows.map(function(r) {
                    return $.extend({}, r);
                }));
            }

            // Reload versions
            loadVersions();

            $(document).trigger('wl:csvReverted', {
                versionId: versionId,
                reason: reason
            });
        }).fail(function(xhr) {
            UI.showMsg("Failed to revert CSV. Please try again.", "error");
            console.error('[wl_versions] Revert failed:', xhr);
        });
    }

    /**
     * Get current version history array.
     */
    function getVersionHistory() {
        return versions.slice();
    }

    // Public API
    return {
        init: init,
        loadVersions: loadVersions,
        showVersionDropdown: showVersionDropdown,
        revertToVersion: revertToVersion,
        getVersionHistory: getVersionHistory
    };
});
