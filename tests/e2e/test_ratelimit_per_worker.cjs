/**
 * Ring 6.1 Day 6.1.8 — Live-test the R6-F8-sibling
 * per-worker rate-limit hypothesis.
 *
 * Hypothesis (deferred from Ring 6 R6-F8):
 *   bin/wl_ratelimit.py:16 stores `_rate_limits` as a
 *   module-level dict. Splunk's PersistentScriptHandler
 *   runs a pool of Python worker processes, each with its
 *   OWN module-level state. So one user's writes routed
 *   across N workers see the cap (RATE_MAX_WRITES=30 / 60s)
 *   enforced INDEPENDENTLY per worker — effective cap is
 *   roughly 30*N, not 30.
 *
 * Test design:
 *   - Use ONE wladmin1 session.
 *   - Fire 60 parallel POSTs to log_event (cheap action,
 *     no admin daily limit, no other side effects).
 *   - Classify each response: success (200 + no error) vs
 *     rate-limit reject (HTTP 429 or "Rate limit
 *     exceeded" body).
 *   - Assert based on hypothesis:
 *
 *     Cross-worker (correct):   successes == 30 exactly.
 *     Per-worker (R6-F8):       successes > 30 (magnitude
 *                                indicates worker count).
 *
 * This test is INFORMATIONAL on Day 6.1.8 — it does NOT
 * hard-fail either way. Its job is to surface concrete
 * evidence for Day 6.1.9 (prototype the fix). Once a fix
 * lands in 6.1.9 or 6.1.10, this test should be tightened
 * to assert successes == 30 exactly.
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

            // ──────── Hypothesis verdict (INFORMATIONAL) ─────
            if (successes === RATE_MAX_WRITES) {
                console.log("    VERDICT: cap enforced "
                    + "cross-worker (NO bug). R6-F8 hypothesis "
                    + "for rate limiter is FALSE.");
            } else if (successes > RATE_MAX_WRITES) {
                const ratio = (successes / RATE_MAX_WRITES);
                console.log("    VERDICT: cap enforced "
                    + "PER-WORKER (R6-F8 hypothesis CONFIRMED). "
                    + "successes/cap = " + ratio.toFixed(2)
                    + " — suggests ~" + Math.ceil(ratio)
                    + " workers in the persistconn pool.");
            } else {
                console.log("    VERDICT: AMBIGUOUS — successes ("
                    + successes + ") < cap (" + RATE_MAX_WRITES
                    + "). Could be other_errors mis-classifying "
                    + "or worker-pool not warmed up. "
                    + "Re-run after server warmup.");
            }

            // No hard assertion on success count by design —
            // Day 6.1.8 is the discovery test. Day 6.1.9 will
            // land the fix and Day 6.1.10 will tighten this
            // test to: assert(successes === RATE_MAX_WRITES).
            //
            // BUT do assert classification math is sound:
            if (successes + rate_rejects + other_errors
                    !== PARALLELISM) {
                throw new Error(
                    "Classification gap: " + (PARALLELISM
                        - successes - rate_rejects - other_errors)
                    + " responses fit no bucket");
            }
        });
    } finally {
        await M.closeSessions(sessions);
    }

    const summary = H.summary(
        "RATELIMIT PER-WORKER HYPOTHESIS (Day 6.1.8 — informational)");
    process.exit(summary.failed > 0 ? 1 : 0);
})().catch(async (e) => {
    console.error("FATAL:", e.message);
    process.exit(1);
});
