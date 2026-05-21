# Whitelist Manager — Icon Source Files

This directory holds the **vector source files** for the app's visual
identity. The customer-facing PNG renderings live in
`appserver/static/` (Splunk's required convention) and are
re-generated from these SVGs whenever the design changes.

The `docs/` tree is excluded from the `.spl` payload by
`scripts/package.sh`, so these SVG sources stay in the repo for
future maintainability without bloating customer installs.

## Files

| File | Purpose |
| --- | --- |
| `appIcon-light.svg` | Light-theme variant — dark icon on light Splunk launcher background. Master for `appIcon.png` + `appIcon_2x.png`. |
| `appIcon-dark.svg` | Dark-theme variant — lighter icon on dark Splunk launcher background. Master for `appIconAlt.png` + `appIconAlt_2x.png`. |

## Visual concept

Aqua shield silhouette (security / protection container) holding
a light-grey document with three list rows (the whitelist itself),
plus a black circular check badge in the document's bottom-right
corner (approved / allowed affordance).

Two reads at every size:

1. **At 36×36** — bright aqua shield with a darker inset
2. **At 144×144+** — distinguishable "secure whitelist document
   with approval mark" composition

Promoted from `concepts/concept-1-document-with-badge.svg` on
2026-05-22 after side-by-side comparison of four candidate
directions.

## Color palette

| Token | Light SVG | Dark SVG | Role |
| --- | --- | --- | --- |
| Shield body | `#1FB8C9` | `#2DD0E2` (+12% lightness) | Brand primary; aqua shield |
| Document body | `#D6DCE0` | `#E2E7EC` | Paper fill |
| Document outline | `#1A1A1A` | `#2A2A2A` | Document border + check badge |
| Title bar | `#4A5560` | `#5A6570` | Page top affordance (no text) |
| List rows | `#8A95A0` | `#9AA5B0` | Subtle "this is a list" hint |
| Check badge bg | `#1A1A1A` | `#1A1A1A` (unchanged) | Approval-mark container |
| Check mark stroke | `#1FB8C9` | `#2DD0E2` | Matches shield colour for brand echo |

The check badge bg is the same `#1A1A1A` in both variants to
preserve maximum contrast against the aqua check stroke. The
shield colour shifts +12% lightness in the dark variant so the
icon pops against very dark Splunk navy dashboards without
changing the brand identity.

## Required PNG export sizes

Splunk's documented icon convention (per the
`splunk-app-developer-tools` docs):

| Filename | Source SVG | Width × Height | Destination directory |
| --- | --- | --- | --- |
| `appIcon.png` | `appIcon-light.svg` | **36 × 36** | `appserver/static/` |
| `appIcon_2x.png` | `appIcon-light.svg` | **72 × 72** | `appserver/static/` |
| `appIconAlt.png` | `appIcon-dark.svg` | **36 × 36** | `appserver/static/` |
| `appIconAlt_2x.png` | `appIcon-dark.svg` | **72 × 72** | `appserver/static/` |

For Splunkbase listing (carousel header / publisher dashboard),
also export:

| Filename | Source SVG | Width × Height | Purpose |
| --- | --- | --- | --- |
| `wl_manager-icon-144.png` | `appIcon-light.svg` | **144 × 144** | Splunkbase listing thumbnail (light variant only — Splunkbase doesn't theme) |
| `wl_manager-icon-512.png` | `appIcon-light.svg` | **512 × 512** | High-DPI fallback + future use |

Splunkbase exports live outside `appserver/static/` (they are
uploaded via the Splunkbase publisher web UI, not shipped in the
`.spl`). Convention is to place them at the repo root under a
gitignored `dist/` directory or here under `docs/icons/exports/`.

## Inkscape export workflow

[Inkscape](https://inkscape.org) is the recommended editor —
free, open-source, multi-platform, and has the cleanest SVG → PNG
pipeline of the free options.

### One-time setup

1. Install Inkscape from <https://inkscape.org/release/>.
2. Open `appIcon-light.svg` in Inkscape (File → Open).
3. (Optional) tweak colors, shape, or proportions — the SVG is
   structured to be readable by hand. Common tweaks:
   - Change `#1F3A5F` to your preferred navy via Edit → Find/Replace
     (Ctrl-F) → "Replace text in property values".
   - Adjust the checkmark stroke-width (currently `22`) for chunkier
     or thinner strokes.
   - Move the list-row rectangles up/down by editing their `y`
     attribute.

### Per-size PNG export

For each of the four Splunk-required sizes:

1. File → Export… (Shift-Ctrl-E).
2. In the right-hand panel, set:
   - **Document** tab selected (exports the full viewBox, not just
     selected geometry)
   - **Width** and **Height**: 36 and 36 (or 72×72, 144×144, 512×512
     per the table above)
   - **Bit depth**: RGBA_8 (default — preserves transparent
     background)
   - **DPI**: 96 (default — irrelevant for PNG; size is set by
     Width × Height)
   - **Format**: PNG
3. Click **Export**.
4. Save to `appserver/static/<name>.png` per the path table above.

Repeat for the `-dark.svg` source for the Alt variants.

### Quick command-line export (alternative to GUI)

If Inkscape's CLI is on your `PATH`, you can batch-export with one
command per file:

```bash
# From repo root:
inkscape docs/icons/appIcon-light.svg \
  --export-type=png \
  --export-filename=appserver/static/appIcon.png \
  --export-width=36 --export-height=36

inkscape docs/icons/appIcon-light.svg \
  --export-type=png \
  --export-filename=appserver/static/appIcon_2x.png \
  --export-width=72 --export-height=72

inkscape docs/icons/appIcon-dark.svg \
  --export-type=png \
  --export-filename=appserver/static/appIconAlt.png \
  --export-width=36 --export-height=36

inkscape docs/icons/appIcon-dark.svg \
  --export-type=png \
  --export-filename=appserver/static/appIconAlt_2x.png \
  --export-width=72 --export-height=72
```

On Windows, the Inkscape binary is typically at
`C:\Program Files\Inkscape\bin\inkscape.exe` — substitute the full
path or add it to `PATH` first.

## Verifying the PNGs are wired correctly

After exporting, deploy to the dev container and confirm Splunk
picks them up:

```bash
# Deploy the 4 PNGs to the dev container's static/ dir
MSYS_NO_PATHCONV=1 docker cp appserver/static/appIcon.png        wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/appIcon.png
MSYS_NO_PATHCONV=1 docker cp appserver/static/appIcon_2x.png     wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/appIcon_2x.png
MSYS_NO_PATHCONV=1 docker cp appserver/static/appIconAlt.png     wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/appIconAlt.png
MSYS_NO_PATHCONV=1 docker cp appserver/static/appIconAlt_2x.png  wl_manager_test:/opt/splunk/etc/apps/wl_manager/appserver/static/appIconAlt_2x.png

# Bump the build number in default/app.conf (Splunk caches icon assets
# under the same urlArgs cache-bust mechanism as JS/CSS — see
# docs/SPLUNK_QUIRKS.md "Splunk caches static assets aggressively").

# Restart Splunk (icons load at app-startup, not on each page load)
MSYS_NO_PATHCONV=1 docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk restart
```

Then load `http://localhost:8000/en-US/app/launcher/home` and
confirm the Whitelist Manager tile shows the new icon. Toggle to
Splunk's dark theme to verify the Alt variant is picked up.

## Why we ship SVGs at all (rather than just PNGs)

The PNGs are what Splunk actually uses at runtime. The SVGs are
the **maintenance source**. If a future contributor wants to
change the icon (re-color, rebrand, tweak shape), they edit the
SVG, re-export, commit both. Without the SVG master, every
re-design starts from scratch — and that path produces visually
inconsistent icons across releases.

This pattern follows the same principle used in `docs/screenshots/`:
keep the editable source alongside the rendered output, but exclude
the source from the customer payload.
