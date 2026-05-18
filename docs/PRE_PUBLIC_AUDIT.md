# Pre-Public Audit (Phase 3.1)

**Date:** 2026-05-18
**Commit at audit time:** `f9ba6c6` (HEAD of `main`)
**Tracked files swept:** 564 (`git ls-files | wc -l`)
**Audit role:** Phase 3.1 of [`docs/PUBLIC_RELEASE_PLAN.md`](PUBLIC_RELEASE_PLAN.md) — read every file from an outsider's perspective; flag anything sensitive or unprofessional before the Phase 3.4 public flip.

This document is the durable record of the sweep. Phase 3.4 (private→public)
must not flip until every CRITICAL/HIGH finding here is **Resolved**.

---

## Methodology

For each file class I asked: *would a hostile outsider (competitor,
adversary, journalist, future legal review) find anything here
embarrassing, sensitive, contradictory, or unprofessional?*

Concrete checks performed:

1. **PII / personal content** — `git ls-files` enumerated against
   keywords `point72|firecrawl|hedge|career|resume|cv|personal|todo|notes`;
   gmail/yahoo/outlook/protonmail/icloud regex over all tracked
   markdown/code/config files (excluding `.venv-appinspect/` which is
   gitignored).
2. **Credentials** — grep for hardcoded passwords beyond the documented
   `Chang3d!` dev-container default (which is allowlisted in
   [`.gitleaks.toml`](../.gitleaks.toml)).
3. **Internal infrastructure** — RFC1918 IP regex over tracked source
   and docs (excluding test fixtures, sample CSVs, demo seed data, and
   API documentation example payloads).
4. **Code red flags** — `TODO|FIXME|XXX|HACK` in `bin/`, `appserver/static/`.
5. **Debug statements** — `console.log|console.debug|debugger;` in
   tracked source.
6. **License consistency** — every `LICENSE`/`MIT`/`Apache` mention
   across `README.md`, `docs/index.md`, `mkdocs.yml`, `app.manifest`,
   `sbom.cdx.json`, `NOTICE`, and `CONTRIBUTING.md`.
7. **Identity consistency** — `wildleo91` / `communicate.oleh@gmail.com`
   / `Security Engineering` mentions checked against D5 + D15 +
   D17 locked decisions.
8. **Top-level inventory** — every file/dir at repo root reviewed.

---

## Findings

### CRITICAL — fixed in-turn AND purged from history per user decision

**F-C1: `.firecrawl/point72-*.md` (3 files) — personal job-search research tracked in repo.**

Files (now gone from working tree AND history):

- `.firecrawl/point72-about.md` (404-page scrape, 121 B)
- `.firecrawl/point72-home.md` (Point72 home-page scrape, 6.2 KB)
- `.firecrawl/point72-splunk-security-engineer.md` (Point72 job posting, 5.2 KB)

These were page-scrape artifacts from a research session unrelated to
wl_manager (likely employer-research). They were accidentally committed
bundled with an unrelated `chore(04-04)` commit on 2026-04-01
(original SHA `15a2250`). Phase 0.10 secret-scan did not flag them
because they contain no credentials, but the outsider-perspective lens
immediately surfaced them.

**Resolution (working tree):** removed in commit `2bcbc5e`
(`docs(release): Phase 3.1 — pre-public audit + in-turn fixes`).
Added `.firecrawl/` to `.gitignore` so the directory cannot be
re-tracked by accident.

**Resolution (git history):** user explicitly authorized history
sanitization ("I do not want anyone know or see that I did research
on Point72 or anything else not related to the project"). Executed
`git filter-repo --path .firecrawl --invert-paths` 2026-05-18:

- All 498 commits in scope at rewrite time were rewritten
  (`git log --oneline | wc -l` returns 499 today — that's the
  498 rewritten plus one follow-up commit `396a9b4` added after
  the force-push to document closure).
- Original `15a2250` (which bundled .firecrawl additions with a
  legitimate `wl_pipelines.py` removal) reshaped to `a92af77` —
  same commit message, same legitimate changes, .firecrawl lines
  removed.
- Original `2bcbc5e` (this audit's commit) reshaped to `6e3efbe`
  — same effect, just no historical trace of .firecrawl ever
  existing.
- Force-pushed to `origin/main` with `--force-with-lease`. Repo
  is private with zero external clones at time of rewrite, so no
  collaborator history was invalidated.

Tag `pre-firecrawl-purge-backup-2026-05-18` was created locally
before the rewrite but filter-repo rewrote it too (it now points at
the post-rewrite HEAD `6e3efbe`). Pushed to origin as a date-marker
of the rewrite, not as a recoverable backup.

**Lesson** (for future contributor handoff if a similar situation
arises): `git filter-repo` rewrites annotated tags inside the repo
along with commits. To preserve an actual pre-rewrite backup,
`git clone . ../backup` BEFORE running filter-repo — the clone
preserves the unmodified history independently. The protection that
actually worked here was that GitHub's `origin/main` retained the
pre-rewrite state until the explicit force-push.

---

### CRITICAL — fixed in-turn (added post-audit, 2026-05-18)

**F-C2: `lookups/` polluted with E2E test artifacts that would ship to customers.**

The initial Phase 3.1 sweep checked `lookups/DR*.csv` for "real IPs vs
synthetic" (the RFC1918 lens) and confirmed all hostnames/IPs were
synthetic. It did NOT check "is every CSV here legitimate seed data
vs leftover test fixture." User raised the concern during the
public-flip readiness discussion, and a targeted recheck found
significant pollution.

**Why this would have been actively user-facing**: files in `lookups/`
are packaged into the `.spl` and installed onto every customer's
Splunk instance. `DR_BROWSER_TEST.csv` / `DR_TEST_2.csv` /
`DR_E2E_ADMIN.csv` would have shown up as real whitelist dropdown
options in the customer's UI. That's not "weird stuff in source"; that's
visible product pollution.

**Removed (tracked, 29 files)**:

- 11 root-level test CSVs that match the
  `DR_(TEST|STRESS|VERSION|TRASH|APPROVAL|E2E|BROWSER|LONG)_*.csv`
  or `AL_(test|super)_*` patterns:
  `DR_TEST_2.csv`, `DR_TEST_3.csv`, `DR_E2E_ADMIN.csv`,
  `DR_BROWSER_TEST.csv`, `DR_VERSION_TEST.csv`, `DR_TRASH_TEST.csv`,
  `DR_APPROVAL_TEST_1_v2.csv`, `DR_LONG_NOTIFICATION_TEST_2.csv`,
  `DR_STRESS_2000x100.csv`, `AL_test_1775974555656.csv`,
  `AL_super_1775974555731.csv`.
- 18 files in `lookups/_trash/` — runtime soft-delete state captured
  from past test sessions. The `_trash/` directory is the running
  app's recycle-bin storage, not source-of-truth.

**Removed (working-tree only, 6 files, never tracked)**: the
DR777 / DR778 / DR998 test artifacts that the existing `.gitignore`
patterns at `lookups/DR777_*.csv` / `DR778_*.csv` / `DR998_*.csv`
already covered. These were untracked but visible in `ls`; cleaned
up for tidiness.

**`rule_csv_map.csv` trimmed from 33 rows → 19 rows**. The 14 removed
rows split into two groups:

- 10 mappings that pointed at the test CSVs above (now orphaned).
- 4 mappings that pointed at CSVs which never existed in the working
  tree at all: `DR_TEST_4.csv`, `test_gated_csv.csv`,
  `AL13_test_limits.csv`, `AL15_super_exempt.csv`. These were a
  pre-existing "ghost map entry" bug — the map was already
  internally inconsistent. Removing them is a net improvement
  regardless of public release.

**`.gitignore` updated**: `lookups/_trash/` is now ignored alongside
the already-ignored `lookups/_versions/`, `lookups/_detection_rules.json`,
and the runtime `_*.json` state files. Future test runs that exercise
the trash feature will not re-track its state.

**Test-impact verification before deletion**: every test referencing
the deleted CSV names (`tests/test_e2e_api.py`,
`tests/e2e/test_admin_limits.cjs`, `tests/test_e2e_advanced.py`,
`tests/unit/test_approval_queue_state_machine.py`,
`tests/integration/test_chaos_save_csv_chain.py`,
`tests/test_e2e_manual_browser.py`) creates the CSV at runtime via the
REST API as part of test setup. None depend on the tracked file
pre-existing on disk. Deletion is safe.

**Why the initial audit missed it**: the "outsider would find this
embarrassing" lens has multiple orthogonal sub-lenses (real-data
leaks, branding inconsistency, legal/license issues, product
pollution, dev cruft, ...). The initial pass exercised four of them
strongly but skipped product-pollution-via-tracked-data. F-C2
extends the audit lens; future pre-public sweeps should explicitly
ask "does every file in a directory that ships to customers belong
in the product" for each directory under the .spl payload.

---

### HIGH — fixed in-turn

**F-H1: License inconsistency — LICENSE/NOTICE say Apache 2.0; README, mkdocs.yml, docs/index.md, app.manifest, sbom.cdx.json claimed MIT.**

Phase 0.6 (2026-05-15, commit `e55e9ab`) deliberately switched the
project license from MIT to Apache 2.0 per locked decision D1
(rationale: explicit patent grant matters for a security tool;
matches `splunk/*` official repos; enterprise procurement allow-lists
Apache more often than MIT). The `LICENSE` and `NOTICE` files were
updated to Apache 2.0 text. Five downstream sites were missed:

| File | Old claim | New value |
|------|-----------|-----------|
| `README.md` (badge) | `License-MIT` | `License-Apache_2.0` |
| `README.md` (License section) | "MIT License" | "Apache License 2.0" + NOTICE pointer |
| `docs/index.md` (License section) | "MIT — see LICENSE" | "Apache License 2.0 — see LICENSE and NOTICE" |
| `mkdocs.yml` (copyright) | "released under the MIT License" | "released under the Apache License, Version 2.0" |
| `app.manifest` (`license.name`) | `"MIT"` | `"Apache-2.0"` |
| `sbom.cdx.json` (`licenses.id`) | `MIT` | `Apache-2.0` |
| `sbom.cdx.json` (`publisher`) | `"Security Engineering"` (placeholder) | `"Oleh Bezsonov"` (per D5) |

Two intentional MIT mentions are preserved (correctly):

- `NOTICE` lines 31–32 — jQuery and Bootstrap are MIT-licensed third
  parties, bundled with Splunk Enterprise, consumed via the runtime
  platform; not the wl_manager project license.
- `docs/PUBLIC_RELEASE_PLAN.md` lines 28 and 77 — historical record of
  the D1 locked decision and the Phase 0.6 closure. Must not be
  edited (it's the audit trail of the switch).

**Why this would have been a real problem in public:** a user reading
the MIT badge in the README might rely on MIT's terms (no explicit
patent grant, simpler attribution requirements). Apache 2.0 actually
applies. Court precedent on "which license controls when files
disagree" is inconsistent — the conservative reading is that the
LICENSE file controls, but having the README contradict it is the
kind of fact pattern that produces avoidable legal ambiguity.

**Resolution:** all 6 sites updated to Apache-2.0 in this audit's
commit.

---

### LOW — fixed in-turn

**F-L1: `test_py.py` at repo root — 1-line `print(123)` dev cruft.**

A single-file Python script (`print(123)`, 11 bytes) was tracked at
the repo root. Origin unclear; presumably a dev sanity-check from an
early session. Adds nothing; confuses an outsider reading the tree
("what is this script for?").

**Resolution:** removed in this audit's commit.

---

### LOW — resolved post-audit per user decision

**F-L2: `docs/superpowers/` → `.planning/superpowers/` (RESOLVED 2026-05-18).**

Two markdown files under `docs/superpowers/{plans,specs}/` documented
the Wave-3 entry-point-rewrite plan written for an "agentic worker"
audience, with references to internal tooling (`superpowers:subagent-driven-development`,
`superpowers:executing-plans`) and per-step checkboxes for an
implementing agent. The content is not embarrassing, but the *framing*
(internal-tooling jargon, agentic-worker reader assumption) is
confusing for a human contributor reading the repo for the first time.

**Resolution (user decision)**: moved to `.planning/superpowers/` to
colocate with other internal-planning artifacts that are still tracked
but contextualized as planning history (the `.planning/` directory is
the conventional home for such material in this repo). The in-file
Spec pointer was updated to the new path; `mkdocs.yml not_in_nav` glob
entries removed since the files are no longer under `docs/`.

**F-L3: `.mcp.json.example` contains Windows-specific paths — deferred to v1.1 per user decision.**

The committed example points at `C:\Users\PC\AppData\Local\Microsoft\WindowsApps\python.exe`
and `C:/Users/PC/wl_manager` as MCP server paths. A Mac or Linux
contributor copying this to `.mcp.json` will need to substitute
those manually. The comments in the file already explain the
substitution.

**Resolution (user decision)**: defer to v1.1. Not load-bearing for
public release. Tracked in `docs/PUBLIC_RELEASE_PLAN.md` §10 as a
v1.1-backlog candidate when the next polish pass happens.

---

## Items checked and PASSED (no finding)

### Personal identity

- `communicate.oleh@gmail.com` appears in `docs/DECISION_LOG.md`,
  `docs/PUBLIC_RELEASE_PLAN.md`, `docs/RUNBOOKS.md` — intentional per
  locked decision D15 (Splunkbase publisher email is publicly visible
  on every Splunkbase listing; trade-off accepted).
- `wildleo91@gmail.com` appears only in `docs/PUBLIC_RELEASE_PLAN.md`
  D17 historical entry documenting the identity switch away from this
  handle — no current attribution. Acceptable.
- All committer emails on commits since D17 (2026-05-17) map to
  `20013626+RelativisticJet@users.noreply.github.com` — GitHub's
  noreply alias, which is correct for a public repo.

### Credentials

- `Chang3d!` is the documented Splunk dev-container default, allowlisted
  in `.gitleaks.toml` line 33. No other hardcoded passwords found in
  `bin/`, `appserver/static/`, `tests/`, `scripts/`.

### Network references

- All RFC1918 IPs (`10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`) trace
  to demo seed data (`demo/demo.sh`), example API payloads
  (`docs/api/README.md`, `docs/api/openapi.yaml`), or sample whitelist
  CSVs (`lookups/DR*.csv`). No real internal infrastructure
  referenced.
- Hostnames like `dmz.local`, `prod.internal` appear in sample CSVs
  only — clearly synthetic.

### Code hygiene

- Zero `TODO|FIXME|XXX|HACK` markers in production code under `bin/`
  and `appserver/static/`. (CLAUDE.md global instruction "Default to
  writing no comments" is respected throughout.)
- Only `console.log` mention in production XML is `default/data/ui/views/test_runner.xml`
  — a hidden QUnit test-runner dashboard explicitly marked "Not
  visible in UI." Acceptable.

### Required files

- `LICENSE` — Apache 2.0 boilerplate from apache.org, with "How to
  apply" appendix carrying `Copyright 2026 Oleh Bezsonov` (matches D5).
- `NOTICE` — present, Apache 2.0 conventions, Splunk trademark
  disclaimer, third-party content statement.
- `README.md` — present, screenshots embedded, badges, docs callout
  (post-2.10).
- `CONTRIBUTING.md` — present, response-SLA section (post-2.4),
  security-CI section, full PR/issue workflow.
- `CODE_OF_CONDUCT.md` — present (Contributor Covenant per locked
  decision 2.5).
- `SECURITY.md` — present, "Coordinated Disclosure Timeline" section
  per locked decision D16.
- `CHANGELOG.md` — present, Keep-a-Changelog format, status header
  records security-hardening-track closure.
- `docs/screenshots/` — 4 PNG screenshots referenced from
  `README.md` and `docs/Whitelist_Manager_Documentation.md`; all
  present.

### CI workflows

- All 11 workflows (`appinspect`, `appinspect-api`, `ci`, `codeql`,
  `docs`, `e2e-full`, `e2e-smoke`, `integration-tests`, `pip-audit`,
  `release`, `scorecard`, `secret-scan`, `semgrep`,
  `validate-and-package`, `a11y-audit`) reviewed for sensitive
  hardcoded values. CodeQL, Scorecard, and Docs all carry the
  `github.event.repository.private == false` guard for the deploy
  steps — they will activate at Phase 3.4 flip.

### `.planning/` directory

The `.planning/` directory (40+ tracked files) is intentionally
public-facing per the project convention. Reviewed: contains
roadmaps, requirements, project-state, AppInspect run records, and
phase-by-phase planning artifacts. No PII or sensitive content
beyond the intentional D15 publisher email.

---

## Open questions for user — ALL RESOLVED (2026-05-18)

All three items have been decided. Phase 3.1 is closed.

1. **F-C1 history retention** → user picked option (b) "rewrite via
   `git filter-repo` before Phase 3.4". Executed; force-pushed to
   `origin/main` 2026-05-18.
2. **F-L2 `docs/superpowers/` disposition** → user picked "move to
   `.planning/superpowers/`". Executed.
3. **F-L3 `.mcp.json.example` Windows-path genericization** → user
   picked "defer to v1.1". Tracked in `PUBLIC_RELEASE_PLAN.md` §10.

---

## Revision log

| Date | Auditor | Notes |
|------|---------|-------|
| 2026-05-18 | claude-opus-4-7 (Phase 3.1) | Initial audit. 1 CRITICAL + 1 HIGH fixed in-turn; 1 LOW fixed in-turn; 2 LOW + 1 git-history question surfaced for user decision. |
| 2026-05-18 | claude-opus-4-7 + user | Follow-up: F-C1 history rewritten + force-pushed per user authorization; F-L2 superpowers moved to .planning/; F-L3 deferred to v1.1. |
| 2026-05-18 | claude-opus-4-7 + user | Post-audit catch — F-C2 (`lookups/` test-artifact pollution) raised by user during public-flip readiness review. 29 tracked test CSVs + 18 `_trash/` items removed; `rule_csv_map.csv` trimmed 33→19 rows; `.gitignore` extended. Lesson recorded: future pre-public sweeps must explicitly ask "does every file in each .spl-payload directory belong in the product." |
