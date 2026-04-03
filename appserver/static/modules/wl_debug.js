/**
 * wl_debug.js — Frontend error interceptor
 *
 * Captures all AJAX failures, JS exceptions, and unhandled promise rejections.
 * Sends them to a backend debug endpoint that writes to /tmp/wl_debug.log.
 * Also logs to browser console with full details.
 *
 * Load order: must be loaded AFTER jQuery is available.
 * Remove from require() deps to disable.
 */
define([], function () {
    "use strict";

    var debugUrl = Splunk.util.make_url(
        "/splunkd/__raw/services/custom/wl_manager"
    );
    var MAX_LOG_ENTRIES = 200;
    var logBuffer = [];

    function _ts() {
        return new Date().toISOString().replace("T", " ").replace("Z", "");
    }

    function _send(entry) {
        entry.ts = _ts();
        entry.url_path = window.location.pathname;
        logBuffer.push(entry);
        if (logBuffer.length > MAX_LOG_ENTRIES) { logBuffer.shift(); }

        // Fire-and-forget POST to backend debug endpoint
        try {
            var $ = window.jQuery || window.$;
            if (!$) { return; }
            $.ajax({
                url: debugUrl + "?output_mode=json",
                type: "POST",
                contentType: "application/json",
                data: JSON.stringify({
                    action: "debug_log",
                    entry: entry
                }),
                dataType: "json",
                // Don't trigger ajaxError for debug calls (would loop)
                global: false
            });
        } catch (e) {
            // Fallback: just console
        }
    }

    function init() {
        var $ = window.jQuery || window.$;
        if (!$) {
            console.warn("[wl_debug] jQuery not found, debug interceptor disabled");
            return;
        }

        // ── 1. Global AJAX error handler ────────────────────────────
        $(document).ajaxError(function (event, xhr, settings, thrownError) {
            // Skip debug endpoint calls to avoid infinite loop
            if (settings.url && settings.url.indexOf("debug_log") !== -1) { return; }
            // Skip Splunk internal polling (noisy)
            if (settings.url && settings.url.indexOf("/services/messages") !== -1) { return; }

            var responseText = "";
            try { responseText = xhr.responseText || ""; } catch (e) { /* */ }
            // Truncate large responses
            if (responseText.length > 2000) {
                responseText = responseText.substring(0, 2000) + "...(truncated)";
            }

            var entry = {
                type: "ajax_error",
                method: settings.type || "GET",
                url: settings.url || "",
                status: xhr.status,
                statusText: xhr.statusText || "",
                error: thrownError || "",
                response: responseText,
                payload: null
            };

            // Capture POST payload (truncated)
            if (settings.data) {
                try {
                    var payload = typeof settings.data === "string"
                        ? settings.data.substring(0, 1000)
                        : JSON.stringify(settings.data).substring(0, 1000);
                    entry.payload = payload;
                } catch (e) { /* */ }
            }

            console.error("[wl_debug] AJAX Error:", entry);
            _send(entry);
        });

        // ── 2. Global JS error handler ──────────────────────────────
        var origOnError = window.onerror;
        window.onerror = function (msg, source, lineno, colno, error) {
            var entry = {
                type: "js_error",
                message: msg,
                source: (source || "").replace(/.*\/static\//, ""),
                line: lineno,
                col: colno,
                stack: error && error.stack
                    ? error.stack.substring(0, 1500)
                    : ""
            };
            console.error("[wl_debug] JS Error:", entry);
            _send(entry);

            if (origOnError) { return origOnError.apply(this, arguments); }
            return false;
        };

        // ── 3. Unhandled promise rejections ─────────────────────────
        window.addEventListener("unhandledrejection", function (event) {
            var reason = event.reason;
            var entry = {
                type: "promise_rejection",
                message: reason ? (reason.message || String(reason)) : "unknown",
                stack: reason && reason.stack
                    ? reason.stack.substring(0, 1500)
                    : ""
            };
            console.error("[wl_debug] Unhandled Promise:", entry);
            _send(entry);
        });

        console.info("[wl_debug] Debug interceptor active — errors logged to /tmp/wl_debug.log");
    }

    return {
        init: init,
        getLog: function () { return logBuffer; }
    };
});
