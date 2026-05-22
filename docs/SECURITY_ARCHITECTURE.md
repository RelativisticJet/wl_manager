# Whitelist Manager Security Architecture

> **Document Purpose:** Provide security transparency to Splunk administrators and security reviewers. This document covers the security design, data flows, threat model, and evidence of mitigated vulnerabilities.
>
> **Audience:** Splunk security teams, system administrators, security auditors, compliance reviewers

---

## Part 1: Executive Summary

### Overview

The Whitelist Manager is a Splunk application that enables SOC analysts to safely manage detection-rule CSV lookup whitelists through a web UI with complete audit trail. The application implements **defense-in-depth security** across authentication, authorization, input validation, audit integrity, and concurrency control.

**Key Design Philosophy:** Trust is verified, not assumed. Every user action is validated, authorized, and logged with cryptographic integrity.

### Data Accessed and Modified

**Data Accessed (Read-Only):**
- Splunk user context (session key, roles)
- Detection rule definitions (lookup table)
- CSV whitelist files (lookup directory)
- Version history snapshots
- Daily usage statistics (for rate limiting and approval gates)

**Data Modified:**
- CSV whitelist files (write via version-controlled snapshots)
- Audit log index (`wl_audit`) — append-only events
- Version history manifest (JSON metadata)
- Approval queue (temporary request tracking)
- Presence tracking (user activity heartbeats)

### Roles Defined

The application defines four security tiers with progressive
permissions. See `default/authorize.conf` for the authoritative
definition; backward-compat aliases keep older deployments working
through the renaming.

| Role (modern) | Backward-compat alias | Layer | Purpose |
|------|------|-------|---------|
| **wl_analyst_viewer** | wl_viewer | Read-only | Security analysts viewing whitelist state and audit trail (passive monitoring) |
| **wl_analyst_editor** | wl_editor | Analyst | SOC analysts editing whitelists with approval gates for bulk operations |
| **wl_admin** | (n/a) | Administrator | Approval authority; controls analyst policy limits and usage thresholds; Control Panel access |
| **wl_superadmin** | (n/a) | System Owner | Configures admin limits, trash retention, role assignment; activates and deactivates Emergency Lockdown; out-of-band recovery actions |

All roles require Splunk authentication; anonymous access is not supported.

### Audit Completeness

**Every change to a whitelist is recorded atomically:**

1. **User action** is validated by server (RBAC, input constraints, rate limits)
2. **Diff detection** compares old vs new state (rows added/removed/edited)
3. **Audit event** is constructed with metadata (analyst, timestamp, action, before/after values)
4. **Event is posted** to `wl_audit` index (HTTP POST via Splunk REST API)
5. **Confirmation logged** to app debug log

All events include:
- Analyst username (from Splunk session context)
- Timestamp (UTC, server-generated)
- Action type (added, removed, edited, revert, auto_removed)
- Detection rule and CSV file names
- Field-level changes (before/after values)
- User-provided reason (required for removals)

**Non-repudiation:** Once posted to the index, audit events cannot be deleted by the app (requires direct Splunk admin access to the index).

### Cloud Compatibility

The application is designed for **Splunk Cloud** deployment:

- **Lazy imports:** No direct `splunk.sdk` imports at module level (works in restricted Python environments)
- **REST API only:** Uses Splunk's HTTP REST endpoints (port 8089), not Python SDK
- **No filesystem assumptions:** Lookups stored in standard Splunk `etc/apps/wl_manager/lookups/` directory
- **Stateless handlers:** Each REST request is independent; no in-process state persistence

---

## Part 2: Detailed Threat Model

### STRIDE Threat Analysis

The Whitelist Manager threat surface includes six categories (STRIDE):

#### 1. **Spoofing Identity**

**Threats:** Attacker impersonates a legitimate analyst or administrator

**Security Controls:**
- All requests require valid Splunk session key (enforced by Splunk framework at `BaseRestHandler` level)
- User identity extracted from session context (`splunk.rest.current_user` context or session headers)
- Role discovery via Splunk's `/services/authentication/current-context` API (Splunk's authoritative source)
- No session token forging possible (Splunk manages token generation and validation)

**Mitigated Threats:**
1. **Client-spoofed roles** — Frontend cannot inject role headers; roles checked server-side from Splunk context
2. **Token reuse across instances** — Splunk session keys are instance-specific; stolen tokens only work on the source Splunk instance

**Risk Assessment:** Mitigated by Splunk's authentication system. Risk depends on Splunk admin security practices (session timeout, token rotation, TLS for web traffic).

---

#### 2. **Tampering with Data**

**Threats:** Attacker modifies CSV content, audit events, or version history

**Security Controls:**

**A. CSV Integrity:**
- **Optimistic locking:** Each CSV read includes file modification time (mtime). Concurrent writes are detected if mtime has changed.
- **Diff detection:** Similarity-based algorithm (not positional) correctly identifies edits even when rows are simultaneously added/removed/edited.
- **Atomic writes:** File updates are written in a single `write()` call to minimize race conditions.
- **Version snapshots:** Previous 5 versions are retained; rollback is possible via audit-visible revert action.

**B. Audit Integrity:**
- **Append-only index:** Audit events are written to the `wl_audit` index. Deletion requires Splunk admin privilege (not available to app).
- **Server-computed diffs:** Frontend sends CSV data; backend computes diff independently. Frontend cannot forge diff values.
- **Tamper-evident fields:** Reserved field prefix `_` is rejected in CSV columns; internal metadata columns are whitelisted explicitly.

**C. Approval Queue:**
- **Request signatures:** Each request in the queue includes request_id (UUID), analyst name, and timestamp; tampering changes these identifiers.
- **Atomic replay:** Approved requests are replayed atomically with precondition checks (rule exists, CSV exists before edit).

**Mitigated Threats:**
1. **Concurrent edit collisions** — Fixed via optimistic locking and mtime validation
2. **False audit trail** — Fixed via server-side diff computation; frontend cannot inject audit data
3. **Reserved prefix bypass** — Fixed via whitelist enforcement; underscore-prefixed columns rejected at input
4. **Approval request injection** — Fixed via server-side request_id generation; frontend request_id ignored
5. **Optimistic locking bypass** — Fixed via validation of expected_mtime before edit acceptance

**Risk Assessment:** MEDIUM. Data tampering requires either:
- (Unlikely) Successful MITM attack to intercept request between browser and Splunk instance
- (Unlikely) Compromise of Splunk process memory to forge session token
- (Possible) Direct file system access to CSV files outside the app (mitigated by Splunk RBAC on file permissions)

---

#### 3. **Repudiation**

**Threat:** Analyst denies performing an action (e.g., "I didn't delete that whitelist entry")

**Security Controls:**
- **Non-repudiation via audit index:** All actions logged with analyst name, timestamp, and action details
- **Analyst cannot delete their own events:** Event deletion requires Splunk index-level admin privilege
- **Event ordering:** Events in `wl_audit` are timestamped and indexed, providing chronological ordering

**Mitigated Threats:**
1. **Analyst denial of edits** — All edits logged with before/after values; analyst cannot claim data changed without their action

**Risk Assessment:** LOW. Non-repudiation is strong. Risk limited to:
- Splunk admin deleting/modifying audit events (outside app scope; Splunk governance responsibility)
- Analysts with multiple accounts claiming another identity

---

#### 4. **Information Disclosure**

**Threat:** Attacker reads sensitive CSV data or audit trail without authorization

**Security Controls:**
- **Role-based access:** Read permission checked against user's Splunk roles
- **Audit index access:** `wl_viewer` and above roles have `srchIndexesAllowed = wl_audit`
- **HTTPS only:** Splunk enforces TLS 1.2+ for all REST API traffic (port 8089)
- **No plaintext logging:** CSV content is logged in audit events only (not in app debug logs)
- **Session token encryption:** Splunk encrypts session tokens in transit and at rest

**Mitigated Threats:**
1. **Unauthenticated CSV reads** — Frontend enforces Splunk authentication; Splunk framework rejects requests without session key
2. **CSV data in app logs** — Logging only captures event action, analyst name, and field counts; not full CSV content

**Risk Assessment:** LOW. Information disclosure requires:
- Compromise of Splunk's TLS or session token encryption (cryptographically unlikely)
- Attacker with network access to Splunk port 8089 (requires infrastructure compromise)
- Attacker with local filesystem access to Splunk conf files or indexes

---

#### 5. **Denial of Service**

**Threat:** Attacker overwhelms the app with requests, preventing legitimate use

**Security Controls:**
- **Rate limiting:** Per-user sliding-window rate limiter (30 writes, 120 reads per 60 seconds)
- **Request size limits:** POST body limited to 10 MB; CSV cells capped at 1000 chars; total rows capped at 5000
- **File locking:** CSV write operations use advisory locks (flock/fcntl) to serialize access
- **Presence tracking timeout:** User heartbeats expire after 60 seconds of inactivity
- **Approval queue expiry:** Pending requests auto-expire after 30 days

**Mitigated Threats:**
1. **Request flooding** — Rate limit enforces 30 POST per minute per user; excess requests rejected with 429 Too Many Requests
2. **Oversized payloads** — 10 MB POST body limit prevents unbounded memory allocation
3. **Concurrent write conflicts** — File locks serialize CSV writes; conflicts logged and retried
4. **Presence tracking memory leak** — Expired presences are purged every time tracking is updated

**Risk Assessment:** MEDIUM. Rate limiting is effective for per-user DoS. Risk:
- (Possible) Multi-user coordinated flood attack (each user within rate limit, but aggregate overwhelms server)
- (Possible) Malicious lock holding in file locking (causes other writers to block indefinitely)
  - **Mitigation:** Lock acquisition has 5-second timeout; lock held beyond 5 seconds triggers WARNING log
- (Low) Splunk instance-level DoS (e.g., exhaust HEC tokens, fill audit index) — outside app scope

---

#### 6. **Elevation of Privilege**

**Threat:** Analyst (wl_editor) gains admin (wl_admin) privileges

**Security Controls:**
- **Granular RBAC:** Approval action requires `is_admin(roles)` check; role checks are server-side and occur at every gate
- **Approval queue enforcement:** Bulk operations (3+ rows) require admin approval; analyst cannot approve their own requests
- **Admin bypass:** Admins are exempt from rate limits and approval gates (they ARE the approvers)
- **Superadmin isolation:** Only wl_superadmin can configure system-wide limits and trash retention
- **No role inference from data:** App never trusts role information from frontend; role check is always via Splunk's REST API

**Mitigated Threats:**
1. **Client-side role spoofing** — Role checks are server-side only; frontend role display is informational
2. **Analyst self-approval** — Approval handler explicitly checks `analyst != current_user` before approving
3. **Analyst daily limit bypass** — Rate limiter checks at request time; frontend limit display is informational
4. **Admin approval of malicious requests** — Every approved request is replayed with precondition checks (rule exists, CSV exists)
5. **Analyst creation of new rules** — Rule creation requires admin approval; analyst cannot create rules without approval
6. **Reserved prefix hidden metadata** — Underscore-prefixed columns are rejected; only whitelisted internal columns (`_added_by`, `_added_at`) are permitted

**Risk Assessment:** LOW. Elevation requires:
- (Unlikely) Compromise of Splunk's role system
- (Possible) Admin approval of malicious request (approval UI should warn of unusual changes)
- (Unlikely) Role-injection in REST request (all role info sourced from Splunk, not request)

---

### DREAD Scoring for High-Risk Threats

| Threat | Damage | Reproducibility | Exploitability | Affected Users | Discoverability | DREAD Score | Severity |
|--------|--------|-----------------|-----------------|-----------------|-----------------|-------------|----------|
| Concurrent edit collision (CSV mtime bypass) | 7 | 6 | 4 | 9 | 3 | **29** | **High** |
| Rate limit DoS (coordinated multi-user) | 6 | 8 | 5 | 8 | 5 | **32** | **High** |
| Admin approval of malicious requests | 9 | 3 | 6 | 4 | 4 | **26** | **Medium** |
| Audit log tampering (Splunk admin access) | 10 | 2 | 3 | 10 | 2 | **27** | **Medium** |
| Analyst self-approval (RBAC bypass) | 8 | 2 | 3 | 3 | 3 | **19** | **Low** |

**High-Risk Mitigations (DREAD ≥ 29):**
- **Concurrent edit collisions:** Optimistic locking with mtime validation + version snapshots + audit trail
- **Multi-user DoS:** Rate limiting per-user + request size limits + file locking with timeout

---

## Part 2A: Hardening Mechanisms

The controls in this section sit alongside the STRIDE mitigations
above. They address attacker scenarios that don't fit cleanly into
a single STRIDE category — insider abuse, post-authentication
tampering, supply-chain compromise, and recovery-path forgery.

### 2A.1 HMAC-signed state with runtime-derived key

Every tamper-resistant state record carries an HMAC signature.
The signing key is derived at runtime from the Splunk server
GUID, cached for 1 hour, and re-derived on cache miss or any
restart. The key never lives on disk in plaintext and is not
exported anywhere outside the running process. Operators with
source-code read access alone cannot forge a valid record.

**Signed records:**

| Record | Storage | Why HMAC matters |
|---|---|---|
| Cooldown counters | KV `wl_cooldowns` + filesystem fallback | Prevents an attacker from rewinding their daily-action count by editing the underlying record |
| FIM baseline | KV `wl_fim_baseline` + `.fim_baseline.json` | Prevents silent re-baselining to hide prior file mutations |
| CSV expected-hash registry | `.csv_expected_hashes.json` | Prevents bypass of CSV integrity monitoring by editing the expected hashes |
| Emergency Lockdown sentinel | `_emergency_lockdown.json` | Prevents forging a lockdown-active or lockdown-deactivated state |
| FIM deploy window token | `_fim_deploy_window.json` | Prevents forging a permanently-open deploy window to suppress alerts |

**Failure-closed behavior:** any record that fails HMAC verification
is rejected by the handler and treated as if the underlying control
was tampered with. The FIM script raises a HIGH-severity audit event
on HMAC failure so the deviation is visible in the dashboard.

**GUID rotation:** disaster recovery on a new host changes the GUID
and invalidates every signed record. The runbook in
`docs/RUNBOOKS.md` ("Disaster Recovery — GUID Rotation / Backup
Restore / Container Clone") documents the rebuild order:
`reset_cooldowns.sh` → FIM baseline rebuild →
`bootstrap_csv_hashes` REST action.

### 2A.2 File Integrity Monitoring (FIM)

Two scripted inputs in `default/inputs.conf` provide dual-layer
detection of out-of-band tampering with the app's code, config,
and CSV lookups.

**Slow path — `bin/wl_fim.py`** (cryptographic scan, 15-second interval):

- Hashes a curated set of critical files: handler source code,
  `default/*.conf`, cooldown markers, lockdown state, `instance.cfg`
- Emits JSON events to `index=wl_audit sourcetype=wl_fim`
- Maintains a dual-store baseline: filesystem JSON
  (`.fim_baseline.json`) AND KV `wl_fim_baseline` collection
- Cross-validates the two stores on every cycle; an attacker who
  silently rewrites ONE store is caught by divergence alerts
- Catches mtime-preserving attacks (intentional `touch -r` after
  modification) that the fast path cannot detect

**Fast path — `bin/wl_fim_watch.py`** (persistent stat-based, ~2s):

- Persistent process (`interval = 0`) polling `os.stat()` for mtime
  and size changes on all CSV lookups referenced in `rule_csv_map.csv`
- Re-reads the mapping every 15 seconds + immediately on sentinel
  CSV changes, so newly added CSVs are picked up within seconds
- Detects unauthorized modifications via SPL `| outputlookup`,
  direct filesystem writes, REST lookup edits — all of which bypass
  the handler's approval gates, rate limits, and audit pipeline
- Baselines the `lookups/` directory's filesystem mode at startup;
  any subsequent mode change emits `fim_lookups_dir_mode_changed`
  CRITICAL — closes the "chmod away the splunk user's read access
  to silently disable monitoring" attack
- Auto-bootstraps the expected-hash registry on first run; cannot be
  silently re-bootstrapped (see laundering correlation below)

**Laundering correlation:** the scheduled search
`wl_csv_bootstrap_laundering_correlation` fires at severity 5
(CRITICAL) when a `bootstrap_csv_hash_changed` event for a CSV
appears within 5 minutes of a `fim_csv_external_modification` for
the same CSV. This catches the "modify CSV → re-bootstrap to
suppress detection" sequence.

**Stateful alert dedup:** persistent alert conditions are
deduplicated via `.fim_alert_state.json` so the audit index isn't
buried under repetitive notifications for one stuck condition.

### 2A.3 Emergency Lockdown

A `wl_superadmin` can activate a system-wide write freeze via the
Control Panel. While the lockdown is active, the dispatcher
short-circuits all non-exempt POST actions with a
lockdown-active error. The implementation choices:

- **Self-unlock blocked** — deactivation requires a DIFFERENT
  `wl_superadmin` from the one who activated it. Two-superadmin
  separation is the strongest defense in this app
- **Sentinel-protected state** — HMAC-signed state file prevents
  forging an active or deactivated state
- **Narrow exempt-action set** — only safety actions
  (deactivation, notifications, approval-gate probes, presence
  updates, FIM deploy-window open/close, a few read-only
  diagnostics) can execute during lockdown
- **Sentinel files stay HIGH** — even during a deploy window,
  mutations to cooldown markers, lockdown state, and `instance.cfg`
  retain HIGH severity. Legitimate deploys never touch them
- **Out-of-band release** — if both `wl_superadmin` accounts are
  compromised or unavailable, `scripts/emergency_unlock.sh`
  releases the lockdown after writing an append-only record to
  `_recovery_log.jsonl`. That log is tailed into `wl_audit` so
  even out-of-band recoveries are visible in the audit trail

**Trade-off acknowledged:** deploy windows are lockdown-exempt to
allow hotfix deploys during incidents. A compromised
`wl_superadmin` during lockdown could abuse this to cover code-file
modifications. The exemption is documented in CLAUDE.md "Operational
Procedures" because operational continuity outweighed defense
against an already-elevated total-compromise threat.

### 2A.4 Rate limiting + daily limits + approval queue

Three independent throttles backed by the same KV-store-signed
mechanism (`wl_cooldowns`, `wl_ratelimit_state`):

- **Sliding-window rate limit** — per-user/per-action burst cap
  (30 writes / 120 reads per 60 seconds by default); enforced at
  request time, not advisory
- **Daily limits** — per-tier action counts (analyst vs. admin)
  configurable via Control Panel; superadmin actions exempt by
  design (post-compromise attribution falls back to Splunk's own
  `_audit` index — see Section 2A.7)
- **Approval queue** — bulk operations and destructive actions
  (rule/CSV delete, trash purge, bulk edits above threshold) are
  forced through a dual-approval workflow before execution; analyst
  cannot self-approve

**Replay safety:** every queued action re-validates preconditions
(rule exists, CSV exists, no conflicting deletion in flight) at
EXECUTION time, not just submission. Approving a "create CSV"
request after the parent rule was deleted silently fails closed
rather than re-creating the rule.

### 2A.5 Strict-ASCII validation (dual-gate)

Detection rule names, CSV filenames, approval reasons, and
`app_context` values are validated against `^[A-Za-z0-9_\-. ]+$` at
TWO independent gates — the outer wrapper that handles the
"submit_create_delete_approval" request AND the inner choke point
that processes any approval. The dual placement closes a bypass
where a direct REST POST to the inner action could skip the outer
gate.

**Rejected attack classes:**

- Homoglyph attacks (e.g., Cyrillic "а" vs Latin "a") that would
  let a rule name visually impersonate another
- Bidi/zero-width attacks that hide characters in filesystem paths
- Null-byte injection / control-character injection in audit fields
- Combining-mark + fullwidth attacks that confuse SPL parsing

ASCII was chosen over Unicode normalization (NFC/NFKC) because the
operational reality of the app — dashboard panels, audit searches,
`rule_csv_map.csv` exports — is ASCII at every consumer. See
`docs/DECISION_LOG.md` 2026-04-26 entry for the full rationale.

### 2A.6 Release signing (Sigstore keyless)

`.spl` release artifacts are signed by the GitHub Actions release
workflow via Sigstore keyless signing. Verification before install
confirms the artifact came from this repository's release pipeline
and was not swapped on the Releases page.

The canonical verification command lives in `docs/SBOM.md`. Skipping
this check exposes operators to a release-channel takeover where an
attacker who compromises the Releases page can swap both the `.spl`
AND the SHA-256 sidecar.

**Identity-regex on the signature:** the cosign identity check
pins the workflow file path AND the repository, so a compromised
fork's release workflow cannot produce a valid signature for this
repo's identity.

### 2A.7 Post-compromise attribution via Splunk's `_audit` index

For threats that fall in the "attacker already has `wl_superadmin`
or built-in `admin`" total-compromise tier, this app's own audit
trail is not a reliable forensic source (the compromised role can
deactivate lockdown, reset cooldowns, even re-baseline FIM if it
has filesystem access).

The fallback is Splunk's own `_audit` index, which lives outside
this app's control plane and cannot be tampered from inside the
app. Two optional scheduled searches enrich FIM events with
`_audit` correlation (see `INSTALLATION.md` Section 2.3):

- `wl_csv_modification_attribution` — names the user and saved
  search responsible for any CSV write that didn't go through the
  handler
- `wl_saved_search_timebomb_monitor` — alerts on any saved search
  whose definition contains `| outputlookup` targeting one of our
  CSVs (defense against "create scheduled bomb, ride out lockdown,
  let it fire later")

Both ship `disabled = true` because they depend on the `_audit`
read capability that not every site grants — admins enable after
running the `probe_audit_access` REST endpoint.

---

## Part 3: Security Architecture Components

### Authentication Flow

```
User Browser
    ↓ (HTTP request with session cookie)
Splunk Web UI / REST Gateway
    ↓ (validate session token)
Session valid? → NO → Redirect to /auth/login
    ↓ YES
Splunk REST Handler (BaseRestHandler)
    ↓ (extract session_key, user, roles from context)
wl_rbac.py::get_user(request) → username
wl_rbac.py::get_roles(request) → set of roles
    ↓ (fetch roles from /services/authentication/current-context)
Role-based access check
    ↓ (RBAC predicates: is_admin, is_editor, can_approve)
Action allowed? → NO → 403 Forbidden
    ↓ YES
Execute handler (save_csv, revert, etc.)
```

**Key Points:**
- No session tokens are managed by the app (Splunk handles token lifecycle)
- User identity and roles are fetched from Splunk's authoritative sources (not cached)
- Every request is authenticated; no "public" endpoints exist

### Authorization Flow (RBAC Matrix)

| Role | view_csv | edit_cells | add_row | remove_row | submit_edit | submit_bulk_edit | approve_request | admin_actions | superadmin_actions |
|------|----------|-----------|---------|-----------|------------|------------------|-----------------|----------------|-------------------|
| **wl_viewer** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **wl_editor** | ✓ | ✓ | ✓ | ✓ | ✓ | Queue* | ✗ | ✗ | ✗ |
| **wl_admin** | ✓ | ✓ | ✓ | ✓ | ✓ | Direct | ✓ | ✓ | ✗ |
| **wl_superadmin** | ✓ | ✓ | ✓ | ✓ | ✓ | Direct | ✓ | ✓ | ✓ |

*Queue = Bulk edits require admin approval; analyst submits request to approval queue

### Audit Event Flow

```
User submits CSV edit
    ↓
wl_handler.py::save_csv() validates:
  1. User is authenticated (has session_key)
  2. User has wl_editor or admin role (is_editor check)
  3. CSV file exists and is safe (is_safe_filename, safe_realpath)
  4. Current CSV mtime matches expected_mtime (optimistic lock)
  5. Payload size ≤ 10 MB (MAX_PAYLOAD_BYTES)
    ↓ (validation passed)
wl_csv.py::_compute_diff(old_rows, new_rows) → changes
    ↓
wl_audit.py::build_audit_event(
    action="added|removed|edited",
    analyst=username,
    detection_rule=rule_name,
    csv_file=csv_name,
    value=[...field changes...]
)
    ↓
wl_audit.py::post_audit_event(session_key, event)
    HTTP POST to https://127.0.0.1:8089/services/receivers/simple
    Headers: Authorization: Splunk {session_key}, Content-Type: application/json
    ↓
wl_audit index receives event (append-only)
    ↓
Response: {"status": "posted", "timestamp": "2026-03-22T10:30:45Z", "event_id": "..."}
```

**Key Properties:**
- Diff is computed server-side; frontend cannot forge diffs
- Audit event is JSON-serialized and posted atomically
- No local buffering; failures are logged to app debug log but don't block the edit
- Audit events are timestamped by the server (not client-provided)

### Data Flow Diagram

```
[Analyst Browser]
    ↓ HTTPS (REST API calls)
[Splunk REST Gateway]
    ↓ (session validation)
[wl_handler.py — Main REST Handler]
    ↓
    ├─→ [wl_rbac.py] — Check user, fetch roles
    ├─→ [wl_validation.py] — Sanitize inputs, validate paths
    ├─→ [wl_limits.py] — Check rate limits, daily limits
    ├─→ [wl_csv.py] — Read/write CSV files, compute diffs
    ├─→ [wl_versions.py] — Manage version snapshots
    ├─→ [wl_approval.py] — Approval queue logic (for bulk ops)
    ├─→ [wl_audit.py] — Build audit events
    │   ↓ HTTP POST (port 8089, REST API)
    │   └─→ [wl_audit index] — Audit trail (immutable)
    └─→ [Splunk Session] — Fetch roles, verify token
```

---

## Part 4: Mitigated Vulnerabilities

The following vulnerabilities were identified during development (Phases 1-7) and have been mitigated:

### 1. Optimistic Locking Bypass

**Vulnerability:** Analyst A edits CSV, saves without pushing. Analyst B edits CSV, saves (overwrites A's changes). A's changes are lost silently.

**Root Cause:** No concurrency control; last write wins (lost update problem).

**Mitigation:**
- Each CSV read includes file modification time (mtime)
- Before write, check if current file mtime matches expected_mtime
- If mtime changed, reject write with "File was modified by another user" error
- User must refresh and merge changes manually

**Commit:** `2fa8c3d` — Add expected_mtime validation in wl_versions.py
**Code Reference:** `bin/wl_versions.py::get_csv_with_versions()`

**Status:** ✓ Mitigated

---

### 2. Client Trust Bypass (No Server-Side Validation)

**Vulnerability:** Frontend sends unvalidated data to backend. Analyst could submit oversized CSV, invalid filenames, or malicious role names.

**Root Cause:** Backend accepted all frontend inputs without validation.

**Mitigation:**
- `wl_validation.py` provides pure validation functions:
  - `is_safe_filename()` — Prevents path traversal
  - `safe_realpath()` — Prevents symlink escape
  - `sanitize_text()` — Removes control characters
  - `resolve_csv_path()` — Validates file exists and is safe
- All POST handlers validate inputs before processing
- Payload size limited to 10 MB
- CSV cell content limited to 1000 characters
- CSV rows limited to 5000

**Commit:** `3e7f2b1` — Extract wl_validation.py, add 25 unit tests
**Code Reference:** `bin/wl_validation.py` — All 5 functions are pure with 93% test coverage

**Status:** ✓ Mitigated

---

### 3. Reserved Prefix Convention Enforcement

**Vulnerability:** Analyst creates a CSV column named `_hidden`. This column:
- Is filtered from diffs (mistaken for internal metadata)
- Cannot be edited (internal columns are read-only)
- Could overwrite internal columns (`_added_by`, `_added_at`) if not explicitly whitelisted

**Root Cause:** Underscore-prefixed columns were used for internal metadata but not restricted at input.

**Mitigation:**
- Whitelist internal columns explicitly: `_added_by`, `_added_at`, `_review_status`
- Reject any user-provided column starting with `_` that is not in the whitelist
- Validation occurs at both frontend (for UX feedback) and backend (for security)

**Commit:** `5c3a9e2` — Add internal column whitelist in wl_csv.py
**Code Reference:** `bin/wl_csv.py::INTERNAL_COLUMNS` — whitelist constant

**Status:** ✓ Mitigated

---

### 4. RBAC Bypass (Missing Role Checks in Approval Paths)

**Vulnerability:** Admin approval handler (`approve_request`) only checked if requester was admin, not if CURRENT user is admin. Analyst could trigger approval action.

**Root Cause:** Role check was incomplete; only one gate checked when multiple gates were needed.

**Mitigation:**
- **Gate 1:** Handler entry — `is_admin(roles)` check before entering approve_request()
- **Gate 2:** Approval action — Explicit `analyst != current_user` check (admins cannot approve own requests)
- **Gate 3:** Request validation — Precondition checks (rule exists, CSV exists, analyst exists)
- All role checks sourced from Splunk's `/services/authentication/current-context` API

**Commit:** `39d37ef` — Add comprehensive RBAC checks in wl_approval.py
**Code Reference:** `bin/wl_approval.py::approve_request()` — All three gates present

**Status:** ✓ Mitigated

---

### 5. Set vs. Counter Bug (Duplicate Row Tracking)

**Vulnerability:** App used Python `set()` to track duplicate rows in diffs. If CSV had rows:
- Old: `[{user: "jsmith"}, {user: "jsmith"}]` (same user twice)
- New: `[{user: "jsmith"}]` (same user once)
- Set operation: `{jsmith} - {jsmith} = {}` (lost count info; falsely reported 0 duplicates)

**Root Cause:** Sets are unordered and don't track multiplicities. Duplicate-aware diff required `Counter`.

**Mitigation:**
- Use `collections.Counter` instead of `set()` for all multiset operations
- Counter preserves duplicate counts: `Counter({user: 2}) - Counter({user: 1}) = Counter({user: 1})`
- Applied across: `_compute_diff()`, `added_row_map`, `_removed_row_map`, approval replay paths

**Commit:** `4a2f8d9` — Replace set() with Counter() in wl_csv.py and approval handlers
**Code Reference:** `bin/wl_csv.py::_compute_diff()` — Uses Counter for duplicate tracking

**Status:** ✓ Mitigated

---

### 6. State Sync Contract Violation (Data Loss on Row Add)

**Vulnerability:** "Add Row" button didn't sync user-typed data from DOM inputs into the `currentRows` array before appending a new row. If analyst typed data in cells and clicked "Add Row" again, previous row's data was lost.

**Root Cause:** Table refresh logic didn't call `syncInputs()` to capture pending edits before mutation.

**Mitigation:**
- Enforce contract: **Always call `syncInputs()` before `refreshTable()`**
- `syncInputs()` scans all `<input>` elements in the table and copies values into the data model
- All mutation handlers check for unsaved rows and warn user before proceeding

**Commit:** `2e1d4c5` — Add syncInputs() guard in whitelist_manager.js handlers
**Code Reference:** `appserver/static/whitelist_manager.js::onAddRow()` — Calls syncInputs before mutation

**Status:** ✓ Mitigated

---

## Part 5: Security Recommendations

### For Splunk Administrators

1. **Role Assignment:** Assign app roles through Splunk's Settings > Access Controls > Roles
   - `wl_viewer` to analysts who should only read whitelists
   - `wl_editor` to analysts who need edit permissions
   - `wl_admin` to security team leads (approval authority)
   - `wl_superadmin` to system owner only

2. **Session Timeout:** Configure Splunk session timeout (recommended: 8 hours for interactive, 1 hour for API)

3. **Audit Index Retention:** Configure `wl_audit` index retention policy (recommend: 1 year minimum for compliance)

4. **TLS/HTTPS:** Ensure Splunk enforces HTTPS on port 8000 (web UI) and 8089 (REST API)

5. **Network Segmentation:** Restrict access to port 8089 (REST API) to trusted networks only

6. **Monitoring:** Monitor the `wl_audit` index for:
   - Bulk removals (potential whitelist bypass)
   - Unexpected reverts (potential undoing of security controls)
   - Failed attempts (repeated 403 Forbidden responses)

### For Security Auditors

1. **Test RBAC:** Verify analysts with `wl_editor` role cannot access the approval UI
2. **Test Input Validation:** Submit oversized CSVs, path traversal filenames, control characters — all should be rejected
3. **Test Audit Trail:** Edit a CSV and verify audit event appears in `wl_audit` index with correct before/after values
4. **Test Rate Limiting:** Submit 30+ requests in 60 seconds; verify 429 Too Many Requests on excess
5. **Test Approval Gate:** Bulk edit 3+ rows as analyst; verify request goes to approval queue, not direct CSV write

### For Developers

1. **Principle of Least Privilege:** When adding features, use the minimal privilege gate needed
2. **Defense in Depth:** Implement validation at multiple layers (frontend UX + backend validation)
3. **Never Trust Client Data:** Always re-validate server-side (role, action type, request ID)
4. **Trace Data Flows:** When modifying diff/audit logic, trace data from input → processing → output
5. **Test Edge Cases:** Adversarial scenarios from MEMORY.md (concurrent edits, out-of-order approvals, duplicate handling)

---

## Part 6: Compliance & Standards

### Security Standards Alignment

- **Authentication:** Splunk session tokens (RFC 6749 Bearer Token pattern)
- **Authorization:** Role-based access control (RBAC) per NIST SP 800-53 AC-3
- **Audit:** Immutable append-only log per NIST SP 800-53 AU-3
- **Input Validation:** OWASP Top 10 A03:2021 Injection control
- **Rate Limiting:** OWASP Rate Limiting pattern for DoS mitigation
- **Encryption in Transit:** TLS 1.2+ (enforced by Splunk)

### Data Classification

| Data | Classification | Retention | Compliance |
|------|-----------------|-----------|-----------|
| Detection rule whitelists | Confidential | 1+ years (configurable) | SOC operational data |
| Audit trail (wl_audit index) | Sensitive | 1+ years (recommend: 3+ for compliance) | Immutable log for investigations |
| User presence data | Non-sensitive | 24 hours | Session activity tracking |
| Daily usage statistics | Sensitive | 30 days (configurable) | Billing/metering data |
| Approval queue requests | Sensitive | 30 days (auto-expire) | Temporary workflow state |

---

## Part 7: Known Limitations & Future Work

### Current Limitations

1. **File-based Concurrency:** CSV updates use file-level locking (advisory locks). High-concurrency scenarios (10+ simultaneous editors) may experience lock contention.

2. **Rate Limiting Scope:** Rate limits are per-user, per-action type. No global/system-level rate limiting (would require Splunk rate limit policies).

3. **Approval Notifications:** Approval queue is pull-based (users must refresh to see new approvals). Real-time push notifications require Splunk Enterprise Message Queue (EMQ) or external webhook integration.

4. **Audit Query Performance:** The `wl_audit` index is append-only; querying large time ranges may have latency. Recommend indexes with time-series optimization.

### Future Security Enhancements

1. **Approval Signatures:** Digitally sign approved requests (requires PKI infrastructure)
2. **Encryption at Rest:** Encrypt CSV files on disk (requires key management system)
3. **Multi-Factor Authentication (MFA):** Require MFA for admin actions (requires Splunk MFA integration)
4. **API Rate Limiting by IP:** Add IP-based rate limiting to prevent DoS from compromised accounts
5. **Suspicious Activity Alerts:** Automatically alert on bulk removals or unusual approval patterns

---

## Appendix: Security Testing Checklist

Use this checklist when deploying updates or reviewing security posture:

- [ ] All POST endpoints require `is_admin` or `is_editor` check
- [ ] All user inputs are validated with `wl_validation` functions
- [ ] All file paths use `safe_realpath()` and `is_safe_filename()`
- [ ] All CSV writes check optimistic lock (expected_mtime)
- [ ] All audit events are constructed with server-side diffs (not frontend-provided)
- [ ] All role checks fetch roles from Splunk API (not cached, not from request)
- [ ] All timestamps are server-generated (not client-provided)
- [ ] Rate limiting middleware is active on POST endpoints
- [ ] Approval queue prevents analyst self-approval
- [ ] Internal columns are whitelisted; underscore-prefixed columns are rejected
- [ ] CSV size limits (5000 rows, 100 columns, 1000 chars/cell) are enforced
- [ ] HTTP response headers include `X-Content-Type-Options: nosniff`
- [ ] Splunk REST calls use `raiseException=False` to prevent unhandled exceptions
- [ ] Audit events are posted non-blocking (failures logged, not fatal)

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-02 | Initial comprehensive security architecture document |
| 1.1 | 2026-05-22 | Added Part 2A (Hardening Mechanisms): HMAC-signed state, FIM dual-path scripts, Emergency Lockdown, rate-limit + daily-limit + approval-queue triad, strict-ASCII dual-gate validation, Sigstore release signing, post-compromise attribution via Splunk `_audit`. Updated Roles Defined table with modern names + backward-compat aliases. |

---

**Questions or Concerns?** Contact the security team. This document is a living document and should be updated as threats are discovered and mitigations implemented.
