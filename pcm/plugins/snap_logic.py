"""Corner and edge courtyard snapping — pure Python, no KiCad API dependencies.

All coordinates are in nanometres (KiCad internal units).
1 mm = 1_000_000 nm.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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
VERTICAL_EDGES   = ("L", "R")


# ---------------------------------------------------------------------------
# BBox — thin wrapper so callers don't depend on any KiCad type
# ---------------------------------------------------------------------------

class BBox:
    """Axis-aligned bounding box in nanometres."""

    __slots__ = ("left", "top", "right", "bottom")

    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left   = int(left)
        self.top    = int(top)
        self.right  = int(right)
        self.bottom = int(bottom)

    def __repr__(self) -> str:
        return (f"BBox(left={self.left}, top={self.top}, "
                f"right={self.right}, bottom={self.bottom})")


def bbox_from_kipy(fp) -> BBox:
    """Build a BBox from a kipy Footprint object.

    kipy exposes ``fp.bounding_box`` as a ``Box2`` proto with
    ``.start`` (top-left) and ``.end`` (bottom-right) Vector2 values,
    both in nanometres.

    NOTE: The KiCad IPC API does not yet expose individual courtyard
    PCB_SHAPE strokes separately.  We therefore use the overall footprint
    bounding box as a conservative approximation.  A future kipy release
    may add a dedicated ``fp.courtyard_bounding_box`` property.
    """
    bb = fp.bounding_box
    return BBox(
        left   = int(bb.start.x),
        top    = int(bb.start.y),
        right  = int(bb.end.x),
        bottom = int(bb.end.y),
    )


# ---------------------------------------------------------------------------
# Unit helper
# ---------------------------------------------------------------------------

def from_mm(mm: float) -> int:
    """Convert millimetres to KiCad internal units (nanometres)."""
    return int(float(mm) * 1_000_000)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def corner_point(bbox: BBox, corner: str) -> tuple[int, int]:
    """Return (x, y) of the named corner.  KiCad y-axis grows downward."""
    if corner not in CORNERS:
        raise ValueError(f"Unknown corner: {corner!r}. Must be one of {CORNERS}.")
    x = bbox.left  if corner in ("TL", "BL") else bbox.right
    y = bbox.top   if corner in ("TL", "TR") else bbox.bottom
    return x, y


def edge_coord(bbox: BBox, edge: str) -> int:
    """Return the scalar coordinate of the named bbox edge."""
    if edge == "L": return bbox.left
    if edge == "R": return bbox.right
    if edge == "T": return bbox.top
    if edge == "B": return bbox.bottom
    raise ValueError(f"Unknown edge: {edge!r}. Must be one of {EDGES}.")


# ---------------------------------------------------------------------------
# Snap calculations — return (dx, dy) deltas, never mutate footprints
# ---------------------------------------------------------------------------

def delta_corner_to_corner(
    anchor_bbox:   BBox,
    move_bbox:     BBox,
    anchor_corner: str,
    move_corner:   str,
    dx_nm: int = 0,
    dy_nm: int = 0,
) -> tuple[int, int]:
    """Return (dx, dy) to translate the moving footprint so its chosen corner
    meets the anchor's chosen corner (plus optional extra offset)."""
    ax, ay = corner_point(anchor_bbox, anchor_corner)
    mx, my = corner_point(move_bbox,   move_corner)
    return ax - mx + dx_nm, ay - my + dy_nm


def delta_edge_to_edge(
    anchor_bbox: BBox,
    move_bbox:   BBox,
    anchor_edge: str,
    move_edge:   str,
    dx_nm: int = 0,
    dy_nm: int = 0,
) -> tuple[int, int]:
    """Return (dx, dy) to translate the moving footprint so its chosen edge
    meets the anchor's chosen edge.

    Only the *perpendicular* axis is snapped; the parallel-axis position is
    unchanged (user can nudge with dx_nm / dy_nm).
    """
    a_horiz = anchor_edge in HORIZONTAL_EDGES
    m_horiz = move_edge   in HORIZONTAL_EDGES
    if a_horiz != m_horiz:
        raise ValueError(
            "Anchor and moving edges must share orientation "
            "(both T/B or both L/R)."
        )
    delta = edge_coord(anchor_bbox, anchor_edge) - edge_coord(move_bbox, move_edge)
    if a_horiz:
        return dx_nm, delta + dy_nm
    else:
        return delta + dx_nm, dy_nm


# ---------------------------------------------------------------------------
# Chain helper — drives a sequence of snaps
# ---------------------------------------------------------------------------

def chain_deltas(
    bboxes:        list[BBox],
    anchor_idx:    int,
    a_slot:        str,
    m_slot:        str,
    dx_nm:         int = 0,
    dy_nm:         int = 0,
) -> list[tuple[int, int]]:
    """Compute per-footprint (dx, dy) deltas for a full chain snap.

    The footprint at *anchor_idx* stays fixed (delta = (0, 0)).
    Every other footprint snaps to the previous one in chain order.

    Returns a list of (dx, dy) with the same length as *bboxes*,
    where bboxes[i] is the *original* bbox of footprint i.

    Callers must apply each delta to the *cumulative* position:
    after footprint i moves, its new bbox must be recomputed before
    snapping footprint i+1 to it.
    """
    is_corner = a_slot in CORNERS

    n = len(bboxes)
    deltas: list[tuple[int, int]] = [(0, 0)] * n

    # Build chain order: anchor first, then the rest in their original order.
    others = [i for i in range(n) if i != anchor_idx]
    chain = [anchor_idx] + others

    # We need to track bbox positions as we move each footprint.
    # Start with copies of the original bboxes.
    current = [BBox(b.left, b.top, b.right, b.bottom) for b in bboxes]

    for k in range(1, len(chain)):
        prev_idx = chain[k - 1]
        curr_idx = chain[k]
        prev_bb  = current[prev_idx]
        curr_bb  = current[curr_idx]

        if is_corner:
            dx, dy = delta_corner_to_corner(prev_bb, curr_bb, a_slot, m_slot,
                                            dx_nm, dy_nm)
        else:
            dx, dy = delta_edge_to_edge(prev_bb, curr_bb, a_slot, m_slot,
                                        dx_nm, dy_nm)

        deltas[curr_idx] = (dx, dy)

        # Shift current bbox so the next footprint snaps to the moved position.
        b = current[curr_idx]
        current[curr_idx] = BBox(b.left  + dx, b.top    + dy,
                                 b.right + dx, b.bottom + dy)

    return deltas
