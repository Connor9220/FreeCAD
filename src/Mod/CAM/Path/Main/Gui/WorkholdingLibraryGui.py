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

"""The vises or clamps on this computer and in the libraries, to choose one to add to a Job: what
each is, where it came from, its licence, whether it is here; one a library has downloaded."""

import os
import threading

import FreeCAD
import FreeCADGui
import Path.Main.WorkholdingLibrary as PathLibrary

from PySide import QtCore, QtGui, QtWidgets

translate = FreeCAD.Qt.translate

THUMBNAIL = 96


def _states():
    """What each state says: a library's against the file of its name here, as status has it;
    one here against its library's, as localStates has it."""
    return {
        "missing": translate("CAM_AddVise", "Not installed"),
        "current": translate("CAM_AddVise", "Installed"),
        "here": translate("CAM_AddVise", "Up to date"),
        "update": translate("CAM_AddVise", "Update available"),
        "modified": translate("CAM_AddVise", "Modified here"),
    }


def _badged(icon):
    """An icon with an update's badge on its corner: an orange disc with an arrow up, seen in any
    theme."""
    pixmap = icon.pixmap(THUMBNAIL, THUMBNAIL)
    if pixmap.isNull():
        return icon
    pixmap = QtGui.QPixmap(pixmap)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    size = max(18, pixmap.width() // 3)
    disc = QtCore.QRectF(pixmap.width() - size - 1, 1, size, size)
    painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.5))
    painter.setBrush(QtGui.QColor("#f08c00"))
    painter.drawEllipse(disc)
    c = disc.center()
    h = size * 0.28
    arrow = QtGui.QPolygonF(
        [
            QtCore.QPointF(c.x(), c.y() - h),
            QtCore.QPointF(c.x() + h, c.y()),
            QtCore.QPointF(c.x() + h * 0.4, c.y()),
            QtCore.QPointF(c.x() + h * 0.4, c.y() + h),
            QtCore.QPointF(c.x() - h * 0.4, c.y() + h),
            QtCore.QPointF(c.x() - h * 0.4, c.y()),
            QtCore.QPointF(c.x() - h, c.y()),
        ]
    )
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor("#ffffff"))
    painter.drawPolygon(arrow)
    painter.end()
    return QtGui.QIcon(pixmap)


def _length(mm):
    return FreeCAD.Units.Quantity(mm, FreeCAD.Units.Length).UserString


def _nominal(item):
    """A vise's size as it is sold: its jaw width to the nearest inch."""
    return max(1, round(item.get("settings", {}).get("jawWidth", 0) / 25.4))


def _words(kind):
    """What the dialog says for vises, or for clamps."""
    if kind == "clamp":
        return {
            "title": translate("CAM_AddVise", "Choose a Clamp"),
            "icon": ":/icons/CAM_Job.svg",
            "search": translate(
                "CAM_AddVise", "The clamps whose name, maker, model or type has every word"
            ),
            "type": translate("CAM_AddVise", "The clamps of a type"),
            "none": translate("CAM_AddVise", "This library lists no clamps."),
            "nomatch": translate("CAM_AddVise", "No clamp matches."),
            "local": translate(
                "CAM_AddVise",
                "No clamps on this computer yet: add a library with Libraries…, or open one with "
                "Other file….",
            ),
            "other": translate("CAM_AddVise", "Open a Clamp"),
            "update": translate("CAM_AddVise", "Update Clamp"),
        }
    return {
        "title": translate("CAM_AddVise", "Choose a Vise"),
        "icon": ":/icons/CAM_Vise.svg",
        "search": translate(
            "CAM_AddVise", "The vises whose name, maker, model or type has every word"
        ),
        "type": translate("CAM_AddVise", "The vises of a type"),
        "none": translate("CAM_AddVise", "This library lists no vises."),
        "nomatch": translate("CAM_AddVise", "No vise matches."),
        "local": translate(
            "CAM_AddVise",
            "No vises on this computer yet: add a library with Libraries…, or open one with "
            "Other file….",
        ),
        "other": translate("CAM_AddVise", "Open a Vise"),
        "update": translate("CAM_AddVise", "Update Vise"),
    }


def _nominalText(size):
    """A vise's size as it is sold, in inches, or 25 mm to the inch where the user works in mm."""
    if FreeCAD.Units.Quantity(1, FreeCAD.Units.Length).UserString.endswith("mm"):
        return translate("CAM_AddVise", "%d mm jaws") % (size * 25)
    return translate("CAM_AddVise", "%d in. jaws") % size


class _Combo(QtWidgets.QComboBox):
    """A drop-down whose list, dropped down below it, is as tall as its rows, up to as many as
    it shows: a theme's padding inside the list is not let make it scroll."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("combobox-popup: 0;")

    def showPopup(self):
        super().showPopup()
        view = self.view()
        rows = min(self.count(), self.maxVisibleItems())
        wanted = sum(view.sizeHintForRow(i) for i in range(rows))
        short = wanted - view.viewport().height()
        if short > 0:
            popup = view.window()
            popup.resize(popup.width(), popup.height() + short)


class _Refresher(QtCore.QObject):
    """The libraries' indexes fetched again and kept, away from the dialog, each once it opens:
    one that cannot be is let be, its kept one used, and tried again the next time."""

    refreshed = QtCore.Signal()

    def refresh(self, addresses):
        threading.Thread(target=self.work, args=(list(addresses),), daemon=True).start()

    def work(self, addresses):
        for address in addresses:
            PathLibrary.refreshIndex(address)
        self.refreshed.emit()


class _Fetcher(QtCore.QObject):
    """What is fetched away from the panel, handed back to it: the library's index, then each
    thumbnail as it comes. Each fetch has its number: what comes late, for a library no longer
    shown, is let be."""

    listed = QtCore.Signal(int, object, str)
    pictured = QtCore.Signal(int, int, object)

    def fetch(self, number, address, kind="vise"):
        threading.Thread(target=self.work, args=(number, address, kind), daemon=True).start()

    def work(self, number, address, kind):
        try:
            items = PathLibrary.loadIndex(address, kind)
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


class LibrariesDialog(QtWidgets.QDialog):
    """The libraries to look in, each an address and a branch, added, changed in place or taken
    away; none, the default."""

    def __init__(self, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setWindowTitle(translate("CAM_AddVise", "Libraries"))
        self.resize(620, 300)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            translate(
                "CAM_AddVise",
                "The libraries to look in: a GitHub repository, the address of an index.json, or "
                "a folder. The branch is a GitHub repository's; empty, its default. None, the "
                "default library.",
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(
            [translate("CAM_AddVise", "Library"), translate("CAM_AddVise", "Branch")]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        self.table.setColumnWidth(1, 120)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        for address, branch in PathLibrary.libraries():
            self.addRow(address, branch)
        layout.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QToolButton()
        add.setIcon(QtGui.QIcon.fromTheme("list-add", QtGui.QIcon(":/icons/list-add.svg")))
        add.setToolTip(translate("CAM_AddVise", "Add a library"))
        add.clicked.connect(self.added)
        remove = QtWidgets.QToolButton()
        remove.setIcon(QtGui.QIcon.fromTheme("list-remove", QtGui.QIcon(":/icons/list-remove.svg")))
        remove.setToolTip(translate("CAM_AddVise", "Take the library picked away"))
        remove.clicked.connect(self.removed)
        for button, text in ((add, "+"), (remove, "−")):
            if button.icon().isNull():
                button.setText(text)
            row.addWidget(button)
        row.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

    def addRow(self, address="", branch=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(address))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(branch))
        return row

    def added(self):
        row = self.addRow()
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))

    def removed(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def libraries(self):
        """The libraries as the table has them, (address, branch) pairs."""
        found = []
        for row in range(self.table.rowCount()):
            address, branch = (
                (self.table.item(row, column) or QtWidgets.QTableWidgetItem()).text().strip()
                for column in (0, 1)
            )
            if address:
                found.append((address, branch))
        return found


class LibraryDialog(QtWidgets.QDialog):
    """The vises, or clamps, on this computer, by the library each came from, or a library's,
    listed: one chosen, downloaded first if it is not here, its path in downloaded."""

    def __init__(self, parent=None, kind="vise"):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.kind = kind
        self.words = _words(kind)
        self.setWindowTitle(self.words["title"])
        self.setWindowIcon(QtGui.QIcon(self.words["icon"]))
        self.resize(580, 560)
        self.downloaded = None
        self.items = []
        # each one's state and thumbnail, by its place in the list of items; of those on this
        # computer, the library's item each would be updated from
        self.states = []
        self.updates = []
        self.icons = {}
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.source = _Combo()
        self.source.setToolTip(translate("CAM_AddVise", "Those on this computer, or a library's"))
        row.addWidget(self.source, 1)
        edit = QtWidgets.QPushButton(translate("CAM_AddVise", "Libraries…"))
        edit.setToolTip(translate("CAM_AddVise", "The libraries to look in, and their branches"))
        edit.clicked.connect(self.editSources)
        row.addWidget(edit)
        layout.addLayout(row)
        # found by what is typed, of a type, of a size
        row = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(translate("CAM_AddVise", "Search"))
        self.search.setToolTip(self.words["search"])
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *args: self.refilter())
        row.addWidget(self.search, 1)
        self.count = QtWidgets.QLabel()
        row.addWidget(self.count)
        layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.type = _Combo()
        self.type.setToolTip(self.words["type"])
        self.width = _Combo()
        self.width.setToolTip(translate("CAM_AddVise", "The vises of a size, by their jaw width"))
        for combo in (self.type, self.width):
            combo.currentIndexChanged.connect(lambda *args: self.refilter())
            row.addWidget(combo, 1)
        # a clamp has no jaws
        self.width.setVisible(kind == "vise")
        layout.addLayout(row)
        self.list = QtWidgets.QListWidget()
        self.list.setIconSize(QtCore.QSize(THUMBNAIL, THUMBNAIL))
        # a long line cut short, not scrolled sideways to
        self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list.setSpacing(2)
        self.list.currentItemChanged.connect(lambda *args: self.showPicked())
        self.list.itemSelectionChanged.connect(self.showPicked)
        self.list.itemDoubleClicked.connect(
            lambda *args: self.download() if self.get.isEnabled() else None
        )
        layout.addWidget(self.list, 1)
        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setOpenExternalLinks(True)
        self.details.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(self.details)
        buttons = QtWidgets.QDialogButtonBox()
        other = buttons.addButton(
            translate("CAM_AddVise", "Other file…"), QtWidgets.QDialogButtonBox.ActionRole
        )
        other.setToolTip(
            translate("CAM_AddVise", "One kept somewhere else, found on this computer")
        )
        other.setIcon(QtGui.QIcon.fromTheme("edit-find", QtGui.QIcon(":/icons/zoom-in.svg")))
        other.clicked.connect(self.otherFile)
        self.get = buttons.addButton(
            translate("CAM_AddVise", "Add"), QtWidgets.QDialogButtonBox.AcceptRole
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
        # the library whose are listed, None for those on this computer
        self.showing = None
        self.fillSources()
        self.source.currentIndexChanged.connect(lambda *args: self.load())
        # those here first; a library's when none are
        if not PathLibrary.localItems(kind) and self.source.count() > 1:
            self.source.setCurrentIndex(1)
        self.load()
        # the libraries' indexes brought up to date, those here told against them when they are
        self.refresher = _Refresher()
        self.refresher.refreshed.connect(self.refreshed)
        self.refresher.refresh(PathLibrary.sources())

    def local(self):
        """Whether those on this computer are shown."""
        return self.showing is None

    def fillSources(self):
        keep = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem(translate("CAM_AddVise", "On this computer"), None)
        for address in PathLibrary.sources():
            self.source.addItem(PathLibrary.libraryName(address), address)
            self.source.setItemData(self.source.count() - 1, address, QtCore.Qt.ToolTipRole)
        self.source.setCurrentIndex(max(0, self.source.findData(keep)) if keep else 0)
        self.source.blockSignals(False)

    def refreshed(self):
        """The libraries' indexes fetched again: those here told against them anew."""
        if self.local() and self.items:
            self.tellLocal()
            self.refilter()

    def tellLocal(self):
        """Those on this computer against the indexes kept of their libraries."""
        found = PathLibrary.localStates(self.items)
        self.states = [{"current": "here"}.get(state, state) for state, _ in found]
        self.updates = [listed for _, listed in found]
        # one not stamped, found in a library by what it is: its type the library's
        for item, listed in zip(self.items, self.updates):
            if listed is not None and not item.get("library"):
                item.setdefault("type", listed.get("type", ""))

    def editSources(self):
        dialog = LibrariesDialog(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            PathLibrary.setLibraries(dialog.libraries())
            self.fillSources()
            self.load()

    def load(self):
        """Those on this computer read, or a library's fetched, listed when they come, their
        thumbnails after."""
        self.list.clear()
        self.items = []
        self.states = []
        self.updates = []
        self.icons = {}
        self.fillFilters()
        self.count.setText("")
        self.get.setEnabled(False)
        self.loading += 1
        self.showing = self.source.currentData()
        if self.local():
            items = PathLibrary.localItems(self.kind)
            self.listed(self.loading, items, "")
            for index, item in enumerate(items):
                data = PathLibrary.thumbnail(item["path"])
                if data:
                    self.pictured(self.loading, index, data)
            return
        self.details.setText(translate("CAM_AddVise", "Loading the library…"))
        self.fetcher.fetch(self.loading, self.showing, self.kind)

    def listed(self, number, items, error):
        """Those listed come: each with whether it is here, an icon until its thumbnail comes."""
        if number != self.loading:
            return
        if error:
            self.details.setText(error)
            return
        self.items = items
        if self.local():
            self.tellLocal()
        else:
            self.states = [PathLibrary.status(item) for item in items]
            self.updates = [None] * len(items)
        self.fillFilters()
        self.refilter()
        if not self.items:
            self.details.setText(self.words["local"] if self.local() else self.words["none"])

    def fillFilters(self):
        """The types and sizes listed, to pick from; what was picked kept if it is there."""
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
        """Whether one is of the type and size picked, and has every word searched for."""
        kind = self.type.currentData()
        if kind is not None and item.get("type") != kind:
            return False
        size = self.width.currentData()
        if self.kind == "vise" and size is not None and _nominal(item) != size:
            return False
        words = " ".join(
            str(item.get(key, "")) for key in ("label", "maker", "model", "type", "id")
        ).lower()
        return all(word in words for word in self.search.text().lower().split())

    def group(self, index):
        """The heading one is listed under on this computer: those with an update first, then
        the library each came from, else the user's own; and the order of the headings."""
        if self.states[index] == "update":
            return (-1, ""), translate("CAM_AddVise", "Updates available")
        item = self.items[index]
        # its stamp's library, else the one it was found in by what it is
        listed = self.updates[index] if index < len(self.updates) else None
        library = item.get("library", "") or (listed["index"] if listed else "")
        if library:
            return (0, PathLibrary.libraryName(library).lower()), PathLibrary.libraryName(library)
        return (1, ""), translate("CAM_Vise", "Your own files")

    def refilter(self):
        """Those found listed by name, under the library each came from on this computer; the
        one picked before still picked."""
        keep = self.pickedIndex()
        states = _states()
        found = [index for index, item in enumerate(self.items) if self.shown(item)]
        if self.local():
            found.sort(key=lambda i: (self.group(i)[0], self.items[i]["label"].lower()))
        else:
            # those with an update first
            found.sort(
                key=lambda i: (self.states[i] != "update", self.items[i].get("label", "").lower())
            )
        self.list.blockSignals(True)
        self.list.clear()
        heading = None
        for index in found:
            item = self.items[index]
            if self.local() and self.group(index)[1] != heading:
                heading = self.group(index)[1]
                entry = QtWidgets.QListWidgetItem(heading)
                font = entry.font()
                font.setBold(True)
                entry.setFont(font)
                entry.setFlags(QtCore.Qt.NoItemFlags)
                self.list.addItem(entry)
            settings = item.get("settings", {})
            text = "%s\n%s" % (
                item.get("label", item["id"]),
                " · ".join(
                    part
                    for part in (
                        states.get(self.states[index], ""),
                        item.get("type", ""),
                        (
                            translate("CAM_AddVise", "%s jaws, opens %s")
                            % (
                                _length(settings.get("jawWidth", 0)),
                                _length(settings.get("maxOpening", 0)),
                            )
                            if self.kind == "vise" and settings.get("jawWidth")
                            else ""
                        ),
                    )
                    if part
                ),
            )
            icon = self.icons.get(index) or QtGui.QIcon(self.words["icon"])
            if self.states[index] == "update":
                icon = _badged(icon)
            entry = QtWidgets.QListWidgetItem(icon, text)
            entry.setData(QtCore.Qt.UserRole, index)
            if self.states[index] == "update":
                font = entry.font()
                font.setBold(True)
                entry.setFont(font)
            self.list.addItem(entry)
            if index == keep:
                self.list.setCurrentItem(entry)
        self.list.blockSignals(False)
        if self.items:
            self.count.setText(translate("CAM_AddVise", "%d of %d") % (len(found), len(self.items)))
        self.showPicked()

    def pictured(self, number, index, data):
        """A thumbnail come, in place of the icon."""
        if number != self.loading:
            return
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(data):
            return
        icon = QtGui.QIcon(pixmap.scaled(THUMBNAIL, THUMBNAIL, QtCore.Qt.KeepAspectRatio))
        self.icons[index] = icon
        if index < len(self.states) and self.states[index] == "update":
            icon = _badged(icon)
        for row in range(self.list.count()):
            entry = self.list.item(row)
            if entry.data(QtCore.Qt.UserRole) == index:
                entry.setIcon(icon)

    def pickedIndex(self):
        """Where the one picked is in the list of items, None if none is."""
        entry = self.list.currentItem()
        if entry is None or not entry.isSelected():
            return None
        return entry.data(QtCore.Qt.UserRole)

    def picked(self):
        """The one picked, or None."""
        index = self.pickedIndex()
        return None if index is None else self.items[index]

    def done(self, result):
        # what is still being fetched comes to nothing
        self.loading += 1
        super().done(result)

    def showPicked(self):
        """What the one picked is, where it came from, its licence, and whether it is here."""
        index = self.pickedIndex()
        if index is None:
            if self.items:
                self.details.setText(
                    translate("CAM_AddVise", "Pick one to see what it is.")
                    if self.list.count()
                    else self.words["nomatch"]
                )
            self.get.setText(translate("CAM_AddVise", "Add"))
            self.get.setEnabled(False)
            return
        item = self.items[index]
        # the library's put in first: one here that is older, or a library's that differs here;
        # a library's already here as it has it, nothing to get
        updating = self.states[index] == "update" or (
            not self.local() and self.states[index] == "modified"
        )
        installed = not self.local() and self.states[index] == "current"
        self.get.setEnabled(not installed)
        self.get.setText(
            translate("CAM_AddVise", "Installed")
            if installed
            else (
                translate("CAM_AddVise", "Update") if updating else translate("CAM_AddVise", "Add")
            )
        )
        source = item.get("source", "")
        lines = ["<b>%s</b>" % item.get("label", item["id"])]
        made = "%s %s" % (item.get("maker", ""), item.get("model", ""))
        if made.strip():
            lines.append(made)
        if item.get("licence"):
            lines.append("%s: %s" % (translate("CAM_AddVise", "Licence"), item["licence"]))
        if item.get("attribution"):
            lines.append(item["attribution"])
        if source:
            lines.append("<a href='%s'>%s</a>" % (source, source))
        if item.get("path"):
            lines.append(item["path"])
        self.details.setText("<br>".join(lines))

    def otherFile(self):
        """One kept somewhere else, found by the user: chosen as it is if it is one."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.words["other"],
            PathLibrary.folder(self.kind),
            translate("CAM_AddVise", "FreeCAD document (*.FCStd)"),
        )
        if not path:
            return
        if PathLibrary.about(path).get("kind") != self.kind:
            QtWidgets.QMessageBox.warning(
                self,
                self.words["other"],
                translate("CAM_AddVise", "%s holds no %s.")
                % (
                    path,
                    (
                        translate("CAM_AddVise", "vise")
                        if self.kind == "vise"
                        else translate("CAM_AddVise", "clamp")
                    ),
                ),
            )
            return
        self.downloaded = path
        self.accept()

    def download(self):
        """The one picked chosen: one on this computer as it is; a library's saved where they
        are kept first, one already here used as it is, one changed here replaced only if the
        user says so."""
        index = self.pickedIndex()
        if index is None:
            return
        item = self.items[index]
        state = self.states[index]
        where = None
        if item.get("path"):
            if state != "update":
                self.downloaded = item["path"]
                self.accept()
                return
            # the library's newer one put in its place
            where = os.path.dirname(item["path"])
            item = self.updates[index]
        elif state == "current":
            self.downloaded = PathLibrary.localPath(item)
            self.accept()
            return
        if state == "modified":
            answer = QtWidgets.QMessageBox.question(
                self,
                self.words["update"],
                translate(
                    "CAM_AddVise",
                    "%s is here, changed from any the library has published. Replace it with "
                    "the library's?",
                )
                % PathLibrary.localPath(item),
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.downloaded = PathLibrary.download(item, where)
        except (OSError, ValueError) as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, self.words["title"], str(e))
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self.accept()


def getVise(parent=None):
    """getVise(parent=None) ... the path of a vise chosen, on this computer or from a library,
    downloaded; None if none was."""
    dialog = LibraryDialog(parent)
    if dialog.exec() == QtWidgets.QDialog.Accepted:
        return dialog.downloaded
    return None


def getClamp(parent=None):
    """getClamp(parent=None) ... the path of a clamp chosen, on this computer or from a library,
    downloaded; None if none was."""
    dialog = LibraryDialog(parent, kind="clamp")
    if dialog.exec() == QtWidgets.QDialog.Accepted:
        return dialog.downloaded
    return None
