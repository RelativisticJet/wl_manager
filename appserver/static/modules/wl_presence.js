/**
 * Whitelist Manager — Real-time Presence/Collaboration Module
 *
 * Manages user presence tracking:
 *   - Polls server every 15 seconds to track concurrent users on the same CSV
 *   - Detects idle timeout (30 min) and auto-kicks sessions
 *   - Handles max concurrent users limit
 *   - Renders "Also viewing: user1, user2" bar above the table
 *   - Detects CSV deletion (404 responses)
 */

define(["jquery", "underscore", "splunkjs/mvc",
        "app/wl_manager/modules/wl_rest"],
function ($, _, mvc, REST) {
    "use strict";

    var restGet = REST.restGet;

    var presenceTimer = null;
    var currentUser = "";
    var lastActivityTime = Date.now();
    var IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

    var _state = null;
    var _$table = null;
    var _actions = null;

    function getCurrentUser() {
        if (currentUser) { return; }
        try {
            // Splunk JS SDK provides the current user
            var currentUserModel = mvc.Components.getInstance("env");
            if (currentUserModel) {
                currentUser = currentUserModel.get("user") || "";
            }
        } catch (e) { /* ignore */ }

        // Fallback: extract from page
        if (!currentUser) {
            try {
                currentUser = $(".user-name").text().trim() || Splunk.util.getConfigValue("USERNAME") || "";
            } catch (e) { /* ignore */ }
        }
    }

    function startPresenceMonitoring() {
        stopPresenceMonitoring();
        if (!_state.selectedCsv) { return; }
        getCurrentUser();
        reportPresence();
        presenceTimer = setInterval(reportPresence, 15000);
    }

    function stopPresenceMonitoring() {
        if (presenceTimer) { clearInterval(presenceTimer); presenceTimer = null; }
    }

    function reportPresence() {
        if (!_state.selectedCsv || !currentUser) { return; }

        // Check if THIS user is idle — auto-kick locally
        var idleMs = Date.now() - lastActivityTime;
        if (idleMs >= IDLE_TIMEOUT_MS) {
            stopPresenceMonitoring();
            showPresenceFullModal(
                "You have been idle for 30 minutes and your session on this CSV has been released."
            );
            return;
        }

        restGet({
            action:        "report_presence",
            csv_file:      _state.selectedCsv,
            app:           _state.selectedApp || "",
            user:          currentUser,
            last_activity: Math.floor(lastActivityTime / 1000)
        })
        .done(function (data) {
            if (data.presence_full) {
                stopPresenceMonitoring();
                showPresenceFullModal(data.error || "Maximum number of simultaneous users reached for this CSV file.");
                return;
            }
            if (data.idle_kicked) {
                stopPresenceMonitoring();
                showPresenceFullModal(data.error || "You have been idle too long and your session was released.");
                return;
            }
            renderPresenceBar(data.active_users || []);
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(_state.selectedCsv);
                return;
            }
            try {
                var data = JSON.parse(xhr.responseText);
                if (data.presence_full) {
                    stopPresenceMonitoring();
                    showPresenceFullModal(data.error || "Maximum number of simultaneous users reached for this CSV file.");
                }
            } catch (e) { /* ignore */ }
        });
    }

    function showPresenceFullModal(message) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">CSV Busy</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0;color:#e74c3c">' + _.escape(message) + '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<button type="button" class="btn btn-primary" id="wl-presence-full-ok">OK</button>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        function dismiss() {
            $modal.remove();
            $(document).off("keydown.wlpresence");
            // Reset to initial state
            _actions.onDismiss();
        }
        $modal.on("click", "#wl-presence-full-ok", dismiss);
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { dismiss(); }
        });
        $(document).off("keydown.wlpresence").on("keydown.wlpresence", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) { dismiss(); }
        });
    }

    function handleCsvRemoved(csvName) {
        _actions.stopChangeMonitoring();
        stopPresenceMonitoring();
        $(".wl-modal-overlay").remove();
        var displayName = csvName || _state.selectedCsv || "This CSV";
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">CSV Removed</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0">' +
                        '<strong>' + _.escape(displayName) + '</strong> has been removed ' +
                        'by an administrator and is no longer available.' +
                    '</p>' +
                    '<p style="margin:8px 0 0;font-size:13px;color:var(--wl-muted-text,#999)">' +
                        'If this was unexpected, contact your admin. ' +
                        'Removed files can be restored from the Trash in the Control Panel.' +
                    '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<button type="button" class="btn btn-primary" id="wl-csv-removed-ok">OK</button>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        function dismiss() {
            $modal.remove();
            $(document).off("keydown.wlcsvremoved");
            _actions.onDismiss();
        }
        $modal.on("click", "#wl-csv-removed-ok", dismiss);
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { dismiss(); }
        });
        $(document).off("keydown.wlcsvremoved").on("keydown.wlcsvremoved", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) { dismiss(); }
        });
    }

    function renderPresenceBar(users) {
        var $bar = _$table.find("#wl-presence-bar");
        if (!$bar.length) {
            $bar = $('<div id="wl-presence-bar" class="wl-presence-bar"></div>');
            _$table.prepend($bar);
        }

        if (!users.length || (users.length === 1 && users[0] === currentUser)) {
            $bar.empty().removeClass("wl-presence-active");
            return;
        }

        var otherUsers = users.filter(function (u) { return u !== currentUser; });
        if (!otherUsers.length) {
            $bar.empty().removeClass("wl-presence-active");
            return;
        }

        var PRESENCE_SHOW_MAX = 5;
        var visible = otherUsers.slice(0, PRESENCE_SHOW_MAX);
        var hidden  = otherUsers.slice(PRESENCE_SHOW_MAX);

        var html = '<span style="margin-right:4px">Also viewing:</span>';
        visible.forEach(function (user) {
            html += '<span class="wl-presence-user">' +
                    '<span class="wl-presence-dot"></span>' +
                    _.escape(user) + '</span>';
        });
        if (hidden.length) {
            html += '<span class="wl-presence-toggle" ' +
                    'style="cursor:pointer;color:var(--wl-link,#5ba0d0);margin-left:4px;font-weight:600" ' +
                    'title="Click to show all">+' + hidden.length + ' more</span>';
            html += '<span class="wl-presence-hidden" style="display:none">';
            hidden.forEach(function (user) {
                html += '<span class="wl-presence-user">' +
                        '<span class="wl-presence-dot"></span>' +
                        _.escape(user) + '</span>';
            });
            html += '</span>';
        }
        $bar.html(html).addClass("wl-presence-active");
        $bar.find(".wl-presence-toggle").off("click").on("click", function () {
            var $hidden = $bar.find(".wl-presence-hidden");
            if ($hidden.is(":visible")) {
                $hidden.hide();
                $(this).text("+" + hidden.length + " more");
            } else {
                $hidden.show();
                $(this).text("show less");
            }
        });
    }

    return {
        init: function (opts) {
            _$table = opts.$table;
            _state = opts.state;
            _actions = opts.actions;
        },
        startPresenceMonitoring: startPresenceMonitoring,
        stopPresenceMonitoring: stopPresenceMonitoring,
        handleCsvRemoved: handleCsvRemoved,
        getCurrentUser: getCurrentUser,
        getUsername: function () { return currentUser; }, // getter for current username
        updateActivity: function () { lastActivityTime = Date.now(); }
    };
});
