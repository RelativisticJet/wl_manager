/**
 * Control Panel — AMD Entry Point
 *
 * Provides:
 * - User detection and access control gate
 * - Theme detection via UI module
 * - Shared modal helpers (alert, confirm, prompt)
 * - Tab routing with URL state management
 * - Browser visibility handler for polling lifecycle
 * - Context injection for Wave 2 feature modules
 */

/*global require */
require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "modules/wl_rest",
    "modules/wl_ui",
    "modules/wl_constants",
    "modules/wl_cp_queue",
    "modules/wl_cp_limits",
    "modules/wl_cp_trash",
    "modules/wl_cp_admin_limits",
    "modules/wl_cp_usage"
], function ($, _, mvc, REST, UI, Constants, QueueModule, LimitsModule, TrashModule, AdminLimitsModule, UsageModule) {
    "use strict";

    var cpCurrentUser = "", cpIsSuperAdmin = false, cpIsAdmin = false;

    // User Detection
    try {
        var tokenHandler = mvc.Components.get("default_tokenHandler");
        if (tokenHandler) {
            var info = tokenHandler.getPageInfo();
            if (info && info.content) {
                cpCurrentUser = info.content.username || "";
                var roles = info.content.roles || [];
                cpIsSuperAdmin = roles.indexOf("sc_admin") !== -1;
                cpIsAdmin = cpIsSuperAdmin || roles.indexOf("wl_editor") !== -1;
            }
        }
    } catch (e) { /* ignore */ }

    // Access Control Gate
    REST.restGet("get_approval_queue").done(function () {
        initCP();
    }).fail(function (xhr) {
        if (xhr.status === 403 || (xhr.responseJSON && xhr.responseJSON.error)) {
            $("#wl-cp-loading").hide();
            $("#wl-cp-access-denied").html(
                $("<div>").addClass("wl-msg wl-msg-error").css("margin", "20px 0")
                    .text("You do not have permission to access the Control Panel. Administrators only.")
            ).show();
        }
    });

    function initCP() {
        // Theme
        if (UI.detectTheme() === "dark") {
            $(document.body).addClass("wl-dark");
        }

        // Modal Helper Factory
        function createOverlay() {
            return $("<div>").css({
                position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
                "background-color": "rgba(0,0,0,0.5)", display: "flex",
                "align-items": "center", "justify-content": "center", "z-index": 10000
            }).addClass("wl-modal-overlay");
        }

        function createModal(isDark) {
            return $("<div>").addClass("wl-cp-modal").css({
                "background-color": isDark ? "#2c2e31" : "#fff",
                "color": isDark ? "#e0e0e0" : "#333",
                border: "1px solid " + (isDark ? "#444" : "#ddd"),
                "border-radius": "8px", "box-shadow": "0 4px 20px rgba(0,0,0,0.3)",
                padding: "20px", "max-width": "500px", "min-width": "300px"
            });
        }

        function showCpAlert(title, message) {
            return new Promise(function (resolve) {
                var isDark = $("body").hasClass("wl-dark");
                var $overlay = createOverlay();
                var $modal = createModal(isDark)
                    .append($("<h2>").css("margin-top", "0").text(title))
                    .append($("<p>").text(message))
                    .append($("<span>").addClass("btn btn-primary").css("cursor", "pointer")
                        .text("OK").on("click", function () {
                            $overlay.fadeOut(200, function () { $overlay.remove(); });
                            resolve();
                        }));
                $overlay.append($modal).appendTo("body");
            });
        }

        function showCpConfirm(title, message, opts) {
            opts = opts || {};
            return new Promise(function (resolve) {
                var isDark = $("body").hasClass("wl-dark");
                var $overlay = createOverlay();
                var $modal = createModal(isDark)
                    .append($("<h2>").css("margin-top", "0").text(title))
                    .append($("<p>").text(message))
                    .append(
                        $("<div>").css({ "margin-top": "15px", display: "flex", gap: "8px" })
                            .append($("<span>").addClass("btn").css("cursor", "pointer")
                                .text(opts.cancelLabel || "Cancel").on("click", function () {
                                    $overlay.fadeOut(200, function () { $overlay.remove(); });
                                    resolve(false);
                                }))
                            .append($("<span>").addClass("btn btn-primary").css("cursor", "pointer")
                                .text(opts.okLabel || "OK").on("click", function () {
                                    $overlay.fadeOut(200, function () { $overlay.remove(); });
                                    resolve(true);
                                }))
                    );
                $overlay.append($modal).appendTo("body");
            });
        }

        function showCpPrompt(title, message, placeholder) {
            return new Promise(function (resolve) {
                var isDark = $("body").hasClass("wl-dark");
                var $input = $("<input>").attr("type", "text").attr("placeholder", placeholder || "")
                    .css({
                        width: "100%", padding: "8px", margin: "10px 0 15px 0",
                        "background-color": isDark ? "#1a1c20" : "#f5f5f5",
                        "color": isDark ? "#e0e0e0" : "#333",
                        border: "1px solid " + (isDark ? "#444" : "#ddd"),
                        "border-radius": "4px", "box-sizing": "border-box"
                    });
                var $overlay = createOverlay();
                var $modal = createModal(isDark)
                    .append($("<h2>").css("margin-top", "0").text(title))
                    .append($("<p>").text(message))
                    .append($input)
                    .append(
                        $("<div>").css({ display: "flex", gap: "8px" })
                            .append($("<span>").addClass("btn").css("cursor", "pointer")
                                .text("Cancel").on("click", function () {
                                    $overlay.fadeOut(200, function () { $overlay.remove(); });
                                    resolve(null);
                                }))
                            .append($("<span>").addClass("btn btn-primary").css("cursor", "pointer")
                                .text("OK").on("click", function () {
                                    $overlay.fadeOut(200, function () { $overlay.remove(); });
                                    resolve($input.val());
                                }))
                    );
                $overlay.append($modal).appendTo("body");
                $input.focus();
            });
        }

        // Tab Routing
        var tabs = ["queue", "limits", "usage", "trash", "admin"];
        var activeTab = "queue";

        function showTab(tabName) {
            if (tabs.indexOf(tabName) === -1) tabName = "queue";
            $(".wl-cp-tab-content").hide();
            $(".wl-cp-tab-button").removeClass("wl-active");
            $("#wl-cp-tab-" + tabName).show();
            $("[data-tab='" + tabName + "']").addClass("wl-active");
            activeTab = tabName;
            history.replaceState(null, "", "?tab=" + tabName);

            // Stop polling on all modules with polling
            if (QueueModule && typeof QueueModule.stopPolling === "function") {
                QueueModule.stopPolling();
            }
            if (window.UsageModule && typeof window.UsageModule.stopPolling === "function") {
                window.UsageModule.stopPolling();
            }

            // Load and start polling for active tab
            if (tabName === "queue") {
                if (QueueModule && typeof QueueModule.load === "function") {
                    QueueModule.load().done(function() {
                        updateQueueBadge();
                        if (typeof QueueModule.startPolling === "function") {
                            QueueModule.startPolling();
                        }
                    });
                }
            } else if (tabName === "limits") {
                if (LimitsModule && typeof LimitsModule.load === "function") {
                    LimitsModule.load();
                }
            } else if (tabName === "usage") {
                if (window.UsageModule && typeof window.UsageModule.load === "function") {
                    window.UsageModule.load().then(function () {
                        if (typeof window.UsageModule.startPolling === "function") {
                            window.UsageModule.startPolling();
                        }
                    });
                }
            } else if (tabName === "trash") {
                if (window.TrashModule && typeof window.TrashModule.load === "function") {
                    window.TrashModule.load();
                }
            } else if (tabName === "admin") {
                if (window.AdminLimitsModule && typeof window.AdminLimitsModule.load === "function") {
                    window.AdminLimitsModule.load();
                }
            }
        }

        // Render tabs
        var tabHtml = "<div style='display:flex;gap:8px;margin-bottom:12px;border-bottom:1px solid var(--wl-border,#ddd);'>";
        tabs.forEach(function (t) {
            tabHtml += "<span class='wl-cp-tab-button' data-tab='" + t + "' " +
                "style='padding:8px 16px;cursor:pointer;border-bottom:2px solid transparent;'>" +
                t.charAt(0).toUpperCase() + t.slice(1) + "</span>";
        });
        tabHtml += "</div>";
        tabs.forEach(function (t) {
            tabHtml += "<div id='wl-cp-tab-" + t + "' class='wl-cp-tab-content' style='display:none;'></div>";
        });
        $("#wl-cp-tabs").html(tabHtml);

        $(document).off("click.cptabs").on("click.cptabs", ".wl-cp-tab-button", function () {
            showTab($(this).data("tab"));
        });

        var urlParams = new URLSearchParams(window.location.search);
        showTab(urlParams.get("tab") || "queue");

        // Browser Visibility
        $(document).off("visibilitychange.cpvis").on("visibilitychange.cpvis", function () {
            if (document.hidden) {
                // Stop polling when page hidden
                if (QueueModule && typeof QueueModule.stopPolling === "function") {
                    QueueModule.stopPolling();
                }
                if (window.UsageModule && typeof window.UsageModule.stopPolling === "function") {
                    window.UsageModule.stopPolling();
                }
            } else {
                // Resume polling when page visible
                if (activeTab === "queue" && QueueModule && typeof QueueModule.startPolling === "function") {
                    QueueModule.startPolling();
                }
                if (activeTab === "usage" && window.UsageModule && typeof window.UsageModule.startPolling === "function") {
                    window.UsageModule.startPolling();
                }
            }
        });

        // Notification System
        var lastPendingCount = 0;

        function showNewRequestsToast(count) {
            var message = count + " new pending request" + (count === 1 ? "" : "s");
            var $toast = $('<div class="wl-cp-toast">').html(
                '<span>' + message + '</span>' +
                '<button class="wl-cp-toast-dismiss" style="background:none;border:none;color:#ccc;font-size:18px;' +
                'cursor:pointer;padding:0;line-height:1;margin-left:16px">&times;</button>'
            ).css({
                position: "fixed", bottom: "20px", right: "20px",
                "background-color": "#1a1c20", color: "#ffffff",
                padding: "12px 16px", "border-radius": "4px",
                display: "flex", "justify-content": "space-between",
                "align-items": "center", gap: "16px",
                "z-index": 1001, "font-size": "14px", "line-height": "1.4",
                "box-shadow": "0 2px 8px rgba(0,0,0,0.15)"
            });

            $("body").append($toast);

            $toast.find(".wl-cp-toast-dismiss").on("click", function(e) {
                e.stopPropagation();
                $toast.fadeOut(300, function() { $toast.remove(); });
            });

            $toast.on("click", function() {
                showTab("queue");
                $toast.fadeOut(300, function() { $toast.remove(); });
            });

            setTimeout(function() {
                $toast.fadeOut(300, function() { $toast.remove(); });
            }, 5000);
        }

        function updateQueueBadge() {
            var count = QueueModule.getPendingCount();
            var $queueBtn = $("[data-tab='queue']");
            if (count > 0) {
                $queueBtn.text("Queue (" + count + ")");
            } else {
                $queueBtn.text("Queue");
            }
        }

        // Listen for new pending requests from Queue module
        $(document).off("wl:newPendingRequests").on("wl:newPendingRequests", function(e, data) {
            var newCount = data.newCount;
            if (newCount > lastPendingCount) {
                var diff = newCount - lastPendingCount;
                showNewRequestsToast(diff);
            }
            lastPendingCount = newCount;
            updateQueueBadge();
        });

        // Module Context
        window.__cpContext = {
            showAlert: showCpAlert,
            showConfirm: showCpConfirm,
            showPrompt: showCpPrompt,
            currentUser: cpCurrentUser,
            isSuperAdmin: cpIsSuperAdmin,
            isAdmin: cpIsAdmin
        };

        // Initialize all modules
        window.QueueModule = QueueModule;
        window.LimitsModule = LimitsModule;
        window.TrashModule = TrashModule;
        window.AdminLimitsModule = AdminLimitsModule;
        window.UsageModule = UsageModule;

        try {
            QueueModule.init(window.__cpContext);
            LimitsModule.init(window.__cpContext);
            TrashModule.init(window.__cpContext);
            AdminLimitsModule.init(window.__cpContext);
            UsageModule.init(window.__cpContext);
        } catch (e) {
            console.error("Module initialization failed:", e);
        }

        $("#wl-cp-loading").hide();
        $("#wl-cp-content").show();
    }
});
