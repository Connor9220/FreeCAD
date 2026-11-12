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

"""The Machine Library: the machines of every registered library, each installed alone."""

import os
import time

import FreeCAD
import FreeCADGui
import Path
from PySide import QtCore, QtGui
from PySide.QtCore import QT_TRANSLATE_NOOP

from Machine.models import library
from Machine.models.machine import MachineFactory

translate = FreeCAD.Qt.translate

# the list's columns, and the column of a machine's state here
COLUMNS = (
    QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Machine"),
    QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Maker"),
    QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Axes"),
    QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Units"),
    QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Here"),
)
STATE_COLUMN = 4
# marks a machine whose file includes its 3D model
MODEL_ICON = ":/icons/view-axonometric.svg"
# the Show filter's choices: the states each lists
SHOW = (
    (QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Show: all"), None),
    (QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Not installed"), ("absent",)),
    (QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Installed"), ("current", "update", "modified")),
    (QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Updates"), ("update",)),
)


def _stateText(state):
    return {
        "absent": "",
        "current": translate("CAM_MachineLibrary", "Installed"),
        "update": translate("CAM_MachineLibrary", "Update available"),
        "modified": translate("CAM_MachineLibrary", "Changed here"),
    }[state]


class MachineLibraryDialog(QtGui.QDialog):
    """Lists the machines of every registered library, grouped by library and by the folder
    each library keeps them in. Install saves the
    machines picked in the user's Machines folder; installed holds the paths saved."""

    def __init__(self, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setWindowTitle(translate("CAM_MachineLibrary", "Machine Library"))
        self.resize(980, 600)
        self.installed = []
        self.folder = str(MachineFactory.get_config_directory())
        # each library: (label, address, branch, its machines, when its kept index was kept or
        # None, the error reading it or None)
        self.libraries = []
        layout = QtGui.QVBoxLayout(self)

        row = QtGui.QHBoxLayout()
        self.libraryPick = QtGui.QComboBox()
        self.libraryPick.setToolTip(translate("CAM_MachineLibrary", "Every library, or one"))
        self.search = QtGui.QLineEdit()
        self.search.setPlaceholderText(
            translate("CAM_MachineLibrary", "Search machines, makers, controllers")
        )
        self.search.setClearButtonEnabled(True)
        self.axesPick = QtGui.QComboBox()
        self.axesPick.setToolTip(translate("CAM_MachineLibrary", "Machines with these axes"))
        self.showPick = QtGui.QComboBox()
        for text, _ in SHOW:
            self.showPick.addItem(translate("CAM_MachineLibrary", text))
        for pick in (self.libraryPick, self.axesPick, self.showPick):
            pick.setSizeAdjustPolicy(QtGui.QComboBox.AdjustToContents)
        row.addWidget(self.libraryPick)
        row.addWidget(self.search, 1)
        row.addWidget(self.axesPick)
        row.addWidget(self.showPick)
        layout.addLayout(row)

        row = QtGui.QHBoxLayout()
        self.tree = QtGui.QTreeWidget()
        self.tree.setHeaderLabels([translate("CAM_MachineLibrary", c) for c in COLUMNS])
        self.tree.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self.picked)
        self.tree.itemDoubleClicked.connect(lambda *args: self.install())
        row.addWidget(self.tree, 1)
        self.details = self.makeDetails()
        row.addWidget(self.details)
        layout.addLayout(row, 1)

        row = QtGui.QHBoxLayout()
        self.summary = QtGui.QLabel()
        row.addWidget(self.summary, 1)
        self.updateAllButton = QtGui.QPushButton()
        self.updateAllButton.setToolTip(
            translate("CAM_MachineLibrary", "Install the newer version of every machine listed")
        )
        self.updateAllButton.clicked.connect(self.updateAll)
        self.installButton = QtGui.QPushButton(translate("CAM_MachineLibrary", "Install"))
        self.installButton.setToolTip(
            translate("CAM_MachineLibrary", "Save the machines picked in your Machines folder")
        )
        self.installButton.setDefault(True)
        self.installButton.clicked.connect(self.install)
        close = QtGui.QPushButton(translate("CAM_MachineLibrary", "Close"))
        close.clicked.connect(self.reject)
        for button in (self.updateAllButton, self.installButton, close):
            row.addWidget(button)
        layout.addLayout(row)

        self.libraryPick.currentIndexChanged.connect(lambda *args: self.fill())
        self.axesPick.currentIndexChanged.connect(lambda *args: self.fill())
        self.showPick.currentIndexChanged.connect(lambda *args: self.fill())
        self.search.textChanged.connect(lambda *args: self.fill())
        QtCore.QTimer.singleShot(0, self.load)

    def makeDetails(self):
        """The picked machine's description, post processor, library, file and folder."""
        panel = QtGui.QFrame()
        panel.setFrameShape(QtGui.QFrame.StyledPanel)
        panel.setFixedWidth(270)
        layout = QtGui.QVBoxLayout(panel)
        self.title = QtGui.QLabel()
        font = self.title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.title.setFont(font)
        self.title.setWordWrap(True)
        self.description = QtGui.QLabel()
        self.description.setWordWrap(True)
        self.description.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self.form = QtGui.QFormLayout()
        self.facts = {}
        for key, text in (
            ("postprocessor", QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Post")),
            ("library", QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Library")),
            ("file", QT_TRANSLATE_NOOP("CAM_MachineLibrary", "File")),
            ("model", QT_TRANSLATE_NOOP("CAM_MachineLibrary", "3D model")),
            ("license", QT_TRANSLATE_NOOP("CAM_MachineLibrary", "License")),
            ("folder", QT_TRANSLATE_NOOP("CAM_MachineLibrary", "Saved to")),
        ):
            value = QtGui.QLabel()
            value.setWordWrap(True)
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.facts[key] = value
            self.form.addRow(translate("CAM_MachineLibrary", text), value)
        layout.addWidget(self.title)
        layout.addWidget(self.description)
        layout.addLayout(self.form)
        layout.addStretch(1)
        return panel

    def load(self):
        """Read every library's index, its kept copy when it cannot be fetched."""
        self.libraries = []
        QtGui.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            for label, address, branch in library.libraries():
                try:
                    items, keptAt = library.loadIndex(address, branch)
                    self.libraries.append((label, address, branch, items, keptAt, None))
                except ValueError as e:
                    Path.Log.warning(str(e))
                    self.libraries.append((label, address, branch, [], None, str(e)))
        finally:
            QtGui.QApplication.restoreOverrideCursor()
        with QtCore.QSignalBlocker(self.libraryPick), QtCore.QSignalBlocker(self.axesPick):
            self.libraryPick.clear()
            self.libraryPick.addItem(translate("CAM_MachineLibrary", "All libraries"), None)
            for label, address, *_ in self.libraries:
                self.libraryPick.addItem(label, address)
            self.axesPick.clear()
            self.axesPick.addItem(translate("CAM_MachineLibrary", "Axes: any"), None)
            axes = {i.get("axes", "") for entry in self.libraries for i in entry[3]}
            for name in sorted(a for a in axes if a):
                self.axesPick.addItem(name, name)
        if not self.libraries:
            self.summary.setText(translate("CAM_MachineLibrary", "No machine library is known."))
        self.fill()

    def listed(self, item):
        """Whether the filters let a machine through."""
        axes = self.axesPick.currentData()
        if axes and item.get("axes") != axes:
            return False
        states = SHOW[max(0, self.showPick.currentIndex())][1]
        if states and library.status(item, self.folder) not in states:
            return False
        words = self.search.text().lower().split()
        text = " ".join(
            str(item.get(k, "")) for k in ("label", "maker", "description", "postprocessor")
        ).lower()
        return all(w in text for w in words)

    def fill(self):
        """List the machines the filters let through, grouped by library and folder."""
        self.tree.clear()
        picked = self.libraryPick.currentData()
        filtered = bool(
            self.search.text().strip()
            or self.axesPick.currentData()
            or self.showPick.currentIndex()
        )
        shown = 0
        for label, address, branch, items, keptAt, error in self.libraries:
            if picked and address != picked:
                continue
            top = QtGui.QTreeWidgetItem([label])
            top.setFlags(QtCore.Qt.ItemIsEnabled)
            top.setToolTip(0, address + (" (%s)" % branch if branch else ""))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            if error:
                top.setText(1, translate("CAM_MachineLibrary", "could not be read"))
            elif keptAt is not None:
                top.setText(
                    1,
                    translate("CAM_MachineLibrary", "offline, listed from the copy kept %s")
                    % time.strftime("%Y-%m-%d", time.localtime(keptAt)),
                )
            self.tree.addTopLevelItem(top)
            groups = {}
            for item in sorted(items, key=lambda i: (i.get("group", ""), i.get("label", ""))):
                if not self.listed(item):
                    continue
                group = item.get("group", "")
                if group not in groups:
                    groups[group] = QtGui.QTreeWidgetItem(top, [group or label])
                    groups[group].setFlags(QtCore.Qt.ItemIsEnabled)
                self.addMachine(groups[group], item, label)
                shown += 1
            # a library none of whose machines pass the filters is left out, unless unread
            if filtered and not groups and not error:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(top))
        self.tree.expandAll()
        for column in range(len(COLUMNS)):
            self.tree.resizeColumnToContents(column)
        self.counts(shown)
        self.picked()

    def addMachine(self, parent, item, label):
        row = QtGui.QTreeWidgetItem(
            parent,
            [
                item.get("label", ""),
                item.get("maker", ""),
                item.get("axes", ""),
                item.get("units", ""),
                _stateText(library.status(item, self.folder)),
            ],
        )
        row.setData(0, QtCore.Qt.UserRole, dict(item, libraryLabel=label))
        tip = item.get("description", "")
        if item.get("model"):
            # a machine whose file brings its 3D model, for the simulator's machine view
            row.setIcon(0, QtGui.QIcon(MODEL_ICON))
            tip = "\n".join(
                t for t in (tip, translate("CAM_MachineLibrary", "Includes a 3D model")) if t
            )
        row.setToolTip(0, tip)
        return row

    def machines(self):
        """Every machine listed, as its row."""
        found = []
        rows = QtGui.QTreeWidgetItemIterator(self.tree)
        while rows.value():
            if rows.value().data(0, QtCore.Qt.UserRole):
                found.append(rows.value())
            rows += 1
        return found

    def counts(self, shown):
        machines = sum(len(entry[3]) for entry in self.libraries)
        here = sum(
            library.status(i, self.folder) != "absent" for entry in self.libraries for i in entry[3]
        )
        self.summary.setText(
            translate("CAM_MachineLibrary", "%d libraries · %d machines · %d installed · %d shown")
            % (len(self.libraries), machines, here, shown)
        )
        updates = [r for r in self.machines() if self.state(r) == "update"]
        self.updateAllButton.setText(
            translate("CAM_MachineLibrary", "Update all (%d)") % len(updates)
        )
        self.updateAllButton.setEnabled(bool(updates))

    def state(self, row):
        return library.status(row.data(0, QtCore.Qt.UserRole), self.folder)

    def chosen(self):
        """The machines picked, as their index entries."""
        return [
            row.data(0, QtCore.Qt.UserRole)
            for row in self.tree.selectedItems()
            if row.data(0, QtCore.Qt.UserRole)
        ]

    def picked(self):
        items = self.chosen()
        self.installButton.setEnabled(
            any(library.status(item, self.folder) != "current" for item in items)
        )
        item = items[0] if len(items) == 1 else None
        self.details.setVisible(item is not None)
        if item is None:
            return
        # the maker in front, unless the machine's name already starts with it
        maker, name = item.get("maker", ""), item.get("label", "")
        self.title.setText(name if not maker or name.startswith(maker) else maker + " " + name)
        self.description.setText(item.get("description", ""))
        values = {
            "postprocessor": item.get("postprocessor") or "-",
            "library": item.get("libraryLabel", ""),
            "file": os.path.basename(item["file"]),
            "model": translate("CAM_MachineLibrary", "included") if item.get("model") else "",
            "license": item.get("license", ""),
            "folder": self.folder,
        }
        for key, value in values.items():
            self.facts[key].setText(value)
            self.form.setRowVisible(self.facts[key], bool(value))
        self.details.layout().activate()

    def save(self, items):
        """Save items; one changed here is replaced only once confirmed."""
        for item in items:
            state = library.status(item, self.folder)
            if state == "current":
                continue
            if state == "modified":
                answer = QtGui.QMessageBox.question(
                    self,
                    translate("CAM_MachineLibrary", "Replace machine"),
                    translate(
                        "CAM_MachineLibrary",
                        "%s in your Machines folder is not the library's. Replace it?",
                    )
                    % library.localPath(item, self.folder),
                )
                if answer != QtGui.QMessageBox.Yes:
                    continue
            try:
                path = library.download(item, self.folder)
            except (OSError, ValueError) as e:
                QtGui.QMessageBox.warning(
                    self, translate("CAM_MachineLibrary", "Machine not installed"), str(e)
                )
                continue
            self.installed.append(path)
            Path.Log.info(
                translate("CAM_MachineLibrary", "%s saved in %s") % (item.get("label", ""), path)
            )
        for row in self.machines():
            row.setText(STATE_COLUMN, _stateText(self.state(row)))
        self.counts(len(self.machines()))
        self.picked()

    def install(self):
        self.save(self.chosen())

    def updateAll(self):
        self.save(
            [
                row.data(0, QtCore.Qt.UserRole)
                for row in self.machines()
                if self.state(row) == "update"
            ]
        )
