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

"""What the workholding modules share, importing none of them but its constants: lengths, a
part of a vise on one of its jaws, and reading a FreeCAD file as the zip it is, never opened as a
document."""

import zipfile

from xml.etree import ElementTree

import FreeCAD

from Path.Workholding.Constants import Sides
from PySide.QtCore import QT_TRANSLATE_NOOP


class SidePart:
    """A part of a vise of a Job's Workholding made from the vise's settings, on one of its jaws:
    a soft jaw, a grip, a parallel. Its Side, one of Sides, is fixed when it is made; its shape,
    made by shape(obj, vise), stands in the vise's frame."""

    # the group of its Side, and what it says
    group = None
    sideDoc = QT_TRANSLATE_NOOP("App::Property", "The vise's jaw it is on")

    def __init__(self, obj, side):
        obj.addProperty("App::PropertyEnumeration", "Side", self.group, self.sideDoc)
        obj.Side = Sides
        obj.Side = side
        obj.setEditorMode("Side", ["ReadOnly"])
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def shape(self, obj, vise):
        """Its shape in the vise's frame, None while the vise cannot say."""
        return None

    def execute(self, obj):
        vise = obj.getParentGeoFeatureGroup()
        shape = self.shape(obj, vise) if vise is not None else None
        if shape is None:
            return
        shape.Placement = obj.Placement
        obj.Shape = shape


def stockTopUnder(job, place, low, high):
    """stockTopUnder(job, place, low, high) ... how high the Job's stock's top is under the
    rectangle from low to high, (x, y) corners in the frame place, turned about Z only: where a
    clamp bears on it, not the highest of a model's features elsewhere. The top of the stock's
    box when none of it is under there."""
    import Part

    stock = job.Stock.Shape
    box = stock.optimalBoundingBox()
    if stock.isNull() or high[0] <= low[0] or high[1] <= low[1]:
        return box.ZMax
    column = Part.makeBox(
        high[0] - low[0], high[1] - low[1], box.ZLength + 2, FreeCAD.Vector(low[0], low[1], 0)
    )
    column.Placement = FreeCAD.Placement(
        FreeCAD.Vector(place.Base.x, place.Base.y, box.ZMin - 1), place.Rotation
    )
    under = stock.common(column)
    if under.isNull() or not under.Solids:
        return box.ZMax
    return under.BoundBox.ZMax


def userLength(value):
    """userLength(value) ... a length in mm, as the document's units show it."""
    return FreeCAD.Units.Quantity(value, FreeCAD.Units.Length).UserString


def _member(path, name):
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def readMember(path, name):
    """readMember(path, name) ... the file name in the FreeCAD file at path, as bytes; None if
    the file is not a zip or does not hold it."""
    try:
        return _member(path, name)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def readDocumentXml(path, strict=False):
    """readDocumentXml(path, strict=False) ... the Document.xml of the FreeCAD file at path, its
    root element; None if it cannot be read: not a zip, no Document.xml in it, not XML. With
    strict, why it cannot be read raised."""
    try:
        return ElementTree.fromstring(_member(path, "Document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        if strict:
            raise
        return None


def objectKinds(root):
    """objectKinds(root) ... the objects a Document.xml lists, {name: type}."""
    return {o.get("name"): o.get("type") for o in root.iter("Object") if o.get("type")}


def objectProperties(root):
    """objectProperties(root) ... each object's properties as a Document.xml saves them, (name,
    {property name: its element}) pairs."""
    data = root.find("ObjectData")
    for obj in data.findall("Object") if data is not None else []:
        yield obj.get("name"), {p.get("name"): p for p in obj.iter("Property")}


def varsetProperties(root, kinds=None):
    """varsetProperties(root, kinds=None) ... the properties of each VarSet of a Document.xml, as
    objectProperties gives them; kinds, objectKinds of it, read when None."""
    kinds = objectKinds(root) if kinds is None else kinds
    for name, props in objectProperties(root):
        if kinds.get(name) == "App::VarSet":
            yield name, props
