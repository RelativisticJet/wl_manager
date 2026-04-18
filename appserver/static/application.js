// application.js — runs on EVERY view in the wl_manager app.
// Hides "Control Panel" nav link for non-admin users.
// application.css hides by default; this script reveals for admins.
require(["jquery", "splunkjs/mvc/utils"], function ($, utils) {

    function hideControlPanelNav() {
        // Multiple selectors for Splunk nav variations
        $("a").filter(function () {
            return $(this).text().trim() === "Control Panel";
        }).closest("li").addClass("wl-cp-hidden");

        $("a[href*='control_panel']").closest("li").addClass("wl-cp-hidden");
    }

    function showControlPanelNav() {
        $(".wl-cp-hidden").removeClass("wl-cp-hidden");
        // Also override the application.css rule
        if (!$("#wl-cp-admin-override").length) {
            $("head").append(
                '<style id="wl-cp-admin-override">' +
                '.nav a[href*="control_panel"], a[href*="control_panel"], ' +
                'li[data-view="control_panel"], .nav-item-control_panel ' +
                '{ display: initial !important; }' +
                '</style>'
            );
        }
    }

    // Run immediately + observe DOM for late-rendering nav
    hideControlPanelNav();
    var observer = new MutationObserver(function () { hideControlPanelNav(); });
    observer.observe(document.body, { childList: true, subtree: true });
    // Stop observing after 5s to avoid performance impact
    setTimeout(function () { observer.disconnect(); }, 5000);

    // Check if admin (using get_user_info — no 403 for non-admins)
    $.ajax({
        url: utils.make_url("/splunkd/__raw/services/custom/wl_manager") +
             "?action=get_user_info&output_mode=json",
        type: "GET",
        dataType: "json",
        headers: {
            "X-Splunk-Form-Key": (document.cookie.match(/splunkweb_csrf_token_8000=([^;]+)/) || [])[1] || "",
            "X-Requested-With": "XMLHttpRequest"
        }
    }).done(function (data) {
        if (data.is_admin) {
            observer.disconnect();
            showControlPanelNav();
        }
    });
});
