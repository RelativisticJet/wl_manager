# Operational Runbooks

Step-by-step recovery procedures, rollback paths, and disaster-recovery runbooks for the Whitelist Manager Splunk app. Pair this with the SECURITY.md disclosure policy and the dashboard-driven monitoring described in INSTALLATION.md.

This file is the canonical public-facing source. The CLAUDE.md content stays gitignored as a personal-overlay file; THIS file is authoritative.

Plan-reference: Phase 0.5 migration (PUBLIC_RELEASE_PLAN.md, DECISION_LOG D11).

---

## Rollback Path (document BEFORE deploy)


For any NEW mechanism added (security control, scheduled job, scripted input, KV collection, REST action, FIM watcher), the rollback procedure MUST be documented in this file before the deploy that adds it. "We will figure it out when it breaks" = the on-call person at 3 AM does not know what to do.

**Required fields per mechanism**:

- **Mechanism name + build added**
- **How to disable temporarily** (one command or file change — should be reversible without restart if possible)
- **How to remove entirely** (commands + files to delete + KV collections to drop + audit-trail cleanup if any)
- **Side effects of disabling** (what stops working, what alerts go silent, whether security posture degrades)
- **Recovery if rollback corrupts state** (pointer to recovery script or manual remediation steps)

**Existing rollback procedures** (already documented under "Operational Procedures"):

- Emergency lockdown release → `scripts/emergency_unlock.sh`
- Cooldown counter recovery → `scripts/reset_cooldowns.sh`
- GUID rotation / DR restore → 5-step runbook under "Disaster Recovery"
- FIM deploy window → `scripts/fim_deploy_window.sh` + REST API

**Backfilled rollback procedures** (added 2026-04-23):

### CSV hash registry (`.csv_expected_hashes.json`)

- **Build added**: 557 (CSV integrity monitoring).
- **Temp disable (stop detection)**: CSV hash checking happens inside
  `bin/wl_fim_watch.py`. There is no per-feature flag. To stop the
  check, either disable the watcher (see next entry) or rename the
  registry (`mv .csv_expected_hashes.json .csv_expected_hashes.json.off`)
  — the watcher then treats every managed CSV as unregistered and fires
  `fim_csv_unregistered` alerts, which is NOT a quiet disable. Only
  useful as a debugging step while isolating a hash problem.
- **Full removal**: delete `lookups/_versions/.csv_expected_hashes.json`
  AND disable the watcher. If you only delete the registry, the watcher
  auto-bootstraps a new one on its next cycle (see `fim_csv_auto_bootstrap`
  in the audit trail) — so to KEEP the registry removed, the watcher
  MUST be stopped first.
- **Side effects of disabling**: CSV tampering via SPL `| outputlookup`,
  direct filesystem writes, and REST lookup edits becomes invisible to
  us. The handler's own save_csv path continues writing to the
  (deleted) registry on each save, which silently recreates a partial
  registry unless you also disable saves. Defense against "bootstrap
  laundering" disappears.
- **Recovery if rollback corrupts state**: run
  `bootstrap_csv_hashes` (superadmin-only REST action, rate-limit
  exempt) to rebuild the registry from the current CSVs and resume
  detection. Expect one `bootstrap_csv_hash_changed` HIGH event per
  CSV whose hash differs from the last known-good registry — this is
  the diff-aware audit trail CLAUDE mentions elsewhere and is exactly
  what the scheduled laundering-correlation search watches for.

### CSV integrity watcher (`bin/wl_fim_watch.py`)

- **Build added**: 557 (CSV integrity monitoring).
- **Temp disable**: add a `local/inputs.conf` overlay:
  ```ini
  [script://./bin/wl_fim_watch.py]
  disabled = true
  ```
  and restart Splunk. `default/inputs.conf` stays untouched so the
  next app upgrade doesn't silently re-enable the watcher. Takes
  effect within ~30 seconds of restart.
- **Full removal**: remove the stanza from `default/inputs.conf`
  entirely and delete `bin/wl_fim_watch.py`. Also remove the
  `wl_fim_watcher_heartbeat_monitor` saved search in
  `savedsearches.conf` — otherwise it will fire within 7 minutes
  (missing-heartbeat alert) and keep firing forever.
- **Side effects of disabling**: near-real-time (~2 s) CSV change
  detection is gone. `bin/wl_fim.py` (baseline FIM on code files,
  every 15 s) is a SEPARATE scripted input and continues running —
  so `default/*.conf`, `bin/*.py`, and sentinel-file monitoring are
  unaffected. The only thing lost is CSV-mutation detection + the
  laundering-correlation signal.
- **Recovery if rollback corrupts state**: set `disabled = false`,
  restart Splunk. On the first cycle the watcher re-reads
  `rule_csv_map.csv`, re-loads the expected-hash registry, and
  resumes detection. If the registry was also deleted, see the
  "CSV hash registry" entry above for the bootstrap step.

### KV `wl_cooldowns` collection

- **Build added**: 553 (KV-store cooldowns).
- **Temp disable**: there is no runtime toggle — the handler calls
  `_check_admin_daily_limit()` on every admin write, which reads the
  collection unconditionally. To temporarily stop rate-limiting,
  increase the limit values to a very large number via the Control
  Panel → Admin Settings tab (superadmin-only); the collection keeps
  counting but no limit will be hit.
- **Full drop-and-rebuild** (distinct from `reset_cooldowns.sh`, which
  clears the single `state` record while preserving the collection):
  ```bash
  curl -sk -u admin:<pw> -X DELETE \
    "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns"
  MSYS_NO_PATHCONV=1 docker exec -u splunk wl_manager_test \
    /opt/splunk/bin/splunk restart
  ```
  On the next admin write the handler re-bootstraps a fresh record
  under a new HMAC signature. No audit record is written by the DELETE
  itself — append a line to `_recovery_log.jsonl` manually if this is
  being done as part of incident response.
- **Side effects of disabling** (via "raise limits" approach): admins
  can exceed what super-admin configured limits expected. Rate-limit
  audit events still fire but with `current >= maximum` effectively
  meaningless. The defense against a compromised admin account burning
  through destructive actions in bulk is reduced.
- **Recovery if rollback corrupts state**: `./scripts/reset_cooldowns.sh`
  recreates the tamper flag + init marker cleanly and restarts
  Splunk to flush the in-process HMAC key cache. Use this BEFORE
  attempting anything heavier — it handles every observed corruption
  mode we have seen.

### KV `wl_fim_baseline` collection

- **Build added**: 554 (FIM dual-store).
- **Temp disable**: no runtime toggle. `bin/wl_fim.py` always reads
  both the filesystem baseline and the KV copy and alerts on
  divergence. To suppress the KV-side check specifically, delete the
  collection (next point); the file baseline continues to work on its
  own, but you lose the cross-validation that catches the "attacker
  deletes `.fim_baseline.json` to hide prior mutations" scenario.
- **Full drop-and-rebuild without false-positive flood**:
  ```bash
  # 1. Delete BOTH copies so next FIM run rebuilds from the current
  #    filesystem state in one shot. If you only delete one, the next
  #    run fires a `fim_baseline_kv_fs_divergence` alert.
  curl -sk -u admin:<pw> -X DELETE \
    "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline"
  MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    rm -f /opt/splunk/etc/apps/wl_manager/lookups/_versions/.fim_baseline.json
  # 2. Wait up to 15 s for the next wl_fim.py cycle. You should see
  #    a single `fim_baseline_initialized` audit event, NOT a storm of
  #    per-file tamper alerts — the stateful alert dedup in the same
  #    run path suppresses the transient "rebuilt" notice to one event.
  ```
- **Side effects of disabling** (via KV-only delete without deleting
  the file copy): you lose defense against single-sided tampering.
  An attacker who can edit files but not KV — or vice versa — can no
  longer be caught via the cross-validation alert. Keeping only the
  file copy reverts us to the pre-hardening-round-3 posture, which
  was explicitly the attack we built the KV copy to catch.
- **Recovery if rollback corrupts state**: if the rebuild somehow
  produces a baseline you don't trust, delete both stores again and
  let the next FIM cycle re-seed. The baseline is derived from the
  CURRENT filesystem state, so rebuild is idempotent as long as the
  filesystem itself is clean.

### Stateful FIM alert dedup (`.fim_alert_state.json`)

- **Build added**: 560 (stateful alert reduction).
- **Temp reset (fire all currently-present alerts as if new)**:
  ```bash
  MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    rm -f /opt/splunk/etc/apps/wl_manager/lookups/_versions/.fim_alert_state.json
  ```
  The next `bin/wl_fim.py` cycle (within 15 s) re-evaluates every
  condition in `STATEFUL_ALERT_ACTIONS` (`fim_baseline_tampered`,
  `fim_baseline_hmac_mismatch`, `fim_csv_hash_registry_tampered`, and
  8 others in `bin/wl_fim.py`) and re-emits an event for each one
  that is currently active. Safe at any time; cost is a temporary
  burst of alerts you have presumably already seen.
- **Full removal**: there is nothing to "remove" — the file is purely
  a dedup cache. Deleting it is the rollback. If you want to stop the
  dedup behavior entirely (and have every cycle re-fire), empty the
  `STATEFUL_ALERT_ACTIONS` frozenset in `bin/wl_fim.py` and redeploy.
  Not recommended — the reason the dedup exists is that the bell and
  audit index were being buried under repetitive alerts from one
  persistent condition.
- **Side effects of resetting**: the stateful-reminder interval
  (`STATEFUL_REMIND_INTERVAL_SECS = 3600`) effectively resets to zero
  for every currently-active alert, so users get a second notification
  for conditions they have already acknowledged. Short-lived.
- **Recovery if rollback corrupts state**: state file is a simple JSON
  map, lazily loaded. Corruption is self-healing — `_load_alert_state`
  catches `JSONDecodeError` and returns an empty dict, and the next
  `_save_alert_state` overwrites it atomically.

### Notification bell + UI-watch insider-threat features

- **Build added**: 573 (insider-threat hardening).
- **Components**: (1) the bell + dropdown in `appserver/static/notifications.js`
  loaded by every dashboard, (2) the `report_presence` / `get_presence`
  actions + `bin/wl_presence.py`, (3) lockdown-tagging of notifications
  inside the handler, (4) the UI-watch badge that flags concurrent
  editors.
- **Temp disable — bell only**: remove `notifications.js` from the
  `script="..."` attribute of every `default/data/ui/views/*.xml` (or
  apply the change in `local/data/ui/views/` overlays). The bell
  disappears on the next dashboard load; server-side notification
  generation in the handler continues unchanged (audit trail is
  preserved). Hit every XML — `whitelist_manager.xml`, `control_panel.xml`,
  and `audit.xml` currently reference it.
- **Temp disable — UI-watch only**: the `report_presence` action is
  called from `whitelist_manager.js` every few seconds. Disable via
  a `local/restmap.conf` overlay:
  ```ini
  [script:wl_manager]
  # (keep existing directives, then drop report_presence from the allow-list)
  ```
  OR simpler, remove the `report_presence` dispatch entry from
  `wl_handler.py :: GET_ACTIONS` locally. The frontend calls will all
  404, presence-based UI-watch goes quiet, nothing else breaks.
- **Full removal**: delete `appserver/static/notifications.js`, remove
  its references from every `data/ui/views/*.xml`, remove
  `bin/wl_presence.py` + its three dispatch entries in `wl_handler.py`
  (`report_presence`, `get_presence`, `cleanup_presence`), and remove
  the `.presence.json` file from `lookups/_versions/`.
- **Side effects of disabling**: admins lose real-time awareness of
  new approval requests, lockdown activations, and concurrent-editor
  warnings. Audit events still land in `wl_audit` and the dashboards
  still render — the loss is purely human-attention velocity, not
  forensic coverage. Insider-threat attribution via `_audit` index
  (if enabled per INSTALLATION.md) is independent of this UI and
  continues to work.
- **Recovery if rollback corrupts state**: nothing persistent that
  isn't recreated on the next poll. Re-add the `<script>` attribute
  and hard-refresh; the bell reappears. If `.presence.json` is
  corrupt, delete it — `wl_presence.py` recreates it on the next
  `report_presence` call.

**Trigger to update this list**: any commit that adds a new file in `bin/`, a new section in `restmap.conf`, a new `[<name>]` stanza in `inputs.conf`, or a new KV collection in `collections.conf`.


---

## Operational Procedures


### Emergency Unlock Recovery (`scripts/emergency_unlock.sh`)

**Use when**: Both superadmin accounts are compromised or unavailable, and the app is locked down with no way to deactivate via the UI.

```bash
./scripts/emergency_unlock.sh [container_name]   # default: wl_manager_test
```

The script **requires** a reason (incident ticket or free-text) and writes an append-only audit record to `lookups/_versions/_recovery_log.jsonl` **before** deleting `_emergency_lockdown.json`. That log is tailed by the `wl_audit_recovery` scripted input into `index=wl_audit` and surfaces in the Audit dashboard "Out-of-Band Recovery Actions" panel. Still document the use in your incident response log and consider rotating superadmin credentials.

### Cooldown Counter Recovery (`scripts/reset_cooldowns.sh`)

**Use when**: The rate-limit cooldown state (`wl_cooldowns` KV record or on-disk tamper flag) is broken. Symptoms: `Security lockdown: rate limit counter has been tampered with` error when changing admin limits or purging trash. The tamper flag persists across process restarts — only this script can clear it.

```bash
./scripts/reset_cooldowns.sh [container_name]   # default: wl_manager_test
```

Clears the tamper flag + init marker + legacy cooldown file, deletes the KV store `wl_cooldowns/state` record, appends an audit record to `_recovery_log.jsonl`, and restarts Splunk so the runtime HMAC key cache is dropped. The handler re-bootstraps a fresh record on the next request.

### Disaster Recovery — GUID Rotation / Backup Restore / Container Clone

**Context**: since the hardening rounds, the cooldown HMAC key is derived from the Splunk server GUID at runtime (introduced in build 552, 2026-04-12). Any event that changes the GUID — DR restore from backup on a new host, container clone, host reinstall, rebuild from image — invalidates every cooldown record signed by the old key. The same applies to the FIM baseline and the deploy-window file. Cached runtime keys have a 1-hour TTL but that window is too long for post-DR operation.

**Mandatory first step after ANY GUID-changing event:**

```bash
./scripts/reset_cooldowns.sh <container_name>
```

This is **step 1** of every DR runbook — not an "optional follow-up". Running it later means a 1-hour window where every admin limit change and purge operation returns "Security lockdown". Run it first, confirm the recovery-log entry appears in the Audit dashboard, THEN proceed with any other recovery work.

**Full DR runbook order:**

1. **Immediately after any GUID-changing event:**
   - `./scripts/reset_cooldowns.sh <container>` — clears all cooldown state, deletes the KV record (which was signed with the OLD key), deletes the tamper flag and init marker, restarts Splunk, and appends a recovery-log entry. The restart flushes every worker's key cache so the NEW key is derived on the next request.
   - Verify the "Out-of-Band Recovery Actions" panel in the Audit dashboard shows the `reset_cooldowns` event with the correct host_user and reason.

2. **Rebuild the FIM baseline:**
   - `rm /opt/splunk/etc/apps/wl_manager/lookups/_versions/.fim_baseline.json`
   - Also delete the `wl_fim_baseline` KV collection record (it was signed with the OLD key too).
   - The next FIM scripted-input run (within 60 seconds) establishes a fresh dual-store baseline and emits `fim_baseline_initialized`.

3. **Optional — if you wanted to preserve cooldown counters across the GUID rotation:**
   - `bin/wl_migrate_cooldowns.py` supports re-signing records under a new key in theory, but it cannot help here because the GUID rotation changes the HMAC key, not the schema version. The right call is still "reset cleanly via `reset_cooldowns.sh`". Migration is only for schema-version bumps on the SAME instance.

4. **Rebuild the CSV expected-hash registry:**
   - Call `bootstrap_csv_hashes` via REST API (superadmin required). The old registry was signed with the OLD GUID-derived key and will fail HMAC verification.
   - Alternatively, delete `.csv_expected_hashes.json` and let the watcher auto-bootstrap on its next cycle.

5. **Verify operations resume:**
   - Log in as superadmin, change any admin limit to a new value, confirm no "Security lockdown" error.
   - Trigger a file modification (e.g., touch `default/app.conf` in the test env) and confirm FIM produces a new event, proving the baseline was rebuilt under the new key.

**Never**: hardcode a GUID or copy `etc/instance.cfg` between instances to "preserve" cooldown state. The HMAC is a security boundary, not a data migration hook. Reset cleanly and re-bootstrap.

### FIM Deploy Window

**Context**: Every deploy touches watched files (`default/*.conf`, `bin/*.py`) and generates HIGH-severity FIM alerts. A deploy window downgrades code-file alerts to INFO-severity `fim_file_modified_during_deploy` events so they are still logged but don't wake anyone up. **Sentinel files** (cooldown markers, lockdown state, `instance.cfg`) remain at HIGH severity even during a deploy window — legitimate deploys never touch them.

**Two interfaces** (use whichever fits your workflow):

```bash
# Shell script (manual / emergency use — requires docker exec)
./scripts/fim_deploy_window.sh start --duration 20 --reason "deploy build 555"
./scripts/fim_deploy_window.sh end
./scripts/fim_deploy_window.sh status

# REST API (CI/CD pipelines — requires wl_superadmin role, no shell access)
# NOTE: The built-in 'admin' role is NOT sufficient — the REST actions
# require the 'wl_superadmin' role (SUPERADMIN_ROLES). CI/CD service
# accounts need this role explicitly granted. The shell script has no
# RBAC and works with any user that has docker exec access.
curl -sk -u svc_deploy:token -X POST https://localhost:8089/custom/wl_manager \
  -d '{"action":"open_deploy_window","duration_minutes":20,"reason":"CI deploy build 557"}'
curl -sk -u svc_deploy:token -X POST https://localhost:8089/custom/wl_manager \
  -d '{"action":"close_deploy_window"}'
curl -sk -u svc_deploy:token https://localhost:8089/custom/wl_manager?action=get_deploy_window_status
```

**Security properties**:

- The window file (`lookups/_versions/_fim_deploy_window.json`) is HMAC-signed with the runtime key. An attacker cannot forge a permanent suppression window from outside the container.
- The FIM script enforces a hard 1-hour cap regardless of what the file claims — a forged file that says "expires in 10 years" is rejected at read time.
- Both `start` and `end` append records to `_recovery_log.jsonl`, so opening and closing windows are visible in the Audit dashboard.
- Alerts during an active window are tagged with `deploy_window: {started_by, reason, expires_at}` so correlating legitimate changes with the operator is trivial.
- Sentinel-file mutations (cooldown markers, lockdown state, `instance.cfg`) are **never** downgraded — they stay at HIGH severity regardless of deploy window state.
- Deploy window actions are lockdown-exempt (you can open/close windows even during emergency lockdown, so hotfixes can be deployed).
- Every REST-initiated window open/close emits a HIGH-severity event to `wl_audit` (in addition to the recovery log), so SOC dashboards surface abnormal window-opening patterns.
- Sentinel events that fire during a deploy window carry `sentinel_alert: true` so dashboards can distinguish them from legitimately-downgraded code-file alerts.

### File Integrity Monitor (`bin/wl_fim.py`)

A Splunk scripted input runs every 60 seconds and hashes a curated set of critical files (handler source code, `default/*.conf`, cooldown markers, lockdown state, `instance.cfg`). An unexpected change emits a JSON event indexed to `wl_audit sourcetype=wl_fim` and visible in the Audit dashboard "File Integrity Monitor Alerts" panel. The baseline file (`lookups/_versions/.fim_baseline.json`) is itself HMAC-signed with a GUID-derived key so an attacker cannot silently rewrite the baseline to match tampered state.

**When an alert fires, correlate**:

- Does it coincide with a deploy? (Expected — the baseline auto-updates, you only see ONE alert per file per deploy.)
- Does it coincide with a recovery script run? (Check `action=reset_cooldowns` or `action=emergency_unlock` events in the recovery log panel.)
- If neither — investigate as a potential compromise. Compare `old_hash` and `new_hash` in the FIM event; if it's a `bin/*.py` file, take an image of the container for forensics before any remediation.

### CSV Integrity Monitoring (`bin/wl_fim_watch.py`)

A persistent Splunk scripted input (`interval = 0`) that monitors all managed CSV files for unauthorized modifications. Detects SPL `| outputlookup` bypass, direct filesystem writes, and REST API lookup edits — all of which bypass the handler's security controls (approval gates, rate limits, audit trail).

**Architecture (5-layer defense):**
1. Handler writes expected hashes to `.csv_expected_hashes.json` on every save
2. Registry is HMAC-signed with GUID-derived key (attacker can't forge)
3. Stat-based watcher detects file changes in ~2 seconds
4. Full hash sweep every 15 seconds catches mtime-preserving attacks
5. Fail-closed on HMAC failure (all CSVs treated as unregistered)

**Detection timing:** Regular modifications ~2s, mtime-preserving attacks ~15s, hash registry tamper = immediate fail-closed.

**Auto-bootstrap:** On first run, if no registry file exists, the watcher auto-creates one by hashing all managed CSVs. This prevents a storm of `fim_csv_unregistered` alerts on fresh installs. The `fim_csv_auto_bootstrap` event appears in `index=wl_audit sourcetype=wl_fim` (watcher stdout), NOT in the handler's audit trail (the watcher has no session key for `_index_audit()`). Use `index=wl_audit source_script=wl_fim_watch action=fim_csv_auto_bootstrap` to find it.

**Mapping refresh:** The watcher re-reads `rule_csv_map.csv` every 15 seconds and immediately on any change to the mapping file (sentinel CSV). New CSVs are picked up within seconds of creation.

**Laundering correlation:** A scheduled search (`wl_csv_bootstrap_laundering_correlation`) runs every 5 minutes and alerts at severity 5 (CRITICAL) if a `bootstrap_csv_hash_changed` event for a CSV appears within 5 minutes of a `fim_csv_external_modification` for the same CSV. This detects the scenario where an attacker modifies a CSV and then immediately re-bootstraps to suppress detection alerts.

### Bootstrap CSV Hashes (`bootstrap_csv_hashes` action)

**Use when**: Fresh install, after disaster recovery, or when the expected-hash registry is corrupt/missing.

```bash
# Via REST API (requires wl_superadmin role)
curl -sk -u superadmin1:token -X POST \
  "https://localhost:8089/services/custom/wl_manager" \
  -d '{"action":"bootstrap_csv_hashes"}'
```

**Properties:**
- **SUPERADMIN-only**, lockdown-exempt, rate-limit-exempt
- **Diff-aware**: compares new hashes against the previous registry and emits individual `bootstrap_csv_hash_changed` HIGH events for each CSV whose hash differs. This makes "bootstrap laundering" attacks visible — if an attacker modifies a CSV then immediately bootstraps, the per-CSV change events still appear in the audit trail.
- Returns `hashed_count`, `missing_count`, `changed_count`, and lists of changed/new/missing CSV files
- Emits `bootstrap_csv_hashes` summary audit event and per-CSV `bootstrap_csv_hash_changed` events

**After GUID rotation / DR restore:** Run `bootstrap_csv_hashes` after `reset_cooldowns.sh` and FIM baseline rebuild to re-sign the CSV hash registry with the new GUID-derived key.

### Dev Environment — Install Splunk Developer License

**Use when**: a local dev/test container's 60-day Splunk trial has expired (or you want to run E2E tests past the 60-day mark) and you have a personal Splunk Developer license from dev.splunk.com.

**The license is private to your dev.splunk.com account. Never commit it to the repo.** Keep it on your host machine (e.g. `~/Desktop` or a secrets directory) and copy it into the container only at install time. CI does not need a license — every workflow run spins up a fresh `splunk/splunk:9.3.1` container which gets a fresh 60-day Enterprise trial that lasts longer than any CI job.

```bash
# 1. Copy the license into the container (NOT into the repo workspace)
docker cp ~/Desktop/Splunk.License wl_manager_test:/tmp/Splunk.License

# 2. Install (the CLI auto-files it under /opt/splunk/etc/licenses/enterprise/)
docker exec -u splunk wl_manager_test \
  /opt/splunk/bin/splunk add licenses /tmp/Splunk.License \
  -auth admin:Chang3d!

# 3. Restart (CLAUDE.md convention: stop + start, no -auth; the `!` in the
#    password is a bash history-expansion trigger).
docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk stop
docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk start --answer-yes

# 4. Verify (look for type=enterprise + the expected quota)
docker exec -u splunk wl_manager_test \
  curl -sk -u admin:Chang3d! \
  "https://localhost:8089/services/licenser/licenses?output_mode=json" \
  | python3 -m json.tool | grep -E '"label"|"type"|"quota"'

# 5. Clean up the temp copy in /tmp (the install already filed it under
#    /opt/splunk/etc/licenses/enterprise/). docker cp created /tmp file as
#    root, so the cleanup needs -u 0.
docker exec -u 0 wl_manager_test rm -f /tmp/Splunk.License
```

**Caveats:**

- **License is keyed to the Splunk GUID at install time.** Rebuilding the container (`docker rm` + recreate) generates a new GUID and the license must be re-installed. The cooldown / FIM / CSV-hash recovery procedures earlier in this section also need to run after a rebuild — license install is one more step in that DR runbook.
- **Splunk Free + Splunk Forwarder licenses stay listed alongside the Developer license** after install — that is normal. Enterprise takes precedence; Free is the fallback if Enterprise expires or its daily quota is breached.
- **Quota**: a Personal Dev license is typically 10 GB/day. The full E2E suite consumes a few hundred MB/day at most, so quota is not a real constraint for a single-developer dev container.
- **Expiry**: Dev licenses ship with a built-in expiry (usually 6-12 months from issue). Watch the `expiration_time` field in the verify command above; rotate before it lapses.

**Smoke-test after install:** run `node tests/e2e/test_ratelimit_per_worker.cjs` (or any representative E2E test). A green run confirms no licensing-mode regression (custom roles still work, KV access still works, scheduled inputs still fire).

**When to re-install:**

- Container rebuilt from image (new GUID).
- The Splunk Enterprise trial expired AND you want to keep using Enterprise-only features (custom roles, scheduled searches, distributed search, etc.) locally.
- License file rotated (rare — you would get a new file from dev.splunk.com when the current one expires).

