# Splunkbase Launch Kit

> **Status**: drafted 2026-05-23 during rc1 4-week hold (Phase 3.6,
> ends ~2026-06-18). Sections are TEMPLATES — placeholder content
> marked with `<...>` needs the maintainer's voice before going
> public.
>
> Three things this doc contains:
>
> 1. **Phase 3.5** — community pre-announcement templates (3 lengths)
> 2. **Phase 4.1** — Splunkbase publisher signup checklist
> 3. **Phase 4.2** — Splunkbase listing draft (all required fields)
>
> The order below mirrors the recommended execution order during
> the hold period.

---

## 1. Phase 3.5 — Community pre-announcement

The 4-week hold period only does its job if there are users running
the rc1 and reporting issues. Without an announcement, the hold is
calendar-time. **The single highest-leverage hold-period activity.**

Recommended venues, by audit value:

| Venue | Why | Effort |
|-------|-----|--------|
| Splunk Community Slack `#dev-talk` | reaches the audience most likely to install + try | 10 min |
| Splunk Lantern (`Submit your blog`) | persists; SEO; ties to Splunkbase listing later | 1-2 hr |
| Splunk dev.splunk.com forums | persists; specific to detection engineering | 30 min |
| LinkedIn post tagging Splunk + SOC people | reaches non-Slack practitioners | 15 min |
| GitHub Discussions tab (this repo) | self-service; visible to anyone landing on the repo | 5 min |

### Short variant (Slack / Discussions, ~80 words)

```
🛡 wl_manager v1.0.0-rc1 just landed — a Splunk app for managing
detection-rule CSV whitelists from a web UI. Built for SOC analysts
who currently edit whitelists by hand-editing CSVs (or via SPL
| outputlookup, with all the audit-trail loss that implies).

Approval workflows, version control, full diff-based audit trail
to a dedicated index. RBAC (viewer / analyst editor / admin /
superadmin). Sigstore-signed releases.

Trying it during the rc1 hold (next 4 weeks) is high-leverage —
issues found now go into v1.0.0 GA.

Repo: github.com/RelativisticJet/wl_manager
Docs: relativisticjet.github.io/wl_manager
```

### Medium variant (dev.splunk.com, LinkedIn, ~200 words)

```
<headline like "Whitelist Manager for Splunk ES — public RC1">

After about a year of solo work, I'm publishing the first release
candidate of Whitelist Manager — a Splunk app that lets SOC analysts
manage detection-rule CSV whitelists from a web UI instead of by
hand-editing CSVs or via `| outputlookup`.

The problem it solves: every SOC I've worked with manages dozens
of detection rules that each have a whitelist CSV (allowed users,
allowed IPs, allowed hosts). The "just edit the CSV" workflow
leaks audit history, makes concurrent edits unsafe, and has no
approval gates — so a single analyst can bulk-remove rows nobody
reviewed.

What v1.0.0-rc1 ships:

- Inline cell editing with row-level approval workflows
- Configurable per-analyst daily limits + approval thresholds
- Full diff-based audit trail to a dedicated `wl_audit` index
- Version snapshots (last 6 retained) with revert
- 4-tier RBAC enforced server-side
- Sigstore-signed releases (cosign-verifiable)
- Splunk Enterprise 9.3 (the only currently-supported on-prem version)

I'm in a 4-week public hold period before cutting v1.0.0 GA. Bugs
or feedback during this window go directly into the GA tag.

Repo: <link>
Docs: <link>
Issues: <link>
```

### Long variant (Lantern blog, ~600-1000 words)

Outline only — fill in your voice:

1. **The problem narrative** (200-300 words) — describe the SOC pain
   point: detection rules, whitelist CSVs, the "edit-the-file"
   workflow, how it falls apart at scale. Use a concrete example
   like the brute-force-detection rule with a 50-row "known service
   accounts" whitelist that drifts over time.
2. **Why existing solutions don't fit** (100 words) — Splunk's own
   lookup editor doesn't do approval workflows; SPL `| outputlookup`
   bypasses audit; Git-PR-on-the-CSV workflows are too slow for
   incident-response timelines.
3. **What wl_manager does differently** (300-400 words) — RBAC,
   approval workflows, dedicated audit index, optimistic locking,
   FIM, expiration. Screenshots inline (`docs/screenshots/01–04`).
4. **What it doesn't do** (100-200 words) — Splunk Cloud (on-prem
   only for v1.0); not for detection-rule SPL itself (just the
   whitelists they reference); not a replacement for ES content
   management.
5. **How to try it during the rc1 hold** (100 words) — Docker demo
   instructions, links, response SLA from SECURITY.md /
   CONTRIBUTING.md.

**Pre-publish checklist before posting any variant:**

- [ ] Verify docs site renders correctly:
      `relativisticjet.github.io/wl_manager`
- [ ] Verify rc1 release artifacts have working download links +
      signature files (`.spl` + `.spl.sig` + `.spl.crt`)
- [ ] Cosign verify-blob command runs cleanly against your local
      copy of the rc1 .spl
- [ ] GitHub Discussions tab enabled (so questions land there, not
      in private DMs that are easy to lose)
- [ ] CONTRIBUTING.md response SLA matches what you can actually
      sustain during the hold

---

## 2. Phase 4.1 — Splunkbase publisher signup checklist

This is the legal/identity-verification step. **Do this NOW during
the hold**, not after Phase 3.8 GA — Splunk's publisher-account
review can take several business days, and you don't want it on
the critical path.

- [ ] Visit <https://splunkbase.splunk.com/> while logged into your
      existing splunk.com Developer account (the one from D15)
- [ ] Navigate to "Publish an app" / "Become a publisher"
- [ ] Confirm display name: **`Oleh Bezsonov`** (real name per D5
      + D15 — this is publicly visible on every listing)
- [ ] Sign the Splunkbase Publisher Agreement (legal terms)
- [ ] Provide contact email: **`communicate.oleh@gmail.com`** (per
      D15 — matches your splunk.com Developer account)
- [ ] If a payment/tax form is requested (some publishers see this
      for paid apps): SKIP / mark "free apps only" since wl_manager
      is Apache-2.0
- [ ] Wait for account-active confirmation email (1-3 business days
      typical)

**Closing decision (will go in DECISION_LOG when done):**

- Publisher name = real name (per D5 + D15; reversibility note in
  D15 covers future LLC vehicle)
- Free-apps-only at signup; revisit if commercialization happens

---

## 3. Phase 4.2 — Splunkbase listing draft

Required fields per Splunkbase's "Create a new app" flow.
**Pre-fill these BEFORE you start the actual submission flow** so
you're not editing under deadline pressure in a web form.

### 3.1 App identity

| Field | Value |
|-------|-------|
| App name | `Whitelist Manager` *(per D4 — confirmed unique on Splunkbase 2026-05-13; no collision found)* |
| App ID | `wl_manager` *(must match `default/app.conf [id].name`)* |
| Author | `Oleh Bezsonov` *(per D5 + D15)* |
| Version | `1.0.0` *(must match the GA tag — NOT rc1)* |
| Splunk versions supported | `9.3.x` *(per `app.manifest`)* |
| Platforms | `Linux`, `Windows` *(Splunk Enterprise on-prem; NOT Cloud — see Phase 1.6 closure for rationale)* |
| License | `Apache 2.0` *(per LICENSE + NOTICE)* |

### 3.2 Listing copy

**Short description** (Splunkbase requires ~120 chars):

```
SOC web UI for managing Splunk ES detection-rule CSV whitelists —
approval workflows, version control, diff-based audit trail.
```

**Long description** (~800-1500 chars, Splunkbase shows on the
listing page):

```
<draft below — adjust to your voice before submitting>

Whitelist Manager gives SOC analysts a web UI for managing the
allowlist CSVs that detection rules in Splunk Enterprise Security
depend on. Instead of hand-editing CSV files or running
| outputlookup commands (which bypass audit trails), analysts
edit rows inline, submit approval requests for bulk operations,
and every change is logged to a dedicated wl_audit index with
before/after diffs.

KEY FEATURES

- Inline cell editing with change tracking and bulk operations
- 4-tier role-based access (viewer / analyst editor / admin /
  superadmin) enforced server-side
- Approval workflows for bulk row removal, column changes, and
  high-impact edits
- Configurable daily limits per analyst tier
- Diff-based audit trail to a dedicated wl_audit index
- Row expiration dates (auto-cleanup at scheduled intervals)
- Last 6 version snapshots with one-click revert
- File Integrity Monitoring detects out-of-band CSV mutations
- Sigstore-signed releases (verifiable with `cosign verify-blob`)
- Designed for desktop SOC workflows (1280×720 minimum)

REQUIREMENTS

- Splunk Enterprise 9.3 (only currently-supported on-prem version
  per Splunk's release-standards page)
- Python 3 (bundled with Splunk 9)
- ~10 MB disk + audit-data storage

NOT INCLUDED

- Splunk Cloud support (on-prem only for v1.0 — Cloud-cert refactor
  is on the v1.1 roadmap)
- Manages the whitelist CSVs that detection rules consume, NOT the
  detection-rule SPL itself
```

### 3.3 Category + tags

| Field | Value |
|-------|-------|
| Primary category | `Security, Fraud & Compliance` |
| Sub-category | `Use Case → Security Operations` *(or `IT Operations` if Splunk forces a single pick)* |
| Tags | `security`, `siem`, `splunk-enterprise-security`, `detection-engineering`, `soc-tools`, `whitelist` *(matches the topics already set on the GitHub repo per Phase 2.11)* |

### 3.4 Assets to upload

- **App archive**: `dist/wl_manager-1.0.0.spl` (built via
  `scripts/package.sh` at GA tag time)
- **Screenshots**: already in repo at `docs/screenshots/` (fresh
  build-669 captures from 2026-05-24; matches the 5 referenced in
  `docs/SPLUNKBASE_LISTING_DRAFT.md` §8):
  - `01-whitelist-manager-dashboard.png`
  - `02-control-panel-approval-queue.png`
  - `03-audit-trail-dashboard.png`
  - `04-inline-csv-editing.png`
  - `05-control-panel-activity.png`
- **Icon**: already in repo at `static/appIcon.png` and
  `appserver/static/appIcon.png` (per the launcher-icon-path quirk
  documented in SPLUNK_QUIRKS.md)

### 3.5 Required URLs

| Field | URL |
|-------|-----|
| Homepage | `https://relativisticjet.github.io/wl_manager/` |
| Repository | `https://github.com/RelativisticJet/wl_manager` |
| Issue tracker | `https://github.com/RelativisticJet/wl_manager/issues` |
| Documentation | `https://relativisticjet.github.io/wl_manager/` |

### 3.6 Pre-submit checklist

- [ ] GA tag `v1.0.0` exists + Sigstore-signed (`release.yml` ran
      cleanly on tag push)
- [ ] §3.5 Version-Tag Consistency pre-flight green per
      `docs/RELEASE_CHECKLIST.md`
- [ ] `dist/wl_manager-1.0.0.spl` downloaded from GitHub Release
      page (not built locally — to confirm the upload matches what
      end-users see)
- [ ] Screenshot files are PNG, < 1 MB each, > 800px wide
- [ ] App icon files (`appIcon.png` + `appIcon_2x.png`) are square
      36px / 72px PNG (Splunkbase rejects non-square / wrong-size)
- [ ] `app.manifest` `info.id.version` matches the tag exactly

### 3.7 After submission

- Splunkbase moves the listing to **"In Review"** status — wait
  state, 1-2 weeks typical per Phase 4.4 estimate
- Findings come back via the publisher dashboard + email
- Each finding gets a corresponding fix commit (atomic, on `main`)
  + re-upload of the patched `.spl`
- Once approved, the listing flips **"Published"** — at this point
  the app is searchable + installable on Splunkbase

---

## 4. After Splunkbase listing goes live (Phase 4.7)

- [ ] Update README badge: add "[![Splunkbase](...)](https://...)" linking
      to the live listing
- [ ] Update repo topics / description if Splunkbase listing copy
      differs from the GitHub description (keep them in sync)
- [ ] Post "now on Splunkbase" follow-up to whatever channel(s)
      ran the Phase 3.5 pre-announcement
- [ ] Pin the GitHub Release notes for v1.0.0 GA to mention the
      Splunkbase listing as the canonical install path for
      production users (Docker demo stays as the "try it" path)

---

## Maintenance note

When this doc is no longer needed (Phase 4.6+ landed and the
content has been moved into permanent locations like README badges,
listing copy is live on Splunkbase, the announcements have been
posted), **delete this file**. It's a launch-kit, not permanent
documentation.

Until then: every claim above that references a Decision Log row
or another doc has the cross-reference inline so the source of
truth is always traceable.
