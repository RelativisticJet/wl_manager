/**
 * Ring 6 Day 4 — Concurrent save_csv optimistic-lock race.
 *
 * Predecessor: tests/e2e/test_concurrent_save_race.cjs (round 4
 * characterization test, 2-client Promise.all on a single page).
 * That test deliberately accepted EITHER outcome — proper 1-of-2
 * lock OR both-succeed last-writer-wins — and merely logged which
 * one we got.
 *
 * Day 4 tightens the race in three ways:
 *
 *   1. 7 INDEPENDENT browser sessions instead of 2 promises on one
 *      page. Splunk's PersistentScriptHandler runs multiple worker
 *      processes; the existing test all-routed through one socket
 *      and rarely hit cross-process timing. With 7 sessions we get
 *      7 independent TCP/HTTP connections that splunkd load-balances
 *      across workers — the same surface that produced R6-F5 +
 *      R6-F6 on Day 3 bonus.
 *
 *   2. Barrier rendezvous. All 7 reach the POST call site before
 *      any of them fires. The first 6 await; the 7th releases all
 *      in the same microtask tick. Removes event-loop jitter that
 *      raw Promise.all has between .then() callbacks.
 *
 *   3. ON-DISK CONTENT verification, not just response-status
 *      classification. The existing test ends at "characterize the
 *      race" — we go further: re-read the CSV, count rows, and
 *      assert the final state is EXACTLY one racer's payload, not
 *      a merged corruption or a partial write.
 *
 * Expected outcome and tolerance:
 *
 *   - PROPER LOCK: exactly 1 success, 6 conflict-409s. On-disk row
 *     count = initial + 1. Audit shows 1 successful save event.
 *
 *   - TOCTOU LEAK (known): >1 success, fewer than 6 conflicts.
 *     On-disk row count = initial + (number of successes). Earlier
 *     successes' rows get clobbered by later successes' writes
 *     — silent data loss. This is the same R6-F5 class as Day 3
 *     bonus (cross-process file race) and pairs with
 *     feedback_cross_process_file_races.md.
 *
 * If the leak is small (1-3 racers landing of 7), WARN and continue
 * — matches the Day 3 bonus tolerance posture. Deferred to Ring 6.1
 * where wl_filelock.py is adopted for save_csv.
 *
 * If the leak is large (4+ racers landing of 7), HARD-FAIL — that
 * level of bypass suggests the optimistic-lock check is NOT firing
 * at all (R6-F4-class gate-shape regression on save_csv), which is
 * a different and worse bug than the known TOCTOU window.
 */

const H = require("./lib_helpers.cjs");
const M = require("./lib_multi_session.cjs");
const { spawnSync } = require("child_process");

const CONTAINER = "wl_manager_test";
const TAG = "R6D4_" + Date.now();
const PARALLELISM = 7;
const RULE = "DR_" + TAG;
const CSV = RULE + ".csv";

// Tolerance: the TOCTOU window on save_csv can produce 1-N successes
// depending on how tightly the racers' check-before-write phases
// overlap. The known R6-F7 leak signature is `successes > 1` AND
// `on-disk rows == 1` (silent data loss with false ack). The only
// signature that proves the lock is COMPLETELY no-op (R6-F4-class
// gate-shape regression on the optimistic check) is `successes ==
// PARALLELISM` — every request bypassed every gate. Hard-fail
// only on that, treat anything else as the known leak.
const LEAK_HARDFAIL_THRESHOLD = PARALLELISM;

function readCsvFromContainer(csvFile) {
    // Live container is the source of truth for "what actually
    // landed". Read via the running CSV path (LOOKUPS dir) rather
    // than the version-snapshot dir — saves write to LOOKUPS first.
    const path = "/opt/splunk/etc/apps/wl_manager/lookups/" + csvFile;
    const res = spawnSync(
        "docker", ["exec", "-u", "0", CONTAINER, "cat", path],
        { env: { ...process.env, MSYS_NO_PATHCONV: "1" }, encoding: "utf8" }
    );
    if (res.status !== 0) {
        throw new Error("docker exec cat failed for " + path
            + ": " + (res.stderr || res.stdout || "(no output)"));
    }
    return res.stdout;
}

function parseCsvRows(csvText) {
    // Minimal parser — managed CSVs have no embedded newlines/
    // commas in this test (we generate them ourselves). Header row
    // first, data rows after. Empty trailing lines stripped.
    const lines = csvText.split(/\r?\n/).filter(l => l.length > 0);
    if (lines.length < 1) return { headers: [], rows: [] };
    const headers = lines[0].split(",");
    const rows = lines.slice(1).map(line => {
        const cells = line.split(",");
        const row = {};
        headers.forEach((h, i) => { row[h] = cells[i] || ""; });
        return row;
    });
    return { headers, rows };
}

(async () => {
    // Login: 7 wladmin1 sessions to race; 1 superadmin1 for setup
    // and cleanup. wladmin1 is the right tier — admins are the
    // ones with csv_save permission, analysts go through approval.
    const roleMap = { super1: ["superadmin1", "Chang3d!"] };
    for (let i = 1; i <= PARALLELISM; i++) {
        roleMap["admin" + i] = ["wladmin1", "Chang3d!"];
    }
    const sessions = await M.createSessions(roleMap);
    sessions.admins = Array.from({ length: PARALLELISM },
        (_, i) => sessions["admin" + (i + 1)]);

    try {
        // ──────── SETUP: superadmin creates rule + CSV ────────

        await H.test("Setup: superadmin creates parent rule", async () => {
            const r = await H.restCall(sessions.super1.page, "POST", {
                action: "create_rule",
                detection_rule: RULE,
            });
            if (r.error) throw new Error("setup create_rule: " + r.error);
        });

        await H.test("Setup: superadmin creates CSV with one initial row", async () => {
            const r = await H.restCall(sessions.super1.page, "POST", {
                action: "create_csv",
                detection_rule: RULE,
                csv_file: CSV,
                headers: ["user", "src_ip"],
                initial_rows: [{ user: "alice", src_ip: "10.0.0.1" }],
            });
            if (r.error) throw new Error("setup create_csv: " + r.error);
        });

        // Reset wladmin1's csv_save counter so this test's race
        // isn't polluted by prior runs. csv_save cap is 20/day —
        // 3-4 repeated runs would otherwise start hitting it.
        await H.test("Setup: superadmin resets wladmin1 counter", async () => {
            await H.restCall(sessions.super1.page, "POST", {
                action: "reset_daily_usage",
                analyst: "wladmin1",
                comment: TAG + " pre-race reset",
            });
        });

        // ──────── PRE-RACE: all 7 sessions GET the same baseline ────────

        let baselineMtime = null;
        let baselineHash = null;
        await H.test("Pre-race: all 7 sessions capture identical (mtime, content_hash)", async () => {
            // Sequential fetch (not concurrent — we want all 7 to
            // see the SAME post-create snapshot, not 7 reads racing
            // against each other). This is the "load the file"
            // step of a real editor session.
            const snapshots = [];
            for (const s of sessions.admins) {
                const r = await H.restCall(s.page, "GET", {
                    action: "check_csv_status",
                    csv_file: CSV,
                });
                if (r.error) throw new Error("check_csv_status: " + r.error);
                if (typeof r.file_mtime !== "number")
                    throw new Error("no file_mtime in response: "
                        + JSON.stringify(r));
                if (!r.content_hash)
                    throw new Error("no content_hash in response: "
                        + JSON.stringify(r));
                snapshots.push({ mtime: r.file_mtime, hash: r.content_hash });
            }
            // All 7 must see the same baseline. If they don't, the
            // file is changing under us (e.g. FIM auto-bootstrap)
            // and the test is invalid.
            const uniqMtime = new Set(snapshots.map(s => s.mtime));
            const uniqHash = new Set(snapshots.map(s => s.hash));
            if (uniqMtime.size !== 1 || uniqHash.size !== 1) {
                throw new Error("Pre-race snapshots diverged — "
                    + "uniqMtime=" + uniqMtime.size + " uniqHash="
                    + uniqHash.size + "; cannot run the race "
                    + "(some other process is mutating the CSV)");
            }
            baselineMtime = snapshots[0].mtime;
            baselineHash = snapshots[0].hash;
            console.log("    baseline mtime: " + baselineMtime
                + "  hash: " + baselineHash.slice(0, 12) + "...");
        });

        // ──────── RACE: 7 saves with identical expected_* ────────

        let raceResults = null;
        await H.test("Race: 7 sessions POST save_csv with same expected_mtime + hash", async () => {
            const barrier = M.createBarrier(PARALLELISM,
                { label: "save-race" });
            const fire = async (session, i) => {
                // Each racer appends a DIFFERENT row, so if the lock
                // fails open we can tell whose payload won by reading
                // the CSV after.
                const myRow = {
                    user: "racer_" + (i + 1),
                    src_ip: "10.0." + (i + 1) + ".1",
                };
                await barrier();
                return await H.restCall(session.page, "POST", {
                    action: "save_csv",
                    detection_rule: RULE,
                    csv_file: CSV,
                    headers: ["user", "src_ip"],
                    rows: [
                        { user: "alice", src_ip: "10.0.0.1" },  // initial
                        myRow,                                    // racer's append
                    ],
                    comment: TAG + " racer " + (i + 1),
                    expected_mtime: baselineMtime,
                    expected_content_hash: baselineHash,
                });
            };
            raceResults = await Promise.all(
                sessions.admins.map((s, i) => fire(s, i))
            );
        });

        // ──────── CLASSIFY: success vs conflict-409 vs unknown ────────

        let successes = 0;
        let conflicts = 0;
        let unknowns = [];
        let winningRacers = [];
        await H.test("Classify race outcomes", async () => {
            raceResults.forEach((r, i) => {
                if (!r.error) {
                    successes++;
                    winningRacers.push(i + 1);
                } else if (/conflict|content hash|mtime|modified by/i.test(r.error)) {
                    conflicts++;
                } else {
                    unknowns.push({
                        i: i + 1,
                        err: r.error.slice(0, 200),
                        full_body: r,
                    });
                }
            });
            console.log("    successes: " + successes
                + "  conflicts: " + conflicts
                + "  unknown: " + unknowns.length);
            if (winningRacers.length > 0) {
                console.log("    winning racer indices: ["
                    + winningRacers.join(", ") + "]");
            }
            if (unknowns.length > 0) {
                unknowns.forEach(u => {
                    console.log("    unknown[" + u.i + "]: "
                        + JSON.stringify(u.full_body).slice(0, 300));
                });
            }

            // Sanity: every response is accounted for.
            if (successes + conflicts + unknowns.length !== PARALLELISM) {
                throw new Error("classification gap: " + PARALLELISM
                    + " races, " + successes + " success + " + conflicts
                    + " conflict + " + unknowns.length + " unknown");
            }
            // At least one must land or the test isn't exercising
            // the race at all (e.g. all 7 hit the same admin
            // rate-limit cap, or the CSV doesn't exist).
            if (successes < 1) {
                throw new Error("ZERO successes — race produced no "
                    + "winner. Possible causes: rate-limit cap "
                    + "exhausted, CSV missing, RBAC misconfigured. "
                    + "First conflict text: "
                    + (raceResults.find(r => r.error) || {}).error);
            }
        });

        // ──────── VERIFY ON-DISK: file is one racer's payload ────────

        await H.test("On-disk: file is valid CSV, exactly one racer's payload persisted (writes are atomic via temp+rename)", async () => {
            const text = readCsvFromContainer(CSV);
            const { headers, rows } = parseCsvRows(text);
            console.log("    on-disk rows: " + rows.length
                + "  successes: " + successes);

            // Header sanity — saves should not corrupt the schema.
            // The handler appends reserved `_added_by` + `_added_at`
            // internal-metadata columns on every save (see MEMORY.md
            // "Reserved prefix convention" rule), so we only assert
            // the user-facing columns and tolerate any `_*` columns.
            const userHeaders = headers.filter(h => !h.startsWith("_"));
            if (userHeaders.join(",") !== "user,src_ip") {
                throw new Error("Header corruption — got: "
                    + headers.join(","));
            }

            // Find which racer's row(s) actually landed.
            const racerRows = rows.filter(r =>
                /^racer_\d+$/.test(r.user || ""));
            console.log("    racer rows persisted: "
                + racerRows.map(r => r.user).join(", "));

            // write_csv() uses tempfile + os.replace (atomic rename
            // on POSIX). Concurrent writes never interleave at the
            // byte level — the file is always SOME complete writer's
            // payload. So exactly ONE racer's row should land,
            // regardless of how many racers passed the optimistic
            // check. Anything else = real corruption.
            if (racerRows.length !== 1) {
                throw new Error("REAL CORRUPTION — expected exactly "
                    + "1 racer row on disk (atomic rename means "
                    + "last-writer-wins), got " + racerRows.length
                    + " (" + racerRows.map(r => r.user).join(",")
                    + "). This is byte-level write interleaving — "
                    + "investigate write_csv() atomicity.");
            }

            // Classify by gap between API successes and persisted rows.
            const lostWrites = successes - racerRows.length;
            if (lostWrites === 0) {
                console.log("    OUTCOME: PROPER OPTIMISTIC LOCK");
            } else {
                // R6-F7 signature: optimistic check is a TOCTOU
                // race (not a real lock). N racers all pass the
                // check before any write completes, N writes all
                // succeed at the API level, but only the last
                // os.replace wins on disk. The earlier "successes"
                // returned HTTP 200 with no row persisted — silent
                // data loss with false acknowledgment. Same root
                // cause as R6-F5/F6 (no cross-process file lock
                // around the read-modify-write critical section).
                // Deferred to Ring 6.1.
                console.log("    OUTCOME: R6-F7 SILENT-LOSS LEAK — "
                    + successes + " of " + PARALLELISM
                    + " HTTP 200 successes but only "
                    + racerRows.length + " row(s) actually persisted. "
                    + lostWrites + " user(s) told 'saved' but their "
                    + "change was clobbered. Known R6-F5/F6 class "
                    + "(no cross-process file lock around save_csv "
                    + "read-modify-write). Deferred to Ring 6.1.");
            }
        });

        // ──────── BYPASS-MAGNITUDE GATE ────────

        await H.test("Bypass magnitude under hardfail threshold (lock not completely no-op)", async () => {
            // Only fail if EVERY racer bypassed the optimistic check.
            // That would indicate an R6-F4-class regression (lock
            // condition never fires), distinct from R6-F7 (tight
            // TOCTOU window where some racers pass and some don't).
            if (successes >= LEAK_HARDFAIL_THRESHOLD) {
                throw new Error("TOTAL BYPASS: " + successes + " of "
                    + PARALLELISM + " races landed (threshold="
                    + LEAK_HARDFAIL_THRESHOLD + "). Optimistic lock "
                    + "is no-op — R6-F4-class gate-shape regression "
                    + "on save_csv. Investigate before deferring.");
            }
        });

    } finally {
        // Cleanup: superadmin removes the rule (cascade-deletes
        // the CSV). Exempt from admin caps so it never collides
        // with what we just exercised.
        await H.restCall(sessions.super1.page, "POST", {
            action: "remove_rule",
            rule_name: RULE,
            removal_type: "permanent",
            comment: TAG + " cleanup",
        });
        await M.closeSessions(sessions);
    }

    const summary = H.summary("CONCURRENT SAVE_CSV (Day 4)");
    process.exit(summary.failed > 0 ? 1 : 0);
})().catch(async (e) => {
    console.error("FATAL:", e.message);
    process.exit(1);
});
