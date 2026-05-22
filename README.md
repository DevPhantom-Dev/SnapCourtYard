# SnapCourtYard

A KiCad PCB editor plugin that snaps selected footprints edge-to-edge (or corner-to-corner) using their courtyard outlines.

## What It Does

Select footprints in **pcbnew**, run the plugin, and they will be repositioned so their courtyard boundaries touch — with an optional gap. Useful for quickly packing components side-by-side without manual measurement.

**Snap modes**

| Mode | Behavior |
|------|----------|
| Edge-to-Edge | Moving footprint slides along the perpendicular axis until the chosen edges touch; parallel-axis position is preserved |
| Corner-to-Corner | A chosen corner on the anchor and a chosen corner on the moving footprint are made to coincide |

Courtyards are derived from the merged `F.CrtYd` + `B.CrtYd` bounding box. When no courtyard polygon exists the footprint bounding box is used as a fallback. Only translation is applied — rotation is always preserved.

## Requirements

- KiCad 7.0 or later (tested on 7.x and 8.x)
- Python 3 (bundled with KiCad)

## Installation

### Option A — PCM (Plugin and Content Manager)

1. Download the latest `.zip` from the [Releases](../../releases) page, **or** build it yourself:
   ```
   python build_pcm.py
   ```
   The archive is written to `dist/SnapCourtYard-<version>-pcm.zip`.

2. In KiCad: **Plugin and Content Manager → Install from File…** → select the zip.
3. Click **Apply Changes**. The toolbar button appears in pcbnew (use **Tools → External Plugins → Refresh** if it doesn't show immediately).

### Option B — Manual

Copy the `SnapCourtYard/` folder into your KiCad scripting plugins directory:

| OS | Path |
|----|------|
| Windows | `%APPDATA%\kicad\<ver>\scripting\plugins\SnapCourtYard` |
| Linux | `~/.local/share/kicad/<ver>/scripting/plugins/SnapCourtYard` |
| macOS | `~/Documents/KiCad/<ver>/scripting/plugins/SnapCourtYard` |

Replace `<ver>` with your KiCad version (e.g. `8.0`, `7.0`). Restart KiCad or use **Tools → External Plugins → Refresh**.

## Usage

1. Open a PCB in **pcbnew**.
2. Select two or more footprints.
3. Click the **Snap CourtYard** toolbar button, or go to **Tools → External Plugins → Snap CourtYard**.
4. Choose the snap mode, axis (horizontal / vertical), and an optional gap in mm.
5. Click **OK**.

Footprints are sorted by their current position along the chosen axis. The first footprint stays anchored; the rest are moved so each courtyard edge meets the previous one (plus the specified gap).

## Project Structure

```
SnapCourtYard/
├── SnapCourtYard/          # Plugin package (copy this folder for manual install)
│   ├── __init__.py         # Registers the plugin with KiCad
│   ├── snap_courtyard_action.py  # ActionPlugin subclass + wxPython dialog
│   └── snap_logic.py       # Courtyard bbox extraction & snapping math (no wx/KiCad deps)
├── pcm/
│   └── metadata.json       # KiCad PCM package metadata
├── dist/                   # Built release archives
├── build_pcm.py            # Script to produce PCM-compatible .zip
└── plugins.pdf             # Reference: KiCad C++ plugin system (informational only)
```

## Building a Release

```bash
python build_pcm.py
```

Produces a versioned PCM archive in `dist/`. The version is read from `pcm/metadata.json`.

## License

MIT
