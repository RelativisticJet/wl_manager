/**
 * Accessibility audit — wl_manager dashboards (Ring 5 Day 4).
 *
 * Scans the three main user-facing dashboards with axe-core for
 * WCAG 2.1 Level AA conformance:
 *
 *   1. /app/wl_manager/whitelist_manager — the main editing UI
 *   2. /app/wl_manager/control_panel      — admin settings
 *   3. /app/wl_manager/audit              — audit trail viewer
 *
 * Logs in as `superadmin1` so all UI is visible (admin-only panels,
 * superadmin-only controls in the control panel). For pages with
 * role-conditional UI, an analyst-tier scan would miss
 * admin-rendered subtrees — superadmin1 is the maximum-coverage
 * pass.
 *
 * Exit code:
 *   0 if every page passes (no critical/serious violations
 *     outside baseline.json)
 *   1 if any page has critical/serious violations not in the
 *     baseline
 *   2 for an unrecoverable error (browser launch failed,
 *     login failed, network down)
 *
 * Reports written to tests/a11y/reports/:
 *   - <label>.json — full axe-core results per page
 *   - summary.json — one-line summary per page + suppression count
 *
 * Caveats:
 *   - Splunk's own DOM (chrome, header, footer, app nav) is
 *     OUT of our control. Violations rooted in Splunk-bundled
 *     selectors should be added to baseline.json with a
 *     "Splunk-bundled, not our DOM" reason.
 *   - axe-core can't catch every a11y issue — keyboard-only
 *     navigation, screen-reader announcement quality, and
 *     reduced-motion preferences need manual verification.
 *     This audit is the AUTOMATED floor, not the ceiling.
 */

const path = require("path");
const H = require("../e2e/lib_helpers.cjs");
const A = require("./lib_a11y.cjs");

const REPORTS_DIR = path.join(__dirname, "reports");
const SUPER_USER = "superadmin1";
const SUPER_PASS = "Chang3d!";

// Pages to scan. Each entry has a label (used for reports
// filename), a path under /en-US/app/wl_manager/, and a
// "ready selector" we wait for before scanning.
const PAGES = [
    {
        label: "whitelist_manager",
        urlPath: "/en-US/app/wl_manager/whitelist_manager",
        readySelector: "#rule-search",
    },
    {
        label: "control_panel",
        urlPath: "/en-US/app/wl_manager/control_panel",
        // Control panel renders the Approval Queue tab first
        // by default; its container is a reliable ready signal.
        readySelector: "#cp-tab-content",
    },
    {
        label: "audit",
        urlPath: "/en-US/app/wl_manager/audit",
        // The audit dashboard is a SimpleXML view; the timestamp
        // dropdown is rendered last and reliably indicates the
        // dashboard is fully loaded.
        readySelector: "input[type='text']",
    },
];


async function main() {
    const { browser, page } = await H.createSession(SUPER_USER, SUPER_PASS);

    const allResults = [];
    let unrecoverable = false;

    try {
        const baseline = A.loadBaseline();

        for (const cfg of PAGES) {
            console.log(`[a11y] scanning ${cfg.label}...`);
            try {
                await page.goto(
                    `http://localhost:8000${cfg.urlPath}`,
                    { waitUntil: "domcontentloaded", timeout: 30000 },
                );
                await page.waitForSelector(cfg.readySelector, {
                    timeout: 15000,
                });
                // Give Splunk's MVC + our async JS another beat to
                // settle before scanning. 2s matches the
                // navigateToWM helper's pattern.
                await page.waitForTimeout(2000);

                const raw = await A.scanPage(page, { label: cfg.label });
                const filtered = A.filterAgainstBaseline(raw, baseline);
                console.log("  " + A.summarize(filtered));
                if (filtered.__suppressed_rule_ids.length > 0) {
                    console.log(
                        `  suppressed by baseline: ` +
                        filtered.__suppressed_rule_ids.join(", "),
                    );
                }
                allResults.push(filtered);
            } catch (err) {
                console.error(
                    `[a11y] FAILED to scan ${cfg.label}: ${err.message}`,
                );
                unrecoverable = true;
            }
        }
    } finally {
        await browser.close();
    }

    if (allResults.length === 0) {
        console.error("[a11y] no pages successfully scanned");
        process.exit(2);
    }

    const summary = A.writeReports(allResults, REPORTS_DIR);
    console.log("\n=== SUMMARY ===");
    for (const s of summary) {
        const status = s.passing ? "PASS" : "FAIL";
        console.log(`  ${status}  ${s.label}  ` +
                    `(${s.violation_count} violations, ` +
                    `${s.suppressed.length} suppressed)`);
    }
    console.log("\nFull reports: " + REPORTS_DIR);

    if (unrecoverable) {
        process.exit(2);
    }
    const anyFailing = summary.some(s => !s.passing);
    process.exit(anyFailing ? 1 : 0);
}


main().catch(err => {
    console.error("[a11y] uncaught error:", err);
    process.exit(2);
});
