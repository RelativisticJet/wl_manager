# Phase 0.0 — AppInspect De-risk Run

> **Status**: Complete (2026-05-13).
> **Verdict**: Phase 1 effort class = **TRACTABLE** (1-2 weeks per the optimistic
> envelope in `docs/PUBLIC_RELEASE_PLAN.md` §4). NO D7 escalation triggered.
> Proceed with the rest of Phase 0.

---

## 1. Goal

Per Phase 0.0 in `docs/PUBLIC_RELEASE_PLAN.md`: install `splunk-appinspect`
locally and run against the current `.spl` with both `cloud` and
`splunk-platform-standalone` profiles. Surface the Cloud-cert refactor
scope (the single biggest unknown in the public-release plan, risk R1.1)
**BEFORE** committing the rest of Phase 0.

If findings are catastrophic → escalate to user per D7 (NO auto-fallback).
If findings are tractable → proceed.

---

## 2. Methodology + caveats

### How

- `splunk-appinspect` 4.2.0 installed in Docker (`python:3.11-slim` +
  `libmagic1`). Image tag `wl-appinspect:latest`. Reusable Dockerfile at
  `.planning/appinspect/Dockerfile`.
- Local Python 3.14 was insufficient: no pre-built wheels for
  `splunk-appinspect`'s transitive deps (`pillow`, `lxml`) on 3.14 yet,
  and source build failed in pip's dep resolver. **Phase 1.2 CI workflow
  should pin the GitHub Actions runner to Python 3.11 or 3.12.**
- `.spl` rebuilt with comprehensive exclusion list before final runs
  (see §3 for details — the unmodified `scripts/package.sh` produced a
  dirty `.spl` that masked real findings; this is a separate Phase 0.11
  task captured in §6).
- Raw outputs (`.json`) at:
  - `.planning/appinspect/appinspect-standalone-clean.json`
  - `.planning/appinspect/appinspect-cloud-clean.json`
  - First-pass dirty runs (for reference): `appinspect-standalone.json`,
    `appinspect-cloud.json`.

### Tag mapping

The local CLI exposes these tags (242–249 checks total):

| Local tag         | Maps to Splunk cert |
|-------------------|--------------------|
| `cloud`           | Splunk Cloud Vetting (static stage) |
| (no tag filter)   | Splunk Platform Standalone (on-prem) |
| `private_app`     | Self-Service Cloud |
| `private_classic` | Self-Service Classic stack |
| `private_victoria`| Self-Service Victoria stack |
| `migration_victoria` | Victoria migration audit |

The on-prem cert tag in the AppInspect HTTP API is documented as
`splunk_platform_standalone`, but that tag is NOT exposed by the local
CLI in 4.2.0. The default (no-filter) run is the local equivalent.

### What this DOES NOT cover

1. **Dynamic / runtime checks.** AppInspect API performs a live container
   boot for Cloud Vetting (network call detection, runtime memory, etc.).
   Static-only finds **packaging + config + Python AST** issues. Runtime
   issues with `wl_fim.py` / `wl_fim_watch.py` / `wl_expiration_cleanup.py`
   could still surface in Phase 1.6 (first AppInspect API run).
2. **Manual-review checks.** Cloud Vetting also has a human-reviewed
   stage for the first submission to Splunkbase under any account; that
   process can surface issues outside AppInspect's automated checks.

These remain real (but smaller) risk surfaces. They're sized as
"low-moderate" — not catastrophic — based on the static signal below.

---

## 3. The clean-build correction (separate Phase 0.11 task)

The first `scripts/package.sh` run produced a dirty `.spl` (20 MB) that
contained:

- Dot-prefix dev directories not in the exclude list:
  `.playwright-mcp`, `.mutmut-cache`, `.firecrawl`, `.audit`, `.planning`,
  `.zap`, `.hypothesis`, `.coverage`, `.graphifyignore`, `.mcp.json.example`
- `node_modules/` (Playwright test deps — 15 MB; ~75% of total size)
- `htmlcov/` (pytest-cov HTML reports)
- `bench_results/`, `test-results/` (E2E artifacts)
- ~30 PNG screenshots at the app root (verification artifacts)

AppInspect's `check_that_extracted_splunk_app_does_not_contain_prohibited_directories_or_files`
failed on the dot-prefix entries, which **gates many downstream checks**:
the dirty `.spl` reported 237 skipped / 8 success / 2 failures and looked
"surprisingly clean". After cleanup (`.spl` size 20 MB → 5 MB), the same
profiles reported 153 success / 1 failure / 9 warnings / 3 future_failure
(see §4).

**Lesson**: `package.sh` uses a denylist for excludes; this drifts as new
dev tooling is added. Fix in Phase 0.11 (in scope per
`PUBLIC_RELEASE_PLAN.md` §3 task 0.11 "scripts/package.sh version-tag
drift"): switch to an allowlist or add a `*/.*` glob. Until then, every
release must double-check `tar -tzf` output for surprise dirs.

---

## 4. Findings against clean `.spl`

### Headline numbers (clean run)

| Result class    | Standalone (249 total) | Cloud (242 total) |
|-----------------|------------------------|-------------------|
| success         | 153                    | 150               |
| not_applicable  | 83                     | 80                |
| skipped         | 0                      | 0                 |
| warning         | 9                      | 8                 |
| failure         | 1                      | 1                 |
| future_failure  | 3                      | 3                 |
| error           | 0                      | 0                 |

**Zero errors. One failure. Three future-failures. All trivial.**

### 4.1 Failure (both profiles, 1 instance)

**`check_version_is_valid_semver`** — version mismatch across files:

- `default/app.conf` `[launcher] version = 2.0.0`
- `app.manifest` `info.id.version = "1.0.0"`
- No `[id]` stanza in `default/app.conf`

**Fix**: align all three. Phase 0.8 (`app.conf:version` bump to
`1.0.0-rc1`) will fix this anyway. Effort: **5 min** (single Edit each).

### 4.2 Future-failures (both profiles, 3 instances each)

All three are the same pattern: replace deprecated `python.version =
python3` with `python.required = python3` (Splunk Enterprise 10.2+).

| Check                                          | File              | Stanzas |
|------------------------------------------------|-------------------|---------|
| `check_scripted_inputs_python_required`        | `default/inputs.conf`   | 3 (`wl_expiration_cleanup`, `wl_fim`, `wl_fim_watch`) |
| `check_commands_conf_python_required`          | `default/commands.conf` | 1 (`wlexpiringsoon`) |
| `check_script_restmap_conf_python_required`    | `default/restmap.conf`  | 1 (`script:wl_manager_handler`) |

**Fix**: 5 stanzas across 3 files. Replace `python.version = python3`
with `python.required = python3` (and optionally keep both for backward
compat with Splunk ≤9.x — but check whether the app's minimum Splunk
version in `app.conf` allows dropping `python.version` entirely). Effort:
**15 min**.

### 4.3 Warnings (9 standalone / 8 cloud)

| # | Check | Severity assessment | Recommended action |
|---|-------|---------------------|--------------------|
| W1 | `check_scripted_inputs_cmd_path_pattern` (3 stanzas) | Cosmetic — best practice suggests `$SPLUNK_HOME/etc/apps/AppName/bin/` over `./bin/`. Both work. | Defer or fix opportunistically. |
| W2 | `check_for_indexer_synced_configs` (Victoria, standalone-only) | `default/inputs.conf` doesn't sync to indexers on Victoria. | Already correct — scripted inputs run on the search head only. Add a comment in `inputs.conf` explaining. |
| W3 | `check_for_splunk_js` (8 instances) | **Telemetry warning. Message literally says "Please ignore this warning as it has no impact to your Splunk app."** | IGNORE. |
| W4 | `check_for_python_script_existence` | Informational — "24 Python files found, must be cross-compat with Python 2 and 3 for Splunk Enterprise 8.0." | Check target Splunk version in `app.manifest` (currently no min set). If min is 8.x, this is real work. If min is 9.0+, ignore — Py2 is gone. **DECISION POINT.** |
| W5 | `check_for_scripted_inputs` | Informational enumeration ("No action required"). | IGNORE. |
| W6 | `check_for_gratuitous_cron_scheduling` (4 saved searches) | Real concern — searches scheduled >12 times/hour. Affected: `wl_csv_external_modification_alert`, `wl_csv_modification_attribution`, `wl_saved_search_timebomb_monitor`, `wl_deploy_window_opened_during_lockdown`. | Review each. Some (`wl_csv_external_modification_alert`) are intentional 5-min runs per `CLAUDE.md` Decision Log entry 2026-04-23. Document justification. |
| W7 | `check_for_valid_package_id` | No `[id]` stanza in `app.conf`. | Same as failure 4.1 — fix together. |
| W8 | `check_collections_conf` | Informational ("No action required"). | IGNORE. |
| W9 | `check_hostnames_and_ips` | Private IPs (`10.0.0.1`–`10.0.0.8`) found in `lookups/_trash/DR999_stress_test.csv__csv_20260405_013042/DR999_stress_test.csv`. | **Exclude `lookups/_trash/` from `.spl` packaging.** It's runtime state, not source. Fix in `scripts/package.sh` (Phase 0.11). |

Cloud profile has 8 warnings instead of 9 because **W2 (Victoria
indexer-sync)** is standalone-only.

---

## 5. Phase 1 effort-class verdict + D7 decision

### Effort classification

| Class | Definition | Phase 0.0 says? |
|-------|------------|-----------------|
| Trivial | <1 day; config tweaks only | ✅ Static signal supports this |
| Tractable | 1-2 weeks; some real work but no architectural changes | ✅ ← **This is where we are** |
| Multi-week refactor | 3-6 weeks; scripted inputs → modular inputs, REST → AdminConfigService, etc. | ❌ Not supported by signal |
| Catastrophic | >6 weeks OR Cloud cert blocked entirely | ❌ Not supported |

### Why "Tractable" (not "Trivial")

Static AppInspect alone doesn't size the work:

1. **W6 (cron scheduling)** requires per-saved-search justification or
   schedule changes. Some are intentional (per CLAUDE.md Decision Log
   2026-04-23 — the 5-min FIM correlation search). Documenting these as
   `accepted` in the formal Phase 1.3 triage takes time.
2. **W4 (Python 2/3 compat)** decision point — depends on the
   `app.manifest` minimum Splunk version (currently unset). If we
   declare minimum Splunk 9.0+, W4 disappears. If we want to support
   Splunk 8.x for legacy users, real Py2 audit work is needed.
3. **Dynamic AppInspect API checks (Phase 1.5-1.6)** still TBD. Static
   gives us strong signal that the *static* surface is clean, but the
   runtime stage (container boot, network detection, runtime restrictions
   on `wl_fim_watch.py`'s `interval=0` long-running process) is a
   smaller-but-real risk.

### D7 decision

> "D7 — Cloud-cert escalation: at Phase 1 week 4 if not green, escalate
> to user for re-decision. Soft cap. NOT auto-fallback."

**No escalation triggered.** Findings are NOT catastrophic. The single
biggest unknown in the entire 4-phase plan (R1.1) has been substantially
de-risked. The R1.1 worst-case ("6 weeks of scripted-input refactoring")
is not supported by the static signal.

**Action**: proceed with the rest of Phase 0 as planned.

---

## 6. Recommended follow-ups (for Phase 0 + Phase 1)

Sized in this section to inform Phase 0 task list updates:

| Where | What | Effort |
|-------|------|--------|
| **Phase 0.5** | When extracting `docs/DECISION_LOG.md`, record decision: "Phase 0.0 verdict — Phase 1 = tractable, NO D7 escalation triggered." | 5 min |
| **Phase 0.8** | Sync `app.conf:[launcher] version`, `app.manifest:info.id.version`, and any other version fields together to `1.0.0-rc1`. Add `[id]` stanza with `name = wl_manager`. Closes failure 4.1 + warning W7. | 10 min |
| **Phase 0.8** | Replace `python.version` → `python.required` in `inputs.conf`, `commands.conf`, `restmap.conf` (5 stanzas). Closes all 3 future_failures. | 15 min |
| **Phase 0.11** | `scripts/package.sh` — switch to allowlist-based bundling OR add `*/.*` glob exclude + tar-output sanity-check step. Without this, every release risks shipping dev artifacts again. Closes the root cause of §3. | 1-2 hr |
| **Phase 0.11** | `scripts/package.sh` — exclude `lookups/_trash/` from `.spl`. Closes warning W9. | 5 min |
| **Phase 1.2** | Pin CI runner to Python 3.11 (or 3.12). Document in `appinspect.yml`. | 5 min |
| **Phase 1.3** | Document `app.manifest` minimum Splunk version decision. If ≥9.0, dismiss W4 (Py2/3 compat). | 30 min |
| **Phase 1.3** | Per-saved-search justification for 4 high-frequency cron schedules (W6). Document in formal `docs/APPINSPECT_FINDINGS.md`. | 1 hr |
| **Phase 1.5** | AppInspect API dynamic-stage run — first real validation of `wl_fim.py` / `wl_fim_watch.py` / `wl_expiration_cleanup.py` under live container. **Most likely outstanding risk.** | 2-4 hr investigation |

Aggregate Phase 0.x fixes that this run revealed: **~3 hours**.
Aggregate Phase 1.x triage that this run already drafts: **2-4 hours**.

---

## 7. Re-runnable command (for future sessions)

```bash
# Build the appinspect image once (already exists as wl-appinspect:latest):
docker build -t wl-appinspect:latest .planning/appinspect

# Build clean .spl (until package.sh is fixed in Phase 0.11):
bash scripts/package.sh    # OR the manual tar in this session's transcript

# Standalone (on-prem) profile:
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$PWD/dist:/spl:ro" \
  -v "$PWD/.planning/appinspect:/out" \
  wl-appinspect:latest inspect /spl/wl_manager-<VERSION>.spl \
    --mode test --data-format json \
    --output-file /out/appinspect-standalone.json

# Cloud profile:
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$PWD/dist:/spl:ro" \
  -v "$PWD/.planning/appinspect:/out" \
  wl-appinspect:latest inspect /spl/wl_manager-<VERSION>.spl \
    --mode test --data-format json --included-tags cloud \
    --output-file /out/appinspect-cloud.json
```

---

## 8. Post-fix re-run (2026-05-14, build 660)

After applying the bundled fix commit (failure 4.1 + 3 future_failures
+ W1 path patterns + W9 `_trash` + W7 [id]/[package] dual stanza +
`package.sh` exclusion hardening), re-ran AppInspect:

### Clean result (build 660 .spl)

| Result class    | Standalone (249 total) | Cloud (242 total) |
|-----------------|------------------------|-------------------|
| success         | **160**                | **157**           |
| not_applicable  | 83                     | 80                |
| skipped         | 0                      | 0                 |
| warning         | 6                      | 5                 |
| **failure**     | **0**                  | **0**             |
| **future_failure** | **0**               | **0**             |
| **error**       | **0**                  | **0**             |

**All AppInspect errors, failures, and future_failures eliminated.**
Raw outputs: `.planning/appinspect/appinspect-standalone-final2.json`,
`.planning/appinspect/appinspect-cloud-final2.json`.

### What's left (warnings only, all informational)

Both profiles:
- `check_for_splunk_js` — telemetry; AppInspect's own message says "Please ignore this warning". IGNORE.
- `check_for_python_script_existence` — Py2/3 compat warning for Splunk 8.x. Moot via `app.manifest:platformRequirements.splunk.Enterprise >=9.0.0`. IGNORE.
- `check_for_scripted_inputs` — informational enumeration ("No action required"). IGNORE.
- `check_for_gratuitous_cron_scheduling` — 4 saved searches. Phase 1.3 will document per-search justification. One (FIM correlation) already justified in CLAUDE.md Decision Log.
- `check_collections_conf` — informational ("No action required"). IGNORE.

Standalone-only:
- `check_for_indexer_synced_configs` — Victoria-stack indexer sync. `inputs.conf` runs on search head only; correct as-is. Add documentation comment if Phase 1.3 wants explicit justification.

### Subtle gotchas surfaced by the re-run

Two AppInspect 4.2.0 quirks worth recording for future sessions:

1. **Dual `python.version` + `python.required` requirement.** The two
   are NOT aliases:
   - `check_*_python_version` (current cert) demands `python.version =
     python3` (or `python3.7`, `python3.9`). The value is a Splunk
     alias, not a semver.
   - `check_*_python_required` (Splunk 10.2+ future cert) demands
     `python.required = 3.13` — a **literal semver**, not `python3`.
   Removing the legacy `python.version` triggers a current failure;
   setting `python.required = python3` triggers a future_failure
   ("invalid value 'python3' for python.required"). Both must
   coexist with their respective canonical values.

2. **Dual `[package]` + `[id]` stanza requirement.** AppInspect
   enforces:
   - The legacy `[package]` stanza must exist with `id = X` (for
     `check_for_updates_disabled`).
   - The new `[id]` stanza must exist with `name = X` (for
     `check_for_valid_package_id`).
   - The two values MUST match.
   Removing `[package]` triggers two failures (one demands the
   stanza, the other demands the id-name match). The full rename
   to just `[id]` is wrong; the correct migration is **keep both**
   with matching values.

These are documented in the conf files via inline comments at the
relevant stanzas so the next maintainer doesn't repeat the experiment.

### Files changed in the build-660 commit

- `default/app.conf` — bumped `build` 659 → 660; added `[id]` stanza
  with `name = wl_manager`, kept `[package]` stanza, both with
  matching identifiers
- `default/inputs.conf` — 3 stanzas: switched cmd paths to
  `$SPLUNK_HOME/etc/apps/wl_manager/bin/...`; kept `python.version =
  python3`; added `python.required = 3.13`
- `default/commands.conf` — same dual-stanza fix
- `default/restmap.conf` — same dual-stanza fix
- `app.manifest` — `info.id.version` 1.0.0 → 2.0.0; `releaseDate`
  bumped to current
- `appserver/static/whitelist_manager.js` — `urlArgs: "_b=660"` to
  match build bump
- `scripts/package.sh` — `--exclude='*/.*'` glob + explicit excludes
  for `node_modules`, `htmlcov`, `bench_results`, `test-results`,
  `graphify-out`, `lookups/_trash`, `*.png`, etc. + post-tar sanity
  check (Step 4b)
- `scripts/validate.sh` — accept either `[id]` or `[package]` stanza
  in the local check (was hardcoded to `[package]` only)
- `CHANGELOG.md` — release notes for build 660

### Spec verification (the Phase 0.0 deliverable)

- ✅ `splunk-appinspect` installed (via Docker — Python 3.14 unwheeled
  for pillow/lxml; runner pinned to 3.11 for Phase 1.2 CI workflow).
- ✅ Current `.spl` run against `cloud` profile.
- ✅ Current `.spl` run against on-prem (Standalone) profile.
- ✅ Findings summary written (this document).
- ✅ Phase 1 effort-class estimated: **TRACTABLE**.
- ✅ Per D7: no escalation triggered.
- ✅ Bonus: failure + future_failure + 4 warning classes already
  fixed in the same session (build 660), so Phase 1 starts further
  ahead than the original plan anticipated.

## 9. Revision log

- 2026-05-13 — initial run; verdict = **tractable, no D7 escalation**.
- 2026-05-14 — bundled fixes applied (build 660); both profiles
  produce **0 errors / 0 failures / 0 future_failures**. Remaining
  6 standalone / 5 cloud warnings are all triaged as ignorable or
  Phase 1.3 documentation work.
