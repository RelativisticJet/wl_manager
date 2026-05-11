/**
 * Unit tests for wl_diff.js — renderDiff()
 *
 * Ring 4 Day 3. Tests the HTML output of the diff renderer,
 * which is the user-facing summary shown after every save.
 * Bugs here mean users see wrong / misleading counts of what
 * they're about to save — a class of bug that's easy to ship
 * because the data path looks fine and only the display
 * differs.
 *
 * Why renderDiff is testable
 * --------------------------
 *
 * The function calls ``$diff.html(html)`` at the end (writes
 * to a jQuery DOM ref). Unit-testable by capturing what gets
 * passed to ``.html()`` — no real DOM needed, just a mock
 * jQuery wrapper.
 *
 * The function ALSO calls ``$("#wl-diff-expand-btn").on(...)``
 * for an expand handler. The global ``$`` mock returns a
 * no-op chainable object so this doesn't throw.
 *
 * What we DON'T test here
 * -----------------------
 *
 * - The click handler behavior (would need a real DOM)
 * - Exact CSS styles (those are visual regression's job —
 *   see tests/e2e/test_visual_regression.cjs)
 *
 * What we DO test
 * ---------------
 *
 * - The output string contains the expected structural
 *   sections for each diff input shape
 * - Counts are correctly reflected
 * - Internal _-prefixed columns are NOT leaked into the
 *   user-visible output
 * - Truncation kicks in correctly for long lists
 */
import path from "path";
import { fileURLToPath } from "url";
import { describe, it, expect, beforeEach } from "vitest";
import bridge from "./lib_amd_bridge.cjs";
const { loadAmdModule } = bridge;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const MODULE_PATH = path.resolve(
    __dirname, "..", "..",
    "appserver", "static", "modules", "wl_diff.js");

function underscoreEscape(str) {
    return String(str == null ? "" : str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#x27;");
}

/**
 * Build a jQuery-like mock that's chainable enough for
 * renderDiff's needs: ``$diff.html(s)`` and the global
 * ``$("#...").on("click", ...)`` handler-wiring.
 */
function makeJqMock(capture) {
    // Chainable no-op for the global $ selector
    const chainable = {
        on: function () { return chainable; },
        is: function () { return false; },
        hide: function () { return chainable; },
        show: function () { return chainable; },
        text: function () { return ""; },
    };
    // $ as a function returning chainable
    const jq = function () { return chainable; };
    // $diff target — captures HTML
    const $diff = {
        html: function (s) { capture.html = s; },
    };
    return { jq: jq, $diff: $diff };
}

let mod;
let capture;
let mocks;

beforeEach(() => {
    capture = { html: null };
    mocks = makeJqMock(capture);
    mod = loadAmdModule(MODULE_PATH, {
        "jquery": mocks.jq,
        "underscore": { escape: underscoreEscape },
    });
    // renderDiff requires init() to set the $diff target first
    mod.init({ $diff: mocks.$diff });
});

describe("renderDiff — empty diff", () => {
    it("renders the heading even with no changes", () => {
        mod.renderDiff({});
        expect(capture.html).toContain("Change Summary");
        // No stats line means no <span style=...> color tags
        expect(capture.html).not.toContain("added");
        expect(capture.html).not.toContain("removed");
    });
});

describe("renderDiff — stats bar", () => {
    it("renders added/removed/edited counts with correct labels", () => {
        mod.renderDiff({
            added_count: 3,
            removed_count: 2,
            edited_count: 5,
        });
        // Each count is a plain integer in the stats text
        expect(capture.html).toContain("+3 added");
        expect(capture.html).toContain("2 removed");
        expect(capture.html).toContain("5 edited");
    });

    it("omits a stat when its count is 0/missing", () => {
        // Only added_count provided — the other two should
        // NOT appear in the stats line (no "0 removed", no
        // "0 edited" clutter).
        mod.renderDiff({ added_count: 1 });
        expect(capture.html).toContain("+1 added");
        expect(capture.html).not.toContain("removed");
        expect(capture.html).not.toContain("edited");
    });

    it("renders column add/remove counts", () => {
        mod.renderDiff({
            added_columns: ["new_col", "second"],
            removed_columns: ["old"],
        });
        expect(capture.html).toContain("+2 column(s)");
        expect(capture.html).toContain("1 column(s)");
    });
});

describe("renderDiff — added/removed rows section", () => {
    it("lists each added row's visible fields", () => {
        mod.renderDiff({
            added: [
                { user: "jsmith", host: "h1" },
                { user: "jdoe", host: "h2" },
            ],
        });
        expect(capture.html).toContain("Added Rows (2)");
        expect(capture.html).toContain("jsmith");
        expect(capture.html).toContain("jdoe");
        expect(capture.html).toContain("user: jsmith");
        expect(capture.html).toContain("host: h2");
    });

    it("EXCLUDES internal _-prefixed columns from output", () => {
        // _added_by, _review_status, etc. are internal
        // metadata. Leaking them into the user-visible diff
        // would (a) expose admin user IDs to analysts and
        // (b) clutter the summary. This is a security/UX
        // contract that should be unit-pinned.
        mod.renderDiff({
            added: [{
                user: "jsmith",
                _added_by: "admin",
                _review_status: "pending",
            }],
        });
        expect(capture.html).toContain("user: jsmith");
        expect(capture.html).not.toContain("_added_by");
        expect(capture.html).not.toContain("admin");
        expect(capture.html).not.toContain("_review_status");
    });

    it("lists removed rows separately from added", () => {
        mod.renderDiff({
            removed: [
                { user: "old1", host: "h1" },
            ],
        });
        expect(capture.html).toContain("Removed Rows (1)");
        expect(capture.html).toContain("user: old1");
    });
});

describe("renderDiff — edit truncation", () => {
    it("shows the truncation hint when edits exceed DIFF_MAX_ROWS (10)", () => {
        // Build 12 edits — should show first 10 + truncation
        // message "showing first 10". This is the contract
        // that protects the UI from rendering 1000-edit
        // diffs and freezing the browser.
        const edits = [];
        for (let i = 0; i < 12; i++) {
            edits.push({
                row_num: i + 1,
                old_row: { user: "old_" + i },
                new_row: { user: "new_" + i },
                changed_fields: [{ field: "user" }],
            });
        }
        mod.renderDiff({ edited: edits });
        expect(capture.html).toContain("Edited Rows (12)");
        // Pin the literal truncation phrase — if the UI
        // copy changes, this catches it intentionally.
        expect(capture.html).toContain("showing first 10");
        // First 10 should render; last 2 should not
        expect(capture.html).toContain("old_0");
        expect(capture.html).toContain("old_9");
        expect(capture.html).not.toContain("old_10");
        expect(capture.html).not.toContain("old_11");
    });

    it("does NOT show the truncation hint when edits <= 10", () => {
        const edits = [];
        for (let i = 0; i < 5; i++) {
            edits.push({
                row_num: i + 1,
                old_row: { user: "x_" + i },
                new_row: { user: "y_" + i },
                changed_fields: [{ field: "user" }],
            });
        }
        mod.renderDiff({ edited: edits });
        expect(capture.html).toContain("Edited Rows (5)");
        expect(capture.html).not.toContain("showing first");
    });
});

describe("renderDiff — column change badges", () => {
    it("renders a badge per added/removed column", () => {
        mod.renderDiff({
            added_columns: ["new_col"],
            removed_columns: ["old_col"],
        });
        expect(capture.html).toContain("Column Changes");
        // Badges show the column name with +/- prefix
        expect(capture.html).toContain("new_col");
        expect(capture.html).toContain("old_col");
    });
});
