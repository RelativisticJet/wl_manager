# Splunk 10.x Compatibility Audit (v1.0.2)

**Date:** 2026-06-02
**Trigger:** AppInspect 4.2.1 SLIM validation for AppInspect request
`30b72763-6425-4ae2-807a-b05c9aaf7bde` (Splunkbase upload 8800-43285)
rejected `platformRequirements.splunk.Enterprise: "9.3"` because
9.3 is no longer on Splunk's supported-version list. Cloud Vetting
blocked until the manifest declares at least one currently-supported
version.

**Decision** (see `docs/DECISION_LOG.md` 2026-06-02 row): declare
`["9.4", "10.0"]` as supported. This requires the 7-risk-area code
audit from `CLAUDE.md` "Splunk Version Pinning Audit" against 10.x.

The audit below is a **code-reading sweep**, not a runtime
verification. The pinned dev container at `splunk/splunk:9.3.1`
remains the only environment where full E2E has been executed. A
future cycle will stand up parallel `splunk/splunk:9.4.x` and
`splunk/splunk:10.0.x` containers for runtime confirmation; until
then, customer-facing release notes must acknowledge that 9.4 / 10.0
support is "API-stability-declared, not E2E-verified" (the
intermediate option B from the manifest-pin decision was rejected
specifically to make this distinction).

## Risk-area sweep

The seven areas come from `CLAUDE.md` "Splunk Version Pinning Audit"
(checklist established 2026-04-29) — these are the surfaces that
have bitten this app at least once and are therefore the most likely
to bite again on a major-version upgrade.

### 1. `splunk.rest.BaseRestHandler`

**Status: N/A** — we do not extend `BaseRestHandler`. The handler at
`bin/wl_handler.py:49` extends
`splunk.persistconn.application.PersistentServerConnectionApplication`,
which is Splunk's recommended class for REST endpoints since 7.x and
remains the documented endpoint base in 9.x + 10.x. The CLAUDE.md
note about `BaseRestHandler` predates the persistconn switch and is
retained in the checklist because the project's earliest prototype
used it.

### 2. `mvc.Components` two-instance-per-token quirk

**Status: Used; theoretical-only risk vs 10.x.**
Three JS files call `mvc.Components.getInstances()` or
`mvc.Components.get(...)`:

- `appserver/static/audit_trail.js:51` — `getInstances()` for the
  detail panel close-handler wiring
- `appserver/static/audit_tz.js:262` — `getInstances()` for the
  timezone-aware audit dashboard
- `appserver/static/control_panel.js:37` — `mvc.Components.getInstance("env")`

The quirk we have to live with on 9.x is that `mvc.Components`
exposes two instances per named token in some dashboards — the
"submitted" and "default" token models — and code must read both
sides to see the truth. The 9.x code already handles this (see
`audit_tz.js:333-334` reading both `submittedTokens` and
`defaultTokens`). If Splunk 10.x changes the model to a single
instance, our 9.x code still works: reading the same value twice
through both wrappers is idempotent. If 10.x renames either method,
`getInstances()` and `get(...)` would have to be migrated together.

Both methods are documented Splunk JS Stack public API; Splunk
typically deprecates over multiple major versions before removing.
No deprecation notices in 9.x release notes that I am aware of.

**Verification gap:** the actual two-instance behavior would only
surface on a 10.0 container with a SimpleXML dashboard that sets
the same token from both inline JS and a `<form>` element. Not
checked here.

### 3. `INDEXED_EXTRACTIONS=json` + `KV_MODE=none`

**Status: Used; stable Splunk behavior.**
`default/props.conf:15-16` and `:27-28` set these for the
`wl_audit` and `wl_audit_recovery` sourcetypes. The combination is
the documented way to write self-describing JSON events without
Splunk auto-extracting fields twice (once at index time, once at
search time). Splunk Docs explicitly document `KV_MODE=none` as the
companion to `INDEXED_EXTRACTIONS=json`.

No 10.x release-note changes to either knob are in scope of this
audit. If 10.x makes `KV_MODE=none` the implicit default when
`INDEXED_EXTRACTIONS=json` is set, our explicit setting becomes a
no-op (safe). If 10.x retires either knob, the migration would be
a `transforms.conf` rewrite — but every Splunk customer would feel
that change, so a deprecation would be flagged in 10.x release
notes before any quiet behavior shift.

### 4. `dispatch_session.context()` user impersonation

**Status: N/A — not used.** A grep across `bin/*.py` and
`default/*.conf` for `dispatch_session`, `impersonate`, and `owner=`
returns nothing in our code. Our scripted inputs
(`wl_fim.py`, `wl_fim_watch.py`, `wl_expiration_cleanup.py`) all
run under the splunkd service account; we never impersonate end
users for the audit-emission path. If a future feature needs
impersonation, it would have to land its own 10.x compat check.

### 5. `splunk.rest.simpleRequest` 404-as-exception

**Status: Used 9×; all wrapped, mix of broad and specific catches.**
Call sites: `bin/wl_handler.py:780, 927, 972, 991, 2055, 2162, 2317`
plus `bin/wl_presence.py:58, 104, 118`. Wrapper inventory:

- `wl_handler.py:780` (`_get_splunk_guid` via `/services/server/info`) —
  `try: ... except Exception as exc: _logger.warning(...)` (line 793,
  marked `# noqa: BLE001`). The broad catch is intentional here
  because GUID lookup is a best-effort fallback path; ANY failure
  (404, 401, connection error, malformed JSON) routes through the
  same fallback to read `instance.cfg` directly.
- 8 other sites — `try ... except splunk.ResourceNotFound` or
  `try ... except Exception` where the 404 case is a known-benign
  "not created yet" code path, per
  `feedback_splunk_simplerequest_404.md`. Where the catch is broad,
  the surrounding logic falls through to a documented zero-state
  default (empty notification list, no presence record, etc.),
  not to a silent failure.

The 9.x behavior is "404 raises `ResourceNotFound` even when
`raiseAllErrors=False`". I am not aware of any 10.x change that
changes this exception type; the Splunk Python SDK contract has
been stable across multiple majors. If 10.x switches to returning
`(404, body)` for any sub-class of 404, our code would silently
treat the 404 as a 200 — but the call sites also check `status ==
200` before acting on `content`, so the worst case is a no-op log
line, not a security bypass.

### 6. `MAX_MULTIVAL_COUNT` field-extraction limit (~371 entries)

**Status: N/A — not relied on.** Grep across `bin/`, `default/`,
and `appserver/static/` for `MAX_MULTIVAL_COUNT` or `MV_ADD`
returns nothing. The dashboard searches that surface row-level
audit detail use `mvexpand` (a search command) before any
multi-value field expansion, which is not bounded by the
extraction-time limit. If 10.x changes the default limit, our code
is unaffected.

### 7. `<panel depends>` reactivity to programmatic token unset

**Status: Used once; we do not depend on broken behavior.**
`default/data/ui/views/audit.xml:684` has
`<row depends="$detail_ts$">`. The known 9.x quirk is that
`<panel depends>` does not react to programmatic `token.unset()`
calls — once the panel is visible, setting the token to null/empty
via JS does NOT hide it again; only setting it to a fresh value
(or a server-side re-render) does.

Our code does NOT rely on programmatic unset to hide this panel.
The panel hides naturally when the user navigates away or when
`$detail_ts$` is re-bound to a different value. If 10.x fixes the
quirk (i.e., `<panel depends>` DOES react to `unset()`), the panel
will hide cleanly when the close button fires. If 10.x changes the
behavior in any other direction, we would need to re-test the close
flow.

## Python language version

`default/commands.conf:9`, `default/inputs.conf:17, 44, 61`, and
`default/restmap.conf:22` all set `python.version = python3` (Splunk
8.0-9.x cert) AND `python.required = 3.13` (Splunk 10.2+ future cert,
pre-emptively documented in the conf comments). The `python3` value
is accepted by every Splunk version from 8.0 onward; the
`python.required` value is ignored by 9.x and consumed by 10.2+.

Syntax sweep across `bin/*.py`:

| Feature | Min Python | Used? |
|---------|------------|-------|
| f-strings | 3.6 | 12 files (safe) |
| walrus operator `:=` | 3.8 | 0 lines |
| `match`/`case` statement | 3.10 | 0 lines (the 4 grep hits are `match = re.search(...)` variable assignments, not structural pattern matching) |
| PEP 604 union types `int \| str` | 3.10 | 0 lines |

Conclusion: bin/*.py runs on Python 3.7 (Splunk 9.3-9.5 baseline) AND
on Python 3.9 (Splunk 10.0 baseline) without modification. The
`python.required = 3.13` pin in inputs.conf is forward-looking, not
load-bearing.

## What is NOT covered by this audit

- Splunk Web JS Stack changes — the `mvc.Components` quirk would
  only surface on a 10.0 dashboard runtime; we have not stood one
  up.
- Splunk Cloud SSAI signing pipeline — if 10.0 SSAI requires a
  different code-signing chain than 9.x, the v1.0.2 release artifact
  may need re-signing.
- KV store schema — 10.0 release notes mention KV store changes;
  our `collections.conf` uses only documented public KV API
  (`POST/GET/PUT/DELETE` against `/servicesNS/.../storage/collections/data/<name>`),
  but a runtime smoke against a 10.0 container is the only way to
  confirm.
- Browser cache invalidation — the `urlArgs: "_b=<build>"` mechanism
  in `whitelist_manager.js:14` works on any Splunk version that
  serves static assets through the `/static/@<server-hash>/` path,
  but a 10.0-side change to that URL path would break the
  cache-bust without breaking the underlying asset load.

## Action items captured by this audit

1. **Update `app.manifest`** — change
   `platformRequirements.splunk.Enterprise` from `"9.3"` to
   `["9.4", "10.0"]`. Done in the same commit as this doc.
2. **CHANGELOG / release notes** — v1.0.2 must say "Declared
   compatible with Splunk Enterprise 9.4 and 10.0 based on API
   stability + 7-risk-area code audit; full E2E suite execution
   against 9.4 and 10.0 containers deferred to v1.1."
3. **CLAUDE.md "Splunk Version Pinning Audit" log table** — append a
   2026-06-02 row marking the audit performed, the decision, and
   the deferred runtime verification.
4. **v1.1 backlog item** — stand up `splunk/splunk:9.4.x` and
   `splunk/splunk:10.0.x` parallel containers, run the integration
   + E2E suite against both, capture any failures here.

## Runtime verification — Splunkbase upload 8800-43334 (2026-06-03)

The v1.0.2 hosted-AppInspect re-run on 2026-06-03 (request
`7f105ce0-6ed6-4e7c-be76-adfe132d879c`, run 8800-43334) was the
runtime confirmation of two things:

1. **SLIM 2.0 LIST-FORM SYNTAX: REJECTED.** SLIM emitted exactly
   one error against `app.manifest`:

   > Expected String value for `manifest.platformRequirements.splunk.Enterprise`,
   > not `['9.4', '10.0']`

   The list form is NOT accepted by SLIM 2.0. Adding this finding
   to the row of historical SLIM-format rejections (cumulative as
   of v1.0.3):

   | Format tried | Result | Tag | Notes |
   |---|---|---|---|
   | `">=9.0.0"` | REJECTED | v1.0.0 (pre-release attempt) | "no upper bound = no concrete version in range" |
   | `">=9.0,<10.0"` | REJECTED | v1.0.0-rc series | Phase 1.7 retry; "no supported version" |
   | `"9.3"` | ACCEPTED | v1.0.0, v1.0.1 | Worked until 9.3 was retired from supported list |
   | `["9.4", "10.0"]` | REJECTED | v1.0.2 | "Expected String value, not [...]" |
   | `"10.0"` | (this release) | v1.0.3 | Expected to pass (matches Phase 1.7's `"9.3"` pattern) |

   **Conclusion (added 2026-06-03)**: SLIM 2.0's
   `platformRequirements.splunk.Enterprise` field accepts ONLY a
   single concrete-version string (`"X.Y"`). Multi-version
   declaration via list form or semver range is NOT supported. The
   only way to declare support for multiple versions in one release
   is for Splunk to ship a SLIM 2.x schema change; no such change
   is on the public Splunkbase roadmap as of 2026-06-03.

2. **The 5 WARNINGS are byte-identical to the v1.0.1 run.** Same
   warnings as `docs/APPINSPECT_FINDINGS.md` §3 (SplunkJS telemetry,
   Python 2/3 compat note, scripted-inputs informational,
   gratuitous-cron-scheduling on 4 security-critical alerts,
   collections.conf informational). No new warning class introduced
   by the manifest edit. Confirms that the manifest change is
   strictly scoped to the platform-requirements declaration with no
   spillover effects on other AppInspect rules.

### Updated decision — v1.0.3

- `app.manifest.platformRequirements.splunk.Enterprise` changes from
  list `["9.4", "10.0"]` to single string `"10.0"` (chosen over
  `"9.4"` for the forward-leaning trade-off documented in
  `docs/DECISION_LOG.md` 2026-06-03 row).
- The 7-risk-area audit results (sections 1-7 above) remain valid —
  the underlying code didn't change between v1.0.2 and v1.0.3, only
  the declared compatibility surface.
- The Python syntax sweep (3.7-compat confirmed) remains valid for
  the same reason.
- 9.4 customers see the standard Splunkbase compatibility-override
  prompt instead of a clean install path; we accept this trade-off
  rather than ship `"9.4"` and force another forced-retirement
  re-release in ~12-18 months when 9.4 hits its end-of-life.

### v1.1 backlog (carries over from v1.0.2, restated for clarity)

- Stand up `splunk/splunk:10.0.x` parallel container, run the
  integration + E2E suite against it before the 2026-07-18 quarterly
  audit. If 10.0 surfaces a regression, v1.0.4 reverts the manifest
  to `"9.4"` (the prior documented fallback in
  `docs/DECISION_LOG.md` 2026-06-02 row) and adds the regression
  details here.
- Track Splunk's SLIM 2.x roadmap: if a future SLIM version adds
  list-form or semver-range support for `platformRequirements`, the
  declaration trade-off in `docs/DECISION_LOG.md` 2026-06-03 row
  can be re-evaluated.

## Runtime verification — Splunkbase upload 8800-43335 (2026-06-04)

v1.0.3's `"10.0"` was REJECTED with the same error class as v1.0.1's
`"9.3"`:

> manifest.platformRequirements.splunk: Version requirement includes
> no supported version of Splunk Enterprise: 10.0

**Lesson**: Splunk Cloud Classic's supported-version list is INTERNAL
to Splunk's managed infrastructure and lags on-prem GA. 10.0 is GA
on-prem but not (yet) on Cloud Classic's supported list. The
2026-06-03 "forward-leaning" choice was wrong for the same reason
`"9.3"` failed: declared value not on Cloud Classic's list.

**Updated cumulative SLIM format history**:

| Format tried | Result | Tag | Notes |
|---|---|---|---|
| `">=9.0.0"` | REJECTED | v1.0.0 pre-release | "no upper bound" |
| `">=9.0,<10.0"` | REJECTED | v1.0.0-rc | Phase 1.7 retry |
| `"9.3"` | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 | 9.3 dropped from list ~2026-05/06 |
| `["9.4", "10.0"]` | REJECTED | v1.0.2 | "Expected String value, not [...]" (F14) |
| `"10.0"` | REJECTED | v1.0.3 | 10.0 not on Cloud Classic supported list (F15) |
| `"9.4"` | v1.0.4 attempt | v1.0.4 | Documented fallback from DECISION_LOG 2026-06-02 row |

**AI-explainer gotcha**: Splunkbase's AI today recommended
`">=9.0.0,<10.0.0"` semver range. That format is empirically rejected
per Phase 1.7. The `<10.0.0` upper bound IS directionally useful (it
confirms Cloud Classic is 9.x), but the specific format suggestion
ignored SLIM's `String value` constraint. Future maintainers: filter
AI explainer suggestions through the cumulative SLIM format history
table above.

**v1.0.4 decision**: Enterprise changes from `"10.0"` to `"9.4"`. The
7-risk-area audit (sections 1-7) remains valid — only the declared
compatibility surface changed. See `docs/DECISION_LOG.md` 2026-06-04
row for the full rationale.

**v1.1 backlog (new)**: investigate Splunkbase publisher RSS/API for
supported-version-list change notifications — both 9.3 and 10.0 became
invalid AFTER the corresponding release was cut.

## Runtime verification — Splunkbase upload of v1.0.4 (2026-06-04 evening) + v1.0.5 trial

v1.0.4's `"9.4"` was ALSO rejected by SLIM with the same error class
as `"9.3"` (v1.0.1) and `"10.0"` (v1.0.3):

> manifest.platformRequirements.splunk: Version requirement includes
> no supported version of Splunk Enterprise: 9.4

**Three single-version strings now confirmed NOT on Cloud Classic's
supported list**: `"9.3"`, `"9.4"`, `"10.0"`. Cloud Classic's
supported list is much narrower than I assumed when writing the
"only `"X.Y"` accepted" conclusion above.

### Analytical correction (2026-06-04 evening)

The prior Runtime Verification section claimed "semver ranges are
type-rejected by SLIM" based on Phase 1.7 evidence. **That conclusion
was overconfident.** Re-examining the error wordings:

- Phase 1.7's `">=9.0,<10.0"` rejection: "no supported version of
  Splunk Enterprise: `>=9.0,<10.0`"
- v1.0.3's `"10.0"` rejection: "no supported version of Splunk
  Enterprise: 10.0"
- v1.0.4's `"9.4"` rejection: "no supported version of Splunk
  Enterprise: 9.4"

All three use the SAME "no supported version" wording. Contrast with
v1.0.2's `["9.4","10.0"]` rejection: "**Expected String value, not
`[...]`**" — clearly different wording.

The Phase 1.7 rejection of `">=9.0,<10.0"` could equally have been
content-based (no version in the range matched the supported list at
that moment), not type-based. v1.0.5 tests this hypothesis with
`">=9.0.0"` (the Splunkbase AI explainer's literal recommendation).

### v1.0.5 — testing `">=9.0.0"`

`app.manifest.platformRequirements.splunk.Enterprise` set to
`">=9.0.0"` (chosen via user AskUserQuestion over `">=9.4"` and
`">=9.0.0,<10.0.0"` alternatives). Rationale: this is the literal AI
recommendation from the v1.0.4 failure explainer; it has the broadest
match set so if ANY version is on Cloud Classic's supported list, it
should match.

Two outcomes possible:

1. **SLIM accepts** — semver ranges work; the cumulative SLIM format
   history learns its first accepted range entry; future releases can
   pin to a semver range and avoid version-retirement re-releases.
2. **SLIM rejects with "Expected String value"** — confirms range is
   type-rejected; my Phase 1.7 conclusion was correct; next move is a
   Splunkbase publisher support ticket asking for Cloud Classic's
   actual supported-version list.
3. **SLIM rejects with "no supported version"** — semver ranges ARE
   parsed but the range still doesn't match anything on the supported
   list, suggesting Cloud Classic's list is NARROWER than `[9.0.0, ∞)`
   (maybe just 8.x or a specific minor like 9.2 only). Next move: try
   narrower ranges anchored to specific candidates, or contact Splunk
   support.

The empirical result of v1.0.5 determines which docs need correcting
and what the next iteration looks like.

### Updated cumulative SLIM format history (post-v1.0.4)

| Format tried | Result | Tag | Notes |
|---|---|---|---|
| `">=9.0.0"` | REJECTED ("no supported version") | v1.0.0 pre-release | Phase 1.6; cause ambiguous (type vs content) |
| `">=9.0,<10.0"` | REJECTED ("no supported version") | v1.0.0-rc | Phase 1.7; cause ambiguous (type vs content) |
| `"9.3"` | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 | Worked until 9.3 dropped from supported list |
| `["9.4", "10.0"]` | REJECTED ("Expected String value") | v1.0.2 | Clearly type-rejected (F14) |
| `"10.0"` | REJECTED ("no supported version") | v1.0.3 | Content rejection (10.0 not on list) (F15) |
| `"9.4"` | REJECTED ("no supported version") | v1.0.4 | Content rejection (9.4 not on list) (F16) |
| `">=9.0.0"` | REJECTED (content) | v1.0.5 | **Critical empirical finding: SLIM echoed back the literal `">=9.0.0"` string, NOT "Expected String value"** — confirming SLIM parses semver ranges as a valid TYPE. Phase 1.7's "type rejection" conclusion was wrong. |
| `">=8.1.0 <10.0.0"` | (v1.0.6 trial) | v1.0.6 | Bounded range (space-conjunction), AI's "temporary broaden" recommendation. Extends floor to 8.x based on AI's new floor hint. |

## Runtime verification — Splunkbase upload of v1.0.5 (2026-06-05) + v1.0.6 trial

v1.0.5's `">=9.0.0"` was rejected by SLIM with:

> manifest.platformRequirements.splunk: Version requirement includes
> no supported version of Splunk Enterprise: **>=9.0.0**

**Major analytical finding — semver ranges parse as TYPE.** The error
echoed back the literal range string `">=9.0.0"`, NOT the "Expected
String value" wording of v1.0.2's clear type rejection. This is the
empirical disambiguation point: SLIM PARSED the range; the rejection
was content-based (no version in `[9.0.0, ∞)` matched Cloud Classic's
supported list).

**Phase 1.7's conclusion was wrong.** My v1.0.2 / v1.0.3 / v1.0.4 docs
flagged semver ranges as type-rejected; that claim is now empirically
falsified. Cleanup commit needed to correct prior overconfident docs.

### Cloud Classic supported-list shape inference (from F13-F17 results)

Versions confirmed NOT on the list:
- 9.3 (F13, v1.0.1)
- 10.0 (F15, v1.0.3)
- 9.4 (F16, v1.0.4)
- All of `[9.0.0, ∞)` (F17, v1.0.5)

The set of supported versions is NOT a contiguous semver range with a
low floor. The Splunkbase AI explainer's new floor hint (`">=8.1.0"`)
suggests Cloud Classic's list may include 8.x versions, OR the AI is
recommending a broad range to maximize match probability.

### v1.0.6 — testing `">=8.1.0 <10.0.0"`

Bounded semver range (space conjunction per AI explainer's example,
NOT comma — Phase 1.7's `">=9.0,<10.0"` used comma which may have
been a syntax issue layered on top of content rejection). Excludes
10.x explicitly. If Cloud Classic's list includes ANY of: 8.1.0
through 9.x latest, this should match.

Three outcomes possible:

1. **SLIM accepts** → first accepted semver-range entry in history;
   future releases pin to this format and stop the version-retirement
   treadmill entirely. Format-history docs need a "CANONICAL FORMAT"
   marker.
2. **SLIM rejects with "no supported version: >=8.1.0 <10.0.0"** →
   Cloud Classic's list is even narrower than `[8.1.0, 10.0.0)`;
   possibly only 10.x or 11.x; next move is Splunkbase publisher
   support ticket.
3. **SLIM rejects with "Expected String value"** → unexpected; would
   mean the space-conjunction form is type-rejected even though
   `">=9.0.0"` was type-accepted. Low probability per the Splunkbase
   AI explainer's recommendation.

The empirical result of v1.0.6 determines whether the project pins to
a stable range format or escalates to Splunk publisher support.

## Runtime verification — Splunkbase upload 8800-43335 (2026-06-04)

The v1.0.3 hosted-AppInspect re-run on 2026-06-04 (request
`c7a3ee83-5b37-43f9-9375-4f59cfaacdde`, run 8800-43335) was the
runtime confirmation of the v1.0.3 `"10.0"` declaration. **Result:
REJECTED.** SLIM emitted exactly one error:

> manifest.platformRequirements.splunk: Version requirement includes
> no supported version of Splunk Enterprise: 10.0

This is the SAME error class as v1.0.1's `"9.3"` rejection (different
version, same mechanism). The lesson — added to the cumulative SLIM
format history — is **structural, not format**:

### Lesson (2026-06-04): Splunk Cloud Classic supported-version list is INTERNAL and lags on-prem GA

The on-prem world has Splunk Enterprise 10.0 GA. Splunk Cloud Classic
(a managed service) runs whatever Enterprise version Splunk's hosted
infrastructure decides — and they tend to be conservative. As of
2026-06-04, Cloud Classic's underlying Enterprise version is 9.x,
NOT 10.0. The 2026-06-03 "forward-leaning" choice was based on a
false assumption that "10.0 GA on-prem" implied "10.0 in Cloud
Vetting's supported list".

**Updated cumulative SLIM format history** (extends the table from
the 2026-06-03 Runtime Verification section):

| Format tried | Result | Tag | Notes |
|---|---|---|---|
| `">=9.0.0"` | REJECTED | v1.0.0 (pre-release attempt) | "no upper bound = no concrete version in range" |
| `">=9.0,<10.0"` | REJECTED | v1.0.0-rc series | Phase 1.7 retry; "no supported version" |
| `"9.3"` | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 | Worked until 9.3 was retired from supported list (2026-05/06) |
| `["9.4", "10.0"]` | REJECTED | v1.0.2 | "Expected String value, not [...]" (F14) |
| `"10.0"` | REJECTED | v1.0.3 | "no supported version of Splunk Enterprise: 10.0" — 10.0 not on Cloud Classic supported list (F15) |
| `"9.4"` | (v1.0.4 attempt) | v1.0.4 | Expected to pass: matches Phase 1.7's `"9.3"` working pattern; AI explainer's `<10.0.0` upper bound implicitly confirms 9.x is Cloud Classic's range |

**Two new conclusions**:

1. SLIM's `platformRequirements.splunk.Enterprise` field accepts only
   single-concrete-version strings, AND those strings must match a
   version currently on Splunk Cloud Classic's internal supported list.
   That list is not published in the app.manifest schema docs and is
   not visible from the AppInspect API spec — the only signal is the
   hosted-AppInspect rejection at upload time.

2. The Splunkbase AI-explainer for SLIM failures is directionally
   useful but NOT format-precise. On 2026-06-04 it recommended
   `">=9.0.0,<10.0.0"` (semver range), which is empirically rejected
   per Phase 1.7. The `<10.0.0` upper bound IS useful — it confirms
   Cloud Classic's current range is 9.x — but the full recommendation
   should be filtered through our cumulative SLIM format history table
   above before being applied.

### Updated decision — v1.0.4

- `app.manifest.platformRequirements.splunk.Enterprise` changes from
  `"10.0"` (v1.0.3) to `"9.4"` (single string, the literal
  "documented fallback" from `docs/DECISION_LOG.md` 2026-06-02 row).
- The 7-risk-area audit results (sections 1-7 above) remain valid —
  the underlying code didn't change between v1.0.3 and v1.0.4, only
  the declared compatibility surface.
- The Python syntax sweep (3.7-compat confirmed) remains valid.
- 10.0-on-prem customers (the population we declared in v1.0.3) see
  the standard Splunkbase compatibility-override prompt instead of a
  clean install path; we accept this trade-off as the cost of
  passing Cloud Vetting.

### v1.1 backlog (extended on 2026-06-04)

- **Cloud Classic version-list freshness gap** (new item): investigate
  Splunkbase publisher RSS/API for supported-version-list change
  notifications. Both 9.3 (v1.0.1) and 10.0 (v1.0.3) became invalid
  AFTER the corresponding release was cut — we had no upstream signal
  until the customer-visible upload failure. If such a feed exists,
  wire a quarterly check into `CLAUDE.md` "Splunk Version Pinning
  Audit". If no feed exists, the only available signal is
  Splunkbase's own AI-explainer message — but per the lesson above,
  that message is directional, not format-precise.
- Stand up `splunk/splunk:9.4.x` parallel container, run the
  integration + E2E suite against it before the 2026-07-18 quarterly
  audit. If 9.4 surfaces a regression, v1.0.5 falls back to a newer
  Cloud-Classic-supported version (currently unknown without
  empirical testing); the recovery path is another hosted-AppInspect
  rejection-driven iteration.
- Track Splunk's SLIM 2.x roadmap: if a future SLIM version adds
  list-form or semver-range support for `platformRequirements`, the
  declaration trade-off in `docs/DECISION_LOG.md` 2026-06-02 and
  2026-06-04 rows can be re-evaluated.

## Runtime verification — Splunkbase upload of v1.0.6 (2026-06-05 evening) + v1.0.7 trial

v1.0.6's `">=8.1.0 <10.0.0"` (space conjunction) was rejected by SLIM
with a **NEW error class**:

> manifest.platformRequirements.splunk.Enterprise: **Illegal version
> specification**: >=8.1.0 <10.0.0

This wording differs structurally from the prior "no supported
version" class. SLIM's
[`check_that_app_passes_slim_validation_for_cloud`](https://dev.splunk.com/enterprise/reference/packagingtoolkit/packagingtoolkitcli/#slim-validate)
now empirically emits at least THREE distinct error wordings:

| Error wording | Rejection class | Example |
|---|---|---|
| `Expected String value, not [...]` | **type** | v1.0.2 list form |
| `Illegal version specification: <value>` | **syntax** | v1.0.6 space form (F18) |
| `Version requirement includes no supported version of Splunk Enterprise: <value>` | **content** | F13, F15, F16, F17 |

### Phase 1.7 retroactive disambiguation

The 2026-06-05 morning Runtime Verification section concluded
"Phase 1.7's `">=9.0,<10.0"` rejection was plausibly content-based,
not type-based." The v1.0.6 result now CONFIRMS this empirically:

- v1.0.6's space form → **syntax** error wording
- Phase 1.7's comma form → **content** error wording (no supported
  version)

Therefore the comma syntax PARSES correctly; Phase 1.7's rejection
was content-based. The set of versions in `[9.0.0, 10.0.0)` did not
match Cloud Classic's supported list at that time, and given v1.0.5's
identical content-rejection of `">=9.0.0"`, still doesn't.

### Cloud Classic supported-list shape narrows further

Combining:

- Phase 1.7's `">=9.0,<10.0"` (comma) → content rejection → no
  version in `[9.0.0, 10.0.0)` matches.
- v1.0.5's `">=9.0.0"` → content rejection → no version in
  `[9.0.0, ∞)` matches.

Therefore: **Cloud Classic's supported list is entirely BELOW
9.0.0** — i.e., 8.x only. This matches Splunkbase AI's 8.1.0 floor
hint from the v1.0.5 explainer.

### Updated cumulative SLIM format history (post-v1.0.6)

| Format | Error class | Result | Release |
|---|---|---|---|
| `">=9.0.0"` | content | REJECTED | v1.0.0 pre-release; v1.0.5 |
| `">=9.0,<10.0"` | **content** (re-classified 2026-06-05 eve) | REJECTED | v1.0.0-rc Phase 1.7 |
| `"9.3"` | (no error then) | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 |
| `["9.4", "10.0"]` | type | REJECTED | v1.0.2 |
| `"10.0"` | content | REJECTED | v1.0.3 |
| `"9.4"` | content | REJECTED | v1.0.4 |
| `">=9.0.0"` | content | REJECTED | v1.0.5 |
| `">=8.1.0 <10.0.0"` (space) | **syntax** | REJECTED | v1.0.6 (F18) |
| `">=8.1.0, <10.0.0"` (comma) | empirical test | (v1.0.7 trial) | v1.0.7 |

### v1.0.7 — testing the comma form

Same range as v1.0.6, but using the comma conjunction the AI
explicitly recommended in the v1.0.6 failure explainer:

> The Packaging Toolkit requires multiple constraints to be
> comma-separated (`">=8.1.0, <10.0.0"`). The space-only separation
> is parsed as an illegal version specification.

If the range `[8.1.0, 10.0.0)` contains any version on Cloud
Classic's supported list (and the 8.x-only shape inference strongly
predicts it does), SLIM should accept.

### Updated decision — v1.0.7

- `app.manifest.platformRequirements.splunk.Enterprise` changes from
  `">=8.1.0 <10.0.0"` (space, v1.0.6) to `">=8.1.0, <10.0.0"`
  (comma, AI's literal recommended form).
- The 7-risk-area audit results remain valid — no code changed
  between v1.0.6 and v1.0.7.

### Three outcomes possible

1. **SLIM accepts** → first ACCEPTED semver-range entry in cumulative
   history. Pin to this comma-form bounded range permanently. Cleanup
   commit fixes the v1.0.2-v1.0.6 docs' "ranges are type-rejected"
   and "space-conjunction is correct" claims.
2. **SLIM rejects with "no supported version: >=8.1.0, <10.0.0"** →
   Cloud Classic's list excludes `[8.1.0, 10.0.0)`. Either the list
   is narrower (e.g., specific 8.x patches only) or even older
   (`<8.1.0`). Next move = Splunkbase publisher support ticket
   (documented escalation path).
3. **SLIM rejects with another unexpected wording** → unprecedented
   class; would require careful analysis of the new error wording
   before next iteration.

### v1.1 backlog (extended on 2026-06-05 evening)

- **AI-explainer-recommendation distillation gap**: the AI gave
  conflicting recommendations across explainers (`">=9.0.0,<10.0.0"`
  semver in v1.0.4 explainer; `">=8.1.0 <10.0.0"` space form in v1.0.5
  explainer; `">=8.1.0, <10.0.0"` comma+space form in v1.0.6 explainer;
  `">=8.1.0,<10.0.0"` no-space form in v1.0.7 explainer).
  Future maintainers reading the AI explainer must read against the
  cumulative SLIM format history table above before applying — the
  AI's specific format suggestions evolve faster than our
  documentation.
- **Consolidate the cumulative SLIM format history into ONE canonical
  table** (cleanup deferred from 2026-06-07 escalation). This doc
  currently contains 5 chronological "Runtime verification"
  subsections, each carrying a snapshot of the cumulative format
  history table. When the Splunkbase support ticket
  (`docs/SPLUNKBASE_SUPPORT_TICKET.md`) returns a working format and
  v1.0.9 is cut, the cleanup commit should: (a) add a "READ THIS
  FIRST — current accepted format" banner at the top of the doc with
  a single canonical table marked `**Updated YYYY-MM-DD**`; (b)
  demote the 5 chronological subsections under a "## Historical
  iterations" heading; (c) mirror the same canonical table into
  `docs/APPINSPECT_FINDINGS.md` §7.12 cumulative-history table so
  the next contributor doesn't have to cross-reference 5 doc
  sections to know what works today. Origin of this item: the
  `scripts/pre-commit-doc-drift.sh` hook does NOT enforce cross-doc
  table consistency (by design — the hook is scoped to build-number
  + file-path drift only). The F20 row was added to
  `docs/APPINSPECT_FINDINGS.md` §7.12 in commit `a9231c4` but is
  not yet present in this doc's cumulative tables, which is the
  exact drift class the consolidation prevents.

## Runtime verification — Splunkbase upload of v1.0.7 (2026-06-06) + v1.0.8 trial

v1.0.7's `">=8.1.0, <10.0.0"` (comma + space) was rejected by SLIM
with the SAME syntax-class error as v1.0.6's space-only form:

> manifest.platformRequirements.splunk.Enterprise: **Illegal version
> specification**: >=8.1.0, <10.0.0

The Splunkbase AI explainer for this failure explicitly corrects
its prior recommendation:

> SLIM's version parser expects a valid specifier set without
> whitespace around commas. The space after the comma causes the
> version spec to be considered invalid.

### Whitespace-sensitivity discovery — the comma is fine, the space is not

We now have a 3-position contrast that fully isolates the
whitespace-sensitivity:

| Form | Whitespace around comma | Error wording |
|---|---|---|
| `">=8.1.0 <10.0.0"` (v1.0.6, space only) | (no comma) | `Illegal version specification` |
| `">=8.1.0, <10.0.0"` (v1.0.7, comma+space) | yes | `Illegal version specification` |
| `">=9.0,<10.0"` (Phase 1.7, comma+no-space) | no | `no supported version` (CONTENT) |

The Phase 1.7 form's content-class error proves comma-with-no-space
parses correctly. The whitespace around the comma is what breaks
parsing.

### Cloud Classic supported-list shape unchanged

The shape inference from 2026-06-05 (8.x only — Phase 1.7 + v1.0.5
both content-rejected `[9.0.0, ...)`) is unchanged by F19. The
whitespace correction is orthogonal to the version-set question.

### v1.0.8 — testing comma with no space

`">=8.1.0,<10.0.0"` — comma directly between constraints, no
surrounding whitespace. This is the form the AI now recommends and
matches Phase 1.7's confirmed-parsable syntax.

### Updated cumulative SLIM format history (post-v1.0.7)

| Format | Error class | Result | Release |
|---|---|---|---|
| `">=9.0.0"` | content | REJECTED | v1.0.0 pre-release; v1.0.5 |
| `">=9.0,<10.0"` | content | REJECTED | v1.0.0-rc Phase 1.7 |
| `"9.3"` | (none then) | ACCEPTED-then-RETIRED | v1.0.0, v1.0.1 |
| `["9.4", "10.0"]` | type | REJECTED | v1.0.2 (F14) |
| `"10.0"` | content | REJECTED | v1.0.3 (F15) |
| `"9.4"` | content | REJECTED | v1.0.4 (F16) |
| `">=9.0.0"` | content | REJECTED | v1.0.5 (F17) |
| `">=8.1.0 <10.0.0"` (space) | syntax | REJECTED | v1.0.6 (F18) |
| `">=8.1.0, <10.0.0"` (comma+space) | syntax | REJECTED | v1.0.7 (F19) |
| `">=8.1.0,<10.0.0"` (comma+no-space) | empirical test | (v1.0.8 trial) | v1.0.8 |

### Three outcomes possible

1. **SLIM accepts** → first ACCEPTED semver-range entry in cumulative
   history. Pin to this comma-no-space bounded form permanently.
2. **SLIM rejects with `no supported version: >=8.1.0,<10.0.0`** →
   Cloud Classic's list excludes `[8.1.0, 10.0.0)`. Either the
   8.x-only inference was wrong, or the list is narrower (specific
   8.x patches only). Next move = Splunkbase publisher support ticket.
3. **SLIM rejects with another unprecedented wording** → new error
   class to catalogue; careful analysis required.
