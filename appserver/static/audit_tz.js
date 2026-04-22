/**
 * Audit Trail — Timezone Display Toggle (Phase A: Data Changes panel)
 *
 * Reformats the "timestamp" column of #audit_table_changes on the fly
 * based on the tz_display dropdown token. No server-side work — the
 * heavy lifting is done against a hidden epoch_ts column the SPL search
 * puts at the end of the result set.
 *
 * Why client-side:
 *   Splunk servers run in a single timezone (usually UTC or the host OS
 *   timezone). Analysts in different regions would otherwise see
 *   timestamps in the server's zone instead of their own. Doing this in
 *   the browser means every analyst sees familiar wall-clock times
 *   without any server config.
 *
 * Why polling (setInterval) instead of mvc/mvc search:done events:
 *   Splunk's table widget re-renders on search refresh, sort, pagination,
 *   drilldown navigation, etc. A single event hook would miss some of
 *   these re-renders. Polling every 500 ms with an idempotent
 *   "data-tz-formatted" attribute is simple, cheap (<1 ms per tick for
 *   a ~5-row table), and robust against every re-render path.
 *
 * Persistence:
 *   Choice is stored in localStorage under key "wl_audit_tz". Default
 *   is "browser" (first-time analyst sees local time). The XML dropdown
 *   default matches so the token+storage+UI stay in sync on first load.
 *
 * Label format:
 *   Browser mode:  "DD-MM-YYYY HH:MM:SS +OO:MM"  (offset from UTC)
 *   UTC mode:      "DD-MM-YYYY HH:MM:SS UTC"     (literal label)
 *
 *   Mixing offset-for-local with literal-for-UTC avoids the ambiguity
 *   that would arise in UTC+00:00 analysts (e.g. London in winter):
 *   their offset is +00:00, which would visually collide with UTC mode.
 *   The literal "UTC" label makes the toggle state unambiguous at a
 *   glance.
 */
require([
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/simplexml/ready!"
], function ($, mvc) {
    "use strict";

    var STORAGE_KEY = "wl_audit_tz";
    var TOKEN_NAME = "tz_display";
    var TABLE_SELECTOR = "#audit_table_changes table";
    var POLL_INTERVAL_MS = 500;
    var DEFAULT_MODE = "browser";
    var VALID_MODES = { "browser": true, "utc": true };

    // ────────────────────────────────────────────────────────────────
    // localStorage helpers (defensive — some browsers/modes disable it)
    // ────────────────────────────────────────────────────────────────

    function readStoredMode() {
        try {
            var v = window.localStorage.getItem(STORAGE_KEY);
            if (v && VALID_MODES[v]) {
                return v;
            }
        } catch (e) {
            // localStorage disabled (private mode, strict CSP) — fall through
        }
        return DEFAULT_MODE;
    }

    function writeStoredMode(mode) {
        if (!VALID_MODES[mode]) {
            return;
        }
        try {
            window.localStorage.setItem(STORAGE_KEY, mode);
        } catch (e) {
            // localStorage disabled — silent failure is fine, the token
            // still drives the current page's display for this session
        }
    }

    // ────────────────────────────────────────────────────────────────
    // CSS — hide the last column (epoch_ts) of the Data Changes table
    // without touching other tables on the page.
    //
    // Splunk renders both <thead> and <tbody>, so hide :last-child on
    // both. Using visibility:collapse + width:0 instead of display:none
    // would leave a phantom column border; display:none is cleanest.
    // ────────────────────────────────────────────────────────────────

    function injectStyles() {
        var css = [
            TABLE_SELECTOR + " thead th:last-child,",
            TABLE_SELECTOR + " tbody td:last-child {",
            "  display: none !important;",
            "}"
        ].join("\n");
        $("<style>").attr("id", "wl-audit-tz-style").text(css).appendTo("head");
    }

    // ────────────────────────────────────────────────────────────────
    // Formatting
    // ────────────────────────────────────────────────────────────────

    function pad2(n) {
        return (n < 10 ? "0" : "") + n;
    }

    // Returns "+HH:MM" / "-HH:MM" for the given Date's local offset
    // relative to UTC. Note Date.getTimezoneOffset() returns minutes
    // WEST of UTC (inverted sign) — e.g., UTC+2 returns -120.
    function formatLocalOffset(date) {
        var offsetMin = date.getTimezoneOffset();
        var sign = offsetMin <= 0 ? "+" : "-";
        var abs = Math.abs(offsetMin);
        var hh = pad2(Math.floor(abs / 60));
        var mm = pad2(abs % 60);
        return sign + hh + ":" + mm;
    }

    function formatBrowserLocal(epochSec) {
        var d = new Date(epochSec * 1000);
        return pad2(d.getDate()) + "-" +
               pad2(d.getMonth() + 1) + "-" +
               d.getFullYear() + " " +
               pad2(d.getHours()) + ":" +
               pad2(d.getMinutes()) + ":" +
               pad2(d.getSeconds()) + " " +
               formatLocalOffset(d);
    }

    function formatUTC(epochSec) {
        var d = new Date(epochSec * 1000);
        return pad2(d.getUTCDate()) + "-" +
               pad2(d.getUTCMonth() + 1) + "-" +
               d.getUTCFullYear() + " " +
               pad2(d.getUTCHours()) + ":" +
               pad2(d.getUTCMinutes()) + ":" +
               pad2(d.getUTCSeconds()) + " UTC";
    }

    function formatForMode(epochSec, mode) {
        if (mode === "utc") {
            return formatUTC(epochSec);
        }
        return formatBrowserLocal(epochSec);
    }

    // ────────────────────────────────────────────────────────────────
    // Parse the hidden epoch_ts cell. Returns a finite epoch-seconds
    // number on success, or null if the value doesn't look like one —
    // in which case the caller should leave the row untouched.
    // ────────────────────────────────────────────────────────────────

    function parseEpoch(text) {
        if (text === null || text === undefined) {
            return null;
        }
        var trimmed = String(text).trim();
        if (!trimmed) {
            return null;
        }
        // Guard against strings that happen to contain letters/spaces
        // (e.g., pre-formatted timestamps that slipped through).
        if (!/^-?\d+(\.\d+)?$/.test(trimmed)) {
            return null;
        }
        var n = parseFloat(trimmed);
        if (!isFinite(n)) {
            return null;
        }
        return n;
    }

    // ────────────────────────────────────────────────────────────────
    // Main paint loop. For every row whose first cell isn't yet tagged
    // with data-tz-formatted="<mode>", read epoch_ts from the last cell
    // and rewrite the first cell. The attribute makes the operation
    // idempotent + cheap: re-running on every tick is a no-op until
    // Splunk re-renders the table.
    // ────────────────────────────────────────────────────────────────

    function repaintTable(mode) {
        var $rows = $(TABLE_SELECTOR + " tbody tr");
        if (!$rows.length) {
            return;
        }
        $rows.each(function () {
            var $row = $(this);
            var $cells = $row.children("td");
            if ($cells.length < 2) {
                return;
            }
            var $first = $cells.eq(0);
            if ($first.attr("data-tz-formatted") === mode) {
                return; // already up to date
            }
            var $last = $cells.eq($cells.length - 1);
            var epoch = parseEpoch($last.text());
            if (epoch === null) {
                // Source wasn't epoch — leave the cell as Splunk rendered
                // it (already human-readable) and mark so we don't retry.
                $first.attr("data-tz-formatted", mode);
                return;
            }
            $first.text(formatForMode(epoch, mode));
            $first.attr("data-tz-formatted", mode);
        });
    }

    // ────────────────────────────────────────────────────────────────
    // Find the dropdown widget bound to `tz_display` by scanning the
    // mvc component registry. Same pattern as audit_trail.js uses for
    // the action-filter dropdowns — and for the same reason: writing
    // to `submitted.set("tz_display", ...)` updates the token BUT NOT
    // the widget's visible label. Only `dropdown.settings.set("value", ...)`
    // updates BOTH the internal value and fires the re-render that
    // changes the displayed option text ("Browser Local" ↔ "UTC").
    // ────────────────────────────────────────────────────────────────

    function findDropdownsByToken(tokenName) {
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

    // ────────────────────────────────────────────────────────────────
    // Wiring
    // ────────────────────────────────────────────────────────────────

    var currentMode = readStoredMode();
    var syncingFromStorage = false;

    // 1) Inject CSS before the table paints to avoid a flash of the
    //    epoch_ts column on first load.
    injectStyles();

    // 2) Start polling immediately. Runs independent of dropdown
    //    wiring so the table gets repainted even if the dropdown
    //    never materializes (e.g., browser extension removes it).
    setInterval(function () {
        repaintTable(currentMode);
    }, POLL_INTERVAL_MS);
    repaintTable(currentMode); // eager paint for the initial render

    // 3) Wire the dropdown widget. Retry until it shows up — the
    //    dashboard's ready event fires before all child views finish
    //    their first render, so the widget may not be in the mvc
    //    registry on our first look. Cap attempts so a missing widget
    //    doesn't spin forever.
    var wireAttempts = 0;
    function wireDropdown() {
        wireAttempts++;
        var dds = findDropdownsByToken(TOKEN_NAME);
        if (!dds.length) {
            if (wireAttempts < 40) {
                setTimeout(wireDropdown, 250);
            }
            return;
        }
        dds.forEach(function (dd) {
            // Restore saved choice from localStorage. Use the dropdown's
            // own settings — NOT submitted.set() alone — so the visible
            // label matches the underlying value. Splunk 9.3 renders
            // this dropdown as a React component; setting `value` on
            // the widget's settings is what drives the React re-render
            // of the selected-option button label. Setting only the
            // `submitted` token bypasses that render and leaves the
            // label stale ("Browser Local" while cells show UTC).
            //
            // syncingFromStorage guards the change:value handler so
            // our storage-driven seed doesn't fire a redundant
            // writeStoredMode() (and doesn't echo back to the token
            // side in a loop).
            try {
                var widgetValue = dd.settings.get("value");
                if (currentMode !== widgetValue && VALID_MODES[currentMode]) {
                    syncingFromStorage = true;
                    try {
                        dd.settings.set("value", currentMode);
                        // Also mirror into the token models so any
                        // future SPL/UI code that references
                        // `$tz_display$` stays in sync. No current
                        // panel depends on this token for its search,
                        // so this is defense-in-depth, not load-bearing.
                        var submittedTokens = mvc.Components.get("submitted");
                        var defaultTokens = mvc.Components.get("default");
                        if (submittedTokens) submittedTokens.set(TOKEN_NAME, currentMode);
                        if (defaultTokens) defaultTokens.set(TOKEN_NAME, currentMode);
                    } finally {
                        syncingFromStorage = false;
                    }
                }
            } catch (e) { /* widget not fully initialized */ }

            // Listen for user-initiated changes. Signature is
            // (model, newValue) — Backbone's change:<attr> event.
            dd.settings.on("change:value", function (model, newValue) {
                if (syncingFromStorage) return;
                if (!newValue || !VALID_MODES[newValue]) return;
                currentMode = newValue;
                writeStoredMode(newValue);
                // Also push to the token models so $tz_display$ stays
                // accurate for any future dependent search/UI.
                var submittedTokens = mvc.Components.get("submitted");
                var defaultTokens = mvc.Components.get("default");
                if (submittedTokens) submittedTokens.set(TOKEN_NAME, newValue);
                if (defaultTokens) defaultTokens.set(TOKEN_NAME, newValue);
                // Invalidate all rows so the next tick repaints them.
                $(TABLE_SELECTOR + " tbody td:first-child")
                    .removeAttr("data-tz-formatted");
                repaintTable(currentMode);
            });
        });
    }
    wireDropdown();
});
