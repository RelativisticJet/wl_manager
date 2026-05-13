# Software Bill of Materials (SBOM) + Subresource Integrity (SRI)

Origin: round 7 C1 (2026-04-29). This document captures the
distribution-chain investigation: what we ship, how it gets to
customers, and what the realistic supply-chain attack surface looks
like.

## What gets distributed

The only customer-facing artifact is `dist/wl_manager-<version>.spl` —
a gzipped tarball produced by `scripts/package.sh` and uploaded to
GitHub Releases by `.github/workflows/release.yml`. The .spl
contains, at the time of writing:

- Backend Python modules under `bin/` — first-party code
- Frontend AMD modules under `appserver/static/` and
  `appserver/static/modules/` — first-party code
- Splunk configuration under `default/` — first-party config
- Default lookups under `lookups/` (header-only `rule_csv_map.csv`,
  no sample CSVs)
- Static assets (icons, images) under `static/`
- App metadata under `metadata/`

It explicitly excludes (see `package.sh` --exclude flags):

- `.git`, `.github`, `.claude`, `.vscode`, `.docker`,
  `.code-review-graph`, `.pytest_cache`, `.superpowers`
- Test code (`tests/`)
- Documentation (`docs/`)
- Operational scripts (`scripts/`)
- Demo materials (`demo/`)
- Development-only files (`docker-compose.yml`, `.dockerignore`,
  `.gitignore`, `Makefile`, `CLAUDE.md`)
- Per-instance state (`local/`, `lookups/_versions/`,
  `lookups/_*.json`)
- Sample whitelist CSVs (`lookups/DR*`, `lookups/*.bak`)
- Build artifacts (`__pycache__`, `*.pyc`, `*.spl`)

## Third-party runtime dependencies

**None bundled.** The .spl tarball contains zero third-party
libraries. All runtime dependencies are provided by Splunk
Enterprise:

| Layer | Provider | Notes |
|-------|----------|-------|
| Python interpreter | Splunk-bundled at `/opt/splunk/bin/python3` | We do NOT ship our own |
| Python stdlib | Splunk-bundled | We import only `json`, `os`, `re`, `time`, `hmac`, `hashlib`, `urllib`, etc. |
| `splunk.rest.BaseRestHandler` | Splunk Enterprise | REST handler base class |
| `splunklib` | Splunk Enterprise | KV-store client, config parsing |
| jQuery | Splunk-bundled | Frontend AMD `require(['jquery'])` |
| Underscore.js | Splunk-bundled | Frontend AMD `require(['underscore'])` |
| `splunkjs/mvc/utils` | Splunk-bundled | REST helpers from Splunk's web framework |
| RequireJS | Splunk-bundled | AMD loader serving the modules |

This drastically reduces our supply-chain surface: there is no
`vendor/` directory, no bundled minified JS, and no transitive
dependency graph to scan. Vulnerabilities in jQuery, Underscore,
or any other Splunk-bundled library are Splunk's responsibility —
we track them via Splunk's release notes and our own quarterly
version-pinning audit (`CLAUDE.md` "Splunk Version Pinning Audit").

## Third-party dev dependencies (not shipped)

Audited separately in `docs/PIP_AUDIT_LOG.md` (B4):

- `pytest`, `pytest-cov`, `freezegun`, `hypothesis`,
  `pytest-timeout`, `playwright`, `pytest-playwright`, `radon`
- `playwright-core` (Node) for the E2E test runner

None of these are present in the .spl. They run only on developer
machines and CI runners.

## Distribution integrity

The release workflow (`release.yml`) uploads two artifacts per tag:

- `wl_manager-<version>.spl` — the app
- `wl_manager-<version>.spl.sha256` — SHA-256 hash of the .spl

Customers verify by:

```bash
curl -L -O https://github.com/RelativisticJet/wl_manager/releases/download/<tag>/wl_manager-<version>.spl
curl -L -O https://github.com/RelativisticJet/wl_manager/releases/download/<tag>/wl_manager-<version>.spl.sha256
sha256sum -c wl_manager-<version>.spl.sha256
```

### Limitations of the current model

1. (resolved as of 2026-05-13) — The .spl is now Sigstore-signed in
   addition to having a SHA-256 sidecar. Customers who run only the
   `sha256sum -c` check have the same exposure to a release-channel
   takeover as before, but customers who run the cosign verification
   below cannot be deceived by a Releases-page swap.
2. There is still no GPG signature on the .sha256 file. A `gpg --verify`
   step would tie the release to a maintainer key whose public half is
   distributed out-of-band. Not in this round; see "Future hardening"
   below.

### Verifying a release with cosign

Each release ships `.sig` (signature) and `.crt` (Fulcio short-lived
certificate) sidecar files for both the `.spl` and the `.cdx.json`
SBOM. The signing identity is the GitHub Actions workflow
(`.github/workflows/release.yml`) that produced the artifact, recorded
in the Rekor transparency log.

Install cosign (>= v2.4):

- macOS: `brew install cosign`
- Linux: see <https://docs.sigstore.dev/cosign/system_config/installation/>
- Windows: `winget install sigstore.cosign`

Verify (replace `<VERSION>` with the release you're installing):

```bash
cosign verify-blob \
  --new-bundle-format=false \
  --certificate wl_manager-<VERSION>.spl.crt \
  --signature wl_manager-<VERSION>.spl.sig \
  --certificate-identity-regexp '^https://github.com/RelativisticJet/wl_manager/\.github/workflows/release\.yml@refs/tags/.*$' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  wl_manager-<VERSION>.spl
```

A passing verifier prints `Verified OK`. A tampered .spl or a signature
from any other repo's workflow fails closed.

`--new-bundle-format=false` is required for cosign 3.x because the
release workflow currently signs with cosign v2.4.1 (producing the
legacy `.sig` + `.crt` pair, not the new single-`.sigstore`-bundle
format that cosign 3.x defaults to). cosign 2.x users can drop the
flag — the command works either way.

You can also verify the SBOM the same way by substituting
`wl_manager-<VERSION>.spl.cdx.json` and its `.sig` / `.crt` pair.

### Future hardening (not in this round)

- **GPG sidecar on .sha256**: a maintainer key distributed via a `KEYS`
  file at repo root, with `release.yml` GPG-signing the .sha256. Heavier
  than Sigstore but matches what most established Splunk apps ship.
  Defense-in-depth against the day Fulcio's CA cert chain rotates faster
  than customers can update their cosign install.
- **Upgrade signing to cosign v3.x new-bundle format**: removes the
  `--new-bundle-format=false` flag from the customer command. Wait until
  the customer base demonstrates they're on cosign 3.x; today most
  package managers still ship cosign 2.x.

## Subresource Integrity (SRI) — N/A by architecture

SRI is the `<script integrity="sha384-...">` mechanism that lets a
browser refuse to execute a JS file whose hash doesn't match a
declared value. It exists to protect pages that load scripts from
CDNs / third-party origins.

In our architecture there is no third-party origin to protect:

- All frontend modules under `appserver/static/` are served by
  Splunkweb itself (port 8000) from the same origin as the
  dashboard. They are served via Splunk's internal asset pipeline
  with a cache-busting `_b=<build>` parameter (see
  `quirk_splunk_static_cache_1yr.md`).
- Splunk's bundled libraries (jQuery, Underscore) are served from
  the same Splunk origin, not from a CDN.
- SimpleXML dashboards do not allow injecting raw `<script
  src="https://...">` tags pointing at external resources, so
  there is no place to add an `integrity=` attribute even if we
  wanted to.

If a future feature adds a `<script src="...">` pointing at an
external resource (CDN-hosted library, third-party widget), SRI
should be applied at that point. Until then, SRI is structurally
not applicable.

The integrity guarantees we DO have:

- The Splunk-internal cache layer signs static assets with a
  server-build hash (`/static/@<server-hash>/...`) — corruption
  in the cache invalidates the URL automatically.
- Browser cache invalidation is forced via `urlArgs: "_b=<build>"`
  every time we bump `default/app.conf` `build`. See
  `feedback_three_layer_fix_pattern.md` for the rule that ties
  these together.
- The .spl integrity check at install time (above) ensures the
  static assets reach the Splunk instance unmodified.

## Baseline SBOM (CycloneDX 1.5)

A minimal CycloneDX-format SBOM is committed alongside this doc as
`sbom.cdx.json`. Regenerate per release; the static version below
captures build 627 (2026-04-29) for reference. Per-release
generation is a future improvement (next round) — adding a step
to `release.yml` that runs a CycloneDX generator over the produced
.spl and uploads the SBOM as a third release artifact.

The SBOM structure is intentionally minimal because the dependency
graph is shallow (1 first-party app, 1 declared platform
requirement). Customers running automated SCA tools will get a
clean "no third-party components, no known vulnerabilities" report
out of it.
