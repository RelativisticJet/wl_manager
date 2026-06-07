# Splunkbase Publisher Support Ticket Draft

**Status:** READY TO SEND (as of 2026-06-07).
**Decision rationale:** `docs/DECISION_LOG.md` 2026-06-07 row.

## Why this ticket

After 8 release attempts (v1.0.1 → v1.0.8) and 7 distinct empirical
data points, the iterate-and-test discovery method has run out of
defensible next guesses for
`app.manifest.platformRequirements.splunk.Enterprise`. The cumulative
SLIM format history shows the supported-version list is somewhere
we can't reach without direct guidance from Splunkbase.

The iteration cost (8 releases over 7 days, each visible in
Splunkbase's public listing) now exceeds the support-ticket cost.
This is the documented escalation path from `docs/DECISION_LOG.md`
2026-06-02 row's reversal-cost column and every subsequent row's
"if v1.0.N+1 also fails" guidance.

## How to send

1. Sign in to Splunkbase as the publisher (`Oleh Bezsonov`,
   `communicate.oleh@gmail.com`).
2. Open the support form for Splunkbase Publisher Support.
3. Paste the ticket body below verbatim into the support form.
4. Subject: `wl_manager (Splunkbase 8800) — please confirm supported
   Splunk Enterprise versions for Cloud Classic SSAI`.
5. After sending, append the ticket ID + sent timestamp to the
   "Ticket tracking" section below.

## Ticket body — paste this verbatim

```text
Hi Splunkbase Publisher Support,

I'm the publisher of "Whitelist Manager" — Splunkbase listing 8800,
GitHub source at https://github.com/RelativisticJet/wl_manager.

I've been iterating on `app.manifest.platformRequirements.splunk.Enterprise`
to pass `check_that_app_passes_slim_validation_for_cloud` for Cloud
Classic SSAI, and I'm asking for direct guidance because my empirical
results have diverged from the AI-explainer recommendations.

Over 8 release attempts (v1.0.1 through v1.0.8, all visible at
https://github.com/RelativisticJet/wl_manager/releases) I've established
the following empirical results:

  Format tried                       Error class       Result
  --------------------------------   ---------------   -----------
  "9.3"                              (none — accepted)  ACCEPTED in
                                                        v1.0.0 / v1.0.1,
                                                        retired ~2026-06
  "10.0"                             content            REJECTED v1.0.3
  "9.4"                              content            REJECTED v1.0.4
  ">=9.0.0"                          content            REJECTED v1.0.5
  ["9.4", "10.0"]                    type               REJECTED v1.0.2
  ">=8.1.0 <10.0.0"  (space)         syntax             REJECTED v1.0.6
  ">=8.1.0, <10.0.0" (comma + space) syntax             REJECTED v1.0.7
  ">=8.1.0,<10.0.0"  (comma, no sp)  content            REJECTED v1.0.8

The AI explainer attached to each rejected upload (i.e., the
recommendation SLIM returned alongside each failure, which informed
the NEXT release's trial value) has changed across successive
reports:

  Rejection of    AI explainer's recommended next value
  --------------  ----------------------------------------
  v1.0.4 upload   ">=9.0.0,<10.0.0"   (semver range)
  v1.0.5 upload   ">=8.1.0 <10.0.0"   (space-only, no comma)
  v1.0.6 upload   ">=8.1.0, <10.0.0"  (comma + space)
  v1.0.7 upload   ">=8.1.0,<10.0.0"   (comma, no whitespace)
  v1.0.8 upload   ">=9.0.0"           (open floor)

We tried each one literally (v1.0.5 used ">=9.0.0" from a different
discovery path; the AI explainer for v1.0.4 was directionally similar
but with an upper bound).

The v1.0.8 explainer recommended ">=9.0.0", but that value was
already empirically rejected in v1.0.5 with the same "no supported
version" content error — i.e., the AI is recycling a known-failed
value rather than offering new triangulation.

The v1.0.8 result is informative: comma-no-space syntax PARSES (we
get a content error, not the "Illegal version specification" syntax
error). This means the supported-version set is just somewhere I'm
not declaring.

My questions:

  1. What Splunk Enterprise versions are currently on Splunk Cloud
     Classic's supported list for `platformRequirements.splunk.Enterprise`?

     Empirically nothing in [8.1.0, 10.0.0) is on the list, and 10.0
     was independently rejected as a single-version string. Is the
     supported list currently below 8.1.0, or is there a specific
     9.x patch version I should declare explicitly?

  2. If it's easier, what is the recommended manifest value for a
     freshly-published v1.x app targeting Cloud Classic today? I
     can pattern-match that and skip the format trial-and-error
     entirely.

The full cumulative SLIM format history (with error wordings and
release tags) is in our public docs:
https://github.com/RelativisticJet/wl_manager/blob/main/docs/SPLUNK_10_COMPATIBILITY.md

Thank you,
Oleh Bezsonov
Publisher of Whitelist Manager (Splunkbase 8800)
```

## What I will do with the response

- **If Splunkbase gives a specific version string** (e.g., "use `\"9.2\"`"):
  cut v1.0.9 with that value verbatim. Document the answer in
  `docs/SPLUNK_10_COMPATIBILITY.md` "Runtime verification" + add the
  CANONICAL row to the cumulative format history table.
- **If Splunkbase gives a range form** (e.g.,
  `">=9.2.0,<9.4.0"`): same as above — cut v1.0.9 with that value.
- **If Splunkbase confirms the on-prem-only fallback** (or says Cloud
  Classic SSAI is not currently accepting new apps): update
  `docs/DECISION_LOG.md` with the on-prem-only decision and ship the
  app as `_standalone` / `_distributed` only. Splunkbase listing
  stays available; only the SSAI / Cloud Classic install path is
  blocked.

## Ticket tracking

| Field | Value |
|---|---|
| Sent at | (to fill in after sending) |
| Splunkbase ticket ID | (to fill in) |
| First response received | (to fill in) |
| Resolution | (to fill in) |
| v1.0.9 release cut | (to fill in once we have the answer) |

## Cross-references

- Cumulative empirical history: `docs/SPLUNK_10_COMPATIBILITY.md`
  Runtime Verification sections.
- Decision rationale for escalation:
  `docs/DECISION_LOG.md` 2026-06-07 row.
- Per-release failure breakdown: `docs/APPINSPECT_FINDINGS.md`
  sections 7.5 (v1.0.1) through 7.11 (v1.0.7) + the v1.0.8 result
  (added in the escalation commit).
- Audit log of the version-pinning iteration: `CLAUDE.md`
  "Splunk Version Pinning Audit" table, 2026-06-02 through 2026-06-07.
