/**
 * wl_rest.js — Shared REST helpers for HTTP communication
 *
 * Eliminates 6x duplication of $.ajax patterns across whitelist_manager.js
 * and notifications.js. Provides unified URL building, error handling, and
 * response parsing.
 *
 * Usage:
 *   REST.restGet('get_csv', { rule: 'DR001' }).done(callback).fail(errorHandler);
 *   REST.restPost('save_csv', { rows: [...] }).done(callback).fail(errorHandler);
 *   REST.setErrorHandler(customErrorHandler);
 */

define(["jquery", "modules/wl_constants"], function ($, Constants) {
    "use strict";

    /**
     * REST helper module — provides unified HTTP interface
     */
    var REST = {
        // Default error handler — fires 'wl:restError' event
        _defaultErrorHandler: function (xhr, status, error, action) {
            var message = error;
            var statusCode = xhr.status;

            // Try to parse JSON error response
            try {
                if (xhr.responseJSON && xhr.responseJSON.message) {
                    message = xhr.responseJSON.message;
                } else if (xhr.responseText) {
                    var parsed = JSON.parse(xhr.responseText);
                    if (parsed.message) {
                        message = parsed.message;
                    }
                }
            } catch (e) {
                // Ignore parse errors; use default message
            }

            // Fire event for interested modules to handle
            $(document).trigger("wl:restError", {
                status: statusCode,
                message: message,
                action: action,
                xhr: xhr,
            });
        },

        // Custom error handler (can be set by caller)
        _customErrorHandler: null,

        /**
         * Register a custom error handler to be called instead of default.
         * If null, restores default handler.
         *
         * @param {function} handler - Error handler function(xhr, status, error, action)
         */
        setErrorHandler: function (handler) {
            this._customErrorHandler = handler;
        },

        /**
         * Build Splunk REST URL for custom endpoint.
         * Uses Splunk.util.make_url() if available, falls back to manual construction.
         *
         * @param {string} action - Action name (e.g., 'get_csv')
         * @param {object} params - Optional query parameters { key: value, ... }
         * @returns {string} Full URL to /custom/wl_manager?action=...&key=value...
         */
        _buildUrl: function (action, params) {
            params = params || {};
            var queryParts = ["action=" + encodeURIComponent(action)];

            Object.keys(params).forEach(function (key) {
                var val = params[key];
                if (val !== null && val !== undefined) {
                    queryParts.push(
                        encodeURIComponent(key) + "=" + encodeURIComponent(val)
                    );
                }
            });

            var url = "/custom/wl_manager?" + queryParts.join("&");

            // Use Splunk.util.make_url() if available
            if (typeof Splunk !== "undefined" && Splunk.util && Splunk.util.make_url) {
                try {
                    url = Splunk.util.make_url(url);
                } catch (e) {
                    // Fallback to manual URL
                }
            }

            return url;
        },

        /**
         * Perform GET request to custom endpoint.
         * Returns jQuery promise with .done(callback) and .fail(callback).
         * Default error handler fires 'wl:restError' event.
         * Modules can override per-call with .fail(customHandler).
         *
         * @param {string} action - Action name
         * @param {object} params - Optional query parameters
         * @returns {jQuery.Promise} Promise with done/fail callbacks
         */
        restGet: function (action, params) {
            var self = this;
            var url = this._buildUrl(action, params);

            return $.ajax({
                type: "GET",
                url: url,
                dataType: "json",
                timeout: 30000,
                error: function (xhr, status, error) {
                    var handler = self._customErrorHandler || self._defaultErrorHandler;
                    handler(xhr, status, error, action);
                },
            });
        },

        /**
         * Perform POST request to custom endpoint.
         * Sends payload as { action: string, data: object } JSON.
         * Returns jQuery promise with .done(callback) and .fail(callback).
         *
         * @param {string} action - Action name
         * @param {object} payload - Data to send (becomes 'data' field in POST body)
         * @returns {jQuery.Promise} Promise with done/fail callbacks
         */
        restPost: function (action, payload) {
            var self = this;
            var url = this._buildUrl(action);

            var postData = {
                action: action,
                data: payload || {},
            };

            return $.ajax({
                type: "POST",
                url: url,
                contentType: "application/json",
                dataType: "json",
                data: JSON.stringify(postData),
                timeout: 30000,
                error: function (xhr, status, error) {
                    var handler = self._customErrorHandler || self._defaultErrorHandler;
                    handler(xhr, status, error, action);
                },
            });
        },

        /**
         * Initialize REST helper. Called by entry point at startup.
         * Registers event listeners and sets up default error handling.
         */
        init: function () {
            var self = this;

            // Listen for 'wl:restError' events and log them (can be extended)
            $(document).on("wl:restError", function (e, errorData) {
                if (window.__wlDebug) {
                    console.log("REST Error [" + errorData.action + "]: " + errorData.message);
                }
            });
        },
    };

    // Initialize REST module
    REST.init();

    return REST;
});
