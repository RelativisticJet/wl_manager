# Contributing to Whitelist Manager

Thanks for your interest in contributing! This guide covers the development setup, workflow, and guidelines.

## Development Environment

### Prerequisites

- Docker and Docker Compose
- Git Bash (Windows) or any Unix shell
- Python 3.9+

### Setup

```bash
git clone https://github.com/RelativisticJet/wl_manager.git
cd wl_manager
docker compose up -d      # Start Splunk container
make docker-wait          # Wait until Splunk is ready (~90s)
```

Open `http://localhost:8000` and log in with `admin` / `Chang3d!` (override with `SPLUNK_PASSWORD` env var).

### Pre-commit Hooks

Install the pre-commit hook to catch common issues before they reach CI:

```bash
cp scripts/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook checks for: CLAUDE.md accidentally staged, `.env` files, `console.log` in production JS, `debugger` statements, Python syntax errors, and hardcoded credentials.

### Development Workflow

1. Make changes to source files
2. Deploy to the dev container:
   ```bash
   # Copy files and restart Splunk
   MSYS_NO_PATHCONV=1 docker cp bin/wl_handler.py wl_manager_test:/opt/splunk/etc/apps/wl_manager/bin/
   MSYS_NO_PATHCONV=1 docker cp appserver/static/whitelist_manager.js wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/
   ```
3. Bump `build` in `default/app.conf` (Splunk caches JS/CSS aggressively)
4. Restart Splunk inside the container
5. Test in the browser

### Validation

```bash
make validate    # AppInspect-style checks (syntax, security, structure)
make test        # Integration tests against Docker Splunk
make package     # Build .spl package
```

## Project Structure

| Directory | Purpose |
| --- | --- |
| `bin/` | Python backend — REST handler, scheduled scripts |
| `appserver/static/` | Frontend — JavaScript controllers, CSS |
| `default/` | Splunk config files and dashboard XML |
| `lookups/` | CSV lookup files and rule mapping |
| `scripts/` | Build, validation, and test scripts |
| `docs/` | User documentation and screenshots |
| `demo/` | Docker demo scripts and guide |

## Architecture Overview

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the full codebase map, module dependency graph, and design decisions.

### Known Limitations

**`wl_handler.py` (5,200+ lines)** is the main REST endpoint and the largest file. It uses a dispatch-table pattern where each action maps to a wrapper method. The core business logic has been extracted into domain modules (`wl_csv.py`, `wl_rules.py`, `wl_approval.py`, etc.), but the action wrappers remain in the handler. Splitting the handler further is the top refactoring priority.

**Test coverage is 32%** (target: 80%). The extracted domain modules have good coverage (80-100%), but `wl_handler.py` itself has 0% — contributions that add handler-level tests are especially welcome. See [docs/CODE_METRICS.md](docs/CODE_METRICS.md) for per-module coverage.

**`control_panel.js` (2,000 lines)** has not yet been modularized like the main editor. The same AMD module pattern used in `whitelist_manager.js` can be applied here.

## Guidelines

### Code Style

- **Python**: Follow PEP 8. No `eval()`, `exec()`, or `os.system()`. Use `_sanitize_text()` for all user input written to audit logs.
- **JavaScript**: Use jQuery (bundled with Splunk). Escape all user data with `_.escape()` before `.html()`. Build UI in JavaScript, not HTML (Splunk strips most HTML from SimpleXML panels).
- **CSS**: Prefix all custom classes with `wl-` to avoid Splunk CSS conflicts.

### Security

- Never trust client-provided values for security decisions (compute server-side)
- All POST actions must check RBAC via `_get_roles()`
- Path traversal protection required for any file path from user input
- Sanitize all fields written to the audit index

### Security CI (Semgrep Taint Rules)

A GitHub Actions job ([`.github/workflows/semgrep.yml`](.github/workflows/semgrep.yml))
runs three Splunk-adapted Semgrep taint rules on every PR and every push to
`main`. The rules live in [`tests/semgrep/`](tests/semgrep/) and gate against:

- **SSRF** — user payload reaching outbound HTTP calls (`urllib.request.*`, `requests.*`) without a hardcoded-localhost prefix
- **Command injection** — payload reaching `subprocess.run(..., shell=True)` without `shlex.quote` / `shlex.join`
- **Path traversal** — payload reaching filesystem calls (`open`, `os.path.join`, `shutil.copy*`, `os.remove`, etc.) without going through `build_csv_path` / `resolve_csv_path` / `is_safe_filename` or a canonicalization sanitizer

**Run them locally before pushing** (same command CI uses):

```bash
docker run --rm \
  -v "$(pwd)/tests/semgrep:/rules:ro" \
  -v "$(pwd)/bin:/src:ro" \
  semgrep/semgrep semgrep --config=/rules --error --metrics=off /src
```

**When a finding fires — decision tree, in order:**

1. **Is it a real bug?** (Payload really does reach a sink without validation.)
   → **Fix the code.** Route the path through `build_csv_path()`, wrap the
   subprocess arg in `shlex.quote()`, validate the URL against an allowlist, etc.

2. **Did you add a new validation wrapper the rule doesn't know about?**
   (e.g. a new `validate_rule_path()` that does `basename` + `startswith(APPS_DIR)` containment)
   → **Update the rule's `pattern-sanitizers` list** in the relevant
   `tests/semgrep/*-splunk.yaml`. Add the wrapper name as a new
   `- pattern: your_wrapper(...)` entry in the **same PR** that introduces
   the wrapper. This teaches Semgrep about your new defense once, for
   everyone — otherwise every legitimate caller of your wrapper will
   trigger a false positive and the next contributor will suppress it.

3. **Is the finding architecturally impossible in that call site?**
   (e.g. the variable Semgrep flagged is actually a module-level constant
   that only *looks* like tainted data to the scanner)
   → Refactor so the scanner's reading matches reality. If truly
   unavoidable, add `# nosemgrep: <rule-id> — <one-line explanation>` on
   the line. **Never `# nosemgrep` without the explanation** — a
   suppression without context becomes permanent dead weight within a
   month.

See [tests/semgrep/README.md](tests/semgrep/README.md) for rule internals,
how Semgrep taint mode handles function boundaries, and why the non-taint
`splunk.ssrf.dynamic-url` rule is kept audit-only (not CI-gated).

### Commits

- One logical change per commit
- Prefix: `fix:`, `feat:`, `chore:`, `docs:`, `refactor:`, `test:`
- Bump `build` in `app.conf` for any JS/CSS/Python change

### Pull Requests

1. Create a feature branch from `main`
2. Make your changes with clean commits
3. Run `make validate` and `make test`
4. Open a PR with a description of what and why

## Reporting Issues

Use [GitHub Issues](https://github.com/RelativisticJet/wl_manager/issues) with the provided templates. Include your Splunk version, browser, and steps to reproduce.
