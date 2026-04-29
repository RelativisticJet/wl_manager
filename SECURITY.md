# Security Policy

## Supported Versions

| Version | Supported |
| --- | --- |
| 2.0.x | Yes |
| 1.0.x | No |

## Reporting a Vulnerability

If you discover a security vulnerability in Whitelist Manager, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Email the details to the repository maintainer via GitHub's private messaging or open a [private security advisory](https://github.com/RelativisticJet/wl_manager/security/advisories/new)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge receipt within 48 hours and aim to release a fix within 7 days for critical issues.

## Coordinated Disclosure Timeline

We follow a coordinated-disclosure model. Default timeline once a report is acknowledged:

| Phase | Target |
| --- | --- |
| Acknowledgement | 48 hours after report received |
| Triage + initial severity assessment | 5 days |
| Fix shipped (CRITICAL / HIGH) | 7 days |
| Fix shipped (MEDIUM) | 30 days |
| Fix shipped (LOW) | Next regular release |
| Public disclosure | 90 days from initial report, OR after a fix is shipped, whichever is sooner |

We may negotiate the public-disclosure date if a fix is in active development at day 90 — please engage with us before publishing if so. We never silently drop a report; if we decide an issue is out of scope or non-exploitable, we explain the reasoning and you are free to publish on your timeline.

## Scope

**In scope** (please report):

- All code under `bin/` (REST handler, scripted inputs, helpers)
- All code under `appserver/static/` (frontend modules)
- Splunk configuration under `default/` (RBAC, restmap, savedsearches, etc.)
- Recovery scripts under `scripts/`
- The .spl release artifact and the build pipeline that produces it
- Any vulnerability that allows: bypassing approval gates, bypassing rate limits, escalating role, forging audit events, suppressing alerts, modifying CSVs without a corresponding audit record, or exfiltrating session keys

**Out of scope** (typically forward elsewhere):

- Vulnerabilities in Splunk Enterprise itself — report to [Splunk's bug bounty / security team](https://www.splunk.com/en_us/product-security.html)
- Vulnerabilities in third-party packages we depend on — please file with the upstream project; we'll track via Dependabot
- Issues that require an attacker to already hold superadmin / `admin` role on the Splunk instance (that role is total compromise by design)
- Denial of service via legitimate but high-volume use of approved actions (this is rate-limit configuration, not a vuln)
- Theoretical issues with no demonstrated exploit path

If you are unsure whether your finding is in scope, report it anyway — we'd rather route a misfiled report than miss a real one.

## Safe Harbor

We commit to the following for security researchers acting in good faith:

- We will not pursue legal action under the CFAA, DMCA, or equivalent statutes against research that is consistent with this policy
- We will not request that hosting providers, ISPs, or law enforcement take action against you
- We will work with you to understand and resolve the issue quickly
- We will publicly credit you in the release notes for the fix (unless you prefer to remain anonymous)

This safe harbor applies to research that:

- Targets only the Whitelist Manager codebase (not the Splunk core, the OS, or third-party services)
- Avoids accessing or exfiltrating data belonging to other users
- Stops at proof-of-concept depth — does not pivot, persist, or destroy
- Reports findings via the channels above before any public disclosure

If you reasonably believe your work falls under this safe harbor, you are authorized to perform the testing.

## Recognition

Researchers whose reports lead to a fix are listed in the release notes for the build that contains the fix, unless they request anonymity. We do not currently offer monetary bounties. The historical record (v2.0.0 review, 2026-03-22) is captured in the section below — future fixes will append to that history.

## Security Architecture

The Whitelist Manager implements defense-in-depth:

- **Authentication**: All REST endpoints require Splunk authentication (`requireAuthentication = true`)
- **Authorization**: Server-side RBAC checks on every POST request via Splunk's REST API
- **Input validation**: Path traversal protection (`_safe_filename`, `_safe_realpath`), input sanitization (`_sanitize_text`), payload size limits
- **Rate limiting**: Per-user sliding window rate limiter for read and write operations
- **Audit integrity**: All data modifications produce tamper-evident audit events in a dedicated Splunk index
- **Concurrency control**: Optimistic locking via file mtime prevents silent data loss from concurrent edits
- **Approval gates**: Bulk operations above configurable thresholds require admin approval

### Full Security Architecture Documentation

For a comprehensive threat model, STRIDE analysis, DREAD scoring, and detailed security design documentation suitable for security auditors and compliance reviews, see **[docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md)**.

This document includes:
- Executive summary for Splunk administrators
- Detailed threat model using STRIDE methodology
- DREAD risk scoring for top threats
- Evidence of mitigated vulnerabilities identified during development
- RBAC matrix with all role capabilities
- Data flow diagrams (Mermaid format)
- Security testing checklist

## Security Review History

- **v2.0.0** (2026-03-22): Comprehensive security review with active exploitation testing. Fixed RBAC bypass in approval cancel path, audit log injection via `log_event`, client-controllable `_bulk_edit_count`, and approval request ID injection. See commit `39d37ef`.
