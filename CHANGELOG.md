# Changelog

All notable changes to this project will be documented in this file.

---

## Status — Security hardening track CLOSED at build 629 (2026-04-29)

After 9 progressive rounds (builds 552 → 629), the security-hardening
backlog is closed. Round 9 found zero new bugs and shipped no runtime
changes — first round in the series with no `app.conf [install] build`
bump, the natural signal that we're at diminishing returns.

The defense system is now self-sustaining without further hardening
rounds:

- **CI gates** — 4 Semgrep rules (SSRF, command injection, path
  traversal, `_from_*` payload bypass), doc-drift pre-commit + CI
  hook, quarterly `pip-audit` cron, unit-test suite on every PR
- **Live monitoring** — `wl_fim.py` (15 s hash sweep) +
  `wl_fim_watch.py` (~2 s stat-based) + `_recovery_log.jsonl`
  append-only watch + dual-store FIM baseline (file + KV)
- **Recurring audits** — Q3 2026 version-pinning routine
  (`run_once_at: 2026-07-18T07:00:00Z`) auto-fires and opens a PR
- **First-release verification** — Section 8 of
  `docs/RELEASE_CHECKLIST.md` enumerates the Sigstore end-to-end
  test for the first signed tag (legitimate verify + tamper test +
  Rekor confirmation + customer-doc publication)
- **Per-release artifacts** — Sigstore keyless signing of `.spl` +
  CycloneDX 1.5 SBOM, both signed via the workflow's OIDC token
  through Fulcio + recorded in Rekor

### Re-opening criteria

The track is closed but not frozen. Re-open with a new round when ANY
of these signals fires:

- A CVE that affects this codebase or a Splunk-bundled dependency we
  rely on (jQuery, Underscore, the bundled Python stdlib, Splunk
  Enterprise itself)
- A production incident traceable to a security control failure
- An external audit finding (formal pentest, customer-side review,
  red-team exercise)
- The Q3 2026 version-pinning routine surfaces a Splunk major-version
  change requiring compatibility work
- Methodology shift — fuzz coverage extended to a new code surface
  (e.g., the diff engine's pairing logic, version manifest math)

Future inbound work that does NOT meet these criteria is feature work
or bug-fix work, not hardening work. Don't queue another "round N"
unless one of the signals above fires.

### Per-round summary

| Round | Builds | Theme |
|-------|--------|-------|
| 1-5 | 552 → 622 | Primary hardening — KV cooldowns, runtime HMAC + TTL, FIM dual-store, deploy windows, schema versioning, strict content-hash, CSV integrity monitoring, ASCII-only validation, TOCTOU + insider-threat hardening |
| 6 | 625 | LOW items — CI pipeline, recovery-script FIM coverage, preliminary Splunk version audit |
| 7 | 626-628 | A items: residue cleanup + 2 fuzz-discovered bugs (newline-injection bypass via `$` vs `\Z`, `read_expected_hashes` UnicodeDecodeError fail-open). B items: supply-chain (`package.sh` FIM, per-job CI permissions, SECURITY.md disclosure policy, pip-audit one-off, audit-volume forecast). C items: SBOM + backup/restore + `.html()` audit |
| 8 | 629 | Sigstore keyless signing, recurring pip-audit cron, per-release SBOM generation, `coldToFrozenScript` archival guidance, `.append()` audit, Q3 audit scheduled |
| 9 | 629 (no bump) | Housekeeping — `fim_code_modified` doc drift, stale `dist/` artifacts, root-PNG `.gitignore`, PR-time Semgrep rule for `_from_*` anti-pattern |

Detailed per-round entries below.

---

## Unreleased — 2026-05-01 (build 632, UI consistency sweep)

### UI consistency: button taxonomy + audit dashboard polish (builds 631-632)

Three user-reported issues triggered a wider audit of every page,
dropdown, modal, and form. The root cause was structural: the codebase
had two button-class taxonomies coexisting, and **neither was fully
styled**. Splunk's bundled CSS ships rules for `.btn` and `.btn-primary`
only — `.btn-success`, `.btn-danger`, and `.btn-warning` silently fall
back to plain `.btn` grey. The custom `.wl-btn` / `.wl-btn-primary` /
`.wl-btn-danger` classes had **no CSS rules at all** beyond
`.wl-btn-locked` (an opacity helper). Result: every "Approve / Reject /
Remove / Purge" button across the app rendered the same grey as
"Cancel" — destructive actions had no colour signal.

Fixed by (a) defining `.btn-success`, `.btn-danger`, `.btn-warning`
with hover + focus + disabled states in `whitelist_manager.css`, and
(b) migrating the 9 `wl-btn` sites in `control_panel.js` to the
Splunk-bundled `btn` taxonomy. Custom `.wl-btn-locked` is preserved
(it's the approval-lock opacity helper, used by `wl_table.js` and
`wl_approval_ui.js`). See Decision Log entry 2026-05-01 for the
"kill `wl-btn` taxonomy entirely" rationale.

#### Fixed — user-reported

- **"Activate Emergency Lockdown"** in Control Panel header now
  renders as a proper red button instead of 12 px red plain text on
  the page background. The single most consequential action in the
  app is now visually appropriate.
- **"Change" retention link** on the Trash tab now uses the
  `.wl-link` rule's new default accent colour (was inheriting muted
  grey from parent).
- **Admin Settings "Save Changes" / "Reset to Defaults"** now match
  Analyst Settings visually (green primary + neutral grey). Both
  pages were previously using completely different button systems.

#### Fixed — surfaced by the wider audit

- **Whitelist Manager "Save Changes"** (`btn-success`) renders green
  for the first time. Previously rendered grey, identical to
  "Discard Changes".
- **Row-level "Remove" button** in the Actions column now red
  (`btn-danger` rule added). Previously grey, identical to "Export CSV".
- **Modal "Approve" / "Reject"** now green / red. Previously both grey.
- **CSV Import "Replace"** button (destructive) now red. Was grey.
- **Disabled-state contrast** on `btn-primary` / `btn-success` /
  `btn-danger` / `btn-warning` lifted from ~1.3:1 (failed WCAG AA)
  to a uniform `opacity: 0.55` so the colour identity stays readable
  while still signalling disabled.
- **`.wl-link` default colour** added — sites without an inline
  `color` attribute (conflict-reload link in `wl_save.js`, presence
  hooks in `wl_presence.js`, nav links in `wl_nav.js`) are now
  readable on dark theme.
- **Keyboard-focus ring** added for all `.btn` variants. `<span
  class="btn">` elements previously had no focus indication; they
  now show the same accent outline as `<button>` / `<a>` variants.
  (Note: `<span class="btn">` are still NOT keyboard-tab-able —
  see CLAUDE.md "Pending / Future Work" for the L3 span→button
  migration plan.)

#### Fixed — Audit Trail dashboard layout

- **"Expiring Soon" panel** capped at `max-height: 400px` with
  internal scroll. Previously auto-extended to ~14,000 px on
  dashboards with many expiring rows, pushing the rest of the page
  off-screen and producing a 17,850-px-tall dashboard. Page is now
  ~2,600 px after the cap (86% reduction). The Splunk SimpleXML
  `<option name="height">` is ignored on table panels so the cap is
  CSS-side via `#expiring_soon_table { max-height: 400px; ... }`.
- **Empty-state inconsistency** fixed across 7 single-value panels
  (Rows Added / Removed / Auto-Removed / Edited / Columns Added /
  Removed / Renamed). They previously showed "No results found." on
  empty input because `stats sum(...)` produces zero rows when no
  events match the `where action=X` filter. Now post-fixed with
  `| append [| makeresults count=1 | eval x=0] | stats max(x) as x`
  so the panels always render `0` when empty, matching the
  `stats count` panels next to them.

#### Polish

- **Visual separator** between [Add/Edit/Destroy] group and
  [Save/Discard persist] group on the WM main action bar
  (`#btn-save::before` thin border). The two semantic groups
  previously sat in one undifferentiated row of buttons.
- **`urlArgs: "_b=632"`** in `whitelist_manager.js` keeps cache-bust
  in sync with `app.conf [install] build = 632` per the CLAUDE.md
  maintenance rule.

#### Tests touched

- `tests/e2e/test_admin_limits.cjs` — assertion `saveClass.includes("wl-btn")`
  updated to `saveClass.includes("btn-primary")` since the migrated
  Save Changes button no longer carries the legacy class.
- `tests/qunit/test_wl_modals.js` — header comment added
  documenting that the test fixtures use synthetic `wl-btn-*`
  identifiers that DO NOT mirror production class names. The
  fixtures are self-contained and tests still pass; the comment
  prevents future-reader confusion.

#### Deferred to separate work

- **`<span class="btn">` → `<button class="btn">` accessibility
  migration** (audit finding L3). Visible buttons are tab-focusable
  via the new focus ring, but `<span>` still doesn't receive
  Splunk's tab traversal or ARIA "button" role. Doing this right
  requires unifying three different "disabled" patterns
  (`<button disabled>`, inline `opacity:0.5;pointer-events:none`,
  `wl-btn-locked` class) into one. See CLAUDE.md "Pending / Future
  Work" for the full scope.
- **Sigstore E2E verification** — already on the Pending list,
  unchanged.

#### Migration / rollback

CSS-only and class-rename changes; click handlers find by `#id` not
class. Rollback: `git revert` the build-631 + build-632 commits and
redeploy at the next build number. The `.wl-btn-locked` class is
preserved.

---

## Unreleased — 2026-04-29 (build 629, no app changes)

### Round 9: housekeeping — doc-drift, dead artifacts, PR-time anti-pattern gating

No runtime behavior change. All edits are repo housekeeping that the
prior 8 rounds accumulated. First round in the 552→629 series with no
`app.conf [install] build` bump — appropriate signal that we're now
in pure cleanup territory.

#### Fixed (doc drift only)

- **`fim_code_modified` → `fim_file_modified`** in `bin/wl_fim.py`
  comments (2 sites) and prior round-7 + round-6 CHANGELOG prose
  entries. Round 8 verification surfaced the drift: a search for
  `fim_code_modified` returned zero rows because the actual emitted
  action name is `fim_file_modified`. Code unchanged; only prose
  was wrong. The round-8 drift-discovery entry that DOCUMENTS the
  drift is left intact (it correctly reports both names).

#### Cleaned up

- **Stale `dist/` artifacts removed**: `wl_manager-1.0.0.spl` and
  `wl_manager-2.0.0.spl` (+ their `.sha256` sidecars). Both
  predated build 406 (current is 629). They were untracked
  (`dist/` is gitignored) but confused anyone running
  `package.sh` for the first signed release. Empty `dist/` now;
  `package.sh` writes fresh artifacts on next run.
- **Root-level PNG screenshots gitignored**: 17 untracked PNGs at
  the repo root (e.g. `csv-loaded.png`, `stress-pending-table-build615.png`)
  from past dev/Playwright sessions polluted `git status`.
  `.gitignore` now has `/*.png` (root-only) so session debris
  doesn't accumulate in tracked-file status. Canonical product
  screenshots under `docs/screenshots/` remain tracked.

#### Added

- **PR-time anti-pattern gating via Semgrep**:
  `tests/semgrep/payload-from-flag-bypass-splunk.yaml`. Catches at
  PR-review time what
  `tests/unit/test_ascii_validation.py::TestNoUnderscoreFlagPayloadBypass`
  catches at test-run time. Earlier feedback in the dev loop = lower
  fix cost. Pattern-mode (not taint-mode) because the anti-pattern is
  a structurally-illegitimate code shape, not a tainted dataflow:
  any `payload.get("_from_*")` or `payload["_from_*"]` READ is wrong
  regardless of subsequent sanitization. Writes (LHS of assignment)
  are explicitly excluded via `pattern-not-inside`. Verified: 4/4
  positive cases fire, 0/3 negative cases fire, 0 findings on
  current `bin/`. Past incidents addressed:
  - Round 1-3: `_from_approval` reads in 4 action wrappers
  - Round 5: `_from_dual_approval` reads in dual-admin paths
  - Round 7 A1: 7 dead writes removed (writes were OK; reads were not)
- `tests/semgrep/README.md` updated to document the new rule and
  why it's pattern-mode while the other three are taint-mode.

## Unreleased — 2026-04-29 (build 629)

### Round 8: residue + recurring guards + supply-chain hardening

#### Verified

- **FIM coverage live-tested**. Wrote a probe line to a `WATCH_CODE`
  file (`default/savedsearches.conf`) inside the container; both the
  ~2 s stat-based watcher (`wl_fim_watch.py`, action
  `fim_watch_file_modified`) and the 15 s hash-sweep
  (`wl_fim.py`, action `fim_file_modified`) emitted audit events
  with the correct `monitored_path`. Confirms round 6/7 FIM
  additions (recovery scripts, `scripts/package.sh`, append-only
  `_recovery_log.jsonl`) fire end-to-end, not just look right
  in static review.
- **Documentation cleanup**: prior commit messages and parts of
  CLAUDE.md called the modify-event `fim_code_modified`. The
  actual wire-level `action=` field is `fim_file_modified`. The
  inconsistency surfaced during the live FIM probe — a search for
  `fim_code_modified` returned no rows. The code is unchanged;
  only the prose was wrong. Future searches should use
  `fim_file_modified` (regular file changes) and
  `fim_watch_file_modified` (stat-watcher events).

#### Added

- **Sigstore keyless signing of the .spl + per-release SBOM** in
  `.github/workflows/release.yml`. Uses the workflow's OIDC token
  to mint short-lived ephemeral signing keys via Fulcio, records
  the signature in the public Rekor transparency log, and
  produces `<artifact>.sig` + `<artifact>.crt` for each .spl and
  each .cdx.json. Closes the previously-documented gap in
  `docs/SBOM.md` where the .sha256 + .spl shared a single channel
  (GitHub Releases) and a Releases takeover defeated both.
  Verifier command included in workflow comments.
- **Quarterly `pip-audit` CI workflow**
  (`.github/workflows/pip-audit.yml`) — fires Jan 1 / Apr 1 / Jul
  1 / Oct 1 at 09:00 UTC and on `workflow_dispatch`. Fails the
  workflow on any vulnerability, surfacing via GitHub's existing
  notification settings. Origin: round 7 B4 was a one-off run;
  without recurrence we'd forget to re-audit.
- **Per-release SBOM generation** (`scripts/generate_sbom.py`) —
  extracts the .spl tarball, hashes every bundled file, and emits
  a CycloneDX 1.5 JSON document with one `application:wl_manager`
  envelope and per-file `component` entries. `scripts/package.sh`
  now calls it as step 6/6, producing `<artifact>.cdx.json`
  alongside `<artifact>.spl.sha256`. Replaces the static
  `sbom.cdx.json` baseline (round 7 C1) with a per-release
  artifact that matches the .spl byte-for-byte.
- **`wl_audit` long-term archival guidance** in
  `default/indexes.conf` — documents two options for going past
  the default 3-year retention (extend online vs. archive on
  freeze via `coldToFrozenScript`), with example config blocks
  and pointers to Splunk's official docs. No default changed —
  guidance only.
- **`.append()` / `$(htmlString)` audit extension** appended to
  `docs/HTML_INJECTION_AUDIT.md`. 62 jQuery DOM-injection sinks
  beyond `.html()` audited (40 append + 3 prepend + 3 before + 1
  after + 5 replaceWith + 10 factory). Result: zero XSS bugs —
  every string-arg site already escapes user-controlled
  substrings. Same project-wide convention as round 7 C3 found.

#### Operational

- **Q3 2026 Splunk version-pinning audit scheduled**
  (`run_once_at: 2026-07-18T07:00:00Z` = 09:00 Europe/Warsaw).
  Remote routine `trig_01QE78KzCtSTuwFv2LjrUQqC` will re-run
  pip-audit, probe Splunk's supported-versions list, scan for new
  9.3.x CVEs, assess 10.x compat against the 7 risk areas listed
  in CLAUDE.md, run the pure-Python test suite, and open a PR
  with findings. One-shot rather than recurring because each
  audit's findings shape the next prompt.

## Released — 2026-04-29 (build 628)

### Round 7 C items: SBOM + backup/restore + .html() audit

#### Added

- **`docs/SBOM.md` + `sbom.cdx.json`** — Software Bill of Materials
  investigation and CycloneDX 1.5 baseline. Documents that the .spl
  artifact ships zero bundled third-party libraries; all runtime
  dependencies are Splunk-provided. Per-release SBOM generation
  flagged as future work.
- **SRI investigation** (in `docs/SBOM.md`) — concludes SRI is
  structurally N/A because Splunk-served same-origin assets have no
  third-party CDN scripts to protect. Documents the existing
  integrity layers we DO have (server cache hash, urlArgs cache-bust,
  .spl SHA-256 sidecar).
- **`scripts/backup_data.sh`** — captures the customer-meaningful
  data layer (CSVs + mapping + version snapshots) into a single
  timestamped tarball with SHA-256 + manifest. Excludes HMAC-bound
  state by design (cooldowns / FIM baselines / hash registry would
  fail HMAC verification on a different host; rebuild-on-restore is
  cheaper than back-up-then-fail).
- **`scripts/test_backup_restore.sh`** — smoke test that runs the
  backup, verifies the checksum, extracts the archive, and confirms
  every live file is byte-identical in the restored copy. Validated
  against a 127-file (964 KB) live state. Exit non-zero on any
  mismatch so it's CI-pluggable later.
- **`docs/BACKUP_AND_RESTORE.md`** — consolidated runbook for the
  three buckets (data layer / audit index / HMAC-bound state) with
  separate strategies. Replaces scattered guidance previously only
  in CLAUDE.md. Step-by-step planned-restore procedure including
  the FIM baseline drop-and-rebuild sequence.
- **`docs/HTML_INJECTION_AUDIT.md`** — methodology + per-file
  results of auditing every `.html()` call site in production
  frontend code (36 sites across 11 files). Result: zero XSS bugs
  — every user-controlled substring is already `_.escape`-wrapped
  before concatenation.
- **`wl_ui.js :: showTextMsg(text, type)`** — XSS-safe companion
  to `showMsg`. Uses `.text()` for the message body so any
  HTML-shaped input renders as literal characters. New call sites
  that don't need markup should prefer this; existing
  HTML-aware callers stay on `showMsg`.

#### Hardened

- **`wl_ui.js :: showMsg` contract documented** — the implicit
  caller-must-pre-escape rule was previously undocumented. Future
  maintainers adding a new call site without reading every existing
  caller could trivially have introduced an XSS bug. The function
  now carries an explicit contract docblock + a pointer to
  `showTextMsg` for cases where the message has no markup.

#### Misc

- `.gitignore` adds `backups/` and `.tmp_smoke_*/` /
  `.tmp_restore_*/` to keep backup artifacts and smoke-test scratch
  out of the repo.

## Released — 2026-04-29 (build 627)

### Round 7 B items: supply-chain + disclosure + audit-volume + dep audit

#### Added

- **`scripts/package.sh` to FIM `WATCH_CODE`** (`bin/wl_fim.py`). The
  release-packaging script produces the .spl artifact installed by
  downstream customers. Tampering means a poisoned release ships
  without ever modifying runtime code in the container — supply-chain
  surface that was upstream of every other monitored path. FIM now
  alerts within ~15 s on any edit (`fim_file_modified` HIGH).
- **Per-job `permissions:` blocks** on every CI workflow
  (`.github/workflows/{ci,release,semgrep,validate-and-package}.yml`).
  Each job declares its required scope independently of the
  workflow-level setting, so adding a future workflow-level
  permissions widening (e.g., for a comment-bot job) cannot silently
  enrich existing jobs' tokens. `validate-and-package.yml` previously
  had no `permissions:` block at all — fixed.
- **Coordinated disclosure policy** added to `SECURITY.md`. New
  sections: "Coordinated Disclosure Timeline" (acknowledgement /
  triage / fix / public-disclosure SLAs), "Scope" (in-scope code
  paths + out-of-scope deferrals to Splunk core / upstream
  dependencies), "Safe Harbor" (no-CFAA-action commitment for
  good-faith research), "Recognition" (release-notes credit,
  no monetary bounty currently).
- **Dev-dependency vulnerability audit** (`docs/PIP_AUDIT_LOG.md`).
  Documents the 2026-04-29 `pip-audit` run against
  `requirements-dev.txt`, the per-package OSV results, and the
  fallback OSV-API helper for re-running when pip-audit's sandbox
  installer fails.
- **`whitelist_view` audit volume forecast**
  (`docs/AUDIT_VOLUME_FORECAST.md`). Per-event size assumptions,
  write-side baseline, dedup-cache math, single-worker /
  multi-worker forecasts, storage envelope (raw + indexed), and
  re-forecast triggers. Realistic estimate: ~3,200 events/day per
  worker on a 100-analyst team; worst case ~40,000 events/day per
  worker.

#### Fixed

- **pytest 8.1.1 → 9.0.3** (`requirements-dev.txt`,
  `.github/workflows/ci.yml`). Closes GHSA-6w46-j5rx-g56g
  (CVE-2025-71176, CVSS 5.5 LOCAL): pre-9.0.3 pytest leaves the
  per-user tmpdir world-writable, allowing a local attacker on
  shared dev hosts to symlink-trick a test into reading files
  outside the test working directory. Verified: 664 tests pass
  under 9.0.3 (579 unit + 85 module-level), no API breakage.
- **radon 6.1.1 → 6.0.1** (`requirements-dev.txt`). 6.1.1 was a
  typo / aspirational pin and was never published to PyPI, so
  `pip install -r requirements-dev.txt` failed for any new
  contributor who tried to set up the project locally. 6.0.1 is
  the current latest and is what `metrics_collector.py` was
  originally tested against.
- **CI module-level test list aligned with reality**
  (`.github/workflows/ci.yml`). Removed a dangling reference to a
  removed-but-still-listed module-level filelock test file (the
  filelock paths are exercised inside `tests/unit/test_filelock.py`).
  Added the two existing module-level files that were not in the CI
  list: `tests/test_wl_fim_common.py` and
  `tests/test_wl_expiration_cleanup.py`.

## Released — 2026-04-29 (build 626)

### Round 7: residue cleanup + 2 fuzz-discovered bugs (A items)

#### Fixed

- **CRITICAL — newline-injection bypass in 3 validator regexes**
  (Hypothesis fuzz finding). `_ASCII_NAME_RE`, `_ASCII_FILENAME_STEM_RE`,
  and `_APP_CONTEXT_RE` in `bin/wl_validation.py` used `$` as the
  end-of-string anchor. Python's `$` matches BEFORE a trailing
  newline by default, so `is_ascii_name("DR_test\n")` was returning
  True. An attacker could submit rule names / CSV filenames /
  app-context values containing `\n` or `\r`, corrupting:
  audit-log readability (newline mid-event), dashboard rendering
  (line-break in display strings), SPL expressions consuming the
  identifiers, and filesystem path components. Switched all three
  regexes to `\Z` (absolute end-of-string). Deterministic regression
  test `test_trailing_newline_rejected` pins rejection of `\n`,
  `\r`, `\r\n`, `\t`, `\x00`, `\x1f` trailers.
- **HIGH — `read_expected_hashes` crashed on non-UTF-8 bytes**
  (Hypothesis fuzz finding). Catch-clause caught `OSError` and
  `JSONDecodeError` but not `UnicodeDecodeError`. An attacker who
  wrote garbage bytes to the registry would crash the FIM watcher,
  silently disabling integrity monitoring. Fixed by extending the
  exception list and adding a top-level dict-type guard.
- **`check_admin_daily_limit` -1=unlimited semantics** —
  `bin/wl_limits.py` now short-circuits `max_count == -1` to
  `(True, 0, -1)` matching `check_analyst_limit`. Previously took
  -1 literally (`current + 1 <= -1` is always False), so an admin
  with `-1` configured for an action was completely blocked. Round
  6 surfaced and pinned this asymmetry; round 7 fixes it. 5 new
  unit tests verify: short-circuit, ignores huge action_count,
  doesn't consult counters (mocked-to-raise check), 0 takes
  priority over -1, normal enforcement still works.

#### Cleaned up

- 7 dead `replay_payload["_from_approval"] = True` and
  `replay_payload["_approval_request_id"] = request_id` writes in
  `bin/wl_handler.py` removed. They were written but never read by
  any function — leftover from an earlier refactor. Future
  maintainers might mistake them for meaningful security flags.
  The `_from_approval` kwarg passed to `_save_csv` is the
  authoritative path; payload writes are noise.

#### Added

- **`_recovery_log.jsonl` append-only FIM watch** (`bin/wl_fim.py`).
  Round 6 added recovery SCRIPTS to FIM coverage but not the LOG
  they write to. Different alert model from WATCH_CODE because
  legitimate appends must NOT alert. New `WATCH_APPEND_ONLY` list,
  `_append_only_state()` snapshot helper, and per-cycle
  `(size, prefix_hash)` check. Alerts on:
  - `fim_append_only_truncated` — size DECREASED (entries removed)
  - `fim_append_only_rewritten` — prefix at previous size doesn't
    match the recorded prefix hash (entries edited in place)
  - `fim_append_only_removed` — file disappeared
  Closes the visibility gap: an attacker who runs
  `emergency_unlock.sh` maliciously and then truncates the
  recovery log to hide the entry now triggers a CRITICAL alert.
- 16 unit tests for the append-only watch logic
  (`tests/unit/test_fim_append_only.py`): zero-length prefix,
  partial prefix, length-exceeds-file, missing-file, legitimate
  append, no-change-silent, truncation, removal, same-size
  rewrite, partial-rewrite-with-append, first-baseline transitions.
- 10 Hypothesis fuzz tests for the HMAC sig path
  (`tests/unit/test_hmac_sig_fuzz.py`): stability against random
  bytes, malformed sig dicts, type confusion in sig fields.
  Determinism + correctness: same input → same checksum, any
  change to data → different checksum, round-trip preserves data,
  tampered data fails-closed to empty dict. ~1300 fuzz cases
  total. Found 1 real bug (`read_expected_hashes`
  UnicodeDecodeError) which is now fixed.

### Round 6: LOW items — infrastructure (CI, recovery-script FIM, version audit)

#### Added

- **CI pipeline** (`.github/workflows/ci.yml`) — two new jobs
  alongside the existing validate+package job:
  - `doc-drift`: runs `scripts/pre-commit-doc-drift.sh` on every
    push/PR. Mirrors the local pre-commit hook so a developer
    bypassing it with `--no-verify` is caught at PR time.
  - `unit-tests`: installs pytest + hypothesis + freezegun and
    runs `pytest tests/unit/` (539 tests, ~7s) and the lower-layer
    module tests `test_wl_limits` / `test_wl_hmac_key` /
    `test_wl_filelock`. Together they form the green baseline that
    item 5 just restored. E2E tests stay gated by
    `WL_TEST_HARNESS=1` and a real Splunk container — see the
    workflow's gate-notice block.
- **Recovery-script FIM coverage** — `bin/wl_fim.py` `WATCH_CODE`
  now includes `scripts/emergency_unlock.sh`,
  `scripts/reset_cooldowns.sh`, `scripts/fim_deploy_window.sh`,
  and `scripts/pre-commit-doc-drift.sh`. Tampering with these
  unsigned bash scripts (which perform privileged operations like
  clearing tamper flags or appending to the recovery log) now
  surfaces as a `fim_file_modified` event within ~15s.

#### Splunk version audit (preliminary)

- Recorded preliminary entry in `CLAUDE.md` audit log. Container
  confirmed running `Splunk 9.3.1 (build 0b8d769cb912)`. Decision:
  keep 9.3.1 for the current release; defer 10.x compatibility
  work to a dedicated cycle. Formal audit remains scheduled for
  2026-07-18 with the 7 risk areas listed in CLAUDE.md.

### Round 6: MED items — read-audit + test-suite cleanup + concurrency

#### Added

- **`whitelist_view` audit event** (`bin/wl_handler.py`) — emitted on
  every own-app CSV read, deduped per-process to one event per
  `(user, csv, app_context)` tuple per hour. Provides forensic
  visibility for insider-threat investigations ("did analyst X
  view DR_payment_fraud.csv before resignation?") without flooding
  the audit index. Cross-app reads still emit `cross_app_csv_read`
  separately (kept; no dedup since they're already rare). New
  dropdown choice in `audit.xml` General Actions filter.
- 9 dedup-cache unit tests (`tests/unit/test_view_audit_dedup.py`):
  emit-on-first-call, dedup-within-TTL, re-emit-after-TTL,
  user-isolation, csv-isolation, app-context-isolation, pruning,
  cache-size scaling, dashboard-tab-switch flood test.
- E2E concurrency test (`tests/e2e/test_concurrent_approval_race.cjs`):
  fires two simultaneous `process_approval` calls for the same
  request_id from two admin sessions. Verifies the
  `_approval_queue_lock()` rmw lock serializes them — exactly one
  reaches the replay path; the other observes post-mortem state.

#### Security audit — confirmed clean

- **Stored-XSS scan** across all data-at-rest layers: 169 version
  snapshot CSVs + 257 approval queue entries + notifications +
  rule_csv_map.csv + entire wl_audit index. Zero hits for
  `<script>`, `javascript:`, `onerror=`, `onload=`, `onclick=`.
  Confirms input ASCII validation has historically held and there
  are no XSS payloads waiting to render via the frontend's
  `.html()` call sites.

#### Fixed (test debt)

- Repaired 33 stale tests in `tests/unit/test_limits.py` and
  `tests/unit/test_rbac.py` that referenced symbols renamed during
  the wl_limits / wl_rbac refactor (`_read_daily_limits` →
  `read_daily_limits`, `_get_limits_dir` → `_get_limit_config_path`,
  `_should_reset_now` removed). Result: `pytest tests/unit/` now
  reports 539 passed, 1 skipped, 0 failed for the first time this
  round. Two `_should_reset_now` tests deleted (function inlined
  into reset_daily_limits during refactor; equivalent boundary
  coverage exists in `tests/test_wl_limits.py`).
- Renamed `test_admin_limit_respects_unlimited` →
  `test_admin_limit_unlimited_semantics_NOT_supported` to pin a
  PRODUCTION SEMANTIC ASYMMETRY: `check_analyst_limit` short-
  circuits `max_count == -1` to True, but `check_admin_daily_limit`
  takes -1 literally so any positive count fails. The Control
  Panel UI minimum-1 input prevents users from hitting this. If
  a future round wants to align them, update production AND this
  test together.

### Security — Round 6: structural bypass closeout (HIGH items)

Three structural-bypass items the user flagged in the post-round-5
gap assessment. Each closes a class of bug rather than a single
instance.

#### Added

- **HMAC sidecar for `_approval_queue.json`** — `bin/wl_approval.py`
  now writes a `.approval_queue.sig` sidecar file containing the
  SHA-256 of the queue file plus an HMAC over that hash signed
  with the GUID-derived runtime key (same key the CSV expected-hash
  registry uses). On every read, the sig is verified; on mismatch,
  the read fails closed (returns empty queue) and the admin-facing
  `get_approval_queue` action surfaces a `tamper_warning` field.
  This closes the gap noted in round 5: every other major state
  file was HMAC-signed; the approval queue was the only one
  protected by detection-after-the-fact (FIM 15s polling) instead
  of fail-closed read verification. Bootstrap-on-first-read means
  zero migration overhead for existing deployments.
- **Anti-pattern regression test** —
  `tests/unit/test_ascii_validation.py::TestNoUnderscoreFlagPayloadBypass`
  mechanically scans every `bin/*.py` for `payload.get("_from_*"...)`
  and `payload["_from_*"]` (read forms only — server-controlled
  writes via `replay_payload[...] = True` are allowed by word-
  boundary regex). Catches the entire bug class that bit us in
  rounds 1-5 (`_from_approval`) and 5 (`_from_dual_approval`).
- **Hypothesis fuzz on `compute_diff`** —
  `tests/unit/test_diff_fuzz.py`: 12 property-based test classes
  exercising stability, identity, conservation, append-only,
  delete-only, no-op-reorder, determinism, no-double-classification,
  and edit-pair invariants. Hits ~2400+ random/mutated CSV pairs.
  No new bugs found — the diff engine is robust to the historical
  failure modes (sets-vs-Counter, duplicate row identity,
  position-iteration) thanks to the targeted fixes that landed
  rounds 0-3. Property-based coverage now prevents regression.
- 6 unit tests in `tests/unit/test_approval.py::TestApprovalQueueHmac`
  covering bootstrap, queue tamper, sig tamper, sig deletion,
  round-trip preservation, and fresh-install behavior.

#### Security audit — confirmed clean

- Every action wrapper in `bin/wl_handler.py` no longer reads any
  `_from_*` flag from the user-controlled `payload`. The only
  remaining `_from_*` references are function kwargs (server-set)
  and writes to server-constructed `replay_payload` dicts.

### Security — Round 5: STRIDE + Hypothesis fuzz + attack-surface audit

Three independent verification techniques applied on top of rounds 1-4
to surface bugs that line-by-line review missed.

#### Fixed

- **CRITICAL** Dual-admin gate bypass via `_from_dual_approval` payload
  flag in `_action_remove_rule_csv`. Identical anti-pattern to the
  `_from_approval` bypass fixed earlier — `payload` is user-controlled,
  so any analyst could send `{"_from_dual_approval": true}` to skip the
  3+ CSV dual-admin requirement. The legitimate replay path
  (`_process_approval_inner`) calls `delete_rule_pipeline()` directly
  and never went through the action wrapper, so the flag had no
  legitimate use. Discovered via STRIDE Elevation-of-Privilege pass
  with the explicit "search for `payload.get('_from_*')` patterns"
  prompt. Regression test in `tests/unit/test_ascii_validation.py`
  (`TestNoDualApprovalPayloadBypass`) greps the handler source for the
  pattern and fails CI if it returns.
- **MED** `is_safe_filename` accepted ASCII-printable characters that
  `is_ascii_name(allow_spaces=False)` rejected. Falsifying example:
  `is_safe_filename("0;.csv") → True` while `is_ascii_name("0;",
  allow_spaces=False) → False`. The `;` is an SPL command separator —
  a CSV filename containing it would break dashboard drilldowns and
  audit search expressions. Tightened `is_safe_filename` to use
  `_ASCII_FILENAME_STEM_RE` (regex `^[A-Za-z0-9_\-]+$`) AND require ≥1
  ASCII alphanumeric in the stem. Discovered via Hypothesis
  property-based test `test_safe_filename_implies_ascii_stem`
  (`tests/unit/test_validator_fuzz.py`).
- **MED** `savedsearches.conf` write permission inherited by `wl_admin`
  via the `[]` default stanza in `metadata/default.meta`. A malicious
  `wl_admin` could modify e.g. `wl_csv_external_modification_alert` to
  inject SPL that runs with the search owner's permissions on schedule
  (e.g. `| outputlookup DR_critical.csv` to bypass approval gates).
  Locked `[savedsearches]` write to `admin`/`sc_admin` only. The
  detection control `wl_saved_search_timebomb_monitor` (catches
  modifications via `index=_audit`) is a runtime detection layer; this
  metadata change is the preventive layer.

#### Added

- `tests/unit/test_validator_fuzz.py`: 19 Hypothesis property-based
  fuzz tests with `max_examples=500`. Covers stability (validators
  never raise on any input including non-string types), determinism
  (same input → same output), accepted-input invariants (every char
  in an accepted ASCII name must be in the documented allow-list),
  `sanitize_text` invariants (no doubled whitespace, no control chars,
  respects `max_length`), and cross-validator consistency.
- `tests/e2e/test_rate_limit_burst.cjs`: REST API rate-limit burst
  test. Fires 60 + 80 concurrent GET `get_rules` requests and verifies
  the per-user sliding-window limiter (RATE_MAX_READS=120/min) clamps
  precisely. Result: 120/120 successes, 20 rate-limited — limiter is
  exact, not approximate.
- `tests/unit/test_ascii_validation.py::TestNoDualApprovalPayloadBypass`:
  mechanical regression check that `payload.get("_from_dual_approval"`
  doesn't reappear in `bin/wl_handler.py`.
- `metadata/default.meta`: explicit `[savedsearches]` stanza with
  write restricted to `admin`/`sc_admin`.

#### Changed

- Round 5 closeout commit (hardening rounds 1-5 inclusive).
- Cache-bust `_b=621` → `_b=622` in `appserver/static/whitelist_manager.js`
  per the maintenance rule (decision-log entry 2026-04-22).

#### Audit results that found nothing

- Auth/session/RBAC: `EDIT_ROLES`/`ADMIN_ROLES`/`SUPERADMIN_ROLES`
  membership checks consistent across all gates; no role escalation
  via custom-role membership manipulation possible at the handler
  level.
- KV-store integrity: `wl_cooldowns` and `wl_fim_baseline` collections
  both HMAC-signed with GUID-derived runtime key; tamper detection
  fail-closed.

#### Known deferred items

- `_approval_queue.json` is not currently HMAC-signed. The threat
  model treats this as lower priority because (a) every approval
  decision emits an audit event independent of the queue file, and
  (b) the FIM watcher hashes the file every 15s, so silent tampering
  would surface as a `fim_csv_unregistered`-class event. Adding HMAC
  to the queue is queued for a future round.

### Security — ASCII validation tightening (rounds 1-4)

**Breaking change**: detection rule names, CSV filenames, approval reasons,
comments, and `app_context` values are now strictly ASCII. Submissions
containing CJK ideographs, Cyrillic, Greek, Arabic, emoji, zero-width
characters, bidi-override marks, fullwidth ASCII lookalikes, combining
diacritics, null bytes, or other control characters are rejected with
HTTP 400. Length caps also enforced at the submission gate (rule names
≤100 chars, CSV filenames ≤200 chars).

If you have external automation that submits requests via REST and was
relying on the historical Unicode-permissive behavior of `c.isalnum()`,
those calls now return 400 instead of being queued for approval.
Migrate to ASCII-only payloads.

### Added

- `bin/wl_validation.py`: `is_ascii_name()`, `is_valid_app_context()`,
  `validate_ascii_text()` (round 1)
- `bin/wl_trash.py`: `_safe_trash_item_dir()` containment helper used
  by `purge_trash_item` and `restore_from_trash` (round 3)
- `tests/unit/test_ascii_validation.py`: 69 unit tests covering
  adversarial Unicode edge cases (rounds 1-3)
- `tests/e2e/test_concurrent_save_race.cjs`: characterizes the
  optimistic-lock behavior under concurrent saves (round 4)
- `scripts/pre-commit`: section #8 blocks new `c.isalnum()` usage in
  `bin/` to prevent regression to the Unicode-permissive pattern
  (round 3)
- `cross_app_csv_read` audit event: emitted when a user reads a CSV
  from an `app_context` other than `wl_manager` — provides forensic
  visibility into cross-app lookups for insider-threat investigations
  (round 4)
- `fim_mapping_unreadable` audit event: emitted by FIM watcher when
  `rule_csv_map.csv` cannot be parsed (e.g. UTF-8 corruption); this
  prevents silent loss of CSV integrity monitoring (round 3)

### Fixed

- **HIGH** Trash item path traversal: `purge_trash_item` and
  `restore_from_trash` previously fed user-supplied `trash_id`
  directly into `os.path.join` and `shutil.rmtree` without
  containment checks. A malicious admin sending
  `trash_id="../../tmp"` would have silently deleted
  `/opt/splunk/.../tmp` (round 3)
- **MED** Dual-admin meta validation: `_submit_dual_approval`
  accepted CJK in `rule_name`, `csv_file`, and `trash_id` fields
  even though POST-action wrappers had been tightened. Pollution
  of the dual-approval queue and audit trail prevented (round 3)
- **MED** Submit-approval bypass: a direct
  `action=submit_approval` POST bypassed the ASCII validation that
  was wired into `_submit_create_delete_approval`. Inner choke
  point now validates too (round 2)
- **MED** GET handler `app_context` validation: 4 GET endpoints
  (`get_csv_content`, `get_versions`, `check_csv_status`,
  `get_col_widths`) now reject malformed `app_context` at the
  wrapper instead of relying on lower-layer `resolve_csv_path`
  (round 4)
- **MED** FIM watcher resilient to UnicodeDecodeError on
  `rule_csv_map.csv` — single rogue byte previously crashed the
  watcher and silently disabled CSV integrity monitoring (round 3)
- **LOW** `is_ascii_name` rejects whitespace-only strings; previously
  `"   "` would pass the regex
- **LOW** `is_safe_filename` rejects null bytes and other ASCII
  control characters (round 2)
- **LOW** `_execute_replay_create_csv` returns clear "Invalid CSV
  file name" error for legacy CJK queue entries instead of crashing
  with `NoneType` from `write_csv(None, ...)` (round 2)

### Changed

- Build numbers 618 → 620 over 4 hardening rounds in this release
- Pre-commit hook now runs additional drift guard for `c.isalnum()`
  pattern in `bin/`

## [2.0.0] - 2026-03-22

### Added

- **Approval Workflows**: Bulk operations above configurable thresholds require admin approval. Admins approve/reject/cancel from the Control Panel. Self-approval prevention enforced.
- **Control Panel** (admin-only dashboard): Approval Queue with approve/reject buttons, Analyst Usage monitoring, Limits & Permissions configuration.
- **Daily Usage Limits**: Per-analyst caps on row removals, edits, additions, column changes, and reverts. Configurable reset frequency (daily/weekly/monthly/permanent).
- **Notification System**: Bell icon notifications for approval status updates (submitted, approved, rejected, cancelled).
- **Version Control**: Every save creates a timestamped CSV snapshot. Revert to any of the last 5 versions with full audit trail. Revert events use `*back` field naming for clarity.
- **Inline Cell Editing**: Click any cell to edit in place with textarea. Change tracking shows before/after diffs.
- **Bulk Edit Mode**: Edit multiple rows and save as a single operation.
- **Column Management**: Add and remove columns. Column removal with non-empty cells can require approval.
- **Row Drag-and-Drop Reordering**: Drag rows to reorder with `_row_reorder` audit events.
- **CSV Import**: Upload CSV files with merge logic (only new rows added).
- **Row Expiration**: Set expiration dates with presets (7d, 30d, 6mo, 1yr). Expired rows auto-removed on load and via hourly scheduled cleanup.
- **Dark/Light Theme**: Automatic theme detection with CSS custom properties.
- **Search Bar**: Filter rows across all columns with clear button.
- **Optimistic Locking**: Concurrent edit detection via file mtime. Second save with stale mtime is rejected with conflict error.
- **Rate Limiting**: Per-user sliding window rate limiter for read/write operations.
- **New Roles**: `wl_admin`, `wl_analyst_editor`, `wl_analyst_viewer` (legacy `wl_editor`/`wl_viewer` still supported).
- **Audit Dashboard**: Enhanced with approval stats, column change tracking, revert tracking, and expiring-soon panel.
- **Example SPL Queries**: Documentation with common audit queries for compliance and monitoring.

### Security

- Server-side RBAC enforcement on every POST request via Splunk REST API
- Path traversal protection with `_safe_filename()`, `_safe_realpath()`, and symlink detection
- Input sanitization via `_sanitize_text()` on all user-controlled audit log fields
- `_from_approval` flag is a Python function parameter (not injectable from client)
- `_bulk_edit_count` computed server-side from diff (not trusted from client)
- `_approval_request_id` only read when `_from_approval=True`
- `log_event` action requires `EDIT_ROLES` (prevents audit log injection by viewers)
- `wl_analyst_viewer` role inherits `user` instead of `power` (least privilege)
- Payload size limit (10 MB) to prevent DoS
- `props.conf` with `TRUNCATE=0` for large audit events

### Fixed

- RBAC cancel bug: compared username to role name strings instead of checking user's actual roles
- `_build_request_value_fields()` crash: removed call to non-existent method in cancel path
- `doSave` failure handler: now resets `currentHeaders` alongside `currentRows`
- `MAX_TRACKED_ANALYSTS` overflow: tracks under `__overflow__` bucket instead of silently allowing unlimited operations
- GET 400 response: added missing `get_notifications` and `get_request_csv` to valid actions list

### Changed

- Version bumped to 2.0.0
- Navigation: replaced Search tab with Control Panel (admin-only)
- `default.meta`: updated permissions for new roles
- `restmap.conf`: added `passSystemAuth = true` for audit event writing
- Package script: excludes dev artifacts (`.claude/`, `.pytest_cache/`, `CLAUDE.md`, etc.)
- Development credentials moved to environment variables with defaults

## [1.0.0] - 2026-02-15

### Added

- Initial release of Splunk Whitelist Manager
- Web-based interface for managing detection rule CSV whitelists
- Support for 18 sample detection rules
- Role-based access control (`wl_editor`, `wl_viewer`)
- Audit trail logging to `wl_audit` index
- Bulk add/remove operations
- REST API at `/custom/wl_manager`
- Configurable rule mapping via `rule_csv_map.csv`
