# Development Hooks

Shareable Claude Code hook scripts for this project. Every developer
working on `wl_manager` should wire these into their local Claude Code
settings so the project's development discipline is enforced
mechanically, not just by prose in `CLAUDE.md`.

The hooks themselves live here (git-tracked) so they evolve with the
project. The per-developer wiring lives in `.claude/settings.json`
(git-ignored), which is why each contributor must follow the one-time
setup below.

## Quick start for new collaborators

```bash
bash scripts/install-hooks.sh   # writes .claude/settings.json from template
make hook-tests                  # confirm everything wired up (105 assertions)
```

`scripts/install-hooks.sh` reads the tracked TEMPLATE at
`.claude/settings.example.json`, substitutes the hardcoded
`c:/Users/PC/wl_manager` prefix with your actual checkout path, and
writes the result to `.claude/settings.json` (the actual per-developer
config, gitignored). Re-running on the same checkout is a silent no-op;
re-running against a different checkout refuses unless you pass
`--force`.

If you prefer to edit settings.json by hand:

```bash
cp .claude/settings.example.json .claude/settings.json
# Then s/c:\/Users\/PC\/wl_manager/<your checkout>/ throughout.
```

### Global hooks (separate from this directory)

Three additional hooks live under `~/.claude/hooks/` (NOT in this repo)
and are registered in `~/.claude/settings.json`. They are not part of
`install-hooks.sh` because they apply to ALL projects on your machine,
not just `wl_manager`:

- `force-push-guard.js` — PreToolUse Bash; blocks `git push --force`
  to shared branches; allows `--force-with-lease`.
- `banned-phrase-trigger.js` + companion prompt hook — Stop +
  UserPromptSubmit pair; scans last assistant message for the 5
  CLAUDE.md banned phrases ("Should be fine", "Probably passes",
  "Theoretically correct", "I think it's fixed", "I fixed it, you
  try"), injects a system-reminder next turn requiring
  evidence-backed retraction.
- `additional-thoughts-trigger.sh` + companion prompt hook — Stop +
  UserPromptSubmit pair; mechanizes the user preference to always
  surface gap-analysis after substantive work.

The global hooks are covered by `tests/hooks/test_global_*.sh` which
skip gracefully if the hook isn't installed. Source for the global
hooks isn't in this repo; ask the maintainer for the install bundle
if you want them.

## Available hooks

### `block-synthetic-fixtures.js`

**Type**: `PreToolUse`
**Matcher**: `Write | Edit | Bash`

Blocks direct writes to Splunk-internal state files that would bypass
the handler's production code path during feature verification. This
exists because prose rules in `CLAUDE.md` ("Verification Before Done",
"Audit Trail Verification") failed to prevent the build 614 (2026-04-23)
"Invalid Date" incident — synthetic injection into `_approval_queue.json`
masked schema drift between `timestamp` and `submitted_at`.

**Blocks**:

- `Write` / `Edit` to `lookups/_versions/_approval_queue.json`,
  `_daily_limits.json`, `_detection_rules.json`, `_limit_config.json`,
  `_notifications.json`, `_trash_config.json`, `_emergency_lockdown.json`,
  `_action_cooldowns.json`, `_fim_deploy_window.json`, plus hidden files
  `.fim_baseline.json`, `.fim_alert_state.json`, `.csv_expected_hashes.json`,
  `.presence.json`
- `Write` / `Edit` to synthetic-fixture scripts: `tests/_inject_*.py`,
  `tests/*_fixture_*.py`, `tests/*synthetic*.py`
- `Bash` that writes (via `>`, `>>`, `tee`, `json.dump`, `docker cp`,
  `cp`, `mv`) to any of the above paths
- `Bash` that calls `POST`/`PUT`/`DELETE`/`PATCH` against
  `storage/collections/data/wl_cooldowns|wl_fim_baseline|wl_presence|wl_lockdown`

**Exceptions (by design)**:

- Any path under `tests/unit/**` — pure-helper unit tests verify
  math in isolation, not feature behavior. The existing 19 tests in
  `tests/unit/` (test_approval, test_audit, test_csv, etc.) stay
  unaffected.
- `Bash` commands that contain the literal marker `# JUSTIFIED: <reason>`.
  Use ONLY when no production endpoint exists — e.g. first-install
  bootstrapping of the FIM baseline on a brand-new container. The
  reason must be concrete; "for testing" is not a reason.
- `GET` calls against KV collections (read-only; no mutation).
- Appends to `_recovery_log.jsonl` (it is designed as an append-only
  fallback from `wl_expiration_cleanup.py` and the recovery scripts).

### `preflight-tag-guard.js`

**Type**: `PreToolUse`
**Matcher**: `Bash`

Catches `git tag vX.Y.Z`, `gh release create vX.Y.Z`, and
`gh api ... tag_name=vX.Y.Z` commands and runs the §3.5
Version-Tag Consistency pre-flight from
`docs/RELEASE_CHECKLIST.md`. Blocks (exit 2) if any of the four
sources of truth disagree with the intended tag:

- `default/app.conf [launcher].version`
- `default/app.conf [id].version`
- `app.manifest info.id.version`
- `default/app.conf [package].id == [id].name`

Non-semver tag names (`my-feature-branch`, `pre-release-test`) are
ignored. `Edit` / `Write` / non-Bash tool calls are ignored.

The underlying check is `scripts/preflight-tag.sh` — it can also
be run manually before any tag-cut.

### `validate-runner.js`

**Type**: `PostToolUse`
**Matcher**: `Edit | Write`

After edits to `default/*.conf`, `app.manifest`, or
`default/data/ui/{views,nav}/*.xml`, runs `scripts/validate.sh`
(the same checks Splunk AppInspect runs locally) and surfaces the
FAIL count + first 10 failing lines to Claude via stderr.
Non-blocking. Latency ~7.7s on Windows + Git Bash + Python; only
triggered by the narrow set of config edits.

### `urlargs-sync.js`

**Type**: `PostToolUse`
**Matcher**: `Edit | Write`

After any edit to `default/app.conf`, syncs
`appserver/static/whitelist_manager.js`'s
`require.config({ urlArgs: "_b=N" })` to match
`[install].build`. Mechanizes the rule in CLAUDE.md "Splunk
Quirks": *bumping `build` in `app.conf` REQUIRES also bumping
`_b=` in `whitelist_manager.js`*. Without this, the year-long
browser cache leaves users running stale JS until they hard-refresh.

### `lib/code-quality-checks.js`

**Type**: shared library (not a hook itself)

Detection patterns used by both `.claude/hooks/post-edit-check.js`
(PostToolUse) and `.claude/hooks/stop-check.js` (Stop). Catches
Python `print()` / `pdb` / bare `except:` and JS `console.log` /
`debugger` / `innerHTML` XSS patterns. Consolidated 2026-06-01 so
the two consumers stay in sync (previously the regex set drifted
between them).

The two consumer hooks live under `.claude/hooks/` (per-developer)
because their threshold logic is personal preference — but the
patterns themselves live here, tracked.

## Setup (per developer, one-time)

Add this entry to your project-local `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "tool == 'Write' || tool == 'Edit' || tool == 'Bash'",
        "hooks": [
          {
            "type": "command",
            "command": "node ${workspaceFolder}/scripts/hooks/block-synthetic-fixtures.js"
          }
        ]
      }
    ]
  }
}
```

Claude Code does not expand `${workspaceFolder}` in the `command`
string today, so use the absolute path to your checkout, e.g.
`node <your-checkout>/scripts/hooks/block-synthetic-fixtures.js`.
This is the reason the wiring is per-developer rather than a single
shared config.

### Smoke-test after wiring

```bash
# Should BLOCK (exit 2 with message)
TOOL_NAME=Write \
  TOOL_INPUT_file_path="lookups/_versions/_approval_queue.json" \
  node scripts/hooks/block-synthetic-fixtures.js
echo "exit=$?"

# Should ALLOW (exit 0, silent)
TOOL_NAME=Write \
  TOOL_INPUT_file_path="tests/unit/test_something.py" \
  node scripts/hooks/block-synthetic-fixtures.js
echo "exit=$?"
```

## Why this lives in `scripts/hooks/` and not `.claude/hooks/`

- `.claude/` is git-ignored (see `.gitignore`) so each developer can
  keep personal permissions and paths in `settings.local.json` without
  leaking them into PRs.
- The hook SCRIPTS are project discipline, not personal config, so
  they are tracked here and reviewed like any other code change.
- Split inspired by the way `scripts/pre-commit` is tracked but the
  git-hook symlink at `.git/hooks/pre-commit` is per-developer.

## Adding a new hook

1. Drop the script in `scripts/hooks/<your-hook-name>.js` (or `.py` / `.sh`).
2. Document it in this README under "Available hooks".
3. Provide a `Setup` snippet showing the exact `.claude/settings.json`
   entry to add.
4. Smoke-test with at least one blocking and one allowing case.
5. Commit. Collaborators opt in individually via step 3.

## Known Limitations

### Subagents bypass the hook

Smoke-test on 2026-04-24: a subagent dispatched via the `Agent` tool
(subagent_type: `general-purpose`) was able to execute
`echo "{}" > lookups/_versions/_fim_deploy_window.json` without the
hook firing. The parent session has the hook wired in
`.claude/settings.json`, but the subagent ran in an isolated Claude
Code context that does not inherit project-local PreToolUse hooks.

**Until this gap is closed, do not delegate writes to protected
Splunk state to subagents.** The `Agent` tool is safe for research,
exploration, and read-only analysis; reserve mutations for the
parent session where the hook applies.

**Mitigation options** (none implemented today):

- Duplicate the hook at `~/.claude/hooks/` referenced from
  `~/.claude/settings.json` — may propagate to subagents because
  user-level settings can inherit differently than project-level.
  Needs verification.
- File system ACL on `lookups/_versions/*.json` granting write only
  to the Splunk container user. Tradeoff: breaks hand-editing for
  debugging and may break deploy scripts.
- Explicit CLAUDE.md rule forbidding subagent delegation for writes.
  Prose-only, relies on self-discipline; the same kind of rule that
  failed to prevent the incident this hook exists to address.

### Obfuscated Bash bypasses the write indicators

The Bash matcher uses a regex for `WRITE_INDICATORS`. A heavily
obfuscated command (e.g. base64-encoded Python, multi-stage shell
expansion) could evade it. The threat model is "Claude talking itself
into shortcuts", not "a motivated attacker" — obfuscation is not
a pattern I use, so this is an accepted gap.

## Related

- `CLAUDE.md` → "Synthetic Fixtures — Banned for Feature Verification
  (mechanically enforced)" — the prose policy the hook enforces.
- `CLAUDE.md` → "Decision Log" → 2026-04-23 row — why hook beats prose.
- `~/.claude/projects/c--Users-PC-wl-manager/memory/feedback_synthetic_fixtures_mask_schema_drift.md`
  — the lesson captured for future sessions.
