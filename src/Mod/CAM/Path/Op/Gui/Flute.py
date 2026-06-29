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

__title__ = "CAM Flute Operation UI"
__author__ = "Connor (Billy Huddleston <billy@ivdc.com>)"
__url__ = "https://www.freecad.org"
__doc__ = "Flute operation task panel controller and command implementation."

import FreeCAD
import FreeCADGui
import Path
import Path.Base.Gui.Util as PathGuiUtil
import Path.Op.Flute as PathFlute
import Path.Op.Gui.Base as PathOpGui

from PySide import QtCore

translate = FreeCAD.Qt.translate

if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())


class TaskPanelOpPage(PathOpGui.TaskPanelPage):
    """Task panel page for the Flute operation."""

    def getForm(self):
        import os

        ui_path = os.path.join(os.path.dirname(__file__), "PageOpFluteEdit.ui")
        if os.path.exists(ui_path):
            return FreeCADGui.PySideUic.loadUi(ui_path)
        return FreeCADGui.PySideUic.loadUi(":/panels/PageOpFluteEdit.ui")

    def initPage(self, obj):
        self.setTitle("Flute - " + obj.Label)

        self.axialStockToLeaveSpinBox = PathGuiUtil.QuantitySpinBox(
            self.form.axialStockToLeave, obj, "AxialStockToLeave"
        )

    def setFields(self, obj):
        self.setupToolController(obj, self.form.toolController)
        self.setupCoolant(obj, self.form.coolantController)

        self.form.reverseDirection.setCheckState(
            QtCore.Qt.Checked if obj.ReverseDirection else QtCore.Qt.Unchecked
        )

        self.axialStockToLeaveSpinBox.updateWidget()

    def getFields(self, obj):
        self.updateToolController(obj, self.form.toolController)
        self.updateCoolant(obj, self.form.coolantController)

        obj.ReverseDirection = self.form.reverseDirection.isChecked()
        self.axialStockToLeaveSpinBox.updateProperty()

    def getSignalsForUpdate(self, obj):
        signals = []
        signals.append(self.form.toolController.currentIndexChanged)
        signals.append(self.form.coolantController.currentIndexChanged)

        if hasattr(self.form.reverseDirection, "checkStateChanged"):
            signals.append(self.form.reverseDirection.checkStateChanged)
        else:
            signals.append(self.form.reverseDirection.stateChanged)

        signals.append(self.form.axialStockToLeave.editingFinished)

        return signals


Command = PathOpGui.SetupOperation(
    "Flute",
    PathFlute.Create,
    TaskPanelOpPage,
    "CAM_Slot",  # placeholder icon until CAM_Flute.svg is created
    QtCore.QT_TRANSLATE_NOOP("CAM_Flute", "Flute"),
    QtCore.QT_TRANSLATE_NOOP(
        "CAM_Flute",
        "Create a ramping flute toolpath from a selected bottom face."
        "\n\nThe path runs along the centerline of the face, stepping down"
        "\nincrementally.  Supported tool types: flat, bull-nose, V-bit.",
    ),
    PathFlute.SetupProperties,
)

FreeCAD.Console.PrintLog("Loading PathFluteGui... done\n")
