# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2017 sliptonic <shopinthewoods@gmail.com>               *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import FreeCAD
import FreeCADGui
import Path
import Path.Op.Gui.Base as PathOpGui
import PathGui

from PySide import QtCore, QtGui

__title__ = "Base for Circular Hole based operations' UI"
__author__ = "sliptonic (Brad Collette)"
__url__ = "https://www.freecad.org"
__doc__ = "Implementation of circular hole specific base geometry page controller."

LOGLEVEL = False

if LOGLEVEL:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.NOTICE, Path.Log.thisModule())


class TaskPanelHoleGeometryPage(PathOpGui.TaskPanelBaseGeometryPage):
    """Controller class to be used for the BaseGeomtery page.
    Circular holes don't just display the feature, they also add a column
    displaying the radius the feature describes. This page provides that
    UI and functionality for all circular hole based operations."""

    DataFeatureName = QtCore.Qt.ItemDataRole.UserRole
    DataObject = QtCore.Qt.ItemDataRole.UserRole + 1
    DataObjectSub = QtCore.Qt.ItemDataRole.UserRole + 2

    InitBase = True

    def getForm(self):
        """getForm() ... load and return page"""
        return FreeCADGui.PySideUic.loadUi(":/panels/PageBaseHoleGeometryEdit.ui")

    def initPage(self, obj):
        self.updating = False

    def setFields(self, obj):
        """setFields(obj) ... fill form with values from obj"""
        Path.Log.track()
        self.form.baseList.blockSignals(True)
        self.form.baseList.clearContents()
        self.form.baseList.setRowCount(0)
        for base, subs in obj.Base:
            for sub in subs:
                self.form.baseList.insertRow(self.form.baseList.rowCount())

                item = QtGui.QTableWidgetItem("%s.%s" % (base.Label, sub))
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                if obj.Proxy.isHoleEnabled(obj, base, sub):
                    item.setCheckState(QtCore.Qt.Checked)
                else:
                    item.setCheckState(QtCore.Qt.Unchecked)
                name = "%s.%s" % (base.Name, sub)
                item.setData(self.DataFeatureName, name)
                item.setData(self.DataObject, base)
                item.setData(self.DataObjectSub, sub)
                self.form.baseList.setItem(self.form.baseList.rowCount() - 1, 0, item)

                dia = obj.Proxy.holeDiameter(base, sub)
                item = QtGui.QTableWidgetItem()
                item.setData(QtCore.Qt.DisplayRole, float(dia))
                item.setTextAlignment(QtCore.Qt.AlignHCenter)
                self.form.baseList.setItem(self.form.baseList.rowCount() - 1, 1, item)

        self.form.baseList.resizeColumnToContents(0)
        self.form.baseList.blockSignals(False)
        self.form.baseList.setSortingEnabled(True)
        self.itemActivated()

    def itemActivated(self):
        """itemActivated() ... callback when item in table is selected"""
        Path.Log.track()
        if self.form.baseList.selectedItems():
            self.form.deleteBase.setEnabled(True)
            FreeCADGui.Selection.clearSelection()
            activatedRows = []
            for item in self.form.baseList.selectedItems():
                row = item.row()
                if not row in activatedRows:
                    activatedRows.append(row)
                    obj = item.data(self.DataObject)
                    sub = str(item.data(self.DataObjectSub))
                    Path.Log.debug("itemActivated() -> %s.%s" % (obj.Label, sub))
                    if sub:
                        FreeCADGui.Selection.addSelection(obj, sub)
                    else:
                        FreeCADGui.Selection.addSelection(obj)
        else:
            self.form.deleteBase.setEnabled(False)

    def deleteBase(self):
        """deleteBase() ... callback for push button"""
        Path.Log.track()
        selected = [self.form.baseList.row(item) for item in self.form.baseList.selectedItems()]
        self.form.baseList.blockSignals(True)
        for row in sorted(list(set(selected)), key=lambda row: -row):
            self.form.baseList.removeRow(row)
        self.updateBase()
        self.form.baseList.resizeColumnToContents(0)
        self.form.baseList.blockSignals(False)
        # self.obj.Proxy.execute(self.obj)
        FreeCAD.ActiveDocument.recompute()
        self.setFields(self.obj)

    def updateBase(self):
        """updateBase() ... helper function to transfer current table to obj"""
        Path.Log.track()
        newlist = []
        for i in range(self.form.baseList.rowCount()):
            item = self.form.baseList.item(i, 0)
            obj = item.data(self.DataObject)
            sub = str(item.data(self.DataObjectSub))
            base = (obj, sub)
            Path.Log.debug("keeping (%s.%s)" % (obj.Label, sub))
            newlist.append(base)
        Path.Log.debug("obj.Base=%s newlist=%s" % (self.obj.Base, newlist))
        self.updating = True
        self.obj.Base = newlist
        self.updating = False

    def checkedChanged(self):
        """checkeChanged() ... callback when checked status of a base feature changed"""
        Path.Log.track()
        disabled = []
        for i in range(0, self.form.baseList.rowCount()):
            item = self.form.baseList.item(i, 0)
            if item.checkState() != QtCore.Qt.Checked:
                disabled.append(item.data(self.DataFeatureName))
        self.obj.Disabled = disabled
        FreeCAD.ActiveDocument.recompute()

    def updateChecked(self):
        self.updating = True
        for i in range(self.form.baseList.rowCount()):
            item = self.form.baseList.item(i, COL_FEATURE)
            base_name = item.data(self.DataObjectName)
            base = FreeCAD.ActiveDocument.getObject(base_name)
            sub = str(item.data(self.DataObjectSub))
            guiState = item.checkState() == QtCore.Qt.Checked
            holeEnabled = self.obj.Proxy.isHoleEnabled(self.obj, base, sub)
            if not holeEnabled and guiState:
                item.setCheckState(QtCore.Qt.Unchecked)
            elif holeEnabled and not guiState:
                item.setCheckState(QtCore.Qt.Checked)
        self.updating = False

    def updateOrderNumbers(self):
        """Update the order numbers in the first column after row reordering or sorting."""
        table = self.form.baseList
        for row in range(table.rowCount()):
            item = table.item(row, COL_ORDER)
            if item:
                item.setData(QtCore.Qt.DisplayRole, row + 1)
        self.updateBase()
        self.filterBaseList(self.form.lineEdit.text())  # Reapply filter after
        FreeCAD.ActiveDocument.recompute()

    def updateSelectAllCheckbox(self):
        """Set the Select All checkbox state based on visible rows."""
        all_checked = True
        any_visible = False
        for row in range(self.form.baseList.rowCount()):
            if not self.form.baseList.isRowHidden(row):
                any_visible = True
                item = self.form.baseList.item(row, COL_FEATURE)
                if item.checkState() != QtCore.Qt.Checked:
                    all_checked = False
                    break
        if not any_visible:
            self.form.checkBox.setCheckState(QtCore.Qt.Unchecked)
        else:
            self.form.checkBox.setCheckState(
                QtCore.Qt.Checked if all_checked else QtCore.Qt.Unchecked
            )

    def registerSignalHandlers(self, obj):
        """registerSignalHandlers(obj) ... setup signal handlers"""
        self.form.baseList.itemSelectionChanged.connect(self.itemActivated)
        self.form.addBase.clicked.connect(self.addBase)
        self.form.deleteBase.clicked.connect(self.deleteBase)
        self.form.resetBase.clicked.connect(self.resetBase)
        self.form.baseList.itemChanged.connect(self.checkedChanged)

    def resetBase(self):
        """resetBase() ... push button callback"""
        self.obj.Base = []
        self.obj.Disabled = []
        self.obj.Proxy.findAllHoles(self.obj)

        self.obj.Proxy.execute(self.obj)
        FreeCAD.ActiveDocument.recompute()

    def updateData(self, obj, prop):
        """updateData(obj, prop) ... callback whenever a property of the model changed"""
        if not self.updating and prop in ["Base", "Disabled"]:
            self.setFields(obj)

    def cellManuallyChanged(self, row, column):
        if column == COL_ORDER:
            item = self.form.baseList.item(row, column)
            try:
                # Subtract 1 from the current order number so that it will be pushed to the top of the stack
                self.form.baseList.blockSignals(True)
                item.setText(str(int(item.text()) - 1))
                self.form.baseList.blockSignals(False)
            except (ValueError, AttributeError):
                # If the input is invalid, reset to the original order number
                self.form.baseList.blockSignals(True)
                item.setText(str(row + 1))
                self.form.baseList.blockSignals(False)
                return  # Ignore invalid input

            # Resort rows based on the new order numbers
            rows = []
            for row in range(self.form.baseList.rowCount()):
                order_item = self.form.baseList.item(row, COL_ORDER)
                feature_item = self.form.baseList.item(row, COL_FEATURE)
                diameter_item = self.form.baseList.item(row, COL_DIAMETER)
                try:
                    order = int(order_item.text())
                except (ValueError, AttributeError):
                    order = row + 1
                rows.append(
                    (
                        order,
                        [
                            order_item.clone() if order_item else None,
                            feature_item.clone() if feature_item else None,
                            diameter_item.clone() if diameter_item else None,
                        ],
                    )
                )
            # Sort rows by the order number
            rows.sort(key=lambda x: x[0])
            # Rebuild the table
            self.form.baseList.blockSignals(True)
            self.form.baseList.setRowCount(0)
            for idx, (order, items) in enumerate(rows):
                self.form.baseList.insertRow(idx)
                # Set consecutive order numbers
                items[0].setData(QtCore.Qt.DisplayRole, idx + 1)
                for col, item in enumerate(items):
                    if item:
                        self.form.baseList.setItem(idx, col, item)
            self.form.baseList.blockSignals(False)
            self.updateOrderNumbers()
            self.updateBase()
            self.filterBaseList(self.form.lineEdit.text())  # Reapply filter after reordering

    def itemChanged(self, item):
        """itemChanged(item) ... callback when any item in the table changes"""
        if not self.updating and item.column() == COL_FEATURE:
            self.checkedChanged()


class TaskPanelOpPage(PathOpGui.TaskPanelPage):
    """Base class for circular hole based operation's page controller."""

    def taskPanelBaseGeometryPage(self, obj, features):
        """taskPanelBaseGeometryPage(obj, features) ... Return circular hole specific page controller for Base Geometry."""
        return TaskPanelHoleGeometryPage(obj, features)

    def pageUpdateData(self, obj, prop):
        if prop == "Disabled" and getattr(self, "parent", None):
            for page in self.parent.featurePages:
                if isinstance(page, TaskPanelHoleGeometryPage):
                    page.updateChecked()

        self.updateData(obj, prop)


class LineEditEventFilter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress and event.key() in (
            QtCore.Qt.Key_Return,
            QtCore.Qt.Key_Enter,
        ):
            # Prevent Enter key from propagating to the main form
            return True
        return super(LineEditEventFilter, self).eventFilter(obj, event)
