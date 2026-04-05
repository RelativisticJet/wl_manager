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
    "app/wl_manager/modules/wl_debug",
    "splunkjs/mvc/simplexml/ready!"
], function ($, _, mvc, utils, C, REST, UI, Table, Versions, Modals, CsvIO, Diff, Debug) {
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
    var undoTimer       = null;     // timeout id for undo bar
    var undoState       = null;     // {row, reason, prevRows, prevOriginal}
    var saving           = false;   // debounce flag to prevent rapid saves
    var MAX_CELL_CHARS   = C.MAX_CELL_CHARS;
    var expireColumn     = "";      // name of the expiration column (e.g. "Expires", "expiry", "termination_date")
    var searchQuery      = "";      // current search/filter text for the CSV table
    var loadedMtime      = null;    // file mtime when CSV was loaded/saved (for external change detection)
    var loadedPendingCount = 0;    // pending approval count when CSV was loaded (for lock-state polling)
    var changeCheckTimer = null;    // setInterval ID for external change polling
    var pendingApprovals = [];      // pending approval items for current CSV (from server)
    var csvLocked        = false;  // true when ANY pending approval exists — entire file locked
    var isAdmin          = false;  // true if current user has admin/sc_admin/wl_admin role
    var pendingBulkEditCount = 0;  // tracks unsaved Bulk Edit changes (for correct limit classification)

    // ── Dark theme (module handles body class; WM adds panel class) ──
    if (UI.detectDarkTheme()) {
        $("#wl-dropdowns").closest(".dashboard-panel").addClass("wl-dark");
    }

    // ══════════════════════════════════════════════════════════════════
    // Detect admin role
    // ══════════════════════════════════════════════════════════════════
    (function detectAdminRole() {
        restGet({ action: "get_approval_queue" })
        .done(function () {
            isAdmin = true;
            // If CSV was already loaded & locked before this check completed,
            // re-render the approval bar now that we know user is admin
            if (pendingApprovals.length) {
                applyPendingHighlighting();
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
            doSave:                    function () { return doSave(); },
            doSaveRemoval:             function () { return doSaveRemoval.apply(null, arguments); },
            doSaveBulkRemoval:         function () { return doSaveBulkRemoval.apply(null, arguments); },
            doSaveColumnAddition:      function () { return doSaveColumnAddition.apply(null, arguments); },
            doColumnRemoveWithGateCheck: function () { return doColumnRemoveWithGateCheck.apply(null, arguments); },
            submitApprovalRequest:     function () { return submitApprovalRequest.apply(null, arguments); },
            exportCsv:                 function () { return CsvIO.exportCsv(); },
            importCsv:                 function () { return CsvIO.importCsv.apply(null, arguments); },
            loadVersions:              function () { return loadVersions.apply(null, arguments); },
            clearUndo:                 function () { return clearUndo(); },
            applyPendingCssHighlighting: function () { return applyPendingCssHighlighting(); },
            formatLocalDateTime:       function () { return formatLocalDateTime.apply(null, arguments); },
            handleSaveError:           function () { return handleSaveError.apply(null, arguments); }
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

    // ── CSV I/O module alias ──
    var csvEscape = CsvIO.csvEscape;

    // ── Diff module init ──
    Diff.init({ $diff: $diff });
    var renderDiff = Diff.renderDiff;

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
            handleSaveError: function () { return handleSaveError.apply(null, arguments); },
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
                    stopChangeMonitoring();
                    $searchGroup.hide();
                    Versions.hide();
                    $table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
                    $diff.empty();
                } else if (!isRule && name === selectedCsv) {
                    selectedCsv = "";
                    selectedApp = "";
                    stopChangeMonitoring();
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
            reloadCsv: function () { loadCsv(selectedCsv, selectedApp); }
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

    // ══════════════════════════════════════════════════════════════════
    // Conflict handling (optimistic locking)
    // ══════════════════════════════════════════════════════════════════
    function handleSaveError(xhr, fallbackMsg) {
        var err = fallbackMsg || "Save failed.";
        try {
            var resp = JSON.parse(xhr.responseText);
            err = resp.error || err;
            // On 409 conflict, update mtime so external change modal
            // doesn't also fire, and offer to reload
            if (xhr.status === 409 && resp.current_mtime) {
                loadedMtime = resp.current_mtime;
            }
        } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
        // Escape server error to prevent XSS
        var safeErr = _.escape(err);
        if (xhr.status === 409) {
            showMsg(safeErr + ' <span class="wl-link" id="wl-conflict-reload">Click to reload.</span>', "error");
            $msg.off("click", "#wl-conflict-reload").on("click", "#wl-conflict-reload", function () {
                loadCsv(selectedCsv, selectedApp);
            });
        } else {
            showMsg(safeErr, "error");
        }
    }

    // showMsg, formatDailyLimitMsg → wl_ui.js module (aliased above)

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
        stopChangeMonitoring();
        loadedMtime = null;
        loadedPendingCount = 0;
        $searchGroup.hide();
        Versions.hide();
        clearUndo();
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
        clearUndo();
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
            stopChangeMonitoring();
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
        stopChangeMonitoring();
        loadedMtime = null;
        loadedPendingCount = 0;
        selectedCsv = csvFile || "";
        selectedApp = appCtx || "";
        clearUndo();
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


    function doSaveColumnAddition(colName) {
        syncInputs();

        // Snapshot state for undo
        var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });
        var prevHeaders = currentHeaders.slice();
        var prevOrigHeaders = originalHeaders.slice();

        // Insert before metadata columns (those starting with "_")
        var insertIdx = currentHeaders.length;
        for (var i = 0; i < currentHeaders.length; i++) {
            if (currentHeaders[i].charAt(0) === "_") { insertIdx = i; break; }
        }
        currentHeaders.splice(insertIdx, 0, colName);

        // Add empty value for the new column to all rows
        currentRows.forEach(function (row) { row[colName] = ""; });

        refreshTable();
        showMsg("Adding column and saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Column addition",
            removal_reasons: [],
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentHeaders = prevHeaders;
                originalHeaders = prevOrigHeaders;
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            showMsg('Column <strong>' + _.escape(colName) + '</strong> added and saved.', "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            if (data.file_mtime) { loadedMtime = data.file_mtime; }

            if (data.diff && data.diff.text_diff && data.diff.text_diff.length) {
                renderDiff(data.diff);
            }

            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after column addition.");
            currentHeaders = prevHeaders;
            originalHeaders = prevOrigHeaders;
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

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
                    submitApprovalRequest("column_removal", reason, null, colName);
                });
            } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                showMsg(formatDailyLimitMsg(gateData.daily_limit), "error"
                );
            } else {
                showRemoveColumnModal(colName, function (reason) {
                    doSaveColumnRemoval(colName, reason);
                });
            }
        }).fail(function () {
            // Fallback to normal flow if gate check fails
            showRemoveColumnModal(colName, function (reason) {
                doSaveColumnRemoval(colName, reason);
            });
        });
    }

    function submitApprovalRequest(actionType, reason, rowIndices, colName) {
        syncInputs();

        var description = "";
        var highlight = {};
        var originalPayload = {};

        if (actionType === "bulk_row_removal") {
            description = reason || "Remove " + rowIndices.length + " selected rows";
            var visHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var rowKeys = rowIndices.map(function (idx) {
                return visHeaders.map(function (h) { return currentRows[idx][h] || ""; });
            });
            highlight = { type: "rows", row_keys: rowKeys, headers: visHeaders };

            var removedEntries = [];
            rowIndices.sort(function (a, b) { return a - b; });
            rowIndices.forEach(function (idx) {
                removedEntries.push({
                    row_number: idx + 1,
                    row: $.extend({}, currentRows[idx])
                });
            });
            var rowsCopy = currentRows.map(function (r) { return $.extend({}, r); });
            for (var i = rowIndices.length - 1; i >= 0; i--) {
                rowsCopy.splice(rowIndices[i], 1);
            }
            originalPayload = {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: rowsCopy,
                comment: "Bulk removal (" + rowIndices.length + " rows) - approved",
                removal_reasons: [],
                bulk_removal: removedEntries.map(function (e) {
                    return { row_number: e.row_number, row: e.row, reason: reason };
                })
            };
        } else if (actionType === "bulk_row_addition") {
            // The new rows are at the end of currentRows (beyond originalRows.length)
            var addedCount = Math.max(0, currentRows.length - originalRows.length);
            var visHeadersAdd = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
            var addedRowKeys = [];
            for (var ai = originalRows.length; ai < currentRows.length; ai++) {
                addedRowKeys.push(visHeadersAdd.map(function (h) { return currentRows[ai][h] || ""; }));
            }
            highlight = { type: "rows", row_keys: addedRowKeys, headers: visHeadersAdd };
            description = reason || "Add " + addedCount + " new rows";
            originalPayload = {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: currentRows.map(function (r) { return $.extend({}, r); }),
                comment: "Row addition (" + addedCount + " rows)",
                row_add_reason: reason || "",
                removal_reasons: []
            };
        } else if (actionType === "column_removal") {
            description = reason || "Remove column '" + colName + "'";
            highlight = { type: "column", column_name: colName };

            var headersCopy = currentHeaders.slice();
            var cidx = headersCopy.indexOf(colName);
            if (cidx !== -1) { headersCopy.splice(cidx, 1); }
            var rowsCopyCol = currentRows.map(function (r) {
                var copy = $.extend({}, r);
                delete copy[colName];
                return copy;
            });
            originalPayload = {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: headersCopy,
                rows: rowsCopyCol,
                comment: reason || "Column removal - approved",
                removal_reasons: [],
                column_removal_reasons: [{ column: colName, reason: reason }]
            };
        }

        showMsg("Submitting approval request&hellip;", "info");

        // Compute selected_count for daily limit validation
        var approvalCount = 1;
        if (actionType === "bulk_row_removal" && rowIndices) {
            approvalCount = rowIndices.length;
        } else if (actionType === "bulk_row_addition") {
            approvalCount = Math.max(0, currentRows.length - originalRows.length);
        } else if (actionType === "column_removal") {
            approvalCount = 1;
        }

        restPost({
            action: "submit_approval",
            approval_action_type: actionType,
            csv_file: selectedCsv,
            app_context: selectedApp,
            detection_rule: selectedRule || "",
            description: description,
            comment: reason || "",
            original_payload: originalPayload,
            expected_mtime: loadedMtime,
            pending_highlight: highlight,
            selected_count: approvalCount
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Your request has been submitted for approval. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            // Reload to show orange highlighting
            loadCsv(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit approval request.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function submitBulkEditApproval(col, val, rowIndices, changedCount, reason) {
        syncInputs();
        var visHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var rowKeys = rowIndices.map(function (idx) {
            return visHeaders.map(function (h) { return currentRows[idx][h] || ""; });
        });

        var displayVal = val.length > 100 ? val.substring(0, 100) + "..." : val;
        var description = "Bulk edit " + changedCount + " rows — set '" + col + "' to '" + displayVal + "'";

        showMsg("Submitting bulk edit approval request&hellip;", "info");

        restPost({
            action: "submit_approval",
            approval_action_type: "bulk_row_edit",
            csv_file: selectedCsv,
            app_context: selectedApp,
            detection_rule: selectedRule || "",
            description: description,
            original_payload: {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: currentRows,
                comment: reason || ("Bulk edit (" + changedCount + " rows) - approved"),
                bulk_edit_column: col,
                bulk_edit_value: val,
                _bulk_edit_count: changedCount
            },
            expected_mtime: loadedMtime,
            pending_highlight: { type: "rows", row_keys: rowKeys, headers: visHeaders },
            selected_count: changedCount
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Bulk edit requires approval. Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            loadCsv(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit bulk edit approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function submitInlineMultiEditApproval(changedCount, reason) {
        syncInputs();
        var autoDesc = "Inline edit of " + changedCount + " rows in " +
            (selectedCsv || "unknown CSV");

        showMsg("Submitting edit approval request&hellip;", "info");

        restPost({
            action: "submit_approval",
            approval_action_type: "bulk_row_edit",
            csv_file: selectedCsv,
            app_context: selectedApp,
            detection_rule: selectedRule || "",
            description: reason || autoDesc,
            comment: reason,
            original_payload: {
                action: "save_csv",
                csv_file: selectedCsv,
                app_context: selectedApp,
                detection_rule: selectedRule || "",
                headers: currentHeaders,
                rows: currentRows,
                comment: reason || ("Inline multi-edit (" + changedCount + " rows) - approved"),
                _bulk_edit_count: changedCount
            },
            expected_mtime: loadedMtime,
            selected_count: changedCount
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg(
                "Edit requires approval. Your request has been submitted. " +
                "Request ID: <strong>" + _.escape(data.request_id) + "</strong>",
                "success"
            );
            // Revert local edits since they're pending approval
            loadCsv(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            var err = "Failed to submit edit approval.";
            try { err = JSON.parse(xhr.responseText).error || err; } catch (e) { console.warn("wl_manager: failed to parse error response", e); }
            showMsg(_.escape(err), "error");
        });
    }

    function buildLockedState() {
        csvLocked = pendingApprovals.length > 0;
    }

    /**
     * Re-apply amber CSS classes to rows/columns/table that triggered
     * the pending approval.  Safe to call after every refreshTable().
     */
    function applyPendingCssHighlighting() {
        if (!pendingApprovals.length) { return; }
        pendingApprovals.forEach(function (pa) {
            var hl = pa.pending_highlight || {};
            if (hl.type === "rows" && hl.row_keys) {
                var hlH = hl.headers || currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
                // Use counter (not set) to handle duplicate rows correctly
                var keyCounts = {};
                hl.row_keys.forEach(function (rk) {
                    var k = JSON.stringify(rk);
                    keyCounts[k] = (keyCounts[k] || 0) + 1;
                });
                $table.find("tbody tr").each(function () {
                    var idx = $(this).data("idx");
                    if (idx !== undefined && currentRows[idx]) {
                        var key = hlH.map(function (h) { return currentRows[idx][h] || ""; });
                        var k = JSON.stringify(key);
                        if (keyCounts[k] > 0) {
                            $(this).addClass("wl-pending-approval");
                            keyCounts[k]--;
                        }
                    }
                });
            } else if (hl.type === "column" && hl.column_name) {
                $table.find("th[data-col]").filter(function () {
                    return $(this).data("col") === hl.column_name;
                }).addClass("wl-pending-approval-header");
            } else if (hl.type === "table") {
                $table.find(".wl-table").addClass("wl-pending-approval-table");
            }
        });
    }

    /**
     * Extract the analyst reason from a pending approval entry.
     */
    function extractApprovalReason(pa) {
        var payload = pa.payload || {};
        var at = pa.action_type || "";
        if (at === "bulk_row_removal") {
            var br = payload.bulk_removal;
            if (br && br.length) return br[0].reason || "";
        } else if (at === "bulk_row_addition") {
            return payload.row_add_reason || "";
        } else if (at === "column_removal") {
            var cr = payload.column_removal_reasons;
            if (cr && cr.length) return cr[0].reason || "";
        } else if (at === "revert") {
            return payload.revert_reason || "";
        }
        return "";
    }

    /**
     * Compute which currentRows indices are affected by a pending approval.
     * Uses counter-based matching for correct duplicate handling.
     */
    function getPendingRowIndices(pa) {
        var hl = pa.pending_highlight || {};
        if (hl.type !== "rows" || !hl.row_keys) return [];
        var hlH = hl.headers || currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var keyCounts = {};
        hl.row_keys.forEach(function (rk) {
            var k = JSON.stringify(rk);
            keyCounts[k] = (keyCounts[k] || 0) + 1;
        });
        var indices = [];
        for (var i = 0; i < currentRows.length; i++) {
            var key = hlH.map(function (h) { return currentRows[i][h] || ""; });
            var k = JSON.stringify(key);
            if (keyCounts[k] > 0) {
                indices.push(i);
                keyCounts[k]--;
            }
        }
        return indices;
    }

    var pendingFilterActive = false;  // tracks whether we're filtering to show only requested rows
    var pendingFilterIndices = null;  // array of row indices when filter is active

    function applyPendingHighlighting() {
        buildLockedState();
        if (!pendingApprovals.length) { return; }

        applyPendingCssHighlighting();

        // Lock all controls — entire CSV is locked
        $table.find("#btn-save").addClass("wl-btn-locked").prop("disabled", true);
        $table.find("#btn-add-row").addClass("wl-btn-locked").prop("disabled", true);
        $table.find("#btn-add-col").addClass("wl-btn-locked").prop("disabled", true);
        $table.find("#btn-remove-selected").addClass("wl-btn-locked").prop("disabled", true);
        $table.find(".wl-import-btn").addClass("wl-btn-locked");
        $table.find("#btn-import").prop("disabled", true);
        $revertSelect.prop("disabled", true);

        // Show lock banner
        var descriptions = pendingApprovals.map(function (pa) {
            return '<strong>' + _.escape(pa.action_type.replace(/_/g, " ")) + '</strong> by ' +
                   _.escape(pa.analyst) + ' (' + _.escape(pa.description) + ')';
        });
        showMsg(
            "This CSV is locked &mdash; " +
            (pendingApprovals.length > 1 ? "pending approvals" : "a pending approval") +
            " must be resolved before changes can be made. " +
            descriptions.join("; ") + ".",
            "warning"
        );

        // Approve / Reject / Cancel action bar
        // Shown for admins (approve/reject others, cancel own) and
        // non-admin analysts who own a pending request (cancel only)
        $("#wl-approval-actions").remove();
        getCurrentUser();
        var ownsAnyRequest = currentUser && pendingApprovals.some(function (pa) {
            return pa.analyst === currentUser;
        });
        if (isAdmin || ownsAnyRequest) {
            var barHtml = '<div id="wl-approval-actions" class="wl-approval-bar">';
            pendingApprovals.forEach(function (pa, paIdx) {
                var isSelfRequest = currentUser && pa.analyst === currentUser;
                // Non-admin users only see their own requests
                if (!isAdmin && !isSelfRequest) { return; }
                var reason = extractApprovalReason(pa);
                var hl = pa.pending_highlight || {};
                var hasRowHighlight = (hl.type === "rows" && hl.row_keys && hl.row_keys.length > 0);
                // Use comment (user's typed reason) or description, avoid duplication
                var displayReason = pa.comment || pa.description || "";
                var descTitle = pa.action_type.replace(/_/g, " ") +
                    ' by ' + pa.analyst + ' — ' + displayReason;
                barHtml +=
                    '<div class="wl-approval-item">' +
                        '<span class="wl-approval-desc" title="' + _.escape(descTitle) + '">' +
                            '<strong>' + _.escape(pa.action_type.replace(/_/g, " ")) + '</strong>' +
                            ' by ' + _.escape(pa.analyst) +
                            ' &mdash; ' + _.escape(displayReason) +
                        '</span>' +
                        (isSelfRequest
                            ? '<span class="btn btn-warning wl-cancel-request-btn" data-id="' +
                                _.escape(pa.request_id) + '" style="background:#f39c12;color:#fff">Cancel Request</span>'
                            : '<span class="btn btn-success wl-approve-btn" data-id="' +
                                _.escape(pa.request_id) + '">Approve</span>' +
                              '<span class="btn btn-danger wl-reject-btn" data-id="' +
                                _.escape(pa.request_id) + '">Reject</span>'
                        ) +
                        (hasRowHighlight
                            ? '<span class="btn btn-small wl-filter-requested" data-idx="' + paIdx +
                              '" style="margin-left:8px;cursor:pointer">Show Requested Rows</span>'
                            : '') +
                    '</div>';
            });
            barHtml += '</div>';
            $table.before(barHtml);
            bindApprovalActions();
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Admin Approve / Reject actions (inline on CSV editor)
    // ══════════════════════════════════════════════════════════════════

    function bindApprovalActions() {
        // ── Approve ──────────────────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-approve-btn")
            .on("click.wl", ".wl-approve-btn", function () {
            var requestId = $(this).data("id");
            showApproveConfirmModal(requestId);
        });

        // ── Reject ───────────────────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-reject-btn")
            .on("click.wl", ".wl-reject-btn", function () {
            var requestId = $(this).data("id");
            showRejectReasonModal(requestId);
        });

        // ── Show Requested Rows filter ──────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-filter-requested")
            .on("click.wl", ".wl-filter-requested", function () {
            var idx = $(this).data("idx");
            var pa = pendingApprovals[idx];
            if (!pa) return;

            if (pendingFilterActive) {
                // Remove filter — show all rows
                pendingFilterActive = false;
                pendingFilterIndices = null;
                additionPreviewData = null;
                $("#wl-addition-preview").remove();
                $(this).text("Show Requested Rows");
                Table.resetPage();
                refreshTable();
                applyPendingCssHighlighting();
            } else if (pa.action_type === "bulk_row_addition") {
                // For additions, rows don't exist in CSV yet —
                // show a read-only preview from the stored payload
                pendingFilterActive = true;
                $(this).text("Show All Rows");
                showAdditionPreview(pa);
            } else {
                // For removals/edits, filter the existing table
                var matchedIndices = getPendingRowIndices(pa);
                if (!matchedIndices.length) {
                    showMsg("No matching rows found in current CSV.", "info");
                    return;
                }
                pendingFilterActive = true;
                pendingFilterIndices = matchedIndices;
                $(this).text("Show All Rows");
                Table.resetPage();
                refreshTable();
                applyPendingCssHighlighting();
            }
        });

        // ── Cancel own request ──────────────────────────────────────
        $("#wl-approval-actions").off("click.wl", ".wl-cancel-request-btn")
            .on("click.wl", ".wl-cancel-request-btn", function () {
            var requestId = $(this).data("id");
            showCancelRequestModal(requestId);
        });
    }

    // (showCancelRequestModal → extracted to modules/wl_modals.js)

    /**
     * Show a read-only preview table of rows requested to be added.
     * These rows exist in the stored payload but not yet in the CSV.
     */
    var additionPreviewPage = 0;
    var additionPreviewData = null; // { headers, rowKeys }
    var PREVIEW_PAGE_SIZE = 10;

    function showAdditionPreview(pa) {
        var hl = pa.pending_highlight || {};
        additionPreviewData = {
            headers: hl.headers || [],
            rowKeys: hl.row_keys || []
        };
        if (!additionPreviewData.headers.length || !additionPreviewData.rowKeys.length) {
            showMsg("No row details available for this request.", "info");
            return;
        }
        additionPreviewPage = 0;
        renderAdditionPreview();
    }

    function renderAdditionPreview() {
        $("#wl-addition-preview").remove();
        if (!additionPreviewData) return;
        var headers = additionPreviewData.headers;
        var rowKeys = additionPreviewData.rowKeys;
        var total = rowKeys.length;
        var totalPages = Math.max(1, Math.ceil(total / PREVIEW_PAGE_SIZE));
        if (additionPreviewPage >= totalPages) additionPreviewPage = totalPages - 1;
        var start = additionPreviewPage * PREVIEW_PAGE_SIZE;
        var end = Math.min(start + PREVIEW_PAGE_SIZE, total);
        var pageSlice = rowKeys.slice(start, end);

        var html = '<div id="wl-addition-preview" class="wl-addition-preview">' +
            '<h4 style="margin:0 0 8px">Rows requested to be added (' + total + ')</h4>' +
            '<div style="overflow:auto">' +
            '<table class="wl-table" style="font-size:12px">' +
            '<thead><tr><th>#</th>';
        headers.forEach(function (h) {
            html += '<th>' + _.escape(h) + '</th>';
        });
        html += '</tr></thead><tbody>';
        pageSlice.forEach(function (rk, i) {
            html += '<tr class="wl-pending-approval"><td>' + (start + i + 1) + '</td>';
            if (Array.isArray(rk)) {
                rk.forEach(function (v) {
                    html += '<td title="' + _.escape(v) + '">' + _.escape(v) + '</td>';
                });
            } else {
                html += '<td colspan="' + headers.length + '">' + _.escape(JSON.stringify(rk)) + '</td>';
            }
            html += '</tr>';
        });
        html += '</tbody></table></div>';

        // Pagination controls
        if (totalPages > 1) {
            html += '<div style="margin-top:8px;display:flex;align-items:center;gap:8px">';
            html += '<span class="btn btn-small wl-preview-prev"' +
                (additionPreviewPage <= 0 ? ' style="opacity:0.4;pointer-events:none"' : '') +
                '>&laquo; Prev</span>';
            html += '<span style="font-size:12px">Page ' + (additionPreviewPage + 1) + ' of ' +
                totalPages + ' (' + total + ' rows)</span>';
            html += '<span class="btn btn-small wl-preview-next"' +
                (additionPreviewPage >= totalPages - 1 ? ' style="opacity:0.4;pointer-events:none"' : '') +
                '>Next &raquo;</span>';
            html += '</div>';
        }
        html += '</div>';

        var $bar = $("#wl-approval-actions");
        if ($bar.length) {
            $bar.after(html);
        } else {
            $table.before(html);
        }

        // Bind pagination
        $("#wl-addition-preview").off("click", ".wl-preview-prev").on("click", ".wl-preview-prev", function () {
            if (additionPreviewPage > 0) {
                additionPreviewPage--;
                renderAdditionPreview();
            }
        });
        $("#wl-addition-preview").off("click", ".wl-preview-next").on("click", ".wl-preview-next", function () {
            var totalPages = Math.ceil(additionPreviewData.rowKeys.length / PREVIEW_PAGE_SIZE);
            if (additionPreviewPage < totalPages - 1) {
                additionPreviewPage++;
                renderAdditionPreview();
            }
        });
    }

    // (showApproveConfirmModal, showRejectReasonModal, showRemoveColumnModal
    //  → extracted to modules/wl_modals.js)

    function doSaveColumnRemoval(colName, reason) {
        syncInputs();

        // Prevent removing the last visible column
        var visibleCount = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; }).length;
        if (visibleCount <= 1) {
            showMsg("Cannot remove the last column.", "error");
            return;
        }

        // Snapshot state for undo
        var prevRows = currentRows.map(function (r) { return $.extend({}, r); });
        var prevOriginal = originalRows.map(function (r) { return $.extend({}, r); });
        var prevHeaders = currentHeaders.slice();
        var prevOrigHeaders = originalHeaders.slice();

        // Remove from headers
        var idx = currentHeaders.indexOf(colName);
        if (idx !== -1) { currentHeaders.splice(idx, 1); }

        // Remove from all rows
        currentRows.forEach(function (row) { delete row[colName]; });

        refreshTable();
        showMsg("Removing column and saving&hellip;", "info");

        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         reason || "Column removal",
            removal_reasons: [],
            column_removal_reasons: [{ column: colName, reason: reason }],
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentHeaders = prevHeaders;
                originalHeaders = prevOrigHeaders;
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var msg = 'Column <strong>' + _.escape(colName) + '</strong> removed and saved.';
            if (diffInfo.edited_count > 0) {
                msg += " " + diffInfo.edited_count + " row(s) also edited.";
            }
            showMsg(msg, "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            if (data.file_mtime) { loadedMtime = data.file_mtime; }

            // Show undo bar for column removal
            showUndoBar(null, prevRows, prevOriginal, colName, prevHeaders, prevOrigHeaders);
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to save after column removal.");
            currentHeaders = prevHeaders;
            originalHeaders = prevOrigHeaders;
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Undo removal (10-second window)
    // ══════════════════════════════════════════════════════════════════

    function showUndoBar(removedRow, prevRows, prevOriginal, removedColName, prevHeaders, prevOrigHeaders) {
        clearUndo();

        var desc;
        if (removedColName) {
            desc = 'Column removed: <strong>' + _.escape(removedColName) + '</strong>';
        } else {
            var rowDesc = [];
            currentHeaders.forEach(function (h) {
                if (h.charAt(0) !== "_" && removedRow[h]) {
                    rowDesc.push(removedRow[h]);
                }
            });
            var descText = rowDesc.slice(0, 3).join(", ");
            if (rowDesc.length > 3) { descText += "..."; }
            desc = 'Row removed: <strong>' + _.escape(descText) + '</strong>';
        }

        undoState = {
            prevRows: prevRows,
            prevOriginal: prevOriginal,
            prevHeaders: prevHeaders || null,
            prevOrigHeaders: prevOrigHeaders || null
        };

        var $bar = $table.find("#wl-undo-bar");
        $bar.html(
            '<div class="wl-undo">' +
            '<span>' + desc + '</span> ' +
            '<button class="btn btn-small" id="btn-undo">Undo</button> ' +
            '<span class="wl-undo-countdown" id="undo-countdown">10s</span>' +
            '</div>'
        );

        var secondsLeft = 10;
        undoTimer = setInterval(function () {
            secondsLeft--;
            $bar.find("#undo-countdown").text(secondsLeft + "s");
            if (secondsLeft <= 0) {
                clearUndo();
            }
        }, 1000);

        $bar.off("click", "#btn-undo").on("click", "#btn-undo", function () {
            doUndo();
        });
    }

    function doUndo() {
        if (!undoState) { return; }

        // Restore rows to the state before removal
        currentRows = undoState.prevRows.map(function (r) { return $.extend({}, r); });

        // Restore headers if this was a column removal undo
        if (undoState.prevHeaders) {
            currentHeaders = undoState.prevHeaders.slice();
        }

        var wasColumnUndo = !!undoState.prevHeaders;
        clearUndo();
        showMsg("Saving undo&hellip;", "info");

        // Save the restored state back to the server
        restPost({
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         wasColumnUndo ? "Undo column removal" : "Undo row removal",
            removal_reasons: [],
            expected_mtime:  loadedMtime
        })
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                return;
            }
            showMsg("Removal undone and saved.", "success");
            reloadCsvQuiet();
        })
        .fail(function (xhr) {
            handleSaveError(xhr, "Failed to undo removal.");
        });
    }

    function clearUndo() {
        if (undoTimer) {
            clearInterval(undoTimer);
            undoTimer = null;
        }
        undoState = null;
        var $bar = $table.find("#wl-undo-bar");
        if ($bar.length) { $bar.empty(); }
    }

    // ══════════════════════════════════════════════════════════════════
    // External change detection (poll file mtime every 5s)
    // ══════════════════════════════════════════════════════════════════

    function startChangeMonitoring() {
        stopChangeMonitoring();
        if (!selectedCsv || !loadedMtime) { return; }
        changeCheckTimer = setInterval(checkForExternalChanges, 5000);
    }

    function stopChangeMonitoring() {
        if (changeCheckTimer) { clearInterval(changeCheckTimer); changeCheckTimer = null; }
    }

    function checkForExternalChanges() {
        if (!selectedCsv || !loadedMtime || saving) { return; }
        restGet({
            action:   "check_csv_status",
            csv_file: selectedCsv,
            app:      selectedApp || ""
        })
        .done(function (data) {
            // Lock state changed — auto-reload (no modal needed)
            var newPending = data.pending_count !== undefined ? data.pending_count : 0;
            if (newPending !== loadedPendingCount) {
                loadCsv(selectedCsv, selectedApp);
                return;
            }
            // File content changed — show conflict modal
            if (data.file_mtime && data.file_mtime !== loadedMtime) {
                stopChangeMonitoring();
                showExternalChangeModal();
            }
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(selectedCsv);
            }
        });
    }

    function hasUnsavedChanges() {
        if (currentHeaders.length !== originalHeaders.length) { return true; }
        for (var i = 0; i < currentHeaders.length; i++) {
            if (currentHeaders[i] !== originalHeaders[i]) { return true; }
        }
        if (currentRows.length !== originalRows.length) { return true; }
        for (var r = 0; r < currentRows.length; r++) {
            for (var h = 0; h < currentHeaders.length; h++) {
                var hdr = currentHeaders[h];
                if ((currentRows[r][hdr] || "") !== (originalRows[r][hdr] || "")) { return true; }
            }
        }
        return false;
    }

    function showExternalChangeModal() {
        $(".wl-modal-overlay").remove();

        var unsaved = hasUnsavedChanges();
        var warning = unsaved
            ? '<p style="color:var(--wl-warn-text,#e65100);margin-top:8px">' +
              '<strong>Warning:</strong> You have unsaved changes that will be lost if you reload.</p>'
            : '';

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">CSV File Changed Externally</div>' +
                    '<div class="wl-modal-body">' +
                        'The file <strong>' + _.escape(selectedCsv) + '</strong> has been modified ' +
                        'outside of Whitelist Manager (possibly by another analyst or application).' +
                        warning +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<span class="btn btn-primary" id="wl-extchg-reload">Reload CSV</span> ' +
                        '<span class="btn" id="wl-extchg-keep">Keep editing</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        $modal.on("click", "#wl-extchg-reload", function () {
            $modal.remove();
            loadCsv(selectedCsv, selectedApp);
        });
        $modal.on("click", "#wl-extchg-keep", function () {
            $modal.remove();
            // Update mtime so prompt doesn't immediately reappear
            restGet({
                action:   "check_csv_status",
                csv_file: selectedCsv,
                app:      selectedApp || ""
            })
            .done(function (data) {
                loadedMtime = data.file_mtime || loadedMtime;
                startChangeMonitoring();
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Comment validation
    // ══════════════════════════════════════════════════════════════════

    function getAuditComment(callback) {
        var hasCommentCol = currentHeaders.indexOf("Comment") !== -1;

        $table.find(".wl-input").removeClass("wl-input-error");

        if (hasCommentCol) {
            var emptyFound = false;
            $table.find("tbody tr").each(function () {
                $(this).find('.wl-input[data-header="Comment"]').each(function () {
                    if (!$(this).val().trim()) {
                        $(this).addClass("wl-input-error");
                        emptyFound = true;
                    }
                });
            });

            if (emptyFound) {
                showMsg("Comment field cannot be empty.", "error");
                return;
            }

            callback({ valid: true, comment: "" });
            return;
        }

        // Show styled modal for audit comment
        $(".wl-modal-overlay").remove();
        var html =
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal" style="max-width:480px">' +
                '<h3 style="margin-top:0">Audit Comment Required</h3>' +
                '<p style="font-size:13px;color:var(--wl-text-secondary,#888);margin:0 0 12px">' +
                    'This CSV does not have a "Comment" column.<br>' +
                    'Please provide a reason for this change (max 500 chars).<br>' +
                    '<em>This will be recorded in the audit trail only, not saved in the CSV.</em>' +
                '</p>' +
                '<textarea id="wl-audit-comment-input" rows="3" maxlength="500" ' +
                    'style="width:100%;box-sizing:border-box;font-family:inherit;' +
                    'font-size:13px;padding:6px 8px;border:1px solid var(--wl-border);' +
                    'border-radius:3px;background:var(--wl-bg-input);color:var(--wl-text);' +
                    'resize:vertical" placeholder="Reason for this change\u2026"></textarea>' +
                '<div class="wl-char-counter" data-for="wl-audit-comment-input">0 / 500</div>' +
                '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">' +
                    '<span class="btn btn-primary" id="wl-audit-comment-ok" ' +
                        'style="cursor:pointer">OK</span>' +
                    '<span class="btn" id="wl-audit-comment-cancel" ' +
                        'style="cursor:pointer">Cancel</span>' +
                '</div>' +
            '</div></div>';

        $("body").append(html);
        setTimeout(function () { $("#wl-audit-comment-input").focus(); }, 100);

        $(".wl-modal-overlay").on("click", "#wl-audit-comment-cancel", function () {
            $(".wl-modal-overlay").remove();
        });
        $(".wl-modal-overlay").on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) {
                $(".wl-modal-overlay").remove();
            }
        });
        $(".wl-modal-overlay").on("click", "#wl-audit-comment-ok", function () {
            var comment = ($("#wl-audit-comment-input").val() || "").trim();
            if (!comment) {
                $("#wl-audit-comment-input").css("border-color", "#e74c3c")
                    .attr("placeholder", "A reason is required!");
                return;
            }
            if (C.NON_ASCII_RE.test(comment)) {
                $("#wl-audit-comment-input").css("border-color", "#e74c3c");
                showMsg(C.ASCII_ERROR_MSG, "error");
                return;
            }
            if (comment.length > 500) {
                comment = comment.substring(0, 500);
                showMsg("Comment truncated to 500 characters.", "warning");
            }
            $(".wl-modal-overlay").remove();
            callback({ valid: true, comment: comment });
        });
    }


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
            buildLockedState();
            renderTable(data.headers || [], data.rows || []);
            loadVersions(csvFile, appContext);
            loadedMtime = data.file_mtime || null;
            startChangeMonitoring();
            // Apply pending approval CSS highlighting + banner
            if (pendingApprovals.length) {
                applyPendingHighlighting();
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
                handleCsvRemoved(csvFile);
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
                startChangeMonitoring();
            }
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(selectedCsv);
            }
        })
        .always(function () {
            if (callback) { callback(); }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save CSV (full save — Save Changes button)
    // ══════════════════════════════════════════════════════════════════
    function doSave() {
        if (saving) { return; }
        if (csvLocked) {
            showMsg("This CSV is locked by a pending approval request.", "error");
            return;
        }

        syncInputs();

        // Remove completely empty rows before saving
        var visHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var beforeCount = currentRows.length;
        currentRows = currentRows.filter(function (row) {
            return visHeaders.some(function (h) { return (row[h] || "").trim() !== ""; });
        });
        if (currentRows.length < beforeCount) {
            refreshTable();
        }

        if (!selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        // ── Pre-save gate: estimate edits and additions to check limits ──
        var editedCount = 0;
        var addedCount = Math.max(0, currentRows.length - originalRows.length);
        visHeaders.forEach(function () {}); // reuse visHeaders from above
        var origKeySet = {};
        originalRows.forEach(function (row) {
            var key = visHeaders.map(function (h) { return row[h] || ""; }).join("||");
            origKeySet[key] = true;
        });
        currentRows.forEach(function (row, idx) {
            if (idx < originalRows.length) {
                var changed = visHeaders.some(function (h) {
                    return (row[h] || "") !== (originalRows[idx][h] || "");
                });
                if (changed) { editedCount++; }
            }
        });

        // If either inline edits or additions exceed thresholds, the backend
        // will block the save with a 403.  Show a clear frontend message first.
        function proceedWithSave() {
            getAuditComment(function (result) {
            if (!result) { return; }

            saving = true;
            $table.find("#btn-save").prop("disabled", true).text("Saving...");
            showMsg("Saving&hellip;", "info");

            var savePayload = {
                action:          "save_csv",
                csv_file:        selectedCsv,
                app_context:     selectedApp,
                detection_rule:  selectedRule || "",
                headers:         currentHeaders,
                rows:            currentRows,
                comment:         result.comment,
                removal_reasons: [],
                expected_mtime:  loadedMtime
            };
            // Include bulk edit marker so backend classifies edits correctly
            if (pendingBulkEditCount > 0) {
                savePayload._bulk_edit_count = pendingBulkEditCount;
            }
            restPost(savePayload)
            .done(function (data) {
                if (data.error) {
                    saving = false;
                    showMsg(_.escape(data.error), "error");
                    currentRows = originalRows.map(function (r) { return $.extend({}, r); });
                    refreshTable();
                    return;
                }

                var diffInfo = data.diff || {};
                var totalRowChanges = (diffInfo.added_count || 0) +
                                      (diffInfo.removed_count || 0) +
                                      (diffInfo.edited_count || 0);
                var colsAdded   = (diffInfo.added_columns   || []).length;
                var colsRemoved = (diffInfo.removed_columns || []).length;

                if (totalRowChanges > 0 || colsAdded > 0 || colsRemoved > 0) {
                    var parts = [];
                    if (diffInfo.added_count)   { parts.push("Added: <strong>" + diffInfo.added_count + "</strong> row(s)"); }
                    if (diffInfo.removed_count) { parts.push("Removed: <strong>" + diffInfo.removed_count + "</strong> row(s)"); }
                    if (diffInfo.edited_count)  { parts.push("Edited: <strong>" + diffInfo.edited_count + "</strong> row(s)"); }
                    if (colsAdded)   { parts.push("Columns added: <strong>" + colsAdded + "</strong>"); }
                    if (colsRemoved) { parts.push("Columns removed: <strong>" + colsRemoved + "</strong>"); }
                    showMsg("Saved successfully. " + parts.join(", ") + ".", "success");
                } else {
                    showMsg("No changes detected.", "info");
                }

                if (diffInfo.text_diff && diffInfo.text_diff.length) {
                    renderDiff(diffInfo);
                }

                // Clear search after successful save so all rows are visible
                searchQuery = "";

                // Reload CSV from server to pick up backend-stamped metadata
                // (e.g. _review_status=pending, _added_by, _added_at)
                reloadCsvQuiet(function () {
                    saving = false;
                });
            })
            .fail(function (xhr) {
                saving = false;
                pendingBulkEditCount = 0; // Reset on save failure
                handleSaveError(xhr, "Failed to save CSV.");
                currentRows = originalRows.map(function (r) { return $.extend({}, r); });
                currentHeaders = originalHeaders.slice();
                refreshTable();
            });
            }); // end getAuditComment callback
        }

        // Pre-save checks:
        //  - Bulk Edit edits   → check "bulk_row_edit" approval gate + daily limit
        //  - Inline row edits  → check "row_edit" daily limit (no approval gate)
        //  - Inline row adds   → check "bulk_row_addition" approval gate
        var needsGateCheck = false;
        var gateAction = "";
        var gateCount = 0;

        if (addedCount > 0) {
            // Row additions still use the approval gate for large batches
            needsGateCheck = true;
            gateAction = "bulk_row_addition";
            gateCount = addedCount;
        } else if (editedCount >= 2) {
            // 2+ row edits = bulk edit (matches server-side is_bulk_edit
            // = edited_count >= 2) — check bulk_row_edit gate + limit
            // regardless of whether the Bulk Edit button was used
            needsGateCheck = true;
            gateAction = "bulk_row_edit";
            gateCount = editedCount;
        } else if (editedCount > 0) {
            // Single inline edit — daily limit check only, no approval gate
            needsGateCheck = true;
            gateAction = "inline_row_edit";
            gateCount = editedCount;
        }

        if (needsGateCheck) {
            restPost({
                action: "check_approval_gate",
                gate_action: gateAction,
                csv_file: selectedCsv,
                app_context: selectedApp,
                selected_count: gateCount
            }).done(function (gateData) {
                if (gateData.requires_approval) {
                    // Show reason modal and submit for approval
                    var actionDesc = gateAction === "bulk_row_edit"
                        ? "Editing <strong>" + gateCount + "</strong> row(s)"
                        : "Adding <strong>" + gateCount + "</strong> row(s)";
                    showRemoveRowModal(
                        "Submit for Approval",
                        actionDesc + " requires admin approval.<br>" +
                            "Reason: " + _.escape(gateData.reason) + "<br><br>" +
                            "Your request will be submitted for review.",
                        function (reason) {
                            if (gateAction === "bulk_row_addition") {
                                submitApprovalRequest("bulk_row_addition", reason, null, null);
                            } else if (gateAction === "bulk_row_edit") {
                                // Submit full save payload for approval
                                // (inline multi-row edits don't have a single col/val)
                                submitInlineMultiEditApproval(gateCount, reason);
                            }
                        },
                        {
                            reasonLabel: gateAction === "bulk_row_edit" ? "Reason for bulk edit" : "Reason for adding rows",
                            placeholder: gateAction === "bulk_row_edit" ? "Why are these rows being edited?" : "Why are these rows being added?",
                            confirmText: "Submit",
                            confirmClass: "btn-primary"
                        }
                    );
                } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                    showMsg(formatDailyLimitMsg(gateData.daily_limit),
                        "error"
                    );
                } else {
                    proceedWithSave();
                }
            }).fail(function () {
                // Fail-closed: block save if gate check fails
                showMsg("Unable to verify approval gate. Please try again.", "error");
            });
        } else {
            proceedWithSave();
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // Save for row removal — auto-triggered, with undo support
    // ══════════════════════════════════════════════════════════════════
    function doSaveRemoval(removedRow, reason, rowNumber, prevRows, prevOriginal) {
        if (!selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        showMsg("Removing row and saving&hellip;", "info");

        var rmPayload = {
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Row removal",
            removal_reasons: [{ row: removedRow, reason: reason, row_number: rowNumber }],
            expected_mtime:  loadedMtime
        };
        // If unsaved bulk edits are included in currentRows, mark them
        // so the backend classifies them as bulk_row_edit (not row_edit)
        if (pendingBulkEditCount > 0) {
            rmPayload._bulk_edit_count = pendingBulkEditCount;
        }
        restPost(rmPayload)
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var rmMsg = "Row removed and saved successfully.";
            if (diffInfo.edited_count > 0) {
                rmMsg = "Row removed and " + diffInfo.edited_count + " row(s) edited. Saved successfully.";
            }
            showMsg(rmMsg, "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            pendingBulkEditCount = 0; // Bulk edits (if any) were committed with the removal
            if (data.file_mtime) { loadedMtime = data.file_mtime; }
            refreshTable(); // Re-render to clear stale edit highlights

            // Show undo bar for 10 seconds
            showUndoBar(removedRow, prevRows, prevOriginal);
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            // Refresh version list
            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            pendingBulkEditCount = 0; // Reset on failure too (rows are restored)
            handleSaveError(xhr, "Failed to save after removal.");
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Save for bulk removal — multiple rows at once
    // ══════════════════════════════════════════════════════════════════
    function doSaveBulkRemoval(removedEntries, reason, prevRows, prevOriginal) {
        if (!selectedCsv) {
            showMsg("No CSV file selected.", "error");
            return;
        }

        showMsg("Removing " + removedEntries.length + " row(s) and saving&hellip;", "info");

        // Build bulk_removal payload with row numbers for audit
        var bulkRemoval = removedEntries.map(function (entry) {
            return {
                row_number: entry.row_number,
                row: entry.row,
                reason: reason
            };
        });

        var bulkRmPayload = {
            action:          "save_csv",
            csv_file:        selectedCsv,
            app_context:     selectedApp,
            detection_rule:  selectedRule || "",
            headers:         currentHeaders,
            rows:            currentRows,
            comment:         "Bulk removal (" + removedEntries.length + " rows)",
            removal_reasons: [],
            bulk_removal:    bulkRemoval,
            expected_mtime:  loadedMtime
        };
        if (pendingBulkEditCount > 0) {
            bulkRmPayload._bulk_edit_count = pendingBulkEditCount;
        }
        restPost(bulkRmPayload)
        .done(function (data) {
            if (data.error) {
                showMsg(_.escape(data.error), "error");
                currentRows = prevRows.map(function (r) { return $.extend({}, r); });
                originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
                refreshTable();
                return;
            }

            var diffInfo = data.diff || {};
            var bulkMsg = removedEntries.length + " row(s) removed and saved successfully.";
            if (diffInfo.edited_count > 0) {
                bulkMsg = removedEntries.length + " row(s) removed and " + diffInfo.edited_count + " row(s) edited. Saved successfully.";
            }
            showMsg(bulkMsg, "success");
            originalRows = currentRows.map(function (r) { return $.extend({}, r); });
            originalHeaders = currentHeaders.slice();
            pendingBulkEditCount = 0; // Bulk edits (if any) were committed with the removal
            if (data.file_mtime) { loadedMtime = data.file_mtime; }
            refreshTable(); // Re-render to clear stale edit highlights
            if (diffInfo.text_diff && diffInfo.text_diff.length) {
                renderDiff(diffInfo);
            }

            // Refresh version list
            loadVersions(selectedCsv, selectedApp);
        })
        .fail(function (xhr) {
            pendingBulkEditCount = 0; // Reset on failure too (rows are restored)
            handleSaveError(xhr, "Failed to save after bulk removal.");
            currentRows = prevRows.map(function (r) { return $.extend({}, r); });
            originalRows = prevOriginal.map(function (r) { return $.extend({}, r); });
            refreshTable();
        });
    }

    // (renderDiff → extracted to modules/wl_diff.js)

    // ══════════════════════════════════════════════════════════════════
    // Date/Time Picker for Expires column
    // ══════════════════════════════════════════════════════════════════

    var $datePicker = null;
    var $activeExpiresInput = null;

    function padTwo(n) {
        return n < 10 ? "0" + n : "" + n;
    }

    function formatDateForPicker(d) {
        return d.getFullYear() + "-" + padTwo(d.getMonth() + 1) + "-" + padTwo(d.getDate());
    }

    function formatLocalDateTime(d) {
        return d.getFullYear() + "-" + padTwo(d.getMonth() + 1) + "-" + padTwo(d.getDate()) +
               " " + padTwo(d.getHours()) + ":" + padTwo(d.getMinutes());
    }

    function formatUTCDateTime(d) {
        return d.getUTCFullYear() + "-" + padTwo(d.getUTCMonth() + 1) + "-" + padTwo(d.getUTCDate()) +
               " " + padTwo(d.getUTCHours()) + ":" + padTwo(d.getUTCMinutes());
    }

    function createDatePicker() {
        if ($datePicker) { return; }

        var html =
            '<div id="wl-date-picker" class="wl-date-picker">' +
                '<div class="wl-dp-header">Set Expiration</div>' +
                '<div class="wl-dp-presets">' +
                    '<button class="btn btn-small wl-dp-preset" data-days="7">7 Days</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="30">30 Days</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="182">6 Months</button>' +
                    '<button class="btn btn-small wl-dp-preset" data-days="365">1 Year</button>' +
                '</div>' +
                '<div class="wl-dp-manual">' +
                    '<label class="wl-dp-label">Date</label>' +
                    '<input type="date" class="wl-dp-date" />' +
                    '<label class="wl-dp-label">Time (24h)</label>' +
                    '<input type="text" class="wl-dp-time" value="00:00" placeholder="HH:MM" maxlength="5" />' +
                '</div>' +
                '<div class="wl-dp-actions">' +
                    '<button class="btn btn-small btn-primary wl-dp-apply">Apply</button>' +
                    '<button class="btn btn-small wl-dp-clear">Clear (Permanent)</button>' +
                    '<button class="btn btn-small wl-dp-cancel">Cancel</button>' +
                '</div>' +
            '</div>';

        $datePicker = $(html);
        $("body").append($datePicker);

        // Preset buttons
        $datePicker.on("click", ".wl-dp-preset", function () {
            var days = parseInt($(this).data("days"), 10);
            var future = new Date();
            future.setDate(future.getDate() + days);
            $datePicker.find(".wl-dp-date").val(formatDateForPicker(future));
            $datePicker.find(".wl-dp-time").val(padTwo(future.getHours()) + ":" + padTwo(future.getMinutes()));
        });

        // Apply button — convert local picker values to UTC for storage
        $datePicker.on("click", ".wl-dp-apply", function () {
            var d = $datePicker.find(".wl-dp-date").val();
            var t = ($datePicker.find(".wl-dp-time").val() || "00:00").trim();
            if (!d) { return; }
            // Validate 24h time format (HH:MM, 00:00–23:59)
            if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) {
                $datePicker.find(".wl-dp-time").css("border-color", "#e74c3c");
                return;
            }
            $datePicker.find(".wl-dp-time").css("border-color", "");
            if ($activeExpiresInput) {
                // Parse local date/time from picker
                var tp = t.split(":");
                var localDate = new Date(
                    parseInt(d.substr(0, 4), 10), parseInt(d.substr(5, 2), 10) - 1,
                    parseInt(d.substr(8, 2), 10), parseInt(tp[0], 10), parseInt(tp[1], 10)
                );
                // Store UTC in data model
                var utcStr = formatUTCDateTime(localDate) + " UTC";
                var idx = $activeExpiresInput.closest("tr").data("idx");
                var header = $activeExpiresInput.data("header");
                if (currentRows[idx]) { currentRows[idx][header] = utcStr; }
                // Display local time in the input
                $activeExpiresInput.val(d + " " + t);
            }
            closeDatePicker();
        });

        // Clear button (permanent — empty Expires)
        $datePicker.on("click", ".wl-dp-clear", function () {
            if ($activeExpiresInput) {
                var idx = $activeExpiresInput.closest("tr").data("idx");
                var header = $activeExpiresInput.data("header");
                if (currentRows[idx]) { currentRows[idx][header] = ""; }
                $activeExpiresInput.val("");
            }
            closeDatePicker();
        });

        // Cancel button
        $datePicker.on("click", ".wl-dp-cancel", function () {
            closeDatePicker();
        });
    }

    function showDatePicker($input) {
        createDatePicker();
        $activeExpiresInput = $input;

        // Read stored value from data model (may be UTC with Z suffix)
        var idx = $input.closest("tr").data("idx");
        var header = $input.data("header");
        var stored = (currentRows[idx] && currentRows[idx][header]) || "";
        stored = stored.trim();

        if (stored && stored.endsWith("UTC")) {
            // UTC value — convert to local for picker display
            var utcDate = new Date(stored.replace(" UTC", "Z").replace(" ", "T"));
            if (!isNaN(utcDate.getTime())) {
                $datePicker.find(".wl-dp-date").val(formatDateForPicker(utcDate));
                $datePicker.find(".wl-dp-time").val(padTwo(utcDate.getHours()) + ":" + padTwo(utcDate.getMinutes()));
            }
        } else if (/^\d{4}-\d{2}-\d{2}/.test(stored)) {
            // Legacy local value — use as-is
            var parts = stored.split(" ");
            $datePicker.find(".wl-dp-date").val(parts[0] || "");
            $datePicker.find(".wl-dp-time").val(parts[1] || "00:00");
        } else {
            var now = new Date();
            $datePicker.find(".wl-dp-date").val(formatDateForPicker(now));
            $datePicker.find(".wl-dp-time").val(padTwo(now.getHours()) + ":" + padTwo(now.getMinutes()));
        }

        // Position below the input
        var offset = $input.offset();
        var inputHeight = $input.outerHeight();
        $datePicker.css({
            top: offset.top + inputHeight + 4,
            left: offset.left,
            display: "block"
        });
    }

    function closeDatePicker() {
        if ($datePicker) {
            $datePicker.css("display", "none");
        }
        $activeExpiresInput = null;
    }

    // Bind Expires cell click — delegated on $table
    $table.on("click.wl", ".wl-expires-input", function (e) {
        e.stopPropagation();
        showDatePicker($(this));
    });

    // Close picker when clicking outside
    $(document).on("click", function (e) {
        if ($datePicker && $datePicker.css("display") !== "none") {
            if (!$(e.target).closest("#wl-date-picker").length &&
                !$(e.target).closest(".wl-expires-input").length) {
                closeDatePicker();
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
                doSave();
            }
            return;
        }

        // Escape — close any open modal, date picker, or clear search
        if (e.which === 27 || e.key === "Escape") {
            if ($datePicker && $datePicker.css("display") !== "none") {
                e.preventDefault();
                e.stopPropagation();
                closeDatePicker();
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

    // ══════════════════════════════════════════════════════════════════
    // Bulk Edit Mode — apply same value to a column across selected rows
    // ══════════════════════════════════════════════════════════════════

    function showBulkEditModal() {
        var selectedCount = Table.getSelectedCount();
        if (selectedCount === 0) {
            showMsg("Select rows first using the checkboxes.", "warning");
            return;
        }

        $(".wl-modal-overlay").remove();

        var visibleHeaders = currentHeaders.filter(function (h) { return h.charAt(0) !== "_"; });
        var colOptions = visibleHeaders.map(function (h) {
            return '<option value="' + _.escape(h) + '">' + _.escape(h) + '</option>';
        }).join("");

        var datePickerHtml =
            '<div id="wl-bulk-expires-picker" style="display:none">' +
                '<div class="wl-dp-presets" style="margin-bottom:6px">' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="7">7 Days</button>' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="30">30 Days</button>' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="182">6 Months</button>' +
                    '<button class="btn btn-small wl-bulk-dp-preset" data-days="365">1 Year</button>' +
                '</div>' +
                '<div style="display:flex;gap:8px;align-items:flex-end">' +
                    '<div style="flex:1">' +
                        '<label class="wl-dp-label">Date</label>' +
                        '<input type="date" id="wl-bulk-dp-date" class="wl-dp-date" style="width:100%" />' +
                    '</div>' +
                    '<div style="flex:0 0 80px">' +
                        '<label class="wl-dp-label">Time (24h)</label>' +
                        '<input type="text" id="wl-bulk-dp-time" class="wl-dp-time" value="00:00" ' +
                            'placeholder="HH:MM" maxlength="5" style="width:100%" />' +
                    '</div>' +
                '</div>' +
                '<button class="btn btn-small wl-bulk-dp-clear" style="margin-top:6px">Clear (Permanent)</button>' +
            '</div>';

        var html =
            '<div class="wl-modal-overlay">' +
                '<div class="wl-modal">' +
                    '<div class="wl-modal-header">Bulk Edit</div>' +
                    '<div class="wl-modal-body">' +
                        '<p>Apply the same value to <strong>' + selectedCount + '</strong> selected row(s).</p>' +
                        '<label class="wl-dp-label">Column:</label>' +
                        '<select id="wl-bulk-col" class="wl-select" style="width:100%;margin-bottom:8px">' +
                        colOptions + '</select>' +
                        '<label class="wl-dp-label" id="wl-bulk-val-label">New value:</label>' +
                        '<input type="text" id="wl-bulk-val" class="wl-input" ' +
                            'maxlength="' + MAX_CELL_CHARS + '" ' +
                            'placeholder="Value to apply" style="width:100%" />' +
                        datePickerHtml +
                    '</div>' +
                    '<div class="wl-modal-actions">' +
                        '<span class="btn btn-primary" id="wl-bulk-apply">Apply</span> ' +
                        '<span class="btn" id="wl-bulk-cancel">Cancel</span>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var $modal = $(html);
        $("body").append($modal);

        // Toggle between text input and date picker based on column selection
        function updateBulkValueInput() {
            var col = $modal.find("#wl-bulk-col").val();
            var isExpires = (expireColumn && col === expireColumn);
            if (isExpires) {
                $modal.find("#wl-bulk-val, #wl-bulk-val-label").hide();
                $modal.find("#wl-bulk-expires-picker").show();
                // Default to now
                var now = new Date();
                $modal.find("#wl-bulk-dp-date").val(formatDateForPicker(now));
                $modal.find("#wl-bulk-dp-time").val(padTwo(now.getHours()) + ":" + padTwo(now.getMinutes()));
            } else {
                $modal.find("#wl-bulk-val, #wl-bulk-val-label").show();
                $modal.find("#wl-bulk-expires-picker").hide();
            }
        }
        $modal.on("change", "#wl-bulk-col", updateBulkValueInput);
        // Check initial selection
        updateBulkValueInput();

        // Date picker preset buttons
        $modal.on("click", ".wl-bulk-dp-preset", function () {
            var days = parseInt($(this).data("days"), 10);
            var future = new Date();
            future.setDate(future.getDate() + days);
            $modal.find("#wl-bulk-dp-date").val(formatDateForPicker(future));
            $modal.find("#wl-bulk-dp-time").val(padTwo(future.getHours()) + ":" + padTwo(future.getMinutes()));
        });

        // Clear button — set expiration to empty (permanent)
        $modal.on("click", ".wl-bulk-dp-clear", function () {
            $modal.find("#wl-bulk-dp-date").val("");
            $modal.find("#wl-bulk-dp-time").val("00:00");
        });

        $modal.on("click", "#wl-bulk-apply", function () {
            var col = $modal.find("#wl-bulk-col").val();
            var val;
            var isExpires = (expireColumn && col === expireColumn);

            if (isExpires) {
                // Build UTC value from date picker
                var d = $modal.find("#wl-bulk-dp-date").val();
                var t = ($modal.find("#wl-bulk-dp-time").val() || "00:00").trim();
                if (!d) {
                    // Empty date = clear expiration (permanent)
                    val = "";
                } else {
                    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) {
                        $modal.find("#wl-bulk-dp-time").css("border-color", "#e74c3c");
                        return;
                    }
                    $modal.find("#wl-bulk-dp-time").css("border-color", "");
                    var tp = t.split(":");
                    var localDate = new Date(
                        parseInt(d.substr(0, 4), 10), parseInt(d.substr(5, 2), 10) - 1,
                        parseInt(d.substr(8, 2), 10), parseInt(tp[0], 10), parseInt(tp[1], 10)
                    );
                    val = formatUTCDateTime(localDate) + " UTC";
                }
            } else {
                val = $modal.find("#wl-bulk-val").val();
            }

            if (!col) { return; }

            syncInputs();

            // Count how many rows would actually change
            var selectedIdxs = Table.getSelectedIndices();
            var wouldChange = 0;
            selectedIdxs.forEach(function (idx) {
                if (currentRows[idx] && (currentRows[idx][col] || "") !== val) {
                    wouldChange++;
                }
            });

            if (wouldChange === 0) {
                $modal.remove();
                showMsg("No changes — all selected rows already have that value.", "info");
                return;
            }

            function applyBulkEditLocally() {
                var changedCount = 0;
                selectedIdxs.forEach(function (idx) {
                    if (currentRows[idx]) {
                        var oldVal = currentRows[idx][col] || "";
                        if (oldVal !== val) {
                            trackCellEdit(idx, col, oldVal, val);
                            currentRows[idx][col] = val;
                            changedCount++;
                        }
                    }
                });
                // Track that these edits came from Bulk Edit so the save flow
                // classifies them as bulk_row_edit (not inline row_edit)
                pendingBulkEditCount += changedCount;
                $modal.remove();
                refreshTable();
                showMsg("Bulk edit: set <strong>" + _.escape(col) + "</strong> to &ldquo;" +
                        _.escape(val) + "&rdquo; on " + changedCount + " row(s). " +
                        "Click <strong>Save Changes</strong> to persist.", "success");
            }

            // Check approval gate
            restPost({
                action: "check_approval_gate",
                gate_action: "bulk_row_edit",
                csv_file: selectedCsv,
                app_context: selectedApp,
                selected_count: wouldChange
            }).done(function (gateData) {
                if (gateData.requires_approval) {
                    $modal.remove();
                    showRemoveRowModal(
                        "Submit for Approval",
                        "Bulk editing <strong>" + wouldChange + "</strong> row(s) requires admin approval.<br>" +
                            "Reason: " + _.escape(gateData.reason) + "<br><br>" +
                            "Your request will be submitted for review.",
                        function (reason) {
                            submitBulkEditApproval(col, val, selectedIdxs.slice(), wouldChange, reason);
                        },
                        {
                            reasonLabel: "Reason for bulk edit",
                            placeholder: "Why are these rows being edited?",
                            confirmText: "Submit",
                            confirmClass: "btn-primary"
                        }
                    );
                } else if (gateData.daily_limit && !gateData.daily_limit.allowed) {
                    $modal.remove();
                    showMsg(formatDailyLimitMsg(gateData.daily_limit), "error"
                    );
                } else {
                    applyBulkEditLocally();
                }
            }).fail(function () {
                // Gate check failed — block edit (fail-closed for security)
                $modal.remove();
                showMsg("Unable to verify approval gate. Please try again.", "error");
            });
        });

        $modal.on("click", "#wl-bulk-cancel", function () { $modal.remove(); });
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { $modal.remove(); }
        });
        $modal.on("keydown", "#wl-bulk-val, #wl-bulk-dp-time", function (e) {
            if (e.which === 13) { e.preventDefault(); $modal.find("#wl-bulk-apply").trigger("click"); }
        });

        setTimeout(function () {
            var isExpires = (expireColumn && $modal.find("#wl-bulk-col").val() === expireColumn);
            if (isExpires) {
                $modal.find("#wl-bulk-dp-date").focus();
            } else {
                $modal.find("#wl-bulk-val").focus();
            }
        }, 100);
    }

    // ══════════════════════════════════════════════════════════════════
    // Export Audit Trail as CSV
    // ══════════════════════════════════════════════════════════════════

    function exportAuditCsv() {
        showMsg("Fetching audit data&hellip;", "info");

        // Mirror the Action Log panel query from audit.xml, filtered by current CSV/rule.
        // Escape SPL metacharacters to prevent search injection.
        function splEscape(val) {
            return val.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        }
        var filterParts = '';
        if (selectedCsv) filterParts += ' csv_file="' + splEscape(selectedCsv) + '"';
        if (selectedRule) filterParts += ' detection_rule="' + splEscape(selectedRule) + '"';
        var searchQuery = 'search index=wl_audit sourcetype=wl_audit' + filterParts + ' | head 10000' +
            ' | stats values(value{}) as value values(*) as * by action csv_file analyst timestamp' +
            ' | sort -timestamp' +
            ' | eval timestamp=strftime(timestamp, "%d-%m-%Y %H:%M:%S GMT%:::z")' +
            ' | eval action_label=case(' +
            '     action=="row_removed_multiple", "removed",' +
            '     action=="row_removed",          "removed",' +
            '     action=="auto_removed",         "auto removed",' +
            '     action=="row_edited",           "edited",' +
            '     action=="row_added",            "added",' +
            '     action=="revert",               "reverted",' +
            '     action=="column_removed",       "removed column",' +
            '     action=="column_added",         "added column",' +
            '     action=="row_reordered",        "reordered row",' +
            '     action=="column_reordered",     "reordered column",' +
            '     action=="column_renamed",       "renamed column",' +
            '     action=="audit_exported",       "exported audit",' +
            '     action=="csv_exported",         "exported CSV",' +
            '     action=="csv_imported",         "imported CSV"' +
            '   )' +
            ' | eval row_change_count=case(' +
            '     action=="row_removed_multiple", removed_row_count,' +
            '     action=="row_removed",          removed_row_count,' +
            '     action=="auto_removed",         removed_row_count,' +
            '     action=="row_edited",           edited_row_count,' +
            '     action=="row_added",            added_row_count,' +
            '     action=="row_reordered",        1' +
            '   )' +
            ' | eval column_change_count=case(' +
            '     action=="column_removed",       column_count,' +
            '     action=="column_added",         column_count,' +
            '     action=="column_reordered",     1,' +
            '     action=="column_renamed",       column_count' +
            '   )' +
            ' | eval col_names=mvjoin(\'columns{}\', ", ")' +
            ' | eval summary=case(' +
            '     action_label="reverted",' +
            '       "User ".analyst." ".action_label." ".csv_file." ".reverted_from_version." ".row_count_before." row(s) version to ".reverted_to_version." ".row_count_after." row(s) version (which became the latest in the record ".new_record_version.") at ".timestamp,' +
            '     action=="column_removed",' +
            '       "User ".analyst." ".action_label." ".col_names." from ".csv_file." (".column_change_count." column(s), detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="column_added",' +
            '       "User ".analyst." ".action_label." ".col_names." to ".csv_file." (".column_change_count." column(s), detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="row_reordered",' +
            '       "User ".analyst." ".action_label." in ".csv_file." from position #".row_number_before." to #".row_number_after." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="column_reordered",' +
            '       "User ".analyst." ".action_label." \'".column_name."\' in ".csv_file." from position #".column_number_before." to #".column_number_after." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="column_renamed",' +
            '       "User ".analyst." ".action_label." \'".column_renamed_before."\' to \'".column_renamed_after."\' in ".csv_file." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="audit_exported",' +
            '       "User ".analyst." ".if(status=="success","successfully","unsuccessfully")." exported ".export_file." audit file containing ".event_count." event(s) for ".csv_file." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="csv_exported",' +
            '       "User ".analyst." ".if(status=="success","successfully","unsuccessfully")." exported ".export_file." containing ".row_count." row(s) for ".csv_file." (detection rule - ".detection_rule.") at ".timestamp,' +
            '     action=="csv_imported",' +
            '       "User ".analyst." ".if(status=="success","successfully","unsuccessfully")." ".import_mode." ".export_file." into ".csv_file." (".imported_row_count." row(s), detection rule - ".detection_rule.") at ".timestamp,' +
            '     1==1,' +
            '       "User ".analyst." ".action_label." ".row_change_count." row(s) from ".csv_file." (detection rule - ".detection_rule.") at ".timestamp' +
            '   )' +
            ' | eval value=mvjoin(value, " | ")' +
            ' | table timestamp action analyst csv_file detection_rule comment row_remove_reason row_change_count column_change_count status export_file import_mode value summary';

        $.ajax({
            url: Splunk.util.make_url("/splunkd/__raw/services/search/jobs"),
            type: "POST",
            data: {
                search: searchQuery,
                output_mode: "json",
                exec_mode: "oneshot",
                count: 10000
            },
            dataType: "json"
        })
        .done(function (data) {
            var results = data.results || [];
            if (!results.length) {
                showMsg("No audit events found.", "info");
                return;
            }

            var headers = ["timestamp", "action", "analyst", "csv_file", "detection_rule",
                           "comment", "row_remove_reason", "row_change_count", "column_change_count",
                           "status", "export_file", "import_mode", "value", "summary"];
            var lines = [headers.map(csvEscape).join(",")];
            results.forEach(function (row) {
                var vals = headers.map(function (h) {
                    var v = row[h];
                    if (Array.isArray(v)) v = v.join(" | ");
                    return csvEscape(v || "");
                });
                lines.push(vals.join(","));
            });

            var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
            var link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            var exportName = "wl_audit_export_" +
                (selectedCsv ? selectedCsv.replace(/\.csv$/i, "") + "_" : "") +
                new Date().toISOString().slice(0, 10) + ".csv";
            link.download = exportName;
            link.click();
            URL.revokeObjectURL(link.href);

            showMsg("Exported <strong>" + results.length + "</strong> audit events" +
                (selectedCsv ? " for " + _.escape(selectedCsv) : "") + ".", "success");
            restPost({
                action: "log_event",
                event_action: "audit_exported",
                csv_file: selectedCsv || "",
                detection_rule: selectedRule || "",
                app_context: selectedApp,
                status: "success",
                export_file: link.download,
                event_count: results.length,
                comment: ""
            });
        })
        .fail(function () {
            showMsg("Failed to export audit data.", "error");
            restPost({
                action: "log_event",
                event_action: "audit_exported",
                csv_file: selectedCsv || "",
                detection_rule: selectedRule || "",
                app_context: selectedApp,
                status: "failure",
                export_file: "",
                event_count: 0,
                comment: "Search query failed"
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Real-time Collaboration Indicators (user presence)
    // ══════════════════════════════════════════════════════════════════

    var presenceTimer = null;
    var currentUser = "";
    var lastActivityTime = Date.now();
    var IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

    // Track user activity — any meaningful interaction resets the idle timer
    (function trackActivity() {
        var events = "click.wlactivity keydown.wlactivity input.wlactivity mousedown.wlactivity";
        $(document).off(events).on(events, function () {
            lastActivityTime = Date.now();
        });
    })();

    function getCurrentUser() {
        if (currentUser) { return; }
        try {
            // Splunk JS SDK provides the current user
            var currentUserModel = mvc.Components.getInstance("env");
            if (currentUserModel) {
                currentUser = currentUserModel.get("user") || "";
            }
        } catch (e) { /* ignore */ }

        // Fallback: extract from page
        if (!currentUser) {
            try {
                currentUser = $(".user-name").text().trim() || Splunk.util.getConfigValue("USERNAME") || "";
            } catch (e) { /* ignore */ }
        }
    }

    function startPresenceMonitoring() {
        stopPresenceMonitoring();
        if (!selectedCsv) { return; }
        getCurrentUser();
        reportPresence();
        presenceTimer = setInterval(reportPresence, 15000);
    }

    function stopPresenceMonitoring() {
        if (presenceTimer) { clearInterval(presenceTimer); presenceTimer = null; }
    }

    function reportPresence() {
        if (!selectedCsv || !currentUser) { return; }

        // Check if THIS user is idle — auto-kick locally
        var idleMs = Date.now() - lastActivityTime;
        if (idleMs >= IDLE_TIMEOUT_MS) {
            stopPresenceMonitoring();
            showPresenceFullModal(
                "You have been idle for 30 minutes and your session on this CSV has been released."
            );
            return;
        }

        restGet({
            action:        "report_presence",
            csv_file:      selectedCsv,
            app:           selectedApp || "",
            user:          currentUser,
            last_activity: Math.floor(lastActivityTime / 1000)
        })
        .done(function (data) {
            if (data.presence_full) {
                stopPresenceMonitoring();
                showPresenceFullModal(data.error || "Maximum number of simultaneous users reached for this CSV file.");
                return;
            }
            if (data.idle_kicked) {
                stopPresenceMonitoring();
                showPresenceFullModal(data.error || "You have been idle too long and your session was released.");
                return;
            }
            renderPresenceBar(data.active_users || []);
        })
        .fail(function (xhr) {
            if (xhr.status === 404) {
                handleCsvRemoved(selectedCsv);
                return;
            }
            try {
                var data = JSON.parse(xhr.responseText);
                if (data.presence_full) {
                    stopPresenceMonitoring();
                    showPresenceFullModal(data.error || "Maximum number of simultaneous users reached for this CSV file.");
                }
            } catch (e) { /* ignore */ }
        });
    }

    function showPresenceFullModal(message) {
        $(".wl-modal-overlay").remove();
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">CSV Busy</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0;color:#e74c3c">' + _.escape(message) + '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn btn-primary" id="wl-presence-full-ok">OK</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        function dismiss() {
            $modal.remove();
            $(document).off("keydown.wlpresence");
            // Reset to initial state
            $ruleClear.trigger("click");
        }
        $modal.on("click", "#wl-presence-full-ok", dismiss);
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { dismiss(); }
        });
        $(document).off("keydown.wlpresence").on("keydown.wlpresence", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) { dismiss(); }
        });
    }

    function handleCsvRemoved(csvName) {
        stopChangeMonitoring();
        stopPresenceMonitoring();
        $(".wl-modal-overlay").remove();
        var displayName = csvName || selectedCsv || "This CSV";
        var $modal = $(
            '<div class="wl-modal-overlay">' +
            '<div class="wl-modal">' +
                '<div class="wl-modal-header">CSV Removed</div>' +
                '<div class="wl-modal-body">' +
                    '<p style="margin:0">' +
                        '<strong>' + _.escape(displayName) + '</strong> has been removed ' +
                        'by an administrator and is no longer available.' +
                    '</p>' +
                    '<p style="margin:8px 0 0;font-size:13px;color:var(--wl-muted-text,#999)">' +
                        'If this was unexpected, contact your admin. ' +
                        'Removed files can be restored from the Trash in the Control Panel.' +
                    '</p>' +
                '</div>' +
                '<div class="wl-modal-actions">' +
                    '<span class="btn btn-primary" id="wl-csv-removed-ok">OK</span>' +
                '</div>' +
            '</div></div>'
        );
        $("body").append($modal);
        function dismiss() {
            $modal.remove();
            $(document).off("keydown.wlcsvremoved");
            $ruleClear.trigger("click");
        }
        $modal.on("click", "#wl-csv-removed-ok", dismiss);
        $modal.on("click", function (e) {
            if ($(e.target).hasClass("wl-modal-overlay")) { dismiss(); }
        });
        $(document).off("keydown.wlcsvremoved").on("keydown.wlcsvremoved", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) { dismiss(); }
        });
    }

    function renderPresenceBar(users) {
        var $bar = $table.find("#wl-presence-bar");
        if (!$bar.length) {
            $bar = $('<div id="wl-presence-bar" class="wl-presence-bar"></div>');
            $table.prepend($bar);
        }

        if (!users.length || (users.length === 1 && users[0] === currentUser)) {
            $bar.empty().removeClass("wl-presence-active");
            return;
        }

        var otherUsers = users.filter(function (u) { return u !== currentUser; });
        if (!otherUsers.length) {
            $bar.empty().removeClass("wl-presence-active");
            return;
        }

        var PRESENCE_SHOW_MAX = 5;
        var visible = otherUsers.slice(0, PRESENCE_SHOW_MAX);
        var hidden  = otherUsers.slice(PRESENCE_SHOW_MAX);

        var html = '<span style="margin-right:4px">Also viewing:</span>';
        visible.forEach(function (user) {
            html += '<span class="wl-presence-user">' +
                    '<span class="wl-presence-dot"></span>' +
                    _.escape(user) + '</span>';
        });
        if (hidden.length) {
            html += '<span class="wl-presence-toggle" ' +
                    'style="cursor:pointer;color:var(--wl-link,#5ba0d0);margin-left:4px;font-weight:600" ' +
                    'title="Click to show all">+' + hidden.length + ' more</span>';
            html += '<span class="wl-presence-hidden" style="display:none">';
            hidden.forEach(function (user) {
                html += '<span class="wl-presence-user">' +
                        '<span class="wl-presence-dot"></span>' +
                        _.escape(user) + '</span>';
            });
            html += '</span>';
        }
        $bar.html(html).addClass("wl-presence-active");
        $bar.find(".wl-presence-toggle").off("click").on("click", function () {
            var $hidden = $bar.find(".wl-presence-hidden");
            if ($hidden.is(":visible")) {
                $hidden.hide();
                $(this).text("+" + hidden.length + " more");
            } else {
                $hidden.show();
                $(this).text("show less");
            }
        });
    }

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
        showBulkEditModal();
    });

    // Bind Audit Export button
    $table.on("click.wl", "#btn-audit-export", function () {
        exportAuditCsv();
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

    // Start presence monitoring whenever CSV is loaded
    var origLoadCsv = loadCsv;
    loadCsv = function (csvFile, appContext) {
        origLoadCsv(csvFile, appContext);
        startPresenceMonitoring();
    };

    // Stop presence on page unload
    $(window).on("beforeunload", function () {
        stopChangeMonitoring();
        stopPresenceMonitoring();
    });

});
// build-526-ascii-validation-1775354643
// build-527-arraybuffer-1775355528
