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

"""Checking a vise's own file before it is shared or used: that it holds no Python to run when
opened, and that it is laid out as a vise must be for a Job to seat stock in it.

A library of vises runs check on each file it takes; a vise downloaded is checked before it is
opened. From a shell:

    FreeCADCmd -c "import Path.Workholding.Check as C; C.main(['vise.FCStd'])"
"""

import os
import re
import zipfile

from xml.etree import ElementTree

import FreeCAD
import Path.Workholding.Vise as PathWorkholding
import Path.Workholding.Source as PathSource

from Path.Workholding.Common import objectKinds, readDocumentXml, varsetProperties

translate = FreeCAD.Qt.translate

# how near a face must be to where it should be, mm
TOLERANCE = 0.05


def pythonObjects(path):
    """pythonObjects(path) ... the objects in the FreeCAD file at path that would import Python
    when it is opened, as (name, type) pairs: none in a file that is safe to open. Raises for a
    file that cannot be read."""
    return _pythonIn(readDocumentXml(path, strict=True))


def _pythonIn(root):
    """The objects and properties of a Document.xml that would import Python, (name, type)."""
    found = []
    for obj in root.iter("Object"):
        kind = obj.get("type", "")
        if "Python" in kind:
            found.append((obj.get("name"), kind))
    for prop in root.iter("Property"):
        if "Python" in prop.get("type", ""):
            found.append((prop.get("name"), prop.get("type")))
    return found


def pythonMessage(found):
    """pythonMessage(found) ... what is said of a file holding Python, found as pythonObjects
    gives it."""
    return translate("CAM", "Holds Python, run when opened: %s") % ", ".join(
        "%s (%s)" % f for f in found
    )


def checkZip(path):
    """checkZip(path) ... what is wrong with a vise's file, read as the zip it is, never opened as
    a document: Python in it, run when it is opened; no part, or no VarSet with the settings a
    vise has, a vise of several stations each station's frame and opening; laid out for a newer
    FreeCAD. None wrong, an empty list."""
    try:
        root = readDocumentXml(path, strict=True)
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as e:
        return [translate("CAM", "Not a FreeCAD file: %s") % e]
    errors = []
    found = _pythonIn(root)
    if found:
        errors.append(pythonMessage(found))
    kinds = objectKinds(root)
    if "App::Part" not in kinds.values():
        errors.append(translate("CAM", "No vise: no part holding it"))
    settings = {}
    for _, props in varsetProperties(root, kinds):
        settings.update(props)
    for name in ("Opening", "JawHeight", "MaxOpening"):
        if name not in settings:
            errors.append(translate("CAM", "No %s: not laid out as a vise") % name)
    count = settings.get("Stations")
    if count is not None and len(count) and count[0].get("value") is not None:
        count = int(float(count[0].get("value")))
        if count > 1 and "StationFrames" not in settings:
            errors.append(translate("CAM", "No StationFrames: where its %d stations are") % count)
        for number in range(2, count + 1):
            if "Opening%d" % number not in settings:
                errors.append(
                    translate("CAM", "No Opening%d: the opening of station %d") % (number, number)
                )
    schema = settings.get("ViseSchema")
    if schema is not None and len(schema) and schema[0].get("value") is not None:
        if int(float(schema[0].get("value"))) > PathWorkholding.ViseSchema:
            errors.append(
                translate("CAM", "Laid out for vise schema %s; this FreeCAD knows %d")
                % (schema[0].get("value"), PathWorkholding.ViseSchema)
            )
    return errors


def _driven(container, holder, opening="Opening"):
    """The parts of the vise moved by its Opening, or the opening named, with the expressions
    moving them."""
    name = re.compile(r"(?<![\w.])%s\.%s(?!\w)" % (re.escape(holder.Name), opening))

    def drives(e):
        return name.search(e) is not None

    return [
        (o, [(p, e) for p, e in o.ExpressionEngine if p.startswith(".Placement") and drives(e)])
        for o in container.Group
        if any(p.startswith(".Placement") and drives(e) for p, e in o.ExpressionEngine)
    ]


def _facesFixedJaw(face, y, frame=None):
    """Whether face is flat, at y, and faces +Y, toward the fixed jaw: in the frame of a station,
    a placement, where given."""
    if face.Surface.__class__.__name__ != "Plane":
        return False
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    point = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    if frame is not None:
        normal = frame.Rotation.inverted().multVec(normal)
        point = frame.inverse().multVec(point)
    return abs(point.y - y) <= TOLERANCE and normal.y > 1 - 1e-6


def _shapes(container):
    return [
        o
        for o in container.Group
        if hasattr(o, "Shape") and o.TypeId != "App::Origin" and not o.Shape.isNull()
    ]


def checkDocument(doc):
    """checkDocument(doc) ... (errors, warnings) for the vise an open document holds, each a list
    of what is wrong. Errors keep a Job from using it; warnings are what a vise rarely does. The
    document is left as it was."""
    errors, warnings = [], []
    container = PathWorkholding.viseIn(doc)
    if container is None:
        errors.append(translate("CAM", "No vise: no part holding a VarSet with an Opening"))
        return errors, warnings
    setup = PathWorkholding.viseSetup(container)
    holder = setup["opening"]
    schema = PathWorkholding.schemaOf(container)
    if schema > PathWorkholding.ViseSchema:
        errors.append(
            translate("CAM", "Laid out for vise schema %d; this FreeCAD knows %d")
            % (schema, PathWorkholding.ViseSchema)
        )
    if setup["jawHeight"] is None:
        errors.append(translate("CAM", "No JawHeight: the floor to the jaw tops"))
    if setup["maxOpening"] is None:
        errors.append(translate("CAM", "No MaxOpening: as far as the jaws open"))

    # each station's opening moves its moving parts along its -Y by as much, and nothing else
    frames = PathWorkholding.stations(container)
    count = getattr(holder, "Stations", None)
    if count is not None and count > 1 and len(getattr(holder, "StationFrames", [])) != count:
        errors.append(
            translate("CAM", "StationFrames gives %d frames for %d stations")
            % (len(getattr(holder, "StationFrames", [])), count)
        )
    if len(frames) > 1 and not frames[0].isIdentity():
        errors.append(translate("CAM", "The first station's frame is not the vise's own"))
    for number, frame in enumerate(frames, 1):
        name = "Opening" if number == 1 else "Opening%d" % number
        if not hasattr(holder, name):
            errors.append(translate("CAM", "No %s: the opening of station %d") % (name, number))
            continue
        driven = _driven(container, holder, name)
        if not driven:
            errors.append(translate("CAM", "The %s moves no part") % name)
            continue
        closing = frame.Rotation.multVec(FreeCAD.Vector(0, -10.0, 0))
        before = {o.Name: FreeCAD.Vector(o.Placement.Base) for o, _ in driven}
        opening = getattr(holder, name).Value
        setattr(holder, name, opening + 10.0)
        doc.recompute()
        for o, _ in driven:
            moved = o.Placement.Base - before[o.Name]
            if (moved - closing).Length > 1e-6:
                if number == 1:
                    errors.append(
                        translate("CAM", "%s moves %s for 10 mm more Opening, not 10 mm along -Y")
                        % (o.Label, tuple(round(c, 3) for c in moved))
                    )
                else:
                    errors.append(
                        translate(
                            "CAM", "%s moves %s for 10 mm more %s, not 10 mm along its station's -Y"
                        )
                        % (o.Label, tuple(round(c, 3) for c in moved), name)
                    )
        setattr(holder, name, opening)
        doc.recompute()
        # the moving jaw's face the opening in front of the fixed one, at Y 0, facing it; a
        # screw moving with the jaw may reach further
        if not any(_facesFixedJaw(f, -opening, frame) for o, _ in driven for f in o.Shape.Faces):
            if number == 1:
                warnings.append(
                    translate("CAM", "No moving part has a face toward the fixed jaw at Y %.3f")
                    % -opening
                )
            else:
                warnings.append(
                    translate(
                        "CAM",
                        "No moving part of station %d has a face toward its fixed jaw at Y %.3f",
                    )
                    % (number, -opening)
                )

    # the hard jaw plates other jaws take the place of: two, both parts of the vise
    plates = list(getattr(holder, "JawPlates", []) or [])
    if plates:
        names = [o.Name for o in container.Group]
        if len(plates) != 2:
            errors.append(translate("CAM", "JawPlates names %d parts, not 2") % len(plates))
        for name in plates:
            if name not in names:
                errors.append(translate("CAM", "JawPlates names %s, not a part of it") % name)
    for entry in getattr(holder, "JawSteps", []) or []:
        try:
            height, depth = (float(v) for v in str(entry).split(","))
        except ValueError:
            errors.append(translate("CAM", "A step is 'height,depth': not '%s'") % entry)
            continue
        if height <= 0 or depth <= 0:
            errors.append(translate("CAM", "A step goes down and in: not '%s'") % entry)

    # the jaw tops at Z 0: what stands above them, a handle, is rare but may be
    for o in _shapes(container):
        top = o.Shape.BoundBox.ZMax
        if top > TOLERANCE:
            warnings.append(
                translate("CAM", "%s stands %.3f above the jaw tops, Z 0") % (o.Label, top)
            )
    seat = getattr(holder, "SeatHeight", None)
    if seat is not None and setup["jawHeight"] is not None:
        if abs(seat.Value + setup["jawHeight"]) > TOLERANCE:
            warnings.append(
                translate("CAM", "SeatHeight %.3f is not the JawHeight below the jaw tops, %.3f")
                % (seat.Value, -setup["jawHeight"])
            )
    return errors, warnings


def check(path):
    """check(path) ... (errors, warnings) for the vise's own file at path. One with Python in it
    is not opened."""
    found = pythonObjects(path)
    if found:
        return [pythonMessage(found)], []
    doc, opened = PathSource.openFile(os.path.abspath(path))
    try:
        return checkDocument(doc)
    finally:
        if opened:
            FreeCAD.closeDocument(doc.Name)


def main(paths):
    """main(paths) ... each file checked, what is wrong printed; the number with errors."""
    bad = 0
    for path in paths:
        errors, warnings = check(path)
        print("%s: %s" % (path, "ERROR" if errors else "ok"))
        for e in errors:
            print("  error: %s" % e)
        for w in warnings:
            print("  warning: %s" % w)
        bad += bool(errors)
    return bad
