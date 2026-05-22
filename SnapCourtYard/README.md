# SnapCourtYard

KiCad PCB editor plugin. Snaps selected footprints edge-to-edge using their F.CrtYd / B.CrtYd courtyard outlines.

## Install

### Option A — PCM (Plugin and Content Manager), install from file

1. Build the archive (from the parent folder containing `build_pcm.py`):
   ```
   python build_pcm.py
   ```
   Produces `dist/SnapCourtYard-1.0.0-pcm.zip`.
2. In KiCad: **Plugin and Content Manager** > **Install from File...** > pick the zip.
3. Apply changes. The toolbar button appears in pcbnew (refresh plugins if needed).

### Option B — manual

Copy the `SnapCourtYard/` folder into your KiCad user scripting/plugins directory:

| OS      | Path |
|---------|------|
| Windows | `%APPDATA%\kicad\<ver>\scripting\plugins\SnapCourtYard` |
| Linux   | `~/.local/share/kicad/<ver>/scripting/plugins/SnapCourtYard` |
| macOS   | `~/Documents/KiCad/<ver>/scripting/plugins/SnapCourtYard` |

`<ver>` = `8.0`, `7.0`, etc. Restart KiCad or use **Tools > External Plugins > Refresh**.

Tested with KiCad 7.x / 8.x. The PDF in the parent folder describes the C++ PLUGIN_3D class (3D model loaders) — referenced as plugin-system example only; this plugin uses the Python `pcbnew.ActionPlugin` API instead, which is the right API for PCB-editor actions.

## Use

1. Open a PCB in **pcbnew**.
2. Select 2+ footprints.
3. Click the **Snap CourtYard** toolbar button (or **Tools > External Plugins > Snap CourtYard**).
4. Choose axis (horizontal / vertical) and optional gap in mm. OK.

Footprints sorted by current position along chosen axis. First stays anchored; rest move so courtyard leading edge meets previous courtyard trailing edge (+ gap).

## Files

- `__init__.py` — registers plugin.
- `snap_courtyard_action.py` — `pcbnew.ActionPlugin` subclass + wx dialog.
- `snap_logic.py` — courtyard bbox + chain math (no wx, importable for testing).

## Notes

- If a footprint has no courtyard polygon, falls back to its bounding box.
- Both F.CrtYd and B.CrtYd are merged when present.
- Rotation preserved; only translation applied.
