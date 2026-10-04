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
from Path.Workholding.Common import SidePart
from Path.Workholding.Constants import ALUMINUM_COLOR, GRIP_COLOR, GRIP_JAW_COLOR
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

# grip jaws, sized as common ones for a 6 in. vise: a soft steel jaw, a groove along its
# top a little behind its face, and hardened grips in the groove standing proud of its top. The
# stock sits on the jaw's top against the grips' teeth, which bite into it.
GripJaw = {
    "thickness": FreeCAD.Units.Quantity("0.990 in").Value,
    "height": FreeCAD.Units.Quantity("1.724 in").Value,
    "grip": FreeCAD.Units.Quantity(
        "0.060 in"
    ).Value,  # how far the grips stand above the jaw's top: what is held
    "setback": FreeCAD.Units.Quantity("0.120 in").Value,  # the grips' teeth behind the jaw's face
    "bite": FreeCAD.Units.Quantity("0.015 in").Value,  # how far they bite into the stock
    "grips": 2,  # on each jaw
    "gripLength": FreeCAD.Units.Quantity("0.75 in").Value,
    "gripWidth": FreeCAD.Units.Quantity("0.5 in").Value,
    "grooveDepth": FreeCAD.Units.Quantity("0.190 in").Value,
}


def parseSteps(entries, quiet=False):
    """parseSteps(entries, quiet=False) ... the steps a vise's Steps say, (height, depth) pairs in
    mm: height down from the soft jaw's top, depth in from its face. One that is not two numbers
    is left out, and said so unless quiet."""
    steps = []
    for entry in entries or []:
        try:
            height, depth = (float(v) for v in str(entry).split(","))
        except ValueError:
            if not quiet:
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
    center = low + (high - low) * (index + 0.5) / count
    shape = Part.makeBox(
        GripJaw["gripLength"],
        GripJaw["gripWidth"],
        GripJaw["grooveDepth"] + grip,
        Vector(center - GripJaw["gripLength"] / 2, face + setback, top - GripJaw["grooveDepth"]),
    )
    if side == "Moving":
        shape = shape.mirror(Vector(0, 0, 0), Vector(0, 1, 0))
    return shape


class ObjectSoftJaw(SidePart):
    """A soft jaw of a vise of a Job's Workholding, made from the vise's settings: its jaws, the
    hard plate it stands for, and the side it is on."""

    group = "Jaw"

    def shape(self, obj, vise):
        import Path.Workholding.Vise as PathWorkholding

        size = PathWorkholding.plateSize(vise)
        if size is None or not hasattr(vise, "SoftThickness"):
            return None
        if getattr(vise, "Jaws", "") == "Grip":
            return gripJawShape(
                size,
                vise.SoftThickness.Value,
                vise.SoftHeight.Value,
                vise.GripSetback.Value,
                obj.Side,
            )
        return softJawShape(
            size,
            vise.SoftThickness.Value,
            vise.SoftHeight.Value,
            parseSteps(vise.Steps),
            obj.Side,
        )


def _viewed(obj, color=ALUMINUM_COLOR):
    """obj shown, given a view provider of its own if it has none: in color, aluminum for a
    soft jaw, its edges drawn thin."""
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    import Path.Workholding.Gui.ViewProvider as Gui

    if not isinstance(getattr(obj.ViewObject, "Proxy", None), Gui.ViewProviderSoftJaw):
        Gui.ViewProviderSoftJaw(obj.ViewObject)
        obj.ViewObject.ShapeColor = color


def color(obj, kind):
    """A jaw colored as its kind is made: soft ones aluminum, grip ones steel."""
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    obj.ViewObject.ShapeColor = GRIP_JAW_COLOR if kind == "Grip" else ALUMINUM_COLOR


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


class ObjectGrip(SidePart):
    """A hardened grip of a grip jaw of a vise, made from the vise's settings: the side it is
    on and which of the jaw's grips it is. A tool in it is a crash."""

    group = "Grip"

    def __init__(self, obj, side, index):
        super().__init__(obj, side)
        obj.addProperty(
            "App::PropertyInteger",
            "Index",
            "Grip",
            QT_TRANSLATE_NOOP("App::Property", "Which of the jaw's grips it is, across it"),
        )
        obj.Index = index
        obj.setEditorMode("Index", ["ReadOnly"])

    def shape(self, obj, vise):
        import Path.Workholding.Vise as PathWorkholding

        size = PathWorkholding.plateSize(vise)
        if size is None or not hasattr(vise, "GripHeight"):
            return None
        return gripShape(
            size,
            vise.SoftThickness.Value,
            vise.SoftHeight.Value,
            vise.GripHeight.Value,
            vise.GripSetback.Value,
            max(1, vise.GripCount),
            obj.Index,
            obj.Side,
        )


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
    _viewed(obj, GRIP_COLOR)
    vise.addObject(obj)
    return obj
