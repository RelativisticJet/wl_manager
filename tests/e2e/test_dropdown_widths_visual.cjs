/**
 * Per-pixel verification that the four Whitelist Manager dropdowns
 * (Detection Rule, CSV File, Revert to Version, Search) render at
 * identical widths after the 2026-05-20 CSS fix
 * (.wl-dropdown-group: min-width:300px → width:300px).
 *
 * Why this exists: the original screenshot the user provided showed
 * one dropdown noticeably wider than the others. The root cause was
 * a native <select> whose longest option text expanded its parent
 * .wl-dropdown-group past the 300px floor. min-width was a floor,
 * not a clamp; switching to width fixes it.
 *
 * Runs against WL_E2E_BROWSER (chromium | firefox | webkit) so we
 * can sweep both engines per the user's "per-pixel test" request.
 *
 * Cleanup: read-only — no state mutation, no rules created.
 */

const H = require("./lib_helpers.cjs");

(async () => {
    const { browser, page } = await H.createSession("superadmin1", "Chang3d!");
    H.log("\u{1F4DD}", "=== DROPDOWN WIDTH PARITY ===");

    try {
        await H.navigateToWM(
            page,
            "rule=DR130_privilege_escalation&csv=DR130_priv_escalation.csv"
        );
        // Allow JS to render the Revert + Search groups (they are
        // dynamically appended, not in the static XML).
        await page.waitForSelector("#wl-revert-select", { timeout: 10000 });
        await page.waitForTimeout(500);

        const measurements = await page.evaluate(() => {
            const groups = Array.from(document.querySelectorAll(
                "#wl-dropdowns > .wl-dropdown-group"
            ));
            return groups.map((g) => ({
                label: (g.querySelector(".wl-dropdown-label") || {}).textContent
                    || "(no label)",
                width: Math.round(g.getBoundingClientRect().width),
                visible: g.offsetParent !== null,
            }));
        });

        await H.test("All 4 dropdowns are visible", () => {
            const visible = measurements.filter((m) => m.visible);
            if (visible.length !== 4) {
                throw new Error(
                    `expected 4 visible groups, got ${visible.length}: ` +
                    JSON.stringify(measurements)
                );
            }
        });

        await H.test("All 4 dropdowns measure exactly 300px wide", () => {
            const widths = measurements.map((m) => m.width);
            const unique = Array.from(new Set(widths));
            if (unique.length !== 1 || unique[0] !== 300) {
                throw new Error(
                    `dropdowns must all be 300px wide; got: ` +
                    JSON.stringify(measurements)
                );
            }
        });

        await H.test("Revert dropdown stays 300px even with long option text", () => {
            // The original failure mode: <select id="wl-revert-select"> had
            // an option like "06-04-2026 01:59:41 (current)" whose intrinsic
            // text width pushed the parent group to ~374px on Chromium.
            // After the fix, parent group has explicit width:300px so the
            // select's intrinsic content size no longer affects layout.
            const revert = measurements.find((m) => m.label === "Revert to Version");
            if (!revert) {
                throw new Error("Revert to Version group not found: "
                    + JSON.stringify(measurements));
            }
            if (revert.width !== 300) {
                throw new Error(
                    `Revert dropdown is ${revert.width}px, expected 300px (regression!)`
                );
            }
        });

        H.summary(`DROPDOWN WIDTH PARITY (${process.env.WL_E2E_BROWSER || "chromium"})`);
    } finally {
        await browser.close();
    }
})();
