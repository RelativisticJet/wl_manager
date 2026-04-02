/**
 * notifications.js — Notification Bell & Dropdown
 *
 * AMD module that injects a notification bell into the dashboard header,
 * polls for unread notifications, and renders a dropdown panel.
 *
 * Refactored from standalone IIFE to use wl_rest.js shared REST helpers.
 * Fires 'wl:notificationsUpdated' event instead of window.__wlNotifCallbacks.
 */

define([
    "jquery",
    "underscore",
    "splunkjs/mvc/utils",
    "modules/wl_rest",
    "modules/wl_constants"
], function ($, _, utils, REST, Constants) {
    "use strict";

    /**
     * Notifications module — manages bell icon and dropdown
     */
    var Notifications = {
        // Configuration
        POLL_INTERVAL: 5000,  // Poll every 5 seconds (from Constants.CONFIG)

        // State
        bellInjected: false,
        isAdmin: false,
        adminCheckDone: false,
        pollTimer: null,

        /**
         * Initialize notifications module.
         * Detects admin status, injects bell, starts polling.
         */
        init: function () {
            var self = this;

            // Detect admin status via API call
            this._detectAdmin();

            // Inject bell and dropdown into page
            this._injectBell();

            // Start polling for notifications
            this.start();
        },

        /**
         * Start polling for notifications.
         */
        start: function () {
            if (this.pollTimer) {
                return; // Already polling
            }

            var self = this;
            this._poll();

            this.pollTimer = setInterval(function () {
                self._poll();
            }, this.POLL_INTERVAL);
        },

        /**
         * Stop polling for notifications.
         */
        stop: function () {
            if (this.pollTimer) {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
        },

        /**
         * Poll backend for notification count and list.
         * Updates badge and fires 'wl:notificationsUpdated' event.
         * Maintains legacy window.__wlNotifCallbacks for backward compatibility.
         */
        _poll: function () {
            var self = this;

            REST.restGet("get_notifications")
                .done(function (data) {
                    var unreadCount = data.unread_count || 0;
                    var notifications = data.notifications || [];

                    // Update badge display
                    self._updateBadge(unreadCount);

                    // Fire modern event for new subscribers
                    $(document).trigger("wl:notificationsUpdated", {
                        count: unreadCount,
                        timestamp: Math.floor(Date.now() / 1000),
                    });

                    // Legacy callback support for backward compatibility
                    if (window.__wlNotifCallbacks && Array.isArray(window.__wlNotifCallbacks)) {
                        window.__wlNotifCallbacks.forEach(function (cb) {
                            try {
                                cb(notifications);
                            } catch (e) {
                                // Ignore callback errors
                            }
                        });
                    }

                    // Update shared State if available
                    try {
                        if (require.cache && require.cache["modules/wl_state"]) {
                            var State = require("modules/wl_state");
                            State.set("notificationCount", unreadCount);
                        }
                    } catch (e) {
                        // State not available yet
                    }
                })
                .fail(function () {
                    // Silently fail; retry on next poll
                });
        },

        /**
         * Detect if current user is admin via API call.
         * Used to route notification clicks correctly.
         */
        _detectAdmin: function () {
            var self = this;

            REST.restGet("get_approval_queue")
                .done(function () {
                    self.isAdmin = true;
                    self.adminCheckDone = true;
                })
                .fail(function () {
                    self.adminCheckDone = true;
                });
        },

        /**
         * Inject notification bell into page header.
         */
        _injectBell: function () {
            if (this.bellInjected) {
                return;
            }

            var self = this;

            // Try to find app nav bar
            var $navBar = $("#placeholder-app-bar, .app-bar").first();
            if (!$navBar.length) {
                $navBar = $(".navbar.shared-appbar").first();
            }
            var useFixed = !$navBar.length;

            if (!useFixed && $navBar.css("position") === "static") {
                $navBar.css("position", "relative");
            }

            // Position: fixed for page header, absolute for nav bar
            var posStyle = useFixed
                ? "position:fixed;top:43px;right:90px;z-index:10000"
                : "position:absolute;top:50%;right:12px;transform:translateY(-50%);z-index:10000";

            var bellHtml =
                '<div class="wl-notif-container" style="' + posStyle + '">' +
                    '<div class="wl-notif-bell" id="wl-notif-bell" title="Notifications">' +
                        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" ' +
                            'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
                            'stroke-linejoin="round" style="color:var(--wl-text,#e0e0e0);cursor:pointer">' +
                            '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>' +
                            '<path d="M13.73 21a2 2 0 0 1-3.46 0"></path>' +
                        '</svg>' +
                        '<span class="wl-notif-badge" id="wl-notif-badge" style="display:none">0</span>' +
                    '</div>' +
                    '<div class="wl-notif-dropdown" id="wl-notif-dropdown" style="display:none">' +
                        '<div class="wl-notif-dropdown-header">' +
                            '<strong>Notifications</strong>' +
                            '<span class="wl-notif-mark-all" id="wl-notif-mark-all">Mark all read</span>' +
                        '</div>' +
                        '<div class="wl-notif-dropdown-body" id="wl-notif-dropdown-body">' +
                            '<div class="wl-notif-empty">No notifications</div>' +
                        '</div>' +
                    '</div>' +
                '</div>';

            if (useFixed) {
                $("body").append(bellHtml);
            } else {
                $navBar.append(bellHtml);
            }
            this.bellInjected = true;

            // Toggle dropdown on bell click
            $(document).on("click", "#wl-notif-bell", function (e) {
                e.stopPropagation();
                var $dd = $("#wl-notif-dropdown");
                if ($dd.is(":visible")) {
                    $dd.hide();
                } else {
                    self._fetchAndRender();
                    $dd.show();
                }
            });

            // Close dropdown on outside click
            $(document).on("click", function (e) {
                if (!$(e.target).closest(".wl-notif-container").length) {
                    $("#wl-notif-dropdown").hide();
                }
            });

            // Mark all read
            $(document).on("click", "#wl-notif-mark-all", function () {
                REST.restPost("mark_notifications_read", { notification_ids: "all" })
                    .done(function () {
                        self._updateBadge(0);
                        $("#wl-notif-dropdown-body .wl-notif-item").removeClass("unread");
                    });
            });

            // Notification item click: mark read and navigate
            $(document).on("click", ".wl-notif-item", function () {
                self._handleNotificationClick($(this));
            });
        },

        /**
         * Handle notification item click: mark read and navigate.
         */
        _handleNotificationClick: function ($item) {
            var self = this;
            var notifId = $item.data("notif-id");

            if ($item.hasClass("unread")) {
                $item.removeClass("unread");

                REST.restPost("mark_notifications_read", {
                    notification_ids: [notifId],
                });

                var current = parseInt($("#wl-notif-badge").text(), 10) || 0;
                this._updateBadge(Math.max(0, current - 1));
            }

            // Get notification metadata from DOM
            var notifType = $item.data("notif-type") || "";
            var actionType = $item.data("action-type") || "";
            var csvFile = $item.data("csv-file") || "";
            var detectionRule = $item.data("detection-rule") || "";

            // Route based on user role (admin vs analyst)
            var cpUrl = Splunk.util.make_url("/app/wl_manager/control_panel") + "?tab=queue";
            var wmBase = Splunk.util.make_url("/app/wl_manager/whitelist_manager");

            // Detect admin: prefer async check, fallback to nav link check
            var effectiveAdmin = this.isAdmin;
            if (!this.adminCheckDone) {
                effectiveAdmin = $('a[href*="control_panel"]').length > 0;
            }

            if (effectiveAdmin) {
                // Admin routing
                if (notifType === "new_request" || notifType === "cancelled") {
                    window.location.href = cpUrl;
                    return;
                }
                if (detectionRule) {
                    var adminParams = ["rule=" + encodeURIComponent(detectionRule)];
                    if (csvFile && csvFile !== "__rule_operation__") {
                        adminParams.push("csv=" + encodeURIComponent(csvFile));
                    }
                    window.location.href = wmBase + "?" + adminParams.join("&");
                    return;
                }
                window.location.href = cpUrl;
                return;
            }

            // Analyst routing
            if (actionType === "create_csv" || actionType === "create_rule") {
                if (notifType === "approved" && actionType === "create_csv" &&
                    detectionRule && csvFile) {
                    window.location.href = wmBase +
                        "?rule=" + encodeURIComponent(detectionRule) +
                        "&csv=" + encodeURIComponent(csvFile);
                    return;
                }
                $("#wl-notif-dropdown").hide();
                return;
            }

            // Navigate to CSV in Whitelist Manager if available
            if (!csvFile && !detectionRule) {
                $("#wl-notif-dropdown").hide();
                return;
            }
            var params = [];
            if (detectionRule) {
                params.push("rule=" + encodeURIComponent(detectionRule));
            }
            if (csvFile && csvFile !== "__rule_operation__") {
                params.push("csv=" + encodeURIComponent(csvFile));
            }
            window.location.href = wmBase + (params.length ? "?" + params.join("&") : "");
        },

        /**
         * Update badge display with unread count.
         */
        _updateBadge: function (count) {
            var $badge = $("#wl-notif-badge");
            if (count > 0) {
                $badge.text(count > 99 ? "99+" : count).show();
            } else {
                $badge.hide();
            }
        },

        /**
         * Fetch notifications and render dropdown.
         */
        _fetchAndRender: function () {
            var self = this;

            REST.restGet("get_notifications")
                .done(function (data) {
                    var unreadCount = data.unread_count || 0;
                    var notifications = data.notifications || [];

                    self._updateBadge(unreadCount);
                    self._renderDropdown(notifications);
                });
        },

        /**
         * Render notification list in dropdown.
         */
        _renderDropdown: function (notifications) {
            var $body = $("#wl-notif-dropdown-body");

            if (!notifications.length) {
                $body.html('<div class="wl-notif-empty">No notifications</div>');
                return;
            }

            var html = "";
            notifications.forEach(function (n) {
                var cls = "wl-notif-item";
                if (!n.read) {
                    cls += " unread";
                }
                var icon = this._getIcon(n.type);
                html += '<div class="' + cls + '" data-notif-id="' + _.escape(n.id) + '"' +
                    ' data-notif-type="' + _.escape(n.type || "") + '"' +
                    ' data-action-type="' + _.escape(n.action_type || "") + '"' +
                    ' data-csv-file="' + _.escape(n.csv_file || "") + '"' +
                    ' data-detection-rule="' + _.escape(n.detection_rule || "") + '">' +
                    '<span class="wl-notif-icon">' + icon + '</span>' +
                    '<div class="wl-notif-content">' +
                        '<div class="wl-notif-message" title="' + _.escape(n.message) + '">' +
                            _.escape(n.message) +
                        '</div>' +
                        '<div class="wl-notif-time">' + this._formatTimeAgo(n.timestamp) + '</div>' +
                    '</div>' +
                    '</div>';
            }, this);

            $body.html(html);
        },

        /**
         * Get icon HTML for notification type.
         */
        _getIcon: function (type) {
            switch (type) {
                case "approved":
                    return '<span style="color:#27ae60">&#x2714;</span>';
                case "rejected":
                    return '<span style="color:#e74c3c">&#x2716;</span>';
                case "cancelled":
                    return '<span style="color:#95a5a6">&#x25CB;</span>';
                default:
                    return '<span style="color:#3498db">&#x25CF;</span>';
            }
        },

        /**
         * Format timestamp as relative time (e.g., "5m ago").
         */
        _formatTimeAgo: function (ts) {
            var diff = Math.floor(Date.now() / 1000) - ts;
            if (diff < 60) return "just now";
            if (diff < 3600) return Math.floor(diff / 60) + "m ago";
            if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
            return Math.floor(diff / 86400) + "d ago";
        },
    };

    // Initialize on load
    Notifications.init();

    // Return public API
    return {
        init: function () { Notifications.init(); },
        start: function () { Notifications.start(); },
        stop: function () { Notifications.stop(); },
    };
});
