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
            return groups.map((g) => {
                // Each group's "control" is the visible input/select/dropdown:
                //  - Detection Rule: <input class="wl-search-input">
                //  - CSV File:       <div class="wl-csv-display">
                //  - Revert:         <select class="wl-select">
                //  - Search:         <input class="wl-search-field">
                // We measure the OUTERMOST control element because that's
                // the box whose bottom-edge the user sees aligning across
                // the row. Without this normalization, a height delta in
                // any one widget pushes that group's bottom below the
                // others — caught visually in 2026-05-20 screenshot.
                const ctrl = g.querySelector(
                    ".wl-csv-display, .wl-search-input, .wl-search-field, .wl-select"
                );
                const cRect = ctrl ? ctrl.getBoundingClientRect() : null;
                return {
                    label: (g.querySelector(".wl-dropdown-label") || {}).textContent
                        || "(no label)",
                    width: Math.round(g.getBoundingClientRect().width),
                    visible: g.offsetParent !== null,
                    controlHeight: cRect ? Math.round(cRect.height) : null,
                    controlBottom: cRect ? Math.round(cRect.bottom) : null,
                };
            });
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

        await H.test("All 4 dropdown controls share the same height", () => {
            // Origin: 2026-05-20 build-665. Before the fix, .wl-csv-display
            // (a <div> in the CSV-File widget) rendered ~36px while the
            // other three (<input>/<select>) rendered ~32px — same padding
            // + border but <div> uses a taller inherited line-height. The
            // 4px differential pushed the CSV-File's bottom edge below its
            // neighbours and was caught visually in the user's screenshot.
            // We allow 1px rounding tolerance because subpixel layout can
            // produce values like 31.9 / 32.0 / 32.1 across engines.
            const heights = measurements.map((m) => m.controlHeight);
            const min = Math.min.apply(null, heights);
            const max = Math.max.apply(null, heights);
            if (max - min > 1) {
                throw new Error(
                    `dropdown control heights diverge by ${max - min}px ` +
                    `(min=${min}, max=${max}); expected <= 1px tolerance. ` +
                    JSON.stringify(measurements)
                );
            }
        });

        await H.test("All 4 dropdown controls share the same bottom edge", () => {
            // The user-visible failure mode is BOTTOM-EDGE misalignment,
            // not control height per se. Even if heights matched, a
            // top-edge offset would still produce a bottom-edge drift.
            // This is the assertion that most directly matches what
            // the screenshot showed.
            const bottoms = measurements.map((m) => m.controlBottom);
            const min = Math.min.apply(null, bottoms);
            const max = Math.max.apply(null, bottoms);
            if (max - min > 1) {
                throw new Error(
                    `dropdown control bottom edges diverge by ${max - min}px ` +
                    `(min=${min}, max=${max}). ` +
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

        // QA round-3 follow-up (2026-05-20): the QA reviewer flagged that
        // clamping the group to 300px raises the possibility of the
        // <select>'s CLOSED-state text being truncated (with `...`) if the
        // selected option's text exceeds what fits in 300px minus padding
        // and arrow chrome. The OPEN popup is browser-controlled and
        // auto-sizes to option text, so that's not at risk. But the
        // closed-state is the default visible state and would be a
        // user-visible regression if truncated.
        await H.test("Revert closed-state shows full selected option text", async () => {
            const truncation = await page.evaluate(() => {
                const sel = document.querySelector("#wl-revert-select");
                if (!sel) return { error: "select not found" };
                const opt = sel.options[sel.selectedIndex];
                // scrollWidth vs clientWidth tells us if content overflows.
                // For native <select>, scrollWidth equals the rendered
                // intrinsic content width; clientWidth equals the visible
                // box width. If they differ, the visible text is truncated.
                return {
                    selectedText: opt ? opt.text : null,
                    scrollWidth: sel.scrollWidth,
                    clientWidth: sel.clientWidth,
                    overflows: sel.scrollWidth > sel.clientWidth,
                };
            });
            // We tolerate up to a 4px scrollWidth/clientWidth gap because
            // some browsers report the arrow chrome inconsistently in
            // clientWidth. Beyond 4px is a real truncation signal.
            if (truncation.scrollWidth > truncation.clientWidth + 4) {
                throw new Error(
                    `Revert selected text appears truncated: ` +
                    `scrollWidth=${truncation.scrollWidth}, ` +
                    `clientWidth=${truncation.clientWidth}, ` +
                    `selected="${truncation.selectedText}". ` +
                    `Either the 300px clamp is too narrow for current ` +
                    `timestamp format, or the test rule's "current" ` +
                    `option text changed shape.`
                );
            }
        });

        H.summary(`DROPDOWN WIDTH PARITY (${process.env.WL_E2E_BROWSER || "chromium"})`);
    } finally {
        await browser.close();
    }
})();
