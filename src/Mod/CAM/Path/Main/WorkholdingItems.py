# SPDX-License-Identifier: LGPL-2.1-or-later

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

- a Stop, a dog in the table, the stock pushed against it;
- a Push, a side clamp pushing the stock onto the stops;
- a HoldDown, a clamp over the stock's top edge, an EdgeHugger or a toe clamp;
- a Table, the bed the rest stands on: its T-track rails, its dog holes, the waste board the
  stock lies on. Cut into on purpose, it is shown but nothing is found hitting it.

A Stop or a Push has its origin where it touches the stock, on the surface the stock lies on,
its +Y into the stock. A HoldDown has its origin on the stock's top edge, its +Y into the stock,
its lip reaching in over the top and its body standing beside the stock down to the table."""

import FreeCAD
import Part
import Path

from FreeCAD import Vector
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

INCH = 25.4


class Kind:
    Stop = "Stop"
    Push = "Push"
    HoldDown = "HoldDown"
    Table = "Table"


class ObjectItem:
    """A piece of workholding made from a few dimensions."""

    kind = None

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


class ObjectDog(ObjectItem):
    """A dog: a round pin standing in a hole of the table."""

    kind = Kind.Stop

    def addProperties(self, obj):
        self._add(obj, "App::PropertyLength", "Diameter", "Across the pin", 0.75 * INCH)
        self._add(obj, "App::PropertyLength", "Height", "Above the table", 0.5 * INCH)

    def shape(self, obj):
        r = obj.Diameter.Value / 2
        return Part.makeCylinder(r, obj.Height.Value, Vector(0, -r, 0))


class ObjectSideClamp(ObjectItem):
    """A side clamp: a block pushing on the stock's side, a cam or wedge clamp."""

    kind = Kind.Push

    def addProperties(self, obj):
        self._add(obj, "App::PropertyLength", "Width", "Along the stock's side", 2.0 * INCH)
        self._add(obj, "App::PropertyLength", "Depth", "Away from the stock", 1.5 * INCH)
        self._add(obj, "App::PropertyLength", "Height", "Above the table", 0.5 * INCH)

    def shape(self, obj):
        w, d, h = obj.Width.Value, obj.Depth.Value, obj.Height.Value
        return Part.makeBox(w, d, h, Vector(-w / 2, -d, 0))


class ObjectEdgeClamp(ObjectItem):
    """A hold-down over the stock's top edge: its body beside the stock on the table, its lip
    over the top. As an EdgeHugger: 0.22 in above the stock, reaching 0.23 in over it."""

    kind = Kind.HoldDown

    def addProperties(self, obj):
        self._add(obj, "App::PropertyLength", "Width", "Along the stock's edge", 1.0 * INCH)
        self._add(obj, "App::PropertyLength", "Depth", "Its body, away from the stock", 0.75 * INCH)
        self._add(obj, "App::PropertyLength", "Reach", "Over the stock's top", 0.23 * INCH)
        self._add(obj, "App::PropertyLength", "Rise", "Above the stock's top", 0.22 * INCH)
        self._add(
            obj,
            "App::PropertyLength",
            "Drop",
            "From the stock's top down to the table",
            0.75 * INCH,
        )

    def shape(self, obj):
        w, d = obj.Width.Value, obj.Depth.Value
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
        self._add(obj, "App::PropertyLength", "Length", "Along X", 96 * INCH)
        self._add(obj, "App::PropertyLength", "Width", "Along Y", 60 * INCH)
        self._add(obj, "App::PropertyLength", "Thickness", "Of the spoilboard", 1.0 * INCH)
        self._add(obj, "App::PropertyLength", "RailSpacing", "Between the rails, in Y", 5 * INCH)
        self._add(obj, "App::PropertyLength", "RailWidth", "Of a rail", 0.75 * INCH)
        self._add(
            obj, "App::PropertyLength", "HoleSpacing", "Between the dog holes, both ways", 4 * INCH
        )
        self._add(obj, "App::PropertyLength", "HoleDiameter", "Of a dog hole", 0.75 * INCH)
        self._add(
            obj,
            "App::PropertyLength",
            "WasteBoard",
            "Of the sheet on the spoilboard the stock lies on, none if 0",
            0.25 * INCH,
        )

    def shape(self, obj):
        length, width = obj.Length.Value, obj.Width.Value
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


Classes = {
    "Dog": ObjectDog,
    "SideClamp": ObjectSideClamp,
    "EdgeClamp": ObjectEdgeClamp,
    "Table": ObjectTable,
}


def create(job, which, name=None):
    """create(job, which, name=None) ... a new piece of workholding of class which, one of
    Classes, in the Job's Workholding."""
    doc = job.Document
    obj = doc.addObject("Part::FeaturePython", name or which)
    Classes[which](obj)
    if FreeCAD.GuiUp:
        import Path.Main.Gui.WorkholdingItems as Gui

        Gui.ViewProvider(obj.ViewObject)
    job.Workholding.addObject(obj)
    return obj


def _stockFrame(job):
    bb = job.Stock.Shape.BoundBox
    return bb.ZMin, bb.ZMax


def placeAgainst(job, item, point, normal):
    """placeAgainst(job, item, point, normal) ... a Stop or a Push touching the stock's side
    whose outward normal is normal, at point along it, standing on the surface the stock lies
    on."""
    normal = Vector(normal.x, normal.y, 0)
    if normal.Length < 1e-9:
        raise ValueError("A stop or a side clamp goes against a side of the stock, not its top")
    normal.normalize()
    bottom, _ = _stockFrame(job)
    rotation = FreeCAD.Rotation(Vector(0, 1, 0), normal * -1)
    item.Placement = FreeCAD.Placement(Vector(point.x, point.y, bottom), rotation)


def placeOnEdge(job, item, point, normal):
    """placeOnEdge(job, item, point, normal) ... a HoldDown over the stock's top edge on the
    side whose outward normal is normal, at point along it, its body down to the table."""
    normal = Vector(normal.x, normal.y, 0)
    if normal.Length < 1e-9:
        raise ValueError("A hold-down goes over an edge of the stock's top")
    normal.normalize()
    bottom, top = _stockFrame(job)
    rotation = FreeCAD.Rotation(Vector(0, 1, 0), normal * -1)
    item.Placement = FreeCAD.Placement(Vector(point.x, point.y, top), rotation)
    if hasattr(item, "Drop"):
        item.Drop = top - bottom


def placeTable(job, table):
    """placeTable(job, table) ... the table under the stock: its waste board's top where the
    stock lies, the stock's front left corner at the table's, inset by a hole spacing."""
    bb = job.Stock.Shape.BoundBox
    inset = table.HoleSpacing.Value if hasattr(table, "HoleSpacing") else 0
    table.Placement = FreeCAD.Placement(
        Vector(bb.XMin - inset, bb.YMin - inset, bb.ZMin), FreeCAD.Rotation()
    )


def onSide(shape, point):
    """onSide(shape, point) ... the side of shape nearest point: its outward normal, and point
    brought onto it. A click on the model, inside the stock, lands on the stock's side."""
    normal = sideAt(shape, point)
    best = min(shape.Faces, key=lambda f: f.distToShape(Part.Vertex(point))[0])
    on = best.distToShape(Part.Vertex(point))[1][0][0]
    # along the side where clicked, on its plane
    return normal, point + normal * (on - point).dot(normal)


def sideAt(shape, point):
    """sideAt(shape, point) ... the outward normal of the face of shape nearest point."""
    best = None
    for face in shape.Faces:
        d = face.distToShape(Part.Vertex(point))[0]
        if best is None or d < best[0]:
            best = (d, face)
    face = best[1]
    u, v = face.Surface.parameter(point)
    n = face.normalAt(u, v)
    # outward: away from the shape's middle, whichever way the face is oriented
    if n.dot(point - shape.BoundBox.Center) < 0:
        n = n * -1
    return n
