/**
 * Notification Bell & Dropdown — shared across all Whitelist Manager pages.
 *
 * Injects a bell icon into the dashboard header, polls for unread
 * notifications every 30 seconds, and renders a dropdown panel.
 */
require([
    "jquery",
    "underscore",
    "splunkjs/mvc/utils"
], function ($, _, utils) {

    var POLL_INTERVAL = 30000;  // 30 seconds
    var bellInjected = false;

    // Detect admin via server-verified API call (same pattern as
    // whitelist_manager.js).  DOM-based checks are fragile — the nav
    // may not have rendered yet or could be manipulated.
    var isAdmin = false;
    restPost({ action: "get_approval_queue" }).done(function () {
        isAdmin = true;
    });

    // Global hook: other modules can register callbacks via
    // window.__wlNotifCallbacks.push(function(notifications) { ... })
    // Called on every poll with the full notification list.
    window.__wlNotifCallbacks = window.__wlNotifCallbacks || [];

    // ── REST helpers ──────────────────────────────────────────────
    var BASE_URL = Splunk.util.make_url(
        "/splunkd/__raw/services/custom/wl_manager");

    function restGet(params) {
        params.output_mode = "json";
        return $.ajax({
            url: BASE_URL,
            type: "GET",
            data: params,
            dataType: "json",
        });
    }

    function restPost(data) {
        return $.ajax({
            url: BASE_URL + "?output_mode=json",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(data),
            dataType: "json",
        });
    }

    // ── Time formatting ──────────────────────────────────────────
    function timeAgo(ts) {
        var diff = Math.floor(Date.now() / 1000) - ts;
        if (diff < 60) return "just now";
        if (diff < 3600) return Math.floor(diff / 60) + "m ago";
        if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
        return Math.floor(diff / 86400) + "d ago";
    }

    // ── Inject bell into page header ─────────────────────────────
    function injectBell() {
        if (bellInjected) return;

        // Place the bell in the app navigation bar row.
        // Try known Splunk nav bar selectors; fall back to fixed positioning.
        var $navBar = $("#placeholder-app-bar, .app-bar").first();
        if (!$navBar.length) {
            $navBar = $(".navbar.shared-appbar").first();
        }
        var useFixed = !$navBar.length;

        if (!useFixed) {
            if ($navBar.css("position") === "static") {
                $navBar.css("position", "relative");
            }
        }

        // fixed fallback: top:43px aligns with the app nav row in Splunk 9.x
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
        bellInjected = true;

        // Toggle dropdown on bell click
        $(document).on("click", "#wl-notif-bell", function (e) {
            e.stopPropagation();
            var $dd = $("#wl-notif-dropdown");
            if ($dd.is(":visible")) {
                $dd.hide();
            } else {
                fetchAndRender();
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
            restPost({ action: "mark_notifications_read", notification_ids: "all" })
            .done(function () {
                updateBadge(0);
                $("#wl-notif-dropdown-body .wl-notif-item").removeClass("unread");
            });
        });

        // Click notification: mark read + navigate to relevant CSV
        $(document).on("click", ".wl-notif-item", function () {
            var notifId = $(this).data("notif-id");
            if ($(this).hasClass("unread")) {
                $(this).removeClass("unread");
                restPost({ action: "mark_notifications_read", notification_ids: [notifId] });
                var current = parseInt($("#wl-notif-badge").text(), 10) || 0;
                updateBadge(Math.max(0, current - 1));
            }

            // Read notification metadata stored on the DOM element
            var notifType = $(this).data("notif-type") || "";   // new_request, approved, rejected, cancelled
            var actionType = $(this).data("action-type") || "";  // create_csv, create_rule, bulk_row_removal, etc.
            var csvFile = $(this).data("csv-file") || "";
            var detectionRule = $(this).data("detection-rule") || "";

            // Route based on WHO the user is (admin vs analyst), not notifType.
            // notifType "cancelled" can go to BOTH roles (analyst manual cancel
            // → admin notif; auto-cancel on rule removal → analyst notif).
            var cpUrl = Splunk.util.make_url(
                "/app/wl_manager/control_panel") + "?tab=queue";
            var wmBase = Splunk.util.make_url("/app/wl_manager/whitelist_manager");

            if (isAdmin) {
                // Admins: always go to Control Panel for actionable items
                // (new requests, cancellations, pending reviews)
                if (notifType === "new_request" || notifType === "cancelled") {
                    window.location.href = cpUrl;
                    return;
                }
                // Admin seeing approved/rejected (rare — from their own actions)
                // Navigate to the CSV if available
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

            // ── Analyst routing ──
            // create_csv / create_rule actions
            if (actionType === "create_csv" || actionType === "create_rule") {
                // Approved create_csv → CSV now exists, navigate to it
                if (notifType === "approved" && actionType === "create_csv" &&
                    detectionRule && csvFile) {
                    window.location.href = wmBase +
                        "?rule=" + encodeURIComponent(detectionRule) +
                        "&csv=" + encodeURIComponent(csvFile);
                    return;
                }
                // Rejected, cancelled, or create_rule approved (no CSV) → just close
                $("#wl-notif-dropdown").hide();
                return;
            }

            // Other analyst notifications → navigate to the CSV in Whitelist Manager
            if (!csvFile && !detectionRule) {
                $("#wl-notif-dropdown").hide();
                return;
            }
            var params = [];
            if (detectionRule) { params.push("rule=" + encodeURIComponent(detectionRule)); }
            if (csvFile && csvFile !== "__rule_operation__") {
                params.push("csv=" + encodeURIComponent(csvFile));
            }
            window.location.href = wmBase + (params.length ? "?" + params.join("&") : "");
        });

    }

    // ── Badge update ─────────────────────────────────────────────
    function updateBadge(count) {
        var $badge = $("#wl-notif-badge");
        if (count > 0) {
            $badge.text(count > 99 ? "99+" : count).show();
        } else {
            $badge.hide();
        }
    }

    // ── Fetch and render notifications ───────────────────────────
    function fetchAndRender() {
        restGet({ action: "get_notifications" })
        .done(function (data) {
            updateBadge(data.unread_count || 0);
            renderDropdown(data.notifications || []);
        });
    }

    function renderDropdown(notifications) {
        var $body = $("#wl-notif-dropdown-body");
        if (!notifications.length) {
            $body.html('<div class="wl-notif-empty">No notifications</div>');
            return;
        }

        var html = "";
        notifications.forEach(function (n) {
            var cls = "wl-notif-item";
            if (!n.read) cls += " unread";
            var icon = getIcon(n.type);
            html += '<div class="' + cls + '" data-notif-id="' + _.escape(n.id) + '"' +
                ' data-notif-type="' + _.escape(n.type || "") + '"' +
                ' data-action-type="' + _.escape(n.action_type || "") + '"' +
                ' data-csv-file="' + _.escape(n.csv_file || "") + '"' +
                ' data-detection-rule="' + _.escape(n.detection_rule || "") + '">' +
                '<span class="wl-notif-icon">' + icon + '</span>' +
                '<div class="wl-notif-content">' +
                    '<div class="wl-notif-message" title="' + _.escape(n.message) + '">' + _.escape(n.message) + '</div>' +
                    '<div class="wl-notif-time">' + timeAgo(n.timestamp) + '</div>' +
                '</div>' +
            '</div>';
        });
        $body.html(html);
    }

    function getIcon(type) {
        switch (type) {
            case "approved":  return '<span style="color:#27ae60">&#x2714;</span>';
            case "rejected":  return '<span style="color:#e74c3c">&#x2716;</span>';
            case "cancelled": return '<span style="color:#95a5a6">&#x25CB;</span>';
            default:          return '<span style="color:#3498db">&#x25CF;</span>';
        }
    }

    // ── Polling ──────────────────────────────────────────────────
    function pollCount() {
        restGet({ action: "get_notifications" })
        .done(function (data) {
            updateBadge(data.unread_count || 0);
            var notifs = data.notifications || [];
            window.__wlNotifCallbacks.forEach(function (cb) {
                try { cb(notifs); } catch (e) { /* ignore */ }
            });
        });
    }

    // ── Dark theme detection (runs on every page that loads notifications) ──
    function ensureDarkTheme() {
        if ($("body").hasClass("wl-dark")) return;
        var bg = window.getComputedStyle(document.body).backgroundColor;
        var m = bg.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (m) {
            var brightness = (parseInt(m[1]) + parseInt(m[2]) + parseInt(m[3])) / 3;
            if (brightness < 128) {
                $("body").addClass("wl-dark");
            }
        }
    }

    // ── Init ─────────────────────────────────────────────────────
    $(function () {
        // Wait a moment for Splunk dashboard to fully render
        setTimeout(function () {
            ensureDarkTheme();
            injectBell();
            pollCount();
            setInterval(pollCount, POLL_INTERVAL);
        }, 1500);
    });
});
