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

### CRITICAL — fixed in-turn

**F-C1: `.firecrawl/point72-*.md` (3 files) — personal job-search research tracked in repo.**

Files:

- `.firecrawl/point72-about.md` (404-page scrape, 121 B)
- `.firecrawl/point72-home.md` (Point72 home-page scrape, 6.2 KB)
- `.firecrawl/point72-splunk-security-engineer.md` (Point72 job posting, 5.2 KB)

These are page-scrape artifacts from a research session unrelated to
wl_manager (likely employer-research). On Phase 3.4 public flip they
would be visible to anyone with the repo URL. Phase 0.10 secret-scan
did not flag them because they contain no credentials, but the
outsider-perspective lens immediately surfaces them.

**Resolution:** removed in commit landing this audit. Also added
`.firecrawl/` to `.gitignore` so the directory cannot be re-tracked
by accident.

**Residual risk:** files remain in `git log`/blame history. If the
user wants them removed from history entirely before the public flip,
that requires either:
(a) a `git filter-repo` history rewrite — invalidates any existing
clones / forks. Acceptable here because the repo is still private and
has no external collaborators.
(b) accept the history retains them — they are findable by anyone who
clones and runs `git log -p`. For 3 page-scrape files of public
content, the practical privacy cost is low (the content was already
public on point72.com; the only signal is "the maintainer once
researched this employer").

**Decision needed from user before Phase 3.4** — see
"Open Questions" below.

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

### LOW — flagged for user decision (not auto-fixed)

**F-L2: `docs/superpowers/` — internal planning docs visible to outsiders.**

Two markdown files under `docs/superpowers/{plans,specs}/` document
the Wave-3 entry-point-rewrite plan written for an "agentic worker"
audience, with references to internal tooling (`superpowers:subagent-driven-development`,
`superpowers:executing-plans`) and per-step checkboxes for an
implementing agent. The content is not embarrassing, but the *framing*
(internal-tooling jargon, agentic-worker reader assumption) is
confusing for a human contributor reading the repo for the first time.

`mkdocs.yml` already excludes `superpowers/plans/*.md` and
`superpowers/specs/*.md` from the MkDocs site nav, so they don't
appear on the hosted docs. But they remain visible via GitHub's
file-tree browse after the public flip.

**Options:**

a. **Leave as-is** — transparency about development methodology;
   contributors who care can read them.
b. **Move to `.planning/superpowers/`** — colocates with other
   internal-planning artifacts that are still tracked but
   contextualized as planning history.
c. **Remove entirely** — they served their purpose; the Wave-3
   refactor is shipped and documented in CHANGELOG.

Recommendation: (b) — preserves the planning history (which is
genuinely valuable as an example of how the codebase was modularized)
while making clear that it's internal-process material, not
end-user documentation.

**Needs user decision before Phase 3.4.**

**F-L3: `.mcp.json.example` contains Windows-specific paths.**

The committed example points at `C:\Users\PC\AppData\Local\Microsoft\WindowsApps\python.exe`
and `C:/Users/PC/wl_manager` as MCP server paths. A Mac or Linux
contributor copying this to `.mcp.json` will need to substitute
those manually.

**Options:**

a. **Leave as-is** — comments explain the substitution; not
   load-bearing for public release.
b. **Genericize to `<path-to-python>` / `<path-to-repo>` placeholders**
   — slightly cleaner onboarding, more contributor-friendly.

Recommendation: (b), but **NOT** blocking Phase 3.4 — the comments
in the file already explain that contributors must substitute their
own paths. Park as a v1.1 polish item.

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

## Open questions for user

These three items need a decision before Phase 3.4 (`repo private →
public`) can fire. None block the **Phase 3.2** release-tag cut
itself — they can be addressed during the Phase 3.3 verification or
right before 3.4.

1. **`.firecrawl/point72-*.md` git history retention** (from F-C1).
   The files are removed from the working tree and gitignored, but
   they still exist in `git log -p` history. Three options:
   - **(a)** Accept — repo is still private, no external clones exist
     yet, the page content was already public on point72.com so the
     practical privacy cost is low. Phase 3.4 ships with the history
     intact.
   - **(b)** History rewrite via `git filter-repo` before Phase 3.4
     — produces a clean history but invalidates any existing
     clones/forks (currently zero, so cost is trivial).
   - **(c)** Same as (b) but coordinated with a force-push to GitHub
     after Phase 3.4 — more risky, redundant.
   Recommendation: **(a)** unless the user has a specific reason to
   sanitize the history (e.g., the page scrapes contain anything
   they'd rather not be tied to publicly).

2. **`docs/superpowers/` disposition** (from F-L2). Leave, move to
   `.planning/`, or remove?

3. **`.mcp.json.example` Windows path genericization** (from F-L3).
   Fix now or defer to v1.1?

---

## Revision log

| Date | Auditor | Notes |
|------|---------|-------|
| 2026-05-18 | claude-opus-4-7 (Phase 3.1) | Initial audit. 1 CRITICAL + 1 HIGH fixed in-turn; 1 LOW fixed in-turn; 2 LOW + 1 git-history question surfaced for user decision. |
