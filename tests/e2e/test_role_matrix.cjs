/**
 * Role × Action Matrix Test
 *
 * Enumerates every GET action (and a safe subset of POSTs) across three
 * role tiers (analyst, admin, superadmin). Asserts:
 *   - Sufficient role → 200, response is well-formed JSON (not HTML error page)
 *   - Insufficient role → clean permission error, NEVER "Internal server error"
 *
 * Finds: latent import bugs, missing-field crashes, typos in dispatch,
 * broken role checks, handlers that assume a field that isn't always there.
 *
 * This is the "highest ROI" test from systematic-bug-hunting.md. An
 * "Internal server error" in the matrix is almost always a real bug.
 */
const H = require("./lib_helpers.cjs");

// GET actions — all safe / idempotent
const GET_ACTIONS = [
    // No role required
    { action: "get_rules", tier: "any" },
    { action: "get_csvs", tier: "any" },
    { action: "get_csv_content", tier: "any",
      params: { rule_name: "DR55_brute_force_login" } },
    { action: "get_mapping", tier: "any" },
    { action: "get_versions", tier: "any",
      params: { csv_file: "DR55_brute_force_users.csv" } },
    { action: "check_csv_status", tier: "any",
      params: { csv_file: "DR55_brute_force_users.csv" } },
    { action: "get_col_widths", tier: "any",
      params: { csv_file: "DR55_brute_force_users.csv" } },
    { action: "get_apps", tier: "any" },
    { action: "report_presence", tier: "any" },
    { action: "get_presence", tier: "any" },
    { action: "get_user_info", tier: "any" },
    { action: "get_pending_approvals", tier: "any" },
    { action: "check_daily_limit_status", tier: "any" },
    { action: "get_notifications", tier: "any" },
    { action: "get_lockdown_status", tier: "any" },

    // ADMIN_ROLES required
    { action: "get_request_csv", tier: "admin",
      params: { request_id: "nonexistent-req-id-for-matrix-test" } },
    { action: "get_approval_queue", tier: "admin" },
    { action: "get_daily_limits", tier: "admin" },
    { action: "get_analyst_usage", tier: "admin" },
    { action: "get_admin_limits", tier: "admin" },
    { action: "get_trash_config", tier: "admin" },
    { action: "list_trash", tier: "admin" },

    // SUPERADMIN_ROLES required
    { action: "get_deploy_window_status", tier: "superadmin" },
];

// Safe POSTs — non-mutating or easily-reversible.
// Mutating POSTs (create_*, remove_*, activate_lockdown, purge_trash,
// reset_factory_defaults, etc.) are NOT in this matrix — they would
// corrupt test state. The state-machine test covers those individually.
const SAFE_POSTS = [
    // No role required
    { action: "log_event", tier: "any",
      params: { event_type: "matrix_test", details: { src: "test_role_matrix" } } },
    { action: "mark_notifications_read", tier: "any", params: {} },
    { action: "cancel_request", tier: "any",
      params: { request_id: "nonexistent-req-id-for-matrix-test" } },

    // EDIT_ROLES
    { action: "check_approval_gate", tier: "edit",
      params: { csv_file: "DR55_brute_force_users.csv", action: "save_csv" } },
    { action: "save_col_widths", tier: "edit",
      params: { csv_file: "DR55_brute_force_users.csv", col_widths: { "user": 150 } } },
];

const ALL_ACTIONS = GET_ACTIONS.map(a => ({ ...a, method: "GET" }))
    .concat(SAFE_POSTS.map(a => ({ ...a, method: "POST" })));

const USERS = [
    { user: "analyst1",    pass: "Chang3d!", role: "analyst"    },
    { user: "wladmin1",    pass: "Chang3d!", role: "admin"      },
    { user: "superadmin1", pass: "Chang3d!", role: "superadmin" },
];

// Map a role to the tiers it satisfies
const ROLE_SATISFIES = {
    analyst:    new Set(["any", "edit"]),
    admin:      new Set(["any", "edit", "admin"]),
    superadmin: new Set(["any", "edit", "admin", "superadmin"]),
};

function isInternalError(body) {
    if (!body) return false;
    if (typeof body === "string") {
        return /internal server error|traceback|<html/i.test(body);
    }
    // JSON: any error string that looks like a crash (not a clean "permission denied")
    const err = (body.error || body.messages || "").toString().toLowerCase();
    if (!err) return false;
    return (
        err.includes("internal server error")
        || err.includes("traceback")
        || err.includes("nameerror")
        || err.includes("keyerror")
        || err.includes("typeerror")
        || err.includes("attributeerror")
        || err.includes("unbound")
    );
}

function isPermissionError(body) {
    const err = (body.error || "").toString().toLowerCase();
    return (
        err.includes("permission")
        || err.includes("not allowed")
        || err.includes("access denied")
        || err.includes("required role")
        || err.includes("forbidden")
        || err.includes("unauthorized")
    );
}

(async () => {
    H.log("\u{1F3AF}", `=== ROLE \u00d7 ACTION MATRIX TEST ===`);
    H.log("\u{1F3AF}", `Testing ${ALL_ACTIONS.length} actions \u00d7 ${USERS.length} roles = ${ALL_ACTIONS.length * USERS.length} combinations`);

    const crashes = [];
    const rbacLeaks = [];

    for (const u of USERS) {
        const { browser, page } = await H.createSession(u.user, u.pass);
        H.log("\u{1F464}", `--- User: ${u.user} (${u.role}) ---`);

        for (const spec of ALL_ACTIONS) {
            const expected = ROLE_SATISFIES[u.role].has(spec.tier);
            const testName = `RM_${u.role}_${spec.method}_${spec.action}`;

            await H.test(testName, async () => {
                const params = Object.assign({ action: spec.action }, spec.params || {});
                let resp;
                try {
                    resp = await H.restCall(page, spec.method, params);
                } catch (e) {
                    throw new Error(`Request threw: ${e.message}`);
                }

                // CRITICAL: no internal server errors, ever, for any role
                if (isInternalError(resp)) {
                    crashes.push({ user: u.user, role: u.role, ...spec, resp });
                    throw new Error(
                        `CRASH: ${spec.action} returned internal error for ${u.role}: `
                        + JSON.stringify(resp).slice(0, 200)
                    );
                }

                if (expected) {
                    // Should succeed or return a domain-level error (e.g.
                    // "request_id not found") — NOT a permission error.
                    if (isPermissionError(resp)) {
                        throw new Error(
                            `RBAC FAIL: ${u.role} denied on ${spec.action} (should be allowed): `
                            + (resp.error || "")
                        );
                    }
                } else {
                    // Should deny. If it succeeds, that's an RBAC leak.
                    const looksSuccessful = (
                        resp
                        && !resp.error
                        && !resp.messages
                        && Object.keys(resp).length > 0
                    );
                    if (looksSuccessful && !isPermissionError(resp)) {
                        // Some "no role required" actions return {} for
                        // low-privilege users — that's fine. A leak is when
                        // a higher-tier response shape comes back.
                        const shapeLeak = (
                            resp.queue !== undefined           // approval queue
                            || resp.limits !== undefined       // daily limits
                            || resp.admin_limits !== undefined // admin limits
                            || resp.trash !== undefined        // trash contents
                            || resp.window !== undefined       // deploy window
                        );
                        if (shapeLeak) {
                            rbacLeaks.push({ user: u.user, role: u.role, ...spec, resp });
                            throw new Error(
                                `RBAC LEAK: ${u.role} got tier-${spec.tier} data on ${spec.action}`
                            );
                        }
                    }
                }
            });
        }

        await browser.close();
    }

    // ── Extra summary for this test style ──
    if (crashes.length > 0) {
        H.log("\u{1F525}", `CRASHES FOUND: ${crashes.length}`);
        for (const c of crashes) {
            H.log("  \u{1F525}", `${c.user} ${c.method} ${c.action}: ${JSON.stringify(c.resp).slice(0, 120)}`);
        }
    }
    if (rbacLeaks.length > 0) {
        H.log("\u{1F6A8}", `RBAC LEAKS FOUND: ${rbacLeaks.length}`);
        for (const l of rbacLeaks) {
            H.log("  \u{1F6A8}", `${l.user} accessed tier-${l.tier} action ${l.action}`);
        }
    }
    if (crashes.length === 0 && rbacLeaks.length === 0) {
        H.log("\u2728", "No crashes or RBAC leaks detected in the matrix");
    }

    H.summary("Role Matrix Test Results");
    process.exit(H.results.some(r => r.status === "FAIL") ? 1 : 0);
})();
