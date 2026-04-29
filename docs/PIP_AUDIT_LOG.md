# pip-audit Log — `requirements-dev.txt`

This file records every `pip-audit` run against the dev dependency set,
the findings, and the remediation taken. Goal: future audits start
with a known-clean baseline rather than re-discovering the same noise.

## Tooling

- `pip-audit` queries the OSV database + GitHub Advisory Database
- Backup query path used in the original audit: direct `POST` to
  `https://api.osv.dev/v1/query` for each pinned package, since the
  pip-audit virtualenv installer choked on a non-existent `radon` pin

## Cadence

- Run before every release tag
- Run on demand when a new dev dep is added or a pin is bumped
- Run quarterly even with no dep changes (new advisories land
  retroactively against existing versions)

Command:

```bash
pip-audit -r requirements-dev.txt --format json
```

If pip-audit fails to set up its sandbox venv (sometimes happens when
a pinned version was yanked or never existed), fall back to direct
OSV queries with the helper at the bottom of this file.

## Run history

### 2026-04-29 — round 7 B4

| Package | Pinned | OSV finding | Remediation |
|---------|--------|-------------|-------------|
| pytest | 8.1.1 | GHSA-6w46-j5rx-g56g (CVE-2025-71176, CVSS 5.5 LOCAL) — pre-9.0.3 pytest leaves the per-user tmpdir world-writable, allowing a local attacker on a shared host to symlink-trick a test into reading files outside the test's working directory. | Bumped to 9.0.3. Verified: 664 tests pass under 9.0.3 (579 unit + 85 module-level). No breaking API changes encountered in this codebase. |
| pytest-cov | 5.0.0 | clean | — |
| freezegun | 1.5.1 | clean | — |
| hypothesis | 6.90.0 | clean | — |
| pytest-timeout | 2.1.0 | clean | — |
| playwright | 1.40.0 | clean | — |
| radon | **6.1.1 (does not exist)** | n/a — pinned to a non-existent version. Latest published is 6.0.1. `pip install -r requirements-dev.txt` fails for new contributors. | Bumped to 6.0.1 (current latest). |

#### Bonus housekeeping found during the run

- `.github/workflows/ci.yml` referenced a removed-but-still-listed
  module-level filelock test file which no longer exists — the
  filelock tests now live entirely inside
  `tests/unit/test_filelock.py`. Two newer module-level tests
  (`tests/test_wl_fim_common.py`,
  `tests/test_wl_expiration_cleanup.py`) were not in the CI list.
  Both fixed in the same commit.

## Fallback OSV query helper

When `pip-audit` cannot resolve the requirements file (e.g., a yanked
pin), this script queries OSV directly per package and reproduces the
same advisory data:

```python
import urllib.request, json
def check(name, version):
    body = json.dumps({
        "version": version,
        "package": {"name": name, "ecosystem": "PyPI"},
    }).encode()
    req = urllib.request.Request(
        "https://api.osv.dev/v1/query",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=20).read())
    return resp.get("vulns", [])

# Example:
# print(check("pytest", "8.1.1"))
```
