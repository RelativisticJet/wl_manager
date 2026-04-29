/**
 * Concurrent approval-process race test (round 6).
 *
 * Goal: two admins simultaneously submit `process_approval` for the
 * same pending request. The handler uses ``_approval_queue_lock()``
 * (a sibling .rmw.lock file with fcntl serialization) around the
 * read-modify-write cycle in ``_process_approval_inner``. This test
 * verifies the lock actually works — without it, both admins could
 * pass the "status == pending" check before either writes, leading
 * to the request being executed TWICE (e.g. a delete_rule replayed
 * twice would flap audit events and could re-create then re-delete).
 *
 * Method:
 *   - Create a rule, submit a delete approval.
 *   - Two admins fire `process_approval` decision=approve in parallel
 *     against the same request_id.
 *   - Expect exactly ONE success + one error indicating the entry
 *     is already resolved (or rejected because the approval lock
 *     forced serialization).
 *
 * Origin: round 6 audit, 2026-04-29.
 */

const H = require("./lib_helpers.cjs");

const ADMIN1_USER = "wladmin1";
const ADMIN1_PASS = "Chang3d!";
const SUPERADMIN_USER = "superadmin1";
const SUPERADMIN_PASS = "Chang3d!";
const ANALYST_USER = "analyst1";
const ANALYST_PASS = "Chang3d!";
const TAG = "APPRACE_" + Date.now();
const RULE = "DR_" + TAG;
const CSV = RULE + ".csv";

(async () => {
    // Two separate browser sessions = two independent admins racing.
    const sess1 = await H.createSession(ADMIN1_USER, ADMIN1_PASS);
    const sess2 = await H.createSession(SUPERADMIN_USER, SUPERADMIN_PASS);
    const sessAnalyst = await H.createSession(ANALYST_USER, ANALYST_PASS);

    // Setup: superadmin creates a rule + CSV (skips approval gate).
    await H.test("Setup: superadmin creates rule + CSV", async () => {
        const create = await H.restCall(sess2.page, "POST", {
            action: "create_csv",
            detection_rule: RULE,
            csv_file: CSV,
            headers: ["user"],
            initial_rows: [{ user: "alice" }],
            reason: "race-test setup",
        });
        if (create.error) throw new Error("Setup create failed: " + create.error);
    });

    // Submit a delete-rule approval as the analyst (3 CSV count is
    // not relevant here — single-admin gate is enough to land an
    // entry in the queue).
    let requestId = "";
    await H.test("Analyst submits remove-rule approval", async () => {
        // approval_action_type (NOT action_type), and the action
        // name is `remove_rule` not `delete_rule`. See
        // _submit_approval in wl_handler.py for the allow-list.
        const submit = await H.restCall(sessAnalyst.page, "POST", {
            action: "submit_approval",
            approval_action_type: "remove_rule",
            payload: { detection_rule: RULE, removal_type: "permanent" },
            reason: "race-test approval target",
        });
        if (submit.error) throw new Error("submit failed: " + submit.error);
        requestId = submit.request_id || (submit.entry && submit.entry.request_id) || "";
        if (!requestId) {
            // Some response shapes embed request_id elsewhere — look up the
            // queue and pick the freshest pending entry for our rule.
            const qres = await H.restCall(sess2.page, "GET", {
                action: "get_approval_queue",
            });
            const queue = qres.approval_queue || [];
            const ours = queue.filter(e =>
                e.detection_rule === RULE && e.status === "pending");
            if (!ours.length) throw new Error("no pending entry found");
            requestId = ours[ours.length - 1].request_id;
        }
        console.log("    request_id:", requestId);
    });

    // The actual race: fire both approve calls in parallel.
    //
    // Success criteria for the lock are about EXECUTION REACHED,
    // not about the underlying replay result. The replay can fail
    // for orthogonal reasons (invalid payload, deleted rule, etc.)
    // — what matters is that ONLY ONE admin's call reaches the
    // replay step, and the other observes post-mortem state.
    //
    // Loser identification: their response carries an error
    // matching /already.*(resolved|failed|approved|rejected)/ or
    // similar "not pending" wording. If both admins reach replay,
    // the lock failed.
    let r1 = null, r2 = null;
    await H.test("Two admins approve same request simultaneously", async () => {
        const p1 = H.restCall(sess1.page, "POST", {
            action: "process_approval",
            request_id: requestId,
            decision: "approve",
        });
        const p2 = H.restCall(sess2.page, "POST", {
            action: "process_approval",
            request_id: requestId,
            decision: "approve",
        });
        [r1, r2] = await Promise.all([p1, p2]);
        const sigSeesPostMortem = r =>
            /already.*(resolved|failed|approved|rejected)|not (pending|found)/i
                .test(r.error || "");
        const sigReachedReplay = r =>
            // Either succeeded outright, or got an "Execution failed"
            // (handler entered the replay path but the replay's own
            // logic rejected for orthogonal reasons).
            (!r.error && r.success !== false) ||
            /Execution failed|replay/i.test(r.error || "");

        const post1 = sigSeesPostMortem(r1), post2 = sigSeesPostMortem(r2);
        const exec1 = sigReachedReplay(r1), exec2 = sigReachedReplay(r2);
        console.log("    admin1: post-mortem=" + post1 + " reached-replay=" + exec1);
        console.log("    super1: post-mortem=" + post2 + " reached-replay=" + exec2);

        // The lock is correct iff exactly ONE caller reached replay
        // AND the other saw a post-mortem error.
        if (exec1 && exec2) {
            throw new Error(
                "RACE: both admins reached replay — lock did not "
                + "serialize. r1=" + JSON.stringify(r1)
                + " r2=" + JSON.stringify(r2));
        }
        if (!exec1 && !exec2) {
            throw new Error(
                "BOTH BLOCKED: neither admin reached replay. r1="
                + JSON.stringify(r1) + " r2=" + JSON.stringify(r2));
        }
        // Exactly one reached replay. The other should report
        // post-mortem state.
        const loserReportedPostMortem = exec1 ? post2 : post1;
        if (!loserReportedPostMortem) {
            console.log("    NOTE: loser did not report a clear "
                + "post-mortem error — message could be clearer");
        } else {
            console.log("    LOCK OK: only one admin reached replay; "
                + "the other saw post-mortem state");
        }
    });

    // Sanity: queue should now show resolved. ANY further approval
    // attempt MUST also fail.
    await H.test("Third approval attempt rejected (already resolved)", async () => {
        const r3 = await H.restCall(sess1.page, "POST", {
            action: "process_approval",
            request_id: requestId,
            decision: "approve",
        });
        if (!r3.error && r3.success !== false) {
            throw new Error(
                "third approve unexpectedly succeeded — queue state "
                + "drift detected: " + JSON.stringify(r3));
        }
        console.log("    rejected as expected:", (r3.error || "").slice(0, 80));
    });

    H.summary("CONCURRENT APPROVAL RACE");
    await sess1.browser.close();
    await sess2.browser.close();
    await sessAnalyst.browser.close();
})();
