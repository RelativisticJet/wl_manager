/**
 * wl_presence.js - User Presence Tracking Module
 *
 * Manages user presence tracking with heartbeat polling.
 * Polls backend for other users currently editing this CSV.
 * Sends heartbeat to announce current user presence.
 *
 * Public API: init(), start(), stop(), getPresence()
 *
 * State keys:
 *   - userPresence: {username: string, role: string, lastSeen: timestamp, ...}
 *
 * Events:
 *   - Listens: state:csvFileSelected — update presence on CSV switch
 *   - Fires: wl:presenceUpdated — {presence: {...}, timestamp: ...}
 */

define([
    'modules/wl_constants',
    'modules/wl_state',
    'modules/wl_rest'
], function(Constants, State, REST) {
    'use strict';

    var pollTimer = null;
    var heartbeatTimer = null;
    var currentPresence = {};
    var isStarted = false;
    var POLL_INTERVAL_MS = 30 * 1000; // 30 seconds
    var PRESENCE_TTL_MS = 60 * 1000; // 60 seconds (expire if not updated)

    /**
     * Initialize presence module.
     * Register required state keys.
     */
    function init() {
        State.register('userPresence', {});

        // Listen to CSV selection changes
        State.on('state:csvFileSelected', function() {
            updatePresenceForCurrentCsv();
        });

        // Initialize current presence from state
        var storedPresence = State.get('userPresence');
        if (storedPresence) {
            currentPresence = storedPresence;
        }
    }

    /**
     * Start presence polling and heartbeat.
     * Sends heartbeat immediately, then on POLL_INTERVAL_MS.
     * Polls other users' presence on POLL_INTERVAL_MS.
     */
    function start() {
        if (isStarted) {
            return; // Already running
        }

        isStarted = true;

        // Send initial heartbeat
        sendHeartbeat();

        // Poll other users' presence and send heartbeat
        pollTimer = setInterval(function() {
            pollPresenceStatus();
            sendHeartbeat();
        }, POLL_INTERVAL_MS);
    }

    /**
     * Stop presence polling and heartbeat.
     */
    function stop() {
        isStarted = false;

        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }

        if (heartbeatTimer) {
            clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
    }

    /**
     * Get current presence object from state.
     *
     * @return {Object} Current user presence {username, role, lastSeen, ...}
     */
    function getPresence() {
        return $.extend({}, currentPresence);
    }

    /**
     * Send heartbeat to backend to announce current user is editing this CSV.
     * Called on init and periodically during polling interval.
     */
    function sendHeartbeat() {
        var csvFile = State.get('csvFileSelected');
        if (!csvFile) {
            return; // No CSV selected
        }

        REST.restPost({
            action: 'get_presence_status',
            csv_file: csvFile,
            heartbeat: true
        }, function(response) {
            // Heartbeat sent successfully
            if (response && response.success) {
                // Update own presence info from response if provided
                if (response.current_user) {
                    updateOwnPresence(response.current_user);
                }
            }
        }, function(error) {
            // Gracefully handle heartbeat failure
            console.warn('[wl_presence] Heartbeat failed:', error);
        });
    }

    /**
     * Poll backend for other users' presence.
     */
    function pollPresenceStatus() {
        var csvFile = State.get('csvFileSelected');
        if (!csvFile) {
            return; // No CSV selected
        }

        REST.restGet({
            action: 'get_presence_status',
            csv_file: csvFile
        }, function(response) {
            if (response && response.success) {
                // Update presence info with other users
                updatePresenceFromResponse(response);
            }
        }, function(error) {
            // Gracefully handle polling failure
            console.warn('[wl_presence] Presence poll failed:', error);
        });
    }

    /**
     * Update presence from backend response.
     *
     * @param {Object} response - Backend presence response
     */
    function updatePresenceFromResponse(response) {
        var presence = {
            users: response.users || {},
            lastUpdated: new Date().getTime(),
            csvFile: response.csv_file
        };

        currentPresence = presence;
        State.set('userPresence', presence);

        $(document).trigger('wl:presenceUpdated', {
            presence: presence,
            timestamp: presence.lastUpdated
        });
    }

    /**
     * Update own presence info.
     *
     * @param {Object} userInfo - Current user info from backend
     */
    function updateOwnPresence(userInfo) {
        var presence = currentPresence || {};
        presence.currentUser = userInfo;
        presence.lastUpdated = new Date().getTime();

        currentPresence = presence;
        State.set('userPresence', presence);

        $(document).trigger('wl:presenceUpdated', {
            presence: presence,
            timestamp: presence.lastUpdated
        });
    }

    /**
     * Update presence when CSV is selected.
     */
    function updatePresenceForCurrentCsv() {
        var csvFile = State.get('csvFileSelected');
        if (csvFile) {
            // Reset presence on CSV switch and fetch new presence info
            pollPresenceStatus();
        }
    }

    // Public API
    return {
        init: init,
        start: start,
        stop: stop,
        getPresence: getPresence
    };
});
