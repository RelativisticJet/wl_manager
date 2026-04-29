# `wl_audit` Index — Volume Forecast

This document gives Splunk administrators a back-of-envelope estimate
of `index=wl_audit` daily event count and storage growth, so license
sizing and retention can be planned before the index hits a capacity
ceiling. Origin: round 7 B5 (2026-04-29) — the `whitelist_view`
event added in round 6 is the first read-side audit emission and
materially changes the volume profile.

## Assumed event size

Whitelist Manager audit events are JSON, ~250-700 bytes uncompressed
depending on action type (a `row_added` event with 5 visible fields
is ~400 bytes; a `bulk_row_edit` with 20 rows of before/after values
hits ~3 KB; the read-side `whitelist_view` is the smallest at ~280
bytes since it has no row payload).

Splunk's typical compression ratio on JSON logs is ~7x. Assume:

- Average uncompressed per event: **600 B**
- Indexed (rawdata + tsidx) per event: **~150 B**

These are conservative — adjust by ±50% based on your actual data
mix once you have a real sample.

## Per-action-type baseline (write-side, pre-round-6)

The write-side actions don't fire on idle dashboards — they require
a user click that mutates data. Realistic SOC team baseline:

| Action class | Events / analyst / day |
|--------------|-----------------------:|
| `row_added` | 5-15 |
| `row_removed` | 2-5 |
| `row_edited` | 1-5 |
| `revert` | 0-1 |
| `create_rule` / `create_csv` | 0-2 |
| `delete_rule` / `delete_csv` | 0-1 |
| approval submissions / decisions | 1-3 |
| limit/RBAC admin actions | 0-1 |

**Per-analyst write-side total**: ~10-30 events/day.
**100-analyst team write-side total**: ~1,000-3,000 events/day.

This is small. Even at the high end the write-side load is well
under 1 MB/day uncompressed.

## `whitelist_view` (read-side) — the new variable

Round 6 added `whitelist_view` events on `get_csv_content`. Naive
emission (one event per dashboard load + tab switch) would dwarf
every other audit event class combined. Two design controls cap
the volume:

1. **Per-process dedup cache** keyed on `(user, csv, app_context)`
   with TTL = `_VIEW_AUDIT_DEDUP_TTL = 3600 s` (1 hour). After the
   first emission for a tuple, every subsequent `get_csv_content`
   from the same user-CSV pair within the hour is silent.
2. **In-memory only** — the cache is per-Splunk-worker-process. No
   shared state, so multi-worker deployments may emit up to N
   duplicate events per period (where N is the worker count). This
   is an explicit trade-off; the dedup cache stays lock-free at
   the cost of bounded over-counting.

### Forecast — single-worker

100 analysts × 50 CSVs they could touch × 8 working-hours

= 40,000 events/day **worst case** (every analyst views every CSV
every hour for 8 hours)

Realistic (every analyst opens 5-8 CSVs over 4 active hours):

100 × 8 × 4 = **3,200 events/day**

### Forecast — multi-worker (Splunk default ~4 workers)

The dedup cache is per-process, so the same `(user, csv)` tuple
can fire once per worker. Splunk's REST router does not pin a user
to a single worker, so amplification is roughly the worker count:

- Realistic × 4 workers = **~12,800 events/day**
- Worst case × 4 workers = **160,000 events/day**

In practice the amplification factor is well below the worker
count because individual short bursts of activity on one CSV tend
to land on the same worker (TCP connection reuse + Splunk's
internal routing).

### Storage envelope

|                     | Realistic   | Worst case   |
|---------------------|------------:|-------------:|
| Single-worker / day | 1.9 MB     | 24 MB        |
| 4-worker / day      | 7.7 MB     | 96 MB        |
| 4-worker / year (raw) | ~2.8 GB | ~35 GB       |
| 4-worker / year (indexed) | ~0.7 GB | ~9 GB |

For comparison, write-side audit events (~3,000/day at 100
analysts) come to ~1.8 MB/day uncompressed — `whitelist_view`
is the dominant volume class on a busy team.

## Recommendations

1. **Default `wl_audit` retention to 365 days**. The index already
   defaults to 365d in `default/indexes.conf`. Even at the worst
   case forecast (160k events/day on 4 workers), one year of
   `whitelist_view` data fits in <10 GB — well under the 500 GB
   default `maxTotalDataSizeMB`.

2. **Tune `_VIEW_AUDIT_DEDUP_TTL` if volume is too high**. The
   constant is at line 677 of `bin/wl_handler.py`. Doubling it to
   7200 s (2 h) halves the worst-case volume; quartering it to
   900 s (15 min) quadruples it. The trade-off is forensic
   resolution: a longer TTL means an investigator sees less
   granular timing of when an analyst returned to a CSV.

3. **Watch for unexpected growth.** If the realistic estimate
   (3,200/day per worker) is exceeded by more than 5x without a
   matching increase in user count, investigate:
   - dashboard polling that calls `get_csv_content` repeatedly
   - automation accounts (service users) hitting the read path
   - a worker being restarted frequently (each restart drops the
     dedup cache, so the next request from every active user
     re-emits)

4. **Don't bypass the dedup**. Round 6 audit dedup was specifically
   sized to make read-side auditing affordable at SOC scale. If
   future work needs per-call read events (e.g., for a high-value
   CSV), add a separate event class with its own retention rather
   than removing the dedup.

## Re-forecast triggers

Re-run this estimate when:

- New audit-emitting GET actions are added (currently only
  `whitelist_view`)
- The dedup TTL is changed
- Splunk worker count is materially changed (HA/scale-out)
- User count grows past 5x the assumption (100 analysts)
- A new dashboard auto-loads many CSVs in parallel (would skew
  the realistic estimate above the per-day-per-analyst floor)
