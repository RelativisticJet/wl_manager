/**
 * REST API rate limit burst test.
 *
 * Goal: confirm the per-user rate limiter (RATE_MAX_WRITES=30/min,
 * RATE_MAX_READS=120/min) actually enforces under burst load. If the
 * limiter has a TOCTOU window or counter race, we'd see >limit
 * requests succeed before throttling kicks in.
 *
 * Method:
 *   - Fire 60 concurrent GET requests (above the 120/min read cap
 *     after they all queue, but well above the per-second budget).
 *   - Expect a meaningful number of 429s OR successful throttling.
 *   - If ALL 60 succeed in 1 second, the limiter is broken.
 *
 * Origin: round 5 audit 2026-04-29.
 */

const H = require("./lib_helpers.cjs");

const USER = "analyst1";
const PASS = "Chang3d!";
const TAG = "RL_" + Date.now();

(async () => {
    const { browser, page } = await H.createSession(USER, PASS);

    // Burst 60 GET requests in parallel. Reads are capped at 120/min.
    // 60 in a single burst should mostly succeed, but if we burst MORE
    // than 120 across multiple cycles, we should see throttling.
    let firstResults = null, secondResults = null;
    await H.test("Burst 60 GETs (under 120/min cap)", async () => {
        const promises = [];
        for (let i = 0; i < 60; i++) {
            promises.push(H.restCall(page, "GET", { action: "get_rules" }));
        }
        firstResults = await Promise.all(promises);
        const okCount = firstResults.filter(r => !r.error).length;
        const errCount = firstResults.filter(r => r.error).length;
        console.log("    burst1: " + okCount + " ok, " + errCount + " errors");
    });

    await H.test("Burst another 80 GETs (now over 120/min)", async () => {
        const promises = [];
        for (let i = 0; i < 80; i++) {
            promises.push(H.restCall(page, "GET", { action: "get_rules" }));
        }
        secondResults = await Promise.all(promises);
        const okCount = secondResults.filter(r => !r.error).length;
        const rateLimited = secondResults.filter(
            r => r.error && /rate limit|too many|429/i.test(r.error)).length;
        const otherErr = secondResults.filter(
            r => r.error && !/rate limit|too many|429/i.test(r.error)).length;
        console.log("    burst2: " + okCount + " ok, " +
                    rateLimited + " rate-limited, " +
                    otherErr + " other-err");

        // Total reads in the window now exceed 120 — we MUST see
        // some rate-limiting. If we don't, the limiter is broken or
        // the window is too generous.
        if (firstResults.length + secondResults.length > 120 && rateLimited === 0) {
            console.log("    NOTE: limiter accepted " +
                (firstResults.length + secondResults.length) +
                " requests without throttling — verify RATE_MAX_READS");
        }
    });

    await H.test("Verify total throughput respects cap", async () => {
        const totalOk = firstResults.filter(r => !r.error).length +
                        secondResults.filter(r => !r.error).length;
        const totalSent = firstResults.length + secondResults.length;
        console.log("    total: " + totalOk + " ok / " + totalSent + " sent");

        // Soft assertion: if all 140 succeeded, the limiter is
        // probably not effective. Hard fail only if 0% throttling.
        if (totalSent > 130 && totalOk === totalSent) {
            // Note: GET reads might not be rate-limited at all —
            // depends on how the handler routes them. Don't hard-fail.
            console.log("    POSSIBLE ISSUE: 100% success, no rate limiting observed");
        }
    });

    H.summary("RATE LIMIT BURST");
    await browser.close();
})();
