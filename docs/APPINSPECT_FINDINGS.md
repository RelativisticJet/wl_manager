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

**Zero drift.** Every code change between build 660 and the
1.0.0-rc1 candidate (Phase 0 docs migration, R6-F8 KV-presence
migration, §5a items: FUNDING.yml stub + gitleaks workflow + SSH tag
signing docs) is AppInspect-neutral.

The reason: every change either lived in `docs/`, `.github/`, or
`tests/` (all excluded from the `.spl` by `scripts/package.sh`), or
touched runtime code in `bin/` without introducing a new AppInspect
trigger (KV-store usage was already declared in `collections.conf`
before the migration).

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

**F12 — root cause analysis**: `default/app.conf [id]` is missing
`check_for_updates`. The setting is optional in static AppInspect but
SLIM treats its absence as undefined (vs. the explicit
`check_for_updates = false` Splunk recommends for Cloud apps that
should not auto-update via the in-product update mechanism). One-line
fix in Phase 1.7.

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

## 7. Revision log

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
