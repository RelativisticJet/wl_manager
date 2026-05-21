#!/usr/bin/env node
/**
 * scripts/svg2png.js — Headless SVG → PNG renderer
 *
 * Renders an SVG file to a PNG at the requested pixel dimensions
 * using a headless Chromium instance via playwright-core (already
 * installed for the E2E test suite — no new dependencies needed).
 *
 * Why Chromium-based rendering rather than cairosvg / Inkscape / resvg?
 * Because the customer-facing renderer of Splunk app icons is also
 * a browser — Splunk's launcher tile loads the PNG through Chrome's
 * image pipeline. Using Chromium for the export step means the PNG
 * we ship looks exactly like what end users see, with consistent
 * anti-aliasing and transparency handling. Inkscape would produce
 * slightly different sub-pixel rendering at small sizes; not wrong,
 * just different from what customers see.
 *
 * Usage:
 *   node scripts/svg2png.js <input.svg> <output.png> <width> [height]
 *
 *   If <height> is omitted, output is square (height = width).
 *
 * Example:
 *   node scripts/svg2png.js docs/icons/appIcon-light.svg \
 *                           appserver/static/appIcon.png 36
 *
 * Batch usage (preferred): see scripts/svg2png-batch.sh.
 *
 * Maintained 2026-05-22 alongside the docs/icons/ visual identity.
 */

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright-core");

// Resolve the Playwright-installed Chromium executable. The E2E
// test suite has the same path-resolution logic at
// tests/e2e/lib_helpers.cjs :: resolveChromiumExecutable() — keep
// these two paths in sync if Playwright bumps the chromium revision.
function resolveChromiumExecutable() {
    if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
        return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
    }
    if (process.platform === "win32" && process.env.LOCALAPPDATA) {
        // The exact folder name has drifted over Playwright releases:
        //   chromium-1208 (Sep 2026) uses chrome-win64/chrome.exe
        //   chromium-1217 (newer) might use a different subfolder.
        // Try the v1.59.1-bundled chromium-1208 layout first; fall
        // back to letting playwright-core auto-resolve if absent.
        const candidates = [
            path.join(
                process.env.LOCALAPPDATA,
                "ms-playwright",
                "chromium-1208",
                "chrome-win64",
                "chrome.exe",
            ),
            path.join(
                process.env.LOCALAPPDATA,
                "ms-playwright",
                "chromium-1208",
                "chrome-win",
                "chrome.exe",
            ),
        ];
        for (const candidate of candidates) {
            if (fs.existsSync(candidate)) return candidate;
        }
    }
    return undefined; // let playwright-core auto-resolve
}

async function renderSvgToPng(svgPath, pngPath, width, height) {
    if (!fs.existsSync(svgPath)) {
        throw new Error(`SVG not found: ${svgPath}`);
    }
    const svgContent = fs.readFileSync(svgPath, "utf8");

    // Wrap the SVG inline in an HTML page with transparent background
    // and zero margin. The SVG's viewBox + the body sizing constraints
    // make the rendered output fill the exact viewport dimensions we
    // set below, which become the PNG pixel dimensions.
    const html = `<!DOCTYPE html>
<html><head><style>
  html, body { margin: 0; padding: 0; background: transparent; width: ${width}px; height: ${height}px; }
  svg { display: block; width: ${width}px; height: ${height}px; }
</style></head><body>${svgContent}</body></html>`;

    const executablePath = resolveChromiumExecutable();
    const browser = await chromium.launch({
        executablePath,
        headless: true,
    });

    try {
        const context = await browser.newContext({
            viewport: { width, height },
            deviceScaleFactor: 1,
        });
        const page = await context.newPage();
        await page.setContent(html, { waitUntil: "load" });
        const element = await page.locator("svg").first();

        // Use the page screenshot at the exact viewport, with
        // omitBackground so the transparent PNG comes out clean.
        // (Locator-level screenshots can include sub-pixel padding
        // from CSS positioning; full-page at the matched viewport
        // is more deterministic for icon work.)
        await page.screenshot({
            path: pngPath,
            omitBackground: true,
            type: "png",
            clip: { x: 0, y: 0, width, height },
        });

        const stat = fs.statSync(pngPath);
        console.log(
            `  ✓ ${svgPath} → ${pngPath} (${width}×${height}, ${stat.size} bytes)`,
        );
    } finally {
        await browser.close();
    }
}

async function main() {
    const args = process.argv.slice(2);
    if (args.length < 3 || args.length > 4) {
        console.error(
            "Usage: node scripts/svg2png.js <input.svg> <output.png> <width> [height]",
        );
        process.exit(1);
    }
    const [svgPath, pngPath, widthStr, heightStr] = args;
    const width = parseInt(widthStr, 10);
    const height = heightStr ? parseInt(heightStr, 10) : width;
    if (!Number.isFinite(width) || width <= 0) {
        console.error(`Invalid width: ${widthStr}`);
        process.exit(1);
    }
    if (!Number.isFinite(height) || height <= 0) {
        console.error(`Invalid height: ${heightStr}`);
        process.exit(1);
    }

    // Ensure output directory exists.
    fs.mkdirSync(path.dirname(pngPath), { recursive: true });

    try {
        await renderSvgToPng(svgPath, pngPath, width, height);
    } catch (err) {
        console.error(`Render failed: ${err.message}`);
        process.exit(1);
    }
}

main();
