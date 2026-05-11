/**
 * Unit tests for wl_approval_ui.js — pure helper functions
 *
 * Ring 4 Day 3. Targets the testable subset of the approval
 * UI module: helpers that consume the module's ``_state``
 * proxy without touching the DOM or making network calls.
 *
 * Functions covered
 * -----------------
 *
 * - ``extractApprovalReason(pa)`` — pulls the analyst's
 *   reason out of an approval-queue entry's payload. Per
 *   ``action_type``, the reason lives in different
 *   payload fields (different schemas for bulk_row_removal,
 *   bulk_row_addition, column_removal, revert).
 *
 * - ``getPendingRowIndices(pa)`` — given a pending approval
 *   with row-level highlight metadata, returns the indices
 *   in ``_state.currentRows`` that match those row keys.
 *   Uses counter-based matching (not set) so duplicate rows
 *   are highlighted exactly N times, not just once.
 *
 * - ``buildLockedState()`` — sets ``_state.csvLocked`` based
 *   on whether there are any pending approvals. The UI uses
 *   this to disable editing while a request is in flight.
 *
 * Why these matter
 * ----------------
 *
 * - extractApprovalReason: any schema drift between handler
 *   and frontend (the build 614 "Invalid Date" pattern)
 *   surfaces here. Unit-test each branch so the next
 *   action-type addition is caught at PR time, not after
 *   shipping.
 * - getPendingRowIndices: the counter-based duplicate
 *   handling is a CLAUDE.md-documented bug pattern
 *   ("Sets lose duplicate count info"). Unit-pin so the
 *   fix can't regress.
 * - buildLockedState: 1-line function, but it's the only
 *   gate between "queue is empty so editing is unlocked"
 *   and "queue has entries so editing is locked". Worth
 *   pinning the boundary.
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
    "appserver", "static", "modules", "wl_approval_ui.js");

let mod;
let testState;

beforeEach(() => {
    // Fresh state per test — defaults match what the
    // module expects. Each test mutates testState fields
    // it cares about.
    testState = {
        currentRows: [],
        currentHeaders: [],
        pendingApprovals: [],
        isAdmin: false,
        csvLocked: false,
    };
    mod = loadAmdModule(MODULE_PATH, {
        "jquery": function () {
            return { find: function () { return { each: function () {} }; } };
        },
        "underscore": {},
    });
    mod.init({
        state: testState,
        $table: { find: function () {
            return { each: function () {} };
        } },
        $revertSelect: null,
        actions: {},
    });
});

// ─────────────────────────────────────────────────────────────────
// extractApprovalReason — per-action-type schema dispatch
// ─────────────────────────────────────────────────────────────────

describe("extractApprovalReason — schema-per-action", () => {
    it("returns the first bulk_removal.reason for bulk_row_removal", () => {
        const pa = {
            action_type: "bulk_row_removal",
            payload: {
                bulk_removal: [
                    { reason: "compliance cleanup" },
                    { reason: "second entry" },
                ],
            },
        };
        expect(mod.extractApprovalReason(pa))
            .toBe("compliance cleanup");
    });

    it("returns row_add_reason for bulk_row_addition", () => {
        const pa = {
            action_type: "bulk_row_addition",
            payload: { row_add_reason: "new threat IOC" },
        };
        expect(mod.extractApprovalReason(pa))
            .toBe("new threat IOC");
    });

    it("returns first column_removal_reasons.reason for column_removal", () => {
        const pa = {
            action_type: "column_removal",
            payload: {
                column_removal_reasons: [
                    { reason: "schema cleanup" },
                ],
            },
        };
        expect(mod.extractApprovalReason(pa))
            .toBe("schema cleanup");
    });

    it("returns revert_reason for revert", () => {
        const pa = {
            action_type: "revert",
            payload: { revert_reason: "bad change rollback" },
        };
        expect(mod.extractApprovalReason(pa))
            .toBe("bad change rollback");
    });

    it("returns empty string for unrecognized action_type", () => {
        // Defensive default — the UI displays the result
        // verbatim, so returning "" is safer than throwing.
        const pa = {
            action_type: "newly_added_in_future",
            payload: { some_other_field: "ignored" },
        };
        expect(mod.extractApprovalReason(pa)).toBe("");
    });

    it("returns empty string when payload is missing", () => {
        // Schema-drift guard: if the queue entry shape
        // shifts, the helper must NOT throw. The build 614
        // incident was exactly this pattern (payload field
        // renamed; UI threw on .toLocaleString of undefined).
        expect(mod.extractApprovalReason({
            action_type: "bulk_row_removal",
        })).toBe("");
        expect(mod.extractApprovalReason({
            action_type: "bulk_row_removal",
            payload: {},
        })).toBe("");
        expect(mod.extractApprovalReason({
            action_type: "bulk_row_removal",
            payload: { bulk_removal: [] },
        })).toBe("");
    });
});

// ─────────────────────────────────────────────────────────────────
// getPendingRowIndices — counter-based row matching
// ─────────────────────────────────────────────────────────────────

describe("getPendingRowIndices — single-row highlight", () => {
    it("returns the index of the matching row", () => {
        testState.currentRows = [
            { user: "alice", host: "h1" },
            { user: "bob",   host: "h2" },
            { user: "carol", host: "h3" },
        ];
        testState.currentHeaders = ["user", "host"];
        const pa = {
            pending_highlight: {
                type: "rows",
                row_keys: [["bob", "h2"]],
                headers: ["user", "host"],
            },
        };
        expect(mod.getPendingRowIndices(pa)).toEqual([1]);
    });

    it("returns [] for non-row highlight types", () => {
        // type: "table" or "column" should NOT yield row
        // indices — those are different highlight modes
        // (full-table amber vs column-header amber).
        testState.currentRows = [{ user: "x" }];
        testState.currentHeaders = ["user"];
        expect(mod.getPendingRowIndices({
            pending_highlight: { type: "column",
                column_name: "user" },
        })).toEqual([]);
        expect(mod.getPendingRowIndices({
            pending_highlight: { type: "table" },
        })).toEqual([]);
    });
});

describe("getPendingRowIndices — duplicate-row counter", () => {
    it("matches duplicate-content rows exactly once each", () => {
        // CLAUDE.md "Sets lose duplicate count info" lesson:
        // currentRows has three identical rows; row_keys
        // requests TWO matches. Set-based matching would
        // return all 3 indices (wrong); counter-based
        // returns exactly the first 2.
        testState.currentRows = [
            { user: "dup", host: "h1" }, // 0
            { user: "dup", host: "h1" }, // 1
            { user: "dup", host: "h1" }, // 2
        ];
        testState.currentHeaders = ["user", "host"];
        const pa = {
            pending_highlight: {
                type: "rows",
                row_keys: [
                    ["dup", "h1"],
                    ["dup", "h1"],
                ],
                headers: ["user", "host"],
            },
        };
        expect(mod.getPendingRowIndices(pa)).toEqual([0, 1]);
    });

    it("matches all duplicates when row_keys count equals row count", () => {
        // Three identical rows in the data, three identical
        // row_keys in the request → all 3 indices match.
        testState.currentRows = [
            { user: "dup", host: "h1" },
            { user: "dup", host: "h1" },
            { user: "dup", host: "h1" },
        ];
        testState.currentHeaders = ["user", "host"];
        const pa = {
            pending_highlight: {
                type: "rows",
                row_keys: [
                    ["dup", "h1"],
                    ["dup", "h1"],
                    ["dup", "h1"],
                ],
                headers: ["user", "host"],
            },
        };
        expect(mod.getPendingRowIndices(pa)).toEqual([0, 1, 2]);
    });

    it("skips internal _-prefixed columns when no headers given", () => {
        // When pending_highlight.headers is missing, the
        // helper falls back to currentHeaders MINUS _-cols.
        // _added_by should NOT contribute to the key.
        testState.currentRows = [
            { user: "alice", _added_by: "admin" },
            { user: "alice", _added_by: "other" },
        ];
        testState.currentHeaders = ["user", "_added_by"];
        const pa = {
            pending_highlight: {
                type: "rows",
                row_keys: [["alice"]],
                // headers omitted — fallback path
            },
        };
        // Without _added_by in the key, both rows have key
        // ["alice"]. Counter requests 1; first match (idx 0).
        expect(mod.getPendingRowIndices(pa)).toEqual([0]);
    });
});

// ─────────────────────────────────────────────────────────────────
// buildLockedState — locked-iff-pending boundary
// ─────────────────────────────────────────────────────────────────

describe("buildLockedState — pending-approval gate", () => {
    it("sets csvLocked=false when queue is empty", () => {
        testState.pendingApprovals = [];
        testState.csvLocked = true; // dirty initial
        mod.buildLockedState();
        expect(testState.csvLocked).toBe(false);
    });

    it("sets csvLocked=true when queue has any entry", () => {
        testState.pendingApprovals = [
            { action_type: "bulk_row_removal", payload: {} },
        ];
        testState.csvLocked = false; // dirty initial
        mod.buildLockedState();
        expect(testState.csvLocked).toBe(true);
    });
});
