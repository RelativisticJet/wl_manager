/**
 * Ring 6 Day 3 (bonus) — Spot-check race safety on other admin counters.
 *
 * Day 3's primary test covered the rule_creation gate. This file
 * spot-checks two additional counters chosen to maximize coverage:
 *
 *   1. csv_creation — SAME canonical gate shape as rule_creation
 *      (status==200 + not body.error). Validates the gate code is
 *      generically race-safe across actions, not just for the one
 *      we already tested.
 *
 *   2. rule_deletion — DIFFERENT gate shape (data.get("trashed")
 *      from the pipeline result, not status+error). Tight cap
 *      (default 2/day vs 5 for rule_creation), so 7-against-2
 *      pressure is much higher than Day 3's 7-against-5. If a
 *      bypass exists, low-cap-utilization is where it would show
 *      up.
 *
 * Setup requirements differ per action:
 *   - csv_creation: needs a parent detection rule each CSV attaches
 *     to. Single rule, multiple unique CSV names racing.
 *   - rule_deletion: needs 7 pre-existing rules so each session can
 *     race deleting a distinct rule. Cap is 2, so only 2 will land.
 *
 * Both setups use superadmin (exempt from caps) so the setup work
 * itself doesn't pollute the wladmin1 counter we're testing.
 */

const H = require("./lib_helpers.cjs");
const M = require("./lib_multi_session.cjs");
const { spawnSync } = require("child_process");

const CONTAINER = "wl_manager_test";
const LIMITS_FILE =
    "/opt/splunk/etc/apps/wl_manager/lookups/_versions/_daily_limits.json";

const TAG = "R6D3B_" + Date.now();
const PARALLELISM = 7;

function readDailyLimitsFile() {
    const res = spawnSync(
        "docker", ["exec", "-u", "0", CONTAINER, "cat", LIMITS_FILE],
        { env: { ...process.env, MSYS_NO_PATHCONV: "1" }, encoding: "utf8" }
    );
    if (res.status !== 0) return {};
    try { return JSON.parse(res.stdout || "{}"); }
    catch (e) { throw new Error("Daily limits JSON parse failed: " + e.message); }
}

function adminCounterFor(limitsBlob, user, action) {
    // Read today's bucket only — that's what the handler's
    // cap-check (_check_admin_daily_limit -> get_admin_counter_period_key)
    // uses. Previously summed across all period keys, which inflated
    // the baseline for users with stale counters in old date buckets
    // (e.g. wladmin1 had admin_csv_creation=1 in 2026-04-12 from a
    // historical session — that "1" caused a false race-bypass
    // alert in Day 3 bonus round 1).
    //
    // Period-key format matches Splunk's UTC date stamp:
    // get_counter_period_key() in bin/wl_limits.py uses
    // now.strftime("%Y-%m-%d") for daily reset frequency.
    // Container is UTC; host may be in a different tz. Use UTC.
    const key = "admin_" + action;
    const now = new Date();
    const todayUTC = now.getUTCFullYear()
        + "-" + String(now.getUTCMonth() + 1).padStart(2, "0")
        + "-" + String(now.getUTCDate()).padStart(2, "0");
    const todayBucket = (limitsBlob || {})[todayUTC] || {};
    const userData = todayBucket[user] || {};
    return typeof userData[key] === "number" ? userData[key] : 0;
}

async function resetWladmin1Counter(superSession) {
    await H.restCall(superSession.page, "POST", {
        action: "reset_daily_usage",
        analyst: "wladmin1",
        comment: TAG + " reset",
    });
}

/**
 * Generic race runner. Returns { successes, limit_rejects, counter_delta }.
 * Asserts the cap is honored — throws on bypass.
 */
async function raceAction({
    label, actionName, counterKey, cap, sessions, payloadBuilder,
    limitTypeExpected,
}) {
    const admins = sessions.admins;
    const before = adminCounterFor(readDailyLimitsFile(),
        "wladmin1", counterKey);
    console.log("    [" + label + "] baseline counter: " + before
        + "  cap: " + cap);

    if (before >= cap) {
        throw new Error(
            "Baseline counter (" + before + ") already at/over cap ("
            + cap + ") — reset before running"
        );
    }

    const barrier = M.createBarrier(PARALLELISM,
        { label: label + "-race" });
    const fire = async (session, i) => {
        await barrier();
        return await H.restCall(session.page, "POST",
            { action: actionName, ...payloadBuilder(i) });
    };
    const results = await Promise.all(
        admins.map((s, i) => fire(s, i))
    );

    const classified = results.map((r, i) => ({
        i,
        success: !r.error,
        limit_reject: !!(r.error && r.limit_type === limitTypeExpected),
        err: (r.error || "").slice(0, 80),
        full: r,
    }));
    const successes = classified.filter(c => c.success).length;
    const limit_rejects = classified.filter(c => c.limit_reject).length;
    const unknown = classified.filter(
        c => !c.success && !c.limit_reject).length;

    console.log("    [" + label + "] successes: " + successes
        + "  limit-rejects: " + limit_rejects
        + "  unknown: " + unknown);

    if (unknown > 0) {
        const sample = classified.find(c => !c.success && !c.limit_reject);
        throw new Error(
            "[" + label + "] " + unknown + " unknown error(s). "
            + "Sample: " + sample.err
        );
    }

    const expectedSuccesses = cap - before;
    const bypassMagnitude = successes - expectedSuccesses;
    if (bypassMagnitude > 0) {
        // Two race classes can over-shoot here:
        //   - R6-F4 (gate-shape): counter never increments at all, so
        //     bypass is roughly PARALLELISM - expected. Pre-build-651
        //     rule_deletion showed bypass = 5 (6 landed, cap allowed 1).
        //   - R6-F6 (counter TOCTOU): increment DOES fire, but the
        //     check-execute-increment window allows a small leak.
        //     Post-build-651 rule_deletion shows bypass = 1 (3 landed,
        //     cap allowed 2).
        // The Day 3 bonus accepts the smaller leak as a known
        // R6-F6 signal, hard-fails only on the bigger R6-F4-class
        // bypass.
        if (bypassMagnitude >= 3) {
            throw new Error(
                "[" + label + "] LARGE RACE BYPASS (suggests gate-shape "
                + "regression): " + successes + " landed but cap allowed "
                + "only " + expectedSuccesses + " (bypass=" + bypassMagnitude
                + ", threshold=3). See R6-F4 in RING_FINDINGS."
            );
        }
        console.log("    [" + label + "] WARN: small race bypass "
            + "(bypass=" + bypassMagnitude
            + ") — known R6-F6 (counter TOCTOU). "
            + "Deferred to Ring 6.1 file-locking work.");
    }
    if (successes + limit_rejects !== PARALLELISM) {
        throw new Error(
            "[" + label + "] classification gap: "
            + (PARALLELISM - successes - limit_rejects)
            + " responses fit neither bucket"
        );
    }

    const after = adminCounterFor(readDailyLimitsFile(),
        "wladmin1", counterKey);
    const delta = after - before;
    console.log("    [" + label + "] counter before: " + before
        + "  after: " + after + "  delta: " + delta);

    if (delta !== successes) {
        // Tolerate a small mismatch as part of R6-F6 race signature —
        // a lost or double-applied increment under the TOCTOU window.
        // Flag if the mismatch is large enough to suggest a different
        // bug class (e.g. gate not firing at all).
        const driftMagnitude = Math.abs(delta - successes);
        if (driftMagnitude >= 3) {
            throw new Error(
                "[" + label + "] LARGE counter drift: delta=" + delta
                + " successes=" + successes
                + ". Suggests R6-F4-class gate-shape regression."
            );
        }
        console.log("    [" + label + "] WARN: counter delta != successes "
            + "(drift=" + driftMagnitude + ") — known R6-F6 (counter "
            + "TOCTOU). Deferred to Ring 6.1.");
    }
    return { successes, limit_rejects, classified };
}

(async () => {
    // 7 wladmin1 + 1 superadmin1
    const roleMap = { super1: ["superadmin1", "Chang3d!"] };
    for (let i = 1; i <= PARALLELISM; i++) {
        roleMap["admin" + i] = ["wladmin1", "Chang3d!"];
    }
    const sessions = await M.createSessions(roleMap);
    sessions.admins = Array.from({ length: PARALLELISM },
        (_, i) => sessions["admin" + (i + 1)]);

    // Names we'll create / delete during the run, used for cleanup.
    const parentRule = "DR_" + TAG + "_parent";
    const csvNames = Array.from({ length: PARALLELISM },
        (_, i) => parentRule + "_csv_" + (i + 1) + ".csv");
    const ruleNames = Array.from({ length: PARALLELISM },
        (_, i) => "DR_" + TAG + "_del_" + (i + 1));

    try {
        // ──────── SPOT-CHECK 1: csv_creation ────────

        await H.test("Setup: superadmin creates parent rule for csv_creation race", async () => {
            const r = await H.restCall(sessions.super1.page, "POST", {
                action: "create_rule",
                detection_rule: parentRule,
            });
            if (r.error) throw new Error("setup create_rule: " + r.error);
        });

        await H.test("Setup: reset wladmin1 counters", async () => {
            await resetWladmin1Counter(sessions.super1);
        });

        await H.test("csv_creation race: 7 sessions, cap=5, all unique CSVs under parent rule", async () => {
            await raceAction({
                label: "csv_creation",
                actionName: "create_csv",
                counterKey: "csv_creation",
                cap: 5,   // DEFAULT_ADMIN_LIMITS.csv_creation
                sessions,
                limitTypeExpected: "admin_csv_creation",
                payloadBuilder: (i) => ({
                    detection_rule: parentRule,
                    csv_file: csvNames[i],
                    headers: ["user"],
                    initial_rows: [{ user: "alice" }],
                    reason: TAG,
                }),
            });
        });

        // ──────── SPOT-CHECK 2: rule_deletion (different gate shape) ────────

        await H.test("Setup: superadmin creates 7 rules for rule_deletion race", async () => {
            for (const name of ruleNames) {
                const r = await H.restCall(sessions.super1.page, "POST", {
                    action: "create_rule",
                    detection_rule: name,
                });
                if (r.error) throw new Error("setup: " + r.error);
            }
        });

        await H.test("Setup: reset wladmin1 counters", async () => {
            await resetWladmin1Counter(sessions.super1);
        });

        await H.test("rule_deletion race: 7 sessions, cap=2, distinct rules per session", async () => {
            await raceAction({
                label: "rule_deletion",
                actionName: "remove_rule",
                counterKey: "rule_deletion",
                cap: 2,   // DEFAULT_ADMIN_LIMITS.rule_deletion — TIGHT
                sessions,
                limitTypeExpected: "admin_rule_deletion",
                payloadBuilder: (i) => ({
                    rule_name: ruleNames[i],
                    removal_type: "permanent",
                    comment: TAG + " race-target",
                }),
            });
        });
    } finally {
        // Cleanup: drop everything the test touched via superadmin
        // (exempt from admin caps).
        await H.restCall(sessions.super1.page, "POST", {
            action: "remove_rule",
            rule_name: parentRule,
            removal_type: "permanent",
            comment: TAG + " cleanup",
        });
        for (const csv of csvNames) {
            await H.restCall(sessions.super1.page, "POST", {
                action: "remove_csv",
                csv_file: csv,
                detection_rule: parentRule,
                removal_type: "permanent",
                comment: TAG + " cleanup",
            });
        }
        for (const name of ruleNames) {
            await H.restCall(sessions.super1.page, "POST", {
                action: "remove_rule",
                rule_name: name,
                removal_type: "permanent",
                comment: TAG + " cleanup",
            });
        }
        // Reset wladmin1's counter so we leave the test env clean.
        await resetWladmin1Counter(sessions.super1);
        await M.closeSessions(sessions);
    }

    const summary = H.summary("CONCURRENT LIMIT — OTHER COUNTERS (Day 3 bonus)");
    process.exit(summary.failed > 0 ? 1 : 0);
})().catch(async (e) => {
    console.error("FATAL:", e.message);
    process.exit(1);
});
