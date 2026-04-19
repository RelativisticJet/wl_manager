# Pre-Public Release Plan for `wl_manager`

> **Status: PARKED.**
>
> Do NOT start executing this plan until the user explicitly says one of:
> `"start the pre-public plan"`, `"run the public-ready checklist"`, or
> `"we're done fixing the app, let's prep for public"`.
>
> As of 2026-04-19, the user is actively auditing the **Audit Trail** and
> **Control Panel** and finding issues. Graphify + RAPTOR-adapted Semgrep
> checks surfaced more structural concerns than were visible at the start
> of the audit. More unknowns are expected to be found during the current
> fix wave.

---

## Purpose

When the user is ready to flip `wl_manager` from private to public,
this plan captures **exactly what needs to be verified first**, broken
into discrete gates with acceptance criteria so we don't miss anything
and we don't rush the flip.

The plan is deliberately more cautious than a typical
"just push the button" release. Every production incident in the
author's experience with open-source security tool releases comes from
skipping pre-flight. The ~5–6 hours of work here buys you a release
that can withstand external scrutiny (bug hunters, reviewers, future
you looking back at the git history).

---

## Why we're not starting yet (as of 2026-04-19)

1. **Active bug-fix wave.** The user is reviewing Audit Trail and
   Control Panel and finding real issues. Shipping those as-public
   would bake the bugs into git history.
2. **Phase 3/4 UI not exercised.** The security consolidation landed
   cleanly on backend smoke-tests (curl) and unit tests, but the
   browser path hasn't been walked since the Phase 3 deploys. The
   CLAUDE.md "Verification Before Done" rule explicitly calls this
   out.
3. **Doc drift.** `default/app.conf` says build 593 but CLAUDE.md's
   "Current State" section still says build 587. Going public with
   stale docs is a bad look.
4. **MEMORY.md says not-ready.** The `project_release_status.md`
   memory file says "NOT release-ready (2026-04-16). More features +
   E2E rounds planned. Don't auto-suggest packaging/AppInspect/
   Splunkbase." That note hasn't been invalidated.
5. **No artificial deadline.** Nothing forces a public flip by a
   specific date. Do it when it's ready.

---

## Current state snapshot

### ✅ Green (ship as-is)

- Security consolidation Phases 1–4 complete and committed
  (`3521b0c`, `0ea1cf1`, `7c19d62`, `255002e`, `98390d2`, `1b07350`)
- 125 unit tests green (`test_wl_limits`, `test_wl_hmac_key`,
  `test_wl_expiration_cleanup`, `test_wl_fim_common`, unit/`test_approval`)
- Semgrep CI gate live and green on `bin/` (commit `57bfbc6` +
  docs in `9dd53a1`)
- Complete commit provenance for every architectural decision in
  `CLAUDE.md` Decision Log

### 🟡 Yellow (known, acceptable to ship with documented caveats)

- Test coverage 32% (target 80%) — already flagged in
  `CONTRIBUTING.md` under "Known Limitations"
- `wl_handler.py` is ~5,200 lines — flagged
- `control_panel.js` is ~2,000 lines (not yet modularized) — flagged
- Semgrep OSS inter-procedural gap papered over with explicit
  sanitizer annotations — documented in `tests/semgrep/README.md`

### 🔴 Red (must fix before public — the fix wave)

_Fill this in as current audit surfaces issues. Format:
`YYYY-MM-DD — area — one-line description — status`._

- 2026-04-19 — Audit Trail — user investigating — OPEN
- 2026-04-19 — Control Panel — user investigating — OPEN
- 2026-04-19 — Doc drift — CLAUDE.md says build 587, actual 593 — OPEN
- 2026-04-19 — UI E2E — no browser-level smoke of Phase 3/4 builds
  (589 → 593) — OPEN

---

## Activation triggers

**Start gate 1** only after ALL of the following are true:

1. All entries in the "Red" section above show `FIXED` or `ACCEPTED`
   (with explicit user sign-off on anything not fixed).
2. User explicitly issues one of the activation phrases at the top of
   this file.
3. At least one commit after the last `Red` entry is closed, so the
   plan starts from a known-clean baseline.

**Do not autonomously activate** this plan. The user is in control of
the public/private decision.

---

## The 11-gate plan (run sequentially, commit at each boundary)

### Gate 1 — Documentation drift audit

| | |
|---|---|
| **Owner** | agent |
| **Estimate** | 30 min |
| **Acceptance** | CLAUDE.md "Current State" matches actual build number; every file/function referenced in CLAUDE.md still exists; MEMORY.md index reflects all current `feedback_*.md` files; "Pending / Future Work" section has no completed items left in it |
| **Commands** | grep-sweep per CLAUDE.md "Documentation Drift Audit" checklist |
| **Output** | commit: `docs: pre-public drift audit (gate 1)` |

### Gate 2 — Secret / PII sweep of git history

| | |
|---|---|
| **Owner** | agent (run) + user (review flags) |
| **Estimate** | 20 min |
| **Acceptance** | `git log --all -p` grep for: passwords (`Chang3d`, `admin:`), email addresses (committer identity), internal hostnames, API keys, PEM blocks, AWS/Stripe/GCP key patterns — produces zero hits OR every hit is explicitly reviewed and accepted |
| **Commands** | `opensource-sanitizer` skill or manual grep sweep |
| **Output** | report file `.planning/go-public/gate-2-report.md`; commits to scrub anything scrubbable; any unscrubbable secrets (e.g. `Chang3d!` as documented dev password) flagged for user decision |
| **Escape hatch** | If a real secret is found in history, STOP and discuss whether to rewrite history (painful, changes all hashes) vs. rotate the secret and accept the exposure |

### Gate 3 — Internal-content audit

| | |
|---|---|
| **Owner** | agent (flag) + user (decide) |
| **Estimate** | 30 min agent + your review |
| **Scope** | `.planning/` (this whole tree — lots of internal context), `docs/` (may reference internal tooling or customer context), `tests/fixtures/` (may contain real data snapshots), README and all `.md` files |
| **Acceptance** | Every file in scope either (a) is safe to publish as-is, (b) is scrubbed, (c) is moved to a private mirror, or (d) is gitignored and removed from history |
| **Output** | report file `.planning/go-public/gate-3-report.md` listing every flagged file + proposed disposition; user signs off on each line |
| **Pause point** | STOP after flag list; do NOT scrub autonomously — user reviews and decides disposition item-by-item |

### Gate 4 — Dependency + license audit

| | |
|---|---|
| **Owner** | agent |
| **Estimate** | 15 min |
| **Acceptance** | `pip-audit -r requirements.txt` clean or CVEs triaged; every third-party dep in `DEPENDENCIES.md` has license compatible with MIT (Apache 2.0, BSD, MIT, ISC — OK; GPL/AGPL/LGPL — needs user decision on license compatibility); `package.json` if any, same check |
| **Output** | commit: `chore: pre-public dependency audit (gate 4)` + updated `DEPENDENCIES.md` if any drift |

### Gate 5 — Installation validation from a fresh clone

| | |
|---|---|
| **Owner** | agent |
| **Estimate** | 45 min |
| **Acceptance** | Clone the repo into a fresh directory (e.g. `/tmp/wl_manager_fresh`); follow README.md Quick Start step-by-step verbatim without consulting any other source; Docker demo comes up; `http://localhost:8000` is reachable; admin can log in; at least one CSV can be edited and audited. No "obvious next step that's not in the README." |
| **Failure mode** | If a step is unclear or undocumented, fix the README in the same pass. Most common: `make` commands referenced in CONTRIBUTING.md but no actual `Makefile`; env vars assumed set but not documented; Docker network name assumed but not printed. |
| **Output** | commit: `docs: pre-public README validation (gate 5)` |

### Gate 6 — UI E2E after Phase 3/4

| | |
|---|---|
| **Owner** | agent + user (final click-through) |
| **Estimate** | 1 hr |
| **Acceptance** | All E2E Playwright tests green OR (if infrastructure not ready) a manual browser smoke covering: save CSV, revert CSV, add/remove row with approval, approval queue action, notification bell, audit drilldown, control panel tabs including Audit Trail |
| **Red flag** | Any of the currently-known Audit Trail and Control Panel issues (user's current investigation) must be CLOSED before this gate runs — otherwise the gate just reconfirms known-bad state |
| **Output** | commit: `test: pre-public UI E2E smoke (gate 6)` + any test additions for paths that had no coverage |

### Gate 7 — Security disclosure process

| | |
|---|---|
| **Owner** | user (decision) + agent (draft) |
| **Estimate** | 15 min |
| **User decides** | Disclosure channel — options: (a) GitHub Private Vulnerability Reporting (free, zero-ops, just check a box), (b) dedicated security email alias (e.g. `security@...`), (c) "report as GitHub issue" (bad for anything exploitable; OK for small projects with no hostile threat model) |
| **Acceptance** | `SECURITY.md` exists at repo root; describes disclosure channel, response SLA, scope (which components are in / out of scope), acknowledgements policy (optional) |
| **Output** | commit: `docs: add SECURITY.md (gate 7)` |

### Gate 8 — Release notes / CHANGELOG for v1.0

| | |
|---|---|
| **Owner** | agent |
| **Estimate** | 20 min |
| **Acceptance** | `CHANGELOG.md` present at repo root; aggregates what's in the first public release (reasonable cutoff: everything through current HEAD at the time gate 8 runs); uses Keep-a-Changelog format or similar; version tagging scheme decided (likely `v1.0.0-public` or similar) |
| **Output** | commit: `docs: CHANGELOG for v1.0 (gate 8)` |

### Gate 9 — Splunk AppInspect validation run

| | |
|---|---|
| **Owner** | agent |
| **Estimate** | 15 min |
| **Acceptance** | `bash scripts/validate.sh` runs clean; `bash scripts/package.sh` produces a valid `.spl` that imports successfully into the fresh-clone Docker container from gate 5; no AppInspect warnings beyond any that the project has already triaged as accepted |
| **Output** | commit: `build: pre-public AppInspect clean (gate 9)` + updated `scripts/` if needed |

### Gate 10 — Final pre-flight (user review)

| | |
|---|---|
| **Owner** | user |
| **Estimate** | 10 min |
| **Acceptance** | User reviews cumulative diff from gates 1–9, confirms the repo reflects what they want to publish. User flips visibility to Public via GitHub Settings → General → Danger Zone → "Change visibility." |
| **No agent action** | This is strictly a user step. Agent waits. |

### Gate 11 — Post-public enablement

| | |
|---|---|
| **Owner** | user (clicks) + agent (guides) |
| **Estimate** | 30 min |
| **Steps** | 1. Settings → Branches → Add rule for `main` → Require status checks → add "Run Semgrep taint rules" as required + "Require branches to be up to date." 2. Settings → Code security → enable Code scanning → CodeQL default setup (now free, because public). 3. Settings → Code security → enable Dependabot alerts + security updates. 4. Settings → Code security → enable Private Vulnerability Reporting if chosen in gate 7. 5. Tag `v1.0.0-public` and push the tag. 6. (Optional) create a GitHub Release from the tag with CHANGELOG content. |
| **Acceptance** | Fresh PR to a branch that intentionally violates a Semgrep taint rule → CI fails → PR is unmergeable. Confirms enforcement actually works, not just configured. |

---

## User decisions needed before gate 1 starts

Revisit these at activation time (some may have drifted):

1. **Start the whole plan?** Yes / not yet / modified scope
2. **Gate 3 (internal-content audit)** — agent pauses after flagging for your review (recommended), OR scrubs obvious items autonomously and pauses only on ambiguous ones?
3. **Gate 7 (vulnerability reporting)** — (a) GitHub Private Vulnerability Reporting, (b) dedicated security email, or (c) "GitHub issues for now"?
4. **Gate 6 (UI E2E)** — full Playwright suite under `tests/e2e/` or shorter manual browser smoke?
5. **Tag scheme** for v1.0 — `v1.0.0`, `v1.0.0-public`, `v2.0.0` (given CLAUDE.md already has "version: 2.0.0"), or other?

---

## What's intentionally NOT in this plan

- **Test coverage to 80%** — months of work; current 32% is OK to ship documented
- **`wl_handler.py` module split** — already documented as known limitation
- **`control_panel.js` modularization** — already documented
- **Bug bounty program** — premature; start with Private Vulnerability Reporting
- **Automated release pipeline** — manual tag + Release for v1.0 is fine
- **Documentation for every edge case** — ship what we have, improve iteratively

---

## Appendix A — Current known issues (fix wave)

**This section is active while we're in the fix wave. Update as issues
are identified and closed.**

### Format

```
- YYYY-MM-DD — AREA — description — OPEN|INVESTIGATING|FIXED|ACCEPTED
```

### Issues

- 2026-04-19 — Audit Trail — user investigating — OPEN
- 2026-04-19 — Control Panel — user investigating — OPEN
- 2026-04-19 — Doc drift — CLAUDE.md "Current State" says build 587,
  actual is 593 — OPEN
- 2026-04-19 — UI E2E gap — no browser-level verification of commits
  `7c19d62` through `1b07350` — OPEN

### Exit criteria for fix wave

All issues above show `FIXED` or `ACCEPTED` (with user sign-off), AND
no new issues have been opened in the last N days (user's judgment).
Then activate gate 1.

---

## Appendix B — Revision log for this plan

- 2026-04-19 — initial version, while user continues fixing application-layer
  issues found in Audit Trail and Control Panel
