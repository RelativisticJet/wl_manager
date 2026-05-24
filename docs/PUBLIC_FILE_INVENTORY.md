# Public File Inventory

**Date:** 2026-05-18
**Commit at audit time:** `e6ccbae` (HEAD of `main`)
**Tracked files swept:** 374 (`git ls-files | wc -l`)
**Audit role:** Per-file checklist for the GitHub public-release flip. Companion to the higher-level [`PRE_PUBLIC_AUDIT.md`](PRE_PUBLIC_AUDIT.md). For every tracked file/directory, this doc says (a) what it is, (b) whether it should be in the public release, (c) whether it's current, and (d) any caveat.

---

## Reading the columns

- **Public?** — **Yes** = belongs in the public GitHub repo. **Ship** = also ships in the `.spl` payload installed on customer Splunks. **Repo-only** = public on GitHub but excluded from the customer `.spl`. **No** = should not be in the repo (any open finding here is a leak to be fixed).
- **Up-to-date?** — **Yes** = current state matches code/decisions. **Stale-OK** = historical record that is intentionally frozen. **Needs-update** = drift exists and should be fixed.

The packaging rule for what reaches a customer's `.spl` is in [`scripts/package.sh`](../scripts/package.sh) (EXCLUDES list at lines ~120-165 — every "Repo-only" classification in this doc maps to an entry in that list).

---

## Top-level files (21 tracked)

| File | Purpose | Public? | Up-to-date? | Notes |
|---|---|---|---|---|
| `.appinspect_api.expect.yaml` | Pinned expectations for the AppInspect API workflow — declares the version of the AppInspect ruleset we built against (`4.2.0`) so any drift in the upstream is caught in CI. Read by `.github/workflows/appinspect-api.yml` at runtime. | Repo-only | Yes | Phase 1.5 artifact. |
| `.gitignore` | Standard ignore list. Excludes build artifacts, secrets, IDE files, runtime state (`lookups/_*.json`, `_versions/`), local Splunk `local/` overrides, screenshot/debug debris from tests, the `.firecrawl/` directory removed in F-C1, `.planning/` post-F-M6 untrack, etc. | Repo-only | Yes | Audit V2 closure added `tests/e2e_phase*.png` + `screenshot_debug.png` + `.planning/`. |
| `.gitleaks.toml` | Configuration for `gitleaks` (secret scanner). Allowlists the documented `Chang3d!` dev-container password + SimpleXML dashboard tokens so the CI gate doesn't refire on those. Read by `.github/workflows/secret-scan.yml`. | Repo-only | Yes | Established in Phase 0.10 (one-shot historical scan baseline). |
| `.mcp.json.example` | Template for a per-developer `.mcp.json` (Claude Code MCP server config) so contributors can wire up the local Splunk MCP without me leaking my own machine paths. The actual `.mcp.json` is `.gitignored`. | Repo-only | Stale-OK | F-L3 noted Windows-only paths in the example; deferred to v1.1 per user decision. |
| `ARCHITECTURE.md` | Customer/contributor doc explaining how the app is structured: REST handler, frontend AMD modules, audit pipeline, FIM dual-store, RBAC tiers, version control system. The entry point for "how does this work." | Ship | Yes | Follows the doc-drift rules (`scripts/pre-commit-doc-drift.sh` enforces). |
| `CHANGELOG.md` | Per-build chronological record of every shipped change, signed-off-by user. Each entry maps a `default/app.conf` build number to the user-visible change. | Ship | Yes | Build entries verified by doc-drift hook. |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1 (per `docs/PUBLIC_RELEASE_PLAN.md` §2.5). Standard text. | Repo-only | Yes | Required for OSS posture. |
| `CONTRIBUTING.md` | Contributor guide — branch model, commit conventions, test requirements, response SLA expectations. | Repo-only | Yes | Phase 2.4 task closed. |
| `INSTALLATION.md` | Customer-facing install + first-run guide. Splunk admins read this to deploy the app. | Ship | Yes | Drift-checked. |
| `LICENSE` | Apache 2.0 license text. Required by Apache 2.0 §4(a) — must ship with every distribution. | Ship | Yes | D5 locked the license choice. |
| `Makefile` | Developer convenience targets (`make doc-check`, `make metrics`, etc.). Not part of the runtime app. | Repo-only | Yes | Excluded from `.spl` via `scripts/package.sh:133`. |
| `NOTICE` | Required companion to `LICENSE` per Apache 2.0 §4(d). Names the project and copyright holder. | Ship | Yes | Matches `LICENSE` and D5. |
| `README.md` | Repository landing page. First file most viewers see. Drives the rest of the doc tree. | Ship | Yes | Drift-checked. |
| `SECURITY.md` | Vulnerability disclosure policy (per `docs/PUBLIC_RELEASE_PLAN.md` §2.3). Points reporters at GitHub Security Advisories. | Ship | Yes | D-pending decision on dedicated email vs GHSA-only — currently GHSA-only. |
| `app.manifest` | Splunkbase metadata: name, version, license, author, supported Splunk versions, intended audience. Splunkbase reads this during ingestion. | Ship | Yes | F-M3 closure set author = "Oleh Bezsonov" + D15 email. **F-M4 deferred:** `releaseDate` field updates at Phase 3.2 rc1 cut. |
| `docker-compose.yml` | Local dev container definition (Splunk 9.3.1). Not part of the customer install — they bring their own Splunk. | Repo-only | Yes | Excluded from `.spl`. |
| `mkdocs.yml` | MkDocs site config for `docs/`. Used by `.github/workflows/docs.yml` to publish the GitHub Pages docs site. Not part of the runtime app. | Repo-only | Yes | **F-M1 closure** added it to `scripts/package.sh` EXCLUDES. |
| `package-lock.json` | npm lockfile for the small JS tooling tree (eslint, prettier, etc.). | Repo-only | Yes | Excluded from `.spl:136`. |
| `package.json` | npm manifest declaring the JS tooling tree (markdownlint, etc.). | Repo-only | Yes | Excluded from `.spl:135`. |
| `requirements-dev.txt` | Python test/lint dependencies (pytest, freezegun, hypothesis, splunk-appinspect, etc.). | Repo-only | Yes | Excluded from `.spl:139`. |
| `sbom.cdx.json` | CycloneDX 1.5 Software Bill of Materials. Customers and Splunkbase reviewers use this to inventory the app's components for vulnerability tracking. | Ship | Yes | **F-M2 closure** synced to v1.0.0-rc1 / build 660. Currently a manual baseline (`tools.name = "manual-baseline"`); `scripts/generate_sbom.py` can rebuild from a packaged `.spl` at rc1 cut time. |

---

## `.github/` — community & CI/CD config (23 tracked)

This whole tree is GitHub-platform metadata, never inside the `.spl`.

| File | Purpose | Public? | Up-to-date? | Notes |
|---|---|---|---|---|
| `.github/FUNDING.yml` | Stub for GitHub Sponsors / Ko-fi / etc. badges in the repo sidebar. All platforms commented out — no Sponsor button renders today. | Repo-only | Yes | Trivial to uncomment if the maintainer ever onboards a platform. |
| `.github/dependabot.yml` | Dependabot config — auto-PRs for outdated Python deps + GitHub Actions versions. | Repo-only | Yes | |
| `.github/ISSUE_TEMPLATE/bug_report.md` | Bug-report issue template. | Repo-only | Yes | |
| `.github/ISSUE_TEMPLATE/feature_request.md` | Feature-request template. | Repo-only | Yes | |
| `.github/ISSUE_TEMPLATE/question.md` | Question / discussion template (points users to Discussions). | Repo-only | Yes | |
| `.github/ISSUE_TEMPLATE/config.yml` | Disables blank-issue creation; points users at the three templates above. | Repo-only | Yes | |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR template (summary / test plan / checklist). | Repo-only | Yes | |
| `.github/workflows/a11y-audit.yml` | Axe-core accessibility scan against `tests/a11y/baseline.json`. | Repo-only | Yes | Ring 4 Day 6 infrastructure. |
| `.github/workflows/appinspect-api.yml` | Uploads built `.spl` to the AppInspect HTTP API, blocks on errors. | Repo-only | Yes | Phase 1.5. |
| `.github/workflows/appinspect.yml` | Local-CLI AppInspect run + Phase 1.3 baseline diff. Writes JSON to `.planning/appinspect/` (scratch path; see Phase G F-M6 note in `PRE_PUBLIC_AUDIT.md`). | Repo-only | Yes | Pins `splunk-appinspect==4.2.0` (matches `.appinspect_api.expect.yaml`). |
| `.github/workflows/ci.yml` | The main CI pipeline — runs unit tests against the mocked-Splunk stubs (~600 tests, ~12s). | Repo-only | Yes | |
| `.github/workflows/codeql.yml` | GitHub CodeQL SAST scan (Python + JS). | Repo-only | Yes | |
| `.github/workflows/docs.yml` | Builds + deploys the MkDocs site to GitHub Pages (`https://relativisticjet.github.io/wl_manager/` per D16). | Repo-only | Yes | |
| `.github/workflows/e2e-smoke.yml` | Smoke E2E subset (~5 min) on every PR. | Repo-only | Yes | Two-workflow E2E pattern per D-2026-05-11. |
| `.github/workflows/e2e-full.yml` | Nightly full E2E suite + `workflow_dispatch`. | Repo-only | Yes | Companion to e2e-smoke. |
| `.github/workflows/integration-tests.yml` | `pytest tests/integration/` against a real Splunk 9.3.1 container. Runs the F-C3 chaos test that prompted this audit. | Repo-only | Yes | |
| `.github/workflows/pip-audit.yml` | `pip-audit` against `requirements-dev.txt` — surfaces CVEs in test/lint deps. | Repo-only | Yes | |
| `.github/workflows/release.yml` | Cuts a signed release: builds `.spl`, signs via Sigstore (keyless OIDC), uploads to GitHub Releases + Rekor transparency log. | Repo-only | Yes | Round 8 hardening artifact. E2E verification at Phase 3.8. |
| `.github/workflows/scorecard.yml` | OpenSSF Scorecard supply-chain hygiene scan. | Repo-only | Yes | |
| `.github/workflows/secret-scan.yml` | `gitleaks` on push + PR + weekly + manual dispatch. Reads `.gitleaks.toml`. | Repo-only | Yes | Phase 0.10 artifact. |
| `.github/workflows/semgrep.yml` | Splunk-adapted Semgrep ruleset (under `tests/semgrep/`). | Repo-only | Yes | |
| `.github/workflows/validate-and-package.yml` | `scripts/validate.sh` + `scripts/package.sh` — builds the `.spl` and confirms it loads in a clean Splunk. The pre-flight before any release. | Repo-only | Yes | |
| `.github/workflows/zap-baseline.yml` | OWASP ZAP baseline scan against the running dev container. Reads `.zap/rules.tsv` for customizations. | Repo-only | Yes | |

---

## `.claude/` and `.zap/` — local tooling (2 tracked)

| File | Purpose | Public? | Up-to-date? | Notes |
|---|---|---|---|---|
| `.claude/qa-failure-modes.md` | Project-specific QA pattern library that the Second-pass review SubAgent applies on top of the global library. Append-only history of catchable mistakes (e.g., Splunk cache claims without bust). | Repo-only | Yes | The rest of `.claude/` is gitignored per `.gitignore:2-5` exception. |
| `.zap/rules.tsv` | ZAP baseline-scan rule customizations (allow/deny entries for known-benign Splunk responses). | Repo-only | Yes | |

---

## `bin/` — Splunk REST handler backend (24 tracked, **all ship**)

All Python modules implementing the `/custom/wl_manager` REST endpoint and its scheduled scripted inputs. Every module gets installed on the customer's Splunk.

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `bin/wl_handler.py` | The main `splunk.rest.BaseRestHandler` subclass. Dispatch table for all GET/POST actions. The single entry point for every request. | Ship | Yes |
| `bin/wl_constants.py` | Project-wide constants (MAX_VERSIONS, LOCKDOWN_EXEMPT_ACTIONS, etc.). | Ship | Yes |
| `bin/wl_rbac.py` | Role tier resolution (`is_superadmin`, `is_admin`, `is_editor`, `is_viewer`) — single source of truth for RBAC gates. | Ship | Yes |
| `bin/wl_csv.py` | CSV read/write/diff. The similarity-based diff engine that detects edit-vs-removal correctly. | Ship | Yes |
| `bin/wl_audit.py` | Audit-event emission to `index=wl_audit` via Splunk REST. | Ship | Yes |
| `bin/wl_approval.py` | Approval-queue management — submit, approve, reject, list. | Ship | Yes |
| `bin/wl_replay.py` | Replays an approved request — re-executes the action the admin signed off on. | Ship | Yes |
| `bin/wl_rules.py` | Detection-rule CRUD (`create_rule`, `delete_rule`) + mapping management. | Ship | Yes |
| `bin/wl_versions.py` | Version-snapshot lifecycle: snapshot on save, retain last 6, revert flow. | Ship | Yes |
| `bin/wl_trash.py` | Soft-delete / restore for rules and CSVs (`_trash/`). | Ship | Yes |
| `bin/wl_limits.py` | Per-analyst + per-admin daily-action limits with configurable reset schedules. | Ship | Yes |
| `bin/wl_ratelimit.py` | Cross-process rate-limit counters in the `wl_cooldowns` KV collection. | Ship | Yes |
| `bin/wl_filelock.py` | Cross-platform file locking for concurrent-write safety on shared lookups. | Ship | Yes |
| `bin/wl_hmac_key.py` | Derives a runtime HMAC key from the Splunk server GUID with a 1-hour cache TTL (D-2026-04-12 decision). | Ship | Yes |
| `bin/wl_fim.py` | Baseline FIM (scheduled scripted input, 15s) on app code + config + sentinel files. Dual-store baseline (file + KV). | Ship | Yes |
| `bin/wl_fim_watch.py` | Stat-based persistent CSV watcher (`interval=0`) for ~2s detection of `outputlookup` bypasses. | Ship | Yes |
| `bin/wl_fim_common.py` | Shared helpers between `wl_fim.py` and `wl_fim_watch.py`. | Ship | Yes |
| `bin/wl_notify.py` | Notification bell — produces per-admin notifications for queue events, lockdown activations, FIM alerts. | Ship | Yes |
| `bin/wl_presence.py` | Tracks which user is currently editing which CSV (5-minute window). Drives the UI-watch insider-threat badge. | Ship | Yes |
| `bin/wl_validation.py` | Input validation (strict ASCII on rule/csv names, payload schema). | Ship | Yes |
| `bin/wl_logging.py` | Centralized logger config — log level + format. | Ship | Yes |
| `bin/wl_expiring_soon.py` | Powers the "Expiring Soon" dashboard panel via `savedsearches.conf`. | Ship | Yes |
| `bin/wl_expiration_cleanup.py` | Scheduled job (`inputs.conf`) that auto-removes expired rows. | Ship | Yes |
| `bin/wl_migrate_cooldowns.py` | One-shot migration tool for the `wl_cooldowns` KV schema. Not invoked at runtime — run by an admin when upgrading. | Ship | Yes |

---

## `appserver/` — frontend (27 tracked)

The `static/` tree holds JS/CSS the dashboards load. The `static/modules/` subtree is the AMD module set the entry point loads via RequireJS.

### Entry-point JS + dashboard scripts (ship)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `appserver/static/whitelist_manager.js` | Main Whitelist Manager dashboard entry point. Loads the 13 modules under `modules/` and wires up the UI. Thin entry after the Wave 3 modularization. | Ship | Yes |
| `appserver/static/control_panel.js` | Control Panel dashboard entry point (Approval Queue / Activity / Settings / Trash tabs). | Ship | Yes |
| `appserver/static/audit_trail.js` | Audit Trail dashboard — counter panels, activity log, recovery panel. | Ship | Yes |
| `appserver/static/audit_tz.js` | Timezone toggle for the audit dashboard (browser-local vs UTC). | Ship | Yes |
| `appserver/static/notifications.js` | The notification bell + dropdown. Loaded on every dashboard. | Ship | Yes |
| `appserver/static/application.js` | Splunk-app-wide JS — runs on every view. Hides the Control Panel nav link for non-admins. | Ship | Yes |
| `appserver/static/application.css` | Splunk-app-wide CSS — the `wl-cp-hidden` rule that `application.js` toggles. | Ship | Yes |
| `appserver/static/whitelist_manager.css` | Project-wide styles (modal overlays, table, buttons, dark theme tokens). Used by every dashboard. | Ship | Yes |

### AMD modules under `appserver/static/modules/` (13, all ship)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `modules/wl_constants.js` | Frontend constants (MAX rows, debounce ms, etc.). | Ship | Yes |
| `modules/wl_rest.js` | REST helpers (`restGet`, `restPost`) — every call to the backend goes through here. | Ship | Yes |
| `modules/wl_ui.js` | Shared UI primitives — message banners, loading spinners, theme detection. | Ship | Yes |
| `modules/wl_table.js` | The editable table widget. Inline editing, row selection, search, column reorder. | Ship | Yes |
| `modules/wl_modals.js` | Generic modal stack + entity-CRUD modals (create rule, create CSV, etc.). | Ship | Yes |
| `modules/wl_csv_io.js` | CSV import/export, schema validation, merge/replace approval. | Ship | Yes |
| `modules/wl_versions.js` | Version dropdown + revert modal. | Ship | Yes |
| `modules/wl_diff.js` | Git-style diff display in the approval modal. | Ship | Yes |
| `modules/wl_datepicker.js` | Date-picker widget for the `Expires` column. | Ship | Yes |
| `modules/wl_presence.js` | Reports the current user's presence + reads other users' presence for UI-watch badges. | Ship | Yes |
| `modules/wl_approval_ui.js` | Approval-highlight UI on the table + submit-for-approval flow. | Ship | Yes |
| `modules/wl_save.js` | The save pipeline — collect changes, build payload, POST, handle gate. | Ship | Yes |
| `modules/wl_nav.js` | Detection-rule + CSV dropdown logic. | Ship | Yes |

### Test/debug artifacts under `appserver/static/` (now excluded from `.spl`)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `appserver/static/test_runner.xml` | Orphan duplicate of the QUnit test runner. References a no-longer-existing `wl_state.js`. Useful only for local dev. | Repo-only | Stale-OK |
| `appserver/static/tests/test_wl_cp_admin_limits.js` | QUnit suite for Control Panel admin-limit logic. | Repo-only | Yes |
| `appserver/static/tests/test_wl_cp_limits.js` | QUnit suite for analyst-limit logic. | Repo-only | Yes |
| `appserver/static/tests/test_wl_cp_queue.js` | QUnit suite for the Approval Queue tab. | Repo-only | Yes |
| `appserver/static/tests/test_wl_cp_trash.js` | QUnit suite for the Trash tab. | Repo-only | Yes |
| `appserver/static/tests/test_wl_cp_usage.js` | QUnit suite for the Activity (usage) tab. | Repo-only | Yes |

> **F-L4/F-L5 closure** added `appserver/static/test_runner.xml` and `appserver/static/tests/` to `scripts/package.sh:158-160` EXCLUDES, so customers don't see these.

---

## `default/` — Splunk app configuration (16 tracked, **all ship**)

Every file here is read by Splunk at app load to set up endpoints, indexes, role ACLs, scheduled jobs, etc.

### `.conf` files (12)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `default/app.conf` | App metadata: id, version, build, author, description. Read by Splunkbase and by `scripts/pre-commit-doc-drift.sh`. | Ship | Yes |
| `default/authorize.conf` | Custom RBAC roles: `wl_superadmin`, `wl_admin`, `wl_analyst_editor`, `wl_analyst_viewer`. | Ship | Yes |
| `default/restmap.conf` | Maps `/custom/wl_manager` to the Python handler. Pins `python.version=python3` and `python.required=3.13` (AppInspect requirement). | Ship | Yes |
| `default/web.conf` | Exposes the REST endpoint over Splunk Web. | Ship | Yes |
| `default/indexes.conf` | Defines the `wl_audit` index (audit-event home). | Ship | Yes |
| `default/inputs.conf` | Scripted-input registrations for `wl_fim.py`, `wl_fim_watch.py`, `wl_expiration_cleanup.py`. | Ship | Yes |
| `default/collections.conf` | KV-store collections (`wl_cooldowns`, `wl_fim_baseline`, `wl_presence`, etc.). | Ship | Yes |
| `default/commands.conf` | Splunk custom-command registrations (currently none beyond required stubs). | Ship | Yes |
| `default/transforms.conf` | Registers `rule_csv_map.csv` as a Splunk lookup. | Ship | Yes |
| `default/props.conf` | Field-extraction config for the `wl_audit` sourcetype + `wl_fim` events. | Ship | Yes |
| `default/savedsearches.conf` | The 4 scheduled searches that surface FIM/laundering/lockdown alerts. Includes inline `AppInspect note` justifications for above-threshold cron schedules. | Ship | Yes |

### Dashboards `default/data/ui/` (5)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `default/data/ui/nav/default.xml` | The nav menu: Whitelist Manager / Audit Trail / Control Panel. `test_runner` is intentionally NOT in the nav. | Ship | Yes |
| `default/data/ui/views/whitelist_manager.xml` | The main dashboard SimpleXML. Loads `whitelist_manager.js`+`notifications.js`. | Ship | Yes |
| `default/data/ui/views/audit.xml` | The Audit Trail dashboard SimpleXML (1098 LOC of counter + table panels). | Ship | Yes |
| `default/data/ui/views/control_panel.xml` | Control Panel dashboard shell. | Ship | Yes |
| `default/data/ui/views/test_runner.xml` | QUnit test runner dashboard. URL-reachable at `/app/wl_manager/test_runner` if shipped — **excluded from `.spl` per F-L4 closure** (`scripts/package.sh:158`). | Repo-only | Yes |

---

## `metadata/` — Splunk RBAC ACLs (1)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `metadata/default.meta` | Per-object access controls — which roles can read/write each saved search, dashboard, etc. | Ship | Yes |

---

## `lookups/` — Splunk lookup files (4 tracked)

The `lookups/DR*.csv` files are demo data, also used as test fixtures. `rule_csv_map.csv` is the master rule→csv mapping. Both are tracked, but the demo CSVs are **excluded from the customer `.spl`** (`scripts/package.sh:146`) and `rule_csv_map.csv` is swapped to a header-only version before packaging (`scripts/package.sh:103`).

The set was trimmed from 19 demo CSVs to 3 on 2026-05-18 — the dropped 16 only existed as test fixtures; nothing customer-visible changed (the .spl already excluded all `DR*.csv`).

| File | Purpose | Public? | Up-to-date? | Notes |
|---|---|---|---|---|
| `lookups/rule_csv_map.csv` | Master mapping: detection_rule → csv_file → app_context. 3 mapping rows (DR55 pair + DR130). | Repo-only (header-only in `.spl`) | Yes | Trimmed from 19 rows on 2026-05-18. |
| `lookups/DR55_brute_force_src.csv` | Demo: source-IP whitelist for brute-force rule. Simple 3-column schema (`src_ip,src_host,Comment`). | Repo-only | Yes | |
| `lookups/DR55_brute_force_users.csv` | Demo: user whitelist for brute-force rule. 7-column schema with `Expires` + audit-trail columns. | Repo-only | Yes | |
| `lookups/DR130_priv_escalation.csv` | Demo: priv-escalation user whitelist. 10-column rich schema (the rule shown in `docs/screenshots/02-inline-editing.png`). | Repo-only | Yes | |

> **Why ship a header-only `rule_csv_map.csv` and no `DR*.csv` at all to customers?** Customers should populate their own detection rules, not inherit our demo set. The .spl ships the mechanism (handler, dashboards, RBAC, alerts), not pre-loaded content.

---

## `bench_results/` — performance baselines (1)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `bench_results/.gitkeep` | Empty placeholder so the directory is checked into git even though real bench results (`*.json` files) are gitignored. Lets `scripts/bench.py` write into a tracked directory shape. | Repo-only | Yes |

---

## `demo/` — demo script + guide (3)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `demo/Demo_Guide.pdf` | The customer-walkthrough deck (built from `generate_demo_guide.py`). 8 pages, screenshots, scenario walkthroughs. | Repo-only | Yes |
| `demo/demo.sh` | One-shot seed script: stands up the container, creates demo users with `Chang3d!`, seeds the demo CSVs. The "live demo" surface a new contributor runs. | Repo-only | Yes |
| `demo/generate_demo_guide.py` | The script that rebuilds `Demo_Guide.pdf` from a template — keeps the PDF reproducible. | Repo-only | Yes |

---

## `docs/` — public docs site (29 tracked)

Everything here is built into the MkDocs site at `https://relativisticjet.github.io/wl_manager/` (per D16) and is also a tracked Markdown set the doc-drift hook polices.

### Customer-facing reference

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `docs/index.md` | MkDocs landing page. | Repo-only | Yes |
| `docs/Whitelist_Manager_Documentation.md` | Long-form product doc. Behavior, role tiers, workflows. | Repo-only | Yes |
| `docs/Splunk_Admin_Installation_Guide.md` | Admin-targeted install guide (complements the root `INSTALLATION.md`). | Repo-only | Yes |
| `docs/example_spl_queries.md` | SPL recipes for common audit-trail reporting questions. | Repo-only | Yes |
| `docs/api/README.md` | REST API reference overview. | Repo-only | Yes |
| `docs/api/openapi.yaml` | OpenAPI 3 spec for the REST handler. | Repo-only | Yes |

### Operational + architectural

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `docs/RUNBOOKS.md` | Operational procedures: emergency unlock, cooldown reset, DR restore, deploy windows. The on-call surface. | Repo-only | Yes |
| `docs/BACKUP_AND_RESTORE.md` | Backup target locations + restore steps. | Repo-only | Yes |
| `docs/SECURITY_ARCHITECTURE.md` | Architecture-level security model — RBAC tiers, HMAC, FIM dual-store, deploy windows. | Repo-only | Yes |
| `docs/SPLUNK_QUIRKS.md` | Splunk-specific gotchas we've collected (cache layers, SimpleXML stripping, etc.). | Repo-only | Yes |
| `docs/BACKWARD_COMPAT.md` | Compatibility matrix across Splunk versions + upgrade notes. | Repo-only | Yes |
| `docs/AUDIT_VOLUME_FORECAST.md` | Per-action audit-event volume estimates for capacity planning. | Repo-only | Yes |

### Audit + decision records (frozen-history)

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `docs/DECISION_LOG.md` | Locked decisions D1-D18+. The reason-why archive. | Repo-only | Yes |
| `docs/PUBLIC_RELEASE_PLAN.md` | The phase 0-4 release plan. | Repo-only | Yes |
| `docs/PRE_PUBLIC_AUDIT.md` | The Audit V1 + V2 record (this audit's parent doc). | Repo-only | Yes |
| `docs/RELEASE_CHECKLIST.md` | Phase 3 release-cut checklist. | Repo-only | Yes |
| `docs/APPINSPECT_FINDINGS.md` | Phase 1.3 baseline + ongoing AppInspect triage. | Repo-only | Yes |
| `docs/APPINSPECT_NOTES.md` | Companion notes for individual AppInspect findings. | Repo-only | Yes |
| `docs/HTML_INJECTION_AUDIT.md` | Round-X XSS audit findings. | Repo-only | Stale-OK |
| `docs/PIP_AUDIT_LOG.md` | Quarterly pip-audit triage log. | Repo-only | Yes |
| `docs/RING_FINDINGS.md` | Findings from the post-modularization hardening rings (R1-R6+). | Repo-only | Stale-OK |
| `docs/RING1_INPUT_handler_contracts.md` | Ring-1 input-handler contract baseline (frozen historical reference). | Repo-only | Stale-OK |
| `docs/SBOM.md` | SBOM explainer — what `sbom.cdx.json` covers and why. | Repo-only | Yes |
| `docs/TESTING.md` | Test taxonomy + how to run each suite locally. | Repo-only | Yes |
| `docs/TESTING_PROGRESS_2026-04-15.md` | Frozen mid-rings progress snapshot. The doc-drift hook intentionally skips dated snapshots. | Repo-only | Stale-OK |

### Screenshots

**Active set (build 669, captured 2026-05-24)** — referenced by
`README.md`, `docs/SPLUNKBASE_LISTING_DRAFT.md`, and
`docs/SPLUNKBASE_LAUNCH_KIT.md`:

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `docs/screenshots/01-whitelist-manager-dashboard.png` | Splash on docs site + repo README. | Repo-only | Yes (build 669, 2026-05-24) |
| `docs/screenshots/02-control-panel-approval-queue.png` | Admin Approval Queue tab. | Repo-only | Yes (build 669, 2026-05-24) |
| `docs/screenshots/03-audit-trail-dashboard.png` | Audit Trail dashboard. | Repo-only | Yes (build 669, 2026-05-24) |
| `docs/screenshots/04-inline-csv-editing.png` | DR130 inline CSV editing view. | Repo-only | Yes (build 669, 2026-05-24) |
| `docs/screenshots/05-control-panel-activity.png` | Per-analyst usage counters + tier-aware caps. | Repo-only | Yes (build 669, 2026-05-24) |

**Historical set (build ~640, captured 2026-05-06)** — retained as
audit evidence for `docs/PRE_PUBLIC_AUDIT.md` §Phase F (F-L11
visual-review log). No longer referenced by user-facing docs:

| File | Original purpose | Status |
|---|---|---|
| `docs/screenshots/01-main-dashboard.png` | README splash (build ~640). | Superseded by `01-whitelist-manager-dashboard.png`; retained for PRE_PUBLIC_AUDIT F-L11 grounding. |
| `docs/screenshots/02-inline-editing.png` | DR130 editing view (build ~640). | Superseded by `04-inline-csv-editing.png`; retained for PRE_PUBLIC_AUDIT F-L11 grounding. |
| `docs/screenshots/03-audit-trail.png` | Audit Trail (build ~640). | Superseded by `03-audit-trail-dashboard.png`; retained for PRE_PUBLIC_AUDIT F-L11 grounding. |
| `docs/screenshots/04-control-panel.png` | Control Panel Approval Queue (build ~640). | Superseded by `02-control-panel-approval-queue.png`; retained for PRE_PUBLIC_AUDIT F-L11 grounding. |

---

## `scripts/` — packaging, CI, dev tools (19 tracked)

All scripts here are **repo-only** — they don't run on the customer's Splunk.

| File | Purpose | Public? | Up-to-date? |
|---|---|---|---|
| `scripts/package.sh` | Builds the `.spl` payload. Trims `lookups/`, excludes `mkdocs.yml`/`tests/`/`docs/`/`.firecrawl/` per the rules above. The single source of truth for what reaches customers. | Repo-only | Yes |
| `scripts/validate.sh` | Pre-package validation: AppInspect dry-run, JSON schema, etc. | Repo-only | Yes |
| `scripts/verify_appinspect.sh` | Wrapper around the AppInspect CLI for local re-runs that match the CI workflow. | Repo-only | Yes |
| `scripts/generate_sbom.py` | Rebuilds `sbom.cdx.json` from a built `.spl`. Run at rc1 cut time. | Repo-only | Yes |
| `scripts/pre-commit` | Wrapper that calls `pre-commit-doc-drift.sh` + future hooks. Symlinked from `.git/hooks/pre-commit`. | Repo-only | Yes |
| `scripts/pre-commit-doc-drift.sh` | Drift guard for the tracked doc set — path-existence + build-number checks. | Repo-only | Yes |
| `scripts/test_integration.sh` | Local runner for `tests/integration/` against the dev container. | Repo-only | Yes |
| `scripts/test_backup_restore.sh` | Smoke test for the backup/restore runbook. | Repo-only | Yes |
<!-- The previous upgrade-test script (under scripts/) was removed 2026-05-18 — targeted a stale v2.0->v3.0 path and would have destroyed the live dev container. A fresh upgrade test will be written when v1.0.0 GA is cut. -->

| `scripts/emergency_unlock.sh` | Out-of-band recovery: clears the emergency-lockdown sentinel. | Repo-only | Yes |
| `scripts/reset_cooldowns.sh` | Out-of-band recovery: clears the `wl_cooldowns` KV record after tamper detection or GUID rotation. | Repo-only | Yes |
| `scripts/fim_deploy_window.sh` | Operator helper to open/close a FIM deploy window without using the REST API. | Repo-only | Yes |
| `scripts/backup_data.sh` | Snapshots lookups + versions to a tarball under `backups/` (gitignored). | Repo-only | Yes |
| `scripts/bench.py` | Performance benchmarks (concurrency, memory) — writes to `bench_results/` (gitignored). | Repo-only | Yes |
| `scripts/metrics_collector.py` | Repo metrics (line counts, test coverage) for `make metrics`. | Repo-only | Yes |
| `scripts/mutmut.sh` | Mutation-testing harness (Ring 3). | Repo-only | Yes |
| `scripts/seed-demo-state.py` | Programmatic seed of the demo state (alternative to `demo/demo.sh`). | Repo-only | Yes |
| `scripts/hooks/README.md` | Documentation for the Claude Code PreToolUse hook (`block-synthetic-fixtures.js`). | Repo-only | Yes (F-L9 closure replaced maintainer path with placeholder) |
| `scripts/hooks/block-synthetic-fixtures.js` | The synthetic-fixture-blocker hook itself. Per-developer wiring; not part of the runtime app. | Repo-only | Yes |

---

## `tests/` — test suite (188 tracked, **all repo-only**)

The entire `tests/` tree is excluded from the `.spl` payload (`scripts/package.sh` excludes `test_*.py` at root and the whole `tests/` directory). Listed by subdirectory:

| Subdirectory | Files | Purpose | Public? | Up-to-date? |
|---|---|---|---|---|
| `tests/` (root-level Python tests) | 35 | Cross-suite Python tests (unit + light integration), the manual E2E scripts (`test_e2e_realworld.py`, `test_e2e_manual_browser.py`), and shared utilities (`conftest.py`, `pytest.ini`, `__init__.py`). | Repo-only | Yes (F-M5 closure made the manual scripts portable) |
| `tests/unit/` | 27 | Pure-helper unit tests against mocked Splunk stubs. Fastest tier — runs on every PR via `ci.yml`. | Repo-only | Yes |
| `tests/integration/` | 33 | Live-Splunk integration tests via Docker. Run via `integration-tests.yml`. Includes the F-C3 chaos test. | Repo-only | Yes |
| `tests/e2e/` | 52 | Playwright `.cjs` E2E tests + visual baselines under `visual_baselines/`. Run via `e2e-smoke.yml` (PR subset) and `e2e-full.yml` (nightly full). | Repo-only | Yes |
| `tests/qunit/` | 11 | QUnit suites for frontend modules (loaded by the test_runner dashboard locally). | Repo-only | Yes |
| `tests/security/` | 10 | Security-focused tests: HMAC integrity, role-bypass attempts, etc. | Repo-only | Yes |
| `tests/js/` | 6 | Headless-Node JS unit tests (not browser-loaded). | Repo-only | Yes |
| `tests/stubs/` | 5 | Mocked `splunk.*` stubs so unit tests don't need a real Splunk. | Repo-only | Yes |
| `tests/semgrep/` | 5 | Project-specific Semgrep rules (e.g., "no synthetic fixtures in feature verification"). Loaded by `semgrep.yml`. | Repo-only | Yes |
| `tests/fixtures/` | 4 | Shared fixture files (CSV samples, payloads). | Repo-only | Yes |
| `tests/a11y/` | 4 | Axe-core baseline + Playwright harness. Read by `a11y-audit.yml`. | Repo-only | Yes |
| `tests/MANUAL_TEST_PLAN.md` | 1 (root) | Human-driven QA checklist for things that don't automate well. | Repo-only | Yes |
| `tests/generate_test_plan.py` | 1 (root) | Generates the test-plan doc from per-suite metadata. | Repo-only | Yes |

---

## Things NOT in the public release (verified absent)

The Audit V2 walk explicitly checked that these are absent from tracking. Listed for the record:

| Pattern | Status | Reason |
|---|---|---|
| `.firecrawl/` | Gitignored + history-rewritten | F-C1 (personal job-research scrapes). Resolved 2026-05-18. |
| `lookups/DR777_*.csv` / `DR778_*.csv` / `DR998_*.csv` | Gitignored | Demo/test rule prefixes (`.gitignore:32-35`). |
| `lookups/_*.json` | Gitignored | Runtime state (approval queue, daily limits, notifications). |
| `lookups/_versions/` | Gitignored | Per-CSV snapshot history — runtime state, can grow unbounded. |
| `lookups/_trash/` | Gitignored | Soft-delete recycle bin. F-C2 (2026-05-18) added this — was previously tracked by mistake. |
| `local/` and `metadata/local.meta` | Gitignored | Per-install overrides. Customer-private. |
| `CLAUDE.md` | Gitignored | Maintainer's personal Claude Code overlay. Tracked equivalents live at `docs/DECISION_LOG.md`, `docs/RUNBOOKS.md`, `docs/SPLUNK_QUIRKS.md`. |
| `.mcp.json` | Gitignored | Per-developer Claude Code MCP config. Template at `.mcp.json.example`. |
| `.planning/` | Gitignored (F-M6 closure 2026-05-18) | GSD-style internal phase plans. Was tracked with 170 maintainer-local paths; untracked but preserved on disk. |
| `.audit/` | Gitignored | One-shot Semgrep-rule pulls + scan output for triage rounds. |
| `.playwright-mcp/` | Gitignored | Per-session Playwright MCP scratch (snapshots, console logs). |
| `.superpowers/` | Gitignored | Superpowers framework local state. |
| `.graphifyignore` + `graphify-out/` | Gitignored | Local-only audit tooling output. |
| `bench_results/*.json` | Gitignored | Per-run perf data. Only the `.gitkeep` placeholder is tracked. |
| `tests/zap-reports/` | Gitignored | Local ZAP HTML/JSON dumps. CI uploads its own report artifacts. |
| `tests/a11y/reports/` | Gitignored | Per-page raw axe reports (the `baseline.json` contract IS tracked). |
| `tests/e2e/visual_artifacts/` | Gitignored | Per-run visual diff diagnostics. Baselines at `tests/e2e/visual_baselines/` ARE tracked. |
| `tests/e2e_phase*.png` plus a `screenshot_debug.png` pattern | Gitignored (F-L8 closure 2026-05-18) | Output artifacts of `test_e2e_realworld.py`. Were 6 stale tracked PNGs; now ignored. |
| `mempalace.yaml`, `entities.json` | Gitignored | MemPalace per-project state. |
| `.env`, `.env.*` | Gitignored | Secrets — never committed. |
| `*.spl`, `*.tar.gz` | Gitignored | Built distribution artifacts. CI builds them on demand. |
| `*.pyc`, `__pycache__/`, `.pytest_cache/`, `.coverage`, `htmlcov/` | Gitignored | Python build/test debris. |
| `.mutmut-cache` | Gitignored | Local mutation-testing cache. |
| `node_modules/` | Gitignored | npm dependency tree. |

---

## Open release-blockers

After Audit V2 Phase G batch (HEAD `e6ccbae`) the only remaining V2 finding is:

- **F-M4 (LOW)** — `app.manifest:releaseDate` predates the actual release. Explicitly deferred to Phase 3.2 rc1 cut, where `build` + `version` + `releaseDate` all bump together.

All other V2 findings (F-C3, F-H2, F-M1, F-M2, F-M3, F-M5, F-M6, F-L4, F-L5, F-L6, F-L7, F-L8, F-L9, F-L10, F-L11) are closed. The Phase 3.4 (private→public) flip is unblocked.

---

## Revision log

| Date | Auditor | Notes |
|---|---|---|
| 2026-05-18 | claude-opus-4-7 (per-file inventory pass) | Initial publication. 374 tracked files classified across 13 top-level paths. Coordinated with Audit V2 closure in [`PRE_PUBLIC_AUDIT.md`](PRE_PUBLIC_AUDIT.md). |
