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

## 5. Open items for Phase 1.5 / 1.6 (Cloud API + dynamic checks)

Static AppInspect (this run) is the input to Phase 1.5
(`splunk/appinspect-api-action` wiring) and Phase 1.6 (first API run).
The API stage performs container boot + runtime checks the local CLI
cannot do. Expected surfaces of concern, in order of likelihood:

1. **Persistent scripted inputs**. `bin/wl_fim_watch.py` runs with
   `interval = 0` (long-running daemon). Cloud Vetting historically
   has restrictions on persistent processes. This is the single biggest
   remaining unknown — call it out explicitly in the Phase 1.6 triage
   pass.
2. **Outbound network calls**. The handler talks to `localhost:8089`
   for the audit-emission `simpleRequest` call. Loopback is normally
   permitted, but Cloud Vetting may treat `splunk.rest.simpleRequest`
   differently than direct socket usage. Confirm in 1.6.
3. **CycloneDX SBOM file (`*.cdx.json`)** sits next to the .spl, not
   inside it. Splunkbase upload accepts it as a sibling. Phase 1.5
   workflow may need an explicit upload step.

None of these are *expected* to fail; they are the surfaces where
expected and actual could plausibly diverge. The plan-doc D7 escalation
clause (Phase 1 week 4) governs if any of these turn out to be hard
blockers.

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
