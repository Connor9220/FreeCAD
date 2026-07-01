# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Billy Huddleston <billy@ivdc.com>
# SPDX-FileNotice: Part of the FreeCAD project.

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

__title__ = "CAM Flute Operation"
__author__ = "Connor (Billy Huddleston <billy@ivdc.com>)"
__url__ = "https://www.freecad.org"
__doc__ = "Class and implementation of the Flute operation."

import collections
import math

import FreeCAD
from PySide import QtCore
import Path
import Path.Op.Base as PathOp
import Path.Base.Generator.flute as FluteGenerator
import Path.Base.Generator.linking as linking
import PathScripts.PathUtils as PathUtils

from lazy_loader.lazy_loader import LazyLoader

Part = LazyLoader("Part", globals(), "Part")

translate = FreeCAD.Qt.translate

if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())

_PREC = FreeCAD.Base.Precision.confusion()  # standard FreeCAD coincidence epsilon (1e-7)

_FLAT_SLOPE = 0.001  # dZ/ds below this → "flat" segment
_SECTION_Z_TOL_FRAC = 0.05  # z_tol = max(1mm, depth * this fraction)
_CHAIN_MAX_EDGES = 200  # guard against infinite loop (not a tolerance)
_WALL_SLOPE_MAX = 5.0  # dz/ds above this → discard as a side wall
_WALL_DS_MIN = _PREC * 10  # floating-point "is this exactly zero" epsilon
# Middle-only sample points — endpoints excluded because a legitimately tapered
# channel's edges converge there too and would give a false degenerate signal.
_PCA_DEGENERATE_T_VALUES = (0.25, 0.5, 0.75)
_VBIT_ANGLE_FRAC = 0.025  # 2.5% of groove half-angle — fuzzy margin for V-bit fit check

_Tol = collections.namedtuple(
    "_Tol",
    ["edge", "chain2", "floor_snap", "axial_floor", "bb_overlap",
     "section_overshoot", "pca_degenerate", "arc_chord"],
)


def _make_tolerances(geom_tol):
    """Derive all absolute-distance tolerances from the job's GeometryTolerance.
    Fallback of 0.01 mm matches the default used across other CAM operations.
    """
    t = geom_tol if geom_tol and geom_tol > 0 else 0.01
    return _Tol(
        edge=t * 0.01,           # exact topological edge-coincidence
        chain2=(t * 200.0) ** 2, # vertex snap distance while chaining (stored squared)
        floor_snap=t * 50.0,     # floor-seam Z snapping
        axial_floor=t * 50.0,    # axial-leave floor-point detection
        bb_overlap=t * 100.0,    # face grouping by bounding-box touch
        section_overshoot=t * 1000.0,  # section-plane / candidate-filter margin
        pca_degenerate=t * 5.0,  # centerline-coincides-with-edge test
        arc_chord=t * 10.0,      # arc discretization chord (matches LeadInOut dressup)
    )


# ---------------------------------------------------------------------------
# Face analysis helpers
# ---------------------------------------------------------------------------


def _analyze_face_cylinder(face):
    """Centerline from a Part.Cylinder face using the face BoundBox directly.

    The BoundBox gives us everything we need:
      - Groove center X (or Y): midpoint of the perpendicular extents
      - Shallow end: the BoundBox extreme at ZMax (stock surface)
      - Deep end:    the BoundBox extreme at ZMin (floor)
      - Width:       2 * surface.Radius

    The cylinder axis direction tells us which BoundBox dimension the groove
    runs along, and the sign of that axis component tells us which extreme
    is the shallow (entry) end.

    Returns the same dict as _analyze_face_pca, or None if not a cylinder.
    """
    try:
        surface = face.Surface
        if not isinstance(surface, Part.Cylinder):
            return None

        axis = surface.Axis
        radius = surface.Radius
        bb = face.BoundBox

        ax, ay, az = abs(axis.x), abs(axis.y), abs(axis.z)

        if ay >= ax and ay >= az:
            # Groove runs primarily in Y
            cx = (bb.XMin + bb.XMax) / 2.0
            if axis.y < 0:
                # Moving along +axis → Y decreases → deep end = YMin
                p_start = FreeCAD.Vector(cx, bb.YMax, bb.ZMax)
                p_end = FreeCAD.Vector(cx, bb.YMin, bb.ZMin)
            else:
                # Moving along +axis → Y increases → deep end = YMax
                p_start = FreeCAD.Vector(cx, bb.YMin, bb.ZMax)
                p_end = FreeCAD.Vector(cx, bb.YMax, bb.ZMin)

        elif ax >= ay and ax >= az:
            # Groove runs primarily in X
            cy = (bb.YMin + bb.YMax) / 2.0
            if axis.x < 0:
                p_start = FreeCAD.Vector(bb.XMax, cy, bb.ZMax)
                p_end = FreeCAD.Vector(bb.XMin, cy, bb.ZMin)
            else:
                p_start = FreeCAD.Vector(bb.XMin, cy, bb.ZMax)
                p_end = FreeCAD.Vector(bb.XMax, cy, bb.ZMin)

        else:
            return None  # Z-dominant - not a typical flute orientation

        Path.Log.debug(
            "CAM_Flute BoundBox:\n"
            "  X: [{:.4f}, {:.4f}]  Y: [{:.4f}, {:.4f}]  Z: [{:.4f}, {:.4f}]\n"
            "  axis=({:.4f},{:.4f},{:.4f})  radius={:.4f}\n"
            "CAM_Flute centerline:\n"
            "  start=({:.4f},{:.4f},{:.4f})  end=({:.4f},{:.4f},{:.4f})\n".format(
                bb.XMin,
                bb.XMax,
                bb.YMin,
                bb.YMax,
                bb.ZMin,
                bb.ZMax,
                axis.x,
                axis.y,
                axis.z,
                radius,
                p_start.x,
                p_start.y,
                p_start.z,
                p_end.x,
                p_end.y,
                p_end.z,
            )
        )

        def _clean(v, tol=_PREC):
            return 0.0 if abs(v) < tol else v

        return {
            "start": p_start,
            "end": p_end,
            "top_z": _clean(bb.ZMax),
            "width": _clean(2.0 * radius),
        }
    except Exception:
        return None


def _line_coincides_with_an_edge(face, p_a, p_b, tol):
    """True if the MIDDLE portion of the line p_a->p_b lies ON one of the
    face's own boundary edges (within tol.pca_degenerate).

    A real floor's centerline runs through the face's interior. A face that
    legitimately tapers to a point at one end (e.g. a pointed channel) will
    have its boundary edges genuinely converge near that end -- that's not
    a sign of a missing partner face, so the endpoints are deliberately
    excluded. Only the middle of the line is tested: a single wall of an
    unselected V-groove pair has zero interior width along its ENTIRE
    length, so it still coincides with the shared valley edge there too.
    """
    try:
        edges = face.Edges
    except Exception:
        return False

    for edge in edges:
        coincides = True
        for t in _PCA_DEGENERATE_T_VALUES:
            p = FreeCAD.Vector(
                p_a.x + t * (p_b.x - p_a.x),
                p_a.y + t * (p_b.y - p_a.y),
                p_a.z + t * (p_b.z - p_a.z),
            )
            try:
                dist = edge.distToShape(Part.Vertex(p))[0]
            except Exception:
                coincides = False
                break
            if dist > tol.pca_degenerate:
                coincides = False
                break
        if coincides:
            return True
    return False


def _analyze_face_pca(face, tol):
    """Centerline fallback via edge sampling + PCA for non-cylindrical faces.

    Samples all face edges, uses PCA to split into two end-zones, then
    finds the lowest-Z cluster in each zone.  Key insight: for any groove
    profile the deepest cross-section point IS on the centreline.

    Returns dict with keys start, end, top_z, width, or None on failure.
    """
    pts = []
    try:
        for edge in face.Edges:
            pts.extend(edge.discretize(Number=100))
    except Exception:
        pass

    if len(pts) < 4:
        return None

    mx = sum(p.x for p in pts) / len(pts)
    my = sum(p.y for p in pts) / len(pts)

    cxx = sum((p.x - mx) ** 2 for p in pts)
    cyy = sum((p.y - my) ** 2 for p in pts)
    cxy = sum((p.x - mx) * (p.y - my) for p in pts)

    angle = 0.5 * math.atan2(2.0 * cxy, cxx - cyy)
    ux, uy = math.cos(angle), math.sin(angle)
    vx, vy = -uy, ux

    s_vals = [(p.x - mx) * ux + (p.y - my) * uy for p in pts]
    t_vals = [(p.x - mx) * vx + (p.y - my) * vy for p in pts]

    s_min, s_max = min(s_vals), max(s_vals)
    span = s_max - s_min
    if span < _PREC:
        return None

    zone = span * 0.20
    a_pts = [p for p, s in zip(pts, s_vals) if s <= s_min + zone]
    b_pts = [p for p, s in zip(pts, s_vals) if s >= s_max - zone]

    if not a_pts or not b_pts:
        return None

    def _lowest_z_center(zone_pts):
        z_floor = min(p.z for p in zone_pts)
        z_range = max(p.z for p in zone_pts) - z_floor
        tol = max(0.01, z_range * 0.02)
        near = [p for p in zone_pts if p.z <= z_floor + tol]
        return FreeCAD.Vector(
            sum(p.x for p in near) / len(near),
            sum(p.y for p in near) / len(near),
            sum(p.z for p in near) / len(near),
        )

    p_a = _lowest_z_center(a_pts)
    p_b = _lowest_z_center(b_pts)
    if p_a.z < p_b.z:
        p_a, p_b = p_b, p_a

    # Reject a degenerate result: if the computed centerline coincides with
    # one of the face's own boundary edges, this face has no floor of its
    # own -- it's most likely a single wall of an unselected V-groove pair.
    if _line_coincides_with_an_edge(face, p_a, p_b, tol):
        FreeCAD.Console.PrintWarning(
            translate(
                "CAM_Flute",
                "Face appears to be a single wall of a V-groove (its "
                "centerline coincides with a face edge). Select both walls "
                "of the groove, or select the valley edge directly.\n",
            )
        )
        return None

    top_z = max(p.z for p in pts)

    def _clean(v, tol=_PREC):
        return 0.0 if abs(v) < tol else v

    return {
        "start": p_a,
        "end": p_b,
        "top_z": _clean(top_z),
        "width": _clean(max(t_vals) - min(t_vals)),
    }


def _analyze_face(face, tol):
    """Determine the centerline of a single groove face.

    Tries exact cylinder-surface detection first; falls back to edge-
    sampling PCA for BSpline or other surface types.
    """
    result = _analyze_face_cylinder(face)
    if result is not None:
        FreeCAD.Console.PrintLog("CAM_Flute: centerline via cylinder surface (exact)\n")
        return result
    FreeCAD.Console.PrintLog("CAM_Flute: centerline via edge-sampling PCA (fallback)\n")
    return _analyze_face_pca(face, tol)


# ---------------------------------------------------------------------------
# V-bottom (multi-face) grouping helpers
# ---------------------------------------------------------------------------


def _find_shared_edges(face_a, face_b, tol):
    """Return edges that are geometrically coincident between two faces."""
    shared = []
    for ea in face_a.Edges:
        com_a = ea.CenterOfMass
        len_a = ea.Length
        for eb in face_b.Edges:
            if abs(len_a - eb.Length) > tol.edge:
                continue
            if com_a.distanceToPoint(eb.CenterOfMass) > tol.edge:
                continue
            # Verify endpoints match (in either order)
            pa0 = ea.Vertexes[0].Point
            pa1 = ea.Vertexes[-1].Point
            pb0 = eb.Vertexes[0].Point
            pb1 = eb.Vertexes[-1].Point
            if (pa0.distanceToPoint(pb0) < tol.edge and pa1.distanceToPoint(pb1) < tol.edge) or (
                pa0.distanceToPoint(pb1) < tol.edge and pa1.distanceToPoint(pb0) < tol.edge
            ):
                shared.append(ea)
                break
    return shared



def _is_valley_edge(edge, face_a, face_b):
    """Return True if the shared edge sits below both adjacent face centroids.

    For any groove in a flute operation the valley edge is always the lowest
    part of the two wall faces - its Z centroid is below the average face Z.
    This is simpler and more reliable than a cross-product sign test, which
    depends on the BRep edge orientation and can flip sign unexpectedly.
    """
    try:
        edge_z = edge.CenterOfMass.z
        face_z = (face_a.CenterOfMass.z + face_b.CenterOfMass.z) / 2.0
        return edge_z < face_z - _PREC * 10
    except Exception:
        return False


def _group_flutes(face_tuples, tol):
    """Group (face, sub_name, base_obj) tuples into flute groups.

    Primary grouping: faces whose XY bounding boxes overlap or touch (within
    tol.bb_overlap) are treated as parts of the same groove.  This correctly
    merges ramp + flat faces (which share an edge but are not a concave
    V-bottom) as well as V-groove face pairs.

    Within each resulting group, valley-edge detection is still run so that
    two-face V-bottom groups can expose their shared concave edge for
    centerline extraction.

    Returns list of dicts:
        {
          'faces':       [(face, sub, base), ...],
          'valley_edge': list[Part.Edge] or None,
        }
    """
    n = len(face_tuples)
    if n == 0:
        return []

    def _bb_overlaps_xy(bb_a, bb_b):
        return (
            bb_a.XMin <= bb_b.XMax + tol.bb_overlap
            and bb_a.XMax >= bb_b.XMin - tol.bb_overlap
            and bb_a.YMin <= bb_b.YMax + tol.bb_overlap
            and bb_a.YMax >= bb_b.YMin - tol.bb_overlap
        )

    parent = list(range(n))

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x, y):
        rx, ry = _find(x), _find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if _bb_overlaps_xy(face_tuples[i][0].BoundBox, face_tuples[j][0].BoundBox):
                _union(i, j)

    groups_map = {}
    for i in range(n):
        groups_map.setdefault(_find(i), []).append(i)

    result = []
    for indices in groups_map.values():
        flute_faces = [face_tuples[k] for k in indices]

        # Check for concave (valley) edges within the group - used only for
        # V-bottom two-face centerline detection. The valley boundary between
        # the two faces can be split into several B-Rep edge segments (e.g. a
        # tapered V-groove with a seam partway along); collect ALL of them so
        # the centerline isn't truncated at the first segment found.
        valley_edges = []
        if len(indices) == 2:
            fa, fb = flute_faces[0][0], flute_faces[1][0]
            shared = _find_shared_edges(fa, fb, tol)
            for edge in shared:
                if _is_valley_edge(edge, fa, fb):
                    valley_edges.append(edge)

        result.append({"faces": flute_faces, "valley_edge": valley_edges or None})

    return result


def _centerline_from_valley_edge(edges, face_tuples, tol):
    """Get start/end/top_z from one or more V-bottom valley edges.

    The valley boundary between two faces may consist of several colinear/
    curved edge segments rather than a single edge. Chain them end-to-end
    by matching coincident endpoints and use the two outer extremities of
    the resulting chain as the cutting centerline. Start = shallower end.
    top_z = highest Z across all face bounding boxes.
    """
    if not isinstance(edges, (list, tuple)):
        edges = [edges]

    if len(edges) == 1:
        v0 = edges[0].Vertexes[0].Point
        v1 = edges[0].Vertexes[-1].Point
    else:
        remaining = list(edges[1:])
        chain = [edges[0].Vertexes[0].Point, edges[0].Vertexes[-1].Point]
        changed = True
        while remaining and changed:
            changed = False
            for e in list(remaining):
                p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
                if chain[-1].distanceToPoint(p0) < tol.edge:
                    chain.append(p1)
                elif chain[-1].distanceToPoint(p1) < tol.edge:
                    chain.append(p0)
                elif chain[0].distanceToPoint(p0) < tol.edge:
                    chain.insert(0, p1)
                elif chain[0].distanceToPoint(p1) < tol.edge:
                    chain.insert(0, p0)
                else:
                    continue
                remaining.remove(e)
                changed = True
        v0, v1 = chain[0], chain[-1]

    if v0.z < v1.z:
        v0, v1 = v1, v0  # v0 = shallow, v1 = deep

    top_z = max(ft[0].BoundBox.ZMax for ft in face_tuples)

    # Groove half-angle from the first planar wall face normal.
    # For a V-wall: normal points mostly horizontal (outward) with a Z
    # component encoding the slope.  half_angle = arcsin(|n.z|).
    groove_half_angle = 0.0
    for ft in face_tuples:
        try:
            n = ft[0].Surface.Axis
            nlen = math.sqrt(n.x ** 2 + n.y ** 2 + n.z ** 2)
            if nlen > _PREC * 0.01:
                groove_half_angle = math.degrees(math.asin(min(1.0, abs(n.z) / nlen)))
                break
        except Exception:
            pass

    def _clean(val, tol=_PREC):
        return 0.0 if abs(val) < tol else val

    return {
        "start": FreeCAD.Vector(v0),
        "end": FreeCAD.Vector(v1),
        "top_z": _clean(top_z),
        "width": 0.0,
        "groove_half_angle": groove_half_angle,
    }


def _centerline_from_faces(face_tuples):
    """Run PCA across all faces in a group (fallback for >2-face groups)."""
    pts = []
    for face, _sub, _base in face_tuples:
        try:
            for edge in face.OuterWire.Edges:
                pts.extend(edge.discretize(Number=20))
        except Exception:
            pass

    if len(pts) < 2:
        return None

    # Re-use the single-face PCA logic on the combined point cloud
    mx = sum(p.x for p in pts) / len(pts)
    my = sum(p.y for p in pts) / len(pts)
    cxx = sum((p.x - mx) ** 2 for p in pts)
    cyy = sum((p.y - my) ** 2 for p in pts)
    cxy = sum((p.x - mx) * (p.y - my) for p in pts)

    angle = 0.5 * math.atan2(2.0 * cxy, cxx - cyy)
    ux, uy = math.cos(angle), math.sin(angle)
    vx, vy = -uy, ux

    proj = []
    for p in pts:
        dx, dy = p.x - mx, p.y - my
        proj.append((p, dx * ux + dy * uy, dx * vx + dy * vy))

    s_min = min(r[1] for r in proj)
    s_max = max(r[1] for r in proj)
    t_min = min(r[2] for r in proj)
    t_max = max(r[2] for r in proj)
    zone = (s_max - s_min) * 0.05

    def _avg(points):
        return FreeCAD.Vector(
            sum(p.x for p in points) / len(points),
            sum(p.y for p in points) / len(points),
            sum(p.z for p in points) / len(points),
        )

    a_pts = [p for p, s, _t in proj if s <= s_min + zone]
    b_pts = [p for p, s, _t in proj if s >= s_max - zone]
    p_a, p_b = _avg(a_pts), _avg(b_pts)
    if p_a.z < p_b.z:
        p_a, p_b = p_b, p_a

    top_z = max(p.z for p in pts)

    def _clean(v, tol=_PREC):
        return 0.0 if abs(v) < tol else v

    return {
        "start": p_a,
        "end": p_b,
        "top_z": _clean(top_z),
        "width": _clean(t_max - t_min),
    }


def _check_tool_fit(info, tool):
    """Warn if the tool appears too large for the detected groove geometry.

    Checks two independent conditions from the centerline info dict:
      - width > 0: rounded/flat channel - tool diameter vs groove width.
      - groove_half_angle > 0: V-groove - V-bit half-angle vs groove half-angle.
    Always returns None; caller continues regardless.
    """
    tool_dia = float(tool.Diameter)
    is_vbit = hasattr(tool, "CuttingEdgeAngle")

    # Width check only applies to flat/bull-nose tools - a V-bit's effective
    # cutting width depends on depth, not diameter.
    def _qty(mm):
        return FreeCAD.Units.Quantity(mm, FreeCAD.Units.Length).UserString

    if not is_vbit:
        groove_width = info.get("width", 0.0)
        if groove_width > 0.0 and tool_dia > groove_width:
            FreeCAD.Console.PrintWarning(
                translate(
                    "CAM_Flute",
                    "CAM_Flute: tool diameter ({}) exceeds groove width ({})"
                    " - path may overcut.\n",
                ).format(_qty(tool_dia), _qty(groove_width))
            )

    if is_vbit:
        try:
            tool_ha = tool.CuttingEdgeAngle.Value / 2.0
        except Exception:
            tool_ha = 0.0

        groove_ha = info.get("groove_half_angle", 0.0)
        if groove_ha == 0.0:
            # Valley edge not detected - estimate from PCA width and depth.
            width = info.get("width", 0.0)
            depth = info["top_z"] - info["end"].z
            if width > 0.0 and depth > 0.0:
                groove_ha = math.degrees(math.atan2(width / 2.0, depth))

        Path.Log.debug(
            "CAM_Flute: tool half-angle={:.2f}° groove half-angle={:.2f}°\n".format(
                tool_ha, groove_ha
            )
        )
        if tool_ha > 0.0 and groove_ha > 0.0 and tool_ha > groove_ha * (1.0 + _VBIT_ANGLE_FRAC):
            FreeCAD.Console.PrintWarning(
                translate(
                    "CAM_Flute",
                    "CAM_Flute: V-bit half-angle ({:.1f}°) exceeds groove"
                    " half-angle ({:.1f}°) - flanks may contact walls before"
                    " reaching depth.\n",
                ).format(tool_ha, groove_ha)
            )


def _get_centerline(group, tol):
    """Return the centerline dict for a flute group (any size)."""
    valley_edge = group.get("valley_edge")
    face_tuples = group["faces"]

    if valley_edge is not None:
        # 2-face V-bottom: the valley edge IS the centerline
        return _centerline_from_valley_edge(valley_edge, face_tuples, tol)
    elif len(face_tuples) == 1:
        # Single flat/bull-nose face: PCA
        return _analyze_face(face_tuples[0][0], tol)
    else:
        # >2 faces with no detected valley edge: run PCA across all faces
        Path.Log.debug(
            "Flute group has {} faces with no detected valley edge; "
            "falling back to combined PCA.\n".format(len(face_tuples))
        )
        return _centerline_from_faces(face_tuples)


def _dist2(a, b):
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2


def _classify_chain_segments(chain, path_proj, tol):
    """Classify an ordered chain of (seg_start, seg_end, edge) triples into
    the generic segment-dict format used by the path generator.

    - Part.Circle edges  -> "arc": exact radius, discretized arc_points.
    - Straight-line edges -> "ramp"/"flat" by overall slope, exact endpoints.
    - Anything else (BSpline, Bezier, ...) -> "ramp"/"flat" by overall slope,
      discretized into arc_points to preserve the actual curve shape.
    """
    segments = []
    for seg_start, seg_end, edge in chain:
        dp = path_proj(seg_end) - path_proj(seg_start)
        dz = seg_end.z - seg_start.z
        slope = (dz / dp) if abs(dp) > _PREC * 10 else 0.0

        try:
            curve = edge.Curve
        except Exception:
            curve = None

        if isinstance(curve, Part.Circle):
            seg_type = "arc"
            radius = curve.Radius
            raw_pts = edge.discretize(Distance=tol.arc_chord)
            if _dist2(raw_pts[0], seg_start) > _dist2(raw_pts[-1], seg_start):
                raw_pts = list(reversed(raw_pts))
            arc_pts = raw_pts
        elif curve is None or isinstance(curve, (Part.Line, Part.LineSegment)):
            seg_type = "flat" if abs(slope) < _FLAT_SLOPE else "ramp"
            radius = None
            arc_pts = None
        else:
            # BSpline / Bezier / other curve types: discretize to preserve shape.
            seg_type = "flat" if abs(slope) < _FLAT_SLOPE else "ramp"
            radius = None
            raw_pts = edge.discretize(Distance=tol.arc_chord)
            if _dist2(raw_pts[0], seg_start) > _dist2(raw_pts[-1], seg_start):
                raw_pts = list(reversed(raw_pts))
            arc_pts = raw_pts

        segments.append(
            {
                "type": seg_type,
                "start": FreeCAD.Vector(seg_start),
                "end": FreeCAD.Vector(seg_end),
                "radius": radius,
                "arc_points": arc_pts,
            }
        )
    return segments


# ---------------------------------------------------------------------------
# Centerline directly from a selected wire (edges) - bypasses face/solid
# analysis entirely. The wire IS the centerline.
# ---------------------------------------------------------------------------


def _split_into_wires(edges, tol):
    """Split a flat list of edges into connected components (separate wires).

    Each component becomes one independent flute (mirrors how separate face
    groups become separate flutes).
    """
    remaining = list(edges)
    wires = []
    while remaining:
        comp = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            for e in list(remaining):
                v0, v1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
                for c in comp:
                    cv0, cv1 = c.Vertexes[0].Point, c.Vertexes[-1].Point
                    if (
                        _dist2(v0, cv0) < tol.chain2
                        or _dist2(v0, cv1) < tol.chain2
                        or _dist2(v1, cv0) < tol.chain2
                        or _dist2(v1, cv1) < tol.chain2
                    ):
                        comp.append(e)
                        remaining.remove(e)
                        changed = True
                        break
        wires.append(comp)
    return wires


def _chain_wire_edges(edges, tol):
    """Chain a connected set of edges into ordered (seg_start, seg_end, edge)
    triples by matching coincident endpoints.

    Assumes edges form a single simple open path (no branching).  Returns
    None if they don't all connect into one chain.
    """
    if not edges:
        return None

    remaining = list(edges[1:])
    e0 = edges[0]
    chain = [(e0.Vertexes[0].Point, e0.Vertexes[-1].Point, e0)]

    changed = True
    while remaining and changed:
        changed = False
        cur_s, cur_e = chain[0][0], chain[-1][1]
        for e in list(remaining):
            v0, v1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if _dist2(cur_e, v0) < tol.chain2:
                chain.append((v0, v1, e))
            elif _dist2(cur_e, v1) < tol.chain2:
                chain.append((v1, v0, e))
            elif _dist2(cur_s, v0) < tol.chain2:
                chain.insert(0, (v1, v0, e))
            elif _dist2(cur_s, v1) < tol.chain2:
                chain.insert(0, (v0, v1, e))
            else:
                continue
            remaining.remove(e)
            changed = True
            break

    if remaining:
        return None  # could not connect all edges into a single chain

    return chain


def _segments_from_wire(edges, tol):
    """Convert a connected wire (chain of edges) directly into the generic
    segment-chain format used by the path generator. The wire IS the
    centerline - no face or solid-section analysis is performed.

    Returns (segments, top_z, floor_z), or (None, None, None) on failure.
    """
    chain = _chain_wire_edges(edges, tol)
    if not chain:
        FreeCAD.Console.PrintWarning(
            translate("CAM_Flute", "Selected edges do not form a single connected wire.\n")
        )
        return None, None, None

    # Orient so the shallower (higher Z) free end is the start.
    if chain[0][0].z < chain[-1][1].z:
        chain = [(e, s, edge) for s, e, edge in reversed(chain)]

    start = chain[0][0]
    end = chain[-1][1]
    dx, dy = end.x - start.x, end.y - start.y
    L = math.sqrt(dx * dx + dy * dy)
    path_dir = FreeCAD.Vector(dx / L, dy / L, 0.0) if L > _PREC else FreeCAD.Vector(0.0, 0.0, 0.0)

    def path_proj(v):
        return (v.x - start.x) * path_dir.x + (v.y - start.y) * path_dir.y

    segments = _classify_chain_segments(chain, path_proj, tol)

    all_z = [v.z for s, e, _ in chain for v in (s, e)]
    return segments, max(all_z), min(all_z)


# ---------------------------------------------------------------------------
# Profile detection via solid section
# ---------------------------------------------------------------------------


def _detect_floor_segments(face, base_obj, info, tol, group_extent=None):
    """Section base_obj.Shape with a vertical plane through the groove
    centreline and return an ordered list of typed segment dicts.

    Each dict has keys: "type" ("ramp"|"flat"|"arc"), "start" (Vector),
    "end" (Vector), "radius" (float or None), "arc_points" (list or None).

    Returns [] on any failure; the caller falls back to a plain Ramp.
    """
    try:
        start = info["start"]
        end_info = info["end"]
        top_z = info["top_z"]
        floor_z = end_info.z

        dx = end_info.x - start.x
        dy = end_info.y - start.y
        L = math.sqrt(dx * dx + dy * dy)
        if L < _PREC:
            return []

        path_dir = FreeCAD.Vector(dx / L, dy / L, 0.0)

        # Plane normal is perpendicular to path_dir in XY (i.e. across the groove).
        cx = (start.x + end_info.x) / 2.0
        cy = (start.y + end_info.y) / 2.0
        cz = (top_z + floor_z) / 2.0

        # Use the full group XY span (all selected faces) when available so the
        # plane covers ramp + flat + any exit ramp even though section_info only
        # describes the ramp cylinder face.  Without this, the flat section that
        # extends past the ramp end would fall outside the plane.
        extent = group_extent if (group_extent is not None and group_extent > L) else L
        depth = abs(top_z - floor_z)
        half = max(extent, depth) + tol.section_overshoot
        z_dir = FreeCAD.Vector(0.0, 0.0, 1.0)
        ctr = FreeCAD.Vector(cx, cy, cz)

        p1 = ctr - half * path_dir - half * z_dir
        p2 = ctr + half * path_dir - half * z_dir
        p3 = ctr + half * path_dir + half * z_dir
        p4 = ctr - half * path_dir + half * z_dir
        plane_face = Part.Face(Part.makePolygon([p1, p2, p3, p4, p1]))

        section = base_obj.Shape.section(plane_face)
        all_edges = section.Edges
        if not all_edges:
            Path.Log.debug("CAM_Flute: section returned no edges\n")
            return []

        Path.Log.debug(
            "CAM_Flute: section returned {} edge(s)\n".format(len(all_edges))
        )

        # --- filter candidates --------------------------------------------------
        def path_proj(v):
            return (v.x - start.x) * path_dir.x + (v.y - start.y) * path_dir.y

        z_tol = max(1.0, abs(top_z - floor_z) * _SECTION_Z_TOL_FRAC)
        p_min = path_proj(start) - tol.section_overshoot
        p_max = path_proj(start) + extent + tol.section_overshoot

        candidates = []
        for edge in all_edges:
            bb = edge.BoundBox
            if bb.ZMax < floor_z - z_tol or bb.ZMin > top_z + z_tol:
                continue
            mid = edge.CenterOfMass
            if path_proj(mid) < p_min or path_proj(mid) > p_max:
                continue
            # Reject near-vertical edges (side walls).
            v0 = edge.Vertexes[0].Point
            v1 = edge.Vertexes[-1].Point
            ds = abs(path_proj(v1) - path_proj(v0))
            dz = abs(v1.z - v0.z)
            if ds < _WALL_DS_MIN and dz > 0.5:
                continue
            if ds > _WALL_DS_MIN and dz / ds > _WALL_SLOPE_MAX:
                continue
            candidates.append(edge)

        if not candidates:
            Path.Log.debug("CAM_Flute: no floor edge candidates\n")
            return []

        Path.Log.debug(
            "CAM_Flute: {} candidate floor edge(s)\n".format(len(candidates))
        )

        # --- chain from start ---------------------------------------------------
        def _orient(edge, toward_pt):
            v0 = edge.Vertexes[0].Point
            v1 = edge.Vertexes[-1].Point
            if _dist2(v0, toward_pt) <= _dist2(v1, toward_pt):
                return v0, v1
            return v1, v0

        remaining = list(candidates)
        best_d, best_e = 1e18, None
        for e in remaining:
            d = min(_dist2(e.Vertexes[0].Point, start), _dist2(e.Vertexes[-1].Point, start))
            if d < best_d:
                best_d, best_e = d, e

        if best_e is None:
            return []

        remaining.remove(best_e)
        cur_s, cur_e = _orient(best_e, start)
        chain = [(cur_s, cur_e, best_e)]

        for _ in range(_CHAIN_MAX_EDGES):
            nxt_e = nxt_s = nxt_end = None
            bd = tol.chain2
            for e in remaining:
                v0 = e.Vertexes[0].Point
                v1 = e.Vertexes[-1].Point
                d0 = _dist2(v0, cur_e)
                d1 = _dist2(v1, cur_e)
                if d0 < bd:
                    bd, nxt_e, nxt_s, nxt_end = d0, e, v0, v1
                elif d1 < bd:
                    bd, nxt_e, nxt_s, nxt_end = d1, e, v1, v0
            if nxt_e is None:
                break
            if nxt_end.z > top_z + z_tol:
                break
            if nxt_end.z < floor_z - z_tol:
                # Deeper than the known groove floor: this is geometry outside
                # the selected group (e.g. an adjacent groove or a step ledge
                # past the tip), not a continuation of this flute's profile.
                break
            remaining.remove(nxt_e)
            chain.append((nxt_s, nxt_end, nxt_e))
            cur_e = nxt_end

        Path.Log.debug("CAM_Flute: chained {} edge(s)\n".format(len(chain)))

        # --- classify each edge -------------------------------------------------
        segments = _classify_chain_segments(chain, path_proj, tol)

        # Snap all floor-level endpoints to the minimum Z found.
        # Two adjacent faces can produce slightly different Z values at their
        # shared edge when sectioned (modeling seam); snapping to the deeper
        # value removes any tiny unwanted Z step in the toolpath.
        if segments:
            floor_z = min(min(s["start"].z, s["end"].z) for s in segments)

            def _snap_z(v):
                return (
                    FreeCAD.Vector(v.x, v.y, floor_z)
                    if abs(v.z - floor_z) < tol.floor_snap
                    else FreeCAD.Vector(v)
                )

            snapped = []
            for seg in segments:
                s = dict(seg)
                s["start"] = _snap_z(seg["start"])
                s["end"] = _snap_z(seg["end"])
                if seg.get("arc_points"):
                    s["arc_points"] = [_snap_z(p) for p in seg["arc_points"]]
                snapped.append(s)
            segments = snapped

        Path.Log.debug(
            "CAM_Flute: segments → {}\n".format(
                [(s["type"], round(s["start"].z, 3), round(s["end"].z, 3)) for s in segments]
            )
        )
        return segments

    except Exception as exc:
        import traceback

        Path.Log.debug(
            "CAM_Flute: _detect_floor_segments error: {}\n{}\n".format(exc, traceback.format_exc())
        )
        return []


def _apply_axial_leave(segments, axial_leave, stock_top_z, tol):
    """Raise the floor Z of all segments by axial_leave and trim the first/last
    ramp/arc entry/exit ends inward proportionally (same angle, less depth)."""
    if not segments or axial_leave <= _PREC:
        return segments

    all_z = [s["start"].z for s in segments] + [s["end"].z for s in segments]
    floor_z = min(all_z)
    total_d = stock_top_z - floor_z
    if total_d <= axial_leave + _PREC:
        return segments

    new_floor_z = floor_z + axial_leave
    frac = axial_leave / total_d

    def _raise(v, ref_z, new_z):
        if abs(v.z - ref_z) < tol.axial_floor:
            return FreeCAD.Vector(v.x, v.y, new_z)
        return FreeCAD.Vector(v)

    result = []
    for seg in segments:
        s = dict(seg)
        s["start"] = _raise(seg["start"], floor_z, new_floor_z)
        s["end"] = _raise(seg["end"], floor_z, new_floor_z)
        if seg.get("arc_points"):
            s["arc_points"] = [_raise(p, floor_z, new_floor_z) for p in seg["arc_points"]]
        result.append(s)

    # Trim entry: move the first segment's far start XY inward by frac.
    first = result[0]
    if abs(first["start"].z - stock_top_z) < tol.axial_floor and first["type"] in ("ramp", "arc"):
        sx = first["start"].x + frac * (first["end"].x - first["start"].x)
        sy = first["start"].y + frac * (first["end"].y - first["start"].y)
        first["start"] = FreeCAD.Vector(sx, sy, stock_top_z)
        if first.get("arc_points"):
            first["arc_points"][0] = FreeCAD.Vector(sx, sy, stock_top_z)

    # Trim exit: move the last segment's far end XY inward by frac.
    last = result[-1]
    if abs(last["end"].z - stock_top_z) < tol.axial_floor and last["type"] in ("ramp", "arc"):
        ex = last["end"].x + frac * (last["start"].x - last["end"].x)
        ey = last["end"].y + frac * (last["start"].y - last["end"].y)
        last["end"] = FreeCAD.Vector(ex, ey, stock_top_z)
        if last.get("arc_points"):
            last["arc_points"][-1] = FreeCAD.Vector(ex, ey, stock_top_z)

    return result


def _rescale_segments_z(segments, stock_top_z, floor_z, op_start_z, op_final_z):
    """Linearly remap segment Z values from [stock_top_z, floor_z] to
    [op_start_z, op_final_z].  Preserves profile shape while honouring the
    Depths tab settings."""
    if abs(stock_top_z - floor_z) < _PREC:
        return segments
    z_range_src = stock_top_z - floor_z
    z_range_dst = op_start_z - op_final_z

    def _remap(v):
        t = (v.z - floor_z) / z_range_src  # 0 = floor, 1 = stock top
        new_z = op_final_z + t * z_range_dst
        return FreeCAD.Vector(v.x, v.y, new_z)

    result = []
    for seg in segments:
        s = dict(seg)
        s["start"] = _remap(seg["start"])
        s["end"] = _remap(seg["end"])
        if seg.get("arc_points"):
            s["arc_points"] = [_remap(p) for p in seg["arc_points"]]
        result.append(s)
    return result


# ---------------------------------------------------------------------------
# Operation class
# ---------------------------------------------------------------------------


class ObjectFlute(PathOp.ObjectOp):
    """Proxy object for the Flute operation.

    A flute is a ramping slot cut – shallow at one end, deeper at the other.
    The cutting path is derived from selected bottom faces:

    - A single face (flat/bull-nose):  centerline found by PCA.
    - Two faces sharing a concave edge (V-bottom):  the shared edge is the
      centerline.
    - Multiple groups (e.g. two V-flutes side-by-side with a ridge between
      them):  the face adjacency graph is analysed so that faces connected
      only by a convex (peak) edge are placed in separate flute groups.

    Multiple passes step down incrementally.  Each intermediate pass starts
    where the ramp first contacts uncut stock so that air-cut time is
    minimised.
    """

    def opFeatures(self, obj):
        return (
            PathOp.FeatureTool
            | PathOp.FeatureDepths
            | PathOp.FeatureFinishDepth
            | PathOp.FeatureHeights
            | PathOp.FeatureStepDown
            | PathOp.FeatureCoolant
            | PathOp.FeatureBaseFaces
            | PathOp.FeatureBaseEdges
            | PathOp.FeatureLinking
        )

    def initOperation(self, obj):
        obj.addProperty(
            "App::PropertyBool",
            "ReverseDirection",
            "Flute",
            QtCore.QT_TRANSLATE_NOOP(
                "App::Property",
                "Reverse the cut direction (enters at the deep end).",
            ),
        )
        obj.addProperty(
            "App::PropertyDistance",
            "AxialStockToLeave",
            "Flute",
            QtCore.QT_TRANSLATE_NOOP(
                "App::Property",
                "Set the stock to leave in the axial (depth) direction.",
            ),
        )
        obj.addProperty(
            "App::PropertyBool",
            "BlindEndCompensation",
            "Flute",
            QtCore.QT_TRANSLATE_NOOP(
                "App::Property",
                "Pull the path end back by the tool radius when the flute "
                "terminates at depth (blind end). Has no effect when the "
                "path ramps back up to stock surface.",
            ),
        )

    def opSetDefaultValues(self, obj, job):
        obj.ReverseDirection = False
        obj.AxialStockToLeave = 0.0
        obj.BlindEndCompensation = False

        d = None
        if job and job.Stock:
            d = PathUtils.guessDepths(job.Stock.Shape, None)

        if d is not None:
            obj.OpFinalDepth.Value = d.final_depth
            obj.OpStartDepth.Value = d.start_depth
        else:
            obj.OpFinalDepth.Value = -10.0
            obj.OpStartDepth.Value = 0.0

    def opApplyPropertyLimits(self, obj):
        # No property range clamping needed for this operation.
        pass

    def opUpdateDepths(self, obj):
        """Auto-populate start/final depths from the face bounding boxes."""
        if not hasattr(obj, "Base") or not obj.Base:
            return

        z_max = None
        z_min = None

        for base, sub_list in obj.Base:
            for sub in sub_list:
                try:
                    bb = base.Shape.getElement(sub).BoundBox
                    z_max = bb.ZMax if z_max is None else max(z_max, bb.ZMax)
                    z_min = bb.ZMin if z_min is None else min(z_min, bb.ZMin)
                except Part.OCCError as err:
                    Path.Log.error(err)

        if z_max is not None:
            obj.OpStartDepth = z_max
        if z_min is not None:
            obj.OpFinalDepth = z_min

    def onChanged(self, obj, prop):
        if prop == "Active" and obj.ViewObject:
            obj.ViewObject.signalChangeIcon()

    def opOnDocumentRestored(self, obj):
        if not hasattr(obj, "BlindEndCompensation"):
            obj.addProperty(
                "App::PropertyBool",
                "BlindEndCompensation",
                "Flute",
                QtCore.QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Pull the path end back by the tool radius when the flute "
                    "terminates at depth (blind end). Has no effect when the "
                    "path ramps back up to stock surface.",
                ),
            )
            obj.BlindEndCompensation = False

    def _emitFluteSegments(
        self,
        obj,
        segments,
        geo_top_z,
        geo_floor_z,
        sub_names,
        op_start_z,
        op_final_z,
        axial_leave,
        finish_d,
        step_down,
        retract_z,
        linking_kwargs,
        tool_pos,
        tol,
    ):
        """Take a segment chain (from face/solid analysis OR a directly
        selected centerline wire) through Z remap, axial-leave, blind-end
        compensation, pass generation, linking, and G-code emission.

        Returns (new_tool_pos, emitted) where emitted is True if any G-code
        was appended to self.commandlist.
        """
        # --- remap Z from geometry to operation Depths tab -------------------
        if abs(geo_top_z - geo_floor_z) > _PREC:
            segments = _rescale_segments_z(segments, geo_top_z, geo_floor_z, op_start_z, op_final_z)

        # --- axial stock to leave ---------------------------------------------
        if axial_leave > _PREC:
            segments = _apply_axial_leave(segments, axial_leave, op_start_z, tol)

        # --- blind end compensation ---------------------------------------------
        # When the path terminates at depth (no exit ramp), pull the last
        # endpoint back by the tool radius so the cutting edge - not the
        # centre - aligns with the groove end.  No effect when the last
        # segment exits back to stock surface.
        if getattr(obj, "BlindEndCompensation", False) and segments:
            last = segments[-1]
            floor_z_seg = min(min(s["start"].z, s["end"].z) for s in segments)
            if abs(last["end"].z - floor_z_seg) < tol.floor_snap:
                try:
                    tool_radius = obj.ToolController.Tool.Diameter.Value / 2.0
                except Exception:
                    tool_radius = 0.0
                if tool_radius > _PREC * 10:
                    dx = last["end"].x - last["start"].x
                    dy = last["end"].y - last["start"].y
                    seg_len = math.sqrt(dx * dx + dy * dy)
                    if seg_len > _PREC * 10:
                        pd = FreeCAD.Vector(dx / seg_len, dy / seg_len, 0.0)
                        s = dict(last)
                        s["end"] = FreeCAD.Vector(
                            last["end"].x - pd.x * tool_radius,
                            last["end"].y - pd.y * tool_radius,
                            last["end"].z,
                        )
                        if last.get("arc_points"):
                            ap = list(last["arc_points"])
                            ap[-1] = FreeCAD.Vector(
                                ap[-1].x - pd.x * tool_radius,
                                ap[-1].y - pd.y * tool_radius,
                                ap[-1].z,
                            )
                            s["arc_points"] = ap
                        segments = segments[:-1] + [s]

        # --- compute passes -------------------------------------------------
        passes = FluteGenerator.generate_passes(
            segments,
            op_start_z,
            step_down,
            finish_depth=finish_d,
            reverse=obj.ReverseDirection,
        )
        if not passes:
            FreeCAD.Console.PrintWarning(
                translate("CAM_Flute", "No passes computed for: {}\n").format(sub_names)
            )
            return tool_pos, False

        first_cut = passes[0][0]
        entry_pos = FreeCAD.Vector(first_cut.x, first_cut.y, obj.SafeHeight.Value)

        if tool_pos is not None:
            linking_kwargs["start_position"] = tool_pos
            linking_kwargs["target_position"] = entry_pos
            self.commandlist.extend(linking.get_linking_moves(**linking_kwargs))

        cmds = FluteGenerator.generate(
            segments,
            op_start_z,
            step_down,
            retract_z,
            self.horizFeed,
            self.vertFeed,
            finish_depth=finish_d,
            reverse=obj.ReverseDirection,
        )

        if not cmds:
            FreeCAD.Console.PrintWarning(
                translate("CAM_Flute", "No path generated for: {}\n").format(sub_names)
            )
            return tool_pos, False

        self.commandlist.extend(cmds)
        last_deep = passes[-1][-1]
        return FreeCAD.Vector(last_deep.x, last_deep.y, retract_z), True

    def opExecute(self, obj):
        """Build the path for all selected flute faces and/or edges."""
        Path.Log.track()

        self.commandlist = []

        if not hasattr(obj, "Base") or not obj.Base:
            FreeCAD.Console.PrintError(
                translate("CAM_Flute", "No base geometry selected for Flute operation.\n")
            )
            return False

        step_down = obj.StepDown.Value
        if step_down <= 0:
            FreeCAD.Console.PrintError(
                translate("CAM_Flute", "StepDown must be greater than zero.\n")
            )
            return False

        # All absolute-distance tolerances used below scale with the Job's
        # configured GeometryTolerance (same property Profile/Deburr/Engrave/
        # Waterline/etc. already use), rather than being fixed mm values.
        geom_tol = self.job.GeometryTolerance.Value if getattr(self, "job", None) else None
        tol = _make_tolerances(geom_tol)

        # Selected subelements can be faces (analysed via solid section) or
        # edges (used directly as the centerline wire, no analysis needed).
        face_tuples = []
        edge_tuples = []
        for base, sub_list in obj.Base:
            for sub in sub_list:
                try:
                    elem = base.Shape.getElement(sub)
                except Part.OCCError as err:
                    Path.Log.error(err)
                    continue
                if elem.ShapeType == "Face":
                    face_tuples.append((elem, sub, base))
                elif elem.ShapeType == "Edge":
                    edge_tuples.append((elem, sub, base))

        if not face_tuples and not edge_tuples:
            FreeCAD.Console.PrintError(
                translate("CAM_Flute", "No valid faces or edges found in base geometry.\n")
            )
            return False

        groups = _group_flutes(face_tuples, tol) if face_tuples else []

        Path.Log.debug(
            "CAM_Flute: {} face(s) -> {} group(s), {} edge(s)\n".format(
                len(face_tuples), len(groups), len(edge_tuples)
            )
        )

        if obj.Comment:
            self.commandlist.append(Path.Command("({})".format(obj.Comment)))
        self.commandlist.append(Path.Command("({})".format(obj.Label)))
        self.commandlist.append(Path.Command("G0", {"Z": obj.ClearanceHeight.Value}))

        solids = []
        if getattr(self, "job", None) and hasattr(self.job, "Model"):
            solids = [b.Shape for b in self.job.Model.Group if hasattr(b, "Shape")]

        linking_kwargs = {
            "start_position": None,
            "target_position": None,
            "heights_clearance": (obj.SafeHeight.Value, obj.ClearanceHeight.Value),
            "solids": None,
            "tool_shape": None,
            "tool_diameter": None,
            "collision_clearance": obj.CollisionClearance.Value,
        }
        strategy = obj.CollisionAvoidanceStrategy
        if strategy == "Clearance Height":
            linking_kwargs["heights_clearance"] = obj.ClearanceHeight.Value
        elif strategy == "Line of Sight":
            linking_kwargs["solids"] = solids
        elif strategy == "Tool Diameter":
            linking_kwargs["solids"] = solids
            linking_kwargs["tool_diameter"] = obj.ToolController.Tool.Diameter.Value
        elif strategy == "Tool Shape":
            linking_kwargs["solids"] = solids
            linking_kwargs["tool_shape"] = obj.ToolController.Tool.BitBody.Shape

        retract_z = (
            obj.ClearanceHeight.Value if strategy == "Clearance Height" else obj.SafeHeight.Value
        )

        op_start_z = obj.StartDepth.Value
        op_final_z = obj.FinalDepth.Value
        axial_leave = getattr(obj, "AxialStockToLeave", None)
        axial_leave = axial_leave.Value if axial_leave is not None else 0.0
        finish_d = getattr(obj, "FinishDepth", None)
        finish_d = finish_d.Value if finish_d is not None else 0.0

        any_path = False
        tool_pos = None

        for group in groups:
            sub_names = [ft[1] for ft in group["faces"]]

            # --- centerline selection ---
            # V-bottom groups (valley edge present) MUST use the valley-edge
            # centerline - it bisects the two faces, unlike either face's own
            # cylinder axis. Only fall back to per-face cylinder analysis for
            # groups with no valley edge (e.g. ramp + flat merged by XY-overlap),
            # where _get_centerline's PCA-on-combined-faces is less accurate
            # than just analysing the ramp cylinder face directly.
            section_info = None
            section_face = None
            section_base = None

            if group.get("valley_edge") is not None:
                section_info = _get_centerline(group, tol)
                section_face = group["faces"][0][0]
                section_base = group["faces"][0][2]
            else:
                for ft in group["faces"]:
                    cyl_info = _analyze_face_cylinder(ft[0])
                    if cyl_info is not None:
                        section_info = cyl_info
                        section_face = ft[0]
                        section_base = ft[2]
                        break

                if section_info is None:
                    section_info = _get_centerline(group, tol)
                    section_face = group["faces"][0][0]
                    section_base = group["faces"][0][2]

            if section_info is None:
                FreeCAD.Console.PrintWarning(
                    translate("CAM_Flute", "Could not determine centerline for: {}\n").format(
                        sub_names
                    )
                )
                continue

            _check_tool_fit(section_info, self.tool)

            geo_top_z = section_info["top_z"]
            geo_floor_z = section_info["end"].z

            Path.Log.debug(
                "CAM_Flute: centerline start=({:.3f},{:.3f},{:.3f}) "
                "end=({:.3f},{:.3f},{:.3f})\n".format(
                    section_info["start"].x,
                    section_info["start"].y,
                    section_info["start"].z,
                    section_info["end"].x,
                    section_info["end"].y,
                    section_info["end"].z,
                )
            )

            # --- profile detection via solid section ---
            # Compute the XY span of ALL faces in the group so the section
            # plane and candidate filter cover ramp + flat + any exit ramp,
            # even though section_info only describes the ramp cylinder face.
            bb_list = [ft[0].BoundBox for ft in group["faces"]]
            group_xy_span = math.sqrt(
                (max(b.XMax for b in bb_list) - min(b.XMin for b in bb_list)) ** 2
                + (max(b.YMax for b in bb_list) - min(b.YMin for b in bb_list)) ** 2
            )
            segments = _detect_floor_segments(
                section_face, section_base, section_info, tol, group_extent=group_xy_span
            )

            if not segments:
                # Fall back to a plain Ramp using the centerline endpoints.
                Path.Log.debug("CAM_Flute: falling back to plain Ramp\n")
                segments = [
                    {
                        "type": "ramp",
                        "start": FreeCAD.Vector(section_info["start"]),
                        "end": FreeCAD.Vector(section_info["end"]),
                        "radius": None,
                        "arc_points": None,
                    }
                ]
            else:
                # Re-derive top/floor Z from the ACTUAL detected segments,
                # not the upstream centerline estimate. section_info's Z
                # range (PCA fallback, or a single face's cylinder axis) can
                # disagree with the real sectioned profile -- e.g. PCA
                # averages points within an end-zone and can land short of
                # the true valley depth. Rescaling against a floor_z that
                # doesn't match the segments' real floor extrapolates the
                # deepest points past the intended depth.
                all_z = [v.z for s in segments for v in (s["start"], s["end"])] + [
                    p.z for s in segments if s.get("arc_points") for p in s["arc_points"]
                ]
                geo_top_z = max(all_z)
                geo_floor_z = min(all_z)

            tool_pos, emitted = self._emitFluteSegments(
                obj,
                segments,
                geo_top_z,
                geo_floor_z,
                sub_names,
                op_start_z,
                op_final_z,
                axial_leave,
                finish_d,
                step_down,
                retract_z,
                linking_kwargs,
                tool_pos,
                tol,
            )
            any_path = any_path or emitted

        # --- edges selected directly as centerline wires --------------------
        # Each connected component of selected edges is its own flute; no
        # face/solid analysis - the wire itself defines the ramp/flat/arc
        # profile (may include straight, arc, and BSpline segments).
        if edge_tuples:
            edge_by_id = {id(e): sub for e, sub, _b in edge_tuples}
            wires = _split_into_wires([e for e, _sub, _b in edge_tuples], tol)
            Path.Log.debug(
                "CAM_Flute: {} edge(s) -> {} wire(s)\n".format(len(edge_tuples), len(wires))
            )
            for wire_edges in wires:
                sub_names = [edge_by_id.get(id(e), "?") for e in wire_edges]
                segments, geo_top_z, geo_floor_z = _segments_from_wire(wire_edges, tol)
                if not segments:
                    continue
                tool_pos, emitted = self._emitFluteSegments(
                    obj,
                    segments,
                    geo_top_z,
                    geo_floor_z,
                    sub_names,
                    op_start_z,
                    op_final_z,
                    axial_leave,
                    finish_d,
                    step_down,
                    retract_z,
                    linking_kwargs,
                    tool_pos,
                    tol,
                )
                any_path = any_path or emitted

        if not any_path:
            self.commandlist.clear()
            return False

        self.commandlist.append(
            Path.Command("G0", {"Z": obj.ClearanceHeight.Value, "F": self.vertRapid})
        )
        return True


# ---------------------------------------------------------------------------
# Module-level API expected by PathOpGui.SetupOperation
# ---------------------------------------------------------------------------


def SetupProperties():
    return [tup[1] for tup in ObjectFlute._propertyDefinitions()]


def Create(name, obj=None, parentJob=None):
    if obj is None:
        obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectFlute(obj, name, parentJob)
    return obj
