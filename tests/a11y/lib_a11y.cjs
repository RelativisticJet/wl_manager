/**
 * Helpers for axe-core accessibility audits.
 *
 * Ring 5 Day 4 (2026-05-11).
 *
 * Wraps @axe-core/playwright's AxeBuilder with our conventions:
 *
 *  - Target: WCAG 2.1 Level AA (industry-standard public-app
 *    bar). Best-practice rules included but classified as
 *    informational.
 *  - Baseline diff: compare current violations against
 *    `tests/a11y/baseline.json`. New violations fail; previously-
 *    accepted ones (e.g., Splunk-bundled DOM we don't own) are
 *    suppressed.
 *  - Output: JSON per-page reports + a combined summary at
 *    `tests/a11y/reports/`. The CI workflow uploads the directory
 *    as an artifact.
 *
 * Why axe-core (not pa11y or Lighthouse):
 *
 *  - axe-core has the highest signal-to-noise of any open
 *    a11y engine — its rules are tightly aligned with WCAG
 *    success criteria and curated by Deque (a real a11y
 *    consultancy).
 *  - @axe-core/playwright works against the Page object we
 *    already use in tests/e2e/. No new browser dep.
 *  - Lighthouse runs a full perf audit on top of a11y; we
 *    only want the a11y signal here. Cost overhead doesn't
 *    pay off.
 */

const { AxeBuilder } = require("@axe-core/playwright");
const fs = require("fs");
const path = require("path");

// WCAG 2.1 Level AA is our target. axe-core tags map to these:
//   wcag2a    — WCAG 2.0 Level A
//   wcag2aa   — WCAG 2.0 Level AA
//   wcag21a   — WCAG 2.1 Level A (new in 2.1)
//   wcag21aa  — WCAG 2.1 Level AA (new in 2.1)
//   best-practice — axe's own additional best-practices
//
// We include all four WCAG tags. Best-practice rules are run too
// but classified as informational (don't fail the audit) — they
// often flag patterns that are technically conformant but could
// be improved.
const AUDIT_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"];

// Severity thresholds. Any violation at or above SEVERITY_FAIL
// fails the audit; below that, it's reported but doesn't block.
// axe-core's severity is: minor < moderate < serious < critical
const SEVERITY_FAIL = ["serious", "critical"];


/**
 * Run an axe-core scan on the current page state.
 *
 * @param {Page} page  Playwright Page instance (post-navigation,
 *                     post-render). The page must be in the
 *                     "fully loaded" state — wait for whatever
 *                     selector indicates the UI is ready BEFORE
 *                     calling this.
 * @param {object} opts
 * @param {string} opts.label  Human-readable label for this scan
 *                             (used in report filenames + log
 *                             output). E.g., "whitelist_manager".
 * @returns {Promise<object>} axe-core results object with
 *                            {violations, passes, incomplete,
 *                             inapplicable} keys.
 */
async function scanPage(page, opts) {
    const label = (opts && opts.label) || "unnamed";
    const builder = new AxeBuilder({ page }).withTags(AUDIT_TAGS);
    const results = await builder.analyze();
    results.__label = label;
    return results;
}


/**
 * Load the accepted-violations baseline. Returns an object
 * keyed by rule id; each value is an array of selector
 * strings whose violations are pre-accepted.
 *
 * Baseline format (tests/a11y/baseline.json):
 *   {
 *     "color-contrast": ["body > .splunk-banner .label"],
 *     "region": ["body > .splunk-footer"]
 *   }
 *
 * If the file doesn't exist or is empty, returns {} (no
 * suppressions).
 */
function loadBaseline() {
    const p = path.join(__dirname, "baseline.json");
    if (!fs.existsSync(p)) return {};
    try {
        return JSON.parse(fs.readFileSync(p, "utf-8")) || {};
    } catch (err) {
        console.warn(`[a11y] baseline.json parse failed: ${err.message}`);
        return {};
    }
}


/**
 * Filter axe results against the baseline. A violation is
 * suppressed when:
 *  - its rule id has an entry in baseline.json, AND
 *  - every one of its node.target selectors matches an entry
 *    in that rule's accepted-selectors array.
 *
 * Match modes (per accepted-selector entry):
 *  - plain string  -> exact equality with target.join(" ")
 *  - "re:<regex>"  -> tested as a regex against target.join(" ")
 *                     Use this for Splunk-bundled elements whose
 *                     IDs are auto-generated per render (e.g.
 *                     "re:^#view_\\d+-paginator\\d+ > ...").
 *
 * Returns a NEW results object — the input is not mutated.
 */
function filterAgainstBaseline(results, baseline) {
    const acceptedRules = baseline || {};
    const surviving = [];
    const suppressed = [];

    function nodeMatchesAny(targetString, acceptedList) {
        for (const entry of acceptedList) {
            if (typeof entry !== "string") continue;
            if (entry.startsWith("re:")) {
                try {
                    if (new RegExp(entry.slice(3)).test(targetString)) {
                        return true;
                    }
                } catch (_e) {
                    // Bad regex in baseline — skip; the entry won't
                    // suppress anything.
                }
            } else if (entry === targetString) {
                return true;
            }
        }
        return false;
    }

    for (const v of results.violations) {
        const acceptedList = acceptedRules[v.id] || [];
        if (acceptedList.length === 0) {
            surviving.push(v);
            continue;
        }
        // For each violation, check every node — if ALL of this
        // violation's nodes are in the accepted set, suppress.
        // If ANY node is new, keep the violation but trim it to
        // just the new nodes.
        const newNodes = v.nodes.filter(node => {
            const target = (node.target || []).join(" ");
            return !nodeMatchesAny(target, acceptedList);
        });
        if (newNodes.length === 0) {
            suppressed.push(v.id);
        } else {
            surviving.push({ ...v, nodes: newNodes });
        }
    }

    return {
        ...results,
        violations: surviving,
        __suppressed_rule_ids: suppressed,
    };
}


/**
 * Reduce a results object to a one-line summary string.
 * Used in the test output for fast scanning.
 */
function summarize(results) {
    const v = results.violations || [];
    const counts = { critical: 0, serious: 0, moderate: 0, minor: 0 };
    for (const violation of v) {
        const sev = violation.impact || "moderate";
        counts[sev] = (counts[sev] || 0) + (violation.nodes || []).length;
    }
    return `[${results.__label}] violations: ` +
           `${counts.critical} critical, ${counts.serious} serious, ` +
           `${counts.moderate} moderate, ${counts.minor} minor`;
}


/**
 * Decide pass/fail for the page based on the severity threshold.
 * Returns true if the page passes (no critical/serious
 * violations); false otherwise.
 */
function pageIsPassing(results) {
    for (const v of results.violations || []) {
        if (SEVERITY_FAIL.includes(v.impact)) return false;
    }
    return true;
}


/**
 * Write per-page report and append to summary index.
 */
function writeReports(allResults, reportsDir) {
    fs.mkdirSync(reportsDir, { recursive: true });
    const summary = [];
    for (const r of allResults) {
        const label = r.__label || "unnamed";
        const file = path.join(reportsDir, `${label}.json`);
        fs.writeFileSync(file, JSON.stringify(r, null, 2), "utf-8");
        summary.push({
            label,
            violation_count: (r.violations || []).length,
            passing: pageIsPassing(r),
            suppressed: r.__suppressed_rule_ids || [],
        });
    }
    fs.writeFileSync(
        path.join(reportsDir, "summary.json"),
        JSON.stringify(summary, null, 2),
        "utf-8",
    );
    return summary;
}


module.exports = {
    scanPage,
    loadBaseline,
    filterAgainstBaseline,
    summarize,
    pageIsPassing,
    writeReports,
    AUDIT_TAGS,
    SEVERITY_FAIL,
};
