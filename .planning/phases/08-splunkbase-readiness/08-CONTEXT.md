# Phase 8: Splunkbase Readiness - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate production readiness, achieve AppInspect compliance (including cloud tag set), publish comprehensive documentation, verify backward compatibility with a full upgrade path test, and report code quality metrics for Splunkbase publication as version 1.0.0. No new features -- this phase validates and documents the v3.0 modular rewrite.

</domain>

<decisions>
## Implementation Decisions

### AppInspect Strategy
- **Run method**: CLI local first (splunk-appinspect installed locally), cloud API submission deferred to manual publication step
- **Tag sets**: Run both standard AND cloud tag sets -- target Splunk Cloud compatibility
- **Warning handling**: Fix all fixable warnings; document remaining unfixable ones (known false positives) in APPINSPECT_NOTES.md with justifications
- **validate.sh**: Extend with checks discovered from AppInspect findings -- acts as fast pre-flight gate for future changes
- **Makefile target**: Add `make appinspect` that runs package.sh, validate.sh, splunk-appinspect inspect. One-command validation
- **Python compliance**: Full compliance -- no bare except, no dangerous dynamic execution, proper imports, Splunk SDK patterns. Verify all 14 modules use wl_logging.py consistently (no print() or direct logging.getLogger())
- **JS security audit**: Scan all 15+ JS files for AppInspect-flagged patterns (dangerous dynamic code execution, innerHTML assignments, unsafe DOM writes, inline event handlers). Fix any found
- **Conf file audit**: Systematically validate all 8+ .conf files (app.conf, restmap.conf, authorize.conf, indexes.conf, savedsearches.conf, commands.conf, props.conf, transforms.conf, web.conf) against Splunk spec files
- **Custom commands**: Verify commands.conf entries for wl_expiration_cleanup.py and wl_expiring_soon.py match actual scripts and follow AppInspect patterns
- **Metadata audit**: Verify default.meta exports views, lookups, saved searches correctly; ensure RBAC roles from authorize.conf are properly referenced
- **web.conf**: Audit for proper static file serving config, endpoint exposure, deprecated directives
- **Python 3 scan**: Quick grep for Python 2 remnants (print without parens, old-style exceptions, legacy string methods)
- **Cloud compatibility**: Target cloud tag set. If audit writing via localhost:8089 (urllib in wl_audit.py) is flagged, refactor to use Splunk SDK service.indexes API -- only change what is actually flagged
- **Packaging cleanup**: Define explicit exclude patterns in package.sh -- no tests/, __pycache__, .planning/, docker-compose.yml, Makefile, scripts/, htmlcov/, dev artifacts
- **app.manifest**: Fill with real details -- RelativisticJet identity, actual release date, MIT license (matching LICENSE file). User will confirm values
- **About dashboard**: Create about.xml dashboard with app version, description, links to documentation, support info

### Documentation Scope
- **Security architecture doc**: Two-audience document -- executive summary for Splunk admins (what data the app accesses/writes, RBAC matrix, audit completeness) + detailed threat model appendix for security reviewers (STRIDE/DREAD, trust boundaries, attack surface)
- **Location**: docs/SECURITY_ARCHITECTURE.md in .spl package + summary in existing SECURITY.md with link to full doc
- **Diagrams**: Mermaid syntax embedded in Markdown -- data flow, RBAC permission matrix, audit event flow
- **Mitigated threats**: Include past vulnerabilities found during development (optimistic locking bypass, client trust bypass, reserved prefix bypass, RBAC bypass) as "identified and mitigated threats" with evidence of fixes
- **OpenAPI spec**: Manual YAML (OpenAPI 3.0), hand-written in docs/api/openapi.yaml. All REST actions (get_csv, save_csv, get_mapping, get_versions, revert_csv, etc.), parameters, response shapes, error codes, with full example request/response bodies per action
- **Existing docs audit**: Review and update all 3 existing docs (Splunk_Admin_Installation_Guide.md, Whitelist_Manager_Documentation.md, example_spl_queries.md) for accuracy after v3.0 rewrite
- **README overhaul**: Rewrite for Splunkbase audience -- feature highlights, screenshots, installation steps, requirements (Splunk version, RBAC setup), links to detailed docs. Professional, user-facing tone
- **Screenshots**: Capture fresh set from Docker container -- main CSV editor, audit dashboard, control panel, dark/light theme, approval workflow. Reference from README
- **CHANGELOG**: Update with comprehensive v3.0 entry covering all 8 phases of the rewrite
- **Docs in .spl**: Include all documentation in the .spl package

### Backward Compat Verification
- **Audit events**: Both static analysis (review every SPL query in audit.xml for field name correctness) AND runtime golden event testing (inject representative pre-rewrite audit events into wl_audit index, run audit.xml searches, verify parsing)
- **Version manifests**: Claude's discretion on approach -- check how much format changed and choose fixture-based or live container test accordingly
- **Approval queue**: Fixture-based test -- create pre-rewrite approval queue entries, feed through v3.0 wl_approval.py, verify load/approve/reject/audit
- **Full upgrade path test**: Script end-to-end in Docker: install v2.0, create CSVs, audit events, approval queue entries, version snapshots, upgrade to v3.0 .spl, verify all data accessible and functional
- **Conf merging**: Verify after upgrade that all conf files reflect v3.0 values -- no stale v2.0 stanzas bleeding through (restmap.conf, authorize.conf, savedsearches.conf)
- **Formal report**: Create docs/BACKWARD_COMPAT.md with matrix: data type x test method x result

### Metrics and Packaging
- **Collection**: Automated Python script -- radon for cyclomatic complexity, coverage for test coverage, custom line counter for function sizes. JS metrics via eslint/escomplex or equivalent
- **Scope**: Both Python (14 modules) and JavaScript (15+ AMD modules) -- CC scores, function sizes, module sizes, test coverage
- **Quality gate**: Script enforces thresholds from PUBL-05 (CC >15 = fail, coverage <80% = fail, function >100 lines = fail). Non-zero exit code on failure
- **Report location**: Generate to docs/CODE_METRICS.md + copy to root CODE_METRICS.md for GitHub visibility
- **Version**: Ship as 1.0.0 (first Splunkbase publication). app.manifest and app.conf both set to 1.0.0. Build number continues incrementing
- **package.sh enhancement**: (1) Exclude dev files, (2) run validate.sh as pre-flight, (3) verify app.manifest version matches app.conf, (4) produce SHA256 checksum

### Claude's Discretion
- Version manifest backward compat test approach (fixture vs live container)
- Exact AppInspect warning remediation order
- Screenshots composition and framing
- JS complexity tool selection (eslint complexity rules vs escomplex vs custom)
- Mermaid diagram layout and level of detail
- OpenAPI spec organization (single file vs split by action group)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### AppInspect targets
- `default/app.conf` -- App metadata, version, build number (must match app.manifest)
- `default/restmap.conf` -- REST handler mapping (AppInspect validates schema)
- `default/authorize.conf` -- RBAC roles: wl_editor, wl_viewer (metadata audit target)
- `default/indexes.conf` -- wl_audit index definition
- `default/commands.conf` -- Custom command definitions for wl_expiration_cleanup.py, wl_expiring_soon.py
- `default/savedsearches.conf` -- Scheduled searches (AppInspect validates)
- `default/props.conf` -- Source type config (TRUNCATE setting)
- `default/transforms.conf` -- Lookup definitions
- `default/web.conf` -- Static file serving, endpoint config
- `metadata/` -- default.meta permissions and exports
- `app.manifest` -- Splunkbase manifest (null fields need filling)
- `scripts/validate.sh` -- Existing pre-flight checks (extend with AppInspect findings)
- `scripts/package.sh` -- .spl packaging script (enhance with exclusions + validation)
- `Makefile` -- Build targets (add appinspect and metrics targets)

### Backend modules (Python compliance audit targets)
- `bin/wl_handler.py` -- REST router
- `bin/wl_audit.py` -- Audit logging (cloud compat: localhost:8089 urllib usage may need refactoring)
- `bin/wl_logging.py` -- Logging wrapper (verify all modules use this)
- `bin/wl_constants.py`, `bin/wl_csv.py`, `bin/wl_versions.py`, `bin/wl_approval.py`, `bin/wl_rbac.py`, `bin/wl_limits.py`, `bin/wl_trash.py`, `bin/wl_rules.py`, `bin/wl_presence.py`, `bin/wl_validation.py`, `bin/wl_filelock.py`, `bin/wl_notify.py`, `bin/wl_ratelimit.py`, `bin/wl_replay.py`
- `bin/wl_expiration_cleanup.py`, `bin/wl_expiring_soon.py` -- Custom search commands

### Frontend modules (JS security audit targets)
- `appserver/static/whitelist_manager.js` -- Main entry point
- `appserver/static/control_panel.js` -- Admin panel entry point
- `appserver/static/notifications.js` -- Notification system
- `appserver/static/modules/*.js` -- All 11 feature modules + 5 admin panel modules

### Existing documentation (audit + update targets)
- `docs/Splunk_Admin_Installation_Guide.md` -- Admin install guide (may reference old architecture)
- `docs/Whitelist_Manager_Documentation.md` -- User documentation
- `docs/example_spl_queries.md` -- SPL query examples
- `SECURITY.md` -- Security overview (add link to full architecture doc)
- `CONTRIBUTING.md` -- Contribution guide
- `README.md` -- Project README (overhaul for Splunkbase)
- `CHANGELOG.md` -- Change history (update with v3.0 entry)
- `LICENSE` -- MIT license

### Backward compatibility targets
- `default/data/ui/views/audit.xml` -- Audit dashboard (SPL queries to audit against)
- `lookups/_versions/` -- Version manifest JSON files
- `bin/wl_approval.py` -- Approval queue JSON format
- `bin/wl_audit.py` -- Audit event field structure

### Prior phase context
- `.planning/phases/07-test-coverage-validation/07-CONTEXT.md` -- Test infrastructure, coverage reports feed PUBL-05
- `.planning/REQUIREMENTS.md` -- PUBL-01 through PUBL-05 requirement definitions
- `.planning/ROADMAP.md` section "Phase 8" -- Success criteria
- `CODE_QUALITY_AUDIT.md` -- Initial code quality findings (43 findings, baseline for metrics comparison)

### Bug pattern memory (mitigated threats for security doc)
- `~/.claude/projects/c--Users-PC-wl-manager/memory/MEMORY.md` -- Documented vulnerabilities: optimistic locking bypass, client trust bypass, reserved prefix convention, RBAC bypass, set-vs-counter, syncInputs contract

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **validate.sh**: Pre-flight validation script already mirrors many AppInspect checks -- extend rather than replace
- **package.sh**: .spl builder with version extraction -- enhance with exclusions and pre-flight gate
- **app.manifest**: Exists with correct schema, needs null fields populated
- **Makefile**: Exists -- add appinspect and metrics targets
- **htmlcov/**: Coverage HTML reports from Phase 7 pytest runs -- feed into metrics script
- **CODE_QUALITY_AUDIT.md**: Baseline quality findings (43 issues) -- comparison point for v3.0 metrics
- **docs/**: 3 existing documentation files + screenshots directory -- update rather than rewrite from scratch
- **SECURITY.md, CONTRIBUTING.md, LICENSE**: Existing project files -- verify accuracy for Splunkbase

### Established Patterns
- **Module structure**: 14 Python modules in bin/, 15+ JS AMD modules in appserver/static/modules/ -- metrics script must enumerate all
- **wl_logging.py**: Centralized logging wrapper -- all modules should use this exclusively
- **REST dispatch**: GET_ACTIONS/POST_ACTIONS dicts in wl_handler.py -- OpenAPI spec maps directly to these
- **Audit event structure**: Documented in CLAUDE.md -- source for security architecture doc
- **RBAC roles**: 4-tier (viewer, editor, admin, superadmin) defined in authorize.conf + wl_rbac.py -- source for RBAC matrix

### Integration Points
- **Docker container**: wl_manager_test -- target for upgrade path test, screenshot capture, golden event injection
- **dist/**: Output directory for .spl packages -- package.sh already writes here
- **git history**: v2.0 code available via git for building pre-rewrite .spl for upgrade test
- **Splunk AppInspect CLI**: External tool, installed via pip (splunk-appinspect)
- **radon**: Python complexity analyzer, installed via pip
- **eslint/escomplex**: JS complexity tools (Claude's discretion on specific tool)

</code_context>

<specifics>
## Specific Ideas

- Run AppInspect cloud tag set to catch Splunk Cloud incompatibilities early -- the localhost:8089 urllib usage in wl_audit.py is the most likely flag
- The upgrade path test (v2.0 to v3.0) is the strongest backward compatibility evidence -- build v2.0 .spl from pre-rewrite git commit, install in fresh Docker, populate data, then upgrade
- MEMORY.md documented vulnerabilities (optimistic locking bypass, client trust bypass, reserved prefix, RBAC bypass) become "identified and mitigated threats" in the security architecture doc -- shows security maturity
- Phase 7 test matrix document serves dual purpose: test coverage evidence AND AppInspect documentation
- Quality gate script with enforced thresholds becomes a CI-ready artifact for future maintenance
- Version 1.0.0 for first Splunkbase publication -- clean start for public versioning even though internal was v2.0/v3.0

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 08-splunkbase-readiness*
*Context gathered: 2026-04-02*
