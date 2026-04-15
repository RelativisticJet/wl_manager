# Installation & Deployment Guide — Whitelist Manager for Splunk ES

This document covers: (1) base install, (2) required permissions, and
(3) **optional security features** that require additional Splunk
permissions which your organization may or may not grant.

---

## 1. Base install

Deploy the app under `$SPLUNK_HOME/etc/apps/wl_manager`, restart Splunk,
and verify the app appears in Splunk Web. See the README for the full
quick-start.

## 2. Required permissions (always needed)

These must be present for the app to function at all:

| Permission | Why it's needed |
|---|---|
| Write access to `$SPLUNK_HOME/etc/apps/wl_manager/lookups/` | CSV editing |
| Write access to `$SPLUNK_HOME/etc/apps/wl_manager/lookups/_versions/` | Version snapshots, audit, HMAC-signed state |
| Read/write on the `wl_audit` index | Audit trail + FIM alerts |
| The `wl_admin`, `wl_superadmin`, `wl_editor` roles installed (via `authorize.conf`) | RBAC |
| KV store collections `wl_cooldowns`, `wl_fim_baseline` | Tamper-resistant state |

These are covered by the bundled `authorize.conf`, `indexes.conf`, and
`collections.conf`. Nothing for the admin to do beyond installing.

## 3. **Optional security features** — trade-off matrix

Some features depend on Splunk permissions that many organizations do
**not** grant by default. These features ship **disabled**; enable them
post-install after confirming the underlying permissions. **The app
works without them** — they are additive, not required.

### 3.1 Insider-threat attribution (`_audit` index read)

**What you get if enabled:**

| Scheduled search | What it does |
|---|---|
| `wl_csv_modification_attribution` | When a CSV is modified outside the handler (via SPL `outputlookup`, REST, or direct FS edit), correlates the `_audit` log to name the user and saved search that caused the write. Attribution arrives within ~1 minute of the CSV event. |
| `wl_saved_search_timebomb_monitor` | Alerts when any user creates, edits, or deletes a saved search whose definition contains `outputlookup` targeting one of the CSVs we manage. Catches planted timebomb scheduled searches before they run. |

**What you get WITHOUT them:**

- Core CSV integrity alert `wl_csv_external_modification_alert` still
  fires at severity 5 within 1 minute of any external CSV write.
- You still know a CSV was modified outside the handler.
- You just do **not** know which user/search did it — forensic lookup
  requires a Splunk admin with `_audit` access to correlate manually.

**Why these ship disabled:**

Many Splunk ES customers restrict `_audit` to core-platform admins as a
policy baseline. The app cannot know your policy up front. Shipping
these searches enabled would either:
- run silently and produce zero results (harmless but confusing), or
- generate permission errors in `splunkd.log` every minute (noisy).

Shipping disabled with a runtime probe is cleaner: admins opt in after
confirming the permission.

**How to check if your deployment supports them:**

```bash
curl -sk -u <wl_superadmin_user>:<password> \
  "https://<splunk>:8089/servicesNS/nobody/wl_manager/custom/wl_manager?action=probe_audit_access&output_mode=json"
```

Sample response when `_audit` is accessible:

```json
{
  "audit_index_accessible": true,
  "diagnostic": "_audit index is visible to this session (HTTP 200 from REST probe).",
  "optional_features": {
    "wl_csv_modification_attribution": "available",
    "wl_saved_search_timebomb_monitor": "available"
  },
  "recommendation": "Enable wl_csv_modification_attribution and wl_saved_search_timebomb_monitor in savedsearches.conf (set disabled = false) to activate insider-threat attribution features."
}
```

When `_audit` is NOT accessible:

```json
{
  "audit_index_accessible": false,
  "diagnostic": "_audit index is NOT accessible to this session (HTTP 403 from REST probe). Your Splunk admin has not granted read access to this app's role context. Contact them if you want to enable the optional insider-threat attribution features.",
  "optional_features": {
    "wl_csv_modification_attribution": "unavailable",
    "wl_saved_search_timebomb_monitor": "unavailable"
  },
  "recommendation": "Optional insider-threat attribution features remain disabled. The core CSV integrity alert (wl_csv_external_modification_alert) is NOT affected and continues to work. To unlock attribution, ask your Splunk admin to grant _audit index read to the app's role context (typically the wl_superadmin and wl_admin roles need a srchIndexesAllowed entry that includes _audit)."
}
```

**How to enable (if the probe says `available`):**

1. Ask your Splunk admin to add `_audit` to the `srchIndexesAllowed`
   list for the `wl_admin` and/or `wl_superadmin` roles, or whichever
   role runs these scheduled searches (via `authorize.conf` or Settings
   > Roles in the UI).
2. In `$SPLUNK_HOME/etc/apps/wl_manager/local/savedsearches.conf`
   (create the file if it doesn't exist), add:

   ```ini
   [wl_csv_modification_attribution]
   disabled = false

   [wl_saved_search_timebomb_monitor]
   disabled = false
   ```

3. Reload the configuration (Settings > Server Controls > Restart, or
   `$SPLUNK_HOME/bin/splunk restart`).

4. Verify in Settings > Searches, Reports, Alerts — both should show
   status "Enabled" and the next-run time should be populated.

### 3.2 FIM lookups-directory integrity (Feature 3 — always enabled)

The watcher detects chmod or ownership changes on the
`lookups/` directory that would DoS our CSV integrity monitoring. This
is fully self-contained: it runs inside the watcher's own access rights
and emits `fim_lookups_dir_mode_changed` or `fim_lookups_dir_unreadable`
at CRITICAL severity.

**No additional permissions required.** Works out of the box.

### 3.3 Other optional alerts already enabled by default

| Alert | What it catches | Dependency |
|---|---|---|
| `wl_csv_external_modification_alert` | External CSV writes (SPL, REST, FS) on mapped CSVs | None — uses our own `wl_audit` index + the managed CSV list |
| `wl_deploy_window_opened_during_lockdown` | Deploy window opened while emergency lockdown is active (compromised-superadmin signal) | None — uses our own events |
| `wl_csv_bootstrap_laundering_correlation` | CSV modified then re-bootstrapped within 5 min to hide evidence | None |
| `wl_fim_watcher_heartbeat_monitor` | CSV watcher process killed or wedged | None |

These all work in every deployment regardless of `_audit` access.

## 4. Summary

| Deployment scenario | What works | What's missing |
|---|---|---|
| Base install, no extra permissions | CSV edits, approval workflow, core FIM alerts, chmod detection, bootstrap-laundering correlation, heartbeat monitor | User/search attribution when CSVs are externally modified; early warning on timebomb saved-search creation |
| Base install + `_audit` read granted | Everything above + attribution + timebomb detection | — |

The decision point is whether your Splunk admin is willing to grant
`_audit` read. If yes, enable the two optional searches and you have
full visibility. If no, the app still runs and still detects insider
CSV tampering — you just lose attribution.
