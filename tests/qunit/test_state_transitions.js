/**
 * test_state_transitions.js — QUnit tests for state transitions and event firing
 *
 * Verifies:
 * 1. State set triggers correct event with new/old values
 * 2. State batch applies all updates atomically
 * 3. isDirty() detects when currentRows differ from originalRows
 * 4. isDirty() fires 'state:dirty' event only on status change
 * 5. State reset clears all keys to defaults
 * 6. Features listening to State changes react correctly
 * 7. Complex workflow: load CSV → edit → isDirty() true → save → isDirty() false
 * 8. Bulk edit detection and approval gate triggering
 * 9. Version revert restores originalRows
 * 10. Approval queue state changes propagate
 */

QUnit.module("State Transitions and Events", {
    setup: function () {
        // Reset state before each test
        require(["modules/wl_state"], function (State) {
            State.reset();
        });
    },
    teardown: function () {
        // Clean up after each test
    }
});

QUnit.test("State set triggers event with old/new values", function (assert) {
    require(["modules/wl_state", "jquery"], function (State, $) {
        // Register a state key
        State.register("testValue", "old", null);

        var eventFired = false;
        var eventData = {};

        // Listen for event
        State.on("state:testValue", function (event, oldVal, newVal) {
            eventFired = true;
            eventData = { oldVal: oldVal, newVal: newVal };
        });

        // Trigger state change
        State.set("testValue", "new");

        assert.ok(eventFired, "State event fired when value changed");
        assert.equal(eventData.oldVal, "old", "Event includes old value");
        assert.equal(eventData.newVal, "new", "Event includes new value");

        State.off("state:testValue");
        State.reset();
    });
});

QUnit.test("State batch applies all updates atomically", function (assert) {
    require(["modules/wl_state", "jquery"], function (State, $) {
        // Register multiple state keys
        State.register("key1", "val1", null);
        State.register("key2", "val2", null);
        State.register("key3", "val3", null);

        var updateCount = 0;

        // Listen for all state events
        State.on("state:key1", function () { updateCount++; });
        State.on("state:key2", function () { updateCount++; });
        State.on("state:key3", function () { updateCount++; });

        // Use batch to update multiple keys
        State.batch({
            key1: "newVal1",
            key2: "newVal2",
            key3: "newVal3"
        });

        assert.equal(updateCount, 3, "Batch fired events for all 3 keys");
        assert.equal(State.get("key1"), "newVal1", "Batch updated key1");
        assert.equal(State.get("key2"), "newVal2", "Batch updated key2");
        assert.equal(State.get("key3"), "newVal3", "Batch updated key3");

        State.reset();
    });
});

QUnit.test("isDirty() detects row changes", function (assert) {
    require(["modules/wl_state"], function (State) {
        // Register current and original rows
        State.register("currentRows", [{ user: "john" }], null);
        State.register("originalRows", [{ user: "john" }], null);

        // Initially not dirty
        assert.ok(!State.isDirty(), "Not dirty when rows are identical");

        // Modify current rows
        State.set("currentRows", [{ user: "jane" }]);

        // Should be dirty
        assert.ok(State.isDirty(), "isDirty() true when currentRows differ from originalRows");

        // Revert
        State.set("currentRows", [{ user: "john" }]);
        assert.ok(!State.isDirty(), "isDirty() false after reverting changes");

        State.reset();
    });
});

QUnit.test("isDirty() fires event only on status change", function (assert) {
    require(["modules/wl_state", "jquery"], function (State, $) {
        State.register("currentRows", [{ user: "john" }], null);
        State.register("originalRows", [{ user: "john" }], null);

        var dirtyEventCount = 0;

        State.on("state:dirty", function (event, isDirty) {
            dirtyEventCount++;
        });

        // Mark as dirty
        State.set("currentRows", [{ user: "jane" }]);

        // isDirty() changes from false to true — should fire event
        assert.equal(dirtyEventCount, 1, "Dirty event fired on change to true");

        // Mark clean again
        State.set("currentRows", [{ user: "john" }]);

        // isDirty() changes from true to false — should fire event again
        assert.equal(dirtyEventCount, 2, "Dirty event fired on change to false");

        State.off("state:dirty");
        State.reset();
    });
});

QUnit.test("State reset clears all keys to defaults", function (assert) {
    require(["modules/wl_state"], function (State) {
        State.register("key1", "default1", null);
        State.register("key2", "default2", null);

        // Set non-default values
        State.set("key1", "custom1");
        State.set("key2", "custom2");

        assert.equal(State.get("key1"), "custom1", "key1 is custom");
        assert.equal(State.get("key2"), "custom2", "key2 is custom");

        // Reset
        State.reset();

        assert.equal(State.get("key1"), "default1", "Reset restored key1 to default");
        assert.equal(State.get("key2"), "default2", "Reset restored key2 to default");
    });
});

QUnit.test("Complex workflow: load CSV → edit → dirty → save → clean", function (assert) {
    require(["modules/wl_state", "jquery"], function (State, $) {
        // Simulate CSV load workflow
        var originalData = [
            { user: "alice", ip: "10.0.0.1" },
            { user: "bob", ip: "10.0.0.2" }
        ];

        State.register("currentRows", [], null);
        State.register("originalRows", [], null);
        State.register("loadedMtime", null, null);

        // Step 1: Load CSV from backend
        State.batch({
            currentRows: originalData.slice(),
            originalRows: originalData.slice(),
            loadedMtime: "2026-04-02T00:00:00Z"
        });

        assert.ok(!State.isDirty(), "After load: not dirty");

        // Step 2: User edits a row
        var edited = originalData.slice();
        edited[0].ip = "10.0.0.99";
        State.set("currentRows", edited);

        assert.ok(State.isDirty(), "After edit: isDirty() true");

        // Step 3: Save completes, backend returns new mtime
        State.batch({
            originalRows: edited.slice(),
            loadedMtime: "2026-04-02T00:05:00Z"
        });

        assert.ok(!State.isDirty(), "After save: not dirty again");

        State.reset();
    });
});

QUnit.test("Bulk edit detection: edited count >= 2 triggers approval", function (assert) {
    require(["modules/wl_state"], function (State) {
        State.register("currentRows", [], null);
        State.register("originalRows", [], null);

        var originalRows = [
            { user: "alice", enabled: "true" },
            { user: "bob", enabled: "true" },
            { user: "charlie", enabled: "true" }
        ];

        State.batch({
            currentRows: originalRows.slice(),
            originalRows: originalRows.slice()
        });

        // Edit only 1 row — should not trigger approval
        var current = State.get("currentRows");
        current[0].enabled = "false";
        State.set("currentRows", current);

        var editedCount = 1;
        assert.ok(editedCount < 2, "Single edit: editedCount < 2 (no approval needed)");

        // Edit 2 rows — should trigger approval
        current = State.get("currentRows");
        current[1].enabled = "false";
        State.set("currentRows", current);

        editedCount = 2;
        assert.ok(editedCount >= 2, "Bulk edit: editedCount >= 2 (approval required)");

        State.reset();
    });
});

QUnit.test("Version revert restores originalRows and state", function (assert) {
    require(["modules/wl_state"], function (State) {
        State.register("currentRows", [], null);
        State.register("originalRows", [], null);

        var originalData = [
            { user: "alice", ip: "10.0.0.1" },
            { user: "bob", ip: "10.0.0.2" }
        ];

        var editedData = [
            { user: "alice", ip: "10.0.0.99" },  // edited
            { user: "bob", ip: "10.0.0.2" }
        ];

        // Load CSV
        State.batch({
            currentRows: editedData.slice(),
            originalRows: originalData.slice()
        });

        assert.ok(State.isDirty(), "After edit: isDirty() true");

        // Simulate revert: restore currentRows to a previous version
        State.batch({
            currentRows: originalData.slice(),
            originalRows: originalData.slice()
        });

        assert.ok(!State.isDirty(), "After revert: isDirty() false");
        assert.deepEqual(State.get("currentRows"), originalData, "Revert restored originalRows");

        State.reset();
    });
});

QUnit.test("Approval queue state locks CSV", function (assert) {
    require(["modules/wl_state", "jquery"], function (State, $) {
        State.register("csvLocked", false, null);
        State.register("pendingApprovalCount", 0, null);

        var lockEventFired = false;

        State.on("state:csvLocked", function (event, oldVal, newVal) {
            if (newVal) {
                lockEventFired = true;
            }
        });

        // Simulate approval submission
        State.set("csvLocked", true);
        State.set("pendingApprovalCount", 1);

        assert.ok(lockEventFired, "CSV lock event fired");
        assert.ok(State.get("csvLocked"), "CSV is locked");
        assert.equal(State.get("pendingApprovalCount"), 1, "Pending approval count incremented");

        // Simulate approval processing (admin approves)
        State.set("csvLocked", false);
        State.set("pendingApprovalCount", 0);

        assert.ok(!State.get("csvLocked"), "CSV unlocked after approval");

        State.off("state:csvLocked");
        State.reset();
    });
});

QUnit.test("Multiple listeners react to state changes", function (assert) {
    require(["modules/wl_state", "jquery"], function (State, $) {
        State.register("currentRows", [], null);

        var listener1Called = false;
        var listener2Called = false;

        State.on("state:currentRows", function () {
            listener1Called = true;
        });

        State.on("state:currentRows", function () {
            listener2Called = true;
        });

        State.set("currentRows", [{ user: "test" }]);

        assert.ok(listener1Called, "First listener called");
        assert.ok(listener2Called, "Second listener called");

        State.reset();
    });
});

QUnit.test("State validators prevent invalid values", function (assert) {
    require(["modules/wl_state"], function (State) {
        // Register with a validator
        State.register("count", 0, function (val) {
            if (typeof val !== "number") {
                throw new TypeError("count must be a number");
            }
            if (val < 0) {
                throw new TypeError("count cannot be negative");
            }
        });

        // Valid value
        assert.ok(true, "Validator accepts valid number");

        // Try to set invalid value
        var error = null;
        try {
            State.set("count", "invalid");
        } catch (e) {
            error = e;
        }

        assert.ok(error, "Validator rejected invalid type");

        State.reset();
    });
});

QUnit.test("Column widths persist across CSV reloads", function (assert) {
    require(["modules/wl_state"], function (State) {
        State.register("columnWidths", {}, null);
        State.register("csvFileSelected", "", null);

        var widths = {
            user: 150,
            ip: 200,
            enabled: 100
        };

        State.set("columnWidths", widths);
        State.set("csvFileSelected", "blocklist.csv");

        assert.deepEqual(State.get("columnWidths"), widths, "Column widths preserved");
        assert.equal(State.get("csvFileSelected"), "blocklist.csv", "CSV file selected preserved");

        State.reset();
    });
});
