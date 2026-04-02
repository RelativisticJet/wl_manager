/**
 * Daily Limits Module — AMD
 *
 * Manages the daily limits tab: form fields, validation, change history,
 * and save/reset handlers for analyst daily action limits.
 *
 * Exports: init, load
 */

define([
    'jquery',
    'underscore',
    'modules/wl_rest',
    'modules/wl_constants'
], function($, _, REST, Constants) {
    'use strict';

    // Module-local state
    var loadedLimits = {};
    var currentLimits = {};
    var changeHistory = [];
    var showingHistory = false;
    var $limitsContent = null;
    var ctx = null;

    function init(context) {
        ctx = context;
        if (!ctx.isAdmin) {
            return Promise.reject("Access denied: admin role required");
        }

        $limitsContent = $("#wl-cp-tab-limits");
        if (!$limitsContent.length) {
            return Promise.reject("Limits tab container not found");
        }

        // Bind handlers (delegated)
        $(document).off("click.wllimits").on("click.wllimits", ".wl-cp-limits-save-btn", saveLimits);
        $(document).off("click.wllimits").on("click.wllimits", ".wl-cp-limits-reset-btn", resetDefaults);
        $(document).off("click.wllimits").on("click.wllimits", ".wl-cp-limits-history-toggle", toggleHistoryClick);
        $(document).off("input.wllimits").on("input.wllimits", ".wl-cp-limits-input", inputChange);

        return load();
    }

    function load() {
        return REST.restGet({ action: "get_daily_limits" }).done(function(data) {
            loadedLimits = deepCopy(data.limits || {});
            currentLimits = deepCopy(data.limits || {});
            changeHistory = data.change_history || [];
            render();
        }).fail(function(xhr) {
            var err = "Error loading limits";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
            ctx.showAlert("Error", err);
        });
    }

    function render() {
        var html = '';

        // Heading
        html += '<h3 style="margin:12px 0 4px;font-size:18px;font-weight:600">Edit Daily Limits</h3>';
        html += '<p style="margin:0 0 12px;font-size:14px;color:var(--wl-muted,#888)">Set max edits per analyst per calendar day. Limits are evaluated at UTC boundaries.</p>';

        html += '<div style="max-width:600px">';

        // Analyst limit field
        var analystVal = currentLimits.analyst_limit !== undefined ? currentLimits.analyst_limit : 10;
        html += '<div style="margin-bottom:16px">' +
            '<label style="display:block;margin-bottom:4px;font-weight:600;font-size:13px">Max edits per analyst per day</label>' +
            '<input type="number" class="wl-cp-limits-input wl-input" data-key="analyst_limit" value="' + analystVal + '" ' +
                'style="width:100%;padding:8px;border:1px solid var(--wl-border,#ddd);border-radius:4px;box-sizing:border-box" />' +
            '<p style="margin:4px 0 0;font-size:12px;color:var(--wl-muted,#888)">0 = disabled, -1 = unlimited</p>' +
            '</div>';

        // Admin limit (if superadmin)
        if (ctx.isSuperAdmin) {
            var adminVal = currentLimits.admin_limit !== undefined ? currentLimits.admin_limit : 100;
            html += '<div style="margin-bottom:16px">' +
                '<label style="display:block;margin-bottom:4px;font-weight:600;font-size:13px">Max admin actions per day</label>' +
                '<input type="number" class="wl-cp-limits-input wl-input" data-key="admin_limit" value="' + adminVal + '" ' +
                    'style="width:100%;padding:8px;border:1px solid var(--wl-border,#ddd);border-radius:4px;box-sizing:border-box" />' +
                '<p style="margin:4px 0 0;font-size:12px;color:var(--wl-muted,#888)">0 = disabled, -1 = unlimited</p>' +
                '</div>';
        }

        // Bulk threshold
        var bulkVal = currentLimits.bulk_threshold !== undefined ? currentLimits.bulk_threshold : 5;
        html += '<div style="margin-bottom:16px">' +
            '<label style="display:block;margin-bottom:4px;font-weight:600;font-size:13px">Bulk edit threshold (requires approval)</label>' +
            '<input type="number" class="wl-cp-limits-input wl-input" data-key="bulk_threshold" value="' + bulkVal + '" min="2" ' +
                'style="width:100%;padding:8px;border:1px solid var(--wl-border,#ddd);border-radius:4px;box-sizing:border-box" />' +
            '<p style="margin:4px 0 0;font-size:12px;color:var(--wl-muted,#888)">Minimum 2 rows. Actions affecting this many rows require approval.</p>' +
            '</div>';

        // Reset boundary (UTC hours)
        var boundaryVal = currentLimits.reset_boundary !== undefined ? currentLimits.reset_boundary : 0;
        html += '<div style="margin-bottom:16px">' +
            '<label style="display:block;margin-bottom:4px;font-weight:600;font-size:13px">Daily reset boundary (UTC hours)' +
                '<span class="wl-cp-reset-info-icon" style="display:inline-block;margin-left:6px;width:18px;height:18px;' +
                'border-radius:50%;background:var(--wl-border,#ccc);color:var(--wl-text,#333);font-size:12px;' +
                'font-weight:700;text-align:center;line-height:18px;cursor:pointer">i</span></label>' +
            '<input type="number" class="wl-cp-limits-input wl-input" data-key="reset_boundary" value="' + boundaryVal + '" min="0" max="23" ' +
                'style="width:100%;padding:8px;border:1px solid var(--wl-border,#ddd);border-radius:4px;box-sizing:border-box" />' +
            '<p style="margin:4px 0 0;font-size:12px;color:var(--wl-muted,#888)">0 = UTC midnight (00:00), 6 = 06:00 UTC, etc.</p>' +
            '</div>';

        // Buttons
        html += '<div style="margin-top:20px;display:flex;gap:8px;flex-wrap:wrap">' +
            '<span class="btn btn-primary wl-cp-limits-save-btn" style="cursor:pointer;padding:8px 12px;' +
                (hasChanges() ? '' : 'opacity:0.5;pointer-events:none;') +
                '">Save Limits</span>' +
            '<span class="btn wl-cp-limits-reset-btn" style="background:#e74c3c;color:#fff;cursor:pointer;padding:8px 12px;">Reset to Factory Defaults</span>' +
            '</div>';

        // Change history section
        html += '<div style="margin-top:20px;border-top:1px solid var(--wl-border-light,#f0f0f0);padding-top:12px">' +
            '<h4 style="margin:0 0 8px;cursor:pointer;user-select:none" class="wl-cp-limits-history-toggle">' +
                (showingHistory ? '▼' : '▶') + ' Change History (' + changeHistory.length + ')</h4>';

        if (showingHistory && changeHistory.length) {
            html += '<table class="wl-table" style="width:100%;border-collapse:collapse;font-size:12px">' +
                '<thead><tr>' +
                '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--wl-border,#ddd)">Timestamp</th>' +
                '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--wl-border,#ddd)">Admin</th>' +
                '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--wl-border,#ddd)">Field</th>' +
                '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--wl-border,#ddd)">Old Value</th>' +
                '<th style="text-align:left;padding:6px;border-bottom:1px solid var(--wl-border,#ddd)">New Value</th>' +
                '</tr></thead><tbody>';

            changeHistory.slice(0, 20).forEach(function(entry) {
                var changes = entry.changes || [];
                changes.forEach(function(change) {
                    var ts = entry.timestamp || "";
                    var admin = entry.admin || "";
                    var field = change.key || "";
                    var oldVal = String(change.old || "");
                    var newVal = String(change["new"] || "");

                    html += '<tr style="border-bottom:1px solid var(--wl-border-light,#f0f0f0)">' +
                        '<td style="padding:6px;color:var(--wl-muted,#888)">' + _.escape(ts) + '</td>' +
                        '<td style="padding:6px">' + _.escape(admin) + '</td>' +
                        '<td style="padding:6px">' + _.escape(field) + '</td>' +
                        '<td style="padding:6px;color:var(--wl-diff-rm,#c62828)">' + _.escape(oldVal) + '</td>' +
                        '<td style="padding:6px;color:var(--wl-diff-add,#2e7d32)">' + _.escape(newVal) + '</td>' +
                        '</tr>';
                });
            });

            html += '</tbody></table>';
        } else if (!changeHistory.length) {
            html += '<p style="color:var(--wl-muted,#888);font-size:12px">No changes recorded yet.</p>';
        }
        html += '</div>';

        html += '</div>';

        $limitsContent.html(html);

        // Bind info icon click
        $limitsContent.off("click.info").on("click.info", ".wl-cp-reset-info-icon", function() {
            var isDark = $("body").hasClass("wl-dark");
            var bg = isDark ? "#1a1c20" : "#fafafa";
            var bdr = isDark ? "#444" : "#ccc";
            var clr = isDark ? "#e0e0e0" : "#333";

            var $tooltip = $('<div class="wl-cp-limits-info-tooltip" style="' +
                'position:fixed;z-index:10000;background:' + bg + ';border:1px solid ' + bdr + ';' +
                'border-radius:6px;padding:10px;font-size:12px;color:' + clr + ';' +
                'width:200px;line-height:1.5;box-shadow:0 2px 8px rgba(0,0,0,0.15)' +
                '">The daily counter resets at this UTC hour. If you set it to 6, daily limits reset at 6:00 AM UTC every day.</div>');

            var rect = this.getBoundingClientRect();
            $tooltip.css({
                top: (rect.bottom + 8) + "px",
                left: (rect.left - 100) + "px"
            });

            $("body").append($tooltip);

            setTimeout(function() {
                $tooltip.fadeOut(300, function() { $tooltip.remove(); });
            }, 5000);
        });
    }

    function inputChange() {
        var $input = $(this);
        var key = $input.data("key");
        var val = parseInt($input.val(), 10);
        if (isNaN(val)) val = 0;
        currentLimits[key] = val;

        // Update Save button state
        var $saveBtn = $(".wl-cp-limits-save-btn");
        if (hasChanges()) {
            $saveBtn.css({ opacity: 1, "pointer-events": "auto" });
        } else {
            $saveBtn.css({ opacity: 0.5, "pointer-events": "none" });
        }
    }

    function hasChanges() {
        for (var key in currentLimits) {
            if (currentLimits[key] !== loadedLimits[key]) {
                return true;
            }
        }
        return false;
    }

    function deepCopy(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    function saveLimits() {
        // Validate fields
        var errors = {};

        for (var key in currentLimits) {
            var val = currentLimits[key];
            if (typeof val !== "number" || isNaN(val)) {
                errors[key] = "Must be a number";
                continue;
            }
            if (val !== 0 && val !== -1 && val < 0) {
                errors[key] = "Must be 0, -1, or positive";
                continue;
            }
            if (key === "bulk_threshold" && val !== 0 && val < 2) {
                errors[key] = "Must be 0 or >= 2";
                continue;
            }
            if (key === "reset_boundary" && (val < 0 || val > 23)) {
                errors[key] = "Must be 0-23";
                continue;
            }
        }

        if (Object.keys(errors).length > 0) {
            var errMsg = "Validation errors:\n";
            for (var k in errors) {
                errMsg += "  " + k + ": " + errors[k] + "\n";
            }
            ctx.showAlert("Validation Error", errMsg);
            return;
        }

        if (!hasChanges()) {
            ctx.showAlert("Info", "No changes detected");
            return;
        }

        var $btn = $(".wl-cp-limits-save-btn");
        $btn.text("Saving...").css("pointer-events", "none");

        REST.restPost({
            action: "set_limits",
            limits: currentLimits
        }).done(function(data) {
            if (data.error) {
                ctx.showAlert("Error", data.error);
                $btn.text("Save Limits").css("pointer-events", "auto");
            } else {
                ctx.showAlert("Success", "Limits saved successfully");
                load();
            }
        }).fail(function(xhr) {
            var err = "Failed to save limits";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
            ctx.showAlert("Error", err);
            $btn.text("Save Limits").css("pointer-events", "auto");
        });
    }

    function resetDefaults() {
        ctx.showConfirm("Reset to Factory Defaults",
            "Restore factory default limits? This cannot be undone.",
            { okLabel: "Reset" }).then(function(confirmed) {
            if (!confirmed) return;

            var $btn = $(".wl-cp-limits-reset-btn");
            $btn.text("Resetting...").css("pointer-events", "none");

            REST.restPost({
                action: "reset_factory_defaults"
            }).done(function(data) {
                if (data.error) {
                    ctx.showAlert("Error", data.error);
                    $btn.text("Reset to Factory Defaults").css("pointer-events", "auto");
                } else {
                    ctx.showAlert("Success", "Limits reset to factory defaults");
                    load();
                }
            }).fail(function(xhr) {
                var err = "Failed to reset limits";
                try { err = JSON.parse(xhr.responseText).error || err; } catch (e) {}
                ctx.showAlert("Error", err);
                $btn.text("Reset to Factory Defaults").css("pointer-events", "auto");
            });
        });
    }

    function toggleHistoryClick() {
        showingHistory = !showingHistory;
        render();
    }

    return {
        init: init,
        load: load
    };
});
