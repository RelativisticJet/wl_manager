/**
 * Ring 6 Day 3 — Concurrent rate-limit consumption (TOCTOU race test).
 *
 * Tests whether the admin rule_creation daily rate-limit gate
 * is safe under simultaneous racing requests, OR whether it
 * has a Time-of-Check-Time-of-Use window that lets multiple
 * requests bypass the cap.
 *
 * Pre-fix context: this test was IMPOSSIBLE to write meaningfully
 * before R6-F2 (build 649) because the counter never incremented
 * at all — every request would have passed regardless of the cap.
 * Now that the increment fires correctly, the next-class question
 * is whether the read-check-execute-increment sequence is atomic
 * across parallel processes.
 *
 * The race target:
 *   - wladmin1 (regular admin, subject to rule_creation cap of 5/day)
 *   - 7 parallel browser sessions
 *   - Each submits create_rule with a unique name at a barrier-released tick
 *
 * Plan diverges from the original Ring 6 plan (which said "one
 * analyst with daily limit N=5") because:
 *   - Analyst create_rule path returns 403 or routes to approval
 *     queue, neither of which exercises a counter rate-limit.
 *   - Admin create_rule path has the actual counter race we want
 *     to test, and the rate-limit (5/day) is the default.
 *
 * Expected behaviour (if the gate is correctly serialized):
 *   - exactly 5 successes + 2 rejections
 *   - counter delta == 5 (matches success count)
 *   - all 2 rejections carry the limit_type=admin_rule_creation error shape
 *
 * Failure modes that would be caught:
 *   - successes > 5: RACE BYPASS — the check-execute-increment
 *     sequence is not atomic; multiple workers read counter=N,
 *     all pass the (N+1)<=max check, all execute, all increment.
 *     This is the canonical TOCTOU on a rate-limit counter.
 *   - successes < 5: UNDER-CHARGE / non-race failure (login
 *     timeout, validation error). Investigated, not auto-failed.
 *   - counter delta != successes: counter-write race that
 *     loses an increment, or a double-counted one.
 *   - rejection error shape doesn't match
 *     limit_type=admin_rule_creation: the rejection is happening
 *     for the wrong reason (e.g. ascii validation, role check).
 *
 * Cleanup: superadmin1 deletes whatever rules actually landed.
 * Superadmin is exempt from admin_rule_creation cap so cleanup
 * never blocks on the rate-limit.
 */

const H = require("./lib_helpers.cjs");
const M = require("./lib_multi_session.cjs");
const { spawnSync } = require("child_process");

const CONTAINER = "wl_manager_test";
const LIMITS_FILE =
    "/opt/splunk/etc/apps/wl_manager/lookups/_versions/_daily_limits.json";

const TAG = "R6D3_" + Date.now();
const PARALLELISM = 7;
const RULE_LIMIT = 5;   // default admin rule_creation cap (DEFAULT_ADMIN_LIMITS)

function readDailyLimitsFile() {
    const res = spawnSync(
        "docker", ["exec", "-u", "0", CONTAINER, "cat", LIMITS_FILE],
        { env: { ...process.env, MSYS_NO_PATHCONV: "1" }, encoding: "utf8" }
    );
    if (res.status !== 0) return {};
    try { return JSON.parse(res.stdout || "{}"); }
    catch (e) {
        throw new Error("Daily limits JSON parse failed: " + e.message);
    }
}

/**
 * Read admin_<action> counter from TODAY's bucket only. The handler's
 * cap-check (get_admin_counter_period_key in bin/wl_limits.py) uses
 * the current UTC date as the period key under daily reset frequency;
 * old buckets from prior date keys are not counted toward the cap.
 *
 * Previous version of this helper summed across all periods, which
 * caused false race-bypass alerts when wladmin1 had stale counters
 * from a different date bucket (Day 3 bonus round 1, 2026-05-12).
 */
function adminCounterFor(limitsBlob, user, action) {
    const key = "admin_" + action;
    const now = new Date();
    const todayUTC = now.getUTCFullYear()
        + "-" + String(now.getUTCMonth() + 1).padStart(2, "0")
        + "-" + String(now.getUTCDate()).padStart(2, "0");
    const todayBucket = (limitsBlob || {})[todayUTC] || {};
    const userData = todayBucket[user] || {};
    return typeof userData[key] === "number" ? userData[key] : 0;
}

(async () => {
    // 7 wladmin1 sessions (same user, different browser contexts =
    // different cookies = independent Splunk session keys).
    const roleMap = {};
    for (let i = 1; i <= PARALLELISM; i++) {
        roleMap["admin" + i] = ["wladmin1", "Chang3d!"];
    }
    roleMap["super1"] = ["superadmin1", "Chang3d!"];

    const sessions = await M.createSessions(roleMap);
    const admins = Array.from({ length: PARALLELISM },
        (_, i) => sessions["admin" + (i + 1)]);

    // Generate 7 unique rule names so the race target is per-session.
    const ruleNames = Array.from({ length: PARALLELISM },
        (_, i) => `DR_${TAG}_${i + 1}`);

    let counterBefore = 0;
    let counterAfter = 0;
    let results = [];

    try {
        await H.test("Capture baseline admin_rule_creation counter for wladmin1", async () => {
            const blob = readDailyLimitsFile();
            counterBefore = adminCounterFor(blob, "wladmin1", "rule_creation");
            console.log("    baseline counter: " + counterBefore
                + " (admin cap: " + RULE_LIMIT + ")");
            if (counterBefore >= RULE_LIMIT) {
                throw new Error(
                    "Baseline counter (" + counterBefore + ") already at/over cap ("
                    + RULE_LIMIT + ") — earlier work consumed the budget. Reset "
                    + "_daily_limits.json for wladmin1 admin_rule_creation before "
                    + "re-running, e.g. via reset_daily_usage as superadmin2."
                );
            }
        });

        await H.test("RACE: " + PARALLELISM + " wladmin1 sessions call create_rule simultaneously", async () => {
            const barrier = M.createBarrier(PARALLELISM,
                { label: "create-rule-race" });
            const fire = async (session, ruleName) => {
                await barrier();
                return await H.restCall(session.page, "POST", {
                    action: "create_rule",
                    detection_rule: ruleName,
                });
            };
            results = await Promise.all(
                admins.map((s, i) => fire(s, ruleNames[i]))
            );

            // Triage each response: success vs limit-reject vs other.
            const classified = results.map((r, i) => {
                const isSuccess = !r.error;
                const isLimitReject = r.error
                    && r.limit_type === "admin_rule_creation";
                const isUnknownError = r.error && !isLimitReject;
                return {
                    rule: ruleNames[i],
                    success: isSuccess,
                    limit_reject: !!isLimitReject,
                    unknown_error: !!isUnknownError,
                    err: (r.error || "").slice(0, 80),
                };
            });
            const successes = classified.filter(c => c.success).length;
            const limitRejects = classified.filter(c => c.limit_reject).length;
            const unknownErrors = classified.filter(c => c.unknown_error).length;
            console.log("    successes: " + successes
                + "  limit-rejects: " + limitRejects
                + "  unknown errors: " + unknownErrors);
            for (const c of classified) {
                console.log("      " + c.rule + ": "
                    + (c.success ? "OK" : c.err));
            }

            // Hard-fail conditions.
            if (unknownErrors > 0) {
                throw new Error(
                    unknownErrors + " request(s) failed with non-limit error. "
                    + "Sample: " + classified.find(c => c.unknown_error).err
                );
            }
            const expectedSuccesses = RULE_LIMIT - counterBefore;
            if (successes > expectedSuccesses) {
                throw new Error(
                    "RACE BYPASS: " + successes + " requests landed but only "
                    + expectedSuccesses + " were allowed by the cap. "
                    + "Counter race in admin_rule_creation gate."
                );
            }
            if (successes + limitRejects !== PARALLELISM) {
                throw new Error(
                    "Response classification gap: "
                    + (PARALLELISM - successes - limitRejects)
                    + " responses fit neither success nor limit-reject."
                );
            }
            // Stash counts for the post-race counter assertion below.
            classified.successes = successes;
            classified.limitRejects = limitRejects;
            results.classified = classified;
        });

        await H.test("Counter delta matches success count (no double or lost charges)", async () => {
            const blob = readDailyLimitsFile();
            counterAfter = adminCounterFor(blob, "wladmin1", "rule_creation");
            const delta = counterAfter - counterBefore;
            const successes = results.classified.successes;
            console.log("    counter before: " + counterBefore
                + "  after: " + counterAfter
                + "  delta: " + delta
                + "  successes: " + successes);
            if (delta !== successes) {
                throw new Error(
                    "Counter delta (" + delta + ") != success count ("
                    + successes + "). Counter-write race: an increment was "
                    + "lost or double-applied."
                );
            }
        });

        await H.test("Counter is now exactly at the cap (or below if baseline > 0)", async () => {
            // If we started at counterBefore=0 and cap=5, we should be
            // at exactly 5 now (5 of 7 landed, 2 limited). If we started
            // higher, we should be at the cap.
            const expected = Math.min(counterBefore + PARALLELISM, RULE_LIMIT);
            if (counterAfter !== expected) {
                throw new Error(
                    "Counter after race is " + counterAfter
                    + ", expected " + expected
                    + " (min(before+parallelism, cap))."
                );
            }
            console.log("    counter at cap as expected: " + counterAfter);
        });

        await H.test("Limit-reject responses carry the correct error shape", async () => {
            const rejects = results.filter(r => r.error);
            for (const r of rejects) {
                if (r.limit_type !== "admin_rule_creation") {
                    throw new Error(
                        "Rejection has wrong limit_type: "
                        + JSON.stringify(r).slice(0, 200)
                    );
                }
                if (typeof r.current !== "number"
                        || typeof r.maximum !== "number") {
                    throw new Error(
                        "Rejection missing current/maximum: "
                        + JSON.stringify(r).slice(0, 200)
                    );
                }
                if (r.maximum !== RULE_LIMIT) {
                    throw new Error(
                        "Rejection maximum=" + r.maximum
                        + ", expected " + RULE_LIMIT
                    );
                }
            }
            console.log("    " + rejects.length
                + " rejection(s) carried complete current/maximum error shape");
        });
    } finally {
        // Cleanup: superadmin1 deletes whatever rules actually landed.
        // Superadmin is exempt from admin_rule_creation cap, so cleanup
        // is not subject to the very race we are testing.
        //
        // API asymmetry note: create_rule takes detection_rule but
        // remove_rule takes rule_name (despite referring to the same
        // entity). Caught during Day 3 — using detection_rule here
        // returned "rule_name is required" for every cleanup attempt.
        for (let i = 0; i < ruleNames.length; i++) {
            try {
                const r = await H.restCall(sessions.super1.page, "POST", {
                    action: "remove_rule",
                    rule_name: ruleNames[i],
                    removal_type: "permanent",
                    comment: TAG + " cleanup",
                });
                // Silent on "not found" — the rules that didn't land
                // are expected to return an error here.
                if (r.error && !/not found|does not exist/i.test(r.error)) {
                    console.log("    cleanup note (" + ruleNames[i] + "): "
                        + r.error.slice(0, 80));
                }
            } catch (_) { /* idempotent */ }
        }
        await M.closeSessions(sessions);
    }

    const summary = H.summary("CONCURRENT RATE-LIMIT (Ring 6 Day 3)");
    process.exit(summary.failed > 0 ? 1 : 0);
})().catch(async (e) => {
    console.error("FATAL:", e.message);
    process.exit(1);
});
