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
