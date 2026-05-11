/**
 * Multi-session orchestration helpers for Ring 6 concurrency tests.
 *
 * Builds on lib_helpers.cjs::createSession. The core primitives:
 *
 *   createBarrier(n, opts?) -> async arrive()
 *     Single-use rendezvous. N callers must await arrive() before any
 *     of them resume. The Nth caller releases all of them at once.
 *     This tightens race timing vs raw Promise.all (which has inherent
 *     event-loop jitter between the .then() callbacks of each promise).
 *     A new barrier is required per phase — by design, no "round N"
 *     state machine to reason about.
 *
 *   delay(ms)
 *     setTimeout wrapped in a promise. Used for phased races where
 *     one session must fire WHILE another's request is in-flight
 *     (Day 5: presence ping during an in-progress save).
 *
 *   createSessions(roleMap)
 *     Parallel login. roleMap: { alias: [user, pass], ... } -> { alias: session }.
 *     Sequential createSession() costs ~2s per session; 7 sessions
 *     (Day 3's same-user limit consumption) would be 14s of setup
 *     before the test does anything interesting. Parallel cuts to ~2s.
 *
 *   closeSessions(sessions)
 *     Idempotent. Safe in catch blocks. Closes all browsers in parallel.
 *
 * Why this lives next to lib_helpers.cjs and not inside it: the helpers
 * here are useful only for tests that intentionally interleave actions
 * across sessions. Most E2E tests are single-session and don't need
 * this surface. Keeping it separate makes the multi-session tests
 * declare their dependency explicitly.
 */

const H = require("./lib_helpers.cjs");

const DEFAULT_BARRIER_TIMEOUT_MS = 30_000;

/**
 * Single-use barrier. Returns an async arrive() function.
 *
 * The first (n-1) callers block. The nth caller resolves the shared
 * promise, releasing all waiters in the same microtask tick.
 *
 * Timeout: if fewer than n callers arrive within opts.timeoutMs, every
 * blocked caller throws. Default 30s — long enough for slow CI, short
 * enough that a bug doesn't hang the suite.
 *
 * Calling arrive() more than n times is a programming error and throws.
 * (A barrier that silently accepted overflow callers would hide test bugs.)
 */
function createBarrier(n, opts) {
    if (!Number.isInteger(n) || n < 1) {
        throw new Error(`createBarrier: n must be a positive integer (got ${n})`);
    }
    const timeoutMs = (opts && opts.timeoutMs) || DEFAULT_BARRIER_TIMEOUT_MS;
    const label = (opts && opts.label) || `barrier(${n})`;

    let arrived = 0;
    let releaseAll;
    let rejectAll;
    const ready = new Promise((resolve, reject) => {
        releaseAll = resolve;
        rejectAll = reject;
    });

    const timer = setTimeout(() => {
        rejectAll(new Error(
            `${label}: timeout after ${timeoutMs}ms with only ${arrived}/${n} arrivals — `
            + "a session never reached the rendezvous point"
        ));
    }, timeoutMs);
    timer.unref && timer.unref();

    return async function arrive() {
        arrived++;
        if (arrived > n) {
            clearTimeout(timer);
            throw new Error(
                `${label}: arrive() called ${arrived} times but only ${n} expected — `
                + "single-use barrier overflow (programming error)"
            );
        }
        if (arrived === n) {
            clearTimeout(timer);
            releaseAll();
        }
        await ready;
    };
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Parallel session creation.
 *
 * Input:  { alice: ["analyst1", "Chang3d!"], bob: ["wladmin1", "Chang3d!"] }
 * Output: { alice: {browser, context, page}, bob: {browser, context, page} }
 *
 * All sessions log in concurrently via Promise.all. On any failure,
 * partial sessions are torn down before re-throwing so the test
 * runner doesn't leak chromium processes.
 */
async function createSessions(roleMap) {
    const aliases = Object.keys(roleMap);
    const settled = await Promise.allSettled(
        aliases.map(alias => {
            const [user, pass] = roleMap[alias];
            return H.createSession(user, pass);
        })
    );

    const sessions = {};
    const errors = [];
    settled.forEach((r, i) => {
        const alias = aliases[i];
        if (r.status === "fulfilled") {
            sessions[alias] = r.value;
        } else {
            errors.push(`${alias} (${roleMap[alias][0]}): ${r.reason.message}`);
        }
    });

    if (errors.length > 0) {
        await closeSessions(sessions);
        throw new Error(
            `createSessions: ${errors.length}/${aliases.length} logins failed:\n  `
            + errors.join("\n  ")
        );
    }
    return sessions;
}

/**
 * Close every session's browser in parallel. Safe to call with a
 * partial map (e.g. from a catch block where only some sessions
 * succeeded). Errors from .close() are swallowed — the only goal
 * is to not leak chromium processes.
 */
async function closeSessions(sessions) {
    if (!sessions) return;
    await Promise.all(
        Object.values(sessions).map(async s => {
            if (!s || !s.browser) return;
            try { await s.browser.close(); } catch (_) { /* idempotent */ }
        })
    );
}

module.exports = {
    createBarrier,
    delay,
    createSessions,
    closeSessions,
    DEFAULT_BARRIER_TIMEOUT_MS,
};
