/**
 * wl_cp_modals — Reusable Modal Helper Factory
 *
 * Provides: createOverlay, createModal, showCpAlert, showCpConfirm, showCpPrompt
 * Used by: control_panel.js and all CP modules (queue, limits, trash, usage, admin_limits)
 *
 * All functions detect dark theme via $("body").hasClass("wl-dark")
 * and return Promises for asynchronous modal interactions.
 */

/*global define */
define(function () {
    "use strict";

    /**
     * Creates a fixed-position overlay div with dark semi-transparent background,
     * centered flex layout, and high z-index (10000) for modal layering.
     * @returns {jQuery} Overlay div element with class "wl-modal-overlay"
     */
    function createOverlay() {
        return $("<div>").css({
            position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
            "background-color": "rgba(0,0,0,0.5)", display: "flex",
            "align-items": "center", "justify-content": "center", "z-index": 10000
        }).addClass("wl-modal-overlay");
    }

    /**
     * Creates a modal container div with theme-aware colors.
     * @param {boolean} isDark - True for dark theme, false for light theme
     * @returns {jQuery} Modal div element with class "wl-cp-modal"
     */
    function createModal(isDark) {
        return $("<div>").addClass("wl-cp-modal").css({
            "background-color": isDark ? "#2c2e31" : "#fff",
            "color": isDark ? "#e0e0e0" : "#333",
            border: "1px solid " + (isDark ? "#444" : "#ddd"),
            "border-radius": "8px", "box-shadow": "0 4px 20px rgba(0,0,0,0.3)",
            padding: "20px", "max-width": "500px", "min-width": "300px"
        });
    }

    /**
     * Shows a modal alert with title, message, and OK button.
     * Resolves immediately when OK is clicked.
     * @param {string} title - Modal title (rendered as h2)
     * @param {string} message - Modal message body (rendered as p)
     * @returns {Promise<void>} Promise resolved on OK click
     */
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

    /**
     * Shows a modal confirmation dialog with title, message, Cancel and OK buttons.
     * Resolves false on Cancel, true on OK.
     * @param {string} title - Modal title (rendered as h2)
     * @param {string} message - Modal message body (rendered as p)
     * @param {Object} opts - Optional button labels: { cancelLabel, okLabel }
     * @returns {Promise<boolean>} Promise resolved with false (Cancel) or true (OK)
     */
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

    /**
     * Shows a modal prompt dialog with title, message, text input, Cancel and OK buttons.
     * Resolves null on Cancel, or input value (string) on OK.
     * Auto-focuses the input field for immediate typing.
     * @param {string} title - Modal title (rendered as h2)
     * @param {string} message - Modal message body (rendered as p)
     * @param {string} placeholder - Placeholder text for input field (or empty string)
     * @returns {Promise<string|null>} Promise resolved with null (Cancel) or input value (OK)
     */
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

    // Export all 5 modal factory functions
    return {
        createOverlay: createOverlay,
        createModal: createModal,
        showCpAlert: showCpAlert,
        showCpConfirm: showCpConfirm,
        showCpPrompt: showCpPrompt
    };
});
