/**
 * E2E test for the Audit Trail dashboard's split Action dropdowns (build 581+).
 *
 * Design:
 *   Two side-by-side dropdowns ("General Action" + "Admin Action") split the
 *   former 37-choice list by category. Both drive the shared `action_filter`
 *   token via <change> handlers. Mutual exclusion is enforced via JS in
 *   audit_trail.js: picking a non-default value in one dropdown resets the
 *   other to its "All ___ Actions" default. The reset is done at the
 *   component level (settings.set("value", "*")) with a guard flag to
 *   prevent infinite ping-pong between the two dropdowns' change listeners.
 *
 * Verifies:
 *   1. Initial state: both dropdowns show "All ___ Actions"
 *   2. Pick General -> Admin stays at "All Admin Actions"
 *   3. Pick Admin -> General resets to "All General Actions" (mutual reset)
 *   4. Pick "All Admin Actions" -> filter cleared, no other side-effect
 *   5. Newly added admin actions (build 576+) are selectable + reset General
 *   6. Reverse mutual reset: pick General after Admin -> Admin resets
 *   7. Both popovers render their full choice set
 *
 * Run: node tests/e2e/test_audit_dropdowns.cjs
 */
const { createSession, test, summary } = require("./lib_helpers.cjs");

const AUDIT_URL = "http://localhost:8000/en-US/app/wl_manager/audit";

async function gotoAudit(page) {
    await page.goto(AUDIT_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForFunction(() => {
        return !!document.querySelector('button[aria-label="All General Actions"]')
            && !!document.querySelector('button[aria-label="All Admin Actions"]');
    }, { timeout: 25000 });
    await page.waitForTimeout(2000);
}

async function readDropdownLabels(page) {
    return page.evaluate(() => {
        const out = {};
        document.querySelectorAll(".input.input-dropdown").forEach(container => {
            const label = container.querySelector("label");
            const button = container.querySelector('button[data-test="select"]');
            if (!label || !button) return;
            const labelText = (label.innerText || label.textContent || "").trim();
            const valueText = button.getAttribute("aria-label") || (button.innerText || "").trim();
            if (labelText === "General Action") out.general = valueText;
            else if (labelText === "Admin Action") out.admin = valueText;
        });
        return out;
    });
}

// The Filter: indicator panel was removed in build 581. The truth is now
// the JS-enforced mutual exclusion: only one dropdown is non-default at a time.

async function pickOption(page, dropdownLabel, optionText) {
    await page.evaluate((label) => {
        const containers = document.querySelectorAll(".input.input-dropdown");
        for (const c of containers) {
            const lbl = c.querySelector("label");
            if (lbl && (lbl.innerText || "").trim() === label) {
                const btn = c.querySelector('button[data-test="select"]');
                if (btn) { btn.click(); return; }
            }
        }
        throw new Error("Dropdown not found: " + label);
    }, dropdownLabel);

    await page.waitForFunction((txt) => {
        const items = document.querySelectorAll('[role="option"], [role="menuitem"]');
        for (const el of items) {
            if ((el.innerText || el.textContent || "").trim() === txt) return true;
        }
        return false;
    }, optionText, { timeout: 10000 });

    await page.evaluate((txt) => {
        const items = document.querySelectorAll('[role="option"], [role="menuitem"]');
        for (const el of items) {
            if ((el.innerText || el.textContent || "").trim() === txt) { el.click(); return; }
        }
        throw new Error("Option not found in popover: " + txt);
    }, optionText);

    await page.waitForTimeout(900);
}

(async () => {
    const { browser, page } = await createSession("admin", "Chang3d!");
    page.on("pageerror", e => console.log("PAGEERROR:", e.message));

    await gotoAudit(page);

    await test("S1: Initial state — both dropdowns show 'All ___ Actions'", async () => {
        const labels = await readDropdownLabels(page);
        if (labels.general !== "All General Actions") throw new Error(`General = "${labels.general}"`);
        if (labels.admin !== "All Admin Actions") throw new Error(`Admin = "${labels.admin}"`);
    });

    await test("S2: Pick 'Row Added' in General — Admin stays at 'All Admin Actions'", async () => {
        await pickOption(page, "General Action", "Row Added");
        const labels = await readDropdownLabels(page);
        if (labels.general !== "Row Added") throw new Error(`General = "${labels.general}"`);
        if (labels.admin !== "All Admin Actions") throw new Error(`Admin should be 'All' but is "${labels.admin}"`);
    });

    await test("S3: Pick 'Lockdown Activated' in Admin — General resets to 'All General Actions' (mutual reset)", async () => {
        await pickOption(page, "Admin Action", "Lockdown Activated");
        const labels = await readDropdownLabels(page);
        if (labels.admin !== "Lockdown Activated") throw new Error(`Admin = "${labels.admin}"`);
        if (labels.general !== "All General Actions") throw new Error(`General should reset to 'All' but is "${labels.general}"`);
    });

    await test("S4: Pick 'All Admin Actions' — both dropdowns at default, no side-effect", async () => {
        await pickOption(page, "Admin Action", "All Admin Actions");
        const labels = await readDropdownLabels(page);
        if (labels.general !== "All General Actions") throw new Error(`General = "${labels.general}"`);
        if (labels.admin !== "All Admin Actions") throw new Error(`Admin = "${labels.admin}"`);
    });

    await test("S5: Newly added admin action 'Bootstrap CSV Hashes' is selectable + resets General", async () => {
        // First put General into a non-default state to confirm mutual reset fires
        await pickOption(page, "General Action", "Row Removed");
        await pickOption(page, "Admin Action", "Bootstrap CSV Hashes");
        const labels = await readDropdownLabels(page);
        if (labels.admin !== "Bootstrap CSV Hashes") throw new Error(`Admin = "${labels.admin}"`);
        if (labels.general !== "All General Actions") throw new Error(`General should reset to 'All' but is "${labels.general}"`);
    });

    await test("S6: Reverse mutual-reset — pick General after Admin -> Admin resets", async () => {
        // After S5: Admin = "Bootstrap CSV Hashes", General = "All General Actions"
        await pickOption(page, "General Action", "Column Renamed");
        const labels = await readDropdownLabels(page);
        if (labels.general !== "Column Renamed") throw new Error(`General = "${labels.general}"`);
        if (labels.admin !== "All Admin Actions") throw new Error(`Admin should reset to 'All' but is "${labels.admin}"`);
    });

    await test("S7: General popover renders 24 choices (1 'All' + 23 actions)", async () => {
        const count = await page.evaluate(() => {
            return new Promise(resolve => {
                const containers = document.querySelectorAll(".input.input-dropdown");
                for (const c of containers) {
                    const lbl = c.querySelector("label");
                    if (lbl && (lbl.innerText || "").trim() === "General Action") {
                        c.querySelector('button[data-test="select"]').click();
                        setTimeout(() => {
                            const items = document.querySelectorAll('[role="option"], [role="menuitem"]');
                            document.body.click();
                            resolve(items.length);
                        }, 800);
                        return;
                    }
                }
                resolve(-1);
            });
        });
        if (count < 24) throw new Error(`General has ${count} choices (expected >= 24)`);
    });

    await test("S8: Admin popover renders 20 choices (1 'All' + 19 actions including the 5 new)", async () => {
        await page.waitForTimeout(500);
        const count = await page.evaluate(() => {
            return new Promise(resolve => {
                const containers = document.querySelectorAll(".input.input-dropdown");
                for (const c of containers) {
                    const lbl = c.querySelector("label");
                    if (lbl && (lbl.innerText || "").trim() === "Admin Action") {
                        c.querySelector('button[data-test="select"]').click();
                        setTimeout(() => {
                            const items = document.querySelectorAll('[role="option"], [role="menuitem"]');
                            document.body.click();
                            resolve(items.length);
                        }, 800);
                        return;
                    }
                }
                resolve(-1);
            });
        });
        if (count < 20) throw new Error(`Admin has ${count} choices (expected >= 20)`);
    });

    // ────────────────────────────────────────────────────────────────
    // Rapid-switching race condition test (bug from build 584)
    //
    // Reproduces: pick General → pick Admin → pick General again.
    // The third pick must set action_filter to the General value,
    // NOT to "*" (which is what the reset-target's stale XML <change>
    // handler used to clobber it with).
    // ────────────────────────────────────────────────────────────────
    await test("S9: Rapid switch: General → Admin → General — action_filter correct on 3rd pick", async () => {
        // Start clean
        await pickOption(page, "General Action", "All General Actions");
        await pickOption(page, "Admin Action", "All Admin Actions");
        await page.waitForTimeout(300);

        // Step 1: pick General = Row Added
        await pickOption(page, "General Action", "Row Added");
        // Step 2: pick Admin = Lockdown Activated
        await pickOption(page, "Admin Action", "Lockdown Activated");
        // Step 3: pick General = CSV Removed (the failing case)
        await pickOption(page, "General Action", "CSV Removed");

        // Verify: action_filter must be "csv_removed", NOT "*"
        const tokenVal = await page.evaluate(() => {
            return new Promise(resolve => {
                window.requirejs(["splunkjs/mvc"], function(mvc) {
                    var sub = mvc.Components.get("submitted");
                    resolve(sub ? sub.get("action_filter") : null);
                });
            });
        });
        if (tokenVal !== "csv_removed") {
            throw new Error(`action_filter = "${tokenVal}" (expected "csv_removed") — race condition`);
        }
        // Also verify visual state
        const labels = await readDropdownLabels(page);
        if (labels.general !== "CSV Removed") throw new Error(`General visual = "${labels.general}"`);
        if (labels.admin !== "All Admin Actions") throw new Error(`Admin visual = "${labels.admin}"`);
    });

    await test("S10: Rapid switch x5 — action_filter tracks the last pick correctly", async () => {
        await pickOption(page, "Admin Action", "Lockdown Activated");
        await pickOption(page, "General Action", "Row Edited");
        await pickOption(page, "Admin Action", "Admin Limit Changed");
        await pickOption(page, "General Action", "Revert");
        await pickOption(page, "Admin Action", "Factory Reset");

        const tokenVal = await page.evaluate(() => {
            return new Promise(resolve => {
                window.requirejs(["splunkjs/mvc"], function(mvc) {
                    var sub = mvc.Components.get("submitted");
                    resolve(sub ? sub.get("action_filter") : null);
                });
            });
        });
        if (tokenVal !== "factory_reset_executed") {
            throw new Error(`action_filter = "${tokenVal}" (expected "factory_reset_executed")`);
        }
    });

    const result = summary("AUDIT DASHBOARD DROPDOWN SPLIT");
    await browser.close();
    process.exit(result.failed > 0 ? 1 : 0);
})();
