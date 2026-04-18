# Release Prep Checklist

Pre-release verification steps for `wl_manager`. Run through this list before
cutting any tagged release, packaging for Splunkbase, or pushing to a public
GitHub release.

> **Status (2026-04-16):** Public release is **not** imminent — more features
> and additional E2E rounds are planned. This checklist exists so the parity
> checks stay current as the codebase grows; running them periodically (not
> only at release time) keeps drift small.

---

## 1. Audit Dashboard ↔ Action Code Parity

The Audit Trail dashboard's Action dropdowns (`default/data/ui/views/audit.xml`)
are split into "General Action" and "Admin Action". Whenever a backend module
emits a new `action=` value, the dropdown can silently fall behind — the audit
log shows the action but the dashboard filter has no choice for it. Audit
investigators then can't filter on the new action type.

**Run:**

```bash
# 1. List every action emitted by any handler module
grep -rh '"action":' bin/*.py 2>/dev/null \
  | grep -oE '"action"\s*:\s*"[a-z_]+"' \
  | grep -oE '[a-z_]+(?=")' \
  | sort -u > /tmp/code_actions.txt

# 2. List every choice value present in the audit dashboard dropdowns
grep -oE 'value="[a-z_]+"' default/data/ui/views/audit.xml \
  | grep -oE '[a-z_]+' | sort -u > /tmp/view_actions.txt

# 3. Show actions in code but missing from dropdowns
echo "=== Missing from dropdowns (in code, NOT in view) ==="
comm -23 /tmp/code_actions.txt /tmp/view_actions.txt

# 4. Show stale dropdown choices (in view, NOT in code)
echo "=== Stale dropdowns (in view, NOT in code) ==="
comm -13 /tmp/code_actions.txt /tmp/view_actions.txt
```

**What to do with the output:**

- **Missing from dropdowns** — for each, classify as General (data/CSV/request
  lifecycle) or Admin (governance/security/recovery) per the comment block in
  `audit.xml`, then add a `<choice>` to the right dropdown. See the
  classification rule in the XML for borderline cases.
- **Stale dropdowns** — only worth removing if the action type was renamed or
  permanently retired. If an action just hasn't fired in your test data
  recently, keep the dropdown choice (users may want to filter historical
  events).
- **FIM actions (`fim_*`)** — most go to `sourcetype=wl_fim` rather than
  `wl_audit`, so they show in the FIM panel and don't need dropdown coverage.
  Exceptions are `fim_deploy_window_start/end` which DO go to `wl_audit` and
  must be in the Admin dropdown.

**Acceptance:** zero entries in "Missing from dropdowns" output, OR every
listed action has a documented reason for exclusion (e.g., FIM-only).

---

## 2. wl_debug.js Removed

Confirm no entry point loads the dev-aid module:

```bash
grep -rE "wl_debug" appserver/static/whitelist_manager.js \
                    appserver/static/control_panel.js \
                    appserver/static/audit_trail.js
# Expected: no matches
```

---

## 3. Build Number Bumped

Splunk caches static assets aggressively. Every release must bump
`default/app.conf [install] build = N`.

```bash
grep -E "^build\s*=" default/app.conf
```

---

## 4. E2E Suite Green

```bash
WL_TEST_HARNESS=1 ./tests/e2e/run_all.sh   # or whichever runner is current
```

Expected: all suites pass (current baseline 274/274 + audit dropdown 7/7).

---

## 5. AppInspect Dry-Run

Run Splunk's AppInspect tool against a packaged tarball. See
`docs/APPINSPECT_NOTES.md` for known-warning justifications.

---

## 6. No Uncommitted Working-Tree Changes

```bash
git status --short
# Expected: clean tree (or only the release-tag commit pending)
```

---

## 7. CHANGELOG / Release Notes Drafted

Summarize user-facing changes since the last tag (not internal refactors).
Audit-trail dashboard changes are user-facing — flag dropdown reorganizations
or new filters here.
