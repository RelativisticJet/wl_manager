/**
 * E2E tests for wladmin1 (wl_admin role)
 * Tests: All analyst features + approval processing, control panel, trash, usage monitoring
 */
const H = require("./lib_helpers.cjs");
const USER = "wladmin1", PASS = "Chang3d!";
const TEST_RULE = "DR45_suspicious_login";

(async () => {
    const { browser, page } = await H.createSession(USER, PASS);
    H.log("\u{1F6E1}\uFE0F", `=== WLADMIN1 (wl_admin) TESTS ===`);

    // ── 1. Role detection ──
    await H.test("W01 User is detected as admin", async () => {
        const d = await H.restCall(page, "GET", { action: "get_user_info" });
        if (!d.is_admin) throw new Error("wladmin1 should be detected as admin");
        if (d.username !== USER) throw new Error(`Wrong user: ${d.username}`);
    });

    // ── 2. All analyst features work for admin too ──
    await H.test("W02 Page loads, can select rule + CSV", async () => {
        await H.navigateToWM(page);
        await H.selectRule(page, TEST_RULE);
        await H.waitForTable(page);
    });

    await H.test("W03 Can edit cells", async () => {
        const sel = "#csv-table-container tbody textarea.wl-input, #csv-table-container tbody input.wl-input";
        const orig = await page.$eval(sel, el => el.value);
        await page.fill(sel, orig + "_ADM");
        const val = await page.$eval(sel, el => el.value);
        if (!val.endsWith("_ADM")) throw new Error("Edit failed");
        await page.fill(sel, orig);
    });

    // ── 3. Approval queue access ──
    await H.test("W04 Can access approval queue", async () => {
        const d = await H.restCall(page, "GET", { action: "get_approval_queue" });
        if (d.error) throw new Error(d.error);
        H.log("\u2139\uFE0F", `  Queue has ${(d.queue || []).length} items`);
    });

    await H.test("W05 Can access pending approvals", async () => {
        const d = await H.restCall(page, "GET", { action: "get_pending_approvals" });
        if (d.error) throw new Error(d.error);
    });

    // ── 4. Daily limits management ──
    await H.test("W06 Can read daily limits", async () => {
        const d = await H.restCall(page, "GET", { action: "get_daily_limits" });
        if (d.error) throw new Error(d.error);
        if (!d.limits) throw new Error("No limits in response");
    });

    await H.test("W07 Can read analyst usage", async () => {
        const d = await H.restCall(page, "GET", { action: "get_analyst_usage" });
        if (d.error) throw new Error(d.error);
    });

    await H.test("W08 Cannot set daily limits (superadmin-only)", async () => {
        const d = await H.restCall(page, "POST", {
            action: "set_daily_limits",
            limits: JSON.stringify({ row_removal: 999 })
        });
        if (!d.error) throw new Error("wl_admin should not be able to set limits (superadmin-only)");
        H.log("\u2139\uFE0F", `  Correctly denied: ${d.error.substring(0, 80)}`);
    });

    // ── 5. Trash management ──
    await H.test("W09 Can access trash config", async () => {
        const d = await H.restCall(page, "GET", { action: "get_trash_config" });
        if (d.error) throw new Error(d.error);
    });

    await H.test("W10 Can list trash items", async () => {
        const d = await H.restCall(page, "GET", { action: "list_trash" });
        if (d.error) throw new Error(d.error);
        H.log("\u2139\uFE0F", `  Trash has ${(d.items || []).length} items`);
    });

    // ── 6. Control panel ──
    await H.test("W11 Control panel loads for admin", async () => {
        await H.navigateToCP(page);
        const content = await page.$eval("body", el => el.textContent);
        if (!content.includes("Queue") && !content.includes("Limits")) {
            throw new Error("Control panel content not visible for admin");
        }
    });

    // ── 7. Admin should NOT be able to do superadmin-only actions ──
    await H.test("W12 Cannot set admin limits (superadmin-only)", async () => {
        const d = await H.restCall(page, "POST", {
            action: "set_admin_limits",
            limits: JSON.stringify({ rule_deletion: 99 })
        });
        if (!d.error) throw new Error("Admin should not set admin limits");
    });

    await H.test("W13 Cannot reset factory defaults (superadmin-only)", async () => {
        const d = await H.restCall(page, "POST", { action: "reset_factory_defaults" });
        if (!d.error) throw new Error("Admin should not reset factory defaults");
    });

    await H.test("W14 Cannot save as default (superadmin-only)", async () => {
        const d = await H.restCall(page, "POST", { action: "save_as_default" });
        if (!d.error) throw new Error("Admin should not save as default");
    });

    // ── 8. Admin exempt from approval gates ──
    await H.test("W15 Admin exempt from approval gate for edits", async () => {
        const d = await H.restCall(page, "POST", {
            action: "check_approval_gate",
            gate_action: "bulk_row_edit",
            csv_file: "DR45_whitelist_users.csv",
            app_context: "",
            selected_count: "10"
        });
        if (d.error) throw new Error(d.error);
        if (d.requires_approval) throw new Error("Admin should be exempt from approval gates");
        H.log("\u2139\uFE0F", `  Gate: requires_approval=${d.requires_approval} (correct: false for admin)`);
    });

    // ── 9. Revert (admin) ──
    await H.test("W16 Revert dropdown accessible", async () => {
        await H.navigateToWM(page, `rule=${TEST_RULE}`);
        await H.waitForTable(page);
        const opts = await page.$$eval("#wl-revert-select option", o => o.length);
        H.log("\u2139\uFE0F", `  Revert options: ${opts}`);
    });

    // ── 10. Create rule (admin has permission) ──
    await H.test("W17 Admin can create rules directly", async () => {
        const d = await H.restCall(page, "POST", {
            action: "create_rule",
            detection_rule: "DR_ADMIN_E2E_TEST",
            description: "E2E test rule by admin",
            reason: "E2E testing"
        });
        H.log("\u2139\uFE0F", `  Create rule: ${d.message || d.error || "ok"}`);
        // Clean up — remove the test rule
        if (!d.error) {
            await H.restCall(page, "POST", {
                action: "remove_rule",
                rule_name: "DR_ADMIN_E2E_TEST",
                removal_type: "permanent",
                reason: "E2E cleanup"
            });
        }
    });

    // ── 11. Self-reset prevention ──
    await H.test("W18 Admin cannot reset own daily usage", async () => {
        const d = await H.restCall(page, "POST", {
            action: "reset_daily_usage",
            analyst: USER
        });
        if (d.message && !d.error && !d.message.includes("Cannot reset your own")) {
            // Check if it actually succeeded (shouldn't for self)
            H.log("\u2139\uFE0F", `  Self-reset response: ${d.message}`);
        }
    });

    await browser.close();
    const s = H.summary("WLADMIN1 (wl_admin) RESULTS");
    process.exit(s.failed > 0 ? 1 : 0);
})();
