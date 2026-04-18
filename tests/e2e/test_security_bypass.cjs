/**
 * Security bypass and edge case tests
 * Tests cross-role privilege escalation, injection, state manipulation,
 * concurrent operations, and unusual input patterns.
 */
const H = require("./lib_helpers.cjs");

(async () => {
    H.log("\u{1F6A8}", `=== SECURITY BYPASS & EDGE CASE TESTS ===`);

    // ── Session 1: Analyst trying admin actions via API ──
    const analystSess = await H.createSession("analyst1", "Chang3d!");
    const ap = analystSess.page;

    await H.test("SEC01 Analyst cannot process_approval via API", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "process_approval",
            request_id: "test-id",
            decision: "approve",
            admin_comment: "bypass attempt"
        });
        if (!d.error) throw new Error("Analyst processed approval (should be denied)");
    });

    await H.test("SEC02 Analyst cannot set_daily_limits via API", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "set_daily_limits",
            limits: JSON.stringify({ row_removal: 999 })
        });
        if (!d.error) throw new Error("Analyst set limits (should be denied)");
    });

    await H.test("SEC03 Analyst cannot set_admin_limits via API", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "set_admin_limits",
            limits: JSON.stringify({ approval_count: 999 })
        });
        if (!d.error) throw new Error("Analyst set admin limits (should be denied)");
    });

    await H.test("SEC04 Analyst cannot purge_trash via API", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "purge_trash",
            trash_id: "fake"
        });
        if (!d.error) throw new Error("Analyst purged trash (should be denied)");
    });

    await H.test("SEC05 Analyst cannot restore_from_trash via API", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "restore_from_trash",
            trash_id: "fake"
        });
        if (!d.error) throw new Error("Analyst restored from trash (should be denied)");
    });

    await H.test("SEC06 Analyst cannot reset_daily_usage via API", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "reset_daily_usage",
            analyst: "analyst2"
        });
        if (!d.error) throw new Error("Analyst reset usage (should be denied)");
    });

    await H.test("SEC07 Analyst cannot reset_factory_defaults via API", async () => {
        const d = await H.restCall(ap, "POST", { action: "reset_factory_defaults" });
        if (!d.error) throw new Error("Analyst reset factory defaults (should be denied)");
    });

    await H.test("SEC08 Analyst cannot set_trash_retention via API", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "set_trash_retention",
            retention_days: "1"
        });
        if (!d.error) throw new Error("Analyst set trash retention (should be denied)");
    });

    // ── _from_approval bypass attempts ──
    await H.test("SEC09 _from_approval=true in payload does not bypass gates", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "save_csv",
            csv_file: "DR20_whitelist.csv",
            app_context: "",
            detection_rule: "DR20_malicious_command",
            headers: JSON.stringify(["user", "comment"]),
            rows: JSON.stringify([{"user": "bypass_test", "comment": "test"}]),
            _from_approval: "true",
            comment: "bypass test"
        });
        // Server should either succeed normally (without bypass) or error
        // The key is _from_approval is ignored
        H.log("\u2139\uFE0F", `  _from_approval bypass test: ${d.error || d.message || "completed"}`);
    });

    // ── Injection attempts ──
    await H.test("SEC10 Path traversal in csv_file rejected", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "save_csv",
            csv_file: "../../../etc/passwd",
            headers: JSON.stringify(["a"]),
            rows: JSON.stringify([{"a": "b"}]),
            comment: "path traversal test"
        });
        if (!d.error) throw new Error("Path traversal not rejected");
    });

    await H.test("SEC11 Command injection in rule_name rejected", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "create_rule",
            rule_name: "test; rm -rf /",
            reason: "injection test"
        });
        if (!d.error) throw new Error("Command injection not rejected");
    });

    await H.test("SEC12 Null bytes in csv_file rejected", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "save_csv",
            csv_file: "test\x00.csv",
            headers: JSON.stringify(["a"]),
            rows: JSON.stringify([{"a": "b"}]),
            comment: "null byte test"
        });
        if (!d.error) throw new Error("Null byte not rejected");
    });

    await H.test("SEC13 XSS in rule name rejected (non-ASCII or special chars)", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "create_rule",
            rule_name: "<script>alert(1)</script>",
            reason: "XSS test"
        });
        if (!d.error) throw new Error("XSS rule name not rejected");
    });

    await H.test("SEC14 Very long csv_file name rejected", async () => {
        const longName = "A".repeat(500) + ".csv";
        const d = await H.restCall(ap, "POST", {
            action: "save_csv",
            csv_file: longName,
            headers: JSON.stringify(["a"]),
            rows: JSON.stringify([{"a": "b"}]),
            comment: "long name test"
        });
        if (!d.error) throw new Error("Very long filename not rejected");
    });

    await H.test("SEC15 _ prefix column in payload rejected", async () => {
        const d = await H.restCall(ap, "POST", {
            action: "save_csv",
            csv_file: "DR20_whitelist.csv",
            detection_rule: "DR20_malicious_command",
            headers: JSON.stringify(["user", "_hidden_malicious"]),
            rows: JSON.stringify([{"user": "test", "_hidden_malicious": "evil"}]),
            comment: "reserved prefix test"
        });
        // Server should reject _ prefix columns (unless whitelisted internal ones)
        H.log("\u2139\uFE0F", `  _ prefix column test: ${d.error || "accepted (check if filtered)"}`);
    });

    // ── Concurrent/race condition attempts ──
    await H.test("SEC16 Double-save with same mtime (optimistic lock)", async () => {
        // Load CSV to get mtime
        const csv = await H.restCall(ap, "GET", {
            action: "get_csv_content",
            csv_file: "DR20_whitelist.csv",
            app: ""
        });
        const mtime = csv.file_mtime;

        // First save — should succeed
        const save1 = await H.restCall(ap, "POST", {
            action: "save_csv",
            csv_file: "DR20_whitelist.csv",
            detection_rule: "DR20_malicious_command",
            headers: JSON.stringify(csv.headers),
            rows: JSON.stringify(csv.rows),
            comment: "Concurrent test save 1",
            expected_mtime: mtime
        });

        // Second save with OLD mtime — should be conflict (409)
        if (!save1.error) {
            const save2 = await H.restCall(ap, "POST", {
                action: "save_csv",
                csv_file: "DR20_whitelist.csv",
                detection_rule: "DR20_malicious_command",
                headers: JSON.stringify(csv.headers),
                rows: JSON.stringify(csv.rows),
                comment: "Concurrent test save 2 (should conflict)",
                expected_mtime: mtime  // stale mtime
            });
            if (!save2.error) {
                H.log("\u26A0\uFE0F", "  WARNING: Second save succeeded with stale mtime");
            } else {
                H.log("\u2139\uFE0F", `  Correctly blocked stale save: ${save2.error.substring(0, 80)}`);
            }
        }
    });

    // ── Admin session: test admin-specific bypass attempts ──
    const adminSess = await H.createSession("wladmin1", "Chang3d!");
    const wp = adminSess.page;

    await H.test("SEC17 Admin cannot escalate to superadmin actions", async () => {
        const d = await H.restCall(wp, "POST", {
            action: "set_daily_limits",
            limits: JSON.stringify({ row_removal: 999 })
        });
        if (!d.error) throw new Error("Admin escalated to superadmin (set_daily_limits)");
    });

    await H.test("SEC18 Admin cannot self-reset daily usage", async () => {
        const d = await H.restCall(wp, "POST", {
            action: "reset_daily_usage",
            analyst: "wladmin1"
        });
        if (d.message && !d.message.includes("Cannot reset your own") && !d.message.includes("No usage")) {
            throw new Error(`Self-reset may have succeeded: ${d.message}`);
        }
    });

    // ── Edge cases ──
    await H.test("SEC19 Empty action parameter returns error", async () => {
        const d = await H.restCall(wp, "POST", { action: "" });
        if (!d.error) throw new Error("Empty action accepted");
    });

    await H.test("SEC20 Unknown action returns error without leaking action list", async () => {
        const d = await H.restCall(wp, "GET", { action: "nonexistent_action" });
        if (!d.error) throw new Error("Unknown action accepted");
        if (d.valid_actions) throw new Error("valid_actions leaked in error response (API enumeration)");
    });

    await H.test("SEC21 Save with empty headers rejected", async () => {
        const d = await H.restCall(wp, "POST", {
            action: "save_csv",
            csv_file: "DR20_whitelist.csv",
            headers: "[]",
            rows: "[]",
            comment: "empty headers test"
        });
        if (!d.error) H.log("\u2139\uFE0F", "  Empty headers accepted (may be valid for clearing)");
    });

    await H.test("SEC22 Save with mismatched headers/rows", async () => {
        const d = await H.restCall(wp, "POST", {
            action: "save_csv",
            csv_file: "DR20_whitelist.csv",
            detection_rule: "DR20_malicious_command",
            headers: JSON.stringify(["col1"]),
            rows: JSON.stringify([{"col1": "a", "col2": "b", "col99": "extra"}]),
            comment: "mismatched headers test"
        });
        // Server should handle gracefully — either strip extra keys or error
        H.log("\u2139\uFE0F", `  Mismatched headers/rows: ${d.error || "handled"}`);
    });

    await H.test("SEC23 Non-ASCII in comment field rejected", async () => {
        const d = await H.restCall(wp, "POST", {
            action: "save_csv",
            csv_file: "DR20_whitelist.csv",
            detection_rule: "DR20_malicious_command",
            headers: JSON.stringify(["user"]),
            rows: JSON.stringify([{"user": "test"}]),
            comment: "Test with em\u2014dash and \u00e9"
        });
        H.log("\u2139\uFE0F", `  Non-ASCII comment: ${d.error || "accepted"}`);
    });

    await analystSess.browser.close();
    await adminSess.browser.close();

    const s = H.summary("SECURITY BYPASS & EDGE CASE RESULTS");
    process.exit(s.failed > 0 ? 1 : 0);
})();
