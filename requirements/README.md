# Hashed Python requirements lockfiles

This directory holds the `.in` source files and `--generate-hashes`
lockfiles consumed by the workflows under `.github/workflows/`. The
lockfiles let those workflows run `pip install --require-hashes -r
requirements/<file>.txt`, which:

- Pins every transitive dependency to a specific version + SHA-256
  hash (closes the Scorecard `pipCommand not pinned by hash` finding)
- Detects registry-swap attacks where a malicious actor publishes a
  different artifact under the same version on a PyPI mirror
- Makes CI builds bit-for-bit reproducible across runners

## Files

| `.in` (source) | `.txt` (lockfile) | Consumed by |
|---|---|---|
| `test.in` | `test.txt` | `.github/workflows/ci.yml`, `integration-tests.yml` |
| `docs.in` | `docs.txt` | `.github/workflows/docs.yml` (build + deploy jobs) |
| `pip-audit.in` | `pip-audit.txt` | `.github/workflows/pip-audit.yml` |
| `appinspect.in` | `appinspect.txt` | `.github/workflows/appinspect.yml` |

The `.in` files are the human-edited source of truth — they declare
direct dependencies and version ranges/pins. The `.txt` files are
mechanically generated from the `.in` files by `pip-compile` and
must NOT be hand-edited.

## When to regenerate

- A direct dependency in an `.in` file changes (version bump, new
  package, removal)
- A security advisory requires bumping a transitive dependency
- Dependabot opens a PR against one of the `.in` files (regenerate
  the matching `.txt` before merging)

## How to regenerate

Run `scripts/regen_requirements.sh` from the repo root. The script
runs `pip-compile --generate-hashes --strip-extras` inside a
`python:3.11-slim` container so the lockfile matches what CI sees,
regardless of which platform the maintainer is on.

If Docker is not available, run on a Linux/macOS host with Python 3.11:

```bash
python -m pip install pip-tools
for f in test docs pip-audit appinspect; do
  pip-compile --generate-hashes --strip-extras \
    --output-file=requirements/$f.txt requirements/$f.in
done
```

Generating on Windows or a different Python version can produce
platform-specific transitive resolutions (e.g., Windows-only `pywin32`)
that won't match CI. Always regenerate in a Linux + Python 3.11
environment.

## Verifying a lockfile

```bash
# Sanity check: the lockfile installs cleanly with --require-hashes
python -m venv /tmp/wlmgr-reqcheck
/tmp/wlmgr-reqcheck/bin/pip install --upgrade pip
/tmp/wlmgr-reqcheck/bin/pip install --require-hashes -r requirements/test.txt
```

If any hash fails or any required package is missing, `pip` exits
non-zero. CI will catch the same failure on the next push.
