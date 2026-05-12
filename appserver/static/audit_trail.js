/**
 * Audit Trail — Refresh button + mutual-exclusion of Action dropdowns
 *
 * (1) Inserts a "Refresh" button before the "Hide Filters" link.
 *
 * (2) Enforces mutual exclusion between the General Action and Admin Action
 *     dropdowns: picking a non-default value in one resets the other to its
 *     "All ___ Actions" default. This must be done in JS (not via XML
 *     <change> cross-set) because:
 *       - SimpleXML's <set token="..."> from one input's <change> updates the
 *         underlying token but does NOT re-render the target dropdown widget,
 *         leaving a misleading stale label.
 *       - JS sync that re-fires change events causes infinite ping-pong
 *         between the two <change> handlers.
 *     Doing the reset via the dropdown component's settings.set("value", ...)
 *     updates BOTH display and token, and we use a guard flag + skip-if-same
 *     check to prevent the listener firing recursively.
 */
require([
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/simplexml/ready!"
], function ($, mvc) {
    "use strict";

    // ────────────────────────────────────────────────────────────────
    // Mutual exclusion + action_filter token management
    // ────────────────────────────────────────────────────────────────
    //
    // All state management happens in JS — NOT in XML <change> handlers.
    // The XML dropdowns have NO <change> elements. This eliminates a race
    // condition: when JS resets the opposite dropdown to "*", the old XML
    // <change> would fire and overwrite action_filter with "*",
    // clobbering the user's intended filter value.
    //
    // Flow:
    //   1. User picks a value in one dropdown
    //   2. JS change:value fires (resetting=false → user-initiated)
    //   3. JS sets action_filter = new value (via submitted tokens)
    //   4. JS resets the OTHER dropdown to "*" (sets resetting=true)
    //   5. The reset triggers change:value on the other dropdown
    //   6. JS sees resetting=true → skips (no action_filter write, no cross-reset)
    //
    var DEFAULT_VALUE = "*";
    var GENERAL_TOKEN = "general_action_display";
    var ADMIN_TOKEN = "admin_action_display";
    var resetting = false;

    function findAllDropdownsByToken(tokenName) {
        var matches = [];
        var instances = mvc.Components.getInstances();
        for (var key in instances) {
            if (!Object.prototype.hasOwnProperty.call(instances, key)) continue;
            var c = instances[key];
            if (!c || !c.settings || typeof c.settings.get !== "function") continue;
            try {
                if (c.settings.get("token") === tokenName) matches.push(c);
            } catch (e) { /* not a token-bound component */ }
        }
        return matches;
    }

    function setActionFilter(value) {
        // Write to BOTH token models so searches re-run and URL updates.
        var submitted = mvc.Components.get("submitted");
        var def = mvc.Components.get("default");
        if (submitted) submitted.set("action_filter", value);
        if (def) def.set("action_filter", value);
    }

    function resetOtherDropdown(otherTokenName) {
        var dds = findAllDropdownsByToken(otherTokenName);
        if (!dds.length) return;
        resetting = true;
        try {
            dds.forEach(function (dd) {
                try {
                    if (dd.settings.get("value") !== DEFAULT_VALUE) {
                        dd.settings.set("value", DEFAULT_VALUE);
                    }
                } catch (e) { /* widget not ready yet */ }
            });
        } finally {
            resetting = false;
        }
    }

    var wireAttempts = 0;
    function wireMutualExclusion() {
        wireAttempts++;
        var general = findAllDropdownsByToken(GENERAL_TOKEN);
        var admin = findAllDropdownsByToken(ADMIN_TOKEN);
        if (!general.length || !admin.length) {
            if (wireAttempts < 40) {
                setTimeout(wireMutualExclusion, 250);
            }
            return;
        }
        // Initialize action_filter to "*" on page load (since XML no longer
        // has a <change> handler to set it from the dropdown defaults).
        setActionFilter(DEFAULT_VALUE);

        general.forEach(function (c) {
            c.settings.on("change:value", function (m, v) {
                if (resetting) return;
                // User-initiated pick: set the filter and reset the other dropdown
                setActionFilter(v);
                if (v !== DEFAULT_VALUE) resetOtherDropdown(ADMIN_TOKEN);
            });
        });
        admin.forEach(function (c) {
            c.settings.on("change:value", function (m, v) {
                if (resetting) return;
                setActionFilter(v);
                if (v !== DEFAULT_VALUE) resetOtherDropdown(GENERAL_TOKEN);
            });
        });
    }
    wireMutualExclusion();

    // ────────────────────────────────────────────────────────────────
    // Detail panel show/hide for Data Changes drilldown.
    //
    // Splunk's `depends="$detail_ts$"` evaluates on form submission,
    // NOT reactively on programmatic token changes. So we manage
    // visibility directly via CSS + token state. The detail panel
    // is identified by its containing row having a child with
    // id="audit_detail_values".
    // ────────────────────────────────────────────────────────────────
    function findDetailRow() {
        var el = document.getElementById("audit_detail_values");
        while (el && !el.classList.contains("dashboard-row")) {
            el = el.parentElement;
        }
        return el;
    }

    function hideDetailPanel() {
        var row = findDetailRow();
        if (row) row.style.display = "none";
        var submitted = mvc.Components.get("submitted");
        var def = mvc.Components.get("default");
        if (submitted) {
            submitted.unset("detail_ts");
            submitted.unset("detail_action");
            submitted.unset("detail_analyst");
            submitted.unset("detail_csv");
        }
        if (def) {
            def.unset("detail_ts");
            def.unset("detail_action");
            def.unset("detail_analyst");
            def.unset("detail_csv");
        }
    }

    function showDetailPanel() {
        var row = findDetailRow();
        if (row) row.style.display = "";
    }

    // Close button — use both jQuery delegation AND direct binding with
    // polling, since Splunk HTML panels may render the element after the
    // initial DOM is ready.
    $(document).on("click", "#wl-close-details", function () {
        hideDetailPanel();
    });
    // Build 637: keyboard support for role="button" span. Splunk's
    // SimpleXML strips <button> elements inside <html> panels, so this
    // close control has to be a span. The role + tabindex + key handler
    // gives it minimal a11y parity (Enter/Space to activate).
    $(document).on("keydown", "#wl-close-details", function (e) {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            hideDetailPanel();
        }
    });
    // Also try direct binding with polling (in case jQuery delegation
    // doesn't reach Splunk HTML panel content for some reason)
    function bindCloseButton() {
        var btn = document.getElementById("wl-close-details");
        if (btn && !btn._wl_bound) {
            btn._wl_bound = true;
            btn.addEventListener("click", function () {
                hideDetailPanel();
            });
        }
        // Re-check periodically since the element appears/disappears with drilldown
        setTimeout(bindCloseButton, 2000);
    }
    bindCloseButton();

    // Show panel when drilldown tokens appear (submitted model change)
    function wireDetailVisibility() {
        var submitted = mvc.Components.get("submitted");
        if (!submitted) {
            setTimeout(wireDetailVisibility, 250);
            return;
        }
        // Initially hide the detail panel (no drilldown active)
        hideDetailPanel();
        submitted.on("change:detail_ts", function (m, v) {
            if (v) {
                showDetailPanel();
            } else {
                hideDetailPanel();
            }
        });
    }
    wireDetailVisibility();

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

        // a11y triage (build 658): darkened from #5cc05c -> #2e7d32
        // so the white-on-green contrast hits WCAG AA 4.5:1
        // (previous ratio was 2.05).
        var $btn = $(
            '<span class="wl-audit-refresh" style="display:inline-block;padding:6px 14px;' +
            'margin-right:10px;background:#2e7d32;color:#fff;border-radius:4px;' +
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
