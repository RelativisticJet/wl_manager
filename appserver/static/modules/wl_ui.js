/**
 * wl_ui.js — UI helpers for Whitelist Manager
 *
 * Message display (banner alerts with auto-dismiss), dark theme detection,
 * daily-limit message formatting, and textarea character counters.
 * Depends on jQuery (Splunk builtin) and underscore for _.escape().
 */
define(["jquery", "underscore"], function ($, _) {
    "use strict";

    var $msgContainer = null;
    var msgTimer      = null;

    // ── Dark theme detection ────────────────────────────────────────
    // Build 637: dark-only theme. The previous brightness-based detection
    // was load-bearing for a half-implemented light mode that produced
    // visual mismatches. Light theme support was ripped out (CSS :root +
    // body.wl-dark blocks collapsed to single :root). This function now
    // unconditionally tags <body> with .wl-dark so the existing 19
    // .wl-dark X selectors in whitelist_manager.css continue to match.
    // Returns true so callers that gate panel-class application
    // (whitelist_manager.js:69-71) keep working unchanged.
    function detectDarkTheme() {
        $("body").addClass("wl-dark");
        return true;
    }

    // ── Message banner ──────────────────────────────────────────────
    //
    // CONTRACT (round 7 C3, 2026-04-29):
    //   `text` is rendered as HTML inside the alert body. Callers that
    //   include user-supplied content (rule names, CSV filenames,
    //   analyst usernames, error messages from the backend) MUST
    //   pre-escape those substrings with `_.escape(...)` before
    //   concatenating them into the message string. Failing to do so
    //   is a stored-XSS bug, not a styling one.
    //
    //   The HTML-input contract exists because most call sites need
    //   `<strong>`, `<br>`, or `&hellip;` markup in the message body
    //   (e.g., "Request ID: <strong>...</strong>"). A pure-text API
    //   that rejects all markup would force every caller to pre-render
    //   HTML through DOM building, which is heavier than the current
    //   per-substring `_.escape` discipline.
    //
    //   When the message is purely text (no markup needed), prefer
    //   `showTextMsg(text, type)` below — it uses `.text()` and is
    //   structurally immune to the escape-discipline footgun.
    function showMsg(text, type) {
        if (!$msgContainer) return;
        var cls = {
            error:   "wl-alert wl-alert-error",
            success: "wl-alert wl-alert-success",
            info:    "wl-alert wl-alert-info",
            warning: "wl-alert wl-alert-warning"
        }[type || "info"] || "wl-alert wl-alert-info";

        if (msgTimer) { clearTimeout(msgTimer); msgTimer = null; }

        $msgContainer.html(
            '<div class="' + cls + '">' +
            '<span class="wl-alert-close">&times;</span>' +
            text +
            "</div>"
        );
        $msgContainer.children().first().stop(true).css("opacity", 1);

        msgTimer = setTimeout(function () {
            $msgContainer.children().first().fadeOut(400, function () { $(this).remove(); });
            msgTimer = null;
        }, 10000);
    }

    // Plain-text variant of `showMsg`. Use this when the message body
    // is a single string with no markup — the alert chrome (CSS class,
    // close button) is built as DOM nodes and `text` is set via
    // jQuery's `.text()` so any HTML-shaped content from the caller
    // is rendered as literal characters. Round 7 C3 — gives new call
    // sites an XSS-safe path without breaking the existing HTML-aware
    // `showMsg` callers.
    function showTextMsg(text, type) {
        if (!$msgContainer) return;
        var cls = {
            error:   "wl-alert wl-alert-error",
            success: "wl-alert wl-alert-success",
            info:    "wl-alert wl-alert-info",
            warning: "wl-alert wl-alert-warning"
        }[type || "info"] || "wl-alert wl-alert-info";

        if (msgTimer) { clearTimeout(msgTimer); msgTimer = null; }

        var $alert = $('<div>').addClass(cls);
        $('<span class="wl-alert-close">&times;</span>').appendTo($alert);
        $('<span>').text(text == null ? "" : String(text)).appendTo($alert);

        $msgContainer.empty().append($alert);
        $alert.stop(true).css("opacity", 1);

        msgTimer = setTimeout(function () {
            $msgContainer.children().first().fadeOut(400, function () { $(this).remove(); });
            msgTimer = null;
        }, 10000);
    }

    function clearMsg() {
        if (msgTimer) { clearTimeout(msgTimer); msgTimer = null; }
        if ($msgContainer) { $msgContainer.empty(); }
    }

    function getContainer() {
        return $msgContainer;
    }

    // ── Daily limit message ─────────────────────────────────────────
    var LIMIT_LABELS = {
        "row_removal":      "Row removal",
        "row_addition":     "Row addition",
        "row_edit":         "Row editing",
        "bulk_row_removal": "Bulk row removal",
        "bulk_row_edit":    "Bulk row editing",
        "column_removal":   "Column removal",
        "revert":           "CSV revert"
    };

    function formatDailyLimitMsg(dl) {
        var raw = String(dl.limit_type || "");
        var label = _.escape(LIMIT_LABELS[raw] || raw.replace(/_/g, " "));
        if (dl.disabled || dl.maximum === 0) {
            return label + " has been disabled by your administrator. " +
                "This action is not permitted.";
        }
        var count = dl.action_count || "?";
        var over = dl.exceeded_by || (dl.current + count - dl.maximum);
        return "Daily limit exceeded for " + label.toLowerCase() + ". " +
            "This action affects " + count + " row(s), exceeding your daily limit by " +
            over + " (" + dl.current + "/" + dl.maximum + " used). " +
            "Contact your administrator.";
    }

    // ── Character counter ───────────────────────────────────────────
    function initCharCounter() {
        $(document).on("input", "textarea[maxlength]", function () {
            var $ta = $(this);
            var id = $ta.attr("id");
            if (!id) return;
            var $counter = $(".wl-char-counter[data-for='" + id + "']");
            if ($counter.length) {
                var max = parseInt($ta.attr("maxlength"), 10) || 500;
                var used = ($ta.val() || "").length;
                $counter.text(used + " / " + max);
            }
        });
    }

    // ── Initialization ──────────────────────────────────────────────
    function init($container) {
        $msgContainer = $container || null;

        // Bind close button (delegated on container)
        if ($msgContainer) {
            $msgContainer.on("click", ".wl-alert-close", function () {
                if (msgTimer) { clearTimeout(msgTimer); msgTimer = null; }
                $(this).parent().fadeOut(200, function () { $(this).remove(); });
            });
        }

        initCharCounter();
    }

    return {
        init:                init,
        detectDarkTheme:     detectDarkTheme,
        showMsg:             showMsg,
        showTextMsg:         showTextMsg,
        clearMsg:            clearMsg,
        getContainer:        getContainer,
        formatDailyLimitMsg: formatDailyLimitMsg
    };
});
