<!--
  Please fill out every section below. PRs that skip the Test Plan or
  Verification sections will be asked to add them before review.
  Delete this comment block before submitting.
-->

## Summary

<!-- One sentence: what does this PR change and why? -->

## Type of change

<!-- Check all that apply -->
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to break)
- [ ] Documentation update
- [ ] Refactor / internal cleanup (no behavior change)
- [ ] Security fix (please also follow [SECURITY.md](../SECURITY.md))

## Related issues

<!-- Link issues this PR resolves, e.g. "Closes #123" -->

## Test Plan

<!--
  How was this change tested? Include enough detail that a reviewer can
  reproduce the verification on their own clean Splunk container.
  Note: PRs that touch backend (bin/*.py), security paths, or audit
  emission MUST include browser-level E2E or integration evidence.
-->
- [ ] Unit tests added / updated (`tests/unit/`)
- [ ] Integration tests added / updated (`tests/integration/`)
- [ ] E2E tests added / updated (`tests/e2e/`)
- [ ] Manual verification steps documented below

<!-- Manual verification steps, if any: -->

## Verification

<!-- For UI/dashboard changes, attach screenshots or short clips. -->
<!-- For backend changes, paste an audit-trail snippet showing the new event. -->

- [ ] `appinspect.yml` workflow passes (no new errors / future_failures)
- [ ] All other CI workflows green (or any failures explained below)
- [ ] No new secrets / credentials / personal data added to source
- [ ] `default/app.conf` `build` bumped if user-visible behavior changed

## Audit-trail impact

<!-- Required if the PR adds or modifies a handler action. -->

- [ ] This PR does NOT add or modify any handler action (no audit impact)
- [ ] This PR adds a new audit action — listed below + verified via `/verify-audit`
- [ ] This PR modifies an existing audit action — listed below + verified via `/verify-audit`

<!-- If you ticked one of the audit boxes, list affected actions: -->

## Documentation

- [ ] `CHANGELOG.md` updated
- [ ] User-facing docs updated (README / INSTALLATION / docs/*) if user-visible behavior changed
- [ ] No docs change required

## Reviewer notes

<!-- Anything else the reviewer should know: risks, follow-ups, deferred work. -->
