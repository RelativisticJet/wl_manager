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

The application defines four security tiers with progressive permissions:

| Role | Layer | Purpose |
|------|-------|---------|
| **wl_viewer** | Read-only | Security analysts viewing whitelist state and audit trail (passive monitoring) |
| **wl_editor** | Analyst | SOC analysts editing whitelists with approval gates for bulk operations |
| **wl_admin** | Administrator | Approval authority; controls policy limits and usage thresholds |
| **wl_superadmin** | System Owner | Manages trash retention, limit policies, and system configuration |

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

---

**Questions or Concerns?** Contact the security team. This document is a living document and should be updated as threats are discovered and mitigations implemented.
