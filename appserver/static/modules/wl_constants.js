/**
 * wl_constants.js — Centralized configuration, selectors, patterns, and magic numbers
 *
 * Extracted from whitelist_manager.js to eliminate duplication across frontend modules.
 * All hardcoded values, DOM selectors, regex patterns, role names, and API constants.
 */

define([], function () {
    "use strict";

    var Constants = {
        // ════════════════════════════════════════════════════════════════
        // DOM Selectors — CSS class names used throughout the app
        // ════════════════════════════════════════════════════════════════
        SELECTORS: {
            // Main containers
            csvTableContainer: "#csv-table-container",
            messageContainer: "#message-container",
            diffContainer: "#diff-container",
            dropdownsContainer: "#wl-dropdowns",
            ruleSelectContainer: "#rule-select",
            csvDisplayContainer: "#csv-display",

            // Rule selection
            ruleSearch: "#rule-search",
            ruleList: "#rule-list",
            ruleClear: ".wl-rule-clear-btn",

            // CSV selection
            csvSelect: "#csv-select",
            csvDropdown: "#csv-dropdown",
            csvList: "#csv-list",
            csvRemoveBtn: ".wl-csv-remove",

            // Table elements
            table: "table.wl-csv-table",
            tableHead: "table.wl-csv-table thead",
            tableBody: "table.wl-csv-table tbody",
            tableRow: "table.wl-csv-table tbody tr",
            tableCell: "table.wl-csv-table td",

            // Action buttons and controls
            addRowBtn: ".wl-add-row-btn",
            removeBtn: ".wl-remove-btn",
            removeSelectedBtn: ".wl-remove-selected-btn",
            revertBtn: ".wl-revert-btn",
            saveBtn: ".wl-save-btn",
            checkboxSelectAll: ".wl-select-all",
            checkboxRow: ".wl-row-checkbox",

            // Theme and UI
            darkModeToggle: ".wl-theme-toggle",
            dashboardPanel: ".dashboard-panel",
            bodyElement: "body",
            htmlElement: "html",

            // Search/filter
            searchInput: ".wl-search-input",
            searchClear: ".wl-search-clear-btn",
            csvSearchClear: ".wl-csv-clear-btn",

            // Modals and overlays
            modalOverlay: ".wl-modal-overlay",
            modal: ".wl-modal",
            modalClose: ".wl-modal-close",

            // Messages and notifications
            msgError: ".wl-msg-error",
            msgSuccess: ".wl-msg-success",
            msgWarning: ".wl-msg-warning",
            msgInfo: ".wl-msg-info",
        },

        // ════════════════════════════════════════════════════════════════
        // Configuration — Application behavior and limits
        // ════════════════════════════════════════════════════════════════
        CONFIG: {
            // Pagination
            ROWS_PER_PAGE: 10,
            PAGE_SIZE_OPTIONS: [10, 20, 50],

            // CSV limits
            MAX_ROWS: 5000,
            MAX_COLUMNS: 100,
            MAX_CELL_CHARS: 1000,

            // UI behavior
            MESSAGE_AUTO_HIDE_MS: 4000,  // Auto-dismiss non-error messages after 4s
            MESSAGE_FADE_OUT_MS: 400,    // Fade out animation
            UNDO_DISPLAY_MS: 5000,       // Undo bar display duration
            COLUMN_RESIZE_DEBOUNCE_MS: 300,  // Debounce column width saves
            CHANGE_CHECK_INTERVAL_MS: 5000,  // Poll for external changes every 5s

            // CSV import
            IMPORT_MAX_FILE_SIZE: 2 * 1024 * 1024,  // 2 MB
            IMPORT_PREVIEW_ROWS: 10,
            IMPORT_MAX_ERRORS: 10,
            IMPORT_MAX_WARN_EXAMPLES: 5,

            // Approval and limits
            MAX_BULK_EDIT_COUNT: 2,  // Threshold for requiring approval
            NOTIFICATION_POLLING_INTERVAL: 5000,  // Poll notifications every 5s

            // Version control
            MAX_VERSIONS_SHOWN: 5,  // Number of previous versions in dropdown
        },

        // ════════════════════════════════════════════════════════════════
        // Regular Expressions — Validation patterns for CSV import
        // ════════════════════════════════════════════════════════════════
        PATTERNS: {
            // Column name validation: must start with letter/digit, contain only safe chars
            SAFE_COLNAME: /^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-.()\/:&#@+]+$/,

            // Expiration date validation: YYYY-MM-DD or YYYY-MM-DD HH:MM or YYYY-MM-DD HH:MM UTC
            VALID_EXPIRE_DATE: /^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?( UTC)?$/,

            // Email validation (basic)
            EMAIL: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,

            // IP address (basic IPv4 and IPv6)
            IP_ADDRESS: /^(\d{1,3}\.){3}\d{1,3}$|^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/,
        },

        // ════════════════════════════════════════════════════════════════
        // Roles — RBAC role names from authorize.conf
        // ════════════════════════════════════════════════════════════════
        ROLES: {
            ADMIN: "admin",
            SC_ADMIN: "sc_admin",
            WL_EDITOR: "wl_editor",
            WL_VIEWER: "wl_viewer",
            POWER: "power",

            // Role combinations for permission checks
            ADMIN_ROLES: ["admin", "sc_admin", "power"],
            EDITOR_ROLES: ["admin", "sc_admin", "wl_editor", "power"],
            VIEWER_ROLES: ["admin", "sc_admin", "wl_editor", "wl_viewer", "power"],
        },

        // ════════════════════════════════════════════════════════════════
        // Action Types — Operations tracked in audit trail
        // ════════════════════════════════════════════════════════════════
        ACTION_TYPES: {
            SAVE_CSV: "save_csv",
            REVERT_CSV: "revert_csv",
            CREATE_CSV: "create_csv",
            DELETE_CSV: "delete_csv",
            CREATE_RULE: "create_rule",
            DELETE_RULE: "delete_rule",
            EDIT_ROW: "edit_row",
            ADD_ROW: "add_row",
            REMOVE_ROW: "remove_row",
            IMPORT_CSV: "import_csv",
            SET_EXPIRATION: "set_expiration",
        },

        // ════════════════════════════════════════════════════════════════
        // HTTP Constants — REST API methods and status codes
        // ════════════════════════════════════════════════════════════════
        HTTP: {
            // HTTP methods
            GET: "GET",
            POST: "POST",
            PUT: "PUT",
            DELETE: "DELETE",

            // Status codes
            OK: 200,
            CREATED: 201,
            ACCEPTED: 202,
            NO_CONTENT: 204,
            BAD_REQUEST: 400,
            UNAUTHORIZED: 401,
            FORBIDDEN: 403,
            NOT_FOUND: 404,
            CONFLICT: 409,
            INTERNAL_ERROR: 500,
            SERVICE_UNAVAILABLE: 503,
        },

        // ════════════════════════════════════════════════════════════════
        // Message Types — Notification categories used in UI
        // ════════════════════════════════════════════════════════════════
        MESSAGE_TYPES: {
            ERROR: "error",
            SUCCESS: "success",
            WARNING: "warning",
            INFO: "info",
        },

        // ════════════════════════════════════════════════════════════════
        // Expire Column Names — Case-insensitive list of supported expiry columns
        // ════════════════════════════════════════════════════════════════
        EXPIRE_COLUMN_NAMES: [
            "expires",
            "expire",
            "expiration",
            "expiration_date",
            "expiry",
            "termination_date",
            "end_date",
            "deactivation_date",
        ],
    };

    return Constants;
});
