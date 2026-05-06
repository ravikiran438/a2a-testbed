# A2A Testbed - Logo Asset Pack

## App icon

**SVG sources:**
- `a2a-testbed-icon.svg` — bright color master (cyan→magenta gradient, lime observer, glow)
- `a2a-testbed-icon-mono.svg` — monochrome fallback (single-color, no effects, for embroidery / fax / stamps / single-color print)

**PNG icon sizes:**
- `a2a-testbed-icon-1024.png` — iOS App Store, marketing
- `a2a-testbed-icon-512.png` — Android, marketing
- `a2a-testbed-icon-256.png` — macOS .icns, large
- `a2a-testbed-icon-192.png` — PWA manifest, Android Chrome
- `a2a-testbed-icon-128.png` — Chrome Web Store
- `a2a-testbed-icon-64.png` — toolbar, large favicon
- `a2a-testbed-icon-48.png` — Windows shortcut
- `a2a-testbed-icon-32.png` — favicon (standard)
- `a2a-testbed-icon-16.png` — favicon (small)

**Monochrome PNG sizes:**
- `a2a-testbed-icon-mono-1024.png`, `-512.png`, `-256.png`, `-64.png`

**Favicon:**
- `favicon.ico` — multi-resolution (16/32/48) for `<link rel="icon">`

## Expanded logo lockup

- `a2a-testbed-logo-dark.svg` — dark wordmark for **light backgrounds**
- `a2a-testbed-logo-light.svg` — light wordmark for **dark backgrounds**
- PNG renders at 1640w / 820w / 410w (preserving 820:240 aspect)

## Usage notes

- The `icon-mono` files are for any context where gradients/colors won't reproduce: laser-engraved swag, single-color screen-print, fax cover sheets, ASCII-style favicons.
- The expanded logo's wordmark uses Helvetica/Arial fallback. If you want it locked to a specific font (Inter, JetBrains Mono, etc.), open the SVG and swap the `font-family` attribute.
- The "2" in "A2A" picks up the icon's cyan→magenta gradient — this is the visual link between mark and wordmark.

## Color tokens

| Element | Value |
|---|---|
| Tile background (radial) | `#1a1240` → `#070514` |
| Arc gradient | `#22d3ee` → `#6366f1` → `#d946ef` |
| Observer (validator) | `#a3e635` |
| A circles & letters | `#f8fafc` |
| Observation lines | `#cbd5e1` (35-40% opacity) |
| Wordmark (dark) | `#0f172a` |
| Wordmark (light) | `#f8fafc` |
| Tagline | `#64748b` (light bg) / `#94a3b8` (dark bg) |
