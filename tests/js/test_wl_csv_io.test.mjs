/**
 * Unit tests for wl_csv_io.js — parseCSV()
 *
 * Ring 4 Day 1. Establishes the JS unit-test contract using
 * Vitest + the AMD bridge in lib_amd_bridge.cjs. Covers the
 * RFC 4180 CSV parser at its corner cases, which are the
 * historical bug surface in this codebase:
 *
 * - BOM handling
 * - CRLF vs LF line endings
 * - Quoted fields with embedded commas / escaped quotes
 * - Binary-file detection (null-byte guard)
 * - Header whitespace validation
 *
 * Why this module first: parseCSV is genuinely PURE
 * (string → {headers, rows, errors}). The AMD module declares
 * deps on jQuery, underscore, and three sibling modules, but
 * parseCSV's BODY only uses String/RegExp/Array primitives —
 * so empty mocks suffice. Other modules in appserver/static/
 * mix DOM access into their pure helpers and need richer
 * mocks; we'll add those over Days 2-3.
 */
// ESM test file (.mjs) — vitest is ESM-only since v3.x. The
// AMD bridge stays CJS (uses Node's `vm` module to evaluate
// AMD code); ESM can import CJS without ceremony.
import path from "path";
import { fileURLToPath } from "url";
import { describe, it, expect, beforeAll } from "vitest";
import bridge from "./lib_amd_bridge.cjs";
const { loadAmdModule } = bridge;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const MODULE_PATH = path.resolve(
    __dirname, "..", "..",
    "appserver", "static", "modules", "wl_csv_io.js");

let mod;
beforeAll(() => {
    // parseCSV doesn't use the injected jQuery / underscore /
    // wl_constants / wl_rest / wl_ui — pass empty mocks. If a
    // future refactor adds a dependency into parseCSV's body,
    // the test will throw with a clear error pointing at the
    // missing mock.
    mod = loadAmdModule(MODULE_PATH, {
        "jquery": {},
        "underscore": {},
        "app/wl_manager/modules/wl_constants": {
            // parseCSV doesn't read any of these but the
            // module's top-level destructuring (var MAX_ROWS
            // = C.MAX_ROWS) accesses them. Provide
            // placeholders so the factory doesn't throw on
            // ``C.SAFE_COLNAME_RE.test(...)`` etc. that other
            // exported functions reference.
            MAX_ROWS: 10000,
            MAX_COLUMNS: 50,
            MAX_CELL_CHARS: 1024,
            IMPORT_PREVIEW_ROWS: 5,
            IMPORT_MAX_ERRORS: 50,
            IMPORT_MAX_WARN_EXAMPLES: 3,
            SAFE_COLNAME_RE: /^[A-Za-z0-9_-]+$/,
            EXPIRE_COLUMN_NAMES_LIST: [
                "expires", "expire", "expiration"],
            VALID_EXPIRE_RE: /^\d{4}-\d{2}-\d{2}$/,
            NON_ASCII_RE: /[^\x00-\x7F]/,
        },
        "app/wl_manager/modules/wl_rest": {
            restGet: function () {},
            restPost: function () {},
        },
        "app/wl_manager/modules/wl_ui": {
            showMsg: function () {},
            formatDailyLimitMsg: function () { return ""; },
        },
    });
});

describe("parseCSV — happy path", () => {
    it("parses a basic CSV with LF line endings", () => {
        const csv = "user,host\njsmith,h1\njdoe,h2\n";
        const result = mod.parseCSV(csv);
        expect(result.errors).toEqual([]);
        expect(result.headers).toEqual(["user", "host"]);
        expect(result.rows).toEqual([
            { user: "jsmith", host: "h1" },
            { user: "jdoe", host: "h2" },
        ]);
    });
});

describe("parseCSV — Windows source format (CRLF + BOM)", () => {
    it("strips UTF-8 BOM and normalizes CRLF line endings", () => {
        // 0xFEFF is the BOM; combined with CRLF it's the
        // common output of Excel "Save As CSV (UTF-8)" on
        // Windows.
        const csv = "﻿user,host\r\njsmith,h1\r\njdoe,h2\r\n";
        const result = mod.parseCSV(csv);
        expect(result.errors).toEqual([]);
        expect(result.headers).toEqual(["user", "host"]);
        expect(result.rows.length).toBe(2);
        // BOM should NOT leak into the first header. Pinning
        // by exact equality catches the regression where a
        // BOM-stripped header becomes "﻿user" — that
        // would silently break lookups by column name.
        expect(result.headers[0]).toBe("user");
    });
});

describe("parseCSV — RFC 4180 quoted fields", () => {
    it("handles embedded commas and escaped double-quotes", () => {
        // RFC 4180 §2.5-2.7: fields containing commas, line
        // breaks, or double-quote chars MUST be quoted; an
        // embedded double-quote is represented by a pair.
        //
        // Test input has three corner cases in one field:
        //   - embedded comma: "name, with comma"
        //   - escaped quote: "she said ""hi"""
        //   - normal unquoted field after a quoted one
        const csv = 'col1,col2\n'
                  + '"name, with comma","she said ""hi"""\n'
                  + 'plain,value\n';
        const result = mod.parseCSV(csv);
        expect(result.errors).toEqual([]);
        expect(result.rows).toEqual([
            { col1: "name, with comma", col2: 'she said "hi"' },
            { col1: "plain", col2: "value" },
        ]);
    });
});

describe("parseCSV — binary-file rejection", () => {
    it("returns a clear error on null-byte content", () => {
        // The parser checks the first 8KB for null bytes.
        // PNG/JPEG/PDF uploads (where the user accidentally
        // hit "import CSV" with a non-CSV file) all contain
        // \x00 in the first few bytes; this fingerprint is
        // the cheapest way to reject them BEFORE trying to
        // tokenize.
        const csv = "user,host\nfoo\x00bar,h1\n";
        const result = mod.parseCSV(csv);
        expect(result.headers).toEqual([]);
        expect(result.rows).toEqual([]);
        expect(result.errors).toEqual([
            "File appears to be binary, not a text CSV.",
        ]);
    });
});

describe("parseCSV — header validation", () => {
    it("rejects column names containing whitespace", () => {
        // Whitespace in column names breaks downstream code
        // that uses `headers[i]` as a key (the row dict
        // would key by "col one" with a literal space, which
        // doesn't match anything elsewhere in the app where
        // column names are bare identifiers). Catch at parse
        // time so the user gets a meaningful error instead
        // of silently broken lookups.
        const csv = "user_id,col one,host\n1,foo,h1\n";
        const result = mod.parseCSV(csv);
        expect(result.errors.length).toBe(1);
        expect(result.errors[0]).toMatch(/col one/);
        expect(result.errors[0]).toMatch(/cannot have spaces/);
        // When header validation fails, rows are NOT
        // returned — the contract is "errors-only response"
        // so callers don't accidentally process malformed
        // data.
        expect(result.rows).toEqual([]);
    });
});
