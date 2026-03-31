# Testing

## Framework & Infrastructure

| Aspect | Details |
|--------|---------|
| Framework | Python `unittest` (stdlib) |
| Runner | `python -m unittest` or `python -m pytest` |
| Test directory | `tests/` (24 files, 9,007 lines) |
| Base class | `tests/test_integration_base.py` — shared helpers, constants, API wrappers |
| Dependencies | No external test framework — stdlib only (`unittest`, `urllib`, `json`, `ssl`) |
| CI | `.github/workflows/ci.yml` |

## Test Categories

### Unit Tests (standalone, no Splunk required)
| File | What it tests | Technique |
|------|--------------|-----------|
| `test_compute_diff.py` | `_compute_diff()` algorithm | Extracts function from source via regex (avoids Splunk SDK imports) |
| `test_safe_filename.py` | Filename sanitization | Direct function extraction |
| `test_remove_expired_rows.py` | Expiration logic | Direct function extraction |

### Integration Tests (require running Splunk Docker container)
| File | What it tests |
|------|--------------|
| `test_approval_gates.py` | Approval workflow gates and notifications |
| `test_approval_workflow.py` | Full approval lifecycle |
| `test_bulk_edit.py` | Bulk edit operations and diff correctness |
| `test_combined_actions.py` | Simultaneous add/remove/edit |
| `test_comprehensive.py` | Full feature coverage |
| `test_cross_admin.py` | Dual-admin and cross-admin operations |
| `test_csv_import.py` | CSV import/create operations |
| `test_daily_limits.py` | Rate limiting enforcement |
| `test_e2e_advanced.py` | Advanced end-to-end scenarios |
| `test_e2e_api.py` | API-level end-to-end |
| `test_e2e_realworld.py` | Real-world usage patterns |
| `test_expiration.py` | Row expiration logic |
| `test_final.py` | Final integration verification |
| `test_rbac.py` | 4-tier RBAC enforcement |
| `test_stress.py` | Load testing (large CSVs) |
| `test_version_revert.py` | Version control and revert |

### Browser Tests
| File | What it tests |
|------|--------------|
| `test_ui_browser.py` | Browser-based UI interactions |
| `test_e2e_manual_browser.py` | Manual browser E2E scenarios |

## Test Patterns

### Function Extraction Pattern
Unit tests can't import `wl_handler.py` directly (requires Splunk SDK). Instead, they:
1. Read `wl_handler.py` source as text
2. Extract target function definition via regex
3. Run the extracted code in a minimal namespace with required stdlib imports
4. Test the function in isolation

### Integration Test Base
`test_integration_base.py` provides:
- **Constants:** `ADMIN`, `WLADMIN1`, `ANALYST1`, test CSV/rule names
- **API helpers:** `api_get()`, `api_post()`, `get_csv_content()`, `save_csv()`
- **Workflow helpers:** `submit_approval()`, `process_approval()`, `cancel_request()`
- **Wait helpers:** `wait_for_indexing()` — polls Splunk until audit events appear
- **SSL context:** Disabled verification for localhost Docker container

### Test Run Commands
```bash
# Unit tests (no Splunk needed)
python -m pytest tests/test_compute_diff.py tests/test_safe_filename.py -v

# Integration tests (requires Docker container running)
python -m pytest tests/test_rbac.py -v

# All tests
cd tests && python -m unittest discover -v

# Via script
./scripts/test_integration.sh
```

## Mocking Strategy

- **No mocking framework used** — tests run against real Splunk instance in Docker
- Unit tests use function extraction to avoid Splunk SDK dependency
- Integration tests use real HTTP calls to `https://localhost:8089`
- Test data created/cleaned up per test via API calls

## Coverage Assessment

| Area | Coverage | Notes |
|------|----------|-------|
| Diff algorithm | Good | Dedicated unit tests |
| RBAC enforcement | Good | Tests all 4 role tiers |
| Approval workflow | Good | Multiple test files |
| CSV CRUD operations | Good | Integration tests |
| Version control/revert | Good | Dedicated tests |
| Daily limits | Good | Dedicated tests |
| Concurrent writes | None | No file locking tests |
| XSS/injection | None | No security-specific tests |
| CSRF | None | No CSRF validation tests |
| Browser UI interactions | Partial | `test_ui_browser.py` exists |
| Control panel admin UI | Unknown | No dedicated tests found |
| Notification system | Partial | Tested via approval tests |

## Validation Scripts

| Script | Purpose |
|--------|---------|
| `scripts/validate.sh` | Runs Splunk AppInspect validation |
| `scripts/package.sh` | Creates .spl package |
| `scripts/test_integration.sh` | Runs integration test suite |

---
*Generated: 2026-03-31 by gsd:map-codebase*
