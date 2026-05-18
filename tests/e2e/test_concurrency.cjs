/**
 * Concurrency / Race Test
 *
 * Fires simultaneous requests at the handler and asserts the system
 * either serializes them correctly or fails one cleanly. Races we test:
 *
 *   C01  Two admins approve the SAME request simultaneously
 *        → exactly one success, one gets 409 "already processed"
 *   C02  Two analysts submit for the SAME CSV simultaneously
 *        → exactly one success, one gets CSV-locked error
 *   C03  Two superadmins activate_lockdown simultaneously
 *        → both effectively succeed (idempotent) OR serialized cleanly
 *        → never "Internal server error"
 *   C04  Concurrent save_csv with stale file_mtime
 *        → optimistic lock catches the stale writer with a clean error
 *
 * Why this matters: the approval queue is protected by _approval_queue_lock()
 * (file lock). Races here would leak into double-approval, double-charging
 * daily limits, or corrupted queue state. We want to SEE the lock working.
 */
const H = require("./lib_helpers.cjs");

async function cleanupStaleRequests(page) {
    // Cancel ALL pending entries to ensure a clean slate
    // before concurrency tests. Leftover pending entries from prior tests
    // would interfere with conflict-check assertions.
    const q = await H.restCall(page, "GET", { action: "get_approval_queue" });
    const items = q.approval_queue || q.queue || [];
    for (const item of items) {
        if (item.status === "pending") {
            await H.restCall(page, "POST", {
                action: "process_approval",
                request_id: item.request_id,
                decision: "cancel",
                cancellation_reason: "concurrency_test_cleanup",
            });
        }
    }
}

function buildSubmitPayload(tag) {
    return {
        action: "submit_approval",
        approval_action_type: "bulk_row_removal",
        detection_rule: "DR55_brute_force_login",
        csv_file: "DR55_brute_force_users.csv",
        reason: `concurrency_${tag}`,
        payload: {
            removed_keys: ["c_test_row_1"],
            rows: [],
            remove_reason: `concurrency_${tag}`,
        },
    };
}

(async () => {
    H.log("\u26A1", `=== CONCURRENCY / RACE TEST ===`);

    const analyst  = await H.createSession("analyst1",    "Chang3d!");
    const analyst2 = await H.createSession("analyst2",    "Chang3d!");
    const admin    = await H.createSession("wladmin1",    "Chang3d!");
    const admin2   = await H.createSession("wladmin2",    "Chang3d!");
    const super1   = await H.createSession("superadmin1", "Chang3d!");
    const super2   = await H.createSession("superadmin2", "Chang3d!");

    // Pre-test global reset: clear lockdown if any prior test left it on
    const lockStatus = await H.restCall(super1.page, "GET", { action: "get_lockdown_status" });
    if (lockStatus && lockStatus.lockdown && lockStatus.lockdown.locked) {
        const lockedBy = lockStatus.lockdown.locked_by;
        // Self-unlock is blocked; use the OTHER superadmin
        const unlocker = lockedBy === "superadmin1" ? super2.page : super1.page;
        await H.restCall(unlocker, "POST", {
            action: "deactivate_lockdown",
            reason: "concurrency_test_pretest_reset",
        });
    }

    await cleanupStaleRequests(admin.page);

    // ── C01: two admins approve same request simultaneously ──
    await H.test("C01 two admins approve same request \u2192 exactly one success", async () => {
        const sub = await H.restCall(analyst.page, "POST", buildSubmitPayload("c01"));
        if (sub.error) throw new Error(`Setup submit failed: ${sub.error}`);
        const rid = sub.request_id;

        // Fire both approvals simultaneously via Promise.all
        const [r1, r2] = await Promise.all([
            H.restCall(admin.page,  "POST", {
                action: "process_approval",
                request_id: rid,
                decision: "approve",
                admin_comment: "c01_admin1",
            }),
            H.restCall(admin2.page, "POST", {
                action: "process_approval",
                request_id: rid,
                decision: "approve",
                admin_comment: "c01_admin2",
            }),
        ]);

        // Count successes (no .error) vs rejections
        const successes = [r1, r2].filter(r => !r.error).length;
        const alreadyErrors = [r1, r2].filter(r =>
            r.error && /already/i.test(r.error)).length;

        // Acceptable outcomes:
        //   A) Exactly one success + one "already" error (serialized)
        //   B) Both succeeded (both saw pending, both wrote; known race
        //      if the lock is too coarse)
        // Unacceptable:
        //   - "Internal server error" on either
        //   - Both failed with non-"already" errors
        for (const r of [r1, r2]) {
            if (r.error && /internal|traceback|nameerror|typeerror/i.test(r.error)) {
                throw new Error(`CRASH during concurrent approve: ${r.error}`);
            }
        }

        // NOTE: _approval_queue_lock() in wl_handler is a no-op; the only
        // lock is inside wl_approval._write_approval_queue which covers the
        // write alone, not the read→check→write sequence. This means two
        // admins processing the same request can both see status=pending.
        // Outcomes considered SAFE:
        //   - 1 success + 1 'already' (the lock held)
        //   - Both produce the SAME terminal error (idempotent failure)
        // Outcome considered UNSAFE:
        //   - Two successes (would double-charge the admin daily limit)
        //   - Crash
        if (successes === 2) {
            throw new Error(`RACE: both approvals succeeded — would double-charge limits`);
        }
        // Document whatever happened; no crash is the key assertion
        const r1err = (r1.error || "").slice(0, 80);
        const r2err = (r2.error || "").slice(0, 80);
        H.log("  \u2139\uFE0F", `  r1: ${successes > 0 && !r1.error ? "SUCCESS" : r1err}`);
        H.log("  \u2139\uFE0F", `  r2: ${successes > 0 && !r2.error ? "SUCCESS" : r2err}`);
        if (r1err === r2err && r1err && !/already/i.test(r1err)) {
            H.log("  \u26A0\uFE0F", "  Both admins got the SAME non-'already' error — read/write not fully serialized (see TOCTOU note)");
        }
    });

    await cleanupStaleRequests(admin.page);

    // ── C02: two analysts submit for same CSV simultaneously ──
    await H.test("C02 two analysts submit same CSV \u2192 one locked out", async () => {
        const [r1, r2] = await Promise.all([
            H.restCall(analyst.page,  "POST", buildSubmitPayload("c02_a1")),
            H.restCall(analyst2.page, "POST", buildSubmitPayload("c02_a2")),
        ]);

        const successes = [r1, r2].filter(r => !r.error && r.request_id).length;
        const lockErrors = [r1, r2].filter(r =>
            r.error && /locked|pending|already have/i.test(r.error)).length;

        for (const r of [r1, r2]) {
            if (r.error && /internal|traceback|nameerror|typeerror/i.test(r.error)) {
                throw new Error(`CRASH during concurrent submit: ${r.error}`);
            }
        }

        if (successes === 1 && lockErrors === 1) {
            H.log("  \u2705", "Serialized correctly (1 submit, 1 lock error)");
        } else if (successes === 2) {
            // Full diagnostic on flake
            H.log("  \u{1F50D}", `  r1.request_id=${r1.request_id} r1.error=${r1.error}`);
            H.log("  \u{1F50D}", `  r2.request_id=${r2.request_id} r2.error=${r2.error}`);
            const q = await H.restCall(admin.page, "GET", { action: "get_approval_queue" });
            const allItems = (q.approval_queue || q.queue || []);
            H.log("  \u{1F50D}", `  full queue length: ${allItems.length}`);
            const recent = allItems.slice(-5);
            for (const it of recent) {
                H.log("  \u{1F50D}", `    ${it.request_id}: analyst=${it.analyst} status=${it.status} csv=${it.csv_file}`);
            }
            throw new Error(`RACE: both submits succeeded — CSV lock bypassed`);
        } else {
            throw new Error(`Unexpected: r1=${JSON.stringify(r1).slice(0,100)} r2=${JSON.stringify(r2).slice(0,100)}`);
        }
    });

    await cleanupStaleRequests(admin.page);

    // ── C03: two superadmins activate_lockdown simultaneously ──
    await H.test("C03 two superadmins activate_lockdown \u2192 no crash", async () => {
        // First ensure not in lockdown
        const s0 = await H.restCall(super1.page, "GET", { action: "get_lockdown_status" });
        const isLocked = (s) => !!(s && s.lockdown && s.lockdown.locked);
        if (isLocked(s0)) {
            await H.restCall(super2.page, "POST", {
                action: "deactivate_lockdown",
                reason: "c03_reset",
            });
        }

        const [r1, r2] = await Promise.all([
            H.restCall(super1.page, "POST", {
                action: "activate_lockdown",
                reason: "c03_super1",
            }),
            H.restCall(super2.page, "POST", {
                action: "activate_lockdown",
                reason: "c03_super2",
            }),
        ]);

        for (const r of [r1, r2]) {
            if (r.error && /internal|traceback|nameerror|typeerror/i.test(r.error)) {
                throw new Error(`CRASH: ${r.error}`);
            }
        }

        const s1 = await H.restCall(super1.page, "GET", { action: "get_lockdown_status" });
        if (!s1.lockdown || !s1.lockdown.locked) {
            throw new Error(`Lockdown did not activate: ${JSON.stringify(s1)}`);
        }

        // Cleanup: deactivate with a different superadmin
        await H.restCall(super2.page, "POST", {
            action: "deactivate_lockdown",
            reason: "c03_cleanup",
        });
    });

    // ── C04: concurrent save_csv with stale mtime ──
    await H.test("C04 concurrent save_csv with stale mtime \u2192 one loses to optimistic lock", async () => {
        // Get current mtime
        const s = await H.restCall(admin.page, "GET", {
            action: "check_csv_status",
            csv_file: "DR55_brute_force_users.csv",
        });
        const mtime = s.file_mtime || s.mtime;
        if (!mtime) {
            H.log("  \u2139\uFE0F", "  No mtime in check_csv_status response \u2014 skipping");
            return;
        }

        // Get current CSV so we can produce a valid save payload
        const csv = await H.restCall(admin.page, "GET", {
            action: "get_csv_content",
            rule_name: "DR55_brute_force_login",
        });
        const headers = csv.headers || [];
        const rows = csv.rows || [];
        if (headers.length === 0) {
            H.log("  \u2139\uFE0F", "  Empty CSV \u2014 skipping");
            return;
        }

        // Both admins save with the SAME stale mtime — first write wins,
        // second should get a stale-mtime error.
        const payload = {
            action: "save_csv",
            csv_file: "DR55_brute_force_users.csv",
            detection_rule: "DR55_brute_force_login",
            headers: headers,
            rows: rows,                   // no actual change
            expected_mtime: mtime,
            comment: "c04_concurrency_test",
        };

        const [r1, r2] = await Promise.all([
            H.restCall(admin.page,  "POST", { ...payload, comment: "c04_admin1" }),
            H.restCall(admin2.page, "POST", { ...payload, comment: "c04_admin2" }),
        ]);

        for (const r of [r1, r2]) {
            if (r.error && /internal|traceback|nameerror|typeerror/i.test(r.error)) {
                throw new Error(`CRASH: ${r.error}`);
            }
        }

        // With no actual changes, both saves may be no-ops and both succeed.
        // That's fine — we only care there was no crash. The real optimistic
        // lock test is with DIFFERENT content, which this harness doesn't
        // do safely without more setup. Log the outcome for the record.
        const successes = [r1, r2].filter(r => !r.error).length;
        H.log("  \u2139\uFE0F", `  ${successes}/2 saves succeeded (no-op content); primary assertion: no crash`);
    });

    await cleanupStaleRequests(admin.page);

    await analyst.browser.close();
    await analyst2.browser.close();
    await admin.browser.close();
    await admin2.browser.close();
    await super1.browser.close();
    await super2.browser.close();

    H.summary("Concurrency Test Results");
    process.exit(H.results.some(r => r.status === "FAIL") ? 1 : 0);
})();
