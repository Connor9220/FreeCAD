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


"""The view providers of a Job's workholding: a vise, its parts, jaws and parallels; simple
workholding, steel for what holds, a pale table to see the rest on; and a clamp from a file of
its own."""

import FreeCAD
import Path.Workholding.Vise as PathWorkholding

translate = FreeCAD.Qt.translate

from Path.Workholding.Constants import (
    DRAG_TURN_STEP,
    STOP_COLOR,
    TABLE_COLOR,
    TABLE_TRANSPARENCY,
    THIN_LINE_WIDTH,
    TRANSFORM_NO_DIALOG,
)
from Path.Workholding.Gui.Source import closeFilesAfter

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore


# while the workholding panel is open a stop, clamp or vise is hovered over and picked whole,
# not a face of it
wholePicks = False


def setWholePicks(on):
    """setWholePicks(on) ... the workholding hovered over and picked whole in the 3D view, or by
    face as anything else is."""
    global wholePicks
    wholePicks = bool(on)


def _picked(pp):
    """What of a part of the workholding a click or hover picks: all of it while the panel is
    open, else what FreeCAD picks."""
    if wholePicks:
        return ""
    raise NotImplementedError


def _unselectable(vobj):
    """A part of the workholding not picked in the 3D view, nor lit when picked in the tree: a
    vise, its jaws, grips and parallels are there to be seen and missed, not worked on."""
    if vobj is not None and "Selectable" in vobj.PropertiesList:
        vobj.Selectable = False


def _outOfTree(vobj):
    """A part of a vise or clamp not listed in the tree; the tree's Show Hidden lists it."""
    if vobj is not None and "ShowInTree" in vobj.PropertiesList and vobj.ShowInTree:
        vobj.ShowInTree = False


def thinLines(vobj):
    """thinLines(vobj) ... its edges and vertices drawn thin, its vertices, where it says, the
    color of its edges, not drawn over them."""
    names = vobj.PropertiesList
    for name in ("LineWidth", "PointSize"):
        if name in names:
            setattr(vobj, name, THIN_LINE_WIDTH)
    if "PointColor" in names and "LineColor" in names:
        vobj.PointColor = vobj.LineColor


def _removeUnselected(objects):
    """objects taken out of the document, in Delete's own undoable step; those selected too are
    left to Delete, which still has them to remove."""
    for obj in objects:
        if obj.isAttachedToDocument() and not FreeCADGui.Selection.isSelected(obj):
            obj.Document.removeObject(obj.Name)


class _PartViewProvider:
    """A part of a vise of a Job's Workholding as Part shows its shapes, not picked in the 3D
    view: a linked part, a soft jaw, a grip or a parallel. Made shown in its displayMode, its
    edges thin."""

    displayMode = None

    def __init__(self, vobj):
        vobj.Proxy = self
        if self.displayMode is not None:
            vobj.DisplayMode = self.displayMode
        thinLines(vobj)

    def attach(self, vobj):
        self.Object = vobj.Object
        self.vobj = vobj
        _unselectable(vobj)

    def finishRestoring(self):
        # one saved before it was so: not picked in the 3D view either
        _unselectable(getattr(self, "vobj", None))

    def getElementPicked(self, pp):
        return _picked(pp)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderViseMember(_PartViewProvider):
    """A part of a vise of a Job's Workholding: deleting it deletes the whole vise, a vise
    short of a part being no use. Left out of the tree: the vise is what is worked with, its
    parts placed by it."""

    def attach(self, vobj):
        super().attach(vobj)
        _outOfTree(vobj)

    def finishRestoring(self):
        super().finishRestoring()
        # one saved before it was so: out of the tree too
        _outOfTree(getattr(self, "vobj", None))

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        job, vise = PathWorkholding.memberOf(obj)
        if vise is None or vise == obj:
            return True
        # the rest of the vise; no longer shared with other Jobs
        PathWorkholding.release(vise)
        closeFilesAfter(vise)
        _removeUnselected([o for o in list(vise.Group) + [vise] if o != obj])
        return True

    def doubleClicked(self, vobj):
        return _showVise(vobj.Object)


def _showVise(obj):
    """The vise panel on the vise obj is, or is part of; on the stops and clamps, the stop or
    clamp obj is picked out: True if it is shown."""
    import Path.Workholding.Gui.Vise as ViseGui

    job, member = PathWorkholding.memberOf(obj)
    if member is None or FreeCADGui.Control.activeDialog():
        return False
    if PathWorkholding.isVise(member):
        ViseGui.showPanel(ViseGui.TaskPanelVise(job, member))
    else:
        ViseGui.showPanel(ViseGui.TaskPanelVise(job, piece=member))
    return True


def _seatedDragger(along=False):
    """The Transform dragger of a seated vise without what would move it into the jaws or turn
    it: along the jaws and up, and the plane of the two, are left; along, along the jaws only and
    turned every way."""
    from pivy import coin

    view = FreeCADGui.ActiveDocument.ActiveView if FreeCADGui.ActiveDocument else None
    if view is None or not hasattr(view, "getSceneGraph"):
        return
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName("SoTransformDragger"))
    search.setInterest(coin.SoSearchAction.FIRST)
    search.apply(view.getSceneGraph())
    if search.getPath() is None:
        return
    dragger = search.getPath().getTail()
    hidden = ["yTranslatorDragger", "xRotatorDragger", "yRotatorDragger"]
    planes = ["xyPlanarTranslatorSwitch", "yzPlanarTranslatorSwitch"]
    if along:
        # along the jaws, and turned about all three: about the vertical a degree at a time,
        # about the others onto its side or over, a quarter turn once let go
        import math

        # across the table too, by X, Y and the square of the two: across the jaws, the part
        # held in it with it
        hidden = ["zTranslatorDragger"]
        planes = ["yzPlanarTranslatorSwitch", "zxPlanarTranslatorSwitch"]
        dragger.getField("rotationIncrement").set(repr(math.radians(DRAG_TURN_STEP)))
    else:
        hidden.append("zRotatorDragger")
    for name in hidden:
        part = dragger.getPart(name, True)
        if part is not None:
            part.getField("visible").set("FALSE")
    # the planes, where the dragger draws them
    for name in planes:
        dragger.set("%s { whichChild -1 }" % name)


def canTransform(obj):
    """canTransform(obj) ... whether FreeCAD's Transform moves this stop or clamp, as its kind
    allows."""
    import Path.Workholding.Items as Items

    return Items.canTransform(PathWorkholding.memberOf(obj)[1])


def findDragger():
    """findDragger() ... FreeCAD's Transform dragger in the active 3D view, None if none."""
    from pivy import coin

    view = FreeCADGui.ActiveDocument.ActiveView if FreeCADGui.ActiveDocument else None
    if view is None or not hasattr(view, "getSceneGraph"):
        return None
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName("SoTransformDragger"))
    search.setInterest(coin.SoSearchAction.FIRST)
    search.apply(view.getSceneGraph())
    if search.getPath() is None:
        return None
    return search.getPath().getTail()


def draggerPlacement(dragger):
    """draggerPlacement(dragger) ... where the Transform dragger stands now, mid-drag too: where
    the piece it moves will be put."""
    from pivy import coin

    at = coin.cast(dragger.getField("translation"), "SoSFVec3f").getValue().getValue()
    turn = coin.cast(dragger.getField("rotation"), "SoSFRotation").getValue().getValue()
    return FreeCAD.Placement(FreeCAD.Vector(*at), FreeCAD.Rotation(*turn))


def stockDragger():
    """stockDragger() ... the Transform dragger on the stock: across the table and turned about
    the vertical, a degree at a time."""
    import math

    dragger = findDragger()
    if dragger is None:
        return
    dragger.getField("rotationIncrement").set(repr(math.radians(DRAG_TURN_STEP)))
    for name in ("zTranslatorDragger", "xRotatorDragger", "yRotatorDragger"):
        part = dragger.getPart(name, True)
        if part is not None:
            part.getField("visible").set("FALSE")
    for name in ("yzPlanarTranslatorSwitch", "zxPlanarTranslatorSwitch"):
        dragger.set("%s { whichChild -1 }" % name)


def _limitedDragger(piece):
    """The Transform dragger on piece showing only what moves it as its kind allows: across the
    table, and a lever clamp or a side clamp turned too."""
    import math
    import Path.Workholding.Items as Items
    import Path.Workholding.Lever as Lever

    dragger = findDragger()
    if dragger is None:
        return
    dragger.getField("rotationIncrement").set(repr(math.radians(DRAG_TURN_STEP)))
    keep = ("xTranslatorDragger", "yTranslatorDragger")
    if Lever.isLever(piece) or getattr(piece, "Kind", None) == Items.Kind.Push:
        keep += ("zRotatorDragger",)
    planes = ("xyPlanarTranslatorSwitch",)
    for name in (
        "xTranslatorDragger",
        "yTranslatorDragger",
        "zTranslatorDragger",
        "xRotatorDragger",
        "yRotatorDragger",
        "zRotatorDragger",
    ):
        if name not in keep:
            part = dragger.getPart(name, True)
            if part is not None:
                part.getField("visible").set("FALSE")
    for name in (
        "xyPlanarTranslatorSwitch",
        "yzPlanarTranslatorSwitch",
        "zxPlanarTranslatorSwitch",
    ):
        if name not in planes:
            dragger.set("%s { whichChild -1 }" % name)


def setDragOrigin(vobj):
    """The Transform dragger of a stop or clamp placed against a side put where it meets the
    stock, square to the side, however a side clamp is turned: dragged along the side, turned
    about where it pushes."""
    import Path.Workholding.Items as Items

    if "TransformOrigin" not in vobj.PropertiesList:
        return
    job, piece = PathWorkholding.memberOf(vobj.Object)
    contact = Items.contactFrame(job, piece) if piece is not None else None
    origin = FreeCAD.Placement()
    if contact is not None:
        origin = PathWorkholding.placementOf(piece).inverse().multiply(contact)
    vobj.TransformOrigin = origin


def dragPlacement(vobj):
    """Where the Transform dragger of the piece stands: its placement, from where it meets the
    stock for one placed against a side."""
    obj = vobj.Object
    origin = vobj.TransformOrigin if "TransformOrigin" in vobj.PropertiesList else None
    placement = PathWorkholding.placementOf(obj)
    return placement.multiply(origin) if origin is not None else placement


def _transformed(name, docName, before, at=None):
    """Transform done on a piece: where it was moved to kept as its settings, if it moved."""
    import Path.Workholding.Items as Items

    doc = FreeCAD.getDocument(docName) if docName in FreeCAD.listDocuments() else None
    piece = doc.getObject(name) if doc is not None else None
    if piece is None:
        return
    if not piece.Placement.isSame(before, 1e-9):
        doc.openTransaction(translate("CAM_Workholding", "Move workholding"))
        try:
            Items.fromTransform(piece, at)
        except ValueError as e:
            FreeCAD.Console.PrintWarning(str(e) + "\n")
        finally:
            doc.commitTransaction()


class _ViewProvider:
    """A piece of a Job's Workholding: double-clicked, the workholding panel; set inactive, the
    icon an inactive operation has."""

    icon = ":/icons/CAM_Job.svg"

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        # not in use, the icon an inactive operation has
        if not getattr(getattr(self, "Object", None), "Active", True):
            return ":/icons/CAM_OpActive.svg"
        return self.icon

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def doubleClicked(self, vobj):
        return _showVise(vobj.Object)

    def getElementPicked(self, pp):
        return _picked(pp)

    def setEdit(self, vobj, mode):
        # Transform, with its panel or without in the workholding panel: FreeCAD's dragger, once
        # made, showing only what moves this piece
        if mode in (1, TRANSFORM_NO_DIALOG) and canTransform(vobj.Object):
            obj = vobj.Object
            if mode == 1:
                self.transformStart = FreeCAD.Placement(obj.Placement)
            setDragOrigin(vobj)
            QtCore.QTimer.singleShot(0, lambda: _limitedDragger(obj))
        return None

    def unsetEdit(self, vobj, mode):
        # Transform done: where it was moved to kept as its settings, once FreeCAD is done
        start = getattr(self, "transformStart", None)
        if mode == 1 and start is not None:
            self.transformStart = None
            obj = vobj.Object
            name, docName = obj.Name, obj.Document.Name
            at = dragPlacement(vobj)
            QtCore.QTimer.singleShot(0, lambda: _transformed(name, docName, start, at))
        if mode in (1, TRANSFORM_NO_DIALOG) and "TransformOrigin" in vobj.PropertiesList:
            vobj.TransformOrigin = FreeCAD.Placement()
        return False


class _GroupViewProvider(_ViewProvider):
    """A vise or a clamp of a Job's Workholding, a group of the parts it links from its file:
    deleted, all of it, its file closed after if nothing links to it."""

    def __init__(self, vobj):
        vobj.addExtension("Gui::ViewProviderGeoFeatureGroupExtensionPython")
        vobj.Proxy = self

    def onDelete(self, vobj, subelements):
        # its parts with it
        closeFilesAfter(vobj.Object)
        _removeUnselected(list(vobj.Object.Group))
        return True


class ViewProviderVise(_GroupViewProvider):
    """A vise of a Job's Workholding: double-clicked, its panel; deleted, all of it."""

    icon = ":/icons/CAM_Vise.svg"

    def setEdit(self, vobj, mode):
        # Transform: FreeCAD's dragger, once made, showing only how a seated vise may move
        if mode == 1 and getattr(vobj.Object, "Seated", False):
            QtCore.QTimer.singleShot(0, _seatedDragger)
        elif mode == TRANSFORM_NO_DIALOG and getattr(vobj.Object, "Seated", False):
            # in the workholding panel: along the jaws, and turned a quarter at a time, not held
            # to its seat while dragged; the panel seats it again where it is let go
            vobj.Object.Proxy.free = True
            QtCore.QTimer.singleShot(0, lambda: _seatedDragger(along=True))
        return None

    def unsetEdit(self, vobj, mode):
        if mode == TRANSFORM_NO_DIALOG and getattr(vobj.Object, "Proxy", None) is not None:
            vobj.Object.Proxy.free = False
        return super().unsetEdit(vobj, mode)

    def onDelete(self, vobj, subelements):
        # no longer shared with other Jobs
        PathWorkholding.release(vobj.Object)
        return super().onDelete(vobj, subelements)


class ViewProvider(_ViewProvider):
    """A stop, side or edge clamp, or table made here: not picked in the 3D view but while the
    workholding panel is open, as a vise's parts are not; picked in the tree."""

    def __init__(self, vobj):
        vobj.Proxy = self
        obj = vobj.Object
        if getattr(obj, "Kind", "") == "Table":
            vobj.ShapeColor = TABLE_COLOR
            vobj.Transparency = TABLE_TRANSPARENCY
        else:
            vobj.ShapeColor = STOP_COLOR
        thinLines(vobj)

    def attach(self, vobj):
        super().attach(vobj)
        _unselectable(vobj)

    def finishRestoring(self):
        # one saved before it was so: not picked in the 3D view either
        _unselectable(getattr(getattr(self, "Object", None), "ViewObject", None))

    def onDelete(self, vobj, subelements):
        # a stop shared with another Job no longer shared: theirs stays where it is
        PathWorkholding.release(vobj.Object)
        return True


class ViewProviderClamp(_GroupViewProvider):
    """A clamp of a Job's Workholding from a file of its own: double-clicked, the workholding
    panel; deleted, all of it."""


class ViewProviderSoftJaw(_PartViewProvider):
    """A soft jaw as Part shows its shapes, in aluminum, its edges drawn: they help to see the
    jaws."""

    displayMode = "Flat Lines"


class ViewProviderParallel(_PartViewProvider):
    """A parallel as Part shows its shapes: dark steel, or light for soft ones, shaded, no edges
    drawn over it."""

    displayMode = "Shaded"
