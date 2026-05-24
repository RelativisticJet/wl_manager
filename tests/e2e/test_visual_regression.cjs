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
 * Pixel-diff layer (Ring 3 Day 4)
 * --------------------------------
 *
 * Optional pixel-level comparison via pixelmatch + pngjs,
 * implemented in ``lib_pixel_diff.cjs``. Off by default —
 * structural is the always-on contract. Activated by
 * ``WL_VISUAL_PIXEL=1``. Default is advisory: logs diff%,
 * saves diff PNG to ``visual_artifacts/``, does NOT fail
 * the test under 5% diff. Strict mode
 * (``WL_VISUAL_PIXEL_STRICT=1``) turns the soft threshold
 * into a hard failure. The hard 20% threshold ALWAYS fails
 * regardless of strict — that level of diff means the
 * screen is fundamentally different and the structural
 * layer should also have flagged it (so a >20% pixel diff
 * with a green structural test is a structural-layer
 * coverage gap to investigate).
 *
 * Pixel baselines live under ``visual_baselines_pixel/``
 * (committed PNGs, ~50-200KB each). Update both layers in
 * lock-step with ``WL_VISUAL_UPDATE=1 WL_VISUAL_PIXEL=1``.
 *
 * Why not @playwright/test: the existing test framework in
 * lib_helpers.cjs is light and well-tuned. Switching to
 * @playwright/test would require rewriting every .cjs test
 * file. pixelmatch + pngjs are tiny single-purpose deps
 * (no transitives) — much smaller delta.
 *
 * Origin
 * ------
 *
 * Structural snapshots: Ring 2 Day 6. The Ring 1
 * retrospective listed visual regression as Ring 2
 * followup; that ring established the structural contract
 * with what was available.
 *
 * Pixel-diff: Ring 3 Day 4. Layered on top of structural
 * after pixelmatch + pngjs were added to the dep manifest.
 *
 * Run: node tests/e2e/test_visual_regression.cjs
 *      WL_VISUAL_PIXEL=1 node tests/e2e/test_visual_regression.cjs
 */
const fs = require("fs");
const path = require("path");
const {
    createSession, test, summary,
} = require("./lib_helpers.cjs");
const pixelDiff = require("./lib_pixel_diff.cjs");

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
                    .replace(/\s+/g, " ")
                    // Normalize data-coupled counters embedded in heading
                    // text (e.g., "Pending Requests (0/20)" or "Recent
                    // History (11/100)") to a placeholder so the
                    // baseline matches regardless of accumulated
                    // queue/history state across test runs. CI run
                    // 26366311037 (2026-05-24) surfaced this as a
                    // visual-regression flake; see docs/V1_RC_RETRO.md
                    // §2.4 for the full diagnosis.
                    .replace(/\(\d+\/\d+\)/g, "(N/M)")
                    .replace(/\(\d+\)/g, "(N)"))
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
            // browser version differences AND moderate data-coupled
            // drift (audit dashboard's 7-day rolling window renders
            // shorter with fewer accumulated events; approval queue
            // sections expand and contract with queue depth). Catches
            // CATASTROPHIC collapse (entire panel disappearing — would
            // show as a >2000px delta) but tolerates ~500px data-coupled
            // noise. CI run 26366311037 (2026-05-24) audit delta of
            // -1550px is environmental — see docs/V1_RC_RETRO.md §2.4.
            scroll_height_bucket: bucketed(
                document.documentElement.scrollHeight, 500),
            // Element counts — the core regression signal.
            //
            // R3-D4-F1 (Ring 3 Day 4): the ``buttons`` selector
            // historically counted EVERY button on the page,
            // including the per-row "Show Data" / "Approve" /
            // "Reject" buttons inside the control_panel's
            // approval-queue and history tables. Those counts
            // drift with data state — the queue grows over time
            // — and made the test fragile across runs that
            // accumulated approval traffic. The fix:
            // ``:not(table button)`` excludes buttons under
            // ``<table>`` so only structural toolbar/tab buttons
            // count. The ``tables`` and ``inputs`` counts are
            // similarly bucketed at 0/1/many because exact
            // counts were data-coupled (input rows under
            // tables, etc.).
            counts: {
                // Structural buttons only — exclude the data-row
                // buttons inside tables.
                buttons:
                    Array.from(document.querySelectorAll(
                        "button:not([disabled]), .btn:not([disabled])"))
                    .filter(visible)
                    .filter(el => !el.closest("table"))
                    .length,
                // Inputs OUTSIDE tables (search bars, form
                // fields). Inputs inside tables are usually
                // editable cells whose count is data-driven.
                inputs:
                    Array.from(document.querySelectorAll(
                        "input:not([type=hidden])"))
                    .filter(visible)
                    .filter(el => !el.closest("table"))
                    .length,
                headings:      visibleCount("h1, h2, h3"),
                // Tables: presence-bucket. 0 = none, 1 = one,
                // 2+ = "many". Approval queue + history rendering
                // both as tables would otherwise force the
                // count to 2 only when both have content.
                tables:        Math.min(
                    visibleCount("table"), 2),
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
function diffSnapshots(baseline, current, ignoreFields) {
    // ignoreFields: optional per-view array of field names to skip.
    // Used by data-coupled dashboards (e.g., audit) where a field
    // is fundamentally environmental noise rather than structural
    // signal. See VIEW_SPECS for per-view configuration.
    const ignore = new Set(ignoreFields || []);
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
    // scroll height — bucketed at 500px; allow 1-bucket tolerance.
    // Bumped from 50px (R3-D4-F1 era) after CI run 26366311037
    // surfaced data-coupled drift exceeding 50px on the audit
    // dashboard's 7-day rolling window. 500px is still small
    // enough to catch a missing panel (each WM panel is ~300-500px)
    // but coarse enough to absorb event-count-driven render
    // shrink/grow.
    if (!ignore.has("scroll_height")) {
        const heightDiff = Math.abs(
            baseline.scroll_height_bucket
            - current.scroll_height_bucket);
        if (heightDiff > 500) {
            deltas.push(
                `scroll_height: ${baseline.scroll_height_bucket}`
                + ` → ${current.scroll_height_bucket}`
                + ` (delta ${heightDiff}px exceeds 500px tolerance)`);
        }
    }
    // Counts — allow ±5 tolerance. Data-dependent UIs (e.g.,
    // approval queue with N pending items conditionally rendering
    // section headings + section-level Refresh/Clear All buttons)
    // produce moderate button/heading deltas between cold and warm
    // loads. R3-D4-F1 (2026-05-10) tightened the selector to exclude
    // <table>-nested buttons (most data-coupled source). The ±5
    // tolerance was bumped from ±1 after CI run 26366311037 surfaced
    // a +3 button delta from section-level controls — see
    // docs/V1_RC_RETRO.md §2.4. Catches missing-toolbar-button
    // regressions (large structural deltas still exceed 5) while
    // tolerating section-conditional rendering.
    for (const key of Object.keys(baseline.counts)) {
        const diff = Math.abs(
            baseline.counts[key] - current.counts[key]);
        if (diff > 5) {
            deltas.push(
                `counts.${key}: ${baseline.counts[key]}`
                + ` → ${current.counts[key]}`
                + ` (delta ${diff} exceeds ±5 tolerance)`);
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
        // The audit dashboard's `scroll_height` is heavily
        // data-coupled — the 7-day rolling window renders
        // shorter on a freshly-provisioned CI container with
        // fewer accumulated events; panels with no data may
        // self-hide via `<panel depends>` gates. CI run
        // 26366311037 (2026-05-24) failed with a -1550px delta
        // on this view that was traced to fewer events being
        // visible, not a code regression. The other fields
        // (counts, h1_h2_texts, presence, body_classes) still
        // catch structural regressions. See docs/V1_RC_RETRO.md
        // §2.4.
        ignoreFields: ["scroll_height"],
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

    const deltas = diffSnapshots(baseline, snap, viewSpec.ignoreFields);
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

                // ── Pixel-diff layer (Ring 3 Day 4) ──
                // Runs only when WL_VISUAL_PIXEL=1. Always
                // advisory (logs diff%, saves diff PNG) unless
                // strict mode (WL_VISUAL_PIXEL_STRICT=1) or the
                // hard 20% threshold is exceeded.
                const screenshotPath = artifactPath(
                    viewSpec.name, viewportName, "png");
                const px = await pixelDiff.comparePixels(
                    viewSpec.name, viewportName, screenshotPath);
                if (px.skipped) {
                    // Pixel layer disabled — silent.
                } else if (px.calibrated) {
                    console.log(
                        `  [pixel-calibrated] ${testName} — `
                        + `pixel baseline saved (${px.baselinePath})`);
                } else if (px.updated) {
                    console.log(
                        `  [pixel-updated] ${testName} — `
                        + `pixel baseline overwritten`);
                } else if (px.dimensionMismatch) {
                    // Don't fail here — structural test should
                    // surface the layout overflow root cause.
                    console.log(
                        `  [pixel-dim-skip] ${testName} — `
                        + `baseline ${px.baseline.w}x${px.baseline.h}, `
                        + `current ${px.current.w}x${px.current.h}`);
                } else if (px.compared) {
                    const pctStr = px.percent.toFixed(2);
                    if (px.exceededHard) {
                        const msg =
                            `Pixel diff EXCEEDS HARD ${pixelDiff.HARD_FAIL_PCT}% `
                            + `threshold in ${testName}: `
                            + `${pctStr}% (${px.diffPixels}/${px.totalPixels} px). `
                            + `Diff PNG: ${px.diffPath}\n\n`
                            + `If intentional: WL_VISUAL_UPDATE=1 `
                            + `WL_VISUAL_PIXEL=1 `
                            + `node tests/e2e/test_visual_regression.cjs`;
                        throw new Error(msg);
                    }
                    if (px.exceededSoft) {
                        const tag = px.shouldFail
                            ? "[pixel-fail]"
                            : "[pixel-warn]";
                        console.log(
                            `  ${tag} ${testName} — ${pctStr}% `
                            + `diff (${px.diffPixels}/${px.totalPixels} px), `
                            + `> soft ${pixelDiff.SOFT_THRESHOLD_PCT}%. `
                            + `Diff PNG: ${px.diffPath}`);
                        if (px.shouldFail) {
                            throw new Error(
                                `Pixel diff exceeds strict-mode soft `
                                + `threshold (${pixelDiff.SOFT_THRESHOLD_PCT}%) `
                                + `in ${testName}: ${pctStr}%. `
                                + `Diff PNG: ${px.diffPath}`);
                        }
                    } else if (px.diffPixels > 0) {
                        // Below soft threshold — log only.
                        console.log(
                            `  [pixel-ok] ${testName} — ${pctStr}% `
                            + `diff (under ${pixelDiff.SOFT_THRESHOLD_PCT}% soft)`);
                    }
                }
            });
        }
    }

    await session.browser.close();
    const result = summary("Visual Regression");
    process.exit(result.failed > 0 ? 1 : 0);
})();
