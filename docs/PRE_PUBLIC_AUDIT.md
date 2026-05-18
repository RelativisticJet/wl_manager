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

## Audit V2 — comprehensive walk (in progress, started 2026-05-18)

### Why V2

After the Audit V1 work above closed (`F-C1`/`F-H1`/`F-L1`/`F-L2`/`F-L3`),
user pointed out `lookups/` contained obvious test-fixture pollution
that V1 had missed. Targeted cleanup landed as `F-C2`. Subsequent QA
also caught that the `F-C2` commit message overclaimed test-impact
("every test creates the CSV at runtime") without tracing through
`tests/integration/test_chaos_save_csv_chain.py`, which broke CI.

The pattern: V1 applied audit lenses opportunistically rather than
exhaustively. Each new finding was a fresh lens that V1 hadn't
explicitly enumerated up front. V2 fixes this methodology problem.

### V2 methodology

**Ten lenses applied to EVERY tracked file**:

| # | Lens | Question |
|---|------|----------|
| L1 | Customer-visible (.spl payload) | Does this ship onto customer Splunk installs? If so, is it product-appropriate? |
| L2 | PII / personal | Real names, emails, internal handles, scraped content from unrelated sessions? |
| L3 | Credentials / secrets | API keys, tokens, dev passwords beyond documented `Chang3d!`? |
| L4 | Internal infrastructure | Real IPs/hostnames/Splunk indexes/Slack/Jira refs? |
| L5 | Out-of-date / stale | Content match current code? Old version strings, dead links? |
| L6 | Orphaned / dead | File actually used? Test fixtures with no test, scripts referenced nowhere? |
| L7 | Maintainer-specific | Hardcoded `C:\Users\PC\`, machine-specific assumptions? |
| L8 | Unprofessional / embarrassing | Profanity, dev frustration, `XXX:`, internal jokes, draft markers? |
| L9 | Branding / consistency | License, version, copyright, project name align with locked decisions? |
| L10 | Legal / IP | Third-party content embedded without attribution? Someone else's IP? |

**Three buckets**:

The packaging script `scripts/package.sh` excludes a substantial set
of paths from the `.spl` archive that ships to customers. So
"in the GitHub repo" ≠ "on customer's Splunk." Audit must ask both
questions.

- **Bucket A — ships in `.spl` (customer-visible)**:
  - `app.manifest`
  - `appserver/static/` (JS, CSS, XML)
  - `bin/` (Python source)
  - `default/` (Splunk configs, dashboards)
  - `lookups/rule_csv_map.csv` (swapped to header-only at package time)
  - `metadata/default.meta`
  - Root `.md` files: `ARCHITECTURE.md`, `CHANGELOG.md`,
    `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `INSTALLATION.md`,
    `LICENSE`, `NOTICE`, `README.md`, `SECURITY.md`
  - `mkdocs.yml` ← currently not excluded; may or may not be
    intentional (audit-level question — see Phase A)
  - Strict on ALL ten lenses.

- **Bucket B — GitHub-visible but NOT in `.spl`**:
  - All dot-dirs (`*/.*` exclude in package.sh): `.github/`,
    `.planning/`, `.claude/`, `.zap/`, `.appinspect_api.expect.yaml`,
    `.gitignore`, `.gitleaks.toml`, `.mcp.json.example`
  - `bench_results/`, `dist/`, `demo/`, `docs/`, `scripts/`, `tests/`
  - `docker-compose.yml`, `Makefile`, `package.json`,
    `package-lock.json`, `requirements-dev.txt`, `sbom.cdx.json`
  - `lookups/DR*.csv`, `lookups/_*` (all the seed/test CSVs)
  - Lenient on L1, strict on L2-L10.

- **Bucket C — should be gitignored entirely**: runtime state, build
  output, transient state never appropriate for tracking.

**Per-directory walk**:

V2 walks every directory and applies every lens to every file.
Findings recorded below as they're produced. Severity ranks
CRITICAL / HIGH / MEDIUM / LOW. Fixes batched at the end after
user authorization.

### V2 finding registry

#### F-C3 (HIGH, CI-blocker — surfaced during V2 prep, before walk)

**`tests/integration/test_chaos_save_csv_chain.py` requires `DR_VERSION_TEST.csv` to exist on the container; F-C2 deleted it.**

The chaos test exercises save-csv-chain consistency by killing
splunkd mid-write. It needs a stable pre-test snapshot of an
existing CSV to measure post-recovery state against. Lines 299-302
have a hard assertion:

```python
pre_state = _capture_state()
assert pre_state["csv_hash"] is not None, (
    "chaos target CSV missing pre-test — DR_VERSION_TEST.csv "
    "must exist for this test to run")
```

`DR_VERSION_TEST.csv` was a tracked test fixture deleted in
F-C2 (commit `b30c433`) on the rationale that no test depended
on its tracked presence. That rationale held for
`tests/test_e2e_api.py` (creates CSV via API at runtime) but
NOT for this chaos test (assumes pre-existence).

CI integration tests run via `.github/workflows/integration-tests.yml`
→ `python -m pytest tests/integration/ -q --tb=short` → this
test is collected. Next run (after June 1 Actions reset) will fail.

**Sibling fallout** — `tests/test_e2e_advanced.py` (manual smoke,
not in CI) has the same pattern at line 99 with `DR_BROWSER_TEST.csv`,
also deleted in F-C2. Lower operational severity (not in CI) but
same structural issue.

**Fix approach (deferred to V2 batch fix)**:

1. **Chaos test**: session-scoped fixture in `tests/integration/conftest.py`
   that creates `DR_VERSION_TEST.csv` via REST API once before any
   test in the integration suite runs. Schema per the test docstring:
   `user, src_ip, Comment`. Cleans up at session end.
2. **Manual smoke**: add a `_seed_required_csvs()` function called
   at the top of `main()` in `tests/test_e2e_advanced.py` that
   creates the CSVs the tests assume to exist. Uses existing
   `post()` helper and the `create_rule`/`create_csv` REST actions.

**Why not fix in-turn**: per user direction 2026-05-18, V2 audit
runs to completion FIRST, then batch-fix at the end. Avoids touching
code mid-audit since other findings may interact (e.g., if V2 finds
that a related test should itself be deleted, the chaos-test fix
might be a fixture restructure rather than a seed-and-add).

### Per-directory walk (in progress)

#### Phase A — root files (21 tracked files, completed 2026-05-18)

**Files audited** (all 21 tracked at repo root):

Dotfiles: `.appinspect_api.expect.yaml`, `.gitignore`, `.gitleaks.toml`,
`.mcp.json.example`.
Configs: `Makefile`, `app.manifest`, `docker-compose.yml`, `mkdocs.yml`,
`package.json`, `package-lock.json`, `requirements-dev.txt`,
`sbom.cdx.json`.
Docs (also in Bucket A — ship in .spl): `ARCHITECTURE.md`,
`CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`,
`INSTALLATION.md`, `LICENSE`, `NOTICE`, `README.md`, `SECURITY.md`.

**PASS (16 files, no finding)**:

- `.appinspect_api.expect.yaml` — single suppression entry with full
  re-eval triggers, dated, current. Bucket B.
- `.gitignore` — every entry justified by inline comment. Bucket B.
- `.gitleaks.toml` — minimal allowlist (Chang3d! dev password +
  audit.xml dashboard variables only). Bucket B.
- `.mcp.json.example` — F-L3 already known (Windows-only paths,
  deferred to v1.1).
- `Makefile` — relative paths, documented Splunk dev password.
  Bucket B.
- `docker-compose.yml` — relative volume mounts, documented dev
  password env-var. Bucket B.
- `package.json`, `package-lock.json`, `requirements-dev.txt` — dev
  dependency declarations. Bucket B.
- `ARCHITECTURE.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`,
  `CONTRIBUTING.md`, `INSTALLATION.md`, `LICENSE`, `NOTICE`,
  `README.md`, `SECURITY.md` — clean. No maintainer paths
  (`grep C:\\Users\|/Users/PC` returns 0 across all 9 files).
  Bucket A (ship in .spl).

**Findings (5 new)**:

##### F-H2 (HIGH — release-blocker for Phase 3.8): git tag namespace collision

`git tag -l` returns:

```
hardening-v1-complete
pre-firecrawl-purge-backup-2026-05-18
v1.0.0
v2.0.0
```

`v1.0.0` points at commit `d525bf5` (2026-02-18) — historical
internal milestone "Fix JS REST URL to use splunkd proxy path".
`v2.0.0` points at commit `732de19` (2026-03-22) — historical
internal milestone "docs: add screenshots, community files".
Both are **lightweight tags** (`git tag -v` errors "cannot
verify a non-tag object of type commit") — not annotated,
not signed.

D12 (`docs/PUBLIC_RELEASE_PLAN.md` §1) locks: "Versioning: reset
to v1.0.0 for first public release." Phase 3.8 (§6 row 3.8)
plans to `Cut v1.0.0 (GA) release`. Phase 3.2 also references
`v1.0.0-rc1` which does NOT collide. But Phase 3.8 will fail
because `v1.0.0` already exists locally AND on origin (these
tags were pushed historically).

**Fix approach (deferred to V2 batch fix)**:
- `git tag -d v1.0.0 && git push origin :refs/tags/v1.0.0`
- `git tag -d v2.0.0 && git push origin :refs/tags/v2.0.0`
- Both can be deleted because they're lightweight and have no
  associated GitHub Release (the GitHub Release for v2.0.0 visible
  in the user's screenshot — verify separately whether deletable).
- Rename the existing GitHub Release if it must be preserved
  (e.g., `v2.0.0-internal-2026-03-22`).

##### F-M1 (MEDIUM): mkdocs.yml ships in .spl payload unnecessarily

`scripts/package.sh` exclude list omits `mkdocs.yml`. The docs-site
build config gets installed onto every customer Splunk instance. Not
security-sensitive but unnecessary bloat that may confuse customers
("why is there a Material-theme mkdocs config in my app dir?").

**Fix approach**: add `--exclude="$APP_NAME/mkdocs.yml"` to the
package.sh tar command.

##### F-M2 (MEDIUM): sbom.cdx.json is stale

```
sbom.cdx.json:
  metadata.component.version: "2.0.0"  ← stale; current is "1.0.0-rc1"
  splunk:build property: "627"          ← stale; current is "660"
  metadata.timestamp: "2026-04-29T00:00:00Z"  ← stale
```

The SBOM tool field is `"name": "manual-baseline"` so it's
hand-maintained. The values were correct at Round 7 baseline
(2026-04-29) but the app has moved on since.

**Fix approach**: regenerate the SBOM before Phase 3.2 cut. Either
manually with current version+build, or wire a CI step that
regenerates on every release-tagged commit.

##### F-M3 (MEDIUM): app.manifest author identity inconsistency

```
app.manifest:        "author": [{"name": "RelativisticJet", ...}]
LICENSE line 189:    Copyright 2026 Oleh Bezsonov
NOTICE line 2:       Copyright 2026 Oleh Bezsonov
sbom.cdx.json:       "publisher": "Oleh Bezsonov"
```

Per D5 + D15 + D17 (locked decisions in `docs/DECISION_LOG.md`):
copyright + Splunkbase publisher + repo-owner identity all unified
on "Oleh Bezsonov". CHANGELOG explicitly schedules the
`app.manifest:author.name` update for "Phase 0.7":

> CHANGELOG.md:151-153
>   `app.manifest:license.name = "MIT"` and `author.name = "RelativisticJet"`
>   — scheduled for Phase 0.6 (Apache 2.0 switch) and Phase 0.7
>   (D5/D15 copyright/publisher = Oleh Bezsonov).

Phase 0.6 happened (license fixed, eventually re-fixed in F-H1).
Phase 0.7 apparently never closed — `app.manifest:author.name`
is still "RelativisticJet."

**Fix approach**: change to `"name": "Oleh Bezsonov"` and add
`"email": "communicate.oleh@gmail.com"` (per D15 — the publisher
email is intentionally public per the locked decision).

##### F-M4 (LOW): app.manifest releaseDate predates actual release

`"releaseDate": "2026-05-17"` was set during Phase 1 planning. Phase
3.2 hasn't cut `v1.0.0-rc1` yet. The date should be updated to the
actual rc1 cut date when Phase 3.2 fires.

**Fix approach**: update at Phase 3.2 time, not now. Tracked as a
release-cut-prep item.

---

**Phase A summary**: 16 pass, 5 findings (1 HIGH, 3 MEDIUM, 1 LOW).
No CRITICAL findings. The HIGH (F-H2) blocks Phase 3.8 but not
Phase 3.2 or 3.4. The MEDIUM findings should land before Phase 3.2
to keep the rc1 cut clean. The LOW (F-M4) is a release-time task.

#### Phase B — `.github/` (23 tracked files, completed 2026-05-18)

**Files audited**:

- `.github/FUNDING.yml`
- `.github/ISSUE_TEMPLATE/bug_report.md`, `config.yml`,
  `feature_request.md`, `question.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/dependabot.yml`
- 16 workflows in `.github/workflows/`: `a11y-audit.yml`,
  `appinspect-api.yml`, `appinspect.yml`, `ci.yml`, `codeql.yml`,
  `docs.yml`, `e2e-full.yml`, `e2e-smoke.yml`, `integration-tests.yml`,
  `pip-audit.yml`, `release.yml`, `scorecard.yml`, `secret-scan.yml`,
  `semgrep.yml`, `validate-and-package.yml`, `zap-baseline.yml`.

**Verified clean across all 10 lenses**:

- **L3 (credentials)**: only 3 distinct secrets referenced:
  `SPLUNK_DEV_USERNAME` + `SPLUNK_DEV_PASSWORD` (in `appinspect-api.yml`,
  both job-scoped, both registered per Phase 1.4) and the built-in
  `GITHUB_TOKEN` (in `release.yml` for `gh release upload` and
  `secret-scan.yml` for gitleaks). No secret VALUES embedded. No
  third-party tokens (Slack, Datadog, etc.). All secret names are
  generic enough to not fingerprint internal infrastructure.
- **L4 (internal refs)**: only `main` branch referenced. No
  fingerprint of internal branch conventions (`dev/`, `feature/`,
  `release/`). No internal hostnames or Splunk index names beyond
  what's documented in code.
- **L7 (maintainer paths)**: zero `C:\Users\PC\` or `/Users/PC/`
  matches across all 23 files.
- **L5 (stale content)**: action versions all pinned to major
  versions (no `@main` / `@master`). `splunk/appinspect-api-action@v3.0.5`,
  `ossf/scorecard-action@v2.4.0`, `sigstore/cosign-installer@v3`,
  `zaproxy/action-baseline@v0.14.0` — all current as of 2026-05.
- **L6 (orphans)**: every workflow has documented trigger rationale
  in comments; `codeql.yml`, `scorecard.yml`, `docs.yml` correctly
  carry `if: github.event.repository.private == false` job-level
  guards until Phase 3.4 flips public.
- **L8 (TODO/FIXME/XXX/HACK)**: zero hits across all workflows.
- **L9 (consistency)**: trigger discipline aligns with
  PUBLIC_RELEASE_PLAN expectations — heavy workflows (e2e-full,
  a11y-audit, zap-baseline) are schedule-only + workflow_dispatch,
  PR-gating workflows (e2e-smoke, ci, integration-tests, semgrep,
  appinspect, validate-and-package, docs, secret-scan) trigger on
  push:main + pull_request.
- **release.yml specifically** — comment block at line 52-58
  publishes the customer-facing `cosign verify-blob` command with
  correct `--certificate-identity-regexp` for the
  `RelativisticJet/wl_manager` workflow identity and correct
  `--certificate-oidc-issuer https://token.actions.githubusercontent.com`.
  Sigstore E2E (Phase 3.2) will exercise this exact command.

**Findings: 0 (zero) in Phase B.**

The closest thing to a finding is a minor "future hardening"
observation, not a release-blocker:

> Action pins use major-version-only (`@v4`, `@v5`, `@v2`) rather
> than full 40-char SHA pins. OSSF Scorecard's "Pinned Dependencies"
> check will flag this once we flip public and Scorecard activates
> in `scorecard.yml`. SHA-pinning is more supply-chain-secure but
> adds maintenance friction (Dependabot has to bump SHAs instead of
> tags). Recommend leaving as-is for v1.0.0 and revisiting if
> Scorecard scores drop the project below a target threshold.

**Phase B summary**: 23 pass, 0 findings.

#### Phase C — Bucket A directories (ship in `.spl`, completed 2026-05-18)

**Scope walked:** `appserver/static/` (12 top-level files + `modules/` 13 files + `tests/` 5 files), `bin/` (24 Python modules), `default/` (12 `.conf` files + 4 dashboard XMLs + nav XML + viewstates), `lookups/` (19 demo `DR*.csv` + `rule_csv_map.csv` + `_versions/` excluded from `.spl`), `metadata/default.meta`. 78 files inspected directly + bulk grep across 13,317 LOC of JS / ~24 KLOC of Python.

**Mechanical checks run across the bucket:**

- `Oleh|Bezsonov|wildleo|RelativisticJet|c:\\Users|/Users/PC|/home/[a-z]+|point72|@gmail` against `appserver/`, `bin/`, `default/` — only legitimate `author = Oleh Bezsonov` in `default/app.conf:11` (intentional per D5/D17).
- `TODO|FIXME|XXX|HACK` against `bin/*.py` and `appserver/static/**/*.js` — zero matches.
- RFC1918-vs-public IP regex against `appserver/` — zero matches (no embedded customer infra).
- `partnercorp\.com|Carlos Rodriguez|David Kim|Jose Martinez` against `default/data/ui/views/audit.xml` (the largest dashboard, 1098 LOC) — zero matches.
- All embedded URLs in dashboards / JS confined to `code.jquery.com` (CDN) and Splunk-internal paths.

**Per-area PASS notes:**

- `bin/` (24 Python modules covering handler / approval / audit / FIM / RBAC / replay / trash / versions / HMAC / limits / migration / etc.): no maintainer paths, no debug `print()` left behind, no `TODO`. `wl_hmac_key.py` derives the runtime key from the Splunk server GUID (per D-2026-04-12 decision-log entry) — no static keys.
- `default/*.conf`: every `cron_schedule` above the AppInspect 12/hr threshold carries an inline "AppInspect note (check_for_gratuitous_cron_scheduling)" justification keyed to the attack window it defends (see `savedsearches.conf:87-94, 168-178, 213-222, 244-253`). Documented openly so a hostile reviewer sees the reasoning.
- `default/data/ui/views/{whitelist_manager,control_panel,audit}.xml`: minimal SimpleXML wrappers around JS-rendered UI; no embedded customer data; no `<form>`-leaked default tokens.
- `appserver/static/{whitelist_manager,control_panel,audit_trail,audit_tz,notifications,application}.js` + 13 `modules/wl_*.js`: clean.
- `metadata/default.meta`: ACLs match the four-tier RBAC scheme (`wl_superadmin` / `wl_admin` / `wl_analyst_editor` / `wl_analyst_viewer`); saved searches locked to `admin`/`sc_admin`. No exported objects beyond what the dashboards need.
- `lookups/rule_csv_map.csv`: 19 production-rule rows (post-F-C2 cleanup, see `lookups/rule_csv_map.csv:1-20`). `scripts/package.sh:103` swaps to a header-only file before `tar`, so customers receive an empty mapping — confirmed in the existing F-C2 closure.

**New Phase C findings:**

##### F-L4 (LOW): `test_runner.xml` QUnit dashboards ship in `.spl` payload

Two test-runner dashboards exist and BOTH ship to customers:

1. **`default/data/ui/views/test_runner.xml` (112 LOC)** — registers as a Splunk view at `https://<host>:8000/app/wl_manager/test_runner` (see `default/data/ui/views/test_runner.xml:2` `<form hideSplunkBar="true" hideTitle="true">`). It is NOT in `default/data/ui/nav/default.xml` (the nav menu only exposes Whitelist Manager / Audit Trail / Control Panel), but the URL is still reachable by anyone who guesses or scrapes it. The dashboard:
   - Loads QUnit from external CDN: `https://code.jquery.com/qunit/qunit-2.19.4.{css,js}` (lines 18, 36)
   - Tries to load nine test files via relative paths under `../../app/wl_manager/tests/qunit/...` (lines 54-57) and `../../app/wl_manager/appserver/static/tests/...` (lines 58-62)
   - The first four resolve into `tests/qunit/` which is **excluded by `scripts/package.sh`** (the `tests/` directory is repo-only, never ships). So in a customer install they 404 silently. The last five resolve into `appserver/static/tests/` which DOES ship (see F-L5 below).
   - Net effect: a customer who navigates to `/app/wl_manager/test_runner` sees a half-broken QUnit page calling an external CDN — unprofessional for a security app.
2. **`appserver/static/test_runner.xml` (70 LOC)** — orphan duplicate, NOT registered as a view (Splunk only registers XMLs under `default/data/ui/views/`). Lives in the static-asset tree so the file is web-served at `/static/app/wl_manager/test_runner.xml`. References a non-existent `wl_state.js` module (file deleted during Wave-3 extraction per `MEMORY.md` notes) and the same broken `tests/qunit/` paths.

**Risk lens:** L5 (stale — both files predate Wave-3 module extraction) + L8 (unprofessional — broken paths in production) + L1 (customer-visible, even if URL-only).

**Recommended fix (batch with Phase G):** add `default/data/ui/views/test_runner.xml` and `appserver/static/test_runner.xml` to the `EXCLUDES` block in `scripts/package.sh:140-160`. Both files can stay in the repo for developer use, but they should not ship. Verify post-fix by extracting the `.spl` and confirming neither path is present.

##### F-L5 (LOW): `appserver/static/tests/` QUnit test files ship in `.spl` payload

Five QUnit test files (`test_wl_cp_admin_limits.js`, `test_wl_cp_limits.js`, `test_wl_cp_queue.js`, `test_wl_cp_trash.js`, `test_wl_cp_usage.js`) live under `appserver/static/tests/` and are NOT excluded by `scripts/package.sh` (the package script excludes top-level `tests/`, not `appserver/static/tests/`).

They are not registered as views and are reachable only via direct URL (`/static/app/wl_manager/tests/test_wl_cp_*.js`), so the exposure surface is low. But:

- They contain `QUnit.module(...)` test-setup code that exposes the internal shape of the Control Panel tabs (mock DOM templates, expected response shapes, edge-case names) — useful intel for an attacker mapping out the surface.
- Adds ~test-only bytes to every customer install for zero customer value.

**Risk lens:** L5 (test debris) + L8 (unprofessional). Mirror finding to F-L4.

**Recommended fix:** add `appserver/static/tests/` to the `EXCLUDES` block in `scripts/package.sh`. Optionally move the files to `tests/qunit/cp/` so they're co-located with the rest of the QUnit suite (already repo-only).

##### F-L6 (LOW): Demo CSVs in `lookups/` carry realistic-looking PII-shaped narratives

The `lookups/DR*.csv` files (19 demo whitelists, GitHub-public but excluded from `.spl` per `scripts/package.sh:145`) contain demo rows with:

- Name-shaped strings with backstories. Spot-checked rows:
  - `lookups/DR310_impossible_travel.csv:2` — `c.rodriguez,US,Carlos Rodriguez - commutes between NYC and Miami offices weekly,2026-12-31`
  - `lookups/DR310_impossible_travel.csv:3` — `d.kim,KRTES,David Kim - based in Seoul but uses US VPN for corp access,2026-06-30`
  - `lookups/DR71_data_exfil_users.csv:4` — `j.martinez,Jose Martinez - video editor uploads raw footage to cloud storage daily`
  - `lookups/DR520_anomalous_logon_time.csv:4` — `n.williams,22-06,Night shift NOC analyst - works 10pm to 6am`
- One real-world domain: `lookups/DR630_email_exfiltration.csv:2` — `l.thompson,partnercorp.com,50,Legal team sharing contracts with external counsel,`. `partnercorp.com` resolves to a real registered domain (Partner Corp — a real entity per public WHOIS). Other demo domains (`vendor-xyz.co.jp`, `boardmembers.org`) are RFC-2606-safe-ish patterns but `partnercorp.com` is not in the reserved-example space.

**Risk lens:** L2 (PII-shape — though the names are common enough to plausibly be synthetic, a casual GitHub viewer cannot tell at a glance) + L9 (branding / professional appearance — real domain in a demo dataset implies sloppy curation).

**Recommended fix:** in a batch with Phase G, rewrite person-narratives to use **reserved example names** (`alice`, `bob`, `carol`, `dave`, `eve`) and replace `partnercorp.com` with `example.com` / `example.net` / `example.org` (RFC 2606 reserved). The narrative strings stay (they're useful demo context), only the identifiers change.

##### F-L7 (LOW): Demo CSVs contain obvious E2E-run debris

Same files as F-L6, but separate finding because the fix is a content-curation pass rather than a name-replacement:

- `lookups/DR102_whitelist.csv:2` — `E2E-EDITED-HOST,analyst2,1774751458` (E2E test artifact left behind after a verification run)
- `lookups/DR88_whitelist.csv:2` — `EDITED_AFTER_LAZY_INIT,SRV-FILE01,Approved file share access` (clearly a test marker)
- `lookups/DR88_whitelist.csv:3` — `SECOND_EDIT,Station_2,Test comment for DR88`
- `lookups/DR20_whitelist.csv:3` — `TEST_2,,` and `TEST_3,,` (sparse test rows)

These rows tell a casual viewer "this is dev debris, not a curated demo set." They are not customer-shipped (excluded from `.spl`), so the audit lens is L8 (unprofessional / dev-debris on GitHub-public) + L5 (stale — accumulated from prior E2E runs that didn't clean up).

**Recommended fix:** curate each `lookups/DR*.csv` down to ~5 realistic synthetic rows. Pair with F-L6 (rename to `alice`/`bob`/`carol`) and F-C2 lessons (the `lookups/` dir already had 29 unrelated test CSVs pulled — these are the surviving residue).

##### Bucket A summary

- **F-L4, F-L5** — block on `.spl` payload hygiene; fix in Phase G batch.
- **F-L6, F-L7** — GitHub-public hygiene only (customers never see these CSVs); fix in same batch.
- No CRITICAL / HIGH / MEDIUM findings in this bucket. Bucket A is in better shape than Buckets B or C will likely be — handler / dashboard / module code is professional and well-defended.

#### Phase D — Bucket B directories (repo-only, completed 2026-05-18)

**Scope walked:** `tests/` (199 tracked files across 11 subdirs), `scripts/` (18 files), `demo/` (3 files), `docs/` (29 tracked files), `bench_results/` (3 JSON files). ~252 files total. Audit lens is **public-on-GitHub** only — Bucket B does not ship in the `.spl`, so customer install never sees these.

**Mechanical sweeps:**

- `point72|wildleo|@gmail|@yahoo|@hotmail|@outlook|@protonmail|@icloud` — every match resolved to legitimate intentional content:
  - `communicate.oleh@gmail.com` in `docs/DECISION_LOG.md:48`, `docs/PUBLIC_RELEASE_PLAN.md` (5 lines), `docs/RUNBOOKS.md:436/451/475/521` → D15 / D17 publisher email, intentionally public per locked decisions.
  - `wildleo91` (handle, no `@gmail`) in `docs/PUBLIC_RELEASE_PLAN.md:44/215` → D17 historical-attribution context ("commits remain attributed to wildleo91; no history rewrite").
  - Email mentions in `docs/PRE_PUBLIC_AUDIT.md` are this audit doc's own findings registry (meta-reference, not a leak).
  - `tests/a11y/reports/*.json` show `DevLicense:communicate.oleh@gmail.com` in 12 places — these are the gitignored raw a11y reports (`.gitignore:163-164`); the file is NOT tracked. `git ls-files tests/a11y/` confirms only `README.md`, `baseline.json`, `lib_a11y.cjs`, `test_a11y_dashboards.cjs` are tracked, and `grep` shows zero email matches in those four.
- Hardcoded-credential sweep (`password|secret|api_key|bearer|token` with 8+ char value) across all 252 files — only the documented `Chang3d!` dev-container password appears (in `demo/demo.sh`, `demo/generate_demo_guide.py`, `docs/PUBLIC_RELEASE_PLAN.md`, `docs/RING_FINDINGS.md`, `docs/PRE_PUBLIC_AUDIT.md`). Allowlisted in `.gitleaks.toml`. No other secrets.
- RFC1918 IP regex — every match is intentional demo seed data (`demo/demo.sh:254-256`, `scripts/seed-demo-state.py:130`, `scripts/test_upgrade_path.sh:110/112`, `docs/api/README.md`, `docs/api/openapi.yaml`).
- `TODO|FIXME|XXX|HACK` — only false positives (UUID placeholder `XXXXXXXX-XXXX-XXXX` in `tests/integration/test_backward_compat_approval.py:166`, `'XXXX'` substring sentinel in `tests/unit/test_validation.py:407/424` and `docs/RING_FINDINGS.md:2090`).
- `bench_results/` — three JSONs of 838-byte perf data each. Container name `wl_manager_test` is the documented dev container. Clean.

**New Phase D findings:**

##### F-M5 (MEDIUM): Hardcoded maintainer paths in 2 tracked test files

Seven hardcoded absolute Windows paths embedded in two tracked Python E2E tests:

- `tests/test_e2e_manual_browser.py:106` — `page.screenshot(path=f"C:/Users/PC/wl_manager/tests/e2e_{name}.png", full_page=True)`
- `tests/test_e2e_realworld.py:265` — `e2e_phase1.png`
- `tests/test_e2e_realworld.py:439` — `e2e_phase2.png`
- `tests/test_e2e_realworld.py:512` — `e2e_phase3.png`
- `tests/test_e2e_realworld.py:602` — `e2e_phase4.png`
- `tests/test_e2e_realworld.py:650` — `e2e_phase5_analyst.png`
- `tests/test_e2e_realworld.py:651` — `e2e_phase5_admin.png`

Every other contributor running these tests will fail (`FileNotFoundError` on a path that doesn't exist on their machine — Linux/macOS — or silently writes to `C:\Users\PC\` if it exists). This breaks the "any new contributor can run the test suite" contract.

**Risk lens:** L7 (maintainer-specific) + L8 (unprofessional for an OSS project).

**Recommended fix:** replace with `Path(__file__).parent / f"e2e_{name}.png"` (resolves to `tests/e2e_*.png` relative to the test file, portable across machines). Single-line edit per occurrence.

##### F-L8 (LOW): Stale E2E screenshot debris tracked at `tests/` root

Six tracked PNGs at `tests/` top level, all dated 2026-03-29 (~6 weeks before the v1.0.0-rc1 cut):

- `tests/e2e_phase1.png` (111 KB)
- `tests/e2e_phase3.png` (72 KB) — note: `e2e_phase2.png` does NOT exist on disk despite being written by `test_e2e_realworld.py:439`, indicating the run that produced these terminated before phase 2 screenshot landed
- `tests/e2e_phase4.png` (446 KB)
- `tests/e2e_phase5_admin.png` (59 KB)
- `tests/e2e_phase5_analyst.png` (57 KB)
- `tests/screenshot_debug.png` (size n/a) — name self-identifies as debug artifact

These are output artifacts of `tests/test_e2e_realworld.py` from one specific manual run on 2026-03-29. The committed-screenshots-as-reference-baseline pattern lives elsewhere (under `tests/e2e/visual_baselines/`, which is the real pixel-diff contract). The root-level PNGs are dev debris.

**Risk lens:** L5 (stale by 6+ weeks) + L8 (unprofessional dev debris) + L6 (orphaned-ish — useful only for the specific 2026-03-29 run).

**Recommended fix:** `git rm` all 6 PNGs and add patterns to `.gitignore` (`tests/e2e_phase*.png`, `tests/screenshot_debug.png`). Pairs with F-M5 — once those paths are made relative, future runs land in the same place but get ignored by git.

##### F-L9 (LOW): `scripts/hooks/README.md:80` embeds maintainer's exact path as example

```text
80: `node c:/Users/PC/wl_manager/scripts/hooks/block-synthetic-fixtures.js`.
```

The README explains how to wire the hook into Claude Code settings and recommends an absolute path because Claude Code does not currently expand `${workspaceFolder}`. The example uses the maintainer's literal layout instead of a placeholder.

**Risk lens:** L7 (maintainer-specific in public-facing README) — cosmetic.

**Recommended fix:** replace with `node <your-checkout>/scripts/hooks/block-synthetic-fixtures.js` (matches the surrounding "per-developer" framing).

##### F-L10 (LOW): Drift in Audit V1 claim about `wildleo91@gmail.com` location

`docs/PRE_PUBLIC_AUDIT.md:275` from V1 says:

> `wildleo91@gmail.com` appears only in `docs/PUBLIC_RELEASE_PLAN.md` …

But `git ls-files | xargs grep -l "wildleo91@gmail"` shows the full email is in `docs/PRE_PUBLIC_AUDIT.md` ONLY — `docs/PUBLIC_RELEASE_PLAN.md` contains `wildleo91` (handle, no `@gmail`) but never the full email. Either (a) the V1 audit cited the wrong location, or (b) the email was removed from `PUBLIC_RELEASE_PLAN.md` after V1 closed and the audit doc was not updated.

Net effect: the full email `wildleo91@gmail.com` is one grep hit, and that hit is the audit doc itself documenting (incorrectly) where the email appears. Not a real leak — but the inaccurate claim should be corrected so a future reader doesn't go hunting for the email in `PUBLIC_RELEASE_PLAN.md` and be confused when they don't find it.

**Risk lens:** L8 (audit-doc accuracy / documentation drift).

**Recommended fix:** edit `docs/PRE_PUBLIC_AUDIT.md:271-277` (the "Personal identity" subsection) to reflect the actual location of each email and where it does NOT appear. One paragraph rewrite.

##### Bucket B summary

- **F-M5 (MEDIUM)** — fix together with F-L8 in Phase G batch; both center on tests/ portability.
- **F-L8, F-L9, F-L10** — cosmetic / hygiene, all batchable.
- No CRITICAL / HIGH in Bucket B. Two ack notes worth keeping in mind for Phase G:
  - `tests/a11y/reports/` correctly stays gitignored — verify `.gitignore:163-164` is preserved in any future cleanup that touches `tests/` ignore patterns.
  - The `Chang3d!` allowlist in `.gitleaks.toml` correctly suppresses ~5 mentions across `demo/` and `docs/`; do NOT widen the allowlist without explicit decision.

#### Phase E — Internal/process dot-dirs — pending

#### Phase F — Visual review of `docs/screenshots/` — pending

---

## Revision log

| Date | Auditor | Notes |
|------|---------|-------|
| 2026-05-18 | claude-opus-4-7 (Phase 3.1) | Initial audit. 1 CRITICAL + 1 HIGH fixed in-turn; 1 LOW fixed in-turn; 2 LOW + 1 git-history question surfaced for user decision. |
| 2026-05-18 | claude-opus-4-7 + user | Follow-up: F-C1 history rewritten + force-pushed per user authorization; F-L2 superpowers moved to .planning/; F-L3 deferred to v1.1. |
| 2026-05-18 | claude-opus-4-7 + user | Post-audit catch — F-C2 (`lookups/` test-artifact pollution) raised by user during public-flip readiness review. 29 tracked test CSVs + 18 `_trash/` items removed; `rule_csv_map.csv` trimmed 33→19 rows; `.gitignore` extended. Lesson recorded: future pre-public sweeps must explicitly ask "does every file in each .spl-payload directory belong in the product." |
| 2026-05-18 | claude-opus-4-7 + user | Audit V2 Phase C closed — 78 files inspected across `appserver/`, `bin/`, `default/`, `lookups/`, `metadata/`. Four LOW findings recorded: F-L4 (test_runner.xml dashboards ship), F-L5 (`appserver/static/tests/` QUnit files ship), F-L6 (demo CSVs name-shaped narratives + one real domain `partnercorp.com`), F-L7 (demo CSV E2E debris). No CRITICAL/HIGH/MEDIUM in this bucket. All four queued for Phase G batch fix. |
