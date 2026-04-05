/**
 * wl_constants.js — Shared constants extracted from whitelist_manager.js
 *
 * Limits, patterns, and configuration values used across multiple modules.
 * No dependencies. Pure data module.
 */
define([], function () {
    "use strict";

    return {
        // ── Pagination ──────────────────────────────────────────────
        ROWS_PER_PAGE:    10,
        PAGE_SIZE_OPTIONS: [10, 20, 50],

        // ── CSV limits ──────────────────────────────────────────────
        MAX_ROWS:       5000,
        MAX_COLUMNS:    100,
        MAX_CELL_CHARS: 1000,

        // ── CSV Import ──────────────────────────────────────────────
        IMPORT_MAX_FILE_SIZE:    2 * 1024 * 1024,   // 2 MB
        IMPORT_PREVIEW_ROWS:     10,
        IMPORT_MAX_ERRORS:       10,
        IMPORT_MAX_WARN_EXAMPLES: 5,

        // ── Validation patterns ─────────────────────────────────────
        SAFE_COLNAME_RE:  /^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_\-.()\/:&#@+]+$/,
        VALID_EXPIRE_RE:  /^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?( UTC)?$/,

        // ── Expire column detection ─────────────────────────────────
        EXPIRE_COLUMN_NAMES_LIST: [
            "expires", "expire", "expiration", "expiration_date",
            "expiry", "termination", "termination_date"
        ],

        // ── Text field validation ──────────────────────────────────
        NON_ASCII_RE: /[^\x00-\x7F]/,
        ASCII_ERROR_MSG: "Only ASCII characters are allowed in text fields"
    };
});
