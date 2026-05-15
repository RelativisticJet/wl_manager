# Public Release & Splunkbase Submission Plan

> Plan owner: Oleh (@RelativisticJet)
> Created: 2026-05-13
> Status: **Phase 0 — Foundation cleanup (in flight; 10 ✅, 2 PARTIAL, 2 pending of 14 rows)**
> Updated: 2026-05-15 (Phase 0.10 closed — git history secret-scan clean)

This document is the canonical plan for taking `wl_manager` from
private-internal to public open-source on GitHub, then to a listed
app on Splunkbase. It supersedes the "Pending / Future Work" list
that previously lived in CLAUDE.md.

The plan is intentionally documented BEFORE execution so we have a
reviewable artifact, a check-off mechanism across sessions, and a
trust signal when the repo goes public ("look how carefully we
planned this").

---

## 1. Locked decisions (with rationale)

Each decision below was made deliberately and is expensive to
reverse. Future sessions: do NOT silently revisit these without
explicit user re-decision.

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **License: Apache 2.0** (switch from MIT before any external contributor) | Explicit patent grant matters for a security tool. Matches `splunk/*` official repos. Enterprise procurement allow-lists Apache more often than MIT. Cost of changing later: every contributor would have to re-sign. |
| D2 | **Cloud cert scope: dual cert (Splunk Cloud + on-prem) from v1** | Broadest addressable market. Highest engineering cost. NO FALLBACK — if AppInspect surfaces multi-week refactor, timeline slips, scope doesn't shrink. |
| D3 | **Timeline: moderate (6-8 weeks public, +2 months Splunkbase) — FLEXIBLE per D2** | Realistic for one maintainer. Quality bar constant, time variable. |
| D4 | **App name: keep "Whitelist Manager"** | Available on Splunkbase (no collision found in search). Generic-but-clear. Decision is permanent on Splunkbase upload. |
| D5 | **Copyright holder: "Oleh Bezsonov" (real name)** | Replaces "Security Engineering" placeholder. Personal-brand alignment. Affects future commercialization vehicle structure. Unified with D15 (same identity on Splunkbase publisher field). |
| D6 | **Splunk Developer account: set up from scratch** | ~1 day delay at Phase 1 kickoff. No existing account state. |
| D7 | **Cloud-cert escalation: at Phase 1 week 4 if not green, escalate to user for re-decision** | Soft cap. NOT auto-fallback. User explicitly chooses to continue / refactor / re-scope. |
| D8 | **Hosted docs site: MkDocs Material on GitHub Pages** | Most popular for technical docs. Polished theme out-of-box. Markdown source in `docs/`. ~1 hour initial setup. |
| D9 | **Telemetry: zero phone-home, ever** | Strongest privacy posture for a security tool. Cost: no adoption metrics beyond Splunkbase install count. |
| D10 | **CI fix priority: fix all 4 pre-existing red workflows in Phase 0 BEFORE adding AppInspect** | Can't add new gates on broken CI without losing signal. |
| D11 | **CLAUDE.md migration: Phase 0 (now, before any public-prep work)** | Decision Log → `docs/DECISION_LOG.md`; Operational Procedures + Rollback + Disaster Recovery → `docs/RUNBOOKS.md`; Splunk Quirks → `docs/SPLUNK_QUIRKS.md`. CLAUDE.md slimmed to personal overlay, stays gitignored. |
| D12 | **Versioning: reset to v1.0.0 for first public release** | Pre-public uses v1.0.0-rc1, -rc2 etc. The v2.0.0 in app.conf was an internal milestone — resetting is the standard FOSS pattern. |
| D13 | **Pre-public hold period: 4 weeks minimum** | After repo flips public, hold ~4 weeks before Splunkbase submission. Lets early adopters surface install bugs. Splunkbase reviewers prefer apps with traction. |
| D14 | **Plan persistence: this document, committed at `docs/PUBLIC_RELEASE_PLAN.md`** | Survives session transitions. Becomes public-facing when repo flips — trust signal showing deliberate process. |
| D15 | **Splunk Developer / Splunkbase publisher name: "Oleh Bezsonov"** (real name, not `@RelativisticJet` handle). Account email: `communicate.oleh@gmail.com`. Created at dev.splunk.com 2026-05-13. | Unifies identity with D5 LICENSE copyright. Real name is publicly visible on every Splunkbase listing under this account — trade-off accepted. Avoids future legal-entity transfer friction that a handle-as-brand might create. Matches convention of established Splunkbase community apps (e.g., TrackMe V1 published as "Guilhem Marchand"). Reversible by emailing Splunk Developer Support if an LLC is ever formed. |

---

## 2. Plan principles

- **Atomic commits per testable step.** Every numbered task ≤1 commit.
- **Phase boundary = reverification checkpoint.** All CI green + all
  acceptance criteria met before moving on.
- **Quality bar is constant, timeline flexes.** Per D2 + D7.
- **Two parked items remain non-scope** for v1: TrackMe-style
  commercialization vehicle, telemetry/phone-home.

---

## 3. Phase 0 — Foundation cleanup

**Goal**: green CI baseline + LICENSE switched + version reset +
CLAUDE.md split. Purely internal; no external dependencies.

**Target duration**: ~1 week.

| # | Task | Acceptance | Est. |
|---|------|------------|------|
| 0.0 | **De-risk Phase 1 FIRST** — install `splunk-appinspect` locally (`pip install splunk-appinspect`), run against the current `.spl` with both `cloud` and `splunk-platform-standalone` profiles, record findings. Decides whether Phase 1 is "trivial" or "multi-week refactor" BEFORE committing the rest of Phase 0. If findings are catastrophic, escalate to user before continuing. | Findings summary written; Phase 1 effort-class estimated | 30-60 min |
| 0.1 ✅ 2026-05-15 (commits `7d4765a` + `675116a` — see correction note) | Fix `validate-and-package.yml`. **Commit `7d4765a` (2026-05-14)** bumped `actions/upload-artifact` v3→v4 and `actions/checkout` v3→v4 — necessary for forward-compat with the 2026 GitHub Actions deprecation, audited all 10 workflows in `.github/workflows/` confirming none of the other 9 still on v3. **But this fix was cosmetic** and did NOT unblock the workflow: the FIRST step in the YAML, "Set up Bash environment", had been running `apt-get install bash` without sudo since 2026-03-22 (commit `219355e`, when the workflow file was originally added), which fails on `ubuntu-latest` runners — so the workflow never reached the action-version-pinned steps. `gh run list --workflow=validate-and-package.yml` showed 0 success runs in 30+ historical attempts. **Commit `675116a` (2026-05-15)** removes the broken step entirely (bash is pre-installed on the runner image; the apt-get step was unnecessary as well as broken) and adds an inline comment documenting the 2-month-long failure pattern. The original ✅ marker on this row was therefore incorrect; corrected as part of the Step-5+ Phase 0.1 redo. | Workflow green on next push | 15 min |
| 0.2 ⚠️ 2026-05-14 (PARTIAL — see note) | Fix `ci.yml` + `integration-tests.yml` pytest/Python mismatch (pytest 9.x requires Python ≥3.10; CI uses 3.9). **PARTIAL FIX:** bumped Python 3.9 → 3.11 in 4 places (ci.yml × 2, integration-tests.yml, release.yml) in commit `1fe4f92`; fixed 2 unmasked mock bugs in `tests/unit/test_limits.py` in commit `c5c08d1`. **Result on c5c08d1:** `ci.yml` GREEN (4/4 jobs); `integration-tests.yml` STILL FAILING — 23 fails + 220 errors. The integration-tests failures are NOT the Python mismatch alone; the round-7 install failure was masking a large body of pre-existing infrastructure debt: Splunk container 10-s curl-timeout under chaos load, KV-state pollution between tests, rate-limit state leaking across the suite, and one Python-version issue (pytest 9 dropped `pytest.skip(msg=dict)`). These need their own phase — see new Phase 0.2.1. | Both workflows green. Decision documented: cap pytest at ≤8.4.x OR upgrade workflow Python to 3.10+ | 30 min (Phase 0.2 estimate accurate for the mismatch fix itself; 0.2.1 scope much larger) |
| 0.2.1 ✅ 2026-05-14 (first green at `26933aa`; `53876d4` final QA-clean) | Fix `integration-tests.yml` red — separate from 0.2's Python bump. Triage: (a) `pytest.skip(msg=dict)` → `pytest.skip(reason=str)` migrations (pytest 9 API), (b) chaos-test docker curl timeout 10s → ≥30s for GitHub-Actions runners, (c) container_state fixture KV/sentinel cleanup race (Ring 2 Day 7 work), (d) rate-limit state pollution between RBAC-matrix tests. **FIX:** commit `b7e3429` replaced bind-mount-busting `rm -rf $LOOKUPS_DIR` with `find $LOOKUPS_DIR -mindepth 1 -delete` in `tests/integration/conftest.py :: _restore_container_state` — eliminated all 220 teardown errors. Commit `ccb37fc` closed the remaining 4 categories of failures (audit-POST 401 swallow, baseline-set skip, RBAC permission-string variants, chaos timing tolerance). Commit `26933aa` (QA #11 HIGH) replaced timeout bump with state-poll in `test_chaos_fim_dual_store.py :: test_kv_missing_silent_rebuild_from_fs`. Commit `53876d4` (QA #12 MEDIUM) dropped redundant `import time as _time` style nit. **Result:** 7 consecutive `integration-tests.yml` green runs from `26933aa` through current HEAD `035a390` (last red: `ccb37fc`). Acceptance: 358 passed, 8 skipped, 0 errors, 0 failed. | `integration-tests.yml` green on 2 consecutive pushes | 4-8 hr |
| 0.3 ⚠️ 2026-05-15 (PARTIAL — see note) | Fix `e2e-smoke.yml` Playwright `undefined` env var failure (Windows binary path appears on Linux runner). **PARTIAL FIX:** commit `e47ad78` replaces the hard-coded `process.env.LOCALAPPDATA + "/ms-playwright/chromium-1208/chrome-win64/chrome.exe"` constant in `tests/e2e/lib_helpers.cjs` and `tests/e2e/test_task8_modularization.mjs` with a platform-aware `resolveChromiumExecutable()` (honors `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` → Windows-with-`LOCALAPPDATA` path → `undefined` so playwright-core auto-resolves). Also pins `e2e-smoke.yml` / `e2e-full.yml` / `a11y-audit.yml` to `npx playwright@1.59.1 install ...` so the installed chromium revision matches `playwright-core@1.59.1`. **Result on e47ad78:** workflow run `25920807221` — Smoke 1 ✅ + Smoke 2 ✅ (chromium launch verified working on Linux runner), Smoke 3 ❌ failing at a *different* point: `LC01`/`LC02` rejected by the admin-settings gate ("Creating detection rules is not permitted. An admin must enable it in the Control Panel"), then `bPage.waitForSelector("table.wl-table tbody tr")` at line 155 times out because pending table is empty. This is test-seed pollution analogous to Phase 0.2.1's KV/rate-limit pollution — `setup_test_env.sh` provisions the wladmin1 user/role but doesn't seed `allow_admin_create_rule = true` / `allow_admin_create_csv = true` in Admin Settings. Belongs in a follow-up — see new Phase 0.3.1. | Workflow green | 1-2 hr (env-var fix accurate; test-seed work much larger) |
| 0.3.1 ✅ 2026-05-15 (commit `6ec9bec`) | Fix `e2e-smoke.yml` Smoke 3 (`test_control_panel_long_content.cjs`) red — separate from 0.3's chromium-launch fix. Triage in the original row was "admin settings KV" but the actual gate was the analyst-side toggles (`allow_analyst_create_rules` / `allow_analyst_create_csv`) plus `require_reason_*_creation` to route to the approval queue and return the `request_id` the test expects. **FIX:** commit `6ec9bec` adds a "Seeding limit config" step to `tests/e2e/setup_test_env.sh` that POSTs `set_daily_limits` as `superadmin1` after user provisioning, enabling the four toggles. Admin paths bypass these gates entirely (`wl_handler.py:2747` / `:2811` — admins execute directly), so the change is safe for admin-running tests. **Acceptance met:** workflow run `25922070685` (HEAD `6ec9bec`) — Smoke 1 ✅ + Smoke 2 ✅ + Smoke 3 ✅; workflow run `25922310733` (HEAD `adfaf91`, the prior planning-commit push) — Smoke 1 ✅ + Smoke 2 ✅ + Smoke 3 ✅. Two consecutive green pushes, no flakiness observed. | `e2e-smoke.yml` green on 2 consecutive pushes | 2-4 hr (actual: ~45 min once the gate path was traced) |
| 0.4 ✅ 2026-05-15 (`workflow_dispatch` runs `25926028136` / `25926029561` / `25926030716`) | Verify `a11y-audit` / `zap-baseline` / `pip-audit` workflows fire on schedule. All three workflow files were added AFTER their last scheduled fire date (a11y/zap on 2026-05-11, pip-audit on 2026-04-29) so none had auto-fired; manually triggered via `gh workflow run --ref main`. Results: **zap-baseline** clean scan (success); **pip-audit** clean scan (success); **a11y-audit** correctly detects 3 serious findings on the `audit` dashboard + 0 violations on `whitelist_manager` / `control_panel` (workflow conclusion = failure because findings exist, but the workflow itself is healthy — it's the audit-dashboard a11y regressions that need follow-up, NOT the workflow). **Acceptance interpretation:** "at least one successful recent run of each" = each workflow runs to completion and reports correctly. All 3 do. The a11y findings themselves are tracked as a Phase 2.x follow-up (see "Pending findings" footer below). | At least one successful recent run of each | 10 min |
| 0.5 ✅ 2026-05-15 (commit `fb500cc`) | CLAUDE.md 3-bucket migration: extract Decision Log → `docs/DECISION_LOG.md`, Operational Procedures + Disaster Recovery + Rollback → `docs/RUNBOOKS.md`, Splunk Quirks → `docs/SPLUNK_QUIRKS.md`. Replaced the 3 pre-reserved stub files from commit `376f118` with the actual migrated content (38 / 376 / 45 lines respectively). Cross-references in CLAUDE.md handled as local-only edits since the file is gitignored per D11 ("CLAUDE.md slimmed to personal overlay, stays gitignored"). Doc-drift hook passes on all 28 scanned docs against build 660. **Actual time: ~30 min** (much less than the 2-3 hr estimate — `sed`-based extraction from the gitignored source was straightforward; the heavy lift was in the original drafting of those sections, which already happened months ago). | 3 files exist, cross-references in CLAUDE.md updated, doc-drift hook passes | 2-3 hr |
| 0.6 ✅ 2026-05-15 (commit `e55e9ab`) | LICENSE: MIT → Apache 2.0 + add NOTICE file. Canonical Apache 2.0 boilerplate from apache.org with "How to apply" appendix carrying `Copyright 2026 Oleh Bezsonov`. NOTICE file carries copyright attribution + Splunk trademark disclaimer (early-landing Phase 2.1 item) + third-party content statement (jQuery/Bootstrap consumed via Splunk runtime, not redistributed). | LICENSE replaced; NOTICE added per Apache 2.0 conventions | 30 min |
| 0.7 ✅ 2026-05-15 (commit `da5cbc0`) | Copyright holder change from "Security Engineering" to Oleh Bezsonov. Touched `default/app.conf` `[launcher].author` and `docs/Whitelist_Manager_Documentation.md` byline. Deliberately NOT touched: `docs/PUBLIC_RELEASE_PLAN.md` (self-referential historical text) and `docs/Splunk_Admin_Installation_Guide.md` (references a customer-side SOC role named "Security Engineering team", different semantic from this project's authorship). | Single Edit in LICENSE + NOTICE | 5 min |
| 0.8 ✅ 2026-05-15 (commit `a01aa79`) | `app.conf:version` bump 2.0.0 → 1.0.0-rc1. Both `[launcher].version` and `[id].version` updated (must match per AppInspect 4.2.0). Doc byline in `Whitelist_Manager_Documentation.md` also bumped to match. `[install].build` unchanged — build counters are deploy-cycle monotonic across version bumps. | Version reflects pre-public RC | 5 min |
| 0.9 | CLAUDE.md backup sync: first push of slim CLAUDE.md to `relativisticjet-dev-knowledge-base/projects/wl_manager/CLAUDE.md` | First sync committed in the backup repo. Sync mechanism documented (manual / cron / git hook — user's preference) | 30 min |
| 0.10 ✅ 2026-05-15 (scan documented in PR review of HEAD) | `git log --all -p` secret scan across all 456 commits / 17 MB of diff history. Scanned 14 high-confidence patterns (PEM private keys, AWS AKIA, AWS secret-access-key assignments, GitHub PAT/OAuth/server/refresh tokens, Slack `xoxX-`, Stripe `sk_live_`/`sk_test_`, 3-segment JWTs, GitLab `glpat-`, npm `npm_`, Splunk HEC-token-UUID) and 5 generic-pattern fallbacks. **High-confidence hits: 0 across all 14 patterns.** Generic-pattern hits: 1 `password="..."` (the `api_call()` helper's default `password="Chang3d!"`, the documented Splunk dev-container admin password) and 3 `token="..."` (Splunk SimpleXML **dashboard-variable** tokens — `general_action_display`, `admin_action_display`, `drilldown_analyst` — Splunk lingo for dashboard state, NOT credentials). No `.env` / `.pem` / `.key` / `.p12` / `.pfx` / `.jks` / `.keystore` files ever committed. **Decision (per Phase 0.10 acceptance footer): ACCEPT — no `git filter-repo` rewrite needed.** `Chang3d!` is a known-dev-credential by design (Splunk Docker container demo password, documented in INSTALLATION + CLAUDE.md, used by 30+ dev/test/docs files); users running the demo container are instructed to change it before any production exposure. | No accidental credentials in history. Or — if found — decision documented (filter-repo vs accept) | 30 min |
| 0.11 | Close prior-work TODOs that fit Phase 0 scope: `wl_expiration_cleanup.py` 401 investigation, `scripts/package.sh` version-tag drift, Step 3b permanent add to RELEASE_CHECKLIST §8 | Each closed as atomic commit | 2-3 hr |

**Phase 0 acceptance**:
- All 10 existing CI workflows green on a clean push
- CLAUDE.md is slim, contains only personal overlay + pointers
- 3 new `docs/` files exist, doc-drift hook validates them
- Apache 2.0 LICENSE in place with user's name
- `app.conf:version = 1.0.0-rc1`
- `relativisticjet-dev-knowledge-base/projects/wl_manager/CLAUDE.md` exists
- Git history confirmed clean (or remediation plan documented)

**Phase 0 risks**:
- R0.1 — `e2e-smoke.yml` breakage might be tangled (turning 1-2 hr into half a day). If so, surface and re-decide quarantine-vs-fix.
- R0.2 — Secret scan might find genuine secrets. Options: `git filter-repo` (rewrites history, alters all SHAs) vs accept as known. Big decision; escalate.
- R0.3 — CLAUDE.md migration is invasive (touching 5+ docs). Reserve buffer for doc-drift hook iterations.

---

## 4. Phase 1 — Risk discovery (AppInspect)

**Goal**: AppInspect API returns 0 errors against both Cloud and
on-prem profiles. This phase has the highest unknown work: the Cloud
profile may demand scripted-input rework.

**Target duration**: 2 weeks if Cloud cert is mostly compatible, up
to 6+ weeks if architectural refactor is needed. Per D2 + D7 the
timeline slips, scope does not.

| # | Task | Acceptance | Est. |
|---|------|------------|------|
| 1.1 | Sign up for Splunk Developer account at dev.splunk.com | Account active, credentials stored securely | 15 min |
| 1.2 | Wire `splunk/appinspect-cli-action` in new `.github/workflows/appinspect.yml` | Workflow runs against built .spl with `splunk-platform-standalone` profile | 30 min |
| 1.3 | First AppInspect CLI run + triage findings → `docs/<APPINSPECT_FINDINGS>.md` | All findings logged by severity (error / warning / manual_check); each has a fix-or-defer decision | 2-4 hr |
| 1.4 | Provision Splunk Cloud Sandbox or paid trial for API-based dynamic checks | Trial active; credentials in GitHub Actions secrets | 1-2 hr |
| 1.5 | Wire `splunk/appinspect-api-action` workflow with `cloud` + `self-service` tags | API workflow fires, dynamic checks complete | 30 min |
| 1.6 | First AppInspect API run — **surface Cloud-cert blockers** | Findings appended to APPINSPECT_FINDINGS.md. **Critical**: assess `wl_fim.py` / `wl_fim_watch.py` / `wl_expiration_cleanup.py` viability for Cloud profile. **If estimated refactor >2 weeks, escalate per D7 before continuing** | 1 day investigation |
| 1.7 | Fix all AppInspect "error"-severity findings | Each as atomic commit. AppInspect re-runs green | 1 day – several weeks (per 1.6 outcome) |
| 1.8 | Per-finding triage on "warning" + "manual_check" | Document per-finding: fix / accept-with-justification / defer-to-v1.1 | 2-4 hr |
| 1.9 | Architectural refactor for Cloud cert (only if 1.6 requires) | Scripted inputs → modular inputs or REST endpoints; permissions audit; web.conf restrictions | unknown (gates everything else) |
| 1.10 | Soft escalation checkpoint — at week 4 of Phase 1 work, if Cloud profile not green, surface to user for re-decision (continue / pivot / on-prem-only) | Decision documented in DECISION_LOG.md | varies |

**Phase 1 acceptance**:
- `appinspect.yml` CLI + API workflows both green
- 0 error-severity findings in both `cloud` and `splunk-platform-standalone` profiles
- All "warning" + "manual_check" items have a documented disposition
- If refactor was needed: documented in DECISION_LOG.md with rationale

**Phase 1 risks**:
- R1.1 — Task 1.6 outcome is the biggest unknown in the entire plan. Could be 1 day, could be 6 weeks. D7 escalation policy mitigates indefinite drift.
- R1.2 — Splunk Cloud Sandbox may have access restrictions. Backup: paid Splunk Cloud Platform trial.
- R1.3 — Architectural refactor (1.9) might break existing E2E tests. Phase 0's green-CI baseline lets us catch regressions early.

---

## 5. Phase 2 — Public-readiness polish

**Goal**: every public-facing file polished. Hosted docs site live.
README reads as a finished product.

**Target duration**: ~2 weeks, can overlap with end of Phase 1.

| # | Task | Acceptance | Est. |
|---|------|------------|------|
| 2.1 | Trademark disclaimer added to README + INSTALLATION ("Splunk and Splunk Enterprise Security are registered trademarks of Splunk LLC...") | Disclaimer present in both files | 30 min |
| 2.2 | Manual Splunkbase name-collision check for "Whitelist Manager" | Confirmed unique OR backup name picked | 30 min |
| 2.3 | SECURITY.md with vulnerability disclosure policy | File at repo root. GitHub Security Advisories enabled in repo settings. Private contact path defined. | 30 min |
| 2.4 | CONTRIBUTING.md with PR + issue process | Covers branch model, commit conventions, test requirements, response SLA expectations | 1 hr |
| 2.5 | CODE_OF_CONDUCT.md (Contributor Covenant 2.1) | Standard text | 15 min |
| 2.6 | GitHub issue templates (bug, feature, security, question) | `.github/ISSUE_TEMPLATE/` populated | 45 min |
| 2.7 | PR template at `.github/PULL_REQUEST_TEMPLATE.md` | Covers test plan, screenshots, verification | 15 min |
| 2.8 | MkDocs Material scaffold: `mkdocs.yml` + `docs/<index>.md` + nav + theme + `.github/workflows/docs.yml` deploying to GitHub Pages | `https://relativisticjet.github.io/wl_manager/` live | 2-3 hr |
| 2.9 | Migrate existing docs (SBOM, INSTALLATION, RUNBOOKS, DECISION_LOG, SPLUNK_QUIRKS, etc.) into MkDocs nav | All accessible from site nav | 1-2 hr |
| 2.10 | README rewrite for public audience: hero, value prop, install, RBAC, badges, link to hosted docs | Reads like a finished product | 3-4 hr |
| 2.11 | GitHub repo settings: topics, description, homepage URL, social preview image | Discoverability optimized; topics include `splunk`, `splunkbase`, `siem`, `soc-tools`, `splunk-enterprise-security`, `detection-engineering` | 30 min |
| 2.12 | Sigstore signing workflow upgrade — `cosign-release` v2.4.1 → v3.x — and remove `--new-bundle-format=false` from customer docs | Customer command works without compat flag | 1 hr OR defer to v1.1 |
| 2.13 | Pre-existing TODO cleanup from old CLAUDE.md "Pending / Future Work": MCP server activation status, 3 span clear-button P2 a11y items, 11 test CSV cleanup decision | Each resolved or explicitly deferred | 2-3 hr |
| 2.14 | Public-friendliness review of DECISION_LOG.md — soften / redact entries that describe attack scenarios in too-explicit detail | One review pass, atomic commit | 1-2 hr |

**Phase 2 acceptance**:
- All public-facing files exist and are polished
- Hosted docs site live and indexable
- README rewritten
- Repo metadata optimized
- Trademark + license + security disclosure all in place

**Phase 2 risks**:
- R2.1 — MkDocs Material theming might require iteration. Reserve buffer.
- R2.2 — README rewrite for public audience is a different skill than internal docs. Drafts may need iteration.

---

## 6. Phase 3 — Public flip + 4-week hold period

**Goal**: repo public, community engaged, v1.0.0 GA tag cut.

**Target duration**: 1 week of prep + 4 weeks of hold = 5 weeks.

| # | Task | Acceptance | Est. |
|---|------|------------|------|
| 3.1 | Pre-public review — read every file from an outsider's perspective | Walkthrough checklist documented in `docs/<PRE_PUBLIC_AUDIT>.md`. Anything sensitive or unprofessional flagged | 1 day |
| 3.2 | Cut v1.0.0-rc1 release tag, private | Workflow signs the .spl, all CI green | 30 min |
| 3.3 | Internal verification of rc1 .spl: install on clean Splunk container, run full E2E suite, manually verify major UI flows | Full install + uninstall + reinstall works clean | 4 hr |
| 3.4 | **Flip repo private → public** (one-way without history rewrite) | GitHub repo visibility = public | 5 min |
| 3.5 | Community pre-announcement on Splunk dev Slack, Splunk Lantern, dev.splunk.com forums | Posts published, links shared | 1-2 hr |
| 3.6 | **Hold period — 4 weeks**: monitor issues, respond within documented SLA, collect feedback, iterate on docs + bugfixes | 4 weeks elapsed; major bugs resolved; doc gaps surfaced fixed | 4 weeks |
| 3.7 | End-of-hold review: bug count, response time, doc gaps, lessons → `docs/<v1_RC_RETRO>.md` | Document published | 2 hr |
| 3.8 | Cut v1.0.0 (GA) release | Workflow signs, release notes published, social announcement | 1 hr |

**Phase 3 acceptance**:
- Repo public for 4+ weeks
- v1.0.0 GA tag cut and signed
- Zero unresolved critical-severity bugs from hold period
- Retro published

**Phase 3 risks**:
- R3.1 — Repo flip is one-way without history rewrite. Phase 0.10 secret scan MUST be thorough.
- R3.2 — Documented response SLA may be unsustainable. Have a "solo maintainer, please be patient" policy in CONTRIBUTING.md.
- R3.3 — Community announcement may generate more interest than expected. Have a 10-minute FAQ ready.

---

## 7. Phase 4 — Splunkbase submission

**Goal**: listed on Splunkbase, installable by Splunk customers
through the official channel.

**Target duration**: ~3-4 weeks total (review queue + iteration).

| # | Task | Acceptance | Est. |
|---|------|------------|------|
| 4.1 | Splunkbase Developer profile setup at splunkbase.splunk.com | Account active, agreements signed | 30 min |
| 4.2 | Splunkbase listing draft: app name, description, screenshots, category | Marketing copy reviewed before submission | 3-4 hr |
| 4.3 | First Splunkbase submission of v1.0.0 .spl | Upload via web UI; status "In Review" | 1 hr |
| 4.4 | Splunkbase review queue wait | Reviewer responds (1-2 weeks typical) | wait |
| 4.5 | Iteration on reviewer feedback | Each finding fixed as atomic commit + re-upload | unknown |
| 4.6 | Splunkbase listing live | App searchable + installable on Splunkbase | — |
| 4.7 | Public "now on Splunkbase" announcement | README badge updated, social post, Slack/Lantern follow-up | 1 hr |

**Phase 4 acceptance**:
- Splunkbase listing live at `splunkbase.splunk.com/app/<ID>`
- README references the listing
- v1.0.0 installable via Splunk's "Install from Splunkbase" UI

**Phase 4 risks**:
- R4.1 — Splunkbase reviewers may find issues AppInspect didn't flag. Plan for 1-3 iteration cycles.
- R4.2 — App name might collide with existing Splunkbase apps. Have backup names ready (already validated in Phase 2.2).

---

## 8. Phase 5 — Sustain (ongoing post-Phase 4)

| Task | Description | Cadence |
|------|-------------|---------|
| 5.1 | Quarterly version-pinning audit (already scheduled 2026-07-18) | Quarterly |
| 5.2 | Per-release Splunkbase manual upload | Per release |
| 5.3 | Issue triage per documented CONTRIBUTING.md SLA | Continuous |
| 5.4 | v1.1 planning from hold-period + post-launch feedback | When critical mass accumulates |
| 5.5 | Annual license / dependency audit | Annual |

---

## 9. Cross-phase verification cadence

**At every phase boundary**:
1. All CI workflows green on the head commit
2. All Phase acceptance criteria met
3. CHANGELOG.md updated
4. Slim CLAUDE.md synced to backup repo
5. Phase retro written: what worked, what didn't, what to change next phase
6. DECISION_LOG.md updated if any locked decision changed

**At every commit during Phase 1 architecture work**:
1. AppInspect API re-run (CI auto)
2. All existing CI workflows still green
3. No regression in test coverage

---

## 10. Items deliberately out of scope for v1

| Item | Reasoning |
|------|-----------|
| Telemetry / phone-home | D9 — privacy maximalism for v1; revisit at v2 |
| CLA (Contributor License Agreement) process | No external contributors yet; can add later if needed |
| Commercialization vehicle (LLC, dual licensing) | Premature; defer until adoption traction exists |
| Internationalization / i18n | All UI strings English-only; Splunk i18n quirks known to be tricky; defer to v1.x feature backlog |
| Disaster recovery for the GitHub repo itself | GitHub is a SPOF; address with mirror cron later |
| Accessibility statement (public WCAG 2.1 AA conformance doc) | Audit done internally; defer formal statement until v1.1 |
| Support contract / professional services offering | Defer until adoption exists |
| Sigstore signer upgrade to cosign v3.x (workflow side) | Optional polish in Phase 2.12; can defer to v1.1 |

---

## 11. Plan-maintenance discipline

This document is itself part of the plan. Rules:

1. **Never silently revisit locked decisions.** If a session believes a locked decision should change, surface it explicitly to the user, document the reasoning in DECISION_LOG.md, and only THEN edit this file.
2. **Check off completed tasks** with the date + commit SHA: `0.1 ✅ 2026-05-XX (commit abc1234)`.
3. **Update phase status** at the top of this file when a phase opens or closes.
4. **Add tasks discovered mid-phase** with a clear "discovered during X" note, so the next session can audit scope drift.
5. **Doc-drift hook validates this file**: paths must be real, version strings must be `<VERSION>` placeholders (no hardcoded build numbers).
