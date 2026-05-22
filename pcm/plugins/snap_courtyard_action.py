"SnapCourtYard ActionPlugin entry point."

import json
import os
import time

import pcbnew
import wx

from .snap_logic import (
    HORIZONTAL_EDGES,
    snap_corner_to_corner,
    snap_edge_to_edge,
)


SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".snapcourtyard.json")

CORNER_SLOTS = ("TL", "TR", "BL", "BR")
EDGE_SLOTS = ("T", "R", "B", "L")

SLOT_GLYPH = {
    "TL": "┌", "TR": "┐",
    "BL": "└", "BR": "┘",
    "T":  "─", "B":  "─",
    "L":  "│", "R":  "│",
}


def _is_corner(slot):
    return slot in CORNER_SLOTS


def _is_edge(slot):
    return slot in EDGE_SLOTS


def _load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _save_settings(data):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# ---- canvas click hook: records click order in PCB editor ---------------

_CLICK_HISTORY = []  # list of (timestamp, kiid)
_HOOK_INSTALLED = False
_HOOK_CANVAS = None


def _on_canvas_click(evt):
    "Canvas wx.EVT_LEFT_DOWN handler. Records fp under cursor at click time."
    try:
        evt.Skip()  # never block KiCad's own handling
    except Exception:
        pass
    try:
        screen_pos = evt.GetPosition()
    except Exception:
        return
    try:
        frame = pcbnew.GetFrame()
        if frame is None:
            return
        canvas = frame.GetCanvas()
        view = canvas.GetView()
    except Exception:
        return

    # Convert screen -> world coords (nm)
    world_x = world_y = None
    try:
        vec2d_cls = getattr(pcbnew, "VECTOR2D", None)
        if vec2d_cls is None:
            return
        screen_vec = vec2d_cls(float(screen_pos.x), float(screen_pos.y))
        try:
            world = view.ToWorld(screen_vec, True)
        except TypeError:
            world = view.ToWorld(screen_vec)
        world_x = int(world.x)
        world_y = int(world.y)
    except Exception:
        return

    # Find smallest footprint whose bbox contains the world point
    try:
        board = pcbnew.GetBoard()
        if board is None:
            return
        target = pcbnew.VECTOR2I(world_x, world_y)
    except Exception:
        return

    best = None
    best_area = None
    try:
        for fp in board.GetFootprints():
            try:
                bbox = fp.GetBoundingBox()
                contains = False
                try:
                    contains = bbox.Contains(target)
                except Exception:
                    try:
                        contains = bbox.Contains(world_x, world_y)
                    except Exception:
                        contains = False
                if not contains:
                    continue
                w = bbox.GetWidth()
                h = bbox.GetHeight()
                area = abs(w * h)
                if best_area is None or area < best_area:
                    best = fp
                    best_area = area
            except Exception:
                continue
    except Exception:
        return

    if best is None:
        return
    kiid = _fp_kiid(best)
    if not kiid:
        return
    _CLICK_HISTORY.append((time.time(), kiid))
    if len(_CLICK_HISTORY) > 200:
        del _CLICK_HISTORY[:-200]


def install_click_hook():
    "Bind LEFT_DOWN on PCB canvas. Idempotent. Returns True if installed."
    global _HOOK_INSTALLED, _HOOK_CANVAS
    if _HOOK_INSTALLED and _HOOK_CANVAS is not None:
        return True
    try:
        frame = pcbnew.GetFrame()
        if frame is None:
            return False
        canvas = frame.GetCanvas()
        if canvas is None:
            return False
        # Avoid double-bind on same canvas instance
        if _HOOK_CANVAS is canvas:
            _HOOK_INSTALLED = True
            return True
        canvas.Bind(wx.EVT_LEFT_DOWN, _on_canvas_click)
        _HOOK_INSTALLED = True
        _HOOK_CANVAS = canvas
        return True
    except Exception:
        return False


def _last_clicked_index(footprints):
    "Return index of fp most recently clicked (per hook history); -1 if none."
    fp_to_idx = {}
    for i, fp in enumerate(footprints):
        k = _fp_kiid(fp)
        if k:
            fp_to_idx[k] = i
    if not fp_to_idx:
        return -1
    for _ts, kiid in reversed(_CLICK_HISTORY):
        if kiid in fp_to_idx:
            return fp_to_idx[kiid]
    return -1


# ---- footprint identification --------------------------------------------


def _fp_kiid(fp):
    "Return stable string id for a footprint, or None."
    for attr in ("m_Uuid",):
        try:
            uid = getattr(fp, attr)
            return str(uid.AsString())
        except Exception:
            continue
    try:
        return str(fp.GetPath().AsString())
    except Exception:
        return None


def _cursor_world_position():
    """Return last canvas cursor position as (x, y) in board nm, or None.

    KiCad retains the last canvas-cursor world position even when mouse
    moves to toolbar. Use it as a proxy for 'where user last clicked'.
    """
    try:
        frame = pcbnew.GetFrame()
        if frame is None:
            return None
        canvas = frame.GetCanvas()
        controls = canvas.GetViewControls()
    except Exception:
        return None

    for getter_name in ("GetCursorPosition", "GetMousePosition"):
        try:
            getter = getattr(controls, getter_name)
            cursor = getter()
            x = getattr(cursor, "x", None)
            y = getattr(cursor, "y", None)
            if x is None or y is None:
                # may be a tuple-like
                try:
                    x, y = cursor[0], cursor[1]
                except Exception:
                    continue
            return int(x), int(y)
        except Exception:
            continue
    return None


def _index_closest_to_cursor(footprints):
    "Return index of fp closest to current cursor; -1 if cursor unavailable."
    cursor = _cursor_world_position()
    if cursor is None or not footprints:
        return -1
    best_idx = 0
    best_d = None
    cx, cy = cursor
    for i, fp in enumerate(footprints):
        try:
            p = fp.GetPosition()
            d = (p.x - cx) ** 2 + (p.y - cy) ** 2
        except Exception:
            continue
        if best_d is None or d < best_d:
            best_d = d
            best_idx = i
    return best_idx


def _default_anchor_index(footprints):
    """Pick best default anchor index.

    Priority:
    1. Explicitly marked anchor (settings['anchor_kiid']) if in selection.
    2. Most-recently-clicked fp (per canvas click hook history).
    3. Fp closest to last canvas cursor position.
    4. Last item in selection list.
    """
    if not footprints:
        return 0

    settings = _load_settings()
    marked = settings.get("anchor_kiid")
    if marked:
        for i, fp in enumerate(footprints):
            if _fp_kiid(fp) == marked:
                return i

    idx = _last_clicked_index(footprints)
    if idx >= 0:
        return idx

    idx = _index_closest_to_cursor(footprints)
    if idx >= 0:
        return idx

    return len(footprints) - 1


def _selected_footprints_ordered(board):
    """Return selected unlocked footprints in selection (click) order.

    pcbnew.GetCurrentSelection() returns BOARD_ITEM_VECTOR which iterates
    the internal SELECTION deque in insertion order. Single-click /
    Ctrl+click append in click order. Box-select / Select-All append in
    board order. Duck-type filter (avoid isinstance class checks which
    may fail across SWIG-wrapped builds).

    Fallback: board iteration order (only when GetCurrentSelection is
    unavailable or returned no usable items).
    """
    ordered = []
    sel = None
    try:
        sel = pcbnew.GetCurrentSelection()
    except Exception:
        sel = None

    if sel is not None:
        try:
            iterator = iter(sel)
        except TypeError:
            iterator = None
        if iterator is not None:
            for it in iterator:
                # Duck-type as FOOTPRINT: has GetReference + GraphicalItems
                if not hasattr(it, "GetReference"):
                    continue
                if not hasattr(it, "GraphicalItems"):
                    continue
                try:
                    if not it.IsSelected() or it.IsLocked():
                        continue
                except Exception:
                    continue
                ordered.append(it)

    if ordered:
        return ordered
    return [fp for fp in board.GetFootprints()
            if fp.IsSelected() and not fp.IsLocked()]


def _valid_combo(a_slot, m_slot):
    if _is_corner(a_slot) and _is_corner(m_slot):
        return True
    if _is_edge(a_slot) and _is_edge(m_slot):
        return (a_slot in HORIZONTAL_EDGES) == (m_slot in HORIZONTAL_EDGES)
    return False


def _do_snap(anchor, moving, a_slot, m_slot, dx_nm, dy_nm):
    if _is_corner(a_slot) and _is_corner(m_slot):
        snap_corner_to_corner(anchor, moving, a_slot, m_slot,
                              dx_nm=dx_nm, dy_nm=dy_nm)
    elif _is_edge(a_slot) and _is_edge(m_slot):
        snap_edge_to_edge(anchor, moving, a_slot, m_slot,
                          dx_nm=dx_nm, dy_nm=dy_nm)


def _apply_chain(footprints, anchor_idx, a_slot, m_slot, dx_nm, dy_nm):
    """Snap chain: anchor first, then each subsequent fp snaps to previous.

    Other footprints stay in their original selection order.
    """
    if len(footprints) < 2:
        return
    anchor = footprints[anchor_idx]
    others = [fp for i, fp in enumerate(footprints) if i != anchor_idx]
    chain = [anchor] + others
    for i in range(1, len(chain)):
        _do_snap(chain[i - 1], chain[i], a_slot, m_slot, dx_nm, dy_nm)


def _apply_persisted(board, footprints):
    """Apply last-used config without dialog."""
    if len(footprints) < 2:
        return False
    settings = _load_settings()
    a_slot = settings.get("anchor_slot", "BR")
    m_slot = settings.get("move_slot", "TL")
    if not _valid_combo(a_slot, m_slot):
        return False
    dx = pcbnew.FromMM(float(settings.get("dx_mm", 0)))
    dy = pcbnew.FromMM(float(settings.get("dy_mm", 0)))
    anchor_idx = _default_anchor_index(footprints)
    _apply_chain(footprints, anchor_idx, a_slot, m_slot, dx, dy)
    pcbnew.Refresh()
    return True


class _SidePicker(wx.Panel):
    """3x3 grid of toggle buttons forming a rectangle outline."""

    LAYOUT = [
        "TL", "T", "TR",
        "L",  None, "R",
        "BL", "B", "BR",
    ]

    def __init__(self, parent, label, default="BR"):
        super().__init__(parent)
        outer = wx.StaticBoxSizer(wx.StaticBox(self, label=label), wx.VERTICAL)
        grid = wx.GridSizer(rows=3, cols=3, hgap=2, vgap=2)

        self._buttons = {}
        for slot in self.LAYOUT:
            if slot is None:
                grid.Add(wx.StaticText(self, label=""), flag=wx.EXPAND)
                continue
            btn = wx.ToggleButton(self, label=SLOT_GLYPH[slot])
            btn.SetMinSize((42, 32))
            btn.SetToolTip(slot)
            btn.Bind(wx.EVT_TOGGLEBUTTON,
                     lambda e, s=slot: self._select(s, fire=True))
            grid.Add(btn, flag=wx.EXPAND)
            self._buttons[slot] = btn

        outer.Add(grid, proportion=1, flag=wx.EXPAND | wx.ALL, border=6)
        self.SetSizer(outer)

        self._listener = None
        self.set(default)

    def _select(self, slot, fire=False):
        for s, btn in self._buttons.items():
            btn.SetValue(s == slot)
        if fire and self._listener:
            self._listener(slot)

    def set(self, slot):
        if slot not in self._buttons:
            slot = "BR"
        self._select(slot)

    def value(self):
        for slot, btn in self._buttons.items():
            if btn.GetValue():
                return slot
        return "BR"

    def on_change(self, callback):
        self._listener = callback


class _SnapDialog(wx.Dialog):
    def __init__(self, parent, footprints, settings):
        super().__init__(parent, title="Snap CourtYard",
                         size=(560, 500))
        self._footprints = footprints
        self._original_positions = [fp.GetPosition() for fp in footprints]
        self._settings = settings

        root = wx.BoxSizer(wx.VERTICAL)

        # Anchor row: big bold ref label + dropdown + Swap (cycle)
        anchor_box = wx.StaticBoxSizer(
            wx.StaticBox(self, label="Anchor footprint (stays put)"),
            wx.VERTICAL)
        self.anchor_ref_label = wx.StaticText(self, label="")
        big = self.anchor_ref_label.GetFont()
        big.SetPointSize(big.GetPointSize() + 4)
        big.SetWeight(wx.FONTWEIGHT_BOLD)
        self.anchor_ref_label.SetFont(big)
        self.anchor_ref_label.SetForegroundColour(wx.Colour(180, 80, 30))
        anchor_box.Add(self.anchor_ref_label, flag=wx.ALL, border=6)

        anchor_row = wx.BoxSizer(wx.HORIZONTAL)
        refs = [self._label(fp) for fp in footprints]
        self.anchor_choice = wx.Choice(self, choices=refs)
        # default: marked > cursor-proximity > last in selection
        self.anchor_choice.SetSelection(_default_anchor_index(footprints))
        anchor_row.Add(self.anchor_choice, proportion=1, flag=wx.RIGHT, border=8)
        self.swap_btn = wx.Button(self, label="Next" if len(footprints) > 2 else "Swap")
        self.swap_btn.SetToolTip("Cycle anchor through selected footprints")
        self.swap_btn.Bind(wx.EVT_BUTTON, self._on_swap)
        anchor_row.Add(self.swap_btn, flag=wx.ALIGN_CENTER_VERTICAL)
        anchor_box.Add(anchor_row, flag=wx.ALL | wx.EXPAND, border=6)

        # Diagnose: selection order + signals used for default
        order_str = " -> ".join(self._label(fp) for fp in footprints)
        clicked_idx = _last_clicked_index(footprints)
        clicked_hint = (self._label(footprints[clicked_idx])
                        if clicked_idx >= 0 else "n/a (hook history empty)")
        cursor_idx = _index_closest_to_cursor(footprints)
        cursor_hint = (self._label(footprints[cursor_idx])
                       if cursor_idx >= 0 else "n/a")
        sel_note = wx.StaticText(
            self,
            label=("Selection: {}\n"
                   "Last clicked (hook): {}\n"
                   "Cursor closest: {}").format(
                order_str, clicked_hint, cursor_hint))
        sel_note.SetForegroundColour(wx.Colour(120, 120, 120))
        anchor_box.Add(sel_note, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=6)

        root.Add(anchor_box, flag=wx.ALL | wx.EXPAND, border=10)

        # Chain note (for N>2)
        if len(footprints) > 2:
            note = wx.StaticText(
                self,
                label="Chain mode: {} footprints. Anchor stays; others "
                      "snap in selection order.".format(len(footprints)))
            note.SetForegroundColour(wx.Colour(40, 90, 160))
            root.Add(note, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

        # Pickers
        pickers = wx.BoxSizer(wx.HORIZONTAL)
        self.anchor_picker = _SidePicker(
            self, "Anchor side", default=settings.get("anchor_slot", "BR"))
        self.move_picker = _SidePicker(
            self, "Moving side", default=settings.get("move_slot", "TL"))
        pickers.Add(self.anchor_picker, proportion=1,
                    flag=wx.EXPAND | wx.ALL, border=6)
        pickers.Add(self.move_picker, proportion=1,
                    flag=wx.EXPAND | wx.ALL, border=6)
        root.Add(pickers, proportion=1, flag=wx.ALL | wx.EXPAND, border=6)

        # Mode label
        self.mode_label = wx.StaticText(self, label="")
        font = self.mode_label.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.mode_label.SetFont(font)
        root.Add(self.mode_label, flag=wx.LEFT | wx.RIGHT, border=12)

        # Offset
        self.off_static = wx.StaticBox(self, label="Offset (mm)")
        off_box = wx.StaticBoxSizer(self.off_static, wx.HORIZONTAL)
        dx_default = str(settings.get("dx_mm", 0))
        dy_default = str(settings.get("dy_mm", 0))
        off_box.Add(wx.StaticText(self, label="dx:"),
                    flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        self.dx_ctrl = wx.TextCtrl(self, value=dx_default)
        off_box.Add(self.dx_ctrl, proportion=1, flag=wx.RIGHT, border=12)
        off_box.Add(wx.StaticText(self, label="dy:"),
                    flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4)
        self.dy_ctrl = wx.TextCtrl(self, value=dy_default)
        off_box.Add(self.dy_ctrl, proportion=1, flag=wx.RIGHT, border=8)
        self.reset_btn = wx.Button(self, label="Reset", size=(60, -1))
        self.reset_btn.Bind(wx.EVT_BUTTON, self._on_reset_offset)
        off_box.Add(self.reset_btn, flag=wx.ALIGN_CENTER_VERTICAL)
        root.Add(off_box, flag=wx.ALL | wx.EXPAND, border=10)

        # Hint
        hint = wx.StaticText(
            self,
            label="Tip: bind hotkey via Preferences > Hotkeys.  "
                  "Shift+click toolbar = repeat last config.")
        hint.SetForegroundColour(wx.Colour(120, 120, 120))
        root.Add(hint, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

        # OK/Cancel
        root.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL),
                 flag=wx.ALL | wx.EXPAND, border=8)
        self.SetSizer(root)

        # Wire live preview
        self.anchor_picker.on_change(lambda s: self._update())
        self.move_picker.on_change(lambda s: self._update())
        self.dx_ctrl.Bind(wx.EVT_TEXT, lambda e: self._update())
        self.dy_ctrl.Bind(wx.EVT_TEXT, lambda e: self._update())
        self.anchor_choice.Bind(wx.EVT_CHOICE, lambda e: self._update())
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._refresh_mode_label()
        self._refresh_offset_warning()
        self._update()

    @staticmethod
    def _label(fp):
        ref = fp.GetReference() or "?"
        val = fp.GetValue() or ""
        return "{} ({})".format(ref, val) if val else ref

    def _restore_positions(self):
        for fp, pos in zip(self._footprints, self._original_positions):
            try:
                fp.SetPosition(pos)
            except Exception:
                pass

    def _update(self):
        self._restore_positions()
        a_slot = self.anchor_picker.value()
        m_slot = self.move_picker.value()
        if _valid_combo(a_slot, m_slot):
            try:
                dx, dy = self.offset_nm()
                _apply_chain(self._footprints, self.anchor_index(),
                             a_slot, m_slot, dx, dy)
            except Exception:
                pass
        self._refresh_anchor_label()
        self._refresh_mode_label()
        self._refresh_offset_warning()
        pcbnew.Refresh()

    def _refresh_anchor_label(self):
        idx = self.anchor_index()
        if 0 <= idx < len(self._footprints):
            self.anchor_ref_label.SetLabel(self._label(self._footprints[idx]))
        else:
            self.anchor_ref_label.SetLabel("?")
        self.Layout()

    def _on_swap(self, _evt):
        n = len(self._footprints)
        if n < 2:
            return
        sel = self.anchor_choice.GetSelection()
        if sel == wx.NOT_FOUND:
            sel = 0
        next_sel = (sel + 1) % n
        self.anchor_choice.SetSelection(next_sel)
        # picker config preserved: only anchor identity changes.
        self._update()

    def _on_reset_offset(self, _evt):
        self.dx_ctrl.SetValue("0")
        self.dy_ctrl.SetValue("0")

    def _refresh_offset_warning(self):
        dx, dy = self.offset_mm()
        nonzero = dx != 0 or dy != 0
        label = "Offset (mm) - NON-ZERO" if nonzero else "Offset (mm)"
        self.off_static.SetLabel(label)
        color = wx.Colour(180, 30, 30) if nonzero else wx.NullColour
        self.off_static.SetForegroundColour(color)
        self.off_static.Refresh()

    def _refresh_mode_label(self):
        a = self.anchor_picker.value()
        m = self.move_picker.value()
        n = len(self._footprints)
        prefix = "Chain {} fp's | ".format(n) if n > 2 else ""
        if _is_corner(a) and _is_corner(m):
            txt = "{}Mode: Corner -> Corner  ({} -> {})".format(prefix, a, m)
            color = wx.Colour(40, 120, 40)
        elif _is_edge(a) and _is_edge(m):
            a_h = a in HORIZONTAL_EDGES
            m_h = m in HORIZONTAL_EDGES
            if a_h == m_h:
                txt = "{}Mode: Edge -> Edge  ({} -> {})".format(prefix, a, m)
                color = wx.Colour(40, 120, 40)
            else:
                txt = "Edges must share orientation (both T/B or both L/R)"
                color = wx.Colour(180, 30, 30)
        else:
            txt = "Pick two corners OR two edges (not mixed)"
            color = wx.Colour(180, 30, 30)
        self.mode_label.SetLabel(txt)
        self.mode_label.SetForegroundColour(color)
        self.Layout()

    def _on_ok(self, _evt):
        # board already in previewed state
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _evt):
        self._restore_positions()
        pcbnew.Refresh()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, _evt):
        # window X = cancel
        self._restore_positions()
        pcbnew.Refresh()
        self.EndModal(wx.ID_CANCEL)

    def anchor_index(self):
        idx = self.anchor_choice.GetSelection()
        return idx if idx != wx.NOT_FOUND else 0

    def picks(self):
        return self.anchor_picker.value(), self.move_picker.value()

    def offset_mm(self):
        def parse(ctrl):
            try:
                return float(ctrl.GetValue().replace(",", "."))
            except ValueError:
                return 0.0
        return parse(self.dx_ctrl), parse(self.dy_ctrl)

    def offset_nm(self):
        dx_mm, dy_mm = self.offset_mm()
        return pcbnew.FromMM(dx_mm), pcbnew.FromMM(dy_mm)


class SnapCourtYardPlugin(pcbnew.ActionPlugin):
    "Interactive Snap CourtYard."

    def defaults(self):
        self.name = "Snap CourtYard"
        self.category = "Layout Helper"
        self.description = "Snap footprint courtyards corner-to-corner or edge-to-edge."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        install_click_hook()
        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox("No board open.", "Snap CourtYard", wx.ICON_ERROR)
            return

        fps = _selected_footprints_ordered(board)
        if len(fps) < 2:
            wx.MessageBox(
                "Select at least two unlocked footprints (got {}).".format(len(fps)),
                "Snap CourtYard", wx.ICON_INFORMATION)
            return

        # Shift+click toolbar = skip dialog, reuse last config
        try:
            shift_held = wx.GetMouseState().ShiftDown()
        except Exception:
            shift_held = False
        if shift_held and _apply_persisted(board, fps):
            return

        settings = _load_settings()
        dlg = _SnapDialog(None, fps, settings)
        try:
            result = dlg.ShowModal()
            if result != wx.ID_OK:
                return
            a_idx = dlg.anchor_index()
            a_slot, m_slot = dlg.picks()
            dx_mm, dy_mm = dlg.offset_mm()
        finally:
            dlg.Destroy()

        settings["dx_mm"] = dx_mm
        settings["dy_mm"] = dy_mm
        settings["anchor_slot"] = a_slot
        settings["move_slot"] = m_slot
        # anchor_index intentionally not persisted: selection composition
        # changes between runs; always derive default from selection order.
        settings.pop("anchor_index", None)
        _save_settings(settings)
        pcbnew.Refresh()


class SnapCourtYardMarkAnchorPlugin(pcbnew.ActionPlugin):
    "Mark the currently-selected single footprint as the anchor."

    def defaults(self):
        self.name = "Snap CourtYard: Mark Anchor"
        self.category = "Layout Helper"
        self.description = ("Mark the currently-selected footprint as the "
                            "default anchor for next Snap CourtYard runs.")
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        install_click_hook()
        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox("No board open.", "Mark Anchor", wx.ICON_ERROR)
            return
        fps = _selected_footprints_ordered(board)
        if len(fps) == 0:
            settings = _load_settings()
            had = settings.pop("anchor_kiid", None)
            _save_settings(settings)
            wx.MessageBox(
                "No selection. Cleared marked anchor." if had else
                "No selection. No marked anchor to clear.",
                "Mark Anchor", wx.ICON_INFORMATION)
            return
        if len(fps) != 1:
            wx.MessageBox(
                "Select exactly ONE footprint to mark (got {}).".format(len(fps)),
                "Mark Anchor", wx.ICON_INFORMATION)
            return
        fp = fps[0]
        kiid = _fp_kiid(fp)
        if not kiid:
            wx.MessageBox("Could not read footprint id.",
                          "Mark Anchor", wx.ICON_ERROR)
            return
        settings = _load_settings()
        settings["anchor_kiid"] = kiid
        _save_settings(settings)
        wx.MessageBox(
            "Anchor marked: {}\n(Used as default in next Snap CourtYard runs.)".format(
                fp.GetReference()),
            "Mark Anchor", wx.ICON_INFORMATION)


class SnapCourtYardRepeatPlugin(pcbnew.ActionPlugin):
    "Re-apply last Snap CourtYard config without dialog."

    def defaults(self):
        self.name = "Snap CourtYard (Repeat)"
        self.category = "Layout Helper"
        self.description = ("Re-apply the last Snap CourtYard configuration "
                            "to the current selection without showing a dialog.")
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        install_click_hook()
        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox("No board open.", "Snap CourtYard", wx.ICON_ERROR)
            return
        fps = _selected_footprints_ordered(board)
        if len(fps) < 2:
            wx.MessageBox(
                "Select at least two unlocked footprints.",
                "Snap CourtYard", wx.ICON_INFORMATION)
            return
        if not _apply_persisted(board, fps):
            wx.MessageBox(
                "No saved configuration. Run the main Snap CourtYard plugin first.",
                "Snap CourtYard", wx.ICON_INFORMATION)
