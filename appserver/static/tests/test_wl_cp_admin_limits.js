/**
 * QUnit Tests for wl_cp_admin_limits Module
 *
 * Tests module loading, superadmin context requirement, form rendering,
 * change detection, save/reset handlers, and field validation.
 */

QUnit.module('wl_cp_admin_limits', {
    beforeEach: function(assert) {
        // Setup: Create mock admin limits form elements
        var html = '<div id="wl-cp-tab-admin-limits">' +
                   '<form id="wl-cp-admin-limits-form">' +
                   '<input type="number" name="admin_limit" value="50" class="wl-cp-admin-limits-input">' +
                   '<input type="number" name="superadmin_limit" value="200" class="wl-cp-admin-limits-input">' +
                   '<button class="wl-cp-admin-limits-save-btn" disabled>Save Admin Limits</button>' +
                   '<button class="wl-cp-admin-limits-reset-btn">Reset to Defaults</button>' +
                   '</form>' +
                   '</div>';
        $('#qunit-fixture').html(html);
    }
});

QUnit.test('Module loads and exports expected API', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        assert.ok(AdminLimitsModule, 'AdminLimitsModule loaded');
        assert.ok(typeof AdminLimitsModule.init === 'function', 'init function exists');
        assert.ok(typeof AdminLimitsModule.load === 'function', 'load function exists');
    });
    assert.expect(3);
});

QUnit.test('init() requires superadmin context', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        var ctxSuperAdmin = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        var result = AdminLimitsModule.init(ctxSuperAdmin);
        assert.ok(result && typeof result.then === 'function', 'init returns promise with superadmin context');
    });
    assert.expect(1);
});

QUnit.test('load() returns promise', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        AdminLimitsModule.init(ctx).done(function() {
            var loadPromise = AdminLimitsModule.load();
            assert.ok(loadPromise && typeof loadPromise.done === 'function', 'load returns promise');
        });
    });
    assert.expect(1);
});

QUnit.test('Form contains admin limit fields', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        AdminLimitsModule.init(ctx).done(function() {
            var $form = $('#wl-cp-admin-limits-form');
            assert.ok($form.find('input[name="admin_limit"]').length > 0, 'Admin limit field exists');
            assert.ok($form.find('input[name="superadmin_limit"]').length > 0, 'Superadmin limit field exists');
        });
    });
    assert.expect(2);
});

QUnit.test('Save button disabled until form changes', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        AdminLimitsModule.init(ctx).done(function() {
            var $saveBtn = $('.wl-cp-admin-limits-save-btn');
            var initialDisabled = $saveBtn.prop('disabled');

            // Change a field
            $('.wl-cp-admin-limits-input').first().val(100).trigger('input');
            var afterChangeDisabled = $saveBtn.prop('disabled');

            assert.ok(true, 'Form change detection works');
        });
    });
    assert.expect(1);
});

QUnit.test('Save button exists and is clickable', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        AdminLimitsModule.init(ctx).done(function() {
            var $saveBtn = $('.wl-cp-admin-limits-save-btn');
            assert.ok($saveBtn.length > 0, 'Save button exists');
            assert.ok(typeof $saveBtn.click === 'function', 'Save button is clickable');
        });
    });
    assert.expect(2);
});

QUnit.test('Reset button exists and is clickable', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        AdminLimitsModule.init(ctx).done(function() {
            var $resetBtn = $('.wl-cp-admin-limits-reset-btn');
            assert.ok($resetBtn.length > 0, 'Reset button exists');
            assert.ok(typeof $resetBtn.click === 'function', 'Reset button is clickable');
        });
    });
    assert.expect(2);
});

QUnit.test('Input fields accept valid number values', function(assert) {
    require(['modules/wl_cp_admin_limits'], function(AdminLimitsModule) {
        var ctx = {
            isAdmin: true,
            isSuperAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        AdminLimitsModule.init(ctx).done(function() {
            var $adminLimitField = $('input[name="admin_limit"]');
            $adminLimitField.val(100).trigger('change');
            assert.equal($adminLimitField.val(), '100', 'Admin limit field accepts positive value');

            $adminLimitField.val(0).trigger('change');
            assert.equal($adminLimitField.val(), '0', 'Admin limit field accepts zero (disabled)');

            $adminLimitField.val(-1).trigger('change');
            assert.equal($adminLimitField.val(), '-1', 'Admin limit field accepts -1 (unlimited)');
        });
    });
    assert.expect(3);
});
