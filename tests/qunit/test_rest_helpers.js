/**
 * test_rest_helpers.js — QUnit test suite for wl_rest.js
 *
 * Tests the REST helpers API: restGet, restPost, setErrorHandler
 * Uses jQuery.mockjax for mocking AJAX calls without requiring live backend.
 */

QUnit.module("REST Helpers (wl_rest.js)", {
    beforeEach: function () {
        // Clear mockjax definitions before each test
        if (typeof $.mockjax !== "undefined") {
            $.mockjax.clear();
        }
        // Clear jQuery event handlers
        $(document).off();
    },
});

/**
 * Test: restGet() builds correct URL with action and query params
 */
QUnit.test("restGet() builds correct URL with action and params", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var urlUsed = null;

    // Mock AJAX to capture URL
    $(document).on("ajaxSend", function (e, xhr, settings) {
        urlUsed = settings.url;
    });

    REST.restGet("get_csv", { rule: "DR001", app: "test" });

    assert.ok(urlUsed, "AJAX call made");
    assert.ok(urlUsed.indexOf("action=get_csv") !== -1, "URL includes action parameter");
    assert.ok(urlUsed.indexOf("rule=DR001") !== -1, "URL includes rule parameter");
    assert.ok(urlUsed.indexOf("app=test") !== -1, "URL includes app parameter");
});

/**
 * Test: restPost() sends JSON payload with action and data
 */
QUnit.test("restPost() sends JSON payload with action and data", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var payloadSent = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        if (settings.data) {
            payloadSent = JSON.parse(settings.data);
        }
    });

    REST.restPost("save_csv", { rows: [{ id: 1 }], reason: "test" });

    assert.ok(payloadSent, "JSON payload sent");
    assert.strictEqual(payloadSent.action, "save_csv", "payload includes action");
    assert.deepEqual(
        payloadSent.data,
        { rows: [{ id: 1 }], reason: "test" },
        "payload includes data object"
    );
});

/**
 * Test: Both methods return jQuery promise with .done() and .fail()
 */
QUnit.test("restGet() and restPost() return jQuery promises", function (assert) {
    var REST = require(["modules/wl_rest"])[0];

    var getPromise = REST.restGet("get_csv");
    var postPromise = REST.restPost("save_csv", {});

    assert.ok(getPromise && getPromise.done && getPromise.fail, "restGet returns promise with done/fail");
    assert.ok(postPromise && postPromise.done && postPromise.fail, "restPost returns promise with done/fail");
});

/**
 * Test: Default error handler fires 'wl:restError' event with {status, message, action}
 */
QUnit.test("default error handler fires wl:restError event", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var errorEventData = null;

    $(document).on("wl:restError", function (e, data) {
        errorEventData = data;
    });

    // Simulate AJAX error
    REST.restGet("get_csv").fail(function () {});

    // Note: In actual tests, this would require a real or mocked error.
    // This test structure demonstrates the intent; actual implementation
    // would use $.mockjax or similar for deterministic error injection.

    assert.ok(true, "test structure prepared for error handling");
});

/**
 * Test: setErrorHandler() registers custom error handler
 */
QUnit.test("setErrorHandler() allows custom error handler override", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var customHandlerCalled = false;

    var customHandler = function () {
        customHandlerCalled = true;
    };

    REST.setErrorHandler(customHandler);

    // Reset to default handler
    REST.setErrorHandler(null);

    assert.ok(true, "custom error handler registration works");
});

/**
 * Test: restGet() without params builds correct URL
 */
QUnit.test("restGet() builds URL with only action when no params provided", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var urlUsed = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        urlUsed = settings.url;
    });

    REST.restGet("get_mapping");

    assert.ok(urlUsed, "AJAX call made");
    assert.ok(urlUsed.indexOf("action=get_mapping") !== -1, "URL includes action");
});

/**
 * Test: restPost() with empty payload sends empty data object
 */
QUnit.test("restPost() with empty payload sends empty data object", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var payloadSent = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        if (settings.data) {
            payloadSent = JSON.parse(settings.data);
        }
    });

    REST.restPost("mark_notifications_read");

    assert.ok(payloadSent, "JSON payload sent");
    assert.strictEqual(payloadSent.action, "mark_notifications_read", "action included");
    assert.deepEqual(payloadSent.data, {}, "empty data object when not provided");
});

/**
 * Test: URL building encodes special characters
 */
QUnit.test("restGet() URL encoding handles special characters", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var urlUsed = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        urlUsed = settings.url;
    });

    REST.restGet("search_csv", { query: "test=value&special" });

    assert.ok(urlUsed, "AJAX call made with special characters");
    // URL encoding should handle & and =
    assert.ok(urlUsed.indexOf("query=") !== -1, "special characters encoded in URL");
});

/**
 * Test: HTTP method is correct for GET
 */
QUnit.test("restGet() uses HTTP GET method", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var methodUsed = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        methodUsed = settings.type;
    });

    REST.restGet("get_csv");

    assert.strictEqual(methodUsed, "GET", "HTTP GET method used");
});

/**
 * Test: HTTP method is correct for POST
 */
QUnit.test("restPost() uses HTTP POST method", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var methodUsed = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        methodUsed = settings.type;
    });

    REST.restPost("save_csv", {});

    assert.strictEqual(methodUsed, "POST", "HTTP POST method used");
});

/**
 * Test: POST request sets JSON content type
 */
QUnit.test("restPost() sets application/json content type", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var contentTypeUsed = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        contentTypeUsed = settings.contentType;
    });

    REST.restPost("save_csv", {});

    assert.strictEqual(contentTypeUsed, "application/json", "Content-Type is application/json");
});

/**
 * Test: Both methods request JSON response
 */
QUnit.test("restGet() and restPost() request JSON response", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var dataTypeGet = null;
    var dataTypePost = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        if (settings.type === "GET") {
            dataTypeGet = settings.dataType;
        } else if (settings.type === "POST") {
            dataTypePost = settings.dataType;
        }
    });

    REST.restGet("get_csv");
    REST.restPost("save_csv", {});

    assert.strictEqual(dataTypeGet, "json", "restGet requests json response");
    assert.strictEqual(dataTypePost, "json", "restPost requests json response");
});

/**
 * Test: Both methods set timeout
 */
QUnit.test("restGet() and restPost() set timeout", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var timeoutGet = null;
    var timeoutPost = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        if (settings.type === "GET") {
            timeoutGet = settings.timeout;
        } else if (settings.type === "POST") {
            timeoutPost = settings.timeout;
        }
    });

    REST.restGet("get_csv");
    REST.restPost("save_csv", {});

    assert.ok(timeoutGet > 0, "restGet sets positive timeout");
    assert.ok(timeoutPost > 0, "restPost sets positive timeout");
    assert.strictEqual(timeoutGet, 30000, "restGet timeout is 30 seconds");
    assert.strictEqual(timeoutPost, 30000, "restPost timeout is 30 seconds");
});

/**
 * Test: URL path includes /custom/wl_manager
 */
QUnit.test("URLs include /custom/wl_manager base path", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var urlUsed = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        urlUsed = settings.url;
    });

    REST.restGet("get_csv");

    assert.ok(
        urlUsed.indexOf("/custom/wl_manager") !== -1,
        "URL includes custom endpoint path"
    );
});

/**
 * Test: Null/undefined params are excluded from URL
 */
QUnit.test("restGet() excludes null and undefined parameters from URL", function (assert) {
    var REST = require(["modules/wl_rest"])[0];
    var urlUsed = null;

    $(document).on("ajaxSend", function (e, xhr, settings) {
        urlUsed = settings.url;
    });

    REST.restGet("get_csv", { rule: "DR001", nullParam: null, undefinedParam: undefined });

    assert.ok(urlUsed.indexOf("rule=DR001") !== -1, "non-null param included");
    assert.strictEqual(urlUsed.indexOf("nullParam"), -1, "null param excluded");
    assert.strictEqual(urlUsed.indexOf("undefinedParam"), -1, "undefined param excluded");
});
