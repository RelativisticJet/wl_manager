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
    "modules/wl_constants"
], function ($, _, mvc, REST, UI, Constants) {
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

            // Stop polling on all modules
            if (window.QueueModule && typeof window.QueueModule.stopPolling === "function") {
                window.QueueModule.stopPolling();
            }
            if (window.UsageModule && typeof window.UsageModule.stopPolling === "function") {
                window.UsageModule.stopPolling();
            }

            // Load and start polling for active tab
            var mod = tabName === "queue" ? window.QueueModule : (tabName === "usage" ? window.UsageModule : null);
            if (mod && typeof mod.load === "function") {
                mod.load().then(function () {
                    if (typeof mod.startPolling === "function") mod.startPolling();
                });
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
                if (window.QueueModule && typeof window.QueueModule.stopPolling === "function") {
                    window.QueueModule.stopPolling();
                }
                if (window.UsageModule && typeof window.UsageModule.stopPolling === "function") {
                    window.UsageModule.stopPolling();
                }
            } else {
                var mod = activeTab === "queue" ? window.QueueModule : (activeTab === "usage" ? window.UsageModule : null);
                if (mod && typeof mod.startPolling === "function") {
                    mod.startPolling();
                }
            }
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

        $("#wl-cp-loading").hide();
        $("#wl-cp-content").show();
    }
});
