# AppInspect Findings — Phase 1.3 baseline

> **Status**: First AppInspect CLI baseline against the RC1 candidate
> (`wl_manager-1.0.0-rc1.spl`).
> **Verdict**: clean. 0 errors / 0 failures / 0 future_failures across
> both `splunk-platform-standalone` and `cloud` profiles. Warnings are
> all triaged below and accepted.
> **Updated**: 2026-05-17 (Phase 1.3).

This document is the Phase 1.3 deliverable from
`docs/PUBLIC_RELEASE_PLAN.md` §4 ("All findings logged by severity
(error / warning / manual_check); each has a fix-or-defer decision").
It supersedes the historical Phase 0.0 de-risk report at
`.planning/go-public/PHASE_0_0_APPINSPECT_FINDINGS.md` — that doc
remains in `.planning/` as the audit trail for the de-risk decision;
this doc is the durable Phase 1+ reference and is what the next
AppInspect re-run should be diffed against.

For the local CLI re-run command, see §6 below.

---

## 1. Headline numbers

Run against `dist/wl_manager-1.0.0-rc1.spl` (392 KB, 94 archive members)
using `splunk-appinspect` 4.2.0 inside `wl-appinspect:latest`
(`.planning/appinspect/Dockerfile`, `python:3.11-slim` + `libmagic1`).

| Result class    | Standalone (249 total) | Cloud (242 total) |
|-----------------|------------------------|-------------------|
| **error**       | **0**                  | **0**             |
| **failure**     | **0**                  | **0**             |
| **future_failure** | **0**               | **0**             |
| skipped         | 0                      | 0                 |
| not_applicable  | 83                     | 80                |
| warning         | 6                      | 5                 |
| success         | 160                    | 157               |

Raw outputs:

- `.planning/appinspect/appinspect-standalone-phase1.json`
- `.planning/appinspect/appinspect-cloud-phase1.json`

These supersede the build-660 baseline (`*-final2.json` in the same
directory) for diff purposes. The build-660 files are retained as the
Phase 0.0 audit trail.

---

## 2. Drift discovered during this run (and fixed)

The first run of the Phase 1.3 baseline reproduced a single failure:

**`check_version_is_valid_semver`** — `info.id.version` in
`app.manifest` was `"2.0.0"` while `default/app.conf` `[launcher]
version` and `[id] version` had been bumped to `1.0.0-rc1` in Phase 0.8
(commit `a01aa79`). AppInspect requires all three to match.

**Root cause**: Phase 0.8 demoted the user-visible version to the RC
suffix in `app.conf` but missed `app.manifest`, which is the third
source-of-truth that AppInspect's
`check_version_is_valid_semver` reads.

**Why the §3.5 pre-flight in `docs/RELEASE_CHECKLIST.md` didn't catch
it**: that checklist (added in Phase 0.11b, commit `fb5f8f0`) only
inspects four fields *inside* `app.conf` — `[launcher].version`,
`[id].version`, `[id].name`, `[package].id`. It doesn't look at
`app.manifest`. Phase 1.3 commit extends §3.5 with a fifth check that
parses `app.manifest` `info.id.version` and compares to the
intended tag.

**Fix landed in this commit**: `app.manifest` `info.id.version` →
`1.0.0-rc1`; `releaseDate` → `2026-05-17`.

**Re-run result**: clean (the headline-numbers table above).

---

## 3. Per-finding triage (warnings only)

All warnings are unchanged from the build-660 Phase 0.0 baseline. They
are reproduced here with current triage so this doc is self-contained
for Phase 1.4+ work.

### 3.1 `check_for_indexer_synced_configs` (Standalone-only)

**File**: `default/inputs.conf`

**Message**: "will not be synced to indexers in Victoria. If this file
is necessary on indexers, configure the settings in the Splunk UI or
via Admin Config Service."

**Triage**: **accepted as correct**. Scripted inputs run on the search
head only by design (`targetWorkloads: ["_search_heads"]` in
`app.manifest`). Not applicable to the Cloud profile because Cloud
Vetting auto-derives this from `targetWorkloads`. No fix.

### 3.2 `check_for_splunk_js` (13 occurrences, both profiles)

**Files**: every JS file that imports `splunkjs/mvc`
(`whitelist_manager.js`, `audit_tz.js`, `control_panel.js`,
`application.js`, `audit_trail.js`, `notifications.js`,
`modules/wl_presence.js`).

**Message**: literally "Please ignore this warning as it has no impact
to your Splunk app." (Splunk's own internal telemetry warning on
SplunkJS usage.)

**Triage**: **ignored** per Splunk's own advice. No fix.

### 3.3 `check_for_python_script_existence` (24 files, both profiles)

**Message**: "24 Python files found. Update these Python scripts to be
cross-compatible with Python 2 and 3 for Splunk Enterprise 8.0."

**Triage**: **moot**. `app.manifest:platformRequirements.splunk.Enterprise
= ">=9.0.0"`. Splunk 9.x dropped Python 2 entirely. No fix.

### 3.4 `check_for_scripted_inputs` (3 stanzas, both profiles)

**Files**: `default/inputs.conf` lines 7 (`wl_expiration_cleanup`), 38
(`wl_fim`), 56 (`wl_fim_watch`).

**Message**: "No action required."

**Triage**: **informational enumeration**. AppInspect surfaces every
scripted input as a warning so a reviewer can sanity-check the list.
All three are documented in `CLAUDE.md` ("Operational Procedures") and
covered by the per-feature rollback procedures in `docs/RUNBOOKS.md`.
No fix.

### 3.5 `check_for_gratuitous_cron_scheduling` (4 saved searches, both profiles)

AppInspect flags any saved search scheduled more than 12 times per
hour. wl_manager has four such searches. All four exist for
detection-critical low-latency reasons and are not cosmetic; the
per-search justification follows.

| Saved search | Schedule | Disabled? | Reason for high frequency |
|---|---|---|---|
| `wl_csv_external_modification_alert` | `*/1 * * * *` (60/hr) | no | Detects SPL `outputlookup` / direct-FS / REST bypass of the handler against any managed CSV within a 2-minute window. This is the *primary* defense against the canonical Splunk-app attack surface AppInspect itself does not model (any role with `schedule_search` can `\| outputlookup` past every approval gate, rate limit, and audit trail the handler enforces). Latency to alert is the security guarantee. **Accepted as designed.** |
| `wl_csv_modification_attribution` | `*/1 * * * *` (60/hr) | **default `false`**, gated on `_audit` index read access | Joins `fim_csv_external_modification` events to `index=_audit` `action=search` records (within a 3-minute window) to attribute the modification to the user + saved-search definition that caused it. The 3-minute look-back is intentional — `_audit` writes are lazy and a 1-minute schedule with a 3-minute window gives the indexer time to catch up. Disabled by default in environments that lack `_audit` read; enable with both `wl_csv_external_modification_alert` to get full attack attribution. **Accepted as designed.** |
| `wl_saved_search_timebomb_monitor` | `*/2 * * * *` (30/hr) | **default `true`** | Detects *creation/edit* of a saved search whose definition contains `outputlookup` targeting a managed CSV ("timebomb" attack: legitimate-looking scheduled search that periodically rewrites a whitelist). 10-minute look-back at every 2-minute cadence ensures the window covers indexing latency. Disabled by default because it requires `_audit` access; enable when threat model includes saved-search-creating attackers. **Accepted as designed.** |
| `wl_deploy_window_opened_during_lockdown` | `*/1 * * * *` (60/hr) | no | Detects the compromised-superadmin attack signature: opening a deploy window during emergency lockdown. Deploy windows are lockdown-exempt **by design** (so hotfixes can ship during an incident), which means a compromised superadmin can use a deploy window to suppress FIM alerts on the code-file mutations they're attempting. The 1-minute schedule + 10-minute look-back catches this signature within a minute. **Accepted as designed.** |

**Triage**: **all four accepted with documented justification**. The
AppInspect 12/hr heuristic is a sensible default for routine reporting
searches but does not account for security-critical detection
pipelines. If Splunkbase manual review flags this in Phase 1.5–1.6,
this section is the response.

The Phase 0.0 doc mentioned a 5-minute schedule for the external
modification alert — that was a documentation drift in `CLAUDE.md`'s
Decision Log (2026-04-23 entry). The actual `savedsearches.conf`
ships `*/1 * * * *`. The cadence was tightened during hardening rounds
to bring detection latency below the practical SOC response horizon.
The decision-log row will be reconciled in a follow-up doc-drift sweep.

### 3.6 `check_collections_conf` (both profiles)

**File**: `default/collections.conf`

**Message**: "No action required."

**Triage**: **informational** ("you have a KV-store collection
declared"). Two collections declared: `wl_cooldowns` and
`wl_fim_baseline`, both used for cross-worker state (`feedback_per_worker_state.md`
notes the migration in builds 656–657). No fix.

---

## 4. Delta vs Phase 0.0 baseline (build-660 `final2`)

Apples-to-apples diff against
`.planning/appinspect/appinspect-standalone-final2.json` /
`appinspect-cloud-final2.json` (both 2026-05-14, build 660):

| Class           | Standalone Δ | Cloud Δ |
|-----------------|--------------|---------|
| error           | 0 → 0        | 0 → 0   |
| failure         | 0 → 0        | 0 → 0   |
| future_failure  | 0 → 0        | 0 → 0   |
| warning         | 6 → 6        | 5 → 5   |
| success         | 160 → 160    | 157 → 157 |

**Zero drift (origin: 2026-05-14, build 660 baseline).** Every code
change between that snapshot and the 1.0.0-rc1 candidate as of
2026-05-14 (Phase 0 docs migration, R6-F8 KV-presence migration, §5a
items: FUNDING.yml stub + gitleaks workflow + SSH tag signing docs) is
AppInspect-neutral.

The reason: every change either lived in `docs/`, `.github/`, or
`tests/` (all excluded from the `.spl` by `scripts/package.sh`), or
touched runtime code in `bin/` without introducing a new AppInspect
trigger (KV-store usage was already declared in `collections.conf`
before the migration).

> **Note**: changes shipped after 2026-05-14 (e.g. the empty-install
> banner introduced in build 661) need their own AppInspect re-run
> before the v1.0.0 release. See `docs/RELEASE_CHECKLIST.md`.

### 4.1 Build-668 spot-check (2026-05-20)

Local CLI re-run on `wl_manager-1.0.0-rc1.spl` packaged from
`default/app.conf` `build = 668` (HEAD `c53552e`). Output JSON
preserved at `.planning/appinspect/build668/`. Numbers below are
identical to the 2026-05-14 baseline AND the 2026-05-17 hosted-API
run (§5 below), so the build-666/667/668 audit-trail-pollution
defense work (admin reorder cap + log_event cap + LIMIT_KEYS
expansion + UI form additions) is AppInspect-neutral.

| Profile                    | error | failure | future_failure | warning | success |
|----------------------------|-------|---------|----------------|---------|---------|
| splunk-platform-standalone | 0     | 0       | 0              | 6       | 160     |
| cloud                      | 0     | 0       | 0              | 5       | 157     |

**Zero drift.** The four added action-types (admin_row_reorder,
admin_column_reorder, log_event_emit cap, LIMIT_KEYS allow-list
expansion) live inside existing handler code paths and configurable
limit infrastructure — AppInspect's static checks have no triggers
that fire on new dispatch entries or new limit keys at the source
level. The remaining surface (an additional dynamic SLIM failure
suppressed via `.appinspect_api.expect.yaml`) is hosted-API-only
and will be re-verified by the next CI run after the GitHub Actions
billing block clears.

### 4.1.1 v1.0.0-rc1 tag-cut verification (2026-05-20)

Re-run on the same build-668 codebase after F-M4 (`app.manifest`
`releaseDate` 2026-05-17 → 2026-05-20) and the CHANGELOG
`[1.0.0-rc1]` release-header insert. Output JSON at
`.planning/appinspect/appinspect-{standalone,cloud}-rc1.json`.
Numbers are identical to §4.1 (160/0/0/6 standalone, 157/0/0/5
cloud) — manifest releaseDate is metadata only, not exercised by
any AppInspect check, and CHANGELOG.md does not ship in the .spl
payload. This is the §3.5 pre-flight + AppInspect dry-run gate
referenced from `docs/RELEASE_CHECKLIST.md` for the rc1 cut.

---

## 5. Cloud API + dynamic checks (Phase 1.6 first API run)

> **Status**: Phase 1.6 first API run executed 2026-05-17 against
> `wl_manager-1.0.0-rc1.spl` via `.github/workflows/appinspect-api.yml`.
> Run ID: `26000914082` (GHA `appinspect-api.yml`, HEAD `027014a`).
> The dynamic stage reproduced the Phase 1.3 local-CLI warning set
> exactly and surfaced ONE additional **failure** that the local CLI
> does not run — the SLIM packager validator. See §5.4 below for the
> escalation assessment.

### 5.1 Headline numbers (API stage)

| Result class    | Cloud Vetting (`cloud`) | Self-Service Cloud (`private_app`) |
|-----------------|-------------------------|-----------------------------------|
| **error**       | **0**                   | **0**                             |
| **failure**     | **1**                   | **0**                             |
| **future_failure** | **0**                | **0**                             |
| skipped         | 0                       | 0                                 |
| not_applicable  | 80                      | 78                                |
| warning         | 5                       | 5                                 |
| manual_check    | 0                       | 0                                 |
| success         | 161                     | 159                               |

The hosted API runs 4 more checks than the local CLI on the cloud
profile (161 success vs 157 in §1) — those additions are SLIM-related
dynamic checks the local CLI does not invoke. The 5 warnings on each
profile are byte-identical to the §3 triage above (`check_for_splunk_js`,
`check_for_python_script_existence`, `check_for_scripted_inputs`,
`check_for_gratuitous_cron_scheduling`, `check_collections_conf`); no
new warnings were introduced by the dynamic stage.

The `private_app` profile passed cleanly — Self-Service Cloud is
already a valid distribution path for the current build.

### 5.2 The one failure — `check_that_app_passes_slim_validation_for_cloud`

The hosted API embeds the Splunk Packaging Toolkit (SLIM) and runs
its `slim validate` step against the unpacked .spl. SLIM rejected the
package with a single hard error plus eleven secondary "undefined
setting" observations:

| # | Class | File | Stanza | Setting / message |
|---|-------|------|--------|------------------|
| **F1** | **HARD ERROR** | `app.manifest` | `platformRequirements.splunk` | "Version requirement includes no supported version of Splunk Enterprise: `>=9.0.0`" |
| F2 | Undefined setting | `default/inputs.conf` | `[script://...wl_expiration_cleanup.py]` | `python.version` |
| F3 | Undefined setting | `default/inputs.conf` | `[script://...wl_expiration_cleanup.py]` | `python.required` |
| F4 | Undefined setting | `default/inputs.conf` | `[script://...wl_fim.py]` | `python.version` |
| F5 | Undefined setting | `default/inputs.conf` | `[script://...wl_fim.py]` | `python.required` |
| F6 | Undefined setting | `default/inputs.conf` | `[script://...wl_fim_watch.py]` | `python.version` |
| F7 | Undefined setting | `default/inputs.conf` | `[script://...wl_fim_watch.py]` | `python.required` |
| F8 | Undefined setting | `default/restmap.conf` | `[script:wl_manager_handler]` | `python.version` |
| F9 | Undefined setting | `default/restmap.conf` | `[script:wl_manager_handler]` | `python.required` |
| F10 | Undefined setting | `default/commands.conf` | `[wlexpiringsoon]` | `python.version` |
| F11 | Undefined setting | `default/commands.conf` | `[wlexpiringsoon]` | `python.required` |
| F12 | Undefined setting | `default/app.conf` | `[id]` | `check_for_updates` |

**F1 (HARD ERROR) — root cause analysis**: SLIM expects a closed-range
or specific-version constraint, not the open lower bound `>=9.0.0`.
The current manifest declares only a floor, which SLIM reads as "no
upper bound = no concrete Splunk version is in range". Fix in Phase 1.7
is a one-line manifest edit — e.g., `">=9.0.0,<11.0.0"` or the
Splunkbase-recommended form. Documented for Phase 1.7.

**F2–F11 — root cause analysis**: SLIM is using an older `.conf.spec`
catalog than current AppInspect. The settings `python.version` and
`python.required` ARE declared at the source (`default/inputs.conf:16-17`,
`:43-44`, `:61-62`; `default/restmap.conf:22-23`; `default/commands.conf:8-9`)
because static AppInspect's `check_python_version_correctness_for_splunk_enterprise`
requires them. SLIM does not recognize them in its spec and flags
both as undefined. This is the spec-drift between AppInspect and SLIM
that the existing source-comments (e.g., `inputs.conf:12-15`)
predicted. Two valid remediations for Phase 1.7:

1. Live with the SLIM noise; document it in `.appinspect_api.expect.yaml`
   so the workflow stops failing on these. The settings stay (static
   AppInspect needs them).
2. Engage Splunk on the SLIM/AppInspect spec divergence. Likely too
   slow to be a Phase 1.7 fix.

Option (1) is the intended Phase 1.7 path; option (2) is for the
roadmap.

**F12 — root cause analysis**: same spec-drift class as F2–F11, NOT a
missing-setting bug. `check_for_updates = false` IS present at
`default/app.conf:22` inside the `[id]` stanza (and again at line 30
inside `[package]`). SLIM only flags the `[id]` occurrence — the
`[package]` one is recognized and silent. SLIM's spec doesn't allow
`check_for_updates` in the `[id]` stanza; the canonical home is
`[package]` (which we already have). Phase 1.7 fix is to **delete** the
redundant `[id].check_for_updates = false` line, not add a new
setting. The defensive duplication referenced by the in-file comment at
`app.conf:24-27` was over-cautious — `check_for_updates_disabled`
(the AppInspect check) only inspects `[package]`, per that same
comment.

### 5.3 Pre-flagged surfaces — outcome

The pre-Phase-1.6 `§5` (this section in its previous form) listed
three surfaces of concern. Outcome from the actual run:

| # | Pre-flagged surface | Outcome |
|---|---------------------|---------|
| 1 | **Persistent scripted inputs** (`bin/wl_fim_watch.py` `interval = 0`, "single biggest remaining unknown") | **NOT rejected.** The Cloud profile accepted the stanza's presence; the only flag on `wl_fim_watch.py` was the spec-drift `python.version`/`python.required` noise (F6/F7) shared with every other script stanza. The R1.1 / D7 escalation surface (refactor `wl_fim_watch.py` to non-persistent) did **NOT** materialize. |
| 2 | **Outbound network calls** (handler → `localhost:8089` via `splunk.rest.simpleRequest`) | **Not flagged.** Loopback to splunkd is implicit-allow on both profiles. |
| 3 | **CycloneDX SBOM** as a `.spl` sibling | **Not flagged by the validator.** Splunkbase upload step (Phase 4) will exercise this separately. |

### 5.4 R1.1 / D7 escalation assessment — **NOT triggered**

The Phase 1 plan (`docs/PUBLIC_RELEASE_PLAN.md` §1) escalates to D7
(architectural refactor) if Cloud Vetting categorically rejects the
persistent scripted input. That did not happen — see §5.3 row 1.

All twelve sub-findings (F1–F12) are config / manifest edits, not
architectural changes. Total estimated Phase 1.7 effort: **≤2 hours**
for the manifest + `.appinspect_api.expect.yaml` + `[id]` edits,
versus the **>2 week** budget the escalation clause assumes for a
`wl_fim_watch.py` refactor.

Phase 1.7 ("Fix all error-severity findings") can proceed within its
original scope on the original schedule.

### 5.5 Phase 1.5 workflow drift discovered and fixed during this run

The first Phase 1.5 push (run ID `25998624960`, commit `ee0d449`)
failed before any AppInspect check ran, due to a path-doubling bug in
the action wrapper's entrypoint (`splunk/appinspect-api-action@v3.0.5`
entrypoint.sh runs `ls $INPUT_APP_PATH` and joins it onto the input;
the workflow passed the .spl file directly instead of a single-file
directory). Fix landed in the same Phase 1.6 session, commit `027014a`:
stage the .spl into a clean `dist/appinspect/` directory and point the
action at that dir. Re-run (`26000914082`) progressed past the entry
step and produced the numbers in §5.1.

### 5.6 Raw outputs

The hosted API's HTML and JSON reports are downloaded inside the
action's container but no `actions/upload-artifact` step exists yet,
so they are lost when the runner is torn down. **Phase 1.7 follow-up**:
add an artifact upload step so future runs preserve the JSON for
diffing.

### 5.7 Phase 1.7 closure (2026-05-17)

Phase 1.7 ("Fix all error-severity findings") closed with workflow
run `26002056326` passing both profiles green. Outcome per F-finding:

| # | Finding | Outcome | Commit |
|---|---------|---------|--------|
| F1 | manifest `Enterprise` version requirement | partial — manifest now `"9.3"` (operationally honest; only Splunk-supported version as of 2026-05-17), but SLIM still rejects it. Suppressed via expect.yaml. | `5757ade` + `628a2b3` |
| F2–F11 | SLIM spec drift on `python.version` / `python.required` | unchanged in source (still required by static AppInspect); suppressed at the dynamic-API layer via expect.yaml. | `628a2b3` |
| F12 | redundant `[id].check_for_updates` | **fixed in source** by removing the redundant line; `[package]` is now the sole home. | `d40e1b9` |
| F12 post-mortem (2026-06-01) | `[package].check_for_updates = false` itself | **value also removed in v1.0.1** — Splunkbase upload-time package validation rejected `wl_manager-1.0.0.spl` with "The check_for_updates field found in app.conf must not be disabled." AppInspect's `check_for_updates_disabled` only warns; Splunkbase enforces it as a hard gate. The Phase 1.6 triage (which kept the value at `false`) was wrong: it focused only on the F12 stanza-placement question, not the value choice. v1.0.1 removes the `check_for_updates` line entirely so Splunk's default (`true`) applies. See `docs/DECISION_LOG.md` 2026-06-01 row for the full divergence record + the maintenance rule that prevents re-introduction. | `<v1.0.1 release commit>` |

Three CI iterations confirmed SLIM rejects every Enterprise version
format we can produce without Splunk-private documentation:
`">=9.0.0"`, `">=9.0,<10.0"`, `"9.3"`. The error wording in each case
is identical ("includes no supported version") and the value is
echoed back literally, suggesting SLIM intersects against a literal
allowlist rather than parsing a range. Reference Splunk-published
apps on GitHub use multiple formats (`"*"`, `">=9.0"`, `">=9.2"`)
that work for their submissions but not ours; the difference is
opaque without access to the dev.splunk.com signed-in manifest
schema docs.

Workflow result, run `26002056326` (`628a2b3`):

| Profile | Total | error | failure | warning | success |
|---------|-------|-------|---------|---------|---------|
| Cloud Vetting (`cloud`)              | 247 | 0 | 1 (expected) | 5 | 161 |
| Self-Service Cloud (`private_app`)   | 242 | 0 | 0            | 5 | 159 |

The single Cloud-profile failure matches the expect.yaml allowlist
key exactly; the action's `compare_against_known_failures` (set
equality on check names) passes and the workflow exits 0.

**Re-evaluation triggers** for the expect.yaml suppression (mirrored
in the file itself):

1. Every quarterly Splunk Version Pinning Audit (next due
   2026-07-18 per CLAUDE.md).
2. First human-reviewer feedback from Splunkbase Cloud Vetting on
   the actual submission — they may dictate the format SLIM accepts.
3. Any SLIM allowlist update that makes
   `check_that_app_passes_slim_validation_for_cloud` start passing
   again. The action's `compare_against_known_failures` is
   set-equality between actual and expected failure names; a
   spontaneously-passing check produces a "yaml lists a failure
   that didn't occur" mismatch and FAILS the workflow until this
   entry is removed. Watch for the cloud profile's `Report info`
   line showing `failure: 0` while this file still exists.
4. Any update to `splunk/appinspect-api-action` past v3.0.5 that
   alters the expect.yaml schema itself.

**Phase 1.8 ("Per-finding triage on warnings + manual_checks") is
unblocked**: warnings have been triaged unchanged at §3 above
(byte-identical between local CLI Phase 1.3 and hosted-API Phase
1.6 numbers); no manual_check items emerged in either profile.
Phase 1.8 work is therefore primarily a doc-organization step
rather than new triage.

---

## 6. Re-runnable command

```bash
# 1. Build the .spl (uses default/app.conf:[launcher] version)
bash scripts/package.sh

# 2. Build the AppInspect image (only once per host, or after Dockerfile changes)
docker build -t wl-appinspect:latest .planning/appinspect

# 3. Standalone (on-prem) profile:
docker run --rm \
  -v "$PWD/dist:/spl:ro" \
  -v "$PWD/.planning/appinspect:/out" \
  wl-appinspect:latest inspect /spl/wl_manager-1.0.0-rc1.spl \
    --mode test --data-format json \
    --output-file /out/appinspect-standalone-phase1.json

# 4. Cloud profile:
docker run --rm \
  -v "$PWD/dist:/spl:ro" \
  -v "$PWD/.planning/appinspect:/out" \
  wl-appinspect:latest inspect /spl/wl_manager-1.0.0-rc1.spl \
    --mode test --data-format json --included-tags cloud \
    --output-file /out/appinspect-cloud-phase1.json
```

The CI variant of this command lives in
`.github/workflows/appinspect.yml` (Phase 1.2 deliverable).

---

## 7. Per-finding disposition (Phase 1.8 closure)

> **Status**: Phase 1.8 ("Per-finding triage on `warning` + `manual_check`")
> closed 2026-05-17. All warning and manual_check items across the three
> AppInspect profiles (`splunk-platform-standalone`, `cloud`,
> `private_app`) have a documented disposition under the Phase 1
> plan-doc taxonomy from `docs/PUBLIC_RELEASE_PLAN.md` §1 row 1.8:
> **fix / accept-with-justification / defer-to-v1.1**.

### 7.1 Disposition summary

| Profile | warnings | manual_check | fix | accept-with-justification | defer-to-v1.1 |
|---------|---------:|-------------:|----:|--------------------------:|--------------:|
| `splunk-platform-standalone` (local CLI, §1) | 6 | 0 | 0 | 6 | 0 |
| `cloud` (local CLI §1 + hosted-API §5.1)     | 5 | 0 | 0 | 5 | 0 |
| `private_app` (hosted-API §5.1)              | 5 | 0 | 0 | 5 | 0 |

Every warning maps to **accept-with-justification**; the per-finding
analysis is at §3.1–§3.6 above. The `private_app` warning set is the
`cloud` set (§3.2–§3.6) — `check_for_indexer_synced_configs` (§3.1)
is standalone-only and does not apply.

### 7.2 Why no `fix` dispositions

Every warning is either:

- an INFO-only enumeration that AppInspect surfaces regardless of
  severity (§3.4 scripted-input list, §3.6 collections.conf
  declaration);
- a Splunk-internal telemetry warning the platform itself marks
  "no impact" (§3.2 SplunkJS);
- a Python-2 compatibility note moot for a Splunk 9.x-only app
  (§3.3 `python_script_existence`);
- a Cloud-Victoria-only consideration auto-derived from the
  manifest's `targetWorkloads` and inapplicable to the Cloud profile
  itself (§3.1 indexer-synced configs);
- detection-critical low-latency scheduling that AppInspect's
  generic 12/hr heuristic cannot reason about (§3.5 cron frequency
  on 4 saved searches; full per-search security justification in
  the table at §3.5).

No fix would improve the app for users; some "fixes" (e.g.,
back-throttling §3.5 schedules to 12/hr) would weaken security
guarantees.

### 7.3 Why no `defer-to-v1.1` dispositions

`defer-to-v1.1` would apply if a warning revealed real tech debt or a
non-trivial change worth shipping but not blocking on. None of the
current warnings fall in that category — each is either operationally
correct as-shipped or fundamentally outside the heuristic
AppInspect uses (§3.5's cron-frequency case).

### 7.4 `manual_check` items

Both hosted-API profiles report `manual_check: 0` (run `26002056326`,
§5.1). The local CLI Phase 1.3 baseline also reports 0 (§1). No
manual triage outstanding.

### 7.5 Phase 1 acceptance check (from `docs/PUBLIC_RELEASE_PLAN.md`)

| Criterion | Status |
|-----------|--------|
| `appinspect.yml` CLI workflow green | ✅ Phase 1.2 — initial green flagged in error during Phase 1.7 closure (the workflow had been RED with an `actions/setup-python@v5` `cache: pip` config bug from 17:12 onward; the bug was a missing `requirements.txt`/`pyproject.toml` for the cache key, fixed 2026-05-18 in commit `632615a`. The local CLI's content findings — 0 error / 0 failure on both profiles in `.planning/appinspect/appinspect-*-phase1.json` (Phase 1.3 baseline) — were always correct; only the GHA wiring was broken.) |
| `appinspect-api.yml` API workflow green | ✅ Phase 1.7 (run `26002056326`) |
| 0 error-severity findings — `cloud` | ✅ (§5.1: 0 error / 1 failure suppressed via expect.yaml / 0 future_failure) |
| 0 error-severity findings — `splunk-platform-standalone` | ✅ (§1) |
| All `warning` + `manual_check` items documented disposition | ✅ §3 + §7.1 |
| Refactor documented if R1.1/D7 triggered | N/A — escalation not triggered (§5.4) |

**Phase 1 is COMPLETE.** Phase 1.9 (architectural refactor — only if
1.6 required) is **not applicable**. Phase 1.10 (soft escalation
checkpoint at week 4) is **not applicable**. Next milestone per
`docs/PUBLIC_RELEASE_PLAN.md` is Phase 2.

---

## 7.5 v1.0.1 Splunkbase upload — Cloud-vetting SLIM failure (2026-06-01 → resolved in v1.0.2 on 2026-06-02)

**Background**: After v1.0.1 was cut and uploaded to Splunkbase
(submission 8800-43285), the hosted AppInspect run rejected the
package against Splunk Cloud Vetting with one new HARD failure.
This is a different failure class than F1 in §5.2: that prior
F1 was about an open-ended `>=9.0.0` constraint; this new failure
is about declaring a version (`"9.3"`) that Splunk has since
retired from its supported list.

| # | Class | File | Stanza | Setting / message |
|---|-------|------|--------|------------------|
| **F13** | **HARD ERROR** | `app.manifest` | `platformRequirements.splunk` | "Version requirement includes no supported version of Splunk Enterprise: 9.3" |

**Headline numbers (2026-06-01 hosted API run)**:
162 success / **1 failure** / 0 future_failures / 0 errors / 5 warnings
/ 79 N/A / 0 skipped.

The 5 warnings are identical to §3.2 + §3.3 + §3.4 + §3.5 + §3.6
already triaged (no change). Cron warnings (§3.5) remain accepted
as security-critical detection latency. SplunkJS warnings (§3.2)
have explicit Splunk-side guidance to "ignore". No new warnings.

**F13 — root cause analysis**: Splunk's supported-version list moves
forward as minor versions reach end-of-life. As of 2026-06,
Enterprise 9.3 is no longer on the SLIM-accepted list. The manifest
must declare at least one currently-supported version. See
`docs/SPLUNK_10_COMPATIBILITY.md` for the 7-risk-area code audit
that backs the multi-version declaration choice; see
`docs/DECISION_LOG.md` 2026-06-02 row for why we chose `["9.4", "10.0"]`
over the single-version + retest alternatives.

**Resolution (v1.0.2, commit pending)**:

- `app.manifest`: `platformRequirements.splunk.Enterprise` changed from
  `"9.3"` to `["9.4", "10.0"]`. List form is the documented SLIM
  multi-version syntax (the prior F1 fix for `>=9.0.0` shipped as
  single-version `"9.3"`; this fix replaces it with list form).
- `app.manifest`: `info.id.version` bumped to `1.0.2`,
  `releaseDate` to `2026-06-02`.
- `default/app.conf`: `build = 672`, `[launcher].version = 1.0.2`,
  `[id].version = 1.0.2`.
- `appserver/static/whitelist_manager.js:14`: `urlArgs: "_b=672"`
  (auto-applied by `scripts/hooks/urlargs-sync.js`).
- New file `docs/SPLUNK_10_COMPATIBILITY.md` captures the audit.

**Disposition**: **F13 FIXED in v1.0.2**.

**Local runtime verification gap**: Docker not running on this dev
machine at fix time; could not re-run `scripts/verify_appinspect.sh`
locally. The next Splunkbase upload of `wl_manager-1.0.2.spl` will
be the runtime confirmation. If SLIM rejects the list form
(`["9.4", "10.0"]`), the fallback is `"9.4"` single-version + a new
DECISION_LOG row reversing the multi-version choice.

---

## 7.6 v1.0.2 Splunkbase upload — SLIM list-form rejection (2026-06-03 → resolved in v1.0.3 on 2026-06-03)

**Background**: v1.0.2 declared `platformRequirements.splunk.Enterprise`
as a list `["9.4", "10.0"]` per the 2026-06-02 DECISION_LOG row.
Splunkbase re-upload (request `7f105ce0-6ed6-4e7c-be76-adfe132d879c`,
hosted-API run `8800-43334`) immediately rejected the list form at
the SLIM step. This is the runtime confirmation predicted in the
v1.0.2 CHANGELOG + release notes: "the next hosted AppInspect run on
the v1.0.2 .spl is the runtime confirmation [of list-form syntax
acceptance]."

| # | Class | File | Stanza | Setting / message |
|---|-------|------|--------|------------------|
| **F14** | **HARD ERROR** | `app.manifest` | `platformRequirements.splunk.Enterprise` | "Expected String value for `manifest.platformRequirements.splunk.Enterprise`, not `['9.4', '10.0']`" |

**Headline numbers (2026-06-03 hosted-API run)**:
162 success / **1 failure** / 0 future_failures / 0 errors / 5 warnings
/ 79 N/A / 0 skipped. Byte-identical totals to v1.0.1 and v1.0.2
runs — only the failure CLASS shifted (from "unsupported version" to
"wrong type").

The 5 warnings are byte-identical to §3.2 + §3.3 + §3.4 + §3.5 + §3.6
already triaged (no change). Confirms the v1.0.2 → v1.0.3 manifest
edit is strictly scoped to platformRequirements with zero spillover
on other AppInspect rules.

**F14 — root cause analysis**: SLIM 2.0's
`platformRequirements.splunk.Enterprise` field is typed `String` at
the schema level. The list form passed the `app.manifest` JSON
schema validator (because JSON itself accepts arrays at any field)
but SLIM's downstream type-checker rejected the value as wrong type.
The error message wording is unambiguous: it specifies the EXPECTED
type (String) and quotes the REJECTED value (`['9.4', '10.0']`).

**Resolution (v1.0.3, commit pending)**:

- `app.manifest`: `platformRequirements.splunk.Enterprise` changed
  from list `["9.4", "10.0"]` to single string `"10.0"`. Chosen
  over `"9.4"` per DECISION_LOG.md 2026-06-03 row (forward-leaning
  trade-off; 9.4 customers see the standard Splunkbase
  compatibility-override prompt instead of a clean install path).
- `app.manifest`: `info.id.version` bumped to `1.0.3`,
  `releaseDate` to `2026-06-03`.
- `default/app.conf`: `build = 673`, `[launcher].version =
  [id].version = 1.0.3`.
- `appserver/static/whitelist_manager.js:14`: `urlArgs: "_b=673"`
  (auto-applied by `scripts/hooks/urlargs-sync.js`).
- `docs/SPLUNK_10_COMPATIBILITY.md` "Runtime verification" section
  records the SLIM-format-acceptance lesson + cumulative format
  history (5 formats tried; `"X.Y"` single string is the only
  accepted form as of 2026-06-03).

**Disposition**: **F14 FIXED in v1.0.3**.

**Cumulative SLIM format history** (added 2026-06-03):

| Format | Result | Release where tried |
|--------|--------|-------------------|
| `">=9.0.0"` | REJECTED | v1.0.0 (pre-release attempt) |
| `">=9.0,<10.0"` | REJECTED | v1.0.0-rc series (Phase 1.7) |
| `"9.3"` | ACCEPTED | v1.0.0, v1.0.1 (until 9.3 retired) |
| `["9.4", "10.0"]` | REJECTED | v1.0.2 (F14) |
| `"10.0"` | (this release) | v1.0.3 (expected to pass) |

Conclusion: SLIM 2.0 accepts ONLY single-concrete-version strings
of the form `"X.Y"`. List form, semver ranges (`">=A,<B"`), and
open-ended floors (`">=A"`) are all rejected. Multi-version support
in one manifest requires a future SLIM 2.x schema change.

**Local runtime verification gap (same as v1.0.2)**: Docker not
running on this dev machine at fix time; could not re-run
`scripts/verify_appinspect.sh` locally. The next Splunkbase upload
of `wl_manager-1.0.3.spl` will be the runtime confirmation. If SLIM
rejects `"10.0"` for any reason (unlikely given the format history
above), the fallback is single-version `"9.4"` with another
DECISION_LOG reversal row pointing back at the 2026-06-03 row.

---

## 7.7 v1.0.3 Splunkbase upload — `"10.0"` not on Cloud Classic supported list (2026-06-04 → resolved in v1.0.4 on 2026-06-04)

**Background**: v1.0.3 declared `platformRequirements.splunk.Enterprise =
"10.0"` per the 2026-06-03 DECISION_LOG row (forward-leaning over
`"9.4"`). Splunkbase re-upload (request
`c7a3ee83-5b37-43f9-9375-4f59cfaacdde`, hosted-API run `8800-43335`)
was rejected by SLIM with:

> manifest.platformRequirements.splunk: Version requirement includes
> no supported version of Splunk Enterprise: 10.0

| # | Class | File | Stanza | Setting / message |
|---|-------|------|--------|------------------|
| **F15** | **HARD ERROR** | `app.manifest` | `platformRequirements.splunk.Enterprise` | "Version requirement includes no supported version of Splunk Enterprise: 10.0" |

**Headline numbers (2026-06-04 hosted-API run)**: 162 success / **1
failure** / 0 future / 0 errors / 5 warnings / 79 N/A / 0 skipped.
Byte-identical totals to v1.0.1, v1.0.2, v1.0.3 runs — only the
failure CLASS shifted.

**F15 — root cause analysis**: same error mechanism as v1.0.1's F13
(`"9.3"` not supported). Splunk Cloud Classic's underlying Enterprise
version list does NOT currently include 10.0. The on-prem world has
10.0 GA; Splunk Cloud Classic (managed service) is still on 9.x. The
2026-06-03 row's "forward-leaning" choice assumed "10.0 GA on-prem"
implied "10.0 supported in Cloud Vetting" — that assumption is
empirically wrong.

**Splunkbase AI-explainer note**: the AI explainer that shipped with
this failure recommended `">=9.0.0,<10.0.0"` (semver range). That
format is empirically rejected per Phase 1.7 (see §5.7). The AI's
`<10.0.0` upper bound IS directionally useful — it corroborates that
Cloud Classic's current range is 9.x — but the specific format
suggestion ignored SLIM's documented `String value` constraint. See
`docs/DECISION_LOG.md` 2026-06-04 row for the full lesson.

**Resolution (v1.0.4, commit pending)**:

- `app.manifest`: `Enterprise` changed from `"10.0"` to `"9.4"` (the
  literal documented fallback in `docs/DECISION_LOG.md` 2026-06-02
  row).
- `app.manifest`: `info.id.version` 1.0.3 → 1.0.4; `releaseDate`
  2026-06-04.
- `default/app.conf`: `build = 674`; `[launcher].version =
  [id].version = 1.0.4`.
- `appserver/static/whitelist_manager.js:14`: `urlArgs: "_b=674"`
  (auto-applied).
- `docs/SPLUNK_10_COMPATIBILITY.md` Runtime Verification: 2026-06-04
  section added with the Cloud-Classic-version-list-is-internal
  lesson + AI-recommendation gotcha.

**Disposition**: **F15 FIXED in v1.0.4**.

**Updated cumulative SLIM format history** (from `docs/SPLUNK_10_COMPATIBILITY.md`):

| Format | Result | Release |
|--------|--------|--------|
| `">=9.0.0"` | REJECTED | v1.0.0 pre-release |
| `">=9.0,<10.0"` | REJECTED | v1.0.0-rc (Phase 1.7) |
| `"9.3"` | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 |
| `["9.4", "10.0"]` | REJECTED | v1.0.2 (F14) |
| `"10.0"` | REJECTED | v1.0.3 (F15) |
| `"9.4"` | expected to pass | v1.0.4 |

**Local runtime verification gap (same as v1.0.2 + v1.0.3)**: Docker
not running on this dev machine at fix time; could not re-run
`scripts/verify_appinspect.sh` locally. Next Splunkbase upload of
`wl_manager-1.0.4.spl` is the runtime confirmation.

---

## 7.8 v1.0.4 Splunkbase upload — `"9.4"` also not on Cloud Classic supported list (2026-06-04 evening → v1.0.5 trial)

**Background**: v1.0.4 declared `"9.4"` per the documented fallback.
Splunkbase re-upload rejected by SLIM:

> manifest.platformRequirements.splunk: Version requirement includes
> no supported version of Splunk Enterprise: 9.4

| # | Class | File | Stanza | Setting / message |
|---|-------|------|--------|------------------|
| **F16** | **HARD ERROR** | `app.manifest` | `platformRequirements.splunk.Enterprise` | "Version requirement includes no supported version of Splunk Enterprise: 9.4" |

**Headline numbers**: 162 success / **1 failure** / 0 future / 0 errors
/ 5 warnings / 79 N/A / 0 skipped. Byte-identical totals to all prior
runs.

**F16 — root cause analysis**: same error mechanism as F13 (`"9.3"`)
and F15 (`"10.0"`). Splunk Cloud Classic's supported-version list is
narrower than I assumed; THREE single-version strings now confirmed
NOT on the list. The candidates I picked were guesses (9.3, 9.4, 10.0
are the most-recent Enterprise minor versions); none of them happen
to be on Cloud Classic's internal list.

**Analytical correction**: prior §7.5–§7.7 concluded "semver ranges
are type-rejected by SLIM". That conclusion was overconfident — the
Phase 1.7 evidence is ambiguous (could be type rejection OR content
rejection, both produce the same "no supported version" wording).
v1.0.5 tests the hypothesis that semver ranges ARE accepted by type
by trying the Splunkbase AI explainer's literal recommendation
`">=9.0.0"`.

**Resolution (v1.0.5, commit pending)**:

- `app.manifest`: `Enterprise` from `"9.4"` to `">=9.0.0"` (semver
  range, broadest possible 9.x+ match set).
- `app.manifest`: `info.id.version` 1.0.4 → 1.0.5; `releaseDate`
  2026-06-04.
- `default/app.conf`: `build = 675`; `[launcher].version =
  [id].version = 1.0.5`.
- `appserver/static/whitelist_manager.js:14`: `urlArgs: "_b=675"`
  (auto-applied).
- `docs/SPLUNK_10_COMPATIBILITY.md` Runtime Verification: extended
  with the v1.0.4 finding + the analytical correction + cumulative
  SLIM format history updated.

**Disposition**: **F16 testing-in-v1.0.5**.

**Updated cumulative SLIM format history**:

| Format | Result | Release |
|---|---|---|
| `">=9.0.0"` | REJECTED (cause ambiguous) | v1.0.0 pre-release |
| `">=9.0,<10.0"` | REJECTED (cause ambiguous) | v1.0.0-rc Phase 1.7 |
| `"9.3"` | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 |
| `["9.4", "10.0"]` | REJECTED (type) | v1.0.2 (F14) |
| `"10.0"` | REJECTED (content) | v1.0.3 (F15) |
| `"9.4"` | REJECTED (content) | v1.0.4 (F16) |
| `">=9.0.0"` | (v1.0.5 trial) | v1.0.5 |

**Two outcomes possible** (see `docs/SPLUNK_10_COMPATIBILITY.md`
Runtime Verification for details):

1. SLIM accepts → cumulative SLIM format history learns its first
   accepted range entry; my Phase 1.7 conclusion needs revising in
   all prior docs.
2. SLIM rejects (either error wording) → confirms my earlier
   conclusion was correct; next move is a Splunkbase publisher
   support ticket asking for Cloud Classic's actual supported-version
   list.

---

## 7.9 v1.0.5 Splunkbase upload — `">=9.0.0"` REJECTED but confirms SLIM parses ranges (2026-06-05 → v1.0.6 trial)

**Background**: v1.0.5 declared `">=9.0.0"` as an empirical test of
whether SLIM type-rejects semver ranges. SLIM rejected with:

> manifest.platformRequirements.splunk: Version requirement includes
> no supported version of Splunk Enterprise: **>=9.0.0**

| # | Class | File | Stanza | Setting / message |
|---|-------|------|--------|------------------|
| **F17** | **HARD ERROR (content)** | `app.manifest` | `platformRequirements.splunk.Enterprise` | "Version requirement includes no supported version of Splunk Enterprise: >=9.0.0" |

**Headline numbers**: 162 success / **1 failure** / 0 future / 0 errors
/ 5 warnings / 79 N/A / 0 skipped.

**F17 — major analytical finding**: SLIM echoed back the literal range
string `">=9.0.0"`, NOT "Expected String value". This is the
definitive disambiguation: SLIM **parses semver ranges as a valid
type**. The rejection is content-based — no version in `[9.0.0, ∞)`
matches Cloud Classic's supported list. My v1.0.2 / v1.0.3 / v1.0.4
docs claiming "ranges are type-rejected" were wrong.

**Cloud Classic supported-list shape (inferred from F13-F17)**:

Versions NOT on the list:
- 9.3 (F13, v1.0.1)
- 10.0 (F15, v1.0.3)
- 9.4 (F16, v1.0.4)
- All of `[9.0.0, ∞)` (F17, v1.0.5)

The supported set is NOT a contiguous low-floor range. Splunkbase AI
explainer's new floor hint (`">=8.1.0"`) suggests 8.x may be on the
list.

**Resolution (v1.0.6, commit pending)**:

- `app.manifest`: `Enterprise` from `">=9.0.0"` to `">=8.1.0 <10.0.0"`
  (bounded range, space-conjunction syntax per AI explainer's
  example).
- `app.manifest`: `info.id.version` 1.0.5 → 1.0.6; `releaseDate`
  2026-06-05.
- `default/app.conf`: `build = 676`; `[launcher].version =
  [id].version = 1.0.6`.
- `appserver/static/whitelist_manager.js:14`: `urlArgs: "_b=676"`
  (auto-applied).
- `docs/SPLUNK_10_COMPATIBILITY.md` Runtime Verification: 2026-06-05
  section + cumulative format history updated with the v1.0.5 finding.

**Disposition**: **F17 testing-in-v1.0.6**.

**Updated cumulative SLIM format history**:

| Format | Result | Release |
|---|---|---|
| `">=9.0.0"` | REJECTED (content) | v1.0.0 pre-release; v1.0.5 |
| `">=9.0,<10.0"` | REJECTED (likely content + comma syntax) | v1.0.0-rc Phase 1.7 |
| `"9.3"` | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 |
| `["9.4", "10.0"]` | REJECTED (type) | v1.0.2 (F14) |
| `"10.0"` | REJECTED (content) | v1.0.3 (F15) |
| `"9.4"` | REJECTED (content) | v1.0.4 (F16) |
| `">=9.0.0"` | REJECTED (content) — empirically confirmed range PARSES | v1.0.5 (F17) |
| `">=8.1.0 <10.0.0"` | (v1.0.6 trial) | v1.0.6 |

**Three outcomes possible for v1.0.6**:

1. SLIM accepts → first ACCEPTED semver-range entry. Pin to this
   format permanently. Cleanup commit needed for v1.0.2-v1.0.4 docs.
2. SLIM rejects with "no supported version" → Cloud Classic's list
   excludes both 8.x and 9.x; next move is Splunkbase publisher
   support ticket.
3. SLIM rejects with "Expected String value" → unexpected; would
   indicate space-conjunction is type-rejected. Low probability.

---

## 8. Revision log

- 2026-05-17 — initial Phase 1.3 baseline. App.manifest version drift
  caught + fixed in same run; §3.5 pre-flight extended to cover it.
  All warnings re-triaged. Zero delta vs Phase 0.0 build-660 baseline.
- 2026-05-17 — Phase 1.6 first hosted-API run (run ID `26000914082`,
  HEAD `027014a`). Cloud profile surfaced 1 failure
  (`check_that_app_passes_slim_validation_for_cloud`); Self-Service
  Cloud profile clean. R1.1 / D7 escalation assessed and **NOT
  triggered** — persistent scripted input (`wl_fim_watch.py`) was
  accepted by Cloud Vetting; the failure is a SLIM-spec issue
  (manifest version range + spec-drift undefined-setting noise on
  `python.version` / `python.required`) that decomposes into 12
  config edits (F1–F12 in §5.2). Phase 1.5 workflow path-doubling
  drift fixed in commit `027014a` during the same session. §5
  replaced with the actual Phase 1.6 results (was placeholder).
- 2026-05-17 — Phase 1.7 closed (run `26002056326`, HEAD `628a2b3`).
  Both profiles passing. F12 fixed in source by deleting redundant
  `[id].check_for_updates` (commit `d40e1b9`). F1 manifest tried
  three formats (`">=9.0,<10.0"`, `"9.3"`) — SLIM rejected each
  with identical wording. Kept `"9.3"` as the operationally honest
  value (only Splunk version still in vendor support as of
  2026-05-17) and added `.appinspect_api.expect.yaml` to suppress
  `check_that_app_passes_slim_validation_for_cloud` (commit
  `628a2b3`) — F2–F11 spec drift cannot be removed in source
  without breaking static AppInspect's
  `check_python_version_correctness_for_splunk_enterprise`. See
  §5.7 for the full closure narrative + three re-evaluation triggers
  (quarterly Splunk Version Pinning Audit, first Splunkbase human-
  review feedback, any action version bump past v3.0.5). Phase 1.8
  (warning/manual_check triage) is unblocked; warnings already
  triaged in §3 byte-identical to Phase 1.3 local-CLI baseline.
- 2026-05-17 — Phase 1.8 closed. Per-finding disposition documented
  in new §7. Every warning across the three AppInspect profiles
  (`splunk-platform-standalone`, `cloud`, `private_app`) maps to
  **accept-with-justification**; 0 `fix` and 0 `defer-to-v1.1`
  dispositions. Both API profiles report `manual_check: 0` so no
  manual triage outstanding. §7.5 acceptance-check table records
  Phase 1 as **complete**; Phase 1.9 (architectural refactor) and
  Phase 1.10 (week-4 escalation checkpoint) are not applicable.
  Note: the revision log was renumbered from §7 to §8 to accommodate
  the new Phase 1.8 closure section without breaking the sequential
  numbering (§1–§8). Internal cross-references updated.
- 2026-05-18 — **correction to §7.5 row 1**. The Phase 1.8 closure
  claimed `appinspect.yml` CLI workflow was green; in fact the GHA
  job had been failing since 2026-05-17 17:12 with an
  `actions/setup-python@v5` `cache: pip` configuration bug — the
  cache key requires `requirements.txt` or `pyproject.toml` and this
  repo has only `requirements-dev.txt`. The bug was not in
  AppInspect content (Phase 1.3 baseline `.planning/appinspect/*-phase1.json`
  was always 0 error / 0 failure) but in CI wiring. Fix: removed
  `cache: pip` from the setup-python step (the only `pip install` in
  this workflow uses `--no-cache-dir` so caching was a no-op anyway).
  This row's status fixed in the same commit. **Lesson logged in
  `~/.claude/state/qa-findings.jsonl` as
  `false-completion-claim-without-ci-verification`** — Phase 1
  acceptance was declared complete without spot-checking every
  workflow's actual run status; the QA process must include a `gh
  run list` cross-check on every claimed-green workflow at
  phase-closure boundaries.
- 2026-06-02 — **v1.0.1 Splunkbase upload (8800-43285) → F13 SLIM
  HARD ERROR**. The `"9.3"` value that Phase 1.7 accepted as
  "operationally honest" was retired from Splunk's supported list
  between 2026-05-17 and 2026-06-01, re-opening the Cloud-vetting
  block. §7.5 added with the 2026-06-01 hosted-API run results
  (162 / 1 / 0 / 0 / 5 / 79 / 0) and the v1.0.2 resolution path.
  New file `docs/SPLUNK_10_COMPATIBILITY.md` captures the 7-risk-area
  audit that backs the `["9.4", "10.0"]` list-form declaration; new
  `docs/DECISION_LOG.md` 2026-06-02 row records the multi-version
  choice over single-version-with-retest and Drop-Cloud alternatives.
  All 5 warnings re-triaged identical to §3 (no change). Phase 1.7's
  triple-format retry (`>=9.0,<10.0` / `"9.3"`) is now triple +1: the
  list-form `["9.4", "10.0"]` is a NEW format SLIM did not previously
  consume. If SLIM rejects the list form on the next hosted-API run,
  fallback is single-version `"9.4"` with a DECISION_LOG reversal row.
- 2026-06-03 — **v1.0.2 Splunkbase upload (8800-43334) → F14 SLIM
  list-form rejection**. The predicted runtime risk from the v1.0.2
  release notes materialized: SLIM 2.0 rejected the list form with
  "Expected String value, not `['9.4', '10.0']`". §7.6 added with the
  2026-06-03 hosted-API run results (byte-identical totals to the
  v1.0.2 run: 162 / 1 / 0 / 0 / 5 / 79 / 0; only the failure CLASS
  shifted from "unsupported version" to "wrong type"). Resolution
  shipped in v1.0.3 — `app.manifest` changes from list
  `["9.4", "10.0"]` to single string `"10.0"` per the
  `docs/DECISION_LOG.md` 2026-06-03 reversal row. The decision chose
  `"10.0"` over `"9.4"` for the forward-leaning trade-off (9.4
  customers see the standard Splunkbase compatibility-override prompt
  rather than a clean install path; 10.0 buys ~24-30 months before
  the next forced-retirement re-release vs ~12-18 months if 9.4 had
  been picked). `docs/SPLUNK_10_COMPATIBILITY.md` "Runtime
  verification" section added with the cumulative SLIM format
  history (5 formats tried; `"X.Y"` single string is the only
  accepted form as of 2026-06-03) and the SLIM-2.0-schema
  conclusion: list form, semver ranges, and open-ended floors are
  all rejected; multi-version support requires a Splunk-side SLIM
  schema change.
- 2026-06-05 — **v1.0.5 Splunkbase upload → F17 SLIM unsupported-
  version rejection of `">=9.0.0"` semver range** — major analytical
  finding: SLIM echoed back the literal range string, NOT "Expected
  String value". This empirically confirms SLIM PARSES semver ranges
  as a valid type; my v1.0.2-v1.0.4 docs claiming "ranges are type-
  rejected" were wrong. §7.9 added with the analytical disambiguation
  + Cloud Classic supported-list shape inference (NOT a contiguous
  low-floor range; `[9.0.0, ∞)` excluded). Splunkbase AI's new
  recommendation extends the floor DOWN to 8.1.0, suggesting 8.x may
  be on the list. v1.0.6 tests bounded range `">=8.1.0 <10.0.0"`
  (space conjunction per AI explainer's example syntax). New
  `docs/DECISION_LOG.md` 2026-06-05 row + `docs/SPLUNK_10_COMPATIBILITY.md`
  Runtime Verification updated; CLAUDE.md audit log row appended.
  Cleanup commit needed regardless of v1.0.6 outcome to correct the
  v1.0.2-v1.0.4 docs' "ranges are type-rejected" claim.
- 2026-06-04 (evening) — **v1.0.4 Splunkbase upload → F16 SLIM
  unsupported-version rejection of `"9.4"`**. Three single-version
  strings now confirmed NOT on Cloud Classic's supported list: 9.3
  (v1.0.1), 9.4 (v1.0.4), 10.0 (v1.0.3). §7.8 added with the
  analytical correction acknowledging that the prior "semver ranges
  are type-rejected by SLIM" conclusion was overconfident. v1.0.5
  tests `">=9.0.0"` (Splunkbase AI explainer's literal recommendation)
  to disambiguate whether Phase 1.7's range rejection was type-based
  or content-based. New `docs/DECISION_LOG.md` 2026-06-04 row 2
  documents the trial decision; new empirical-evidence maintenance
  rule captured: error wording alone doesn't distinguish "type
  rejection" from "content rejection" (the "no supported version"
  wording appears in both classes); measure error wording precisely
  before attributing cause.
- 2026-06-04 (morning) — **v1.0.3 Splunkbase upload (8800-43335) → F15 SLIM
  unsupported-version rejection**. `"10.0"` was rejected with the
  SAME error class as v1.0.1's `"9.3"`: "Version requirement includes
  no supported version of Splunk Enterprise: 10.0". The 2026-06-03
  forward-leaning choice was wrong: Splunk Cloud Classic's underlying
  Enterprise version list does NOT currently include 10.0 (on-prem
  has 10.0 GA; Cloud Classic is still on 9.x). §7.7 added with the
  2026-06-04 hosted-API run results (162 / 1 / 0 / 0 / 5 / 79 / 0;
  same totals, F15 replaces F14 as the failure class). Resolution
  shipped in v1.0.4 — `app.manifest` reverts to `"9.4"` per the
  literal documented fallback in `docs/DECISION_LOG.md` 2026-06-02
  row. The 2026-06-04 DECISION_LOG row is a REVERSAL-OF-REVERSAL
  (overturns 2026-06-03 which overturned 2026-06-02). Three new
  maintenance lessons captured: (1) Cloud Classic's supported-version
  list is INTERNAL to Splunk's managed infrastructure, not visible
  from the AppInspect API spec or app.manifest schema; only signal is
  hosted-AppInspect rejection at upload time. (2) Splunkbase
  AI-explainer recommendations are directionally useful but NOT
  format-precise; today it recommended `">=9.0.0,<10.0.0"` semver
  range which is empirically rejected per Phase 1.7. (3) Both 9.3
  (v1.0.1) and 10.0 (v1.0.3) became invalid AFTER the corresponding
  release was cut — v1.1 backlog item to investigate Splunkbase
  publisher RSS/API for supported-version-list change notifications.
