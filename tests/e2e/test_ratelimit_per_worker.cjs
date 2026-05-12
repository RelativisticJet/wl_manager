/**
 * Ring 6.1 Day 6.1.8 (discovery) + Day 6.1.10 (tightened):
 * verify R6-F8 stays closed for the rate limiter.
 *
 * Context: bin/wl_ratelimit.py originally stored
 * `_rate_limits` as a module-level dict. Splunk's
 * PersistentScriptHandler runs N worker processes, each
 * with its OWN module-level state, so the cap was enforced
 * INDEPENDENTLY per worker (effective cap ~30*N, not 30).
 *
 * Day 6.1.9b (build 657) closed R6-F8 by:
 *   - Migrating state to a Splunk KV collection
 *     (`wl_ratelimit_state`).
 *   - Wrapping the read-modify-write sequence in a
 *     per-(user, action_type) cross-process file lock.
 *
 * This test (post-fix shape, Day 6.1.10) fires 60 parallel
 * POSTs to log_event from ONE user and HARD-FAILS if:
 *   - any other-errors appear
 *   - successes is not in {RATE_MAX_WRITES,
 *     RATE_MAX_WRITES - 1}  (the -1 is warmup accounting)
 *   - rate_rejects != PARALLELISM - successes
 *
 * Any deviation = regression — either the KV path isn't
 * running, or the lock isn't held across the RMW.
 *
 * Note on test-run cadence: rate-limit state is shared
 * cross-worker, so back-to-back runs of this test (or
 * other E2E tests using wladmin1) can collide on the
 * same 60s sliding window. Wait ≥75s between runs OR
 * use a distinct user — see tests/e2e/README on
 * test-run cadence guidance (Day 6.1.10 follow-up).
 */

const H = require("./lib_helpers.cjs");
const M = require("./lib_multi_session.cjs");

const PARALLELISM = 60;
const RATE_MAX_WRITES = 30;  // matches bin/wl_constants.py
const TAG = "R6F8_RL_" + Date.now();

/**
 * Status-aware REST POST. Returns
 * { ok, status, body, rate_limited }.
 * Cannot reuse H.restCall because that one swallows
 * status codes via res.json() unconditionally.
 */
async function restCallStatusAware(page, action, payload) {
    return page.evaluate(async ({ action, payload }) => {
        const csrfMatch = document.cookie.match(
            /splunkweb_csrf_token_8000=([^;]+)/);
        const token = csrfMatch ? csrfMatch[1] : "";
        const headers = {
            "X-Splunk-Form-Key": token,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
        };
        const base = "/en-US/splunkd/__raw/services/custom/wl_manager";
        const res = await fetch(base + "?output_mode=json", {
            method: "POST",
            headers,
            body: JSON.stringify({ action, ...payload }),
        });
        let body = null;
        try { body = await res.json(); }
        catch (_e) { body = { _parse_failed: true }; }
        return {
            ok: res.ok,
            status: res.status,
            body,
            rate_limited:
                res.status === 429 ||
                (body && typeof body.error === "string" &&
                 body.error.toLowerCase().includes("rate limit")),
        };
    }, { action, payload });
}

(async () => {
    // One wladmin1 session is enough — every request goes
    // through the same authentication path but Splunk's
    // PersistentScriptHandler dispatches across the worker
    // pool.
    const sessions = await M.createSessions({
        admin1: ["wladmin1", "Chang3d!"],
    });

    try {
        await H.test("Setup: warm up session", async () => {
            // log_event requires event_action from
            // {"audit_exported", "csv_exported", "csv_imported"}
            // — audit_exported is the cheapest valid shape.
            const r = await restCallStatusAware(
                sessions.admin1.page,
                "log_event",
                { event_action: "audit_exported",
                  event_count: 0,
                  comment: TAG + " warmup" });
            if (!r.ok) {
                throw new Error("warmup failed: status="
                    + r.status + " body=" + JSON.stringify(r.body));
            }
        });

        await H.test("Burst: 60 concurrent POSTs hit log_event "
                     + "from ONE user (cap=30/60s)", async () => {
            const barrier = M.createBarrier(PARALLELISM,
                { label: "ratelimit-burst" });
            const fire = async (i) => {
                await barrier();
                return restCallStatusAware(
                    sessions.admin1.page,
                    "log_event",
                    { event_action: "audit_exported",
                      event_count: i,
                      comment: TAG + " burst_" + i });
            };
            const results = await Promise.all(
                Array.from({ length: PARALLELISM }, (_, i) => fire(i)));

            const successes = results.filter(
                r => r.ok && !r.rate_limited).length;
            const rate_rejects = results.filter(
                r => r.rate_limited).length;
            const other_errors = results.filter(
                r => !r.ok && !r.rate_limited).length;

            console.log("    parallelism: " + PARALLELISM
                + "  cap: " + RATE_MAX_WRITES
                + "  successes: " + successes
                + "  rate_rejects: " + rate_rejects
                + "  other_errors: " + other_errors);

            if (other_errors > 0) {
                const sample = results.find(
                    r => !r.ok && !r.rate_limited);
                console.log("    sample other-error: status="
                    + sample.status + " body="
                    + JSON.stringify(sample.body).slice(0, 200));
            }

            // Ring 6.1 Day 6.1.10 — tightened post-fix.
            //
            // R6-F8 closed at build 657 (KV-backed state +
            // per-(user,action_type) file lock around the RMW).
            // Cross-worker enforcement is now strict, so the
            // burst must produce EXACTLY RATE_MAX_WRITES
            // successes — minus any budget the warmup call
            // consumed in the same sliding window.
            //
            // Expected post-fix outcomes:
            //   - successes IN {RATE_MAX_WRITES,
            //                   RATE_MAX_WRITES - 1}
            //     The -1 is the warmup-accounting case (warmup
            //     burned 1 of the 30 budget; 29 of 60 burst
            //     calls succeed).
            //   - rate_rejects == PARALLELISM - successes
            //   - other_errors == 0
            //
            // Any deviation = regression: either the lock
            // isn't holding the RMW (KV-only fallback) or the
            // KV-backed code path isn't running (module
            // reverted to in-memory).
            if (other_errors > 0) {
                throw new Error("REGRESSION: " + other_errors
                    + " other-errors. Sample: status="
                    + (results.find(r => !r.ok && !r.rate_limited)
                       || {}).status);
            }
            if (successes < RATE_MAX_WRITES - 1
                    || successes > RATE_MAX_WRITES) {
                throw new Error("R6-F8 REGRESSION: successes="
                    + successes + " (expected "
                    + (RATE_MAX_WRITES - 1) + " or "
                    + RATE_MAX_WRITES + "). Post-Ring-6.1 cap "
                    + "must be enforced cross-worker. "
                    + (successes > RATE_MAX_WRITES
                       ? "successes > cap implies the KV-backed "
                         + "code path isn't running or the lock "
                         + "isn't held."
                       : "successes < cap-1 implies excess "
                         + "warmup consumption or test "
                         + "contamination from a prior run "
                         + "within the 60s window."));
            }
            if (rate_rejects !== PARALLELISM - successes) {
                throw new Error("Classification gap: rate_rejects="
                    + rate_rejects + " expected "
                    + (PARALLELISM - successes));
            }
            console.log("    VERDICT: cap enforced "
                + "cross-worker (R6-F8 CLOSED). successes="
                + successes + " / " + RATE_MAX_WRITES + " cap.");
        });
    } finally {
        await M.closeSessions(sessions);
    }

    const summary = H.summary(
        "RATELIMIT CROSS-WORKER ENFORCEMENT (R6-F8 closed at build 657)");
    process.exit(summary.failed > 0 ? 1 : 0);
})().catch(async (e) => {
    console.error("FATAL:", e.message);
    process.exit(1);
});
