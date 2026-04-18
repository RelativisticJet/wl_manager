/**
 * Stress test for Audit Trail Data Changes drilldown with 5000 rows.
 *
 * Flow:
 *   1. Create a test detection rule + CSV
 *   2. Add 5000 rows via save_csv (generates massive audit event)
 *   3. Remove the 5000 rows (generates massive removal audit event)
 *   4. Navigate to Audit Trail, verify value truncation shows "... +N more"
 *   5. Click drilldown, verify detail panel renders all entries
 *   6. Click Close Details, verify panel hides
 *   7. Cleanup: delete the test rule + CSV
 *
 * Run: WL_TEST_HARNESS=1 node tests/e2e/test_audit_stress.cjs
 */
const { createSession, test, summary, assertTestHarness, restCall } = require("./lib_helpers.cjs");

const TEST_RULE = "STRESS_AUDIT_5K";
const TEST_CSV = "STRESS_audit_5k.csv";
const ROW_COUNT = 5000;

(async () => {
    assertTestHarness();
    const { browser, page } = await createSession("admin", "Chang3d!");
    page.on("pageerror", e => console.log("PAGEERROR:", e.message));

    // ── Setup: create rule + CSV with 5000 rows ──────────────────

    async function post(params) { return restCall(page, "POST", params); }
    async function get(params) { return restCall(page, "GET", params); }

    await test("Setup: clean up leftover from previous run (if any)", async () => {
        // Try to permanently remove any leftover rule/CSV
        await post({ action: "remove_csv", csv_file: TEST_CSV, detection_rule: TEST_RULE, removal_type: "permanent", comment: "pre-cleanup" }).catch(() => {});
        await post({ action: "remove_rule", rule_name: TEST_RULE, removal_type: "permanent", comment: "pre-cleanup" }).catch(() => {});
        // Also purge from trash if trashed
        await post({ action: "purge_trash_item", item_type: "csv", name: TEST_CSV, comment: "pre-cleanup" }).catch(() => {});
        await post({ action: "purge_trash_item", item_type: "rule", name: TEST_RULE, comment: "pre-cleanup" }).catch(() => {});
        await page.waitForTimeout(1000);
        console.log("    Pre-cleanup done");
    });

    await test("Setup: create detection rule", async () => {
        const d = await post({
            action: "create_rule",
            detection_rule: TEST_RULE,
            description: "Stress test for audit drilldown",
            reason: "E2E stress test"
        });
        if (d.error) throw new Error("create_rule: " + d.error);
        console.log("    Rule: " + (d.message || "ok"));
    });

    await test("Setup: create empty CSV with headers only", async () => {
        const d = await post({
            action: "create_csv",
            csv_file: TEST_CSV,
            detection_rule: TEST_RULE,
            headers: ["host", "user", "reason"],
            rows: []
        });
        if (d.error) throw new Error("create_csv: " + d.error);
        console.log("    Empty CSV created");
    });

    await test("Add " + ROW_COUNT + " rows via save_csv (generates row_added audit event)", async () => {
        // Get current CSV to obtain the content hash (optimistic locking)
        const csv = await get({ action: "get_csv_content", csv_file: TEST_CSV });
        if (csv.error) throw new Error("get_csv: " + csv.error);
        const hash = csv.content_hash;
        if (!hash) throw new Error("No content hash returned from get_csv");

        const rows = [];
        for (let i = 0; i < ROW_COUNT; i++) {
            rows.push({ host: "host_" + i, user: "user_" + i, reason: "stress_row_" + i });
        }
        const d = await post({
            action: "save_csv",
            detection_rule: TEST_RULE,
            csv_file: TEST_CSV,
            rows: rows,
            expected_content_hash: hash,
            comment: "Adding " + ROW_COUNT + " rows for stress test"
        });
        if (d.error) throw new Error("save_csv add: " + d.error);
        console.log("    Saved " + ROW_COUNT + " rows");
    });

    await test("Remove all " + ROW_COUNT + " rows via save_csv (empty)", async () => {
        const csv = await get({ action: "get_csv_content", csv_file: TEST_CSV });
        if (csv.error) throw new Error("get_csv: " + csv.error);
        const hash = csv.content_hash;

        const d = await post({
            action: "save_csv",
            detection_rule: TEST_RULE,
            csv_file: TEST_CSV,
            rows: [],
            expected_content_hash: hash,
            comment: "Removing all rows for stress test"
        });
        if (d.error) throw new Error("save_csv empty: " + d.error);
        console.log("    All rows removed");
    });

    // Wait for Splunk to index the events
    await page.waitForTimeout(5000);

    // ── Test: audit drilldown on the 5000-row event ──────────────

    await test("Audit Trail: value column shows truncated preview with '... +N more'", async () => {
        await page.goto("http://localhost:8000/en-US/app/wl_manager/audit", { waitUntil: "domcontentloaded", timeout: 60000 });
        await page.waitForFunction(() => !!document.querySelector('button[aria-label="All General Actions"]'), { timeout: 25000 });
        await page.waitForTimeout(5000);

        // Filter by our stress test detection rule to narrow results
        // (set rule_filter to STRESS_AUDIT_5K)
        await page.evaluate(() => {
            for (const c of document.querySelectorAll(".input.input-dropdown")) {
                if ((c.querySelector("label")?.innerText || "").trim() === "Detection Rule") {
                    c.querySelector('button[data-test="select"]').click();
                    return;
                }
            }
        });
        await page.waitForFunction(() => {
            return Array.from(document.querySelectorAll('[role="option"], [role="menuitem"]'))
                .some(e => (e.innerText || "").includes("STRESS_AUDIT_5K"));
        }, { timeout: 15000 });
        await page.evaluate(() => {
            for (const e of document.querySelectorAll('[role="option"], [role="menuitem"]')) {
                if ((e.innerText || "").includes("STRESS_AUDIT_5K")) { e.click(); return; }
            }
        });
        await page.waitForTimeout(3000);

        // Scroll to Data Changes table
        await page.evaluate(() => {
            const titles = document.querySelectorAll(".panel-title, h3, h2");
            for (const t of titles) {
                if ((t.innerText || "").trim() === "Data Changes") {
                    t.scrollIntoView({ block: "start" });
                    break;
                }
            }
        });
        await page.waitForTimeout(3000);

        // Check that a value cell contains "... +" truncation
        const hasMore = await page.evaluate(() => {
            const cells = document.querySelectorAll("#audit_table_changes table tbody td");
            for (const c of cells) {
                const text = c.innerText || "";
                if (text.includes("... +") && text.includes("more")) return text.substring(text.indexOf("... +"), text.indexOf("more") + 4);
            }
            return null;
        });
        if (!hasMore) throw new Error("No truncation indicator found in value cells");
        console.log("    Found truncation: " + hasMore);
    });

    await test("Drilldown on 5000-row event: detail panel renders all value entries", async () => {
        // Click the first Data Changes row (should be one of our 5000-row events)
        const cell = page.locator("#audit_table_changes table tbody tr:first-child td:first-child");
        await cell.click({ force: true });

        // Wait for detail panel to appear
        const appeared = await page.waitForFunction(() => {
            const el = document.getElementById("audit_detail_values");
            if (!el) return false;
            var walker = el;
            while (walker && !walker.classList.contains("dashboard-row")) walker = walker.parentElement;
            return walker && window.getComputedStyle(walker).display !== "none";
        }, { timeout: 15000 }).then(() => true).catch(() => false);
        if (!appeared) throw new Error("Detail panel did not appear");

        // Wait for the search to complete (5000+ rows takes time)
        await page.waitForTimeout(10000);

        // Check if the detail table has data (not "No results found")
        const detailState = await page.evaluate(() => {
            const table = document.querySelector("#audit_detail_values table");
            if (!table) return "no_table";
            const rows = table.querySelectorAll("tbody tr");
            if (rows.length === 0) return "no_rows";
            // Also check the pagination — are there multiple pages?
            const pageInfo = document.querySelector("#audit_detail_values .pagination-results, #audit_detail_values .results-count");
            const infoText = pageInfo ? pageInfo.innerText : "";
            return "rows:" + rows.length + " pagination:" + infoText;
        });
        if (detailState === "no_table" || detailState === "no_rows") {
            throw new Error("Detail panel shows: " + detailState);
        }
        console.log("    Detail state: " + detailState);
    });

    await test("Close Details button works after viewing 5000-entry panel", async () => {
        await page.locator("#wl-close-details").click({ force: true });
        await page.waitForTimeout(1500);

        const hidden = await page.evaluate(() => {
            var el = document.getElementById("audit_detail_values");
            if (!el) return true;
            var walker = el;
            while (walker && !walker.classList.contains("dashboard-row")) walker = walker.parentElement;
            return walker ? window.getComputedStyle(walker).display === "none" : true;
        });
        if (!hidden) throw new Error("Detail panel still visible after Close");
    });

    // ── Cleanup ──────────────────────────────────────────────────

    await test("Cleanup: delete test rule + CSV", async () => {
        const csvDel = await post({
            action: "remove_csv",
            csv_file: TEST_CSV,
            detection_rule: TEST_RULE,
            removal_type: "permanent",
            comment: "E2E stress test cleanup"
        });
        console.log("    CSV: " + (csvDel.message || csvDel.error || "done"));
        const ruleDel = await post({
            action: "remove_rule",
            rule_name: TEST_RULE,
            removal_type: "permanent",
            comment: "E2E stress test cleanup"
        });
        console.log("    Rule: " + (ruleDel.message || ruleDel.error || "done"));
    });

    const result = summary("AUDIT STRESS TEST (5000 rows)");
    await browser.close();
    process.exit(result.failed > 0 ? 1 : 0);
})();
