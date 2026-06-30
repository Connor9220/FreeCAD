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

_EDGE_TOL       = 1e-4   # geometric coincidence tolerance (mm)
_FLAT_SLOPE     = 0.001  # dZ/ds below this → "flat" segment
_ARC_SEGS       = 16     # discretisation points per arc segment

# Section plane
_SECTION_OVERSHOOT  = 10.0  # mm — extra margin added to each side of the section plane
_SECTION_Z_TOL_FRAC = 0.05  # z_tol = max(1mm, depth * this fraction)

# Edge chaining
_CHAIN_MAX_EDGES = 200        # guard against infinite loop
_CHAIN_TOL2      = 4.0        # squared mm — 2 mm snap distance for vertex matching
_WALL_SLOPE_MAX  = 5.0        # dz/ds above this → discard as a side wall
_WALL_DS_MIN     = 1e-6       # ds below this (vertical) → also discard

# Floor Z snapping (removes seam artifacts at face junctions)
_FLOOR_SNAP_TOL = 0.5         # mm — endpoints within this of floor_z are snapped

# Axial-leave raise / entry-exit trim
_AXIAL_FLOOR_TOL = 0.5        # mm — same snap window used in _apply_axial_leave

# Bounding-box grouping
_BB_OVERLAP_TOL = 1.0         # mm — faces touching within this distance are co-grouped


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

        axis   = surface.Axis
        radius = surface.Radius
        bb     = face.BoundBox

        ax, ay, az = abs(axis.x), abs(axis.y), abs(axis.z)

        if ay >= ax and ay >= az:
            # Groove runs primarily in Y
            cx = (bb.XMin + bb.XMax) / 2.0
            if axis.y < 0:
                # Moving along +axis → Y decreases → deep end = YMin
                p_start = FreeCAD.Vector(cx, bb.YMax, bb.ZMax)
                p_end   = FreeCAD.Vector(cx, bb.YMin, bb.ZMin)
            else:
                # Moving along +axis → Y increases → deep end = YMax
                p_start = FreeCAD.Vector(cx, bb.YMin, bb.ZMax)
                p_end   = FreeCAD.Vector(cx, bb.YMax, bb.ZMin)

        elif ax >= ay and ax >= az:
            # Groove runs primarily in X
            cy = (bb.YMin + bb.YMax) / 2.0
            if axis.x < 0:
                p_start = FreeCAD.Vector(bb.XMax, cy, bb.ZMax)
                p_end   = FreeCAD.Vector(bb.XMin, cy, bb.ZMin)
            else:
                p_start = FreeCAD.Vector(bb.XMin, cy, bb.ZMax)
                p_end   = FreeCAD.Vector(bb.XMax, cy, bb.ZMin)

        else:
            return None  # Z-dominant — not a typical flute orientation

        # Print BoundBox values and computed centerline
        FreeCAD.Console.PrintMessage(
            "CAM_Flute BoundBox:\n"
            "  X: [{:.4f}, {:.4f}]  Y: [{:.4f}, {:.4f}]  Z: [{:.4f}, {:.4f}]\n"
            "  axis=({:.4f},{:.4f},{:.4f})  radius={:.4f}\n"
            "CAM_Flute centerline:\n"
            "  start=({:.4f},{:.4f},{:.4f})  end=({:.4f},{:.4f},{:.4f})\n".format(
                bb.XMin, bb.XMax,
                bb.YMin, bb.YMax,
                bb.ZMin, bb.ZMax,
                axis.x, axis.y, axis.z, radius,
                p_start.x, p_start.y, p_start.z,
                p_end.x,   p_end.y,   p_end.z,
            )
        )

        def _clean(v, tol=1e-7):
            return 0.0 if abs(v) < tol else v

        return {
            "start": p_start,
            "end":   p_end,
            "top_z": _clean(bb.ZMax),
            "width": _clean(2.0 * radius),
        }
    except Exception:
        return None


def _analyze_face_pca(face):
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
    if span < 1e-7:
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

    top_z = max(p.z for p in pts)

    def _clean(v, tol=1e-7):
        return 0.0 if abs(v) < tol else v

    return {
        "start": p_a,
        "end": p_b,
        "top_z": _clean(top_z),
        "width": _clean(max(t_vals) - min(t_vals)),
    }


def _analyze_face(face):
    """Determine the centerline of a single groove face.

    Tries exact cylinder-surface detection first; falls back to edge-
    sampling PCA for BSpline or other surface types.
    """
    result = _analyze_face_cylinder(face)
    if result is not None:
        FreeCAD.Console.PrintLog("CAM_Flute: centerline via cylinder surface (exact)\n")
        return result
    FreeCAD.Console.PrintLog("CAM_Flute: centerline via edge-sampling PCA (fallback)\n")
    return _analyze_face_pca(face)


# ---------------------------------------------------------------------------
# V-bottom (multi-face) grouping helpers
# ---------------------------------------------------------------------------

def _find_shared_edges(face_a, face_b):
    """Return edges that are geometrically coincident between two faces."""
    shared = []
    for ea in face_a.Edges:
        com_a = ea.CenterOfMass
        len_a = ea.Length
        for eb in face_b.Edges:
            if abs(len_a - eb.Length) > _EDGE_TOL:
                continue
            if com_a.distanceToPoint(eb.CenterOfMass) > _EDGE_TOL:
                continue
            # Verify endpoints match (in either order)
            pa0 = ea.Vertexes[0].Point
            pa1 = ea.Vertexes[-1].Point
            pb0 = eb.Vertexes[0].Point
            pb1 = eb.Vertexes[-1].Point
            if (pa0.distanceToPoint(pb0) < _EDGE_TOL and pa1.distanceToPoint(pb1) < _EDGE_TOL) or \
               (pa0.distanceToPoint(pb1) < _EDGE_TOL and pa1.distanceToPoint(pb0) < _EDGE_TOL):
                shared.append(ea)
                break
    return shared


def _face_normal_near(face, pt):
    """Sample the outward normal of a face at or near point pt."""
    try:
        u, v = face.Surface.parameter(pt)
        return face.normalAt(u, v)
    except Exception:
        pass
    try:
        com = face.CenterOfMass
        u, v = face.Surface.parameter(com)
        return face.normalAt(u, v)
    except Exception:
        pass
    try:
        return face.normalAt(0, 0)
    except Exception:
        return None


def _is_valley_edge(edge, face_a, face_b):
    """Return True if the shared edge is a concave (valley / V-pocket bottom).

    Sign test: (n_A × n_B) · edge_tangent > 0  ⟹  concave (pocket/valley).
               (n_A × n_B) · edge_tangent < 0  ⟹  convex  (ridge/peak).

    This is a standard convexity test for adjacent faces at a shared edge.
    For a V-pocket, the face normals diverge, giving a positive cross·tangent.
    For a ridge, they converge, giving a negative result.
    """
    try:
        mid_t = (edge.FirstParameter + edge.LastParameter) / 2.0
        pt = edge.valueAt(mid_t)
        tangent = edge.tangentAt(mid_t)
        if tangent.Length < 1e-10:
            return False
        tangent.normalize()

        n_a = _face_normal_near(face_a, pt)
        n_b = _face_normal_near(face_b, pt)
        if n_a is None or n_b is None:
            return False

        cross = n_a.cross(n_b)
        return cross.dot(tangent) > 0
    except Exception:
        return False


def _group_flutes(face_tuples):
    """Group (face, sub_name, base_obj) tuples into flute groups.

    Primary grouping: faces whose XY bounding boxes overlap or touch (within
    _BB_TOL) are treated as parts of the same groove.  This correctly merges
    ramp + flat faces (which share an edge but are not a concave V-bottom) as
    well as V-groove face pairs.

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
        return (bb_a.XMin <= bb_b.XMax + _BB_OVERLAP_TOL and
                bb_a.XMax >= bb_b.XMin - _BB_OVERLAP_TOL and
                bb_a.YMin <= bb_b.YMax + _BB_OVERLAP_TOL and
                bb_a.YMax >= bb_b.YMin - _BB_OVERLAP_TOL)

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

        # Check for concave (valley) edges within the group — used only for
        # V-bottom two-face centerline detection. The valley boundary between
        # the two faces can be split into several B-Rep edge segments (e.g. a
        # tapered V-groove with a seam partway along); collect ALL of them so
        # the centerline isn't truncated at the first segment found.
        valley_edges = []
        if len(indices) == 2:
            fa, fb = flute_faces[0][0], flute_faces[1][0]
            for edge in _find_shared_edges(fa, fb):
                if _is_valley_edge(edge, fa, fb):
                    valley_edges.append(edge)

        result.append({"faces": flute_faces, "valley_edge": valley_edges or None})

    return result


def _centerline_from_valley_edge(edges, face_tuples):
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
                if chain[-1].distanceToPoint(p0) < _EDGE_TOL:
                    chain.append(p1)
                elif chain[-1].distanceToPoint(p1) < _EDGE_TOL:
                    chain.append(p0)
                elif chain[0].distanceToPoint(p0) < _EDGE_TOL:
                    chain.insert(0, p1)
                elif chain[0].distanceToPoint(p1) < _EDGE_TOL:
                    chain.insert(0, p0)
                else:
                    continue
                remaining.remove(e)
                changed = True
        v0, v1 = chain[0], chain[-1]

    if v0.z < v1.z:
        v0, v1 = v1, v0  # v0 = shallow, v1 = deep

    top_z = max(ft[0].BoundBox.ZMax for ft in face_tuples)

    def _clean(val, tol=1e-7):
        return 0.0 if abs(val) < tol else val

    return {
        "start": FreeCAD.Vector(v0),
        "end": FreeCAD.Vector(v1),
        "top_z": _clean(top_z),
        "width": 0.0,  # computed separately if needed
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

    def _clean(v, tol=1e-7):
        return 0.0 if abs(v) < tol else v

    return {
        "start": p_a,
        "end": p_b,
        "top_z": _clean(top_z),
        "width": _clean(t_max - t_min),
    }


def _get_centerline(group):
    """Return the centerline dict for a flute group (any size)."""
    valley_edge = group.get("valley_edge")
    face_tuples = group["faces"]

    if valley_edge is not None:
        # 2-face V-bottom: the valley edge IS the centerline
        return _centerline_from_valley_edge(valley_edge, face_tuples)
    elif len(face_tuples) == 1:
        # Single flat/bull-nose face: PCA
        return _analyze_face(face_tuples[0][0])
    else:
        # >2 faces with no detected valley edge: run PCA across all faces
        Path.Log.warning(
            "Flute group has {} faces with no detected valley edge; "
            "falling back to combined PCA.\n".format(len(face_tuples))
        )
        return _centerline_from_faces(face_tuples)


# ---------------------------------------------------------------------------
# Profile detection via solid section
# ---------------------------------------------------------------------------

def _detect_floor_segments(face, base_obj, info, group_extent=None):
    """Section base_obj.Shape with a vertical plane through the groove
    centreline and return an ordered list of typed segment dicts.

    Each dict has keys: "type" ("ramp"|"flat"|"arc"), "start" (Vector),
    "end" (Vector), "radius" (float or None), "arc_points" (list or None).

    Returns [] on any failure; the caller falls back to a plain Ramp.
    """
    try:
        start    = info["start"]
        end_info = info["end"]
        top_z    = info["top_z"]
        floor_z  = end_info.z

        dx = end_info.x - start.x
        dy = end_info.y - start.y
        L  = math.sqrt(dx * dx + dy * dy)
        if L < 1e-7:
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
        depth  = abs(top_z - floor_z)
        half   = max(extent, depth) + _SECTION_OVERSHOOT
        z_dir = FreeCAD.Vector(0.0, 0.0, 1.0)
        ctr   = FreeCAD.Vector(cx, cy, cz)

        p1 = ctr - half * path_dir - half * z_dir
        p2 = ctr + half * path_dir - half * z_dir
        p3 = ctr + half * path_dir + half * z_dir
        p4 = ctr - half * path_dir + half * z_dir
        plane_face = Part.Face(Part.makePolygon([p1, p2, p3, p4, p1]))

        section = base_obj.Shape.section(plane_face)
        all_edges = section.Edges
        if not all_edges:
            FreeCAD.Console.PrintMessage("CAM_Flute: section returned no edges\n")
            return []

        FreeCAD.Console.PrintMessage(
            "CAM_Flute: section returned {} edge(s)\n".format(len(all_edges))
        )

        # --- filter candidates --------------------------------------------------
        def path_proj(v):
            return (v.x - start.x) * path_dir.x + (v.y - start.y) * path_dir.y

        z_tol  = max(1.0, abs(top_z - floor_z) * _SECTION_Z_TOL_FRAC)
        p_min  = path_proj(start) - _SECTION_OVERSHOOT
        p_max  = path_proj(start) + extent + _SECTION_OVERSHOOT

        candidates = []
        for edge in all_edges:
            bb  = edge.BoundBox
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
            FreeCAD.Console.PrintMessage("CAM_Flute: no floor edge candidates\n")
            return []

        FreeCAD.Console.PrintMessage(
            "CAM_Flute: {} candidate floor edge(s)\n".format(len(candidates))
        )

        # --- chain from start ---------------------------------------------------
        def _dist2(a, b):
            return (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2

        def _orient(edge, toward_pt):
            v0 = edge.Vertexes[0].Point
            v1 = edge.Vertexes[-1].Point
            if _dist2(v0, toward_pt) <= _dist2(v1, toward_pt):
                return v0, v1
            return v1, v0

        remaining = list(candidates)
        best_d, best_e = 1e18, None
        for e in remaining:
            d = min(_dist2(e.Vertexes[0].Point, start),
                    _dist2(e.Vertexes[-1].Point, start))
            if d < best_d:
                best_d, best_e = d, e

        if best_e is None:
            return []

        remaining.remove(best_e)
        cur_s, cur_e = _orient(best_e, start)
        chain = [(cur_s, cur_e, best_e)]

        for _ in range(_CHAIN_MAX_EDGES):
            nxt_e = nxt_s = nxt_end = None
            bd = _CHAIN_TOL2
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
            remaining.remove(nxt_e)
            chain.append((nxt_s, nxt_end, nxt_e))
            cur_e = nxt_end

        FreeCAD.Console.PrintMessage(
            "CAM_Flute: chained {} edge(s)\n".format(len(chain))
        )

        # --- classify each edge -------------------------------------------------
        segments = []
        for seg_start, seg_end, edge in chain:
            dp = path_proj(seg_end) - path_proj(seg_start)
            dz = seg_end.z - seg_start.z
            slope = (dz / dp) if abs(dp) > 1e-6 else 0.0

            try:
                is_arc = isinstance(edge.Curve, Part.Circle)
            except Exception:
                is_arc = False

            if is_arc:
                seg_type = "arc"
                radius   = edge.Curve.Radius
                raw_pts  = edge.discretize(Number=_ARC_SEGS + 1)
                # Orient so first point is nearest seg_start
                if _dist2(raw_pts[0], seg_start) > _dist2(raw_pts[-1], seg_start):
                    raw_pts = list(reversed(raw_pts))
                arc_pts = raw_pts
            else:
                seg_type = "flat" if abs(slope) < _FLAT_SLOPE else "ramp"
                radius   = None
                arc_pts  = None

            segments.append({
                "type":       seg_type,
                "start":      FreeCAD.Vector(seg_start),
                "end":        FreeCAD.Vector(seg_end),
                "radius":     radius,
                "arc_points": arc_pts,
            })

        # Snap all floor-level endpoints to the minimum Z found.
        # Two adjacent faces can produce slightly different Z values at their
        # shared edge when sectioned (modeling seam); snapping to the deeper
        # value removes any tiny unwanted Z step in the toolpath.
        if segments:
            floor_z = min(
                min(s["start"].z, s["end"].z) for s in segments
            )
            def _snap_z(v):
                return FreeCAD.Vector(v.x, v.y, floor_z) if abs(v.z - floor_z) < _FLOOR_SNAP_TOL else FreeCAD.Vector(v)

            snapped = []
            for seg in segments:
                s = dict(seg)
                s["start"] = _snap_z(seg["start"])
                s["end"]   = _snap_z(seg["end"])
                if seg.get("arc_points"):
                    s["arc_points"] = [_snap_z(p) for p in seg["arc_points"]]
                snapped.append(s)
            segments = snapped

        FreeCAD.Console.PrintMessage(
            "CAM_Flute: segments → {}\n".format(
                [(s["type"], round(s["start"].z, 3), round(s["end"].z, 3))
                 for s in segments]
            )
        )
        return segments

    except Exception as exc:
        import traceback
        FreeCAD.Console.PrintMessage(
            "CAM_Flute: _detect_floor_segments error: {}\n{}\n".format(
                exc, traceback.format_exc()
            )
        )
        return []


def _apply_axial_leave(segments, axial_leave, stock_top_z):
    """Raise the floor Z of all segments by axial_leave and trim the first/last
    ramp/arc entry/exit ends inward proportionally (same angle, less depth)."""
    if not segments or axial_leave <= 1e-7:
        return segments

    all_z   = [s["start"].z for s in segments] + [s["end"].z for s in segments]
    floor_z = min(all_z)
    total_d = stock_top_z - floor_z
    if total_d <= axial_leave + 1e-7:
        return segments

    new_floor_z = floor_z + axial_leave
    frac = axial_leave / total_d

    def _raise(v, ref_z, new_z):
        if abs(v.z - ref_z) < _AXIAL_FLOOR_TOL:
            return FreeCAD.Vector(v.x, v.y, new_z)
        return FreeCAD.Vector(v)

    result = []
    for seg in segments:
        s = dict(seg)
        s["start"] = _raise(seg["start"], floor_z, new_floor_z)
        s["end"]   = _raise(seg["end"],   floor_z, new_floor_z)
        if seg.get("arc_points"):
            s["arc_points"] = [_raise(p, floor_z, new_floor_z) for p in seg["arc_points"]]
        result.append(s)

    # Trim entry: move the first segment's far start XY inward by frac.
    first = result[0]
    if abs(first["start"].z - stock_top_z) < _AXIAL_FLOOR_TOL and first["type"] in ("ramp", "arc"):
        sx = first["start"].x + frac * (first["end"].x - first["start"].x)
        sy = first["start"].y + frac * (first["end"].y - first["start"].y)
        first["start"] = FreeCAD.Vector(sx, sy, stock_top_z)
        if first.get("arc_points"):
            first["arc_points"][0] = FreeCAD.Vector(sx, sy, stock_top_z)

    # Trim exit: move the last segment's far end XY inward by frac.
    last = result[-1]
    if abs(last["end"].z - stock_top_z) < _AXIAL_FLOOR_TOL and last["type"] in ("ramp", "arc"):
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
    if abs(stock_top_z - floor_z) < 1e-7:
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
        s["end"]   = _remap(seg["end"])
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
            | PathOp.FeatureLinking
        )

    def initOperation(self, obj):
        self.propertiesReady = False
        self._initOpProperties(obj)

    def _initOpProperties(self, obj, warn=False):
        self.addNewProps = []

        for prop_type, name, group, tooltip in self._propertyDefinitions():
            if not hasattr(obj, name):
                obj.addProperty(prop_type, name, group, tooltip)
                self.addNewProps.append(name)

        if warn and self.addNewProps:
            msg = translate("CAM_Flute", "New property added to")
            msg += ' "{}": {}'.format(obj.Label, self.addNewProps) + ". "
            msg += translate("CAM_Flute", "Check default value(s).")
            FreeCAD.Console.PrintWarning(msg + "\n")

        self.propertiesReady = True

    @staticmethod
    def _propertyDefinitions():
        return [
            (
                "App::PropertyBool",
                "ReverseDirection",
                "Flute",
                QtCore.QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Reverse the cut direction (enters at the deep end).",
                ),
            ),
            (
                "App::PropertyDistance",
                "AxialStockToLeave",
                "Flute",
                QtCore.QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Set the stock to leave in the axial (depth) direction.",
                ),
            ),
            (
                "App::PropertyBool",
                "BlindEndCompensation",
                "Flute",
                QtCore.QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Pull the path end back by the tool radius when the flute "
                    "terminates at depth (blind end). Has no effect when the "
                    "path ramps back up to stock surface.",
                ),
            ),
        ]

    def opPropertyDefaults(self, obj, job):
        return {
            "ReverseDirection": False,
            "AxialStockToLeave": 0.0,
            "BlindEndCompensation": False,
        }

    def opSetDefaultValues(self, obj, job):
        job = PathUtils.findParentJob(obj)
        self._applyPropertyDefaults(obj, job, self.addNewProps)

        d = None
        if job and job.Stock:
            d = PathUtils.guessDepths(job.Stock.Shape, None)

        if d is not None:
            obj.OpFinalDepth.Value = d.final_depth
            obj.OpStartDepth.Value = d.start_depth
        else:
            obj.OpFinalDepth.Value = -10.0
            obj.OpStartDepth.Value = 0.0

    def _applyPropertyDefaults(self, obj, job, prop_list):
        defaults = self.opPropertyDefaults(obj, job)
        for name in defaults:
            if name in prop_list:
                prop = getattr(obj, name)
                val = defaults[name]
                if hasattr(prop, "Value") and isinstance(val, (int, float)):
                    prop.Value = val
                else:
                    setattr(obj, name, val)

    def opApplyPropertyLimits(self, obj):
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
        self.propertiesReady = False
        job = PathUtils.findParentJob(obj)
        self._initOpProperties(obj, warn=True)
        self._applyPropertyDefaults(obj, job, self.addNewProps)

    def opExecute(self, obj):
        """Build the path for all selected flute faces."""
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

        face_tuples = []
        for base, sub_list in obj.Base:
            for sub in sub_list:
                try:
                    face = base.Shape.getElement(sub)
                    face_tuples.append((face, sub, base))
                except Part.OCCError as err:
                    Path.Log.error(err)

        if not face_tuples:
            FreeCAD.Console.PrintError(
                translate("CAM_Flute", "No valid faces found in base geometry.\n")
            )
            return False

        groups = _group_flutes(face_tuples)

        FreeCAD.Console.PrintMessage(
            "CAM_Flute: {} face(s) → {} group(s)\n".format(len(face_tuples), len(groups))
        )

        if obj.Comment:
            self.commandlist.append(Path.Command("N ({})".format(obj.Comment), {}))
        self.commandlist.append(Path.Command("N ({})".format(obj.Label), {}))
        self.commandlist.append(
            Path.Command("G0", {"Z": obj.ClearanceHeight.Value, "F": self.vertRapid})
        )

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

        retract_z = obj.ClearanceHeight.Value if strategy == "Clearance Height" else obj.SafeHeight.Value

        op_start_z = obj.StartDepth.Value
        op_final_z = obj.FinalDepth.Value
        axial_leave = getattr(obj, "AxialStockToLeave", None)
        axial_leave = axial_leave.Value if axial_leave is not None else 0.0
        finish_d = getattr(obj, "FinishDepth", None)
        finish_d = finish_d.Value if finish_d is not None else 0.0

        any_path = False
        tool_pos  = None

        for group in groups:
            sub_names = [ft[1] for ft in group["faces"]]

            # --- centerline selection ---
            # V-bottom groups (valley edge present) MUST use the valley-edge
            # centerline — it bisects the two faces, unlike either face's own
            # cylinder axis. Only fall back to per-face cylinder analysis for
            # groups with no valley edge (e.g. ramp + flat merged by XY-overlap),
            # where _get_centerline's PCA-on-combined-faces is less accurate
            # than just analysing the ramp cylinder face directly.
            section_info = None
            section_face = None
            section_base = None

            if group.get("valley_edge") is not None:
                section_info = _get_centerline(group)
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
                    section_info = _get_centerline(group)
                    section_face = group["faces"][0][0]
                    section_base = group["faces"][0][2]

            if section_info is None:
                FreeCAD.Console.PrintWarning(
                    translate("CAM_Flute", "Could not determine centerline for: {}\n").format(sub_names)
                )
                continue

            geo_top_z   = section_info["top_z"]
            geo_floor_z = section_info["end"].z

            FreeCAD.Console.PrintMessage(
                "CAM_Flute: centerline start=({:.3f},{:.3f},{:.3f}) "
                "end=({:.3f},{:.3f},{:.3f})\n".format(
                    section_info["start"].x, section_info["start"].y, section_info["start"].z,
                    section_info["end"].x,   section_info["end"].y,   section_info["end"].z,
                )
            )

            # --- profile detection via solid section ---
            # Compute the XY span of ALL faces in the group so the section
            # plane and candidate filter cover ramp + flat + any exit ramp,
            # even though section_info only describes the ramp cylinder face.
            bb_list = [ft[0].BoundBox for ft in group["faces"]]
            group_xy_span = math.sqrt(
                (max(b.XMax for b in bb_list) - min(b.XMin for b in bb_list)) ** 2 +
                (max(b.YMax for b in bb_list) - min(b.YMin for b in bb_list)) ** 2
            )
            segments = _detect_floor_segments(
                section_face, section_base, section_info, group_extent=group_xy_span
            )

            if not segments:
                # Fall back to a plain Ramp using the centerline endpoints.
                FreeCAD.Console.PrintMessage("CAM_Flute: falling back to plain Ramp\n")
                segments = [
                    {
                        "type":       "ramp",
                        "start":      FreeCAD.Vector(centerline["start"]),
                        "end":        FreeCAD.Vector(centerline["end"]),
                        "radius":     None,
                        "arc_points": None,
                    }
                ]

            # --- remap Z from geometry to operation Depths tab ------------------
            if abs(geo_top_z - geo_floor_z) > 1e-7:
                segments = _rescale_segments_z(
                    segments, geo_top_z, geo_floor_z, op_start_z, op_final_z
                )

            # --- axial stock to leave -------------------------------------------
            if axial_leave > 1e-7:
                segments = _apply_axial_leave(segments, axial_leave, op_start_z)

            # --- blind end compensation -----------------------------------------
            # When the path terminates at depth (no exit ramp), pull the last
            # endpoint back by the tool radius so the cutting edge — not the
            # centre — aligns with the groove end.  No effect when the last
            # segment exits back to stock surface.
            if getattr(obj, "BlindEndCompensation", False) and segments:
                last = segments[-1]
                floor_z_seg = min(min(s["start"].z, s["end"].z) for s in segments)
                if abs(last["end"].z - floor_z_seg) < _FLOOR_SNAP_TOL:
                    try:
                        tool_radius = obj.ToolController.Tool.Diameter.Value / 2.0
                    except Exception:
                        tool_radius = 0.0
                    if tool_radius > 1e-6:
                        dx = last["end"].x - last["start"].x
                        dy = last["end"].y - last["start"].y
                        seg_len = math.sqrt(dx * dx + dy * dy)
                        if seg_len > 1e-6:
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
                segments, op_start_z, step_down,
                finish_depth=finish_d,
                reverse=obj.ReverseDirection,
            )
            if not passes:
                FreeCAD.Console.PrintWarning(
                    translate("CAM_Flute", "No passes computed for faces: {}\n").format(sub_names)
                )
                continue

            first_cut = passes[0][0]
            entry_pos = FreeCAD.Vector(first_cut.x, first_cut.y, obj.SafeHeight.Value)

            if tool_pos is not None:
                linking_kwargs["start_position"] = tool_pos
                linking_kwargs["target_position"] = entry_pos
                self.commandlist.extend(linking.get_linking_moves(**linking_kwargs))

            cmds = FluteGenerator.generate(
                segments, op_start_z, step_down, retract_z,
                self.horizFeed, self.vertFeed, self.horizRapid, self.vertRapid,
                finish_depth=finish_d,
                reverse=obj.ReverseDirection,
            )

            if cmds:
                self.commandlist.extend(cmds)
                any_path = True
                last_deep = passes[-1][-1]
                tool_pos  = FreeCAD.Vector(last_deep.x, last_deep.y, retract_z)
            else:
                FreeCAD.Console.PrintWarning(
                    translate("CAM_Flute", "No path generated for faces: {}\n").format(sub_names)
                )

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
