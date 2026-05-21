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

Each of the 4 launcher PNGs must ship in **two** locations.
The Splunk app-developer docs describe `appserver/static/` as the
canonical app-static path; in practice the Splunk launcher's REST
proxy at `/servicesNS/<user>/<app>/static/<file>` resolves to the
**bare `<app>/static/` directory** (no `appserver/` prefix), and falls
back to `$SPLUNK_HOME/etc/system/static/appIcon.png` (Splunk's generic
"App" placeholder) when that bare path is missing.

Shipping in both locations matches what production Splunk apps like
Splunk Secure Gateway do, and is verified to render correctly on the
launcher tile + still satisfy the documented `appserver/static/`
convention that Splunkbase publishing tooling reads. See
**[Splunk quirk: launcher icon path](#splunk-quirk-launcher-icon-path)**
below for the empirical evidence.

| Filename | Source SVG | Width × Height | Destination directories |
| --- | --- | --- | --- |
| `appIcon.png` | `appIcon-light.svg` | **36 × 36** | `static/` **AND** `appserver/static/` |
| `appIcon_2x.png` | `appIcon-light.svg` | **72 × 72** | `static/` **AND** `appserver/static/` |
| `appIconAlt.png` | `appIcon-dark.svg` | **36 × 36** | `static/` **AND** `appserver/static/` |
| `appIconAlt_2x.png` | `appIcon-dark.svg` | **72 × 72** | `static/` **AND** `appserver/static/` |

For Splunkbase listing (carousel header / publisher dashboard),
also export:

| Filename | Source SVG | Width × Height | Purpose |
| --- | --- | --- | --- |
| `wl_manager-icon-144.png` | `appIcon-light.svg` | **144 × 144** | Splunkbase listing thumbnail (light variant only — Splunkbase doesn't theme) |
| `wl_manager-icon-512.png` | `appIcon-light.svg` | **512 × 512** | High-DPI fallback + future use |

Splunkbase exports live outside both static directories (they are
uploaded via the Splunkbase publisher web UI, not shipped in the
`.spl`). Convention is to place them under
`docs/icons/exports/` so they are visible alongside the SVG masters
but excluded from the customer payload by `scripts/package.sh`.

### Splunk quirk: launcher icon path

This is documented at the top of `CLAUDE.md` under "Splunk Quirks"
because future Splunk projects will hit it too. Summary:

- The launcher icon `<img>` element loads from
  `http://<host>/<lang>/splunkd/__raw/servicesNS/<user>/<app>/static/appIcon.png`.
- That REST endpoint reads from `$SPLUNK_HOME/etc/apps/<app>/static/`,
  **not** `$SPLUNK_HOME/etc/apps/<app>/appserver/static/`.
- If the bare `<app>/static/appIcon.png` file is missing, Splunk
  silently falls back to its system default
  (`/opt/splunk/etc/system/static/appIcon.png` — a grey rounded
  square with the text "App"), and the icon `<img>` still reports
  `complete: true` + `naturalWidth: 36`, so the failure is invisible
  from the DOM. The only reliable verification is byte-level: pull
  the served PNG via `curl /servicesNS/.../static/appIcon.png` and
  `md5sum` it against the source PNG.
- Dashboards loading their own JS/CSS via relative URLs like
  `static/whitelist_manager.js` still resolve via the
  `appserver/static/` path — so `appserver/static/` must continue
  to hold the JS/CSS, regardless of where the icons live.

## Automated export (preferred — zero extra install)

`scripts/svg2png.js` renders an SVG to a PNG at the requested pixel
dimensions using the headless Chromium that ships with `playwright-core`
(already a dev dependency for the E2E test suite). No new toolchain to
install.

```bash
# From repo root — re-generate the 4 required Splunk PNGs in BOTH locations
# (see "Splunk quirk: launcher icon path" below for why both are needed):
for dir in static appserver/static; do
  node scripts/svg2png.js docs/icons/appIcon-light.svg "$dir/appIcon.png"        36
  node scripts/svg2png.js docs/icons/appIcon-light.svg "$dir/appIcon_2x.png"     72
  node scripts/svg2png.js docs/icons/appIcon-dark.svg  "$dir/appIconAlt.png"     36
  node scripts/svg2png.js docs/icons/appIcon-dark.svg  "$dir/appIconAlt_2x.png"  72
done

# Optional Splunkbase sizes (light variant — Splunkbase doesn't theme):
node scripts/svg2png.js docs/icons/appIcon-light.svg docs/icons/exports/wl_manager-icon-144.png 144
node scripts/svg2png.js docs/icons/appIcon-light.svg docs/icons/exports/wl_manager-icon-512.png 512
```

Why Chromium-based rendering rather than Inkscape / cairosvg / resvg?
Because the customer-facing renderer of Splunk app icons is also a
browser — the launcher tile loads the PNG through Chrome's image
pipeline. Using Chromium for the export step means the PNG we ship
looks exactly like what end users see, with consistent anti-aliasing
and transparent-PNG handling.

If `playwright-core`'s Chromium isn't on disk yet (fresh clone with no
E2E run), install it with `npx playwright install chromium` first.

## Inkscape export workflow (fallback — manual GUI route)

[Inkscape](https://inkscape.org) is a free, open-source, multi-platform
SVG editor. Use this route if you want to visually tweak the SVG before
exporting, or if `playwright-core` isn't available on your machine.

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

After exporting, deploy BOTH copies to the dev container and
confirm Splunk picks them up:

```bash
# Deploy the 4 PNGs to the dev container — bare static/ AND appserver/static/.
# Bare static/ is what the launcher REST endpoint actually reads;
# appserver/static/ is the documented convention that other Splunk
# tooling (e.g. Splunkbase publisher) still expects.
for sub in static appserver/static; do
  for name in appIcon.png appIcon_2x.png appIconAlt.png appIconAlt_2x.png; do
    MSYS_NO_PATHCONV=1 docker cp "$sub/$name" \
      "wl_manager_test:/opt/splunk/etc/apps/wl_manager/$sub/$name"
  done
done

# Restart Splunk (icons load at app-startup, not on each page load).
MSYS_NO_PATHCONV=1 docker exec -u splunk wl_manager_test /opt/splunk/bin/splunk restart
```

Then load `http://localhost:8000/en-US/app/launcher/home` and
confirm the Whitelist Manager tile shows the new icon. Toggle to
Splunk's dark theme to verify the Alt variant is picked up.

**Byte-level verification** (catches the silent-fallback failure
mode described in "Splunk quirk: launcher icon path" above):

```bash
# Pull whatever Splunk is actually serving for the launcher and
# compare to the source PNG. MD5s must match exactly; if they don't,
# Splunk is serving the system default placeholder and the bare
# static/ copy is missing.
MSYS_NO_PATHCONV=1 docker exec wl_manager_test bash -c \
  "curl -sk -u 'admin:<pw>' 'https://localhost:8089/servicesNS/admin/wl_manager/static/appIcon.png' -o /tmp/served.png && md5sum /tmp/served.png"
md5sum static/appIcon.png
```

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
