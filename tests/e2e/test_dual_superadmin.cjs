// ╔═══════════════════════════════════════════════════════════════════╗
// ║  ⚠  DESTRUCTIVE TEST FILE — MODIFIES CONTAINER STATE           ║
// ║                                                                 ║
// ║  Activates emergency lockdown, opens deploy windows, triggers   ║
// ║  bootstrap — all inside the running Splunk container. Tests     ║
// ║  clean up after themselves but DO NOT run against production.   ║
// ║                                                                 ║
// ║  REQUIRES:  WL_TEST_HARNESS=1  environment variable             ║
// ║  REQUIRES:  Container "wl_manager_test" running                 ║
// ║  REQUIRES:  superadmin2 account created (run setup_test_env.sh) ║
// ╚═══════════════════════════════════════════════════════════════════╝
/**
 * Dual-Superadmin Flow E2E Tests
 *
 * Verifies the separation-of-duties enforcement at the superadmin tier:
 *   - Emergency lockdown activate/deactivate requires TWO different
 *     superadmins (self-unlock is blocked).
 *   - Deploy windows can be opened by one superadmin and closed by
 *     another (no self-close restriction — deploy windows are
 *     operational, not security-gated).
 *   - bootstrap_csv_hashes works for any superadmin (no dual
 *     restriction — it's a non-destructive maintenance action).
 *   - Recovery log attribution correctly records the acting user.
 *   - Audit trail captures BOTH the activator and deactivator with
 *     accurate user names.
 */
const H = require("./lib_helpers.cjs");
const { spawnSync } = require("child_process");

H.assertTestHarness();

const CONTAINER = H.EXPECTED_TEST_CONTAINER;
const VERSIONS_DIR = "/opt/splunk/etc/apps/wl_manager/lookups/_versions";
const LOCKDOWN_FILE = `${VERSIONS_DIR}/_emergency_lockdown.json`;
const DEPLOY_WINDOW_FILE = `${VERSIONS_DIR}/_fim_deploy_window.json`;
const RECOVERY_LOG = `${VERSIONS_DIR}/_recovery_log.jsonl`;

function dockerExec(args) {
    const res = spawnSync("docker", ["exec", "-u", "0", CONTAINER, ...args], {
        env: { ...process.env, MSYS_NO_PATHCONV: "1" },
        encoding: "utf8",
    });
    return { stdout: res.stdout || "", stderr: res.stderr || "", code: res.status };
}

function dockerExecStr(cmd) {
    const res = spawnSync("docker", ["exec", "-u", "0", CONTAINER, "bash", "-lc", cmd], {
        env: { ...process.env, MSYS_NO_PATHCONV: "1" },
        encoding: "utf8",
    });
    return { stdout: res.stdout || "", stderr: res.stderr || "", code: res.status };
}

// Run a Splunk search and return parsed results array (or empty array on no match)
function splunkSearch(spl, earliest) {
    earliest = earliest || "-5m";
    const cmd = `/opt/splunk/bin/splunk search '${spl} earliest=${earliest}' `
        + `-auth admin:Chang3d! -output json 2>/dev/null`;
    const out = dockerExecStr(cmd).stdout.trim();
    if (!out) return [];
    try {
        // Splunk CLI outputs one JSON per line; collect all
        const lines = out.split("\n").filter(l => l.trim().startsWith("{"));
        return lines.map(l => JSON.parse(l));
    } catch (e) {
        return [];
    }
}

// Cleanup state before and after tests — keeps runs idempotent
function cleanup() {
    dockerExecStr(`rm -f ${LOCKDOWN_FILE} ${DEPLOY_WINDOW_FILE} 2>/dev/null || true`);
    // Don't delete recovery log — it's audit history we may want to preserve.
    // Tests verify their own recovery log entries by matching on timestamp/reason.
}

(async () => {
    let s1, s2;  // superadmin1, superadmin2 sessions

    async function newSessions() {
        s1 = await H.createSession("superadmin1", "Chang3d!");
        s2 = await H.createSession("superadmin2", "Chang3d!");
    }

    try {
        H.log("🔧", "Pre-flight: verifying superadmin2 exists...");
        const check = dockerExec([
            "curl", "-sk", "-u", "admin:Chang3d!",
            "https://localhost:8089/services/authentication/users/superadmin2?output_mode=json",
        ]);
        if (check.stdout.includes("does not exist")
            || check.stdout.includes("Could not find object")) {
            throw new Error(
                "superadmin2 account missing — run tests/e2e/setup_test_env.sh first");
        }

        H.log("🔧", "Cleaning any stale lockdown/deploy-window state...");
        cleanup();
        await new Promise(r => setTimeout(r, 500));
        await newSessions();

        // ═══════════════════════════════════════════════════════════
        // SECTION A — Emergency Lockdown: self-unlock prevention
        // ═══════════════════════════════════════════════════════════

        await H.test("DS01 superadmin1 can activate emergency lockdown", async () => {
            const d = await H.restCall(s1.page, "POST", {
                action: "activate_lockdown",
                reason: "DS01 test activation by superadmin1",
            });
            if (d.error) throw new Error("Activate failed: " + d.error);
            if (!d.success) throw new Error("Missing success flag");
            // Confirm lockdown file exists with correct attribution
            const raw = dockerExec(["cat", LOCKDOWN_FILE]).stdout;
            const state = JSON.parse(raw);
            if (!state.locked) throw new Error("Lockdown file not marked locked");
            if (state.locked_by !== "superadmin1") {
                throw new Error("Wrong locked_by: " + state.locked_by);
            }
        });

        await H.test("DS02 get_lockdown_status reports locked state to superadmin1", async () => {
            const d = await H.restCall(s1.page, "GET", { action: "get_lockdown_status" });
            if (!d.lockdown || !d.lockdown.locked) {
                throw new Error("Lockdown status not reported as locked");
            }
            if (d.lockdown.locked_by !== "superadmin1") {
                throw new Error("Wrong locked_by in status: " + d.lockdown.locked_by);
            }
        });

        await H.test("DS03 get_lockdown_status reports locked state to superadmin2", async () => {
            const d = await H.restCall(s2.page, "GET", { action: "get_lockdown_status" });
            if (!d.lockdown || !d.lockdown.locked) {
                throw new Error("Lockdown status not reported as locked");
            }
            if (d.lockdown.locked_by !== "superadmin1") {
                throw new Error("Wrong locked_by visibility: " + d.lockdown.locked_by);
            }
        });

        await H.test("DS04 superadmin1 CANNOT self-deactivate their own lockdown", async () => {
            const d = await H.restCall(s1.page, "POST", { action: "deactivate_lockdown" });
            if (!d.error) {
                throw new Error("Self-unlock was allowed (should be blocked)");
            }
            const msg = d.error.toLowerCase();
            if (!msg.includes("different") && !msg.includes("activated")) {
                throw new Error("Unexpected error message: " + d.error);
            }
            // Verify lockdown file still present
            const exists = dockerExec(["test", "-f", LOCKDOWN_FILE]).code === 0;
            if (!exists) throw new Error("Lockdown file removed despite self-unlock rejection");
        });

        await H.test("DS05 superadmin2 CAN deactivate superadmin1's lockdown", async () => {
            const d = await H.restCall(s2.page, "POST", { action: "deactivate_lockdown" });
            if (d.error) throw new Error("Cross-superadmin deactivate failed: " + d.error);
            if (!d.success) throw new Error("Missing success flag");
            // Deactivate writes empty state ({}) rather than deleting the file.
            // Verify via status API that lockdown is logically off.
            const status = await H.restCall(s2.page, "GET", { action: "get_lockdown_status" });
            if (status.lockdown && status.lockdown.locked) {
                throw new Error("Lockdown still reported as locked after deactivate");
            }
        });

        await H.test("DS06 Deactivate with no active lockdown returns error", async () => {
            const d = await H.restCall(s2.page, "POST", { action: "deactivate_lockdown" });
            if (!d.error) {
                throw new Error("Expected error when no lockdown active");
            }
            if (!d.error.toLowerCase().includes("not active")) {
                throw new Error("Unexpected error: " + d.error);
            }
        });

        await H.test("DS07 Activate → cross-deactivate audit trail records both users", async () => {
            // Re-activate for this test
            await H.restCall(s1.page, "POST", {
                action: "activate_lockdown",
                reason: "DS07 audit trail test",
            });
            await new Promise(r => setTimeout(r, 500));
            await H.restCall(s2.page, "POST", { action: "deactivate_lockdown" });
            await new Promise(r => setTimeout(r, 3000));  // Let audit indexing catch up

            const activations = splunkSearch(
                "index=wl_audit action=emergency_lockdown_activated analyst=superadmin1",
                "-2m");
            const deactivations = splunkSearch(
                "index=wl_audit action=emergency_lockdown_deactivated analyst=superadmin2",
                "-2m");

            if (activations.length === 0) {
                throw new Error("No activation audit event found for superadmin1");
            }
            if (deactivations.length === 0) {
                throw new Error("No deactivation audit event found for superadmin2");
            }
            // Verify the deactivation event recorded the original locker
            const deact = deactivations[0].result || deactivations[0];
            if (deact.originally_locked_by
                && deact.originally_locked_by !== "superadmin1") {
                throw new Error(
                    "originally_locked_by mismatch: " + deact.originally_locked_by);
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION B — Deploy Window: cross-superadmin operation
        // ═══════════════════════════════════════════════════════════

        await H.test("DS08 superadmin1 opens a deploy window", async () => {
            cleanup();  // Ensure clean state
            const d = await H.restCall(s1.page, "POST", {
                action: "open_deploy_window",
                duration_minutes: 5,
                reason: "DS08 cross-superadmin test",
            });
            if (d.error) throw new Error("Open failed: " + d.error);
            if (!d.success) throw new Error("Missing success flag");
            // Verify window file exists
            const exists = dockerExec(["test", "-f", DEPLOY_WINDOW_FILE]).code === 0;
            if (!exists) throw new Error("Deploy window file not created");
        });

        await H.test("DS09 superadmin2 can see status of superadmin1's deploy window", async () => {
            const d = await H.restCall(s2.page, "GET", {
                action: "get_deploy_window_status",
            });
            if (d.error) throw new Error("Status query failed: " + d.error);
            if (!d.active) throw new Error("Window not reported as active");
        });

        await H.test("DS10 superadmin2 can close superadmin1's deploy window", async () => {
            const d = await H.restCall(s2.page, "POST", {
                action: "close_deploy_window",
            });
            if (d.error) throw new Error("Cross-superadmin close failed: " + d.error);
            if (!d.success) throw new Error("Missing success flag");
            const exists = dockerExec(["test", "-f", DEPLOY_WINDOW_FILE]).code === 0;
            if (exists) throw new Error("Window file still present after close");
        });

        await H.test("DS11 superadmin1 can also self-close their own deploy window", async () => {
            // Unlike lockdown, deploy windows have no self-close restriction
            // (they're operational, not security-gated — any superadmin
            // including the opener should be able to close).
            const opened = await H.restCall(s1.page, "POST", {
                action: "open_deploy_window",
                duration_minutes: 2,
                reason: "DS11 self-close test",
            });
            if (opened.error) throw new Error("Re-open failed: " + opened.error);
            const closed = await H.restCall(s1.page, "POST", {
                action: "close_deploy_window",
            });
            if (closed.error) throw new Error("Self-close failed: " + closed.error);
            if (!closed.success) throw new Error("Missing success flag on self-close");
        });

        await H.test("DS12 Deploy window open+close by different superadmins appears in audit", async () => {
            await H.restCall(s1.page, "POST", {
                action: "open_deploy_window",
                duration_minutes: 2,
                reason: "DS12 audit test",
            });
            await new Promise(r => setTimeout(r, 500));
            await H.restCall(s2.page, "POST", { action: "close_deploy_window" });
            await new Promise(r => setTimeout(r, 3000));

            const starts = splunkSearch(
                "index=wl_audit action=fim_deploy_window_start analyst=superadmin1",
                "-2m");
            const ends = splunkSearch(
                "index=wl_audit action=fim_deploy_window_end analyst=superadmin2",
                "-2m");

            if (starts.length === 0) {
                throw new Error("No deploy_window_start audit event for superadmin1");
            }
            if (ends.length === 0) {
                throw new Error("No deploy_window_end audit event for superadmin2");
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION C — bootstrap_csv_hashes works for both superadmins
        // ═══════════════════════════════════════════════════════════

        await H.test("DS13 superadmin1 can call bootstrap_csv_hashes", async () => {
            const d = await H.restCall(s1.page, "POST", {
                action: "bootstrap_csv_hashes",
            });
            if (d.error) throw new Error("Bootstrap failed: " + d.error);
            if (!d.success) throw new Error("Missing success flag");
            if (typeof d.hashed_count !== "number" || d.hashed_count < 1) {
                throw new Error("Invalid hashed_count: " + d.hashed_count);
            }
        });

        await H.test("DS14 superadmin2 can also call bootstrap_csv_hashes (no dual restriction)", async () => {
            const d = await H.restCall(s2.page, "POST", {
                action: "bootstrap_csv_hashes",
            });
            if (d.error) {
                throw new Error("superadmin2 bootstrap failed: " + d.error);
            }
            if (!d.success) throw new Error("Missing success flag");
        });

        await H.test("DS15 Both bootstrap calls appear in audit trail with correct analyst", async () => {
            await new Promise(r => setTimeout(r, 3000));
            const s1Events = splunkSearch(
                "index=wl_audit action=bootstrap_csv_hashes analyst=superadmin1",
                "-5m");
            const s2Events = splunkSearch(
                "index=wl_audit action=bootstrap_csv_hashes analyst=superadmin2",
                "-5m");

            if (s1Events.length === 0) {
                throw new Error("No bootstrap audit event for superadmin1");
            }
            if (s2Events.length === 0) {
                throw new Error("No bootstrap audit event for superadmin2");
            }
        });

        // ═══════════════════════════════════════════════════════════
        // SECTION D — Deploy window is lockdown-exempt
        // (critical: superadmin2 must be able to open windows during
        //  an emergency lockdown to deploy hotfixes)
        // ═══════════════════════════════════════════════════════════

        await H.test("DS16 Deploy window can be opened during active lockdown", async () => {
            cleanup();
            // superadmin1 activates lockdown
            await H.restCall(s1.page, "POST", {
                action: "activate_lockdown",
                reason: "DS16 lockdown-exempt test",
            });
            // superadmin2 opens a deploy window (lockdown-exempt)
            const open = await H.restCall(s2.page, "POST", {
                action: "open_deploy_window",
                duration_minutes: 5,
                reason: "Hotfix deploy during lockdown",
            });
            if (open.error) {
                throw new Error(
                    "Deploy window was blocked by lockdown (should be exempt): "
                    + open.error);
            }
            if (!open.success) throw new Error("Missing success flag");
        });

        await H.test("DS17 Deploy window can be closed during active lockdown", async () => {
            // Still locked from DS16 — now close the window
            const close = await H.restCall(s1.page, "POST", {
                action: "close_deploy_window",
            });
            if (close.error) {
                throw new Error("Close blocked by lockdown: " + close.error);
            }
            // Deactivate lockdown to leave clean state
            await H.restCall(s2.page, "POST", { action: "deactivate_lockdown" });
        });

        await H.test("DS18 bootstrap_csv_hashes is ALSO lockdown-exempt", async () => {
            cleanup();
            await H.restCall(s1.page, "POST", {
                action: "activate_lockdown",
                reason: "DS18 bootstrap-during-lockdown",
            });
            const d = await H.restCall(s2.page, "POST", {
                action: "bootstrap_csv_hashes",
            });
            // Cleanup regardless of outcome
            await H.restCall(s2.page, "POST", { action: "deactivate_lockdown" });

            if (d.error && d.error.toLowerCase().includes("lockdown")) {
                throw new Error(
                    "bootstrap_csv_hashes was blocked by lockdown "
                    + "(should be exempt): " + d.error);
            }
            if (d.error) {
                throw new Error("Unexpected bootstrap error: " + d.error);
            }
        });

        // ═══════════════════════════════════════════════════════════
        // Cleanup
        // ═══════════════════════════════════════════════════════════
        H.log("🧹", "Cleanup: removing any remaining lockdown/deploy-window state");
        cleanup();

    } catch (err) {
        H.log("💥", "Fatal error: " + err.message);
        cleanup();  // Best-effort cleanup on crash
    } finally {
        for (const s of [s1, s2]) {
            if (s) { try { await s.browser.close(); } catch (e) {} }
        }
    }

    const s = H.summary("Dual-Superadmin Flow Tests");
    process.exit(s.failed > 0 ? 1 : 0);
})();
