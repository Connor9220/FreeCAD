# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2025 sliptonic sliptonic@freecad.org
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

import Constants
import FreeCAD
import Part
import Path
import Path.Base.Util as PathUtil
from FreeCAD import Vector

if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())


def get_linking_args(obj, job) -> dict | None:
    """
    Build get_linking_moves() arguments from an operation's linking properties
    (CollisionAvoidanceStrategy, CollisionClearance, SafeHeight, ClearanceHeight).
    start_position and target_position are left for the caller.
    Returns None if the operation has no linking properties.
    """
    strategy = getattr(obj, "CollisionAvoidanceStrategy", None)
    if strategy is None:
        return None

    solids = []
    if job and hasattr(job, "Model"):
        solids = [b.Shape for b in job.Model.Group if hasattr(b, "Shape")]
        # The operation generates in its work plane's frame; the model is
        # world geometry. Bring the solids into that frame, or the collision
        # checks read world coordinates as plane-local.
        frame = PathUtil.workplaneForOp(obj)
        if not frame.isIdentity(1e-9):
            matrix = frame.inverse().toMatrix()
            solids = [s.copy().transformShape(matrix, False, False) for s in solids]
    solids = solids + workholding_solids(obj, job)

    tool = obj.ToolController.Tool if getattr(obj, "ToolController", None) else None
    clearance = obj.CollisionClearance.Value

    args = {
        "start_position": None,
        "target_position": None,
        "heights_clearance": (obj.SafeHeight.Value, obj.ClearanceHeight.Value),
        "solids": None,
        "tool_shape": None,
        "tool_diameter": None,
        "collision_clearance": clearance,
        "retract_height_offset": None,
        "split_plunge_height": obj.SafeHeight.Value,
    }
    if strategy == "Clearance Height":
        args["heights_clearance"] = obj.ClearanceHeight.Value
    elif strategy == "Retract Height":
        pass
    elif strategy == "Line of Sight":
        args["retract_height_offset"] = clearance
        args["solids"] = solids
    elif strategy == "Tool Diameter":
        args["retract_height_offset"] = clearance
        args["solids"] = solids
        args["tool_diameter"] = tool.Diameter.Value
    elif strategy == "Tool Shape":
        args["retract_height_offset"] = clearance
        args["solids"] = solids
        args["tool_shape"] = tool.BitBody.Shape

    return args


def workholding_solids(obj, job) -> list:
    """
    The Job's workholding in use (clamps, dogs, rails, vises and what else
    stands on the machine with the part), where it stands, in the operation's
    work plane frame: what linking moves keep clear of besides the model.

    An operation coming in and going out at Clearance Height, or linking at a
    fixed height, sees none of it: said so when the workholding over the stock
    stands above that height.
    """
    if job is None or not hasattr(job, "Workholding"):
        return []
    try:
        import Path.Main.Job as PathJob

        shapes = [s for _, s in PathJob.workholdingParts(job)]
        shapes += [s for _, s in PathJob.workholdingParts(job, cuttable=True)]
    except Exception as e:
        Path.Log.warning(f"Workholding not seen by linking: {e}")
        return []
    if not shapes:
        return []
    frame = PathUtil.workplaneForOp(obj)
    if not frame.isIdentity(1e-9):
        matrix = frame.inverse().toMatrix()
        shapes = [s.copy().transformShape(matrix, False, False) for s in shapes]
    _warn_fixed_height(obj, job, shapes, frame)
    return shapes


def _warn_fixed_height(obj, job, shapes, frame):
    """Said when an operation travels at a fixed height through workholding over
    its stock: at Clearance Height, as it comes in and goes out, whatever its
    strategy; at Safe Height too, linking at Retract Height."""
    if not hasattr(obj, "ClearanceHeight"):
        return
    stock = getattr(job, "Stock", None)
    if stock is None or stock.Shape.isNull():
        return
    footprint = stock.Shape.copy()
    if not frame.isIdentity(1e-9):
        footprint.transformShape(frame.inverse().toMatrix(), False, False)
    footprint = footprint.BoundBox
    tops = [s.BoundBox.ZMax for s in shapes if _overlapXY(s.BoundBox, footprint)]
    if not tops:
        return
    top = max(tops)
    heights = [("Clearance Height", obj.ClearanceHeight.Value)]
    if getattr(obj, "CollisionAvoidanceStrategy", None) == "Retract Height":
        heights.append(("Safe Height", obj.SafeHeight.Value))
    for name, height in heights:
        if top > height + 1e-6:
            Path.Log.warning(
                f"{getattr(obj, 'Label', '')}: travel at {name} ({height:.3f}) passes through "
                f"workholding over the stock, which stands up to {top:.3f}; raise {name} above it"
            )


def _overlapXY(a, b, margin=0.0):
    return (
        a.XMin <= b.XMax + margin
        and b.XMin <= a.XMax + margin
        and a.YMin <= b.YMax + margin
        and b.YMin <= a.YMax + margin
    )


def _obstacles(solids) -> list:
    """The solids to keep clear of, each on its own: a compound or a list of them."""
    if not solids:
        return []
    if not isinstance(solids, (list, tuple)):
        solids = [solids]
    return [s for s in solids if s and not s.isNull()]


def _clear_of(shape, obstacles, collision_clearance) -> bool:
    """Whether shape keeps collision_clearance from every obstacle. One whose box
    the shape's box, grown by the clearance, does not reach is clear without
    measuring: only the obstacles a move comes near are measured."""
    reach = shape.BoundBox
    for obstacle in obstacles:
        box = FreeCAD.BoundBox(obstacle.BoundBox)
        box.enlarge(collision_clearance)
        if not reach.intersect(box):
            continue
        distance = shape.distToShape(obstacle)[0]
        if distance < collision_clearance and not Path.Geom.isRoughly(
            distance, collision_clearance
        ):
            return False
    return True


def get_dressup_linking_moves(
    linking_args: dict,
    start_position: Vector,
    target_position: Vector,
    start_depth: float,
    safe_height: float,
    vert_feed: float | None = None,
) -> list | None:
    """
    Linking moves for travel a dressup adds between two points, using the
    operation's linking arguments (see get_linking_args).

    The collision check sees only the model, not the stock. The operation's own
    links start and end in material it just removed, but a dressup's travel
    (e.g. between a lead-out and the next lead-in) can cross uncut stock, so the
    travel never goes below start_depth plus the operation's retract offset.

    Moves below safe_height are fed with vert_feed, unless vert_feed is None.
    Returns None if no collision-free path was found.
    """
    args = dict(linking_args)
    args["start_position"] = start_position
    args["target_position"] = target_position
    offset = args.get("retract_height_offset")
    if offset is not None:
        minOffset = start_depth + offset - max(start_position.z, target_position.z)
        args["retract_height_offset"] = max(offset, minOffset)
    try:
        cmds = get_linking_moves(**args)
    except RuntimeError as e:
        Path.Log.warning(f"{e}, fallback to safe height")
        return None

    if vert_feed is not None:
        for cmd in cmds:
            param = cmd.Parameters
            if param.get("Z", target_position.z) < safe_height:
                # below safe height move with feed rate, as the operations do
                cmd.Name = "G1"
                param["F"] = vert_feed
                cmd.Parameters = param
    return cmds


def check_collision(
    start_position: Vector,
    target_position: Vector,
    solids: list[Part.Shape] | None = None,
    tool_shape: Part.Shape | None = None,
    tool_diameter: float | None = None,
    collision_clearance: float = 1,
) -> bool:
    """
    Check if a direct move from start to target would collide with solids.
    Returns True if collision detected, False if path is clear.

    For collision detection uses one of the methods below:
    - tool_shape: cross-section of the tool shape (most long computation)
    - tool_diameter: uses horizontal face with width of the tool diameter (middle computation)
    - if no tool_shape and tool_diameter uses simple wire (fast computation)
    """

    if Path.Geom.pointsCoincide(start_position, target_position):
        return False

    obstacles = _obstacles(solids)
    if not obstacles:
        return False

    collision_clearance = max(collision_clearance, 0) or 1

    # Create direct path wire
    wire = Part.Wire([Part.makeLine(start_position, target_position)])

    if tool_shape:
        shape = _create_tool_path_shape(wire, tool_shape)
    elif tool_diameter:
        shape = _create_horizontal_face(wire, tool_diameter)
    else:
        shape = wire

    if not shape:
        return False

    return not _clear_of(shape, obstacles, collision_clearance)


def get_linking_moves(
    start_position: Vector,
    target_position: Vector,
    heights_clearance: list[float],
    tool_shape: Part.Shape | None = None,
    tool_diameter: float | None = None,
    solids: list[Part.Shape] | None = None,
    retract_height_offset: float | None = None,
    skip_if_no_collision: bool = False,
    collision_clearance: float = 1,
    split_plunge_height: float | None = None,
) -> list:
    """
    Generate linking moves from start to target position.

    If skip_if_no_collision is True and the direct path at the current height
    is collision-free, returns empty list (useful for canned drill cycles that
    handle their own retraction).

    For collision detection uses one of the methods below:
    - tool_shape: cross-section of the tool shape (most long computation)
    - tool_diameter: uses horizontal face with width of the tool diameter (middle computation)
    - if no tool_shape and tool_diameter uses simple wire (fast computation)
    """
    if Path.Geom.pointsCoincide(start_position, target_position):
        return []

    # For canned cycles: if we're already at a safe height and can move directly, skip linking
    if skip_if_no_collision and not check_collision(start_position, target_position, solids):
        return []

    if retract_height_offset is not None and retract_height_offset < 0:
        raise ValueError("Retract offset must be positive")

    obstacles = _obstacles(solids)

    # Determine candidate heights
    if isinstance(heights_clearance, (float, int)):
        candidate_heights = {heights_clearance}
    else:
        candidate_heights = set(heights_clearance)
    if retract_height_offset is not None:
        retract_height = max(start_position.z, target_position.z) + retract_height_offset
        candidate_heights.add(retract_height)

    heights = sorted(candidate_heights)

    collision_clearance = max(collision_clearance, 0) or 1

    # Try each height, and last, over whatever stands in the way: a clamp or a
    # vise's jaw can stand above the heights the operation was given
    over = _height_over(
        obstacles, start_position, target_position, tool_shape, tool_diameter, collision_clearance
    )
    if over is not None and over > heights[-1]:
        heights.append(over)
    for i in range(len(heights)):
        plunge_heights = heights[: i + 1]
        if (
            split_plunge_height is not None
            and max(plunge_heights) > split_plunge_height > target_position.z
        ):
            plunge_heights = sorted(plunge_heights + [split_plunge_height])
        wire = make_linking_wire(start_position, target_position, plunge_heights)
        if is_travel_collision_free(
            wire, obstacles, tool_shape, tool_diameter, collision_clearance
        ):
            commands = []
            for e in wire.Edges:
                cmd = Path.Geom.cmdsForEdge(e)[0]
                cmd.Name = "G0"
                cmd.Annotations = Constants.ANNOT_LINKING
                commands.append(cmd)
            return commands

    raise RuntimeError("No collision-free path found between start and target positions")


def _height_over(obstacles, start, target, tool_shape, tool_diameter, collision_clearance):
    """The height a move from start to target keeps collision_clearance over every
    obstacle it passes over, as wide as the tool; None if it passes over none."""
    if not obstacles:
        return None
    half = 0.0
    if tool_shape:
        half = max(tool_shape.BoundBox.XLength, tool_shape.BoundBox.YLength) / 2
    elif tool_diameter:
        half = tool_diameter / 2
    path = FreeCAD.BoundBox(
        min(start.x, target.x),
        min(start.y, target.y),
        0,
        max(start.x, target.x),
        max(start.y, target.y),
        0,
    )
    margin = half + max(collision_clearance, 0)
    tops = [o.BoundBox.ZMax for o in obstacles if _overlapXY(o.BoundBox, path, margin)]
    return max(tops) + (max(collision_clearance, 0) or 1) if tops else None


def make_linking_wire(start: Vector, target: Vector, heights: list) -> Part.Wire:
    """Returns a wire connecting start and target points"""
    top_z = heights[-1]
    p1 = Vector(start.x, start.y, top_z)
    p2 = Vector(target.x, target.y, top_z)
    edges = []

    # Only add retract edge if there's actual movement and p1 not on vertical line with p2
    if not Path.Geom.pointsCoincide(start, p1) and not Path.Geom.pointsCoincide(p1, p2):
        edges.append(Part.makeLine(start, p1))

    # Only add traverse edge if there's actual movement
    if not Path.Geom.pointsCoincide(p1, p2):
        edges.append(Part.makeLine(p1, p2))

    # No edges created
    # Start and target on vertical line
    # Find new top_z and exclude heights which is upper
    if not edges:
        top_z = max(start.z, target.z)
    plunge_heights = reversed([target.z] + [h for h in heights[:-1] if h <= top_z])

    # Only add plunge edge if there's actual movement
    if not Path.Geom.pointsCoincide(p2, target):
        last = p2
        for z in plunge_heights:
            p = Vector(target.x, target.y, z)
            if not Path.Geom.pointsCoincide(p, last):
                edges.append(Part.makeLine(last, p))
                last = p

    return Part.Wire(edges) if edges else Part.Wire([Part.makeLine(start, target)])


def is_travel_collision_free(
    wire: Part.Wire,
    solid: Part.Shape | None,
    tool_shape: Part.Shape | None = None,
    tool_diameter: float | None = None,
    collision_clearance: float = 1,
) -> bool:
    """
    Check if a horizontal edge of wire would not collide with solid, a shape
    or a list of them.
    Returns True if path is clear, False if collision detected.
    """
    obstacles = _obstacles(solid)
    if not obstacles:
        return True

    collision_clearance = max(collision_clearance, 0) or 1

    if tool_shape:
        shape = _create_tool_path_shape(wire, tool_shape)
    elif tool_diameter:
        shape = _create_horizontal_face(wire, tool_diameter)
    else:
        shape = _get_hor_edge(wire)

    if not shape:
        return True

    return _clear_of(shape, obstacles, collision_clearance)


def _create_horizontal_face(wire, width):
    """Return a rectangular horizontal face sweeping the wire's horizontal
    edge laterally by `width` (tool diameter). Used for tool-diameter
    collision checks. Returns None if the wire has no horizontal edge."""
    edge = _get_hor_edge(wire)
    if not edge:
        return None
    direction = edge.Vertexes[1].Point - edge.Vertexes[0].Point
    normal = direction.cross(Vector(0, 0, 1))
    offset = normal.normalize() * width / 2
    e1 = edge.translated(offset)
    e2 = edge.translated(-offset)
    e3 = Part.makeLine(e1.Vertexes[0].Point, e2.Vertexes[0].Point)
    e4 = Part.makeLine(e1.Vertexes[1].Point, e2.Vertexes[1].Point)
    wire = Part.Wire(Part.__sortEdges__([e1, e2, e3, e4]))

    return Part.makeFace(wire)


def _create_tool_path_shape(wire, tool_shape):
    """Return a solid representing the volume swept by the tool's
    cross-section along the wire's horizontal edge. Used for full
    tool-shape collision checks. Returns None if there is no
    horizontal edge or the slice is empty."""
    edge = _get_hor_edge(wire)
    if not edge:
        return None
    p0 = edge.Vertexes[0].Point
    p1 = edge.Vertexes[1].Point
    direction = p1 - p0
    section = tool_shape.slice(direction, 0)
    if not section:
        return None
    section[0].translate(p0)

    return section[0].extrude(direction)


def _get_hor_edge(wire):
    """Returns horizontal edge from wire which connect start and target positions"""
    for e in wire.Edges:
        if Path.Geom.isHorizontal(e):
            return e

    return None
