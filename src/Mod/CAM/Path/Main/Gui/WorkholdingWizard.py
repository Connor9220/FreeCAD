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

"""Place Workholding: pick what holds the stock, click on the stock where it goes.

A dog or a side clamp goes against the side clicked, an edge clamp over the edge nearest the
click, each where the stock was clicked. Every click places one, an undoable step of its own,
the panel staying for the next. A table goes under the stock at a button."""

import FreeCAD
import Path
import Path.Main.WorkholdingItems as Items

from PySide.QtCore import QT_TRANSLATE_NOOP

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtWidgets

translate = FreeCAD.Qt.translate

# what can be placed: its class in Items, its name, what to click
Choices = [
    ("Dog", QT_TRANSLATE_NOOP("CAM_Workholding", "Dog"), "side"),
    ("SideClamp", QT_TRANSLATE_NOOP("CAM_Workholding", "Side clamp"), "side"),
    ("EdgeClamp", QT_TRANSLATE_NOOP("CAM_Workholding", "Edge clamp (EdgeHugger)"), "edge"),
]


def _jobs():
    import Path.Main.Job as PathJob

    if FreeCAD.ActiveDocument is None:
        return []
    return [
        o
        for o in FreeCAD.ActiveDocument.Objects
        if hasattr(o, "Proxy") and isinstance(o.Proxy, PathJob.ObjectJob)
    ]


class TaskPanelWorkholding:
    def __init__(self, jobs):
        self.jobs = jobs
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("CAM_Workholding", "Place Workholding"))
        layout = QtWidgets.QFormLayout(self.form)

        self.job = QtWidgets.QComboBox()
        for job in jobs:
            self.job.addItem(job.Label)
        layout.addRow(translate("CAM_Workholding", "Job"), self.job)

        self.what = QtWidgets.QComboBox()
        for _, label, _ in Choices:
            self.what.addItem(translate("CAM_Workholding", label))
        layout.addRow(translate("CAM_Workholding", "Place"), self.what)

        self.hint = QtWidgets.QLabel()
        self.hint.setWordWrap(True)
        layout.addRow(self.hint)

        self.table = QtWidgets.QPushButton(translate("CAM_Workholding", "Put a table under it"))
        self.table.setToolTip(
            translate(
                "CAM_Workholding",
                "A spoilboard with T-track rails and dog holes, and the waste board the stock "
                "lies on, shown but never hit",
            )
        )
        layout.addRow(self.table)

        self.placed = QtWidgets.QLabel()
        layout.addRow(self.placed)
        self.count = 0

        self.what.currentIndexChanged.connect(self.updateHint)
        self.table.clicked.connect(self.addTable)
        self.updateHint()
        # the stock clickable while placing: the Job's editor may have left it not
        self.selectable = {}
        self.job.currentIndexChanged.connect(self.makeStockClickable)
        self.makeStockClickable()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addObserver(self)

    def makeStockClickable(self, *args):
        self.restoreSelectable()
        stock = self.currentJob().Stock
        if stock is not None and stock.ViewObject is not None:
            self.selectable[stock.Name] = (stock, stock.ViewObject.Selectable)
            stock.ViewObject.Selectable = True

    def restoreSelectable(self):
        for stock, selectable in self.selectable.values():
            try:
                stock.ViewObject.Selectable = selectable
            except Exception:
                pass
        self.selectable = {}

    def currentJob(self):
        return self.jobs[self.job.currentIndex()]

    def updateHint(self):
        _, _, click = Choices[self.what.currentIndex()]
        if click == "side":
            text = translate(
                "CAM_Workholding",
                "Click a side of the stock, or the model, where it goes: each click places one.",
            )
        else:
            text = translate(
                "CAM_Workholding",
                "Click near the top edge of the stock, or the model, where it goes: each click places one.",
            )
        self.hint.setText(text)

    # the selection observer: a click on the stock places the chosen piece there
    def addSelection(self, doc, name, sub, point):
        job = self.currentJob()
        stock = job.Stock
        if stock is None or doc != job.Document.Name or point is None:
            return
        # the stock, or the model in it: a click on the model lands on the stock's side nearest
        if name != stock.Name and name not in [m.Name for m in job.Model.Group]:
            self.placed.setText(
                translate("CAM_Workholding", "Click the stock, or the model in it, to place it")
            )
            return
        point = FreeCAD.Vector(*point) if not isinstance(point, FreeCAD.Vector) else point
        which, label, click = Choices[self.what.currentIndex()]
        doc = job.Document
        doc.openTransaction(
            translate("CAM_Workholding", "Place %s") % translate("CAM_Workholding", label)
        )
        try:
            normal, point = Items.onSide(stock.Shape, point)
            item = Items.create(job, which)
            if click == "side":
                Items.placeAgainst(job, item, point, normal)
            else:
                Items.placeOnEdge(job, item, point, normal)
        except ValueError as e:
            doc.abortTransaction()
            Path.Log.error(str(e))
            FreeCADGui.Selection.clearSelection()
            return
        doc.commitTransaction()
        doc.recompute()
        self.count += 1
        self.placed.setText(translate("CAM_Workholding", "Placed %d") % self.count)
        FreeCADGui.Selection.clearSelection()

    def addTable(self):
        job = self.currentJob()
        doc = job.Document
        doc.openTransaction(translate("CAM_Workholding", "Place a table"))
        table = Items.create(job, "Table")
        Items.placeTable(job, table)
        doc.commitTransaction()
        doc.recompute()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close

    def _done(self):
        FreeCADGui.Selection.removeObserver(self)
        self.restoreSelectable()
        FreeCADGui.Control.closeDialog()

    def reject(self):
        self._done()
        return True

    def accept(self):
        self._done()
        return True


class CommandPlaceWorkholding:
    def GetResources(self):
        return {
            "Pixmap": "CAM_Job",
            "MenuText": QT_TRANSLATE_NOOP("CAM_Workholding", "Place Workholding"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_Workholding",
                "Place dogs, side clamps and edge clamps by clicking on the stock where they go, "
                "and a table under it.",
            ),
        }

    def IsActive(self):
        if FreeCAD.ActiveDocument is None or FreeCADGui.Control.activeDialog():
            return False
        return any(getattr(j, "Workholding", None) for j in _jobs())

    def Activated(self):
        jobs = [j for j in _jobs() if getattr(j, "Workholding", None)]
        if jobs:
            FreeCADGui.Control.showDialog(TaskPanelWorkholding(jobs))


if FreeCAD.GuiUp:
    FreeCADGui.addCommand("CAM_PlaceWorkholding", CommandPlaceWorkholding())

FreeCAD.Console.PrintLog("Loading WorkholdingWizard… done\n")
