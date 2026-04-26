/**
 * E2E regression for Control Panel long-content rendering.
 *
 * Origin: 2026-04-25 user feedback that Show Data + Download CSV in
 * Pending Requests looked messy and Recent History's Show Data wasn't
 * aligned across rows. While fixing those, also stress-tested how the
 * tables handle worst-case content (100-char rule, 100-char CSV name,
 * 500-char reason, 50-char CJK rule, 200-char rule that fails
 * approval-time validation).
 *
 * What this test asserts:
 *   1. Pending table has the new "Inspect" column (Show Data + Download CSV)
 *   2. Recent History table has its own "Inspect" column (no longer
 *      crammed into the Resolved By cell)
 *   3. Long-content rows do not blow out the page width
 *      (page horizontal overflow is the user-visible failure mode)
 *   4. Long-content cells stay within max-width:260px (word-break works)
 *   5. Show Data modal does not exceed viewport when opened on a
 *      long-content row
 *
 * The test submits its stress data through the real production endpoint
 * (POST /custom/wl_manager) as analyst1, NOT by writing directly to
 * `_approval_queue.json`. Per CLAUDE.md "Synthetic Fixtures - Banned
 * for Feature Verification", direct queue mutation is enforced-blocked.
 *
 * Cleanup: each test submission gets a deterministic request_id stored
 * in the description so the cleanup phase can find + cancel them.
 */

const H = require("./lib_helpers.cjs");

const ANALYST_USER = "analyst1", ANALYST_PASS = "Chang3d!";
const ADMIN_USER = "wladmin1", ADMIN_PASS = "Chang3d!";

// Stress payloads - sized to the server-side validators:
//   detection_rule:  max 100 chars (line 3607 of bin/wl_handler.py)
//   csv_file:        max 100 chars (line 3779)
//   approval_reason: no enforced max in submit path
const TAG = "WLLONGCONTENT";  // marker so cleanup can find these
const RULE_100  = "DR_" + TAG + "_" + "a".repeat(100 - 3 - TAG.length - 1);
const CSV_100   = "DR_" + TAG + "_csv_" + "a".repeat(100 - 7 - TAG.length - 4) + ".csv";
const REASON_500 = ("Stress test reason for long-content rendering. ".repeat(11))
    .substring(0, 500);
const CJK_RULE  = "DR_" + TAG + "_检" + "测".repeat(40);
const RULE_200  = "DR_" + TAG + "_" + "a".repeat(200 - 3 - TAG.length - 1);

(async () => {
    const { browser: aBrowser, page: aPage } =
        await H.createSession(ANALYST_USER, ANALYST_PASS);
    H.log("\u{1F4DD}", "=== CONTROL PANEL LONG-CONTENT TESTS ===");

    const submitted = [];

    // -- LC00: clean up any prior stress-test rows from the queue.
    // The Pending table paginates at 10 rows; if prior runs left
    // debris (DR_STRESS_*, DR_WLLONGCONTENT_*, DR_TOOLONG_*), our
    // freshly-submitted rows get pushed to page 2 and the layout
    // assertions can't see them. get_approval_queue is admin-only,
    // so we briefly create an admin session for cleanup, reject any
    // matching rows, then close it. analyst1 cannot fetch the queue
    // themselves.
    await H.test("LC00 Clean up prior stress-test debris (admin)", async () => {
        const cleanup = await H.createSession(ADMIN_USER, ADMIN_PASS);
        const queue = await H.restCall(cleanup.page, "GET", {
            action: "get_approval_queue"
        });
        const items = queue.queue || queue.approval_queue || [];
        const targets = items.filter(item => {
            const rule = item.detection_rule || "";
            const csv = item.csv_file || "";
            return /^DR_(STRESS|WLLONGCONTENT|TOOLONG)/.test(rule) ||
                   /^DR_(STRESS|WLLONGCONTENT|TOOLONG)/.test(csv) ||
                   rule.includes("压力") || // "压力" CJK marker
                   rule.includes("检测");   // "检测" CJK marker
        });
        for (const item of targets) {
            await H.restCall(cleanup.page, "POST", {
                action: "process_approval",
                request_id: item.request_id,
                decision: "reject",
                rejection_reason: "Stress-test cleanup before fresh run"
            });
        }
        await cleanup.browser.close();
        H.log("\u{1F9F9}", `  Rejected ${targets.length} ` +
            `pre-existing stress-test rows`);
    });

    // -- Submit stress requests as analyst1 --
    await H.test("LC01 Submit 100-char rule with 500-char reason", async () => {
        const d = await H.restCall(aPage, "POST", {
            action: "create_rule",
            detection_rule: RULE_100,
            approval_reason: REASON_500,
            comment: REASON_500,
        });
        if (d.error) throw new Error(`Submit failed: ${d.error}`);
        if (!d.request_id) throw new Error("No request_id returned");
        submitted.push(d.request_id);
    });

    await H.test("LC02 Submit 100-char CSV name", async () => {
        const d = await H.restCall(aPage, "POST", {
            action: "create_csv",
            csv_file: CSV_100,
            detection_rule: "DR_BLOCKED_TEST",
            headers: ["user", "src_ip"],
            approval_reason: TAG + " 100-char CSV stress test",
            comment: TAG + " 100-char CSV stress test",
        });
        if (d.error) throw new Error(`Submit failed: ${d.error}`);
        submitted.push(d.request_id);
    });

    await H.test("LC03 Submit 50-char CJK rule", async () => {
        const d = await H.restCall(aPage, "POST", {
            action: "create_rule",
            detection_rule: CJK_RULE,
            approval_reason: TAG + " CJK rule",
            comment: TAG + " CJK rule",
        });
        if (d.error) throw new Error(`Submit failed: ${d.error}`);
        submitted.push(d.request_id);
    });

    await H.test("LC04 Submit 200-char rule (will fail at approval-time validation)",
        async () => {
            const d = await H.restCall(aPage, "POST", {
                action: "create_rule",
                detection_rule: RULE_200,
                approval_reason: TAG + " 200-char rule, expect approval rejection",
                comment: TAG + " 200-char rule",
            });
            if (d.error) throw new Error(`Submit failed: ${d.error}`);
            submitted.push(d.request_id);
        });

    // Switch to admin session for the visual checks. Navigate AFTER all
    // submissions land so the rendered page reflects the final queue.
    const { browser: bBrowser, page: bPage } =
        await H.createSession(ADMIN_USER, ADMIN_PASS);
    await H.navigateToCP(bPage);
    // Wait for the pending table to fully render the latest rows.
    await bPage.waitForSelector("table.wl-table tbody tr", { timeout: 10000 });

    // -- Layout structure: new Inspect columns --
    await H.test("LC05 Pending table has Inspect column", async () => {
        const headers = await bPage.locator(
            "table.wl-table"
        ).first().locator("thead th").allInnerTexts();
        if (!headers.includes("Inspect")) {
            throw new Error("Pending table missing 'Inspect' column. Headers: "
                + JSON.stringify(headers));
        }
    });

    await H.test("LC06 Recent History table has Inspect column",
        async () => {
            const tableCount = await bPage.locator("table.wl-table").count();
            if (tableCount < 2) {
                throw new Error(`Expected >=2 tables, found ${tableCount}`);
            }
            const headers = await bPage.locator(
                "table.wl-table"
            ).nth(1).locator("thead th").allInnerTexts();
            if (!headers.includes("Inspect")) {
                throw new Error("Recent History missing 'Inspect' column. " +
                    "Headers: " + JSON.stringify(headers));
            }
        });

    // -- No horizontal page overflow --
    await H.test("LC07 Page does not overflow horizontally with long content",
        async () => {
            const bodyBox = await bPage.locator("body").boundingBox();
            const viewport = bPage.viewportSize();
            // Allow 5px tolerance for rendering rounding
            if (bodyBox && bodyBox.width > viewport.width + 5) {
                throw new Error(
                    `Page horizontal overflow: body.width=${bodyBox.width} ` +
                    `> viewport.width=${viewport.width}. ` +
                    `The Pending/History tables should be wrapped in ` +
                    `<div style="overflow-x:auto"> so they scroll inside ` +
                    `their container, not at the page level.`);
            }
        });

    await H.test("LC08 Pending + History tables have overflow-x:auto wrappers",
        async () => {
            // We check that each table's parent is a DIV with overflow.
            // boundingBox + tagName via locator avoid evaluating in-page.
            for (let i = 0; i < 2; i++) {
                const tableLoc = bPage.locator("table.wl-table").nth(i);
                const wrap = tableLoc.locator("xpath=..");
                const tag = await wrap.evaluate((node) => node.tagName);
                const ovx = await wrap.evaluate(
                    (node) => getComputedStyle(node).overflowX
                );
                if (tag !== "DIV") {
                    throw new Error(`Table ${i} not wrapped in DIV: got ${tag}`);
                }
                if (ovx !== "auto" && ovx !== "scroll") {
                    throw new Error(
                        `Table ${i} wrapper overflowX=${ovx}, ` +
                        `expected auto or scroll`);
                }
            }
        });

    // -- Word-break is constraining cells --
    await H.test("LC09 Long-rule cell stays within max-width", async () => {
        // Find the row with the WLLONGCONTENT marker and check column 4
        // (Detection Rule) bounding-box width. Use locator filter, not
        // page-level evaluation.
        const stressRows = bPage.locator("table.wl-table tbody tr").filter({
            hasText: TAG
        });
        const rowCount = await stressRows.count();
        if (rowCount === 0) {
            throw new Error(`No stress rows found in pending table. ` +
                `Submitted ${submitted.length} requests; check that ` +
                `analyst1 + admin can both see the queue.`);
        }
        for (let i = 0; i < rowCount; i++) {
            const ruleCell = stressRows.nth(i).locator("td").nth(3);
            const box = await ruleCell.boundingBox();
            if (!box) continue;
            // word-break + max-width:260px -> cell should be <= ~290px
            // (260px max-width + ~20px padding)
            if (box.width > 290) {
                const text = (await ruleCell.innerText()).slice(0, 30);
                throw new Error(
                    `Detection Rule cell too wide: ${box.width}px ` +
                    `for content "${text}...". Expected <= 290px ` +
                    `(max-width:260px + padding). word-break may not ` +
                    `be applied - check .wl-cp-truncate class on the cell.`);
            }
        }
    });

    // -- Show Data modal handles long content --
    await H.test("LC10 Show Data modal stays within viewport for long-rule entry",
        async () => {
            // Click Show Data on the first stress row
            const firstStress = bPage.locator(
                "table.wl-table tbody tr"
            ).filter({ hasText: TAG }).first();
            const showBtn = firstStress.locator(".wl-cp-show-data-btn");
            if (await showBtn.count() === 0) {
                throw new Error("No Show Data button on stress row");
            }
            await showBtn.click();
            await bPage.waitForSelector(".wl-modal-overlay", { timeout: 5000 });

            const modalLoc = bPage.locator(".wl-modal-overlay .wl-modal");
            const box = await modalLoc.boundingBox();
            const viewport = bPage.viewportSize();
            if (box.x + box.width > viewport.width + 5) {
                throw new Error(
                    `Modal overflows viewport: right=${box.x + box.width} ` +
                    `> viewportWidth=${viewport.width}`);
            }
            if (box.x < -5) {
                throw new Error(
                    `Modal extends beyond left edge: x=${box.x}`);
            }

            // Header should have word-break:break-word so 100-char rule
            // names wrap. Read the computed style via a single locator
            // evaluation (only place we need page-side computation).
            const headerWordBreak = await bPage.locator(
                ".wl-modal-header"
            ).first().evaluate(
                (node) => getComputedStyle(node).wordBreak
            );
            if (headerWordBreak !== "break-word"
                && headerWordBreak !== "break-all") {
                throw new Error(
                    `Modal header word-break=${headerWordBreak}, ` +
                    `expected break-word. 100-char rule names will overflow.`);
            }

            // Close modal by clicking overlay
            await bPage.keyboard.press("Escape");
        });

    // -- Cleanup: cancel all submitted requests --
    H.log("\u{1F9F9}", `Cleaning up ${submitted.length} submitted requests...`);
    for (const reqId of submitted) {
        try {
            await H.restCall(aPage, "POST", {
                action: "cancel_request",
                request_id: reqId
            });
        } catch (e) {
            H.log("WARN", `  Cancel failed for ${reqId}: ${e.message}`);
        }
    }

    await aBrowser.close();
    await bBrowser.close();
    H.summary("CONTROL PANEL LONG-CONTENT");
})();
