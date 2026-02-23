# Whitelist Manager — Splunk Admin Installation Guide

This document covers everything the Splunk administrator needs to do **before**, **during**, and **after** installing the Whitelist Manager application.

---

## BEFORE Installation (Pre-flight Checklist)

### 1. Verify Splunk Version Compatibility

The app requires **Splunk Enterprise 8.x or 9.x** with Python 3 support.

```bash
$SPLUNK_HOME/bin/splunk version
```

Confirm the output shows 8.0+ or 9.x. The app has been tested on **Splunk 9.3.1**.

### 2. Verify Python 3 Is Enabled

The app uses `python.version = python3` in restmap.conf. Splunk must have Python 3 enabled (it is by default in 8.x+, but some environments force Python 2).

Check the current setting:

```bash
$SPLUNK_HOME/bin/splunk btool server list --debug | grep python.version
```

If the output shows `python.version = python2` at the system level, the Splunk admin needs to ensure Python 3 is available, or update `server.conf` to allow Python 3:

```ini
[general]
python.version = python3
```

### 3. Check for Naming Conflicts

The app creates several objects. Verify none of these already exist on your Splunk instance:

| Object | Type | Check Command |
|---|---|---|
| `wl_manager` | App | `$SPLUNK_HOME/bin/splunk display app` |
| `wl_audit` | Index | `$SPLUNK_HOME/bin/splunk list index` |
| `wl_editor` | Role | `$SPLUNK_HOME/bin/splunk list role` |
| `wl_viewer` | Role | `$SPLUNK_HOME/bin/splunk list role` |
| `/custom/wl_manager` | REST endpoint | Should not conflict unless another app uses this exact path |

If any of these already exist, coordinate with the Security Engineering team before proceeding.

### 4. Review Disk Space for the wl_audit Index

The app creates a `wl_audit` index with these defaults (defined in `indexes.conf`):

| Setting | Value | Meaning |
|---|---|---|
| `maxTotalDataSizeMB` | 1024 | Maximum 1 GB of indexed data |
| `frozenTimePeriodInSecs` | 94608000 | Data retained for 3 years |

The index will be created at the default Splunk data path:
- Hot/warm: `$SPLUNK_DB/wl_audit/db`
- Cold: `$SPLUNK_DB/wl_audit/colddb`
- Thawed: `$SPLUNK_DB/wl_audit/thaweddb`

**Action required**: Verify at least **2 GB** of free disk space at `$SPLUNK_DB` (1 GB for data + overhead).

If your organization requires custom index paths or different retention, you have two options:
- **Option A**: After installation, create a `local/indexes.conf` override in the app
- **Option B**: Modify the `indexes.conf` in the .spl before installation (extract, edit, repackage)

### 5. Review Network/Firewall Requirements

The app makes an internal HTTPS call from the REST handler to Splunk's own management port:

```
https://127.0.0.1:8089/services/receivers/simple
```

This is a **localhost-only** call (Python handler → same Splunk instance) used to index audit events. It should work without any firewall changes. However, if your Splunk deployment has **custom SSL certificates** or **non-default management ports**, see the "Custom SSL/Port" section below.

### 6. Review the RBAC Roles

The app creates two new roles:

| Role | Inherits From | Capabilities |
|---|---|---|
| `wl_editor` | `user` | Read + write whitelists, access `wl_audit` index |
| `wl_viewer` | `user` | Read-only access to whitelists and `wl_audit` index |

Both roles inherit from the built-in `user` role. The REST handler also grants full access to the built-in `admin` and `sc_admin` roles.

**Action required**: Prepare a list of users who need each role. You will assign these after installation.

### 7. Identify the Correct app_context Values

The master mapping CSV (`lookups/rule_csv_map.csv`) references CSV files in **other Splunk apps** via the `app_context` column. The value must exactly match the app's **folder name** on disk.

Common examples:

| Splunk App | Typical Folder Name |
|---|---|
| Enterprise Security | `SplunkEnterpriseSecuritySuite` |
| ES Content Update | `DA-ESS-ContentUpdate` |
| SA-ThreatIntelligence | `SA-ThreatIntelligence` |

**Action required**: Verify the exact folder names by listing:

```bash
ls $SPLUNK_HOME/etc/apps/ | grep -i -E "security|SA-|DA-"
```

Share these folder names with the Security Engineering team so they can populate the mapping CSV correctly.

### 8. Backup (Recommended)

Before any app installation:

```bash
# Backup current app state
tar -czf /tmp/splunk_apps_backup_$(date +%Y%m%d).tar.gz $SPLUNK_HOME/etc/apps/

# Backup current roles and users
$SPLUNK_HOME/bin/splunk list role > /tmp/splunk_roles_backup.txt
$SPLUNK_HOME/bin/splunk list user > /tmp/splunk_users_backup.txt
```

---

## Try It First (Docker Demo)

Before installing on production, you can evaluate the app in a containerized Splunk instance. This requires Docker Desktop and takes about 2-3 minutes.

```bash
# From the wl_manager repository root:
bash demo/demo.sh          # builds .spl, starts Splunk on http://localhost:9000
bash demo/demo.sh --stop   # tear down when done
bash demo/demo.sh --clean  # tear down + remove data volume
```

Login: `admin` / `Chang3d!` at http://localhost:9000

The demo installs the app from the `.spl` package (same as a real install) and seeds three sample detection rules with whitelist data. See `demo/Demo_Guide.pdf` for a detailed walkthrough.

> **Note:** The demo uses ports 9000/9089 to avoid conflicts with any existing Splunk installation.

---

## DURING Installation

### Step 1: Install the .spl Package

**Option A — Splunk Web (recommended for single instance):**

1. Log in to Splunk Web as admin
2. Navigate to **Apps > Manage Apps**
3. Click **Install app from file**
4. Browse to `wl_manager-1.0.0.spl` and click **Upload**
5. Check "Restart Splunk" when prompted

**Option B — Splunk CLI:**

```bash
$SPLUNK_HOME/bin/splunk install app /path/to/wl_manager-1.0.0.spl -auth admin:password
$SPLUNK_HOME/bin/splunk restart
```

**Option C — Manual (for clustered or restricted environments):**

```bash
cd $SPLUNK_HOME/etc/apps/
tar -xzf /path/to/wl_manager-1.0.0.spl
chown -R splunk:splunk wl_manager/
$SPLUNK_HOME/bin/splunk restart
```

### Step 2: Verify No Errors During Startup

After Splunk restarts, check the logs for any errors related to the app:

```bash
# Check for app loading errors
grep -i "wl_manager\|WhitelistHandler" $SPLUNK_HOME/var/log/splunk/splunkd.log | tail -20

# Check for Python errors
grep -i "wl_handler\|wl_manager" $SPLUNK_HOME/var/log/splunk/python_stderr.log | tail -20
```

**Expected**: No errors. If you see `ImportError` or `ModuleNotFoundError`, the Python 3 environment may not be configured correctly (see Pre-flight step 2).

### Step 3: Verify the REST Endpoint

Test that the custom REST endpoint responds:

```bash
curl -sk -u admin:password https://localhost:8089/services/custom/wl_manager?action=get_mapping
```

**Expected response** (JSON with the sample mapping data):

```json
{"mapping": [{"rule_name": "My_Detection_Rule", "csv_file": "my_whitelist.csv", ...}]}
```

If you get a **404**, restart Splunk one more time. If the 404 persists, check the logs above.

---

## AFTER Installation (Post-installation Setup)

### 1. Verify the wl_audit Index

```bash
$SPLUNK_HOME/bin/splunk list index wl_audit
```

Or in Splunk Web: **Settings > Indexes** — find `wl_audit`.

If the index does not appear, create it manually:

```bash
$SPLUNK_HOME/bin/splunk add index wl_audit -maxTotalDataSizeMB 1024 -frozenTimePeriodInSecs 94608000
```

### 2. Verify the App Is Visible

1. Open Splunk Web
2. Click the **Apps** dropdown in the top navigation
3. **Whitelist Manager** should appear in the list
4. Click it — the main dashboard should load with two dropdowns

### 3. Assign Roles to Users

For each analyst who needs to **edit** whitelists:

```bash
$SPLUNK_HOME/bin/splunk edit user <username> -role wl_editor -auth admin:password
```

Or via Splunk Web: **Settings > Access Controls > Users > [username] > Edit > Roles > add wl_editor**

For read-only users:

```bash
$SPLUNK_HOME/bin/splunk edit user <username> -role wl_viewer -auth admin:password
```

### 4. Populate the Master Mapping CSV

This is the most critical post-installation step. The Security Engineering team will provide the mapping data, but the admin may need to assist with verifying `app_context` values.

**Option A — Splunk Web:**

1. Go to **Settings > Lookups > Lookup table files**
2. Find **rule_csv_map** (App: wl_manager)
3. Click the filename to edit
4. Replace the sample data with real detection rule mappings

**Option B — File system:**

```bash
vi $SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv
```

Format:

```csv
rule_name,csv_file,app_context
My_Detection_Rule,my_whitelist.csv,SplunkEnterpriseSecuritySuite
Another_Rule,another_whitelist.csv,DA-ESS-ContentUpdate
```

**Important**: The `app_context` must exactly match the app's folder name in `$SPLUNK_HOME/etc/apps/`.

### 5. Verify CSV File Permissions

The Splunk process (running as the `splunk` user) needs **read and write** access to the CSV files referenced in the mapping. Check:

```bash
# List the CSV files and their permissions
for csv in $(awk -F',' 'NR>1 {print $3"/"$2}' $SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv); do
    ls -la "$SPLUNK_HOME/etc/apps/$csv" 2>/dev/null || echo "NOT FOUND: $csv"
done
```

If any CSV files show as NOT FOUND, the `app_context` or `csv_file` values in the mapping are incorrect.

If permissions are wrong:

```bash
chown splunk:splunk $SPLUNK_HOME/etc/apps/<app_context>/lookups/<csv_file>
chmod 644 $SPLUNK_HOME/etc/apps/<app_context>/lookups/<csv_file>
```

### 6. Test End-to-End

1. Log in as a user with the `wl_editor` role
2. Open **Apps > Whitelist Manager**
3. Select a detection rule from the first dropdown
4. Select a CSV from the second dropdown
5. The table should load with the CSV contents
6. Modify a cell, type a comment, and click **Save**
7. Go to the **Audit Trail** tab — the change should appear
8. Verify in SPL:

```spl
index=wl_audit sourcetype=wl_audit | head 5 | spath | table timestamp analyst detection_rule csv_file comment rows_added rows_removed
```

### 7. Test RBAC Enforcement

1. Log in as a user **without** the `wl_editor` role
2. Open the Whitelist Manager dashboard
3. Try to save a change — it should display: *"Permission denied. Your account requires one of these roles: admin, sc_admin, wl_editor"*

---

## Special Considerations

### Custom Management Port or SSL

If your Splunk management port is not 8089, or you use custom SSL certificates, the audit indexing URL in the REST handler needs adjustment.

The handler currently uses:

```
https://127.0.0.1:8089/services/receivers/simple
```

To change this, create a local override:

```bash
mkdir -p $SPLUNK_HOME/etc/apps/wl_manager/local
```

Then coordinate with the Security Engineering team to update the handler's `_index_audit()` method with the correct port/certificate settings.

### Search Head Cluster (SHC) Deployment

If deploying to a Search Head Cluster:

1. Place the app in the SHC deployer: `$SPLUNK_HOME/etc/shcluster/apps/wl_manager/`
2. Push the bundle: `$SPLUNK_HOME/bin/splunk apply shcluster-bundle -target <captain_uri>`
3. The `wl_audit` index must also be configured on the **indexers** (or forwarded there)

### Indexer Cluster Deployment

If you run an indexer cluster, the `wl_audit` index must be created on the indexers via the cluster master:

```bash
# On the cluster master
mkdir -p $SPLUNK_HOME/etc/master-apps/wl_manager/default/
cp indexes.conf $SPLUNK_HOME/etc/master-apps/wl_manager/default/indexes.conf
$SPLUNK_HOME/bin/splunk apply cluster-bundle
```

### Monitoring and Alerting (Optional)

Consider setting up a saved search to alert on whitelist changes:

```spl
index=wl_audit sourcetype=wl_audit
| spath
| where rows_added > 10 OR rows_removed > 10
| table timestamp analyst detection_rule csv_file rows_added rows_removed comment
```

This alerts when someone adds or removes more than 10 rows in a single save — potentially catching accidental bulk deletions.

---

## Uninstallation

If the app needs to be removed:

```bash
$SPLUNK_HOME/bin/splunk remove app wl_manager -auth admin:password
$SPLUNK_HOME/bin/splunk restart
```

This removes the app but **preserves** the `wl_audit` index data. To also remove the index:

```bash
$SPLUNK_HOME/bin/splunk remove index wl_audit
```

The custom roles (`wl_editor`, `wl_viewer`) are removed with the app. Users who had these roles assigned will lose them automatically.

---

## Quick Reference Card

| Item | Value |
|---|---|
| App folder | `$SPLUNK_HOME/etc/apps/wl_manager/` |
| REST endpoint | `https://<splunk>:8089/services/custom/wl_manager` |
| Web dashboard | `https://<splunk>:8000/app/wl_manager/whitelist_manager` |
| Audit index | `wl_audit` |
| Audit log file | `$SPLUNK_HOME/var/log/splunk/wl_manager_audit.log` |
| Mapping CSV | `$SPLUNK_HOME/etc/apps/wl_manager/lookups/rule_csv_map.csv` |
| Edit role | `wl_editor` |
| View role | `wl_viewer` |
| Python version | Python 3 |
| Splunk version | 8.x+ / 9.x (tested on 9.3.1) |
