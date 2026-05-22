# Security Policy

## Supported Versions

Security fixes are issued for the current 1.x release line. The
authoritative current version lives in `default/app.conf`
(`[launcher].version`) and `app.manifest`
(`info.id.version`).

| Version line | Supported |
| --- | --- |
| 1.0.x (current) | Yes — actively maintained |
| Pre-1.0 development builds | No — never shipped publicly |

When a 2.x release line is opened, this table will be updated to
reflect the supported window for each major.

## Reporting a Vulnerability

If you discover a security vulnerability in Whitelist Manager,
please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Open a [private security advisory](https://github.com/RelativisticJet/wl_manager/security/advisories/new),
   or contact the maintainer via the GitHub profile listed in
   `app.manifest` (`info.author[0]`)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge receipt within 48 hours and aim to release a
fix within 7 days for CRITICAL issues.

## Coordinated Disclosure Timeline

We follow a coordinated-disclosure model. Default timeline once a
report is acknowledged:

| Phase | Target |
| --- | --- |
| Acknowledgement | 48 hours after report received |
| Triage + initial severity assessment | 5 days |
| Fix shipped (CRITICAL / HIGH) | 7 days |
| Fix shipped (MEDIUM) | 30 days |
| Fix shipped (LOW) | Next regular release |
| Public disclosure | 90 days from initial report, OR after a fix is shipped, whichever is sooner |

We may negotiate the public-disclosure date if a fix is in active
development at day 90 — please engage with us before publishing if
so. We never silently drop a report; if we decide an issue is out
of scope or non-exploitable, we explain the reasoning and you are
free to publish on your timeline.

## Scope

**In scope** (please report):

- All code under `bin/` (REST handler, scripted inputs including
  `wl_fim.py` and `wl_fim_watch.py`, helpers)
- All code under `appserver/static/` (frontend AMD modules)
- Splunk configuration under `default/` (RBAC, restmap, indexes,
  inputs, collections, savedsearches)
- Recovery scripts under `scripts/` (`emergency_unlock.sh`,
  `reset_cooldowns.sh`, `fim_deploy_window.sh`, etc.)
- The `.spl` release artifact and the Sigstore-signed release
  pipeline that produces it
- Any vulnerability that allows: bypassing approval gates,
  bypassing rate limits or daily limits, escalating role across
  the `wl_analyst_viewer` → `wl_analyst_editor` → `wl_admin` →
  `wl_superadmin` tiers, forging audit events, suppressing FIM
  alerts, modifying CSVs without a corresponding audit record,
  forging HMAC-signed state (cooldowns, FIM baseline, CSV
  expected-hash registry, lockdown sentinel, deploy-window token),
  bypassing Emergency Lockdown, or exfiltrating session keys

**Out of scope** (typically forward elsewhere):

- Vulnerabilities in Splunk Enterprise itself — report to
  [Splunk's product security team](https://www.splunk.com/en_us/product-security.html)
- Vulnerabilities in third-party packages we depend on — please
  file with the upstream project; we track via Dependabot
- Issues that require an attacker to already hold `wl_superadmin`
  or built-in Splunk `admin` role (those tiers are total compromise
  by design — see `docs/SECURITY_ARCHITECTURE.md` for the
  post-compromise attribution path via Splunk's `_audit` index)
- Denial of service via legitimate but high-volume use of approved
  actions (this is rate-limit configuration, not a vuln)
- Theoretical issues with no demonstrated exploit path

If you are unsure whether your finding is in scope, report it
anyway — we'd rather route a misfiled report than miss a real one.

## Safe Harbor

We commit to the following for security researchers acting in good
faith:

- We will not pursue legal action under the CFAA, DMCA, or
  equivalent statutes against research that is consistent with
  this policy
- We will not request that hosting providers, ISPs, or law
  enforcement take action against you
- We will work with you to understand and resolve the issue quickly
- We will publicly credit you in the release notes for the fix
  (unless you prefer to remain anonymous)

This safe harbor applies to research that:

- Targets only the Whitelist Manager codebase (not Splunk core,
  the host OS, or third-party services)
- Avoids accessing or exfiltrating data belonging to other users
- Stops at proof-of-concept depth — does not pivot, persist, or
  destroy
- Reports findings via the channels above before any public
  disclosure

If you reasonably believe your work falls under this safe harbor,
you are authorized to perform the testing.

## Recognition

Researchers whose reports lead to a fix are listed in the release
notes for the build that contains the fix, unless they request
anonymity. We do not currently offer monetary bounties.

## Security Architecture

The Whitelist Manager implements defense-in-depth across the REST
handler, scripted inputs, and supporting infrastructure:

- **Authentication**: All REST endpoints require Splunk
  authentication (`requireAuthentication = true` in
  `default/restmap.conf`)
- **4-tier RBAC**: `wl_superadmin` / `wl_admin` /
  `wl_analyst_editor` / `wl_analyst_viewer` (plus backward-compat
  aliases `wl_editor` / `wl_viewer`) — see `default/authorize.conf`
- **Input validation**: Path-traversal protection, strict-ASCII
  validation on detection rule names + CSV filenames + approval
  reasons, payload size limits, JSON sanitization
- **Rate limiting + daily limits**: Sliding-window per-user rate
  limiter and per-tier daily action caps backed by the
  `wl_cooldowns` and `wl_ratelimit_state` KV collections; both
  HMAC-signed with a runtime-derived key
- **Approval gates**: Configurable per-action approval workflow;
  destructive actions (rule/CSV delete, bulk edits above
  threshold, trash purge) require an `wl_admin` to approve before
  execution
- **Emergency Lockdown**: System-wide write freeze activatable by
  any `wl_superadmin`; deactivation requires a DIFFERENT
  `wl_superadmin` (self-unlock blocked); narrow exempt-action set
  documented in CLAUDE.md
- **File Integrity Monitoring**: `wl_fim.py` runs a 15-second
  cryptographic scan on critical source/sentinel files;
  `wl_fim_watch.py` is a persistent ~2-second stat-based watcher
  for near-real-time detection of CSV mutations. Dual-store
  baseline (filesystem + `wl_fim_baseline` KV collection) catches
  attackers who tamper with one store
- **CSV expected-hash registry**: HMAC-signed registry detects
  out-of-band CSV modifications (SPL `| outputlookup`, direct FS
  writes, REST lookup edits) that bypass the handler's approval +
  rate-limit + audit pipeline
- **Audit integrity**: All data modifications produce
  tamper-evident events in a dedicated `wl_audit` index; recovery
  actions (emergency unlock, cooldown reset) are tailed from an
  append-only `_recovery_log.jsonl` so out-of-band actions can't
  be suppressed
- **Concurrency control**: Cross-process file locking
  (`bin/wl_filelock.py`, fcntl-based) on every shared-state RMW;
  optimistic content-hash + mtime locking on CSV saves
- **Release signing**: `.spl` artifacts are Sigstore-keyless-signed
  by the GitHub Actions release workflow. Operators verify via
  `cosign verify-blob` before install — canonical command in
  `docs/SBOM.md`

### Full security architecture documentation

For the threat model, STRIDE analysis, DREAD scoring, RBAC matrix,
data flow diagrams, security-testing checklist, and evidence of
mitigated vulnerabilities, see **[docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md)**.

Operational and recovery procedures live in
**[docs/RUNBOOKS.md](docs/RUNBOOKS.md)** — emergency-lockdown
release, cooldown counter recovery, FIM deploy windows, GUID
rotation / disaster recovery.

## Security Review History

Each major hardening pass closes with an entry here. Findings that
required a fix landed in the corresponding build (see
`default/app.conf` `[install].build` at the time of the fix
commit; `git log --grep=security` for the full timeline).

- **Comprehensive security review (2026-03-22)**: Active
  exploitation testing during pre-public hardening. Fixed RBAC
  bypass in approval cancel path, audit log injection via
  `log_event`, client-controllable `_bulk_edit_count`, and
  approval request ID injection. Reference commit `39d37ef`.
- **Ring 6 — TOCTOU + insider-threat hardening (2026-04-21 …
  2026-04-22)**: KV-backed presence + rate-limit state (closed
  per-worker state-coherence gaps), strict-ASCII validation
  dual-gate (closed homoglyph + bidi + zero-width attacks at the
  approval boundary), defense-in-depth gate audit (closed
  shape-mismatch silent bypass at 3 sites). 274/274 E2E green.
- **Ring 8 / 9 — closure (2026-04-29)**: Long-term archival
  guidance for compliance regimes (PCI DSS / HIPAA / SOX / GDPR),
  CI gates (Semgrep + doc-drift + quarterly pip-audit + Sigstore
  keyless signing). See `docs/DECISION_LOG.md` for the closure
  declaration and re-opening criteria.
- **Phase 1 — AppInspect compliance (2026-05-13 …)**: Standalone
  and cloud AppInspect verification, dynamic-findings triage.
  Baseline + per-finding triage in `docs/APPINSPECT_FINDINGS.md`.

Future reviews append here.
