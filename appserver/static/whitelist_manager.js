/**
 * Whitelist Manager — Frontend Controller
 *
 * Features:
 *   1. Searchable detection rule dropdown
 *   2. Editable CSV table with add/remove row buttons
 *   3. Comment column validation (required for audit)
 *   4. Auto-save on row removal with reason prompt
 *   5. 10-second Undo bar after row removal
 *   6. Bulk CSV import (upload) and export (download)
 *   7. Expiration date highlighting (yellow for expired rows)
 *   8. Row-level change history tooltips (added_by, added_at)
 *   9. Git-style diff display after save
 *  10. Auto-removal of expired rows with alert banner
 *  11. Date/time picker for Expires column with presets
 *  12. Search/filter bar with instant filtering and text highlighting
 */

/*global require, Splunk */
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
    "app/wl_manager/modules/wl_debug",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils, C, REST, UI, Table, Versions, Modals, CsvIO, Diff, DatePicker, ApprovalUI, Save, Presence, Debug) {
    "use strict";

    // Activate debug interceptor (remove for production)
    Debug.init();

    // ── Module aliases (Option A: local vars, zero changes to usage sites) ──
    var restUrl  = REST.restUrl;
    var restGet  = REST.restGet;
    var restPost = REST.restPost;

    // ── UI module: message banner, daily limit msgs ──
    var showMsg          = UI.showMsg;
    var clearMsg         = UI.clearMsg;
    var formatDailyLimitMsg = UI.formatDailyLimitMsg;

    // ══════════════════════════════════════════════════════════════════
    // State
    // ══════════════════════════════════════════════════════════════════
    var currentHeaders  = [];
    var originalHeaders = [];
    var currentRows    = [];
    var originalRows   = [];
    var selectedRule    = "";
    var selectedCsv     = "";
    var selectedApp     = "";
    var allRules        = [];
    var mappingData     = [];
    var saving           = false;   // debounce flag to prevent rapid saves
    var MAX_CELL_CHARS   = C.MAX_CELL_CHARS;
    var expireColumn     = "";      // name of the expiration column (e.g. "Expires", "expiry", "termination_date")
    var searchQuery      = "";      // current search/filter text for the CSV table
    var loadedMtime      = null;    // file mtime when CSV was loaded/saved (for external change detection)
    var loadedPendingCount = 0;    // pending approval count when CSV was loaded (for lock-state polling)
    // (undoTimer, undoState, changeCheckTimer → module-private in wl_save.js)
    var pendingApprovals = [];      // pending approval items for current CSV (from server)
    var csvLocked        = false;  // true when ANY pending approval exists — entire file locked
    var isAdmin          = false;  // true if current user has admin/sc_admin/wl_admin role
    var pendingBulkEditCount = 0;  // tracks unsaved Bulk Edit changes (for correct limit classification)
    var pendingFilterActive  = false; // true when approval-highlight filter is active
    var pendingFilterIndices = null;  // array of row indices to highlight, or null
    var additionPreviewData = null;   // { headers, rowKeys } for row-addition approval preview

    // ── Dark theme (module handles body class; WM adds panel class) ──
    if (UI.detectDarkTheme()) {
        $("#wl-dropdowns").closest(".dashboard-panel").addClass("wl-dark");
    }

    // ══════════════════════════════════════════════════════════════════
    // Detect admin role
    // ══════════════════════════════════════════════════════════════════
    (function detectAdminRole() {
        restGet({ action: "get_user_info" })
        .done(function (data) {
            isAdmin = data.is_admin || false;
            // If CSV was already loaded & locked before this check completed,
            // re-render the approval bar now that we know user is admin
            if (isAdmin && pendingApprovals.length) {
                ApprovalUI.applyPendingHighlighting();
            }
        });
    })();

    // ══════════════════════════════════════════════════════════════════
    // DOM references
    // ══════════════════════════════════════════════════════════════════
    var $table       = $("#csv-table-container");
    var $msg         = $("#message-container");
    var $diff        = $("#diff-container");

    // Initialize UI module (message banner, char counter)
    UI.init($msg);
    var $ruleSearch  = $("#rule-search");
    var $ruleList    = $("#rule-list");
    // Replace native CSV <select> with custom dropdown
    var $csvSelectOrig = $("#csv-select");
    $csvSelectOrig.replaceWith(
        '<div id="csv-dropdown" class="wl-search-select" style="position:relative">' +
            '<div id="csv-display" class="wl-csv-display wl-disabled">' +
                '-- Select a Detection Rule first --</div>' +
            '<div id="csv-list" class="wl-dropdown-list"></div>' +
        '</div>'
    );
    var $csvDisplay = $("#csv-display");
    var $csvList    = $("#csv-list");
    var csvDisabled = true;
    // Add clear button to Detection Rule dropdown (built via JS to avoid Splunk stripping)
    var $ruleClear = $('<span class="wl-search-clear-btn wl-rule-clear-btn">\u00D7</span>');
    $("#rule-select").append($ruleClear);
    $ruleClear.hide();
    // Build revert dropdown via JS (Splunk SimpleXML strips empty divs)
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
    // Build search bar via JS (Splunk SimpleXML strips empty divs and buttons)
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
    // Table module: shared state proxy + init
    // ══════════════════════════════════════════════════════════════════
    // ES5 getter/setter proxy lets the table module read/write the same
    // state variables as the entry point without renaming anything.
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

    Table.init({
        $table: $table,
        state:  _tableState,
        dom: {
            $searchInput: $searchInput,
            $searchGroup: $searchGroup,
            $diff:        $diff
        },
        actions: {
            showRemoveRowModal:        function () { return showRemoveRowModal.apply(null, arguments); },
            doSave:                    function () { return Save.doSave(); },
            doSaveRemoval:             function () { return Save.doSaveRemoval.apply(null, arguments); },
            doSaveBulkRemoval:         function () { return Save.doSaveBulkRemoval.apply(null, arguments); },
            doSaveColumnAddition:      function () { return Save.doSaveColumnAddition.apply(null, arguments); },
            doColumnRemoveWithGateCheck: function () { return doColumnRemoveWithGateCheck.apply(null, arguments); },
            submitApprovalRequest:     function () { return ApprovalUI.submitApprovalRequest.apply(null, arguments); },
            exportCsv:                 function () { return CsvIO.exportCsv(); },
            importCsv:                 function () { return CsvIO.importCsv.apply(null, arguments); },
            loadVersions:              function () { return loadVersions.apply(null, arguments); },
            clearUndo:                 function () { return Save.clearUndo(); },
            applyPendingCssHighlighting: function () { return ApprovalUI.applyPendingCssHighlighting(); },
            formatLocalDateTime:       function () { return DatePicker.formatLocalDateTime.apply(null, arguments); },
            handleSaveError:           function () { return Save.handleSaveError.apply(null, arguments); }
        }
    });

    // ── Table module aliases (Option A: zero changes to existing call sites) ──
    var renderTable  = Table.renderTable;
    var refreshTable = Table.refreshTable;
    var syncInputs   = Table.syncInputs;
    var getFilteredRows = Table.getFilteredRows;
    var clearSearch  = Table.clearSearch;
    var undoCellEdit = Table.undoCellEdit;

    // ── CSV I/O module init ──
    CsvIO.init({
        state: _tableState,
        actions: {
            syncInputs:   function () { return syncInputs(); },
            refreshTable: function () { return refreshTable(); },
            loadCsv:      function () { return loadCsv.apply(null, arguments); }
        }
    });

    // ── Diff module init ──
    Diff.init({ $diff: $diff });
    var renderDiff = Diff.renderDiff;

    // ── DatePicker module init ──
    DatePicker.init({ state: _tableState });

    // ── Presence module init ──
    Presence.init({
        $table: $table,
        state:  _tableState,
        actions: {
            onDismiss:            function () { $ruleClear.trigger("click"); },
            stopChangeMonitoring: function () { Save.stopChangeMonitoring(); }
        }
    });

    // ── Versions module init ──
    Versions.init({
        state: _tableState,
        dom: {
            $revertSelect: $revertSelect,
            $revertGroup:  $revertGroup
        },
        actions: {
            renderDiff:     function () { return Diff.renderDiff.apply(null, arguments); },
            reloadCsvQuiet: function () { return reloadCsvQuiet.apply(null, arguments); },
            handleSaveError: function () { return Save.handleSaveError.apply(null, arguments); },
            loadCsv:        function () { return loadCsv.apply(null, arguments); }
        }
    });

    // ── Versions module alias ──
    var loadVersions = Versions.loadVersions;

    // ── Modals module init ──
    Modals.init({
        state: _tableState,
        actions: {
            onEntityRemoved: function (isRule, name, parentRule) {
                if (isRule && name === selectedRule) {
                    selectedRule = "";
                    selectedCsv = "";
                    selectedApp = "";
                    $ruleSearch.val("");
                    $ruleClear.hide();
                    csvDisabled = true;
                    $csvDisplay.text("-- Select a Detection Rule first --")
                        .addClass("wl-disabled");
                    $csvList.empty().removeClass("wl-open");
                    Save.stopChangeMonitoring();
                    $searchGroup.hide();
                    Versions.hide();
                    $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
                    $diff.empty();
                } else if (!isRule && name === selectedCsv) {
                    selectedCsv = "";
                    selectedApp = "";
                    Save.stopChangeMonitoring();
                    $searchGroup.hide();
                    Versions.hide();
                    $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
                    $diff.empty();
                }
                loadRules();
                if (selectedRule && !isRule) {
                    setTimeout(function () { selectRule(selectedRule); }, 500);
                }
            },
            onRuleCreated: function (name) {
                allRules.push(name);
                allRules.sort();
                renderRuleList(allRules);
                selectRule(name);
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
                    var perms = data.permissions || {};
                    canCreateRules = !!perms.can_create_rules;
                    canCreateCsv = !!perms.can_create_csv;
                    var ruleSet = {};
                    mappingData.forEach(function (m) { ruleSet[m.rule_name] = true; });
                    (data.registered_rules || []).forEach(function (r) { ruleSet[r] = true; });
                    allRules = Object.keys(ruleSet).sort();
                    renderRuleList(allRules);
                    selectRule(ruleName, csvName);
                });
            },
            reloadCsv: function () { loadCsv(selectedCsv, selectedApp); },
            // Group D: Bulk edit callbacks
            syncInputs:              function () { return syncInputs(); },
            refreshTable:            function () { return refreshTable(); },
            trackCellEdit:           function () { return Table.trackCellEdit.apply(null, arguments); },
            getSelectedCount:        function () { return Table.getSelectedCount(); },
            getSelectedIndices:      function () { return Table.getSelectedIndices(); },
            submitBulkEditApproval:  function () { return ApprovalUI.submitBulkEditApproval.apply(null, arguments); }
        }
    });

    // ── Modals module aliases ──
    var showRemoveModal         = Modals.showRemoveModal;
    var showNewRuleModal        = Modals.showNewRuleModal;
    var showApprovalReasonPopup = Modals.showApprovalReasonPopup;
    var showCreateCsvModal      = Modals.showCreateCsvModal;
    var showRemoveRowModal      = Modals.showRemoveRowModal;
    var showRemoveColumnModal   = Modals.showRemoveColumnModal;
    var showApproveConfirmModal = Modals.showApproveConfirmModal;
    var showRejectReasonModal   = Modals.showRejectReasonModal;
    var showCancelRequestModal  = Modals.showCancelRequestModal;

    // ── ApprovalUI module init ──
    ApprovalUI.init({
        state: _tableState,
        $table: $table,
        $revertSelect: $revertSelect,
        actions: {
            showMsg: function () { return showMsg.apply(null, arguments); },
            syncInputs: function () { return syncInputs(); },
            refreshTable: function () { return refreshTable(); },
            showApproveConfirmModal: function () { return showApproveConfirmModal.apply(null, arguments); },
            showRejectReasonModal: function () { return showRejectReasonModal.apply(null, arguments); },
            showCancelRequestModal: function () { return showCancelRequestModal.apply(null, arguments); },
            getCurrentUser: function () { return Presence.getCurrentUser(); },
            getUsername: function () { return Presence.getUsername(); },
            resetPage: function () { return Table.resetPage(); },
            loadCsv: function () { return loadCsv.apply(null, arguments); },
            restPost: function () { return restPost.apply(null, arguments); }
        }
    });

    // ── Save module init ──
    Save.init({
        $table: $table,
        $msg:   $msg,
        state:  _tableState,
        actions: {
            syncInputs:                    function () { return syncInputs(); },
            refreshTable:                  function () { return refreshTable(); },
            loadCsv:                       function () { return loadCsv.apply(null, arguments); },
            reloadCsvQuiet:                function () { return reloadCsvQuiet.apply(null, arguments); },
            loadVersions:                  function () { return Versions.loadVersions.apply(null, arguments); },
            renderDiff:                    function () { return Diff.renderDiff.apply(null, arguments); },
            submitApprovalRequest:         function () { return ApprovalUI.submitApprovalRequest.apply(null, arguments); },
            submitInlineMultiEditApproval: function () { return ApprovalUI.submitInlineMultiEditApproval.apply(null, arguments); },
            showRemoveRowModal:            function () { return Modals.showRemoveRowModal.apply(null, arguments); },
            handleCsvRemoved:              function () { return Presence.handleCsvRemoved.apply(null, arguments); }
        }
    });

    // (handleSaveError → extracted to modules/wl_save.js)

    // ══════════════════════════════════════════════════════════════════
    // Searchable Detection Rule Dropdown
    // ══════════════════════════════════════════════════════════════════

    var canCreateRules = false;
    var canCreateCsv = false;
    var canDeleteRules = false;
    var canDeleteCsv = false;
    var reasonGates = {};

    function loadRules() {
        restGet({ action: "get_mapping" })
        .done(function (data) {
            mappingData = data.mapping || [];
            var perms = data.permissions || {};
            canCreateRules = !!perms.can_create_rules;
            canCreateCsv = !!perms.can_create_csv;
            canDeleteRules = !!perms.can_delete_rules;
            canDeleteCsv = !!perms.can_delete_csv;
            reasonGates = perms.reason_gates || {};
            var ruleSet = {};
            mappingData.forEach(function (m) {
                ruleSet[m.rule_name] = true;
            });
            // Merge registered rules (those without CSV mappings yet)
            (data.registered_rules || []).forEach(function (r) {
                ruleSet[r] = true;
            });
            allRules = Object.keys(ruleSet).sort();
            renderRuleList(allRules);

            // Auto-select rule + CSV from URL params (e.g. ?rule=DR102&csv=DR102_whitelist.csv)
            var urlParams = new URLSearchParams(window.location.search);
            var paramRule = urlParams.get("rule");
            var paramCsv = urlParams.get("csv");
            if (paramRule) {
                if (allRules.indexOf(paramRule) === -1) {
                    // Rule doesn't exist — show error
                    $table.html(
                        '<div class="wl-alert wl-alert-warning">' +
                            '<strong>Detection rule "' + _.escape(paramRule) +
                            '" was not found.</strong>' +
                            '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                                'It may have been removed or the link may be outdated.' +
                            '</span>' +
                            '<br><span class="btn btn-primary" id="wl-go-home" ' +
                                'style="margin-top:8px">Back to Whitelist Manager</span>' +
                        '</div>'
                    );
                } else {
                    selectRule(paramRule, paramCsv || undefined);
                    // Check if a specific CSV was requested but doesn't exist for this rule
                    if (paramCsv && selectedCsv !== paramCsv) {
                        showMsg(
                            'CSV file "' + _.escape(paramCsv) +
                            '" was not found for rule "' + _.escape(paramRule) +
                            '". Showing available CSV instead.', "warning");
                    }
                }
            }
        })
        .fail(function () {
            showMsg("Failed to load detection rules.", "error");
        });
    }

    var CREATE_RULE_SENTINEL = "__create_new_rule__";

    function renderRuleList(rules) {
        var createBtn = "";
        if (canCreateRules) {
            createBtn =
                '<div class="wl-dropdown-item wl-dropdown-create-rule" data-value="' +
                    CREATE_RULE_SENTINEL + '" style="border-bottom:1px solid var(--wl-border);' +
                    'font-style:italic;color:var(--wl-link)">' +
                    '+ Create new detection rule' +
                '</div>';
        }

        if (!rules.length) {
            $ruleList.html(
                createBtn +
                '<div class="wl-dropdown-no-match">No matching rules</div>'
            );
            return;
        }
        var html = createBtn;
        rules.forEach(function (rule) {
            var cls = "wl-dropdown-item";
            if (rule === selectedRule) { cls += " wl-selected"; }
            var removeSpan = canDeleteRules
                ? '<span class="wl-dropdown-remove" data-rule="' +
                  _.escape(rule) + '">remove</span>'
                : '';
            html += '<div class="' + cls + '" data-value="' + _.escape(rule) + '">' +
                    '<span>' + _.escape(rule) + '</span>' + removeSpan + '</div>';
        });
        $ruleList.html(html);
    }

    $ruleSearch.on("focus", function () {
        $ruleList.addClass("wl-open");
        renderRuleList(filterRules($ruleSearch.val()));
    });

    $ruleSearch.on("input", function () {
        var filtered = filterRules($(this).val());
        renderRuleList(filtered);
        $ruleList.addClass("wl-open");
    });

    $ruleSearch.on("keydown", function (e) {
        if (e.which === 13) {
            e.preventDefault();
            var typed = $(this).val().trim();
            if (!typed) { return; }
            // If it matches an existing rule exactly, select that
            var exactMatch = allRules.filter(function (r) {
                return r.toLowerCase() === typed.toLowerCase();
            });
            if (exactMatch.length) {
                selectRule(exactMatch[0]);
            } else if (canCreateRules) {
                // Treat as a new/unmapped rule name
                selectRule(typed);
            } else {
                showMsg("Creating new detection rules is restricted to admins.", "error");
            }
            $ruleList.removeClass("wl-open");
        }
    });

    $(document).on("click", function (e) {
        if (!$(e.target).closest("#rule-select").length) {
            $ruleList.removeClass("wl-open");
        }
    });

    // Intercept "remove" click on rule items (before the item click)
    $ruleList.on("click", ".wl-dropdown-remove", function (e) {
        e.stopPropagation();
        var rule = $(this).data("rule");
        $ruleList.removeClass("wl-open");
        if (rule) { showRemoveModal("rule", rule); }
    });

    $ruleList.on("click", ".wl-dropdown-item", function () {
        var rule = $(this).data("value");
        $ruleList.removeClass("wl-open");
        if (rule === CREATE_RULE_SENTINEL) {
            showNewRuleModal();
            return;
        }
        selectRule(rule);
    });

    $ruleClear.on("click", function () {
        selectedRule = "";
        selectedCsv = "";
        selectedApp = "";
        $ruleSearch.val("");
        $ruleClear.hide();
        renderRuleList(allRules);
        $ruleList.removeClass("wl-open");
        csvDisabled = true;
        $csvDisplay.text("-- Select a Detection Rule first --").addClass("wl-disabled");
        $csvList.empty().removeClass("wl-open");
        updateUrlParams();
        Save.stopChangeMonitoring();
        loadedMtime = null;
        loadedPendingCount = 0;
        $searchGroup.hide();
        Versions.hide();
        Save.clearUndo();
        pendingApprovals = [];
        $("#wl-approval-actions").remove();
        $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
        $diff.empty();
        clearMsg();
    });

    function filterRules(query) {
        if (!query || !query.trim()) { return allRules; }
        var q = query.trim().toLowerCase();
        return allRules.filter(function (r) {
            return r.toLowerCase().indexOf(q) !== -1;
        });
    }

    function selectRule(rule, preferCsv) {
        if (!rule) { return; }
        selectedRule = rule;
        selectedCsv = "";
        $ruleSearch.val(rule);
        $ruleClear.show();
        renderRuleList(allRules);
        Save.clearUndo();
        pendingApprovals = [];
        $("#wl-approval-actions").remove();
        updateUrlParams();

        var csvEntries = mappingData.filter(function (m) {
            return m.rule_name === rule;
        });

        csvDisabled = false;
        $csvDisplay.removeClass("wl-disabled");

        if (!csvEntries.length) {
            $csvDisplay.text("No CSV files for this rule").addClass("wl-disabled");
            csvDisabled = true;
            selectedCsv = "";
            selectedApp = "";
            Save.stopChangeMonitoring();
            loadedMtime = null;
            loadedPendingCount = 0;
            $searchGroup.hide();
            Versions.hide();
            var noCsvHtml = '<div class="wl-alert wl-alert-warning">' +
                '<strong>No whitelisting exists for this detection rule.</strong>';
            if (canCreateCsv) {
                noCsvHtml +=
                    '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                        'Would you like to create a new CSV whitelist?' +
                    '</span>' +
                    '<br><span class="btn btn-primary" id="wl-create-csv-btn" ' +
                        'style="margin-top:8px">Create CSV</span>';
            } else {
                noCsvHtml +=
                    '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                        'Contact an administrator to create a CSV whitelist for this rule.' +
                    '</span>';
            }
            noCsvHtml += '</div>';
            $table.html(noCsvHtml);
            $diff.empty();
            return;
        }

        // Store entries for click handler
        $csvList.data("entries", csvEntries);

        // Render custom CSV dropdown items
        renderCsvList(csvEntries);

        var target = preferCsv || csvEntries[0].csv_file;
        selectCsvItem(target, csvEntries);
    }

    function renderCsvList(entries) {
        var html = "";
        if (canCreateCsv) {
            html += '<div class="wl-dropdown-item wl-dropdown-create-csv" ' +
                    'style="border-bottom:1px solid var(--wl-border);' +
                    'font-style:italic;color:var(--wl-link)">+ Create new CSV</div>';
        }
        entries.forEach(function (entry) {
            var cls = "wl-dropdown-item";
            if (entry.csv_file === selectedCsv) { cls += " wl-selected"; }
            var removeSpan = canDeleteCsv
                ? '<span class="wl-dropdown-remove wl-csv-remove" ' +
                  'data-csv="' + _.escape(entry.csv_file) + '" ' +
                  'data-rule="' + _.escape(entry.rule_name || selectedRule) +
                  '">remove</span>'
                : '';
            html += '<div class="' + cls + ' wl-csv-item" ' +
                    'data-csv="' + _.escape(entry.csv_file) + '" ' +
                    'data-app="' + _.escape(entry.app_context || "") + '">' +
                    '<span>' + _.escape(entry.csv_file) + '</span>' +
                    removeSpan + '</div>';
        });
        $csvList.html(html);
    }

    function selectCsvItem(csvFile, entries) {
        if (!entries) { entries = $csvList.data("entries") || []; }
        var entry = null;
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].csv_file === csvFile) { entry = entries[i]; break; }
        }
        if (!entry) { return; }
        $csvDisplay.text(entry.csv_file);
        $csvList.removeClass("wl-open");
        onCsvSelected(entry.csv_file, entry.app_context || "");
    }

    // CSV custom dropdown: open/close
    $csvDisplay.on("click", function () {
        if (csvDisabled) { return; }
        $csvList.toggleClass("wl-open");
    });
    $(document).on("click", function (e) {
        if (!$(e.target).closest("#csv-dropdown").length) {
            $csvList.removeClass("wl-open");
        }
    });
    // CSV item click
    $csvList.on("click", ".wl-csv-item", function (e) {
        if ($(e.target).hasClass("wl-csv-remove")) { return; }
        var csvFile = $(this).data("csv");
        var appCtx = $(this).data("app") || "";
        $csvDisplay.text(csvFile);
        $csvList.removeClass("wl-open");
        onCsvSelected(csvFile, appCtx);
    });
    // CSV "Create new CSV" click
    $csvList.on("click", ".wl-dropdown-create-csv", function () {
        $csvList.removeClass("wl-open");
        showCreateCsvModal(selectedRule);
    });
    // CSV "remove" click
    $csvList.on("click", ".wl-csv-remove", function (e) {
        e.stopPropagation();
        var csv = $(this).data("csv");
        var rule = $(this).data("rule") || selectedRule;
        $csvList.removeClass("wl-open");
        if (csv) { showRemoveModal("csv", csv, rule); }
    });

    // Keep the URL in sync with current selection (no page reload)
    function updateUrlParams() {
        var params = new URLSearchParams(window.location.search);
        if (selectedRule) { params.set("rule", selectedRule); } else { params.delete("rule"); }
        if (selectedCsv) { params.set("csv", selectedCsv); } else { params.delete("csv"); }
        var newUrl = window.location.pathname;
        var qs = params.toString();
        if (qs) { newUrl += "?" + qs; }
        window.history.replaceState(null, "", newUrl);
    }

    function onCsvSelected(csvFile, appCtx) {
        Save.stopChangeMonitoring();
        loadedMtime = null;
        loadedPendingCount = 0;
        selectedCsv = csvFile || "";
        selectedApp = appCtx || "";
        Save.clearUndo();
        updateUrlParams();
        // Update selected highlight in dropdown
        $csvList.find(".wl-csv-item").removeClass("wl-selected");
        $csvList.find(".wl-csv-item").filter(function () {
            return $(this).data("csv") === selectedCsv;
        }).addClass("wl-selected");
        if (selectedCsv) {
            loadCsv(selectedCsv, selectedApp);
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Create CSV for unmapped rules
    // ══════════════════════════════════════════════════════════════════

    $table.on("click", "#wl-create-csv-btn", function () {
        if (!selectedRule) { return; }
        showCreateCsvModal(selectedRule);
    });

    // "Back to Whitelist Manager" button on invalid URL param error
    $table.on("click", "#wl-go-home", function () {
        window.location.href = window.location.pathname;
    });

    // (showRemoveModal, showNewRuleModal, showApprovalReasonPopup,
    //  showCreateCsvModal, _bindCreateCsvEvents → extracted to modules/wl_modals.js)

    // ══════════════════════════════════════════════════════════════════

    // ══════════════════════════════════════════════════════════════════
    // (Table rendering, events, resize, drag, reorder, modals →
    //  extracted to modules/wl_table.js)
    // ══════════════════════════════════════════════════════════════════


    // (doSaveColumnAddition → extracted to modules/wl_save.js)

    // (showRemoveRowModal → extracted to modules/wl_modals.js)

    // ══════════════════════════════════════════════════════════════════
    // ══════════════════════════════════════════════════════════════════
    // Approval workflow — gate checks and submission
    // ══════════════════════════════════════════════════════════════════

    function doColumnRemoveWithGateCheck(colName) {
        if (csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }
        restPost({
            action: "check_approval_gate",
            gate_action: "column_removal",
            csv_file: selectedCsv,
            app_context: selectedApp,
            column_name: colName
        }).done(function (gateData) {
            if (gateData.requires_approval) {
                showRemoveColumnModal(colName, function (reason) {
                    ApprovalUI.submitApprovalRequest("column_removal", reason, null, colName);
                });
            } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                showMsg(formatDailyLimitMsg(gateData.daily_limit), "error"
                );
            } else {
                showRemoveColumnModal(colName, function (reason) {
                    Save.doSaveColumnRemoval(colName, reason);
                });
            }
        }).fail(function () {
            // Fallback to normal flow if gate check fails
            showRemoveColumnModal(colName, function (reason) {
                Save.doSaveColumnRemoval(colName, reason);
            });
        });
    }


    // (showApproveConfirmModal, showRejectReasonModal, showRemoveColumnModal
    //  → extracted to modules/wl_modals.js)

    // (doSaveColumnRemoval, column removal undo → extracted to modules/wl_save.js)

    // (Undo system → extracted to modules/wl_save.js)

    // (External change detection → extracted to modules/wl_save.js)

    // (getAuditComment → extracted to modules/wl_save.js)

    // ══════════════════════════════════════════════════════════════════
    // Load CSV content from REST
    // ══════════════════════════════════════════════════════════════════
    function loadCsv(csvFile, appContext) {
        clearMsg();
        $diff.empty();
        $("#wl-approval-actions").remove();
        $("#wl-addition-preview").remove();
        pendingFilterActive = false;
        pendingFilterIndices = null;
        additionPreviewData = null;
        $table.html('<p class="wl-muted">Loading CSV content&hellip;</p>');

        restGet({
            action:   "get_csv_content",
            csv_file: csvFile,
            app:      appContext || "",
            tz_offset: new Date().getTimezoneOffset()
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                $table.empty();
                return;
            }
            expireColumn = data.expire_column || "";
            if (data.auto_removed_count && data.auto_removed_count > 0) {
                showMsg(
                    "<strong>" + data.auto_removed_count + " expired row(s)</strong> " +
                    "were automatically removed.",
                    "warning"
                );
            }
            // Build locked state BEFORE rendering so buildRow() can check it
            pendingApprovals = data.pending_approvals || [];
            loadedPendingCount = pendingApprovals.length;
            ApprovalUI.buildLockedState();
            renderTable(data.headers || [], data.rows || []);
            loadVersions(csvFile, appContext);
            loadedMtime = data.file_mtime || null;
            Save.startChangeMonitoring();
            Presence.startPresenceMonitoring();
            // Apply pending approval CSS highlighting + banner
            if (pendingApprovals.length) {
                ApprovalUI.applyPendingHighlighting();
            }
            // Load server-side column widths
            restGet({ action: "get_col_widths", csv_file: csvFile, app: appContext || "" })
                .done(function (wdata) {
                    var w = wdata.col_widths || {};
                    if (Object.keys(w).length) {
                        Table.applyColWidths(w);
                    }
                });
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                Presence.handleCsvRemoved(csvFile);
                return;
            }
            var err = "Failed to load CSV.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
            $table.empty();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Silent CSV reload (preserves messages, refreshes metadata)
    // ══════════════════════════════════════════════════════════════════
    function reloadCsvQuiet(callback) {
        if (!selectedCsv) {
            if (callback) { callback(); }
            return;
        }
        restGet({
            action:   "get_csv_content",
            csv_file: selectedCsv,
            app:      selectedApp || "",
            tz_offset: new Date().getTimezoneOffset()
        })
        .done(function (data) {
            if (!data.error) {
                expireColumn = data.expire_column || "";
                if (data.auto_removed_count && data.auto_removed_count > 0) {
                    showMsg(
                        "<strong>" + data.auto_removed_count + " expired row(s)</strong> " +
                        "were automatically removed.",
                        "warning"
                    );
                }
                renderTable(data.headers || [], data.rows || []);
                loadVersions(selectedCsv, selectedApp);
                if (data.file_mtime) { loadedMtime = data.file_mtime; }
                Save.startChangeMonitoring();
            }
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                Presence.handleCsvRemoved(selectedCsv);
            }
        })
        .always(function () {
            if (callback) { callback(); }
        });
    }

    // (doSave, doSaveRemoval, doSaveBulkRemoval → extracted to modules/wl_save.js)

    // (renderDiff → extracted to modules/wl_diff.js)

    // (date/time helpers + popup picker → extracted to modules/wl_datepicker.js)

    // Bind Expires cell click — delegated on $table
    $table.on("click.wl", ".wl-expires-input", function (e) {
        e.stopPropagation();
        DatePicker.showDatePicker($(this));
    });

    // Close picker when clicking outside
    $(document).on("click", function (e) {
        if ($("#wl-date-picker").css("display") !== "none") {
            if (!$(e.target).closest("#wl-date-picker").length &&
                !$(e.target).closest(".wl-expires-input").length) {
                DatePicker.closeDatePicker();
            }
        }
    });

    // ══════════════════════════════════════════════════════════════════
    // Search bar events (static DOM — not inside $table)
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

        // Ctrl+S / Cmd+S — Save Changes
        if ((e.ctrlKey || e.metaKey) && e.which === 83) {
            e.preventDefault();
            if (selectedCsv && !saving) {
                Save.doSave();
            }
            return;
        }

        // Escape — close any open modal, date picker, or clear search
        if (e.which === 27 || e.key === "Escape") {
            if ($("#wl-date-picker").length && $("#wl-date-picker").css("display") !== "none") {
                e.preventDefault();
                e.stopPropagation();
                DatePicker.closeDatePicker();
                return;
            }
            if ($(".wl-modal-overlay").length) {
                e.preventDefault();
                e.stopPropagation();
                $(".wl-modal-overlay").last().remove();
                return;
            }
            if (searchQuery && $(e.target).is("#wl-search-input")) {
                e.preventDefault();
                e.stopPropagation();
                clearSearch();
                return;
            }
        }

        // Alt+Left / Alt+Right — pagination
        if (e.altKey && selectedCsv && currentHeaders.length) {
            if (e.which === 37 || e.key === "ArrowLeft") {
                e.preventDefault();   // always block browser-back
                Table.prevPage();
                return;
            }
            if (e.which === 39 || e.key === "ArrowRight") {
                e.preventDefault();   // always block browser-forward
                Table.nextPage();
                return;
            }
        }

        // Ctrl+Z — undo last cell edit (when not in an input)
        if ((e.ctrlKey || e.metaKey) && e.which === 90 && !e.shiftKey) {
            if (!isInput && Table.hasEditHistory()) {
                e.preventDefault();
                undoCellEdit();
            }
        }
    });

    // (showBulkEditModal → extracted to modules/wl_modals.js)

    // (exportAuditCsv → extracted to modules/wl_csv_io.js)

    // ══════════════════════════════════════════════════════════════════
    // Real-time Collaboration Indicators (user presence)
    // ──────────────────────────────────────────────────────────────────
    // Extracted to wl_presence.js module. See Presence.startPresenceMonitoring(),
    // Presence.stopPresenceMonitoring(), Presence.handleCsvRemoved(), etc.
    // ══════════════════════════════════════════════════════════════════

    // Track user activity — any meaningful interaction resets the idle timer
    (function trackActivity() {
        var events = "click.wlactivity keydown.wlactivity input.wlactivity mousedown.wlactivity";
        $(document).off(events).on(events, function () {
            Presence.updateActivity();
        });
    })();

    // ══════════════════════════════════════════════════════════════════
    // Add Bulk Edit and Audit Export buttons to table action bar
    // ══════════════════════════════════════════════════════════════════

    Table.setOnAfterRefresh(function () {
        // Add Audit Export button in the right section
        var $rightSection = $table.find(".wl-buttons-right");
        if ($rightSection.length && !$table.find("#btn-audit-export").length) {
            $rightSection.prepend(
                '<button class="btn" id="btn-audit-export" title="Export audit trail as CSV">Export Audit</button> '
            );
        }

        // Update Bulk Edit button state based on selection
        updateBulkEditBtn();
    });

    function updateBulkEditBtn() {
        var checked = Table.getSelectedCount();
        $table.find("#btn-bulk-edit").prop("disabled", checked === 0);
    }

    // Bind Bulk Edit button
    $table.on("click.wl", "#btn-bulk-edit", function () {
        Modals.showBulkEditModal();
    });

    // Bind Audit Export button
    $table.on("click.wl", "#btn-audit-export", function () {
        CsvIO.exportAuditCsv();
    });

    // Sync Bulk Edit button when checkbox selection changes
    Table.setOnSelectionChanged(function () {
        updateBulkEditBtn();
    });

    // ══════════════════════════════════════════════════════════════════
    // Initialization
    // ══════════════════════════════════════════════════════════════════
    loadRules();

    // Auto-refresh when a create_csv or create_rule approval comes through
    // for the currently selected rule (so analyst doesn't need to reload).
    var _seenApprovalIds = {};
    var _notifFirstPoll = true;
    window.__wlNotifCallbacks = window.__wlNotifCallbacks || [];
    window.__wlNotifCallbacks.push(function (notifs) {
        if (_notifFirstPoll) {
            // Seed with all existing notifications so we only react to NEW ones
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
            // Refresh if the notification affects the currently viewed CSV/rule
            if (selectedCsv && nCsv === selectedCsv) {
                needsRefresh = true;
            } else if (selectedRule && nRule === selectedRule) {
                needsRefresh = true;
            }
            // Rule-level operations (create/remove rule) need full rule list refresh
            var ruleOps = ["create_rule", "remove_rule",
                           "create_csv", "remove_csv"];
            if (ruleOps.indexOf(extra.action_type || "") !== -1) {
                needsRuleRefresh = true;
            }
        });
        if (needsRefresh || needsRuleRefresh) {
            if (needsRuleRefresh) { loadRules(); }
            var ruleToRefresh = selectedRule;
            var csvToRefresh = selectedCsv;
            if (ruleToRefresh && csvToRefresh) {
                setTimeout(function () {
                    if (selectedRule === ruleToRefresh) {
                        loadCsv(csvToRefresh, selectedApp);
                    }
                }, 300);
            } else if (ruleToRefresh) {
                setTimeout(function () {
                    selectRule(ruleToRefresh);
                }, 500);
            }
        }
    });

    // (Presence monitoring started inside loadCsv .done() handler — after renderTable)

    // Stop presence on page unload
    $(window).on("beforeunload", function () {
        Save.stopChangeMonitoring();
        Presence.stopPresenceMonitoring();
    });

});
// build-526-ascii-validation-1775354643
// build-527-arraybuffer-1775355528
