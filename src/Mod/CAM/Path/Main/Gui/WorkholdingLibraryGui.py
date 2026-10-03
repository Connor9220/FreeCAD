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

"""The vises a library has, to download one: what each is, its licence, whether it is here."""

import threading

import FreeCAD
import FreeCADGui
import Path.Main.WorkholdingLibrary as PathLibrary

from PySide import QtCore, QtGui, QtWidgets

translate = FreeCAD.Qt.translate

THUMBNAIL = 96


def _states():
    return {
        "installed": translate("CAM_AddVise", "Installed"),
        "changed": translate("CAM_AddVise", "Changed in the library"),
        "missing": translate("CAM_AddVise", "Not installed"),
    }


def _length(mm):
    return FreeCAD.Units.Quantity(mm, FreeCAD.Units.Length).UserString


def _nominal(item):
    """A vise's size as it is sold: its jaw width to the nearest inch."""
    return max(1, round(item.get("settings", {}).get("jawWidth", 0) / 25.4))


def _nominalText(size):
    """A vise's size as it is sold, in inches, or 25 mm to the inch where the user works in mm."""
    if FreeCAD.Units.Quantity(1, FreeCAD.Units.Length).UserString.endswith("mm"):
        return translate("CAM_AddVise", "%d mm jaws") % (size * 25)
    return translate("CAM_AddVise", "%d in. jaws") % size


class _Fetcher(QtCore.QObject):
    """What is fetched away from the panel, handed back to it: the library's index, then each
    thumbnail as it comes. Each fetch has its number: what comes late, for a library no longer
    shown, is let be."""

    listed = QtCore.Signal(int, object, str)
    pictured = QtCore.Signal(int, int, object)

    def fetch(self, number, address):
        threading.Thread(target=self.work, args=(number, address), daemon=True).start()

    def work(self, number, address):
        try:
            items = PathLibrary.loadIndex(address)
        except ValueError as e:
            self.listed.emit(number, [], str(e))
            return
        self.listed.emit(number, items, "")
        for row, item in enumerate(items):
            if not item.get("thumbnailUrl"):
                continue
            try:
                self.pictured.emit(number, row, PathLibrary.fetch(item["thumbnailUrl"]))
            except OSError:
                pass


class LibraryDialog(QtWidgets.QDialog):
    """A library's vises, listed: one picked and downloaded, its path in downloaded."""

    def __init__(self, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setWindowTitle(translate("CAM_AddVise", "Get a Vise from a Library"))
        self.setWindowIcon(QtGui.QIcon(":/icons/CAM_Vise.svg"))
        self.resize(560, 520)
        self.downloaded = None
        self.items = []
        # each vise's state here and thumbnail, by its place in the index
        self.states = []
        self.icons = {}
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.source = QtWidgets.QComboBox()
        self.source.setToolTip(translate("CAM_AddVise", "The library looked in: its index"))
        row.addWidget(self.source, 1)
        edit = QtWidgets.QPushButton(translate("CAM_AddVise", "Libraries…"))
        edit.setToolTip(translate("CAM_AddVise", "The libraries to look in, one a line"))
        edit.clicked.connect(self.editSources)
        row.addWidget(edit)
        layout.addLayout(row)
        # the vises found by what is typed, of a type, of a size
        row = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(translate("CAM_AddVise", "Search"))
        self.search.setToolTip(
            translate("CAM_AddVise", "The vises whose name, maker, model or type has every word")
        )
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *args: self.refilter())
        row.addWidget(self.search, 1)
        self.count = QtWidgets.QLabel()
        row.addWidget(self.count)
        layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.type = QtWidgets.QComboBox()
        self.type.setToolTip(translate("CAM_AddVise", "The vises of a type"))
        self.width = QtWidgets.QComboBox()
        self.width.setToolTip(translate("CAM_AddVise", "The vises of a size, by their jaw width"))
        for combo in (self.type, self.width):
            combo.currentIndexChanged.connect(lambda *args: self.refilter())
            row.addWidget(combo, 1)
        layout.addLayout(row)
        for combo in (self.source, self.type, self.width):
            combo.setStyleSheet("combobox-popup: 0;")
        self.list = QtWidgets.QListWidget()
        self.list.setIconSize(QtCore.QSize(THUMBNAIL, THUMBNAIL))
        self.list.setSpacing(2)
        self.list.currentItemChanged.connect(lambda *args: self.showPicked())
        self.list.itemDoubleClicked.connect(lambda *args: self.download())
        layout.addWidget(self.list, 1)
        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setOpenExternalLinks(True)
        self.details.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(self.details)
        buttons = QtWidgets.QDialogButtonBox()
        self.get = buttons.addButton(
            translate("CAM_AddVise", "Download"), QtWidgets.QDialogButtonBox.AcceptRole
        )
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        self.get.clicked.connect(self.download)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # fetched away from the dialog, which opens at once and fills in as they come
        self.fetcher = _Fetcher()
        self.fetcher.listed.connect(self.listed)
        self.fetcher.pictured.connect(self.pictured)
        self.loading = 0
        self.fillSources()
        self.source.currentIndexChanged.connect(lambda *args: self.load())
        self.load()

    def fillSources(self):
        self.source.blockSignals(True)
        self.source.clear()
        for address in PathLibrary.sources():
            self.source.addItem(address)
        self.source.blockSignals(False)

    def editSources(self):
        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self,
            translate("CAM_AddVise", "Libraries"),
            translate(
                "CAM_AddVise",
                "The libraries to look in, the address of each one's index.json, one a line; "
                "none, the default:",
            ),
            "\n".join(PathLibrary.sources()),
        )
        if ok:
            PathLibrary.setSources(text.splitlines())
            self.fillSources()
            self.load()

    def load(self):
        """The library's vises fetched, listed when they come, their thumbnails after."""
        self.list.clear()
        self.items = []
        self.states = []
        self.icons = {}
        self.fillFilters()
        self.count.setText("")
        self.get.setEnabled(False)
        address = self.source.currentText()
        self.loading += 1
        if not address:
            self.details.setText("")
            return
        self.details.setText(translate("CAM_AddVise", "Loading the library…"))
        self.fetcher.fetch(self.loading, address)

    def listed(self, number, items, error):
        """The library's vises come: each listed with whether it is here, a vise's icon until
        its thumbnail comes."""
        if number != self.loading:
            return
        if error:
            self.details.setText(error)
            return
        self.items = items
        self.states = [PathLibrary.status(item) for item in items]
        self.fillFilters()
        self.refilter()
        if not self.items:
            self.details.setText(translate("CAM_AddVise", "This library lists no vises."))

    def fillFilters(self):
        """The types and sizes the library has, to pick from; what was picked kept if it has it."""
        for combo, everything, values, text in (
            (
                self.type,
                translate("CAM_AddVise", "All types"),
                sorted({item.get("type", "") for item in self.items} - {""}),
                lambda value: value,
            ),
            (
                self.width,
                translate("CAM_AddVise", "All jaw widths"),
                sorted({_nominal(item) for item in self.items}),
                _nominalText,
            ),
        ):
            picked = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(everything, None)
            for value in values:
                combo.addItem(text(value), value)
            combo.setCurrentIndex(max(0, combo.findData(picked)))
            combo.blockSignals(False)

    def shown(self, item):
        """Whether a vise is of the type and size picked, and has every word searched for."""
        kind = self.type.currentData()
        if kind is not None and item.get("type") != kind:
            return False
        size = self.width.currentData()
        if size is not None and _nominal(item) != size:
            return False
        words = " ".join(
            str(item.get(key, "")) for key in ("label", "maker", "model", "type", "id")
        ).lower()
        return all(word in words for word in self.search.text().lower().split())

    def refilter(self):
        """The vises found listed by name, the one picked before still picked."""
        current = self.list.currentItem()
        keep = current.data(QtCore.Qt.UserRole) if current else None
        states = _states()
        found = sorted(
            (index for index, item in enumerate(self.items) if self.shown(item)),
            key=lambda index: self.items[index].get("label", "").lower(),
        )
        self.list.blockSignals(True)
        self.list.clear()
        for index in found:
            item = self.items[index]
            settings = item.get("settings", {})
            text = "%s\n%s" % (
                item.get("label", item["id"]),
                " · ".join(
                    part
                    for part in (
                        item.get("type", ""),
                        translate("CAM_AddVise", "%s jaws, opens %s")
                        % (
                            _length(settings.get("jawWidth", 0)),
                            _length(settings.get("maxOpening", 0)),
                        ),
                        states[self.states[index]],
                    )
                    if part
                ),
            )
            icon = self.icons.get(index) or QtGui.QIcon(":/icons/CAM_Vise.svg")
            entry = QtWidgets.QListWidgetItem(icon, text)
            entry.setData(QtCore.Qt.UserRole, index)
            self.list.addItem(entry)
            if index == keep:
                self.list.setCurrentItem(entry)
        self.list.blockSignals(False)
        if self.items:
            self.count.setText(translate("CAM_AddVise", "%d of %d") % (len(found), len(self.items)))
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.showPicked()

    def pictured(self, number, index, data):
        """A thumbnail come, in place of the vise's icon."""
        if number != self.loading:
            return
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(data):
            return
        icon = QtGui.QIcon(pixmap.scaled(THUMBNAIL, THUMBNAIL, QtCore.Qt.KeepAspectRatio))
        self.icons[index] = icon
        for row in range(self.list.count()):
            entry = self.list.item(row)
            if entry.data(QtCore.Qt.UserRole) == index:
                entry.setIcon(icon)

    def picked(self):
        """The vise picked, or None."""
        entry = self.list.currentItem()
        return self.items[entry.data(QtCore.Qt.UserRole)] if entry else None

    def done(self, result):
        # what is still being fetched comes to nothing
        self.loading += 1
        super().done(result)

    def showPicked(self):
        """What the vise picked is, its licence, and whether it is here."""
        item = self.picked()
        if item is None:
            self.details.setText(
                translate("CAM_AddVise", "No vise in the library matches.") if self.items else ""
            )
            self.get.setEnabled(False)
            return
        state = PathLibrary.status(item)
        self.get.setEnabled(True)
        self.get.setText(
            translate("CAM_AddVise", "Use it")
            if state == "installed"
            else (
                translate("CAM_AddVise", "Update")
                if state == "changed"
                else translate("CAM_AddVise", "Download")
            )
        )
        source = item.get("source", "")
        self.details.setText(
            "<b>%s</b><br>%s<br>%s: %s<br>%s<br><a href='%s'>%s</a>"
            % (
                item.get("label", item["id"]),
                "%s %s" % (item.get("maker", ""), item.get("model", "")),
                translate("CAM_AddVise", "Licence"),
                item.get("licence", ""),
                item.get("attribution", ""),
                source,
                source,
            )
        )

    def download(self):
        """The vise picked saved where vises are kept, and the dialog closed: one already here
        used as it is; one changed here replaced only if the user says so."""
        item = self.picked()
        if item is None:
            return
        state = PathLibrary.status(item)
        if state == "installed":
            self.downloaded = PathLibrary.localPath(item)
            self.accept()
            return
        if state == "changed":
            answer = QtWidgets.QMessageBox.question(
                self,
                translate("CAM_AddVise", "Update Vise"),
                translate(
                    "CAM_AddVise",
                    "%s is here, and not as the library has it: changed in the library, or "
                    "here. Replace it with the library's?",
                )
                % PathLibrary.localPath(item),
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.downloaded = PathLibrary.download(item)
        except (OSError, ValueError) as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(
                self, translate("CAM_AddVise", "Get a Vise from a Library"), str(e)
            )
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self.accept()


def getVise(parent=None):
    """getVise(parent=None) ... the path of a vise picked from a library and saved here, None if
    none was."""
    dialog = LibraryDialog(parent)
    if dialog.exec() == QtWidgets.QDialog.Accepted:
        return dialog.downloaded
    return None
