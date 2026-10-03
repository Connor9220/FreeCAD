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

"""The look of simple workholding: steel for what holds, a pale table to see the rest on."""


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
