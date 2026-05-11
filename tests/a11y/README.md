# Accessibility Audit — `tests/a11y/`

Automated WCAG 2.1 Level AA conformance checks for the three
main wl_manager dashboards. Uses [axe-core][axe] via
`@axe-core/playwright`. Ring 5 Day 4 (2026-05-11).

[axe]: https://github.com/dequelabs/axe-core

## What this scans

- `/app/wl_manager/whitelist_manager` — main CSV editing UI
- `/app/wl_manager/control_panel` — admin settings
- `/app/wl_manager/audit` — audit trail viewer

Login is as `superadmin1` so every role-conditional UI subtree
(admin-only panels, superadmin-only controls) renders. An
analyst-tier scan would miss admin-rendered content, so this
audit deliberately uses the maximum-privilege account.

## How to run

```bash
docker compose up -d
./tests/e2e/setup_test_env.sh
npm install
npx playwright install --with-deps chromium
npm run test:a11y
```

Reports land in `tests/a11y/reports/<page-label>.json` plus
`summary.json`. Exit code: 0 (pass), 1 (a11y failures), 2
(infrastructure error).

## Pass/fail criterion

- **FAIL**: any violation at `serious` or `critical` impact
  level that is not in `tests/a11y/baseline.json`.
- **PASS**: everything else (including `moderate` and `minor`
  violations, which are reported but informational).

The threshold is conservative on purpose — `serious` and
`critical` are the levels at which axe-core's authors flag
real barriers for assistive-tech users. `moderate` and `minor`
are real issues to fix but shouldn't block CI.

## Baseline contract — `baseline.json`

Format (no schema enforcement, but the loader is strict
about the shape):

```json
{
  "<rule_id>": ["<selector1>", "<selector2>", ...]
}
```

- `<rule_id>` is the axe-core rule that fired (e.g.
  `color-contrast`, `region`, `landmark-one-main`).
- The array is the list of `node.target` selector strings
  that are pre-accepted for that rule. A violation is
  suppressed iff EVERY one of its nodes is in the accepted
  list; if any node is new, the violation surfaces with
  only the new nodes attached.

**Maintenance contract — every entry must be justified.**
When adding a suppression:

1. Add the entry to `baseline.json`.
2. Append a row to the "Suppressed violations" table below
   citing: the rule id, the selectors, the Splunk-specific
   reason it's acceptable, the date.
3. Commit the two files together.

No silent suppressions. If the reason is "axe is wrong here,"
write that — but it should be unusual.

## Suppressed violations

| Rule id | Selectors | Reason | Date added |
|---------|-----------|--------|------------|
| _(empty — first run will populate)_ | — | — | — |

## First-run flow

The baseline starts empty at Ring 5 Day 4 inception. The
first run will produce a list of violations — many of them
in Splunk's own DOM (header chrome, app nav, footer) that
we don't control. Triage:

1. Run `npm run test:a11y` and review
   `tests/a11y/reports/summary.json`.
2. For each violation:
   - If rooted in `appserver/static/**` or our handler's
     rendered HTML — **fix it**, don't suppress.
   - If rooted in Splunk-bundled DOM (selectors starting
     with `.splunk-`, `#splunk-`, `.dashboard-`, or
     similar) — add to `baseline.json` with a "Splunk-
     bundled, not our DOM" reason.
   - If genuinely ambiguous — flag for manual review in
     a PR comment.

## Caveats

axe-core is the automated floor, not the ceiling. These
checks **don't** catch:

- Keyboard-only navigation (tab order, focus visibility,
  trapped focus in modals)
- Screen-reader announcement quality (correctness of
  ARIA labels, live-region behavior)
- Reduced-motion preferences
- Color-blindness simulation beyond contrast ratio

For those, periodic manual testing with NVDA / VoiceOver /
keyboard-only sessions is required. Track manual a11y
reviews in CHANGELOG separately from this automated audit.
