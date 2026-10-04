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

"""The look of simple workholding: steel for what holds, a pale table to see the rest on; and of
a clamp from a file of its own."""

import FreeCADGui
import Path.Main.Workholding as PathWorkholding


def _showPanel(obj):
    """The workholding panel on the piece obj is, or is part of."""
    import Path.Main.Gui.WorkholdingCmd as WorkholdingCmd

    return WorkholdingCmd._showVise(obj)


class ViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self
        obj = vobj.Object
        if getattr(obj, "Kind", "") == "Table":
            vobj.ShapeColor = (0.80, 0.74, 0.62)
            vobj.Transparency = 60
        else:
            vobj.ShapeColor = (0.55, 0.57, 0.62)
        # its edges and points thin, its points the colour of its edges
        vobj.LineWidth = 1
        vobj.PointSize = 1
        vobj.PointColor = vobj.LineColor

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        # not in use, the icon an inactive operation has
        if not getattr(getattr(self, "Object", None), "Active", True):
            return ":/icons/CAM_OpActive.svg"
        return ":/icons/CAM_Job.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def doubleClicked(self, vobj):
        return _showPanel(vobj.Object)

    def onDelete(self, vobj, subelements):
        # a stop shared with another Job no longer shared: theirs stays where it is
        PathWorkholding.release(vobj.Object)
        return True


class ViewProviderClamp:
    """A clamp of a Job's Workholding from a file of its own: double-clicked, the workholding
    panel; deleted, all of it."""

    def __init__(self, vobj):
        vobj.addExtension("Gui::ViewProviderGeoFeatureGroupExtensionPython")
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        # not in use, the icon an inactive operation has
        if not getattr(getattr(self, "Object", None), "Active", True):
            return ":/icons/CAM_OpActive.svg"
        return ":/icons/CAM_Job.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def doubleClicked(self, vobj):
        return _showPanel(vobj.Object)

    def onDelete(self, vobj, subelements):
        # its parts with it, all in Delete's own undoable step; what is selected too is left to
        # Delete, which still has it to remove; its file closed after if nothing links to it
        import Path.Main.Gui.WorkholdingCmd as WorkholdingCmd

        WorkholdingCmd.closeFilesAfter(vobj.Object)
        doc = vobj.Object.Document
        for obj in list(vobj.Object.Group):
            if obj.isAttachedToDocument() and not FreeCADGui.Selection.isSelected(obj):
                doc.removeObject(obj.Name)
        return True
