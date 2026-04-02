# Phase 8: Splunkbase Readiness - Research

**Researched:** 2026-04-02
**Domain:** Splunkbase publication, AppInspect compliance, security architecture documentation, backward compatibility validation, code quality metrics
**Confidence:** HIGH

## Summary

Phase 8 validates the v3.0 modular rewrite for Splunkbase publication as version 1.0.0. This phase addresses five publication requirements: AppInspect compliance (PUBL-01), security architecture documentation (PUBL-02), OpenAPI REST API specification (PUBL-03), backward compatibility verification (PUBL-04), and code quality metrics reporting (PUBL-05). The phase consolidates validation, documentation, and quality gates into production-ready artifacts.

**Primary recommendation:** Implement a Makefile-driven validation pipeline (`make appinspect`, `make metrics`) that gates all five requirements before release, using automated tools (splunk-appinspect, radon/escomplex, pytest coverage) combined with manual verification steps for conf files, threat modeling, and upgrade path testing.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **AppInspect Strategy**: Run CLI locally first (splunk-appinspect), then cloud API at publication; validate both standard AND cloud tag sets; fix all fixable warnings; document unfixable ones in APPINSPECT_NOTES.md
- **Backward compat approach**: Both static analysis (SPL query review, conf file validation) AND runtime testing (golden audit events, version manifest fixtures, approval queue replay, full Docker upgrade path test)
- **Documentation scope**: Security architecture with executive summary + threat model appendix (STRIDE/DREAD); OpenAPI 3.0 manual YAML spec; update existing docs; README overhaul for Splunkbase audience
- **Python compliance**: Full Python 3 adherence; verify all 14 modules use wl_logging.py; no print(), direct logging, bare except, or dangerous dynamic execution
- **Packaging**: Enhanced script.sh with explicit excludes, pre-flight validation, app.manifest version alignment, SHA256 checksum
- **Version**: Ship as 1.0.0 for Splunkbase (first public release); app.manifest and app.conf both set to 1.0.0
- **Metrics**: Automated script enforcing thresholds (CC >15 = fail, coverage <80% = fail, function >100 lines = fail)

### Claude's Discretion
- Version manifest backward compat test approach (fixture-based vs live container)
- Exact AppInspect warning remediation order and documentation
- Screenshot composition for documentation
- JS complexity tool selection (escomplex vs eslint-plugin-complexity vs custom)
- Mermaid diagram layout and detail level
- OpenAPI spec organization (single vs split by action group)

### Deferred Ideas
None — discussion stayed within phase scope

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PUBL-01 | AppInspect validation passes with 0 high/critical issues; all warnings documented | AppInspect CLI standard + cloud tag sets; conf file schema validation; Python 3 compliance scanning |
| PUBL-02 | Security architecture document (threat model, RBAC breakdown, data flow diagram, audit event structure) | STRIDE/DREAD methodology; documented vulnerabilities (optimistic locking bypass, client trust bypass, etc.); audit event field structure |
| PUBL-03 | OpenAPI schema documenting all REST API actions, parameters, responses, error codes | OpenAPI 3.0 spec format; wl_handler.py GET_ACTIONS/POST_ACTIONS enumeration; manual YAML authoring |
| PUBL-04 | Backward compatibility verified: audit events parse correctly, version manifests load, approval queues process | SPL query static analysis; golden event fixture testing; version manifest JSON validation; Docker upgrade path test |
| PUBL-05 | Code maintainability metrics published (CC <15, avg function <100 lines, ≥80% test coverage per module) | Radon for Python; escomplex/eslint-complexity for JS; pytest coverage integration; quality gate script with enforcement |

---

## Standard Stack

### AppInspect & Validation

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| splunk-appinspect | Latest (via pip) | Automated validation of Splunk apps before submission | Required for Splunkbase compliance; catches high/critical issues automatically |
| splunk-appinspect CLI | Latest | Local CLI validation with tag set filtering (`--included-tags`, `--excluded-tags`) | Faster iteration than cloud API; standard for pre-flight checks |
| Tag sets | `standard` + `cloud` | Run both standard checks AND Splunk Cloud compatibility checks | CONTEXT decision: validate for both deployment types |

### Code Quality Metrics

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| radon | 6.x+ | Python cyclomatic complexity, function length, maintainability index | Measure CC per function, enforce CC <15 threshold |
| coverage.py | 7.x+ | Python test coverage percentage per module | Enforce ≥80% coverage per PUBL-05 |
| escomplex | Latest (npm) | JavaScript cyclomatic complexity analysis via AST | Measure JS module complexity; alternative to eslint-complexity |
| eslint (with complexity rule) | 9.x+ | ESLint complexity rule for JavaScript cyclomatic complexity | Alternative to escomplex; integrates with linting pipeline |

### Security Documentation

| Tool | Format | Purpose | Standard Reference |
|------|--------|---------|-------------------|
| Mermaid | YAML in Markdown | Data flow diagrams, RBAC matrix visualization, audit event flow | Embedded in Markdown docs; no external tool needed |
| OpenAPI 3.0 | YAML | REST API specification format | Industry standard for API documentation |

### Installation

**AppInspect CLI:**
```bash
pip install splunk-appinspect
# Verify installation
splunk-appinspect list tags  # View available tag sets (standard, cloud, etc.)
```

**Python metrics:**
```bash
pip install radon coverage pytest-cov
```

**JavaScript metrics:**
```bash
npm install escomplex escomplex-cli
# OR use ESLint with complexity plugin
npm install eslint eslint-plugin-complexity
```

**Verify versions:**
```bash
splunk-appinspect --version
radon --version
coverage --version
```

### Alternatives Considered

| Standard | Alternative | Tradeoff |
|----------|-------------|----------|
| radon (Python CC) | pylint/flake8 | Radon is dedicated to CC measurement; pylint is broader but less precise on CC |
| escomplex (JS CC) | eslint-plugin-complexity | escomplex provides standalone analysis; eslint integration needs plugin; similar accuracy |
| Mermaid (diagrams) | PlantUML, Graphviz | Mermaid renders in GitHub/Markdown; PlantUML requires compilation; Graphviz is heavyweight |
| OpenAPI 3.0 YAML (manual) | Swagger Editor UI generation | Manual YAML allows full control; UI generators can miss custom error codes and edge cases |

---

## Architecture Patterns

### AppInspect Compliance Pipeline

**What:** Multi-stage validation ensuring app meets Splunk Marketplace standards before publication

**When to use:** Every release to Splunkbase; gates package.sh script

**Pattern:**
```bash
# 1. Pre-flight static checks (bash)
bash scripts/validate.sh         # Custom pre-flight (file presence, Python syntax, conf file structure)

# 2. Standard AppInspect checks (CLI)
splunk-appinspect inspect wl_manager.spl  # Default standard checks

# 3. Cloud compatibility checks (CLI)
splunk-appinspect inspect wl_manager.spl --included-tags cloud  # Cloud-specific checks

# 4. Gap analysis
# Compare results from steps 2-3 against baseline; document any NEW warnings in APPINSPECT_NOTES.md

# 5. Manual verification
# - Conf file schema validation (AppInspect auto-checks, but verify restmap.conf, authorize.conf, etc.)
# - Python 3 compliance (grep for print(), bare except, old string methods)
# - JS security audit (innerHTML, unsafe DOM, inline event handlers)
```

**Key insight:** AppInspect catches structural/configuration issues; manual audits catch patterns that tools miss (e.g., inline JS event handlers in Splunk confusing app contexts).

### Backward Compatibility Testing Matrix

**What:** Three-layer approach: static analysis → fixture-based testing → end-to-end upgrade test

**Pattern:**

```
Layer 1: Static Analysis (Zero runtime cost)
├─ SPL Queries: Review audit.xml search for field name correctness
│  ├─ Audit event fields: action, analyst, detection_rule, csv_file, removed_row_count, value, etc.
│  ├─ Revert event fields: reverted_from_version, reverted_to_version, *back suffixed fields
│  └─ Search for renamed fields between v2.0 and v3.0
├─ Conf Files: Check for stale v2.0 config references after upgrade
│  ├─ restmap.conf: REST endpoint mapping still valid?
│  ├─ authorize.conf: RBAC role definitions unchanged?
│  └─ savedsearches.conf: Saved searches still reference correct data?
└─ Data Structures: Review format changes
   ├─ Version manifest JSON schema (lookups/_versions/*_versions.json)
   ├─ Approval queue entry JSON (bin/wl_approval.py queue format)
   └─ CSV header/column changes (backward compat with old CSVs?)

Layer 2: Fixture-Based Testing (Offline, reproducible)
├─ Golden audit events: Pre-v3.0 events + inject into wl_audit index + run audit.xml searches
├─ Version manifests: Create v2.0-format manifests + load in v3.0 code + verify parsing
├─ Approval queue entries: Build pre-v3.0 queue JSON + feed through wl_approval.py + verify processing
└─ Test data: Script to create representative pre-rewrite state in Docker (v2.0 CSVs, audit events, queues)

Layer 3: End-to-End Upgrade Test (Full Docker simulation)
├─ Step 1: Build v2.0 .spl from git (pre-rewrite commit)
├─ Step 2: Fresh Docker container, install v2.0 app
├─ Step 3: Create representative data (CSVs, audit events, approval queue entries, version snapshots)
├─ Step 4: Upgrade to v3.0 .spl (uninstall v2.0, install v3.0)
├─ Step 5: Verify all data accessible and functional
│  ├─ CSVs load and display correctly
│  ├─ Audit events parse in audit.xml
│  ├─ Version manifests load in UI
│  ├─ Approval queue entries process correctly
│  └─ Conf file merging produces v3.0 values (no stale v2.0 stanzas)
└─ Report: docs/BACKWARD_COMPAT.md with pass/fail matrix
```

### Security Architecture Documentation Structure

**What:** Two-audience document: executive summary for admins + detailed threat model for security reviewers

**Pattern:**

```markdown
# Security Architecture — Whitelist Manager

## Part 1: Executive Summary (1-2 pages)
- What data does this app access? (audit events, CSV data, rule configs)
- What data does it write? (wl_audit index, version snapshots, approval queues)
- RBAC model overview (4-tier: viewer, editor, admin, superadmin)
- Audit completeness (what actions are logged?)
- Compliance posture (Splunk Cloud compatible? Python 3? AppInspect clean?)

## Part 2: Threat Model (3-5 pages)
- Use STRIDE framework:
  | Threat Category | Threat | Mitigation | Evidence |
  |---|---|---|---|
  | **Spoofing** | Attacker impersonates analyst | Splunk auth required; server-side role checks | wl_rbac.py role validation |
  | **Tampering** | Attacker modifies CSV data in-flight | Optimistic locking (file mtime); audit events signed by analyst | wl_filelock.py; wl_audit.py |
  | (... continue for all 6 STRIDE categories) |

- Use DREAD to rank severity:
  | Threat | Damage | Reproducibility | Exploitability | Affected Users | Discoverability | DREAD Score | Risk |
  |---|---|---|---|---|---|---|---|
  | Path traversal | High | Low | High | Few | Low | 5.0 | Medium |
  | (... continue for each threat) |

## Part 3: Mitigated Vulnerabilities (from MEMORY.md)
- Optimistic locking bypass: Fixed in phase X, verified by test Y
- Client trust bypass (reserved prefix): Fixed in phase X, enforced at input validation
- RBAC bypass in approval cancel: Fixed in phase X, added role check before state change
- (... each documented vulnerability becomes "identified and mitigated threat")

## Part 4: Attack Surface Analysis
- External interfaces: REST API endpoints, Splunk auth boundary
- Data flows: CSV read → diff → audit → version snapshot
- Trust boundaries: Splunk auth <-> wl_manager app <-> lookups
- Sensitive operations: CSV save (with audit), approval decision, version revert
```

**Key insight:** Splunk admins read Part 1 (is this safe to deploy?); security auditors read Parts 2-4 (how does it defend against attacks?). Mitigated vulnerabilities show security maturity, not weakness.

### OpenAPI 3.0 REST API Specification

**What:** Manual YAML specification documenting all wl_handler.py actions: parameters, responses, error codes, request/response examples

**When to use:** Published in docs/api/openapi.yaml; included in Splunkbase .spl package for API consumers

**Pattern:**
```yaml
openapi: 3.0.0
info:
  title: Whitelist Manager REST API
  version: 1.0.0
  description: Manage detection-rule CSV whitelists with version control and audit trail

servers:
  - url: /custom/wl_manager
    description: Whitelist Manager REST endpoint

paths:
  /:
    get:
      summary: Retrieve CSV or rule mapping
      operationId: getCSV | getMapping
      parameters:
        - name: action
          in: query
          required: true
          schema:
            enum: [get_csv, get_mapping, get_versions]
        - name: rule_name
          in: query
          required: true
          schema:
            type: string
      responses:
        200:
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  rows:
                    type: array
                  headers:
                    type: array
        400:
          description: Bad request (missing rule, invalid action)
        403:
          description: Forbidden (insufficient role)
        500:
          description: Server error
      examples:
        getCSVRequest:
          summary: Fetch CSV for rule DR-1234
          value:
            action: get_csv
            rule_name: DR-1234
        getCSVResponse:
          summary: CSV data with headers
          value:
            rows: [{user: jsmith}, {user: admin}]
            headers: [user]
    
    post:
      summary: Save CSV or process approval
      operationId: saveCSV | revertCSV
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                action:
                  enum: [save_csv, revert_csv]
                rule_name:
                  type: string
                new_rows:
                  type: array
      responses:
        200:
          description: Success
        400:
          description: Bad request (validation error)
        403:
          description: Forbidden
        409:
          description: Conflict (optimistic lock failure; file changed since fetch)
        (... continue for all GET/POST actions)
```

**Key insight:** Every action in `GET_ACTIONS` and `POST_ACTIONS` dicts in wl_handler.py becomes an operation in OpenAPI; request/response shapes extracted directly from code; error codes (400, 403, 409) documented with reasons.

### Metrics Collection & Quality Gate

**What:** Automated Python script that measures code complexity, function size, and test coverage; enforces thresholds; produces CODE_METRICS.md

**Pattern:**
```python
# metrics_collector.py
import radon.complexity
import radon.metrics
from coverage import Coverage
from pathlib import Path

# Thresholds from PUBL-05
THRESHOLDS = {
    "cyclomatic_complexity": 15,  # CC >15 = FAIL
    "function_length": 100,        # Function >100 lines = FAIL
    "test_coverage": 0.80,         # Coverage <80% = FAIL
}

def analyze_python_modules(bin_dir):
    """Scan all .py files in bin/, compute CC per function"""
    results = {}
    for py_file in bin_dir.glob("*.py"):
        cc_results = radon.complexity.cc_visit(py_file.read_text())
        for func_metrics in cc_results:
            if func_metrics.complexity > THRESHOLDS["cyclomatic_complexity"]:
                results[f"{py_file.name}:{func_metrics.name}"] = {
                    "cc": func_metrics.complexity,
                    "status": "FAIL"
                }
    return results

def analyze_js_modules(appserver_dir):
    """Scan all .js files via escomplex-cli"""
    # Call escomplex-cli or escomplex Node.js API
    # Collect CC per function
    pass

def check_coverage(pytest_coverage_report):
    """Parse pytest coverage, check per-module thresholds"""
    # pytest --cov=bin --cov-report=json produces coverage.json
    # Check each module's coverage against THRESHOLDS["test_coverage"]
    pass

def generate_report():
    """Produce docs/CODE_METRICS.md + exit non-zero if any threshold exceeded"""
    # Format: markdown table with columns:
    # Module | Function | CC Score | Function Length | Status
    # Set exit code 1 if FAIL found → gates Makefile target
    pass
```

**Key insight:** Quality gate script becomes CI-ready artifact; can be invoked in pre-commit hooks or Makefile; non-zero exit code on failure prevents accidental commit of high-complexity code.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| AppInspect validation | Custom Python wrapper to parse app structure | splunk-appinspect CLI with tag filtering | Tool handles all Splunk specifics: conf schema, Python 3, deprecated patterns, etc. |
| Cyclomatic complexity measurement | Custom AST walker for Python or JS | radon (Python) + escomplex (JS) | These tools have been peer-reviewed and are industry-standard; custom implementations miss edge cases (nested lambdas, comprehensions, etc.) |
| REST API documentation | Manual markdown with examples | OpenAPI 3.0 YAML (hand-authored but structured) | OpenAPI enables future tooling (code generation, interactive docs, SDK generation); structured format vs unstructured docs |
| Test coverage reporting | Custom script parsing coverage.py | pytest --cov with coverage.py JSON output | coverage.py already handles per-file and per-function analysis; leverage it directly |
| Backward compat testing | Ad-hoc manual checks | Fixture-based + Docker-based test scripts | Ad-hoc testing is error-prone (easy to miss edge cases); reproducible scripts catch regressions |
| Threat modeling documentation | Narrative prose | STRIDE/DREAD templates | Templates ensure completeness; STRIDE covers all 6 threat categories; DREAD provides systematic risk scoring |

**Key insight:** Splunkbase publication involves many standardized tools and practices. Hand-rolling any of these (AppInspect validator, metrics collector, threat model) introduces unmaintainable code that won't integrate with the Splunk ecosystem or industry best practices.

---

## Common Pitfalls

### Pitfall 1: AppInspect Only on Standard, Not Cloud

**What goes wrong:** App passes standard AppInspect but fails cloud validation at submission (e.g., localhost:8089 usage in wl_audit.py flagged as unsafe). Requires fix + resubmission delay.

**Why it happens:** Developers test against default tag set; cloud tag set catches additional constraints (no direct Splunk management port access, no deprecated Python patterns, etc.).

**How to avoid:** CONTEXT decision: always run BOTH `splunk-appinspect inspect <app>` (standard) AND `splunk-appinspect inspect <app> --included-tags cloud`. Document any cloud-specific warnings in APPINSPECT_NOTES.md before submission.

**Warning signs:** urllib access to localhost:8089 in wl_audit.py; direct import of deprecated Splunk SDK modules; bare except clauses.

### Pitfall 2: Backward Compat Testing Misses Data Format Changes

**What goes wrong:** v3.0 app installs over v2.0, but version manifests or approval queue entries can't be read (JSON schema changed subtly). Audit dashboard queries break because field names changed.

**Why it happens:** Developers assume data format is stable; small refactors (rename key, add optional field) break pre-upgrade data silently.

**How to avoid:** Three-layer approach (locked in CONTEXT): static analysis of SPL queries for field name correctness; fixture-based tests with pre-v3.0 data structures; full Docker upgrade path test from v2.0 to v3.0.

**Warning signs:** Version manifest JSON parsing throws exception; approval queue iteration fails on unexpected key; audit.xml searches return 0 results for old events.

### Pitfall 3: AppInspect Warnings Documented But Never Fixed

**What goes wrong:** APPINSPECT_NOTES.md documents 5 warnings as "known false positives" but 3 are actually fixable. Later reviews find the discrepancy; app appears unmaintained.

**Why it happens:** Warnings are overwhelming; developers doc them and move on without investigating each one's root cause.

**How to avoid:** For each AppInspect warning, ask: "Can this be fixed?" → Yes: fix now. No: verify with Splunk docs (is it really a known false positive?). Only doc truly unfixable warnings with external justification.

**Warning signs:** APPINSPECT_NOTES.md longer than 1 page; same warning appears multiple versions; no attempt to understand why tool flagged it.

### Pitfall 4: Metrics Script Doesn't Enforce Thresholds

**What goes wrong:** CODE_METRICS.md reports "23 functions with CC >15" but process doesn't fail. App gets shipped with unmaintainable code. Developer assumes "it'll be fixed in v2."

**Why it happens:** Metrics are informational; not gated in release process.

**How to avoid:** Metrics script must have non-zero exit code on threshold breach. Makefile target `make metrics` fails if any threshold exceeded. Blocks `make package` → blocks release.

**Warning signs:** CODE_METRICS.md generated but ignored; no pre-commit hook checking thresholds; developer can bypass metrics check.

### Pitfall 5: Security Architecture Doc Reads Like Feature Checklist

**What goes wrong:** Doc lists "RBAC: yes, Audit: yes, Rate limiting: yes" with no actual threat analysis. Reviewer can't assess if mitigations are effective.

**Why it happens:** Developers confused documentation with requirement fulfillment; forgot it's for security auditors and admins.

**How to avoid:** Write for two audiences (CONTEXT decision): Part 1 is one-pager for admins ("is it safe?"). Part 2 is 5-page threat model using STRIDE/DREAD for security pros. Include past vulnerabilities as "identified and mitigated" with evidence (commit hashes, test IDs).

**Warning signs:** Doc is all lists with no narrative threat analysis; no mention of actual attacks or edge cases; no STRIDE categories covered.

---

## Code Examples

### AppInspect CLI Validation

**Source:** [Splunk AppInspect CLI Reference](https://dev.splunk.com/enterprise/reference/appinspect/appinspectcliref)

```bash
# 1. Package the app
bash scripts/package.sh

# 2. Run standard AppInspect checks
splunk-appinspect inspect dist/wl_manager-1.0.0.spl

# 3. Run cloud tag set (CONTEXT decision)
splunk-appinspect inspect dist/wl_manager-1.0.0.spl --included-tags cloud

# 4. Check available tags
splunk-appinspect list tags

# 5. Exclude specific tags if needed (e.g., skip cloud checks during dev)
splunk-appinspect inspect dist/wl_manager-1.0.0.spl --excluded-tags cloud
```

### Python Module CC Analysis with Radon

**Source:** [Radon Documentation](https://radon.readthedocs.io/en/latest/)

```bash
# Cyclomatic complexity per function
radon cc bin/ -a  # -a: show average; outputs CC per function

# Function length (SLOC)
radon raw bin/ -s  # -s: summary; outputs function/module line counts

# Maintainability index (combined metric)
radon mi bin/

# Example output:
# wl_handler.py
#   M 224:4 _save_csv_inner - 720 lines, CC=28 (HIGH)
#   M 156:0 _compute_diff - 186 lines, CC=22 (HIGH)
```

### JavaScript Complexity with escomplex

**Source:** [escomplex npm package](https://www.npmjs.com/package/escomplex)

```bash
# Install escomplex-cli
npm install -g escomplex-cli

# Analyze all JS files
escomplex appserver/static/modules/*.js --format json > js-metrics.json

# Parse results to check CC thresholds
# Example: bindTableEvents has CC=13 (OK, <15)
#          syncInputs+refreshTable pair has CC=11 (OK, <15)
```

### Test Coverage Collection

**Source:** [pytest-cov documentation](https://pytest-cov.readthedocs.io/)

```bash
# Run tests with coverage
pytest tests/ --cov=bin --cov-report=json --cov-report=html

# Coverage report shows per-module percentages
# Example output:
# bin/wl_handler.py       87%  coverage
# bin/wl_csv.py           92%  coverage
# bin/wl_rbac.py          78%  coverage (FAIL: <80%)
```

### OpenAPI 3.0 Example (GET action)

**Source:** [OpenAPI 3.0 Specification](https://spec.openapis.org/oas/v3.0.3)

```yaml
openapi: 3.0.0
info:
  title: Whitelist Manager API
  version: 1.0.0

paths:
  /custom/wl_manager:
    get:
      summary: Get CSV data for a detection rule
      operationId: get_csv
      parameters:
        - name: action
          in: query
          required: true
          schema:
            enum: [get_csv, get_mapping, get_versions]
          example: get_csv
        - name: rule_name
          in: query
          required: true
          schema:
            type: string
            pattern: '^[A-Za-z0-9_-]+$'
          example: DR-1234
      responses:
        200:
          description: CSV data retrieved successfully
          content:
            application/json:
              schema:
                type: object
                properties:
                  rows:
                    type: array
                    items:
                      type: object
                  headers:
                    type: array
                    items:
                      type: string
                  rule_name:
                    type: string
                  last_modified:
                    type: string
                    format: date-time
              examples:
                success:
                  value:
                    rows:
                      - user: jsmith
                        src_ip: 10.1.2.3
                      - user: admin
                        src_ip: 10.0.0.1
                    headers: [user, src_ip]
                    rule_name: DR-1234
                    last_modified: "2026-04-02T14:00:00Z"
        400:
          description: Bad request (missing rule_name, invalid action)
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
        403:
          description: Forbidden (insufficient role)
        404:
          description: Rule not found
```

### Backward Compat Test: Golden Audit Event Injection

```python
# tests/integration/test_backward_compat_audit.py
import pytest
from unittest.mock import patch, MagicMock

# Pre-v3.0 audit event format (what v2.0 produced)
GOLDEN_AUDIT_EVENT_V2 = {
    "timestamp": "2026-01-15 10:30:00",  # Old timestamp format
    "analyst": "jsmith",
    "detection_rule": "DR-1234",
    "csv_file": "whitelist_list.csv",
    "action": "added",
    "removed_row_count": 0,
    "value": {
        "user_row_1": "malware_user",
        "ip_row_1": "192.168.1.100"
    }
}

def test_v2_audit_events_parse_in_v3_audit_xml(docker_container):
    """
    BACKWARD_COMPAT: Audit dashboard queries must parse pre-v3.0 events.
    This test injects a v2.0 audit event and verifies audit.xml searches still work.
    """
    # Step 1: Inject v2.0 audit event into wl_audit index
    inject_event_to_splunk(
        container=docker_container,
        event=GOLDEN_AUDIT_EVENT_V2,
        index="wl_audit",
        sourcetype="wl_audit"
    )
    
    # Step 2: Run audit.xml search (simplified "get all events")
    search_results = run_splunk_search(
        container=docker_container,
        query="index=wl_audit sourcetype=wl_audit | fields action, analyst, detection_rule"
    )
    
    # Step 3: Verify old event parsed correctly
    assert len(search_results) > 0, "v2.0 audit event failed to parse"
    assert search_results[0]["action"] == "added"
    assert search_results[0]["analyst"] == "jsmith"
    assert search_results[0]["detection_rule"] == "DR-1234"
```

### Docker Upgrade Path Test Script

```bash
#!/usr/bin/env bash
# scripts/test_upgrade_path.sh
# Full end-to-end upgrade test: v2.0 -> v3.0

set -e

CONTAINER_NAME="wl_manager_upgrade_test"
V2_COMMIT="abc123def"  # Pre-rewrite commit
V3_SPL="dist/wl_manager-1.0.0.spl"

echo "[1/5] Build v2.0 .spl from git..."
git stash
git checkout $V2_COMMIT
bash scripts/package.sh
V2_SPL=$(ls -t dist/*.spl | head -1)
git checkout -  # Back to main

echo "[2/5] Start fresh container and install v2.0..."
docker run -d \
  --name $CONTAINER_NAME \
  -p 8000:8000 -p 8089:8089 \
  splunk/splunk:9.3.1
# ... wait for startup
docker cp "$V2_SPL" "$CONTAINER_NAME:/opt/splunk/etc/apps/wl_manager.spl"
docker exec "$CONTAINER_NAME" bash -c \
  '/opt/splunk/bin/splunk install app /opt/splunk/etc/apps/wl_manager.spl -auth admin:Chang3d!'

echo "[3/5] Create representative v2.0 data..."
docker exec "$CONTAINER_NAME" python3 tests/integration/fixtures/populate_v2_data.py

echo "[4/5] Upgrade to v3.0..."
docker exec "$CONTAINER_NAME" bash -c \
  '/opt/splunk/bin/splunk remove app wl_manager -auth admin:Chang3d! && \
   /opt/splunk/bin/splunk install app '"$V3_SPL"' -auth admin:Chang3d!'

echo "[5/5] Verify v3.0 reads all v2.0 data..."
docker exec "$CONTAINER_NAME" bash -c \
  '/opt/splunk/bin/splunk search "index=wl_audit | stats count" -auth admin:Chang3d! 2>/dev/null'

echo "✓ Upgrade path verified: v2.0 → v3.0"
docker rm -f $CONTAINER_NAME
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual AppInspect review (cloud submission) | CLI-first validation (local + cloud) | AppInspect CLI stabilized (2024) | Earlier detection of issues; faster iteration before submission |
| Python 2.7 support | Python 3.7+ only | Splunk 9.x release (2023) | Cleaner code; no dual-compatibility burden; enables modern Python patterns |
| Custom diff algorithm | Similarity-based multiset matching | Phase 2 rewrite | Correctly detects edits when rows removed simultaneously |
| Flat monolithic backend | 14-module modular architecture | Phase 1-4 refactor | Testable modules; reusable domain logic; clear responsibilities |
| Manual upgrade testing | Automated Docker path script | Phase 8 | Catches data format regressions; reproducible evidence of compatibility |
| Narrative security docs | STRIDE/DREAD threat model | Phase 8 (research) | Systematic threat identification; DREAD scoring enables risk prioritization |

**Deprecated/outdated:**
- **Python 2 syntax** (print statements, old-style exceptions): Splunk 9.x ships Python 3 only; no 2.7 runtime available
- **Custom REST helpers** (duplicated in 3 JS files): Phase 5-6 refactored into wl_rest.js module
- **Flat conf files** (app.conf, restmap.conf mixed): Modern Splunk prefers modular conf structure; Splunkbase apps should follow best practices
- **Manual version control** (loose snapshots): Phase 2 implemented manifests with schema versioning; backward compatible

---

## Open Questions

1. **Version manifest backward compat test approach**
   - What we know: v2.0 manifests exist in `lookups/_versions/*.json`; format might have changed in v3.0
   - What's unclear: Magnitude of schema change (optional new field vs total rewrite?)
   - Recommendation: Check first if manifest format changed (read git history of wl_versions.py). If minor (new optional field), fixture-based test sufficient. If major, need live Docker test to validate parsing.

2. **JS complexity tool choice (escomplex vs eslint-plugin-complexity)**
   - What we know: Both can measure cyclomatic complexity; escomplex is standalone; eslint-complexity integrates with linting
   - What's unclear: Project already uses eslint? Which tool produces authoritative results for PUBL-05 reporting?
   - Recommendation: Check if project has eslint config (`.eslintrc.json` or `eslint.config.js`). If yes, use eslint-plugin-complexity (integrates existing workflow). If no, use escomplex (no additional tooling needed).

3. **AppInspect cloud tag warnings fixability**
   - What we know: CONTEXT mentions localhost:8089 in wl_audit.py as "most likely flag"
   - What's unclear: Is this truly unfixable? Can we refactor to use Splunk SDK?
   - Recommendation: Run AppInspect cloud tag set early. If localhost:8089 is flagged, research Splunk SDK alternatives (service.indexes API). If no alternative exists, doc in APPINSPECT_NOTES.md with external justification.

4. **Backward compat: CSV header/column compatibility**
   - What we know: CSVs stored in lookups/ directory; v3.0 might support new column types
   - What's unclear: Can v3.0 safely read v2.0 CSVs with missing columns? Will edit operations on old CSVs introduce new columns?
   - Recommendation: Test fixture with old CSV (minimal columns) + edit in v3.0 UI + check if new columns injected (should not).

5. **Documentation screenshot timing**
   - What we know: Needs fresh screenshots of v3.0 UI for Splunkbase README
   - What's unclear: Should screenshots be from dark theme, light theme, or both? Show feature highlights or full workflow?
   - Recommendation: Capture both themes (users have different preferences). For feature highlights: 4-5 screenshots (CSV editor, audit dashboard, admin panel, approval queue, version revert). Pair with concise captions.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with unittest.mock, pytest-cov, custom Docker fixtures (conftest.py) |
| Config file | tests/pytest.ini |
| Quick run command | `pytest tests/unit -v` (offline, <10 seconds) |
| Full suite command | `pytest tests/ -v` (includes integration + Docker, ~5 minutes) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PUBL-01 | AppInspect runs without high/critical issues | integration | `splunk-appinspect inspect dist/*.spl` | ✅ (scripts/validate.sh extended) |
| PUBL-01 | AppInspect cloud tag set passes | integration | `splunk-appinspect inspect dist/*.spl --included-tags cloud` | ❌ Wave 0 (needs verify script) |
| PUBL-02 | Security architecture document exists | manual | Generate docs/SECURITY_ARCHITECTURE.md | ❌ Wave 0 |
| PUBL-02 | Threat model uses STRIDE/DREAD | manual | Review docs/SECURITY_ARCHITECTURE.md for STRIDE/DREAD tables | ❌ Wave 0 |
| PUBL-03 | OpenAPI spec documents all GET_ACTIONS | manual | Hand-author docs/api/openapi.yaml, count operations vs code | ❌ Wave 0 |
| PUBL-03 | OpenAPI spec has request/response examples | manual | Review openapi.yaml for `examples:` blocks per action | ❌ Wave 0 |
| PUBL-04 | Audit event field parsing (v2.0 events in v3.0) | integration | `pytest tests/integration/test_backward_compat_audit.py -v` | ❌ Wave 0 |
| PUBL-04 | Version manifest loading (v2.0 manifests in v3.0) | integration | `pytest tests/integration/test_backward_compat_versions.py -v` | ❌ Wave 0 |
| PUBL-04 | Approval queue replay (v2.0 entries in v3.0) | integration | `pytest tests/integration/test_backward_compat_approval.py -v` | ❌ Wave 0 |
| PUBL-04 | Full upgrade path v2.0 → v3.0 | integration | `bash scripts/test_upgrade_path.sh` | ❌ Wave 0 |
| PUBL-05 | All Python functions CC <15 | unit | `radon cc bin/ -a --fail-under F:15` | ❌ Wave 0 |
| PUBL-05 | All JS functions CC <15 | unit | `escomplex appserver/static/**/*.js --fail-under 15` | ❌ Wave 0 |
| PUBL-05 | Code coverage ≥80% per module | unit | `pytest tests/ --cov=bin --cov-fail-under=80` | ✅ (Phase 7 coverage exists) |
| PUBL-05 | Average function length <100 lines | unit | `radon raw bin/ -s; escomplex ... --function-metrics` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** Quick validation: `bash scripts/validate.sh && pytest tests/unit -v`
- **Per wave merge:** Full suite: `pytest tests/ -v && splunk-appinspect inspect dist/*.spl && radon cc bin/ -a`
- **Phase gate:** Full AppInspect + all metrics checks + backward compat tests must pass before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/integration/test_backward_compat_audit.py` — Golden v2.0 audit event injection test
- [ ] `tests/integration/test_backward_compat_versions.py` — v2.0 version manifest fixture test
- [ ] `tests/integration/test_backward_compat_approval.py` — v2.0 approval queue replay test
- [ ] `scripts/test_upgrade_path.sh` — End-to-end Docker upgrade v2.0 → v3.0
- [ ] `scripts/verify_appinspect.sh` — AppInspect validation wrapper (both standard + cloud tag sets)
- [ ] `scripts/metrics_collector.py` — Radon + escomplex analysis with threshold enforcement
- [ ] `docs/SECURITY_ARCHITECTURE.md` — Two-part STRIDE/DREAD threat model + mitigated vulnerabilities
- [ ] `docs/api/openapi.yaml` — OpenAPI 3.0 manual specification for all REST actions
- [ ] `docs/BACKWARD_COMPAT.md` — Backward compatibility test matrix and results
- [ ] `docs/APPINSPECT_NOTES.md` — AppInspect warnings log (initial: empty or populated with findings)
- [ ] `CODE_METRICS.md` (root) — Summary metrics report (copy from docs/CODE_METRICS.md for GitHub visibility)
- [ ] Makefile targets: `appinspect`, `metrics`, `backward-compat-test` (if not already present)
- [ ] `app.manifest` — Complete fields (author email, company, releaseDate, license details)
- [ ] `README.md` — Rewrite for Splunkbase audience with screenshots, installation, requirements

---

## Sources

### Primary (HIGH confidence)
- [Splunk AppInspect CLI Reference](https://dev.splunk.com/enterprise/reference/appinspect/appinspectcliref) — Command syntax, tag filtering, output formats
- [Splunk AppInspect CLI Tool Documentation](https://dev.splunk.com/enterprise/docs/developapps/testvalidate/appinspect/useappinspectclitool) — Installation (Python 3.7+, libmagic), version checking
- [Splunk Python Compatibility Documentation](https://dev.splunk.com/enterprise/docs/developapps/python-compatibility) — Python 3 required for 8.x+ apps
- [Splunk Splunkbase Publishing Requirements](https://dev.splunk.com/enterprise/docs/releaseapps/splunkbase/) — Submission process, validation steps, metadata requirements
- [Splunk Splunkbase Cloud Compatibility](https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/9.3.2411/administer-splunk-cloud-platform-using-the-admin-config-service-acs-api/manage-splunkbase-apps-in-splunk-cloud-platform) — Cloud deployment requirements, compatibility indicators

### Secondary (MEDIUM confidence)
- [Radon Code Metrics Documentation](https://radon.readthedocs.io/en/latest/) — Cyclomatic complexity measurement, maintainability index
- [escomplex npm Package](https://www.npmjs.com/package/escomplex) — JavaScript complexity analysis via AST
- [STRIDE Threat Modeling](https://www.practical-devsecops.com/what-is-stride-threat-model/) — Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege framework
- [DREAD Risk Assessment](https://threat-modeling.com/dread-threat-modeling/) — Damage, Reproducibility, Exploitability, Affected Users, Discoverability scoring
- [OpenAPI 3.0 Specification](https://spec.openapis.org/oas/v3.0.3) — REST API documentation format, request/response structure
- [Splunk App Version Upgrade Testing](https://lantern.splunk.com/Splunk_Platform/Product_Tips/Upgrades_and_Migration/Upgrading_the_splunk_platform) — Reference instance approach, compatibility verification

### Tertiary (LOW confidence, marked for validation)
- [Splunk products version compatibility matrix](https://docs.splunk.com/Documentation/VersionCompatibility/current/Matrix/CompatMatrix) — Version compatibility reference (updated regularly; verify currency before release)

---

## Metadata

**Confidence breakdown:**
- AppInspect CLI: HIGH — verified against official dev.splunk.com documentation, 2026-current
- Python/JS metrics: HIGH — radon and escomplex are industry-standard, documented on official sites
- OpenAPI 3.0: HIGH — official specification, widely adopted industry standard
- Backward compatibility approach: MEDIUM — general Splunk upgrade patterns documented; specific project approach (Docker path test) is logical but not yet executed
- Security documentation (STRIDE/DREAD): MEDIUM — well-established frameworks; Splunk-specific application requires domain knowledge
- Splunkbase submission: MEDIUM — process outlined in dev.splunk.com; specific validation timelines and edge cases unknown

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (30 days; AppInspect CLI and Splunkbase submission process are stable; CONTEXT decisions lock specific approaches)
