/**
 * AMD → CommonJS bridge for testing the Splunk-bundled
 * RequireJS modules under appserver/static/modules/.
 *
 * The frontend modules use AMD ``define([deps], factory)``
 * because that's what Splunk's RequireJS loader expects at
 * runtime. RequireJS doesn't ship with Node — and we don't
 * want to add it as a test dep just to run unit tests on
 * pure helper functions.
 *
 * The bridge is ~30 lines: parse the file, eval it inside a
 * VM context with a custom ``define`` that captures the
 * factory's return value, and feed dependency mocks if any.
 *
 * For modules whose pure functions don't actually USE the
 * imports (e.g. ``parseCSV`` in wl_csv_io.js uses only
 * String/RegExp/Array — never the injected jQuery), just
 * pass ``{}`` for each mock. For modules that need real
 * deps, hand-build minimal mocks (a couple of jQuery methods,
 * underscore.escape, etc.).
 *
 * Why VM not require(): the modules call ``define`` at
 * top level, which is not a real CommonJS pattern. ``require``
 * would throw "define is not defined". Running inside a VM
 * with a sandboxed ``define`` is the canonical workaround.
 *
 * Ring 4 Day 1.
 */
"use strict";

const fs = require("fs");
const vm = require("vm");

/**
 * Load an AMD module from disk and return its factory's
 * exports.
 *
 * @param {string} modulePath - absolute path to the .js file
 * @param {object} [mocks] - map of AMD dep ID -> mock object
 *   (defaults to empty object for any missing dep)
 * @returns {*} whatever the AMD factory returned
 */
function loadAmdModule(modulePath, mocks) {
    mocks = mocks || {};
    let captured = null;
    let defined = false;

    const sandbox = {
        define: function (depsOrFactory, factory) {
            defined = true;
            // define([deps], factory)
            if (Array.isArray(depsOrFactory)) {
                const resolved = depsOrFactory.map(function (d) {
                    if (Object.prototype.hasOwnProperty.call(mocks, d)) {
                        return mocks[d];
                    }
                    // Strict mode: surface unmocked deps so test
                    // authors don't accidentally pass undefined
                    // into the factory and get cryptic errors
                    // deep inside the module.
                    return {};
                });
                captured = factory.apply(null, resolved);
            } else if (typeof depsOrFactory === "function") {
                // define(factory) — no deps
                captured = depsOrFactory();
            } else if (typeof depsOrFactory === "object"
                    && factory === undefined) {
                // define(object) — value-only module
                captured = depsOrFactory;
            } else {
                throw new Error(
                    "Unsupported define() signature in "
                    + modulePath);
            }
        },
        // Provide a few globals the modules might touch
        // during top-level evaluation. window/document are
        // not needed for pure functions but the sandbox
        // forwards them anyway in case a future module needs.
        console: console,
    };
    sandbox.window = sandbox;
    sandbox.global = sandbox;

    const code = fs.readFileSync(modulePath, "utf8");
    const context = vm.createContext(sandbox);
    try {
        vm.runInContext(code, context,
            { filename: modulePath });
    } catch (e) {
        throw new Error(
            "Failed to evaluate AMD module " + modulePath
            + ":\n  " + (e.stack || e.message));
    }

    if (!defined) {
        throw new Error(
            "Module did not call define(): " + modulePath);
    }
    if (captured == null) {
        throw new Error(
            "AMD factory returned null/undefined: "
            + modulePath);
    }
    return captured;
}

module.exports = { loadAmdModule };
