/**
 * wl_state.js — Centralized application state manager
 *
 * Single source of truth for all application state. Provides getter/setter with
 * fail-fast validation, event-driven mutations via jQuery custom events, and
 * batch atomic updates.
 *
 * Usage:
 *   State.register('currentRows', [], arrayValidator);
 *   State.set('currentRows', newRows);
 *   State.on('state:currentRows', callback);
 *   State.isDirty();  // Computed property
 */

define(["jquery"], function ($) {
    "use strict";

    /**
     * State manager — holds registered keys, provides get/set/batch/event API
     */
    var State = {
        // Internal registry: { key: { default: val, validator: fn } }
        _registry: {},

        // Current values: { key: val }
        _values: {},

        // Event listeners: { 'state:keyName': [callback1, callback2, ...] }
        _listeners: {},

        // Last isDirty() result (for computing "dirty" event)
        _lastDirtyState: false,

        /**
         * Register a state key with default value and optional validator
         *
         * @param {string} key - State key name
         * @param {*} defaultValue - Initial value
         * @param {function} validator - Optional validation function(value) throws TypeError
         */
        register: function (key, defaultValue, validator) {
            if (this._registry[key]) {
                throw new TypeError("State key already registered: " + key);
            }
            this._registry[key] = {
                default: defaultValue,
                validator: validator || null,
            };
            this._values[key] = defaultValue;
        },

        /**
         * Get value for a registered key. Throws TypeError if key unknown.
         *
         * @param {string} key - State key name
         * @returns {*} Current value
         */
        get: function (key) {
            if (!(key in this._registry)) {
                throw new TypeError("Unknown state key: " + key);
            }
            return this._values[key];
        },

        /**
         * Set value for a registered key. Validates before updating.
         * Throws TypeError if key unknown or validation fails.
         * Fires jQuery custom event 'state:keyName' on $(document) after successful update.
         *
         * @param {string} key - State key name
         * @param {*} newValue - New value
         */
        set: function (key, newValue) {
            if (!(key in this._registry)) {
                throw new TypeError("Unknown state key: " + key);
            }

            var entry = this._registry[key];
            var oldValue = this._values[key];

            // Run validator if present
            if (entry.validator) {
                try {
                    entry.validator(newValue);
                } catch (e) {
                    throw new TypeError("Validation failed for key '" + key + "': " + e.message);
                }
            }

            // Update value
            this._values[key] = newValue;

            // Fire event on $(document)
            var eventName = "state:" + key;
            $(document).trigger(eventName, [newValue, oldValue]);

            // Check isDirty() computed property on any state change
            if (key === "currentRows" || key === "originalRows") {
                this._updateDirtyState();
            }
        },

        /**
         * Reset all keys to their registered defaults.
         * Fires 'state:reset' event and individual key events for each reset key.
         */
        reset: function () {
            var self = this;
            var keysReset = [];

            Object.keys(this._registry).forEach(function (key) {
                var defaultValue = self._registry[key].default;
                self._values[key] = defaultValue;
                keysReset.push(key);

                // Fire key-specific event
                var eventName = "state:" + key;
                $(document).trigger(eventName, [defaultValue, null]);
            });

            // Fire reset event
            $(document).trigger("state:reset");

            // Reset dirty state
            this._lastDirtyState = false;
            $(document).trigger("state:dirty", [false]);
        },

        /**
         * Apply multiple updates atomically. All updates applied, then all events fired.
         *
         * @param {object} updates - { key: value, key2: value2, ... }
         */
        batch: function (updates) {
            var self = this;
            var events = [];

            // Validate and collect updates
            Object.keys(updates).forEach(function (key) {
                if (!(key in self._registry)) {
                    throw new TypeError("Unknown state key: " + key);
                }

                var entry = self._registry[key];
                var newValue = updates[key];

                // Run validator if present
                if (entry.validator) {
                    try {
                        entry.validator(newValue);
                    } catch (e) {
                        throw new TypeError("Validation failed for key '" + key + "': " + e.message);
                    }
                }

                var oldValue = self._values[key];
                events.push({
                    key: key,
                    newValue: newValue,
                    oldValue: oldValue,
                });
            });

            // Apply all updates
            events.forEach(function (evt) {
                self._values[evt.key] = evt.newValue;
            });

            // Fire all events
            events.forEach(function (evt) {
                var eventName = "state:" + evt.key;
                $(document).trigger(eventName, [evt.newValue, evt.oldValue]);
            });

            // Check isDirty() computed property
            this._updateDirtyState();
        },

        /**
         * Computed property: Returns true if currentRows differs from originalRows
         * (deep comparison). Fires 'state:dirty' event if status changed.
         *
         * @returns {boolean} True if there are unsaved changes
         */
        isDirty: function () {
            var currentRows = this._values.currentRows;
            var originalRows = this._values.originalRows;

            // Deep comparison: convert to JSON for simplicity
            var isDirty = JSON.stringify(currentRows) !== JSON.stringify(originalRows);
            return isDirty;
        },

        /**
         * Internal: Update dirty state and fire event if changed
         */
        _updateDirtyState: function () {
            var newDirtyState = this.isDirty();
            if (newDirtyState !== this._lastDirtyState) {
                this._lastDirtyState = newDirtyState;
                $(document).trigger("state:dirty", [newDirtyState]);
            }
        },

        /**
         * Register event listener for state changes.
         * Listener called with (value, oldValue) arguments.
         *
         * @param {string} event - Event name (e.g., 'state:currentRows')
         * @param {function} callback - Listener function
         */
        on: function (event, callback) {
            if (!this._listeners[event]) {
                this._listeners[event] = [];
            }
            this._listeners[event].push(callback);

            // Also register with $(document) for jQuery event delegation
            $(document).on(event, callback);
        },

        /**
         * Unregister event listener for state changes.
         *
         * @param {string} event - Event name (e.g., 'state:currentRows')
         * @param {function} callback - Listener function to remove
         */
        off: function (event, callback) {
            if (this._listeners[event]) {
                var idx = this._listeners[event].indexOf(callback);
                if (idx !== -1) {
                    this._listeners[event].splice(idx, 1);
                }
            }

            // Also unregister from $(document)
            $(document).off(event, callback);
        },

        /**
         * Initialize state manager. Register all shared state keys.
         * Called once at application startup.
         */
        init: function () {
            this.register("currentRows", [], this._validateArray);
            this.register("originalRows", [], this._validateArray);
            this.register("selectedRows", {}, this._validateObject);
            this.register("detectionRuleSelected", "", this._validateString);
            this.register("csvFileSelected", "", this._validateString);
            this.register("pageIndex", 0, this._validateNonNegativeInt);
            this.register("columnWidths", {}, this._validateObject);
            this.register("pendingApprovalCount", 0, this._validateNonNegativeInt);
            this.register("adminPendingCount", 0, this._validateNonNegativeInt);
            this.register("userPresence", {}, this._validateObject);
            this.register("notificationCount", 0, this._validateNonNegativeInt);
        },

        /**
         * Validators for common types
         */
        _validateArray: function (val) {
            if (!Array.isArray(val)) {
                throw new TypeError("Expected array, got " + typeof val);
            }
        },

        _validateObject: function (val) {
            if (typeof val !== "object" || val === null || Array.isArray(val)) {
                throw new TypeError("Expected object, got " + typeof val);
            }
        },

        _validateString: function (val) {
            if (typeof val !== "string") {
                throw new TypeError("Expected string, got " + typeof val);
            }
        },

        _validateNonNegativeInt: function (val) {
            if (typeof val !== "number" || val < 0 || !Number.isInteger(val)) {
                throw new TypeError("Expected non-negative integer, got " + val);
            }
        },
    };

    // Initialize state manager
    State.init();

    // Expose debug API if window.__wlDebug is set
    if (window.__wlDebug) {
        window.__wlState = State;
    }

    return State;
});
