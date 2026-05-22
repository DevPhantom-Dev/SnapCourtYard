"""SnapCourtYard ActionPlugin entry point."""

import os

import pcbnew
import wx

from .snap_logic import AXIS_X, AXIS_Y, selected_footprints, snap_edge_to_edge


class _AxisDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Snap CourtYard", size=(280, 200))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label="Snap axis:"),
                  flag=wx.ALL, border=8)
        self.rb_x = wx.RadioButton(panel, label="Horizontal (left -> right)",
                                   style=wx.RB_GROUP)
        self.rb_y = wx.RadioButton(panel, label="Vertical (top -> bottom)")
        self.rb_x.SetValue(True)
        sizer.Add(self.rb_x, flag=wx.LEFT | wx.RIGHT, border=16)
        sizer.Add(self.rb_y, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=16)

        gap_box = wx.BoxSizer(wx.HORIZONTAL)
        gap_box.Add(wx.StaticText(panel, label="Gap (mm):"),
                    flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=8)
        self.gap_ctrl = wx.TextCtrl(panel, value="0")
        gap_box.Add(self.gap_ctrl, proportion=1)
        sizer.Add(gap_box, flag=wx.ALL | wx.EXPAND, border=12)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btns, flag=wx.ALL | wx.EXPAND, border=8)
        panel.SetSizer(sizer)

    def axis(self):
        return AXIS_X if self.rb_x.GetValue() else AXIS_Y

    def gap_nm(self):
        try:
            mm = float(self.gap_ctrl.GetValue())
        except ValueError:
            mm = 0.0
        return pcbnew.FromMM(mm)


class SnapCourtYardPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Snap CourtYard"
        self.category = "Modify PCB"
        self.description = "Snap selected footprints edge-to-edge along courtyards."
        self.show_toolbar_button = True
        icon = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon):
            self.icon_file_name = icon

    def Run(self):
        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox("No board open.", "Snap CourtYard", wx.ICON_ERROR)
            return

        fps = selected_footprints(board)
        if len(fps) < 2:
            wx.MessageBox("Select at least two footprints.",
                          "Snap CourtYard", wx.ICON_INFORMATION)
            return

        dlg = _AxisDialog(None)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            axis = dlg.axis()
            gap = dlg.gap_nm()
        finally:
            dlg.Destroy()

        moved = snap_edge_to_edge(fps, axis=axis, gap_nm=gap)
        pcbnew.Refresh()
        wx.MessageBox(f"Snapped {moved} footprint(s).",
                      "Snap CourtYard", wx.ICON_INFORMATION)
