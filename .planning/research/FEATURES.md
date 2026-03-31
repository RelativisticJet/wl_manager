# Quality Attributes & Splunkbase Requirements

**Domain:** Splunk Enterprise Security app (whitelist management)  
**Researched:** 2026-03-31  
**Confidence:** MEDIUM (training data + audit findings + validation patterns)

---

## Table of Stakes

Features users expect when installing a Splunk app from Splunkbase. Missing these = product feels unpolished or risky.

| Quality Attribute | Why Expected | Current State | Complexity |
|---|---|---|---|
| **AppInspect compliance** | Required for Splunkbase publication; signals production quality | Partial (validates.sh passes core checks) | Medium |
| **Documentation** | New admins need setup, configuration, troubleshooting guides | Complete (user guide + admin guide + screenshots) | Low |
| **Error handling** | Apps that fail silently or crash lack professionalism | Present (fail-closed, state rollback) | Medium |
| **RBAC enforcement** | Security apps MUST have server-side role verification | Complete (4-tier system) | Low |
| **Audit trail** | Whitelist changes must be tracked for compliance | Complete (7,000+ lines of audit logic) | High |
| **Code organization** | Maintainability signals maturity; monolithic code raises concerns | Partial (single 7K-line backend file) | High |
| **Test coverage** | Lack of tests signals fragility; >80% coverage expected | Partial (unit + integration, gaps in XSS/CSRF) | High |
| **Performance** | Apps that hang on large datasets are rejected | Validated (tested 2000x100 CSVs) | Low |
| **Version compatibility** | Support matrix clear and tested | Splunk 8.2+ in app.manifest | Low |
| **Security controls** | No hardcoded secrets, no eval(), path traversal protection | Complete (3-layer path security, no dangerous patterns) | Low |

---

## Differentiators

Features that set this app apart in the Splunkbase ecosystem. Not baseline, but valued by top-rated apps.

| Feature | Value Proposition | Current State | Complexity |
|---|---|---|---|
| **Modular backend** | Code reusability, easier debugging, testable components | Missing (full rewrite target) | High |
| **Modular frontend** | Component library, state management patterns | Missing (AMD modules target) | High |
| **Comprehensive test suite** | Greater than 85 percent coverage plus concurrency tests | Partial (43 tests, gaps in XSS/CSRF/concurrency) | High |
| **API schema (OpenAPI)** | Third-party integrators don't need source code | Missing | Low |
| **Deployment automation** | Docker compose works out-of-box | Complete (9.3.1 with sample data) | Low |
| **Dark/light theme** | Modern UX expectation; rare in Splunk apps | Complete (CSS variables, seamless toggle) | Low |

---

## Anti-Features

Explicitly NOT building. These would detract from quality or violate constraints.

| Anti-Feature | Why Avoid | What to Do Instead |
|---|---|---|
| **Framework migration** (React, Vue, Alpine) | Violates AppInspect requirement for jQuery + AMD | Stay within Splunk ecosystem |
| **Database backend** (PostgreSQL, SQLite) | Adds infrastructure complexity | CSV lookups are appropriate for scale |
| **External API calls** | Network dependency, SSRF risk | Use Splunk internal REST API only |
| **Webpack/bundlers** | AppInspect rejects; breaks Splunk asset serving | Use RequireJS (AMD) |

---

## AppInspect Compliance Map

AppInspect validates ~100 rules across 8 categories. Current app is partially compliant.

### Category 1: Required Files & Metadata
**Status: PASS**

| Check | Current |
|---|---|
| app.conf present, well-formed | PASS |
| [launcher] stanza with version | PASS |
| [package] id matches dirname | PASS |
| app.manifest with schema 2.0 | PASS |
| Version uses semantic versioning | PASS (v2.0.0) |
| Platform requirements documented | PASS (Splunk >=8.2) |
| README.md with screenshots | PASS (4 screenshots) |
| LICENSE file present | PASS (MIT) |

### Category 2: Python Code Quality
**Status: PASS with warnings**

| Check | Current | Notes |
|---|---|---|
| Python syntax valid | PASS | — |
| No hardcoded passwords | PASS | — |
| No hardcoded tokens | PASS | — |
| No eval() calls | PASS | — |
| No exec() calls | PASS | — |
| No os.system() calls | PASS | — |
| Imports from stdlib only | WARN | Uses splunklib (fallback to urllib available) |
| No .pyc files | PASS | Cleaned before package |

### Category 3: JavaScript & Frontend
**Status: PASS with gaps**

| Check | Current | Phase |
|---|---|---|
| Valid JavaScript syntax | PASS | — |
| No eval() in code | PASS | — |
| XSS prevention | PASS | All DOM inserts use _.escape() |
| AMD module structure | PARTIAL | Phase 1 rewrite target |
| jQuery usage (Splunk-bundled) | PASS | — |
| No external CDN links | PASS | All assets local |
| CSS class naming | PASS | All prefixed with wl- |

### Category 4: Configuration Files
**Status: PASS**

| Check | Current |
|---|---|
| restmap.conf well-formed XML | PASS |
| REST endpoints authenticated | PASS (requireAuthentication=true) |
| RBAC roles defined | PASS (4-tier system) |
| indexes.conf for custom index | PASS (wl_audit) |

### Category 5: Views & Dashboards
**Status: PASS**

| Check | Current |
|---|---|
| XML well-formed | PASS (2 dashboards validate) |
| No unsupported HTML in panels | PASS |
| Field names valid | PASS |
| Visualization plugins used properly | PASS |

### Category 6: Security & Permissions
**Status: PASS**

| Check | Current |
|---|---|
| No credentials in code | PASS |
| RBAC properly scoped | PASS |
| CSRF tokens validated | PASS (Splunk framework provides) |

### Category 7: Deployment & Packaging
**Status: PASS**

| Check | Current |
|---|---|
| .spl is valid tar.gz | PASS |
| Top-level directory correct | PASS (wl_manager/) |
| No system files in package | PASS (exclude via script) |

### Category 8: Documentation & Compatibility
**Status: PASS**

| Check | Current |
|---|---|
| Version consistent across files | PASS (2.0.0 everywhere) |
| Splunk version support documented | PASS (>=8.2) |
| Python version documented | PASS (3.9+) |
| Installation instructions | PASS (3 methods) |

---

## Test Coverage Standards

| Test Type | Expected | Current | Gap |
|---|---|---|---|
| **Unit tests** | 70 percent minimum | 40 percent (diff, validation, expiration) | High |
| **Integration tests** | All REST endpoints | 85 percent (16 test files) | Low |
| **Security tests** | XSS, injection, RBAC, path traversal | 10 percent (RBAC only) | High |
| **Concurrency tests** | Race conditions, file locking | 0 percent | High |
| **Browser E2E** | Key workflows | 20 percent (partial) | High |
| **Performance tests** | Large CSV loads, bulk ops | 30 percent (stress test exists) | Medium |

---

## Splunkbase Publication Checklist

### Pre-Submission (Critical Path)

- [x] GitHub repository public
- [ ] AppInspect 100 percent pass (local validation ~95 percent)
- [x] Security audit completed (APPROVED)
- [x] Version consistent across files
- [x] README with screenshots
- [x] Installation instructions tested
- [x] Demo container working
- [x] License file present

### Code Quality

- [x] Python syntax valid
- [x] JavaScript syntax valid
- [x] XML well-formed
- [x] No hardcoded secrets
- [x] No dangerous patterns
- [ ] Modular code organization (PENDING rewrite)
- [ ] Test suite 85 percent coverage (PENDING)
- [ ] Code comments for complex logic (PARTIAL)

### Security

- [x] Authentication on POST
- [x] RBAC enforced server-side
- [x] Input validation
- [x] XSS prevention
- [x] CSRF protection
- [x] Path traversal protection
- [ ] Documented security model (PENDING)

### Documentation

- [x] User guide
- [x] Admin installation guide
- [ ] API schema (OpenAPI) optional
- [ ] Security architecture doc (PENDING)
- [ ] Troubleshooting guide (PARTIAL)

---

## MVP for Splunkbase

If scope required cutting (it does not):

1. CSV viewing/editing with change tracking
2. RBAC and audit trail
3. Version control with revert
4. Approval workflows
5. Error handling and optimistic locking
6. Full documentation and screenshots
7. AppInspect validation passing
8. Modular architecture (defer if time-constrained)
9. 85 percent test coverage (defer if time-constrained)

---

## Key Quality Gaps

| Gap | Impact | Solution |
|---|---|---|
| **Monolithic backend** | Hard to maintain, test, or extend | Phase 1: Split into 10+ modules |
| **Monolithic frontend** | No component reuse, tangled state | Phase 1: AMD module structure |
| **Test gaps** | XSS, CSRF, concurrency untested | Phase 1: Add security + concurrency tests |
| **API undocumented** | Third-party integrators have no contract | Phase 2: OpenAPI schema |
| **No changelog** | Users can't track changes | Phase 2: Structured changelog.md |
| **No security doc** | Enterprise buyers uncertain | Phase 2: Security architecture doc |

---

## Confidence Assessment

| Area | Confidence | Notes |
|---|---|---|
| AppInspect rules | MEDIUM | Local script covers ~60 rules; actual validation ~100 rules |
| Splunkbase requirements | MEDIUM | Inferred from app.manifest schema and published apps |
| Quality benchmarks | LOW | Limited public examples of top-rated apps |
| Security standards | HIGH | Audit report provides evidence |
| Testing standards | MEDIUM | Based on public Splunk testing practices |

---

## Roadmap Implications

### Must-Have (Blocking Publication)

1. **AppInspect 100 percent pass** — Run official tool, fix failures
2. **Modular code** — Splunkbase reviewers inspect architecture
3. **85 percent test coverage** — Publish results with release
4. **Security documentation** — Threat model, RBAC breakdown

### Nice-to-Have (Differentiators)

5. **API schema** — Enables third-party integrations
6. **Community templates** — PR template, CONTRIBUTING.md
7. **Performance benchmarks** — Published metrics
8. **Splunk docs integration** — Links from official docs

---

*Research completed: 2026-03-31*  
*Confidence: MEDIUM across most areas; HIGH on security/testing*
