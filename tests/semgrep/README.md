# Semgrep security rules

Splunk-adapted Semgrep rules that gate every PR via
[`.github/workflows/semgrep.yml`](../../.github/workflows/semgrep.yml).

## What's here

| File | What it catches | Severity |
|---|---|---|
| `ssrf-splunk.yaml` | Splunk handler payload flowing into `urllib.request.urlopen` / `urllib.request.Request` / `requests.{get,post}` without a hardcoded-localhost prefix | ERROR |
| `command-injection-splunk.yaml` | Payload reaching `subprocess.{run,Popen,call,check_call,check_output}(..., shell=True, ...)` without `shlex.quote` / `shlex.join` | ERROR |
| `path-traversal-splunk.yaml` | Payload reaching `open`, `os.path.join`, `shutil.copy*`, `os.rename`, `os.remove`, etc. without going through one of our validation wrappers (`build_csv_path`, `resolve_csv_path`, `is_safe_filename`) or a path-canonicalization sanitizer (`abspath`, `realpath`, `Path(...).resolve()`, `basename`, `startswith` containment check) | ERROR |
| `payload-from-flag-bypass-splunk.yaml` | Reads of `_from_*` flags from the user-controlled REST `payload` dict (e.g. `payload.get("_from_approval")` or `payload["_from_dual_approval"]`). Writes (LHS of assignment) are explicitly allowed because they're server-controlled mutations by replay code. | ERROR |

The first three are **taint mode**: they follow data from source (our handler's
payload accessors) to sink (dangerous calls) and only fire if no sanitizer
breaks the flow.

The fourth (`payload-from-flag-bypass-splunk.yaml`) is **pattern mode** — it
matches a structurally-illegitimate code shape rather than a tainted dataflow.
It pairs with
`tests/unit/test_ascii_validation.py::TestNoUnderscoreFlagPayloadBypass` for
post-merge enforcement; the Semgrep rule fires earlier in the dev loop (PR
review) so a regression is caught before reaching a human reviewer.

## Origin

Adapted from [`gadievron/raptor`](https://github.com/gadievron/raptor)'s
`engine/semgrep/rules/` — MIT licensed. The RAPTOR originals target
generic Flask/Django webapps, so the `pattern-sources` list is rewritten
for Splunk `BaseRestHandler` patterns (`request.get($_)`, `payload.get($_)`,
`payload[$_]`). The sink lists and sanitizer lists are widened for the
idioms wl_manager actually uses (stdlib `urllib`, not `requests`; our
`wl_validation.build_csv_path` as the canonical path sanitizer).

## Running locally

```bash
# Via the official Semgrep Docker image (no host install)
docker run --rm \
  -v "$(pwd)/tests/semgrep:/rules:ro" \
  -v "$(pwd)/bin:/src:ro" \
  semgrep/semgrep semgrep --config=/rules --error --metrics=off /src
```

`--error` exits non-zero on any finding — same gate CI uses.

For a **wider one-shot audit** that includes the non-taint
`splunk.ssrf.dynamic-url` rule (flags every outbound HTTP call for review,
not for CI gating), pull the rule from
[RAPTOR upstream](https://github.com/gadievron/raptor/blob/main/engine/semgrep/rules/sinks/ssrf.yaml)
and run it side-by-side — it's not shipped here because it would produce
8 permanent "findings" on legitimate hardcoded splunkd management-port
URLs and drown the signal.

## When a finding fires

1. **Don't add `# nosemgrep` reflexively.** The rule fired because a
   payload reached a dangerous sink without a sanitizer. If the sanitizer
   exists but is a wrapper the rule doesn't recognize, add the wrapper
   name to the rule's `pattern-sanitizers` list instead — that teaches
   the scanner once for everyone.
2. **If the finding is a real bug**, fix the code (add `build_csv_path`,
   `shlex.quote`, or the relevant sanitizer).
3. **If the finding is architecturally impossible** (e.g. the payload
   variable is actually a hardcoded constant reassigned from a config
   file), refactor so the scanner's reading matches reality — don't
   suppress.

## Adding new rules

Keep these rules **taint mode** unless you have a strong reason for
pattern mode. Non-taint rules fire on every matching call site, produce
noise, and can't be CI-gated without permanent suppressions. The existing
three cover the OWASP A01/A03/A10-style backend flaws most likely to
surface in a Splunk REST handler; anything added here should be the
same shape (untrusted → sink → sanitizer).

Adapted sources live under `.audit/adapted-rules/` locally (gitignored)
as the authoring sandbox. Promote to this directory only once the rule
has zero false positives on the existing codebase.
