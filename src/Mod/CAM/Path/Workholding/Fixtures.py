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

"""Fixtures: the mill tables, router spoilboards, fixture plates, pallets, angle plates and
blocks a Job's workholding, and the stock itself, rests or is clamped on. Grounded, unlike a vise
or a clamp: not holding the stock itself, but what it, another fixture, or workholding of its own
stands, is bolted, or is snapped onto. A fixture may be stacked on another.

A fixture comes from a file of its own, laid out as a vise's or a clamp's: an App::Part holding
Body, its real shape, usually a maker's own, and Settings, a VarSet whose Kind says which of
FIXTURE_KINDS it is and carries, group Fixture:

- Width, Length, Thickness: its overall size, mm, for reference; its shape may not be a plain box;
- HolePositions, HoleDiameters, HoleUsable, HoleDowel, HoleThread: every hole in it, on its top
  face unless it says otherwise, parallel lists one entry a hole. HoleUsable is False for a hole
  only holding the fixture itself down, such as a mounting bolt's, never snapped to. HoleDowel is
  True where a hole is a slip fit for a dowel pin, for locating; HoleThread, its thread, "" where
  it has none. A hole may be both, a dowel fit over a tapped hole, as a fixture plate's often are;
- SlotStarts, SlotEnds, SlotWidths, SlotTrackWidths, SlotDepths: every T-slot in it, parallel
  lists the same way, a slot's ends, its opening's width, mm, the width across the wider track
  below it a T-nut's head is held by, and its depth.

A fixture with none of these, a block or a custom shape with nothing to snap to, leaves the lists
empty.

It is put in a Job as a vise or a clamp is, addFixture: its Body linked from the file, Settings
copied onto the group FreeCAD puts in the Job, an ObjectFixture.

fromStep() builds a fixture's own file from a STEP file, the holes in it found as the cylindrical
faces of each radius asked for; build() does the same from a shape and hole and slot data already
worked out."""

import os

import FreeCAD
import Part

import Path.Workholding.Source as PathSource
import Path.Workholding.Vise as PathWorkholding

from FreeCAD import Vector
from Path.Workholding.Common import objectKinds, readDocumentXml, varsetProperties
from Path.Workholding.Constants import FIXTURE_KINDS
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

# how near two cylindrical faces' radii must be, found in a STEP, to be taken as the same hole
# size, mm
RADIUS_TOLERANCE = 0.05

# the groups a Fixture's own property may be read from, as About's are
FIXTURE = "Fixture"
ABOUT = "About"


class ObjectFixture(PathWorkholding.LinkedGroup):
    """A fixture of a Job's Workholding from a file of its own: a group placing the parts it
    links from the file, the settings of its VarSet copied onto it, its Kind among them."""

    group = FIXTURE
    viewProviderName = "ViewProviderFixture"

    def onDocumentRestored(self, obj):
        # its file looked for again if it is not found
        PathSource.recoverLater(obj.Document)


def isFixture(obj):
    """isFixture(obj) ... whether obj is a fixture: its Kind, copied from its file's VarSet, one
    of FIXTURE_KINDS."""
    return getattr(obj, "Kind", None) in FIXTURE_KINDS


def _kindIn(container):
    for o in getattr(container, "Group", []) or []:
        if o.TypeId == "App::VarSet" and hasattr(o, "Kind"):
            return o.Kind
    return None


def fixtureIn(doc):
    """fixtureIn(doc) ... the fixture a fixture's own file holds: its outermost container with a
    VarSet whose Kind is one of FIXTURE_KINDS, or None."""
    for obj in doc.RootObjects:
        if obj.hasExtension("App::GeoFeatureGroupExtension") and _kindIn(obj) in FIXTURE_KINDS:
            return obj
    return None


def fixtureFile(path):
    """fixtureFile(path) ... the fixture a fixture's own file holds, read from the file without
    opening it: its name, the file's, and its Kind, one of FIXTURE_KINDS. None if it holds none:
    no part, or no VarSet saying it is one."""
    root = readDocumentXml(path)
    if root is None:
        return None
    types = objectKinds(root)
    kind = None
    for _, props in varsetProperties(root, types):
        prop = props.get("Kind")
        if prop is not None and prop.find("String") is not None:
            if prop.find("String").get("value") in FIXTURE_KINDS:
                kind = prop.find("String").get("value")
                break
    if kind not in FIXTURE_KINDS or "App::Part" not in types.values():
        return None
    return os.path.splitext(os.path.basename(path))[0].replace("_", " "), kind


def addFixture(job, path):
    """addFixture(job, path) ... a fixture put in the Job's Workholding from the fixture's own
    file at path, as a vise is: its Body linked from the file, its settings copied onto it.
    Returns it."""
    source = fixtureIn(PathSource.openFile(path, job.Document)[0])
    if source is None:
        raise ValueError(
            translate("CAM", "%s holds no fixture: a part with a VarSet giving its Kind")
            % os.path.basename(path)
        )
    members = PathWorkholding.sourceMembers(source)
    return PathWorkholding._instance(
        job, source.Label, members, FreeCAD.Placement(), ObjectFixture, "Fixture"
    )


def build(
    doc,
    name,
    shape,
    *,
    kind,
    width,
    length,
    thickness,
    holes=(),
    slots=(),
    about=None,
    label=None,
):
    """build(doc, name, shape, kind, width, length, thickness, holes=(), slots=(), about=None,
    label=None) ... a fixture's own file container added to doc: an App::Part named name holding
    Body, a Part::Feature of shape, and Settings, a VarSet of kind, one of FIXTURE_KINDS; width,
    length and thickness, mm, for reference; holes, (position, diameter, usable, dowel, thread)
    tuples, position a Vector, mm, on the top face unless the fixture says otherwise, usable and
    dowel bools, thread a string, "" if it has none; slots, (start, end, width, trackWidth, depth)
    tuples, mm. about, a dict of Library.AboutFields' fields, stamped where given. Returns the
    App::Part."""
    container = doc.addObject("App::Part", name)
    container.Type = "Workholding"
    if label:
        container.Label = label

    body = doc.addObject("Part::Feature", "Body")
    body.Shape = shape
    container.addObject(body)

    settings = doc.addObject("App::VarSet", "Settings")
    container.addObject(settings)

    def add(kind_, prop, group, value):
        settings.addProperty(kind_, prop, group, QT_TRANSLATE_NOOP("App::Property", prop))
        setattr(settings, prop, value)

    add("App::PropertyString", "Kind", FIXTURE, kind)
    add("App::PropertyLength", "Width", FIXTURE, width)
    add("App::PropertyLength", "Length", FIXTURE, length)
    add("App::PropertyLength", "Thickness", FIXTURE, thickness)
    add("App::PropertyVectorList", "HolePositions", FIXTURE, [h[0] for h in holes])
    add("App::PropertyFloatList", "HoleDiameters", FIXTURE, [h[1] for h in holes])
    add("App::PropertyBoolList", "HoleUsable", FIXTURE, [bool(h[2]) for h in holes])
    add("App::PropertyBoolList", "HoleDowel", FIXTURE, [bool(h[3]) for h in holes])
    add("App::PropertyStringList", "HoleThread", FIXTURE, [h[4] or "" for h in holes])
    add("App::PropertyVectorList", "SlotStarts", FIXTURE, [s[0] for s in slots])
    add("App::PropertyVectorList", "SlotEnds", FIXTURE, [s[1] for s in slots])
    add("App::PropertyFloatList", "SlotWidths", FIXTURE, [s[2] for s in slots])
    add("App::PropertyFloatList", "SlotTrackWidths", FIXTURE, [s[3] for s in slots])
    add("App::PropertyFloatList", "SlotDepths", FIXTURE, [s[4] for s in slots])

    if about:
        import Path.Workholding.Library as PathLibrary

        for prop, field in PathLibrary.AboutFields.items():
            value = about.get(field)
            if value:
                add("App::PropertyString", prop, ABOUT, value)

    return container


def _cylindricalFaces(shape):
    """The shape's cylindrical faces grouped by radius, mm, those within RADIUS_TOLERANCE of each
    other taken as one group: {radius: [face, ...]}, radius each group's faces' mean."""
    found = []
    for f in shape.Faces:
        if f.Surface.TypeId == "Part::GeomCylinder":
            found.append((f.Surface.Radius, f))
    found.sort(key=lambda rf: rf[0])
    groups = []
    for r, f in found:
        if groups and r - groups[-1][0] <= RADIUS_TOLERANCE:
            group = groups[-1]
            group[1].append(f)
            group[0] = (group[0] * (len(group[1]) - 1) + r) / len(group[1])
        else:
            groups.append([r, [f]])
    return {round(r, 3): faces for r, faces in groups}


def fromStep(
    path,
    name,
    *,
    kind,
    holeSpecs=(),
    rotation=0,
    origin=(0, 0, 0),
    thickness=None,
    slots=(),
    about=None,
    doc=None,
    label=None,
):
    """fromStep(path, name, kind, holeSpecs=(), rotation=0, origin=(0,0,0), thickness=None,
    slots=(), about=None, doc=None, label=None) ... a fixture's own file container read from the
    STEP file at path: its shape turned rotation degrees about Z then moved by origin (mm) into
    the fixture's own frame, top at Z 0. holeSpecs, dicts of "radius", mm, the cylindrical faces
    of a hole size, as _cylindricalFaces groups them, found within RADIUS_TOLERANCE; "usable" and
    "dowel", bools, True when not given; "thread", a string, "" when not given. Raises ValueError
    if a radius matches none. thickness, mm, its drawing's, when a hole's relief on the back
    reaches past its true bottom; its shape's own depth when None. doc, the document added to, the
    active one when None. Returns the App::Part build() does."""
    doc = doc or FreeCAD.ActiveDocument or FreeCAD.newDocument()
    raw = Part.Shape()
    raw.read(path)
    placement = FreeCAD.Placement(Vector(*origin), FreeCAD.Rotation(Vector(0, 0, 1), rotation))
    matrix = placement.toMatrix()

    groups = _cylindricalFaces(raw)

    def nearest(radius):
        found = min(groups, key=lambda r: abs(r - radius))
        if abs(found - radius) > RADIUS_TOLERANCE:
            raise ValueError(
                "%s: no cylindrical faces of radius %.3f mm found (nearest %.3f)"
                % (path, radius, found)
            )
        return found

    holes = []
    for spec in holeSpecs:
        found = nearest(spec["radius"])
        for f in groups[found]:
            c = matrix.multiply(f.Surface.Center)
            holes.append(
                (
                    Vector(c.x, c.y, 0),
                    2 * found,
                    spec.get("usable", True),
                    spec.get("dowel", False),
                    spec.get("thread", ""),
                )
            )

    shape = raw.copy()
    shape = shape.transformGeometry(matrix)
    bb = shape.BoundBox

    return build(
        doc,
        name,
        shape,
        kind=kind,
        width=bb.XLength,
        length=bb.YLength,
        thickness=thickness if thickness is not None else -bb.ZMin,
        holes=holes,
        slots=slots,
        about=about,
        label=label,
    )
