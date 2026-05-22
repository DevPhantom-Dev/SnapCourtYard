"""Edge-to-edge courtyard snapping for selected footprints."""

import pcbnew


AXIS_X = "x"
AXIS_Y = "y"


def _courtyard_polyset(footprint):
    """Return merged front+back courtyard SHAPE_POLY_SET, or None."""
    layers = []
    for layer_name in ("F_CrtYd", "B_CrtYd"):
        layer_id = getattr(pcbnew, layer_name, None)
        if layer_id is None:
            continue
        try:
            poly = footprint.GetCourtyard(layer_id)
        except Exception:
            poly = None
        if poly and poly.OutlineCount() > 0:
            layers.append(poly)

    if not layers:
        return None

    merged = pcbnew.SHAPE_POLY_SET()
    for poly in layers:
        merged.Append(poly)
    return merged


def courtyard_bbox(footprint):
    """Return BOX2I of footprint courtyard; falls back to footprint bbox if none."""
    poly = _courtyard_polyset(footprint)
    if poly is None or poly.OutlineCount() == 0:
        return footprint.GetBoundingBox(False, False)
    return poly.BBox()


def snap_edge_to_edge(footprints, axis=AXIS_X, gap_nm=0):
    """Chain footprints so courtyards abut along given axis.

    Sort by current position on axis; anchor first; translate rest so leading
    edge meets trailing edge of previous. gap_nm is extra spacing in nanometers.
    Returns count of moved footprints.
    """
    if len(footprints) < 2:
        return 0

    def pos_key(fp):
        p = fp.GetPosition()
        return p.x if axis == AXIS_X else p.y

    ordered = sorted(footprints, key=pos_key)
    moved = 0

    prev_bbox = courtyard_bbox(ordered[0])
    for fp in ordered[1:]:
        cur_bbox = courtyard_bbox(fp)
        if axis == AXIS_X:
            delta = (prev_bbox.GetRight() + gap_nm) - cur_bbox.GetLeft()
            offset = pcbnew.VECTOR2I(delta, 0)
        else:
            delta = (prev_bbox.GetBottom() + gap_nm) - cur_bbox.GetTop()
            offset = pcbnew.VECTOR2I(0, delta)

        fp.Move(offset)
        moved += 1
        prev_bbox = courtyard_bbox(fp)

    return moved


def selected_footprints(board):
    return [fp for fp in board.GetFootprints() if fp.IsSelected()]
