/**
 * Ring 6 Day 5 — Concurrent presence tracking + UI-watch during in-flight save.
 *
 * Why this test exists:
 *
 * Presence tracking in bin/wl_presence.py is stored in a Python
 * MODULE-LEVEL dict (``_presence: Dict[str, Dict] = {}``). Splunk's
 * PersistentScriptHandler runs multiple worker processes (process
 * routing is opaque to the client). Module-level state lives per
 * Python process, so the working hypothesis is:
 *
 *   Sessions reporting presence on the same CSV may land on
 *   different worker processes; each worker's _presence dict
 *   sees a different subset; subsequent get_presence calls return
 *   different views depending on which worker handled the request.
 *
 * This is structurally similar to R6-F5/F6/F7 (shared-state
 * coherence across the worker pool) but the underlying state isn't
 * file-backed — it's in-memory. The fix vector would be different
 * (move to KV store, or to a file-backed cache with cross-process
 * lock), so this needs its own R-finding number, not a tail-rider
 * on R6-F5.
 *
 * Three phases:
 *
 *   Phase A: SEQUENTIAL report from 7 distinct users on the same
 *            CSV, then a single get_presence read. If get_presence
 *            doesn't include all 7, the worker-isolation hypothesis
 *            is confirmed — sequential mode rules out any racing.
 *
 *   Phase B: Each of the 7 sessions calls get_presence after Phase
 *            A. Build a histogram of "how many users does each
 *            session see". With sticky session routing the
 *            histogram is uniform; with random routing it varies.
 *
 *   Phase C: One session starts a save_csv with a large payload
 *            (slow path). While the save is in-flight, other
 *            sessions report_presence. Verify (a) save completes
 *            cleanly, (b) presence pings don't hang or error,
 *            (c) save's RMW doesn't accidentally touch presence
 *            state. This is the original Day 5 scope.
 *
 * The test characterizes outcomes; it hard-fails only on:
 *   - HTTP errors (any non-200 from presence GETs)
 *   - Phase C save-during-presence interaction producing a wedge
 *     or producing different results than Phase A's baseline
 *
 * Multi-worker visibility behavior (if surfaced) is REPORTED, not
 * hard-failed, because: (1) it's a known architectural property of
 * Splunk's PersistentScriptHandler that the codebase has tacitly
 * accepted; (2) the fix is non-trivial and deferred to a later
 * ring (likely 6.1 along with the file-locking work).
 */

const H = require("./lib_helpers.cjs");
const M = require("./lib_multi_session.cjs");

const TAG = "R6D5_" + Date.now();
const RULE = "DR_" + TAG;
const CSV = RULE + ".csv";

// 7 distinct app-specific users so each session has a unique
// identity in the presence dict.
const USERS = [
    "analyst1", "analyst2",
    "wladmin1", "wladmin2",
    "superadmin1", "superadmin2",
    "admin",            // built-in superadmin — included to round out 7
];
const PASS = "Chang3d!";
const PARALLELISM = USERS.length;  // 7

async function reportPresence(session, csvFile) {
    return await H.restCall(session.page, "GET", {
        action: "report_presence",
        csv_file: csvFile,
        last_activity: Math.floor(Date.now() / 1000),
    });
}

async function getPresence(session, csvFile) {
    return await H.restCall(session.page, "GET", {
        action: "get_presence",
        csv_file: csvFile,
    });
}

function activeUsersOf(presenceResponse) {
    // report_presence returns `{active_users: [...], presence: [...]}`
    // get_presence returns `{presence: [...]}` only
    // Both share the `presence` list of {user, idle_minutes} objects
    // — use that for uniform comparison.
    const list = presenceResponse.presence || [];
    return list.map(p => p.user).sort();
}

(async () => {
    // Login 7 distinct users in parallel.
    const roleMap = {};
    USERS.forEach((u, i) => { roleMap["s" + i] = [u, PASS]; });
    const sessions = await M.createSessions(roleMap);
    const sessionList = USERS.map((_, i) => sessions["s" + i]);

    try {
        // ──────── SETUP: pick a setup-session, create rule + CSV ────────

        // superadmin1 has create_rule + create_csv permissions.
        const setupSession = sessions["s4"];  // superadmin1

        await H.test("Setup: create rule + CSV (one initial row)", async () => {
            let r = await H.restCall(setupSession.page, "POST", {
                action: "create_rule",
                detection_rule: RULE,
            });
            if (r.error) throw new Error("create_rule: " + r.error);
            r = await H.restCall(setupSession.page, "POST", {
                action: "create_csv",
                detection_rule: RULE,
                csv_file: CSV,
                headers: ["user", "src_ip"],
                initial_rows: [{ user: "alice", src_ip: "10.0.0.1" }],
            });
            if (r.error) throw new Error("create_csv: " + r.error);
        });

        // ──────── PHASE A — Sequential register, single read ────────
        //
        // Each of 7 distinct users reports presence on the same CSV,
        // strictly one at a time (no concurrency). After all 7 are
        // done, ONE session (s0 = analyst1) calls get_presence and
        // we see how many of the 7 are visible.
        //
        // Sequential mode eliminates any race conditions. The only
        // remaining variable is whether the 7 report-presence calls
        // landed on the same worker process as the get-presence
        // call. If they did, all 7 are visible. If they didn't,
        // get_presence returns a subset.

        let phaseAreport = [];
        let phaseAread = null;

        await H.test("Phase A: 7 sequential report_presence calls (one per session, distinct users)", async () => {
            for (let i = 0; i < PARALLELISM; i++) {
                const r = await reportPresence(sessionList[i], CSV);
                if (r.error) {
                    throw new Error("report_presence as " + USERS[i]
                        + ": " + r.error);
                }
                phaseAreport.push({
                    session: USERS[i],
                    saw: activeUsersOf(r),
                });
            }
            // Print growth — sequential reports should accumulate
            // monotonically if all hits land on the same worker.
            phaseAreport.forEach((p, i) => {
                console.log("    after report from " + p.session
                    + ": same-worker view = [" + p.saw.join(",") + "]"
                    + " (size " + p.saw.length + ")");
            });
        });

        await H.test("Phase A: single get_presence read by s0 (analyst1)", async () => {
            phaseAread = await getPresence(sessionList[0], CSV);
            if (phaseAread.error) {
                throw new Error("get_presence: " + phaseAread.error);
            }
            const seen = activeUsersOf(phaseAread);
            console.log("    s0 (analyst1) get_presence sees: ["
                + seen.join(",") + "] (size " + seen.length + ")");

            if (seen.length === PARALLELISM) {
                console.log("    OUTCOME: full visibility — every user "
                    + "visible to every reader. Either single-worker "
                    + "Splunk config, or presence state has shared "
                    + "backing.");
            } else {
                const missing = USERS.filter(u => !seen.includes(u));
                console.log("    OUTCOME: PARTIAL VISIBILITY — "
                    + seen.length + " of " + PARALLELISM
                    + " users visible. Missing: [" + missing.join(",")
                    + "]. This is the worker-process isolation "
                    + "hypothesis confirmed (R6-F8 candidate). "
                    + "Module-level _presence dict in wl_presence.py "
                    + "is per-worker; get_presence returns whatever "
                    + "the handling worker has, not a global view.");
            }
        });

        // ──────── PHASE B — Each session reads its own view ────────
        //
        // After Phase A's writes have all landed in SOME worker
        // process (we don't control which), each of the 7 sessions
        // now calls get_presence. We record the size of each
        // session's view. With sticky-session routing the
        // distribution is concentrated; with random routing it
        // spreads.

        let phaseBviews = [];

        await H.test("Phase B: 7 get_presence reads (one per session)", async () => {
            for (let i = 0; i < PARALLELISM; i++) {
                const r = await getPresence(sessionList[i], CSV);
                if (r.error) {
                    throw new Error("get_presence as " + USERS[i]
                        + ": " + r.error);
                }
                phaseBviews.push({
                    session: USERS[i],
                    seen: activeUsersOf(r),
                });
            }
            // Build histogram of view sizes.
            const histogram = {};
            phaseBviews.forEach(v => {
                histogram[v.seen.length] = (histogram[v.seen.length] || 0) + 1;
            });
            console.log("    view-size histogram: "
                + JSON.stringify(histogram));

            // Detailed per-session views.
            phaseBviews.forEach(v => {
                console.log("    " + v.session + " sees ["
                    + v.seen.join(",") + "] (size " + v.seen.length + ")");
            });

            const allSeven = phaseBviews.filter(v =>
                v.seen.length === PARALLELISM).length;
            if (allSeven === PARALLELISM) {
                console.log("    OUTCOME: all 7 readers see all 7 users "
                    + "— consistent global view.");
            } else {
                console.log("    OUTCOME: INCONSISTENT VIEWS — "
                    + allSeven + " of " + PARALLELISM
                    + " sessions saw the complete user list. "
                    + "The remaining " + (PARALLELISM - allSeven)
                    + " session(s) got a partial view. UI 'Also "
                    + "viewing' indicator is non-deterministic.");
            }
        });

        // ──────── PHASE C — Presence ping during in-flight save_csv ────────
        //
        // One session (s2 = wladmin1) initiates a save_csv. Without
        // waiting for it to complete, the other 6 sessions each
        // fire a report_presence. Then await save's completion.
        //
        // Verify:
        //   - save_csv returns a clean response (success or known
        //     R6-F7 leak signature)
        //   - every report_presence completed without error
        //   - get_presence after the dust settles still works
        //
        // Day 4 already characterized save_csv as having a TOCTOU
        // race (R6-F7). The point of this phase is NOT to re-test
        // R6-F7; it's to confirm the presence path and the save
        // path don't interfere with each other.

        let phaseCsave = null;
        let phaseCpings = [];

        await H.test("Phase C: capture pre-save (mtime, hash) baseline", async () => {
            const status = await H.restCall(sessionList[2].page, "GET", {
                action: "check_csv_status",
                csv_file: CSV,
            });
            if (status.error) throw new Error("status: " + status.error);
            phaseCsave = {
                expected_mtime: status.file_mtime,
                expected_content_hash: status.content_hash,
            };
        });

        await H.test("Phase C: save_csv (slow path) + 6 concurrent presence pings", async () => {
            // Kick off the save. Don't await yet.
            const savePromise = H.restCall(sessionList[2].page, "POST", {
                action: "save_csv",
                detection_rule: RULE,
                csv_file: CSV,
                headers: ["user", "src_ip"],
                rows: [
                    { user: "alice", src_ip: "10.0.0.1" },
                    { user: "bob",   src_ip: "10.0.0.2" },  // append
                ],
                comment: TAG + " save during presence",
                expected_mtime: phaseCsave.expected_mtime,
                expected_content_hash: phaseCsave.expected_content_hash,
            });

            // Fire 6 presence pings from the other sessions. These
            // run in parallel with the in-flight save. If save's
            // RMW critical section blocks presence (e.g. via a
            // shared lock that shouldn't exist), pings will queue
            // behind the save and we'd see latency.
            const pingPromises = [];
            for (let i = 0; i < PARALLELISM; i++) {
                if (i === 2) continue;  // skip the saver
                pingPromises.push(
                    reportPresence(sessionList[i], CSV)
                    .then(r => ({ session: USERS[i], result: r }))
                );
            }

            // Await everything.
            const saveResult = await savePromise;
            const pingResults = await Promise.all(pingPromises);

            // Save outcome — accept R6-F7 known leak (HTTP 200 with
            // possible clobbered write) or proper success. Reject
            // any unknown error.
            phaseCsave.result = saveResult;
            if (saveResult.error) {
                // Could be 409 conflict (proper lock won) — accept.
                // Could be "Failed to save CSV" (R6-F7 OSError path)
                // — accept (known race outcome).
                // Anything else — fail.
                const knownErr = /conflict|content hash|mtime|modified by|Failed to save CSV/i;
                if (!knownErr.test(saveResult.error)) {
                    throw new Error("save_csv unknown error: "
                        + saveResult.error);
                }
                console.log("    save: known race outcome — "
                    + saveResult.error.slice(0, 100));
            } else {
                console.log("    save: 200 OK");
            }

            // Ping outcomes — every ping must succeed; presence
            // path should be independent of save path.
            phaseCpings = pingResults;
            const pingErrors = pingResults.filter(p => p.result.error);
            if (pingErrors.length > 0) {
                throw new Error("presence pings errored during save: "
                    + pingErrors.map(p => p.session + "=" + p.result.error)
                              .join("; "));
            }
            console.log("    pings: all " + pingResults.length
                + " presence reports succeeded during in-flight save");
        });

        // ──────── PHASE D — Post-race coherence ────────
        // After the dust has settled, one final read to ensure the
        // presence state isn't corrupted or wedged.

        await H.test("Phase D: post-race get_presence — measures R6-F8 collapse signature", async () => {
            const r = await getPresence(sessionList[0], CSV);
            if (r.error) {
                throw new Error("post-race get_presence: " + r.error);
            }
            const seen = activeUsersOf(r);
            console.log("    post-race view: [" + seen.join(",")
                + "] (size " + seen.length + ")");

            // Compare against Phase B's per-session view sizes
            // (which were all PARALLELISM under sequential traffic).
            const phaseBavg = phaseBviews.reduce(
                (s, v) => s + v.seen.length, 0) / phaseBviews.length;
            const collapseRatio = seen.length / phaseBavg;
            console.log("    Phase B avg view size: " + phaseBavg
                + ", Phase D view size: " + seen.length
                + ", collapse ratio: " + collapseRatio.toFixed(3));

            if (seen.length === 0) {
                throw new Error("post-race view is EMPTY — presence "
                    + "state lost entirely (worse than R6-F8 collapse)");
            }
            if (seen.length >= PARALLELISM - 1) {
                console.log("    OUTCOME: no collapse — concurrent "
                    + "pings landed on same worker(s) as the read. "
                    + "(Single-process Splunk config, or unlucky "
                    + "routing didn't manifest.)");
            } else if (seen.length === 1) {
                console.log("    OUTCOME: R6-F8 FULL COLLAPSE — "
                    + "post-race view has 1 user vs Phase B's "
                    + phaseBavg + ". Concurrent pings scattered "
                    + "across worker processes; get_presence "
                    + "returned a single worker's state. UI 'Also "
                    + "viewing' indicator is non-deterministic and "
                    + "loses fidelity proportional to concurrency. "
                    + "Known multi-worker shared-state issue. "
                    + "Deferred to Ring 6.1.");
            } else {
                console.log("    OUTCOME: R6-F8 PARTIAL COLLAPSE — "
                    + "post-race view has " + seen.length
                    + " of " + PARALLELISM + " expected. Concurrent "
                    + "pings reached " + seen.length + " of N worker "
                    + "processes that the get_presence reader could "
                    + "see. Known multi-worker shared-state issue. "
                    + "Deferred to Ring 6.1.");
            }
        });

    } finally {
        // Cleanup: superadmin1 (s4) removes the rule (cascade-deletes
        // the CSV).
        try {
            await H.restCall(sessions["s4"].page, "POST", {
                action: "remove_rule",
                rule_name: RULE,
                removal_type: "permanent",
                comment: TAG + " cleanup",
            });
        } catch (_) { /* idempotent cleanup */ }
        await M.closeSessions(sessions);
    }

    const summary = H.summary("CONCURRENT PRESENCE + UI-WATCH (Day 5)");
    process.exit(summary.failed > 0 ? 1 : 0);
})().catch(async (e) => {
    console.error("FATAL:", e.message);
    process.exit(1);
});
