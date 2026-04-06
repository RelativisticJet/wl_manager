/**
 * Date/Time Picker Module — wl_datepicker.js
 *
 * Handles the popup date/time picker for Expires column cells.
 * Values are stored in UTC, displayed in local time.
 *
 * Exports:
 *   init(opts) — initialize with state reference
 *   showDatePicker($input) — show picker below the given input element
 *   closeDatePicker() — hide picker
 *   formatLocalDateTime(d) — format Date to "YYYY-MM-DD HH:MM" local time
 */

define(["jquery"], function ($) {
    "use strict";

    var $datePicker = null;
    var $activeExpiresInput = null;
    var _state = null;

    function padTwo(n) {
        return n < 10 ? "0" + n : "" + n;
    }

    function formatDateForPicker(d) {
        return d.getFullYear() + "-" + padTwo(d.getMonth() + 1) + "-" + padTwo(d.getDate());
    }

    function formatLocalDateTime(d) {
        return d.getFullYear() + "-" + padTwo(d.getMonth() + 1) + "-" + padTwo(d.getDate()) +
               " " + padTwo(d.getHours()) + ":" + padTwo(d.getMinutes());
    }

    function formatUTCDateTime(d) {
        return d.getUTCFullYear() + "-" + padTwo(d.getUTCMonth() + 1) + "-" + padTwo(d.getUTCDate()) +
               " " + padTwo(d.getUTCHours()) + ":" + padTwo(d.getUTCMinutes());
    }

    function createDatePicker() {
        if ($datePicker) { return; }

        var html =
            '<div id="wl-date-picker" class="wl-date-picker">' +
                '<div class="wl-dp-header">Set Expiration</div>' +
                '<div class="wl-dp-presets">' +
                    '<button class="btn btn-small wl-dp-preset" data-days="7">7 Days</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="30">30 Days</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="182">6 Months</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="365">1 Year</button>' +
                '</div>' +
                '<div class="wl-dp-manual">' +
                    '<label class="wl-dp-label">Date</label>' +
                    '<input type="date" class="wl-dp-date" />' +
                    '<label class="wl-dp-label">Time (24h)</label>' +
                    '<input type="text" class="wl-dp-time" value="00:00" placeholder="HH:MM" maxlength="5" />' +
                '</div>' +
                '<div class="wl-dp-actions">' +
                    '<button class="btn btn-small btn-primary wl-dp-apply">Apply</button>' +
                    '<button class="btn btn-small wl-dp-clear">Clear (Permanent)</button>' +
                    '<button class="btn btn-small wl-dp-cancel">Cancel</button>' +
                '</div>' +
            '</div>';

        $datePicker = $(html);
        $("body").append($datePicker);

        // Preset buttons
        $datePicker.on("click", ".wl-dp-preset", function () {
            var days = parseInt($(this).data("days"), 10);
            var future = new Date();
            future.setDate(future.getDate() + days);
            $datePicker.find(".wl-dp-date").val(formatDateForPicker(future));
            $datePicker.find(".wl-dp-time").val(padTwo(future.getHours()) + ":" + padTwo(future.getMinutes()));
        });

        // Apply button — convert local picker values to UTC for storage
        $datePicker.on("click", ".wl-dp-apply", function () {
            var d = $datePicker.find(".wl-dp-date").val();
            var t = ($datePicker.find(".wl-dp-time").val() || "00:00").trim();
            if (!d) { return; }
            // Validate 24h time format (HH:MM, 00:00–23:59)
            if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) {
                $datePicker.find(".wl-dp-time").css("border-color", "#e74c3c");
                return;
            }
            $datePicker.find(".wl-dp-time").css("border-color", "");
            if ($activeExpiresInput) {
                // Parse local date/time from picker
                var tp = t.split(":");
                var localDate = new Date(
                    parseInt(d.substr(0, 4), 10), parseInt(d.substr(5, 2), 10) - 1,
                    parseInt(d.substr(8, 2), 10), parseInt(tp[0], 10), parseInt(tp[1], 10)
                );
                // Store UTC in data model
                var utcStr = formatUTCDateTime(localDate) + " UTC";
                var idx = $activeExpiresInput.closest("tr").data("idx");
                var header = $activeExpiresInput.data("header");
                if (_state.currentRows[idx]) { _state.currentRows[idx][header] = utcStr; }
                // Display local time in the input
                $activeExpiresInput.val(d + " " + t);
            }
            closeDatePicker();
        });

        // Clear button (permanent — empty Expires)
        $datePicker.on("click", ".wl-dp-clear", function () {
            if ($activeExpiresInput) {
                var idx = $activeExpiresInput.closest("tr").data("idx");
                var header = $activeExpiresInput.data("header");
                if (_state.currentRows[idx]) { _state.currentRows[idx][header] = ""; }
                $activeExpiresInput.val("");
            }
            closeDatePicker();
        });

        // Cancel button
        $datePicker.on("click", ".wl-dp-cancel", function () {
            closeDatePicker();
        });
    }

    function showDatePicker($input) {
        createDatePicker();
        $activeExpiresInput = $input;

        // Read stored value from data model (may be UTC with Z suffix)
        var idx = $input.closest("tr").data("idx");
        var header = $input.data("header");
        var stored = (_state.currentRows[idx] && _state.currentRows[idx][header]) || "";
        stored = stored.trim();

        if (stored && stored.endsWith("UTC")) {
            // UTC value — convert to local for picker display
            var utcDate = new Date(stored.replace(" UTC", "Z").replace(" ", "T"));
            if (!isNaN(utcDate.getTime())) {
                $datePicker.find(".wl-dp-date").val(formatDateForPicker(utcDate));
                $datePicker.find(".wl-dp-time").val(padTwo(utcDate.getHours()) + ":" + padTwo(utcDate.getMinutes()));
            }
        } else if (/^\d{4}-\d{2}-\d{2}/.test(stored)) {
            // Legacy local value — use as-is
            var parts = stored.split(" ");
            $datePicker.find(".wl-dp-date").val(parts[0] || "");
            $datePicker.find(".wl-dp-time").val(parts[1] || "00:00");
        } else {
            var now = new Date();
            $datePicker.find(".wl-dp-date").val(formatDateForPicker(now));
            $datePicker.find(".wl-dp-time").val(padTwo(now.getHours()) + ":" + padTwo(now.getMinutes()));
        }

        // Position below the input
        var offset = $input.offset();
        var inputHeight = $input.outerHeight();
        $datePicker.css({
            top: offset.top + inputHeight + 4,
            left: offset.left,
            display: "block"
        });
    }

    function closeDatePicker() {
        if ($datePicker) {
            $datePicker.css("display", "none");
        }
        $activeExpiresInput = null;
    }

    return {
        init: function (opts) {
            _state = opts.state;
        },
        showDatePicker: showDatePicker,
        closeDatePicker: closeDatePicker,
        formatLocalDateTime: formatLocalDateTime,
        formatDateForPicker: formatDateForPicker,
        formatUTCDateTime: formatUTCDateTime,
        padTwo: padTwo
    };
});
