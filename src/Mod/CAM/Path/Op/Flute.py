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

_EDGE_TOL = 1e-4  # geometric coincidence tolerance (mm)


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

    Faces connected by a concave (valley) edge are grouped into one V-bottom
    flute.  Faces connected only by convex (peak) edges remain separate.

    Example: 4 faces A-B-C-D with valley edges (A,B) and (C,D), and a peak
    edge (B,C) → two groups: {A,B} and {C,D}.

    Returns list of dicts:
        {
          'faces':       [(face, sub, base), ...],
          'valley_edge': Part.Edge or None,   # set for 2-face groups only
        }
    """
    n = len(face_tuples)
    if n == 0:
        return []

    # Collect all valley-edge connections: (i, j) → edge  (i < j)
    valley_connections = {}
    for i in range(n):
        for j in range(i + 1, n):
            fa = face_tuples[i][0]
            fb = face_tuples[j][0]
            for edge in _find_shared_edges(fa, fb):
                if _is_valley_edge(edge, fa, fb):
                    valley_connections[(i, j)] = edge
                    break

    # Union-Find to group faces that share valley edges
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

    for i, j in valley_connections:
        _union(i, j)

    # Collect groups indexed by their union root
    groups_map = {}
    for i in range(n):
        groups_map.setdefault(_find(i), []).append(i)

    result = []
    for indices in groups_map.values():
        flute_faces = [face_tuples[k] for k in indices]
        valley_edge = None
        if len(indices) == 2:
            key = (min(indices), max(indices))
            valley_edge = valley_connections.get(key)
        result.append({"faces": flute_faces, "valley_edge": valley_edge})

    return result


def _centerline_from_valley_edge(edge, face_tuples):
    """Get start/end/top_z from a V-bottom valley edge.

    The edge itself is the cutting centerline.  Start = shallower endpoint.
    top_z = highest Z across all face bounding boxes.
    """
    v0 = edge.Vertexes[0].Point
    v1 = edge.Vertexes[-1].Point
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
        ]

    def opPropertyDefaults(self, obj, job):
        return {
            "ReverseDirection": False,
            "AxialStockToLeave": 0.0,
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

        # Collect all selected faces as (face, sub_name, base_obj) tuples
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

        # Group faces into individual flutes using valley-edge detection
        groups = _group_flutes(face_tuples)

        if obj.Comment:
            self.commandlist.append(Path.Command("N ({})".format(obj.Comment), {}))
        self.commandlist.append(Path.Command("N ({})".format(obj.Label), {}))
        self.commandlist.append(
            Path.Command("G0", {"Z": obj.ClearanceHeight.Value, "F": self.vertRapid})
        )

        # Build linking kwargs — mirrors EngraveBase so all strategies work correctly.
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
        # "Retract Height" uses the default (SafeHeight, ClearanceHeight) tuple

        # retract_z for within-flute pass retracts (handled by FluteGenerator)
        if strategy == "Clearance Height":
            retract_z = obj.ClearanceHeight.Value
        else:
            retract_z = obj.SafeHeight.Value

        any_path = False
        tool_pos = None  # tracks tool position after each group for linking

        for group in groups:
            centerline = _get_centerline(group)
            if centerline is None:
                sub_names = [ft[1] for ft in group["faces"]]
                FreeCAD.Console.PrintWarning(
                    translate("CAM_Flute", "Could not determine centerline for faces: {}\n").format(
                        sub_names
                    )
                )
                continue

            # XY from face analysis; Z from the standard Depths tab (exact bounding-box values).
            start_xyz = centerline["start"]
            end_xyz = centerline["end"]
            stock_top_z = obj.StartDepth.Value
            final_z = obj.FinalDepth.Value

            FreeCAD.Console.PrintMessage(
                translate(
                    "CAM_Flute",
                    "Flute centerline: start_xy=({:.4f}, {:.4f}) end_xy=({:.4f}, {:.4f}) "
                    "stock_z={:.4f} final_z={:.4f}\n",
                ).format(
                    start_xyz.x, start_xyz.y,
                    end_xyz.x, end_xyz.y,
                    stock_top_z, final_z,
                )
            )

            end_xyz = FreeCAD.Vector(end_xyz.x, end_xyz.y, final_z)

            # Apply axial stock to leave.
            # At the deep end: raise end Z so the floor isn't cut to full depth.
            # At the shallow end: move the entry XY inward by the same proportion so the
            # tool still enters at the stock surface with no air cut — the offset ramp
            # surface intersects stock_top_z at a point (axial_leave/total_depth) of the
            # way from the shallow end toward the deep end.
            axial_leave = getattr(obj, "AxialStockToLeave", None)
            axial_leave = axial_leave.Value if axial_leave is not None else 0.0
            if axial_leave > 1e-7:
                total_depth_range = stock_top_z - end_xyz.z
                if total_depth_range > axial_leave + 1e-7:
                    frac = axial_leave / total_depth_range
                    start_xyz = FreeCAD.Vector(
                        start_xyz.x + frac * (end_xyz.x - start_xyz.x),
                        start_xyz.y + frac * (end_xyz.y - start_xyz.y),
                        stock_top_z,
                    )
                end_xyz = FreeCAD.Vector(end_xyz.x, end_xyz.y, end_xyz.z + axial_leave)

            finish_d = getattr(obj, "FinishDepth", None)
            finish_d = finish_d.Value if finish_d is not None else 0.0

            # Compute passes first so we know where the first G0 XY lands.
            # That's the correct linking target — it's near the deep end for pass 1,
            # NOT start_xyz (the shallow end), which would send the tool the wrong way.
            passes = FluteGenerator.generate_passes(
                start_xyz, end_xyz, stock_top_z, step_down,
                finish_depth=finish_d, reverse=obj.ReverseDirection,
            )
            if not passes:
                sub_names = [ft[1] for ft in group["faces"]]
                FreeCAD.Console.PrintWarning(
                    translate("CAM_Flute", "No passes computed for faces: {}\n").format(sub_names)
                )
                continue

            # passes[0][0] is the XY the tool rapids to before the first plunge.
            first_cut = passes[0][0]
            entry = FreeCAD.Vector(first_cut.x, first_cut.y, obj.SafeHeight.Value)

            if tool_pos is not None:
                linking_kwargs["start_position"] = tool_pos
                linking_kwargs["target_position"] = entry
                self.commandlist.extend(linking.get_linking_moves(**linking_kwargs))

            cmds = FluteGenerator.generate(
                start_xyz=start_xyz,
                end_xyz=end_xyz,
                stock_top_z=stock_top_z,
                step_down=step_down,
                retract_z=retract_z,
                horiz_feed=self.horizFeed,
                vert_feed=self.vertFeed,
                horiz_rapid=self.horizRapid,
                vert_rapid=self.vertRapid,
                finish_depth=finish_d,
                reverse=obj.ReverseDirection,
            )

            if cmds:
                self.commandlist.extend(cmds)
                any_path = True
                # After the last pass, tool is at retract_z above the deep end.
                tool_pos = FreeCAD.Vector(end_xyz.x, end_xyz.y, retract_z)
            else:
                sub_names = [ft[1] for ft in group["faces"]]
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
