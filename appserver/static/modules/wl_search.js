/**
 * wl_search.js - Search/Filter Module
 *
 * Provides search/filter functionality for CSV table rows.
 * Listens to state:currentRows changes to update available columns.
 * Matches search terms case-insensitively across all visible columns.
 *
 * Public API: init(), search(query), clearSearch(), getSearchResults()
 *
 * Events:
 *   - Listens: state:currentRows — when current rows change, update available columns
 *   - Fires: wl:searchUpdated — {query, resultCount} after search completes
 */

define([
    'modules/wl_constants',
    'modules/wl_state',
    'modules/wl_ui'
], function(Constants, State, UI) {
    'use strict';

    var currentRows = [];
    var currentHeaders = [];
    var searchResults = [];
    var $searchInput = null;
    var $searchClear = null;
    var debounceTimer = null;
    var DEBOUNCE_MS = 300;

    /**
     * Initialize search module.
     * Bind to search input element and listen to state changes.
     */
    function init() {
        // Bind DOM elements
        $searchInput = $(Constants.SELECTORS.SEARCH_INPUT);
        $searchClear = $(Constants.SELECTORS.SEARCH_CLEAR);

        if (!$searchInput.length || !$searchClear.length) {
            console.warn('[wl_search] Search input or clear button not found in DOM');
            return;
        }

        // Listen to state changes for current rows and headers
        State.on('state:currentRows', function(data) {
            currentRows = (data && data.rows) ? data.rows : [];
            onCurrentRowsChanged();
        });

        State.on('state:currentHeaders', function(data) {
            currentHeaders = (data && data.headers) ? data.headers : [];
        });

        // Bind search input with debounce
        $searchInput.on('input', function() {
            var query = $(this).val().trim();
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function() {
                search(query);
            }, DEBOUNCE_MS);
        });

        // Bind clear button
        $searchClear.on('click', function() {
            clearSearch();
        });

        // Listen to CSV selection changes
        State.on('state:csvFileSelected', function() {
            clearSearch();
        });

        // Initialize with current state
        var rows = State.get('currentRows');
        var headers = State.get('currentHeaders');
        if (rows) {
            currentRows = rows;
        }
        if (headers) {
            currentHeaders = headers;
        }
    }

    /**
     * Search rows matching query term across visible columns.
     * Case-insensitive matching. Updates State with results.
     * Fires wl:searchUpdated event.
     *
     * @param {string} query - Search term
     */
    function search(query) {
        if (!query) {
            clearSearch();
            return;
        }

        query = query.toLowerCase();
        searchResults = [];

        // Get visible headers (exclude _ metadata columns)
        var visibleHeaders = currentHeaders.filter(function(h) {
            return h && h.charAt(0) !== '_';
        });

        // Filter rows matching query in any visible column
        searchResults = currentRows.filter(function(row, idx) {
            for (var j = 0; j < visibleHeaders.length; j++) {
                var header = visibleHeaders[j];
                var val = (row[header] || '').toString().toLowerCase();
                if (val.indexOf(query) !== -1) {
                    return true;
                }
            }
            return false;
        });

        // Update state and UI
        State.set('searchResults', searchResults);
        $searchInput.val(query);

        // Fire custom event
        $(document).trigger('wl:searchUpdated', {
            query: query,
            resultCount: searchResults.length,
            totalCount: currentRows.length
        });
    }

    /**
     * Clear search and reset to all rows.
     */
    function clearSearch() {
        searchResults = currentRows.slice();
        $searchInput.val('');
        State.set('searchResults', searchResults);

        $(document).trigger('wl:searchUpdated', {
            query: '',
            resultCount: searchResults.length,
            totalCount: currentRows.length
        });
    }

    /**
     * Get current search results.
     * Returns array of row objects matching current search query.
     *
     * @return {Array} Current search results (filtered rows)
     */
    function getSearchResults() {
        return searchResults.slice();
    }

    /**
     * Handler when current rows change in state.
     * Reset search results to match new row set.
     */
    function onCurrentRowsChanged() {
        var currentQuery = $searchInput ? $searchInput.val().trim() : '';
        if (currentQuery) {
            // Re-run search with updated rows
            search(currentQuery);
        } else {
            // No active search, reset results to all rows
            searchResults = currentRows.slice();
            State.set('searchResults', searchResults);
        }
    }

    // Public API
    return {
        init: init,
        search: search,
        clearSearch: clearSearch,
        getSearchResults: getSearchResults
    };
});
