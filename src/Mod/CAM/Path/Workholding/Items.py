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

"""Simple workholding made from a few dimensions, and placing it against the stock.

Each piece is of a kind that says how it holds:

- a Stop, a dog in the table or a fence along the stock's side, the stock pushed against it;
- a Push, a side clamp pushing the stock onto the stops;
- a HoldDown, a clamp over the stock's top edge, an edge clamp or a toe clamp;
- a Lever, a bar pressing on the stock's top, its other end on the table, a riser or a step
  block, placed where it presses and at an angle (Path.Workholding.Lever);
- a Table, the bed the rest stands on: its T-track rails, its dog holes, the waste board the
  stock lies on. Cut into on purpose, it is shown but nothing is found hitting it.

A Stop or a Push has its origin where it touches the stock, on the surface the stock lies on,
its +Y into the stock. A HoldDown has its origin on the stock's top edge, its +Y into the stock,
its lip reaching in over the top and its body standing beside the stock down to the table.

A clamp may come from a file of its own, in the CAM assets' Workholding/Clamps folder: a part laid
out in the same frame, with a VarSet whose Kind says how it holds, HoldDown or Push. It is put in a
Job as a vise is, its parts linked from the file, its settings copied onto it.

The stops and clamps are placed round the stock by side, the part's own sides as a vise names
them: stops on one side, or on two next to each other, a corner, the stock pushed against them;
clamps on any side, a side clamp only on one away from the stops. Each says on itself where it is
placed, its Placed settings, so it is placed again as it says when the stock moves or the stops
and clamps change. A stop can be shared by two Jobs, a dog between two parts, each Job's part
against one of its faces; a stop shared stays where it is, the part moving to it."""

import math
import os

import FreeCAD
import Part
import Path
import Path.Workholding.Lever as PathLever
import Path.Workholding.Vise as PathWorkholding
import Path.Workholding.Source as PathSource

from FreeCAD import Vector
from Path.Workholding.Common import (
    objectKinds,
    readDocumentXml,
    stockTopUnder,
    varsetProperties,
)
from Path.Workholding.Constants import ACROSS_AT_LEAST, CLAMP_KINDS, TOUCH_MOVES, TOUCH_NEAR
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate


class Kind:
    Stop = "Stop"
    Push = "Push"
    HoldDown = "HoldDown"
    Lever = "Lever"
    StrapKit = "StrapKit"
    Table = "Table"


class ObjectItem:
    """A piece of workholding made from a few dimensions."""

    kind = None
    # a stop: its dimension from the face touching the stock to the face opposite, the other
    # face a second Job's part touches when the stop is shared
    across = None

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyString",
            "Kind",
            "Workholding",
            QT_TRANSLATE_NOOP("App::Property", "How it holds the stock"),
        )
        obj.Kind = self.kind
        obj.setEditorMode("Kind", 1)
        obj.addProperty(
            "App::PropertyBool",
            "Collides",
            "Workholding",
            QT_TRANSLATE_NOOP(
                "App::Property", "Whether the simulator finds a tool or holder hitting it"
            ),
        )
        obj.Collides = self.kind != Kind.Table
        self.addProperties(obj)

    def _add(self, obj, kind, name, tip, value):
        obj.addProperty(kind, name, "Workholding", QT_TRANSLATE_NOOP("App::Property", tip))
        setattr(obj, name, value)

    def addProperties(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        placement = obj.Placement
        shape = self.shape(obj)
        shape.Placement = placement
        obj.Shape = shape

    def follows(self, obj, owner):
        """obj, another Job's, placed by expression where owner is and as big: where their Contact
        differs, on owner's other face, turned to face the other way."""
        for name in obj.PropertiesList:
            if (
                obj.getGroupOfProperty(name) == "Workholding"
                and obj.getTypeIdOfProperty(name) == "App::PropertyLength"
                and hasattr(owner, name)
            ):
                obj.setExpression(name, "%s.%s" % (owner.Name, name))
        expression = "%s.Placement" % owner.Name
        if self.across and getattr(obj, "Contact", 1) != getattr(owner, "Contact", 1):
            expression += " * placement(vector(0; -%s.%s; 0); rotation(vector(0; 0; 1); 180))" % (
                owner.Name,
                self.across,
            )
        obj.setExpression("Placement", expression)


class ObjectDog(ObjectItem):
    """A dog: a round pin standing in a hole of the table."""

    kind = Kind.Stop
    across = "Diameter"

    def addProperties(self, obj):
        self._add(
            obj,
            "App::PropertyLength",
            "Diameter",
            "Across the pin",
            FreeCAD.Units.Quantity("0.75 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Height",
            "Above the table",
            FreeCAD.Units.Quantity("0.5 in").Value,
        )

    def shape(self, obj):
        r = obj.Diameter.Value / 2
        return Part.makeCylinder(r, obj.Height.Value, Vector(0, -r, 0))


class ObjectFence(ObjectItem):
    """A fence: a bar standing on the table along the stock's side."""

    kind = Kind.Stop
    across = "Width"

    def addProperties(self, obj):
        self._add(
            obj,
            "App::PropertyLength",
            "Length",
            "Its longest, along the stock",
            FreeCAD.Units.Quantity("6.0 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Width",
            "Front to back, away from the stock",
            FreeCAD.Units.Quantity("0.75 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Height",
            "Above the table",
            FreeCAD.Units.Quantity("0.5 in").Value,
        )

    def shape(self, obj):
        length, width = obj.Length.Value, obj.Width.Value
        return Part.makeBox(length, width, obj.Height.Value, Vector(-length / 2, -width, 0))


class ObjectSideClamp(ObjectItem):
    """A side clamp: a block pushing on the stock's side, a cam or wedge clamp."""

    kind = Kind.Push

    def addProperties(self, obj):
        self._add(
            obj,
            "App::PropertyLength",
            "Width",
            "Side to side, along the stock",
            FreeCAD.Units.Quantity("2.0 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Length",
            "Front to back, away from the stock",
            FreeCAD.Units.Quantity("1.5 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Height",
            "Above the table",
            FreeCAD.Units.Quantity("0.5 in").Value,
        )

    def shape(self, obj):
        w, d, h = obj.Width.Value, obj.Length.Value, obj.Height.Value
        return Part.makeBox(w, d, h, Vector(-w / 2, -d, 0))


class ObjectEdgeClamp(ObjectItem):
    """A hold-down over the stock's top edge: its body beside the stock on the table, its lip
    over the top. As a low edge clamp: 0.22 in above the stock, reaching 0.23 in over it."""

    kind = Kind.HoldDown

    def addProperties(self, obj):
        self._add(
            obj,
            "App::PropertyLength",
            "Width",
            "Side to side, along the stock's edge",
            FreeCAD.Units.Quantity("1.0 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Length",
            "Its body, front to back, away from the stock",
            FreeCAD.Units.Quantity("0.75 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Reach",
            "Over the stock's top",
            FreeCAD.Units.Quantity("0.23 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Rise",
            "Above the stock's top",
            FreeCAD.Units.Quantity("0.22 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Drop",
            "From the stock's top down to the table",
            FreeCAD.Units.Quantity("0.75 in").Value,
        )

    def shape(self, obj):
        w, d = obj.Width.Value, obj.Length.Value
        reach, rise, drop = obj.Reach.Value, obj.Rise.Value, obj.Drop.Value
        body = Part.makeBox(w, d, drop + rise, Vector(-w / 2, -d, -drop))
        lip = Part.makeBox(w, reach, rise, Vector(-w / 2, 0, 0))
        return body.fuse(lip).removeSplitter()


class ObjectTable(ObjectItem):
    """The bed: a spoilboard with T-track rails along X and a grid of dog holes, and the waste
    board on it the stock lies on. Its origin is the waste board's top at its front left. Made
    as a router's: 8 ft along X by 5 ft, an inch thick, rails every 5 in."""

    kind = Kind.Table

    def addProperties(self, obj):
        self._add(
            obj,
            "App::PropertyLength",
            "Width",
            "Side to side, along X",
            FreeCAD.Units.Quantity("96 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Length",
            "Front to back, along Y",
            FreeCAD.Units.Quantity("60 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "Thickness",
            "Of the spoilboard",
            FreeCAD.Units.Quantity("1.0 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "RailSpacing",
            "Between the rails, in Y",
            FreeCAD.Units.Quantity("5 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "RailWidth",
            "Of a rail",
            FreeCAD.Units.Quantity("0.75 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "HoleSpacing",
            "Between the dog holes, both ways",
            FreeCAD.Units.Quantity("4 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "HoleDiameter",
            "Of a dog hole",
            FreeCAD.Units.Quantity("0.75 in").Value,
        )
        self._add(
            obj,
            "App::PropertyLength",
            "WasteBoard",
            "Of the sheet on the spoilboard the stock lies on, none if 0",
            FreeCAD.Units.Quantity("0.25 in").Value,
        )

    def shape(self, obj):
        length, width = obj.Width.Value, obj.Length.Value
        waste = obj.WasteBoard.Value
        top = -waste  # the spoilboard's top, under the waste board
        board = Part.makeBox(
            length, width, obj.Thickness.Value, Vector(0, 0, top - obj.Thickness.Value)
        )
        parts = []
        # the rails, flush with the spoilboard
        spacing, railWidth = obj.RailSpacing.Value, obj.RailWidth.Value
        rails = []
        y = spacing
        while spacing > 0 and y + railWidth / 2 < width:
            rails.append(
                Part.makeBox(
                    length,
                    railWidth,
                    railWidth / 2,
                    Vector(0, y - railWidth / 2, top - railWidth / 2),
                )
            )
            y += spacing
        # the dog holes, a grid clear of the rails
        holes = []
        step, radius = obj.HoleSpacing.Value, obj.HoleDiameter.Value / 2
        if step > 0 and radius > 0:
            x = step / 2
            while x < length:
                y = step / 2
                while y < width:
                    clear = all(
                        abs(y - (r.BoundBox.YMin + railWidth / 2)) > railWidth / 2 + radius
                        for r in rails
                    )
                    if clear:
                        holes.append(
                            Part.makeCylinder(
                                radius, obj.Thickness.Value, Vector(x, y, top - obj.Thickness.Value)
                            )
                        )
                    y += step
                x += step
        if rails or holes:
            board = board.cut(Part.makeCompound(rails + holes))
        parts.append(board)
        parts.extend(rails)
        if waste > 0:
            parts.append(Part.makeBox(length, width, waste, Vector(0, 0, top)))
        return Part.makeCompound(parts)


class ObjectClamp(PathWorkholding.LinkedGroup):
    """A clamp of a Job's Workholding from a clamp's own file: a group placing the parts it
    links from the file, laid out as a HoldDown or a Push is, the settings of the file's VarSet
    copied onto it, its Kind among them."""

    group = "Clamp"
    viewProviderName = "ViewProviderClamp"

    def onDocumentRestored(self, obj):
        # its file looked for again if it is not found
        PathSource.recoverLater(obj.Document)


Classes = {
    "Dog": ObjectDog,
    "Fence": ObjectFence,
    "SideClamp": ObjectSideClamp,
    "EdgeClamp": ObjectEdgeClamp,
    "Table": ObjectTable,
}

# the classes a stop and a clamp are made of; a clamp may also be a clamp's own file
StopClasses = ["Dog", "Fence"]
ClampClasses = ["SideClamp", "EdgeClamp"]


def create(job, which, name=None):
    """create(job, which, name=None) ... a new piece of workholding of class which, one of
    Classes, in the Job's Workholding."""
    doc = job.Document
    obj = doc.addObject("Part::FeaturePython", name or which)
    Classes[which](obj)
    if FreeCAD.GuiUp:
        import Path.Workholding.Gui.ViewProvider as Gui

        Gui.ViewProvider(obj.ViewObject)
    job.Workholding.addObject(obj)
    return obj


def placeTable(job, table):
    """placeTable(job, table) ... the table under the stock: its waste board's top where the
    stock lies, the stock's front left corner at the table's, inset by a hole spacing."""
    bb = stockBox(job)
    inset = table.HoleSpacing.Value if hasattr(table, "HoleSpacing") else 0
    table.Placement = FreeCAD.Placement(
        Vector(bb.XMin - inset, bb.YMin - inset, bb.ZMin), FreeCAD.Rotation()
    )


# The part's own sides, as the vise panel names them: the Job's axis each faces out along as the
# part is modeled, -Y its front, +X its right
AllSides = ["-Z", "+Z", "-Y", "+Y", "-X", "+X"]


def _direction(side):
    return PathWorkholding.Directions[side]


def sides(job):
    """sides(job) ... the part's own sides standing round its stock, as AllSides names them: those
    the part is turned to face across the table, not up or down. Stops and clamps go against
    these."""
    turn = PathWorkholding.partTurn(job)
    return [s for s in AllSides if abs(turn.multVec(_direction(s)).z) < 1e-6]


def adjacent(a, b):
    """adjacent(a, b) ... whether two sides of the part are next to each other: square, not the
    same side nor opposite ones."""
    return abs(_direction(a).dot(_direction(b))) < 1e-9


def sideDirection(job, side):
    """sideDirection(job, side) ... the Job's axis the stock's side faces out along: the part's
    own side as sides names it, where the part is turned now."""
    d = PathWorkholding.partTurn(job).multVec(_direction(side))
    if abs(d.z) > 1e-6:
        raise ValueError(
            translate("CAM", "The part's %s side faces up or down: nothing goes against it") % side
        )
    # the stock's box is square to the Job's axes
    return max((_direction(a) for a in ("-Y", "+Y", "-X", "+X")), key=lambda a: a.dot(d))


def _turnOf(along, inward):
    """The turn whose +X is along, whose +Y is inward, its +Z up."""
    up = along.cross(inward)
    return FreeCAD.Rotation(
        FreeCAD.Matrix(
            along.x, inward.x, up.x, 0, along.y, inward.y, up.y, 0, along.z, inward.z, up.z, 0
        )
    )


def stockBox(job):
    """stockBox(job) ... the box round the Job's stock, from its surfaces: a round stock's sides
    where they are, not where the triangles drawing it put them."""
    return job.Stock.Shape.optimalBoundingBox(False)


def sideFrame(job, side):
    """sideFrame(job, side) ... the frame of the stock's side, the part's own side as sides names
    it, and how long the side is: its origin in the middle of the side on the surface the stock
    lies on, its +X along the side, its +Y into the stock, its +Z up. A stop or a side clamp is
    put in it as it is laid out, a hold-down as high up as the stock's top."""
    out = sideDirection(job, side)
    bb = stockBox(job)
    inward = out * -1
    along = inward.cross(Vector(0, 0, 1))
    middle = Vector(bb.Center.x, bb.Center.y, bb.ZMin)
    half = abs(out.x) * bb.XLength / 2 + abs(out.y) * bb.YLength / 2
    length = abs(along.x) * bb.XLength + abs(along.y) * bb.YLength
    return FreeCAD.Placement(middle + out * half, _turnOf(along, inward)), length


def spanSlots(length, count, pinned, width):
    """spanSlots(length, count, pinned, width) ... where count pieces go along a line length long,
    from its middle, pinned the places of those moved there, width how wide each is: as a list of
    (place, the index into pinned of the one that takes it or None). None moved: the even shares.
    One moved: from it to as far the other way from the middle, the next added there and the
    others between, in order. Two or more: evenly from the first moved to the last. Each moved one
    takes the place nearest it, the others the rest in order. Too narrow a span for them side by
    side: the even shares."""
    slots = spread(length, count)
    if pinned and count > 1:
        if len(pinned) == 1:
            # from it to its mirror about the middle
            start, end = pinned[0], -pinned[0]
        else:
            start, end = min(pinned), max(pinned)
        if abs(end - start) >= (count - 1) * width:
            slots = [start + (end - start) * i / (count - 1) for i in range(count)]
    elif pinned and count == 1:
        slots = [pinned[0]]
    taken = {}
    # nearest first, so one moved onto a place keeps it
    wants = sorted((abs(at - x), i, k) for k, at in enumerate(pinned) for i, x in enumerate(slots))
    for _, i, k in wants:
        if k not in taken and i not in taken.values():
            taken[k] = i
    owner = {i: k for k, i in taken.items()}
    return [(x, owner.get(i)) for i, x in enumerate(slots)]


def _slots(job, group, frame, length):
    """Where each of a side's pieces is spread to, in its frame, as spanSlots says; fences,
    which share the side's length, to its even shares."""
    pinned = [p for p in group if getattr(p, "Pinned", False)]
    if any(isinstance(getattr(p, "Proxy", None), ObjectFence) for p in group):
        pinned = []
    low, high = _widthAlong(job, group[0]) if pinned else (0.0, 0.0)
    places = spanSlots(
        length, len(group), [_alongSide(job, p, frame, 0.0) for p in pinned], high - low
    )
    byPinned = {k: x for x, k in places if k is not None}
    free = iter(x for x, k in places if k is None)
    out = []
    for p in group:
        k = pinned.index(p) if p in pinned else None
        out.append(byPinned[k] if k is not None else next(free))
    return out


def spread(length, count):
    """spread(length, count) ... where count pieces go along a side length long, from its middle:
    each in the middle of its even share of the side."""
    if count < 1:
        return []
    return [length * (i + 0.5) / count - length / 2 for i in range(count)]


def sideAxis(job, side):
    """sideAxis(job, side) ... which of the Job's axes the stock's side runs along, 0 for X and 1
    for Y, and +1 or -1 as its frame's +X runs with that axis or against it."""
    frame, _ = sideFrame(job, side)
    way = frame.Rotation.multVec(Vector(1, 0, 0))
    axis = 0 if abs(way.x) > abs(way.y) else 1
    return axis, 1.0 if way[axis] > 0 else -1.0


def _stockStart(job, axis):
    """Where the stock begins along the Job's axis, 0 for X and 1 for Y."""
    bb = stockBox(job)
    return bb.XMin if axis == 0 else bb.YMin


def _alongSide(job, piece, frame, x):
    """Where along its side, in the side's frame, the piece goes: where it is pinned, else x,
    where it is spread to; between the side's ends, where there is stock to touch."""
    if not getattr(piece, "Pinned", False):
        return x
    axis, way = sideAxis(job, piece.StockSide)
    at = (_stockStart(job, axis) + piece.Along.Value - frame.Base[axis]) * way
    low, high = _alongLimits(job, piece)
    return min(max(at, low), high)


def isStop(obj):
    """isStop(obj) ... whether obj is a stop the stock is pushed against."""
    return getattr(obj, "Kind", None) == Kind.Stop


def isClamp(obj):
    """isClamp(obj) ... whether obj is a clamp: a side clamp, a hold-down over the top, or a lever
    clamp."""
    return getattr(obj, "Kind", None) in (Kind.Push, Kind.HoldDown, Kind.Lever)


def isPlaced(obj):
    """isPlaced(obj) ... whether obj is placed by side round the stock: it says which."""
    return bool(getattr(obj, "StockSide", ""))


def itemsOf(job):
    """itemsOf(job) ... the stops, clamps and tables of the Job's Workholding: all of it but its
    vises, placed by side or not."""
    group = getattr(job, "Workholding", None)
    return [o for o in getattr(group, "Group", []) or [] if not PathWorkholding.isVise(o)]


def _on(job, test, side=None):
    found = [
        o for o in itemsOf(job) if test(o) and isPlaced(o) and (side is None or o.StockSide == side)
    ]
    return sorted(found, key=lambda o: (AllSides.index(o.StockSide), o.SideIndex))


def stopsOn(job, side=None):
    """stopsOn(job, side=None) ... the Job's stops placed on side, along it; on every side when
    None."""
    return _on(job, isStop, side)


def clampsOn(job, side=None):
    """clampsOn(job, side=None) ... the Job's clamps placed on side, along it; on every side when
    None."""
    return _on(job, isClamp, side)


def _setRole(piece, side, index, source):
    """Where the piece is placed round the stock, kept on it: its side, which of those along it
    and what it is made as. Where it is pinned stays."""
    for name, kind, doc in (
        (
            "StockSide",
            "App::PropertyString",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "The side of the part it is against, the part's own: -Y its front, +Y its back, "
                "-X its left, +X its right",
            ),
        ),
        (
            "SideIndex",
            "App::PropertyInteger",
            QT_TRANSLATE_NOOP(
                "App::Property", "Which of those on its side it is, counted from 0 along it"
            ),
        ),
        (
            "Source",
            "App::PropertyString",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "What it is made as: Dog, Fence, SideClamp, EdgeClamp, or the clamp's own file",
            ),
        ),
        (
            "Pinned",
            "App::PropertyBool",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Put where Along says, not spread along its side with the others",
            ),
        ),
        (
            "Along",
            "App::PropertyDistance",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Where it is pinned along its side, from the stock's near end along the Job's X "
                "or Y",
            ),
        ),
    ):
        if not hasattr(piece, name):
            piece.addProperty(kind, name, "Placed", doc)
            piece.setEditorMode(name, ["Hidden"])
    piece.StockSide = side
    piece.SideIndex = index
    piece.Source = source


def _addContact(stop, contact):
    """The face of the stop its Job's part touches, kept on it."""
    if not hasattr(stop, "Contact"):
        stop.addProperty(
            "App::PropertyInteger",
            "Contact",
            "Placed",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "The face of the stop its Job's part touches, 1 or 2: a stop shared by two Jobs "
                "touches a part with each",
            ),
        )
        stop.setEditorMode("Contact", ["Hidden"])
    stop.Contact = contact


def _placeAt(job, piece, frame, x):
    """The piece put at x along the side whose frame is given: a hold-down on the stock's top
    edge, its body down to the table; a stop or a side clamp on the surface the stock lies on; a
    lever clamp where it presses, unless it was put elsewhere."""
    if PathLever.isLever(piece):
        PathLever.placeOnSide(job, piece, frame, x)
        return
    box = stockBox(job)
    height = box.ZLength
    _, length = sideFrame(job, piece.StockSide)
    placement = frame.multiply(_touching(piece, x, height, length))
    if piece.Kind == Kind.HoldDown:
        # its lip on the stock's top where it grips, not on the highest of a model's features
        # elsewhere
        lip = _shapeOf(piece).BoundBox
        at = FreeCAD.Placement(frame.multVec(Vector(x, 0, 0)), frame.Rotation)
        drop = (
            stockTopUnder(job, at, (lip.XMin, 0.0), (lip.XMax, max(lip.YMax, TOUCH_NEAR)))
            - box.ZMin
        )
        placement = FreeCAD.Placement(placement.Base + Vector(0, 0, drop), placement.Rotation)
        if hasattr(piece, "Drop") and abs(piece.Drop.Value - drop) > 1e-9:
            piece.Drop = drop
    placement = _toStock(job, piece, placement, frame)
    angle = getattr(piece, "Angle", None)
    if piece.Kind == Kind.Push and angle is not None and abs(angle.Value) > 1e-9:
        # turned, against a flat side of the stock: square to it; at a corner or a round, as it
        # is turned. One square to its side is left as it is, as it was placed
        square = squareAngle(job, piece, placement)
        if square is not None and abs(square - angle.Value) > 1e-6:
            _setAngle(piece, square)
            placement = frame.multiply(_touching(piece, x, height, length))
            placement = _toStock(job, piece, placement, frame)
    if not piece.Placement.isSame(placement, 1e-9):
        piece.Placement = placement


def _shapeOf(piece):
    """The piece's shape where it stands in its own frame, made again first if a setting of it
    changed or it was only just added: placing it goes by its size now."""
    if hasattr(piece, "Shape") and (piece.Shape.isNull() or "Touched" in piece.State):
        piece.recompute()
    return Part.getShape(piece, transform=False)


def _toStock(job, piece, placement, frame):
    """The piece, placed against its side of the stock's box, moved in square to the side until
    it touches the stock itself: on round stock, or a side that slants or has a step, where the
    box's side is not the stock's. Each move as far as the piece is from the stock, so it never
    goes into it. Left where it was when it would not come to touch the stock: past the side's
    end, beside it."""
    shape = _shapeOf(piece)
    stock = job.Stock.Shape
    if shape.isNull() or stock.isNull():
        return placement
    shape = shape.copy()
    inward = frame.Rotation.multVec(Vector(0, 1, 0))
    box = stockBox(job)
    deepest = abs(inward.x) * box.XLength + abs(inward.y) * box.YLength
    moved = 0.0
    for _ in range(TOUCH_MOVES):
        shape.Placement = FreeCAD.Placement(placement.Base + inward * moved, placement.Rotation)
        gap = shape.distToShape(stock)[0]
        if gap < TOUCH_NEAR:
            return shape.Placement
        moved += gap
        if moved > deepest:
            break
    return placement


def squareAngle(job, piece, placement, near=None):
    """squareAngle(job, piece, placement, near=None) ... the Angle that turns a side clamp at
    placement square to the flat side of the stock it touches, within near mm, TOUCH_NEAR when
    not given; None where it touches a corner or a round, or nothing."""
    shape = _shapeOf(piece)
    stock = job.Stock.Shape
    if shape.isNull() or stock.isNull():
        return None
    shape = shape.copy()
    shape.Placement = placement
    gap, _, info = shape.distToShape(stock)
    if gap > (near if near is not None else 10 * TOUCH_NEAR) or not info:
        return None
    normals = []
    for each in info:
        normal = _flatSideNormal(stock, each[3], each[4], each[5])
        if normal is None:
            return None
        normals.append(normal)
    if any((n - normals[0]).Length > 1e-6 for n in normals):
        return None
    frame, _ = sideFrame(job, piece.StockSide)
    inward = frame.Rotation.multVec(Vector(0, 1, 0))
    push = normals[0] * -1
    angle = math.degrees(math.atan2(push.y, push.x) - math.atan2(inward.y, inward.x))
    angle = (angle + 180.0) % 360.0 - 180.0
    return 0.0 if abs(angle) < 1e-9 else angle


def _flatSideNormal(stock, kind, index, param):
    """Which way the flat upright side of the stock out at what a distance found, seen from
    above: a face of it, or an edge along its top or bottom; None for a corner, a round or
    the top."""
    if kind == "Face":
        face = stock.Faces[index]
        if not isinstance(face.Surface, Part.Plane):
            return None
        normal = face.normalAt(*param)
        if abs(normal.z) > 1e-6:
            return None
        return Vector(normal.x, normal.y, 0).normalize()
    if kind == "Edge":
        edge = stock.Edges[index]
        if not isinstance(edge.Curve, Part.Line) or abs(edge.Curve.Direction.z) > 1e-6:
            return None
        found = [
            f
            for f in stock.ancestorsOfType(edge, Part.Face)
            if isinstance(f.Surface, Part.Plane) and abs(f.Surface.Axis.z) < 1e-6
        ]
        if len(found) != 1:
            return None
        face = found[0]
        u, v = face.Surface.parameter(edge.CenterOfMass)
        normal = face.normalAt(u, v)
        return Vector(normal.x, normal.y, 0).normalize()
    return None


def _alongLimits(job, piece):
    """How far along its side, in the side's frame, the piece may go: past either end until only
    ACROSS_AT_LEAST of its width, square to the side, is left across from the stock."""
    _, length = sideFrame(job, piece.StockSide)
    low, high = _widthAlong(job, piece)
    keep = (high - low) * ACROSS_AT_LEAST
    return -length / 2 - high + keep, length / 2 - low - keep


def _widthAlong(job, piece):
    """Where the piece reaches along its side from its origin, square to the side, beside the
    stock: (low, high) in the side's frame. Its width, not what turning it swings out."""
    shape = _shapeOf(piece)
    if shape.isNull():
        return 0.0, 0.0
    height = stockBox(job).ZLength
    box = shape.BoundBox
    # found once for its shape and the stock's height: cutting it is slow, and placing a side
    # asks often
    key = (
        piece.Document.Name,
        piece.Name,
        round(height, 6),
        tuple(round(v, 6) for v in (box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax)),
    )
    if key not in _widths:
        beside = shape.common(
            Part.makeBox(
                box.XLength + 2, box.YLength + 2, height, Vector(box.XMin - 1, box.YMin - 1, 0)
            )
        )
        found = beside.BoundBox if not beside.isNull() and beside.Solids else box
        _widths[key] = (found.XMin, found.XMax)
    return _widths[key]


# what _widthAlong found, by piece, its shape's box and the stock's height
_widths = {}


def _touching(piece, x, height, length):
    """Where the piece goes in its side's frame, at x along it: square to the side, or a side
    clamp turned as its Angle says, moved square to the side until it just touches the stock,
    height high and length along the side: what is below the table or above the stock, a bolt
    or a knob, or past the side's ends, beyond a corner, not counted."""
    angle = getattr(piece, "Angle", None)
    if piece.Kind != Kind.Push or angle is None or abs(angle.Value) < 1e-9:
        return FreeCAD.Placement(Vector(x, 0, 0), FreeCAD.Rotation())
    turned = FreeCAD.Placement(Vector(x, 0, 0), FreeCAD.Rotation(Vector(0, 0, 1), angle.Value))
    shape = _shapeOf(piece)
    if shape.isNull():
        return turned
    shape = shape.copy()
    shape.Placement = turned
    box = shape.BoundBox
    beside = shape.common(
        Part.makeBox(length, box.YLength + 2, height, Vector(-length / 2, box.YMin - 1, 0))
    )
    if beside.isNull() or not beside.Solids:
        # all of it past the side's ends: nothing of the stock across from it
        return turned
    reach = beside.optimalBoundingBox().YMax
    return FreeCAD.Placement(turned.Base - Vector(0, reach, 0), turned.Rotation)


def contactFrame(job, piece):
    """contactFrame(job, piece) ... where a stop or clamp placed against a side meets the stock,
    square to the side, its +X along it and +Y into the stock; None for a lever clamp or one
    not placed by side. A side clamp turned is dragged and turned about it."""
    if piece is None or PathLever.isLever(piece) or not isPlaced(piece):
        return None
    frame, _ = sideFrame(job, piece.StockSide)
    local = frame.inverse().multiply(PathWorkholding.placementOf(piece))
    # in from the box's side as far as the piece was moved in to touch the stock: measured again
    # only when it or the stock changed, slow on a real stock and asked for at every drag step
    inset = 0.0
    shape = Part.getShape(piece, "", transform=True)
    stock = job.Stock.Shape
    if not shape.isNull() and not stock.isNull():
        box = shape.BoundBox
        state = (
            tuple(
                round(v, 6) for v in (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)
            ),
            stock.hashCode(),
            str(job.Stock.Placement),
            piece.StockSide,
        )
        key = (job.Document.Name, piece.Name)
        known = _insets.get(key)
        if known is not None and known[0] == state:
            inset = known[1]
        else:
            gap, pairs, _ = shape.distToShape(stock)
            if gap < 10 * TOUCH_NEAR and pairs:
                inset = max(0.0, frame.inverse().multVec(pairs[0][1]).y)
            _insets[key] = (state, inset)
    return frame.multiply(
        FreeCAD.Placement(Vector(local.Base.x, inset, local.Base.z), FreeCAD.Rotation())
    )


# where each piece placed against a side last met the stock, and what it was measured from
_insets = {}


def _toShared(job, shared):
    """The part moved to the stops it shares with another Job, which stay where they are: turned
    so the side against the first faces it, then moved so the first is where it is spread to
    along that side, the stock touching it and its bottom on the surface the stop stands on;
    then onto the others, square to their faces."""
    # those following another placed where it is
    PathWorkholding.recompute(job.Document)
    for i, stop in enumerate(shared):
        # the stock's side faces out against the stop's face
        face = stop.Placement.Rotation.multVec(Vector(0, -1, 0))
        if i == 0:
            out = sideDirection(job, stop.StockSide)
            if (out - face).Length > 1e-6:
                angle = math.degrees(math.atan2(out.cross(face).z, out.dot(face)))
                PathWorkholding.turnModel(
                    job, FreeCAD.Rotation(Vector(0, 0, 1), angle), stockBox(job).Center
                )
        frame, length = sideFrame(job, stop.StockSide)
        group = stopsOn(job, stop.StockSide)
        x = spread(length, len(group))[group.index(stop)]
        x = _alongSide(job, stop, frame, x)
        move = stop.Placement.Base - frame.multVec(Vector(x, 0, 0))
        if i > 0:
            move = face * move.dot(face)
        if move.Length > 1e-9:
            PathWorkholding.moveModel(job, move)


# how deep in layout the code is: a placement changed meanwhile is layout's own
_layingOut = [0]


def layingOut():
    """layingOut() ... whether layout is placing pieces now: a placement changed meanwhile is
    its own, not a drag's."""
    return _layingOut[0] > 0


def layout(job, sides=None):
    """layout(job, sides=None) ... the Job's stops and clamps placed round its stock as each says:
    a stop shared with another Job stays where it is, the part moving to it first; the rest are
    put against the stock where it then is, spread along their sides, or where they are pinned.
    With sides, those on these sides only, as one is added to or taken off them: the others
    stand as they were."""
    _layingOut[0] += 1
    try:
        _layout(job, sides)
    finally:
        _layingOut[0] -= 1


class _StockWatch:
    """A Job's stock changed, its model taller or moved, its extents set, another made: its stops
    and clamps kept where they stand on the table once the recompute is done, only as high as
    the stock now needs; those whose settings an expression changed as the document recomputed
    placed again. Not for what placing them changes itself, nor while a document loads or
    undoes."""

    def __init__(self):
        self.pending = set()
        self.changed = set()

    def slotChangedObject(self, obj, prop):
        if prop not in ("Shape", "Placement") or layingOut():
            return
        doc = obj.Document
        if doc is None or doc.Restoring or doc.Transacting:
            return
        for job in doc.Objects:
            if getattr(job, "Stock", None) is obj and itemsOf(job):
                self.changed.add((doc.Name, job.Name))

    def slotRecomputedDocument(self, doc):
        changed = [name for docName, name in self.changed if docName == doc.Name]
        self.changed = {key for key in self.changed if key[0] != doc.Name}
        for name in changed:
            job = doc.getObject(name)
            if job is not None and getattr(job, "Stock", None) is not None:
                keepOnTable(job)
        jobs = [name for docName, name in self.pending if docName == doc.Name]
        self.pending = {key for key in self.pending if key[0] != doc.Name}
        for name in jobs:
            job = doc.getObject(name)
            if job is not None and getattr(job, "Stock", None) is not None:
                layout(job)


_stockWatch = None


def _watchStock():
    global _stockWatch
    if _stockWatch is None:
        _stockWatch = _StockWatch()
        FreeCAD.addDocumentObserver(_stockWatch)


_watchStock()


# the top and bottom of each Job's stock its stops and clamps were last stood for
_stockHeights = {}


def keepOnTable(job):
    """keepOnTable(job) ... the Job's stops and clamps kept where they stand on the table as its
    stock changes: placed round it again for how high they stand and what they reach over, then
    put back where they were across the table and turned as they were, and left free there."""
    pieces = [
        p
        for p in itemsOf(job)
        if not PathWorkholding.isShared(p) and getattr(p, "Kind", None) != Kind.Table
    ]
    if not pieces:
        return
    # how high they stand follows only the stock's top and bottom: unchanged, as when it is only
    # slid or turned, they are left as they stand, free
    box = stockBox(job)
    heights = (round(box.ZMin, 6), round(box.ZMax, 6))
    key = (job.Document.Name, job.Name)
    if _stockHeights.get(key) == heights:
        for piece in pieces:
            setFree(piece, True)
        return
    _stockHeights[key] = heights
    before = {p.Name: FreeCAD.Placement(p.Placement) for p in pieces}
    for piece in pieces:
        setFree(piece, False)
    layout(job)
    _layingOut[0] += 1
    try:
        for piece in pieces:
            was = before[piece.Name]
            piece.Placement = FreeCAD.Placement(
                Vector(was.Base.x, was.Base.y, piece.Placement.Base.z), was.Rotation
            )
            setFree(piece, True)
    finally:
        _layingOut[0] -= 1
    PathWorkholding.recompute(job.Document)


def layoutLater(job):
    """layoutLater(job) ... the Job's stops and clamps placed again once the recompute running
    is done: a setting changed by an expression while it runs."""
    _watchStock()
    _stockWatch.pending.add((job.Document.Name, job.Name))


def _layout(job, sides=None):
    shared = [p for p in stopsOn(job) if PathWorkholding.isShared(p)]
    if shared and sides is None:
        _toShared(job, shared)
    for test in (isStop, isClamp):
        bySide = {}
        for piece in _on(job, test):
            bySide.setdefault(piece.StockSide, []).append(piece)
        for side, group in bySide.items():
            if sides is not None and side not in sides:
                continue
            try:
                frame, length = sideFrame(job, side)
            except ValueError as e:
                Path.Log.warning(str(e))
                continue
            # one let go free stays where it was let go, out of the spreading
            group = [p for p in group if not isFree(p)]
            if not group:
                continue
            for piece, x in zip(group, _slots(job, group, frame, length)):
                if piece not in shared:
                    _placeAt(job, piece, frame, _alongSide(job, piece, frame, x))
    PathWorkholding.recompute(job.Document)


def isFree(piece):
    """isFree(piece) ... whether the piece stays where it was let go, not placed against the
    stock or spread along its side with the others: dragged with Shift held."""
    return bool(getattr(piece, "Free", False))


def setFree(piece, free=True):
    """setFree(piece, free=True) ... the piece left where it is, not placed against the stock or
    spread along its side, until it is moved or set again; free False, placed as before."""
    if not hasattr(piece, "Free"):
        if not free:
            return
        piece.addProperty(
            "App::PropertyBool",
            "Free",
            "Placed",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Left where it was let go, not placed against the stock or spread along its side",
            ),
        )
    if piece.Free != free:
        piece.Free = free


def _remove(piece):
    """The piece taken out of the document, no longer shared, its parts with it."""
    PathWorkholding.release(piece)
    doc = piece.Document
    for child in list(getattr(piece, "Group", []) or []):
        doc.removeObject(child.Name)
    doc.removeObject(piece.Name)


def removePiece(piece):
    """removePiece(piece) ... a stop, clamp or table taken out of its Job, no longer shared: those
    left on its side spread along it again."""
    removePieces([piece])


def removePieces(pieces):
    """removePieces(pieces) ... stops, clamps or tables taken out of their Job together, no longer
    shared: those left on their sides spread along them again, once."""
    jobs, docs, sides = [], [], {}
    for each in pieces:
        job, piece = PathWorkholding.memberOf(each)
        if piece is None:
            raise ValueError("Not a piece of a Job's workholding")
        side, stop = getattr(piece, "StockSide", ""), isStop(piece)
        _remove(piece)
        if job.Document not in docs:
            docs.append(job.Document)
        if side:
            for i, other in enumerate((stopsOn if stop else clampsOn)(job, side)):
                other.SideIndex = i
            if job not in jobs:
                jobs.append(job)
            sides.setdefault(job.Name, set()).add(side)
    for job in jobs:
        layout(job, sides[job.Name])
    for doc in docs:
        PathWorkholding.recompute(doc)


def positionOf(piece):
    """positionOf(piece) ... where a stop or clamp is along its side, where it touches the stock:
    its Job X on the front or back, its Job Y on the left or right."""
    job, piece = PathWorkholding.memberOf(piece)
    if piece is None or not isPlaced(piece):
        raise ValueError("Not a stop or clamp placed by side")
    axis, _ = sideAxis(job, piece.StockSide)
    return PathWorkholding.placementOf(piece).Base[axis]


def setPosition(piece, position):
    """setPosition(piece, position) ... a stop or clamp put at position along its side, its Job X
    on the front or back, its Job Y on the left or right, no further than the side's ends, and
    pinned there: it stays as the side's count or the stock's size changes, kept from the stock's
    near end. A shared stop stays
    where it is: it cannot be put elsewhere. Those on its side placed again."""
    job, piece = PathWorkholding.memberOf(piece)
    if piece is None or not isPlaced(piece):
        raise ValueError("Not a stop or clamp placed by side")
    setFree(piece, False)
    if PathWorkholding.isShared(piece):
        raise ValueError(
            translate("CAM", "%s is shared with another Job: it stays where it is") % piece.Label
        )
    axis, way = sideAxis(job, piece.StockSide)
    frame, _ = sideFrame(job, piece.StockSide)
    piece.Pinned = True
    # no further past the side's ends than leaves some of it across from the stock to touch
    low, high = _alongLimits(job, piece)
    at = min(max((position - frame.Base[axis]) * way, low), high)
    piece.Along = frame.Base[axis] + at * way - _stockStart(job, axis)
    # its side only: one moved off another left those there where they are
    layout(job, [piece.StockSide])


def canTransform(piece):
    """canTransform(piece) ... whether FreeCAD's Transform may move the piece, its new placement
    kept as its settings: a lever clamp across the table and round where it presses, one placed
    against a side along that side. Not a shared stop, which stays where the other Job has it,
    nor the table."""
    if piece is None or PathWorkholding.isShared(piece):
        return False
    return PathLever.isLever(piece) or isPlaced(piece)


def fromTransform(piece, at=None):
    """fromTransform(piece, at=None) ... a stop or clamp moved by FreeCAD's Transform kept where
    it was moved to, as its settings: a lever clamp pressing where its placement's origin now is
    and turned as it now is; one placed against a side moved to the side of the stock nearest
    where it meets the stock, at, its placement when not given, and pinned there along it, a side
    clamp turned as it now is, keeping its angle to a side it is moved to. Placed again from them.
    A ValueError, the piece put back, for a side it cannot go on."""
    job, piece = PathWorkholding.memberOf(piece)
    if piece is None or not canTransform(piece):
        return
    setFree(piece, False)
    if PathLever.isLever(piece):
        PathLever.fromPlacement(job, piece)
        return
    placement = PathWorkholding.placementOf(piece)
    at = at or placement
    side = _nearestSide(job, at.Base, piece.StockSide)
    moved = side is not None and side != piece.StockSide
    if moved:
        try:
            _checkSide(job, side, isStop(piece), piece.Kind == Kind.Push, piece)
        except ValueError:
            layout(job)
            raise
        _moveToSide(job, piece, side)
    if piece.Kind == Kind.Push and not moved:
        _setAngle(piece, angleFrom(job, piece, placement.Rotation))
    axis, _ = sideAxis(job, piece.StockSide)
    setPosition(piece, at.Base[axis])


def _nearestSide(job, point, current):
    """The part's own side, as sides names it, whose side of the stock's box is nearest point
    seen from above, its ends and corners as they are: past a corner as near the one side as the
    other, current kept."""
    bb = stockBox(job)
    x0, x1, y0, y1 = bb.XMin, bb.XMax, bb.YMin, bb.YMax
    cx, cy = min(max(point.x, x0), x1), min(max(point.y, y0), y1)
    near = {
        "-Y": math.hypot(point.x - cx, point.y - y0),
        "+Y": math.hypot(point.x - cx, point.y - y1),
        "-X": math.hypot(point.x - x0, point.y - cy),
        "+X": math.hypot(point.x - x1, point.y - cy),
    }
    found = {}
    for side in sides(job):
        world = sideDirection(job, side)
        for name, direction in PathWorkholding.Directions.items():
            if name in near and (direction - world).Length < 1e-6:
                found[side] = near[name]
    if not found:
        return None
    best = min(found.values())
    if current in found and found[current] <= best + 1e-6:
        return current
    return min(found, key=found.get)


def setAngle(piece, angle):
    """setAngle(piece, angle) ... a side clamp turned angle degrees from square to its side,
    pushing at a slant, and placed again."""
    job, piece = PathWorkholding.memberOf(piece)
    if piece is None or piece.Kind != Kind.Push:
        return
    setFree(piece, False)
    _setAngle(piece, angle)
    layout(job)


def angleFrom(job, piece, rotation):
    """angleFrom(job, piece, rotation) ... how far a piece turned by rotation is turned from
    square to its side, -180 to 180 degrees; a lever clamp's Angle."""
    if PathLever.isLever(piece):
        return PathLever.angleFrom(job, piece, rotation)
    frame, _ = sideFrame(job, piece.StockSide)
    facing = rotation.multVec(Vector(1, 0, 0))
    along = frame.Rotation.multVec(Vector(1, 0, 0))
    angle = math.degrees(math.atan2(facing.y, facing.x) - math.atan2(along.y, along.x))
    angle = (angle + 180.0) % 360.0 - 180.0
    # square, not a hair either side of it shown as -0.00
    return 0.0 if abs(angle) < 1e-9 else angle


def _moveToSide(job, piece, side):
    """The piece put on another side, last along it, those left on its old side counted again;
    those on either side stay where they are."""
    old = piece.StockSide
    on = stopsOn if isStop(piece) else clampsOn
    _pinWhereTheyAre(job, [p for p in on(job, old) + on(job, side) if p != piece])
    piece.SideIndex = len(on(job, side))
    piece.StockSide = side
    for i, other in enumerate(on(job, old)):
        other.SideIndex = i


def _pinWhereTheyAre(job, pieces):
    """Those spread along a side pinned where they are now, as no longer spread: one moved onto
    or off the side moves none of them."""
    box = stockBox(job)
    for piece in pieces:
        if getattr(piece, "Pinned", False) or PathWorkholding.isShared(piece):
            continue
        base = PathWorkholding.placementOf(piece).Base
        if PathLever.isLever(piece):
            piece.Proxy.placing = True
            try:
                piece.Pinned = True
                piece.PressX = base.x - box.XMin
                piece.PressY = base.y - box.YMin
            finally:
                piece.Proxy.placing = False
            continue
        axis, _ = sideAxis(job, piece.StockSide)
        piece.Pinned = True
        piece.Along = base[axis] - _stockStart(job, axis)


def _setAngle(piece, angle):
    """How far a side clamp is turned from square to its side, kept on it."""
    if not hasattr(piece, "Angle"):
        piece.addProperty(
            "App::PropertyAngle",
            "Angle",
            "Placed",
            QT_TRANSLATE_NOOP(
                "App::Property", "How far it is turned from square to its side, pushing at a slant"
            ),
        )
    piece.Angle = angle


def checkStopSides(job, stopSides):
    """checkStopSides(job, stopSides) ... a ValueError unless stops can go on the part's sides
    given, as sides names them: standing round the stock, one side, or two next to each other."""
    standing = sides(job)
    for side in stopSides:
        if side not in standing:
            raise ValueError(
                translate("CAM", "The part's %s side faces up or down: nothing goes against it")
                % side
            )
    if len(set(stopSides)) != len(stopSides):
        raise ValueError(translate("CAM", "Stops go on a side once"))
    if len(stopSides) > 2:
        raise ValueError(
            translate("CAM", "Stops go on one side of the stock, or two next to each other")
        )
    if len(stopSides) == 2 and not adjacent(*stopSides):
        raise ValueError(
            translate(
                "CAM",
                "Stops on opposite sides jam the stock between them: put them on one side, or two "
                "next to each other",
            )
        )


def setStops(job, stops):
    """setStops(job, stops) ... the Job's stops as stops says, a list of a dict a side: side, the
    part's own as sides names it; which, the class of stop, one of StopClasses; count, how many
    along the side, one when not given. Or, in place of which, share, a stop of another Job to share on that
    side. One side, or two next to each other, a corner: stock pushed onto stops on opposite
    sides is not held but jammed. Stops on other sides are taken away, those on a side made anew
    of what it says now, each keeping where it is pinned. They are put against the stock where
    it is; one shared stays where it is, the part moving to it. Returns the stops."""
    stops = [dict(spec) for spec in stops]
    checkStopSides(job, [spec["side"] for spec in stops])
    wanted = {spec["side"] for spec in stops}
    for piece in stopsOn(job):
        if piece.StockSide not in wanted:
            _remove(piece)
    shares = []
    for spec in stops:
        side = spec["side"]
        current = stopsOn(job, side)
        owner = spec.get("share")
        if owner is not None:
            owner = PathWorkholding.ownerOf(owner)
            if not (len(current) == 1 and getattr(current[0], "Follows", None) == owner):
                for piece in current:
                    _remove(piece)
                shares.append((owner, side))
            continue
        which = spec.get("which") or "Dog"
        if which not in StopClasses:
            raise ValueError("A stop is one of %s: not %s" % (", ".join(StopClasses), which))
        count = max(1, int(spec.get("count") or 1))
        # made of something else, or following another Job's: made anew
        if any(p.Source != which or PathWorkholding.isFollower(p) for p in current):
            for piece in current:
                _remove(piece)
            current = []
        for piece in current[count:]:
            _remove(piece)
        current = current[:count]
        if len(current) < count:
            _, length = sideFrame(job, side)
        while len(current) < count:
            piece = create(job, which)
            if which == "Fence":
                # along its share of the side
                piece.Length = length / count
            current.append(piece)
        for i, piece in enumerate(current):
            _setRole(piece, side, i, which)
    for owner, side in shares:
        shareStop(owner, job, side)
    layout(job)
    return stopsOn(job)


def _checkSide(job, side, stop, pushing, moving=None):
    """A ValueError unless a stop, or a clamp pushing on the stock's side or not, can go on side,
    the piece moving left out of those there: stops on one side or two next to each other, no
    side clamp on a side with stops."""
    if side not in sides(job):
        raise ValueError(
            translate("CAM", "The part's %s side faces up or down: nothing goes against it") % side
        )
    stopSides = {p.StockSide for p in stopsOn(job) if p != moving}
    if stop:
        checkStopSides(job, sorted(stopSides | {side}))
        if any(pushes(p.Source) for p in clampsOn(job, side) if p != moving):
            raise ValueError(
                translate(
                    "CAM",
                    "A side clamp is on that side: it would push the part off stops there",
                )
            )
    elif pushing and side in stopSides:
        raise ValueError(
            translate(
                "CAM",
                "A side clamp pushes the part onto the stops: not on a side with stops, it "
                "would push it off them",
            )
        )


def _isShare(which):
    """Whether which, what an add puts in, is another Job's stop to share: the stop itself, or
    ("share", its name)."""
    return hasattr(which, "TypeId") or isinstance(which, (tuple, list))


def addPieces(job, side, which, count=1):
    """addPieces(job, side, which, count=1) ... count stops or clamps of which put on the part's
    side, as sides names it, and spread along it with those there not moved elsewhere. which is
    one of StopClasses or ClampClasses, the path of a clamp's own file, or another Job's stop to
    share, the stop or ("share", its name). Refused with a ValueError as setStops and setClamps
    refuse: stops on one side or two next to each other, no side clamp on a side with stops.
    Returns the new pieces."""
    count = max(1, int(count or 1))
    if side not in sides(job):
        raise ValueError(
            translate("CAM", "The part's %s side faces up or down: nothing goes against it") % side
        )
    if _isShare(which):
        owner = which
        if isinstance(which, (tuple, list)):
            owner = job.Document.getObject(which[1])
        if owner is None:
            raise ValueError(translate("CAM", "The stop to share is gone"))
        return [shareStop(owner, job, side)]
    stop = which in StopClasses
    if not stop and which not in ClampClasses and clampFile(which) is None:
        raise ValueError(translate("CAM", "%s holds no clamp") % os.path.basename(str(which)))
    _checkSide(job, side, stop, not stop and pushes(which))
    current = (stopsOn if stop else clampsOn)(job, side)
    new = []
    hidden = []
    for i in range(count):
        piece = create(job, which) if which in Classes else addClamp(job, which)
        # out of sight until placed: drawn where it goes, not first at the Job's origin
        for obj in [piece] + list(getattr(piece, "Group", []) or []):
            if hasattr(obj, "Visibility"):
                hidden.append((obj, obj.Visibility))
                obj.Visibility = False
        _setRole(piece, side, len(current) + i, which)
        new.append(piece)
    if which == "Fence":
        # along their share of the side
        _, length = sideFrame(job, side)
        for piece in new:
            piece.Length = length / (len(current) + count)
    # only their side placed again: the others stand as they were
    try:
        layout(job, [side])
    finally:
        for obj, shown in hidden:
            obj.Visibility = shown
    return new


def _sideAt(job, point):
    """The part's own side, as sides names it, whose side of the stock's box is nearest point,
    seen from above."""
    bb = stockBox(job)
    near = {
        "-Y": abs(point.y - bb.YMin),
        "+Y": abs(point.y - bb.YMax),
        "-X": abs(point.x - bb.XMin),
        "+X": abs(point.x - bb.XMax),
    }
    world = PathWorkholding.Directions[min(near, key=near.get)]
    for side in sides(job):
        if (sideDirection(job, side) - world).Length < 1e-6:
            return side
    return None


def edgeOf(job, piece):
    """edgeOf(job, piece) ... the part's own side a stop or clamp is at now, as sides names it:
    the side of the stock nearest where it touches it, wherever it was first put; None for the
    table under the stock."""
    if getattr(piece, "Kind", None) == Kind.Table:
        return None
    return _sideAt(job, PathWorkholding.placementOf(piece).Base)


def sideOfShape(job, shape):
    """sideOfShape(job, shape) ... the part's own side an edge or face of the stock picked in the
    3D view is on, as sides names it, the shape where it stands. A ValueError for a face looking
    up or down."""
    if shape.ShapeType == "Face":
        u0, u1, v0, v1 = shape.ParameterRange
        normal = shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        if abs(normal.z) > 0.5:
            raise ValueError(
                translate("CAM", "That face of the stock looks up or down: nothing goes on it")
            )
    side = _sideAt(job, shape.BoundBox.Center)
    if side is None:
        raise ValueError(translate("CAM", "Nothing goes against that side of the stock"))
    return side


def pushes(which):
    """pushes(which) ... whether a clamp made as which, one of ClampClasses or the path of a
    clamp's own file, pushes on the stock's side, a side clamp."""
    if which in Classes:
        return which == "SideClamp"
    found = clampFile(which)
    return found is not None and found[1] == Kind.Push


def _sameSource(a, b):
    if a == b:
        return True
    try:
        return a not in Classes and b not in Classes and os.path.samefile(a, b)
    except OSError:
        return False


def setClamps(job, clamps):
    """setClamps(job, clamps) ... the Job's clamps as clamps says, a list of a dict a side: side,
    the part's own as sides names it; which, one of ClampClasses or the path of a clamp's own
    file; count, how many along the side, one when not given. A side
    clamp pushes the part onto the stops: never on a side with stops, it would push it off them.
    Clamps on sides not given are taken away, those on a side made anew of what it says now. They
    are put against the stock where it is. Returns the clamps."""
    clamps = [dict(spec) for spec in clamps if spec.get("which") and spec.get("count", 1)]
    standing = sides(job)
    stopSides = {p.StockSide for p in stopsOn(job)}
    wanted = set()
    for spec in clamps:
        side = spec["side"]
        if side not in standing:
            raise ValueError(
                translate("CAM", "The part's %s side faces up or down: nothing goes against it")
                % side
            )
        if side in wanted:
            raise ValueError(translate("CAM", "Clamps of one kind a side"))
        wanted.add(side)
        if pushes(spec["which"]) and side in stopSides:
            raise ValueError(
                translate(
                    "CAM",
                    "A side clamp pushes the part onto the stops: not on a side with stops, it "
                    "would push it off them",
                )
            )
    for piece in clampsOn(job):
        if piece.StockSide not in wanted:
            _remove(piece)
    for spec in clamps:
        side, which = spec["side"], spec["which"]
        count = max(1, int(spec.get("count") or 1))
        current = clampsOn(job, side)
        if any(not _sameSource(p.Source, which) for p in current):
            for piece in current:
                _remove(piece)
            current = []
        for piece in current[count:]:
            _remove(piece)
        current = current[:count]
        while len(current) < count:
            current.append(create(job, which) if which in Classes else addClamp(job, which))
        for i, piece in enumerate(current):
            _setRole(piece, side, i, which)
    layout(job)
    return clampsOn(job)


def _bySide(job, pieces):
    bySide = {}
    for piece in pieces:
        bySide.setdefault(piece.StockSide, []).append(piece)
    return bySide


def stopsOf(job):
    """stopsOf(job) ... the Job's stops as setStops takes them, read from the stops themselves: a
    dict a side, the side with most stops first. A side whose stop follows another Job's has
    share, that stop, in place of which; one whose stop another Job shares has sharedWith, that
    Job, in a list."""
    found = []
    for side, group in _bySide(job, stopsOn(job)).items():
        follower = next((p for p in group if PathWorkholding.isFollower(p)), None)
        if follower is not None:
            spec = {"side": side, "share": follower.Follows, "count": len(group)}
        else:
            spec = {"side": side, "which": group[0].Source, "count": len(group)}
        others = [
            j
            for p in group
            if not PathWorkholding.isFollower(p)
            for j in PathWorkholding.sharedWith(p)
        ]
        if others:
            spec["sharedWith"] = others
        found.append(spec)
    return sorted(found, key=lambda spec: -spec["count"])


def clampsOf(job):
    """clampsOf(job) ... the Job's clamps as setClamps takes them, read from the clamps: a dict a
    side."""
    return [
        {"side": side, "which": group[0].Source, "count": len(group)}
        for side, group in _bySide(job, clampsOn(job)).items()
    ]


def _jobsOf(doc):
    import Path.Main.Job as PathJob

    return [
        o for o in doc.Objects if hasattr(o, "Proxy") and isinstance(o.Proxy, PathJob.ObjectJob)
    ]


def canShareStop(stop, job=None):
    """canShareStop(stop, job=None) ... whether another Job, job if given, can share the stop: a
    dog or a fence placed by side, its other face free, job not the one it is of."""
    owner = PathWorkholding.ownerOf(stop)
    if not isStop(owner) or getattr(owner, "Source", "") not in StopClasses:
        return False
    if not isPlaced(owner) or PathWorkholding.memberOf(owner)[0] is None:
        return False
    # a part against each of its two faces
    group = PathWorkholding.shareGroup(owner)
    if len(group) > 1:
        return False
    return job is None or all(PathWorkholding.memberOf(o)[0] != job for o in group)


def shareableStops(job):
    """shareableStops(job) ... the stops of other Jobs job can share, their owners."""
    found = []
    for other in _jobsOf(job.Document):
        if other == job:
            continue
        for stop in stopsOn(other):
            owner = PathWorkholding.ownerOf(stop)
            if owner not in found and canShareStop(owner, job):
                found.append(owner)
    return found


def shareStop(owner, job, side):
    """shareStop(owner, job, side) ... the stop owner, of another Job, shared with job against
    the part's side, as sides names it: a stop of job's own placed by expression on the owner's
    other face and as big, its Contact the other. The stop stays where it is: the part moves to
    it, turned so that side faces it, the stop in the middle of the side. Returns the new stop."""
    owner = PathWorkholding.ownerOf(owner)
    if not canShareStop(owner, job):
        raise ValueError(
            translate("CAM", "%s cannot be shared with %s: a part is against each of its faces")
            % (owner.Label, job.Label)
        )
    if stopsOn(job, side):
        raise ValueError(translate("CAM", "%s has stops on that side already") % job.Label)
    checkStopSides(job, sorted({p.StockSide for p in stopsOn(job)}) + [side])
    if not hasattr(owner, "Contact"):
        _addContact(owner, 1)
    stop = create(job, owner.Source)
    _addContact(stop, 2 if owner.Contact == 1 else 1)
    _setRole(stop, side, 0, owner.Source)
    PathWorkholding._follow(stop, owner)
    layout(job)
    return stop


def addTable(job):
    """addTable(job) ... the table under the Job's stock: one put in its Workholding if it has
    none, else the one it has, placed under the stock again. Returns it."""
    tables = [o for o in itemsOf(job) if getattr(o, "Kind", None) == Kind.Table]
    table = tables[0] if tables else create(job, "Table")
    placeTable(job, table)
    PathWorkholding.recompute(job.Document)
    return table


def clampFacts(path):
    """clampFacts(path) ... what a clamp's own file says of it, read without opening it: its Kind,
    and its Width, Reach, MinStockThickness and MaxStockThickness in mm and its Thread, those it
    gives. Empty if it holds no clamp."""
    root = readDocumentXml(path)
    if root is None:
        return {}
    for _, props in varsetProperties(root, objectKinds(root)):
        kind = props.get("Kind")
        if kind is None or kind.find("String") is None:
            continue
        if kind.find("String").get("value") not in CLAMP_KINDS:
            continue
        facts = {"Kind": kind.find("String").get("value")}
        for name in ("Width", "Reach", "MinStockThickness", "MaxStockThickness"):
            value = props.get(name)
            number = value.find("Float") if value is not None else None
            if number is not None:
                facts[name] = float(number.get("value"))
        thread = props.get("Thread")
        if thread is not None and thread.find("String") is not None:
            facts["Thread"] = thread.find("String").get("value")
        return facts
    return {}


def clampFile(path):
    """clampFile(path) ... the clamp a clamp's own file holds, read from the file without opening
    it: its name, the file's, and its Kind, HoldDown, Push, Lever or StrapKit, a strap clamp kit.
    None if it holds none: no part, or no VarSet saying it is one of those."""
    root = readDocumentXml(path)
    if root is None:
        return None
    types = objectKinds(root)
    # the first VarSet saying it is a clamp: the pieces of a kit have Kinds of their own
    kind = None
    for _, props in varsetProperties(root, types):
        prop = props.get("Kind")
        if prop is not None and prop.find("String") is not None:
            if prop.find("String").get("value") in CLAMP_KINDS:
                kind = prop.find("String").get("value")
                break
    if kind not in CLAMP_KINDS or "App::Part" not in types.values():
        return None
    return os.path.splitext(os.path.basename(path))[0].replace("_", " "), kind


def _kindIn(container):
    for o in getattr(container, "Group", []) or []:
        if o.TypeId == "App::VarSet" and hasattr(o, "Kind"):
            return o.Kind
    return None


def clampIn(doc):
    """clampIn(doc) ... the clamp a clamp's own file holds: its outermost container with a
    VarSet whose Kind is HoldDown, Push or Lever, or None."""
    for obj in doc.RootObjects:
        if obj.hasExtension("App::GeoFeatureGroupExtension") and _kindIn(obj) in (
            Kind.HoldDown,
            Kind.Push,
            Kind.Lever,
        ):
            return obj
    return None


def addClamp(job, path):
    """addClamp(job, path) ... a clamp put in the Job's Workholding from the clamp's own file at
    path, as a vise is: its parts linked from the file, its settings copied onto it. setClamps
    places it. A lever clamp, from its own file or a strap clamp kit, is made by
    Path.Workholding.Lever. Returns it."""
    found = clampFile(path)
    if found is not None and found[1] in (Kind.Lever, Kind.StrapKit):
        return PathLever.addLever(job, path)
    source = clampIn(PathSource.openFile(path, job.Document)[0])
    if source is None:
        raise ValueError(
            translate("CAM", "%s holds no clamp: a part with a VarSet giving its Kind")
            % os.path.basename(path)
        )
    members = PathWorkholding.sourceMembers(source)
    return PathWorkholding._instance(
        job, source.Label, members, FreeCAD.Placement(), ObjectClamp, "Clamp"
    )
