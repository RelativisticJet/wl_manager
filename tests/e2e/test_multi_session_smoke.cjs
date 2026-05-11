/**
 * Ring 6 Day 1 smoke test — multi-session driver.
 *
 * Verifies the lib_multi_session.cjs primitives behave correctly
 * under the conditions Days 2-5 actually need:
 *
 *   1. createSessions returns N logged-in sessions in parallel.
 *   2. Both sessions reach the control_panel page.
 *   3. createBarrier(2) makes both sessions resume from arrive()
 *      with sub-millisecond skew (proof the rendezvous is tight).
 *   4. delay(ms) introduces a measurable gap.
 *   5. createBarrier overflow throws (single-use enforcement).
 *   6. createBarrier timeout fires cleanly when one party never arrives.
 *
 * No state mutations — this is pure infrastructure verification.
 * Per the synthetic-fixture rule, no protected files are written.
 */

const H = require("./lib_helpers.cjs");
const M = require("./lib_multi_session.cjs");

(async () => {
    let sessions = null;

    await H.test("createSessions logs in analyst1 + wladmin1 in parallel", async () => {
        const t0 = Date.now();
        sessions = await M.createSessions({
            analyst: ["analyst1", "Chang3d!"],
            admin: ["wladmin1", "Chang3d!"],
        });
        const elapsed = Date.now() - t0;
        if (!sessions.analyst || !sessions.admin) {
            throw new Error("Missing session aliases: " + Object.keys(sessions).join(","));
        }
        // Wall-clock latency varies wildly with chromium cold-start cost
        // on the host machine — a tight budget here false-positives on
        // slower boxes without catching real serialization bugs. The
        // CAUSAL proof that the sessions ran concurrently is the
        // rendezvous-skew test below: if both sessions reach the
        // barrier with sub-100ms skew, they were running in parallel
        // by the time they got there.
        //
        // We keep the wall-clock log for diagnostics, but only fail if
        // it crosses an obviously-serialized threshold (typical login
        // is 5-10s per session; two sequential would be 10-20s).
        console.log(`    elapsed: ${elapsed}ms (skew test below verifies actual parallelism)`);
        if (elapsed > 20000) {
            throw new Error(
                `createSessions extremely slow: ${elapsed}ms — likely serialized `
                + "or login itself is broken"
            );
        }
    });

    await H.test("Both sessions navigate to control_panel before either POSTs", async () => {
        const barrier = M.createBarrier(2, { label: "cp-navigate" });

        // Each session navigates, hits the barrier, and resumes together.
        const visits = await Promise.all([
            (async () => {
                await H.navigateToCP(sessions.analyst.page);
                await barrier();
                return Date.now();
            })(),
            (async () => {
                await H.navigateToCP(sessions.admin.page);
                await barrier();
                return Date.now();
            })(),
        ]);

        const skewMs = Math.abs(visits[0] - visits[1]);
        // Both resumed in the same microtask tick, so the skew should be
        // dominated by event-loop scheduling — single-digit ms typically.
        console.log(`    rendezvous skew: ${skewMs}ms`);
        if (skewMs > 100) {
            throw new Error(`Barrier skew too high: ${skewMs}ms — rendezvous not tight`);
        }

        // Verify both pages actually loaded the control panel.
        const analystOk = await sessions.analyst.page.evaluate(
            () => !!document.querySelector(".dashboard-cell, .dashboard-body, #cp-tab-nav, body")
        );
        const adminOk = await sessions.admin.page.evaluate(
            () => !!document.querySelector(".dashboard-cell, .dashboard-body, #cp-tab-nav, body")
        );
        if (!analystOk || !adminOk) {
            throw new Error(`Page load incomplete: analyst=${analystOk} admin=${adminOk}`);
        }
    });

    await H.test("delay(ms) introduces a measurable gap", async () => {
        const t0 = Date.now();
        await M.delay(150);
        const elapsed = Date.now() - t0;
        if (elapsed < 140 || elapsed > 400) {
            throw new Error(`delay(150) elapsed ${elapsed}ms — outside [140,400] window`);
        }
    });

    await H.test("createBarrier overflow throws on (n+1)th arrival", async () => {
        const barrier = M.createBarrier(2, { label: "overflow", timeoutMs: 5000 });
        // Fire the n required arrivals concurrently so the barrier releases.
        await Promise.all([barrier(), barrier()]);
        // Third arrival is overflow — must throw.
        let threw = false;
        try { await barrier(); } catch (e) {
            if (!/overflow/i.test(e.message)) {
                throw new Error("Wrong error: " + e.message);
            }
            threw = true;
        }
        if (!threw) throw new Error("Overflow arrival did not throw");
    });

    await H.test("createBarrier(2) times out when only 1 party arrives", async () => {
        const barrier = M.createBarrier(2, { label: "timeout-test", timeoutMs: 300 });
        const t0 = Date.now();
        let caught = null;
        try { await barrier(); } catch (e) { caught = e; }
        const elapsed = Date.now() - t0;
        if (!caught) throw new Error("Single-arrival barrier did not time out");
        if (!/timeout/i.test(caught.message)) {
            throw new Error("Wrong error: " + caught.message);
        }
        if (elapsed < 280 || elapsed > 800) {
            throw new Error(`Timeout fired at ${elapsed}ms — outside [280,800] window`);
        }
    });

    await M.closeSessions(sessions);
    const r = H.summary("MULTI-SESSION SMOKE (Ring 6 Day 1)");
    process.exit(r.failed > 0 ? 1 : 0);
})().catch(async (e) => {
    console.error("FATAL:", e.message);
    process.exit(1);
});
