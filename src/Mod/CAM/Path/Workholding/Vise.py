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

"""The workholding a Job's stock is held in, and seating the stock in a vise.

A vise is a container in the Job's Workholding group laid out one way: its origin on the fixed
jaw's face, at the top of the jaws and centered across them, the jaws closing along its -Y, its
+Z up. Its settings carry Opening, the gap between the jaw faces that drives the moving jaw, and
JawHeight, from the floor to the jaw tops: in a vise's own file on a VarSet, in a vise put in a
Job on the vise itself. Seating puts the stock against the fixed jaw, held as deep as asked, and
closes the moving jaw on it.

A vise whose file names its hard jaw plates, its JawPlates, can have them swapped for soft jaws,
plain or stepped: the stock is then seated against the soft jaw's face, or on a step's floor and
against its wall. Hard jaws with steps of their own say so in the file's JawSteps.

A vise of more than one station, its file's Stations, holds a stock in each: StationFrames gives
each station's frame in the vise's, laid out as a vise of one station is, the first the vise's
own; Opening is the first's, Opening2, Opening3... the others'. A Job holds one stock, so seats
it in one station of a vise, its Station; Jobs share such a vise, each with a vise of its own in
its Workholding, the others' placed by expression where the first Job's, the owner's, is."""

import FreeCAD
import Path
import re

import Path.Workholding.Jaws as PathJaws
import Path.Workholding.Parallels as PathParallels
import Path.Workholding.Source as PathSource

from FreeCAD import Vector
from Path.Workholding.Common import userLength
from Path.Workholding.Constants import PROPERTY_ADDED, Sides
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

# The layout of a vise's own file this FreeCAD knows: a file says which it follows in its
# ViseSchema, none being the first; the second adds stations
ViseSchema = 2


def _varsets(container):
    """The VarSets a vise's settings may be on: those it holds, then those in the files its
    links bring its parts from."""
    held = [o for o in getattr(container, "Group", []) or [] if o.TypeId == "App::VarSet"]
    linked = []
    for o in getattr(container, "Group", []) or []:
        source = getattr(o, "LinkedObject", None)
        if source is not None:
            for s in source.Document.Objects:
                if s.TypeId == "App::VarSet" and s not in linked:
                    linked.append(s)
    return held + linked


def _holderOf(container, name):
    """What holds the setting name of a vise or a clamp: the container itself, else the first of
    its VarSets with it; None if none does."""
    for holder in [container] + _varsets(container):
        if hasattr(holder, name):
            return holder
    return None


def _setting(container, name, default=None):
    """The setting name of a vise or a clamp, as _holderOf finds it; default if none has it."""
    holder = _holderOf(container, name)
    return getattr(holder, name) if holder is not None else default


def viseSetup(container):
    """viseSetup(container) ... the vise's settings, or None if container is not a vise: what
    holds its Opening, the vise itself or a VarSet, its JawHeight and MaxOpening in mm, None
    where it does not say."""
    opening = None
    jawHeight = None
    maxOpening = None
    holders = [container] if hasattr(container, "Opening") else []
    for varset in holders + _varsets(container):
        if opening is None and hasattr(varset, "Opening"):
            opening = varset
        if jawHeight is None and hasattr(varset, "JawHeight"):
            jawHeight = varset.JawHeight.Value
        if maxOpening is None and getattr(varset, "MaxOpening", None):
            maxOpening = varset.MaxOpening.Value
    if opening is None:
        return None
    return {"opening": opening, "jawHeight": jawHeight, "maxOpening": maxOpening}


def isVise(obj):
    """isVise(obj) ... whether obj is a vise: it, or a VarSet it holds or its parts' file has,
    holds an Opening."""
    return viseSetup(obj) is not None


def _expressionNames(expression, names):
    """The expression with each object name in names, a dict, swapped for its new one."""
    for old, new in names.items():
        expression = re.sub(r"(?<![\w.])%s(?=\.)" % re.escape(old), new, expression)
    return expression


class LinkedGroup:
    """A piece of a Job's Workholding from a file of its own, a vise or a clamp: a group placing
    the parts it links from the file, the settings of the file's VarSet copied onto it. A part
    cannot be driven by an expression on the group holding it, so the group drives them itself:
    Drives, a part's name, a property of it and the expression it follows, each set again when a
    setting changes. Drives is in the group named group; the view provider, in the GUI, the one
    of Gui.ViewProvider named viewProviderName."""

    # the settings of its file copied onto it, its parts linked
    holdsSettings = True
    group = None
    viewProviderName = None

    @classmethod
    def viewProvider(cls, vobj):
        import Path.Workholding.Gui.ViewProvider as Gui

        getattr(Gui, cls.viewProviderName)(vobj)

    def __init__(self, obj):
        obj.addExtension("App::GeoFeatureGroupExtensionPython")
        obj.addProperty(
            "App::PropertyStringList",
            "Drives",
            self.group,
            QT_TRANSLATE_NOOP(
                "App::Property", "The parts the settings move: a part, its property, an expression"
            ),
        )
        obj.setEditorMode("Drives", ["Hidden"])
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ObjectVise(LinkedGroup):
    """A vise of a Job's Workholding: a group placing the parts it links from the vise's file,
    the settings of the vise's VarSet copied onto it."""

    group = "Vise"
    viewProviderName = "ViewProviderVise"

    def onBeforeChange(self, obj, prop):
        if prop == "Placement":
            self.before = FreeCAD.Placement(obj.Placement)
        elif _isOpening(prop) and hasattr(obj, prop):
            self.opening = (prop, getattr(obj, prop).Value)

    def onChanged(self, obj, prop):
        doc = obj.Document
        if doc is None or doc.Restoring or doc.Transacting:
            return
        if prop == "Placement":
            before, self.before = getattr(self, "before", None), None
            # one following another's placement goes where that one does
            if before is not None and _held(obj) and not isFollower(obj):
                _hold(obj, before)
            return
        if prop == "Parallels" and _held(obj) and getattr(obj, "OnParallels", False):
            _standOnParallels(obj)
            for parallel in parallelsOf(obj).values():
                parallel.touch()
            return
        if prop in ("ParallelThickness", "ParallelLength"):
            for parallel in parallelsOf(obj).values():
                parallel.touch()
            return
        if prop == "ParallelsCuttable":
            for parallel in parallelsOf(obj).values():
                PathParallels.color(parallel)
            return
        if prop == "CloseJaw" and _held(obj) and obj.CloseJaw:
            _closeJaw(obj)
            return
        if prop in obj.PropertiesList and obj.getGroupOfProperty(prop) == "Jaws":
            # setJaws makes the jaws itself once all its settings are in
            if getattr(self, "settingJaws", False):
                return
            if prop == "Jaws":
                _makeJaws(obj)
            else:
                for jaw in softJaws(obj).values():
                    jaw.touch()
            return
        if prop in obj.PropertiesList and obj.getGroupOfProperty(prop) == "Vise":
            if _isOpening(prop):
                opening, self.opening = getattr(self, "opening", None), None
                if opening is not None and opening[0] == prop == openingName(obj):
                    _keepBody(obj, opening[1])
                _shareOpening(obj, prop)
            drive(obj)

    def onDocumentRestored(self, obj):
        # brought up to date with its file, if that is open by now; its file looked for again
        # if it is not found
        try:
            refreshSettings(obj)
        except Exception as e:
            Path.Log.warning("%s: %s" % (obj.Label, e))
        PathSource.recoverLater(obj.Document)


class _Free:
    """A vise's placement free of its seat while seating moves it."""

    def __init__(self, vise):
        proxy = getattr(vise, "Proxy", None)
        self.proxy = proxy if isinstance(proxy, ObjectVise) else None

    def __enter__(self):
        if self.proxy is not None:
            self.proxy.free = True

    def __exit__(self, *args):
        if self.proxy is not None:
            self.proxy.free = False


def _held(vise):
    """Whether the vise holds to its seat: seated, and not being seated."""
    return getattr(vise, "Seated", False) and not getattr(vise.Proxy, "free", False)


def _bottom(job, placement):
    """The stock's bottom in the frame of placement, from its origin, along its +Z."""
    up = placement.Rotation.multVec(Vector(0, 0, 1))
    return _extents(job.Stock.Shape, placement.Base, up)[0]


def _stockIn(job, placement):
    """The stock's extents in the frame of placement, from its origin, each (lowest, highest):
    along its -Y, the way the jaws close; along its X, across them; along its Z, up."""
    return [
        _extents(job.Stock.Shape, placement.Base, placement.Rotation.multVec(direction))
        for direction in (Vector(0, -1, 0), Vector(1, 0, 0), Vector(0, 0, 1))
    ]


def _seatStep(vise, frame):
    """The step of the vise's jaws the stock was seated on, 0 if none or it is gone."""
    step = getattr(vise, "SeatStep", 0)
    return step if 0 < step <= len(frame["steps"]) else 0


def _floor(vise):
    """Where the stock's bottom may go lowest, in the vise's frame: the step it is seated on, the
    vise's floor, or the parallels on it. None if the vise does not say how tall its jaws are."""
    frame = _jawFrame(vise)
    step = _seatStep(vise, frame)
    if step:
        return frame["steps"][step - 1][0]
    if frame["floor"] is None:
        return None
    parallels = vise.Parallels.Value if getattr(vise, "OnParallels", False) else 0.0
    return frame["floor"] + parallels


def _hold(vise, before):
    """The vise moved back to its seat, from before, as far as it may not move: along the jaws
    it slides, up and down it goes no lower than the floor or the parallels and no higher than
    the jaw tops, into the jaws and turned it does not. Its station's jaws, and the floor and
    jaw tops of those of the Jobs sharing it seated too."""
    job = memberOf(vise)[0]
    if job is None:
        return
    after = vise.Placement
    frame = stationFrame(vise)
    was = before.multiply(frame)
    turn = was.Rotation
    d = turn.inverted().multVec(after.multiply(frame).Base - was.Base)
    lift = d.z
    lowest, highest = None, None
    for row in shareGroup(vise):
        rowJob = job if row == vise else memberOf(row)[0]
        floor = _floor(row)
        if rowJob is None or floor is None or not getattr(row, "Seated", False):
            continue
        # the vise up by lift, the stock's bottom down in it by as much
        bottom = _bottom(rowJob, before.multiply(stationFrame(row)))
        low, high = bottom - _jawFrame(row)["top"], bottom - floor
        lowest = low if lowest is None else max(lowest, low)
        highest = high if highest is None else min(highest, high)
    if lowest is not None:
        lift = min(max(lift, lowest), highest)
    held = FreeCAD.Placement(was.Base + turn.multVec(Vector(d.x, 0, lift)), turn)
    held = held.multiply(frame.inverse())
    if held.isSame(after, 1e-7):
        return
    with _Free(vise):
        vise.Placement = held
    Path.Log.info(
        translate(
            "CAM",
            "%s is seated: it slides along the jaws and up, not into them, below the floor or "
            "turned. Clear Seated to move it freely.",
        )
        % vise.Label
    )


def _standOnParallels(vise):
    """The vise moved so the stock stands on its parallels; one shared with other Jobs stays,
    the part moving down onto them."""
    job = memberOf(vise)[0]
    floor = _floor(vise)
    if job is None or floor is None:
        return
    station = stationPlacement(vise)
    lift = _bottom(job, station) - floor
    up = station.Rotation.multVec(Vector(0, 0, 1))
    if len(shareGroup(vise)) > 1:
        moveModel(job, up * -lift)
        return
    placement = FreeCAD.Placement(vise.Placement)
    placement.move(up * lift)
    with _Free(vise):
        vise.Placement = placement


def _keepBody(vise, before):
    """A self-centering vise moved as its station's opening changes from before, so its body
    stays where it is bolted down: the jaws open and close about it, the fixed jaw's face, the
    station's origin, moving half as far as the opening changes. One following another's
    placement cannot move."""
    if not selfCentering(vise) or memberOf(vise)[0] is None or isFollower(vise):
        return
    change = openingOf(vise) - before
    if abs(change) < 1e-9:
        return
    placement = FreeCAD.Placement(vise.Placement)
    placement.move(stationPlacement(vise).Rotation.multVec(Vector(0, change / 2, 0)))
    with _Free(vise):
        vise.Placement = placement


def _closeJaw(vise):
    """The moving jaw closed on the stock, as far as it opens; a self-centering vise's jaws both,
    the stock pushed between them to the middle of its body."""
    job = memberOf(vise)[0]
    if job is None:
        return
    needed, most, _ = opening(job, vise)
    setOpening(vise, needed if most is None else min(needed, most))
    if selfCentering(vise):
        placement = stationPlacement(vise)
        closing = placement.Rotation.multVec(Vector(0, -1, 0))
        near, far = _stockIn(job, placement)[0]
        moveModel(job, closing * (openingOf(vise) - near - far) / 2)


# the Job's axes a vise is turned to, by name
Directions = {
    "+X": Vector(1, 0, 0),
    "-X": Vector(-1, 0, 0),
    "+Y": Vector(0, 1, 0),
    "-Y": Vector(0, -1, 0),
    "+Z": Vector(0, 0, 1),
    "-Z": Vector(0, 0, -1),
}


def orientation(up, fixed):
    """orientation(up, fixed) ... the turn of a vise whose top faces up and whose fixed jaw lies
    toward fixed, both one of Directions: the Job's axis the vise's +Z and its +Y point along."""
    z = Directions[up]
    y = Directions[fixed]
    if abs(z.dot(y)) > 1e-9:
        raise ValueError("The fixed jaw cannot face up or down: %s and %s" % (up, fixed))
    x = y.cross(z)
    return FreeCAD.Rotation(
        FreeCAD.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
    )


def orientationOf(rotation):
    """orientationOf(rotation) ... the (up, fixed) names of a vise turned so, None where it is
    not turned square to the Job's axes."""

    def named(v):
        for name, d in Directions.items():
            if (v - d).Length < 1e-6:
                return name
        return None

    up = named(rotation.multVec(Vector(0, 0, 1)))
    fixed = named(rotation.multVec(Vector(0, 1, 0)))
    return (up, fixed) if up and fixed else None


def _setPath(obj, path, value):
    """The property at path, as an expression names it (.Placement.Base.y), set to value."""
    names = path.lstrip(".").split(".")
    chain = [obj]
    for name in names[:-1]:
        chain.append(getattr(chain[-1], name))
    setattr(chain[-1], names[-1], getattr(value, "Value", value))
    for i in range(len(names) - 2, -1, -1):
        setattr(chain[i], names[i], chain[i + 1])


def drive(vise):
    """drive(vise) ... the vise's parts moved as its settings say."""
    doc = vise.Document
    for entry in getattr(vise, "Drives", []):
        name, path, expression = entry.split("\t")
        part = doc.getObject(name)
        if part is None:
            continue
        try:
            # evaluated on the vise: its names are of its own document
            value = vise.evalExpression(expression)
            _setPath(part, path, value)
        except Exception as e:
            Path.Log.warning("%s: %s %s = %s: %s" % (vise.Label, name, path, expression, e))


def _holdsSettings(obj):
    """Whether obj holds settings to copy: a VarSet, a vise, or a clamp from a file of its own."""
    return obj.TypeId == "App::VarSet" or getattr(
        getattr(obj, "Proxy", None), "holdsSettings", False
    )


def _copySettings(source, vise):
    """The settings added to source, a VarSet or a vise, added to vise: their kind, group, value
    and how they are edited. How a vise was seated is not copied, nor its jaws: setJaws makes
    them; nor where a clamp or a stop is placed round the stock."""
    for name in source.PropertiesList:
        if name in vise.PropertiesList or PROPERTY_ADDED not in source.getPropertyStatus(name):
            continue
        group = source.getGroupOfProperty(name)
        # FreeCAD's own, like Part's shape cache, start with an underscore
        if (
            group in ("Seat", "Jaws", "Placed", "Source", "About", "Lever")
            or name == "Active"
            or name.startswith("_")
        ):
            continue
        _copySetting(source, vise, name)


def _copySetting(source, vise, name):
    """One setting of source added to vise as source has it."""
    kind = source.getTypeIdOfProperty(name)
    vise.addProperty(
        kind, name, source.getGroupOfProperty(name), source.getDocumentationOfProperty(name)
    )
    if kind == "App::PropertyEnumeration":
        setattr(vise, name, source.getEnumerationsOfProperty(name))
    setattr(vise, name, getattr(source, name))
    vise.setEditorMode(name, source.getEditorMode(name))


def _isGroup(obj):
    return obj.hasExtension("App::GeoFeatureGroupExtension")


def recompute(doc):
    """recompute(doc) ... doc recomputed: all of it; or, while the workholding panel holds back
    the toolpaths (the document's RecomputesFrozen set), its Jobs' stops, clamps and vises, their
    stock and model and what these need, not the operations: moving the stock does not compute
    the toolpaths again until the panel's changes are kept."""
    if getattr(doc, "Recomputing", False):
        # asked while the document recomputes, as it says it is done: it refuses a recompute
        # inside its own, so each one changed recomputed by itself, what it needs first
        _recomputeTouched(doc)
        return
    if not getattr(doc, "RecomputesFrozen", False):
        doc.recompute()
        return
    found = []

    def add(obj):
        if obj is None or obj in found:
            return
        found.append(obj)
        for child in getattr(obj, "Group", []) or []:
            add(child)

    for job in doc.Objects:
        if hasattr(job, "Workholding") and hasattr(job, "Stock"):
            add(job.Workholding)
            add(job.Stock)
            for model in getattr(getattr(job, "Model", None), "Group", []) or []:
                add(model)
    if found:
        doc.recompute(found, True)


def _recomputeTouched(doc):
    """The document's objects changed recomputed one by one, each after what it needs."""
    touched = [o for o in doc.Objects if "Touched" in o.State]
    wanted = set(o.Name for o in touched)
    done = []

    def visit(obj):
        if obj.Name in done:
            return
        done.append(obj.Name)
        for need in obj.OutList:
            if need.Name in wanted:
                visit(need)
        obj.recompute()

    for obj in touched:
        visit(obj)


def _instance(job, label, members, placement, proxy=None, name="Vise"):
    """A vise of the Job's Workholding made of members, (object, expressions) pairs: the
    settings of each VarSet or vise among them copied onto it, each part linked, driven as the
    expressions say. Of proxy's class, a vise when None; a clamp from its own file is laid out
    so too."""
    doc = job.Document
    proxy = proxy or ObjectVise
    container = doc.addObject("App::GeometryPython", name)
    proxy(container)
    if FreeCAD.GuiUp:
        proxy.viewProvider(container.ViewObject)
    container.Label = label
    container.Placement = placement
    names = {}
    for obj, _ in members:
        if _holdsSettings(obj):
            _copySettings(obj, container)
            names[obj.Name] = container.Name
    drives = []
    for obj, expressions in members:
        if _holdsSettings(obj):
            continue
        # a Python link, so deleting one part of the vise deletes the whole vise
        link = doc.addObject("App::LinkPython", name + "Link")
        link.LinkedObject = obj.LinkedObject if obj.isDerivedFrom("App::Link") else obj
        if FreeCAD.GuiUp:
            import Path.Workholding.Gui.ViewProvider as Gui

            Gui.ViewProviderViseMember(link.ViewObject)
        link.Label = obj.Label
        link.Placement = obj.Placement
        container.addObject(link)
        for path, expression in expressions:
            drives.append("\t".join((link.Name, path, _expressionNames(expression, names))))
    job.Workholding.addObject(container)
    container.Drives = drives
    # where its file came from: as the one it is another of, or the file its parts are from
    like = next((o for o, _ in members if _holdsSettings(o) and o.Document == doc), None)
    path = next(
        (
            l.Document.FileName
            for l in (o.LinkedObject if o.isDerivedFrom("App::Link") else o for o, _ in members)
            if l is not None and l.Document != doc and l.Document.FileName
        ),
        None,
    )
    PathSource.keepSource(container, path, like)
    return container


def addVise(job, source, placement=None):
    """addVise(job, source, placement=None) ... a vise put in the Job's Workholding from source,
    the container in a vise's own file: its settings copied in, so this one opens on its own,
    its parts linked from the file. Returns the new vise."""
    if not isVise(source):
        raise ValueError("%s is not a vise: it has no Opening" % source.Label)
    if schemaOf(source) > ViseSchema:
        raise ValueError(
            translate("CAM", "%s is laid out for a newer FreeCAD (vise schema %d, this knows %d)")
            % (source.Label, schemaOf(source), ViseSchema)
        )
    members = sourceMembers(source)
    vise = _instance(job, source.Label, members, placement or FreeCAD.Placement())
    if len(stations(vise)) > 1:
        _addStation(vise, 1)
    recompute(job.Document)
    return vise


def sourceMembers(source):
    """sourceMembers(source) ... the settings and parts of the container in a vise's or a clamp's
    own file, as they are put in a Job: each VarSet and each part with a shape, with the
    expressions placing it."""
    return [
        (o, [(p, e) for p, e in o.ExpressionEngine if p.startswith(".Placement")])
        for o in source.Group
        if o.TypeId == "App::VarSet" or (hasattr(o, "Shape") and o.TypeId != "App::Origin")
    ]


def schemaOf(container):
    """schemaOf(container) ... the layout a vise or its file follows, its ViseSchema, 1 where it
    does not say."""
    return int(_setting(container, "ViseSchema", 1))


def _same(a, b):
    return getattr(a, "Value", a) == getattr(b, "Value", b) if type(a) is type(b) else a == b


def refreshSettings(vise, load=False):
    """refreshSettings(vise, load=False) ... a vise of a Job made as its file now says: the
    settings the file keeps fixed (read only there: the jaws' height, how far it opens, its
    steps...) and how its settings move its parts. Its Opening, how it was seated and its jaws
    stay. Returns the names of the settings that changed, none when the file is not open or has
    not changed. A file FreeCAD loaded only in part, or not at all, holds no vise to read: load
    opens it whole first (see Source.sourceDocument). A vise whose parts were imported into its
    document has no file."""
    if not isinstance(getattr(vise, "Proxy", None), ObjectVise):
        return []
    # the container in the vise's own file its parts are linked from
    doc = PathSource.sourceDocument(vise, load)
    source = viseIn(doc) if doc is not None else None
    if source is None:
        return []
    changed = []
    names = {}
    for varset in [o for o in source.Group if o.TypeId == "App::VarSet"]:
        names[varset.Name] = vise.Name
        for name in varset.PropertiesList:
            if PROPERTY_ADDED not in varset.getPropertyStatus(
                name
            ) or "ReadOnly" not in varset.getEditorMode(name):
                continue
            if varset.getGroupOfProperty(name) in ("Seat", "Jaws") or name.startswith("_"):
                continue
            value = getattr(varset, name)
            if not hasattr(vise, name):
                _copySetting(varset, vise, name)
            elif _same(getattr(vise, name), value):
                continue
            else:
                setattr(vise, name, value)
            changed.append(name)
    # how the settings move the parts, as the file has it now; the soft jaws' own kept
    linked = {}
    for o in vise.Group:
        target = getattr(o, "LinkedObject", None) if o.isDerivedFrom("App::Link") else None
        if target is not None:
            linked[target.Name] = o.Name
    drives = [e for e in vise.Drives if e.split("\t")[0] not in linked.values()]
    for o in source.Group:
        if o.Name not in linked:
            continue
        for path, expression in o.ExpressionEngine:
            if path.startswith(".Placement"):
                drives.append(
                    "\t".join((linked[o.Name], path, _expressionNames(expression, names)))
                )
    if sorted(drives) != sorted(vise.Drives):
        vise.Drives = drives
        changed.append("Drives")
    if changed:
        drive(vise)
        Path.Log.info(
            translate("CAM", "%s: brought up to date with its file: %s")
            % (vise.Label, ", ".join(changed))
        )
    return changed


def refreshAll(doc):
    """refreshAll(doc) ... the document's vises brought up to date with their files, each file
    opened whole if FreeCAD loaded it only in part. Returns the vises that changed."""
    changed = []
    for obj in doc.Objects:
        if not isVise(obj):
            continue
        try:
            if refreshSettings(obj, load=True):
                changed.append(obj)
        except Exception as e:
            Path.Log.warning("%s: %s" % (obj.Label, e))
    return changed


def viseIn(doc):
    """viseIn(doc) ... the vise a vise's own file holds: its outermost container with an
    Opening, or None."""
    for obj in doc.RootObjects:
        if _isGroup(obj) and isVise(obj):
            return obj
    return None


def addAnother(member, offset=None):
    """addAnother(member, offset=None) ... another of a piece of the Job's workholding beside it:
    a vise with its own settings, its parts linked from where the first's are, or a copy of a
    clamp or dog, free of the side of the stock the first was placed on. Offset, a vector, from
    the first, else across the vise beside it."""
    job, member = memberOf(member)
    if member is None:
        raise ValueError("Not a piece of a Job's workholding")
    import Path.Workholding.Lever as PathLever

    if PathLever.isLever(member):
        # one more on its side, standing as it does
        return PathLever.another(job, member)
    doc = job.Document
    if offset is None:
        # its width across, in its own frame, and a gap
        where = placementOf(member)
        shape = getattr(member, "Shape", None)
        width = 100.0
        if shape is not None and not shape.isNull():
            width = shape.transformed(where.inverse().toMatrix()).BoundBox.XLength
        offset = where.Rotation.multVec(Vector(width + 25.0, 0, 0))
    placement = FreeCAD.Placement(member.Placement)
    placement.move(offset)
    if _isGroup(member) and (isVise(member) or _holdsSettings(member)):
        # its soft jaws are made from its settings, not linked; a clamp from a file of its own
        # made as it is
        if _holdsSettings(member):
            proxy, name = type(member.Proxy), member.Name.rstrip("0123456789")
        else:
            proxy, name = None, "Vise"
        copy = _instance(job, member.Label, _members(member), placement, proxy, name)
        if len(stations(copy)) > 1:
            _addStation(copy, 1)
        if hasattr(member, "Jaws") and canChangeJaws(copy):
            setJaws(
                copy,
                member.Jaws,
                member.SoftThickness.Value,
                member.SoftHeight.Value,
                PathJaws.parseSteps(member.Steps),
                gripJaws=gripJawsOf(member),
            )
    else:
        copy = doc.copyObject(member, False)
        copy.Placement = placement
        job.Workholding.addObject(copy)
    # where the first is placed round the stock is its own
    for name in copy.PropertiesList:
        if copy.getGroupOfProperty(name) == "Placed":
            copy.removeProperty(name)
    recompute(doc)
    return copy


def wallAt(frame, z):
    """wallAt(frame, z) ... where the fixed jaw's face is at height z, along Y, in a frame as
    jawFrame gives it: its face, or cut back to a step's wall above the step's floor, the
    deepest cut where they overlap. Stock whose bottom is at z is held there."""
    walls = [wall for floor, wall in frame["steps"] if floor <= z + 1e-6]
    return max(walls, default=frame["face"])


def _jawLoss(frame, wall):
    """What the jaws take of the Opening beyond the stock held against wall: the soft jaws
    standing proud of the hard plates, less how far the wall is cut back on each."""
    return frame["gapLoss"] - 2 * (wall - frame["face"])


def opening(job, vise, step=None):
    """opening(job, vise, step=None) ... how far the vise must open for the stock as it stands,
    the most it opens (None if it does not say), and how far for the stock turned a quarter
    round: held on step of its jaws, as it was last seated when None. In the station its stock
    is in."""
    (near, far), (low, high), (bottom, _) = _stockIn(job, stationPlacement(vise))
    frame = _jawFrame(vise)
    if step is None:
        step = _seatStep(vise, frame)
    elif not 0 < step <= len(frame["steps"]):
        step = 0
    wall = frame["steps"][step - 1][1] if step else wallAt(frame, bottom)
    loss = _jawLoss(frame, wall)
    return far - near + loss, viseSetup(vise)["maxOpening"], high - low + loss


def vises(job):
    """vises(job) ... the vises in the Job's Workholding group."""
    group = getattr(job, "Workholding", None)
    return [o for o in getattr(group, "Group", []) or [] if isVise(o)]


def memberOf(obj):
    """memberOf(obj) ... the Job and the member of its Workholding group obj is, or is part of:
    a click on a part of a vise is the vise. (None, None) if obj is no workholding."""
    found = (None, None)
    for job in obj.Document.Objects:
        group = getattr(job, "Workholding", None)
        if group is None or not hasattr(job, "Proxy"):
            continue
        for member in getattr(group, "Group", []) or []:
            if member == obj:
                return job, member
            if found[1] is None and obj in member.OutListRecursive:
                # a shared vise reaches the one it follows, and its parts: not its own
                owner = getattr(member, "Follows", None)
                if owner is None or not (obj == owner or obj in owner.OutListRecursive):
                    found = (job, member)
    return found


def isMember(obj):
    """isMember(obj) ... whether obj is a piece of a Job's workholding, or a part of one."""
    return memberOf(obj)[1] is not None


def isActive(member):
    """isActive(member) ... whether a piece of workholding is in use: shown and hit."""
    return getattr(member, "Active", True)


def setActive(member, active):
    """setActive(member, active) ... a piece of workholding in use or not. Not in use, it stays in
    the document but the simulator neither shows it nor finds anything hitting it, the way an
    operation set inactive is not run."""
    if not hasattr(member, "Active"):
        member.addProperty(
            "App::PropertyBool",
            "Active",
            "Workholding",
            QT_TRANSLATE_NOOP("App::Property", "In use: shown and found hit in the simulator"),
        )
    member.Active = active


def placementOf(obj):
    """placementOf(obj) ... where obj stands in the document. A link has no global placement of
    its own: its placement within whatever part holds it, and the linked object's too when the
    link carries its transform."""
    if hasattr(obj, "getGlobalPlacement"):
        return obj.getGlobalPlacement()
    placement = obj.Placement
    linked = getattr(obj, "LinkedObject", None)
    if getattr(obj, "LinkTransform", False) and hasattr(linked, "Placement"):
        placement = placement.multiply(linked.Placement)
    parent = obj.getParentGeoFeatureGroup()
    return parent.getGlobalPlacement().multiply(placement) if parent else placement


def moveModel(job, offset):
    """moveModel(job, offset) ... the Job's models moved by offset, a vector, and what is placed
    on the part without being attached to it with them: work planes set where they are, the text
    and sketches operations are made from, and the stock. The workholding stays."""
    import Path.Main.Job as PathJob

    carried = PathJob.objectsInModelFrame(job)
    for model in job.Model.Group:
        model.Placement.move(offset)
    for obj in carried:
        obj.Placement.move(offset)
    # the stock is the material the part is cut from: it goes with it, made from the models'
    # box or not, which takes its size from them but its place only when made
    if job.Stock:
        job.Stock.Placement.move(offset)
    PathJob.touchOperations(job)


def partTurn(job):
    """partTurn(job) ... how the Job's part is turned, its model's rotation: the sides a vise
    names, Bottom, Front and so on, are the part's own, as it is modeled."""
    models = getattr(getattr(job, "Model", None), "Group", None) or []
    return FreeCAD.Rotation(models[0].Placement.Rotation) if models else FreeCAD.Rotation()


def turnModel(job, rotation, center):
    """turnModel(job, rotation, center) ... the Job's part turned by rotation about center, as
    moveModel moves it: its models, what is placed on it without being attached to it, and its
    stock; a stock made from the models' box made about them again where they now are."""
    import Path.Main.Job as PathJob
    import Path.Main.Stock as PathStock

    turn = FreeCAD.Placement(Vector(), rotation, center)
    carried = PathJob.objectsInModelFrame(job)
    stock = job.Stock
    fromBase = isinstance(getattr(stock, "Proxy", None), PathStock.StockFromBase)
    if fromBase:
        before = PathStock.shapeBoundBox(job.Model.Group)
        corner = stock.Placement.Base - Vector(before.XMin, before.YMin, before.ZMin)
    for model in job.Model.Group:
        model.Placement = turn.multiply(model.Placement)
    for obj in carried:
        obj.Placement = turn.multiply(obj.Placement)
    if fromBase:
        after = PathStock.shapeBoundBox(job.Model.Group)
        stock.Placement = FreeCAD.Placement(
            Vector(after.XMin, after.YMin, after.ZMin) + corner, stock.Placement.Rotation
        )
        stock.recompute()
    elif stock is not None:
        stock.Placement = turn.multiply(stock.Placement)
    PathJob.touchOperations(job)


def _extents(shape, origin, direction):
    """How far shape reaches along direction from origin, (lowest, highest): from its surfaces,
    not its corners, so a round stock counts its sides."""
    turn = FreeCAD.Placement(Vector(), FreeCAD.Rotation(direction, Vector(0, 0, 1)))
    box = shape.transformed(turn.toMatrix()).optimalBoundingBox(False)
    at = origin.dot(direction)
    return box.ZMin - at, box.ZMax - at


def _closingIn(job, placement, shiftA, width):
    """The stock's extents along the way the jaws close, in the frame of placement, (near, far):
    of what the jaws reach across, width centered on them, once the stock is moved shiftA across
    them; a long stock turned in them is held by its slice there, not its whole length. The
    whole stock when width is not known or nothing is there."""
    import Part

    closing = placement.Rotation.multVec(Vector(0, -1, 0))
    shape = job.Stock.Shape
    if width:
        big = shape.BoundBox.DiagonalLength * 2 + width
        slab = Part.makeBox(width, big, big)
        slab.Placement = placement.multiply(
            FreeCAD.Placement(Vector(-width / 2 - shiftA, -big / 2, -big / 2), FreeCAD.Rotation())
        )
        piece = shape.common(slab)
        if not piece.isNull() and piece.Volume > 1e-9:
            return _extents(piece, placement.Base, closing)
    return _extents(shape, placement.Base, closing)


def _remember(vise, onParallels, close, parallels, step=0, kit=None):
    """How the stock was seated in the vise, kept on it: seated, held to its seat from then on;
    on parallels, how high, thick and long they are, from which set, and whether soft; on a step
    of its jaws; the jaw closed on it. Where the stock sits is the vise's placement: its grip and
    offset are found from that, not kept. The parallels are made, or taken away."""
    for name, kind, doc in (
        (
            "Seated",
            "App::PropertyBool",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Held to its seat: it slides along the jaws and up, not into them or turned",
            ),
        ),
        (
            "OnParallels",
            "App::PropertyBool",
            QT_TRANSLATE_NOOP("App::Property", "The stock seated on parallels"),
        ),
        (
            "Parallels",
            "App::PropertyLength",
            QT_TRANSLATE_NOOP("App::Property", "How tall the parallels the stock stands on are"),
        ),
        (
            "ParallelThickness",
            "App::PropertyLength",
            QT_TRANSLATE_NOOP("App::Property", "How thick each parallel is"),
        ),
        (
            "ParallelLength",
            "App::PropertyLength",
            QT_TRANSLATE_NOOP("App::Property", "How long the parallels are, across the jaws"),
        ),
        (
            "ParallelsCuttable",
            "App::PropertyBool",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Soft parallels, aluminum or plastic: a tool cutting them is warned of, not a "
                "crash",
            ),
        ),
        (
            "ParallelSet",
            "App::PropertyString",
            QT_TRANSLATE_NOOP(
                "App::Property", "The set the parallels are from: unit, type, thickness, height"
            ),
        ),
        (
            "SeatStep",
            "App::PropertyInteger",
            QT_TRANSLATE_NOOP(
                "App::Property", "The step of the jaws the stock stands on, 0 for none"
            ),
        ),
        (
            "CloseJaw",
            "App::PropertyBool",
            QT_TRANSLATE_NOOP("App::Property", "The moving jaw closed on the stock"),
        ),
    ):
        if not hasattr(vise, name):
            vise.addProperty(kind, name, "Seat", doc)
            if name == "ParallelThickness":
                # a standard set's, until one is chosen
                vise.ParallelThickness = PathParallels.DefaultThickness
            elif name == "ParallelLength":
                vise.ParallelLength = PathParallels.DefaultLength
    # kept before, found from the placement now
    for name in ("Grip", "Offset"):
        if hasattr(vise, name) and vise.getGroupOfProperty(name) == "Seat":
            vise.removeProperty(name)
    with _Free(vise):
        vise.OnParallels = onParallels
        if parallels is not None:
            vise.Parallels = max(0.0, parallels)
        if kit is not None:
            vise.ParallelThickness = kit.thickness
            vise.ParallelLength = kit.length
            vise.ParallelsCuttable = kit.cuttable
            vise.ParallelSet = kit.name
        vise.SeatStep = step
        vise.CloseJaw = close
        vise.Seated = True
    # on the floor or a step: no parallels to show
    for name in ("Parallels", "ParallelThickness", "ParallelLength", "ParallelsCuttable"):
        vise.setEditorMode(name, [] if onParallels else ["Hidden"])
    vise.setEditorMode("ParallelSet", ["ReadOnly"] if onParallels else ["Hidden"])
    vise.setEditorMode("SeatStep", [] if step else ["Hidden"])
    _makeParallels(vise)


def _withMovingJaw(vise, part):
    """The Drives moving part, placed in the vise's frame as the moving jaw of a vise of one
    station is drawn, with the moving jaw of the station the stock is in: along its -Y by the
    station's opening."""
    name = "%s.%s" % (_openingHolder(vise).Name, openingName(vise))
    frame = stationFrame(vise)
    if frame.isIdentity():
        return ["\t".join((part.Name, ".Placement.Base.y", "-" + name))]
    closing = frame.Rotation.multVec(Vector(0, -1, 0))
    return [
        "\t".join(
            (
                part.Name,
                ".Placement.Base." + axis,
                "(%s mm) + (%s) * %s"
                % (_number(getattr(frame.Base, axis)), _number(getattr(closing, axis)), name),
            )
        )
        for axis in "xyz"
    ]


def parallelsOf(vise):
    """parallelsOf(vise) ... the parallels made for the vise, by side; none when the stock does
    not stand on them."""
    return {o.Side: o for o in getattr(vise, "Group", []) or [] if PathParallels.isParallel(o)}


def _makeParallels(vise):
    """The vise's parallels made as its seat says: on parallels, a pair, the moving one driven by
    the Opening as the moving jaw is; on the floor or a step, none. A vise that is not one of a
    Job's own, a part with a VarSet, has its parallels' height only."""
    if not isinstance(getattr(vise, "Proxy", None), ObjectVise):
        return []
    parallels = parallelsOf(vise)
    names = [o.Name for o in parallels.values()]
    drives = [e for e in vise.Drives if e.split("\t")[0] not in names]
    if getattr(vise, "OnParallels", False) and vise.Parallels.Value > 0:
        for side in Sides:
            if side not in parallels:
                parallels[side] = PathParallels.create(vise, side)
        # in the station the stock is in, the moving one with its moving jaw
        frame = stationFrame(vise)
        for parallel in parallels.values():
            if not parallel.Placement.Rotation.isSame(frame.Rotation, 1e-9):
                parallel.Placement = FreeCAD.Placement(parallel.Placement.Base, frame.Rotation)
        if not parallels["Fixed"].Placement.isSame(frame, 1e-9):
            parallels["Fixed"].Placement = frame
        drives += _withMovingJaw(vise, parallels["Moving"])
        if sorted(drives) != sorted(vise.Drives):
            vise.Drives = drives
        drive(vise)
        for parallel in parallels.values():
            PathParallels.color(parallel)
            parallel.touch()
        return [parallels[side] for side in Sides]
    if drives != list(vise.Drives):
        vise.Drives = drives
    for parallel in parallels.values():
        vise.Document.removeObject(parallel.Name)
    return []


def isCuttable(obj):
    """isCuttable(obj) ... whether a part of a vise is cut into on purpose, warned of and not a
    crash: a soft jaw, or soft parallels."""
    if PathJaws.isSoftJaw(obj):
        return True
    if PathParallels.isParallel(obj):
        vise = obj.getParentGeoFeatureGroup()
        return bool(vise is not None and getattr(vise, "ParallelsCuttable", False))
    return False


def takesParallels(container):
    """takesParallels(container) ... whether stock can stand on parallels in the vise: not where
    its file says TakesParallels is false, as on a vise whose parallels are built in."""
    return bool(_setting(container, "TakesParallels", True))


def selfCentering(container):
    """selfCentering(container) ... whether both of the vise's jaws close, about the middle of its
    body, as its file says SelfCentering: its body then moves half as far as its moving jaw, and
    stays put as the vise opens and closes."""
    return bool(_setting(container, "SelfCentering", False))


def _isOpening(name):
    """Whether name is that of a station's opening: Opening, Opening2, Opening3..."""
    return re.fullmatch(r"Opening(?:[2-9]|[1-9]\d+)?", name) is not None


def stations(container):
    """stations(container) ... the frames of the vise's stations in its own, the first its own
    origin: as many as its file's Stations, from its StationFrames; one, the vise's own frame,
    where it does not say."""
    count = _setting(container, "Stations")
    frames = [FreeCAD.Placement(p) for p in _setting(container, "StationFrames", [])]
    frames = frames or [FreeCAD.Placement()]
    count = len(frames) if count is None else max(1, int(count))
    return (frames + [FreeCAD.Placement()] * count)[:count]


def station(vise):
    """station(vise) ... the station of the vise its Job's stock is in, counted from 1: its
    Station, 1 where it has none."""
    count = len(stations(vise))
    return min(max(int(getattr(vise, "Station", 1) or 1), 1), count)


def stationFrame(vise, number=None):
    """stationFrame(vise, number=None) ... the frame of station number of the vise in its own,
    of the one its stock is in when None."""
    return stations(vise)[(number or station(vise)) - 1]


def stationPlacement(vise, number=None):
    """stationPlacement(vise, number=None) ... where station number of the vise stands in the
    document, the one its stock is in when None: its origin on that station's fixed jaw's face,
    at the jaw tops, centered across them, its jaws closing along its -Y, as a vise of one
    station is laid out."""
    return placementOf(vise).multiply(stationFrame(vise, number))


def openingName(vise, number=None):
    """openingName(vise, number=None) ... the name of the opening of station number of the vise,
    the one its stock is in when None: Opening for the first, Opening2, Opening3... the others."""
    number = number or station(vise)
    return "Opening" if number == 1 else "Opening%d" % number


def _openingHolder(vise, number=None):
    """What holds the opening of the vise's station, the vise or a VarSet; None if none does."""
    return _holderOf(vise, openingName(vise, number))


def openingOf(vise, number=None):
    """openingOf(vise, number=None) ... the opening of station number of the vise in mm, the one
    its stock is in when None."""
    return getattr(_openingHolder(vise, number), openingName(vise, number)).Value


def setOpening(vise, value, number=None):
    """setOpening(vise, value, number=None) ... the opening of station number of the vise set to
    value, mm, the one its stock is in when None."""
    holder = _openingHolder(vise, number)
    if holder is None:
        raise ValueError(translate("CAM", "%s has no %s") % (vise.Label, openingName(vise, number)))
    setattr(holder, openingName(vise, number), value)


def _addStation(vise, number):
    """The vise's Station added, if it has none, and set to number."""
    if not hasattr(vise, "Station"):
        vise.addProperty(
            "App::PropertyInteger",
            "Station",
            "Seat",
            QT_TRANSLATE_NOOP("App::Property", "The station of the vise the stock is in"),
        )
        vise.setEditorMode("Station", ["ReadOnly"])
    vise.Station = number


def setStation(vise, number):
    """setStation(vise, number) ... the Job's stock to go in station number of the vise, counted
    from 1: one free, not one a Job sharing the vise has. Seat the stock again to put it there."""
    count = len(stations(vise))
    if not 1 <= number <= count:
        raise ValueError(
            translate("CAM", "%s has stations 1 to %d: not %d") % (vise.Label, count, number)
        )
    if number != station(vise) and number not in freeStations(vise):
        raise ValueError(
            translate("CAM", "Station %d of %s is another Job's") % (number, vise.Label)
        )
    _addStation(vise, number)


def isFollower(vise):
    """isFollower(vise) ... whether the vise is another Job's shared: placed where its owner
    is."""
    return getattr(vise, "Follows", None) is not None


def ownerOf(vise):
    """ownerOf(vise) ... the vise a shared vise follows, the vise itself if it follows none."""
    return getattr(vise, "Follows", None) or vise


def followers(vise):
    """followers(vise) ... the vises of other Jobs following the vise, as the document has them;
    none for one that follows another."""
    if isFollower(vise) or vise.Document is None:
        return []
    return [o for o in vise.Document.Objects if getattr(o, "Follows", None) == vise]


def shareGroup(vise):
    """shareGroup(vise) ... the vises of the Jobs sharing the vise: its owner, then those
    following it; the vise alone if it is not shared."""
    owner = ownerOf(vise)
    return [owner] + followers(owner)


def isShared(vise):
    """isShared(vise) ... whether other Jobs share the vise: it then stays where it is, turned as
    it is, for all of them, each Job's part moving to it."""
    return len(shareGroup(vise)) > 1


def sharedWith(vise):
    """sharedWith(vise) ... the other Jobs sharing the vise, each with a vise of its own."""
    return [
        job for job in (memberOf(o)[0] for o in shareGroup(vise) if o != vise) if job is not None
    ]


def freeStations(vise):
    """freeStations(vise) ... the stations of the vise no Job sharing it has, counted from 1."""
    taken = {station(o) for o in shareGroup(vise)}
    return [n for n in range(1, len(stations(vise)) + 1) if n not in taken]


def canShare(vise, job=None):
    """canShare(vise, job=None) ... whether another Job, job if given, can share the vise: one of
    more than one station, one of them free, no vise of it in that Job already."""
    owner = ownerOf(vise)
    if len(stations(owner)) < 2 or not freeStations(owner):
        return False
    return job is None or all(memberOf(o)[0] != job for o in shareGroup(owner))


def _members(vise):
    """The settings and parts of a vise of a Job as _instance takes them: the vise's settings and
    its linked parts, each with the expressions driving it. Its soft jaws, grips and parallels
    are made from its settings, not linked."""
    drives = [entry.split("\t") for entry in getattr(vise, "Drives", [])]
    members = [(vise, [])] if _holdsSettings(vise) else []
    members += [
        (o, list(o.ExpressionEngine) + [(p, e) for n, p, e in drives if n == o.Name])
        for o in vise.Group
        if not PathJaws.isSoftJaw(o) and not PathJaws.isGrip(o) and not PathParallels.isParallel(o)
    ]
    return members


def _follow(vise, owner):
    """The vise placed by expression where owner is, from now on; a piece that says how it
    follows another, a stop on its other face, as it says."""
    if not hasattr(vise, "Follows"):
        vise.addProperty(
            "App::PropertyLinkHidden",
            "Follows",
            "Seat",
            QT_TRANSLATE_NOOP("App::Property", "The vise of another Job this one is placed with"),
        )
        vise.setEditorMode("Follows", ["Hidden"])
    vise.Follows = owner
    follows = getattr(getattr(vise, "Proxy", None), "follows", None)
    if follows is not None:
        follows(vise, owner)
    else:
        vise.setExpression("Placement", "%s.Placement" % owner.Name)


def _unfollow(vise):
    """The vise placed on its own again, where it is; what else it took from the one it followed,
    its own as it is."""
    owner = getattr(vise, "Follows", None)
    placement = FreeCAD.Placement(vise.Placement)
    vise.setExpression("Placement", None)
    if owner is not None:
        named = re.compile(r"(?<![\w.])%s\." % re.escape(owner.Name))
        for path, expression in list(vise.ExpressionEngine):
            if named.search(expression):
                vise.setExpression(path, None)
    with _Free(vise):
        vise.Placement = placement
    if hasattr(vise, "Follows"):
        vise.Follows = None


def shareVise(owner, job, number=None):
    """shareVise(owner, job, number=None) ... the vise owner, of another Job, shared with job, its
    stock to go in station number, the first free when None: a vise of job's own, of the same
    file, placed by expression where the owner is, its Station number. A shared vise, not the
    owner, shares its owner: those sharing always follow the owner. Only a vise of more than
    one station is shared, each Job in a station of its own, a Job in one station only, as it
    holds one stock. Returns the new vise."""
    owner = ownerOf(owner)
    if len(stations(owner)) < 2:
        raise ValueError(
            translate("CAM", "%s has one station: only one Job can hold stock in it") % owner.Label
        )
    if any(memberOf(o)[0] == job for o in shareGroup(owner)):
        raise ValueError(
            translate("CAM", "%s already has %s: a Job holds one stock, in one station")
            % (job.Label, owner.Label)
        )
    free = freeStations(owner)
    if number is None:
        if not free:
            raise ValueError(translate("CAM", "Every station of %s is another Job's") % owner.Label)
        number = free[0]
    if number not in free:
        raise ValueError(translate("CAM", "Station %d of %s is not free") % (number, owner.Label))
    vise = _instance(job, owner.Label, _members(owner), FreeCAD.Placement(owner.Placement))
    _addStation(vise, number)
    _follow(vise, owner)
    recompute(job.Document)
    return vise


def release(vise):
    """release(vise) ... the vise no longer shared, before it is removed or its Job is: one that
    follows another just goes, its station free; the owner hands its place to the first
    following it, which stays where it is and is followed by the others from then on. Returns
    the new owner, None if there is none."""
    if isFollower(vise):
        _unfollow(vise)
        return None
    rest = followers(vise)
    if not rest:
        return None
    heir = rest[0]
    _unfollow(heir)
    for other in rest[1:]:
        _follow(other, heir)
    return heir


def _shareOpening(vise, name):
    """An opening of the vise set on those of the other Jobs sharing it too: each shows the
    jaws of every station as they are."""
    value = getattr(vise, name).Value
    for other in shareGroup(vise):
        if (
            other != vise
            and hasattr(other, name)
            and abs(getattr(other, name).Value - value) > 1e-9
        ):
            setattr(other, name, value)


def seating(job, vise):
    """seating(job, vise) ... how the stock sits in the vise now: its grip, from the jaw tops,
    how far off the jaws' center it is across them, and, as it was last seated, whether on
    parallels, the step it stands on (0 for none) and whether the jaw was closed on it; and the
    vise's jaws, as jawFrame says them. In the station its stock is in."""
    placement = stationPlacement(vise)
    _, (lowA, highA), (bottom, _) = _stockIn(job, placement)
    frame = _jawFrame(vise)
    return {
        "grip": frame["top"] - bottom,
        "offset": (lowA + highA) / 2,
        "onParallels": getattr(vise, "OnParallels", False),
        "step": _seatStep(vise, frame),
        "close": getattr(vise, "CloseJaw", True),
        "orientation": orientationOf(partTurn(job).inverted().multiply(placement.Rotation)),
        "jaws": jawFrame(vise),
    }


def offsetAt(job, vise, placement):
    """offsetAt(job, vise, placement) ... how far off the jaws' center the stock is across them,
    as seating says it, with the vise standing at placement, mid-drag."""
    _, (low, high), _ = _stockIn(job, placement.multiply(stationFrame(vise)))
    return (low + high) / 2


def seat(
    job,
    vise,
    grip=None,
    offset=0.0,
    center=True,
    close=True,
    moveVise=False,
    parallels=None,
    rotation=None,
    quiet=False,
    step=0,
):
    """seat(job, vise, grip=None, offset=0.0, center=True, close=True, moveVise=False,
    parallels=None, rotation=None, step=0) ... put the stock in vise, the vise first turned to
    rotation if given, as orientation names it in the part's own sides: against the fixed jaw, its bottom grip below the jaw tops (as it is now
    when None), or with parallels standing that high off the vise's floor, or, step a step of
    its jaws counted from 1, on that step's floor and against its wall; across the jaws centered
    and then offset, or offset from where it is, and the moving jaw closed on it. The part moves,
    the vise staying, or with moveVise the vise moves. A vise of several stations seats it in
    the station its Station says, as a vise of one in its own frame.

    A vise shared with other Jobs is neither moved nor turned, their parts being in it: the part
    moves, and is turned in it to rotation. Returns what it did: the move, the grip, the parallels, the opening and whether it
    fits."""
    setup = viseSetup(vise)
    if setup is None:
        raise ValueError("%s is not a vise: it has no Opening" % vise.Label)
    shared = isShared(vise)
    if moveVise and shared:
        raise ValueError(
            translate("CAM", "%s is shared with other Jobs: the part moves to it, not the vise")
            % vise.Label
        )
    stationAt = stationFrame(vise)
    if rotation is not None:
        # turned as the part's own sides say
        rotation = partTurn(job).multiply(rotation)
    if rotation is not None and shared:
        # the vise stays: the part turned in it instead
        turn = stationPlacement(vise).Rotation.multiply(rotation.inverted())
        if not turn.isSame(FreeCAD.Rotation(), 1e-7):
            turnModel(job, turn, job.Stock.Shape.BoundBox.Center)
        rotation = None
    kit = None
    if isinstance(parallels, PathParallels.Parallel):
        kit, parallels = parallels, parallels.height
    if parallels is not None and parallels > 1e-9 and not takesParallels(vise):
        raise ValueError("%s takes no parallels: the stock stands on its floor" % vise.Label)
    frame = _jawFrame(vise)
    if step and not 0 < step <= len(frame["steps"]):
        raise ValueError("%s's jaws have no step %d" % (vise.Label, step))
    if rotation is not None:
        # the station turned so, the vise with it
        with _Free(vise):
            vise.Placement = FreeCAD.Placement(
                vise.Placement.Base, rotation.multiply(stationAt.Rotation.inverted())
            )
    placement = stationPlacement(vise)
    closing = placement.Rotation.multVec(Vector(0, -1, 0))
    across = placement.Rotation.multVec(Vector(1, 0, 0))
    up = placement.Rotation.multVec(Vector(0, 0, 1))
    (nearC, farC), (lowA, highA), (bottom, _) = _stockIn(job, placement)
    jawHeight = setup["jawHeight"]
    # the grip from the jaw tops
    top, floor = frame["top"], frame["floor"]
    if step:
        # on the step: its floor sets the grip, no parallels under it
        seatZ = frame["steps"][step - 1][0]
        grip = top - seatZ
        parallels = None
    elif parallels is not None:
        if jawHeight is None:
            raise ValueError("%s has no JawHeight to stand the stock off its floor" % vise.Label)
        if parallels < 0:
            raise ValueError("Parallels cannot be lower than the vise's floor")
        grip = top - floor - parallels
    elif grip is None:
        grip = top - bottom
    if grip < 0:
        raise ValueError("The stock would stand above the jaws")
    # the face the stock goes against: the jaw's as it is at the stock's bottom, the fixed
    # jaw's face, or cut back to a step's wall where the bottom is above the step's floor
    wall = wallAt(frame, top - grip)
    if floor is not None and grip > top - floor + 1e-6 and not quiet:
        Path.Log.warning(
            translate("CAM", "%s: a grip of %s is deeper than the jaws, %s")
            % (vise.Label, userLength(grip), userLength(top - floor))
        )

    # the moving jaw's face, or its step's wall, against the stock's far side: what of the stock
    # the jaws reach across, where it will be along them
    shiftA = (-(lowA + highA) / 2 if center else 0.0) + offset
    nearC, farC = _closingIn(job, placement, shiftA, _jawWidth(vise))
    opening = farC - nearC + _jawLoss(frame, wall)
    maxOpening = setup["maxOpening"]
    fits = maxOpening is None or opening <= maxOpening + 1e-6
    if close and selfCentering(vise):
        # both jaws close about the body, which stays: the fixed jaw where they meet the stock
        setOpening(vise, opening if fits else maxOpening)
        placement = stationPlacement(vise)
        _, (lowA, highA), (bottom, _) = _stockIn(job, placement)
        shiftA = (-(lowA + highA) / 2 if center else 0.0) + offset
        nearC, farC = _closingIn(job, placement, shiftA, _jawWidth(vise))
    move = closing * (-wall - nearC) + across * shiftA + up * (top - grip - bottom)
    if moveVise:
        placement = FreeCAD.Placement(vise.Placement)
        placement.move(move * -1)
        with _Free(vise):
            vise.Placement = placement
    else:
        moveModel(job, move)
    if not fits and not quiet:
        Path.Log.warning(
            translate("CAM", "%s opens %s: too little for the stock, %s between the jaws")
            % (vise.Label, userLength(maxOpening), userLength(opening))
        )
    if close:
        setOpening(vise, opening if fits else maxOpening)
    # parallels of no height: on the floor
    _remember(vise, parallels is not None and parallels > 1e-9, close, parallels, step, kit)
    recompute(job.Document)
    return {
        "move": move if not moveVise else move * -1,
        "grip": grip,
        "parallels": top - grip - floor if floor is not None else None,
        "opening": opening,
        "fits": fits,
    }


JawKinds = ["Hard", "Soft", "Grip"]


def _plates(vise):
    """The vise's hard jaw plates, the fixed then the moving: its links to the parts its file
    names in JawPlates. None found, or one short, none."""
    names = list(getattr(vise, "JawPlates", []) or [])[:2]
    found = {}
    for obj in getattr(vise, "Group", []) or []:
        linked = getattr(obj, "LinkedObject", None)
        if linked is not None and linked != obj and linked.Name in names:
            found.setdefault(linked.Name, obj)
    if len(names) < 2 or len(found) < 2:
        return []
    return [found[name] for name in names]


def plateSize(vise):
    """plateSize(vise) ... the vise's fixed hard jaw plate in its frame, in mm: (tH, hH, xMin,
    xMax), into the jaw from its face, down from the jaw tops and its ends across. None if the
    vise's jaws cannot be changed."""
    import Part

    plates = _plates(vise)
    if not plates:
        return None
    shape = Part.getShape(plates[0], "", needSubElement=False, transform=True, noElementMap=True)
    if shape.isNull():
        return None
    bb = shape.BoundBox
    return (bb.YMax, -bb.ZMin, bb.XMin, bb.XMax)


def canChangeJaws(vise):
    """canChangeJaws(vise) ... whether the vise's hard jaw plates can be swapped for soft jaws:
    a vise put in a Job, its file naming its plates in JawPlates; one station, the jaws of
    several keeping their own hard jaws."""
    return (
        isinstance(getattr(vise, "Proxy", None), ObjectVise)
        and len(stations(vise)) == 1
        and bool(_plates(vise))
    )


def softJaws(vise):
    """softJaws(vise) ... the vise's soft jaws, or grip jaws, by the side they are on: Fixed,
    Moving."""
    return {o.Side: o for o in getattr(vise, "Group", []) or [] if PathJaws.isSoftJaw(o)}


def gripsOf(vise):
    """gripsOf(vise) ... the grips of the vise's grip jaws, by (side, index)."""
    return {(o.Side, o.Index): o for o in getattr(vise, "Group", []) or [] if PathJaws.isGrip(o)}


def gripJawsOf(vise):
    """gripJawsOf(vise) ... the vise's grip jaws' grips as setJaws takes them: grip, setback, bite
    in mm and how many on each jaw; None if it has no such settings."""
    if not hasattr(vise, "GripHeight"):
        return None
    return {
        "grip": vise.GripHeight.Value,
        "setback": vise.GripSetback.Value,
        "bite": vise.GripBite.Value,
        "grips": vise.GripCount,
    }


def _jawWidth(vise):
    """How wide the vise's jaws are in mm, as its settings say, else None."""
    width = _setting(vise, "JawWidth")
    return getattr(width, "Value", width)


def builtInSteps(vise):
    """builtInSteps(vise) ... the steps the vise's hard jaws have of their own, as its file's
    JawSteps say them: (height, depth) pairs in mm, down from the jaw tops and in from the face."""
    return PathJaws.parseSteps(getattr(vise, "JawSteps", []))


def _jawFrame(vise):
    """The vise's jaws as jawFrame says them, the floor None where the vise does not say how
    tall its jaws are."""
    jaw = viseSetup(vise)["jawHeight"]
    size = plateSize(vise)
    frame = {
        "kind": "Hard",
        "face": 0.0,
        "top": 0.0,
        "floor": -jaw if jaw is not None else None,
        "steps": [(-h, d) for h, d in builtInSteps(vise)],
        "gapLoss": 0.0,
        "width": size[3] - size[2] if size else _jawWidth(vise),
    }
    kind = getattr(vise, "Jaws", "Hard")
    if size is None or kind not in ("Soft", "Grip"):
        return frame
    plate, plateHeight = size[0], size[1]
    thickness, height = vise.SoftThickness.Value, vise.SoftHeight.Value
    face = plate - thickness
    top = -plateHeight + height
    frame["kind"] = kind
    frame["face"] = face
    frame["top"] = top
    frame["gapLoss"] = 2 * (thickness - plate)
    if kind == "Grip":
        # the jaws' tops the grips' tops; the stock on the jaws' own tops, held by the grips'
        # teeth bitten into it: a step as deep as the grips stand, its wall their teeth and the
        # bite past them, the stock's face as far in
        frame["top"] = top + vise.GripHeight.Value
        frame["steps"] = [(top, face + vise.GripSetback.Value + vise.GripBite.Value)]
    else:
        frame["steps"] = [(top - h, face + d) for h, d in PathJaws.parseSteps(vise.Steps)]
    return frame


def jawFrame(vise):
    """jawFrame(vise) ... the vise's jaws in its own frame, in mm: kind, one of JawKinds; face,
    the fixed jaw's working face along Y; top, the jaw tops; floor, the vise's floor; steps, each
    step's floor and wall on the fixed jaw, (z, y); gapLoss, what the jaws take of the Opening
    beyond the hard plates, both together; width, across the jaws, None where it does not say.
    None if vise is not a vise or does not say how tall its jaws are."""
    if not isVise(vise):
        return None
    frame = _jawFrame(vise)
    return frame if frame["floor"] is not None else None


def _number(value):
    """A number as a step writes it, no trailing zeros."""
    return ("%.6f" % value).rstrip("0").rstrip(".")


def _value(value):
    return float(getattr(value, "Value", value))


def setJaws(vise, kind, thickness=None, height=None, steps=None, gripJaws=None):
    """setJaws(vise, kind, thickness=None, height=None, steps=None, gripJaws=None) ... the vise's
    jaws made kind, one of JawKinds: Hard, the vise's own plates; Soft, a block in place of each,
    thickness from the jaw's body out to its face, height up from the plate's bottom, its steps,
    (height, depth) pairs or "height,depth" strings, cut down from its top and in from its face,
    the same on both; Grip, a steel jaw in place of each, as thick and tall, hardened grips in a
    groove along its top, gripJaws a dict of any of grip, how far they stand above it, setback, their
    teeth behind its face, bite, how far they bite into the stock, in mm, and grips, how many on
    each jaw. What is not given stays as it was, at first the plates' own size and no steps, for
    grip jaws those of common ones for a 6 in. vise. Returns the jaws, fixed then moving, none
    for hard."""
    if kind not in JawKinds:
        raise ValueError("Jaws are one of %s: not %s" % (", ".join(JawKinds), kind))
    if not canChangeJaws(vise):
        raise ValueError("%s's jaws cannot be changed: its file names no jaw plates" % vise.Label)
    plate, plateHeight, _, _ = plateSize(vise)
    proxy = vise.Proxy
    proxy.settingJaws = True
    try:
        _addJawSettings(vise, plate, plateHeight)
        if kind == "Grip" and vise.Jaws != "Grip":
            # grip jaws are their own size, not the plates'
            thickness = PathJaws.GripJaw["thickness"] if thickness is None else thickness
            height = PathJaws.GripJaw["height"] if height is None else height
        thickness = vise.SoftThickness.Value if thickness is None else _value(thickness)
        height = vise.SoftHeight.Value if height is None else _value(height)
        if kind == "Grip":
            gripJaws = dict(gripJaws or {})
            grip = _value(gripJaws.get("grip", vise.GripHeight))
            setback = _value(gripJaws.get("setback", vise.GripSetback))
            bite = _value(gripJaws.get("bite", vise.GripBite))
            grips = int(gripJaws.get("grips", vise.GripCount))
            if grip <= 0 or bite < 0 or grips < 1:
                raise ValueError("grips must stand above the jaw, and be at least one")
            if not (0 < setback and setback + PathJaws.GripJaw["gripWidth"] < thickness):
                raise ValueError(
                    "The grips' teeth must be behind the jaw's face, their groove in the jaw: %s "
                    "behind it, the jaw %s thick" % (_number(setback), _number(thickness))
                )
            vise.GripHeight = grip
            vise.GripSetback = setback
            vise.GripBite = bite
            vise.GripCount = grips
        if steps is None:
            steps = PathJaws.parseSteps(vise.Steps)
        else:
            steps = [
                PathJaws.parseSteps([s])[0] if isinstance(s, str) else (_value(s[0]), _value(s[1]))
                for s in steps
            ]
        if thickness <= 0 or height <= 0:
            raise ValueError("Soft jaws must be thicker and taller than nothing")
        for h, d in steps:
            if not (0 < h < height and 0 < d < thickness):
                raise ValueError(
                    "A step must be cut into the soft jaw: %s down and %s in, the jaw %s tall and "
                    "%s thick" % (_number(h), _number(d), _number(height), _number(thickness))
                )
        vise.SoftThickness = thickness
        vise.SoftHeight = height
        vise.Steps = ["%s,%s" % (_number(h), _number(d)) for h, d in steps]
        vise.Jaws = kind
    finally:
        proxy.settingJaws = False
    jaws = _makeJaws(vise)
    recompute(vise.Document)
    return jaws


def _addJawSettings(vise, plate, plateHeight):
    """The vise's jaw settings added if it has none: hard jaws, soft ones the plates' size."""
    if not hasattr(vise, "Jaws"):
        vise.addProperty(
            "App::PropertyEnumeration",
            "Jaws",
            "Jaws",
            QT_TRANSLATE_NOOP("App::Property", "The vise's own hard jaw plates, or soft jaws"),
        )
        vise.Jaws = JawKinds
        vise.Jaws = "Hard"
    elif list(vise.getEnumerationsOfProperty("Jaws")) != JawKinds:
        # a vise from before grip jaws: the kinds there are now, its own kept
        now = vise.Jaws
        vise.Jaws = JawKinds
        vise.Jaws = now
    defaults = PathJaws.GripJaw
    for name, kind, value, doc in (
        (
            "SoftThickness",
            "App::PropertyLength",
            plate,
            QT_TRANSLATE_NOOP(
                "App::Property", "The soft jaws' thickness, from the jaw's body out to their face"
            ),
        ),
        (
            "SoftHeight",
            "App::PropertyLength",
            plateHeight,
            QT_TRANSLATE_NOOP(
                "App::Property", "The soft jaws' height, up from the hard plates' bottom"
            ),
        ),
        (
            "GripHeight",
            "App::PropertyLength",
            defaults["grip"],
            QT_TRANSLATE_NOOP(
                "App::Property", "How far grip jaws' grips stand above their tops: the grip"
            ),
        ),
        (
            "GripSetback",
            "App::PropertyLength",
            defaults["setback"],
            QT_TRANSLATE_NOOP("App::Property", "grip jaws' grips' teeth behind their face"),
        ),
        (
            "GripBite",
            "App::PropertyLength",
            defaults["bite"],
            QT_TRANSLATE_NOOP("App::Property", "How far grip jaws' grips bite into the stock"),
        ),
        (
            "GripCount",
            "App::PropertyInteger",
            defaults["grips"],
            QT_TRANSLATE_NOOP("App::Property", "How many grips each grip jaw has"),
        ),
        (
            "Steps",
            "App::PropertyStringList",
            [],
            QT_TRANSLATE_NOOP(
                "App::Property",
                "The steps cut in both soft jaws, each 'height,depth' in mm: down from their top, "
                "in from their face",
            ),
        ),
    ):
        if not hasattr(vise, name):
            vise.addProperty(kind, name, "Jaws", doc)
            setattr(vise, name, value)


def _makeJaws(vise):
    """The vise's parts made as its Jaws say: soft, its plates hidden, out of the way of the
    tools, and a soft jaw in place of each, the moving one driven by the Opening as the moving
    jaw is; hard, the soft jaws gone and the plates shown. Returns the soft jaws."""
    if not canChangeJaws(vise):
        return []
    jaws = softJaws(vise)
    grips = gripsOf(vise)
    names = [o.Name for o in list(jaws.values()) + list(grips.values())]
    drives = [e for e in vise.Drives if e.split("\t")[0] not in names]
    plates = _plates(vise)
    expression = "-%s.Opening" % viseSetup(vise)["opening"].Name
    # grip jaws' grips, as many as each jaw has; none on others
    count = vise.GripCount if vise.Jaws == "Grip" else 0
    for key, grip in list(grips.items()):
        if key[1] >= count:
            vise.Document.removeObject(grip.Name)
            del grips[key]
    for side in Sides:
        for index in range(count):
            if (side, index) not in grips:
                grips[(side, index)] = PathJaws.createGrip(vise, side, index)
            if side == "Moving":
                drives.append(
                    "\t".join((grips[(side, index)].Name, ".Placement.Base.y", expression))
                )
    if vise.Jaws in ("Soft", "Grip"):
        for side in Sides:
            if side not in jaws:
                jaws[side] = PathJaws.create(vise, side)
            PathJaws.color(jaws[side], vise.Jaws)
        for plate in plates:
            plate.Visibility = False
        drives.append("\t".join((jaws["Moving"].Name, ".Placement.Base.y", expression)))
        vise.Drives = drives
        drive(vise)
        for part in list(jaws.values()) + list(grips.values()):
            part.touch()
        return [jaws[side] for side in Sides]
    vise.Drives = drives
    for jaw in jaws.values():
        vise.Document.removeObject(jaw.Name)
    for plate in plates:
        plate.Visibility = True
    return []
