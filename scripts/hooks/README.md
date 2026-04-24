# Development Hooks

Shareable Claude Code hook scripts for this project. Every developer
working on `wl_manager` should wire these into their local Claude Code
settings so the project's development discipline is enforced
mechanically, not just by prose in `CLAUDE.md`.

The hooks themselves live here (git-tracked) so they evolve with the
project. The per-developer wiring lives in `.claude/settings.json`
(git-ignored), which is why each contributor must follow the one-time
setup below.

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
`node c:/Users/PC/wl_manager/scripts/hooks/block-synthetic-fixtures.js`.
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

1. Drop the script in `scripts/hooks/your-hook-name.js` (or `.py` / `.sh`).
2. Document it in this README under "Available hooks".
3. Provide a `Setup` snippet showing the exact `.claude/settings.json`
   entry to add.
4. Smoke-test with at least one blocking and one allowing case.
5. Commit. Collaborators opt in individually via step 3.

## Related

- `CLAUDE.md` → "Synthetic Fixtures — Banned for Feature Verification
  (mechanically enforced)" — the prose policy the hook enforces.
- `CLAUDE.md` → "Decision Log" → 2026-04-23 row — why hook beats prose.
- `~/.claude/projects/c--Users-PC-wl-manager/memory/feedback_synthetic_fixtures_mask_schema_drift.md`
  — the lesson captured for future sessions.
