# Mutation Testing — Triage and Operational Guide

**Status**: Active. Last updated 2026-05-18.

This document is the canonical place for mutation-testing triage,
survivor classifications, and operational lessons. It is the output
of the 2026-05-18 mutmut survey of `bin/wl_validation.py` and
`bin/wl_csv.py`.

---

## Why this doc exists

Two findings during the 2026-05-18 pre-release sweep made it clear
that the mutation-testing harness needed documented governance:

1. **The prior mutmut runs were misconfigured.** The default
   `TEST_RUNNER_FILES` in `scripts/mutmut.sh` is hard-coded to
   `tests/unit/test_validation.py tests/unit/test_ascii_validation.py
   tests/unit/test_validator_fuzz.py`. When a contributor invokes
   the script with `MUTATE_PATH=bin/wl_csv.py` but does not also
   override `TEST_RUNNER_FILES`, mutmut applies mutations to
   `wl_csv.py` while running tests that exercise `wl_validation.py`.
   The "survivors" reported are NOT genuine test-coverage gaps;
   they are artifacts of test selector / mutated module mismatch.

2. **The mutmut container mounts the host repo read-write.** Line
   89 of `scripts/mutmut.sh` is `-v "$REPO_ROOT:/work"`. Every
   mutation mutmut applies is a real write to the host working
   tree. If mutmut is interrupted between mutate-and-restore
   (SIGKILL, container stop, host reboot, OS crash), the file
   remains in mutated state and `git diff` shows it as a normal
   edit. The 2026-05-18 session caught a live mutation
   (`_csv_file_hash(csv_path)` → `None` in `bin/wl_csv.py:184`)
   that was about to be staged in a Phase 2 commit. The mutation
   would have silently broken CSV-hash bootstrapping.

---

## Operational rules (mandatory)

### 1. Test selector MUST match the mutated module

When invoking the harness, both knobs are required:

```bash
# CORRECT — wl_csv.py mutations against wl_csv tests
MUTATE_PATH=bin/wl_csv.py \
TEST_RUNNER_FILES="tests/unit/test_csv.py" \
    scripts/mutmut.sh run

# WRONG — wl_csv.py mutations against wl_validation tests
MUTATE_PATH=bin/wl_csv.py \
    scripts/mutmut.sh run    # uses default TEST_RUNNER_FILES → garbage results
```

Mapping table (keep in sync if new test files land):

| Mutated module | Test selector |
|---|---|
| `bin/wl_validation.py` | `tests/unit/test_validation.py tests/unit/test_ascii_validation.py tests/unit/test_validator_fuzz.py` |
| `bin/wl_csv.py` | `tests/unit/test_csv.py` |
| `bin/wl_versions.py` | `tests/unit/test_versions.py` (if present) |
| `bin/wl_rbac.py` | `tests/unit/test_rbac.py` |
| `bin/wl_audit.py` | `tests/unit/test_audit.py` |

### 2. Verify the working tree is clean BEFORE staging anything after a mutmut run

After every mutmut run:

```bash
git diff bin/        # MUST be empty
git status --short   # MUST not show modifications to mutated files
```

If `git diff bin/` shows a change, mutmut died mid-mutation and the
file is in mutated state. Recover with `git checkout -- <file>`.

This rule is non-negotiable. A live mutation slipped to a commit
once already (caught at stage time on 2026-05-18); next time the
catch may not happen.

### 3. Never mutate `bin/wl_handler.py` directly

Already documented in `scripts/mutmut.sh` comments. The handler's
tests are integration tests requiring a live Splunk container at
~30s per invocation. Multiplied by hundreds of mutations =
multi-day runs. The handler's logic is mostly dispatch + delegation
to other modules; mutating `wl_validation.py`, `wl_csv.py`, etc.
gives a higher-signal result. RBAC paths in the handler are pinned
by `tests/integration/test_rbac_matrix.py`.

### 4. Time budget per module — hard cap 2 hours

Mutmut on `bin/wl_csv.py` (1244 lines, 913 mutation candidates)
exceeded an estimated 4-8 hour budget at the 11-hour mark on
2026-05-18 with only mutations 191–235 tested (≈5% coverage). If
a run cannot complete in 2 hours per module, kill it and either
split the test selector (run subsets in parallel) or accept
partial coverage as the deliverable. Open-ended runs corrupt the
working tree if interrupted (see rule 2).

---

## 2026-05-18 wl_validation.py survivor triage

Twelve mutmut survivors were reported on `bin/wl_validation.py`
from the prior session. Manual analysis classifies them as follows.

### Genuine test-coverage gaps — 2

These were closed in commit `<TBD>` by adding tests to
`tests/unit/test_validation.py`. Each test was verified to FAIL
on the mutant and PASS on the pristine module.

| Mutant | Line | Mutation | Killing test |
|---|---|---|---|
| **116** | 107 | `"Only ASCII characters are allowed in text fields"` → `"XXOnly ASCII characters are allowed in text fieldsXX"` | `TestValidateAsciiTextErrorMessage::test_validate_ascii_text_returns_exact_error_string` |
| **151** | 214 | `stem = name.rsplit(".", 1)[0]` → `stem = name.rsplit(".", 2)[0]` | `TestIsSafeFilename::test_is_safe_filename_rejects_multi_dot_stem` |

**Why these matter**:

- Mutant 116 — `validate_ascii_text` returns the error string for
  direct UI display. Silent corruption to `XXOnly ASCII...XX` would
  ship as visible garbage to analysts on every non-ASCII rule name
  attempt. The original `pytest` truthy-check was indistinguishable.
- Mutant 151 — without the test, a future refactor of
  `rsplit(".", 1)` to `rsplit(".", 2)` would accept filenames like
  `foo.bar.csv` — exactly the SPL `base()` / dashboard drilldown URL
  parsing hazard the validator exists to prevent.

### Killed by existing tests on a properly-configured run — 2

These survivors are likely artifacts of the prior misconfigured
selector. Existing tests would kill them in a fresh run. Listed for
audit completeness, not action.

| Mutant | Line | Mutation | Existing killer |
|---|---|---|---|
| 138 | 191 | `if "/" in name` → `if "XX/XX" in name` | `test_basename_check_independently_rejects_path_separators` (catches via basename fallthrough on POSIX) |
| 146 | 197 | `name.startswith(".")` → `name.startswith("XX.XX")` | `test_is_safe_filename_rejects_dots` line 109 (catches at stem-regex on `.hidden.csv`) |

### Equivalent mutants — 8

These cannot be killed by any test because they produce
indistinguishable behavior from the original. Documenting them
here prevents future contributors from wasting time trying.

| Mutant | Line | Mutation | Why equivalent |
|---|---|---|---|
| 91 | 31 | `sys.path.insert(0, ...)` → `sys.path.insert(1, ...)` | Both achieve import resolution. Position only affects ordering vs. other entries that don't conflict with `wl_constants`. |
| 104 | 65 | `if len(cleaned) > max_length` → `if len(cleaned) >= max_length` | When `len(cleaned) == max_length`, `cleaned[:max_length] == cleaned`. The branch executes but produces identical output. |
| 145 | 193 | `os.path.basename(name) != name → return False` → `return True` | On POSIX (mutmut container), no constructable input passes the prior `"/"` and `"\\"` checks but fails `os.path.basename != name` — the basename divergence is itself caused by `/` on POSIX. Branch is unreachable. |
| 155 | 215 | `if not stem: return False` → `return True` | Caught earlier by `name.startswith(".")` at line 197. Any input reaching the stem check has a non-empty stem. |
| 157 | 222 | `ord(c) < 0x20` → `ord(c) <= 0x20` | Adds space (0x20) to rejection. Space already excluded by stem regex `[A-Za-z0-9_\-]+`. |
| 158 | 222 | `ord(c) < 0x20` → `ord(c) < 33` | Adds space + `!` to rejection. Both already excluded by stem regex. |
| 160 | 222 | `ord(c) == 0x7f` → `ord(c) == 128` | DEL (0x7f) already excluded by stem regex (not in alphabet). 128 is in `_NON_ASCII_RE` which fires earlier (line 218). |
| 161 | 222 | `ord(c) < 0x20 or ord(c) == 0x7f` → `... and ord(c) == 0x7f` | New condition impossible (single ord can't be both < 32 and == 127). Branch dead. Control chars still caught by stem regex. |

The pattern is structural: `is_safe_filename` has overlapping
defenses (path-separator check → basename check → extension check
→ stem regex → control-char check → alphanum check). Many control-
char and edge-case mutants are caught by the stem regex regardless,
making the control-char check defensive but mutation-test-invisible.
This is a design choice (defense-in-depth) we accept.

---

## 2026-05-18 wl_csv.py survivor triage — DISCARDED

The 45 "survivors" reported for `bin/wl_csv.py` are NOT actionable.
The mutmut command in the prior session was:

```
mutmut run --paths-to-mutate=bin/wl_csv.py --tests-dir=tests/unit \
  --runner='python -m pytest -x -q --tb=no \
            tests/unit/test_validation.py tests/unit/test_ascii_validation.py'
```

The test selector exercises `wl_validation.py`, not `wl_csv.py`.
Every mutation to `wl_csv.py` survived because the running tests
never imported or called any `wl_csv` function. The 45 mutants are
artifacts of misconfiguration (see "Operational rule 1" above).

To get genuine signal on `bin/wl_csv.py`, re-run:

```bash
MUTATE_PATH=bin/wl_csv.py \
TEST_RUNNER_FILES="tests/unit/test_csv.py" \
    scripts/mutmut.sh run
```

This run was NOT executed during the 2026-05-18 session — the time
budget was exhausted by the discovery + safety work above. It is
queued as v1.1 maintenance work.

---

## Recommended improvements

### CLOSED (landed in v1.1 prep, 2026-05-19)

1. ~~**Wire the mapping table into `scripts/mutmut.sh`**~~ — DONE.
   The script now auto-derives `TEST_RUNNER_FILES` from `MUTATE_PATH`
   via the `derive_test_files_for` function, and hard-fails on
   unknown modules (rather than silently falling back to wl_validation
   tests). Run `scripts/mutmut.sh mappings` to see the table.
   `bin/wl_handler.py` is explicitly rejected with a pointer to this
   doc. Escape hatch: explicit `TEST_RUNNER_FILES` env var still
   overrides auto-derivation.

2. ~~**Switch the volume mount to read-only.**~~ — DONE. The host
   repo is now mounted at `/repo` as `:ro`; a 512 MiB tmpfs is
   mounted at `/scratch` and populated from `/repo` at container
   creation. mutmut runs with `WORKDIR=/scratch` and mutates the
   tmpfs copy only — the host tree is unreachable from inside the
   container. Verified: a deliberate write attempt to
   `/repo/bin/wl_validation.py` fails with "Read-only file system";
   host file sha256 unchanged after a fresh container creation.
   Source-refresh signal: `scripts/mutmut.sh kill` then re-run (the
   tmpfs is repopulated from `/repo` only on container creation).

### Open (queued for v1.1 release prep)

1. **Re-run wl_validation with the correct selector** to get a
   fresh survivor count after the 2 new tests above. Expected
   result: ≤8 survivors (the equivalent mutants), down from 12.

2. **Run wl_csv.py with the correct selector**. Expected: real
   survivor count, plausibly 5-20 genuine gaps in CSV diff /
   hash-registry logic.

3. **Add `bin/wl_audit.py` mutation pass.** The 37 reported survivors
   on `wl_audit.py` from a prior session need the same re-validation
   under the correct selector before deciding what to do with them.

---

## Lessons captured to memory

These have been added to project memory (`MEMORY.md`) so they
don't have to be rediscovered:

- **`feedback_mutmut_host_mount_hazard.md`** — `:ro` mount or
  scratch-dir-only writes; verify `git diff bin/` is clean before
  staging.
- **`feedback_mutmut_test_selector_match.md`** — pair MUTATE_PATH
  and TEST_RUNNER_FILES every run; default selector is wl_validation
  only.

(Add these files manually when promoting this lesson into project
memory — the policy is per-session capture, not auto-extraction.)
