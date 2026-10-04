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

from Path.Workholding.Constants import STOP_COLOR, TABLE_COLOR, TABLE_TRANSPARENCY, THIN_LINE_WIDTH
from Path.Workholding.Gui.Source import closeFilesAfter

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore


def _unselectable(vobj):
    """A part of the workholding not picked in the 3D view, nor lit when picked in the tree: a
    vise, its jaws, grips and parallels are there to be seen and missed, not worked on."""
    if vobj is not None and "Selectable" in vobj.PropertiesList:
        vobj.Selectable = False


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

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderViseMember(_PartViewProvider):
    """A part of a vise of a Job's Workholding: deleting it deletes the whole vise, a vise
    short of a part being no use."""

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
        FreeCADGui.Control.showDialog(ViseGui.TaskPanelVise(job, member))
    else:
        FreeCADGui.Control.showDialog(ViseGui.TaskPanelVise(job, piece=member))
    return True


def _seatedDragger():
    """The Transform dragger of a seated vise without what would move it into the jaws or turn
    it: along the jaws and up, and the plane of the two, are left."""
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
    for name in ("yTranslatorDragger", "xRotatorDragger", "yRotatorDragger", "zRotatorDragger"):
        part = dragger.getPart(name, True)
        if part is not None:
            part.getField("visible").set("FALSE")
    # the planes, where the dragger draws them
    for name in ("xyPlanarTranslatorSwitch", "yzPlanarTranslatorSwitch"):
        dragger.set("%s { whichChild -1 }" % name)


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
        return None

    def onDelete(self, vobj, subelements):
        # no longer shared with other Jobs
        PathWorkholding.release(vobj.Object)
        return super().onDelete(vobj, subelements)


class ViewProvider(_ViewProvider):
    def __init__(self, vobj):
        vobj.Proxy = self
        obj = vobj.Object
        if getattr(obj, "Kind", "") == "Table":
            vobj.ShapeColor = TABLE_COLOR
            vobj.Transparency = TABLE_TRANSPARENCY
        else:
            vobj.ShapeColor = STOP_COLOR
        thinLines(vobj)

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
