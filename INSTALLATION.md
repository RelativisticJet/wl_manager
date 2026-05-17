# Installation & Deployment Guide — Whitelist Manager for Splunk ES

This app is designed to adapt to different enterprise Splunk policies.
Some features depend on Splunk capabilities that your organization may
or may not grant to third-party apps. This document explains **why** we
use each endpoint, **what breaks** if access is denied, and **how to
work around** each restriction.

---

## Section 1 — What every installation needs

These are table-stakes and must work for the app to function:

| Resource | Why we need it |
|---|---|
| Write access to `$SPLUNK_HOME/etc/apps/wl_manager/lookups/` | CSV editing is the core feature |
| Write access to `$SPLUNK_HOME/etc/apps/wl_manager/lookups/_versions/` | Version snapshots, tamper-resistant signed state |
| Read/write on the `wl_audit` index | Audit trail + FIM alerts live here |
| RBAC roles bundled in `default/authorize.conf` (run `grep '^\[role_' default/authorize.conf` for the live list) | Tier-based access control: superadmin / admin / analyst-editor / analyst-viewer / editor / viewer |
| KV store collections `wl_cooldowns`, `wl_fim_baseline` (bundled `collections.conf`) | Tamper-resistant state |

All of these are installed automatically when you deploy the app bundle.
Nothing for the admin to do beyond putting the app under
`$SPLUNK_HOME/etc/apps/`.

---

## Section 2 — Optional Splunk capabilities (the trade-off matrix)

The following Splunk **capabilities** and **indexes** enhance the app
but are NOT strictly required. Each ships with graceful degradation:
the app keeps working without them; some features just become dormant
or silently fall back. We document each so your Splunk infrastructure
admin can make an informed decision.

### 2.1 `list_server` — server GUID resolution (HIGH importance)

**Why we need it.** The app derives a per-instance HMAC key from the
Splunk server GUID. This key signs every tamper-resistant state file:
cooldown counters, FIM baseline, deploy-window token, emergency
lockdown state, CSV expected-hash registry. Without the HMAC key, an
attacker with filesystem write access could forge any of these files.

**Resolution paths** (app tries them in order):

1. REST `/services/server/info` — requires the `list_server`
   capability. This is the clean path: works in any process (including
   REST handlers with a session key) and transparently picks up GUID
   rotations after disaster recovery.
2. Read `/opt/splunk/etc/instance.cfg` directly — requires filesystem
   read of Splunk's `etc/` directory. The splunk process user normally
   has this. Used as a fallback.

**Failure mode if both blocked:** the HMAC key is `None`, and every
signed operation fails closed with a "tamper detected" error. The app
is effectively unusable until one of the two paths is restored.

**Probe endpoint:**

```bash
curl -sk -u <wl_superadmin>:<pw> \
  "https://<splunk>:8089/servicesNS/nobody/wl_manager/custom/wl_manager?action=probe_server_info_access&output_mode=json"
```

Sample output when REST works:

```json
{
  "rest_api_accessible": true,
  "instance_cfg_readable": true,
  "resolution_path": "rest",
  "guid_resolved": true,
  "diagnostic": {
    "rest": "HTTP 200, GUID resolved via REST endpoint.",
    "instance_cfg": "Read successfully from instance.cfg."
  },
  "recommendation": "HMAC key derivation uses the REST endpoint — clean install path. No action needed."
}
```

Sample when REST denied but filesystem fallback works:

```json
{
  "rest_api_accessible": false,
  "instance_cfg_readable": true,
  "resolution_path": "instance_cfg",
  "diagnostic": {
    "rest": "HTTP 403 from /services/server/info — this session lacks list_server capability.",
    "instance_cfg": "Read successfully from instance.cfg."
  },
  "recommendation": "HMAC key derivation falls back to reading /opt/splunk/etc/instance.cfg directly. This works but means the app cannot self-heal if the GUID rotates between process restarts. If possible, ask your Splunk admin to grant list_server capability..."
}
```

**How to grant (if desired):** `list_server` is a standard Splunk
capability. Add it to the `wl_admin` or `wl_superadmin` role via
`authorize.conf` or Settings > Roles in the UI.

### 2.2 `list_users` — admin/superadmin enumeration (MEDIUM importance)

**Why we need it.** When an analyst submits an approval request, the
app needs to notify every user with the `wl_admin` or `wl_superadmin`
role. To discover that list dynamically, we call
`/services/authentication/users` and filter by role membership.

Many enterprise Splunk deployments restrict `list_users` to
core-platform admins as a privacy baseline — users with custom roles
can't see the full user directory.

**Failure mode if blocked:** without the fallback config (Section 2.2.1
below), notifications silently go only to the built-in `admin` user.
Custom `wl_admin` users **miss** new-request notifications.
Superadmin-to-superadmin notifications (admin-limit-change alerts,
dual-unlock requests) are **silently dropped**. This is the nastiest
restriction because it LOOKS like everything works — `admin` still
gets notifications — but custom roles are effectively invisible to
the fan-out.

**Probe endpoint:**

```bash
curl -sk -u <wl_superadmin>:<pw> \
  "https://<splunk>:8089/servicesNS/nobody/wl_manager/custom/wl_manager?action=probe_list_users_access&output_mode=json"
```

#### 2.2.1 Fallback config — `local/notification_users.conf`

If your admin will not grant `list_users`, declare users explicitly
in a new file at `$SPLUNK_HOME/etc/apps/wl_manager/local/notification_users.conf`:

```ini
# Users with wl_admin / admin role
[admins]
users = alice, bob, carol

# Users with wl_superadmin role
[superadmins]
users = dave, erin
```

The handler reads this file as a fallback whenever REST enumeration
fails. Format is standard Splunk stanza/key style; usernames are
comma or space separated.

**Security note.** This file is a SENSITIVE CONFIG — anyone who can
write to it can redirect notifications to their own account. Protect
it with normal filesystem permissions (`chown splunk:splunk`,
`chmod 0640`). Do NOT rely on it for RBAC — it only affects who
gets NOTIFIED about events, not who can perform actions.

**How to grant (if desired):** `list_users` is a standard Splunk
capability. Add it to the `wl_admin` or `wl_superadmin` role.

### 2.3 `_audit` index read — insider-threat attribution (LOW importance)

**Why we need it.** Two optional scheduled searches enrich FIM events
by correlating them with Splunk's own search-execution log (the
`_audit` index):

- `wl_csv_modification_attribution` — when a CSV is modified outside
  the handler (via SPL `outputlookup`, REST, or direct FS edit),
  names the user and saved search that caused the write.
- `wl_saved_search_timebomb_monitor` — alerts when any user creates,
  edits, or deletes a saved search whose definition contains
  `outputlookup` targeting one of the CSVs we manage.

**Failure mode if blocked:** the core CSV integrity alert
(`wl_csv_external_modification_alert`) still fires at severity 5 within
1 minute of any external CSV write. You still know a CSV was modified
outside the handler. You just do NOT know which user/search did it —
forensic lookup requires a Splunk admin with `_audit` access.

**Default state:** both optional searches ship with `disabled = true`.
Admins enable them post-install after confirming `_audit` access.

**Probe endpoint:**

```bash
curl -sk -u <wl_superadmin>:<pw> \
  "https://<splunk>:8089/servicesNS/nobody/wl_manager/custom/wl_manager?action=probe_audit_access&output_mode=json"
```

**How to enable (if probe says `available`):** edit or create
`$SPLUNK_HOME/etc/apps/wl_manager/local/savedsearches.conf`:

```ini
[wl_csv_modification_attribution]
disabled = false

[wl_saved_search_timebomb_monitor]
disabled = false
```

Then restart Splunk.

### 2.4 `passAuth = true` on scripted inputs (MEDIUM importance)

**Why we need it.** Our FIM script `wl_fim.py` runs as a scripted
input every 60 seconds. With `passAuth = true` (the default we ship
in `default/inputs.conf`), Splunk writes a session token to stdin
that the script uses to read and write the KV-store baseline. The
KV baseline is the "second independent source" in our dual-store
tamper-detection architecture.

**Failure mode if removed:** the script detects a missing session
token and emits `fim_scripted_input_no_session_key` at HIGH severity
on each run. The filesystem baseline still works, but the dual-store
check (catching an attacker who tampered with ONE of the two stores)
degrades to single-store. An attacker who gets filesystem write
access can silently rewrite the baseline without triggering
divergence detection.

**How to restore:** verify `default/inputs.conf` stanza
`[script://$SPLUNK_HOME/etc/apps/wl_manager/bin/wl_fim.py]` has
`passAuth = true`. If your site policy requires overrides, set it in
`local/inputs.conf`.

### 2.5 Lookups directory filesystem permissions (HIGH importance)

**Why we need it.** The app reads and writes CSV files from
`$SPLUNK_HOME/etc/apps/wl_manager/lookups/`. A malicious insider who
can `chmod` this directory to remove the splunk user's read access
would silently disable CSV integrity monitoring.

**Detection.** The watcher (`wl_fim_watch.py`) baselines the lookups
directory's mode at startup and emits `fim_lookups_dir_mode_changed`
CRITICAL on any change, or `fim_lookups_dir_unreadable` CRITICAL if
the directory becomes unstatable. This is self-contained — it uses
the watcher's own access rights, no privileged hooks needed.

**How to protect:** the splunk process user must own
`$SPLUNK_HOME/etc/apps/wl_manager/lookups/` and its contents.
Default install does this correctly. If your deployment system
rewrites ownership, ensure the post-install step runs
`chown -R splunk:splunk $SPLUNK_HOME/etc/apps/wl_manager/`.

---

## Section 3 — Deployment scenarios at a glance

Run the three probe endpoints to see which column applies to your
deployment:

| Capability | Probe action | Feature impact if denied |
|---|---|---|
| `list_server` | `probe_server_info_access` | HARD failure if both REST and instance.cfg denied; degrades gracefully if filesystem fallback works |
| `list_users` | `probe_list_users_access` | Silent — notifications go only to built-in admin; fixable with fallback conf |
| `_audit` index | `probe_audit_access` | Attribution + timebomb monitor unavailable; core alerts unaffected |

### Sample deployment matrix

| Deployment profile | Capabilities granted | What works |
|---|---|---|
| **Lean / restricted** | None of the above beyond defaults | All core features; notifications limited to `admin` user; no attribution; no timebomb monitor |
| **Lean + fallback conf** | None granted, but `local/notification_users.conf` populated | Core + custom-user notifications; still no attribution or timebomb monitor |
| **Standard enterprise** | `list_server` granted to wl_admin/wl_superadmin | Core + clean HMAC path; notifications to listed users; no attribution |
| **Full enterprise** | All three granted | Everything: core + attribution + timebomb monitor + automatic user discovery |

---

## Section 3.6 — Verifying the release signature (recommended before install)

The `.spl` is Sigstore-signed by GitHub Actions. Verifying before install
confirms the artifact came from this repo's release pipeline and was not
swapped on the GitHub Releases page. See
[docs/SBOM.md](docs/SBOM.md#verifying-a-release-with-cosign) for the
canonical `cosign verify-blob` command and identity-regex.

Skipping this check leaves you exposed to a release-channel takeover
(an attacker who compromises the Releases page can swap both the `.spl`
and the `.sha256` sidecar). Sigstore signing closes that gap.

---

## Section 4 — Post-install verification checklist

Run these checks after the first install:

```bash
# 1. GUID resolution path
curl -sk -u <sa>:<pw> ".../services/custom/wl_manager?action=probe_server_info_access&output_mode=json" \
  | grep -Ei '"resolution_path"|"guid_resolved"'

# 2. User enumeration status
curl -sk -u <sa>:<pw> ".../services/custom/wl_manager?action=probe_list_users_access&output_mode=json" \
  | grep -Ei '"rest_api_accessible"|"fallback_config_present"'

# 3. _audit access
curl -sk -u <sa>:<pw> ".../services/custom/wl_manager?action=probe_audit_access&output_mode=json" \
  | grep -Ei '"audit_index_accessible"'
```

If any probe returns `false` without a clear fallback message, follow
the relevant section above to restore functionality OR to set up the
documented fallback.

---

## Section 5 — Other silently degraded paths (for completeness)

The following conditions don't require active intervention but are
worth knowing:

- **KV store disabled globally on the Splunk instance.** The app falls
  back to filesystem-only cooldown + FIM baseline. Dual-store tamper
  detection degrades to single-store; nothing else breaks.
- **splunkd restart during mid-cleanup.** Our `wl_expiration_cleanup.py`
  may get a transient 401 writing audit events. Benign — next run
  succeeds.
- **Clock skew.** The rate-limit and deploy-window logic uses
  `time.time()`. A 1+ hour forward skew on the host could cause
  entries to appear "expired" prematurely. Deploy-window has a hard
  1-hour cap at read time to prevent forged windows from bypassing
  this.

---

## Section 6 — Upgrade notes

When upgrading from an older version:

1. Run `probe_server_info_access` first to confirm GUID resolution
   still works. If it doesn't, regenerate baselines via the steps in
   the "Disaster Recovery" section of `CLAUDE.md`.
2. If `notification_users.conf` was used pre-upgrade, verify the
   format is still recognized after upgrade (we keep the schema
   stable — additions rather than breaks).
3. Check the Audit dashboard's "File Integrity Monitor Alerts" panel
   for any `fim_scripted_input_no_session_key` events — upgrades
   sometimes reset `inputs.conf` if you were using `local/` overrides.

---

## Trademark Notice

Splunk, Splunk Enterprise, and Splunk Enterprise Security are
registered trademarks of Splunk LLC in the United States and other
countries. This project is an independent community tool — it is not
affiliated with, endorsed by, or sponsored by Splunk LLC.
