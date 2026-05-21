# Icon Concepts — Whitelist Manager v2 Visual Direction

Four concepts combining the shield container with a whitelist /
document motif, in the aqua + black + grey palette. Each is a
distinct interpretation of the reference image (clipboard with
list rows + check badge) inside the security-shield container.

## Quick preview

GitHub renders SVG natively. Click to view full-size:

- [Concept 1 — Document with check badge](concept-1-document-with-badge.svg)
- [Concept 2 — Checklist rows inside shield](concept-2-checklist-rows.svg)
- [Concept 3 — Bold check over compact list](concept-3-bold-check-list.svg)
- [Concept 4 — Clipboard with clip detail](concept-4-clipboard.svg)

For local preview, drag any `.svg` onto a browser window.

## Side-by-side comparison

| Concept | Visual identity | Best at small sizes (36×36) | Best at large sizes (144×144+) | Splunkbase polish |
| --- | --- | --- | --- | --- |
| 1. Document + badge | Closest to reference image; explicit "paper document" affordance | Detail dissolves slightly | ✅ Excellent | ✅ |
| 2. Checklist rows | Pure "ticked items" — most abstract | List rows merge at 36px | Good | OK |
| 3. Bold check + list | Single dominant symbol; minimal | ✅ Excellent | Good (but plain) | OK |
| 4. Clipboard with clip | Strongest "this is a real document" feel | Clip detail at top is small | ✅ Excellent | ✅ |

## How to pick

The choice depends on **which size matters most** to you:

- **If the Splunk launcher tile (36×36) is the primary surface** —
  pick **Concept 3**. One dominant black check on aqua reads
  cleanly at every size and never muddies. Trade-off: less
  distinctive than the others; another shield-with-check security
  app could share the same silhouette.
- **If the Splunkbase listing thumbnail (144×144) is the primary
  surface** — pick **Concept 1** or **Concept 4**. The document /
  clipboard imagery is what makes the icon recognisably "whitelist
  manager" rather than "generic security app."
- **If you want a balance** — pick **Concept 2**. It scales
  reasonably well and conveys the "ticking off items" idea without
  the detailed paper imagery. Compromise option.

## Common geometry rules (all four concepts)

- ViewBox 256×256 for clean integer scaling to 36 / 72 / 144 / 512
- All inner content stays within the shield path's interior bounds
  (top y ≥ 60, bottom y ≤ 200, sides curve from x=40/216 at top to
  the bottom point at x=128, y=232)
- Two-color rule at small sizes: aqua silhouette + black for
  outlines/check; grey is supporting detail that fades at 36px
- Transparent background (the Splunk launcher tile provides the
  surrounding shape)
- Aqua `#1FB8C9` is the consistent brand colour across all four

## How to iterate

If one concept is close but not quite right, tell me what to
change and I'll regenerate that single SVG. Common requests:

- "Concept 1 but check badge on the top-right instead of
  bottom-right"
- "Concept 3 but check is aqua, shield is grey"
- "Concept 4 but clipboard clip in aqua instead of black"
- "Mix: concept 1's document with concept 3's bold check size"

Once a final design is locked, I'll move the chosen SVG up to
`docs/icons/appIcon-light.svg` (replacing the v1 navy/green
draft), produce a matching dark-theme variant at
`docs/icons/appIcon-dark.svg`, and you'll export PNGs at the
documented sizes per `../README.md`.

## Why we keep the rejected concepts in the repo

The three concepts you don't pick still hold value as design
context — they document what we considered and why. If a future
redesign asks "did we ever try X?", the answer is here in git
history without needing to re-explain. This is the same reason
`docs/DECISION_LOG.md` keeps reversed decisions visible.
