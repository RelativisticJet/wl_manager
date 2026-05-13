# Phase 1 Cloud-Vetting Runtime-Stage Risk Plan

> **Status**: Pre-positioning (2026-05-14).
> **Scope**: AppInspect Cloud API dynamic-stage findings against
> `bin/wl_fim_watch.py` (and to a lesser extent `bin/wl_fim.py`,
> `bin/wl_expiration_cleanup.py`).
> **Trigger**: Phase 1.5/1.6 in `docs/PUBLIC_RELEASE_PLAN.md` —
> first live AppInspect API run against a Splunk Cloud Sandbox.

## 1. Why pre-position now

The Phase 0.0 static-AppInspect run finished with **0 errors / 0
failures / 0 future_failures** on both profiles. That's a strong
signal, but it covers only the static surface (manifest, conf files,
Python AST, packaging hygiene). Splunk Cloud Vetting also runs a
**dynamic stage**:

1. Install the `.spl` into a live Cloud Sandbox container
2. Start the app's scripted inputs and REST handlers
3. Monitor resource usage, syscalls, file I/O paths, network attempts,
   indexed-event volume for the duration of a smoke window
4. Reject the submission if any flagged behavior is observed

Static AppInspect cannot simulate this. The Phase 0.0 findings doc
flagged the dynamic stage as "low-moderate residual risk". This doc
exists to **pre-think the response options** so Phase 1.6 isn't a
scramble.

## 2. Why `wl_fim_watch.py` is the most likely flag

```ini
[script://$SPLUNK_HOME/etc/apps/wl_manager/bin/wl_fim_watch.py]
disabled        = false
interval        = 0           # persistent long-running process
index           = wl_audit
sourcetype      = wl_fim
python.version  = python3
python.required = 3.13
```

The `interval = 0` is **the canonical Splunk pattern for "long-running
process"** — splunkd starts the script once, monitors stdout, and
restarts it on exit. But it's an unusual pattern in Cloud apps: most
apps use `interval = 60` polling. Cloud Vetting reviewers may:

- ask "why a persistent process? can it be polling-based?"
- run automated resource-usage assertions (CPU%, RSS over time)
- check for signs of unbounded growth (process memory, indexed event
  volume per hour)

**What `wl_fim_watch.py` actually does** (verified 2026-05-14):

| Concern | Behavior | Cloud-risk |
|---|---|---|
| Outbound network | None — zero `requests`/`urllib`/`socket` calls | Compliant |
| Subprocess | None — zero `subprocess` calls | Compliant |
| Threading | None — single-threaded, signal-handler only | Compliant |
| File I/O paths | All within `$SPLUNK_HOME/etc/apps/wl_manager/lookups/_versions/` and `metadata/` | Compliant (app's own subtree) |
| Persistent runtime | Yes — `while True:` with 2-second `os.stat()` poll | **Specific to flag** |
| Indexed event volume | State-change events only (per decision 2026-04-21) — no heartbeat flood | Compliant |
| Memory profile | No accumulating globals; `_HASH_CACHE` capped to mapping size | Compliant — but unverified for long-uptime drift |
| Restart safety | Clean `_load_alert_state` re-init on start; signal handlers exit cleanly | Compliant |

**`wl_fim.py`** (the 15-second polling sibling) is far less likely
to be flagged — it's a conventional `interval = 15` script that
runs, emits, and exits each cycle. Cloud Vetting accepts this
pattern uniformly.

**`wl_expiration_cleanup.py`** runs every hour (`interval = 3600`)
and does CSV mutations. Risk areas: large CSV reads, potential write
contention during deploy windows. Mitigated by reading `rule_csv_map.csv`
and processing one CSV at a time.

## 3. Response options (decided BEFORE 1.6, not during)

If Cloud Vetting flags `wl_fim_watch.py`, we have four options
ranked by preservation of the security property (~2s CSV-modification
detection latency):

### Option A — Accept as-is, with documentation

- **What**: Submit unchanged. Provide a written justification
  document covering (1) why `interval = 0` is necessary for the
  security property, (2) the resource bounds (`_HASH_CACHE` capped,
  no accumulating state), (3) the canonical Splunk precedent for
  long-running scripted inputs (e.g., Splunk's own `splunkd` shell
  alerts), (4) the alternative (polling at 15s loses 13s detection
  latency — equivalent to the slow-path `wl_fim.py`).
- **Effort**: ~2 hours (write the doc, attach to AppInspect API
  submission).
- **Security**: Full preservation — ~2s detection latency intact.
- **Risk**: Cloud Vetting reviewers may reject the justification.
  Splunk's AppInspect API has rejected long-running scripted inputs
  before, even when documented. No prior data on rate.
- **Reversibility**: Free — if rejected, fall back to B/C/D.

### Option B — Convert to scheduled polling

- **What**: Change `interval = 0` → `interval = 15` in `inputs.conf`.
  Refactor `wl_fim_watch.py` from `while True: time.sleep(2)` to
  a single-pass `main()` that exits after one stat sweep.
- **Effort**: ~4 hours (refactor, test, re-run integration suite).
- **Security**: ~15s detection latency instead of ~2s. Same as the
  existing `wl_fim.py` slow path. Effectively, the fast path goes
  away — we have only the slow path. CSV modifications with
  preserved mtime are still detected via the 15s full-hash scan.
- **Risk**: Low — this is the conventional Cloud pattern, near-zero
  rejection risk.
- **Reversibility**: Medium — easy to revert the conf change, but
  if we removed the `wl_fim_watch.py` while-loop, restoring it
  requires the original code.

### Option C — Convert to a modular input

- **What**: Rewrite `wl_fim_watch.py` as a Splunk **modular input**
  (the canonical Cloud-blessed pattern for long-running processes).
  This means: implementing `scheme()`, `validate_input()`,
  `stream_events()` methods; adding an `inputs.conf.spec` file;
  removing the `interval = 0` scripted-input stanza in favor of a
  `[wl_fim_watch://default]` modular-input stanza.
- **Effort**: ~16 hours (refactor + schema XML + E2E test on Splunk
  Cloud Sandbox + integration test update for the new stanza name).
- **Security**: Full preservation — modular inputs are persistent
  by nature; we can keep the 2-second poll cadence.
- **Risk**: Lowest among "preserve security" options — Cloud Vetting
  treats modular inputs as a first-class long-running pattern.
- **Reversibility**: High effort to roll back to scripted input
  (would need the original script + conf restored). But the modular
  input itself is purely additive on the Splunk side.

### Option D — Cloud-only `.spl` without `wl_fim_watch.py`

- **What**: Submit a Cloud-cert `.spl` that ships `wl_fim_watch.py`
  with `disabled = true` (or omits the stanza entirely). On-prem
  `.spl` keeps the fast path. Document the Cloud feature gap.
- **Effort**: ~6 hours (separate Cloud build, separate cert
  submission, doc explaining the gap).
- **Security**: Cloud deployments lose ~2s fast-path detection;
  fall back to the existing 15s `wl_fim.py` slow path. On-prem
  unchanged.
- **Risk**: Zero (we don't ship the flagged behavior to Cloud).
  But carries an operational tax forever — two `.spl` variants to
  maintain, version-skew risk, support burden on documenting which
  deployments have which detection latency.
- **Reversibility**: Medium — re-enabling the stanza in the Cloud
  variant requires re-submitting for Cloud cert.

## 4. Decision criteria (use these AT Phase 1.6, not now)

When Phase 1.6's first dynamic-AppInspect-API run completes, use
this tree:

```
                  Was wl_fim_watch.py flagged?
                  /                          \
                 NO                          YES
                  |                           |
            (proceed to 1.7)         What kind of flag?
                                    /        |        \
                              CPU/Mem    "long-     "modular-
                              bound      running"   input-required"
                                |       (generic)   (specific)
                                |           |             |
                          Option B         Option A        Option C
                          (drop fast       (try doc        (rewrite as
                           path; lower      first; fall    modular —
                           Cloud burden)    back to B/C/D) Cloud-blessed)
```

If Cloud Vetting **soft-warns** without blocking (some checks emit
yellow warnings that can ship with documented justification): start
with Option A. The 2-hour cost is the cheapest experiment.

If Cloud Vetting **hard-blocks** on `wl_fim_watch.py` specifically:
go straight to Option C. Option A failed if we're here. Option B
loses a real security property.

If Cloud Vetting **hard-blocks on resource bounds** (memory growth
flagged): the issue isn't the pattern, it's the implementation.
Profile + fix the leak in `wl_fim_watch.py` first; don't change the
architecture.

## 5. Pre-positioning work (do NOW, in Phase 0)

To make Phase 1.6 fast and de-risked:

1. **Memory-leak smoke test** — run `wl_fim_watch.py` in the Docker
   container for 24h with `tracemalloc` enabled; record RSS over
   time. If flat, Option A's "no growth" claim is defensible
   evidence. If growing, fix BEFORE Phase 1 starts.
2. **Resource baseline** — measure CPU% and indexed-event-per-hour
   on a quiet environment. These numbers become the "expected
   baseline" in Option A's justification doc.
3. **Modular-input skeleton** — sketch (don't implement) the
   modular-input wrapper for `wl_fim_watch.py`. Knowing the diff
   shape ahead of time makes Option C a known quantity instead of
   an unknown.

Items 1 + 2 are 1-2 hours of work. Item 3 is 1 hour of design
notes. Cumulative ~3-4 hours, queued behind Phase 0.1-0.11.

## 6. Open questions for Phase 1.6

- Does Splunk Cloud's automated AppInspect API even **run** scripted
  inputs during the dynamic stage, or does it just inspect their
  declared stanzas? (Documentation says yes; behavior varies by year.)
- Does Cloud Vetting accept written justifications via the
  Splunkbase submission UI, or only via separate manual-review channel?
- For Option C, is there a recipe / template for converting an
  existing scripted input to a modular input without breaking the
  `_HASH_CACHE` warm state across the migration?

Answer these during Phase 1.4 (Splunk Cloud Sandbox provisioning)
before Phase 1.6 runs.

## 7. What this plan is NOT

- It is NOT a commitment to one option. Decision happens AT 1.6
  with real signal in hand.
- It is NOT a substitute for the formal Phase 1.3 triage doc.
  That doc covers ALL Cloud-cert findings; this plan covers ONE
  pre-identified high-risk surface.
- It is NOT scope for Phase 0. The pre-positioning work in §5 is
  the only Phase-0-eligible task; everything else waits for 1.6.

## 8. Revision log

- 2026-05-14 — initial plan written from Phase 0.0 follow-up.
  No live data yet; revisit when Phase 1.4 sandbox is provisioned.
