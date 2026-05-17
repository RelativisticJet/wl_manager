# Whitelist Manager for Splunk

**A web UI for managing Splunk detection-rule CSV whitelists — with approval workflows, version control, and a full diff-based audit trail.**

Built for SOC teams who need to manage detection-rule exceptions without
touching raw CSV files, Splunk configs, or the filesystem.

---

## What it does

Whitelist Manager replaces the typical "open the CSV in a text editor, save
it, commit it, hope nothing breaks" workflow for detection-rule exceptions
with a managed, audited UI inside Splunk Enterprise / Splunk Enterprise
Security.

Analysts:

- Pick a detection rule from a dropdown.
- See the current whitelist as an editable table — with search,
  pagination, and inline cell editing.
- Add, remove, edit, and bulk-edit rows; required removal reason; optional
  per-row expiration date.
- Submit larger changes for admin approval.
- Revert to any of the last 6 versions, with the revert itself audited.

Admins:

- Approve / reject pending changes from a Control Panel.
- Configure per-analyst daily limits, approval thresholds, and per-CSV
  RBAC.
- See real-time usage and the full audit trail in dedicated dashboards.

Every change — by analysts and admins alike — is diff-logged to a
dedicated `wl_audit` index in Splunk, with before/after values for
edits, structured fields for filtering, and a built-in audit dashboard.

---

## Get started

If you are a **Splunk admin** installing this on a fresh Splunk
Enterprise / Splunk Enterprise Security host:

[Splunk Admin Installation Guide :material-arrow-right:](Splunk_Admin_Installation_Guide.md){ .md-button .md-button--primary }

If you want to **try it before installing** on your own Splunk, the
project ships a Docker Compose file that brings up Splunk 9.3.1 + the
app on `http://localhost:8000`. See the [README on
GitHub](https://github.com/RelativisticJet/wl_manager#docker-demo-try-before-installing)
for the one-command quick start.

If you are a **SOC analyst or admin** who has the app installed and
wants to learn the UI, the **User Guide** walks through every screen:

[Whitelist Manager User Guide :material-arrow-right:](Whitelist_Manager_Documentation.md){ .md-button }

---

## Key features

### Editing

- Inline cell editing with before/after change tracking.
- Required removal reason on every row removal.
- Per-row expiration dates with presets (7d, 30d, 6mo, 1yr) or custom
  date/time.
- CSV import / export with diff preview before save.
- Add/remove columns; reorder rows.
- Polished dark theme (light theme intentionally removed; see
  [Decision Log](https://github.com/RelativisticJet/wl_manager/blob/main/docs/DECISION_LOG.md)).

### Approval workflows

- Per-analyst daily limits (rows added, removed, edited, reverted).
- Bulk-edit approval thresholds, separately configurable per CSV.
- Dual-admin approval for destructive admin actions.
- Self-approval prevention: a submitter cannot approve their own
  request.
- Replay-aware approval: when an admin approves, the original analyst's
  intended change is executed exactly, with the gate-bypass flag scoped
  to that one replay.

### Audit trail

- Every change diff-logged to a dedicated `wl_audit` Splunk index.
- Per-field before/after for every cell edit.
- Structured fields for filtering (analyst, rule, action, time range).
- Dedicated audit dashboard with summary stats and an expiring-soon panel.

### Security

- Server-side RBAC enforcement on every request (frontend visibility
  is a UX hint, not a security boundary).
- Path-traversal protection on every CSV path.
- ASCII-only validation on entity names that flow into filesystem paths
  or audit logs (closes homoglyph / bidi / null-byte attack surface).
- Rate limiting on every admin action, with tamper-detected counters.
- KV-store cooldowns with HMAC integrity (a tampered counter
  fails-closed; the app refuses to admit a new admin action until the
  state is repaired via the documented recovery procedure).
- File Integrity Monitor (FIM) watches the handler, configs, and CSV
  hash registry every ~15s.
- Release artifacts are Sigstore-signed; verification command and Rekor
  entry confirmation are documented in the
  [SBOM & Signing](SBOM.md) page.

See [Security Architecture](SECURITY_ARCHITECTURE.md) for the full
threat model and defense layout.

---

## What this app is **not**

- It is **not** a content pack or a detection-rule library. You bring
  your own rules; this app manages the exceptions to them.
- It is **not** a generic CSV editor. The schema and lifecycle assume
  Splunk lookup files with the audit-trail conventions described above.
- It is **not** affiliated with or endorsed by Splunk LLC. See the
  trademark notice on the [GitHub
  README](https://github.com/RelativisticJet/wl_manager#trademark-notice).

---

## Source, releases, and support

- **Source**: [github.com/RelativisticJet/wl_manager](https://github.com/RelativisticJet/wl_manager)
- **Releases**: [GitHub Releases](https://github.com/RelativisticJet/wl_manager/releases) — signed `.spl` artifacts
- **Issues**: [GitHub Issues](https://github.com/RelativisticJet/wl_manager/issues)
- **Security reports**: see the [Security Policy](https://github.com/RelativisticJet/wl_manager/security/policy)
- **Response SLA**: see the [Response Expectations](https://github.com/RelativisticJet/wl_manager/blob/main/CONTRIBUTING.md#response-expectations) section in CONTRIBUTING.md — best-effort, single maintainer

---

## License

MIT — see [LICENSE](https://github.com/RelativisticJet/wl_manager/blob/main/LICENSE).
