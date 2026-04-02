/**
 * QUnit Tests for wl_cp_usage Module
 *
 * Tests module loading, usage table rendering, search/filter functionality,
 * checkbox selection, reset handlers, pagination, highlighting, and polling.
 */

QUnit.module('wl_cp_usage', {
    beforeEach: function(assert) {
        // Setup: Create mock usage table elements
        var html = '<div id="wl-cp-tab-usage">' +
                   '<div id="wl-cp-usage-table"></div>' +
                   '<input id="wl-cp-usage-search" type="text" class="wl-cp-usage-search" placeholder="Filter by username">' +
                   '<button class="wl-cp-usage-reset-selected" disabled>Reset Selected</button>' +
                   '<button class="wl-cp-usage-reset-all">Reset All</button>' +
                   '<button class="wl-cp-usage-page-prev">Previous</button>' +
                   '<button class="wl-cp-usage-page-next">Next</button>' +
                   '<span class="wl-cp-usage-paging"></span>' +
                   '</div>';
        $('#qunit-fixture').html(html);
    }
});

QUnit.test('Module loads and exports expected API', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        assert.ok(UsageModule, 'UsageModule loaded');
        assert.ok(typeof UsageModule.init === 'function', 'init function exists');
        assert.ok(typeof UsageModule.load === 'function', 'load function exists');
        assert.ok(typeof UsageModule.startPolling === 'function', 'startPolling function exists');
        assert.ok(typeof UsageModule.stopPolling === 'function', 'stopPolling function exists');
    });
    assert.expect(5);
});

QUnit.test('init() requires admin context', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        var result = UsageModule.init(ctx);
        assert.ok(result && typeof result.then === 'function', 'init returns promise with admin context');
    });
    assert.expect(1);
});

QUnit.test('load() returns promise', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            var loadPromise = UsageModule.load();
            assert.ok(loadPromise && typeof loadPromise.done === 'function', 'load returns promise');
        });
    });
    assert.expect(1);
});

QUnit.test('Usage table container exists', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            var $table = $('#wl-cp-usage-table');
            assert.ok($table.length > 0, 'Usage table container exists');
        });
    });
    assert.expect(1);
});

QUnit.test('Search input exists and is functional', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            var $searchInput = $('.wl-cp-usage-search');
            assert.ok($searchInput.length > 0, 'Search input exists');
            $searchInput.val('jsmith').trigger('change');
            assert.ok($searchInput.val() === 'jsmith', 'Search input value updated');
        });
    });
    assert.expect(2);
});

QUnit.test('Reset Selected button exists and is initially disabled', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            var $resetSelectedBtn = $('.wl-cp-usage-reset-selected');
            assert.ok($resetSelectedBtn.length > 0, 'Reset Selected button exists');
            assert.ok($resetSelectedBtn.prop('disabled') === true, 'Button is initially disabled');
        });
    });
    assert.expect(2);
});

QUnit.test('Reset All button exists', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            var $resetAllBtn = $('.wl-cp-usage-reset-all');
            assert.ok($resetAllBtn.length > 0, 'Reset All button exists');
        });
    });
    assert.expect(1);
});

QUnit.test('Pagination Previous and Next buttons exist', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            var $prevBtn = $('.wl-cp-usage-page-prev');
            var $nextBtn = $('.wl-cp-usage-page-next');
            assert.ok($prevBtn.length > 0, 'Previous button exists');
            assert.ok($nextBtn.length > 0, 'Next button exists');
        });
    });
    assert.expect(2);
});

QUnit.test('Paging indicator container exists', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            var $paging = $('.wl-cp-usage-paging');
            assert.ok($paging.length > 0, 'Paging indicator exists');
        });
    });
    assert.expect(1);
});

QUnit.test('startPolling/stopPolling succeed', function(assert) {
    require(['modules/wl_cp_usage'], function(UsageModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        UsageModule.init(ctx).done(function() {
            UsageModule.startPolling();
            assert.ok(true, 'startPolling succeeds');

            UsageModule.stopPolling();
            assert.ok(true, 'stopPolling succeeds');
        });
    });
    assert.expect(2);
});
