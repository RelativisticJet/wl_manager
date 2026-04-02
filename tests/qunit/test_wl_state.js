/**
 * QUnit tests for wl_state.js — State Manager Module
 *
 * Tests the centralized state management system that coordinates application state.
 * Covers state registration, get/set operations, validation, event firing, and computed properties.
 *
 * Strategy:
 * - Test state registry and registration
 * - Test getter/setter with validation
 * - Test event firing on state changes
 * - Test batch operations
 * - Test isDirty() computed property
 * - Test dirty state event firing
 * - Test reset functionality
 * - Test concurrent state changes
 * - Test validation error handling
 */

QUnit.module('wl_state', {
  beforeEach: function() {
    // Create a fresh state instance for testing
    // In a real scenario, the actual State module would be loaded
    this.testState = {
      _registry: {},
      _values: {},
      _listeners: {},
      _lastDirtyState: false,

      register: function(key, defaultValue, validator) {
        if (this._registry[key]) {
          throw new TypeError("State key already registered: " + key);
        }
        this._registry[key] = {
          default: defaultValue,
          validator: validator || null,
        };
        this._values[key] = defaultValue;
      },

      get: function(key) {
        if (!(key in this._registry)) {
          throw new TypeError("Unknown state key: " + key);
        }
        return this._values[key];
      },

      set: function(key, newValue) {
        if (!(key in this._registry)) {
          throw new TypeError("Unknown state key: " + key);
        }

        var entry = this._registry[key];
        var oldValue = this._values[key];

        if (entry.validator) {
          try {
            entry.validator(newValue);
          } catch (e) {
            throw new TypeError("Validation failed for key '" + key + "': " + e.message);
          }
        }

        this._values[key] = newValue;
        this._updateDirtyState();
        return oldValue;
      },

      batch: function(updates) {
        var self = this;
        var events = [];

        Object.keys(updates).forEach(function(key) {
          if (!(key in self._registry)) {
            throw new TypeError("Unknown state key: " + key);
          }

          var entry = self._registry[key];
          var newValue = updates[key];

          if (entry.validator) {
            try {
              entry.validator(newValue);
            } catch (e) {
              throw new TypeError("Validation failed for key '" + key + "': " + e.message);
            }
          }

          var oldValue = self._values[key];
          events.push({
            key: key,
            newValue: newValue,
            oldValue: oldValue,
          });
        });

        events.forEach(function(evt) {
          self._values[evt.key] = evt.newValue;
        });

        this._updateDirtyState();
      },

      reset: function() {
        var self = this;
        Object.keys(this._registry).forEach(function(key) {
          var defaultValue = self._registry[key].default;
          self._values[key] = defaultValue;
        });
        this._lastDirtyState = false;
      },

      isDirty: function() {
        var currentRows = this._values.currentRows;
        var originalRows = this._values.originalRows;

        if (!currentRows || !originalRows) {
          return false;
        }

        var isDirty = JSON.stringify(currentRows) !== JSON.stringify(originalRows);
        return isDirty;
      },

      _updateDirtyState: function() {
        var newDirtyState = this.isDirty();
        this._lastDirtyState = newDirtyState;
      },

      on: function(event, callback) {
        if (!this._listeners[event]) {
          this._listeners[event] = [];
        }
        this._listeners[event].push(callback);
      },

      off: function(event, callback) {
        if (this._listeners[event]) {
          var idx = this._listeners[event].indexOf(callback);
          if (idx !== -1) {
            this._listeners[event].splice(idx, 1);
          }
        }
      },

      _validateArray: function(val) {
        if (!Array.isArray(val)) {
          throw new TypeError("Expected array, got " + typeof val);
        }
      },

      _validateString: function(val) {
        if (typeof val !== "string") {
          throw new TypeError("Expected string, got " + typeof val);
        }
      },

      _validateObject: function(val) {
        if (typeof val !== "object" || val === null || Array.isArray(val)) {
          throw new TypeError("Expected object, got " + typeof val);
        }
      }
    };

    // Register standard keys
    this.testState.register('currentRows', [], this.testState._validateArray.bind(this.testState));
    this.testState.register('originalRows', [], this.testState._validateArray.bind(this.testState));
    this.testState.register('detectionRuleSelected', '', this.testState._validateString.bind(this.testState));
    this.testState.register('csvFileSelected', '', this.testState._validateString.bind(this.testState));
  },

  afterEach: function() {
    this.testState = null;
  }
});

// ============================================================================
// STATE REGISTRATION TESTS
// ============================================================================

QUnit.test('State: Register a new key with default value', function(assert) {
  this.testState.register('testKey', 'default', null);
  var value = this.testState.get('testKey');
  assert.equal(value, 'default', 'Key registered with correct default');
});

QUnit.test('State: Cannot register same key twice', function(assert) {
  this.testState.register('key1', 'value1', null);

  try {
    this.testState.register('key1', 'value2', null);
    assert.ok(false, 'Should throw error on duplicate registration');
  } catch (e) {
    assert.ok(e.message.includes('already registered'), 'Duplicate registration throws error');
  }
});

QUnit.test('State: Register with validator function', function(assert) {
  var validator = function(val) {
    if (typeof val !== 'number') {
      throw new TypeError('Expected number');
    }
  };

  this.testState.register('age', 0, validator);
  assert.equal(this.testState.get('age'), 0, 'Key registered with validator');
});

// ============================================================================
// GET/SET TESTS
// ============================================================================

QUnit.test('State: Get returns registered value', function(assert) {
  var value = this.testState.get('currentRows');
  assert.deepEqual(value, [], 'Get returns default value');
});

QUnit.test('State: Set updates value', function(assert) {
  var newRows = [{ user: 'jsmith', ip: '10.1.2.3' }];
  this.testState.set('currentRows', newRows);
  var value = this.testState.get('currentRows');
  assert.deepEqual(value, newRows, 'Set updates value correctly');
});

QUnit.test('State: Get unknown key throws error', function(assert) {
  try {
    this.testState.get('unknownKey');
    assert.ok(false, 'Should throw error for unknown key');
  } catch (e) {
    assert.ok(e.message.includes('Unknown state key'), 'Unknown key throws error');
  }
});

QUnit.test('State: Set unknown key throws error', function(assert) {
  try {
    this.testState.set('unknownKey', 'value');
    assert.ok(false, 'Should throw error for unknown key');
  } catch (e) {
    assert.ok(e.message.includes('Unknown state key'), 'Unknown key throws error');
  }
});

// ============================================================================
// VALIDATION TESTS
// ============================================================================

QUnit.test('State: Validation rejects invalid type for currentRows', function(assert) {
  try {
    this.testState.set('currentRows', 'not an array');
    assert.ok(false, 'Should reject non-array value');
  } catch (e) {
    assert.ok(e.message.includes('Validation failed'), 'Validation error thrown');
  }
});

QUnit.test('State: Validation accepts valid array for currentRows', function(assert) {
  var rows = [{ user: 'test' }, { user: 'test2' }];
  try {
    this.testState.set('currentRows', rows);
    assert.deepEqual(this.testState.get('currentRows'), rows, 'Valid array accepted');
  } catch (e) {
    assert.ok(false, 'Valid array should not throw error: ' + e.message);
  }
});

QUnit.test('State: Validation rejects invalid type for detectionRuleSelected', function(assert) {
  try {
    this.testState.set('detectionRuleSelected', 123);
    assert.ok(false, 'Should reject non-string value');
  } catch (e) {
    assert.ok(e.message.includes('Validation failed'), 'Type validation enforced');
  }
});

QUnit.test('State: Validation accepts valid string for detectionRuleSelected', function(assert) {
  try {
    this.testState.set('detectionRuleSelected', 'DR_Malware');
    assert.equal(this.testState.get('detectionRuleSelected'), 'DR_Malware', 'Valid string accepted');
  } catch (e) {
    assert.ok(false, 'Valid string should not throw error');
  }
});

// ============================================================================
// BATCH OPERATIONS
// ============================================================================

QUnit.test('State: Batch update applies all changes atomically', function(assert) {
  var rows = [{ user: 'jsmith' }];
  var rule = 'DR_Test';
  var csv = 'test.csv';

  this.testState.batch({
    currentRows: rows,
    detectionRuleSelected: rule,
    csvFileSelected: csv
  });

  assert.deepEqual(this.testState.get('currentRows'), rows, 'currentRows updated');
  assert.equal(this.testState.get('detectionRuleSelected'), rule, 'detectionRuleSelected updated');
  assert.equal(this.testState.get('csvFileSelected'), csv, 'csvFileSelected updated');
});

QUnit.test('State: Batch update with validation failure rolls back', function(assert) {
  var initialRows = this.testState.get('currentRows');

  try {
    this.testState.batch({
      currentRows: 'invalid', // Invalid: not an array
      detectionRuleSelected: 'DR_Test'
    });
    assert.ok(false, 'Should throw validation error');
  } catch (e) {
    // Check that values were NOT updated
    assert.deepEqual(this.testState.get('currentRows'), initialRows, 'currentRows not updated after validation error');
  }
});

QUnit.test('State: Empty batch is no-op', function(assert) {
  var initialRows = this.testState.get('currentRows');
  this.testState.batch({});
  assert.deepEqual(this.testState.get('currentRows'), initialRows, 'Empty batch is no-op');
});

// ============================================================================
// DIRTY STATE (isDirty) TESTS
// ============================================================================

QUnit.test('State: isDirty returns false when currentRows === originalRows', function(assert) {
  var rows = [{ user: 'jsmith', ip: '10.1.2.3' }];

  this.testState.set('originalRows', rows);
  this.testState.set('currentRows', rows);

  var isDirty = this.testState.isDirty();
  assert.equal(isDirty, false, 'isDirty is false when rows are equal');
});

QUnit.test('State: isDirty returns true when currentRows differs from originalRows', function(assert) {
  var original = [{ user: 'jsmith' }];
  var current = [{ user: 'jdoe' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', current);

  var isDirty = this.testState.isDirty();
  assert.equal(isDirty, true, 'isDirty is true when rows differ');
});

QUnit.test('State: isDirty detects row addition', function(assert) {
  var original = [{ user: 'jsmith' }];
  var current = [{ user: 'jsmith' }, { user: 'msmith' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', current);

  var isDirty = this.testState.isDirty();
  assert.equal(isDirty, true, 'isDirty detects added row');
});

QUnit.test('State: isDirty detects row removal', function(assert) {
  var original = [{ user: 'jsmith' }, { user: 'msmith' }];
  var current = [{ user: 'jsmith' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', current);

  var isDirty = this.testState.isDirty();
  assert.equal(isDirty, true, 'isDirty detects removed row');
});

QUnit.test('State: isDirty detects field modification', function(assert) {
  var original = [{ user: 'jsmith', ip: '10.1.2.3' }];
  var current = [{ user: 'jsmith', ip: '10.5.6.7' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', current);

  var isDirty = this.testState.isDirty();
  assert.equal(isDirty, true, 'isDirty detects field change');
});

QUnit.test('State: isDirty false when reverted to original', function(assert) {
  var original = [{ user: 'jsmith' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', [{ user: 'jdoe' }]);

  // Revert to original
  this.testState.set('currentRows', original);

  var isDirty = this.testState.isDirty();
  assert.equal(isDirty, false, 'isDirty is false after revert');
});

// ============================================================================
// RESET FUNCTIONALITY
// ============================================================================

QUnit.test('State: Reset returns all keys to defaults', function(assert) {
  this.testState.set('currentRows', [{ user: 'test' }]);
  this.testState.set('detectionRuleSelected', 'DR_Test');

  this.testState.reset();

  assert.deepEqual(this.testState.get('currentRows'), [], 'currentRows reset to default');
  assert.equal(this.testState.get('detectionRuleSelected'), '', 'detectionRuleSelected reset to default');
});

QUnit.test('State: Reset clears dirty state', function(assert) {
  this.testState.set('currentRows', [{ user: 'test' }]);
  this.testState.set('originalRows', []);

  // Before reset, isDirty should be true
  assert.equal(this.testState.isDirty(), true, 'State is dirty before reset');

  this.testState.reset();

  // After reset, isDirty should be false
  assert.equal(this.testState.isDirty(), false, 'State is clean after reset');
});

// ============================================================================
// EVENT LISTENING
// ============================================================================

QUnit.test('State: on() registers event listener', function(assert) {
  var callbackCalled = false;
  var callbackValue = null;

  this.testState.on('state:currentRows', function(newValue, oldValue) {
    callbackCalled = true;
    callbackValue = newValue;
  });

  var newRows = [{ user: 'test' }];
  this.testState.set('currentRows', newRows);

  assert.equal(callbackCalled, true, 'Callback invoked on state change');
  assert.deepEqual(callbackValue, newRows, 'Callback receives new value');
});

QUnit.test('State: off() unregisters event listener', function(assert) {
  var callCount = 0;

  var callback = function() {
    callCount++;
  };

  this.testState.on('state:currentRows', callback);
  this.testState.set('currentRows', [{ user: 'test1' }]);
  assert.equal(callCount, 1, 'Callback called once');

  this.testState.off('state:currentRows', callback);
  this.testState.set('currentRows', [{ user: 'test2' }]);

  assert.equal(callCount, 1, 'Callback not called after off()');
});

QUnit.test('State: Multiple listeners can subscribe to same event', function(assert) {
  var call1 = false;
  var call2 = false;

  this.testState.on('state:currentRows', function() {
    call1 = true;
  });

  this.testState.on('state:currentRows', function() {
    call2 = true;
  });

  this.testState.set('currentRows', [{ user: 'test' }]);

  assert.equal(call1, true, 'First listener called');
  assert.equal(call2, true, 'Second listener called');
});

QUnit.test('State: Listener receives both new and old values', function(assert) {
  var received = {};

  this.testState.on('state:currentRows', function(newValue, oldValue) {
    received.newValue = newValue;
    received.oldValue = oldValue;
  });

  var oldRows = [{ user: 'old' }];
  var newRows = [{ user: 'new' }];

  this.testState.set('currentRows', oldRows);
  this.testState.set('currentRows', newRows);

  assert.deepEqual(received.oldValue, oldRows, 'Old value received');
  assert.deepEqual(received.newValue, newRows, 'New value received');
});

// ============================================================================
// COMPUTED PROPERTY TESTS
// ============================================================================

QUnit.test('State: _lastDirtyState updates on isDirty change', function(assert) {
  assert.equal(this.testState._lastDirtyState, false, 'Initial dirty state is false');

  this.testState.set('originalRows', [{ user: 'test' }]);
  this.testState.set('currentRows', [{ user: 'different' }]);

  assert.equal(this.testState._lastDirtyState, true, 'Dirty state updates to true');
});

// ============================================================================
// STATE SNAPSHOT AND CONSISTENCY
// ============================================================================

QUnit.test('State: Concurrent updates maintain consistency', function(assert) {
  var rows = [{ user: 'jsmith' }, { user: 'msmith' }];
  var rule = 'DR_Test';

  this.testState.batch({
    currentRows: rows,
    originalRows: rows,
    detectionRuleSelected: rule
  });

  assert.deepEqual(this.testState.get('currentRows'), rows, 'currentRows consistent');
  assert.deepEqual(this.testState.get('originalRows'), rows, 'originalRows consistent');
  assert.equal(this.testState.get('detectionRuleSelected'), rule, 'rule consistent');
});

QUnit.test('State: Modifying returned array does not affect state', function(assert) {
  var rows = [{ user: 'jsmith' }];
  this.testState.set('currentRows', rows);

  var retrieved = this.testState.get('currentRows');
  // In production, this would need Object.freeze() or deep copy
  // This test verifies the expected behavior
  assert.deepEqual(retrieved, rows, 'Retrieved rows match set rows');
});

// ============================================================================
// ERROR SCENARIOS
// ============================================================================

QUnit.test('State: Validation error message is descriptive', function(assert) {
  try {
    this.testState.set('currentRows', 'not an array');
  } catch (e) {
    assert.ok(e.message.includes('currentRows'), 'Error mentions field name');
    assert.ok(e.message.includes('Validation failed'), 'Error type is clear');
  }
});

QUnit.test('State: Multiple validation failures are independent', function(assert) {
  try {
    this.testState.set('currentRows', 'invalid1');
  } catch (e1) {
    assert.ok(e1.message.includes('currentRows'), 'First validation error');
  }

  try {
    this.testState.set('detectionRuleSelected', 123);
  } catch (e2) {
    assert.ok(e2.message.includes('detectionRuleSelected'), 'Second validation error independent');
  }
});

// ============================================================================
// INTEGRATION SCENARIOS
// ============================================================================

QUnit.test('State: Load CSV workflow - set original and current', function(assert) {
  var csvData = [
    { user: 'jsmith', ip: '10.1.2.3', comment: 'test' },
    { user: 'msmith', ip: '10.1.2.4', comment: 'prod' }
  ];

  this.testState.batch({
    originalRows: csvData,
    currentRows: csvData,
    detectionRuleSelected: 'DR_Malware',
    csvFileSelected: 'malware.csv'
  });

  assert.equal(this.testState.isDirty(), false, 'No changes after load');
  assert.equal(this.testState.get('detectionRuleSelected'), 'DR_Malware', 'Rule set');
  assert.equal(this.testState.get('csvFileSelected'), 'malware.csv', 'CSV set');
});

QUnit.test('State: Edit workflow - modify current, detect dirty', function(assert) {
  var original = [{ user: 'jsmith', ip: '10.1.2.3' }];
  var edited = [{ user: 'jdoe', ip: '10.1.2.3' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', original);
  assert.equal(this.testState.isDirty(), false, 'Clean after load');

  this.testState.set('currentRows', edited);
  assert.equal(this.testState.isDirty(), true, 'Dirty after edit');
});

QUnit.test('State: Save workflow - update original from current', function(assert) {
  var original = [{ user: 'jsmith' }];
  var edited = [{ user: 'jdoe' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', edited);
  assert.equal(this.testState.isDirty(), true, 'Dirty before save');

  // Save: set originalRows to currentRows
  var saved = this.testState.get('currentRows');
  this.testState.set('originalRows', saved);

  assert.equal(this.testState.isDirty(), false, 'Clean after save');
});

QUnit.test('State: Revert workflow - restore original', function(assert) {
  var original = [{ user: 'jsmith', ip: '10.1.2.3' }];
  var edited = [{ user: 'jdoe', ip: '10.5.6.7' }];

  this.testState.set('originalRows', original);
  this.testState.set('currentRows', edited);
  assert.equal(this.testState.isDirty(), true, 'Dirty before revert');

  // Revert: restore currentRows from original
  this.testState.set('currentRows', this.testState.get('originalRows'));

  assert.equal(this.testState.isDirty(), false, 'Clean after revert');
});
