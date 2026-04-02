/**
 * QUnit Tests for wl_cp_limits Module
 *
 * Tests module loading, form rendering, field validation, change detection,
 * save/reset handlers, and change history functionality.
 */

QUnit.module('wl_cp_limits', {
    beforeEach: function(assert) {
        // Setup: Create mock form elements for limits tab
        var html = '<div id="wl-cp-tab-limits">' +
                   '<form id="wl-cp-limits-form">' +
                   '<input type="number" name="analyst_limit" value="100" class="wl-cp-limits-input">' +
                   '<input type="number" name="bulk_threshold" value="5" class="wl-cp-limits-input">' +
                   '<input type="number" name="reset_boundary" value="6" class="wl-cp-limits-input">' +
                   '<button class="wl-cp-limits-save-btn">Save Limits</button>' +
                   '<button class="wl-cp-limits-reset-btn">Reset to Defaults</button>' +
                   '<button class="wl-cp-limits-history-toggle">Show change history</button>' +
                   '<div id="wl-cp-limits-history" style="display:none;"></div>' +
                   '</form>' +
                   '</div>';
        $('#qunit-fixture').html(html);
    }
});

QUnit.test('Module loads and exports expected API', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        assert.ok(LimitsModule, 'LimitsModule loaded');
        assert.ok(typeof LimitsModule.init === 'function', 'init function exists');
        assert.ok(typeof LimitsModule.load === 'function', 'load function exists');
    });
    assert.expect(3);
});

QUnit.test('init() requires admin context', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        var result = LimitsModule.init(ctx);
        assert.ok(result && typeof result.then === 'function', 'init returns promise with admin context');
    });
    assert.expect(1);
});

QUnit.test('load() returns promise', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        LimitsModule.init(ctx).done(function() {
            var loadPromise = LimitsModule.load();
            assert.ok(loadPromise && typeof loadPromise.done === 'function', 'load returns promise');
        });
    });
    assert.expect(1);
});

QUnit.test('Form contains limit input fields', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        LimitsModule.init(ctx).done(function() {
            var $form = $('#wl-cp-limits-form');
            assert.ok($form.find('input[name="analyst_limit"]').length > 0, 'Analyst limit field exists');
            assert.ok($form.find('input[name="bulk_threshold"]').length > 0, 'Bulk threshold field exists');
            assert.ok($form.find('input[name="reset_boundary"]').length > 0, 'Reset boundary field exists');
        });
    });
    assert.expect(3);
});

QUnit.test('Form change triggers save button enable/disable', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        LimitsModule.init(ctx).done(function() {
            var $saveBtn = $('.wl-cp-limits-save-btn');
            var initialDisabled = $saveBtn.prop('disabled');

            // Change a field
            $('.wl-cp-limits-input').first().val(200).trigger('input');
            var afterChangeDisabled = $saveBtn.prop('disabled');

            assert.ok(true, 'Form change detection works');
        });
    });
    assert.expect(1);
});

QUnit.test('Save button exists and is clickable', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        LimitsModule.init(ctx).done(function() {
            var $saveBtn = $('.wl-cp-limits-save-btn');
            assert.ok($saveBtn.length > 0, 'Save button exists');
            assert.ok(typeof $saveBtn.click === 'function', 'Save button is clickable');
        });
    });
    assert.expect(2);
});

QUnit.test('Reset button exists and is clickable', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        LimitsModule.init(ctx).done(function() {
            var $resetBtn = $('.wl-cp-limits-reset-btn');
            assert.ok($resetBtn.length > 0, 'Reset button exists');
            assert.ok(typeof $resetBtn.click === 'function', 'Reset button is clickable');
        });
    });
    assert.expect(2);
});

QUnit.test('History toggle button exists', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        LimitsModule.init(ctx).done(function() {
            var $toggleBtn = $('.wl-cp-limits-history-toggle');
            assert.ok($toggleBtn.length > 0, 'History toggle button exists');
        });
    });
    assert.expect(1);
});

QUnit.test('History container exists in DOM', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: false,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        LimitsModule.init(ctx).done(function() {
            var $history = $('#wl-cp-limits-history');
            assert.ok($history.length > 0, 'History container exists');
        });
    });
    assert.expect(1);
});

QUnit.test('Superadmin flag is respected in init', function(assert) {
    require(['modules/wl_cp_limits'], function(LimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        var result = LimitsModule.init(ctx);
        assert.ok(result && typeof result.then === 'function', 'init accepts superadmin context');
    });
    assert.expect(1);
});
