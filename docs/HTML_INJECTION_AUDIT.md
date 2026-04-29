# `.html()` User-Data Audit — Round 7 C3 (2026-04-29)

This document records the audit of every `.html()` call site in the
production frontend (`appserver/static/`, excluding `tests/`) to
verify that no user-controlled data reaches the DOM unescaped.

## Method

`grep -rn "\.html(" appserver/static --include="*.js"` produced 36
hits across 11 production files. Each call site was inspected for:

1. The argument to `.html()` — string literal vs. variable
2. If a variable, the path of every concatenated value
3. Whether each user-controlled substring is wrapped in `_.escape(...)`
4. Whether the surrounding context (event handler, render fn) is
   reachable from a user-supplied input

User-controlled data sources audited:

- Detection rule names (`item.detection_rule`, `entry.rule_name`)
- CSV filenames (`item.csv_file`, `entry.csv_file`)
- Analyst usernames (`item.analyst`, `cpCurrentUser`,
  `_state.username`)
- Approval reasons / comments (`item.comment`, `item.description`,
  `item.rejection_reason`, `item.cancellation_reason`)
- Trash items (`item.name`, `item.deleted_by`, `item.comment`)
- CSV cell values (every `row[h]`)
- Diff rows (every `row[k]`)
- Notifications (`n.message`, `n.detection_rule`, `n.csv_file`)
- Backend error strings (`data.error`, `xhr.responseText`)
- Filenames from `<input type="file">` (`file.name`)

## Results — by file

### Confirmed safe (every user-data substring escaped)

| File | Sites | Notes |
|------|-------|-------|
| `control_panel.js` | 17 | Approval queue, daily limits, analyst usage, trash, admin limits — all user data routed through `_.escape()` per cell. |
| `notifications.js` | 2 | Every `data-` attribute and message string escaped. Empty-state is static markup. |
| `modules/wl_table.js` | 2 | CSV row rendering — every cell value `_.escape(val)`, every header `_.escape(h)`. Empty-state is static. |
| `modules/wl_save.js` | 3 | Undo bars use `_.escape(colName)` / `_.escape(descText)`. Loading state is static markup. |
| `modules/wl_diff.js` | 1 | Every diff row field key + value escaped before concatenation. Compact summary applies escape per before/after pair. |
| `modules/wl_nav.js` | 7 | Rule list + CSV list each escape rule/csv name and `app_context`. No-CSV / loading states are static. |
| `modules/wl_csv_io.js` | 2 | Import preview escapes every header + cell. Error/warning renderer escapes per message. |
| `modules/wl_presence.js` | 1 | Every username escaped (visible + hidden lists). |

### Mixed (HTML-input contract, callers responsible for escaping)

| File | Sites | Notes |
|------|-------|-------|
| `modules/wl_ui.js` | 1 | `showMsg(text, type)` renders `text` as HTML. Contract added round 7 C3 — every existing caller already pre-escapes user-supplied substrings (`_.escape(data.error)`, `_.escape(data.request_id)`, etc.) before concatenating into the argument. **No XSS bug found**, but the contract was previously implicit. |

### No user-data risk (constants only)

The remaining sites pass static HTML string literals: empty-state
banners ("Select a detection rule", "No notifications", "Loading…"),
button labels, alert chrome (close button + CSS class).

## Findings — zero XSS bugs

Every `.html()` call site that touches user-controlled data already
runs that data through `_.escape(...)` before concatenation. No
remediation was required.

## Hardening shipped this round

Even though no bug was found, two preventive measures landed:

1. **Explicit contract on `wl_ui.js :: showMsg`** — the function's
   docstring now states that the input is rendered as HTML and
   callers are responsible for `_.escape`-ing user-supplied
   substrings. The implicit contract was correct but undocumented;
   a future maintainer adding a new call site without reading every
   existing caller could trivially have introduced an XSS bug.
2. **New `wl_ui.js :: showTextMsg(text, type)`** — a structurally
   safe variant that uses `.text()` for the message body. New call
   sites that don't need markup should default to this. Existing
   sites can migrate opportunistically; they don't have to migrate
   all at once.

## Extension audit — round 8 (2026-04-29)

Round 8 extended the same methodology to the remaining jQuery
DOM-injection sinks: `.append(string)`, `.prepend(string)`,
`.before(string)`, `.after(string)`, `.replaceWith(string)`, and
the `$(htmlString)` factory form. Same XSS surface as `.html()` —
all parse HTML when given a string starting with `<`.

**Sweep**: 62 sites total (40 + 3 + 3 + 1 + 5 + 10). Result: **zero
XSS bugs found**.

| Sink | Sites | Object args (safe) | String args | Bugs |
|------|------:|-------------------:|------------:|-----:|
| `.append()` | 40 | 32 | 8 | 0 |
| `.prepend()` | 3 | 1 | 2 | 0 |
| `.before()` | 3 | 1 | 2 | 0 |
| `.after()` | 1 | 0 | 1 | 0 |
| `.replaceWith()` | 5 | 3 | 2 | 0 |
| `$('<...')` factory | 10 | 10 | 0 | 0 |

The string-arg sites that take user data follow the same project
convention round 7 C3 documented: every user-controlled substring
is `_.escape`-wrapped before concatenation. Notable patterns:

- `wl_modals.js`, `wl_save.js`, `wl_csv_io.js`, `wl_presence.js`,
  `wl_datepicker.js`, `wl_table.js` — all modal/popup builders
  pass already-constructed jQuery objects (`$modal`, `$bubble`,
  `$datePicker`), so the HTML-parsing path is bypassed entirely.
- `control_panel.js:1878, 2886` — `replaceWith(renderLimitHistory(...))` /
  `replaceWith(renderAdminLimitHistory(...))` pass strings, but the
  builder functions escape every user-controlled field (admin name,
  timestamp, change values).
- `wl_versions.js:96, 117, 127` — `<option>` tags appended to
  the revert dropdown; `_.escape` per filename and display string.
- `wl_approval_ui.js:430, 572, 574` — approval-bar and addition-
  preview HTML; `_.escape` on every header, cell, action_type,
  analyst, reason, request_id.

## What this audit does NOT cover

- DOM `innerHTML` / `outerHTML` — pure DOM API, search-and-audit
  separately. Quick grep of the codebase: zero hits in production
  code.
- `eval`, `Function(string)`, `setTimeout(string, ...)` — these
  would be a different class of bug. Quick grep: zero hits in
  production code.

The methodology has now covered every realistic XSS sink in
jQuery + DOM that this codebase actually uses. Going deeper hits
diminishing returns.

## Re-audit triggers

Re-run this audit when:

- A new `.html()` call site is added (caught by code review +
  the hardened `showMsg` contract)
- A new user-controlled data source is introduced (e.g., free-text
  approval comments, custom dashboard panels, third-party REST
  callbacks)
- A future Splunk or jQuery upgrade changes parsing semantics
  (history: jQuery 3 changed `$(htmlString)` to refuse executing
  scripts on parse — a future change could go the other way)
