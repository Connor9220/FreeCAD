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
from Path.Workholding.Common import objectKinds, readDocumentXml, varsetProperties
from Path.Workholding.Constants import CLAMP_KINDS
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
    bb = job.Stock.Shape.BoundBox
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


def sideFrame(job, side):
    """sideFrame(job, side) ... the frame of the stock's side, the part's own side as sides names
    it, and how long the side is: its origin in the middle of the side on the surface the stock
    lies on, its +X along the side, its +Y into the stock, its +Z up. A stop or a side clamp is
    put in it as it is laid out, a hold-down as high up as the stock's top."""
    out = sideDirection(job, side)
    bb = job.Stock.Shape.BoundBox
    inward = out * -1
    along = inward.cross(Vector(0, 0, 1))
    middle = Vector(bb.Center.x, bb.Center.y, bb.ZMin)
    half = abs(out.x) * bb.XLength / 2 + abs(out.y) * bb.YLength / 2
    length = abs(along.x) * bb.XLength + abs(along.y) * bb.YLength
    return FreeCAD.Placement(middle + out * half, _turnOf(along, inward)), length


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
    bb = job.Stock.Shape.BoundBox
    return bb.XMin if axis == 0 else bb.YMin


def _alongSide(job, piece, frame, x):
    """Where along its side, in the side's frame, the piece goes: where it is pinned, else x,
    where it is spread to."""
    if not getattr(piece, "Pinned", False):
        return x
    axis, way = sideAxis(job, piece.StockSide)
    return (_stockStart(job, axis) + piece.Along.Value - frame.Base[axis]) * way


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
    placement = frame.multiply(FreeCAD.Placement(Vector(x, 0, 0), FreeCAD.Rotation()))
    if piece.Kind == Kind.HoldDown:
        height = job.Stock.Shape.BoundBox.ZLength
        placement = FreeCAD.Placement(placement.Base + Vector(0, 0, height), placement.Rotation)
        if hasattr(piece, "Drop") and abs(piece.Drop.Value - height) > 1e-9:
            piece.Drop = height
    if not piece.Placement.isSame(placement, 1e-9):
        piece.Placement = placement


def _toShared(job, shared):
    """The part moved to the stops it shares with another Job, which stay where they are: turned
    so the side against the first faces it, then moved so the first is where it is spread to
    along that side, the stock touching it and its bottom on the surface the stop stands on;
    then onto the others, square to their faces."""
    # those following another placed where it is
    job.Document.recompute()
    for i, stop in enumerate(shared):
        # the stock's side faces out against the stop's face
        face = stop.Placement.Rotation.multVec(Vector(0, -1, 0))
        if i == 0:
            out = sideDirection(job, stop.StockSide)
            if (out - face).Length > 1e-6:
                angle = math.degrees(math.atan2(out.cross(face).z, out.dot(face)))
                PathWorkholding.turnModel(
                    job, FreeCAD.Rotation(Vector(0, 0, 1), angle), job.Stock.Shape.BoundBox.Center
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


def layout(job):
    """layout(job) ... the Job's stops and clamps placed round its stock as each says: a stop
    shared with another Job stays where it is, the part moving to it first; the rest are put
    against the stock where it then is, spread along their sides, or where they are pinned."""
    shared = [p for p in stopsOn(job) if PathWorkholding.isShared(p)]
    if shared:
        _toShared(job, shared)
    for test in (isStop, isClamp):
        bySide = {}
        for piece in _on(job, test):
            bySide.setdefault(piece.StockSide, []).append(piece)
        for side, group in bySide.items():
            try:
                frame, length = sideFrame(job, side)
            except ValueError as e:
                Path.Log.warning(str(e))
                continue
            for piece, x in zip(group, spread(length, len(group))):
                if piece not in shared:
                    _placeAt(job, piece, frame, _alongSide(job, piece, frame, x))
    job.Document.recompute()


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
    job, piece = PathWorkholding.memberOf(piece)
    if piece is None:
        raise ValueError("Not a piece of a Job's workholding")
    side, stop = getattr(piece, "StockSide", ""), isStop(piece)
    _remove(piece)
    if side:
        for i, other in enumerate((stopsOn if stop else clampsOn)(job, side)):
            other.SideIndex = i
        layout(job)
    job.Document.recompute()


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
    on the front or back, its Job Y on the left or right, and pinned there: it stays as the
    side's count or the stock's size changes, kept from the stock's near end. A shared stop stays
    where it is: it cannot be put elsewhere. The rest placed again."""
    job, piece = PathWorkholding.memberOf(piece)
    if piece is None or not isPlaced(piece):
        raise ValueError("Not a stop or clamp placed by side")
    if PathWorkholding.isShared(piece):
        raise ValueError(
            translate("CAM", "%s is shared with another Job: it stays where it is") % piece.Label
        )
    axis, _ = sideAxis(job, piece.StockSide)
    piece.Pinned = True
    piece.Along = position - _stockStart(job, axis)
    layout(job)


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
    job.Document.recompute()
    return table


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
