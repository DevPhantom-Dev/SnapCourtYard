"This file is executed when the package is imported (on PCB editor startup)"

import wx

from .snap_courtyard_action import (
    SnapCourtYardMarkAnchorPlugin,
    SnapCourtYardPlugin,
    SnapCourtYardRepeatPlugin,
    install_click_hook,
)

SnapCourtYardPlugin().register()
SnapCourtYardRepeatPlugin().register()
SnapCourtYardMarkAnchorPlugin().register()


def _try_install_hook(remaining_tries=8):
    if install_click_hook():
        return
    if remaining_tries <= 0:
        return
    try:
        wx.CallLater(1500, _try_install_hook, remaining_tries - 1)
    except Exception:
        pass


try:
    wx.CallLater(1000, _try_install_hook)
except Exception:
    pass
