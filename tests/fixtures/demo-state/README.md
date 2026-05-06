# Demo state — clean snapshot for screenshot reproduction

Purpose: when you re-take README screenshots, return to a known-clean
state via this checkpoint. This avoids re-running the full
`backup → clean → seed` sequence by hand.

## What's checkpointed here

After a `make demo-reset` run (or the equivalent manual sequence
documented below), this directory holds:

- `_approval_queue.snapshot.json` — pending + resolved approvals
  (3 pending, 6 resolved spread over ~7 days)
- `_daily_limits.snapshot.json` — analyst usage counters showing
  realistic ratios (3/15 row removals, 1/5 CSV saves)
- `_notifications.snapshot.json` — small notification badge (~2-4
  unread, not the dev-accumulated 20+)
- `_trash_config.snapshot.json` — 2 demo trash entries with
  professional names

The actual file content is regenerated on every `make demo-reset`
by hitting the production REST endpoints (submit_approval,
remove_rule, etc.), NOT by writing these fixtures directly. The
synthetic-fixtures hook (see CLAUDE.md "Synthetic Fixtures —
Banned for Feature Verification") applies — these snapshots
are for reference / visual diff only, never for replay.

## Restore steps (manual)

If you've polluted the dev environment and want to return to demo
state for a fresh screenshot session:

```bash
# 1. Backup current state
docker exec -u 0 wl_manager_test bash -c \
  'cd /opt/splunk/etc/apps/wl_manager/lookups/_versions && \
   tar -czf /tmp/preclean.tar.gz _approval_queue.json _daily_limits.json \
                                  _notifications.json _trash_config.json'

# 2. Clean wl_audit index (Splunk must be stopped)
docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk stop
docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk clean eventdata -index wl_audit -f
docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk start --answer-yes --no-prompt

# 3. Truncate state files (cooldown bypass via direct rm)
docker exec -u 0 wl_manager_test bash -c \
  'cd /opt/splunk/etc/apps/wl_manager/lookups/_versions && \
   rm -f _approval_queue.json _daily_limits.json _notifications.json _trash_config.json && \
   : > _recovery_log.jsonl && \
   chown splunk:splunk _recovery_log.jsonl'

# 4. Re-seed via production REST (see scripts/seed-demo-state.sh)
./scripts/seed-demo-state.sh
```

## When to re-snapshot

Update the `*.snapshot.json` files in this directory ONLY when:

- The handler's schema changes (new field added to queue / notification)
- The seed script changes meaningfully

Don't update them just because dates rolled over — the timestamps
within are illustrative, not load-bearing.

## Why we have this at all

The first round of public-release screenshots (2026-05-06)
shipped a Control Panel image showing 14 pending approvals + 245
resolved entries — many with names like `IGNORE_ME_csv` and
zero-width-char rejected fuzz inputs from hardening rounds. That's
unprofessional first-impression material for an open-source
project. This fixture set lets future screenshot rounds skip the
"figure out what to clean" step and jump straight to capture.
