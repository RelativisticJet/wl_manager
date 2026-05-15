# Release Prep Checklist

Pre-release verification steps for `wl_manager`. Run through this list before
cutting any tagged release, packaging for Splunkbase, or pushing to a public
GitHub release.

> **Status (2026-04-16):** Public release is **not** imminent — more features
> and additional E2E rounds are planned. This checklist exists so the parity
> checks stay current as the codebase grows; running them periodically (not
> only at release time) keeps drift small.

---

## 1. Audit Dashboard ↔ Action Code Parity

The Audit Trail dashboard's Action dropdowns (`default/data/ui/views/audit.xml`)
are split into "General Action" and "Admin Action". Whenever a backend module
emits a new `action=` value, the dropdown can silently fall behind — the audit
log shows the action but the dashboard filter has no choice for it. Audit
investigators then can't filter on the new action type.

**Run:**

```bash
# 1. List every action emitted by any handler module
grep -rh '"action":' bin/*.py 2>/dev/null \
  | grep -oE '"action"\s*:\s*"[a-z_]+"' \
  | grep -oE '[a-z_]+(?=")' \
  | sort -u > /tmp/code_actions.txt

# 2. List every choice value present in the audit dashboard dropdowns
grep -oE 'value="[a-z_]+"' default/data/ui/views/audit.xml \
  | grep -oE '[a-z_]+' | sort -u > /tmp/view_actions.txt

# 3. Show actions in code but missing from dropdowns
echo "=== Missing from dropdowns (in code, NOT in view) ==="
comm -23 /tmp/code_actions.txt /tmp/view_actions.txt

# 4. Show stale dropdown choices (in view, NOT in code)
echo "=== Stale dropdowns (in view, NOT in code) ==="
comm -13 /tmp/code_actions.txt /tmp/view_actions.txt
```

**What to do with the output:**

- **Missing from dropdowns** — for each, classify as General (data/CSV/request
  lifecycle) or Admin (governance/security/recovery) per the comment block in
  `audit.xml`, then add a `<choice>` to the right dropdown. See the
  classification rule in the XML for borderline cases.
- **Stale dropdowns** — only worth removing if the action type was renamed or
  permanently retired. If an action just hasn't fired in your test data
  recently, keep the dropdown choice (users may want to filter historical
  events).
- **FIM actions (`fim_*`)** — most go to `sourcetype=wl_fim` rather than
  `wl_audit`, so they show in the FIM panel and don't need dropdown coverage.
  Exceptions are `fim_deploy_window_start/end` which DO go to `wl_audit` and
  must be in the Admin dropdown.

**Acceptance:** zero entries in "Missing from dropdowns" output, OR every
listed action has a documented reason for exclusion (e.g., FIM-only).

---

## 2. wl_debug.js Removed

Confirm no entry point loads the dev-aid module:

```bash
grep -rE "wl_debug" appserver/static/whitelist_manager.js \
                    appserver/static/control_panel.js \
                    appserver/static/audit_trail.js
# Expected: no matches
```

---

## 3. Build Number Bumped

Splunk caches static assets aggressively. Every release must bump
`default/app.conf [install] build = N`.

```bash
grep -E "^build\s*=" default/app.conf
```

---

## 3.5. Version-Tag Consistency (pre-flight before `git tag`)

`scripts/package.sh` derives `<VERSION>` for the .spl filename from
`default/app.conf:version`, NOT from the git tag. If the two diverge —
e.g., we cut tag `v1.0.0-rc2` while `app.conf:version` still says
`1.0.0-rc1` — the produced .spl will be named
`wl_manager-1.0.0-rc1.spl` and uploaded to the `v1.0.0-rc2` release.
Sigstore identity still verifies (it's keyed to the tag, not the
artifact filename), but the customer-facing artifact name mismatches
the release page → support tickets.

This drift was caught during the 2026-05-13 Sigstore dry-run as a
"side-finding worth follow-up but not blocking" (see §8 Outcome
notes). Added here as a permanent pre-tag-cut check.

**Run before pushing any new tag:**

```bash
# Pick the tag name you're about to cut, e.g.
INTENDED_TAG=v1.0.0-rc1

# Extract the bare version (strip the leading "v")
INTENDED_VERSION="${INTENDED_TAG#v}"

# Pull both app.conf version stanzas (AppInspect requires they match)
LAUNCHER_VER=$(awk -F= '/^\[launcher\]/{flag=1; next} /^\[/{flag=0} flag && /^version/{gsub(/[[:space:]]/,""); print $2}' default/app.conf)
ID_VER=$(awk -F= '/^\[id\]/{flag=1; next} /^\[/{flag=0} flag && /^version/{gsub(/[[:space:]]/,""); print $2}' default/app.conf)

if [[ "$LAUNCHER_VER" != "$INTENDED_VERSION" || "$ID_VER" != "$INTENDED_VERSION" ]]; then
  echo "VERSION DRIFT: tag=$INTENDED_TAG app.conf[launcher]=$LAUNCHER_VER app.conf[id]=$ID_VER"
  echo "Fix app.conf before cutting the tag."
  exit 1
fi
echo "OK: app.conf version matches tag $INTENDED_TAG"
```

**Expected:** the script exits 0 with `OK: ...`. Any non-zero exit means
both `[launcher].version` and `[id].version` in `default/app.conf` need
to be edited to match `${INTENDED_TAG#v}` BEFORE you run `git tag` /
`gh release create`.

**Maintenance note:** keep this check in sync with `package.sh:33`
(the grep that reads `^version` from app.conf). If `package.sh` ever
switches to reading from `$GITHUB_REF` instead, retire this section.

---

## 4. E2E Suite Green

```bash
WL_TEST_HARNESS=1 ./tests/e2e/run_all.sh   # or whichever runner is current
```

Expected: all suites pass (current baseline 274/274 + audit dropdown 7/7).

---

## 5. AppInspect Dry-Run

Run Splunk's AppInspect tool against a packaged tarball. See
`docs/APPINSPECT_NOTES.md` for known-warning justifications.

---

## 6. No Uncommitted Working-Tree Changes

```bash
git status --short
# Expected: clean tree (or only the release-tag commit pending)
```

---

## 7. CHANGELOG / Release Notes Drafted

Summarize user-facing changes since the last tag (not internal refactors).
Audit-trail dashboard changes are user-facing — flag dropdown reorganizations
or new filters here.

---

## 8. Sigstore Signing — End-to-End Verification [x] DONE — verified 2026-05-13 on tag v0.0.0-sigstore-test

**Background.** Round 8 (build 629, 2026-04-29) wired Sigstore keyless
signing into `.github/workflows/release.yml`. The workflow uses GitHub
Actions' OIDC token to mint short-lived ephemeral keys via Fulcio,
records the signature in the Rekor transparency log, and produces
`<artifact>.sig` + `<artifact>.crt` alongside the `.spl` and `.cdx.json`.

**The signing path has never been verified end-to-end** — wiring was
deferred until first release rather than tested in a throwaway tag,
because every `release: published` event is observable to anyone
watching the repo and the per-run cost on Sigstore's public infra is
non-zero.

This section MUST be completed before the first signed release ships
publicly. After that, the daily CI job + per-release runs prove the
path stays healthy; this section becomes a one-shot.

### Step 1 — Cut a draft / pre-release tag

Use a `v0.0.0-sigstore-test`-style tag on a throwaway commit so a
verification failure can't affect customer-facing releases:

```bash
git tag v0.0.0-sigstore-test
git push origin v0.0.0-sigstore-test
gh release create v0.0.0-sigstore-test \
  --prerelease \
  --title "Sigstore E2E verification" \
  --notes "Throwaway tag — DO NOT INSTALL. Used to prove the signing pipeline."
```

Watch the run via `gh run watch` and confirm:

- The "Sign .spl with Sigstore (keyless)" step succeeded
- The "Sign per-release SBOM with Sigstore (keyless)" step succeeded
- All four asset types are attached: `.spl`, `.sha256`, `.cdx.json`,
  `.sig`, `.crt`

### Step 2 — Download and verify the legitimate artifact

```bash
mkdir -p /tmp/sigstore-verify && cd /tmp/sigstore-verify
gh release download v0.0.0-sigstore-test
ls -la   # should list .spl, .sha256, .cdx.json, .spl.sig, .spl.crt,
         #                                     .cdx.json.sig, .cdx.json.crt

# Install cosign locally if not already (one-time setup)
# https://docs.sigstore.dev/cosign/installation/

cosign verify-blob \
  --certificate wl_manager-*.spl.crt \
  --signature   wl_manager-*.spl.sig \
  --certificate-identity-regexp \
    'https://github.com/RelativisticJet/wl_manager/.github/workflows/release.yml@refs/tags/.*' \
  --certificate-oidc-issuer \
    https://token.actions.githubusercontent.com \
  wl_manager-*.spl
```

**Expected:** `Verified OK`. Anything else = pipeline broken; do not
ship a real release until resolved.

Also verify the SBOM signature with the same command pattern, swapping
the artifact + cert + sig file names.

### Step 3 — Tamper test (proves the verifier actually verifies)

```bash
cp wl_manager-*.spl wl_manager-tampered.spl
echo "tamper" >> wl_manager-tampered.spl

cosign verify-blob \
  --certificate wl_manager-*.spl.crt \
  --signature   wl_manager-*.spl.sig \
  --certificate-identity-regexp \
    'https://github.com/RelativisticJet/wl_manager/.github/workflows/release.yml@refs/tags/.*' \
  --certificate-oidc-issuer \
    https://token.actions.githubusercontent.com \
  wl_manager-tampered.spl
```

**Expected:** verification FAILS with a hash-mismatch error. If it
passes, the verifier is wired wrong — investigate before shipping.

### Step 3b — Foreign-signature identity-pin test (rigor extension)

Step 3 proves the verifier rejects a tampered artifact. Step 3b
proves the verifier also rejects a **legitimately-signed artifact
from a different repo** — i.e., that the identity-regex pin is
actually load-bearing, not just signature-integrity.

Why this matters: Sigstore signatures are "valid" in two stages —
(a) the cryptographic signature is well-formed and the cert chain
is OK, and (b) the cert's identity claim matches the regex pin. A
broken or absent identity pin would silently accept any
sigstore-signed artifact from anyone (including an attacker's repo
running their own GitHub Actions workflow). Step 3 doesn't exercise
this — it only checks signature integrity.

Pick any other Sigstore-signed artifact + its `.sig` + `.crt`
(a known-good reference today: a recent `sigstore/cosign` release
asset, since cosign self-signs via Google OIDC, not GitHub
Actions). Then attempt to verify it against THIS repo's identity
regex.

```bash
# Download a foreign Sigstore-signed asset for the test:
#   - Reference: sigstore/cosign v2.4.3 .rpm (signed via Google OIDC)
#   - URL pattern: https://github.com/sigstore/cosign/releases/download/v2.4.3/cosign-2.4.3-1.x86_64.rpm
#
# Then attempt verification against THIS repo's identity-regex
# (NOTE: cosign-release v2.4.1 expects --new-bundle-format=false for
# pre-v3 signatures; remove flag if upgrading per Phase 2.12).
cosign verify-blob \
  --certificate cosign-2.4.3-1.x86_64.rpm.crt \
  --signature   cosign-2.4.3-1.x86_64.rpm.sig \
  --certificate-identity-regexp \
    'https://github.com/RelativisticJet/wl_manager/.github/workflows/release.yml@refs/tags/.*' \
  --certificate-oidc-issuer \
    https://token.actions.githubusercontent.com \
  cosign-2.4.3-1.x86_64.rpm
```

**Expected:** verification FAILS, but with a DIFFERENT error than
Step 3. The error must reference the identity-regex mismatch (the
foreign cert was issued for a `sigstore/cosign` identity, not
`RelativisticJet/wl_manager`) or the OIDC-issuer mismatch (Google
vs GitHub Actions). The signature itself IS valid for that foreign
artifact — what fails is the identity pin.

If this step passes (i.e., the foreign artifact is accepted), the
identity pin is broken. STOP. Do not ship — any sigstore-signed
artifact in the world would be accepted as if it came from this
repo.

**Origin:** added 2026-05-15 as a permanent extension after the
2026-05-13 dry-run discovered this gap by accident. See "Outcome
notes" below.

### Step 4 — Confirm Rekor transparency-log entry

```bash
cosign verify-blob ... --rekor-url https://rekor.sigstore.dev <args from step 2>
```

**Expected:** the verify command (with `--rekor-url`) confirms a
matching entry in the public log. The Rekor entry is the cryptographic
receipt that this artifact existed at release time — it's what makes
the signing scheme tamper-evident even against a future repo takeover.

### Step 5 — Document the verifier command for downstream users

After Step 2-4 pass, copy the working `cosign verify-blob` invocation
into:

- `README.md` — "Verifying a downloaded release" section
- `INSTALLATION.md` — recommended verification step before
  `splunk install app`
- `docs/SBOM.md` — append under the existing
  "## Distribution integrity" section

Use the EXACT command that worked in Step 2 — paraphrased versions
that look right but use slightly different flags create support
tickets.

### Step 6 — Tear down the test release

```bash
gh release delete v0.0.0-sigstore-test --yes
git tag -d v0.0.0-sigstore-test
git push origin :refs/tags/v0.0.0-sigstore-test
```

Leaves the repo clean for the real first release tag.

### Acceptance

- Steps 2+3+3b+4 all produced the expected outcomes (legit verify OK,
  tamper verify FAIL on signature, foreign-signature verify FAIL on
  identity, Rekor entry confirmed)
- Verifier command published in at least one customer-facing doc
- Test release deleted

After this section is completed once, mark this section as
**`[x] DONE — verified <date> on tag <tag-name>`** in this file and
leave it in place. Future releases verify automatically via the
quarterly pip-audit cadence + per-release workflow run; this one-shot
just proves the wiring.

### Outcome notes (2026-05-13 dry-run on tag v0.0.0-sigstore-test)

5/5 verification scenarios passed:

- Step 2 (legit verify against production identity-regex) — `Verified OK`
- Step 3 (tamper test, appended bytes to .spl) — failed with "invalid
  signature when validating ASN.1 encoded signature"
- Step 3b (foreign-signature identity-pin test, added as a rigor
  extension to this runbook) — verified that a known-good Sigstore
  signature from a different repo (`sigstore/cosign` v2.4.3 RPM, which
  is signed via Google OIDC, not GitHub Actions) is rejected by the
  production identity-regex. Confirms the identity pin is the actual
  security boundary, not just signature-integrity. Recommend adding
  Step 3b to this checklist permanently.
- Step 4 (Rekor lookup with explicit `--rekor-url`) — `Verified OK`
- Bonus: SBOM (`.cdx.json`) signature verifies the same way

Verifier command published in `docs/SBOM.md` (canonical) with pointers
from `README.md` (Security section) and `INSTALLATION.md` (Section 3.6).

Three side-findings worth follow-up but not blocking:

- The release workflow runs `actions/checkout@v4` + `actions/setup-python@v5`
  which both deprecate Node 20; GitHub forces Node 24 by 2026-09-16.
- `cosign-release: 'v2.4.1'` outputs `.crt` as base64-wrapped PEM
  (cosign-internal format). cosign verify-blob handles it transparently;
  only matters for openssl inspection.
- `scripts/package.sh` derives `<VERSION>` for the .spl filename from
  `default/app.conf:version`, not from the git tag. Pre-tag-cut step
  must bump `app.conf:version` to match the tag, otherwise the .spl
  filename mismatches the tag and Sigstore identity still verifies but
  the customer-facing artifact name looks wrong. Add to "Tag cut"
  pre-checklist on next round.

The two prerequisite fixes that the dry-run forced (commits 691c651 +
6f8dc79) are not Sigstore-related — they were pre-existing validate.sh
issues that had never been exercised by a passing release run.
