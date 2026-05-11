/**
 * Unit tests for wl_csv_io.js — csvEscape() + validateImportedCSV()
 *
 * Ring 4 Day 2. Builds on Day 1's parseCSV tests.
 *
 * Functions under test
 * --------------------
 *
 * - ``csvEscape(val)`` — CSV injection protection. Strings
 *   leading with ``=+-@\t\r`` are formula-execution vectors
 *   in Excel / LibreOffice / Google Sheets. The function
 *   neutralizes them by prefixing ``'`` (forces literal
 *   interpretation). Also handles RFC 4180 field quoting
 *   for embedded commas, quotes, newlines.
 *
 * - ``validateImportedCSV(filename, headers, rows)`` — the
 *   schema/safety guard before an import. Returns
 *   ``{ errors, warnings }``. Errors block the import;
 *   warnings are non-blocking (e.g. control chars get
 *   cleaned).
 *
 * Why these next: csvEscape is THE injection-prevention
 * primitive — any bug here is a security regression.
 * validateImportedCSV is the choke point for malformed
 * uploads. Both pure, both critical, both have multiple
 * branches that test cases can independently pin.
 */
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

/**
 * Real underscore-like ``_.escape``. validateImportedCSV
 * uses ``_.escape(h)`` inside error messages, so the mock
 * needs to actually do something — passing the empty mock
 * would yield ``undefined`` in the error string and the
 * test would fail to match.
 *
 * Underscore's ``escape`` is HTML entity escaping. For our
 * test inputs (which don't contain HTML special chars), an
 * identity function would also work, but mirroring the
 * production behavior is more honest.
 */
function underscoreEscape(str) {
    return String(str == null ? "" : str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#x27;");
}

let mod;
beforeAll(() => {
    mod = loadAmdModule(MODULE_PATH, {
        "jquery": {},
        "underscore": { escape: underscoreEscape },
        "app/wl_manager/modules/wl_constants": {
            MAX_ROWS: 10000,
            MAX_COLUMNS: 50,
            MAX_CELL_CHARS: 1024,
            IMPORT_PREVIEW_ROWS: 5,
            // Force LOW so we can test the cap behavior
            // without having to generate 50+ errors.
            IMPORT_MAX_ERRORS: 50,
            IMPORT_MAX_WARN_EXAMPLES: 3,
            SAFE_COLNAME_RE: /^[A-Za-z0-9_\-.()/:#@&+]+$/,
            EXPIRE_COLUMN_NAMES_LIST: [
                "expires", "expire", "expiration",
                "expiration_date", "expiry",
                "termination", "termination_date"],
            VALID_EXPIRE_RE:
                /^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?$/,
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

// ─────────────────────────────────────────────────────────────────
// csvEscape — CSV injection prevention
// ─────────────────────────────────────────────────────────────────

describe("csvEscape — leaves benign strings unchanged", () => {
    it("returns plain alphanumeric input as-is", () => {
        expect(mod.csvEscape("jsmith")).toBe("jsmith");
        expect(mod.csvEscape("host_01")).toBe("host_01");
        expect(mod.csvEscape("")).toBe("");
    });
});

describe("csvEscape — formula-injection neutralization", () => {
    it("prefixes ' to strings leading with =", () => {
        // Excel/Sheets evaluate "=1+1" as a formula when
        // pasted into a cell. The leading ' tells the
        // spreadsheet to treat it as literal text.
        expect(mod.csvEscape("=SUM(A1:A5)")).toBe("'=SUM(A1:A5)");
    });

    it("prefixes ' to other formula-leading chars", () => {
        // The full set: = + - @ \t \r. Each is a known
        // formula-trigger across at least one popular
        // spreadsheet (DDE attacks use @ in some).
        expect(mod.csvEscape("+1+1")).toBe("'+1+1");
        expect(mod.csvEscape("-1-1")).toBe("'-1-1");
        expect(mod.csvEscape("@cmd")).toBe("'@cmd");
        expect(mod.csvEscape("\tfoo")).toBe("'\tfoo");
        expect(mod.csvEscape("\rfoo")).toBe("'\rfoo");
    });

    it("does NOT prefix ' to formula chars in the middle", () => {
        // Only LEADING chars trigger formula evaluation.
        // "1=1" or "x=y" are literal text in spreadsheets.
        expect(mod.csvEscape("1=1")).toBe("1=1");
        expect(mod.csvEscape("x+y")).toBe("x+y");
    });
});

describe("csvEscape — RFC 4180 field quoting", () => {
    it("quotes fields with embedded commas", () => {
        expect(mod.csvEscape("a,b"))
            .toBe('"a,b"');
    });

    it("doubles embedded quotes per RFC 4180 §2.7", () => {
        // The literal string `she said "hi"` becomes
        // `"she said ""hi"""` in CSV (outer quotes wrap the
        // field; each embedded `"` is doubled).
        expect(mod.csvEscape('she said "hi"'))
            .toBe('"she said ""hi"""');
    });

    it("quotes fields with embedded newlines", () => {
        // Newlines inside a field MUST be quoted (RFC 4180
        // §2.6). Otherwise the line break would terminate
        // the row.
        expect(mod.csvEscape("line1\nline2"))
            .toBe('"line1\nline2"');
    });

    it("combines formula-prefix and quoting when both apply", () => {
        // "=A1,B1" needs BOTH formula-neutralize and quoting
        // (leading `=` AND embedded comma). The function
        // adds `'` first, then wraps in quotes — net result
        // is `"'=A1,B1"`.
        expect(mod.csvEscape("=A1,B1"))
            .toBe('"\'=A1,B1"');
    });
});

// ─────────────────────────────────────────────────────────────────
// validateImportedCSV — schema and safety guard
// ─────────────────────────────────────────────────────────────────

describe("validateImportedCSV — happy path", () => {
    it("accepts a well-formed CSV with no errors or warnings", () => {
        const result = mod.validateImportedCSV(
            "wl_users.csv",
            ["user", "host"],
            [{ user: "jsmith", host: "h1" },
             { user: "jdoe", host: "h2" }]);
        expect(result.errors).toEqual([]);
        expect(result.warnings).toEqual([]);
    });
});

describe("validateImportedCSV — filename rules", () => {
    it("rejects filenames with invalid characters", () => {
        // Shell metacharacters in filenames are an injection
        // vector if the filename ever reaches a subprocess.
        // The check is conservative — only alphanumerics,
        // underscore, hyphen, dot.
        const result = mod.validateImportedCSV(
            "bad file.csv", ["user"], [{ user: "x" }]);
        expect(result.errors.some(e =>
            /invalid characters/.test(e))).toBe(true);
    });

    it("rejects filenames over 100 chars", () => {
        const longName = "a".repeat(101) + ".csv";
        const result = mod.validateImportedCSV(
            longName, ["user"], [{ user: "x" }]);
        expect(result.errors.some(e =>
            /Filename too long/.test(e))).toBe(true);
    });

    it("rejects filenames whose stem has no letter or number", () => {
        // ___.csv has only underscores — no semantic
        // identifier. Could be confused with internal
        // version snapshots like _versions/_*.json.
        const result = mod.validateImportedCSV(
            "___.csv", ["user"], [{ user: "x" }]);
        expect(result.errors.some(e =>
            /at least one letter or number/.test(e))).toBe(true);
    });
});

describe("validateImportedCSV — column-name rules", () => {
    it("rejects underscore-prefixed columns (reserved)", () => {
        // _ prefix is reserved for internal metadata
        // columns (_added_by, _review_status, etc.). Letting
        // users create _-prefixed columns would let them
        // overwrite metadata and hide data from auditors
        // (this is the exact bug class fixed in
        // MEMORY.md's "Reserved prefix convention" lesson).
        const result = mod.validateImportedCSV(
            "wl.csv", ["user", "_hidden"],
            [{ user: "x", _hidden: "y" }]);
        expect(result.errors.some(e =>
            /starts with underscore/.test(e))).toBe(true);
    });

    it("rejects duplicate column headers (case-insensitive)", () => {
        // Two columns named "User" and "user" would collide
        // when keys become dict entries, silently losing
        // data. The check lowercases for comparison so
        // case-only duplicates also fail.
        const result = mod.validateImportedCSV(
            "wl.csv", ["user", "User"],
            [{ user: "x", User: "y" }]);
        expect(result.errors.some(e =>
            /Duplicate column header/.test(e))).toBe(true);
    });

    it("rejects empty column headers", () => {
        // Whitespace-only or empty headers at any position
        // are a malformed-file signal — the user probably
        // has a trailing comma or merged cell issue.
        const result = mod.validateImportedCSV(
            "wl.csv", ["user", "", "host"],
            [{ user: "x", host: "h" }]);
        expect(result.errors.some(e =>
            /position 2 is empty/.test(e))).toBe(true);
    });
});

describe("validateImportedCSV — cell content rules", () => {
    it("flags control-char cells as warning, not error", () => {
        // Control chars are auto-stripped on import (not a
        // blocking issue; we just inform the user). Test
        // that this is in WARNINGS, not errors.
        const result = mod.validateImportedCSV(
            "wl.csv", ["user", "note"],
            [{ user: "x", note: "has\x07bell" }]);
        expect(result.errors).toEqual([]);
        const sanWarning = result.warnings.find(
            w => w.type === "sanitization");
        expect(sanWarning).toBeDefined();
        expect(sanWarning.message)
            .toMatch(/control characters/);
    });

    it("detects encoding-corrupted cells (only ? chars)", () => {
        // Excel's "Save As ANSI CSV" on a Cyrillic / CJK
        // source produces strings of only ?. This pattern
        // means the source had data we can no longer
        // recover. Block the import so the user knows their
        // source file is corrupted, not us.
        const result = mod.validateImportedCSV(
            "wl.csv", ["user", "name"],
            [{ user: "x", name: "????" }]);
        expect(result.errors.some(e =>
            /encoding corruption/.test(e))).toBe(true);
    });

    it("detects an expiration column and flags invalid dates", () => {
        // The validator detects ANY column with a name in
        // EXPIRE_COLUMN_NAMES_LIST and validates its values
        // against YYYY-MM-DD or YYYY-MM-DD HH:MM. Wrong
        // format means scheduled cleanup won't run on
        // those rows.
        const result = mod.validateImportedCSV(
            "wl.csv", ["user", "expires"],
            [{ user: "x", expires: "2026-12-31" },
             { user: "y", expires: "tomorrow" }]);
        // Warning for expires column detection
        const expWarning = result.warnings.find(
            w => w.type === "expires_detected");
        expect(expWarning).toBeDefined();
        // Blocking error for the invalid date
        expect(result.errors.some(e =>
            /invalid dates.*tomorrow/.test(e))).toBe(true);
    });
});
