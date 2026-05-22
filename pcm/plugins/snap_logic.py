"Corner and edge courtyard snapping."

import pcbnew


CORNERS = ("TL", "TR", "BL", "BR")
CORNER_LABELS = {
    "TL": "Top-Left",
    "TR": "Top-Right",
    "BL": "Bottom-Left",
    "BR": "Bottom-Right",
}

EDGES = ("T", "R", "B", "L")
EDGE_LABELS = {"T": "Top", "R": "Right", "B": "Bottom", "L": "Left"}
HORIZONTAL_EDGES = ("T", "B")
VERTICAL_EDGES = ("L", "R")


def _vec(x, y):
    "Return VECTOR2I (KiCad 7+) or wxPoint (KiCad 6)."
    try:
        return pcbnew.VECTOR2I(int(x), int(y))
    except (TypeError, AttributeError):
        return pcbnew.wxPoint(int(x), int(y))


def _courtyard_layer_ids():
    ids = []
    for layer_name in ("F_CrtYd", "B_CrtYd"):
        lid = getattr(pcbnew, layer_name, None)
        if lid is not None:
            ids.append(lid)
    return ids


def courtyard_bbox(footprint):
    """BOX2I covering OUTER edge of visible courtyard stroke.

    Iterates PCB_SHAPE items on F.CrtYd / B.CrtYd and merges their
    GetBoundingBox() (which includes stroke width). Snapping with this
    bbox makes visible strokes abut with no gap and no overlap.
    Falls back to footprint bounding box when no courtyard exists.
    """
    crt_layers = _courtyard_layer_ids()
    if not crt_layers:
        return footprint.GetBoundingBox(False, False)

    box = None
    try:
        items = footprint.GraphicalItems()
    except Exception:
        items = []

    for item in items:
        try:
            if item.GetLayer() not in crt_layers:
                continue
        except Exception:
            continue
        try:
            ibox = item.GetBoundingBox()
        except Exception:
            continue
        if box is None:
            box = pcbnew.BOX2I(ibox.GetOrigin(), ibox.GetSize())
        else:
            box.Merge(ibox)

    if box is None:
        return footprint.GetBoundingBox(False, False)
    return box


def corner_point(bbox, corner):
    "Return (x, y) of bbox corner. KiCad y grows downward."
    if corner not in CORNERS:
        raise ValueError("bad corner: {}".format(corner))
    x = bbox.GetLeft() if corner in ("TL", "BL") else bbox.GetRight()
    y = bbox.GetTop() if corner in ("TL", "TR") else bbox.GetBottom()
    return x, y


def edge_coord(bbox, edge):
    "Return scalar coordinate of bbox edge (x for L/R, y for T/B)."
    if edge == "L":
        return bbox.GetLeft()
    if edge == "R":
        return bbox.GetRight()
    if edge == "T":
        return bbox.GetTop()
    if edge == "B":
        return bbox.GetBottom()
    raise ValueError("bad edge: {}".format(edge))


def snap_corner_to_corner(anchor_fp, move_fp, anchor_corner, move_corner,
                          dx_nm=0, dy_nm=0):
    "Translate move_fp so its corner lands on anchor_fp corner + (dx,dy)."
    a_bbox = courtyard_bbox(anchor_fp)
    m_bbox = courtyard_bbox(move_fp)
    ax, ay = corner_point(a_bbox, anchor_corner)
    mx, my = corner_point(m_bbox, move_corner)
    move_fp.Move(_vec(ax - mx + dx_nm, ay - my + dy_nm))


def snap_edge_to_edge(anchor_fp, move_fp, anchor_edge, move_edge,
                      dx_nm=0, dy_nm=0):
    """Translate move_fp so its edge meets anchor_fp edge along perpendicular axis.

    Only the perpendicular axis is snapped; the parallel axis is preserved
    (user can nudge with dx/dy).
    """
    a_horiz = anchor_edge in HORIZONTAL_EDGES
    m_horiz = move_edge in HORIZONTAL_EDGES
    if a_horiz != m_horiz:
        raise ValueError("edges must share orientation (both T/B or both L/R)")

    a_bbox = courtyard_bbox(anchor_fp)
    m_bbox = courtyard_bbox(move_fp)
    a_val = edge_coord(a_bbox, anchor_edge)
    m_val = edge_coord(m_bbox, move_edge)
    delta = a_val - m_val

    if a_horiz:
        move_fp.Move(_vec(dx_nm, delta + dy_nm))
    else:
        move_fp.Move(_vec(delta + dx_nm, dy_nm))


def selected_footprints(board):
    return [fp for fp in board.GetFootprints() if fp.IsSelected() and not fp.IsLocked()]
