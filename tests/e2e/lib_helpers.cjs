/**
 * Shared helpers for multi-role E2E tests.
 *
 * Browser selection: set the env var WL_E2E_BROWSER to one of
 * "chromium" (default), "firefox", or "webkit". Each browser
 * requires its own Playwright build — `npx playwright@<minor>
 * install <browser>` downloads it. The chromium-1208 path
 * resolver here mirrors the pre-2026-05-20 behavior; the
 * firefox-1511 path resolver was added when the refactor landed.
 *
 * Why explicit executablePath on Windows: when the host already
 * has playwright-CLI Chromium installs (which it does — see
 * docs/SPLUNK_QUIRKS.md), playwright-core's auto-resolver
 * sometimes mis-picks the version. Hard-coding the Windows path
 * removes the ambiguity. On Linux runners executablePath stays
 * undefined and playwright-core auto-resolves.
 */
const path = require("node:path");
const { chromium, firefox, webkit } = require("playwright-core");

function resolveChromiumExecutable() {
    if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
        return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
    }
    if (process.platform === "win32" && process.env.LOCALAPPDATA) {
        return path.join(process.env.LOCALAPPDATA, "ms-playwright", "chromium-1208", "chrome-win64", "chrome.exe");
    }
    return undefined;
}

function resolveFirefoxExecutable() {
    if (process.env.PLAYWRIGHT_FIREFOX_EXECUTABLE_PATH) {
        return process.env.PLAYWRIGHT_FIREFOX_EXECUTABLE_PATH;
    }
    if (process.platform === "win32" && process.env.LOCALAPPDATA) {
        return path.join(process.env.LOCALAPPDATA, "ms-playwright", "firefox-1511", "firefox", "firefox.exe");
    }
    return undefined;
}

function resolveWebkitExecutable() {
    if (process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH) {
        return process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH;
    }
    return undefined;  // No Windows path pin — webkit not currently in scope.
}

// Resolved at module load. To override, set WL_E2E_BROWSER before
// requiring this module (typical: env-var prefix on the test command).
const BROWSER_NAME = (process.env.WL_E2E_BROWSER || "chromium").toLowerCase();
const BROWSER_REGISTRY = {
    chromium: { engine: chromium, exec: resolveChromiumExecutable() },
    firefox:  { engine: firefox,  exec: resolveFirefoxExecutable() },
    webkit:   { engine: webkit,   exec: resolveWebkitExecutable() },
};
if (!BROWSER_REGISTRY[BROWSER_NAME]) {
    throw new Error(
        `WL_E2E_BROWSER='${BROWSER_NAME}' not recognized. ` +
        `Valid values: chromium, firefox, webkit.`
    );
}
const BROWSER = BROWSER_REGISTRY[BROWSER_NAME].engine;
const CHROME = BROWSER_REGISTRY[BROWSER_NAME].exec;  // legacy name preserved
                                                      // for in-file callers
const BASE = "http://localhost:8000";
const REST = "https://localhost:8089";

const results = [];

function log(icon, msg) {
    const ts = new Date().toISOString().slice(11, 19);
    console.log(`[${ts}] ${icon} ${msg}`);
}

async function test(name, fn) {
    try {
        await fn();
        results.push({ name, status: "PASS" });
        log("\u2705", name);
    } catch (e) {
        results.push({ name, status: "FAIL", error: e.message.split("\n")[0] });
        log("\u274C", `${name}: ${e.message.split("\n")[0]}`);
    }
}

function summary(label) {
    const passed = results.filter(r => r.status === "PASS").length;
    const failed = results.filter(r => r.status === "FAIL").length;
    console.log(`\n${"=".repeat(60)}`);
    console.log(`  ${label}`);
    console.log(`  PASSED: ${passed}  |  FAILED: ${failed}  |  TOTAL: ${results.length}`);
    console.log(`${"=".repeat(60)}`);
    for (const r of results) {
        const icon = r.status === "PASS" ? "\u2705" : "\u274C";
        console.log(`  ${icon} ${r.name}${r.error ? ` \u2014 ${r.error}` : ""}`);
    }
    console.log(`${"=".repeat(60)}\n`);
    return { passed, failed, total: results.length, results: [...results] };
}

async function createSession(user, pass) {
    const launchOpts = { headless: true };
    if (CHROME) launchOpts.executablePath = CHROME;
    const browser = await BROWSER.launch(launchOpts);
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    page.__errors = [];
    page.on("console", msg => { if (msg.type() === "error") page.__errors.push(msg.text()); });
    page.on("pageerror", err => page.__errors.push(err.message));

    // Login
    await page.goto(`${BASE}/en-US/account/login`, { waitUntil: "domcontentloaded" });
    await page.fill('input[name="username"]', user);
    await page.fill('input[name="password"]', pass);
    await page.click('input[type="submit"], button[type="submit"]');
    await page.waitForURL(/\/app\/|\/en-US\//, { timeout: 15000 });
    await page.waitForTimeout(2000);
    return { browser, context, page };
}

async function navigateToWM(page, params) {
    const url = params ? `${BASE}/en-US/app/wl_manager/whitelist_manager?${params}` : `${BASE}/en-US/app/wl_manager/whitelist_manager`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#rule-search", { timeout: 15000 });
    await page.waitForFunction(() => {
        const items = document.querySelectorAll("#rule-list .wl-dropdown-item");
        return items.length > 0;
    }, { timeout: 15000 });
}

async function navigateToCP(page) {
    await page.goto(`${BASE}/en-US/app/wl_manager/control_panel`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
}

async function selectRule(page, ruleName) {
    await page.fill("#rule-search", "");
    await page.fill("#rule-search", ruleName);
    await page.waitForTimeout(300);
    const item = page.locator(`#rule-list .wl-dropdown-item[data-value="${ruleName}"]`);
    if (await item.count() > 0) await item.click();
    else await page.press("#rule-search", "Enter");
    await page.waitForTimeout(500);
}

async function waitForTable(page) {
    await page.waitForSelector("#csv-table-container table", { timeout: 12000 });
    await page.waitForTimeout(500);
}

async function restCall(page, method, params) {
    return page.evaluate(async ({ method, params }) => {
        const csrfMatch = document.cookie.match(/splunkweb_csrf_token_8000=([^;]+)/);
        const token = csrfMatch ? csrfMatch[1] : "";
        const headers = {
            "X-Splunk-Form-Key": token,
            "X-Requested-With": "XMLHttpRequest"
        };
        // Splunk web proxy requires locale prefix for proper POST routing
        const base = "/en-US/splunkd/__raw/services/custom/wl_manager";
        if (method === "GET") {
            const qs = new URLSearchParams(params).toString();
            const res = await fetch(base + "?" + qs + "&output_mode=json", { headers });
            return res.json();
        } else {
            headers["Content-Type"] = "application/json";
            const res = await fetch(base + "?output_mode=json", {
                method: "POST", headers, body: JSON.stringify(params)
            });
            return res.json();
        }
    }, { method, params });
}

// ──────────────────────────────────────────────────────────────────
// Test-harness-only destructive operations
// ──────────────────────────────────────────────────────────────────
// These helpers bypass production safety controls (HMAC tamper flags,
// daily rate limits, etc.). They MUST NOT be reachable from anything
// that could run against a real environment. The gate enforces both:
//
//   1. The WL_TEST_HARNESS=1 environment variable is set (declarative
//      opt-in by whoever runs the test runner).
//   2. The target container is exactly "wl_manager_test" (named test
//      container, not production).
//
// A failure in either gate throws before any mutation happens. The
// error is loud and fatal so an accidental run cannot silently
// corrupt production.
const EXPECTED_TEST_CONTAINER = "wl_manager_test";

function assertTestHarness() {
    if (process.env.WL_TEST_HARNESS !== "1") {
        throw new Error(
            "REFUSING to run destructive test helper: WL_TEST_HARNESS=1 is "
            + "not set. Set it explicitly when invoking the test runner: "
            + "`WL_TEST_HARNESS=1 node tests/e2e/<file>.cjs`. This is a "
            + "safety gate — do NOT set it permanently in your shell rc."
        );
    }
    const { spawnSync } = require("child_process");
    const res = spawnSync(
        "docker",
        ["ps", "--format", "{{.Names}}", "--filter",
         "name=" + EXPECTED_TEST_CONTAINER],
        { env: { ...process.env, MSYS_NO_PATHCONV: "1" }, encoding: "utf8" }
    );
    const names = (res.stdout || "").split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (!names.includes(EXPECTED_TEST_CONTAINER)) {
        throw new Error(
            "REFUSING to run destructive test helper: container '"
            + EXPECTED_TEST_CONTAINER + "' is not running. Destructive "
            + "helpers are gated to that exact name."
        );
    }
}

function clearKvCooldownCounter() {
    // Directly deletes the wl_cooldowns KV record and on-disk markers
    // so the 5-changes-per-day production rate limit doesn't block
    // the full test suite. Production code has no analog — only a
    // recovery script can do this.
    assertTestHarness();
    const { spawnSync } = require("child_process");
    spawnSync("docker", ["exec", "-u", "0", EXPECTED_TEST_CONTAINER,
        "curl", "-s", "-k", "-u", "admin:Chang3d!", "-X", "DELETE",
        "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns/state",
    ], { env: { ...process.env, MSYS_NO_PATHCONV: "1" }, encoding: "utf8" });
    spawnSync("docker", ["exec", "-u", "0", EXPECTED_TEST_CONTAINER,
        "rm", "-f",
        "/opt/splunk/etc/apps/wl_manager/lookups/_versions/.cooldown_tamper",
        "/opt/splunk/etc/apps/wl_manager/lookups/_versions/.cooldown_initialized",
    ], { env: { ...process.env, MSYS_NO_PATHCONV: "1" }, encoding: "utf8" });
}

module.exports = {
    test, summary, createSession, navigateToWM, navigateToCP, selectRule,
    waitForTable, restCall, log, results, BASE, REST,
    // Test-harness-only (gated)
    assertTestHarness, clearKvCooldownCounter,
    EXPECTED_TEST_CONTAINER,
};
