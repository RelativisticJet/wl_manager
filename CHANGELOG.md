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

## Unreleased — 2026-05-07 (build 642, regression-sweep follow-up: lock banner + 3-way fallback)

### Bug — sibling drift surfaced during build-641 regression sweep

The build-641 fix repaired the WM action-bar banner ("by analyst —
reason") for `column_removal` / `remove_csv` / `remove_rule` requests.
A targeted regression sweep against every sibling consumer of the
pending-approval projection found two more places carrying the same
class of drift:

1. **Lock banner** at the top of the WM table
   ([wl_approval_ui.js:374-377](appserver/static/modules/wl_approval_ui.js#L374-L377))
   read `pa.description` only with no fallback. For action types where
   the backend leaves `description=""` it rendered "**column removal**
   by analyst1 ()" — empty parens. Cosmetic-only (the action bar below
   carries the actionable approve/reject buttons), but visible side by
   side and confusing.

2. **Action-bar fallback** at
   [wl_approval_ui.js:401-405](appserver/static/modules/wl_approval_ui.js#L401-L405)
   computed `var reason = extractApprovalReason(pa)` but never used it,
   while the Control Panel uses the same helper as a third fallback
   ([control_panel.js:463](appserver/static/control_panel.js#L463)).
   When an analyst structured their reason inside the payload (e.g.
   `column_removal_reasons[0].reason`) instead of the free-form
   comment field, CP rendered the reason and WM rendered nothing —
   asymmetric between the two surfaces.

### Fix

Both call sites now use the same 3-way fallback chain:

```javascript
pa.comment || pa.description || extractApprovalReason(pa) || ""
```

The lock banner additionally drops the parens entirely when no reason
is available (renders "by analyst1" cleanly instead of "by analyst1
()"), matching the action-bar pattern of "no separator when no
reason".

### Why this didn't surface in build-641 verification

Build-641's browser smoke-test confirmed the action-bar banner
rendered "Field deprecated by GRC team" and stopped there. The lock
banner above it WAS visible in the same screenshot but didn't render
empty parens because the demo-state seed only carried the one
column_removal entry — and the lock-banner fallback to `description`
returned a non-empty value for the FIRST entry I inspected (a
`bulk_row_addition` from a different fixture). Three lessons:

1. End-to-end verification of one banner is not verification of the
   page — sibling renders need their own checks.
2. Single-entry demo state masks fallback-chain bugs that only
   surface with action-type variety.
3. The Control Panel's 3-way fallback existed; the WM only had
   2-way; that asymmetry was its own signal that one surface was
   ahead of the other.

### Tests

The build-641 unit suite at
[tests/unit/test_pending_info_projection.py](tests/unit/test_pending_info_projection.py)
already pins the **backend** projection contract (the `comment` field
is reachable to the frontend). The frontend fallback chain is
exercised by E2E click-through; no new unit test added because the
asserting layer would be Playwright (different toolchain than the
pytest suite).

### Migration / rollback

JS-only — no schema or API changes. Cache-bust `_b=` bumped from 640
to 642 so returning users automatically pick up the fresh JS without
hard-refresh. Rollback: revert this commit + redeploy at the
previously-shipped build 641;
the lock banner returns to empty-parens cosmetic behavior, the
action-bar banner stays correct (build-641 fix is independent).

### Build cache-bust caught up

Build 641 shipped with `_b=640` (backend-only fix, no JS changes —
acceptable but the maintenance rule says to keep them in sync).
Build 642 closes the gap.

---

## Unreleased — 2026-05-07 (build 641, fix WM approval-banner blank reason)

### Bug — `comment` dropped from `pending_info` projection

The Whitelist Manager dashboard renders an approval banner when a CSV
has a pending request (`<action> by <analyst> — <reason>`). On a
freshly-seeded DR130 column-removal request, the banner displayed
`column removal by analyst1 —` with **nothing after the dash** even
though the Control Panel's Approval Queue showed the same request
with `Analyst Reason: Field deprecated by GRC team` correctly.

**Root cause**: two endpoints (`_get_csv_content` for the WM page and
`_action_get_pending_approvals` for the polling refresh) constructed
their `pending_info` response inline with this exact field set:
`request_id, action_type, description, analyst, timestamp,
pending_highlight, payload`. **`comment` was not in the list.** The
frontend banner at `wl_approval_ui.js:405` reads
`pa.comment || pa.description || ""` — for `column_removal` /
`remove_csv` / `remove_rule` the auto-`description` is empty by
handler convention, so both fallbacks were falsy and the banner
rendered as empty. The Control Panel was unaffected because it uses
`get_approval_queue` which returns the queue entry verbatim.

**Why the bug stayed dormant**: the prior demo state had ~14 pending
entries and 245 historical entries dominated by `bulk_row_addition`
and `bulk_row_removal` requests, where `description` IS auto-
populated by the handler. The blank-banner case was triggered only
for action types where description is empty AND the analyst typed a
free-form comment — exactly the path my build-640 demo-seed exercised
on a clean state. Stale fuzz data had been masking it the whole time.

**Fix**:

1. Extract the shared projection into `wl_approval.project_pending_info`
   so both endpoints route through one place. Helper is library code
   (no `splunk.rest` import) and can be unit-tested directly.
2. Add `"comment": entry.get("comment", "")` to the projection. The
   `.get` fallback covers older queue entries that may not have the
   field (forward-compatible upgrade path).
3. Both call sites in `wl_handler.py` now read
   `[project_pending_info(p, has_edit=...) for p in queue]` —
   single line replaces the prior inline dict literal.

**Tests**: `tests/unit/test_pending_info_projection.py` — 15 cases
pinning the contract:
- `comment` propagates for `column_removal` (the regression case)
- Missing `comment` defaults to `""`, not `KeyError` or `None`
- All 8 contract fields present (regression guard for future
  field drops)
- `has_edit=False` strips `payload` + `pending_highlight`
  (RBAC contract)
- `has_edit=True` exposes both
- `comment` propagates for all 10 valid `action_type` values

**Verification**: REST endpoint smoke-test confirmed
`comment: "Field deprecated by GRC team"` now appears in the
`get_csv_content` response for DR130; browser-tested the WM page
which now renders the banner with the analyst's reason text.

### Build

- `app.conf [install] build` 640 → 641
- `whitelist_manager.js` urlArgs unchanged (no JS edits)

### Migration / rollback

- Revert: re-inline both projections in `wl_handler.py`
  (`_get_csv_content` ~line 1665, `_action_get_pending_approvals`
  ~line 2336) and delete `project_pending_info` + the export
  from `__all__` in `wl_approval.py`. Tests under
  `tests/unit/test_pending_info_projection.py` would then need to
  be deleted or rewritten against the inline shape. Frontend
  banner reverts to its prior blank-on-column-removal behavior.

### Cleanup

- Removed `backups/2026-05-06/` (audit-index tarball + state
  JSONs + orphan CSVs + version snapshots from build-640 cleanup).
  Was already gitignored; just freed local disk. Re-generate any
  time via the seed-then-clean playbook documented in
  `tests/fixtures/demo-state/README.md`.

---

## Unreleased — 2026-05-06 (build 640, audit consistency + demo-state cleanup)

### Audit Trail consistency

Two issues surfaced when reviewing the Audit Trail dashboard for the
first public-release screenshots:

1. **`timestamp_human` vs `timestamp` field-name drift.** The "File
   Integrity Monitor Alerts" and (formerly) "Out-of-Band Recovery
   Actions" panels rendered their first column with the SPL field
   name `timestamp_human`, while the other three panels (Data
   Changes / Activity Log / Privileged Admin Actions) used
   `timestamp`. The visible column header is the field name, so
   users saw two different labels for the same kind of column.
   `audit_tz.js` overwrites every cell client-side based on the
   hidden `epoch_ts` column anyway, so the SPL field-name choice was
   purely cosmetic. Unified to `timestamp` across all 5 panels.

2. **"Out-of-Band Recovery Actions" panel title.** Jargon for a new
   user. Renamed to **"Recovery Scripts & Maintenance Windows"** —
   self-explanatory: the entries are operator-driven recovery
   scripts (emergency unlock, cooldown reset, schema migrations)
   plus FIM deploy windows. `audit_tz.js` header comment updated to
   reflect the new title.

### Demo-state cleanup (visible in README screenshots)

The build-639 README screenshots leaked accumulated dev/test state:
Control Panel showed 14 pending requests with names like
`DR_TRASH_TEST` plus 245 historical entries (many from hardening-
round fuzz inputs); detection-rule dropdowns listed 19 obvious test
rules (`DR_STRESS_2000x100`, `DR999_stress_test`, `AL13_Test_Rule`,
`DR_RACE_<unix-ms>`, etc.); CSVs themselves contained fuzz-test rows
(`FS_ATTACK_USER`, `auth_method=TEST`, `test_val`); `wl_audit` index
held 12,945 events from every E2E run since builds 552-629.

Cleaned exhaustively:

- Backed up `wl_audit` index (1.9MB tarball, 12,945 events) +
  state JSONs to `backups/2026-05-06/`. Backup dir gitignored.
- `splunk clean eventdata -index wl_audit` after stopping splunkd.
- Truncated `_recovery_log.jsonl` (122 entries from cooldown
  migrations + deploy-window cycling).
- Deleted 4 state files: `_approval_queue.json` (queue),
  `_daily_limits.json`, `_notifications.json`, `_trash_config.json`.
  Each `# JUSTIFIED:` marker explains why direct removal was used
  (no production purge endpoint; trash purge has 1-hour cooldown
  per superadmin by design that blocks bulk cleanup).
- Removed 19 test detection rules + their CSVs via the production
  `remove_rule` action with `removal_type=permanent`.
- Removed 7 orphan test CSVs (`DR778_*`, `DR998_column_stress.csv`,
  `DR_APPROVAL_TEST_1.csv`, `DR_LONG_NOTIFICATION_TEST_2.csv`,
  `DR777_new_rule.csv`) that lingered in `lookups/` after their
  rule-registry entries were already gone.
- Removed 176 orphan version snapshots in `lookups/_versions/`
  (`AL_super_*`, `STRESS_*`, `DR_TEST_*`, `DR_RACE_*` etc.) for
  CSVs that no longer exist.
- Re-bootstrapped `bootstrap_csv_hashes` against the cleaned
  registry (20 CSVs hashed, 0 changed, 0 missing).
- Cleared KV `wl_cooldowns`.
- Cleaned the production CSVs themselves (DR45 had
  `FS_ATTACK_USER`, DR55 had `auth_method=TEST`, DR20 had three
  `test_val,test_val,test_val` rows + a placeholder-X hostname).
  Replaced with realistic-looking data.

### Demo seeding (production-path only)

To give the screenshots non-empty content without re-introducing
the test pollution, ran `scripts/seed-demo-state.py` which hits the
production REST endpoints exactly as a real analyst / admin would:

- analyst1 added `r.thomas` (sales team RDP gateway) to DR45
  whitelist (`row_added` event).
- analyst1 increased `svc_patch` brute-force threshold on DR55
  (`row_edited` event).
- analyst1 submitted 3 approval requests: remove_csv on DR610,
  column_removal of `ticket_id` on DR130, remove_rule on DR640.
- wladmin1 approved the DR610 removal (executed → `csv_removed`
  event + FIM `csv_external_deletion` because the watcher
  observed the file vanish; expected behavior, FIM doesn't
  distinguish handler-driven deletes from external ones).
- wladmin1 rejected the DR640 rule removal with reason "Hold for
  GRC sign-off - see ticket SEC-2412".
- The DR130 column removal stays pending so the queue shows a
  "live" entry.

Final state: 18 production rules, 3 queue entries (1 pending +
1 approved + 1 rejected), ~11 audit events with realistic variety
(`row_added`, `row_edited`, `request_submitted` ×3,
`request_approved`, `request_rejected`, `csv_removed`,
`whitelist_view`, `fim_csv_external_deletion`,
`fim_baseline_initialized`, `fim_watch_started`).

### Demo-state checkpoint

Added `tests/fixtures/demo-state/README.md` documenting the
restore steps so future screenshot rounds skip the
"figure out what to clean" step. The actual snapshot files are
NOT committed — they get regenerated by re-running the seed
script against a freshly-cleaned environment.

### Screenshots refreshed (3 of 4)

- `docs/screenshots/03-audit-trail.png` — Audit Trail with the
  new `timestamp` column header + "Recovery Scripts &
  Maintenance Windows" panel title + clean event variety
- `docs/screenshots/04-control-panel.png` — Control Panel with
  realistic 1-pending / 1-approved / 1-rejected approval queue,
  clean activity counters, no notification accumulation
- `docs/screenshots/02-inline-editing.png` — left as the
  user-provided manual capture (excellent inline-editing demo
  on DR130; the small notification-badge "20" dates from before
  this cleanup but is content-correct for the screenshot's purpose)
- `docs/screenshots/01-main-dashboard.png` — automated capture
  produced byte-identical output to the prior round despite
  await_text confirming DR130 rendered with seeded data
  (suspected browser-tool caching layer with the headless
  Chrome). **Recommend manual recapture before public ship**:
  open WM, select DR130_privilege_escalation +
  DR130_priv_escalation.csv, capture full-page at native
  resolution.

### Build

- `app.conf [install] build` 639 → 640
- `whitelist_manager.js` urlArgs `_b=639` → `_b=640`

### Migration / rollback

- Audit panel reverts: re-introduce `timestamp_human` evals +
  field-name in two `<table>` blocks of `default/data/ui/views/audit.xml`
  and revert the panel title; re-introduce `(timestamp_human)`
  annotations in `appserver/static/audit_tz.js` header comment.
- State restore: extract `backups/2026-05-06/wl_audit_backup_*.tar.gz`
  to `/opt/splunk/var/lib/splunk/wl_audit/` after stopping splunkd;
  extract `wl_state_backup_*.tar.gz` to
  `/opt/splunk/etc/apps/wl_manager/lookups/_versions/`. Test rules
  are NOT auto-restored — the rule registry edit is the source of
  truth and was deliberately pruned.

---

## Unreleased — 2026-05-06 (build 639, pre-release polish round)

### UI hygiene: standardize section headers, empty states, and error card

Round-up of small inconsistencies surfaced during the open-source
pre-release audit. None are functional bugs — purely visual /
maintenance polish.

- **Section header drift** — 8 inline `<h3 style="margin:...">` tags in
  `control_panel.js` used three different margin patterns
  (`12px 0 8px`, `20px 0 8px`, `8px 0 12px`, `8px 0 4px`). Standardized
  on a single `.wl-section-header` class (`margin: 12px 0 8px`).
- **Empty-state token bug** — 12 `<p style="color:var(--wl-muted,#888)">`
  callsites referenced `--wl-muted`, which is **not defined** anywhere
  in the CSS — the `#888` fallback always won, so empty-state copy
  rendered as slate gray regardless of the dark theme tokens. Migrated
  to a `.wl-empty-state` class that uses the actually-defined
  `--wl-text-muted` token.
- **Error card** — Control Panel "failed to load" error rendered as a
  centered yellow box (`#ffc107`) with inline styling and an inline
  `onclick="location.reload()"`. Now uses a `.wl-error-card` class with
  the existing `--wl-err-*` palette (matches every other "something
  went wrong" surface in the app), and the Refresh button binds via a
  delegated jQuery handler instead of inline `onclick`. Future-proofs
  for any CSP nonce/strict-dynamic policy a deployment might layer on.

### Repo hygiene: remove screenshot debris + extend `.gitignore`

- Removed 11 PNG files left at the repo root by the Chrome browser
  tool's `screenshot` action (saved without a file extension when a
  bare name was passed). All confirmed unused — no doc, README, or
  source file referenced any of them.
- Extended `.gitignore` with forward-looking patterns
  (`/build-*`, `/cp-[0-9]*-*`, `/wm-[0-9]*-*`, `/at-[0-9]*-*`,
  `/[0-9][0-9][0-9]-*`, plus the specific debris filenames) so the
  same pattern can't accumulate again.
- Removed 15 additional PNG screenshot debris files
  (`add-row-3.png`, `at-01-04-*.png`, `cp-01-05-*.png`,
  `create-rule-form*.png`, `csv-loaded.png`) that were
  already gitignored by the `/*.png` rule but still cluttering
  the working tree. These were unused — no markdown, HTML, or
  source file referenced them.

### Documentation polish

- **README**: corrected stale claim "Dark and light theme support"
  to "Polished dark theme (light theme intentionally removed in
  build 637 (2026-05-01) — see CHANGELOG)". The light-theme line had
  been left over from before the previously-shipped build-637
  dark-only decision.
- **README screenshots refreshed (3 of 4)**:
  - `docs/screenshots/01-main-dashboard.png` — originally captured
    at build 639 (2026-05-06) showing dark theme + DR20 rule loaded
  - `docs/screenshots/03-audit-trail.png` — full audit dashboard
    fullpage capture at build 639 (2026-05-06)
  - `docs/screenshots/04-control-panel.png` — full Control Panel
    Approval Queue tab fullpage at build 639 (2026-05-06)
  - `docs/screenshots/02-inline-editing.png` — **NOT refreshed**.
    Captures cell-edit state which needs interactive click + cell
    selection that's hard to script reliably in headless mode.
    Recommend manual recapture before public release: open WM,
    load any rule with rows, click into a cell, edit a value so
    the highlight is visible, then screenshot.
- **RELEASE_CHECKLIST.md** Step 5 wording fix: "in `SECURITY.md`
  under the existing 'Distribution integrity' section in
  `docs/SBOM.md`" was a confused two-file reference. Corrected to
  "append under the existing '## Distribution integrity' section"
  in `docs/SBOM.md` only (where the section actually lives).

### Migration / rollback

- CSS: revert by re-introducing inline `style="margin:..."` on the 8
  `<h3>` callsites and `style="color:var(--wl-muted,#888)"` on the 12
  empty-state callsites, then delete the three new classes from
  `whitelist_manager.css`. Error card revert: restore the inline
  `onclick="location.reload()"` block. Files affected:
  `control_panel.js`, `whitelist_manager.css`.
- `.gitignore`: revert by removing the build-639 stanza. The deleted
  PNGs are recoverable from git history if needed (none were
  committed; they were untracked when removed).

---

## Unreleased — 2026-05-01 (build 638, flatten redundant `.wl-dark X` selectors)

### Cleanup follow-up: zero `.wl-dark X` selectors remain in CSS

Build 637 previously collapsed `:root` light + `body.wl-dark` dark blocks
to a single `:root`, but left 13 `.wl-dark X` selectors throughout
`whitelist_manager.css` as harmless redundancy (they always match
because `wl-dark` is unconditionally applied). Build 638 (2026-05-01)
flattened these into their corresponding base rules.

For each pair `X { ...light values... }` + `.wl-dark X { ...dark
values... }`, the dark values were merged into the base rule and
the `.wl-dark X` block deleted. Net: 13 fewer rules, ~50 fewer
CSS lines, single source of truth per element.

Specific elements flattened (all visually verified post-flatten
against expected dark values):

- `.wl-col-check input[type="checkbox"]` (`color-scheme: dark`)
- `.wl-cell-match` (bg `#3b3000`, border `#f9a825`)
- `.wl-cell-edited` (bg `#3e2723`)
- `.wl-bulk-edit-bar` (bg `#1a237e30`, border `#3949ab`)
- `tr.wl-pending-approval` (bg `#3e2200`)
- `tr.wl-pending-approval:hover` (bg `#4a2a00`)
- `tr.wl-pending-approval .wl-input` (bg `#3b2000`)
- `th.wl-pending-approval-header` (bg `#3e2200`, color `#ffd699`)
- `.wl-table.wl-pending-approval-table` (outline `#e65100` 3px solid)
- `.wl-approval-self-note` (color `#ffb74d`)
- `.wl-approval-bar` (bg `#3e2723`, border `#e65100`)
- `.wl-approval-item + .wl-approval-item` (border-top `#e65100`)
- `.wl-addition-preview` (bg `#2a2a2a`)

`wl_ui.js :: detectDarkTheme()` still applies `wl-dark` to `<body>`
unconditionally — kept as a no-op marker for any external code
(Splunk plugins, future debug hooks) that might key off the class.
No in-app CSS rule depends on the class anymore.

### Verification

Browser-tested all 13 clusters via DOM injection of test elements
and `getComputedStyle()` snapshots. Every property matches the
build-637 dark value exactly. Whitelist Manager, Control Panel,
and Audit Trail all render identically to the previously-shipped build 637.

### Migration / rollback

Per-cluster reversion is straightforward: re-introduce the `.wl-dark X`
override block and revert the base rule's properties to the
pre-flatten light values. Files affected: `whitelist_manager.css`
only.

---

## Unreleased — 2026-05-01 (build 637, dark-only theme + final palette unification)

### Theme: dark-only (light-theme support removed)

The app has been dark-first for its entire history; light-mode paths
were half-implemented (the modal-overlay had its own duplicate
`--wl-bg` block, several inline-styled elements assumed dark bg, and
no test passes covered the light-bg case). Rather than complete the
light-theme work, removed it:

- Collapsed `:root` (light defaults) and `body.wl-dark` (dark
  overrides) into a single `:root` block in
  `whitelist_manager.css`. Net: ~70 lines deleted, no duplication.
- Removed the `body.wl-dark > .wl-modal-overlay` re-tightening block
  (modals now inherit all vars from `:root` directly).
- Simplified `wl_ui.js :: detectDarkTheme()` to unconditionally
  apply `wl-dark` to `<body>` and return `true`. The 19 existing
  `.wl-dark X` selectors in `whitelist_manager.css` continue to
  match because the class is always present — they're functionally
  redundant but harmless and can be flattened in a follow-up.

Rationale: open-source release target, no paying customers, no
demand for light theme. Collapsing the parallel theme system
removes a class of failure modes (the half-converted state seen
during the build-636 light-theme test) and simplifies the CSS.

Reversal cost: medium — re-introduce `:root` light vars, re-add
the `body.wl-dark` selector wrapping, restore the brightness check
in `detectDarkTheme()`.

### UI consistency: drift sweep across Audit Trail + Control Panel

Beyond the modal hygiene shipped in build 636, this build sweeps
remaining inline-style drift in the dashboards:

**Audit Trail** (`default/data/ui/views/audit.xml` + `audit_trail.js`):

- "Close Details" span had hardcoded inline `background:#c0392b`
  (vivid Bootstrap red) and was missing keyboard a11y. Migrated to
  `class="btn btn-danger" role="button" tabindex="0"` matching the
  rest of the app's destructive-button styling. Added `keydown`
  handler in `audit_trail.js` for Enter/Space activation.
- Splunk strips `<button>` from SimpleXML `<html>` panels (CLAUDE.md
  documented Splunk quirk), so this control has to remain a `<span>`
  — the role/tabindex/key-handler combo gives it minimal a11y parity.

**Control Panel** (`control_panel.js`):

- Lockdown banner: vivid `#c0392b` → muted `#a93226` (matches
  `.btn-danger` family).
- "Show Data" buttons (queue list, history list): removed inline
  `background:#3498db;color:#fff` so they default to Splunk's `.btn`
  grey. Show Data is a neutral inspection action — doesn't fit
  primary/danger/warning roles.
- "Save as Default" / "Reset to Factory Defaults": same treatment —
  removed vivid blue/grey inline backgrounds, default to `.btn` grey.
- LIMIT badge / RESET badge: vivid `#e74c3c` → muted `#a93226`.
- LIMIT-reached count text: stays at vivid `#e74c3c` (text on dark
  bg needs higher contrast — muted red would fail AA).
- FACTORY badge (grey `#95a5a6`): unchanged, doesn't conflict.

### Modal hygiene round 2

Two more modals had inline-style "actions row" divs replicating
`.wl-modal-actions` styling:

- `wl_modals.js:159` — Remove rule/CSV modal actions row
- `wl_save.js:451` — Audit Comment Required modal actions row

Migrated both to `class="wl-modal-actions"`. Now ALL 19+ dialog
modals render their button row through the shared class.

### Focus ring colour: harmonized with Splunk's accent

`.btn:focus-visible` outline changed from `#2962ff` (vivid blue)
to `#2196f3` (Material Blue 500). Splunk's bundled accent is
`#006eaa` but contrast on our dark bg is only 2.97:1 — just below
WCAG 1.4.11's 3:1 minimum for focus indicators. `#2196f3` stays in
the Splunk-blue family, gives 6.0:1 contrast, and is distinct from
every button colour (green/red/orange) so the focus ring never
visually merges with the button it surrounds.

### Notification badge unified with `.btn-danger` palette

`.wl-notif-badge` background changed from `#e74c3c` (vivid Bootstrap
red) to `#a93226` (muted, matches `.btn-danger`). Single-red-family
palette across buttons + badges + banners. Contrast against white
text: 7.66:1 (excellent for the 16x16 px badge).

### `.btn-warning` semantic role documented

Reviewed the 4 `.btn-warning` callsites — all "Cancel pending
approval request" actions. Decision: KEEP `.btn-warning` for these
sites because they have external impact (admins watching the queue
see the request disappear), which fits the "reversible but
consequential" semantic that warns/oranges traditionally signal.
The CSS comment now spells out: reserve `.btn-warning` for actions
that affect more than the immediate dialog; use plain `.btn` grey
for dismiss-this-modal interactions.

### Migration / rollback

- Light-theme: re-add `:root` light vars, re-add `body.wl-dark`
  override block, restore brightness check in `detectDarkTheme()`.
  Estimated 30 minutes if reverting becomes necessary.
- Drift sweep: per-callsite single-line revert. All edits are
  surface-level visual changes — no behaviour change beyond colour.
- Focus ring: revert one hex value in CSS.

---

## Unreleased — 2026-05-01 (build 636, audit follow-up: contrast + modal hygiene)

### Accessibility: `.btn-warning` AA contrast (gap 2)

The build-634 desaturation pass set `.btn-warning` to `#bf6516` for less
eye-fatigue, which improved the visual but DROPPED the contrast against
white text from 5.9:1 (vivid `#e65100`) to 4.04:1 — below WCAG AA's
4.5:1 floor for normal text. Hover (`#d67828`) was even worse at 3.0:1.
Fixed by darkening to `#a85710` (5.20:1) and `#b25d12` (4.69:1). Border
darkened to `#7a3f0c` to keep the visual hierarchy.

The button stays muted (still distinguishable from `.btn-danger`'s
muted red `#a93226` via hue) and now passes AA on both default and
hover states. Disabled state is intentionally below AA per WCAG 1.4.3
exemption for inactive UI components — that lower contrast IS the
"disabled" signal.

### Modal hygiene: 3 header drifts → standard structure (gap 4)

Three modals were rendering their title via `<h3 style="margin-top:0">`
inline-styled tag instead of the standard `.wl-modal-header` class:

- `wl_modals.js:130` — Remove rule/CSV modal
- `wl_modals.js:365` — "Approval Required" reason prompt
- `wl_save.js:439` — "Audit Comment Required" save prompt

These rendered with subtly-different font size (browser-default `<h3>`
~18px) than the rest of the app's modals (`.wl-modal-header` is 15px,
600 weight). All three migrated to `<div class="wl-modal-header">`.
Width-tuning inline styles (`max-width:520px` etc.) were preserved
since they're per-modal sizing, not drift.

### Button-order audit (gap 5)

After the build-634 `showCpPrompt` fix, ALL 19 dialog modals across
`control_panel.js`, `wl_modals.js`, `wl_versions.js`, `wl_presence.js`,
`wl_save.js`, `wl_csv_io.js`, `wl_table.js` follow the
`[Primary] [Cancel]` DOM order. The Import-CSV modal at
`wl_csv_io.js:694` uses `[Replace] [Merge] [Cancel]` (3 buttons,
destructive option leftmost) — deliberate UX choice, not drift.

### E2E test impact (gap 3)

Zero E2E test files (`tests/e2e/*.cjs`) reference `btn-success`. The
build-635 class rename is safe.

### Light-theme verification (gap 1)

Button colours (`.btn.btn-primary`, `.btn.btn-danger`, `.btn.btn-warning`)
use explicit hex values, NOT CSS variables — they render identically
in light and dark themes. Brand colours for "destructive red" and
"warning orange" should not flip between themes. Modal backgrounds
DO use `var(--wl-bg)` etc. and switch correctly via the existing
`body.wl-dark` override.

### Migration / rollback

- Revert this change set: revert the CHANGELOG entry, revert
  `whitelist_manager.css` warning hex values to `#bf6516`/`#d67828`,
  revert the 3 `<h3 style=...>` → `<div class="wl-modal-header">`
  edits, bump back to the previous build (originally build 635).

---

## Unreleased — 2026-05-01 (build 635, kill `.btn-success` parallel taxonomy)

### UI consistency: collapse green buttons to Splunk's `.btn-primary`

Build 634 originally desaturated `.btn-success` to `#388e3c`, but `.btn-primary`
(used for "+ Add Row", "+ Add Column") stayed at Splunk's bundled vivid
`#1a8929`. Result: same toolbar showed two slightly-different greens
(Save Changes vs Add Row) — the user flagged this as visible drift.

Fixed by killing `.btn-success` entirely and migrating all 5 callsites
to `.btn-primary`:

- `appserver/static/control_panel.js:474` — Approve button (queue list)
- `appserver/static/modules/wl_approval_ui.js:418` — Approve (notification panel)
- `appserver/static/modules/wl_modals.js:883` — Approve modal
- `appserver/static/modules/wl_table.js:334` — Save Changes button
- `appserver/static/whitelist_manager.css:1306-1352` — `.btn.btn-success`
  rule + hover + disabled-state selector removed

All green buttons in the app now share Splunk's bundled `.btn-primary`
(`#1a8929`). Same playbook as the 2026-05-01 `.wl-btn` kill: don't
maintain a parallel CSS taxonomy if a Splunk-bundled equivalent works.

`.btn-danger` (muted brick red `#a93226`) and `.btn-warning` (muted
orange `#bf6516` — historical, superseded in build 636) remain in CSS because
Splunk's bundle ships these classes unstyled.

### Migration / rollback

- Revert: re-add the `.btn.btn-success` rule (with desired shade) to
  `whitelist_manager.css`, revert the 5 callsite class strings.

---

## Unreleased — 2026-05-01 (build 634, separator fix + modal refactor + initial desaturation)

### Bug 1: Save Changes separator rendering inside button

The build-632 toolbar separator used `::before` with `display:inline-block`
which rendered the vertical bar INSIDE the button content box (visible
as a stray `|` to the left of "Save Changes" text). Fixed by switching
to `position: absolute` with `left: -14px`, taking the separator
OUTSIDE the button. Required adding `position: relative` to `#btn-save`.

### Bug 2: Lockdown prompt modal incoherence + reversed button order

`showCpPrompt` (used by Activate Emergency Lockdown and similar
text-input prompts) was rendered with heavy inline styles overriding
the standard `.wl-modal` styling AND had button order `[Cancel] [OK]`
— reversed from every other modal in the app (`[Primary] [Cancel]`).

Refactored to use the standard `wl-modal-header` / `wl-modal-body` /
`wl-modal-actions` structure (matching `showCpConfirm` reference
pattern at `control_panel.js:110-125`) and swapped to `[OK] [Cancel]`.

### Bug 3: Desaturate destructive button palette (initial pass)

User-reported eye fatigue from the vivid `.btn-danger` red (`#c62828`)
across high-density screens (Approval Queue, Trash, Admin Settings).
Muted to Material-Design-style brick red `#a93226`. Same desaturation
applied to `.btn-warning` (`#e65100` → `#bf6516`) and `.btn-success`
(`#1a8929` → `#388e3c`). Build 635 reverted `.btn-success`; build 636
re-tightened `.btn-warning` for AA contrast.

### Migration / rollback

- All three changes revert by reverting CSS hex values and the
  `showCpPrompt` refactor in `control_panel.js`.

---

## Unreleased — 2026-05-01 (build 633, accessibility + L1/L2 follow-up)

### Accessibility: span → button migration (audit finding L3)

The build-632 sweep noted that ~70 in-app action buttons were rendered
as `<span class="btn">` rather than `<button class="btn">`. Visually
identical (Splunk's `.btn` rule applies to both) but `<span>` does NOT
receive the browser's default keyboard tab-traversal or the screen-
reader "button" role announcement. Tab navigation skipped them and
Enter/Space did not activate them.

#### Changed

- All 70+ `<span class="btn ...">` action sites in
  `appserver/static/control_panel.js` and the seven module files
  (`wl_modals.js`, `wl_save.js`, `wl_versions.js`, `wl_presence.js`,
  `wl_nav.js`, `wl_table.js`, `wl_approval_ui.js`) converted to
  `<button type="button" class="btn ...">`. The `type="button"`
  attribute is required so buttons inside any wrapping form do NOT
  auto-submit on click. Click handlers find by `#id` or `data-`
  attribute, so the JS event flow is unchanged.
- Inline-opacity locking pattern (`style="opacity:0.5;
  pointer-events:none"`) preserved on buttons that use it for
  multi-step gating (Remove confirmation, Reject reason, Cancel
  Request) — `pointer-events:none` works on `<button>` exactly like
  on `<span>`, and the existing JS that swaps the inline style on
  state change is unchanged.
- Inline colour overrides on action buttons (`style="background:
  #e74c3c;color:#fff"`) replaced with proper Bootstrap-style class
  attribution (`class="btn btn-danger"` etc.) where redundant. The
  six sites where inline colours simulated `btn-warning` / `btn-danger`
  before those rules existed are now class-driven, taking advantage
  of the rules introduced in build 631.
- `.wl-cp-tab` Control Panel tabs are now real buttons. They
  receive keyboard focus, are announced as "button" by screen
  readers, and respond to Enter/Space. Visual rendering and click
  behavior are unchanged.

#### Tests

- E2E selectors in `tests/test_e2e_realworld.py`,
  `tests/test_e2e_manual_browser.py`, `tests/e2e/test_wl_save.py`,
  and `tests/test_ui_browser.py` made element-agnostic
  (`span.btn-primary` → `.btn-primary`) so they pass for either
  span or button. Done in a separate prior step so tests stayed
  green during the migration.

#### Verified in browser

- Tab traversal reaches all migrated buttons (interactive count went
  from 0 → 56 → 71 on Control Panel as more rows render).
- Enter key activates focused tab buttons (verified on
  `.wl-cp-tab[data-tab="usage"]`).
- Modal lifecycle preserved: Add Column → green Add + grey Cancel,
  Cancel removes overlay; Remove Row → red Remove (locked) + grey
  Cancel; Trash Restore → green Restore + grey Cancel.
- Lockdown prompt → red Activate Emergency Lockdown opens the
  prompt; OK is green primary, Cancel is grey neutral.
- Disabled-state inline opacity pattern intact on buttons; the
  Remove confirmation stays at 0.5 opacity until reason is filled.

### Polish (audit findings L1, L2)

- **L1 panel title alignment** — resolved by the build-632 M2 empty-
  state fix (all single-value panels now render the same way).
  Verified visually in build-633 deploy.
- **L2 active-tab 1px nudge** — fixed via CSS rule
  `.wl-cp-tab, .wl-cp-tab.btn-primary { border: 1px solid transparent;
  padding: 5px 14px; }`. The active tab no longer shifts content by
  1 px when state toggles between `btn` and `btn-primary` (Splunk
  bundle ships them with different border specs).

### Migration / rollback

Class-rename + element-rename only; click handlers find by `#id` or
`data-` attribute, so JS event flow is unchanged. Rollback: `git
revert` the build-633 commit and redeploy at the next build number.
The `.wl-btn-locked` opacity helper is preserved.

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
