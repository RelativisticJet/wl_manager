/**
 * Concurrent save_csv stress test (MED-5 from round 4).
 *
 * Goal: quantify the TOCTOU race in optimistic-lock save_csv.
 * Two clients fetch the same expected_content_hash, both submit
 * different changes simultaneously, and we observe whether:
 *
 *   (a) ONE wins via 409 Conflict on the loser (proper optimistic lock)
 *   (b) BOTH succeed and the loser's change overwrites the winner
 *       (current behavior — TOCTOU window between hash-check and write)
 *
 * This test does NOT fix the bug — it characterizes it. If we ever
 * add file-locking around save_csv, this test should switch from
 * "expects (b)" to "expects (a)" and the assertion will tighten.
 *
 * Origin: round 4 audit, 2026-04-29.
 */

const H = require("./lib_helpers.cjs");

const ADMIN_USER = "wladmin1";
const ADMIN_PASS = "Chang3d!";
const TAG = "RACE_" + Date.now();
const RULE = "DR_" + TAG;
const CSV = RULE + ".csv";

(async () => {
    const { browser, page } = await H.createSession(ADMIN_USER, ADMIN_PASS);

    // Setup: create a CSV with one row.
    await H.test("Setup: create CSV with initial row", async () => {
        const create = await H.restCall(page, "POST", {
            action: "create_csv",
            detection_rule: RULE,
            csv_file: CSV,
            headers: ["user", "src_ip"],
            initial_rows: [{ user: "alice", src_ip: "10.0.0.1" }],
        });
        if (create.error) throw new Error("Setup create failed: " + create.error);
    });

    // Fetch the current content hash so both "clients" start from
    // the same view. Both will pass the optimistic-lock check.
    let initialHash = "";
    await H.test("Fetch baseline content hash", async () => {
        const r = await H.restCall(page, "GET", {
            action: "check_csv_status",
            csv_file: CSV,
        });
        if (!r.content_hash) throw new Error("No content hash: " + JSON.stringify(r));
        initialHash = r.content_hash;
    });

    // Concurrent saves with the SAME expected_content_hash.
    // Client A appends "bob", Client B appends "carol". If
    // optimistic locking works correctly, only one should land
    // (the other should 409). If TOCTOU window is open, both
    // 200 OK and the second write wins.
    let resultA = null, resultB = null;
    await H.test("Concurrent save_csv with same hash", async () => {
        const promiseA = H.restCall(page, "POST", {
            action: "save_csv",
            detection_rule: RULE,
            csv_file: CSV,
            headers: ["user", "src_ip"],
            rows: [
                { user: "alice", src_ip: "10.0.0.1" },
                { user: "bob",   src_ip: "10.0.0.2" },
            ],
            comment: TAG + " client A appends bob",
            expected_content_hash: initialHash,
        });
        const promiseB = H.restCall(page, "POST", {
            action: "save_csv",
            detection_rule: RULE,
            csv_file: CSV,
            headers: ["user", "src_ip"],
            rows: [
                { user: "alice", src_ip: "10.0.0.1" },
                { user: "carol", src_ip: "10.0.0.3" },
            ],
            comment: TAG + " client B appends carol",
            expected_content_hash: initialHash,
        });
        [resultA, resultB] = await Promise.all([promiseA, promiseB]);
    });

    // Characterize the outcome:
    //   - Both succeed:    TOCTOU window confirmed (current expected behavior)
    //   - One 409:         Optimistic lock working as intended
    //   - Both 409:        Implausible (one must have committed first)
    //   - Neither succeed: Some other error
    await H.test("Characterize race outcome", async () => {
        const aOk = !resultA.error;
        const bOk = !resultB.error;
        const aConflict = resultA.error && /409|conflict|content hash/i.test(resultA.error);
        const bConflict = resultB.error && /409|conflict|content hash/i.test(resultB.error);

        console.log("    A:", aOk ? "200 OK" : "ERROR " + resultA.error);
        console.log("    B:", bOk ? "200 OK" : "ERROR " + resultB.error);

        if (aOk && bOk) {
            console.log("    OUTCOME: BOTH SUCCEEDED — TOCTOU window open. " +
                "Last-writer-wins, both audit events emitted. " +
                "Acceptable for now (audit trail captures both intents). " +
                "Future hardening: add file_lock around _save_csv read-write.");
        } else if ((aOk && bConflict) || (aConflict && bOk)) {
            console.log("    OUTCOME: PROPER OPTIMISTIC LOCK — one 409, one 200.");
        } else {
            throw new Error("Unexpected race outcome — both errored or other failure");
        }
    });

    // Cleanup: delete the test rule via dual-admin approval flow,
    // or just leave it for the test debris cleaner. Simpler: delete
    // the CSV directly.
    await H.test("Cleanup: remove test CSV", async () => {
        const r = await H.restCall(page, "POST", {
            action: "remove_csv",
            detection_rule: RULE,
            csv_file: CSV,
            comment: TAG + " cleanup",
        });
        // Don't fail the suite on cleanup error; leave for debris cleaner
        if (r.error) console.log("    cleanup note:", r.error);
    });

    H.summary("CONCURRENT SAVE RACE");
    await browser.close();
})();
