/**
 * Vitest config for the JS unit-test suite.
 *
 * Why a separate config: the repo's existing E2E .cjs tests
 * under tests/e2e/ are NOT vitest tests — they're the
 * ad-hoc lib_helpers.cjs runner. We need vitest to only
 * pick up tests/js/*.test.cjs and ignore everything else.
 *
 * Ring 4 Day 1.
 */
"use strict";

const { defineConfig } = require("vitest/config");

module.exports = defineConfig({
    test: {
        // Only pick up our deliberate test files.
        include: ["tests/js/**/*.test.mjs", "tests/js/**/*.test.cjs"],
        // Don't accidentally pick up tests/e2e/ playwright-
        // core tests or tests/integration/ pytest files.
        exclude: [
            "node_modules/**",
            "tests/e2e/**",
            "tests/integration/**",
            "tests/unit/**",
            "tests/semgrep/**",
        ],
        // Node environment (we're testing pure JS modules,
        // no DOM). jsdom is an option for later when we
        // start testing modules that touch the DOM.
        environment: "node",
        // Default reporter is fine. CI integration deferred
        // to the dedicated CI workflow phase of Ring 4.
        reporters: ["default"],
    },
});
