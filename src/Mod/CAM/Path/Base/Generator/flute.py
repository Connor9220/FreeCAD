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

__title__ = "CAM Flute Generator"
__author__ = "Connor (Billy Huddleston <billy@ivdc.com>)"
__url__ = "https://www.freecad.org"
__doc__ = "Pass and G-code generation for the Flute operation."

import math

import FreeCAD
import Path

# ---------------------------------------------------------------------------
# Core depth-scaling helper
# ---------------------------------------------------------------------------


def _clip_and_scale(pts, f, stock_top_z):
    """Scale a full-depth path to depth fraction f.

    pts: ordered list of FreeCAD.Vector from the FAR (shallow) end to the DEEP
         end.  pts[-1].z is the floor Z; pts[0].z should be stock_top_z.

    At fraction f (0 < f <= 1):
      - Include only the f * total_XY_length closest to the deep end.
      - The new chain-start is forced to stock_top_z.
      - pts[-1] is forced to pass_floor_z = stock_top_z - f*(stock_top_z - floor_z).
      - Intermediate points scale: Z_i = stock_top_z - f*(stock_top_z - Z_i_full).

    Returns a list of FreeCAD.Vectors from shallow (stock_top_z) to deep.
    """
    if not pts or f < 1e-9:
        return []

    n = len(pts)
    floor_z = pts[-1].z
    pass_floor_z = stock_top_z - f * (stock_top_z - floor_z)

    if n == 1:
        return [FreeCAD.Vector(pts[0].x, pts[0].y, pass_floor_z)]

    # Cumulative XY arc lengths from the deep end going backward toward pts[0].
    rev = [0.0] * n
    for i in range(n - 2, -1, -1):
        dx = pts[i].x - pts[i + 1].x
        dy = pts[i].y - pts[i + 1].y
        rev[i] = rev[i + 1] + math.sqrt(dx * dx + dy * dy)

    L_total = rev[0]
    if L_total < 1e-9:
        return [FreeCAD.Vector(pts[-1].x, pts[-1].y, pass_floor_z)]

    target = f * L_total  # XY distance from deep end to include

    result_rev = []  # built deep-end first, reversed at the end
    for i in range(n - 1, -1, -1):
        if rev[i] <= target + 1e-7:
            z_f = stock_top_z - f * (stock_top_z - pts[i].z)
            result_rev.append(FreeCAD.Vector(pts[i].x, pts[i].y, z_f))
        else:
            # Interpolate the boundary point between pts[i+1] and pts[i]
            if result_rev:
                j = i + 1
                seg_len = rev[i] - rev[j]
                if seg_len > 1e-9:
                    t = (target - rev[j]) / seg_len
                    px = pts[j].x + t * (pts[i].x - pts[j].x)
                    py = pts[j].y + t * (pts[i].y - pts[j].y)
                else:
                    px, py = pts[j].x, pts[j].y
            else:
                px, py = pts[-1].x, pts[-1].y
            result_rev.append(FreeCAD.Vector(px, py, stock_top_z))
            break

    if not result_rev:
        return [FreeCAD.Vector(pts[-1].x, pts[-1].y, pass_floor_z)]

    result_rev.reverse()

    # Force exact Z at endpoints
    result_rev[0] = FreeCAD.Vector(result_rev[0].x, result_rev[0].y, stock_top_z)
    result_rev[-1] = FreeCAD.Vector(result_rev[-1].x, result_rev[-1].y, pass_floor_z)

    return result_rev


def _close_xy(a, b, tol=0.5):
    return abs(a.x - b.x) < tol and abs(a.y - b.y) < tol


# ---------------------------------------------------------------------------
# Pass generation  (segment-based generic API)
# ---------------------------------------------------------------------------


def generate_passes(segments, stock_top_z, step_down, finish_depth=0.0, reverse=False):
    """Compute waypoints for each pass of a flute cut.

    segments: ordered list of dicts, each with keys:
        "type"       : "ramp" | "flat" | "arc"
        "start"      : FreeCAD.Vector  (full-depth start of segment)
        "end"        : FreeCAD.Vector  (full-depth end of segment)
        "arc_points" : list of FreeCAD.Vector or None  (for arc segments,
                       precomputed full-depth discretisation from start to end)

    The list must be ordered start-to-end (shallow to deep to shallow).
    Segments before the first "flat" are the entry chain; after the last
    "flat" are the exit chain.

    Returns a list of passes; each pass is a list of FreeCAD.Vectors.
    """
    if not segments:
        return []

    # ---------- split into entry / flat / exit chains -----------------------

    flat_idx = next((i for i, s in enumerate(segments) if s["type"] == "flat"), None)
    last_flat_idx = next(
        (i for i in range(len(segments) - 1, -1, -1) if segments[i]["type"] == "flat"),
        None,
    )

    entry_stop = flat_idx if flat_idx is not None else len(segments)
    entry_segs = segments[:entry_stop]
    exit_segs = segments[last_flat_idx + 1 :] if last_flat_idx is not None else []

    def _chain_to_pts(segs):
        """Flatten segment list into an ordered list of 3D waypoints."""
        pts = []
        for seg in segs:
            ap = seg.get("arc_points")
            if ap:
                for p in ap:
                    if not pts or not _close_xy(pts[-1], p, 1e-4):
                        pts.append(FreeCAD.Vector(p))
            else:
                if not pts:
                    pts.append(FreeCAD.Vector(seg["start"]))
                if not _close_xy(pts[-1], seg["end"], 1e-4):
                    pts.append(FreeCAD.Vector(seg["end"]))
        return pts

    entry_pts = _chain_to_pts(entry_segs)
    exit_pts = _chain_to_pts(exit_segs)

    flat_start = segments[flat_idx]["start"] if flat_idx is not None else None
    flat_end = segments[last_flat_idx]["end"] if last_flat_idx is not None else None

    # Determine floor Z and total depth
    if flat_idx is not None:
        floor_z = segments[flat_idx]["start"].z
    elif entry_pts:
        floor_z = entry_pts[-1].z
    else:
        return []

    total_depth = stock_top_z - floor_z
    if total_depth <= 1e-7:
        return []

    # If no entry at all (flat-only): vertical plunge at flat_start
    if not entry_pts and flat_start is not None:
        entry_pts = [
            FreeCAD.Vector(flat_start.x, flat_start.y, stock_top_z),
            FreeCAD.Vector(flat_start.x, flat_start.y, floor_z),
        ]

    rough_stop = max(0.0, total_depth - max(0.0, finish_depth))

    def _make_pass(depth):
        f = depth / total_depth
        pass_floor_z = stock_top_z - depth
        wps = []

        # Entry
        if entry_pts:
            wps.extend(_clip_and_scale(entry_pts, f, stock_top_z))

        # Flat
        if flat_start is not None and flat_end is not None:
            if not wps or not _close_xy(wps[-1], flat_start):
                wps.append(FreeCAD.Vector(flat_start.x, flat_start.y, pass_floor_z))
            wps.append(FreeCAD.Vector(flat_end.x, flat_end.y, pass_floor_z))

        # Exit (apply _clip_and_scale to reversed exit, then reverse back)
        if exit_pts:
            rev_exit = list(reversed(exit_pts))
            scaled = _clip_and_scale(rev_exit, f, stock_top_z)
            scaled.reverse()
            if scaled:
                start_i = 1 if wps and _close_xy(wps[-1], scaled[0]) else 0
                wps.extend(scaled[start_i:])

        if reverse:
            wps.reverse()

        return wps

    passes = []
    depth = 0.0
    while depth < rough_stop - 1e-7:
        depth = min(depth + step_down, rough_stop)
        passes.append(_make_pass(depth))

    if finish_depth > 1e-7 and total_depth > rough_stop + 1e-7:
        passes.append(_make_pass(total_depth))

    return passes


# ---------------------------------------------------------------------------
# G-code generation
# ---------------------------------------------------------------------------


def generate(
    segments,
    stock_top_z,
    step_down,
    retract_z,
    horiz_feed,
    vert_feed,
    horiz_rapid,
    vert_rapid,
    finish_depth=0.0,
    reverse=False,
):
    """Generate G-code commands for a single flute from a segment list.

    Args:
        segments     - list of segment dicts (see generate_passes)
        stock_top_z  - float, stock surface Z
        step_down    - float, depth per roughing pass (mm, positive)
        retract_z    - float, Z for rapid retract between passes
        horiz_feed   - float, horizontal feed rate
        vert_feed    - float, vertical (plunge) feed rate
        horiz_rapid  - float, horizontal rapid rate
        vert_rapid   - float, vertical rapid rate
        finish_depth - float, depth reserved for finish pass (0 = none)
        reverse      - bool, reverse cut direction
        arc_segments - int, segments per arc (unused here; arcs already discretised)

    Returns a list of Path.Command objects.
    """
    passes = generate_passes(
        segments,
        stock_top_z,
        step_down,
        finish_depth=finish_depth,
        reverse=reverse,
    )
    if not passes:
        return []

    commands = []
    for waypoints in passes:
        if not waypoints:
            continue

        first = waypoints[0]
        commands.append(Path.Command("G0", {"X": first.x, "Y": first.y, "F": horiz_rapid}))
        commands.append(Path.Command("G1", {"Z": first.z, "F": vert_feed}))

        for wp in waypoints[1:]:
            commands.append(Path.Command("G1", {"X": wp.x, "Y": wp.y, "Z": wp.z, "F": horiz_feed}))

        commands.append(Path.Command("G0", {"Z": retract_z, "F": vert_rapid}))

    return commands
