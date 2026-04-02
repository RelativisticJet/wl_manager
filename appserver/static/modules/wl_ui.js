/**
 * wl_ui.js — UI feedback utilities and theme management
 *
 * Provides centralized message display, fatal error blocking, and dark/light
 * theme switching with localStorage persistence.
 *
 * Usage:
 *   UI.showMsg('error', 'Something went wrong');
 *   UI.showFatalError('Critical failure');
 *   UI.toggleTheme();
 *   UI.init();
 */

define(["jquery", "modules/wl_constants"], function ($, Constants) {
    "use strict";

    /**
     * UI utilities module
     */
    var UI = {
        // Message container element
        _messageContainer: null,

        // Fatal error overlay element
        _fatalOverlay: null,

        // Current theme ('light' or 'dark')
        _currentTheme: "light",

        // Storage key for theme preference
        _themeStorageKey: "wl_theme_preference",

        /**
         * Show a message (toast/notification) with auto-hide for non-error types.
         * Error messages persist until dismissed.
         *
         * @param {string} type - Message type: 'error', 'success', 'warning', 'info'
         * @param {string} message - Message text to display
         */
        showMsg: function (type, message) {
            var self = this;
            if (!this._messageContainer) {
                console.warn("Message container not initialized");
                return;
            }

            // Create message element
            var $msg = $("<div>")
                .addClass("wl-message")
                .addClass("wl-msg-" + type)
                .text(message)
                .append(
                    '<span class="wl-msg-close" style="cursor: pointer; margin-left: 1em;">\u00D7</span>'
                );

            // Close button handler
            $msg.on("click", ".wl-msg-close", function () {
                $msg.fadeOut(200, function () {
                    $(this).remove();
                });
            });

            // Add to container
            this._messageContainer.append($msg);

            // Auto-hide non-error messages after 4 seconds
            if (type !== "error") {
                setTimeout(function () {
                    $msg.fadeOut(400, function () {
                        $(this).remove();
                    });
                }, Constants.CONFIG.MESSAGE_AUTO_HIDE_MS);
            }
        },

        /**
         * Show a fatal error with blocking overlay.
         * Prevents further interaction until dismissed.
         *
         * @param {string} message - Error message to display
         */
        showFatalError: function (message) {
            var self = this;

            // Create overlay
            var $overlay = $("<div>")
                .addClass("wl-fatal-error-overlay")
                .css({
                    position: "fixed",
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    "background-color": "rgba(0, 0, 0, 0.7)",
                    display: "flex",
                    "align-items": "center",
                    "justify-content": "center",
                    "z-index": 9999,
                });

            // Create modal
            var $modal = $("<div>")
                .addClass("wl-fatal-error-modal")
                .css({
                    "background-color": "white",
                    padding: "2em",
                    "border-radius": "0.5em",
                    "box-shadow": "0 4px 20px rgba(0, 0, 0, 0.3)",
                    "max-width": "500px",
                    "text-align": "center",
                })
                .append(
                    $("<h2>").text("Fatal Error").css("color", "#d32f2f")
                )
                .append(
                    $("<p>").text(message)
                )
                .append(
                    $("<button>")
                        .text("Dismiss")
                        .css({
                            padding: "0.75em 1.5em",
                            "background-color": "#d32f2f",
                            color: "white",
                            border: "none",
                            "border-radius": "0.25em",
                            cursor: "pointer",
                            "font-size": "1em",
                        })
                        .on("click", function () {
                            $overlay.remove();
                        })
                );

            $overlay.append($modal);
            $("body").append($overlay);

            this._fatalOverlay = $overlay;
        },

        /**
         * Toggle between dark and light theme.
         * Persists preference to localStorage.
         * Applied via .wl-dark class on document.documentElement.
         */
        toggleTheme: function () {
            this._currentTheme = this._currentTheme === "light" ? "dark" : "light";
            this._applyTheme(this._currentTheme);
            localStorage.setItem(this._themeStorageKey, this._currentTheme);
        },

        /**
         * Apply theme by adding/removing .wl-dark class.
         *
         * @param {string} theme - Theme name ('light' or 'dark')
         */
        _applyTheme: function (theme) {
            var $root = $(document.documentElement);

            if (theme === "dark") {
                $root.addClass("wl-dark");
            } else {
                $root.removeClass("wl-dark");
            }
        },

        /**
         * Detect user's theme preference.
         * Priority: localStorage > system preference > light default
         *
         * @returns {string} Detected theme ('light' or 'dark')
         */
        _detectThemePreference: function () {
            // Check localStorage
            var stored = localStorage.getItem(this._themeStorageKey);
            if (stored === "dark" || stored === "light") {
                return stored;
            }

            // Check system preference
            if (
                window.matchMedia &&
                window.matchMedia("(prefers-color-scheme: dark)").matches
            ) {
                return "dark";
            }

            // Default to light
            return "light";
        },

        /**
         * Initialize UI module.
         * Sets up message container, detects theme, applies theme preference.
         * Called once at application startup.
         */
        init: function () {
            var self = this;

            // Create message container if not already present
            if ($("#wl-message-container").length === 0) {
                var $container = $("<div>")
                    .attr("id", "wl-message-container")
                    .css({
                        position: "fixed",
                        top: "1em",
                        right: "1em",
                        "z-index": 10000,
                        "font-family": "Arial, sans-serif",
                    });

                $("body").append($container);
                this._messageContainer = $container;
            } else {
                this._messageContainer = $("#wl-message-container");
            }

            // Detect and apply theme preference
            this._currentTheme = this._detectThemePreference();
            this._applyTheme(this._currentTheme);

            // Listen for 'wl:showMsg' events for programmatic message display
            $(document).on("wl:showMsg", function (e, msgType, msgText) {
                self.showMsg(msgType, msgText);
            });

            // Listen for theme toggle requests
            $(document).on("wl:toggleTheme", function () {
                self.toggleTheme();
            });
        },
    };

    return UI;
});
