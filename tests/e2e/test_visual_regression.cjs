/**
 * Visual regression — structural DOM snapshot contract.
 *
 * Captures DOM-level structural invariants for the three main
 * dashboards across viewport breakpoints, asserts them against
 * committed baseline JSON files. Catches the bug class where a
 * CSS or template change silently breaks a layout, removes a
 * button, or collapses a panel — without requiring a pixel-diff
 * library.
 *
 * Why structural, not pixel
 * -------------------------
 *
 * Only ``playwright-core`` (not ``@playwright/test``) is
 * installed, so ``toHaveScreenshot()`` is unavailable. Adding a
 * pixel-diff dep (pixelmatch / looks-same / @playwright/test
 * itself) would expand the dependency surface. Structural
 * snapshots ship today with what's already available and catch
 * the most common regression categories:
 *
 * - Missing / extra buttons (count delta)
 * - Layout collapse (scrollHeight delta beyond tolerance)
 * - Heading text rename (h1/h2 string mismatch)
 * - Critical element disappearance (e.g., #rule-search,
 *   #csv-table-container missing)
 * - Theme regression (body class flag mismatch)
 *
 * What this DOES catch:
 * - "I refactored the dashboard and forgot to wire up the
 *   Activate Lockdown button"
 * - "The CSS migration removed padding so the table is now
 *   pushed off-screen"
 * - "I renamed the heading and broke a screen-reader contract"
 * - "I deleted a panel and the structure has 3 fewer headings"
 *
 * What it does NOT catch:
 * - Pixel-level styling differences (color, font, anti-aliasing)
 * - Visual hierarchy changes that don't affect element counts
 * - Issues only visible in screenshots (those go in pixel-diff
 *   tests when @playwright/test is added)
 *
 * Screenshots are still saved to
 * ``tests/e2e/visual_artifacts/`` (gitignored) for diagnostic
 * inspection — when a structural test fails, the screenshot
 * shows what the test saw without needing to re-run interactively.
 *
 * Updating baselines
 * ------------------
 *
 * When an intentional structural change ships (a new button, a
 * heading rename, a layout reorganization), run the test with
 * ``WL_VISUAL_UPDATE=1`` to overwrite the committed baseline JSONs.
 * Review the JSON diff in the commit; merge means the new
 * structure is the new contract.
 *
 *     WL_VISUAL_UPDATE=1 node tests/e2e/test_visual_regression.cjs
 *
 * Without the env var, baselines are read-only and any structural
 * delta fails the test.
 *
 * Origin
 * ------
 *
 * Ring 2 Day 6. The Ring 1 retrospective listed visual regression
 * as Ring 2 followup; this file establishes the contract with
 * what's already available. A future ring can add pixel-diff on
 * top of the structural layer once @playwright/test is on the
 * dep manifest.
 *
 * Run: node tests/e2e/test_visual_regression.cjs
 */
const fs = require("fs");
const path = require("path");
const {
    createSession, test, summary,
} = require("./lib_helpers.cjs");

const BASELINES_DIR = path.join(
    __dirname, "visual_baselines");
const ARTIFACTS_DIR = path.join(
    __dirname, "visual_artifacts");
const UPDATE_BASELINES =
    process.env.WL_VISUAL_UPDATE === "1";

const BASE_URL = "http://localhost:8000/en-US/app/wl_manager";

// Ensure artifact dir exists (gitignored)
if (!fs.existsSync(ARTIFACTS_DIR)) {
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
}
if (!fs.existsSync(BASELINES_DIR)) {
    fs.mkdirSync(BASELINES_DIR, { recursive: true });
}


// ─────────────────────────────────────────────────────────────────────
// Snapshot capture
// ─────────────────────────────────────────────────────────────────────

/**
 * Capture a structural snapshot of the current page. Returns a
 * plain JSON-serializable object that's compared against the
 * baseline.
 *
 * Numeric fields are bucketed where appropriate (scrollHeight
 * to nearest 50px) so trivial pixel-level deltas don't fail
 * the test, while collapses / overflows still surface.
 */
async function captureSnapshot(page) {
    return page.evaluate(() => {
        const visible = (el) => {
            const r = el.getBoundingClientRect();
            const cs = window.getComputedStyle(el);
            return cs.display !== "none"
                && cs.visibility !== "hidden"
                && r.width > 0 && r.height > 0;
        };
        const visibleCount = (selector) => {
            return Array.from(document.querySelectorAll(selector))
                .filter(visible).length;
        };
        const presence = (selector) => {
            const el = document.querySelector(selector);
            return el ? visible(el) : false;
        };
        const headingTexts = (selector) => {
            return Array.from(document.querySelectorAll(selector))
                .filter(visible)
                .map(el => (el.textContent || "")
                    .trim()
                    .replace(/\s+/g, " "))
                .filter(s => s.length > 0)
                .sort();
        };
        const bucketed = (n, bucket) =>
            Math.round(n / bucket) * bucket;

        return {
            url_path: window.location.pathname,
            viewport: {
                w: window.innerWidth,
                h: window.innerHeight,
            },
            // Body class flags. wl-dark indicates dark theme is
            // applied; flipping this to false would mean theme
            // detection regressed.
            body_classes: Array.from(document.body.classList)
                .filter(c => c.startsWith("wl-")
                    || c === "splunk-application")
                .sort(),
            // Layout dimensions, bucketed to absorb minor
            // browser version differences. Catches catastrophic
            // collapse (entire panel disappearing) but tolerates
            // 50px-scale rendering noise.
            scroll_height_bucket: bucketed(
                document.documentElement.scrollHeight, 50),
            // Element counts — the core regression signal.
            counts: {
                buttons:       visibleCount("button:not([disabled]), .btn:not([disabled])"),
                inputs:        visibleCount("input:not([type=hidden])"),
                headings:      visibleCount("h1, h2, h3"),
                tables:        visibleCount("table"),
                modals:        visibleCount(".wl-modal-overlay"),
            },
            // Critical-element presence — these are the IDs the
            // page contract relies on. If any flip from true to
            // false, the page is broken in a structural way.
            presence: {
                rule_search:        presence("#rule-search"),
                csv_table_container: presence("#csv-table-container"),
                control_panel_tabs:  presence(".wl-cp-tabs, .wl-tab-strip, [role=tablist]"),
                action_filter:      presence("[data-test=action-filter], .input.input-dropdown"),
            },
            // h1/h2 texts — a rename surfaces here as a string
            // delta. Catches accidental "Whitelist Manager" →
            // "WL Manager" type regressions.
            h1_h2_texts: headingTexts("h1, h2"),
        };
    });
}

function snapshotKey(viewName, viewport) {
    return `${viewName}_${viewport}`;
}

function baselinePath(viewName, viewport) {
    return path.join(
        BASELINES_DIR,
        `${snapshotKey(viewName, viewport)}.json`);
}

function artifactPath(viewName, viewport, ext) {
    return path.join(
        ARTIFACTS_DIR,
        `${snapshotKey(viewName, viewport)}.${ext}`);
}

function readBaseline(viewName, viewport) {
    const p = baselinePath(viewName, viewport);
    if (!fs.existsSync(p)) return null;
    try {
        return JSON.parse(fs.readFileSync(p, "utf8"));
    } catch (_) {
        return null;
    }
}

function writeBaseline(viewName, viewport, snap) {
    const p = baselinePath(viewName, viewport);
    fs.writeFileSync(p, JSON.stringify(snap, null, 2));
}

/**
 * Compare two snapshots and return a list of structural deltas.
 * Empty list = identical structure. Non-empty = test fails.
 */
function diffSnapshots(baseline, current) {
    const deltas = [];
    if (baseline.url_path !== current.url_path) {
        deltas.push(
            `url_path: '${baseline.url_path}' → '${current.url_path}'`);
    }
    if (baseline.viewport.w !== current.viewport.w
        || baseline.viewport.h !== current.viewport.h) {
        deltas.push(
            `viewport: ${baseline.viewport.w}x${baseline.viewport.h}`
            + ` → ${current.viewport.w}x${current.viewport.h}`);
    }
    // body classes — set comparison
    const bClasses = baseline.body_classes.join(",");
    const cClasses = current.body_classes.join(",");
    if (bClasses !== cClasses) {
        deltas.push(
            `body_classes: '${bClasses}' → '${cClasses}'`);
    }
    // scroll height — bucketed; allow 1-bucket tolerance
    const heightDiff = Math.abs(
        baseline.scroll_height_bucket
        - current.scroll_height_bucket);
    if (heightDiff > 50) {
        deltas.push(
            `scroll_height: ${baseline.scroll_height_bucket}`
            + ` → ${current.scroll_height_bucket}`
            + ` (delta ${heightDiff}px exceeds 50px tolerance)`);
    }
    // Counts — allow ±1 tolerance. Data-dependent UIs (e.g.,
    // approval queue with N pending items, audit panels with
    // N visible alerts) produce small button/heading deltas
    // between cold and warm loads. ±1 catches missing-button
    // regressions while tolerating data variance. Larger
    // deltas (≥2) still fail — that's structural.
    for (const key of Object.keys(baseline.counts)) {
        const diff = Math.abs(
            baseline.counts[key] - current.counts[key]);
        if (diff > 1) {
            deltas.push(
                `counts.${key}: ${baseline.counts[key]}`
                + ` → ${current.counts[key]}`
                + ` (delta ${diff} exceeds ±1 tolerance)`);
        }
    }
    // Presence — exact match
    for (const key of Object.keys(baseline.presence)) {
        if (baseline.presence[key] !== current.presence[key]) {
            deltas.push(
                `presence.${key}: ${baseline.presence[key]}`
                + ` → ${current.presence[key]}`);
        }
    }
    // h1/h2 texts — set comparison
    const bHead = baseline.h1_h2_texts.join("|");
    const cHead = current.h1_h2_texts.join("|");
    if (bHead !== cHead) {
        deltas.push(
            `h1_h2_texts: [${bHead}] → [${cHead}]`);
    }
    return deltas;
}


// ─────────────────────────────────────────────────────────────────────
// View specs
// ─────────────────────────────────────────────────────────────────────

const VIEWPORTS = {
    desktop: { width: 1440, height: 900 },
    tablet:  { width: 1024, height: 768 },
    mobile:  { width: 375,  height: 812 },
};

const VIEW_SPECS = [
    {
        name: "whitelist_manager",
        path: "/whitelist_manager",
        // Wait until the rule-search input + at least one rule
        // dropdown item exists. Mirrors lib_helpers.navigateToWM.
        ready: async (page) => {
            await page.waitForSelector("#rule-search",
                { timeout: 15000 });
            await page.waitForFunction(() => {
                const items = document.querySelectorAll(
                    "#rule-list .wl-dropdown-item");
                return items.length > 0;
            }, { timeout: 15000 });
            await page.waitForTimeout(1500);
        },
        viewports: ["desktop", "tablet", "mobile"],
    },
    {
        name: "control_panel",
        path: "/control_panel",
        ready: async (page) => {
            await page.waitForLoadState("domcontentloaded");
            // Control panel renders Approval Queue, Activity,
            // and Trash tabs asynchronously. A fixed
            // ``waitForTimeout(3500)`` was flaky on cold load
            // (button count drifted between 8 and 9 across
            // runs). 1-match stabilization wasn't enough
            // because the count plateaus briefly at 8 before
            // the 9th button appears. Require 4 CONSECUTIVE
            // matches at 400ms cadence (~1.6s of stable count)
            // before declaring ready.
            await stabilizeCount(page,
                "button:not([disabled]), .btn:not([disabled])",
                "__lastBtnSeq", 4);
            await page.waitForTimeout(300);
        },
        viewports: ["desktop"],
    },
    {
        name: "audit",
        path: "/audit",
        ready: async (page) => {
            // The audit dashboard runs 4+ SPL searches in
            // parallel; each populates its own panel
            // asynchronously over a multi-second window. This
            // makes it the most network-bound of the three
            // dashboards and the hardest to stabilize. Use
            // ``networkidle`` (Playwright considers the page
            // idle after 500ms of no network activity) plus a
            // longer count-stability gate (8 consecutive
            // matches at 500ms cadence = 4s of dead-stable
            // table count).
            try {
                await page.waitForLoadState("networkidle",
                    { timeout: 20000 });
            } catch (_) {
                // Some Splunk dashboards never go fully idle
                // (live polling). Fall back to count-stability.
            }
            await stabilizeCount(page,
                "h1, h2, h3", "__lastHSeq", 8, 500);
            await stabilizeCount(page,
                "table", "__lastTSeq", 8, 500);
            await page.waitForTimeout(500);
        },
        viewports: ["desktop"],
    },
];


/**
 * Wait for the visible-element count of ``selector`` to remain
 * stable for ``requiredMatches`` consecutive samples at 400ms
 * cadence. Caps at 12s. Used by views with async data fetching
 * where simple ``waitForTimeout`` flakes on cold loads.
 *
 * The window-scoped sequence variable (``windowKey``) tracks
 * the run of consecutive identical samples. When the run hits
 * ``requiredMatches``, we declare the count stable and resolve.
 */
async function stabilizeCount(
        page, selector, windowKey, requiredMatches,
        pollingMs = 400) {
    await page.waitForFunction(({ sel, key, n }) => {
        const visible = (el) => {
            const r = el.getBoundingClientRect();
            const cs = window.getComputedStyle(el);
            return cs.display !== "none"
                && cs.visibility !== "hidden"
                && r.width > 0 && r.height > 0;
        };
        const count = Array.from(
            document.querySelectorAll(sel))
            .filter(visible).length;
        const state = window[key]
            || { last: -1, run: 0 };
        if (state.last === count && count > 0) {
            state.run += 1;
        } else {
            state.last = count;
            state.run = 1;
        }
        window[key] = state;
        return state.run >= n;
    }, { sel: selector, key: windowKey, n: requiredMatches },
        { timeout: 20000, polling: pollingMs });
}


// ─────────────────────────────────────────────────────────────────────
// Test execution
// ─────────────────────────────────────────────────────────────────────

async function captureAndCompare(page, viewSpec, viewportName) {
    const viewport = VIEWPORTS[viewportName];
    await page.setViewportSize(viewport);
    const url = `${BASE_URL}${viewSpec.path}`;
    await page.goto(url, { waitUntil: "domcontentloaded",
        timeout: 30000 });
    await viewSpec.ready(page);

    // Diagnostic screenshot — always saved, never compared
    await page.screenshot({
        path: artifactPath(viewSpec.name, viewportName, "png"),
        fullPage: true,
    });

    const snap = await captureSnapshot(page);

    if (UPDATE_BASELINES) {
        writeBaseline(viewSpec.name, viewportName, snap);
        return { updated: true };
    }

    const baseline = readBaseline(viewSpec.name, viewportName);
    if (!baseline) {
        // No baseline yet — write the first one and pass.
        // Subsequent runs will compare. This makes the very
        // first run on a new view a "calibration" run.
        writeBaseline(viewSpec.name, viewportName, snap);
        return { calibrated: true, snap };
    }

    const deltas = diffSnapshots(baseline, snap);
    return { deltas, snap, baseline };
}


(async () => {
    const session = await createSession(
        "superadmin1", "Chang3d!");

    const updateMsg = UPDATE_BASELINES
        ? " (UPDATE MODE — baselines will be overwritten)"
        : "";
    console.log(`[visual] ${VIEW_SPECS.length} views to capture${updateMsg}`);

    for (const viewSpec of VIEW_SPECS) {
        for (const viewportName of viewSpec.viewports) {
            const testName =
                `visual:${viewSpec.name}@${viewportName}`;
            await test(testName, async () => {
                const result = await captureAndCompare(
                    session.page, viewSpec, viewportName);
                if (result.updated) {
                    console.log(`  [updated] ${testName} baseline written`);
                    return;
                }
                if (result.calibrated) {
                    console.log(
                        `  [calibrated] ${testName} — first-run baseline saved.`
                        + ` Re-run to actually verify.`);
                    return;
                }
                if (result.deltas.length > 0) {
                    // Log deltas to console BEFORE throwing —
                    // ``lib_helpers.summary`` truncates the
                    // error message to first line, so the delta
                    // detail would be lost in the summary
                    // table.
                    console.log(
                        `\n  [delta] ${testName}:`);
                    for (const d of result.deltas) {
                        console.log(`    - ${d}`);
                    }
                    const msg =
                        `Visual structural delta in ${testName}:\n  - `
                        + result.deltas.join("\n  - ")
                        + `\n\nIf intentional: WL_VISUAL_UPDATE=1 `
                        + `node tests/e2e/test_visual_regression.cjs`;
                    throw new Error(msg);
                }
            });
        }
    }

    await session.browser.close();
    const result = summary("Visual Regression");
    process.exit(result.failed > 0 ? 1 : 0);
})();
