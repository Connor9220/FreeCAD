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

"""Soft jaws: a vise's hard jaw plates swapped for blocks the shop cuts to hold a part, plain or
stepped.

A soft jaw stands where the hard plate did, against the jaw's body and on the plate's bottom, as
thick and as tall as the vise says: its SoftThickness, from the body out to its working face, and
its SoftHeight, up from the plate's bottom. Each of its Steps is cut down from its top and in from
its face, the same on both jaws, so the stock stands on a step's floor against its wall. The
fixed jaw's is drawn where it stands, the moving jaw's mirrored and drawn closed: the vise moves it
with its Opening as it does the moving jaw."""

import FreeCAD
import Part
import Path

from FreeCAD import Vector
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

Sides = ["Fixed", "Moving"]

INCH = 25.4
# grip jaws, sized as common ones for a 6 in. vise: a soft steel jaw, a groove along its
# top a little behind its face, and hardened grips in the groove standing proud of its top. The
# stock sits on the jaw's top against the grips' teeth, which bite into it.
GripJaw = {
    "thickness": 0.990 * INCH,
    "height": 1.724 * INCH,
    "grip": 0.060 * INCH,  # how far the grips stand above the jaw's top: what is held
    "setback": 0.120 * INCH,  # the grips' teeth behind the jaw's face
    "bite": 0.015 * INCH,  # how far they bite into the stock
    "grips": 2,  # on each jaw
    "gripLength": 0.75 * INCH,
    "gripWidth": 0.5 * INCH,
    "grooveDepth": 0.190 * INCH,
}


def parseSteps(entries):
    """parseSteps(entries) ... the steps a vise's Steps say, (height, depth) pairs in mm: height
    down from the soft jaw's top, depth in from its face. One that is not two numbers is left out,
    and said so."""
    steps = []
    for entry in entries or []:
        try:
            height, depth = (float(v) for v in str(entry).split(","))
        except ValueError:
            Path.Log.warning(
                translate("CAM", "A step is its height and depth, '5,3': not '%s'") % entry
            )
            continue
        steps.append((height, depth))
    return steps


def softJawShape(size, thickness, height, steps, side):
    """softJawShape(size, thickness, height, steps, side) ... a soft jaw in the vise's frame, the
    hard plate it stands for size, (tH, hH, xMin, xMax): the plate's thickness and height and its
    ends across. The moving jaw's is the fixed one's mirrored, drawn closed."""
    plate, plateHeight, low, high = size
    width = high - low
    face = plate - thickness
    bottom = -plateHeight
    top = bottom + height
    jaw = Part.makeBox(width, thickness, height, Vector(low, face, bottom))
    for h, d in steps:
        if h <= 0 or d <= 0:
            continue
        cut = Part.makeBox(width, d, h, Vector(low, face, top - h))
        jaw = jaw.cut(cut)
    jaw = jaw.removeSplitter()
    if side == "Moving":
        jaw = jaw.mirror(Vector(0, 0, 0), Vector(0, 1, 0))
    return jaw


def gripJawShape(size, thickness, height, setback, side):
    """gripJawShape(size, thickness, height, setback, side) ... a grip jaw in the vise's frame,
    as softJawShape makes a soft one: a block, the groove its grips sit in cut along its top,
    setback behind its face."""
    plate, plateHeight, low, high = size
    width = high - low
    face = plate - thickness
    top = -plateHeight + height
    jaw = Part.makeBox(width, thickness, height, Vector(low, face, -plateHeight))
    groove = Part.makeBox(
        width,
        GripJaw["gripWidth"],
        GripJaw["grooveDepth"],
        Vector(low, face + setback, top - GripJaw["grooveDepth"]),
    )
    jaw = jaw.cut(groove).removeSplitter()
    if side == "Moving":
        jaw = jaw.mirror(Vector(0, 0, 0), Vector(0, 1, 0))
    return jaw


def gripShape(size, thickness, height, grip, setback, count, index, side):
    """gripShape(size, thickness, height, grip, setback, count, index, side) ... the index'th
    of count grips on a grip jaw, spread evenly across it: hardened, in the jaw's groove, its
    teeth setback behind the jaw's face, standing grip above the jaw's top."""
    plate, plateHeight, low, high = size
    face = plate - thickness
    top = -plateHeight + height
    centre = low + (high - low) * (index + 0.5) / count
    shape = Part.makeBox(
        GripJaw["gripLength"],
        GripJaw["gripWidth"],
        GripJaw["grooveDepth"] + grip,
        Vector(centre - GripJaw["gripLength"] / 2, face + setback, top - GripJaw["grooveDepth"]),
    )
    if side == "Moving":
        shape = shape.mirror(Vector(0, 0, 0), Vector(0, 1, 0))
    return shape


class ObjectSoftJaw:
    """A soft jaw of a vise of a Job's Workholding, made from the vise's settings: its jaws, the
    hard plate it stands for, and the side it is on."""

    def __init__(self, obj, side):
        obj.addProperty(
            "App::PropertyEnumeration",
            "Side",
            "Jaw",
            QT_TRANSLATE_NOOP("App::Property", "The vise's jaw it is on"),
        )
        obj.Side = Sides
        obj.Side = side
        obj.setEditorMode("Side", ["ReadOnly"])
        obj.Proxy = self

    def onDocumentRestored(self, obj):
        # one made before it had a view provider of its own showed nothing
        _viewed(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Path.Main.Workholding as PathWorkholding

        vise = obj.getParentGeoFeatureGroup()
        size = PathWorkholding.plateSize(vise) if vise is not None else None
        if size is None or not hasattr(vise, "SoftThickness"):
            return
        if getattr(vise, "Jaws", "") == "Grip":
            shape = gripJawShape(
                size,
                vise.SoftThickness.Value,
                vise.SoftHeight.Value,
                vise.GripSetback.Value,
                obj.Side,
            )
        else:
            shape = softJawShape(
                size,
                vise.SoftThickness.Value,
                vise.SoftHeight.Value,
                parseSteps(vise.Steps),
                obj.Side,
            )
        shape.Placement = obj.Placement
        obj.Shape = shape


def _unselectable(vobj):
    """Not picked in the 3D view, nor lit when picked in the tree: there to be seen and missed."""
    if vobj is not None and "Selectable" in vobj.PropertiesList:
        vobj.Selectable = False


class ViewProviderSoftJaw:
    """A soft jaw as Part shows its shapes, in aluminium."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self.vobj = vobj
        _unselectable(vobj)

    def finishRestoring(self):
        # one saved before it was so: not picked in the 3D view either
        _unselectable(getattr(self, "vobj", None))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _viewed(obj):
    """obj shown: given a view provider of its own if it has none."""
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    if not isinstance(getattr(obj.ViewObject, "Proxy", None), ViewProviderSoftJaw):
        ViewProviderSoftJaw(obj.ViewObject)
        # the jaws' edges drawn, thin: they help to see the jaws
        obj.ViewObject.DisplayMode = "Flat Lines"
        obj.ViewObject.LineWidth = 1
        obj.ViewObject.PointSize = 1
        # its points the colour of its edges, not drawn over them
        obj.ViewObject.PointColor = obj.ViewObject.LineColor
        # aluminium, apart from the vise's steel
        obj.ViewObject.ShapeColor = (0.60, 0.74, 0.90)


def colour(obj, kind):
    """A jaw coloured as its kind is made: soft ones aluminium, grip ones steel."""
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    obj.ViewObject.ShapeColor = (0.62, 0.64, 0.68) if kind == "Grip" else (0.60, 0.74, 0.90)


def isSoftJaw(obj):
    """isSoftJaw(obj) ... whether obj is a soft jaw of a vise."""
    return isinstance(getattr(obj, "Proxy", None), ObjectSoftJaw)


def create(vise, side):
    """create(vise, side) ... a new soft jaw on side, one of Sides, of the vise."""
    obj = vise.Document.addObject("Part::FeaturePython", "SoftJaw")
    ObjectSoftJaw(obj, side)
    obj.Label = (
        translate("CAM", "Fixed soft jaw")
        if side == "Fixed"
        else translate("CAM", "Moving soft jaw")
    )
    _viewed(obj)
    vise.addObject(obj)
    return obj


class ObjectGrip:
    """A hardened grip of a grip jaw of a vise, made from the vise's settings: the side it is
    on and which of the jaw's grips it is. A tool in it is a crash."""

    def __init__(self, obj, side, index):
        obj.addProperty(
            "App::PropertyEnumeration",
            "Side",
            "Grip",
            QT_TRANSLATE_NOOP("App::Property", "The vise's jaw it is on"),
        )
        obj.Side = Sides
        obj.Side = side
        obj.addProperty(
            "App::PropertyInteger",
            "Index",
            "Grip",
            QT_TRANSLATE_NOOP("App::Property", "Which of the jaw's grips it is, across it"),
        )
        obj.Index = index
        for name in ("Side", "Index"):
            obj.setEditorMode(name, ["ReadOnly"])
        obj.Proxy = self

    def onDocumentRestored(self, obj):
        _viewedGrip(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Path.Main.Workholding as PathWorkholding

        vise = obj.getParentGeoFeatureGroup()
        size = PathWorkholding.plateSize(vise) if vise is not None else None
        if size is None or not hasattr(vise, "GripHeight"):
            return
        shape = gripShape(
            size,
            vise.SoftThickness.Value,
            vise.SoftHeight.Value,
            vise.GripHeight.Value,
            vise.GripSetback.Value,
            max(1, vise.GripCount),
            obj.Index,
            obj.Side,
        )
        shape.Placement = obj.Placement
        obj.Shape = shape


def _viewedGrip(obj):
    """A grip shown dark, hardened, apart from the jaw it sits in."""
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    if not isinstance(getattr(obj.ViewObject, "Proxy", None), ViewProviderSoftJaw):
        ViewProviderSoftJaw(obj.ViewObject)
        # the jaws' edges drawn, thin: they help to see the jaws
        obj.ViewObject.DisplayMode = "Flat Lines"
        obj.ViewObject.LineWidth = 1
        obj.ViewObject.PointSize = 1
        # its points the colour of its edges, not drawn over them
        obj.ViewObject.PointColor = obj.ViewObject.LineColor
        obj.ViewObject.ShapeColor = (0.22, 0.22, 0.25)


def isGrip(obj):
    """isGrip(obj) ... whether obj is a grip of a grip jaw."""
    return isinstance(getattr(obj, "Proxy", None), ObjectGrip)


def createGrip(vise, side, index):
    """createGrip(vise, side, index) ... a new grip, the index'th across the side's grip jaw."""
    obj = vise.Document.addObject("Part::FeaturePython", "Grip")
    ObjectGrip(obj, side, index)
    obj.Label = translate("CAM", "%s jaw grip %d") % (
        translate("CAM", "Fixed") if side == "Fixed" else translate("CAM", "Moving"),
        index + 1,
    )
    _viewedGrip(obj)
    vise.addObject(obj)
    return obj
