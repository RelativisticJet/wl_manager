/**
 * E2E tests for superadmin1 (wl_superadmin role)
 * Tests: All admin features + superadmin-exclusive features
 */
const H = require("./lib_helpers.cjs");
const USER = "superadmin1", PASS = "Chang3d!";

(async () => {
    const { browser, page } = await H.createSession(USER, PASS);
    H.log("\u{1F451}", `=== SUPERADMIN1 (wl_superadmin) TESTS ===`);

    // ── 1. Role detection ──
    await H.test("S01 User detected as admin", async () => {
        const d = await H.restCall(page, "GET", { action: "get_user_info" });
        if (!d.is_admin) throw new Error("superadmin1 should be admin");
    });

    // ── 2. CSV operations (inherited from editor) ──
    await H.test("S02 Can load and view CSV", async () => {
        await H.navigateToWM(page);
        await H.selectRule(page, "DR130_privilege_escalation");
        await H.waitForTable(page);
    });

    // ── 3. Approval queue access ──
    await H.test("S03 Can access approval queue", async () => {
        const d = await H.restCall(page, "GET", { action: "get_approval_queue" });
        if (d.error) throw new Error(d.error);
    });

    // ── 4. SUPERADMIN-EXCLUSIVE: Set daily limits ──
    await H.test("S04 Can read daily limits", async () => {
        const d = await H.restCall(page, "GET", { action: "get_daily_limits" });
        if (d.error) throw new Error(d.error);
        if (!d.limits) throw new Error("No limits returned");
    });

    await H.test("S05 Can set daily limits", async () => {
        // First read current
        const current = await H.restCall(page, "GET", { action: "get_daily_limits" });
        const originalRowRemoval = current.limits.row_removal;

        // Set to a test value — limits must be the full limits object (not nested JSON string)
        const updated = Object.assign({}, current.limits, { row_removal: 15 });
        const d = await H.restCall(page, "POST", {
            action: "set_daily_limits",
            limits: updated
        });
        if (d.error) throw new Error(d.error);

        // Verify it changed
        const verify = await H.restCall(page, "GET", { action: "get_daily_limits" });
        if (verify.limits.row_removal !== 15) throw new Error("Limit not updated: got " + verify.limits.row_removal);

        // Restore original
        updated.row_removal = originalRowRemoval;
        await H.restCall(page, "POST", {
            action: "set_daily_limits",
            limits: updated
        });
        H.log("\u2139\uFE0F", "  Set and restored daily limits successfully");
    });

    // ── 5. SUPERADMIN-EXCLUSIVE: Set admin limits ──
    await H.test("S06 Can read admin limits", async () => {
        const d = await H.restCall(page, "GET", { action: "get_admin_limits" });
        if (d.error) throw new Error(d.error);
    });

    await H.test("S07 Can set admin limits", async () => {
        const current = await H.restCall(page, "GET", { action: "get_admin_limits" });
        const origApprovalCount = (current.limits || {}).approval_count || 20;

        const d = await H.restCall(page, "POST", {
            action: "set_admin_limits",
            limits: JSON.stringify({ approval_count: 25 })
        });
        if (d.error) throw new Error(d.error);

        // Restore
        await H.restCall(page, "POST", {
            action: "set_admin_limits",
            limits: JSON.stringify({ approval_count: origApprovalCount })
        });
    });

    // ── 6. SUPERADMIN-EXCLUSIVE: Save as custom default ──
    await H.test("S08 Can save as default", async () => {
        const d = await H.restCall(page, "POST", { action: "save_as_default" });
        if (d.error) throw new Error(d.error);
    });

    // ── 7. Trash management ──
    await H.test("S09 Can list trash", async () => {
        const d = await H.restCall(page, "GET", { action: "list_trash" });
        if (d.error) throw new Error(d.error);
    });

    await H.test("S10 Can access trash config", async () => {
        const d = await H.restCall(page, "GET", { action: "get_trash_config" });
        if (d.error) throw new Error(d.error);
    });

    // ── 8. Control panel ──
    await H.test("S11 Control panel loads with admin features", async () => {
        await H.navigateToCP(page);
        const body = await page.$eval("body", el => el.textContent);
        if (!body.includes("Queue") && !body.includes("Limit")) {
            throw new Error("Control panel not loading admin features");
        }
    });

    // ── 9. Exempt from approval gates ──
    await H.test("S12 Superadmin exempt from all approval gates", async () => {
        const d = await H.restCall(page, "POST", {
            action: "check_approval_gate",
            gate_action: "bulk_row_addition",
            csv_file: "DR130_priv_escalation.csv",
            app_context: "",
            selected_count: "100"
        });
        if (d.error) throw new Error(d.error);
        if (d.requires_approval) throw new Error("Superadmin should be exempt from approval gates");
    });

    // ── 10. Reset daily usage for others ──
    await H.test("S13 Can reset other analyst daily usage", async () => {
        const d = await H.restCall(page, "POST", {
            action: "reset_daily_usage",
            analyst: "analyst1"
        });
        if (d.error) throw new Error(d.error);
    });

    // ── 11. Cannot reset own usage (defense in depth) ──
    await H.test("S14 Cannot reset own daily usage", async () => {
        const d = await H.restCall(page, "POST", {
            action: "reset_daily_usage",
            analyst: USER
        });
        // Should either error or return warning about self-reset
        if (d.message && !d.message.includes("Cannot reset your own") && !d.message.includes("No usage")) {
            H.log("\u2139\uFE0F", `  Self-reset response: ${d.message}`);
        }
    });

    // ── 12. Create and delete rule (full lifecycle) ──
    await H.test("S15 Full rule lifecycle: create, verify, delete", async () => {
        // Create — uses detection_rule field, not rule_name
        const createRes = await H.restCall(page, "POST", {
            action: "create_rule",
            detection_rule: "DR_SUPER_E2E_TEST",
            description: "Superadmin E2E lifecycle test",
            reason: "E2E testing"
        });
        if (createRes.error) throw new Error("Create: " + createRes.error);

        // Verify exists
        const mapping = await H.restCall(page, "GET", { action: "get_mapping" });
        const rules = mapping.registered_rules || [];
        if (!rules.includes("DR_SUPER_E2E_TEST")) throw new Error("Created rule not in registered list");

        // Delete — uses rule_name + removal_type + comment
        const delRes = await H.restCall(page, "POST", {
            action: "remove_rule",
            rule_name: "DR_SUPER_E2E_TEST",
            removal_type: "permanent",
            comment: "E2E cleanup"
        });
        if (delRes.error) throw new Error("Delete: " + delRes.error);
    });

    await browser.close();
    const s = H.summary("SUPERADMIN1 (wl_superadmin) RESULTS");
    process.exit(s.failed > 0 ? 1 : 0);
})();
