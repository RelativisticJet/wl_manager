/**
 * Whitelist Manager — Frontend Controller (Entry Point)
 *
 * All heavy logic lives in modules/wl_*.js.
 * This file wires modules together, sets up shared state, and binds
 * top-level DOM events (keyboard shortcuts, search bar, date picker).
 */

/*global require, Splunk */
// Cache-bust AMD module URLs so future builds auto-invalidate the browser's
// disk cache. Splunk serves /static/@<server-hash>/... with Cache-Control:
// public, max-age=31536000; without urlArgs, bumped build numbers don't force
// a re-fetch and clients run stale JS until they hard-refresh.
require.config({ urlArgs: "_b=649" });
require([
    "jquery",
    "underscore",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "app/wl_manager/modules/wl_constants",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui",
    "app/wl_manager/modules/wl_table",
    "app/wl_manager/modules/wl_versions",
    "app/wl_manager/modules/wl_modals",
    "app/wl_manager/modules/wl_csv_io",
    "app/wl_manager/modules/wl_diff",
    "app/wl_manager/modules/wl_datepicker",
    "app/wl_manager/modules/wl_approval_ui",
    "app/wl_manager/modules/wl_save",
    "app/wl_manager/modules/wl_presence",
    "app/wl_manager/modules/wl_nav",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils, C, REST, UI, Table, Versions, Modals, CsvIO, Diff, DatePicker, ApprovalUI, Save, Presence, Nav) {
    "use strict";

    // ── Module aliases ──
    var restGet  = REST.restGet;
    var showMsg  = UI.showMsg;
    var clearMsg = UI.clearMsg;

    // ══════════════════════════════════════════════════════════════════
    // State
    // ══════════════════════════════════════════════════════════════════
    var currentHeaders  = [];
    var originalHeaders = [];
    var currentRows     = [];
    var originalRows    = [];
    var selectedRule    = "";
    var selectedCsv     = "";
    var selectedApp     = "";
    var allRules        = [];
    var mappingData     = [];
    var saving          = false;
    var expireColumn    = "";
    var searchQuery     = "";
    var loadedMtime     = null;
    var loadedContentHash = null;
    var loadedPendingCount = 0;
    var pendingApprovals   = [];
    var csvLocked          = false;
    var isAdmin            = false;
    var pendingBulkEditCount = 0;
    var pendingFilterActive  = false;
    var pendingFilterIndices = null;
    var reasonGates = {};

    // ── Dark theme ──
    if (UI.detectDarkTheme()) {
        $("#wl-dropdowns").closest(".dashboard-panel").addClass("wl-dark");
    }

    // ── Detect admin role ──
    (function detectAdminRole() {
        restGet({ action: "get_user_info" })
        .done(function (data) {
            isAdmin = data.is_admin || false;
            if (isAdmin && pendingApprovals.length) {
                ApprovalUI.applyPendingHighlighting();
            }
        });
    })();

    // ══════════════════════════════════════════════════════════════════
    // DOM references
    // ══════════════════════════════════════════════════════════════════
    var $table = $("#csv-table-container");
    var $msg   = $("#message-container");
    var $diff  = $("#diff-container");

    UI.init($msg);

    var $ruleSearch = $("#rule-search");
    var $ruleList   = $("#rule-list");

    // Replace native CSV <select> with custom dropdown
    $("#csv-select").replaceWith(
        '<div id="csv-dropdown" class="wl-search-select" style="position:relative">' +
            '<div id="csv-display" class="wl-csv-display wl-disabled">' +
                '-- Select a Detection Rule first --</div>' +
            '<div id="csv-list" class="wl-dropdown-list"></div>' +
        '</div>'
    );
    var $csvDisplay = $("#csv-display");
    var $csvList    = $("#csv-list");

    // Detection Rule clear button
    var $ruleClear = $('<span class="wl-search-clear-btn wl-rule-clear-btn">\u00D7</span>');
    $("#rule-select").append($ruleClear);
    $ruleClear.hide();

    // Revert dropdown
    var $revertGroup = $(
        '<div class="wl-dropdown-group" id="wl-revert-group" style="display:none">' +
            '<label class="wl-dropdown-label">Revert to Version</label>' +
            '<select class="wl-select" id="wl-revert-select">' +
                '<option value="">-- No previous versions --</option>' +
            '</select>' +
        '</div>'
    );
    $("#wl-dropdowns").append($revertGroup);
    var $revertSelect = $revertGroup.find("#wl-revert-select");

    // Search bar
    var $searchGroup = $(
        '<div class="wl-dropdown-group" style="display:none">' +
            '<label class="wl-dropdown-label">Search</label>' +
            '<div class="wl-search-wrap">' +
                '<input type="text" class="wl-search-field" id="wl-search-input" ' +
                'placeholder="Filter rows..." autocomplete="off" />' +
                '<span class="wl-search-clear-btn" id="wl-search-clear">\u00D7</span>' +
            '</div>' +
        '</div>'
    );
    $("#wl-dropdowns").append($searchGroup);
    var $searchInput = $searchGroup.find("#wl-search-input");
    var $searchClear = $searchGroup.find("#wl-search-clear");

    // ══════════════════════════════════════════════════════════════════
    // Shared state proxy (ES5 getter/setter)
    // ══════════════════════════════════════════════════════════════════
    var _tableState = {};
    (function (o) {
        function prop(name, getter, setter) {
            Object.defineProperty(o, name, { get: getter, set: setter, enumerable: true });
        }
        prop("currentHeaders",      function () { return currentHeaders; },      function (v) { currentHeaders = v; });
        prop("originalHeaders",     function () { return originalHeaders; },     function (v) { originalHeaders = v; });
        prop("currentRows",         function () { return currentRows; },         function (v) { currentRows = v; });
        prop("originalRows",        function () { return originalRows; },        function (v) { originalRows = v; });
        prop("selectedRule",        function () { return selectedRule; },        function (v) { selectedRule = v; });
        prop("selectedCsv",         function () { return selectedCsv; },         function (v) { selectedCsv = v; });
        prop("selectedApp",         function () { return selectedApp; },         function (v) { selectedApp = v; });
        prop("expireColumn",        function () { return expireColumn; },        function (v) { expireColumn = v; });
        prop("searchQuery",         function () { return searchQuery; },         function (v) { searchQuery = v; });
        prop("csvLocked",           function () { return csvLocked; },           function (v) { csvLocked = v; });
        prop("saving",              function () { return saving; },              function (v) { saving = v; });
        prop("loadedMtime",         function () { return loadedMtime; },         function (v) { loadedMtime = v; });
        prop("loadedContentHash",   function () { return loadedContentHash; },   function (v) { loadedContentHash = v; });
        prop("pendingBulkEditCount", function () { return pendingBulkEditCount; }, function (v) { pendingBulkEditCount = v; });
        prop("pendingFilterActive",  function () { return pendingFilterActive; },  function (v) { pendingFilterActive = v; });
        prop("pendingFilterIndices", function () { return pendingFilterIndices; }, function (v) { pendingFilterIndices = v; });
        prop("mappingData",          function () { return mappingData; },          function (v) { mappingData = v; });
        prop("reasonGates",          function () { return reasonGates; },          function (v) { reasonGates = v; });
        prop("allRules",             function () { return allRules; },             function (v) { allRules = v; });
        prop("pendingApprovals",     function () { return pendingApprovals; },     function (v) { pendingApprovals = v; });
        prop("isAdmin",              function () { return isAdmin; },              function (v) { isAdmin = v; });
        prop("loadedPendingCount",   function () { return loadedPendingCount; },   function (v) { loadedPendingCount = v; });
    })(_tableState);

    // ══════════════════════════════════════════════════════════════════
    // Module initialization (order matters — dependencies first)
    // ══════════════════════════════════════════════════════════════════

    Table.init({
        $table: $table,
        state:  _tableState,
        dom: {
            $searchInput: $searchInput,
            $searchGroup: $searchGroup,
            $diff:        $diff
        },
        actions: {
            showRemoveRowModal:        function () { return Modals.showRemoveRowModal.apply(null, arguments); },
            doSave:                    function () { return Save.doSave(); },
            doSaveRemoval:             function () { return Save.doSaveRemoval.apply(null, arguments); },
            doSaveBulkRemoval:         function () { return Save.doSaveBulkRemoval.apply(null, arguments); },
            doSaveColumnAddition:      function () { return Save.doSaveColumnAddition.apply(null, arguments); },
            doColumnRemoveWithGateCheck: function () { return Save.doColumnRemoveWithGateCheck.apply(null, arguments); },
            submitApprovalRequest:     function () { return ApprovalUI.submitApprovalRequest.apply(null, arguments); },
            exportCsv:                 function () { return CsvIO.exportCsv(); },
            importCsv:                 function () { return CsvIO.importCsv.apply(null, arguments); },
            loadVersions:              function () { return Versions.loadVersions.apply(null, arguments); },
            clearUndo:                 function () { return Save.clearUndo(); },
            applyPendingCssHighlighting: function () { return ApprovalUI.applyPendingCssHighlighting(); },
            formatLocalDateTime:       function () { return DatePicker.formatLocalDateTime.apply(null, arguments); },
            handleSaveError:           function () { return Save.handleSaveError.apply(null, arguments); }
        }
    });

    var renderTable  = Table.renderTable;
    var refreshTable = Table.refreshTable;
    var syncInputs   = Table.syncInputs;
    var clearSearch  = Table.clearSearch;

    Diff.init({ $diff: $diff });

    DatePicker.init({ state: _tableState });

    CsvIO.init({
        state: _tableState,
        actions: {
            syncInputs:   function () { return syncInputs(); },
            refreshTable: function () { return refreshTable(); },
            loadCsv:      function () { return Save.loadCsv.apply(null, arguments); }
        }
    });

    Presence.init({
        $table: $table,
        state:  _tableState,
        actions: {
            onDismiss:            function () { Nav.clearSelection(); },
            stopChangeMonitoring: function () { Save.stopChangeMonitoring(); }
        }
    });

    Versions.init({
        state: _tableState,
        dom: {
            $revertSelect: $revertSelect,
            $revertGroup:  $revertGroup
        },
        actions: {
            renderDiff:      function () { return Diff.renderDiff.apply(null, arguments); },
            reloadCsvQuiet:  function () { return Save.reloadCsvQuiet.apply(null, arguments); },
            handleSaveError: function () { return Save.handleSaveError.apply(null, arguments); },
            loadCsv:         function () { return Save.loadCsv.apply(null, arguments); }
        }
    });

    Modals.init({
        state: _tableState,
        actions: {
            onEntityRemoved: function (isRule, name, parentRule) {
                if (isRule && name === selectedRule) {
                    Nav.clearSelection();
                } else if (!isRule && name === selectedCsv) {
                    Nav.clearCsvSelection();
                }
                Nav.loadRules();
                if (selectedRule && !isRule) {
                    setTimeout(function () { Nav.selectRule(selectedRule); }, 500);
                }
            },
            onRuleCreated: function (name) {
                allRules.push(name);
                allRules.sort();
                Nav.renderRuleList(allRules);
                Nav.selectRule(name);
                showMsg(
                    "Detection rule <strong>" + _.escape(name) +
                    "</strong> created. You can now attach a CSV whitelist.",
                    "info"
                );
            },
            onCsvCreated: function (ruleName, csvName) {
                restGet({ action: "get_mapping" })
                .done(function (data) {
                    mappingData = data.mapping || [];
                    var ruleSet = {};
                    mappingData.forEach(function (m) { ruleSet[m.rule_name] = true; });
                    (data.registered_rules || []).forEach(function (r) { ruleSet[r] = true; });
                    allRules = Object.keys(ruleSet).sort();
                    Nav.renderRuleList(allRules);
                    Nav.selectRule(ruleName, csvName);
                });
            },
            reloadCsv: function () { Save.loadCsv(selectedCsv, selectedApp); },
            syncInputs:              function () { return syncInputs(); },
            refreshTable:            function () { return refreshTable(); },
            trackCellEdit:           function () { return Table.trackCellEdit.apply(null, arguments); },
            getSelectedCount:        function () { return Table.getSelectedCount(); },
            getSelectedIndices:      function () { return Table.getSelectedIndices(); },
            submitBulkEditApproval:  function () { return ApprovalUI.submitBulkEditApproval.apply(null, arguments); }
        }
    });

    ApprovalUI.init({
        state: _tableState,
        $table: $table,
        $revertSelect: $revertSelect,
        actions: {
            showMsg:                function () { return showMsg.apply(null, arguments); },
            syncInputs:             function () { return syncInputs(); },
            refreshTable:           function () { return refreshTable(); },
            showApproveConfirmModal: function () { return Modals.showApproveConfirmModal.apply(null, arguments); },
            showRejectReasonModal:  function () { return Modals.showRejectReasonModal.apply(null, arguments); },
            showCancelRequestModal: function () { return Modals.showCancelRequestModal.apply(null, arguments); },
            getCurrentUser:         function () { return Presence.getCurrentUser(); },
            getUsername:            function () { return Presence.getUsername(); },
            resetPage:              function () { return Table.resetPage(); },
            loadCsv:                function () { return Save.loadCsv.apply(null, arguments); },
            restPost:               function () { return REST.restPost.apply(null, arguments); }
        }
    });

    Save.init({
        $table: $table,
        $msg:   $msg,
        state:  _tableState,
        actions: {
            $diff:                         $diff,
            syncInputs:                    function () { return syncInputs(); },
            refreshTable:                  function () { return refreshTable(); },
            renderTable:                   function () { return renderTable.apply(null, arguments); },
            loadVersions:                  function () { return Versions.loadVersions.apply(null, arguments); },
            renderDiff:                    function () { return Diff.renderDiff.apply(null, arguments); },
            submitApprovalRequest:         function () { return ApprovalUI.submitApprovalRequest.apply(null, arguments); },
            submitInlineMultiEditApproval: function () { return ApprovalUI.submitInlineMultiEditApproval.apply(null, arguments); },
            showRemoveRowModal:            function () { return Modals.showRemoveRowModal.apply(null, arguments); },
            showRemoveColumnModal:         function () { return Modals.showRemoveColumnModal.apply(null, arguments); },
            handleCsvRemoved:              function () { return Presence.handleCsvRemoved.apply(null, arguments); },
            buildLockedState:              function () { return ApprovalUI.buildLockedState(); },
            applyPendingHighlighting:      function () { return ApprovalUI.applyPendingHighlighting(); },
            startPresenceMonitoring:       function () { return Presence.startPresenceMonitoring(); },
            applyColWidths:                function () { return Table.applyColWidths.apply(null, arguments); }
        }
    });

    Nav.init({
        state: _tableState,
        dom: {
            $table:      $table,
            $diff:       $diff,
            $ruleSearch: $ruleSearch,
            $ruleList:   $ruleList,
            $ruleClear:  $ruleClear,
            $csvDisplay: $csvDisplay,
            $csvList:    $csvList,
            $searchGroup: $searchGroup
        },
        actions: {
            showMsg:            function () { return showMsg.apply(null, arguments); },
            clearMsg:           function () { return clearMsg(); },
            showRemoveModal:    function () { return Modals.showRemoveModal.apply(null, arguments); },
            showNewRuleModal:   function () { return Modals.showNewRuleModal(); },
            showCreateCsvModal: function () { return Modals.showCreateCsvModal.apply(null, arguments); },
            clearUndo:          function () { return Save.clearUndo(); },
            stopChangeMonitoring: function () { return Save.stopChangeMonitoring(); },
            hideVersions:       function () { return Versions.hide(); },
            loadCsv:            function () { return Save.loadCsv.apply(null, arguments); },
            applyPendingHighlighting: function () { return ApprovalUI.applyPendingHighlighting(); }
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // DatePicker: Expires cell click + outside-click close
    // ══════════════════════════════════════════════════════════════════
    $table.on("click.wl", ".wl-expires-input", function (e) {
        e.stopPropagation();
        DatePicker.showDatePicker($(this));
    });
    $(document).on("click", function (e) {
        if ($("#wl-date-picker").css("display") !== "none") {
            if (!$(e.target).closest("#wl-date-picker").length &&
                !$(e.target).closest(".wl-expires-input").length) {
                DatePicker.closeDatePicker();
            }
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // Search bar events
    // ══════════════════════════════════════════════════════════════════
    $searchInput.on("input", function () {
        syncInputs();
        searchQuery = $(this).val().trim();
        Table.resetPage();
        refreshTable();
    });
    $searchClear.on("click", function () {
        syncInputs();
        clearSearch();
    });

    // ══════════════════════════════════════════════════════════════════
    // Keyboard Shortcuts
    // ══════════════════════════════════════════════════════════════════
    $(document).on("keydown", function (e) {
        var isInput = $(e.target).is("input, textarea, select");

        // Ctrl+S / Cmd+S — Save
        if ((e.ctrlKey || e.metaKey) && e.which === 83) {
            e.preventDefault();
            if (selectedCsv && !saving) { Save.doSave(); }
            return;
        }

        // Escape — close modal / date picker / clear search
        if (e.which === 27 || e.key === "Escape") {
            if ($("#wl-date-picker").length && $("#wl-date-picker").css("display") !== "none") {
                e.preventDefault(); e.stopPropagation();
                DatePicker.closeDatePicker();
                return;
            }
            if ($(".wl-modal-overlay").length) {
                e.preventDefault(); e.stopPropagation();
                $(".wl-modal-overlay").last().remove();
                return;
            }
            if (searchQuery && $(e.target).is("#wl-search-input")) {
                e.preventDefault(); e.stopPropagation();
                clearSearch();
                return;
            }
        }

        // Alt+Left / Alt+Right — pagination
        if (e.altKey && selectedCsv && currentHeaders.length) {
            if (e.which === 37 || e.key === "ArrowLeft") {
                e.preventDefault();
                Table.prevPage();
                return;
            }
            if (e.which === 39 || e.key === "ArrowRight") {
                e.preventDefault();
                Table.nextPage();
                return;
            }
        }

        // Ctrl+Z — undo last cell edit
        if ((e.ctrlKey || e.metaKey) && e.which === 90 && !e.shiftKey) {
            if (!isInput && Table.hasEditHistory()) {
                e.preventDefault();
                Table.undoCellEdit();
            }
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // User activity tracking (for presence)
    // ══════════════════════════════════════════════════════════════════
    (function trackActivity() {
        var events = "click.wlactivity keydown.wlactivity input.wlactivity mousedown.wlactivity";
        $(document).off(events).on(events, function () {
            Presence.updateActivity();
        });
    })();

    // ══════════════════════════════════════════════════════════════════
    // After-refresh hooks (Bulk Edit + Audit Export buttons)
    // ══════════════════════════════════════════════════════════════════
    Table.setOnAfterRefresh(function () {
        var $rightSection = $table.find(".wl-buttons-right");
        if ($rightSection.length && !$table.find("#btn-audit-export").length) {
            $rightSection.prepend(
                '<button class="btn" id="btn-audit-export" title="Export audit trail as CSV">Export Audit</button> '
            );
        }
        updateBulkEditBtn();
    });

    function updateBulkEditBtn() {
        $table.find("#btn-bulk-edit").prop("disabled", Table.getSelectedCount() === 0);
    }

    $table.on("click.wl", "#btn-bulk-edit", function () { Modals.showBulkEditModal(); });
    $table.on("click.wl", "#btn-audit-export", function () { CsvIO.exportAuditCsv(); });
    Table.setOnSelectionChanged(function () { updateBulkEditBtn(); });

    // ══════════════════════════════════════════════════════════════════
    // Initialization
    // ══════════════════════════════════════════════════════════════════
    Nav.loadRules();

    // Auto-refresh on approval notifications for current rule/CSV
    var _seenApprovalIds = {};
    var _notifFirstPoll = true;
    window.__wlNotifCallbacks = window.__wlNotifCallbacks || [];
    window.__wlNotifCallbacks.push(function (notifs) {
        if (_notifFirstPoll) {
            notifs.forEach(function (n) { _seenApprovalIds[n.id] = true; });
            _notifFirstPoll = false;
            return;
        }
        var needsRefresh = false;
        var needsRuleRefresh = false;
        notifs.forEach(function (n) {
            if (_seenApprovalIds[n.id]) return;
            _seenApprovalIds[n.id] = true;
            if (n.type !== "approved" && n.type !== "cancelled") return;
            var extra = n.extra || {};
            var nRule = extra.detection_rule || "";
            var nCsv = extra.csv_file || "";
            if (selectedCsv && nCsv === selectedCsv) { needsRefresh = true; }
            else if (selectedRule && nRule === selectedRule) { needsRefresh = true; }
            var ruleOps = ["create_rule", "remove_rule", "create_csv", "remove_csv"];
            if (ruleOps.indexOf(extra.action_type || "") !== -1) { needsRuleRefresh = true; }
        });
        if (needsRefresh || needsRuleRefresh) {
            if (needsRuleRefresh) { Nav.loadRules(); }
            var ruleToRefresh = selectedRule;
            var csvToRefresh = selectedCsv;
            if (ruleToRefresh && csvToRefresh) {
                setTimeout(function () {
                    if (selectedRule === ruleToRefresh) {
                        Save.loadCsv(csvToRefresh, selectedApp);
                    }
                }, 300);
            } else if (ruleToRefresh) {
                setTimeout(function () { Nav.selectRule(ruleToRefresh); }, 500);
            }
        }
    });

    // Stop presence on page unload
    $(window).on("beforeunload", function () {
        Save.stopChangeMonitoring();
        Presence.stopPresenceMonitoring();
    });

});
