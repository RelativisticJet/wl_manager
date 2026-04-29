# Backup and Restore — Whitelist Manager

This is the consolidated runbook for backing up and restoring the
Whitelist Manager app. It is the SSOT for "how do I prepare for a
host failure / DR exercise / migration to a new Splunk instance"
and supersedes scattered guidance previously in CLAUDE.md.

Origin: round 7 C2 (2026-04-29). The Disaster Recovery section of
CLAUDE.md remains the authority for recovery from a GUID rotation
or container clone — this doc complements it by covering the
*planned* backup side.

## What to back up — three buckets

The app's persistent state splits into three categories with
different backup strategies:

| Bucket | What | Backup strategy |
|--------|------|-----------------|
| **Data layer** (this doc) | Detection-rule CSVs, rule↔CSV mapping, version snapshots | `scripts/backup_data.sh` — produces a single `.tar.gz` per run |
| **Audit index** | `index=wl_audit` events | Splunk's standard index backup procedure (see your Splunk admin runbook); not handled by this app |
| **HMAC-bound state** | Cooldowns, FIM baselines, hash registry, lockdown, deploy windows, presence | **Do NOT back up.** These files / KV records are signed with a key derived from the Splunk server GUID; restoring them on a different host fails HMAC verification. They are *rebuilt cleanly* via the post-restore steps below. |

This split is deliberate. Backing up HMAC-bound state to a different
GUID instance is a foot-gun: the restored files would be silently
rejected (the FIM watcher would treat every CSV as unregistered, the
cooldown counters would refuse to initialize, etc.) and the only
recovery is exactly the same "wipe and rebuild" steps you would have
run in the first place. By excluding them from the backup we make
the failure mode obvious instead of silent.

## When to back up

- **Before every release** that includes data-shape changes (column
  rename / add / remove, mapping schema bumps)
- **Before any disaster-recovery exercise** (so you can roll back if
  the test runbook itself is broken)
- **Daily / weekly via cron** depending on data churn — typical
  100-analyst SOC team's CSVs change a few hundred rows/day,
  archive size <50 MB/year compressed
- **Never** during an active deploy window or migration — wait until
  the deploy completes and the FIM baseline rebuild settles

## Backup procedure

### One-shot manual backup

```bash
bash scripts/backup_data.sh                      # default: container=wl_manager_test, output=./backups
bash scripts/backup_data.sh wl_prod /var/backups/wl  # customize
```

Outputs three files under the chosen output directory:

- `wl_manager_data_<timestamp>.tar.gz` — the archive
- `wl_manager_data_<timestamp>.tar.gz.sha256` — checksum
- `wl_manager_data_<timestamp>.tar.gz.manifest.json` — metadata
  (build number, csv count, scope, restore-runbook pointer)

### Verify the backup roundtrips

Before relying on a fresh backup as your DR fallback, run the
smoke test against a live container:

```bash
bash scripts/test_backup_restore.sh             # default container
bash scripts/test_backup_restore.sh wl_manager_test
```

The smoke test:

1. Inventories every `DR*.csv` + `rule_csv_map.csv` in the live app
2. Hashes each file
3. Runs `backup_data.sh`
4. Verifies the archive checksum
5. Extracts the archive and re-hashes every file
6. Asserts every live file is in the archive with byte-identical
   content

Exit code `0` = backup is trustworthy. Anything non-zero means
investigate before relying on this backup for DR.

## Restore procedure

This is the planned-restore path (target host already has the
wl_manager app installed and Splunk running). For unplanned
recovery from a corrupted state, follow the DR runbook in
`CLAUDE.md` "Disaster Recovery — GUID Rotation / Backup Restore /
Container Clone" first.

### Step 1 — preconditions

- Target Splunk is running (`docker ps | grep wl_manager_test`)
- The wl_manager app is installed at
  `/opt/splunk/etc/apps/wl_manager`
- You have the backup `.tar.gz` AND its `.sha256` file
- You have superadmin credentials on the target Splunk

### Step 2 — verify the backup before extracting

```bash
sha256sum -c wl_manager_data_<timestamp>.tar.gz.sha256
```

Stop here if the checksum fails. A corrupt archive will silently
restore truncated CSVs and you will not notice until an analyst
loads a dashboard with missing rows.

### Step 3 — drop the HMAC-bound state on the target

This is the prerequisite that makes restore work. The FIM
baseline + CSV expected-hash registry on the TARGET were signed
with the TARGET's GUID; once we restore CSVs from the backup,
their hashes will not match either store, so we need to clear
both stores BEFORE restoring data and let them rebuild after.

```bash
# Clear cooldown HMAC state (also handles the KV record).
bash scripts/reset_cooldowns.sh wl_manager_test

# Drop the FIM baseline so it auto-rebuilds against the restored data.
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    rm -f /opt/splunk/etc/apps/wl_manager/lookups/_versions/.fim_baseline.json
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    sh -c 'curl -sk -u admin:Chang3d -X DELETE "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_fim_baseline"' || true

# Drop the CSV expected-hash registry; we will re-bootstrap after restore.
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    rm -f /opt/splunk/etc/apps/wl_manager/lookups/_versions/.csv_expected_hashes.json
```

### Step 4 — restore the data layer

```bash
# Copy the archive into the container.
MSYS_NO_PATHCONV=1 docker cp wl_manager_data_<timestamp>.tar.gz \
    wl_manager_test:/tmp/wl_restore.tar.gz

# Extract over the live lookups directory. Note: the archive's
# top-level entries are the lookup files themselves (no app
# wrapper), so -C points at the lookups dir directly.
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    tar -xzf /tmp/wl_restore.tar.gz \
    -C /opt/splunk/etc/apps/wl_manager/lookups

# Clean up.
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    rm /tmp/wl_restore.tar.gz

# Reset ownership (matches what `docker cp` clobbers).
MSYS_NO_PATHCONV=1 docker exec -u 0 wl_manager_test \
    chown -R splunk:splunk /opt/splunk/etc/apps/wl_manager/lookups
```

### Step 5 — re-bootstrap the integrity layer

After restore, the FIM watcher sees CSVs whose hashes are not
recorded anywhere. Bootstrap the registry against the restored
state:

```bash
# Via the superadmin REST action (preferred — produces audit trail).
curl -sk -u superadmin1:<password> -X POST \
    "https://localhost:8089/services/custom/wl_manager" \
    -d '{"action":"bootstrap_csv_hashes"}'
```

The watcher's next 15-second cycle will rebuild the FIM baseline
automatically.

### Step 6 — verify

- Open a CSV in the dashboard and confirm the rows match what was
  in the source.
- Check `index=wl_audit action=bootstrap_csv_hashes` for the
  superadmin's bootstrap event.
- Check `index=wl_audit action=fim_baseline_initialized` to confirm
  the watcher rebuilt cleanly.
- Run a no-op save on one CSV and confirm the audit event appears.

If any of these fail, the restore is suspect — do NOT advertise the
target Splunk as recovered.

## What is NOT covered by this runbook

- **App code restore** — install the .spl from GitHub Releases.
  The .spl is the SSOT for code; backing it up alongside the data
  is redundant.
- **`wl_audit` index restore** — Splunk's index backup procedure.
  If your retention SLA requires preserving audit events across DR,
  set up frozen-bucket archival to S3 / Azure / NAS via Splunk's
  `coldToFrozenScript` mechanism.
- **Per-instance configuration** in `local/` — these are usually
  the customer's own overlays, not packaged with the app. Restore
  them via your config-management tooling (Ansible, Salt, etc.).
- **GUID-bound recovery** (host loss / container clone) — see the
  DR runbook in `CLAUDE.md`. The procedure here assumes the target
  Splunk is functional; the DR runbook covers the case where it
  is not.
