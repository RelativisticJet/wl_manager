# Splunkbase Listing Draft — Whitelist Manager

**Target listing URL**: `splunkbase.splunk.com/app/<assigned-id>`
**App version submitted**: `1.0.0` (after Phase 3.8 GA tag cut)
**Source of truth for content**: `README.md`, `INSTALLATION.md`, `app.manifest`, `CHANGELOG.md`
**Maintainer**: Oleh Bezsonov (`@RelativisticJet`)
**Date drafted**: 2026-05-24

> **How to use this doc**: Splunkbase's "Submit New App" wizard at
> https://splunkbase.splunk.com/app-developer asks for each field below
> in roughly this order. Copy-paste from the corresponding "Value to
> enter" block. Re-confirm the field name in the live form because
> Splunkbase has changed field labels twice (per their 2024 + 2026
> publisher portal updates) — semantic fields below should still map
> 1:1 even if labels drift.

---

## 1. App identity

| Field | Value to enter | Source |
|-------|---------------|--------|
| App name | `Whitelist Manager` | `app.manifest` → `info.title` |
| Publisher name | `Oleh Bezsonov` | matches Splunkbase Developer account profile |
| Folder name | `wl_manager` | Hard-required; matches the `<app>/` top-level dir in the `.spl` |
| Version | `1.0.0` | `default/app.conf` `[id].version` and `[launcher].version` |
| Build | `670` (post-GA cut) OR `669` if cut without bump | `default/app.conf` `[install].build` |

## 2. Short description (max 200 chars)

> A web UI for managing Splunk Enterprise Security detection-rule CSV whitelists — inline editing, approval workflows, version control, and a full diff-based audit trail. Built for SOC teams.

(196 characters; safe under 200-char Splunkbase limit. Tested in 2026.)

## 3. Long description (Markdown supported; aim ~1500-3000 chars)

Paste the following block. Splunkbase renders Markdown; backticks render as inline code; double-line breaks produce paragraphs.

```markdown
# Whitelist Manager

Built for SOC teams who need to manage detection-rule exceptions
without touching raw CSV files, Splunk configs, or the filesystem.

## What it does

SOC analysts open a Splunk dashboard, pick a detection rule, pick a
CSV whitelist mapped to that rule, edit rows inline, add or remove
entries, and every change is diff-logged to a dedicated `wl_audit`
index. The app handles approval workflows, daily usage limits per
analyst, version snapshots (last 6 retained), and an audit dashboard
with 30 panels covering rule lifecycle, row CRUD, admin actions, FIM
alerts, approval queue events, and recovery scripts.

## Why it exists

The default Splunk + Splunkbase + ES workflow for managing detection
rule whitelists is: open a `.csv` lookup file in Splunk Web → edit
the cell → save. That's: (1) no audit trail, (2) no per-row reason,
(3) no approval gate, (4) no diff, (5) no version revert. SOC teams
that need any of those build them in-house. Whitelist Manager is the
shipped version of that in-house tool.

## Key features

- **Inline cell editing** with change tracking (before/after diffs).
- **Approval workflows**: configurable thresholds trigger admin
  approval for bulk operations. Configurable per-action.
- **Daily usage limits**: per-analyst caps on row removals, edits,
  additions, reverts. Configurable from the Control Panel.
- **Self-approval prevention**: the submitter of a request cannot
  approve it.
- **Version control**: every save snapshots the prior version. Last
  6 versions retained per CSV; one-click revert to any of them.
- **Diff-based audit**: every action emits a structured event to
  `index=wl_audit` with row-level before/after values. Compatible
  with the bundled Audit Trail dashboard out of the box.
- **RBAC**: 4 tiers (Analyst Viewer / Analyst Editor / Admin /
  Superadmin). Granular permission gates for create / delete /
  approve / reset-usage / unlock-emergency.
- **File-integrity monitoring**: 60-second scripted-input scans of
  CSV files for unauthorized changes (e.g., direct SPL
  `outputlookup` bypass). Dual-store baseline (file + KV) to
  prevent silent re-baselining.
- **Emergency lockdown**: superadmin can freeze all write operations
  app-wide; deactivation requires a different superadmin.
- **Cloud-compatible**: passes both AppInspect standalone and cloud
  profiles. SLIM-validation carve-out documented in
  `.appinspect_api.expect.yaml`.

## Architecture (1-line summary)

Single Splunk REST handler (`bin/wl_handler.py`) dispatches 110+ actions
across 20 backend modules. Frontend is jQuery + AMD/RequireJS modules
(modularized in Wave 3 / Phase 3.x). Audit events go to a dedicated
`wl_audit` index. All app state writes go through a write-once
filelock + KV-backed counters that survive concurrent admin traffic.

## Source

Source code, documentation, and SBOM:
https://github.com/RelativisticJet/wl_manager

Hosted documentation: https://relativisticjet.github.io/wl_manager/

## Trademark notice

Splunk® and Splunk Enterprise Security® are registered trademarks of
Cisco Systems, Inc. This is an independent third-party app and is not
affiliated with, endorsed by, or sponsored by Splunk Inc.
```

(After paste, character count: ~3100. Splunkbase max is ~5000 chars
on the long-description field.)

## 4. Category / classification

| Field | Value | Source / reasoning |
|-------|-------|-------|
| Primary category | `Security` (or Splunkbase's current equivalent — "IT Operations" is the fallback if "Security" requires a sub-category we don't qualify for) | App is SOC-tooling; AppInspect cloud profile passes. |
| Secondary category (if available) | `Compliance` (audit trail + RBAC + approvals are the core value props) | — |
| Tags / topics (free-text or pick-list per Splunkbase version) | `splunk`, `splunkbase`, `siem`, `soc-tools`, `splunk-enterprise-security`, `detection-engineering`, `audit-trail`, `rbac`, `whitelist`, `approval-workflow` | Mirrors the GitHub repo topics set in Phase 2.11. |

## 5. Supported platforms

| Field | Value | Source |
|-------|-------|--------|
| Splunk Enterprise versions | `9.2.x`, `9.3.x` (minimum tested: 9.3.1) | `app.manifest` `platformRequirements.splunk.Enterprise` + `docker-compose.yml` test image pin. The quarterly version-pinning audit (next 2026-07-18) re-evaluates whether to support 9.4 / 10.x. |
| Splunk Cloud Platform | YES (AppInspect cloud profile passes) | `appinspect-api.yml` workflow output |
| Splunk Light | NO | Splunk Light is EOL. Out of scope. |
| Splunk ES required? | NO (operates on any lookup CSV in any app context); recommended for SOC use | `bin/wl_handler.py` REST handler has no `splunk_es` dependency import |
| OS support | Linux, Windows, macOS — wherever the indexer runs | `bin/wl_filelock.py` uses cross-platform fcntl/msvcrt fallback |
| Python version | 3.9+ (per `app.manifest`); tested on Splunk's bundled Python 3.9 + 3.11 | `bin/*.py` headers |

## 6. Pricing + licensing

| Field | Value |
|-------|-------|
| Price | **Free** |
| License | **Apache License 2.0** (matches GitHub repo `LICENSE` file) |
| Source available | **YES** — link to the GitHub repo |

## 7. Support

| Field | Value |
|-------|-------|
| Support type | Community (GitHub Issues) |
| Support URL | https://github.com/RelativisticJet/wl_manager/issues |
| Maintainer response SLA | Best-effort; this is a solo-maintainer project. CONTRIBUTING.md documents "please be patient" language per Phase 3.2 risk R3.2. |
| Documentation URL | https://relativisticjet.github.io/wl_manager/ |
| Bug tracker URL | https://github.com/RelativisticJet/wl_manager/issues |

## 8. Screenshots

Splunkbase typically allows 3-5 screenshots. Upload these from `docs/screenshots/` (fresh build-669 captures):

| Order | File | Caption |
|-------|------|---------|
| 1 | `01-whitelist-manager-dashboard.png` | Main dashboard — pick a detection rule, pick a CSV, edit rows inline |
| 2 | `04-inline-csv-editing.png` | Inline editing with change tracking on `DR55_brute_force_login` / `DR55_brute_force_users.csv` |
| 3 | `02-control-panel-approval-queue.png` | Control Panel — Approval Queue tab (admin's view of pending requests) |
| 4 | `03-audit-trail-dashboard.png` | Audit Trail dashboard — 30 panels covering all event categories |
| 5 | `05-control-panel-activity.png` | Control Panel — Activity tab (analyst + admin daily usage counters) |

## 9. .spl artifact

| Field | Value |
|-------|-------|
| File | `wl_manager-1.0.0.spl` (built by `scripts/package.sh` after the GA `default/app.conf` version bump) |
| Sigstore-signed | YES — `cosign verify-blob` instructions in `INSTALLATION.md` |
| SHA256 | Listed in `dist/wl_manager-1.0.0.spl.sha256` (auto-generated by `scripts/package.sh`) |
| Source of binary | GitHub Release page (Phase 3.8 tag) — direct link in submission notes |

## 10. Pre-submission checklist (run before clicking "Submit")

- [ ] GA `v1.0.0` tag cut and `.spl` built (post Phase 3.8)
- [ ] Sigstore signature attached to the GitHub Release
- [ ] `scripts/package.sh` produced `dist/wl_manager-1.0.0.spl` + `.sha256`
- [ ] AppInspect API on the final `.spl` PASSES — re-run `appinspect-api.yml` against the GA tag
- [ ] All 5 screenshots updated for build 669 (already captured 2026-05-24)
- [ ] Long-description block proof-read for typos and broken markdown
- [ ] No mention of "rc1" or "beta" in user-facing copy
- [ ] README + CHANGELOG reference the GA version (`1.0.0`, not `1.0.0-rc1`)
- [ ] Trademark-notice paragraph present in long description (Splunkbase content policy requires it)

## 11. Post-submission

| Event | Expected timeline | Action |
|-------|------------------|--------|
| Submission acknowledged | Within 24h | None — just confirm "In Review" status |
| Reviewer feedback (round 1) | 1-2 weeks typical | Address each finding as an atomic commit; re-package; re-upload |
| Listing live | After all rounds clear | Update `README.md` to badge the listing URL; post community announcement (Phase 4.7) |

## 12. What is NOT in this doc

- The Splunkbase Developer account credentials — kept in the maintainer's personal password manager per `docs/DECISION_LOG.md` 2026-05-16 followup row (same secrets storage as `splunk.com` account)
- The actual upload URL — go directly to https://splunkbase.splunk.com/app-developer when ready
- Pricing tier details — N/A; free app
