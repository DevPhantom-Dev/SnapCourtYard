"""SnapCourtYard — KiCad IPC plugin entry point.

KiCad launches this file as an external process and injects two environment
variables before execution:

    KICAD_API_SOCKET  – IPC socket path (pynng / NNG)
    KICAD_API_TOKEN   – per-session authentication token

All communication with the running PCB editor goes through the kipy library
(package: kicad-python).  No pcbnew / SWIG bindings are used.

Requires: kicad-python >= 0.4.0  (see requirements.txt)
Tested:   KiCad 9.0, 10.0
"""

from __future__ import annotations

import json
import logging
import os
import sys

# Ensure this directory is importable regardless of how KiCad launches us.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx
import kipy
import kipy.geometry

from snap_logic import (
    BBox, bbox_from_kipy, from_mm,
    CORNERS, CORNER_LABELS,
    EDGES,   EDGE_LABELS,
    HORIZONTAL_EDGES,
    delta_corner_to_corner, delta_edge_to_edge, chain_deltas,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(os.path.expanduser("~"), ".snapcourtyard.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".snapcourtyard.json")


def _load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _save_settings(data: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as exc:
        log.warning("Could not save settings: %s", exc)


# ---------------------------------------------------------------------------
# IPC connection
# ---------------------------------------------------------------------------

def _connect() -> kipy.KiCad:
    """Connect to the running KiCad instance via the IPC socket."""
    socket_path = os.environ.get("KICAD_API_SOCKET", "")
    token       = os.environ.get("KICAD_API_TOKEN",  "")

    # On POSIX systems the path is a bare filesystem path; pynng needs ipc://
    if sys.platform != "win32" and socket_path and not socket_path.startswith("ipc://"):
        socket_path = f"ipc://{socket_path}"

    return kipy.KiCad(
        socket_path=socket_path,
        kicad_token=token,
        timeout_ms=5000,
        client_name="SnapCourtYard",
    )


# ---------------------------------------------------------------------------
# Footprint helpers
# ---------------------------------------------------------------------------

def _selected_footprints(client: kipy.KiCad) -> list:
    """Return selected, unlocked footprints in selection order.

    Tries ``client.get_selection()`` first (preserves click order on KiCad 9+).
    Falls back to iterating board footprints.
    """
    try:
        items = client.get_selection()
        fps = [it for it in items
               if hasattr(it, "reference") and not getattr(it, "is_locked", False)]
        if fps:
            return fps
    except Exception as exc:
        log.debug("get_selection() failed, falling back to board scan: %s", exc)

    board = client.get_board()
    return [fp for fp in board.footprints
            if getattr(fp, "is_selected", False) and not getattr(fp, "is_locked", False)]


def _fp_label(fp) -> str:
    ref = getattr(fp, "reference", "") or "?"
    val = getattr(fp, "value",     "") or ""
    return f"{ref} ({val})" if val else ref


def _move_fp(client: kipy.KiCad, fp, dx_nm: int, dy_nm: int) -> None:
    """Translate a footprint by (dx, dy) nm and commit via IPC."""
    if dx_nm == 0 and dy_nm == 0:
        return
    fp.position.x = int(fp.position.x) + dx_nm
    fp.position.y = int(fp.position.y) + dy_nm
    client.update_items([fp])


def _restore_positions(client: kipy.KiCad,
                       fps: list,
                       saved: list[tuple[int, int]]) -> None:
    """Restore footprints to their original (x, y) positions."""
    for fp, (ox, oy) in zip(fps, saved):
        fp.position.x = ox
        fp.position.y = oy
    try:
        client.update_items(fps)
    except Exception as exc:
        log.warning("restore_positions failed: %s", exc)


# ---------------------------------------------------------------------------
# Slot helpers  (slot = corner key like "TL" or edge key like "T")
# ---------------------------------------------------------------------------

CORNER_SLOTS = ("TL", "TR", "BL", "BR")
EDGE_SLOTS   = ("T",  "R",  "B",  "L")

SLOT_GLYPH = {
    "TL": "┌", "TR": "┐",
    "BL": "└", "BR": "┘",
    "T":  "─", "B":  "─",
    "L":  "│", "R":  "│",
}


def _is_corner(slot: str) -> bool:
    return slot in CORNER_SLOTS


def _is_edge(slot: str) -> bool:
    return slot in EDGE_SLOTS


def _valid_combo(a_slot: str, m_slot: str) -> bool:
    if _is_corner(a_slot) and _is_corner(m_slot):
        return True
    if _is_edge(a_slot) and _is_edge(m_slot):
        return (a_slot in HORIZONTAL_EDGES) == (m_slot in HORIZONTAL_EDGES)
    return False


# ---------------------------------------------------------------------------
# wxPython widgets
# ---------------------------------------------------------------------------

class _SidePicker(wx.Panel):
    """3 × 3 grid of toggle buttons representing a footprint's bbox outline.

    Corners (TL / TR / BL / BR) and edges (T / R / B / L) are selectable;
    centre cell is blank.  Only one button is active at a time.
    """

    _LAYOUT = [
        "TL", "T",  "TR",
        "L",  None, "R",
        "BL", "B",  "BR",
    ]

    def __init__(self, parent, label: str, default: str = "BR") -> None:
        super().__init__(parent)
        outer = wx.StaticBoxSizer(wx.StaticBox(self, label=label), wx.VERTICAL)
        grid  = wx.GridSizer(rows=3, cols=3, hgap=2, vgap=2)

        self._buttons: dict[str, wx.ToggleButton] = {}
        for slot in self._LAYOUT:
            if slot is None:
                grid.Add(wx.StaticText(self, label=""), flag=wx.EXPAND)
                continue
            btn = wx.ToggleButton(self, label=SLOT_GLYPH[slot])
            btn.SetMinSize((42, 32))
            btn.SetToolTip(slot)
            btn.Bind(wx.EVT_TOGGLEBUTTON,
                     lambda _e, s=slot: self._select(s, fire=True))
            grid.Add(btn, flag=wx.EXPAND)
            self._buttons[slot] = btn

        outer.Add(grid, proportion=1, flag=wx.EXPAND | wx.ALL, border=6)
        self.SetSizer(outer)

        self._listener = None
        self.set(default)

    # ------------------------------------------------------------------
    def _select(self, slot: str, fire: bool = False) -> None:
        for s, btn in self._buttons.items():
            btn.SetValue(s == slot)
        if fire and self._listener:
            self._listener(slot)

    def set(self, slot: str) -> None:
        if slot not in self._buttons:
            slot = "BR"
        self._select(slot)

    def value(self) -> str:
        for slot, btn in self._buttons.items():
            if btn.GetValue():
                return slot
        return "BR"

    def on_change(self, callback) -> None:
        self._listener = callback


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class _SnapDialog(wx.Dialog):
    """Configuration dialog with live PCB preview."""

    def __init__(self,
                 parent,
                 client:   kipy.KiCad,
                 fps:      list,
                 bboxes:   list[BBox],
                 settings: dict) -> None:
        super().__init__(parent, title="Snap CourtYard", size=(560, 500))

        self._client   = client
        self._fps      = fps
        self._bboxes   = bboxes
        self._saved_xy = [(int(fp.position.x), int(fp.position.y)) for fp in fps]

        root = wx.BoxSizer(wx.VERTICAL)

        # ── Anchor row ────────────────────────────────────────────────
        anchor_row = wx.BoxSizer(wx.HORIZONTAL)
        anchor_row.Add(wx.StaticText(self, label="Anchor footprint (stays put)"),
                       flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=8)
        labels = [_fp_label(fp) for fp in fps]
        self.anchor_choice = wx.Choice(self, choices=labels)
        default_idx = len(fps) - 1  # last-clicked = last in selection order
        self.anchor_choice.SetSelection(default_idx)
        anchor_row.Add(self.anchor_choice, proportion=1, flag=wx.RIGHT, border=8)
        swap_btn = wx.Button(self, label="Swap")
        swap_btn.Bind(wx.EVT_BUTTON, self._on_swap)
        anchor_row.Add(swap_btn, flag=wx.ALIGN_CENTER_VERTICAL)
        root.Add(anchor_row, flag=wx.ALL | wx.EXPAND, border=10)

        # ── Chain note (N > 2) ────────────────────────────────────────
        if len(fps) > 2:
            note = wx.StaticText(
                self,
                label=f"Chain mode: {len(fps)} footprints.  "
                      "Anchor stays; others snap in selection order.")
            note.SetForegroundColour(wx.Colour(40, 90, 160))
            root.Add(note, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

        # ── Side pickers ──────────────────────────────────────────────
        pickers = wx.BoxSizer(wx.HORIZONTAL)
        self.anchor_picker = _SidePicker(
            self, "Anchor side", default=settings.get("anchor_slot", "BR"))
        self.move_picker = _SidePicker(
            self, "Moving side", default=settings.get("move_slot",   "TL"))
        self.anchor_picker.on_change(lambda _s: self._update())
        self.move_picker.on_change(  lambda _s: self._update())
        pickers.Add(self.anchor_picker, proportion=1,
                    flag=wx.EXPAND | wx.ALL, border=6)
        pickers.Add(self.move_picker,   proportion=1,
                    flag=wx.EXPAND | wx.ALL, border=6)
        root.Add(pickers, proportion=1, flag=wx.ALL | wx.EXPAND, border=6)

        # ── Mode label ────────────────────────────────────────────────
        self.mode_label = wx.StaticText(self, label="")
        font = self.mode_label.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.mode_label.SetFont(font)
        root.Add(self.mode_label, flag=wx.LEFT | wx.RIGHT, border=12)

        # ── Offset ────────────────────────────────────────────────────
        self._off_box_label = wx.StaticBox(self, label="Offset (mm)")
        off_box = wx.StaticBoxSizer(self._off_box_label, wx.HORIZONTAL)
        dx_str = str(settings.get("dx_mm", 0))
        dy_str = str(settings.get("dy_mm", 0))
        off_box.Add(wx.StaticText(self, label="dx:"),
                    flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        self.dx_ctrl = wx.TextCtrl(self, value=dx_str)
        off_box.Add(self.dx_ctrl, proportion=1, flag=wx.RIGHT, border=12)
        off_box.Add(wx.StaticText(self, label="dy:"),
                    flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        self.dy_ctrl = wx.TextCtrl(self, value=dy_str)
        off_box.Add(self.dy_ctrl, proportion=1, flag=wx.RIGHT, border=8)
        reset_btn = wx.Button(self, label="Reset", size=(60, -1))
        reset_btn.Bind(wx.EVT_BUTTON, self._on_reset_offset)
        off_box.Add(reset_btn, flag=wx.ALIGN_CENTER_VERTICAL)
        root.Add(off_box, flag=wx.ALL | wx.EXPAND, border=10)

        self.dx_ctrl.Bind(wx.EVT_TEXT, lambda _e: self._update())
        self.dy_ctrl.Bind(wx.EVT_TEXT, lambda _e: self._update())

        # ── Hint ──────────────────────────────────────────────────────
        hint = wx.StaticText(
            self,
            label="Tip: bind hotkey via Preferences > Hotkeys.  "
                  "Shift+click toolbar = repeat last config.")
        hint.SetForegroundColour(wx.Colour(120, 120, 120))
        root.Add(hint, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

        # ── Buttons ───────────────────────────────────────────────────
        root.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL),
                 flag=wx.ALL | wx.EXPAND, border=8)

        self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self._on_ok,     id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE,  self._on_close)
        self.anchor_choice.Bind(wx.EVT_CHOICE, lambda _e: self._update())

        self._update()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _anchor_index(self) -> int:
        idx = self.anchor_choice.GetSelection()
        return idx if idx != wx.NOT_FOUND else 0

    def _offset_mm(self) -> tuple[float, float]:
        def parse(ctrl):
            try:
                return float(ctrl.GetValue().replace(",", "."))
            except ValueError:
                return 0.0
        return parse(self.dx_ctrl), parse(self.dy_ctrl)

    def _offset_nm(self) -> tuple[int, int]:
        dx, dy = self._offset_mm()
        return from_mm(dx), from_mm(dy)

    def _restore(self) -> None:
        _restore_positions(self._client, self._fps, self._saved_xy)

    def _update(self) -> None:
        """Apply live preview: restore original positions, then apply current config."""
        self._restore()
        a_slot = self.anchor_picker.value()
        m_slot = self.move_picker.value()

        # Update mode label
        n      = len(self._fps)
        prefix = f"Chain {n} fp's | " if n > 2 else ""
        if _is_corner(a_slot) and _is_corner(m_slot):
            txt   = f"{prefix}Mode: Corner -> Corner  ({a_slot} -> {m_slot})"
            color = wx.Colour(40, 120, 40)
        elif _is_edge(a_slot) and _is_edge(m_slot):
            a_h = a_slot in HORIZONTAL_EDGES
            m_h = m_slot in HORIZONTAL_EDGES
            if a_h == m_h:
                txt   = f"{prefix}Mode: Edge -> Edge  ({a_slot} -> {m_slot})"
                color = wx.Colour(40, 120, 40)
            else:
                txt   = "Edges must share orientation (both T/B or both L/R)"
                color = wx.Colour(180, 30, 30)
        else:
            txt   = "Pick two corners OR two edges (not mixed)"
            color = wx.Colour(180, 30, 30)

        self.mode_label.SetLabel(txt)
        self.mode_label.SetForegroundColour(color)

        # Update offset label colour
        dx_mm, dy_mm = self._offset_mm()
        nonzero = dx_mm != 0 or dy_mm != 0
        self._off_box_label.SetLabel(
            "Offset (mm) — NON-ZERO" if nonzero else "Offset (mm)")
        self._off_box_label.SetForegroundColour(
            wx.Colour(180, 30, 30) if nonzero else wx.NullColour)
        self._off_box_label.Refresh()
        self.Layout()

        # Apply preview if combo is valid
        if _valid_combo(a_slot, m_slot):
            dx_nm, dy_nm = self._offset_nm()
            deltas = chain_deltas(
                self._bboxes, self._anchor_index(),
                a_slot, m_slot, dx_nm, dy_nm,
            )
            for fp, (dx, dy) in zip(self._fps, deltas):
                _move_fp(self._client, fp, dx, dy)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_swap(self, _evt) -> None:
        if len(self._fps) != 2:
            return
        sel = self.anchor_choice.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        self.anchor_choice.SetSelection(1 - sel)
        a = self.anchor_picker.value()
        m = self.move_picker.value()
        self.anchor_picker.set(m)
        self.move_picker.set(a)
        self._update()

    def _on_reset_offset(self, _evt) -> None:
        self.dx_ctrl.SetValue("0")
        self.dy_ctrl.SetValue("0")

    def _on_ok(self, _evt) -> None:
        # Board is already in the previewed state — just close.
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _evt) -> None:
        self._restore()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, _evt) -> None:
        self._restore()
        self.EndModal(wx.ID_CANCEL)

    # ------------------------------------------------------------------
    # Result accessors (called after ShowModal == ID_OK)
    # ------------------------------------------------------------------

    def result(self) -> dict:
        return {
            "anchor_idx": self._anchor_index(),
            "anchor_slot": self.anchor_picker.value(),
            "move_slot":   self.move_picker.value(),
            "dx_mm":       self._offset_mm()[0],
            "dy_mm":       self._offset_mm()[1],
        }


# ---------------------------------------------------------------------------
# Repeat (no-dialog) helper
# ---------------------------------------------------------------------------

def _apply_persisted(client: kipy.KiCad,
                     fps:    list,
                     bboxes: list[BBox]) -> bool:
    """Apply the last-saved configuration without showing a dialog.

    Returns True if the configuration was valid and applied.
    """
    settings = _load_settings()
    a_slot = settings.get("anchor_slot", "BR")
    m_slot = settings.get("move_slot",   "TL")
    if not _valid_combo(a_slot, m_slot):
        return False

    dx_nm = from_mm(float(settings.get("dx_mm", 0)))
    dy_nm = from_mm(float(settings.get("dy_mm", 0)))

    # anchor = last-clicked = last element in selection-ordered list
    anchor_idx = len(fps) - 1
    deltas = chain_deltas(bboxes, anchor_idx, a_slot, m_slot, dx_nm, dy_nm)

    for fp, (dx, dy) in zip(fps, deltas):
        _move_fp(client, fp, dx, dy)

    return True


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point invoked by KiCad when the plugin action fires."""
    try:
        client = _connect()
    except Exception as exc:
        log.error("Could not connect to KiCad IPC: %s", exc)
        app = wx.App(False)
        wx.MessageBox(
            f"SnapCourtYard: cannot connect to KiCad.\n\n{exc}",
            "Snap CourtYard", wx.ICON_ERROR)
        return

    fps = _selected_footprints(client)
    if len(fps) < 2:
        app = wx.App(False)
        wx.MessageBox(
            f"Select at least two unlocked footprints (got {len(fps)}).",
            "Snap CourtYard", wx.ICON_INFORMATION)
        return

    bboxes = [bbox_from_kipy(fp) for fp in fps]

    # Shift+click = repeat last config silently
    try:
        shift_held = wx.GetMouseState().ShiftDown()
    except Exception:
        shift_held = False

    if shift_held:
        if _apply_persisted(client, fps, bboxes):
            return
        # No valid saved config — fall through to dialog

    settings = _load_settings()
    app = wx.App(False)

    dlg = _SnapDialog(None, client, fps, bboxes, settings)
    try:
        if dlg.ShowModal() != wx.ID_OK:
            return
        res = dlg.result()
    finally:
        dlg.Destroy()

    # Persist settings (anchor_index intentionally omitted — it's per-session)
    _save_settings({
        "anchor_slot": res["anchor_slot"],
        "move_slot":   res["move_slot"],
        "dx_mm":       res["dx_mm"],
        "dy_mm":       res["dy_mm"],
    })


if __name__ == "__main__":
    main()
