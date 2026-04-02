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
