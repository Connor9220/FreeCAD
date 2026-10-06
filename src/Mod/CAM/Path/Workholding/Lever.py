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

"""Lever clamps: a bar pressing on the stock's top with one end, its other end resting on the
table, a riser or a step block, a bolt or stud between them pulling it down. A T-track hold-down
and a machinist's strap clamp are both.

Each is placed by where it presses, X and Y, and its angle round that point seen from above, 0
square to the stock's side it is on; until X and Y are given it is spread along its side as the
other clamps are, pressing Overlap in from the edge. From there its bar is tipped about where it
presses until its other end sits on what it rests on, and the bolt and what is on it follow.

A lever clamp comes from a file of its own in two ways:

- a clamp's file whose VarSet's Kind is Lever: its parts laid out as a HoldDown's are, the
  VarSet's Lever group saying where it presses (ToeContact), where its other end rests on the
  table (HeelContact), the bolt's axis on the bar's top (BoltAxis), and which parts tip with the
  bar (LeverBar), ride on its top at the bolt (LeverRides) or stay in the table's track
  (LeverAnchored);
- a strap clamp kit, a file whose root VarSet's Kind is StrapKit, holding one of each piece of
  a kit, step clamps, step blocks, studs, a T-slot nut, a flange nut, each an App::Part named by
  what it is and holding a VarSet of its sizes. Each clamp picks its step clamp from the kit, the
  step block and its step that bring its heel level with its nose or a hair higher, the shortest
  stud that reaches through the nut.

Either way the clamp in the Job is a group of links to the parts it uses in that one file."""

import json
import math
import os

import FreeCAD
import Part
import Path
import Path.Workholding.Source as PathSource
import Path.Workholding.Vise as PathWorkholding

from FreeCAD import Vector
from Path.Workholding.Common import stockTopUnder, userLength
from Path.Workholding.Constants import (
    BOLT_COLOR,
    LEVER_BOLT_STEP,
    LEVER_EDGE_CLEARANCE,
    LEVER_END_REACH,
    LEVER_HEEL_REST_MAX,
    LEVER_HEEL_REST_MIN,
    LEVER_LEAST_OVERLAP,
    LEVER_LIFT_NOTED,
    LEVER_PROFILE_STEP,
    LEVER_TILT_NOTED,
    LEVER_RISER_LENGTH,
    LEVER_RISER_MARGIN,
    LEVER_RISER_STEP,
    LEVER_SEAT_TOLERANCE,
    LEVER_RISER_THICKNESS,
    LEVER_STUD_ABOVE_NUT,
    RISER_COLOR,
)
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

Lever = "Lever"
StrapKit = "StrapKit"

# which end presses on the stock
Presses = ["Toe", "Heel"]
# what the other end rests on
RestsOn = ["StepBlock", "RiserAndStepBlock", "Riser", "Table"]
# a step block's two ways of standing: on its long side, its steps low, or on its tall end
Poses = ["lying", "standing"]
# a step block chosen for the height
Auto = "Auto"

# the pieces of a strap clamp kit, by the start of their names in its file
KitPieces = {
    "StepClamp": "clamps",
    "StepBlock": "blocks",
    "Stud": "studs",
    "TSlotNut": "tnut",
    "FlangeNut": "nut",
    "CouplingNut": "coupler",
}


def _length(text):
    return FreeCAD.Units.Quantity(text).Value


def _vec(v):
    return [float(v.x), float(v.y), float(v.z)]


def _vector(values):
    return Vector(*values)


# a strap clamp kit's file


def kitIn(doc):
    """kitIn(doc) ... the VarSet of the strap clamp kit doc holds, at its root, whose Kind is
    StrapKit; None if it holds none."""
    for obj in doc.RootObjects:
        if obj.TypeId == "App::VarSet" and getattr(obj, "Kind", None) == StrapKit:
            return obj
    return None


def _pieceOf(container):
    """A kit piece's solid and the VarSet of its sizes, in its App::Part."""
    solid = varset = None
    for obj in getattr(container, "Group", []) or []:
        if obj.TypeId == "App::VarSet":
            varset = varset or obj
        elif solid is None and hasattr(obj, "Shape") and not obj.Shape.isNull():
            solid = obj
    return solid, varset


def _treads(shape, pose):
    """A step block's steps as it stands in pose, one of Poses: turned so its steps rise toward
    +X, its bottom at 0 and its middle on Y 0. The placement doing that, and each step's top as
    (height, its edge toward the taller steps along X, its middle across), lowest first."""
    turn = FreeCAD.Placement()
    if pose == "standing":
        # on its tall end: what ran along X runs up
        turn = FreeCAD.Placement(Vector(), FreeCAD.Rotation(Vector(0, 1, 0), -90))

    def tops(placement):
        posed = shape.copy()
        posed.Placement = placement.multiply(shape.Placement)
        found = []
        for face in posed.Faces:
            if face.Surface.__class__.__name__ != "Plane":
                continue
            u0, u1, v0, v1 = face.ParameterRange
            if face.normalAt((u0 + u1) / 2, (v0 + v1) / 2).z < 0.99:
                continue
            bb = face.BoundBox
            found.append((bb.ZMax, bb))
        return posed.BoundBox, sorted(found, key=lambda t: t[0])

    box, found = tops(turn)
    if len(found) < 2:
        return None
    # the steps rise toward the taller: from the lowest's middle to the highest's
    low, high = found[0][1].Center, found[-1][1].Center
    way = high - low
    angle = math.degrees(math.atan2(way.y, way.x))
    turn = FreeCAD.Placement(Vector(), FreeCAD.Rotation(Vector(0, 0, 1), -angle)).multiply(turn)
    box, found = tops(turn)
    turn = FreeCAD.Placement(
        Vector(-box.Center.x, -box.Center.y, -box.ZMin), FreeCAD.Rotation()
    ).multiply(turn)
    box, found = tops(turn)
    return turn, [(z, bb.XMax, bb.Center.y) for z, bb in found]


def _profile(shape, step=LEVER_PROFILE_STEP):
    """A block's top as it stands, its height every step along X from its least X, its middle
    across: {"x0", "step", "z"}. Teeth of any shape, tipped back or square, as they are."""
    box = shape.BoundBox
    count = int(math.ceil(box.XLength / step)) + 1
    top = [box.ZMin] * count
    for wire in shape.slice(Vector(0, 1, 0), box.Center.y):
        points = wire.discretize(Deflection=step / 4)
        for p, q in zip(points, points[1:]):
            low, high = sorted((p.x, q.x))
            first = max(0, int(math.ceil((low - box.XMin) / step - 1e-9)))
            last = min(count - 1, int(math.floor((high - box.XMin) / step + 1e-9)))
            for i in range(first, last + 1):
                x = box.XMin + i * step
                if high - low < 1e-9:
                    z = max(p.z, q.z)
                else:
                    z = p.z + (q.z - p.z) * (x - p.x) / (q.x - p.x)
                top[i] = max(top[i], z)
    return {"x0": box.XMin, "step": step, "z": [round(z, 4) for z in top]}


# where two of a kit's blocks mesh, by their solids' names and pose: worked out once
_meshCache = {}


def _meshings(low, up, key=None):
    """Where a block upside down seats on another, teeth into teeth, as their tops say: the
    offsets along X of the upper one's middle from the lower one's where it comes down as low
    as it can without meeting the lower one and then bears on it across most of what they
    share, not on one tooth's tip. (offsets, tops, overlaps) as lists: its flat top's height,
    how far along X the two overlap. Kept by key once worked out."""
    if key is not None and key in _meshCache:
        return _meshCache[key]
    import numpy

    lows, ups = numpy.asarray(low["z"]), numpy.asarray(up["z"])
    n, m = len(lows), len(ups)
    step = low["step"]
    tops, bearing = [], []
    for k in range(n + m - 1):
        first, last = max(0, k - m + 1), min(k, n - 1)
        sums = lows[first : last + 1] + ups[k - last : k - first + 1][::-1]
        top = float(sums.max())
        tops.append(top)
        bearing.append(int((sums >= top - 1.5 * step).sum()))
    shifts, seated, overlaps = [], [], []
    for k in range(1, len(tops) - 1):
        if bearing[k] >= 3 and bearing[k] > bearing[k - 1] and bearing[k] >= bearing[k + 1]:
            shifts.append(low["x0"] + up["x0"] + k * step)
            seated.append(tops[k])
            overlaps.append((min(k, n - 1) - max(0, k - m + 1) + 1) * step)
    found = (shifts, seated, overlaps)
    if key is not None:
        _meshCache[key] = found
    return found


def _seats(sizes, pose):
    """A step block's seats as its sizes' VarSet gives them for pose, one of Poses: its Pose
    placement, standing it as _treads does, and its Seats, where a clamp's heel tooth seats in
    that frame. As _treads gives them, the seat's x the heel's end goes over; None if it gives
    none, a block with sawtooth teeth having no flat steps to find."""
    name = pose.capitalize()
    place = getattr(sizes, "Pose" + name, None)
    seats = getattr(sizes, "Seats" + name, None)
    if place is None or not seats:
        return None
    return place, sorted(((p.z, p.x, 0.0) for p in seats), key=lambda t: t[0])


def readKit(doc):
    """readKit(doc) ... what a strap clamp kit's file holds, as a clamp keeps it: each piece's
    solid's name, its label and the sizes placing it takes, by kind. A ValueError if it is no
    kit or misses a piece every clamp needs."""
    kit = kitIn(doc)
    if kit is None:
        raise ValueError(translate("CAM", "%s holds no strap clamp kit") % doc.Label)
    found = {
        "thread": str(getattr(kit, "Thread", "")),
        "name": str(getattr(kit, "KitName", "")),
        "clamps": [],
        "blocks": [],
        "studs": [],
    }
    for container in doc.RootObjects:
        if container.TypeId != "App::Part":
            continue
        kind = next(
            (k for prefix, k in KitPieces.items() if container.Name.startswith(prefix + "_")),
            None,
        )
        if kind is None:
            continue
        solid, sizes = _pieceOf(container)
        if solid is None or sizes is None:
            continue
        piece = {"solid": solid.Name, "label": container.Label}
        if kind == "clamps":
            teeth = int(getattr(sizes, "TeethCount", 0) or 0)
            pitch = getattr(sizes, "HeelPitch", None)
            piece.update(
                toe=_vec(sizes.ToeContact),
                heel=_vec(sizes.HeelTeeth),
                bolt=_vec(sizes.SlotStart),
                boltEnd=_vec(sizes.SlotEnd),
                width=float(sizes.B_Width.Value),
                teeth=teeth * (pitch.Value if pitch is not None else 0.0),
                # a heel with no teeth, a plain slope: on a meshed pair's flat top only
                plain=not bool(getattr(sizes, "HeelToothed", True)),
            )
            # how much of its end rests on a pair's flat top, at least and at most
            for key, name in (("restMin", "HeelRestMin"), ("restMax", "HeelRestMax")):
                rest = getattr(sizes, name, None)
                if rest is not None:
                    piece[key] = float(rest.Value)
            found["clamps"].append(piece)
        elif kind == "blocks":
            piece["volume"] = float(solid.Shape.Volume)
            for pose in Poses:
                treads = _seats(sizes, pose) or _treads(solid.Shape, pose)
                if treads is not None:
                    posed = solid.Shape.copy()
                    posed.Placement = treads[0].multiply(posed.Placement)
                    box = posed.BoundBox
                    piece[pose] = {
                        "place": _placementText(treads[0]),
                        "treads": treads[1],
                        # how tall it stands, and how far it reaches either way along X
                        "height": box.ZMax,
                        "reach": max(-box.XMin, box.XMax),
                        "xmin": box.XMin,
                        "xmax": box.XMax,
                        # its top along X, to mesh it with another teeth into teeth
                        "profile": _profile(posed),
                    }
            found["blocks"].append(piece)
        elif kind == "studs":
            piece["length"] = float(sizes.Length.Value)
            diameter = getattr(sizes, "Diameter", None)
            piece["radius"] = float(diameter.Value) / 2 if diameter is not None else 0.0
            found["studs"].append(piece)
        elif kind == "tnut":
            piece["tongue"] = float(sizes.TongueTop.z)
            found["tnut"] = piece
        elif kind == "nut":
            piece.update(
                height=float(sizes.Height.Value), radius=float(sizes.FlangeDiameter.Value) / 2
            )
            found["nut"] = piece
        elif kind == "coupler":
            piece["length"] = float(sizes.Length.Value)
            # round it, across its corners
            box = solid.Shape.BoundBox
            piece["radius"] = math.hypot(box.XLength, box.YLength) / 2
            found["coupler"] = piece
    found["clamps"].sort(key=lambda p: p["heel"][0])
    found["blocks"].sort(key=lambda p: p["volume"])
    found["studs"].sort(key=lambda p: p["length"])
    missing = [
        name
        for name, have in (
            ("StepClamp", found["clamps"]),
            ("Stud", found["studs"]),
            ("TSlotNut", found.get("tnut")),
            ("FlangeNut", found.get("nut")),
        )
        if not have
    ]
    if missing:
        raise ValueError(
            translate("CAM", "The strap clamp kit %s has no %s") % (doc.Label, ", ".join(missing))
        )
    return found


def _placementText(placement):
    return [_vec(placement.Base), list(placement.Rotation.Q)]


def _placementOf(text):
    return FreeCAD.Placement(_vector(text[0]), FreeCAD.Rotation(*text[1]))


# a lever clamp's own file


def leverIn(doc):
    """leverIn(doc) ... the lever clamp a clamp's own file holds: its outermost container with a
    VarSet whose Kind is Lever, and that VarSet; (None, None) if it holds none."""
    for obj in doc.RootObjects:
        if not obj.hasExtension("App::GeoFeatureGroupExtension"):
            continue
        for varset in getattr(obj, "Group", []) or []:
            if varset.TypeId == "App::VarSet" and getattr(varset, "Kind", None) == Lever:
                return obj, varset
    return None, None


def _readLever(source, varset):
    """What a lever clamp's file says of how it is placed, as a clamp keeps it."""
    missing = [
        name for name in ("ToeContact", "HeelContact", "BoltAxis") if not hasattr(varset, name)
    ]
    if missing:
        raise ValueError(
            translate("CAM", "%s says it is a lever clamp but has no %s")
            % (source.Label, ", ".join(missing))
        )
    roles = {}
    for name, role in (("LeverBar", "Bar"), ("LeverRides", "Rides"), ("LeverAnchored", "Anchored")):
        for part in getattr(varset, name, []) or []:
            roles[part] = role
    width = getattr(varset, "Width", None)
    return {
        "toe": _vec(varset.ToeContact),
        "heel": _vec(varset.HeelContact),
        "bolt": _vec(varset.BoltAxis),
        "width": float(width.Value) if width is not None else 25.0,
        "roles": roles,
    }


# a lever clamp in a Job


class ObjectLever(PathWorkholding.LinkedGroup):
    """A lever clamp of a Job's Workholding: a group placing the parts it links from its file,
    a lever clamp's own or a strap clamp kit, placed again when a setting of it changes."""

    group = "Lever"
    viewProviderName = "ViewProviderClamp"

    def onChanged(self, obj, prop):
        doc = obj.Document
        if doc is None or doc.Restoring or doc.Transacting or getattr(self, "placing", False):
            return
        if prop not in Settings:
            return
        if prop in ("Clamp", "Presses"):
            # pressing as far in as the step clamp chosen, or the end pressing, lets its bolt
            # clear the stock
            self.placing = True
            try:
                obj.Overlap = _overlap(obj, dataOf(obj))
            finally:
                self.placing = False
        job, piece = PathWorkholding.memberOf(obj)
        if piece != obj:
            return
        import Path.Workholding.Items as PathItems

        if doc.Recomputing:
            PathItems.layoutLater(job)
        else:
            PathItems.layout(job)

    def onDocumentRestored(self, obj):
        # placed again when the stock changes: what watches it is loaded with the stops and
        # clamps, which a Job holding only lever clamps would not load until one is moved
        import Path.Workholding.Items  # noqa: F401

        # its file looked for again if it is not found
        PathSource.recoverLater(obj.Document)
        # a kit's clamp offered what its other end may rest on now
        if hasattr(obj, "Clamp") and obj.getEnumerationsOfProperty("RestsOn") != RestsOn:
            self.placing = True
            try:
                current = obj.RestsOn
                obj.RestsOn = list(RestsOn)
                obj.RestsOn = current
            finally:
                self.placing = False


# the settings placing it again when one changes
Settings = (
    "Angle",
    "Presses",
    "RestsOn",
    "RiserThickness",
    "Overlap",
    "Clamp",
    "Block",
    "PressX",
    "PressY",
    "Pinned",
    "BoltFit",
    "BoltLength",
    "BoltAt",
)


def isLever(obj):
    """isLever(obj) ... whether obj is a lever clamp of a Job's Workholding."""
    return isinstance(getattr(obj, "Proxy", None), ObjectLever)


def _add(obj, kind, name, group, tip, value=None, mode=None):
    if not hasattr(obj, name):
        obj.addProperty(kind, name, group, tip)
        if mode is not None:
            obj.setEditorMode(name, mode)
    if value is not None:
        setattr(obj, name, value)


def _addSettings(obj, kit, data):
    """The settings and results of a lever clamp, as its file allows."""
    group = "Lever"
    _add(
        obj,
        "App::PropertyAngle",
        "Angle",
        group,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "Its angle round where it presses, seen from above: 0 square to the stock's side",
        ),
    )
    _add(
        obj,
        "App::PropertyEnumeration",
        "Presses",
        group,
        QT_TRANSLATE_NOOP(
            "App::Property", "The end pressing on the stock: its toe, or its heel for thin stock"
        ),
        Presses,
    )
    _add(
        obj,
        "App::PropertyEnumeration",
        "RestsOn",
        group,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "What its other end rests on: a step block, a step block on a riser, a riser or the table",
        ),
        RestsOn if kit else [r for r in RestsOn if "StepBlock" not in r],
    )
    obj.RestsOn = "StepBlock" if kit else "Table"
    _add(
        obj,
        "App::PropertyLength",
        "RiserThickness",
        group,
        QT_TRANSLATE_NOOP("App::Property", "How thick the riser under its other end is"),
        _length(LEVER_RISER_THICKNESS),
    )
    _add(
        obj,
        "App::PropertyLength",
        "Overlap",
        group,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "How far in from the stock's edge it presses while it is spread along its side",
        ),
        _overlap(obj, data),
    )
    _add(
        obj,
        "App::PropertyDistance",
        "PressX",
        "Placed",
        QT_TRANSLATE_NOOP(
            "App::Property", "Where it presses once placed, from the stock's left along X"
        ),
        mode=["Hidden"],
    )
    _add(
        obj,
        "App::PropertyDistance",
        "PressY",
        "Placed",
        QT_TRANSLATE_NOOP(
            "App::Property", "Where it presses once placed, from the stock's front along Y"
        ),
        mode=["Hidden"],
    )
    if kit:
        _add(
            obj,
            "App::PropertyEnumeration",
            "Clamp",
            group,
            QT_TRANSLATE_NOOP("App::Property", "Its step clamp, of those in the kit"),
            [c["label"] for c in data["clamps"]],
        )
        _add(
            obj,
            "App::PropertyEnumeration",
            "Block",
            group,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Its step block: Auto, the one bringing its heel level, or one of the kit's",
            ),
            [Auto] + [b["label"] for b in data["blocks"]],
        )
        _add(
            obj,
            "App::PropertyLength",
            "BoltAt",
            group,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "How far its bolt is from the end pressing on the stock, along the clamp, within "
                "its slot; 0 for Auto, as near the stock as clears it",
            ),
        )
    if not kit:
        _add(
            obj,
            "App::PropertyBool",
            "BoltFit",
            group,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Cut its bolt to the shortest that clears what is on it, in quarter-inch steps",
            ),
            True,
        )
        _add(
            obj,
            "App::PropertyLength",
            "BoltLength",
            group,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "How long its bolt is cut to: found when cut to fit, else as given; 0 as shipped",
            ),
        )
    # what placing it found, to read
    _add(
        obj,
        "App::PropertyString",
        "Support",
        group,
        QT_TRANSLATE_NOOP("App::Property", "What its other end was found resting on"),
        mode=["ReadOnly"],
    )
    _add(
        obj,
        "App::PropertyAngle",
        "Tilt",
        group,
        QT_TRANSLATE_NOOP(
            "App::Property", "How far its other end is tipped up from level, down when negative"
        ),
        mode=["ReadOnly"],
    )
    if kit:
        _add(
            obj,
            "App::PropertyLength",
            "BoltFound",
            group,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "How far its bolt was put from the end pressing on the stock, along the clamp",
            ),
            mode=["ReadOnly"],
        )
        _add(
            obj,
            "App::PropertyString",
            "Stud",
            group,
            QT_TRANSLATE_NOOP("App::Property", "The stud from the kit reaching through its nut"),
            mode=["ReadOnly"],
        )
    _add(
        obj,
        "App::PropertyString",
        "Note",
        group,
        QT_TRANSLATE_NOOP("App::Property", "Something wrong with how it is placed"),
        mode=["ReadOnly"],
    )


def _lever(data, obj):
    """The clamp's points as it is placed: where it presses at the origin, its other end along
    +X, up +Z; the frame they are given in mapped to it. The points (toe, heel, bolt) and that
    map."""
    clamp = _kitClamp(data, obj)
    toe, heel, bolt = (_vector(clamp[k]) for k in ("toe", "heel", "bolt"))
    if getattr(obj, "Presses", "Toe") == "Heel":
        toe, heel = heel, toe
    way = heel - toe
    turn = FreeCAD.Rotation(Vector(0, 0, 1), math.degrees(math.atan2(way.y, way.x)))
    frame = FreeCAD.Placement(toe, turn).inverse()
    return frame.multVec(toe), frame.multVec(heel), frame.multVec(bolt), frame


def _kitClamp(data, obj):
    """The step clamp chosen of a kit's, or the clamp a lever clamp's own file holds."""
    if data.get("kind") != StrapKit:
        return data
    label = getattr(obj, "Clamp", None)
    return next((c for c in data["clamps"] if c["label"] == label), data["clamps"][0])


def _shankRadius(part, data):
    """The radius of a bolt fixed in the table's track where it passes the stock's side: its
    section halfway between the table and the stock's top, as its file lays it out."""
    sections = part.Shape.slice(Vector(0, 0, 1), data["heel"][2] / 2)
    if not sections:
        return 0.0
    box = Part.makeCompound(sections).BoundBox
    return max(box.XLength, box.YLength) / 2


def _shank(data):
    """The radius of what passes down beside the stock to the table: a kit's stud, the bolt of a
    lever clamp's own file. What sits on the clamp, a nut or a knob, is above the stock and
    clears it."""
    if data.get("kind") == StrapKit:
        return max((s.get("radius", 0.0) for s in data["studs"]), default=0.0)
    return data.get("boltRadius", data.get("radius", 0.0))


def _overlap(obj, data):
    """How far in from the stock's edge it presses when spread along a side: its bolt or stud
    then clear of the stock's side."""
    toe, heel, bolt, _ = _lever(data, obj)
    radius = _shank(data)
    reach = math.hypot(bolt.x, bolt.y) - radius - _length(LEVER_EDGE_CLEARANCE)
    return max(reach, _length(LEVER_LEAST_OVERLAP))


def dataOf(obj):
    """dataOf(obj) ... what the lever clamp keeps of its file, read back."""
    try:
        return json.loads(obj.LeverData)
    except (AttributeError, ValueError):
        return {}


def _setData(obj, data):
    _add(
        obj,
        "App::PropertyString",
        "LeverData",
        "Lever",
        QT_TRANSLATE_NOOP("App::Property", "What it keeps of its file to place it"),
        mode=["Hidden"],
    )
    obj.LeverData = json.dumps(data)


def _link(obj, target, role, name):
    """A link in the clamp to target, taking role in placing it."""
    doc = obj.Document
    link = doc.addObject("App::LinkPython", name)
    link.LinkedObject = target
    _add(
        link,
        "App::PropertyString",
        "LeverRole",
        "Lever",
        QT_TRANSLATE_NOOP("App::Property", "What it is in placing the clamp"),
        role,
        ["Hidden"],
    )
    if FreeCAD.GuiUp:
        import Path.Workholding.Gui.ViewProvider as Gui

        Gui.ViewProviderViseMember(link.ViewObject)
    link.Label = target.Label
    obj.addObject(link)
    return link


def _container(job, label):
    doc = job.Document
    obj = doc.addObject("App::GeometryPython", "Clamp")
    ObjectLever(obj)
    if FreeCAD.GuiUp:
        ObjectLever.viewProvider(obj.ViewObject)
    obj.Label = label
    _add(
        obj,
        "App::PropertyString",
        "Kind",
        "Lever",
        QT_TRANSLATE_NOOP("App::Property", "How it holds the stock"),
        Lever,
        ["ReadOnly"],
    )
    return obj


def addLever(job, path):
    """addLever(job, path) ... a lever clamp put in the Job's Workholding from the file at path,
    a lever clamp's own or a strap clamp kit: its parts linked from it. setClamps places it.
    Returns it."""
    doc, _ = PathSource.openFile(path, job.Document)
    proxy = None
    if kitIn(doc) is not None:
        data = readKit(doc)
        data["kind"] = StrapKit
        # not ending in a number, which FreeCAD counts up for the next one
        named = data["name"] or data["thread"]
        label = (
            translate("CAM", "Strap clamp, %s kit") % named
            if named
            else translate("CAM", "Strap clamp")
        )
        obj = _container(job, label)
        proxy = obj.Proxy
        proxy.placing = True
        try:
            _setData(obj, data)
            _addSettings(obj, True, data)
            clamp = data["clamps"][0]
            _link(obj, doc.getObject(clamp["solid"]), "Clamp", "ClampBar")
            _link(obj, doc.getObject(data["tnut"]["solid"]), "TNut", "ClampTNut")
            _link(obj, doc.getObject(data["studs"][0]["solid"]), "Stud", "ClampStud")
            _link(obj, doc.getObject(data["nut"]["solid"]), "Nut", "ClampNut")
        finally:
            proxy.placing = False
    else:
        source, varset = leverIn(doc)
        if source is None:
            raise ValueError(
                translate(
                    "CAM", "%s holds no lever clamp: a part with a VarSet whose Kind is Lever"
                )
                % os.path.basename(path)
            )
        data = _readLever(source, varset)
        data["kind"] = Lever
        obj = _container(job, source.Label)
        proxy = obj.Proxy
        proxy.placing = True
        try:
            PathWorkholding._copySettings(varset, obj)
            radius = 0.0
            for part in source.Group:
                if part.TypeId == "App::VarSet" or not hasattr(part, "Shape"):
                    continue
                if part.TypeId == "App::Origin" or part.Shape.isNull():
                    continue
                role = data["roles"].get(part.Name, "Bar")
                link = _link(obj, part, role, "ClampLink")
                _add(
                    link,
                    "App::PropertyPlacement",
                    "SourcePlacement",
                    "Lever",
                    QT_TRANSLATE_NOOP("App::Property", "Where it is in its file"),
                    part.Placement,
                    ["Hidden"],
                )
                if role == "Rides":
                    box = part.Shape.BoundBox
                    radius = max(radius, box.XLength / 2, box.YLength / 2)
                elif role == "Anchored":
                    data["boltRadius"] = max(data.get("boltRadius", 0.0), _shankRadius(part, data))
            data["radius"] = radius
            data["table"] = data["heel"][2]
            _setData(obj, data)
            _addSettings(obj, False, data)
        finally:
            proxy.placing = False
    job.Workholding.addObject(obj)
    PathSource.keepSource(obj, path)
    return obj


# placing it


def _linkOf(obj, role):
    return next((o for o in obj.Group if getattr(o, "LeverRole", None) == role), None)


def _retarget(obj, role, solidName, name):
    """The clamp's link of role linked to the kit's solidName, made if it has none; None
    removes it."""
    link = _linkOf(obj, role)
    if solidName is None:
        if link is not None:
            obj.removeObject(link)
            obj.Document.removeObject(link.Name)
        return None
    current = link.LinkedObject if link is not None else None
    if current is not None and current.Name == solidName:
        return link
    target = None
    if current is not None:
        target = current.Document.getObject(solidName)
    if target is None:
        path = getattr(obj, "SourceFile", "")
        if not path or not os.path.exists(path):
            raise ValueError(
                translate("CAM", "%s: its kit's file is not found to change its pieces") % obj.Label
            )
        doc, _ = PathSource.openFile(path, obj.Document)
        target = doc.getObject(solidName)
    if target is None:
        raise ValueError(translate("CAM", "%s: its kit has no %s") % (obj.Label, solidName))
    if link is None:
        return _link(obj, target, role, name)
    link.LinkedObject = target
    link.Label = target.Label
    return link


class _Made:
    """A piece of a lever clamp whose shape placing the clamp makes: a riser under its other end,
    a bolt cut to length."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _cutBolts(obj):
    """The bolts in the table's track cut to length, as the clamp says: cut to fit, the shortest
    reaching past the top of what is on the clamp by a little, in quarter-inch steps; else as
    long as BoltLength, as shipped when 0; never longer than shipped. A bolt cut shorter is shown
    by a trimmed copy, its link hidden."""
    if not hasattr(obj, "BoltFit"):
        return
    rides = [o for o in obj.Group if getattr(o, "LeverRole", None) == "Rides"]
    top = max((Part.getShape(o, "", transform=True).BoundBox.ZMax for o in rides), default=None)
    for link in [o for o in obj.Group if getattr(o, "LeverRole", None) == "Anchored"]:
        shape = Part.getShape(link, "", transform=True)
        box = shape.BoundBox
        full = box.ZLength
        if obj.BoltFit and top is not None:
            step = _length(LEVER_BOLT_STEP)
            need = top + _length(LEVER_STUD_ABOVE_NUT) - box.ZMin
            length = min(math.ceil(need / step - 1e-9) * step, full)
            obj.BoltLength = length
        else:
            length = min(obj.BoltLength.Value or full, full)
        cut = next(
            (
                o
                for o in obj.Group
                if getattr(o, "LeverRole", None) == "BoltCut"
                and getattr(o, "CutFrom", "") == link.Name
            ),
            None,
        )
        if length >= full - 1e-6:
            if cut is not None:
                obj.removeObject(cut)
                obj.Document.removeObject(cut.Name)
            link.Visibility = True
            continue
        if cut is None:
            cut = obj.Document.addObject("Part::FeaturePython", "ClampBoltCut")
            _Made(cut)
            _add(
                cut,
                "App::PropertyString",
                "LeverRole",
                "Lever",
                QT_TRANSLATE_NOOP("App::Property", "What it is in placing the clamp"),
                "BoltCut",
                ["Hidden"],
            )
            _add(
                cut,
                "App::PropertyString",
                "CutFrom",
                "Lever",
                QT_TRANSLATE_NOOP("App::Property", "The bolt it is cut from"),
                link.Name,
                ["Hidden"],
            )
            cut.Label = translate("CAM", "%s, cut") % link.Label
            if FreeCAD.GuiUp:
                import Path.Workholding.Gui.ViewProvider as Gui

                Gui.ViewProviderViseMember(cut.ViewObject)
                cut.ViewObject.ShapeColor = BOLT_COLOR
            obj.addObject(cut)
        keep = Part.makeBox(
            box.XLength + 2, box.YLength + 2, length, Vector(box.XMin - 1, box.YMin - 1, box.ZMin)
        )
        cut.Shape = shape.common(keep)
        link.Visibility = False


def _riser(obj, wanted):
    """The clamp's riser, a plain block, made if wanted and it has none; taken away if not."""
    riser = next((o for o in obj.Group if getattr(o, "LeverRole", None) == "Riser"), None)
    if not wanted:
        if riser is not None:
            obj.removeObject(riser)
            obj.Document.removeObject(riser.Name)
        return None
    if riser is None:
        riser = obj.Document.addObject("Part::FeaturePython", "ClampRiser")
        _Made(riser)
        _add(
            riser,
            "App::PropertyString",
            "LeverRole",
            "Lever",
            QT_TRANSLATE_NOOP("App::Property", "What it is in placing the clamp"),
            "Riser",
            ["Hidden"],
        )
        riser.Label = translate("CAM", "Riser")
        if FreeCAD.GuiUp:
            import Path.Workholding.Gui.ViewProvider as Gui

            Gui.ViewProviderViseMember(riser.ViewObject)
            riser.ViewObject.ShapeColor = RISER_COLOR
        obj.addObject(riser)
    return riser


def _floorUnder(job, obj, heel, table):
    """How high, in the clamp's frame, what its other end stands on is: the table, at table, or
    the top of another piece of the workholding under it, a rail or a block, up to the stock's
    top."""
    import Path.Main.Job as PathJob

    reach = _length(LEVER_END_REACH)
    column = Part.makeBox(2 * reach, 2 * reach, -table, Vector(heel.x - reach, -reach, table))
    column.Placement = obj.Placement.multiply(column.Placement)
    floor = table
    for part, shape in PathJob.workholdingParts(job, cuttable=None):
        if not shape.BoundBox.intersect(column.BoundBox):
            continue
        if part == obj or PathWorkholding.memberOf(part)[1] == obj:
            continue
        common = shape.common(column)
        if common.isNull() or not common.Solids:
            continue
        floor = max(floor, common.BoundBox.ZMax - obj.Placement.Base.z)
    return floor


def _tipping(heel, rise):
    """How far the clamp is tipped about where it presses for its other end, heel, to stand
    rise above where it presses: the turn and its angle up from level, and whether it reaches."""
    reach = heel.Length
    if reach < 1e-9:
        return FreeCAD.Rotation(), 0.0, True
    level = math.degrees(math.atan2(heel.z, math.hypot(heel.x, heel.y)))
    ratio = rise / reach
    reaches = abs(ratio) <= 0.95
    ratio = max(-0.95, min(0.95, ratio))
    tilt = math.degrees(math.asin(ratio))
    return FreeCAD.Rotation(Vector(0, 1, 0), -(tilt - level)), tilt, reaches


def _blockFor(data, obj, height, room=None):
    """The step block, the way it stands and the step its heel goes on, as the clamp says: of
    those that reach height and leave room past the stud, the step nearest above it, the
    smallest block of those. Two meshed teeth into teeth, one standing as it does, the other
    upside down on it, the heel on its flat top, the pair's highest, the pair nearest above
    height: for a clamp whose heel has no teeth, always, a single block's steps giving it
    nothing flat to stand on; for Auto, when no block reaches, or none that reaches leaves room
    past the stud. Never a bigger block on a smaller one. When nothing reaches, the highest. (block, pose, tread,
    reaches, meshed): meshed, for a pair, (the block under, -, how high the top is, -, the upper
    one's middle along X from the lower one's); None for one block."""
    wanted = getattr(obj, "Block", Auto)
    plain = _kitClamp(data, obj).get("plain", False)
    found = []
    for block in data["blocks"]:
        if wanted != Auto and block["label"] != wanted:
            continue
        for pose in Poses:
            for tread in block.get(pose, {}).get("treads", []):
                found.append((block, pose, tread))
    if not found:
        return None
    tallest = max(found, key=lambda f: f[2][0]) + (False, None)
    single = None
    if not plain:
        above = [f for f in found if f[2][0] >= height - 1e-6]
        # a step clamp's heel meshes with a block's teeth standing on end: lying only when no
        # block standing reaches
        standing = [f for f in above if f[1] == "standing"]
        above = standing or above
        # those whose lower steps, reaching back toward the work, stop short of the stud
        fits = above
        if room is not None:
            fits = [f for f in above if f[2][1] + f[0][f[1]].get("reach", 0.0) <= room + 1e-6]
        nearest = lambda f: (round(f[2][0] - height, 6), f[0]["volume"])
        if fits:
            return min(fits, key=nearest) + (True, None)
        if above:
            # reaching, but meeting the stud: a pair, if one fits, before it
            single = min(above, key=nearest) + (True, None)
        if wanted != Auto:
            return single or tallest
    # teeth into teeth: the upper one upside down on the lower one, both standing the same way so
    # their teeth match, sitting where they mesh; at least half the shorter one over the other,
    # a column, not two blocks barely touching; the upper one clear of the table, and never
    # bigger than the lower one
    pairs = []
    for lower in data["blocks"]:
        for upper in data["blocks"]:
            if wanted != Auto and not (lower["label"] == upper["label"] == wanted):
                continue
            if upper["volume"] > lower["volume"] + 1e-6:
                continue
            for pose in Poses:
                low, up = lower.get(pose), upper.get(pose)
                if not low or not up or "profile" not in low or "profile" not in up:
                    continue
                tall = up.get("height", up["treads"][-1][0])
                shorter = min(len(low["profile"]["z"]), len(up["profile"]["z"]))
                shorter *= low["profile"]["step"]
                key = (lower["solid"], upper["solid"], pose, len(low["profile"]["z"]))
                shifts, tops, overlaps = _meshings(low["profile"], up["profile"], key)
                # of the offsets standing clear of the table with half the shorter one over the
                # other, its flat top the pair's highest, the lower one's steps nowhere above it
                # to meet the bar: the one nearest above height, else the highest
                usable = [
                    k
                    for k in range(len(tops))
                    if tops[k] - tall >= -1e-6
                    and 2 * overlaps[k] >= shorter
                    and tops[k] >= low.get("height", 0.0) - LEVER_SEAT_TOLERANCE
                ]
                if not usable:
                    continue
                over = [k for k in usable if tops[k] >= height - 1e-6]
                k = min(over, key=lambda k: tops[k]) if over else max(usable, key=lambda k: tops[k])
                meshed = (lower, None, tops[k], None, shifts[k])
                pairs.append(
                    (
                        tops[k],
                        lower["volume"] + upper["volume"],
                        (upper, pose, up["treads"][-1], meshed),
                    )
                )
    reaching = [p for p in pairs if p[0] >= height - 1e-6]
    if reaching:
        best = min(reaching, key=lambda p: (round(p[0] - height, 6), p[1]))
        return best[2][:3] + (True, best[2][3])
    if single is not None:
        return single
    if pairs:
        best = max(pairs, key=lambda p: (round(p[0], 6), -p[1]))
        if plain or best[0] > tallest[2][0] + 1e-6:
            return best[2][:3] + (False, best[2][3])
    return tallest


def _pairPlan(data, obj, chosen, heel, bolt, rise):
    """Where the meshed pair of step blocks chosen goes under the clamp's other end, along the
    bar before it is tipped, the lower one's middle at 0: the way round about Z, the upper one's
    middle, the pair's edge nearest the work, where on the bar it bears first and where that is
    along the pair, and what is said of it: on its top's edge nearest the work, or tipped down,
    at the bar's end or the top's far edge. The bar's last HeelRestMin to
    HeelRestMax rests on its top, the middle of that when it may: less to clear the stud at
    bolt, or to keep the support farther from it than where the clamp presses, which would press
    less than half as hard as the stud pulls; and never bearing out past the lower one's base,
    where the pair would tip. First the way round putting the upper one's thick back under the
    heel, not its thin point, the lower one's steps toward the work under the bar as it tips
    up by rise over its length."""
    clamp = _kitClamp(data, obj)
    upper, pose, _, _, meshed = chosen
    lower, shift = meshed[0], meshed[4]
    # the upper one's edge over the lower one's, a column, as near as this
    slack = LEVER_SEAT_TOLERANCE
    least = clamp.get("restMin", _length(LEVER_HEEL_REST_MIN))
    most = max(least, clamp.get("restMax", _length(LEVER_HEEL_REST_MAX)))
    # the flat of the bar's underside ends at a plain heel's end, at a toothed one's first step
    end = heel.x + (clamp.get("teeth", 0.0) if clamp.get("plain") else 0.0)
    stud = bolt + _shank(data)

    def span(posed):
        reach = posed.get("reach", posed["treads"][-1][1])
        return posed.get("xmin", -reach), posed.get("xmax", reach)

    upLo, upHi = span(upper[pose])
    lowLo, lowHi = span(lower[pose])
    # the lower one's top along the pair, either way round; the bar over it rising toward its
    # end from where it bears on the upper one's flat top
    profile = lower[pose].get("profile")
    slope = max(0.0, rise) / heel.x
    if profile:
        import numpy

        heights = numpy.asarray(profile["z"])
        along = profile["x0"] + profile["step"] * numpy.arange(len(heights))

    def clash(way, near):
        if not profile:
            return 0.0
        x = along if way > 0 else -along
        under = x < near
        if not under.any():
            return 0.0
        return float((heights[under] - (meshed[2] - (near - x[under]) * slope)).max())

    plans = []
    for way in (1, -1):
        # the upper one upside down, end for end; the pair turned about Z for the other way
        if way > 0:
            top, base = (shift - upHi, shift - upLo), (lowLo, lowHi)
        else:
            top, base = (upLo - shift, upHi - shift), (-lowHi, -lowLo)
        edge = min(top[0], base[0])
        # bearing first on its top's edge, over the lower one's base, not out past it
        tips = top[0] < base[0] - slack
        # the lower one's steps toward the work up into the bar
        meets = clash(way, top[0]) > LEVER_SEAT_TOLERANCE
        # the pair's edge clear of the stud
        clear = end - stud + edge - top[0]
        # the support farther from the stud than where it presses
        strong = end - 2 * bolt
        # bearing no farther out than the lower one's base
        inside = base[1] + slack - top[0] if top[1] > base[1] + slack else math.inf
        # less than the least rather than into the stud, or the stock past it
        rest = max(min(least, max(clear, 0.0)), min((least + most) / 2, clear, strong, inside))
        bad = tips or meets or clear < least - 1e-6 or inside < least - 1e-6
        weak = strong < least - 1e-6
        plans.append(((bad, weak), tips, weak, way, top, edge, rest))
    _, tips, weak, way, top, edge, rest = min(plans, key=lambda p: p[0])
    notes = []
    if tips:
        notes.append(translate("CAM", "the pair of step blocks tips under the heel"))
    # nothing of it on them at all is said once the stud is placed
    if 1e-6 < rest < least - 1e-6:
        notes.append(
            translate(
                "CAM",
                "only %s of its end rests on the step blocks, clear of the stud, %s at least: use a "
                "longer clamp, or put the bolt nearer the work",
            )
            % (userLength(rest), userLength(least))
        )
    if weak:
        notes.append(
            translate(
                "CAM",
                "its step blocks are nearer the stud than where it presses: it presses less than "
                "half as hard as the stud pulls; put the bolt nearer the work",
            )
        )
    # tipped down, the bar bears first at its end, or at the top's far edge short of it
    bears = min(rest, top[1] - top[0]) if rise < 0 else 0.0
    return dict(
        way=way,
        upper=way * shift,
        near=top[0] + bears,
        edge=edge,
        contact=end - rest + bears,
        notes=notes,
    )


def _NO_ROOM():
    return translate(
        "CAM",
        "its step blocks meet its stud, no room between it and the heel: use a longer clamp, or "
        "put the bolt nearer the work",
    )


def _studsFor(data, need):
    """The kit's shortest stud reaching need, (stud, None); else, with a coupling nut in the kit,
    the two whose lengths together reach it least past it, the longer below, (lower, upper);
    (None, None) when nothing reaches."""
    studs = data["studs"]
    one = next((s for s in studs if s["length"] >= need - 1e-6), None)
    if one is not None:
        return one, None
    if data.get("coupler") is None:
        return None, None
    pairs = [
        (a["length"] + b["length"], a, b)
        for i, a in enumerate(studs)
        for b in studs[i:]
        if a["length"] + b["length"] >= need - 1e-6
    ]
    if not pairs:
        return None, None
    _, a, b = min(pairs, key=lambda p: (p[0], abs(p[1]["length"] - p[2]["length"])))
    return (b, a) if b["length"] >= a["length"] else (a, b)


def place(job, obj, press, outward):
    """place(job, obj, press, outward) ... the lever clamp obj placed pressing on the stock's
    top at press, a point in the Job, its other end out along outward, a direction across the
    table, turned by its Angle from there: tipped about press until that end rests on what it
    rests on, the rest following. What placing it found is put in its results."""
    data = dataOf(obj)
    if not data:
        return
    proxy = obj.Proxy
    proxy.placing = True
    try:
        _place(job, obj, data, press, outward)
    finally:
        proxy.placing = False


def _place(job, obj, data, press, outward):
    box = job.Stock.Shape.BoundBox
    kit = data.get("kind") == StrapKit
    notes = []

    toe, heel, bolt, frame = _lever(data, obj)

    angle = math.degrees(math.atan2(outward.y, outward.x)) + obj.Angle.Value
    turn = FreeCAD.Rotation(Vector(0, 0, 1), angle)
    # pressing on the stock's top where its end is, across its width, not on the highest of a
    # model's features elsewhere
    half = _kitClamp(data, obj).get("width", data.get("width", 25.0)) / 2
    reach = _length(LEVER_LEAST_OVERLAP)
    top = stockTopUnder(job, FreeCAD.Placement(press, turn), (-reach, -half), (reach, half))
    height = top - box.ZMin
    press = Vector(press.x, press.y, top)
    table = -height
    obj.Placement = FreeCAD.Placement(press, turn)

    # what its other end rests on, how high above the table: on the table, or on top of another
    # piece of the workholding there, a rail or a block, its floor
    restsOn = getattr(obj, "RestsOn", "Table")
    floor = _floorUnder(job, obj, heel, table) - table
    support = floor
    chosen = None
    # a riser under its step block, as thick as RiserThickness
    under = obj.RiserThickness.Value if restsOn == "RiserAndStepBlock" else 0.0
    if restsOn == "Riser":
        support = floor + obj.RiserThickness.Value
    elif restsOn in ("StepBlock", "RiserAndStepBlock") and kit:
        # the room from the heel back to the stud, the bolt as near the work as it may go
        room = None
        boltNear = bolt.x
        clear = _studClear(job, obj, data)
        end = _kitClamp(data, obj).get("boltEnd")
        if end is not None:
            nearest = min(bolt.x, frame.multVec(_vector(end)).x)
            boltNear = max(nearest, clear if clear is not None else nearest)
            room = heel.x - boltNear - _shank(data)
        chosen = _blockFor(data, obj, height - floor - under, room)
        if restsOn == "StepBlock" and chosen is not None and not chosen[3]:
            # nothing in the kit reaching, a riser under it as thin as lets one reach
            step = _length(LEVER_RISER_STEP)
            thick = step
            while thick < height - floor:
                taller = _blockFor(data, obj, height - floor - thick, room)
                if taller is not None and taller[3]:
                    chosen, under = taller, thick
                    break
                thick += step
        if chosen is None:
            notes.append(translate("CAM", "the kit has no step block"))
        else:
            meshed = chosen[4]
            support = floor + under + (meshed[2] if meshed else chosen[2][0])
            if not chosen[3]:
                notes.append(
                    translate(
                        "CAM", "no step block in the kit reaches the stock's top: its heel is low"
                    )
                )

    # a pair of step blocks: the bar bears first on its top's edge nearest the work, tipped
    # about there, not about its heel
    pivot, pair = heel, None
    if kit and chosen is not None and chosen[4] and heel.x > 1e-9:
        pair = _pairPlan(data, obj, chosen, heel, boltNear, support - height)
        notes.extend(pair["notes"])
        pivot = heel * (pair["contact"] / heel.x)
    if kit:
        _retarget(obj, "Clamp", _kitClamp(data, obj)["solid"], "ClampBar")
    bars = _barShapes(obj, data, frame)
    stock = None
    if bars:
        stock = job.Stock.Shape.copy()
        stock.Placement = obj.Placement.inverse().multiply(stock.Placement)
    # tipped until its other end stands on what it rests on; a round end meets it lower or
    # higher than the point its file gives as the bar tips, so tipped again by what is left
    rise = support - height
    for _ in range(4):
        turn, tilt, reaches = _tipping(pivot, rise)
        tipped = FreeCAD.Placement(Vector(), turn)
        heelAt = turn.multVec(heel)
        pivotAt = turn.multVec(pivot)
        # a bar meeting the stock's edge rests on it, tipped about its other end until it is
        # clear: where it was to press is then lifted off the stock
        if bars:
            lift = _clearing(bars, stock, tipped, pivotAt)
            if lift > 0:
                tipped = _about(pivotAt, lift).multiply(tipped)
                tilt -= lift
        if kit or not bars:
            break
        low = _lowest(bars, tipped, heelAt)
        off = low - (table + support)
        if abs(off) < 0.01:
            break
        rise -= off
    # its heel's teeth into one step block's: the block slid less than a tooth, the bar then
    # tipped to just touch it
    seat = 0.0
    if bars and chosen is not None and not chosen[4] and "profile" in chosen[0][chosen[1]]:
        block, pose, tread = chosen[0], chosen[1], chosen[2]
        for _ in range(3):
            seat, lift = _heelSeat(
                bars, tipped, block, pose, heelAt.x - tread[1], table + floor + under
            )
            if abs(lift) < LEVER_SEAT_TOLERANCE:
                break
            rise += lift
            turn, tilt, reaches = _tipping(heel, rise)
            tipped = FreeCAD.Placement(Vector(), turn)
            heelAt = turn.multVec(heel)
            lift = _clearing(bars, stock, tipped, heelAt)
            if lift > 0:
                tipped = _about(heelAt, lift).multiply(tipped)
                tilt -= lift
    if not reaches:
        notes.append(translate("CAM", "it cannot reach down or up that far"))
    if bars and tipped.multVec(toe).z > _length(LEVER_LIFT_NOTED):
        notes.append(
            translate(
                "CAM",
                "it rests on the stock's edge, where it was to press %s up: raise its other end",
            )
            % userLength(tipped.multVec(toe).z)
        )
    # the stock its file says it is made for, pressing as it is laid out
    low, high = getattr(obj, "MinStockThickness", None), getattr(obj, "MaxStockThickness", None)
    if getattr(obj, "Presses", "Toe") == "Toe" and low is not None and high is not None:
        thick = height - support
        if thick > high.Value + 1e-6:
            notes.append(
                translate(
                    "CAM", "the stock is thicker than it is made for, %s at most: use a riser"
                )
                % high.UserString
            )
        elif thick < low.Value - 1e-6:
            notes.append(
                translate("CAM", "the stock is thinner than it is made for, %s at least")
                % low.UserString
            )
    if kit:
        # too tall for one stud: the coupling nut joining two, wider than the stud, kept clear
        radius = _shank(data)
        coupler = data.get("coupler")
        if coupler is not None:
            bottom = table - data["tnut"]["tongue"]
            need = tipped.multVec(bolt).z + data["nut"]["height"] + _length(LEVER_STUD_ABOVE_NUT)
            if _studsFor(data, need - bottom)[1] is not None:
                radius = max(radius, coupler.get("radius", 2 * radius))
        bolt = _studInSlot(job, obj, data, frame, bolt, notes, radius)
        if hasattr(obj, "BoltFound"):
            obj.BoltFound = abs(bolt.x)
    boltAt = tipped.multVec(bolt)
    ride = boltAt - bolt

    if kit:
        clamp = _kitClamp(data, obj)
        bar = _retarget(obj, "Clamp", clamp["solid"], "ClampBar")
        bar.Placement = tipped.multiply(frame)
        # the T-slot nut's tongue at the table's top, the stud from its bottom up through the
        # nut on the clamp
        tnut = data["tnut"]
        bottom = table - tnut["tongue"]
        link = _retarget(obj, "TNut", tnut["solid"], "ClampTNut")
        link.Placement = FreeCAD.Placement(Vector(boltAt.x, boltAt.y, bottom), FreeCAD.Rotation())
        nut = data["nut"]
        link = _retarget(obj, "Nut", nut["solid"], "ClampNut")
        link.Placement = FreeCAD.Placement(boltAt, FreeCAD.Rotation())
        need = boltAt.z + nut["height"] + _length(LEVER_STUD_ABOVE_NUT) - bottom
        stud, upper = _studsFor(data, need)
        if stud is None:
            stud = data["studs"][-1]
            notes.append(
                translate("CAM", "no stud in the kit is long enough: %s needed") % userLength(need)
            )
        link = _retarget(obj, "Stud", stud["solid"], "ClampStud")
        link.Placement = FreeCAD.Placement(Vector(boltAt.x, boltAt.y, bottom), FreeCAD.Rotation())
        obj.Stud = stud["label"]
        # too tall for one stud: another on it, joined by the kit's coupling nut
        joint = bottom + stud["length"]
        coupler = data.get("coupler") if upper is not None else None
        link = _retarget(obj, "StudUpper", upper["solid"] if upper else None, "ClampStudUpper")
        if link is not None:
            link.Placement = FreeCAD.Placement(
                Vector(boltAt.x, boltAt.y, joint), FreeCAD.Rotation()
            )
        link = _retarget(obj, "Coupler", coupler["solid"] if coupler else None, "ClampCoupler")
        if link is not None:
            link.Placement = FreeCAD.Placement(
                Vector(boltAt.x, boltAt.y, joint - coupler["length"] / 2), FreeCAD.Rotation()
            )
            obj.Stud = translate("CAM", "%s and %s, joined by a %s") % (
                stud["label"],
                upper["label"],
                coupler["label"],
            )
        # its step block, the step's edge toward the taller ones under the heel's end
        if chosen is not None:
            block, pose, tread, _, meshed = chosen
            base = table + floor + under
            steps = block[pose]["treads"]
            link = _retarget(obj, "Block", block["solid"], "ClampBlock")
            low = _retarget(
                obj, "BlockUnder", meshed[0]["solid"] if meshed else None, "ClampBlockUnder"
            )
            if meshed is None:
                # its step's edge toward the taller ones under the heel's end
                link.Placement = FreeCAD.Placement(
                    Vector(heelAt.x - tread[1] + seat, -tread[2], base), FreeCAD.Rotation()
                ).multiply(_placementOf(block[pose]["place"]))
                # its lower steps reach back toward the work: room for them past the stud
                reach = block[pose].get("reach", steps[-1][1])
                if heelAt.x - tread[1] + seat - reach < boltAt.x + _shank(data) - 1e-6:
                    notes.append(_NO_ROOM())
                obj.Support = translate("CAM", "%s %s, step %d of %d") % (
                    block["label"],
                    translate("CAM", pose),
                    steps.index(tread) + 1,
                    len(steps),
                )
            else:
                lower, _, top, _, shift = meshed
                # the pair as planned, under where the bar bears first
                way, move = pair["way"], pivotAt.x - pair["near"]
                upAt, lowAt = pair["upper"] + move, move
                if pair["edge"] + move < boltAt.x + _shank(data) - 1e-6:
                    notes.append(_NO_ROOM())
                turned = FreeCAD.Rotation(Vector(0, 0, 1), 0 if way > 0 else 180)
                link.Placement = FreeCAD.Placement(
                    Vector(upAt, 0, base + top),
                    turned.multiply(FreeCAD.Rotation(Vector(0, 1, 0), 180)),
                ).multiply(_placementOf(block[pose]["place"]))
                low.Placement = FreeCAD.Placement(Vector(lowAt, 0, base), turned).multiply(
                    _placementOf(lower[pose]["place"])
                )
                obj.Support = translate("CAM", "%s upside down on the %s, %s, teeth into teeth") % (
                    block["label"],
                    lower["label"],
                    translate("CAM", pose),
                )
            if under > 0:
                obj.Support += translate("CAM", ", on a riser %s thick") % userLength(under)
            obj.Support += translate("CAM", ", %s high") % userLength(support)
        else:
            _retarget(obj, "Block", None, "ClampBlock")
            _retarget(obj, "BlockUnder", None, "ClampBlockUnder")
    else:
        for link in obj.Group:
            role = getattr(link, "LeverRole", None)
            source = getattr(link, "SourcePlacement", None)
            if source is None:
                continue
            at = frame.multiply(source)
            if role == "Rides":
                link.Placement = FreeCAD.Placement(ride, FreeCAD.Rotation()).multiply(at)
            elif role == "Anchored":
                # in the table's track: under the bolt where it now is, as deep in the table
                lifted = Vector(ride.x, ride.y, table - (data["table"] - _sourceToe(data, obj).z))
                link.Placement = FreeCAD.Placement(lifted, FreeCAD.Rotation()).multiply(at)
            else:
                link.Placement = tipped.multiply(at)
        _cutBolts(obj)

    if restsOn not in ("StepBlock", "RiserAndStepBlock") or not kit:
        obj.Support = (
            translate("CAM", "a riser %s thick") % userLength(support)
            if restsOn == "Riser"
            else translate("CAM", "the table")
        )
    riser = _riser(
        obj,
        restsOn == "Riser" or (restsOn in ("StepBlock", "RiserAndStepBlock") and under > 0),
    )
    if riser is not None:
        length, width = _length(LEVER_RISER_LENGTH), data.get("width", 25.0)
        width = _kitClamp(data, obj).get("width", width) + 2 * _length(LEVER_RISER_MARGIN)
        bottom = _linkOf(obj, "BlockUnder") or _linkOf(obj, "Block")
        if restsOn in ("StepBlock", "RiserAndStepBlock") and bottom is not None:
            # under the step block, past it all round by a margin
            margin = _length(LEVER_RISER_MARGIN)
            box = Part.getShape(bottom, "", transform=True).BoundBox
            riser.Shape = Part.makeBox(
                box.XLength + 2 * margin,
                box.YLength + 2 * margin,
                under,
                Vector(box.XMin - margin, box.YMin - margin, table + floor),
            )
        elif support > floor:
            riser.Shape = Part.makeBox(
                length,
                width,
                support - floor,
                Vector(heelAt.x - length / 2, -width / 2, table + floor),
            )
    obj.Tilt = tilt
    if kit and tilt < -1e-6:
        notes.append(translate("CAM", "its other end is lower than where it presses"))
    elif tilt > LEVER_TILT_NOTED:
        notes.append(
            translate(
                "CAM",
                "its other end is far above where it presses: a thinner riser or a lower step",
            )
        )
    note = "; ".join(notes)
    # said once, not each time it is placed again
    if note and note != obj.Note:
        Path.Log.warning("%s: %s" % (obj.Label, note))
    obj.Note = note


def _about(point, angle):
    """A turn by angle degrees about the line across the clamp through point, lifting what is
    nearer where it presses than point."""
    return FreeCAD.Placement(point, FreeCAD.Rotation(Vector(0, 1, 0), angle)).multiply(
        FreeCAD.Placement(-point, FreeCAD.Rotation())
    )


def _barShapes(obj, data, frame):
    """The shapes of what tips with the clamp's bar, in the clamp's frame before it is tipped."""
    shapes = []
    if data.get("kind") == StrapKit:
        link = _linkOf(obj, "Clamp")
        target = getattr(link, "LinkedObject", None)
        if target is not None:
            shape = target.Shape.copy()
            shape.Placement = frame.multiply(shape.Placement)
            shapes.append(shape)
        return shapes
    for link in obj.Group:
        if getattr(link, "LeverRole", None) != "Bar":
            continue
        target = getattr(link, "LinkedObject", None)
        source = getattr(link, "SourcePlacement", None)
        if target is None or source is None:
            continue
        shape = target.Shape.copy()
        shape.Placement = frame.multiply(source)
        shapes.append(shape)
    return shapes


def _meets(bars, stock, placement):
    """Whether the bars, placed so, cut into the stock by more than a sliver."""
    for bar in bars:
        moved = bar.copy()
        moved.Placement = placement.multiply(moved.Placement)
        if not moved.BoundBox.intersect(stock.BoundBox):
            continue
        if moved.common(stock).Volume > 1e-3:
            return True
    return False


def _lowest(bars, tipped, heel):
    """The lowest the bars reach, placed so, at their other end, heel: what stands on the table
    or riser, within LEVER_END_REACH of heel along the clamp. The end pressing on the stock may
    be lower when what it rests on stands higher than the stock."""
    reach = _length(LEVER_END_REACH)
    low = None
    for bar in bars:
        moved = bar.copy()
        moved.Placement = tipped.multiply(moved.Placement)
        box = moved.BoundBox
        end = Part.makeBox(
            box.XMax - (heel.x - reach) + 1,
            box.YLength + 2,
            box.ZLength + 2,
            Vector(heel.x - reach, box.YMin - 1, box.ZMin - 1),
        )
        part = moved.common(end)
        if part.isNull() or not part.Solids:
            continue
        z = part.BoundBox.ZMin
        low = z if low is None else min(low, z)
    return low if low is not None else heel.z


def _clearing(bars, stock, tipped, heel, most=20.0):
    """How far, in degrees, the bars tipped so must turn about heel to clear the stock, found to a
    hundredth of a degree; 0 when they are clear."""
    if not _meets(bars, stock, tipped):
        return 0.0
    low, high = 0.0, most
    if _meets(bars, stock, _about(heel, high).multiply(tipped)):
        return high
    while high - low > 0.01:
        middle = (low + high) / 2
        if _meets(bars, stock, _about(heel, middle).multiply(tipped)):
            low = middle
        else:
            high = middle
    return high


def _heelSeat(bars, tipped, block, pose, at, base):
    """Where a step block standing on base, its middle along the clamp at at, seats the bars
    tipped so: slid along the clamp by less than half a tooth, the heel's teeth into its teeth
    where they seat deepest, tooth tips in the corners, not tip on tip. (how far it is slid, how
    far the bars must then go up to just touch it): below 0 when they stand clear of it, above
    when they cut into it."""
    import numpy

    profile = block[pose]["profile"]
    step = profile["step"]
    tops = numpy.asarray(profile["z"]) + base
    treads = block[pose]["treads"]
    pitch = (treads[-1][1] - treads[0][1]) / max(1, len(treads) - 1)
    unders = []
    for bar in bars:
        moved = bar.copy()
        moved.Placement = tipped.multiply(moved.Placement)
        # its underside, as the top of it turned over
        under = _profile(moved.mirror(Vector(), Vector(0, 0, 1)), step)
        unders.append((under["x0"], -numpy.asarray(under["z"])))
    best = None
    count = int(pitch / 2 / step)
    for k in sorted(range(-count, count + 1), key=abs):
        x0 = at + profile["x0"] + k * step
        lift = None
        for u0, under in unders:
            first = int(round((x0 - u0) / step))
            i = max(0, -first)
            j = min(len(tops), len(under) - first)
            if j <= i:
                continue
            gap = float((tops[i:j] - under[first + i : first + j]).max())
            lift = gap if lift is None else max(lift, gap)
        if lift is None:
            continue
        # the bars coming down furthest before they touch: the teeth meshed
        score = lift
        if best is None or score < best[0] - 1e-6:
            best = (score, k * step, lift)
    return (best[1], best[2]) if best else (0.0, 0.0)


def _studInSlot(job, obj, data, frame, bolt, notes, radius=None):
    """Where in its slot a kit's step clamp has its stud: where BoltAt puts it, as far from the
    end pressing, kept in the slot; for Auto, as near the stock as the slot lets it, the stud
    clear of the stock's side. Said when the stud is in the stock."""
    end = _kitClamp(data, obj).get("boltEnd")
    if end is None:
        return bolt
    end = frame.multVec(_vector(end))
    low, high = sorted((bolt.x, end.x))
    wanted = getattr(obj, "BoltAt", None)
    wanted = wanted.Value if wanted is not None and wanted.Value > 0 else None
    clear = _studClear(job, obj, data, radius)
    if wanted is not None:
        at = min(max(wanted, low), high)
        if clear is not None and at < clear - 1e-6:
            notes.append(
                translate("CAM", "its stud is in the stock's side: put the bolt %s out at least")
                % userLength(clear)
            )
        return Vector(at, bolt.y, bolt.z)
    if clear is None:
        return bolt
    if clear > high + 1e-6:
        notes.append(
            translate(
                "CAM",
                "its stud is in the stock even at the far end of its slot: press farther in or use "
                "a longer clamp",
            )
        )
    return Vector(min(max(clear, low), high), bolt.y, bolt.z)


def boltRange(obj):
    """boltRange(obj) ... how far from the end pressing on the stock a strap clamp's bolt may
    be, along the clamp, as its slot runs: (nearest, farthest); None for a clamp without a
    slot."""
    data = dataOf(obj)
    end = _kitClamp(data, obj).get("boltEnd") if data else None
    if end is None:
        return None
    _, _, bolt, frame = _lever(data, obj)
    end = frame.multVec(_vector(end))
    return tuple(sorted((abs(bolt.x), abs(end.x))))


def _studClear(job, obj, data, radius=None):
    """How far from the end pressing the stud, radius round, the stud's own when not given, is
    first clear of the stock's side, along the clamp; None when the stock is not under it."""
    stock = job.Stock.Shape.copy()
    stock.Placement = obj.Placement.inverse().multiply(stock.Placement)
    # the stock across the stud's width under the clamp, out along it: the nut on the clamp is
    # above the stock
    radius = radius or _shank(data)
    box = stock.BoundBox
    strip = Part.makeBox(
        box.XLength + 2,
        2 * radius,
        box.ZLength + 2,
        Vector(box.XMin - 1, -radius, box.ZMin - 1),
    )
    under = stock.common(strip)
    if under.isNull() or under.Volume < 1e-9:
        return None
    return under.BoundBox.XMax + radius + _length(LEVER_EDGE_CLEARANCE)


def _sourceToe(data, obj):
    """Where it presses in its own file."""
    key = "heel" if getattr(obj, "Presses", "Toe") == "Heel" else "toe"
    return _vector(data[key])


def pressOf(job, obj):
    """pressOf(job, obj) ... where the lever clamp presses, the Job's X and Y."""
    base = PathWorkholding.placementOf(obj).Base
    return base.x, base.y


def setPress(job, obj, x, y):
    """setPress(job, obj, x, y) ... the lever clamp pressing at the Job's x and y, kept there from
    the stock's front left corner as the stock moves; placed again."""
    box = job.Stock.Shape.BoundBox
    proxy = obj.Proxy
    proxy.placing = True
    try:
        obj.Pinned = True
        obj.PressX = x - box.XMin
        obj.PressY = y - box.YMin
    finally:
        proxy.placing = False
    import Path.Workholding.Items as PathItems

    PathItems.layout(job)


def another(job, obj):
    """another(job, obj) ... one more lever clamp like obj on its side, spread along it with the
    others there, standing as obj does: its settings, but not where obj was put. Returns it."""
    import Path.Workholding.Items as PathItems

    side = obj.StockSide
    specs = PathItems.clampsOf(job)
    for spec in specs:
        if spec["side"] == side:
            spec["count"] += 1
    before = PathItems.clampsOn(job, side)
    PathItems.setClamps(job, specs)
    new = next(c for c in PathItems.clampsOn(job, side) if c not in before)
    new.Proxy.placing = True
    try:
        for name in Settings:
            if name in ("PressX", "PressY", "Pinned") or not hasattr(obj, name):
                continue
            setattr(new, name, getattr(obj, name))
    finally:
        new.Proxy.placing = False
    PathItems.layout(job)
    return new


def fromPlacement(job, obj):
    """fromPlacement(job, obj) ... the lever clamp kept where its placement now puts it, moved
    by FreeCAD's Transform: pressing at its origin, pinned there, turned by how far its
    placement turns it from square to its side. Placed again."""
    import Path.Workholding.Items as PathItems

    base = obj.Placement.Base
    box = job.Stock.Shape.BoundBox
    obj.Proxy.placing = True
    try:
        obj.Angle = angleFrom(job, obj, obj.Placement.Rotation)
        obj.Pinned = True
        obj.PressX = base.x - box.XMin
        obj.PressY = base.y - box.YMin
    finally:
        obj.Proxy.placing = False
    PathItems.layout(job)


def angleFrom(job, obj, rotation):
    """angleFrom(job, obj, rotation) ... the lever clamp's Angle were it turned by rotation: how
    far from square to its side, -180 to 180 degrees."""
    import Path.Workholding.Items as PathItems

    frame, _ = PathItems.sideFrame(job, obj.StockSide)
    outward = frame.Rotation.multVec(Vector(0, -1, 0))
    facing = rotation.multVec(Vector(1, 0, 0))
    angle = math.degrees(math.atan2(facing.y, facing.x) - math.atan2(outward.y, outward.x))
    angle = (angle + 180.0) % 360.0 - 180.0
    # square, not a hair either side of it shown as -0.00
    return 0.0 if abs(angle) < 1e-9 else angle


def placeOnSide(job, obj, frame, x):
    """placeOnSide(job, obj, frame, x) ... the lever clamp placed from its side's frame: pressing
    where it was put, if it was, else x along the side and Overlap in from its edge, its other end
    out from the stock."""
    box = job.Stock.Shape.BoundBox
    if getattr(obj, "Pinned", False):
        press = Vector(box.XMin + obj.PressX.Value, box.YMin + obj.PressY.Value, box.ZMax)
    else:
        press = frame.multVec(Vector(x, obj.Overlap.Value, 0))
    outward = frame.Rotation.multVec(Vector(0, -1, 0))
    place(job, obj, press, outward)
