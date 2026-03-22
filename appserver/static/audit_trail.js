/**
 * Audit Trail — Refresh button injection
 *
 * Inserts a "Refresh" button before the "Hide Filters" link.
 * Uses a polling loop instead of a fixed setTimeout to handle
 * slow-rendering systems where Splunk's fieldset takes longer to build.
 */
require([
    "jquery",
    "splunkjs/mvc/simplexml/ready!"
], function ($) {
    "use strict";

    var attempts = 0;
    var maxAttempts = 20; // 20 x 200ms = 4 seconds max wait

    function injectButton() {
        attempts++;

        // Find the "Hide Filters" / "Show Filters" link
        var $hideLink = $("a").filter(function () {
            var t = $(this).text().trim();
            return t === "Hide Filters" || t === "Show Filters";
        }).first();

        if (!$hideLink.length) {
            if (attempts < maxAttempts) {
                setTimeout(injectButton, 200);
            }
            return;
        }

        // Avoid duplicate injection on auto-refresh
        if ($hideLink.prev(".wl-audit-refresh").length) { return; }

        var $btn = $(
            '<span class="wl-audit-refresh" style="display:inline-block;padding:6px 14px;' +
            'margin-right:10px;background:#5cc05c;color:#fff;border-radius:4px;' +
            'font-size:13px;cursor:pointer;font-weight:600;user-select:none;' +
            'vertical-align:middle">&#x21bb; Refresh</span>'
        );

        $btn.on("click", function () {
            window.location.reload();
        });

        $hideLink.before($btn);
    }

    setTimeout(injectButton, 200);
});
