# Hook unit tests

Bash-based test harness covering the project hooks (in
[`.claude/hooks/`](../../.claude/hooks/) and
[`scripts/hooks/`](../../scripts/hooks/)) plus the user's global hooks
in `~/.claude/hooks/`. The global-hook tests skip gracefully when the
hook isn't installed, so a fresh clone can run the full suite without
extra setup.

## Run

```bash
bash tests/hooks/run.sh
# or
make hook-tests
```

Each `test_*.sh` file is a self-contained suite that ends with a
PASS / FAIL line. The runner prints a final aggregate.

## What's covered

| File | Hook(s) under test |
|------|----|
| `test_doc_drift.sh` | `scripts/pre-commit-doc-drift.sh` |
| `test_preflight_tag_guard.sh` | `scripts/preflight-tag.sh` + `scripts/hooks/preflight-tag-guard.js` |
| `test_validate_runner.sh` | `scripts/hooks/validate-runner.js` |
| `test_urlargs_sync.sh` | `scripts/hooks/urlargs-sync.js` |
| `test_code_quality_checks.sh` | `scripts/hooks/lib/code-quality-checks.js` + `.claude/hooks/post-edit-check.js` + `.claude/hooks/stop-check.js` |
| `test_global_force_push_guard.sh` | `~/.claude/hooks/force-push-guard.js` (skips if missing) |
| `test_global_banned_phrase.sh` | `~/.claude/hooks/banned-phrase-trigger.js` (skips if missing) |
| `test_global_additional_thoughts.sh` | `~/.claude/hooks/additional-thoughts-trigger*.sh` (skips if missing) |

## Writing a new test

Each suite sources `_lib.sh` and uses:

- `start_suite "<name>"` — opens the suite
- `expect_eq "<desc>" "<want>" "<got>"` — equality check
- `expect_exit "<desc>" <want_code> <cmd...>` — runs cmd, checks exit
- `expect_contains "<desc>" "<needle>" "<haystack>"`
- `expect_not_contains "<desc>" "<needle>" "<haystack>"`
- `skip_if_missing "<path>" "<reason>"` — skip whole suite if file absent
- `finish_suite` — prints summary, exits 1 on any failure

Mutate-and-restore tests must register a trap so cleanup runs even on
failure. See `test_urlargs_sync.sh` for the canonical pattern.

## Why bash, not pytest?

Hooks are invoked via `node` / `bash` from `~/.claude/settings.json`
and per-project `.claude/settings.json`. A bash harness exercises the
same surface (stdin JSON, env vars, exit codes) without bringing in a
Python test framework dependency. The hooks themselves are tiny — the
test harness should be too.

## Hidden-pattern trick

Two test scripts (`test_preflight_tag_guard.sh`,
`test_global_force_push_guard.sh`) construct trigger-pattern strings
at runtime (`GIT="g""it"; TAG="t""ag"`). This isn't paranoia — when
the tests are invoked through Claude Code's Bash tool, the outer
command argv is read by the project's PreToolUse guards. A literal
`git tag v0.0.0-drift` in this file's source wouldn't appear in argv
(only the bash invocation line does), but the same string passed to
`subprocess.run(...)` as `tool_input.command` IS what the guards read.
Constructing the triggers at runtime keeps the test SOURCE auditable
by hand while preventing accidental self-blocking when the test reads
the trigger string back into the hook under test.
