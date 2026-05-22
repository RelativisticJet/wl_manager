# Whitelist Manager for Splunk

<!--
  Version badge auto-updates from the latest GitHub Release (including
  pre-releases like v1.0.0-rc1 during the public hold period). Once a
  non-prerelease tag is cut (Phase 3.8 GA), the badge updates
  automatically. Do NOT hardcode the version here.

  Splunk badge auto-sources from app.manifest via shields.io's
  dynamic/json endpoint — bumping platformRequirements.splunk.Enterprise
  in app.manifest updates the badge with no README edit needed.
-->
[![Version](https://img.shields.io/github/v/release/RelativisticJet/wl_manager?include_prereleases&label=version&color=blue)](https://github.com/RelativisticJet/wl_manager/releases)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)
[![Splunk](https://img.shields.io/badge/dynamic/json?url=https://raw.githubusercontent.com/RelativisticJet/wl_manager/main/app.manifest&label=Splunk&query=%24.platformRequirements.splunk.Enterprise&color=orange)](https://www.splunk.com/)
[![Python](https://img.shields.io/badge/Python-3.9+-yellow.svg)](https://www.python.org/)
[![Docs](https://img.shields.io/badge/docs-relativisticjet.github.io%2Fwl__manager-blue?logo=readthedocs&logoColor=white)](https://relativisticjet.github.io/wl_manager/)

A web UI for managing Splunk Enterprise Security detection-rule CSV
whitelists — with inline editing, approval workflows, version control,
and a full diff-based audit trail.

Built for SOC teams who need to manage detection-rule exceptions
without touching raw CSV files, Splunk configs, or the filesystem.

> **Documentation:** the full user guide, security architecture, runbooks,
> and SBOM live on the hosted docs site at
> [**relativisticjet.github.io/wl_manager**](https://relativisticjet.github.io/wl_manager/)
> (deploys at Phase 3.4 public flip; until then, read directly from
> [`docs/`](docs/) in this repo).

## Screenshots

**Main Dashboard** — Inline editing with change tracking, search, pagination, and bulk operations

![Main Dashboard](docs/screenshots/01-main-dashboard.png)

**Inline Editing** — Click any cell to edit. Modified cells are highlighted for review before saving.

![Inline Editing](docs/screenshots/02-inline-editing.png)

**Audit Trail** — Complete audit dashboard with summary stats, filters, and approval tracking

![Audit Trail](docs/screenshots/03-audit-trail.png)

**Control Panel** — Admin-only dashboard for approval queue, analyst usage, and limit configuration

![Control Panel](docs/screenshots/04-control-panel.png)

## Features

### Core Editing

- Inline cell editing with change tracking (before/after diffs)
- Add, remove, and bulk-edit rows with required comments
- Add and remove columns
- Row drag-and-drop reordering
- CSV import/export
- Search and filter rows
- Polished dark theme (light theme intentionally removed in build 637 (2026-05-01) — see CHANGELOG)

### Approval Workflows

- Configurable thresholds trigger admin approval for bulk operations
- Daily usage limits per analyst (row removals, edits, additions, reverts)
- Admins approve/reject/cancel requests from the Control Panel
- Self-approval prevention — submitter cannot approve their own request

### Version Control

- Every save creates a timestamped snapshot (last 6 versions retained)
- Revert to any previous version with full audit trail
- Optimistic locking — concurrent edits detected via file mtime

### Audit Trail

- Every change logged to a dedicated `wl_audit` Splunk index
- Diff-based events: added, removed, edited, revert, auto-removed
- Per-field before/after values for edits
- Dashboard with summary stats, filters by analyst/rule/action/time
- Expiring-soon panel for proactive review

### Security

- Role-based access control: `wl_admin`, `wl_analyst_editor`, `wl_analyst_viewer`
- Server-side RBAC enforcement on every request
- Path traversal protection, input sanitization, rate limiting
- Control Panel restricted to admin roles
- Release artifacts are Sigstore-signed; see [docs/SBOM.md](docs/SBOM.md#verifying-a-release-with-cosign) for the cosign verification command

### Row Expiration

- Set expiration dates with presets (7d, 30d, 6mo, 1yr) or custom date/time
- Expired rows auto-removed on CSV load and via hourly scheduled cleanup
- Expiring-soon alerts in the Audit Trail dashboard

## Quick Start

### Docker Demo (Try Before Installing)

```bash
# Clone and start
git clone https://github.com/RelativisticJet/wl_manager.git
cd wl_manager
docker compose up -d

# Wait ~90 seconds for Splunk to start, then open:
# http://localhost:8000  (admin / Chang3d!)
```

Navigate to **Apps > Whitelist Manager** to start using the app.

### Install on Existing Splunk

Download the latest `.spl` from the [Releases](https://github.com/RelativisticJet/wl_manager/releases) page. Replace `<VERSION>` in the commands below with the release tag you downloaded (e.g., `1.0.0-rc1`).

**Option A — Splunk Web UI:**

1. Go to **Apps > Manage Apps > Install app from file**
2. Upload `wl_manager-<VERSION>.spl`
3. Restart Splunk when prompted

**Option B — CLI:**

```bash
$SPLUNK_HOME/bin/splunk install app wl_manager-<VERSION>.spl
$SPLUNK_HOME/bin/splunk restart
```

**Option C — Manual:**

```bash
tar -xzf wl_manager-<VERSION>.spl -C $SPLUNK_HOME/etc/apps/
chown -R splunk:splunk $SPLUNK_HOME/etc/apps/wl_manager
$SPLUNK_HOME/bin/splunk restart
```

## Post-Installation Setup

### 1. Create User Roles

The app ships with three roles in `authorize.conf`. Assign them to your users via **Settings > Access Controls > Roles**:

| Role | Can View | Can Edit | Control Panel | Inherits |
|------|----------|----------|---------------|----------|
| `wl_admin` | Yes | Yes | Yes | `power` |
| `wl_analyst_editor` | Yes | Yes | No | `power` |
| `wl_analyst_viewer` | Yes | No | No | `user` |

Legacy roles `wl_editor` and `wl_viewer` are supported for backward compatibility.

### 2. Map Your Detection Rules

Edit `lookups/rule_csv_map.csv` to map your detection rules to CSV lookup files:

```csv
rule_name,csv_file,app_context
DR55_brute_force_login,DR55_brute_force_users.csv,wl_manager
DR130_privilege_escalation,DR130_priv_escalation.csv,wl_manager
```

- `rule_name` — display name in the Detection Rule dropdown
- `csv_file` — the CSV lookup file in the app's `lookups/` directory
- `app_context` — the Splunk app containing the CSV (usually `wl_manager`)

The packaged `.spl` ships with an empty `rule_csv_map.csv` — populate
it with your own detection rules. The repo includes a small set of
demo CSVs under `lookups/` for screenshots and tests; these are
excluded from the published `.spl` (see `scripts/package.sh`).

### 3. Verify the Audit Index

The app creates a `wl_audit` index automatically via `indexes.conf`. Verify it exists:

```spl
| eventcount index=wl_audit
```

### 4. Configure Daily Limits (Optional)

Admins can configure per-analyst daily limits from the **Control Panel > Limits & Permissions** tab:

- Row additions, removals, edits (default: 10/day each)
- Column additions and removals (default: 2/day each)
- Reverts (default: 3/day)
- Approval thresholds for bulk operations (default: 3+ rows)

## Architecture

```text
wl_manager/
  bin/wl_handler.py              # REST handler (all server logic)
  appserver/static/
    whitelist_manager.js          # Main dashboard controller
    whitelist_manager.css         # Styles (dark/light theme)
    control_panel.js              # Admin Control Panel
    notifications.js              # Approval notification system
  default/
    app.conf                      # App metadata
    restmap.conf                  # REST endpoint config
    authorize.conf                # RBAC role definitions
    indexes.conf                  # wl_audit index
    savedsearches.conf            # Expiration alert
    data/ui/views/
      whitelist_manager.xml       # Main dashboard
      audit.xml                   # Audit trail dashboard
      control_panel.xml           # Admin panel
  lookups/
    rule_csv_map.csv              # Detection rule -> CSV mapping
```

### How It Works

1. **Frontend** (JavaScript + jQuery) builds the entire UI dynamically inside Splunk SimpleXML panels
2. **Backend** (`wl_handler.py`) is a `PersistentServerConnectionApplication` handling GET/POST at `/custom/wl_manager`
3. **Diff engine** uses similarity-based matching to correctly detect edits even when rows are simultaneously removed
4. **Audit events** are written directly to the `wl_audit` index via Splunk's REST API
5. **Version snapshots** are stored in `lookups/_versions/` with a JSON manifest

## Development

### Prerequisites

- Docker and Docker Compose
- Git Bash (Windows) or any Unix shell
- Python 3.9+ (for validation)

### Development Workflow

```bash
# Start dev environment
make docker-up
make docker-wait

# After code changes
make validate         # Run AppInspect-style checks
make test             # Run integration tests

# Build release package
make package          # Outputs dist/wl_manager-VERSION.spl
```

### Adding a New Detection Rule

1. Create a CSV file in `lookups/` with your column headers
2. Add a row to `lookups/rule_csv_map.csv`
3. The new rule appears in the dashboard dropdown immediately (no code changes needed)

## Requirements

- Splunk Enterprise **9.3** (the only version on Splunk's currently-supported list as of 2026-05; tested on 9.3.1)
- Python 3 (bundled with Splunk 9)
- ~10 MB disk space for the app + audit data
- A modern desktop browser (Chrome, Firefox, Edge) at **1280×720 minimum**.
  Whitelist Manager is designed for SOC-analyst desktop workflows;
  Splunk Web itself is not mobile-optimized, so mobile/tablet layouts
  are out of scope.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.

## Contributing

Issues and pull requests welcome at [github.com/RelativisticJet/wl_manager](https://github.com/RelativisticJet/wl_manager).

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR — especially the
**Security CI (Semgrep Taint Rules)** section. Every PR runs three Splunk-adapted
Semgrep rules that gate against SSRF, command injection, and path traversal.
If you add a new validation wrapper (e.g. a path or URL sanitizer), update the
corresponding `tests/semgrep/*-splunk.yaml` `pattern-sanitizers` list in the
same PR, or legitimate callers of your wrapper will trip the rule.

## 💖 Support This Project

Whitelist Manager is built and maintained on personal time. If it saves your
SOC effort — or you'd like to see it keep evolving — you can support the work:

- **[Sponsor on GitHub](https://github.com/sponsors/RelativisticJet)** — one-time
  or monthly contributions, any tier
- **Star the repo** — helps other SOC teams discover the project
- **Report issues** — bugs found during the v1.0.0-rc1 public hold period are
  high-leverage; see [CONTRIBUTING.md](CONTRIBUTING.md) for the response-SLA
  policy

Sponsorships fund focused time on Whitelist Manager (post-rc1 priorities:
dark-theme polish, multi-org adaptability, richer approval workflows) and on
new open-source SOC tooling in the same audit-first, solo-maintainer-friendly
style.

## Trademark Notice

Splunk, Splunk Enterprise, and Splunk Enterprise Security are registered
trademarks of Splunk LLC in the United States and other countries. This
project is an independent community tool — it is not affiliated with,
endorsed by, or sponsored by Splunk LLC. All other product names, logos,
and brands are property of their respective owners.
