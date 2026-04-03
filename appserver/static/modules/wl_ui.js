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
    // Splunk loads separate CSS for dark/light — no body class by default.
    // Returns true if dark theme is active.
    function detectDarkTheme() {
        var bg = window.getComputedStyle(document.body).backgroundColor;
        var m = bg.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (m) {
            var brightness = (parseInt(m[1]) + parseInt(m[2]) + parseInt(m[3])) / 3;
            if (brightness < 128) {
                $("body").addClass("wl-dark");
                return true;
            }
        }
        return false;
    }

    // ── Message banner ──────────────────────────────────────────────
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
        clearMsg:            clearMsg,
        getContainer:        getContainer,
        formatDailyLimitMsg: formatDailyLimitMsg
    };
});
