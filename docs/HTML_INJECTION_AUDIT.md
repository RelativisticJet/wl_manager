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

## What this audit does NOT cover

- jQuery `.append(string)` / `.prepend(string)` / `.before(string)`
  / `.after(string)` — when called with a string argument, these
  also parse HTML and have the same XSS surface as `.html()`. Not
  audited in this round; future work.
- `$(htmlString)` — the jQuery factory parses HTML when the
  argument starts with `<`. Not audited.
- DOM `innerHTML` / `outerHTML` — pure DOM API, search-and-audit
  separately. Quick grep of the codebase: zero hits in production
  code.
- `eval`, `Function(string)`, `setTimeout(string, ...)` — these
  would be a different class of bug. Quick grep: zero hits in
  production code.

A follow-up round can extend the same methodology to `.append()`
et al. The rationale for stopping at `.html()` here is that it
has the highest concentration of user-data-into-DOM call sites and
the audit returned a clean result; the cost-to-coverage of going
deeper drops sharply once we have confidence the discipline is
consistent.

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
