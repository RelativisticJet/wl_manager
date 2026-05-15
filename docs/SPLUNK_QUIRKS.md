# Splunk Platform Quirks

Splunk-platform behaviors and limitations discovered during development of the Whitelist Manager app. Each entry includes the trigger, the unexpected behavior, the fix or workaround, and (where known) the root cause.

This file is the canonical public-facing source. The CLAUDE.md self-improvement-loop rule mandates capturing new quirks immediately, not at session-end; the rule itself is preserved at the top of this document for visibility.

Plan-reference: Phase 0.5 migration (PUBLIC_RELEASE_PLAN.md, DECISION_LOG D11).

---

## Self-improvement loop — capture rule

When a Splunk-specific quirk causes a bug or surprises us, capture it in this project's MEMORY.md immediately — before the next deploy, not at session-end. Splunk's behavior is non-obvious in dozens of small ways and the cost of re-learning a quirk is high.

**Triggers (capture an entry when ANY of these is true)**:

1. A documented Splunk feature behaved differently than its docs imply (e.g., `<panel depends>` does not react to programmatic token `unset()`).
2. A Splunk component has hidden state we discovered the hard way (e.g., two `mvc.Components` instances per token, internal KV cache overriding files on disk, `MAX_MULTIVAL_COUNT` truncating field extraction at ~371 entries).
3. A configuration combination produced silent corruption (e.g., `INDEXED_EXTRACTIONS=json` + default `KV_MODE` causing field duplication, requiring explicit `KV_MODE=none`).
4. A REST API or CLI behavior differs between proxy port 8000 and management port 8089, or between authenticated and unauthenticated paths.
5. A cache layer ate our changes (server-side `i18n/`, `static/app/<app>/`, `static/build/`, plus browser cache — four layers).

**What to capture (one short paragraph + code snippet if applicable)**:
- Trigger condition: what we did
- Unexpected behavior: what Splunk did
- Fix or workaround
- Root cause if known (which Splunk subsystem owns it)

**Where to write**:
- Append to this project's `MEMORY.md` under "Splunk Quirks"
- If likely to bite any future Splunk project, also add a one-liner to a global pattern note (e.g., `~/.claude/knowledge/`) so future sessions in other Splunk projects benefit
- Do NOT bury it only in a session summary — those get compacted away

**Not a trigger**: a bug in our own code that has nothing to do with Splunk's behavior. That is a regular post-mortem, captured in the relevant `feedback_*.md` file.


---

## Known Splunk quirks

- **Splunk strips HTML elements** from SimpleXML `<html>` panels: `<button>`, empty `<div>`, `<form>`. Build all interactive UI in JavaScript.
- **JS/CSS caching**: Splunk caches static assets aggressively. Bump `build` in `app.conf` AND restart Splunk after every JS/CSS change.
- **`-auth admin:Chang3d!`** breaks in bash because `!` triggers history expansion. Use stop + start without `-auth`, or use the REST API directly.
- **`MSYS_NO_PATHCONV=1`** is required before every `docker exec` and `docker cp` command when using Git Bash on Windows, to prevent MSYS path conversion mangling `/opt/splunk/...` paths.
- **`docker exec -u splunk`** for Splunk commands, **`-u 0`** for root operations (chown, reading protected files).
