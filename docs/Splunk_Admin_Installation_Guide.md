# Whitelist Manager — Splunk Admin Installation Guide

This is the **Day-1 operational playbook** for a Splunk administrator
installing the Whitelist Manager app. It walks through the pre-flight
checks, install, post-install verification, and uninstall procedures.

It is intentionally complementary to (not a duplicate of) three
authoritative companion docs:

- **`INSTALLATION.md`** (repo root) — capability trade-off matrix:
  which Splunk capabilities (`list_server`, `list_users`, `_audit`)
  the app needs, probe endpoints to test them, and how to set up
  fallbacks. Read this BEFORE Step 9 below.
- **`docs/RUNBOOKS.md`** — recovery procedures: Emergency Lockdown
  release, cooldown counter recovery, FIM deploy window, GUID
  rotation / DR.
- **`SECURITY.md`** (repo root) — disclosure policy + scope.

When the same fact lives in code or one of those docs, this guide
references the source rather than copying — copies drift.

---

## BEFORE Installation (Pre-flight Checklist)

### 1. Verify Splunk version compatibility

The app's minimum supported Splunk Enterprise version is declared in
`app.manifest` under `platformRequirements.splunk.Enterprise`:

```bash
grep -A1 platformRequirements app.manifest
```

Confirm your Splunk instance meets or exceeds that version:

```bash
$SPLUNK_HOME/bin/splunk version
```

The CI matrix tests against the version pinned in `docker-compose.yml`
(see `image:` line); earlier 9.x versions usually work but are not
covered by the test matrix.

### 2. Verify Python 3 is enabled

The app declares `python.version = python3` and `python.required = 3.13`
in `default/restmap.conf` and `default/inputs.conf`. Splunk 9.3+ ships
Python 3 by default, but verify the system-level setting:

```bash
$SPLUNK_HOME/bin/splunk btool server list --debug | grep python.version
```

If the output shows `python.version = python2` at the system level,
update `server.conf` to allow Python 3:

```ini
[general]
python.version = python3
```

### 3. Check for naming conflicts

The app creates several Splunk objects. Confirm none collide with
existing objects on your instance:

| Object | Type | Check command |
|---|---|---|
| `wl_manager` | App | `$SPLUNK_HOME/bin/splunk display app` |
| `wl_audit` | Index | `$SPLUNK_HOME/bin/splunk list index` |
| `wl_superadmin`, `wl_admin`, `wl_analyst_editor`, `wl_analyst_viewer` (modern) plus `wl_editor`, `wl_viewer` (backward-compat aliases) | Roles | `$SPLUNK_HOME/bin/splunk list role` |
| `wl_cooldowns`, `wl_fim_baseline`, `wl_presence_state`, `wl_ratelimit_state` | KV collections | `curl -sk -u <admin>:<pw> "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/config"` |
| `/services/custom/wl_manager` | REST endpoint | Should not conflict unless another app maps this exact path |

Modern role names come from `default/authorize.conf`; the legacy
aliases `wl_editor` / `wl_viewer` exist for backward compatibility
and import the new analyst-tier roles automatically.

If any of these already exist, coordinate with your security
engineering team before proceeding.

### 4. Review disk space for the wl_audit index

The app creates a dedicated `wl_audit` index. See `default/indexes.conf`
for the live settings, including the long-term archival guidance for
compliance regimes (PCI DSS, HIPAA, SOX, GDPR) at the bottom of that
file.

The index is created at the default Splunk data path:

- Hot/warm: `$SPLUNK_DB/wl_audit/db`
- Cold:     `$SPLUNK_DB/wl_audit/colddb`
- Thawed:   `$SPLUNK_DB/wl_audit/thaweddb`

For the per-CSV / per-analyst event-volume forecast (sizing input),
see `docs/AUDIT_VOLUME_FORECAST.md`.

If your organization requires custom index paths or a longer
retention policy, plan to ship a `local/indexes.conf` override after
installation (preserves your customization across app upgrades).

### 5. Review network / firewall requirements

The REST handler makes localhost-only HTTPS calls to Splunk's own
management port (`https://127.0.0.1:8089/services/...`) for audit
indexing and KV-store access. No external network access is required.

If your Splunk deployment uses a non-default management port or
custom SSL certificates, see the "Custom SSL / management port"
section under "Special Considerations" below.

### 6. Review the 4-tier RBAC model

The app ships with 4 modern roles plus 2 backward-compat aliases.
See `default/authorize.conf` for the authoritative definitions:

| Role | Tier | Capabilities |
|---|---|---|
| `wl_superadmin` | System owner | Configure admin limits, trash retention, role assignment, emergency-lockdown deactivation, recovery actions |
| `wl_admin` | Admin | Approve/reject requests, configure analyst limits, view usage, access Control Panel |
| `wl_analyst_editor` | Editor | View and edit whitelists; submit changes for approval as configured |
| `wl_analyst_viewer` | Viewer | Read-only access to whitelists and audit trail |
| `wl_editor` | Alias | Imports `wl_analyst_editor` — kept for backward compatibility |
| `wl_viewer` | Alias | Imports `wl_analyst_viewer` — kept for backward compatibility |

All roles allow searching `index=wl_audit`. The Control Panel
exposes role-gated tabs (Approval Queue, Activity, Analyst Settings,
Admin Settings, Trash) — see `docs/SECURITY_ARCHITECTURE.md` for the
gating matrix.

**Action**: Prepare the list of users who should receive each role;
you will assign them in Step 14 below.

### 7. Identify the correct app_context values

The master mapping CSV (`lookups/rule_csv_map.csv`) references CSV
files in other Splunk apps via the `app_context` column. That value
must exactly match the target app's folder name on disk.

Common examples:

| Splunk app | Typical folder name |
|---|---|
| Enterprise Security | `SplunkEnterpriseSecuritySuite` |
| ES Content Update | `DA-ESS-ContentUpdate` |
| SA-ThreatIntelligence | `SA-ThreatIntelligence` |

Verify by listing:

```bash
ls $SPLUNK_HOME/etc/apps/ | grep -i -E "security|SA-|DA-"
```

Share the exact folder names with the security engineering team so
they can populate the mapping CSV accurately. Strict-ASCII validation
applies to detection rule names, CSV filenames, and approval reasons
(see `docs/SECURITY_ARCHITECTURE.md`).

### 8. Backup

Before installing any new app:

```bash
# Snapshot the apps directory + roles + users
tar -czf /tmp/splunk_apps_backup_$(date +%Y%m%d).tar.gz $SPLUNK_HOME/etc/apps/
$SPLUNK_HOME/bin/splunk list role > /tmp/splunk_roles_backup.txt
$SPLUNK_HOME/bin/splunk list user > /tmp/splunk_users_backup.txt
```

For ongoing backups after installation (KV state + CSV lookups +
audit index), use `scripts/backup_data.sh` — see
`docs/BACKUP_AND_RESTORE.md` for the runbook.

### 9. Verify the .spl release signature (recommended)

The `.spl` release artifact is Sigstore-signed by the GitHub Actions
release workflow. Verifying the signature before install confirms
the artifact came from this repository's release pipeline and was
not swapped on the Releases page.

The canonical `cosign verify-blob` command and identity-regex live
in `docs/SBOM.md` under "Verifying a release with cosign". Skipping
this check leaves you exposed to a release-channel takeover.

---

## Try it first (Docker demo)

Before installing on production, evaluate the app in a containerized
Splunk instance:

```bash
# From the wl_manager repository root:
bash demo/demo.sh          # builds .spl, starts Splunk on http://localhost:9000
bash demo/demo.sh --stop   # tear down when done
bash demo/demo.sh --clean  # tear down + remove data volume
```

Login: `admin` / `Chang3d!` at <http://localhost:9000>. The demo
installs the app from the `.spl` package (same path as a real
install) and seeds sample detection rules with whitelist data. See
`demo/Demo_Guide.pdf` for a walkthrough.

The demo uses ports 9000 / 9089 to avoid colliding with any existing
Splunk installation on the host.

---

## DURING Installation

### Step 10. Install the .spl package

Pick the install method that matches your environment:

**Option A — Splunk Web (single instance):**

1. Log in to Splunk Web as a Splunk admin
2. Navigate to **Apps → Manage Apps → Install app from file**
3. Browse to the released `.spl` and click **Upload**
4. When prompted, allow Splunk to restart

**Option B — Splunk CLI:**

```bash
$SPLUNK_HOME/bin/splunk install app /path/to/wl_manager-<version>.spl -auth admin:<pw>
$SPLUNK_HOME/bin/splunk restart
```

Use the released filename verbatim — version is encoded in the
artifact name and matches `default/app.conf` / `app.manifest`.

**Option C — Manual extract (clustered / restricted environments):**

```bash
cd $SPLUNK_HOME/etc/apps/
tar -xzf /path/to/wl_manager-<version>.spl
chown -R splunk:splunk wl_manager/
$SPLUNK_HOME/bin/splunk restart
```

### Step 11. Verify no errors during startup

After Splunk restarts, scan the logs for app-related errors:

```bash
# App loader / handler errors
grep -i "wl_manager\|WhitelistHandler" $SPLUNK_HOME/var/log/splunk/splunkd.log | tail -20

# Python errors (scripted inputs + REST handler)
grep -i "wl_handler\|wl_fim\|wl_expiration" $SPLUNK_HOME/var/log/splunk/python_stderr.log | tail -20
```

Expected: no errors. `ImportError` / `ModuleNotFoundError` usually
indicates Python 3 is not configured (see Step 2).

### Step 12. Verify the REST endpoint

Confirm the custom REST endpoint responds:

```bash
curl -sk -u admin:<pw> "https://localhost:8089/services/custom/wl_manager?action=get_mapping&output_mode=json"
```

Expected: a JSON response containing a `mapping` array (initially
populated with sample data; empty after Step 15 once you replace
the seed). If you get HTTP 404, restart Splunk once more — handler
registration sometimes needs a second restart on a fresh install.
If 404 persists, return to Step 11 and inspect the logs.

### Step 13. Verify KV collections + scripted inputs

The app creates four KV-store collections (see
`default/collections.conf`):

```bash
curl -sk -u admin:<pw> \
  "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/config?output_mode=json" \
  | grep -E '"name"\s*:\s*"wl_'
```

Expected: `wl_cooldowns`, `wl_fim_baseline`, `wl_presence_state`,
`wl_ratelimit_state`.

The app also registers three scripted inputs (see
`default/inputs.conf`): the hourly expiration cleanup, the 15-second
File Integrity Monitor full-scan (`wl_fim.py`), and the persistent
~2-second FIM stat watcher (`wl_fim_watch.py`). Confirm they are
running:

```bash
$SPLUNK_HOME/bin/splunk list inputstatus | grep wl_
```

Then check that FIM has emitted its initial baseline event (allow
~15 seconds after startup):

```spl
index=wl_audit sourcetype=wl_fim action=fim_baseline_initialized | head 1
```

A `fim_baseline_initialized` event confirms the dual-store baseline
(filesystem + KV) is wired up.

---

## AFTER Installation (Post-install Setup)

### Step 14. Verify the wl_audit index

```bash
$SPLUNK_HOME/bin/splunk list index wl_audit
```

Or via Splunk Web: **Settings → Indexes** — find `wl_audit`. If the
index is missing, the app bundle did not load fully — return to
Step 11.

### Step 15. Assign roles to users

For each user, assign the role tier that matches their job (see
Step 6 for the 4-tier matrix):

```bash
# Editor (can edit whitelists, submit for approval)
$SPLUNK_HOME/bin/splunk edit user <username> -role wl_analyst_editor -auth admin:<pw>

# Read-only viewer
$SPLUNK_HOME/bin/splunk edit user <username> -role wl_analyst_viewer -auth admin:<pw>

# Approver
$SPLUNK_HOME/bin/splunk edit user <username> -role wl_admin -auth admin:<pw>

# System owner (system-level controls)
$SPLUNK_HOME/bin/splunk edit user <username> -role wl_superadmin -auth admin:<pw>
```

Alternatively, via Splunk Web:
**Settings → Access Controls → Users → [username] → Edit → Roles**.

If you have legacy users on the backward-compat aliases
(`wl_editor`, `wl_viewer`), they continue to work — the aliases
import the new analyst-tier roles. Migrate them on the next role
review for clarity.

### Step 16. Populate the master mapping CSV

This is the most critical post-install step. The security engineering
team will provide the mapping data; the Splunk admin may need to
verify `app_context` values resolve to real folders on disk.

**Option A — Splunk Web:**

1. **Settings → Lookups → Lookup table files**
2. Find `rule_csv_map` (App: wl_manager)
3. Click the filename to edit
4. Replace the sample data with your real detection-rule mappings

**Option B — file system:**

```bash
vi $SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv
```

Format:

```csv
rule_name,csv_file,app_context
My_Detection_Rule,my_whitelist.csv,SplunkEnterpriseSecuritySuite
Another_Rule,another_whitelist.csv,DA-ESS-ContentUpdate
```

`app_context` must exactly match the target app's folder name in
`$SPLUNK_HOME/etc/apps/`. Strict-ASCII validation rejects non-ASCII
detection rule names and CSV filenames at the API boundary.

### Step 17. Verify CSV file permissions

The Splunk process (running as the `splunk` user) needs **read and
write** access to every CSV referenced in the mapping. Check:

```bash
# List the referenced CSVs and their permissions
awk -F',' 'NR>1 {print $3"/lookups/"$2}' \
  $SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv \
  | while read f; do
      ls -la "$SPLUNK_HOME/etc/apps/$f" 2>/dev/null || echo "NOT FOUND: $f"
    done
```

If any rows show `NOT FOUND`, the `app_context` or `csv_file`
columns are wrong — fix the mapping and re-test.

Fix permissions if needed:

```bash
chown splunk:splunk $SPLUNK_HOME/etc/apps/<app_context>/lookups/<csv_file>
chmod 644 $SPLUNK_HOME/etc/apps/<app_context>/lookups/<csv_file>
```

### Step 18. Bootstrap the CSV expected-hash registry

The CSV integrity monitor (`bin/wl_fim_watch.py`) auto-bootstraps a
hash registry on first run for any CSV referenced in
`rule_csv_map.csv`. Confirm it ran:

```spl
index=wl_audit sourcetype=wl_fim action=fim_csv_auto_bootstrap | head 5
```

If you populated the mapping after install and don't see the
auto-bootstrap events, force a registry rebuild via the
`bootstrap_csv_hashes` REST action (requires `wl_superadmin`,
exempt from rate-limit and lockdown):

```bash
curl -sk -u <wl_superadmin>:<pw> -X POST \
  "https://localhost:8089/services/custom/wl_manager" \
  -d '{"action":"bootstrap_csv_hashes"}'
```

See `docs/RUNBOOKS.md` → "Bootstrap CSV Hashes" for details.

### Step 19. Run the capability probes

Three optional Splunk capabilities (`list_server`, `list_users`,
`_audit` index read) change which features run cleanly vs.
degraded. Run the three probe endpoints documented in
`INSTALLATION.md` Section 2 to see which deployment scenario your
environment matches, and configure the documented fallbacks for
any capability your site policy denies.

Summary:

```bash
curl -sk -u <wl_superadmin>:<pw> ".../services/custom/wl_manager?action=probe_server_info_access&output_mode=json"
curl -sk -u <wl_superadmin>:<pw> ".../services/custom/wl_manager?action=probe_list_users_access&output_mode=json"
curl -sk -u <wl_superadmin>:<pw> ".../services/custom/wl_manager?action=probe_audit_access&output_mode=json"
```

The probe responses include human-readable `recommendation` text.

### Step 20. End-to-end smoke test

1. Log in as a user with the `wl_analyst_editor` role
2. Open **Apps → Whitelist Manager**
3. Select a detection rule, then a CSV file
4. The table loads with the CSV contents
5. Modify a cell, type a comment, click **Save**
6. Open the **Audit** dashboard — the change appears
7. Confirm in SPL:

```spl
index=wl_audit sourcetype=wl_audit
| head 5 | reverse
| table _time analyst detection_rule csv_file action comment
```

### Step 21. Test RBAC enforcement

1. Log in as a user **without** any `wl_*` role
2. Attempt to access the Whitelist Manager dashboard
3. Expected: app is not visible, or save attempts return a
   role-denied error

If you see a permissions inconsistency (e.g., a `wl_analyst_viewer`
can save), check that the user is not inheriting an elevated role
from a built-in group, and re-read `default/authorize.conf` to
confirm the live importRoles chain.

---

## Special Considerations

### Custom SSL or management port

The handler's audit-event indexing path uses Splunk's loopback
management URI (`https://127.0.0.1:<mgmtport>`). It picks up the
running management port from Splunk's environment automatically;
no app config change is needed for a non-default port.

If your deployment uses custom SSL certificates, ensure the splunk
process trusts its own certificate chain (standard Splunk
configuration — `web.conf` `enableSplunkWebSSL`,
`server.conf` `sslVerifyServerCert`).

### Search Head Cluster (SHC) deployment

1. Place the app in the SHC deployer at
   `$SPLUNK_HOME/etc/shcluster/apps/wl_manager/`
2. Push the bundle:
   `$SPLUNK_HOME/bin/splunk apply shcluster-bundle -target <captain_uri>`
3. The `wl_audit` index must also be configured on the **indexers**
   (or forwarded to them) — search heads do not store the data.

### Indexer cluster deployment

Create the `wl_audit` index on the indexers via the cluster master:

```bash
# On the cluster master
mkdir -p $SPLUNK_HOME/etc/master-apps/wl_manager_index/default/
cp default/indexes.conf $SPLUNK_HOME/etc/master-apps/wl_manager_index/default/indexes.conf
$SPLUNK_HOME/bin/splunk apply cluster-bundle
```

The handler + scripted inputs live on the search head; only the
index definition needs to ship to the indexers.

### Long-term audit retention (compliance regimes)

`default/indexes.conf` contains commented guidance for extending
retention beyond 3 years (PCI DSS, HIPAA, SOX, GDPR). Two options
are documented inline:

- **Extend online retention** (simpler, more disk)
- **Archive frozen buckets to cold storage** (recommended past 3 years)

See the comment block at the bottom of `default/indexes.conf` for
the exact `frozenTimePeriodInSecs` / `coldToFrozenScript` syntax.

### Recovery scripts and runbooks

Out-of-band recovery — emergency lockdown release, cooldown counter
reset, FIM deploy windows, GUID rotation, disaster recovery — is
documented in **`docs/RUNBOOKS.md`**. Bookmark that file and read
it once before going live; the scripts under `scripts/` (e.g.
`emergency_unlock.sh`, `reset_cooldowns.sh`,
`fim_deploy_window.sh`) require physical access to the Splunk
host's docker / shell.

---

## Uninstallation

Remove the app:

```bash
$SPLUNK_HOME/bin/splunk remove app wl_manager -auth admin:<pw>
$SPLUNK_HOME/bin/splunk restart
```

This preserves the `wl_audit` index data. To also remove the audit
data:

```bash
$SPLUNK_HOME/bin/splunk remove index wl_audit
```

**KV collections** are removed with the app bundle. If you used
`local/collections.conf` overrides or manually exported collection
contents to preserve audit attribution after uninstall, retrieve
that data first:

```bash
# Example: export wl_cooldowns to JSON before uninstall
curl -sk -u admin:<pw> \
  "https://localhost:8089/servicesNS/nobody/wl_manager/storage/collections/data/wl_cooldowns?output_mode=json" \
  > wl_cooldowns_export.json
```

**Custom roles** (`wl_superadmin`, `wl_admin`, `wl_analyst_editor`,
`wl_analyst_viewer`, plus the `wl_editor` / `wl_viewer` aliases)
are removed with the app. Users who held these roles lose them
automatically.

**Recovery log** (`lookups/_versions/_recovery_log.jsonl`) is
removed with the app's `lookups/` directory. If your retention
policy requires preserving recovery actions after uninstall, copy
that file out first.

---

## Quick Reference Card

| Item | Value |
|---|---|
| App folder | `$SPLUNK_HOME/etc/apps/wl_manager/` |
| REST endpoint | `https://<splunk>:8089/services/custom/wl_manager` |
| Web dashboard | `https://<splunk>:8000/app/wl_manager/whitelist_manager` |
| Audit destination | `index=wl_audit` (all audit events go to this Splunk index — there is no separate log file) |
| Mapping CSV | `$SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv` |
| KV collections | `wl_cooldowns`, `wl_fim_baseline`, `wl_presence_state`, `wl_ratelimit_state` (see `default/collections.conf`) |
| Roles | 4 modern (`wl_superadmin`, `wl_admin`, `wl_analyst_editor`, `wl_analyst_viewer`) + 2 backward-compat aliases (`wl_editor`, `wl_viewer`) — see `default/authorize.conf` |
| Python version | `python3` + `python.required = 3.13` (see `default/restmap.conf`) |
| Splunk version | See `app.manifest` `platformRequirements.splunk.Enterprise` for the minimum |
| App version | See `default/app.conf` `[launcher].version` and `[install].build` for current values |
| Recovery scripts | `scripts/emergency_unlock.sh`, `scripts/reset_cooldowns.sh`, `scripts/fim_deploy_window.sh` — see `docs/RUNBOOKS.md` |

---

## Trademark notice

Splunk, Splunk Enterprise, and Splunk Enterprise Security are
registered trademarks of Splunk LLC in the United States and other
countries. This project is an independent community tool — it is
not affiliated with, endorsed by, or sponsored by Splunk LLC.
