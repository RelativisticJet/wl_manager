// ╔═══════════════════════════════════════════════════════════════════╗
// ║  ⚠  DESTRUCTIVE TEST FILE — MODIFIES CONTAINER STATE           ║
// ║                                                                 ║
// ║  This file resets KV store cooldown counters and modifies       ║
// ║  admin limit configuration inside the Splunk container.         ║
// ║                                                                 ║
// ║  REQUIRES:  WL_TEST_HARNESS=1  environment variable             ║
// ║  REQUIRES:  Container "wl_manager_test" running                 ║
// ║                                                                 ║
// ║  DO NOT run against production. The assertTestHarness() gate    ║
// ║  will refuse, but defense in depth: read this banner first.     ║
// ╚═══════════════════════════════════════════════════════════════════╝
/**
 * Admin Limits — E2E Tests
 *
 * Tests admin limit enforcement, permission toggles, bypass resistance,
 * and superadmin exemption using superadmin1 and wladmin1 accounts.
 */
const H = require("./lib_helpers.cjs");
// Use the shared gated helper so the WL_TEST_HARNESS guard is enforced
// in exactly one place (lib_helpers.cjs :: clearKvCooldownCounter).
const clearKvCooldownCounter = H.clearKvCooldownCounter;

// Helper: set admin limits with verification and retry (handles Splunk rate limiting
// AND the app's own daily rate cap by clearing the KV counter when hit).
async function setAdminLimits(page, limits, retries) {
    retries = retries || 5;
    for (var i = 0; i < retries; i++) {
        if (i > 0) await page.waitForTimeout(3000);
        var d = await H.restCall(page, "POST", {
            action: "set_admin_limits",
            limits: limits
        });
        if (d.error && d.error.indexOf("Rate limit") !== -1) {
            await page.waitForTimeout(5000);
            continue;
        }
        if (d.error && d.error.indexOf("capped at") !== -1) {
            // App's own daily cap — clear KV counter and retry
            clearKvCooldownCounter();
            await page.waitForTimeout(500);
            continue;
        }
        if (d.error && d.error.indexOf("Security lockdown") !== -1) {
            // Tamper flag set (unlikely in CI but handle it)
            clearKvCooldownCounter();
            await page.waitForTimeout(500);
            continue;
        }
        if (d.error) throw new Error("set_admin_limits failed: " + d.error);
        // Verify the settings took effect
        await page.waitForTimeout(500);
        var verify = await H.restCall(page, "GET", { action: "get_admin_limits" });
        var ok = true;
        for (var key in limits) {
            if (verify.admin_limits[key] !== limits[key]) { ok = false; break; }
        }
        if (ok) return d;
        await page.waitForTimeout(2000);
    }
    throw new Error("Failed to set admin limits after " + retries + " retries");
}

(async () => {
    let superSession, adminSession;
    let superPage, adminPage;

    try {
        // ── Setup: Create sessions for both roles ──
        H.log("🔧", "Creating superadmin1 session...");
        superSession = await H.createSession("superadmin1", "Chang3d!");
        superPage = superSession.page;

        H.log("🔧", "Creating wladmin1 session...");
        adminSession = await H.createSession("wladmin1", "Chang3d!");
        adminPage = adminSession.page;

        // ── Clear KV cooldown counter (rate limit bucket) + tamper
        //    state so this test run isn't blocked by the 5-changes-
        //    per-day cap from prior runs. The handler will
        //    auto-bootstrap on first call. Gated by WL_TEST_HARNESS=1. ──
        H.log("🔧", "Clearing KV cooldown state + tamper markers...");
        clearKvCooldownCounter();
        await new Promise(r => setTimeout(r, 500));

        // ── Reset all admin limits to defaults before testing ──
        H.log("🔧", "Resetting admin limits to defaults...");
        await setAdminLimits(superPage, {
            rule_deletion: 2, csv_deletion: 2, approval_count: 20,
            limit_changes: 5, csv_save: 20, csv_revert: 10,
            rule_creation: 5, csv_creation: 5, trash_restore: 10,
            trash_purge: 5, usage_reset: 10,
            reset_frequency: "daily",
            allow_admin_purge_trash: true,
            allow_admin_reset_usage: true
        });
        await superPage.waitForTimeout(2000);

        // ══════════════════════════════════════════════════════════════
        // SECTION 1: Backend GET — verify response shape
        // ══════════════════════════════════════════════════════════════

        await H.test("AL01 get_admin_limits returns all 11 limit keys", async () => {
            const d = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (d.error) throw new Error(d.error);
            const limits = d.admin_limits;
            const expected = [
                "rule_deletion", "csv_deletion", "approval_count", "limit_changes",
                "csv_save", "csv_revert", "rule_creation", "csv_creation",
                "trash_restore", "trash_purge", "usage_reset"
            ];
            for (const key of expected) {
                if (limits[key] === undefined) throw new Error("Missing limit key: " + key);
                if (typeof limits[key] !== "number") throw new Error("Non-numeric limit: " + key);
            }
        });

        await H.test("AL02 get_admin_limits returns defaults object", async () => {
            const d = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (!d.defaults) throw new Error("Missing defaults in response");
            if (d.defaults.csv_save !== 20) throw new Error("Default csv_save should be 20");
            if (d.defaults.trash_purge !== 5) throw new Error("Default trash_purge should be 5");
        });

        await H.test("AL03 get_admin_limits returns reset_frequency fields", async () => {
            const d = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            const limits = d.admin_limits;
            if (!limits.reset_frequency) throw new Error("Missing reset_frequency");
            if (limits.reset_time_utc === undefined) throw new Error("Missing reset_time_utc");
            if (limits.reset_day_of_week === undefined) throw new Error("Missing reset_day_of_week");
        });

        await H.test("AL04 get_admin_limits returns permission toggles", async () => {
            const d = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            const limits = d.admin_limits;
            if (limits.allow_admin_purge_trash === undefined) throw new Error("Missing allow_admin_purge_trash");
            if (limits.allow_admin_reset_usage === undefined) throw new Error("Missing allow_admin_reset_usage");
        });

        await H.test("AL05 get_admin_limits returns change_history array", async () => {
            const d = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (!Array.isArray(d.change_history)) throw new Error("change_history should be an array");
        });

        // ══════════════════════════════════════════════════════════════
        // SECTION 2: RBAC — admin cannot modify admin limits
        // ══════════════════════════════════════════════════════════════

        await H.test("AL06 Admin CANNOT set admin limits (RBAC)", async () => {
            const d = await H.restCall(adminPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 1 }
            });
            // Should get an error (403 or error message)
            if (d.success) throw new Error("Admin should not be able to set admin limits");
        });

        await H.test("AL07 Admin CAN read admin limits", async () => {
            const d = await H.restCall(adminPage, "GET", { action: "get_admin_limits" });
            if (d.error) throw new Error("Admin should be able to read admin limits: " + d.error);
            if (!d.admin_limits) throw new Error("Missing admin_limits in response");
        });

        // ══════════════════════════════════════════════════════════════
        // SECTION 3: Validation — backend rejects invalid values
        // ══════════════════════════════════════════════════════════════

        await H.test("AL08 Backend rejects limit > 100", async () => {
            // Save original
            const orig = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            const origVal = orig.admin_limits.csv_save;

            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 999 }
            });
            // Should either error or silently ignore the invalid value
            const after = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (after.admin_limits.csv_save === 999) {
                throw new Error("Backend accepted csv_save=999 (max should be 100)");
            }
        });

        await H.test("AL09 Backend rejects negative limit", async () => {
            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: -5 }
            });
            const after = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (after.admin_limits.csv_save === -5) {
                throw new Error("Backend accepted csv_save=-5");
            }
        });

        await H.test("AL10 Backend rejects invalid reset_frequency", async () => {
            const d = await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { reset_frequency: "hourly" }
            });
            const after = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (after.admin_limits.reset_frequency === "hourly") {
                throw new Error("Backend accepted invalid frequency 'hourly'");
            }
        });

        await H.test("AL11 Backend ignores unknown keys", async () => {
            await setAdminLimits(superPage, { csv_save: 18 });
            const after = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (after.admin_limits.csv_save !== 18) {
                throw new Error("Valid key csv_save was not updated to 18, got: " + after.admin_limits.csv_save);
            }
            // Now try unknown key — should be ignored
            await H.restCall(superPage, "POST", {
                action: "set_admin_limits",
                limits: { unknown_key: 42 }
            });
            await superPage.waitForTimeout(500);
            const after2 = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (after2.admin_limits.unknown_key === 42) {
                throw new Error("Backend stored unknown_key");
            }
            await setAdminLimits(superPage, { csv_save: 20 });
        });

        // ══════════════════════════════════════════════════════════════
        // SECTION 4: Limit Enforcement — admin hits limit
        // ══════════════════════════════════════════════════════════════

        // ── Setup: Clean up test artifacts from previous runs ──
        // Interrupted prior runs can leave:
        //   (a) stale CSV files on disk
        //   (b) dangling entries in rule_csv_map.csv
        //   (c) dangling entries in detection_rules.json
        // The per-rule CSV cap (20) is computed from the mapping
        // file, so leaving entries behind makes AL13/14/15 fail.
        // Nuke all three sources before each run.
        H.log("🔧", "Cleaning test artifacts from previous runs...");
        const { spawnSync: _spawnSync } = require("child_process");
        _spawnSync("docker", ["exec", "-u", "0", "wl_manager_test",
            "bash", "-c",
            "rm -f /opt/splunk/etc/apps/wl_manager/lookups/AL_test_*.csv "
            + "/opt/splunk/etc/apps/wl_manager/lookups/AL_test2_*.csv "
            + "/opt/splunk/etc/apps/wl_manager/lookups/AL_super_*.csv "
            + "/opt/splunk/etc/apps/wl_manager/lookups/AL13_test_limits.csv "
            + "/opt/splunk/etc/apps/wl_manager/lookups/AL15_super_exempt.csv; "
            // Strip AL_Test_Creation / AL_Super_Exempt rows from the mapping
            + "sed -i '/^AL_Test_Creation,/d;/^AL_Super_Exempt,/d' "
            + "/opt/splunk/etc/apps/wl_manager/lookups/rule_csv_map.csv; "
            // And drop them from detection_rules.json if present
            + "python3 -c \""
            + "import json, os; "
            + "p = '/opt/splunk/etc/apps/wl_manager/lookups/_versions/detection_rules.json'; "
            + "d = json.load(open(p)) if os.path.isfile(p) else {}; "
            + "d.pop('AL_Test_Creation', None); "
            + "d.pop('AL_Super_Exempt', None); "
            + "open(p, 'w').write(json.dumps(d, indent=2))\" 2>/dev/null || true"
        ], { env: { ...process.env, MSYS_NO_PATHCONV: "1" }, encoding: "utf8" });
        for (const rule of ["AL_Test_Creation", "AL_Super_Exempt"]) {
            await H.restCall(superPage, "POST", {
                action: "remove_rule", detection_rule: rule, comment: "pre-cleanup"
            });
            await superPage.waitForTimeout(1000);
        }

        // Reset admin daily counters to start clean
        H.log("🔧", "Resetting wladmin1 daily counters...");
        await superPage.waitForTimeout(2000);
        await H.restCall(superPage, "POST", {
            action: "reset_daily_usage", analyst: "wladmin1"
        });
        await superPage.waitForTimeout(2000);

        // Set csv_creation limit to 1 for testing
        await H.test("AL12 Set csv_creation limit to 1 for enforcement test", async () => {
            await setAdminLimits(superPage, { csv_creation: 1 });
        });

        await H.test("AL13 Admin first csv_creation succeeds within limit", async () => {
            const ts = Date.now();
            const createResult = await H.restCall(adminPage, "POST", {
                action: "create_csv",
                csv_file: "AL_test_" + ts + ".csv",
                detection_rule: "AL_Test_Creation",
                headers: ["src_ip", "Comment"],
                rows: [["10.0.0.1", "test"]]
            });
            if (createResult.error) throw new Error("First csv_creation should succeed: " + createResult.error);
        });

        await H.test("AL14 Admin second csv_creation BLOCKED by limit", async () => {
            const ts = Date.now();
            const createResult = await H.restCall(adminPage, "POST", {
                action: "create_csv",
                csv_file: "AL_test2_" + ts + ".csv",
                detection_rule: "AL_Test_Creation",
                headers: ["src_ip"],
                rows: [["10.0.0.2"]]
            });
            if (!createResult.error) {
                throw new Error("Second csv_creation should have been blocked by limit");
            }
            if (!createResult.error.includes("limit") && !createResult.error.includes("disabled")) {
                throw new Error("Error should mention limit: " + createResult.error);
            }
        });

        await H.test("AL15 Superadmin is EXEMPT from csv_creation limit", async () => {
            const ts = Date.now();
            const createResult = await H.restCall(superPage, "POST", {
                action: "create_csv",
                csv_file: "AL_super_" + ts + ".csv",
                detection_rule: "AL_Super_Exempt",
                headers: ["src_ip"],
                rows: [["10.0.0.3"]]
            });
            if (createResult.error) {
                throw new Error("Superadmin should be exempt from admin limits: " + createResult.error);
            }
        });

        // Restore csv_creation limit
        await setAdminLimits(superPage, { csv_creation: 5 });

        // ══════════════════════════════════════════════════════════════
        // SECTION 5: Permission toggles — disable action for admins
        // ══════════════════════════════════════════════════════════════

        await H.test("AL16 Disable allow_admin_purge_trash blocks admin", async () => {
            await setAdminLimits(superPage, { allow_admin_purge_trash: false });

            const d = await H.restCall(adminPage, "POST", {
                action: "purge_trash",
                item_id: "nonexistent_test_id"
            });
            // Permission check should fire BEFORE item lookup
            if (!d.error || (!d.error.includes("disabled") && !d.error.includes("not permitted"))) {
                throw new Error("Expected permission denied error, got: " + JSON.stringify(d));
            }
        });

        await H.test("AL17 Superadmin can still purge when disabled for admins", async () => {
            // Purge is still disabled for admins — superadmin should be exempt
            const d = await H.restCall(superPage, "POST", {
                action: "purge_trash",
                item_id: "nonexistent_test_id"
            });
            // Should NOT get permission error (item-not-found is expected)
            if (d.error && d.error.includes("disabled")) {
                throw new Error("Superadmin should be exempt from purge toggle");
            }
        });

        await setAdminLimits(superPage, { allow_admin_purge_trash: true });

        await H.test("AL18 Disable allow_admin_reset_usage blocks admin", async () => {
            await setAdminLimits(superPage, { allow_admin_reset_usage: false });

            const d = await H.restCall(adminPage, "POST", {
                action: "reset_daily_usage",
                analyst: "analyst1"
            });
            if (!d.error || (!d.error.includes("disabled") && !d.error.includes("not permitted"))) {
                throw new Error("Expected permission denied error, got: " + JSON.stringify(d));
            }
        });

        await setAdminLimits(superPage, { allow_admin_reset_usage: true });

        // ══════════════════════════════════════════════════════════════
        // SECTION 6: Limit=0 means DISABLED (not unlimited)
        // ══════════════════════════════════════════════════════════════

        await H.test("AL19 Limit=0 disables the action entirely", async () => {
            await setAdminLimits(superPage, { trash_restore: 0 });

            const d = await H.restCall(adminPage, "POST", {
                action: "restore_from_trash",
                item_id: "nonexistent_test"
            });
            if (!d.error || (!d.error.includes("disabled") && !d.error.includes("not permitted"))) {
                throw new Error("Expected 'disabled' in error, got: " + JSON.stringify(d));
            }
        });

        await setAdminLimits(superPage, { trash_restore: 10 });

        // ══════════════════════════════════════════════════════════════
        // SECTION 7: Reset frequency configuration
        // ══════════════════════════════════════════════════════════════

        await H.test("AL20 Can change reset_frequency to weekly", async () => {
            await setAdminLimits(superPage, { reset_frequency: "weekly", reset_day_of_week: 3 });
            const after = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (after.admin_limits.reset_frequency !== "weekly") {
                throw new Error("Frequency not set to weekly");
            }
            if (after.admin_limits.reset_day_of_week !== 3) {
                throw new Error("Day of week not set to 3 (Thursday)");
            }
        });

        await H.test("AL21 Can change reset_frequency to never", async () => {
            await setAdminLimits(superPage, { reset_frequency: "never" });
            const after = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (after.admin_limits.reset_frequency !== "never") {
                throw new Error("Frequency not set to never");
            }
        });

        // Restore to daily
        await setAdminLimits(superPage, { reset_frequency: "daily" });

        // ══════════════════════════════════════════════════════════════
        // SECTION 8: Change history tracking
        // ══════════════════════════════════════════════════════════════

        await H.test("AL22 Changes are tracked in change_history", async () => {
            await setAdminLimits(superPage, { approval_count: 25 });
            const after = await H.restCall(superPage, "GET", { action: "get_admin_limits" });
            if (!after.change_history || after.change_history.length === 0) {
                throw new Error("change_history should have at least 1 entry");
            }
            const latest = after.change_history[0];
            if (!latest.timestamp) throw new Error("Missing timestamp in history entry");
            if (!latest.admin) throw new Error("Missing admin in history entry");
            if (!latest.changes || latest.changes.length === 0) {
                throw new Error("Missing changes array in history entry");
            }
            await setAdminLimits(superPage, { approval_count: 20 });
        });

        // ══════════════════════════════════════════════════════════════
        // SECTION 9: Insider threat — admin bypass attempts
        // ══════════════════════════════════════════════════════════════

        await H.test("AL23 Admin cannot inject _from_approval in payload", async () => {
            await setAdminLimits(superPage, { csv_creation: 0 });

            const d = await H.restCall(adminPage, "POST", {
                action: "create_csv",
                csv_file: "bypass_test.csv",
                detection_rule: "Bypass_Test",
                headers: ["src_ip"],
                rows: [["1.2.3.4"]],
                _from_approval: true
            });
            if (!d.error) {
                throw new Error("Admin bypassed disabled csv_creation with _from_approval");
            }

            await setAdminLimits(superPage, { csv_creation: 5 });
        });

        await H.test("AL24 Admin cannot set own limits via set_admin_limits API", async () => {
            const d = await H.restCall(adminPage, "POST", {
                action: "set_admin_limits",
                limits: { csv_save: 999 }
            });
            if (d.success) {
                throw new Error("Admin should not be able to set admin limits");
            }
        });

        await H.test("AL25 Admin cannot use set_daily_limits to escalate", async () => {
            const d = await H.restCall(adminPage, "POST", {
                action: "set_daily_limits",
                limits: { row_removal: 99 }
            });
            if (d.success || (d.limits && !d.error)) {
                throw new Error("Admin should not be able to set daily limits (superadmin-only)");
            }
        });

        await H.test("AL26 Admin cannot reset_factory_defaults", async () => {
            const d = await H.restCall(adminPage, "POST", {
                action: "reset_factory_defaults"
            });
            if (d.success) {
                throw new Error("Admin should not be able to reset factory defaults");
            }
        });

        // ══════════════════════════════════════════════════════════════
        // SECTION 10: CSV save limit enforcement
        // ══════════════════════════════════════════════════════════════

        await H.test("AL27 csv_save limit enforced on admin", async () => {
            await setAdminLimits(superPage, { csv_save: 1 });

            // Get a CSV to edit
            const mapping = await H.restCall(adminPage, "GET", { action: "get_mapping" });
            if (!mapping.mapping || mapping.mapping.length === 0) {
                throw new Error("No CSV mapping available for test");
            }
            const entry = mapping.mapping[0];
            const csvData = await H.restCall(adminPage, "GET", {
                action: "get_csv_content",
                csv_file: entry.csv_file,
                app: entry.app_context || "wl_manager"
            });
            if (csvData.error) throw new Error("Failed to get CSV: " + csvData.error);

            // Add a row to make an actual change (rows are dicts keyed by header)
            var modifiedRows = (csvData.rows || []).slice();
            var newRow = {};
            (csvData.headers || []).forEach(function (h) {
                var lh = h.toLowerCase();
                if (lh === "comment") newRow[h] = "AL27_test";
                else if (lh === "expires") newRow[h] = "2099-12-31";
                else newRow[h] = "test_val";
            });
            modifiedRows.push(newRow);

            // First save should succeed
            const save1 = await H.restCall(adminPage, "POST", {
                action: "save_csv",
                csv_file: entry.csv_file,
                detection_rule: entry.detection_rule || entry.rule_name,
                app_context: entry.app_context || "wl_manager",
                headers: csvData.headers,
                rows: modifiedRows,
                comment: "Admin limits test save 1",
                expected_mtime: csvData.file_mtime || "",
                expected_content_hash: csvData.content_hash
            });
            if (save1.error) throw new Error("First save should succeed: " + save1.error);

            // Second save should be blocked at the limit check (which
            // runs BEFORE optimistic locking — see _action_save_csv).
            const save2 = await H.restCall(adminPage, "POST", {
                action: "save_csv",
                csv_file: entry.csv_file,
                detection_rule: entry.detection_rule || entry.rule_name,
                app_context: entry.app_context || "wl_manager",
                headers: csvData.headers,
                rows: modifiedRows,
                comment: "Admin limits test save 2 should fail",
                expected_mtime: "999",
                expected_content_hash: csvData.content_hash
            });
            if (!save2.error || !save2.error.includes("limit")) {
                throw new Error("Second csv_save should be blocked by limit=1, got: " +
                    JSON.stringify(save2).substring(0, 200));
            }

            await setAdminLimits(superPage, { csv_save: 20 });
        });

        // ══════════════════════════════════════════════════════════════
        // SECTION 11: UI Tab renders correctly (superadmin only)
        // ══════════════════════════════════════════════════════════════

        await H.test("AL28 Admin Limits tab visible for superadmin", async () => {
            await H.navigateToCP(superPage);
            const tab = superPage.locator('[data-tab="admin-limits"]');
            if (await tab.count() === 0) throw new Error("Admin Limits tab not found for superadmin");
        });

        await H.test("AL29 Admin Limits tab shows all 11 limit inputs", async () => {
            await superPage.click('[data-tab="admin-limits"]');
            await superPage.waitForTimeout(2000);
            const inputs = await superPage.locator(".wl-admin-limit-input").count();
            if (inputs !== 11) {
                throw new Error("Expected 11 limit inputs, found " + inputs);
            }
        });

        await H.test("AL30 Admin Limits tab shows reset frequency dropdown", async () => {
            const freq = superPage.locator("#wl-cp-admin-freq");
            if (await freq.count() === 0) throw new Error("Reset frequency dropdown not found");
        });

        await H.test("AL31 Admin Limits tab shows permission toggles", async () => {
            const purgeToggle = superPage.locator("#wl-cp-admin-perm-purge");
            const resetToggle = superPage.locator("#wl-cp-admin-perm-reset");
            if (await purgeToggle.count() === 0) throw new Error("Purge permission toggle not found");
            if (await resetToggle.count() === 0) throw new Error("Reset usage permission toggle not found");
        });

        await H.test("AL32 Save and Reset buttons are present and styled", async () => {
            const save = superPage.locator("#wl-save-admin-limits");
            const reset = superPage.locator("#wl-reset-admin-limits");
            if (await save.count() === 0) throw new Error("Save button not found");
            if (await reset.count() === 0) throw new Error("Reset button not found");
            // Verify the Save button is rendered with the Splunk-bundled
            // .btn taxonomy (build 631+; pre-build-631 used the unstyled
            // .wl-btn class which silently rendered as plain text — see
            // 2026-04-30 UI consistency audit).
            const saveClass = await save.getAttribute("class");
            if (!saveClass.includes("btn-primary")) {
                throw new Error("Save button missing btn-primary class");
            }
        });

        // ══════════════════════════════════════════════════════════════
        // Cleanup: remove test rules/CSVs created during tests
        // ══════════════════════════════════════════════════════════════

        H.log("🧹", "Cleaning up test artifacts...");
        for (const rule of ["AL_Test_Creation", "AL_Super_Exempt"]) {
            await H.restCall(superPage, "POST", {
                action: "remove_rule",
                detection_rule: rule,
                comment: "E2E cleanup"
            });
        }

    } catch (err) {
        H.log("💥", "Fatal error: " + err.message);
    } finally {
        if (superSession) await superSession.browser.close();
        if (adminSession) await adminSession.browser.close();
    }

    const s = H.summary("Admin Limits E2E Tests");
    process.exit(s.failed > 0 ? 1 : 0);
})();
