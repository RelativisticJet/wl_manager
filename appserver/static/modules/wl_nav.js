/**
 * wl_nav.js — Detection Rule & CSV dropdown navigation
 *
 * Extracted from whitelist_manager.js (Wave 3, Task 8).
 *
 * Functions:
 *   loadRules, renderRuleList, filterRules, selectRule,
 *   renderCsvList, selectCsvItem, onCsvSelected, updateUrlParams
 *   + all dropdown event bindings
 */
define([
    "jquery",
    "underscore",
    "app/wl_manager/modules/wl_rest",
    "app/wl_manager/modules/wl_ui"
], function ($, _, REST, UI) {
    "use strict";

    var restGet  = REST.restGet;
    var showMsg  = UI.showMsg;
    var clearMsg = UI.clearMsg;

    // Module-private refs (set by init)
    var _state   = null;
    var _actions = null;
    var _dom     = null;

    // Permission state (set by loadRules from server response)
    var canCreateRules = false;
    var canCreateCsv   = false;
    var canDeleteRules = false;
    var canDeleteCsv   = false;

    var csvDisabled = true;

    var CREATE_RULE_SENTINEL = "__create_new_rule__";

    // ══════════════════════════════════════════════════════════════════
    // Load rules + mapping from REST
    // ══════════════════════════════════════════════════════════════════
    function loadRules() {
        restGet({ action: "get_mapping" })
        .done(function (data) {
            _state.mappingData = data.mapping || [];
            var perms = data.permissions || {};
            canCreateRules = !!perms.can_create_rules;
            canCreateCsv = !!perms.can_create_csv;
            canDeleteRules = !!perms.can_delete_rules;
            canDeleteCsv = !!perms.can_delete_csv;
            _state.reasonGates = perms.reason_gates || {};
            var ruleSet = {};
            _state.mappingData.forEach(function (m) {
                ruleSet[m.rule_name] = true;
            });
            (data.registered_rules || []).forEach(function (r) {
                ruleSet[r] = true;
            });
            _state.allRules = Object.keys(ruleSet).sort();
            renderRuleList(_state.allRules);
            renderEmptyInstallBanner();

            // Auto-select rule + CSV from URL params
            var urlParams = new URLSearchParams(window.location.search);
            var paramRule = urlParams.get("rule");
            var paramCsv = urlParams.get("csv");
            if (paramRule) {
                if (_state.allRules.indexOf(paramRule) === -1) {
                    _dom.$table.html(
                        '<div class="wl-alert wl-alert-warning">' +
                            '<strong>Detection rule "' + _.escape(paramRule) +
                            '" was not found.</strong>' +
                            '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                                'It may have been removed or the link may be outdated.' +
                            '</span>' +
                            '<br><button type="button" class="btn btn-primary" id="wl-go-home" ' +
                                'style="margin-top:8px">Back to Whitelist Manager</button>' +
                        '</div>'
                    );
                } else {
                    selectRule(paramRule, paramCsv || undefined);
                    if (paramCsv && _state.selectedCsv !== paramCsv) {
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

    // ══════════════════════════════════════════════════════════════════
    // Empty-install Getting Started banner
    //
    // Shown above the dropdowns toolbar when ALL of:
    //   1. _state.allRules is empty (mapping + registered_rules both empty)
    //   2. canCreateRules is true (admin-only; analysts can't act on the CTA)
    //   3. localStorage flag wl_empty_install_banner_dismissed != "1"
    // Called from loadRules(); idempotent (removes any prior instance first).
    // ══════════════════════════════════════════════════════════════════
    var EMPTY_BANNER_ID  = "wl-empty-install-banner";
    var EMPTY_BANNER_KEY = "wl_empty_install_banner_dismissed";

    function renderEmptyInstallBanner() {
        $("#" + EMPTY_BANNER_ID).remove();

        if (!_state || !_state.allRules || _state.allRules.length > 0) { return; }
        if (!canCreateRules) { return; }
        try {
            if (window.localStorage &&
                window.localStorage.getItem(EMPTY_BANNER_KEY) === "1") {
                return;
            }
        } catch (e) {
            // localStorage blocked (private-mode / strict CSP) — keep banner visible
        }

        var $dropdowns = $("#wl-dropdowns");
        if (!$dropdowns.length) { return; }

        var $banner = $(
            '<div id="' + EMPTY_BANNER_ID + '" class="wl-alert wl-alert-info wl-empty-install-banner" ' +
                 'role="region" aria-label="Getting started">' +
                '<strong>Welcome to Whitelist Manager.</strong> ' +
                'No detection rules are mapped yet. ' +
                '<button type="button" class="btn btn-primary wl-empty-install-cta">' +
                    '+ Create your first detection rule' +
                '</button> ' +
                '<a href="https://github.com/RelativisticJet/wl_manager#readme" ' +
                   'target="_blank" rel="noopener noreferrer" class="wl-empty-install-docs">' +
                    'Read the docs' +
                '</a>' +
                '<span class="wl-alert-close" role="button" tabindex="0" ' +
                      'aria-label="Dismiss welcome banner" title="Dismiss">×</span>' +
            '</div>'
        );

        $banner.on("click", ".wl-empty-install-cta", function () {
            if (!_actions || typeof _actions.showNewRuleModal !== "function") {
                return;
            }
            try {
                _actions.showNewRuleModal();
            } catch (e) {
                // Modal failed to open — keep banner visible so admin can
                // retry. Without this branch, both onboarding paths would
                // disappear silently.
                showMsg(
                    "Could not open the new-rule dialog. Reload the page to retry.",
                    "error"
                );
                return;
            }
            // Modal opened — remove banner for this session. Non-sticky
            // (no localStorage flag): if the modal is cancelled and state
            // is still empty, the banner reappears on the next page load.
            $banner.remove();
        });

        function dismiss() {
            try {
                if (window.localStorage) {
                    window.localStorage.setItem(EMPTY_BANNER_KEY, "1");
                }
            } catch (e) {
                // ignore — banner will re-appear on next load
            }
            $banner.remove();
        }

        $banner.on("click", ".wl-alert-close", dismiss);
        $banner.on("keydown", ".wl-alert-close", function (e) {
            if (e.key === "Enter" || e.key === " " || e.which === 13 || e.which === 32) {
                e.preventDefault();
                dismiss();
            }
        });

        $dropdowns.before($banner);
    }

    // ══════════════════════════════════════════════════════════════════
    // Rule dropdown rendering
    // ══════════════════════════════════════════════════════════════════
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
            _dom.$ruleList.html(
                createBtn +
                '<div class="wl-dropdown-no-match">No matching rules</div>'
            );
            return;
        }
        var html = createBtn;
        rules.forEach(function (rule) {
            var cls = "wl-dropdown-item";
            if (rule === _state.selectedRule) { cls += " wl-selected"; }
            var removeSpan = canDeleteRules
                ? '<span class="wl-dropdown-remove" data-rule="' +
                  _.escape(rule) + '">remove</span>'
                : '';
            html += '<div class="' + cls + '" data-value="' + _.escape(rule) + '">' +
                    '<span>' + _.escape(rule) + '</span>' + removeSpan + '</div>';
        });
        _dom.$ruleList.html(html);
    }

    function filterRules(query) {
        if (!query || !query.trim()) { return _state.allRules; }
        var q = query.trim().toLowerCase();
        return _state.allRules.filter(function (r) {
            return r.toLowerCase().indexOf(q) !== -1;
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Rule selection
    // ══════════════════════════════════════════════════════════════════
    function selectRule(rule, preferCsv) {
        if (!rule) { return; }
        _state.selectedRule = rule;
        _state.selectedCsv = "";
        _dom.$ruleSearch.val(rule);
        _dom.$ruleClear.show();
        renderRuleList(_state.allRules);
        _actions.clearUndo();
        _state.pendingApprovals = [];
        $("#wl-approval-actions").remove();
        updateUrlParams();

        var csvEntries = _state.mappingData.filter(function (m) {
            return m.rule_name === rule;
        });

        csvDisabled = false;
        _dom.$csvDisplay.removeClass("wl-disabled");

        if (!csvEntries.length) {
            _dom.$csvDisplay.text("No CSV files for this rule").addClass("wl-disabled");
            csvDisabled = true;
            _state.selectedCsv = "";
            _state.selectedApp = "";
            _actions.stopChangeMonitoring();
            _state.loadedMtime = null;
            _state.loadedContentHash = null;
            _state.loadedPendingCount = 0;
            _dom.$searchGroup.hide();
            _actions.hideVersions();
            var noCsvHtml = '<div class="wl-alert wl-alert-warning">' +
                '<strong>No whitelisting exists for this detection rule.</strong>';
            if (canCreateCsv) {
                noCsvHtml +=
                    '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                        'Would you like to create a new CSV whitelist?' +
                    '</span>' +
                    '<br><button type="button" class="btn btn-primary" id="wl-create-csv-btn" ' +
                        'style="margin-top:8px">Create CSV</button>';
            } else {
                noCsvHtml +=
                    '<br><span style="font-size:13px;margin-top:4px;display:inline-block">' +
                        'Contact an administrator to create a CSV whitelist for this rule.' +
                    '</span>';
            }
            noCsvHtml += '</div>';
            _dom.$table.html(noCsvHtml);
            _dom.$diff.empty();
            return;
        }

        // Store entries for click handler
        _dom.$csvList.data("entries", csvEntries);
        renderCsvList(csvEntries);

        var target = preferCsv || csvEntries[0].csv_file;
        selectCsvItem(target, csvEntries);
    }

    // ══════════════════════════════════════════════════════════════════
    // CSV dropdown rendering
    // ══════════════════════════════════════════════════════════════════
    function renderCsvList(entries) {
        var html = "";
        if (canCreateCsv) {
            html += '<div class="wl-dropdown-item wl-dropdown-create-csv" ' +
                    'style="border-bottom:1px solid var(--wl-border);' +
                    'font-style:italic;color:var(--wl-link)">+ Create new CSV</div>';
        }
        entries.forEach(function (entry) {
            var cls = "wl-dropdown-item";
            if (entry.csv_file === _state.selectedCsv) { cls += " wl-selected"; }
            var removeSpan = canDeleteCsv
                ? '<span class="wl-dropdown-remove wl-csv-remove" ' +
                  'data-csv="' + _.escape(entry.csv_file) + '" ' +
                  'data-rule="' + _.escape(entry.rule_name || _state.selectedRule) +
                  '">remove</span>'
                : '';
            html += '<div class="' + cls + ' wl-csv-item" ' +
                    'data-csv="' + _.escape(entry.csv_file) + '" ' +
                    'data-app="' + _.escape(entry.app_context || "") + '">' +
                    '<span>' + _.escape(entry.csv_file) + '</span>' +
                    removeSpan + '</div>';
        });
        _dom.$csvList.html(html);
    }

    function selectCsvItem(csvFile, entries) {
        if (!entries) { entries = _dom.$csvList.data("entries") || []; }
        var entry = null;
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].csv_file === csvFile) { entry = entries[i]; break; }
        }
        if (!entry) { return; }
        _dom.$csvDisplay.text(entry.csv_file);
        _dom.$csvList.removeClass("wl-open");
        onCsvSelected(entry.csv_file, entry.app_context || "");
    }

    function onCsvSelected(csvFile, appCtx) {
        _actions.stopChangeMonitoring();
        _state.loadedMtime = null;
        _state.loadedContentHash = null;
        _state.loadedPendingCount = 0;
        _state.selectedCsv = csvFile || "";
        _state.selectedApp = appCtx || "";
        _actions.clearUndo();
        updateUrlParams();
        // Update selected highlight in dropdown
        _dom.$csvList.find(".wl-csv-item").removeClass("wl-selected");
        _dom.$csvList.find(".wl-csv-item").filter(function () {
            return $(this).data("csv") === _state.selectedCsv;
        }).addClass("wl-selected");
        if (_state.selectedCsv) {
            _actions.loadCsv(_state.selectedCsv, _state.selectedApp);
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // URL param sync
    // ══════════════════════════════════════════════════════════════════
    function updateUrlParams() {
        var params = new URLSearchParams(window.location.search);
        if (_state.selectedRule) { params.set("rule", _state.selectedRule); } else { params.delete("rule"); }
        if (_state.selectedCsv) { params.set("csv", _state.selectedCsv); } else { params.delete("csv"); }
        var newUrl = window.location.pathname;
        var qs = params.toString();
        if (qs) { newUrl += "?" + qs; }
        window.history.replaceState(null, "", newUrl);
    }

    // ══════════════════════════════════════════════════════════════════
    // Full selection reset (used by onEntityRemoved, Presence dismiss)
    // ══════════════════════════════════════════════════════════════════
    function clearSelection() {
        _dom.$ruleClear.trigger("click");
    }

    function clearCsvSelection() {
        _state.selectedCsv = "";
        _state.selectedApp = "";
        _actions.stopChangeMonitoring();
        _dom.$searchGroup.hide();
        _actions.hideVersions();
        _dom.$table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
        _dom.$diff.empty();
    }

    // ══════════════════════════════════════════════════════════════════
    // Event bindings (called once during init)
    // ══════════════════════════════════════════════════════════════════
    function _bindEvents() {
        var $ruleSearch = _dom.$ruleSearch;
        var $ruleList   = _dom.$ruleList;
        var $ruleClear  = _dom.$ruleClear;
        var $csvDisplay = _dom.$csvDisplay;
        var $csvList    = _dom.$csvList;

        // Rule search focus — open dropdown
        $ruleSearch.on("focus", function () {
            $ruleList.addClass("wl-open");
            renderRuleList(filterRules($ruleSearch.val()));
        });

        // Rule search input — filter
        $ruleSearch.on("input", function () {
            var filtered = filterRules($(this).val());
            renderRuleList(filtered);
            $ruleList.addClass("wl-open");
        });

        // Rule search Enter — select or create
        $ruleSearch.on("keydown", function (e) {
            if (e.which === 13) {
                e.preventDefault();
                var typed = $(this).val().trim();
                if (!typed) { return; }
                var exactMatch = _state.allRules.filter(function (r) {
                    return r.toLowerCase() === typed.toLowerCase();
                });
                if (exactMatch.length) {
                    selectRule(exactMatch[0]);
                } else if (canCreateRules) {
                    selectRule(typed);
                } else {
                    showMsg("Creating new detection rules is restricted to admins.", "error");
                }
                $ruleList.removeClass("wl-open");
            }
        });

        // Close rule dropdown on outside click
        $(document).on("click", function (e) {
            if (!$(e.target).closest("#rule-select").length) {
                $ruleList.removeClass("wl-open");
            }
        });

        // Rule item "remove" click
        $ruleList.on("click", ".wl-dropdown-remove", function (e) {
            e.stopPropagation();
            var rule = $(this).data("rule");
            $ruleList.removeClass("wl-open");
            if (rule) { _actions.showRemoveModal("rule", rule); }
        });

        // Rule item click
        $ruleList.on("click", ".wl-dropdown-item", function () {
            var rule = $(this).data("value");
            $ruleList.removeClass("wl-open");
            if (rule === CREATE_RULE_SENTINEL) {
                _actions.showNewRuleModal();
                return;
            }
            selectRule(rule);
        });

        // Rule clear button
        $ruleClear.on("click", function () {
            _state.selectedRule = "";
            _state.selectedCsv = "";
            _state.selectedApp = "";
            $ruleSearch.val("");
            $ruleClear.hide();
            renderRuleList(_state.allRules);
            $ruleList.removeClass("wl-open");
            csvDisabled = true;
            $csvDisplay.text("-- Select a Detection Rule first --").addClass("wl-disabled");
            $csvList.empty().removeClass("wl-open");
            updateUrlParams();
            _actions.stopChangeMonitoring();
            _state.loadedMtime = null;
            _state.loadedContentHash = null;
            _state.loadedPendingCount = 0;
            _dom.$searchGroup.hide();
            _actions.hideVersions();
            _actions.clearUndo();
            _state.pendingApprovals = [];
            $("#wl-approval-actions").remove();
            _dom.$table.html('<p class="wl-muted">Select a detection rule and CSV file above.</p>');
            _dom.$diff.empty();
            clearMsg();
        });

        // CSV dropdown open/close
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
            _actions.showCreateCsvModal(_state.selectedRule);
        });

        // CSV "remove" click
        $csvList.on("click", ".wl-csv-remove", function (e) {
            e.stopPropagation();
            var csv = $(this).data("csv");
            var rule = $(this).data("rule") || _state.selectedRule;
            $csvList.removeClass("wl-open");
            if (csv) { _actions.showRemoveModal("csv", csv, rule); }
        });

        // "Create CSV" button inside table area (for unmapped rules)
        _dom.$table.on("click", "#wl-create-csv-btn", function () {
            if (!_state.selectedRule) { return; }
            _actions.showCreateCsvModal(_state.selectedRule);
        });

        // "Back to Whitelist Manager" button on invalid URL param error
        _dom.$table.on("click", "#wl-go-home", function () {
            window.location.href = window.location.pathname;
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // Public API
    // ══════════════════════════════════════════════════════════════════
    return {
        init: function (opts) {
            _state   = opts.state;
            _actions = opts.actions;
            _dom     = opts.dom;
            _bindEvents();
        },
        loadRules:         loadRules,
        selectRule:        selectRule,
        renderRuleList:    renderRuleList,
        renderCsvList:     renderCsvList,
        updateUrlParams:   updateUrlParams,
        clearSelection:    clearSelection,
        clearCsvSelection: clearCsvSelection,
        /** Expose for Modals onEntityRemoved / onCsvCreated callbacks */
        getPermissions: function () {
            return {
                canCreateRules: canCreateRules,
                canCreateCsv:   canCreateCsv,
                canDeleteRules: canDeleteRules,
                canDeleteCsv:   canDeleteCsv
            };
        },
        setCsvDisabled: function (v) { csvDisabled = v; }
    };
});
