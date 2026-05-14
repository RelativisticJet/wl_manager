# QA Failure-Mode Library — wl_manager-specific

> Project-specific patterns that the Second-pass review SubAgent applies on
> top of `~/.claude/qa-failure-modes-global.md`.
> Append-only — never delete; mark "rescinded" if needed.

---

## splunk-cache-claim-without-bust

- **Pattern**: I claim a JS/CSS/dashboard change "is deployed" or "users will see" without verifying the cache-bust mechanism (`requirejs urlArgs: "_b=N"`, internal KV-store dashboard cache, `i18n/<file>.js-*` cache) was invalidated. Splunk caches static assets for up to 1 year.
- **Detection signal**: Output contains "deployed", "users will see X", "frontend updated" alongside a `whitelist_manager.js` / `*.css` / `data/ui/views/*.xml` change.
- **How to verify**: (a) `Read` `default/app.conf` for `build = N` and `appserver/static/whitelist_manager.js` for `urlArgs: "_b=N"` — confirm they match (the pre-commit hook now blocks mismatches but check anyway). (b) For dashboard XML, verify the REST POST happened (`grep` deploy command transcript for `data/ui/views/<view>` POST). (c) For i18n cache, check that the relevant `i18n/<file>.js-*` was cleared.
- **Real incident**: build 607 (2026-04-22), `wl_manager`. False-positive modal fix was deployed and "verified" but browser cache kept serving old JS. User reported the bug as still-present for hours after the "fix" landed.

## audit-event-claim-without-verify

- **Pattern**: I claim an audit-emitting action "worked" because the UI showed a success toast or the REST response was 200. I did NOT query `index=wl_audit` to confirm the event actually landed.
- **Detection signal**: Output contains "saved", "approved", "rejected", "removed" + UI/REST evidence but no `mcp__splunk__splunk_search` or `splunk_get_audit` invocation.
- **How to verify**: Use `mcp__splunk__splunk_get_audit` (or `splunk_search index=wl_audit ...`) within the last 5 minutes. Confirm the expected action was indexed with the expected fields. Per CLAUDE.md "Audit Trail Verification" rule, this is mandatory for every audit-emitting action.
- **Real incident**: pattern flagged in CLAUDE.md as standing risk. The `_index_audit()` call has historically failed silently on 401 (expired session key, schema drift on new actions). The success path returns 200 even when the audit write failed.

## synthetic-fixture-injection

- **Pattern**: I "test" a feature by directly editing files in `lookups/_versions/` (approval queue, daily limits, FIM baseline, KV-store cooldowns) instead of exercising the production endpoint. This masks schema drift between what the handler writes and what the frontend reads.
- **Detection signal**: Output contains `Write` or `Edit` to any path under `lookups/_versions/_*.json`, `lookups/_versions/.fim_baseline.json`, or any curl POST/PUT/DELETE to KV-store paths (`wl_cooldowns`, `wl_fim_baseline`, etc.).
- **How to verify**: The PreToolUse hook `scripts/hooks/block-synthetic-fixtures.js` should have blocked this. If the change still landed, either the hook was bypassed (`--no-verify`?), a subagent did it (subagents don't inherit the hook — known gap), or the hook regressed.
- **Real incident**: 2026-04-23, `wl_manager`, build 614. Injected synthetic approval queue entries with `timestamp` and `submitted_at` both set. Real dual-admin submissions only set `submitted_at`. The "Invalid Date" bug shipped because the synthetic fixtures hid the schema mismatch.

## scripted-input-cmd-relative-path

- **Pattern**: I add or edit a scripted input stanza in `default/inputs.conf` using `./bin/<script>` syntax. Splunk accepts this but Cloud Vetting's best practice is the absolute `$SPLUNK_HOME/etc/apps/wl_manager/bin/<script>` form.
- **Detection signal**: `default/inputs.conf` change includes `[script://./bin/`.
- **How to verify**: `Grep` for `script://./bin/` in `default/inputs.conf` — should be zero matches. If present, the change reverted a Phase 0.0 fix.
- **Real incident**: 2026-05-14 fix (build 660) — switched all 3 scripted inputs to absolute paths. Easy to regress.

## python-version-without-python-required

- **Pattern**: I add a new scripted input / custom command / REST handler stanza without including BOTH `python.version = python3` AND `python.required = 3.13`. AppInspect needs both: current cert wants `python.version`, Splunk 10.2+ cert wants `python.required`.
- **Detection signal**: New `default/inputs.conf` / `default/commands.conf` / `default/restmap.conf` stanza for a `.py` file that has one but not the other.
- **How to verify**: `Grep` the new stanza for both `^python\.version` AND `^python\.required` lines. Both required.
- **Real incident**: 2026-05-14 (build 660) — first attempt removed `python.version` and only kept `python.required = python3`, triggering 4 NEW failures. Recovery required adding both back. Documented inline in conf files.

## package-id-without-package-stanza

- **Pattern**: I add an `[id]` stanza to `default/app.conf` without keeping the legacy `[package]` stanza. AppInspect needs both.
- **Detection signal**: `default/app.conf` change adds `[id]` AND removes `[package]`.
- **How to verify**: `Grep` for both `^\[id\]` and `^\[package\]` in `default/app.conf`. Both required, with matching `name = X` (under `[id]`) and `id = X` (under `[package]`).
- **Real incident**: 2026-05-14 (build 660) — same incident as above, first attempt removed `[package]` and triggered 2 NEW failures.

## doc-path-placeholder-in-changelog

- **Pattern**: I use a path-looking placeholder (`bin/foo.py`, `default/something.conf`) in CHANGELOG.md or other doc-drift-checked files as an example. The drift hook parses every path-shaped token as a real file reference and rejects the commit.
- **Detection signal**: A CHANGELOG/README/docs/*.md edit containing strings matching `bin/[a-z_]+\.py`, `default/[a-z_]+\.conf`, `docs/[A-Z_]+\.md`, etc. that don't correspond to existing files.
- **How to verify**: For each path-shaped token in the staged diff, verify the file exists. If a token is a placeholder, replace with concrete filenames or `<script>` / `{name}` style placeholders.
- **Real incident**: 2026-05-14 (commit `daf709f`), `wl_manager`. CHANGELOG entry used `bin/foo.py` and `docs/APPINSPECT_FINDINGS.md` as placeholders; doc-drift hook rejected commit. Lesson saved at `~/.claude/memory/feedback_no_path_placeholders_in_drift_checked_docs.md`.

## test-fixture-leaking-into-spl

- **Pattern**: I claim "the .spl is clean" or "we excluded test data" without checking the actual `tar -tzf` output. `scripts/package.sh`'s denylist has drifted multiple times.
- **Detection signal**: Output contains ".spl built", "package.sh succeeded", ".spl is clean" without a `Bash` invocation showing `tar -tzf` was checked.
- **How to verify**: `Bash`: `tar -tzf dist/wl_manager-<version>.spl | grep -E '(/\.|/node_modules/|/htmlcov/|/bench_results/|/test-results/|/lookups/_trash/)'` — should produce zero output. Note: `scripts/package.sh` Step 4b now does this automatically (build 660), so if package.sh ran successfully the .spl IS clean. But verify by re-running anyway during QA.
- **Real incident**: 2026-05-14, `wl_manager`, Phase 0.0. First `.spl` was 20 MB and contained `node_modules`, `.playwright-mcp`, `.audit`, `.zap`, etc. AppInspect caught it; my own pre-build review did not.

## cron-cadence-justified-but-warning-remains

- **Pattern**: I add prose justification for a high-frequency cron schedule in `savedsearches.conf` and claim the AppInspect warning is "closed". AppInspect reads the `cron_schedule` value, not the comment.
- **Detection signal**: Output contains "closes W6", "closes check_for_gratuitous_cron_scheduling", or similar alongside a comment-only edit to `default/savedsearches.conf`.
- **How to verify**: Re-run AppInspect (`make appinspect`); count `check_for_gratuitous_cron_scheduling` warnings before and after. If the count is unchanged, the prose was for human review only.
- **Real incident**: 2026-05-14 (commit `5da7f07`), `wl_manager`. Added justification comments to 4 saved searches, claimed "closes the W6 warning class". AppInspect still emits W6 because the cron values are unchanged. The doc value for Phase 1.3 triage is real; the closure claim was wrong.
