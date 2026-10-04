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

"""Parallels: the pair of bars the stock stands on in a vise, one against each jaw.

The common sets are listed here, by unit, type, thickness and height; a shop adds its own in
Parallels.json in its Workholding folder, a list of sets as Sets has them. The parallels the stock
is seated on are made from the vise's settings, the moving one following the moving jaw. Hard,
steel, a tool in them is a crash; soft, aluminum packing or plastic, it cuts them, warned of."""

import json
import os

from collections import namedtuple

import FreeCAD
import Part

from FreeCAD import Vector
from Path.Workholding.Common import SidePart
from Path.Workholding.Constants import HARDENED_PARALLEL_COLOR, SOFT_PARALLEL_COLOR
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

# the parallels the stock is seated on, in mm: soft ones cut, not crashed into; the set's name
Parallel = namedtuple("Parallel", "height thickness length cuttable name")


def _inches(first, last, step):
    """Heights from first to last by step, all in inches, as mm."""
    n = int(round((last - first) / step))
    return [round((first + i * step) * FreeCAD.Units.Inch.Value, 6) for i in range(n + 1)]


# The common sets, sizes in mm: the unit they are made in, their type, how long they usually are
# (pairs come shorter or longer too), the thicknesses they come in and their heights. Most shops have a standard set; thin ones are for
# drilling near the stock's edge, wavy ones spring against the jaws.
Sets = [
    {
        "unit": "Imperial",
        "type": "Standard",
        "length": FreeCAD.Units.Quantity("6 in").Value,
        "thicknesses": [FreeCAD.Units.Quantity("1/8 in").Value],
        "heights": _inches(0.5, 1.625, 0.125),
    },
    {
        "unit": "Imperial",
        "type": "Thin",
        "length": FreeCAD.Units.Quantity("6 in").Value,
        "thicknesses": [FreeCAD.Units.Quantity("1/32 in").Value],
        "heights": _inches(0.5, 1.6875, 0.0625),
    },
    {
        "unit": "Imperial",
        "type": "Thick",
        "length": FreeCAD.Units.Quantity("6 in").Value,
        "thicknesses": [FreeCAD.Units.Quantity("1/4 in").Value],
        "heights": _inches(0.5, 1.5, 0.25),
    },
    {
        # spring steel bent in waves: the thickness is what they take up across
        "unit": "Imperial",
        "type": "Wavy",
        "length": FreeCAD.Units.Quantity("4.3125 in").Value,
        "thicknesses": [FreeCAD.Units.Quantity("1/16 in").Value],
        "heights": _inches(0.5, 1.5, 0.125),
    },
    {
        "unit": "Metric",
        "type": "Standard",
        "length": 150.0,
        "thicknesses": [3.0, 4.0],
        "heights": [14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 32.0]
        + [35.0, 40.0, 45.0, 50.0],
    },
]

# the parallels a vise has until a set is chosen: the first set's, a standard one
DefaultThickness = Sets[0]["thicknesses"][0]
DefaultLength = Sets[0]["length"]


def userSets():
    """The sets the shop adds, from Parallels.json in its Workholding folder: none if it has
    none, or it does not read."""
    try:
        import Path.Preferences

        path = os.path.join(str(Path.Preferences.getAssetPath()), "Workholding", "Parallels.json")
    except Exception:
        return []
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            sets = json.load(f)
        return [
            {
                "unit": str(s["unit"]),
                "type": str(s["type"]),
                "length": float(s["length"]),
                "thicknesses": [float(t) for t in s["thicknesses"]],
                "heights": [float(h) for h in s["heights"]],
                "cuttable": bool(s.get("cuttable", False)),
            }
            for s in sets
        ]
    except Exception as e:
        Path.Log.warning("%s: %s" % (path, e))
        return []


def catalog():
    """catalog() ... the sets of parallels there are: the common ones, then the shop's."""
    return Sets + userSets()


def _fraction(mm):
    """A length in inches as a machinist writes it, to a sixty-fourth: 1-3/16"."""
    sixtyfourths = int(round(mm / FreeCAD.Units.Inch.Value * 64))
    whole, rest = divmod(sixtyfourths, 64)
    if rest == 0:
        return '%d"' % whole
    den = 64
    while rest % 2 == 0:
        rest //= 2
        den //= 2
    return '%s%d/%d"' % ("%d-" % whole if whole else "", rest, den)


def label(mm, unit):
    """label(mm, unit) ... a size as a set in unit names it."""
    if (
        unit == "Imperial"
        and abs(mm / FreeCAD.Units.Inch.Value * 64 - round(mm / FreeCAD.Units.Inch.Value * 64))
        < 1e-6
    ):
        return _fraction(mm)
    return ("%.3f" % mm).rstrip("0").rstrip(".") + " mm"


def name(unit, kind, length, thickness, height):
    """name(unit, kind, length, thickness, height) ... the parallels of a set, as the vise keeps
    them: unit, type, thickness, height and length."""
    return ", ".join(
        (unit, kind, label(thickness, unit), label(height, unit), label(length, unit) + " long")
    )


def parallels(entry, thickness, height, length=None):
    """parallels(entry, thickness, height, length=None) ... the parallels of a set of the
    catalog, thick and tall as given, as long as the set's unless length says: soft as the set
    is. Pairs of one set come in other lengths too."""
    length = entry["length"] if length is None else length
    return Parallel(
        height,
        thickness,
        length,
        entry.get("cuttable", False),
        name(entry["unit"], entry["type"], length, thickness, height),
    )


def parallelShape(frame, height, thickness, length, side):
    """parallelShape(frame, height, thickness, length, side) ... a parallel in the vise's frame,
    as jawFrame gives it: on the vise's floor against the fixed jaw's face, centered across the
    jaws. The moving one is the fixed one mirrored, drawn closed."""
    face = frame["face"]
    bar = Part.makeBox(
        length, thickness, height, Vector(-length / 2, face - thickness, frame["floor"])
    )
    if side == "Moving":
        bar = bar.mirror(Vector(0, 0, 0), Vector(0, 1, 0))
    return bar


class ObjectParallel(SidePart):
    """A parallel of a vise of a Job's Workholding, made from the vise's settings: how tall, thick
    and long its parallels are, and the side it is on."""

    group = "Parallel"
    sideDoc = QT_TRANSLATE_NOOP("App::Property", "The vise's jaw it stands against")

    def shape(self, obj, vise):
        import Path.Workholding.Vise as PathWorkholding

        frame = PathWorkholding.jawFrame(vise)
        if frame is None or not hasattr(vise, "ParallelThickness"):
            return None
        height = vise.Parallels.Value
        thickness = vise.ParallelThickness.Value
        length = vise.ParallelLength.Value
        if height <= 0 or thickness <= 0 or length <= 0:
            return None
        return parallelShape(frame, height, thickness, length, obj.Side)


def _viewed(obj):
    """obj shown: given a view provider of its own if it has none, shaded."""
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    import Path.Workholding.Gui.ViewProvider as Gui

    if not isinstance(getattr(obj.ViewObject, "Proxy", None), Gui.ViewProviderParallel):
        Gui.ViewProviderParallel(obj.ViewObject)
    color(obj)


def color(obj):
    """obj colored as its vise has its parallels: hardened steel, or soft."""
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    vise = obj.getParentGeoFeatureGroup()
    soft = vise is not None and getattr(vise, "ParallelsCuttable", False)
    obj.ViewObject.ShapeColor = SOFT_PARALLEL_COLOR if soft else HARDENED_PARALLEL_COLOR


def isParallel(obj):
    """isParallel(obj) ... whether obj is a parallel of a vise."""
    return isinstance(getattr(obj, "Proxy", None), ObjectParallel)


def create(vise, side):
    """create(vise, side) ... a new parallel against side, one of Sides, of the vise."""
    obj = vise.Document.addObject("Part::FeaturePython", "Parallel")
    ObjectParallel(obj, side)
    obj.Label = (
        translate("CAM", "Fixed jaw parallel")
        if side == "Fixed"
        else translate("CAM", "Moving jaw parallel")
    )
    vise.addObject(obj)
    _viewed(obj)
    return obj
