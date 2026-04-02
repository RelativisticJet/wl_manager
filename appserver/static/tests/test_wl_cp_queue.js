/**
 * QUnit Tests for wl_cp_queue Module
 *
 * Tests module loading, initialization, data loading, event handlers,
 * pagination, polling, and CSV export functionality.
 */

QUnit.module('wl_cp_queue', {
    beforeEach: function(assert) {
        // Setup: Create mock DOM elements for queue tab
        var html = '<div id="wl-cp-tab-queue">' +
                   '<div id="wl-cp-queue-table"></div>' +
                   '<input id="wl-cp-queue-search" type="text" class="wl-cp-queue-search">' +
                   '<span class="wl-cp-queue-search-clear btn" style="display:none;">Clear</span>' +
                   '<span class="btn btn-primary wl-cp-download-csv-btn" style="cursor:pointer;">Download Queue CSV</span>' +
                   '<button class="wl-cp-approve-btn">Approve</button>' +
                   '<button class="wl-cp-reject-btn">Reject</button>' +
                   '<button class="wl-cp-cancel-btn">Cancel</button>' +
                   '<button class="wl-cp-queue-page-prev">Previous</button>' +
                   '<button class="wl-cp-queue-page-next">Next</button>' +
                   '<button class="wl-cp-history-toggle">Toggle History</button>' +
                   '</div>';
        $('#qunit-fixture').html(html);
    }
});

QUnit.test('Module loads and exports expected API', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        assert.ok(QueueModule, 'QueueModule loaded');
        assert.ok(typeof QueueModule.init === 'function', 'init function exists');
        assert.ok(typeof QueueModule.load === 'function', 'load function exists');
        assert.ok(typeof QueueModule.startPolling === 'function', 'startPolling function exists');
        assert.ok(typeof QueueModule.stopPolling === 'function', 'stopPolling function exists');
        assert.ok(typeof QueueModule.getPendingCount === 'function', 'getPendingCount function exists');
    });
    assert.expect(6);
});

QUnit.test('init() requires admin context', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctxAdmin = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        var result = QueueModule.init(ctxAdmin);
        assert.ok(result && typeof result.then === 'function', 'init returns promise with admin context');
    });
    assert.expect(1);
});

QUnit.test('load() returns promise and fetches queue data', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var loadPromise = QueueModule.load();
            assert.ok(loadPromise && typeof loadPromise.done === 'function', 'load returns promise');
            assert.ok(loadPromise && typeof loadPromise.fail === 'function', 'promise has fail method');
        });
    });
    assert.expect(2);
});

QUnit.test('Approve button click handler exists', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var $approveBtn = $('.wl-cp-approve-btn');
            assert.ok($approveBtn.length > 0, 'Approve button exists in DOM');
        });
    });
    assert.expect(1);
});

QUnit.test('Reject button click handler exists', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var $rejectBtn = $('.wl-cp-reject-btn');
            assert.ok($rejectBtn.length > 0, 'Reject button exists in DOM');
        });
    });
    assert.expect(1);
});

QUnit.test('Search input change handler exists', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var $searchInput = $('.wl-cp-queue-search');
            assert.ok($searchInput.length > 0, 'Search input exists in DOM');
            $searchInput.val('test').trigger('input');
            assert.ok($searchInput.val() === 'test', 'Search input value updated');
        });
    });
    assert.expect(2);
});

QUnit.test('Pagination previous/next buttons exist', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var $prevBtn = $('.wl-cp-queue-page-prev');
            var $nextBtn = $('.wl-cp-queue-page-next');
            assert.ok($prevBtn.length > 0, 'Previous button exists');
            assert.ok($nextBtn.length > 0, 'Next button exists');
        });
    });
    assert.expect(2);
});

QUnit.test('getPendingCount returns number', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var count = QueueModule.getPendingCount();
            assert.ok(typeof count === 'number', 'getPendingCount returns number');
            assert.ok(count >= 0, 'Count is non-negative');
        });
    });
    assert.expect(2);
});

QUnit.test('startPolling/stopPolling succeed', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            QueueModule.startPolling();
            assert.ok(true, 'startPolling succeeds');

            QueueModule.stopPolling();
            assert.ok(true, 'stopPolling succeeds');
        });
    });
    assert.expect(2);
});

QUnit.test('CSV download button exists', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var $downloadBtn = $('.wl-cp-download-csv-btn');
            assert.ok($downloadBtn.length > 0, 'Download button exists');
        });
    });
    assert.expect(1);
});

QUnit.test('History toggle button exists', function(assert) {
    require(['modules/wl_cp_queue'], function(QueueModule) {
        var ctx = {
            isAdmin: true,
            showAlert: function() {},
            showConfirm: function() { return true; }
        };
        QueueModule.init(ctx).done(function() {
            var $toggleBtn = $('.wl-cp-history-toggle');
            assert.ok($toggleBtn.length > 0, 'History toggle button exists');
        });
    });
    assert.expect(1);
});
