// ╔═══════════════════════════════════════════════════════════════════╗
// ║  ⚠  META-TEST: Verifies the test harness safety gate itself    ║
// ║                                                                 ║
// ║  This file spawns child processes that probe the                ║
// ║  WL_TEST_HARNESS gate — it does NOT modify container state      ║
// ║  directly, but validates that the gate blocks correctly.        ║
// ╚═══════════════════════════════════════════════════════════════════╝
/**
 * Test-harness gate verification.
 *
 * Verifies that lib_helpers.cjs :: assertTestHarness refuses to run
 * destructive helpers when:
 *   - WL_TEST_HARNESS is not set
 *   - WL_TEST_HARNESS is set to anything other than "1"
 *   - the test container is not running (best we can simulate: check
 *     that the guard queries docker)
 *
 * And accepts when WL_TEST_HARNESS=1 AND the container exists.
 *
 * This test spawns child processes so it can manipulate env vars
 * cleanly without polluting the parent process.
 */
const { spawnSync } = require("child_process");
const path = require("path");

const results = [];
function test(name, fn) {
    try {
        fn();
        results.push({ name, status: "PASS" });
        console.log("✅ " + name);
    } catch (e) {
        results.push({ name, status: "FAIL", error: e.message });
        console.log("❌ " + name + ": " + e.message);
    }
}

function runChild(envOverride) {
    // Run a tiny node script that imports the helper and calls the
    // destructive function, then reports the result. The child
    // inherits our cwd so require() of lib_helpers.cjs works.
    const script = `
        const H = require(${JSON.stringify(path.join(__dirname, "lib_helpers.cjs"))});
        try {
            H.clearKvCooldownCounter();
            console.log("ALLOWED");
        } catch (e) {
            console.log("BLOCKED: " + e.message);
        }
    `;
    const env = { ...process.env };
    // Strip any existing WL_TEST_HARNESS so each child starts clean
    delete env.WL_TEST_HARNESS;
    Object.assign(env, envOverride || {});
    const res = spawnSync("node", ["-e", script], {
        env, encoding: "utf8", cwd: __dirname,
    });
    return (res.stdout || "") + (res.stderr || "");
}

test("TH01 assertTestHarness blocks when WL_TEST_HARNESS unset", () => {
    const out = runChild({});
    if (!out.includes("BLOCKED")) {
        throw new Error("Expected BLOCKED, got: " + out.trim().substring(0, 300));
    }
    if (!out.includes("WL_TEST_HARNESS")) {
        throw new Error("Error message should mention WL_TEST_HARNESS: " + out);
    }
});

test("TH02 assertTestHarness blocks when WL_TEST_HARNESS=0", () => {
    const out = runChild({ WL_TEST_HARNESS: "0" });
    if (!out.includes("BLOCKED")) {
        throw new Error("Expected BLOCKED, got: " + out.trim().substring(0, 300));
    }
});

test("TH03 assertTestHarness blocks when WL_TEST_HARNESS=true (not '1')", () => {
    const out = runChild({ WL_TEST_HARNESS: "true" });
    if (!out.includes("BLOCKED")) {
        throw new Error("Expected BLOCKED (only '1' accepted), got: " + out.trim().substring(0, 300));
    }
});

test("TH04 assertTestHarness allows when WL_TEST_HARNESS=1 AND container running", () => {
    // We trust the container is running during a normal test run.
    const out = runChild({ WL_TEST_HARNESS: "1" });
    if (!out.includes("ALLOWED")) {
        throw new Error("Expected ALLOWED, got: " + out.trim().substring(0, 300));
    }
});

const passed = results.filter(r => r.status === "PASS").length;
const failed = results.filter(r => r.status === "FAIL").length;
console.log(`\n========================================`);
console.log(`Test Harness Gate: PASSED=${passed} FAILED=${failed} TOTAL=${results.length}`);
console.log(`========================================\n`);
process.exit(failed > 0 ? 1 : 0);
