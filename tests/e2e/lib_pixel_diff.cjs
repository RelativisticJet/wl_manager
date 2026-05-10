/**
 * Pixel-level visual regression helper (Ring 3 Day 4).
 *
 * Layered ON TOP of the structural snapshot in
 * test_visual_regression.cjs — that test catches structural
 * regressions (missing buttons, layout collapse) and is the
 * always-on contract. This helper catches *cosmetic* changes
 * that structural diffs don't see (colors, spacing,
 * background, font-size). It is INTENTIONALLY off by default
 * because pixel-diff is platform-flaky and the structural
 * layer already gates the scary regressions.
 *
 * Activation: WL_VISUAL_PIXEL=1 enables the pixel layer.
 * Without that env var, the pixel layer is a no-op even if
 * baselines exist.
 *
 * Strict mode: WL_VISUAL_PIXEL_STRICT=1 turns the soft
 * fail (default: log + diff PNG) into a hard test failure
 * when the diff exceeds the threshold.
 *
 * Threshold: WL_VISUAL_PIXEL_THRESHOLD (percent, default 5).
 * Below this, the test is considered passing. The HARD
 * threshold (20%) always fails regardless of strict mode —
 * that level of diff means the screen is fundamentally
 * different and the structural test should also have failed.
 *
 * Why pixelmatch v7 via dynamic import: pixelmatch 7.x is
 * pure ESM ("type": "module"). The test framework here is
 * .cjs, so we use `await import(...)` to bridge. pngjs is
 * CommonJS so it loads normally.
 *
 * Why not @playwright/test: would require rewriting all the
 * existing .cjs test files into the @playwright/test format.
 * The structural test is already the load-bearing contract;
 * pixel-diff is icing.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { PNG } = require("pngjs");

const PIXEL_BASELINES_DIR = path.join(
    __dirname, "visual_baselines_pixel");
const ARTIFACTS_DIR = path.join(__dirname, "visual_artifacts");

const ENABLED = process.env.WL_VISUAL_PIXEL === "1";
const STRICT = process.env.WL_VISUAL_PIXEL_STRICT === "1";
const SOFT_THRESHOLD_PCT = parseFloat(
    process.env.WL_VISUAL_PIXEL_THRESHOLD || "5");
// 20% diff means "the screen is structurally different" —
// always fail at this level, regardless of strict mode. If
// the structural test passed but pixel diff is >20%, the
// structural snapshot has a coverage gap.
const HARD_FAIL_PCT = 20;

if (!fs.existsSync(PIXEL_BASELINES_DIR)) {
    fs.mkdirSync(PIXEL_BASELINES_DIR, { recursive: true });
}
if (!fs.existsSync(ARTIFACTS_DIR)) {
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
}

function pixelBaselinePath(viewName, viewportName) {
    return path.join(PIXEL_BASELINES_DIR,
        `${viewName}_${viewportName}.png`);
}

function pixelDiffArtifactPath(viewName, viewportName) {
    return path.join(ARTIFACTS_DIR,
        `${viewName}_${viewportName}.diff.png`);
}

async function loadPixelmatch() {
    // Dynamic import bridges ESM-only pixelmatch into our
    // CJS module. Cached after first call.
    if (!loadPixelmatch._cached) {
        loadPixelmatch._cached = (
            await import("pixelmatch")).default;
    }
    return loadPixelmatch._cached;
}

function readPng(filePath) {
    const buf = fs.readFileSync(filePath);
    return PNG.sync.read(buf);
}

function writePng(filePath, png) {
    const buf = PNG.sync.write(png);
    fs.writeFileSync(filePath, buf);
}

/**
 * Compare a current screenshot against a committed baseline
 * PNG. Returns a result object describing the comparison.
 *
 * If no baseline exists, the current screenshot becomes the
 * baseline (calibration mode). The caller treats calibration
 * as a pass.
 *
 * If WL_VISUAL_UPDATE=1 is set on the parent process (the
 * structural test's same env var), the baseline is rewritten
 * unconditionally. This keeps both layers in sync — running
 * with WL_VISUAL_UPDATE=1 updates BOTH the JSON structural
 * baseline and the PNG pixel baseline.
 */
async function comparePixels(viewName, viewportName, currentPngPath) {
    if (!ENABLED) {
        return { skipped: true, reason: "WL_VISUAL_PIXEL not set" };
    }

    const baselinePath = pixelBaselinePath(viewName, viewportName);
    const diffPath = pixelDiffArtifactPath(viewName, viewportName);
    const updateMode = process.env.WL_VISUAL_UPDATE === "1";

    if (updateMode) {
        // Update mode: copy current → baseline. Keeps the
        // pixel baseline in lock-step with structural.
        fs.copyFileSync(currentPngPath, baselinePath);
        return { updated: true, baselinePath };
    }

    if (!fs.existsSync(baselinePath)) {
        // First-run calibration. Write current as baseline,
        // skip diff (pass).
        fs.copyFileSync(currentPngPath, baselinePath);
        return { calibrated: true, baselinePath };
    }

    const baseline = readPng(baselinePath);
    const current = readPng(currentPngPath);

    if (baseline.width !== current.width
            || baseline.height !== current.height) {
        // Dimensions differ — that's a structural change,
        // not a pixel change. We don't try to handle this;
        // the structural test should have caught the
        // viewport-size or layout-overflow root cause.
        return {
            dimensionMismatch: true,
            baseline: { w: baseline.width, h: baseline.height },
            current: { w: current.width, h: current.height },
        };
    }

    const pixelmatch = await loadPixelmatch();
    const diff = new PNG({
        width: baseline.width, height: baseline.height });
    // threshold: 0.1 is pixelmatch's default — moderate
    // sensitivity. Anti-aliasing is excluded by default
    // (includeAA: false) so font-rendering jitter doesn't
    // count.
    const diffPixels = pixelmatch(
        baseline.data, current.data, diff.data,
        baseline.width, baseline.height,
        { threshold: 0.1, includeAA: false });

    const totalPixels = baseline.width * baseline.height;
    const percent = (diffPixels / totalPixels) * 100;

    // Always write the diff PNG when there's any diff —
    // human inspection beats a number for triage.
    if (diffPixels > 0) {
        writePng(diffPath, diff);
    }

    const exceededSoft = percent > SOFT_THRESHOLD_PCT;
    const exceededHard = percent > HARD_FAIL_PCT;

    return {
        compared: true,
        diffPixels,
        totalPixels,
        percent,
        diffPath: diffPixels > 0 ? diffPath : null,
        exceededSoft,
        exceededHard,
        // Caller decides whether to throw based on this:
        shouldFail: exceededHard || (STRICT && exceededSoft),
    };
}

module.exports = {
    comparePixels,
    SOFT_THRESHOLD_PCT,
    HARD_FAIL_PCT,
    ENABLED,
    STRICT,
};
