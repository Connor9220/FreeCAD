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


"""The stops and clamps holding a Job's stock on the table, the sections of the workholding panel
that choose them."""

import os

import FreeCAD
import Path.Workholding.Vise as PathWorkholding
import Path.Workholding.Items as Items
import Path.Workholding.Lever as Lever
import Path.Workholding.Gui.Widgets as Widgets

from Path.Workholding.Constants import ERROR_TEXT_COLOR, LEVER_EDIT_DELAY, STOCK_DRAWING_COLOR
from Path.Workholding.Gui.Source import _closeIfUnused

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore, QtGui, QtWidgets

translate = FreeCAD.Qt.translate


def _bound(obj, name):
    """Whether an expression sets obj's property name."""
    return any(path == name for path, _ in getattr(obj, "ExpressionEngine", []))


def _pieceDrawing(piece, palette, width=330, height=130):
    """A drawing of a stop or clamp made here, its sizes named on it as the panel names them:
    from the front, facing the stock's side, its height, the stock behind it standing taller;
    and from above, along the stock across and front to back down, the stock's edge beyond it.
    Each view fills its half. None for any other."""
    kind = type(getattr(piece, "Proxy", None)).__name__
    if kind not in ("ObjectDog", "ObjectFence", "ObjectSideClamp", "ObjectEdgeClamp"):
        return None

    def v(name):
        return float(getattr(piece, name).Value)

    edge = kind == "ObjectEdgeClamp"
    if kind == "ObjectDog":
        wide, deep = ("Diameter", v("Diameter")), ("Diameter", v("Diameter"))
    elif kind == "ObjectFence":
        wide, deep = ("Length", v("Length")), ("Width", v("Width"))
    else:
        wide, deep = ("Width", v("Width")), ("Length", v("Length"))
    tall = v("Drop") + v("Rise") if edge else v("Height")
    reach = v("Reach") if edge else 0.0

    pixmap = QtGui.QPixmap(width, height)
    pixmap.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    ink = palette.color(QtGui.QPalette.Text)
    faint = palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
    dim = palette.color(QtGui.QPalette.Highlight).lighter(150)
    stockColor = QtGui.QColor(*STOCK_DRAWING_COLOR)
    body = palette.color(QtGui.QPalette.Mid)
    font = p.font()
    font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
    p.setFont(font)
    metrics = QtGui.QFontMetrics(font)
    textH = metrics.height()

    def text(x, y, words, color, center=True):
        w = metrics.horizontalAdvance(words)
        p.setPen(color)
        p.drawText(QtCore.QPointF(x - w / 2 if center else x, y), words)

    def across(x1, x2, y, words):
        # its name under the line
        p.setPen(QtGui.QPen(dim, 1))
        p.drawLine(QtCore.QPointF(x1, y), QtCore.QPointF(x2, y))
        for x in (x1, x2):
            p.drawLine(QtCore.QPointF(x, y - 3), QtCore.QPointF(x, y + 3))
        text((x1 + x2) / 2, y + metrics.ascent() + 2, words, dim)

    def up(x, y1, y2, words, right=False):
        p.setPen(QtGui.QPen(dim, 1))
        p.drawLine(QtCore.QPointF(x, y1), QtCore.QPointF(x, y2))
        for y in (y1, y2):
            p.drawLine(QtCore.QPointF(x - 3, y), QtCore.QPointF(x + 3, y))
        w = metrics.horizontalAdvance(words)
        tx = x + 5 if right else x - 5 - w
        text(tx, (y1 + y2) / 2 + metrics.ascent() / 2 - 1, words, dim, False)

    def fit(availW, wide, availH, tall):
        """The scales across and up a view fills its room by, the one no more than 2.5 times
        the other: a thin piece drawn thick enough to see."""
        sx, sy = availW / max(wide, 1e-6), availH / max(tall, 1e-6)
        return min(sx, sy * 2.5), min(sy, sx * 2.5)

    margin, band = 8, 10
    cellW = (width - 3 * margin) / 2
    cellTop = textH + 6
    cellH = height - cellTop - margin
    labelW = max(metrics.horizontalAdvance(n) for n in ("Height", "Drop", "Rise", deep[0])) + 10
    under = textH + 6

    # from the front: the stock behind, taller; the piece on the table before it
    x0 = margin
    text(x0 + cellW / 2, textH, translate("CAM_Workholding", "From the front"), faint)
    stockTall = v("Drop") if edge else tall * 1.5
    sx, sy = fit(cellW - labelW - 16, wide[1], cellH - under - 4, max(stockTall, tall))
    w, h, st = wide[1] * sx, tall * sy, stockTall * sy
    left = x0 + labelW + (cellW - labelW - w) / 2
    base = cellTop + (cellH - under + max(st, h)) / 2
    p.setPen(QtGui.QPen(faint, 1))
    p.setBrush(stockColor)
    p.drawRect(QtCore.QRectF(left - 8, base - st, w + 16, st))
    p.drawLine(QtCore.QPointF(left - 12, base), QtCore.QPointF(left + w + 12, base))
    p.setPen(QtGui.QPen(ink, 1))
    p.setBrush(body)
    if edge:
        p.drawRect(QtCore.QRectF(left, base - h, w, h))
        up(left - 14, base - st, base, "Drop")
        up(left + w + 14, base - h, base - st, "Rise", right=True)
    else:
        p.drawRect(QtCore.QRectF(left, base - h, w, h))
        up(left - 14, base - h, base, "Height")

    # from above: the stock's edge beyond, the piece against it, front to back down
    x0 = 2 * margin + cellW
    text(x0 + cellW / 2, textH, translate("CAM_Workholding", "From above"), faint)
    lipW = (metrics.horizontalAdvance("Reach") + 10) if edge else 0
    sx, sy = fit(cellW - labelW - lipW - 8, wide[1], cellH - band - under - 4, deep[1] + reach)
    if kind == "ObjectDog":
        # round, as it is
        sx = sy = min(sx, sy)
    w, d, r = wide[1] * sx, deep[1] * sy, reach * sy
    left = x0 + labelW + (cellW - labelW - lipW - w) / 2
    top = cellTop + (cellH - under - band - d) / 2
    edgeY = top + band
    p.setPen(QtGui.QPen(faint, 1))
    p.setBrush(stockColor)
    p.drawRect(QtCore.QRectF(left - 8, top, w + 16, band))
    p.setPen(QtGui.QPen(ink, 1))
    p.setBrush(body)
    if kind == "ObjectDog":
        p.drawEllipse(QtCore.QRectF(left, edgeY, w, d))
    else:
        p.drawRect(QtCore.QRectF(left, edgeY, w, d))
        if edge:
            p.drawRect(QtCore.QRectF(left, edgeY - r, w, r))
            up(left + w + 6, edgeY - r, edgeY, "Reach", right=True)
    if kind != "ObjectDog":
        up(left - 6, edgeY, edgeY + d, deep[0])
    across(left, left + w, edgeY + d + 4, wide[0])
    p.end()
    return pixmap


class _StopsClamps:
    """The stops and clamps holding a Job's stock on the table, three sections of the panel: the
    stops, on one side of the stock or on two next to each other, a corner; the clamps, a kind
    and how many on each side; and those placed, each picked out, nudged along its side or taken
    away. Each change put in the document a moment after it, into the panel's pending step."""

    def __init__(self, panel, ui):
        self.panel = panel
        self.job = panel.job
        self.ui = ui
        self.loading = False
        self.names = {direction: label for label, direction in Widgets.sides()}
        # the documents open before: a clamp's file opened here is closed again if unused
        self.open = set(FreeCAD.listDocuments())
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.preview)
        # the clamps' files the Job uses, and those chosen since: (name, path, kind)
        self.files = []
        for spec in Items.clampsOf(self.job):
            which = spec.get("which")
            if which and which not in ("SideClamp", "EdgeClamp"):
                clamp = Items.clampFile(which)
                if clamp is not None and all(p != which for _, p, _ in self.files):
                    self.files.append((self._clampName(which, clamp[0]), which, clamp[1]))
        sections = []
        for title, icon in (
            (translate("CAM_Workholding", "Stops"), Widgets.themedIcon(":/icons/xy-in-stock.svg")),
            (translate("CAM_Workholding", "Clamps"), QtGui.QIcon(":/icons/CAM_Job.svg")),
            (translate("CAM_Workholding", "Placed"), QtGui.QIcon(":/icons/Std_Placement.svg")),
        ):
            section = QtWidgets.QWidget()
            section.setWindowTitle(title)
            section.setWindowIcon(icon)
            sections.append((section, QtWidgets.QFormLayout(section)))
        self.forms = [section for section, _ in sections]
        self.layouts = [layout for _, layout in sections]

        # the stops: a side of the part, what stands against it and how many, spread along it; a
        # second side next to the first, a corner
        layout = self.layouts[0]
        self.stopRows = []
        for label in (
            translate("CAM_Workholding", "First stop"),
            translate("CAM_Workholding", "Second stop"),
        ):
            side = Widgets.combo()
            side.setToolTip(translate("CAM_Workholding", "The side of the part against the stops"))
            kind = Widgets.combo(wide=True)
            kind.setToolTip(
                translate(
                    "CAM_Workholding",
                    "A dog in the table, a fence along the side, or another Job's stop",
                )
            )
            count = QtWidgets.QSpinBox()
            count.setRange(1, 6)
            count.setToolTip(translate("CAM_Workholding", "How many along the side"))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(side, 2)
            row.addWidget(kind, 3)
            row.addWidget(count)
            layout.addRow(label, row)
            self.stopRows.append({"side": side, "kind": kind, "count": count})
        self.shared = Widgets.Note()
        layout.addRow("", self.shared)
        self.error = Widgets.Note()
        self.error.setStyleSheet("color: %s" % ERROR_TEXT_COLOR)
        layout.addRow("", self.error)

        # the clamps: a kind on each side, how many, spread along it
        layout = self.layouts[1]
        self.clampRows = []
        for i in range(4):
            label = QtWidgets.QLabel()
            kind = Widgets.combo(wide=True)
            kind.setToolTip(
                translate(
                    "CAM_Workholding",
                    "A side clamp pushing the part onto the stops, or a hold-down over its top edge",
                )
            )
            count = QtWidgets.QSpinBox()
            count.setRange(1, 12)
            count.setToolTip(translate("CAM_Workholding", "How many along the side"))
            browse = Widgets.browseButton(
                translate("CAM_Workholding", "Choose a clamp on this computer or from a library")
            )
            row = QtWidgets.QHBoxLayout()
            row.addWidget(kind, 1)
            row.addWidget(browse)
            row.addWidget(count)
            layout.addRow(label, row)
            entry = {"label": label, "kind": kind, "count": count, "side": None, "browse": browse}
            self.clampRows.append(entry)
            browse.clicked.connect(lambda checked=False, entry=entry: self.browseClamp(entry))
            self.fillClampKinds(kind)
        self.clampNote = Widgets.Note()
        layout.addRow("", self.clampNote)

        # those placed: picked out in the 3D view too, put where it goes along its side and kept
        # there, taken away
        layout = self.layouts[2]
        self.list = QtWidgets.QListWidget()
        self.list.setToolTip(translate("CAM_Workholding", "The Job's stops, clamps and table"))
        self.list.setFixedHeight(5 * self.list.fontMetrics().height() + 12)
        layout.addRow(self.list)
        self.offset = Widgets.mmBox(
            self.ui,
            translate(
                "CAM_Workholding",
                "Where the one picked is along its side, from the Job's origin: its X on the front "
                "or back, its Y on the left or right",
            ),
            minimum=-10000.0,
        )
        self.remove = QtWidgets.QPushButton(translate("CAM_Workholding", "Remove"))
        self.remove.setToolTip(translate("CAM_Workholding", "Take the one picked away"))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.offset, 1)
        row.addWidget(self.remove)
        layout.addRow(translate("CAM_Workholding", "Position"), row)
        self.positionLabel = layout.labelForField(row)
        # a lever clamp picked: where it presses and how it stands, in place of where it is along
        # its side
        self.leverRows = []
        self.pressX = Widgets.mmBox(
            self.ui,
            translate("CAM_Workholding", "Where it presses on the stock, the Job's X"),
            minimum=-10000.0,
        )
        self.pressY = Widgets.mmBox(
            self.ui,
            translate("CAM_Workholding", "Where it presses on the stock, the Job's Y"),
            minimum=-10000.0,
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("X"))
        row.addWidget(self.pressX, 1)
        row.addWidget(QtWidgets.QLabel("Y"))
        row.addWidget(self.pressY, 1)
        self._leverRow(layout, translate("CAM_Workholding", "Presses at"), row)
        self.angle = self.ui.createWidget("Gui::QuantitySpinBox")
        self.angle.setProperty("unit", "deg")
        self.angle.setProperty("minimum", -180.0)
        self.angle.setProperty("maximum", 180.0)
        self.angle.setToolTip(
            translate(
                "CAM_Workholding",
                "Its angle round where it presses, seen from above: 0 square to the stock's side",
            )
        )
        self.presses = Widgets.combo()
        self.presses.addItem(translate("CAM_Workholding", "Toe presses"), "Toe")
        self.presses.addItem(translate("CAM_Workholding", "Heel presses"), "Heel")
        self.presses.setToolTip(
            translate(
                "CAM_Workholding",
                "The end pressing on the stock: its toe, or its heel for thin stock",
            )
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.angle, 1)
        row.addWidget(self.presses, 1)
        self._leverRow(layout, translate("CAM_Workholding", "Angle"), row)
        self.leverClamp = Widgets.combo(wide=True)
        self.leverClamp.setToolTip(
            translate("CAM_Workholding", "Its step clamp, of those in the kit")
        )
        self._leverRow(layout, translate("CAM_Workholding", "Clamp"), self.leverClamp)
        self.restsOn = Widgets.combo()
        self.restsOn.setToolTip(
            translate(
                "CAM_Workholding",
                "What its other end rests on: a step block, a step block on a riser, a riser or the table",
            )
        )
        self.block = Widgets.combo(wide=True)
        self.block.setToolTip(
            translate(
                "CAM_Workholding",
                "Its step block: Auto, the one bringing its heel level, or one of the kit's",
            )
        )
        self.riser = Widgets.mmBox(
            self.ui,
            translate("CAM_Workholding", "How thick the riser under its other end is"),
            minimum=0.0,
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.restsOn, 1)
        row.addWidget(self.block, 1)
        row.addWidget(self.riser, 1)
        self._leverRow(layout, translate("CAM_Workholding", "Rests on"), row)
        self.boltFit = QtWidgets.QCheckBox(translate("CAM_Workholding", "Cut to fit"))
        self.boltFit.setToolTip(
            translate(
                "CAM_Workholding",
                "Cut its bolt to the shortest that clears what is on it, in quarter-inch steps",
            )
        )
        self.boltLength = Widgets.mmBox(
            self.ui,
            translate("CAM_Workholding", "How long its bolt is cut to; 0 as shipped"),
            minimum=0.0,
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.boltFit)
        row.addWidget(self.boltLength, 1)
        self._leverRow(layout, translate("CAM_Workholding", "Bolt"), row)
        # a kit's step clamp: where its bolt is in its slot
        self.boltAuto = QtWidgets.QCheckBox(translate("CAM_Workholding", "Auto"))
        self.boltAuto.setToolTip(
            translate(
                "CAM_Workholding",
                "Its bolt as near the stock as its slot lets it, the stud clear of the stock",
            )
        )
        self.boltAt = Widgets.mmBox(
            self.ui,
            translate(
                "CAM_Workholding",
                "How far its bolt is from the end pressing on the stock, along the clamp, within "
                "its slot",
            ),
            minimum=0.0,
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.boltAuto)
        row.addWidget(self.boltAt, 1)
        self._leverRow(layout, translate("CAM_Workholding", "Bolt at"), row)
        self.leverFound = Widgets.Note()
        self._leverRow(layout, "", self.leverFound)
        self.leverNote = Widgets.Note()
        self.leverNote.setStyleSheet("color: %s" % ERROR_TEXT_COLOR)
        self._leverRow(layout, "", self.leverNote)
        # the one picked's size, the others of its kind on its side with it; a picture of it,
        # its drawing or a clamp's own thumbnail
        self.sizes = QtWidgets.QWidget()
        self.sizeGrid = QtWidgets.QGridLayout(self.sizes)
        self.sizeGrid.setContentsMargins(0, 0, 0, 0)
        self.sizeBoxes = {}
        layout.addRow(translate("CAM_Workholding", "Size"), self.sizes)
        self.sameSide = QtWidgets.QCheckBox(
            translate("CAM_Workholding", "The others on its side too")
        )
        self.sameSide.setToolTip(
            translate("CAM_Workholding", "Its size given to the others of its kind on its side")
        )
        self.sameSide.setChecked(True)
        layout.addRow("", self.sameSide)
        self.picture = QtWidgets.QLabel()
        self.picture.setAlignment(QtCore.Qt.AlignCenter)
        layout.addRow(self.picture)

        # under it all, the table: in the Stock section
        self.table = QtWidgets.QPushButton(translate("CAM_Workholding", "Put a table under it"))
        self.table.setToolTip(
            translate(
                "CAM_Workholding",
                "A spoilboard with T-track rails and dog holes, and the waste board the stock "
                "lies on, shown but never hit",
            )
        )

        for i, row in enumerate(self.stopRows):
            row["side"].currentIndexChanged.connect(self.stopSideChanged)
            row["kind"].currentIndexChanged.connect(self.stopKindChanged)
            row["count"].valueChanged.connect(self.changed)
        for row in self.clampRows:
            row["kind"].currentIndexChanged.connect(
                lambda index, row=row: self.clampKindChanged(row, index)
            )
            row["count"].valueChanged.connect(self.changed)
        self.list.currentRowChanged.connect(self.picked)
        self.offset.valueChanged.connect(self.nudged)
        # a number turned with the wheel placed once it stops, not at every click
        self.leverPending = {}
        self.leverTimer = QtCore.QTimer()
        self.leverTimer.setSingleShot(True)
        self.leverTimer.setInterval(LEVER_EDIT_DELAY)
        self.leverTimer.timeout.connect(self.applyLever)
        self.pressX.valueChanged.connect(lambda *args: self.later("Press", None))
        self.pressY.valueChanged.connect(lambda *args: self.later("Press", None))
        self.angle.valueChanged.connect(
            lambda *args: self.later("Angle", self.angle.property("rawValue"))
        )
        self.presses.currentIndexChanged.connect(
            lambda *args: self.setLever("Presses", self.presses.currentData())
        )
        self.leverClamp.currentIndexChanged.connect(
            lambda *args: self.setLever("Clamp", self.leverClamp.currentData())
        )
        self.restsOn.currentIndexChanged.connect(
            lambda *args: self.setLever("RestsOn", self.restsOn.currentData())
        )
        self.block.currentIndexChanged.connect(
            lambda *args: self.setLever("Block", self.block.currentData())
        )
        self.riser.valueChanged.connect(
            lambda *args: self.later("RiserThickness", self.riser.property("rawValue"))
        )
        self.boltFit.toggled.connect(lambda checked: self.setLever("BoltFit", checked))
        self.boltAuto.toggled.connect(self.boltAutoToggled)
        self.boltAt.valueChanged.connect(
            lambda *args: self.later("BoltAt", self.boltAt.property("rawValue"))
        )
        self.boltLength.valueChanged.connect(
            lambda *args: self.later("BoltLength", self.boltLength.property("rawValue"))
        )
        self.remove.clicked.connect(self.removeChosen)
        self.table.clicked.connect(self.addTable)

    def _leverRow(self, layout, label, field):
        """A row of the Placed section shown only while a lever clamp is picked."""
        if isinstance(field, QtWidgets.QLayout):
            holder = QtWidgets.QWidget()
            field.setContentsMargins(0, 0, 0, 0)
            holder.setLayout(field)
            field = holder
        layout.addRow(label, field)
        self.leverRows.append(field)

    def changed(self, *args):
        """Something the panel says changed: put in a moment after, not as it is read in."""
        if not self.loading:
            self.timer.start()

    # what the panel says

    def chosenStops(self):
        """The stops the panel says, as setStops takes them."""
        stops = []
        for row in self.stopRows:
            side = row["side"].currentData()
            kind = row["kind"].currentData()
            if side is None or kind is None:
                continue
            if isinstance(kind, (tuple, list)):
                owner = self.job.Document.getObject(kind[1])
                if owner is not None:
                    stops.append({"side": side, "share": owner})
                continue
            stops.append({"side": side, "which": kind, "count": row["count"].value()})
        return stops

    def chosenClamps(self):
        """The clamps the panel says, as setClamps takes them."""
        return [
            {
                "side": row["side"],
                "which": row["kind"].currentData(),
                "count": row["count"].value(),
            }
            for row in self.clampRows
            if row["side"] is not None and row["kind"].currentData() is not None
        ]

    def stopSides(self):
        return [r["side"].currentData() for r in self.stopRows if r["side"].currentData()]

    # rows following one another

    def stopSideChanged(self, *args):
        """A side chosen for the stops: the second only next to the first; the clamps' kinds as
        the stops' sides allow."""
        if not self.loading:
            self.fillSecondSide()
            self.updateRows()
        self.changed()

    def fillSecondSide(self):
        """The sides the second stops can go on, next to the first's, the one chosen kept if it
        still can."""
        first = self.stopRows[0]["side"].currentData()
        combo = self.stopRows[1]["side"]
        keep = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(translate("CAM_Workholding", "None"), None)
        for side in Items.sides(self.job) if first else []:
            if Items.adjacent(first, side):
                combo.addItem(self.names.get(side, side), side)
        combo.setCurrentIndex(max(0, combo.findData(keep)))
        combo.blockSignals(False)

    def stopKindChanged(self, *args):
        if not self.loading:
            self.updateRows()
        self.changed()

    def clampKindChanged(self, row, index):
        """A clamp's file chosen in a document not saved: refused, its parts are linked. One got
        from a library or found elsewhere: added to the rows' lists and chosen."""
        path = row["kind"].currentData()
        if (
            not self.loading
            and path not in (None, "SideClamp", "EdgeClamp")
            and not self.job.Document.FileName
        ):
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(),
                translate("CAM_Workholding", "Clamps"),
                translate(
                    "CAM_Workholding",
                    "Save the document first: the clamp's parts are linked from its own file.",
                ),
            )
            row["kind"].blockSignals(True)
            row["kind"].setCurrentIndex(row.get("last", 0))
            row["kind"].blockSignals(False)
            return
        row["last"] = row["kind"].currentIndex()
        if not self.loading:
            self.updateRows()
        self.changed()

    @staticmethod
    def _clampName(path, name):
        """A clamp's file's name to show: its label, as it says, else its file's name."""
        import Path.Workholding.Library as PathLibrary

        return PathLibrary.about(path).get("label") or name

    def fillClampKinds(self, combo):
        """A clamp row's list: none, the clamps made here, the clamps' files the Job uses and
        those chosen since; what was chosen kept."""
        keep = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(translate("CAM_Workholding", "None"), None)
        combo.addItem(translate("CAM_Workholding", "Side clamp"), "SideClamp")
        combo.addItem(translate("CAM_Workholding", "Edge clamp"), "EdgeClamp")
        for name, path, _ in self.files:
            combo.addItem(name, path)
        combo.setCurrentIndex(max(0, combo.findData(keep)) if keep is not None else 0)
        combo.blockSignals(False)
        Widgets.fitList(combo)

    def browseClamp(self, row):
        """A clamp chosen in the browser, on this computer or from a library, put on the row's
        side; in a document not saved, refused first: its parts are linked."""
        if not self.job.Document.FileName:
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(),
                translate("CAM_Workholding", "Clamps"),
                translate(
                    "CAM_Workholding",
                    "Save the document first: the clamp's parts are linked from its own file.",
                ),
            )
            return
        import Path.Workholding.Gui.Library as LibraryGui

        path = LibraryGui.getClamp()
        index = self.addClampFile(path) if path else None
        if index is not None and index >= 0:
            row["kind"].setCurrentIndex(index)

    def addClampFile(self, path):
        """A clamp's file put in every row's list if it is not there: its place in the lists,
        None if it holds no clamp."""
        for _, known, _ in self.files:
            if os.path.exists(known) and os.path.samefile(known, path):
                return self.clampRows[0]["kind"].findData(known)
        clamp = Items.clampFile(path)
        if clamp is None:
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(),
                translate("CAM_Workholding", "Clamps"),
                translate("CAM_Workholding", "%s holds no clamp.") % os.path.basename(path),
            )
            return None
        self.files.append((self._clampName(path, clamp[0]), path, clamp[1]))
        for row in self.clampRows:
            self.fillClampKinds(row["kind"])
            row["last"] = row["kind"].currentIndex()
        return self.clampRows[0]["kind"].findData(path)

    def updateRows(self):
        """Each row's fields open as its choices say: a side with no stops, or none, nothing more
        to say; a shared stop one, its spread its Job's; no side clamp where the stops are."""
        for i, row in enumerate(self.stopRows):
            side = row["side"].currentData()
            kind = row["kind"].currentData()
            share = isinstance(kind, (tuple, list))
            row["side"].setEnabled(i == 0 or self.stopRows[0]["side"].currentData() is not None)
            row["kind"].setEnabled(side is not None)
            row["count"].setEnabled(side is not None and not share)
            if share:
                row["count"].blockSignals(True)
                row["count"].setValue(1)
                row["count"].blockSignals(False)
        stopSides = self.stopSides()
        taken = []
        for row in self.clampRows:
            combo = row["kind"]
            for index in range(combo.count()):
                which = combo.itemData(index)
                if which is None:
                    continue
                pushes = which == "SideClamp" or any(
                    p == which and k == Items.Kind.Push for _, p, k in self.files
                )
                combo.model().item(index).setEnabled(not (pushes and row["side"] in stopSides))
            if not combo.model().item(combo.currentIndex()).isEnabled():
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
                taken.append(self.names.get(row["side"], row["side"]))
            which = combo.currentData()
            row["count"].setEnabled(which is not None)
        self.clampNote.setText(
            translate(
                "CAM_Workholding", "No side clamp on the %s: it would push the part off the stops"
            )
            % ", ".join(taken)
            if taken
            else ""
        )

    # read in from the Job

    def readIn(self):
        """The rows as the Job's stops and clamps are, read from them: the panel shows what the
        document has."""
        self.loading = True
        try:
            self.readStops()
            self.readClamps()
            self.updateRows()
        finally:
            self.loading = False
        self.fillList()

    def readStops(self):
        standing = Items.sides(self.job)
        stops = Items.stopsOf(self.job)
        first = self.stopRows[0]["side"]
        first.clear()
        first.addItem(translate("CAM_Workholding", "None"), None)
        for side in standing:
            first.addItem(self.names.get(side, side), side)
        first.setCurrentIndex(max(0, first.findData(stops[0]["side"] if stops else None)))
        self.fillSecondSide()
        second = self.stopRows[1]["side"]
        second.setCurrentIndex(
            max(0, second.findData(stops[1]["side"] if len(stops) > 1 else None))
        )
        notes = []
        for i, row in enumerate(self.stopRows):
            spec = stops[i] if i < len(stops) else {}
            kind = row["kind"]
            kind.clear()
            kind.addItem(translate("CAM_Workholding", "Dog"), "Dog")
            kind.addItem(translate("CAM_Workholding", "Fence"), "Fence")
            # another Job's stop, shared: this one's own on its other face
            owners = Items.shareableStops(self.job)
            if spec.get("share") is not None and spec["share"] not in owners:
                owners.insert(0, spec["share"])
            for owner in owners:
                kind.addItem(
                    translate("CAM_Workholding", "%s, in %s")
                    % (owner.Label, PathWorkholding.memberOf(owner)[0].Label),
                    ("share", owner.Name),
                )
            Widgets.fitList(kind)
            if spec.get("share") is not None:
                kind.setCurrentIndex(max(0, kind.findData(("share", spec["share"].Name))))
            else:
                kind.setCurrentIndex(max(0, kind.findData(spec.get("which", "Dog"))))
            # three two one: two on the first side, one on the second
            row["count"].setValue(spec.get("count", 2 if i == 0 else 1))
            for job in spec.get("sharedWith", []):
                notes.append(
                    translate(
                        "CAM_Workholding", "Shared with %s: its stops stay, the part moves to them"
                    )
                    % job.Label
                )
        self.shared.setText("\n".join(notes))

    def readClamps(self):
        standing = Items.sides(self.job)
        clamps = {spec["side"]: spec for spec in Items.clampsOf(self.job)}
        for i, row in enumerate(self.clampRows):
            side = standing[i] if i < len(standing) else None
            row["side"] = side
            row["label"].setText(self.names.get(side, side) if side else "")
            for widget in (row["label"], row["kind"], row["count"]):
                widget.setVisible(side is not None)
            spec = clamps.get(side, {})
            kind = row["kind"]
            which = spec.get("which")
            index = kind.findData(which) if which else 0
            if index < 0:
                # a clamp's file found elsewhere than the folder now
                self.files.append(
                    (os.path.splitext(os.path.basename(which))[0].replace("_", " "), which, None)
                )
                for each in self.clampRows:
                    self.fillClampKinds(each["kind"])
                index = kind.findData(which)
            kind.setCurrentIndex(index)
            row["last"] = index
            row["count"].setValue(spec.get("count", 2))

    # those placed

    def fillList(self, pick=None):
        """The Job's stops, clamps and table listed, the one picked kept."""
        keep = pick or self.chosen()
        keep = keep.Name if keep is not None else None
        pieces = Items.stopsOn(self.job) + Items.clampsOn(self.job)
        pieces += [o for o in Items.itemsOf(self.job) if o not in pieces]
        self.list.blockSignals(True)
        self.list.clear()
        for piece in pieces:
            side = getattr(piece, "StockSide", "")
            text = piece.Label
            if side:
                text = "%s: %s" % (self.names.get(side, side), piece.Label)
            if PathWorkholding.isShared(piece):
                text += " " + translate("CAM_Workholding", "(shared)")
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, piece.Name)
            self.list.addItem(item)
            if piece.Name == keep:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.showChosen()

    def chosen(self):
        """The piece picked in the list, None if none."""
        item = self.list.currentItem()
        if item is None:
            return None
        return self.job.Document.getObject(item.data(QtCore.Qt.UserRole))

    def picked(self, *args):
        """A piece picked: picked in the 3D view too."""
        piece = self.chosen()
        FreeCADGui.Selection.clearSelection()
        if piece is not None:
            FreeCADGui.Selection.addSelection(piece)
        self.showChosen()

    def showChosen(self):
        """Where the piece picked is along its side, as the Job's X or Y; one shared stays where
        it is, and only one placed by side has a place to show."""
        piece = self.chosen()
        placed = piece is not None and Items.isPlaced(piece)
        self.offset.blockSignals(True)
        self.offset.setProperty("rawValue", Items.positionOf(piece) if placed else 0.0)
        self.offset.blockSignals(False)
        self.offset.setEnabled(placed and not PathWorkholding.isShared(piece))
        self.remove.setEnabled(piece is not None)
        # a lever clamp is placed where it presses, not along its side
        lever = Lever.isLever(piece)
        self.offset.setVisible(not lever)
        if self.positionLabel is not None:
            self.positionLabel.setVisible(not lever)
        self.showLever(piece if lever else None)
        self.showSize(piece)

    def showLever(self, piece):
        """The lever clamp picked: where it presses, how it stands and what placing it found; the
        rows gone when none is. Edits not yet put in are dropped."""
        self.leverTimer.stop()
        self.leverPending = {}
        form = self.layouts[2]
        for field in self.leverRows:
            field.setVisible(piece is not None)
            label = form.labelForField(field)
            if label is not None:
                label.setVisible(piece is not None)
        if piece is None:
            return
        kit = hasattr(piece, "Clamp")
        widgets = (
            self.pressX,
            self.pressY,
            self.angle,
            self.presses,
            self.leverClamp,
            self.restsOn,
            self.block,
            self.riser,
            self.boltFit,
            self.boltLength,
            self.boltAuto,
            self.boltAt,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            x, y = Lever.pressOf(self.job, piece)
            self.pressX.setProperty("rawValue", x)
            self.pressY.setProperty("rawValue", y)
            self.angle.setProperty("rawValue", piece.Angle.Value)
            self.presses.setCurrentIndex(max(0, self.presses.findData(piece.Presses)))
            self.leverClamp.clear()
            if kit:
                for label in piece.getEnumerationsOfProperty("Clamp"):
                    self.leverClamp.addItem(label, label)
                self.leverClamp.setCurrentIndex(max(0, self.leverClamp.findData(piece.Clamp)))
                Widgets.fitList(self.leverClamp)
            self.restsOn.clear()
            names = {
                "StepBlock": translate("CAM_Workholding", "Step block"),
                "RiserAndStepBlock": translate("CAM_Workholding", "Riser and step block"),
                "Riser": translate("CAM_Workholding", "Riser"),
                "Table": translate("CAM_Workholding", "Table"),
            }
            for value in piece.getEnumerationsOfProperty("RestsOn"):
                self.restsOn.addItem(names.get(value, value), value)
            self.restsOn.setCurrentIndex(max(0, self.restsOn.findData(piece.RestsOn)))
            self.block.clear()
            if kit:
                for label in piece.getEnumerationsOfProperty("Block"):
                    shown = translate("CAM_Workholding", "Auto") if label == Lever.Auto else label
                    self.block.addItem(shown, label)
                self.block.setCurrentIndex(max(0, self.block.findData(piece.Block)))
                Widgets.fitList(self.block)
            self.riser.setProperty("rawValue", piece.RiserThickness.Value)
            if hasattr(piece, "BoltAt"):
                # no further than its slot runs
                slot = Lever.boltRange(piece)
                if slot is not None:
                    self.boltAt.setProperty("minimum", slot[0])
                    self.boltAt.setProperty("maximum", slot[1])
                auto = piece.BoltAt.Value <= 0
                self.boltAuto.setChecked(auto)
                self.boltAt.setProperty(
                    "rawValue", piece.BoltFound.Value if auto else piece.BoltAt.Value
                )
            bolt = hasattr(piece, "BoltFit")
            if bolt:
                self.boltFit.setChecked(piece.BoltFit)
                self.boltLength.setProperty("rawValue", piece.BoltLength.Value)
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.leverClamp.setVisible(kit)
        bolt = hasattr(piece, "BoltFit")
        holder = self.boltFit.parentWidget()
        holder.setVisible(bolt)
        label = form.labelForField(holder)
        if label is not None:
            label.setVisible(bolt)
        self.boltLength.setEnabled(bolt and not piece.BoltFit)
        slot = hasattr(piece, "BoltAt")
        holder = self.boltAuto.parentWidget()
        holder.setVisible(slot)
        label = form.labelForField(holder)
        if label is not None:
            label.setVisible(slot)
        self.boltAt.setEnabled(slot and piece.BoltAt.Value > 0)
        label = form.labelForField(self.leverClamp)
        if label is not None:
            label.setVisible(kit)
        self.block.setVisible(kit and piece.RestsOn in ("StepBlock", "RiserAndStepBlock"))
        self.riser.setVisible(piece.RestsOn in ("Riser", "RiserAndStepBlock"))
        found = [translate("CAM_Workholding", "On %s") % piece.Support] if piece.Support else []
        found.append(translate("CAM_Workholding", "tilted %.1f°") % piece.Tilt.Value)
        if getattr(piece, "Stud", ""):
            found.append(piece.Stud)
        if bolt and piece.BoltLength.Value > 0:
            found.append(
                translate("CAM_Workholding", "its bolt %s long") % piece.BoltLength.UserString
            )
        self.leverFound.setText(", ".join(found))
        self.leverNote.setText(piece.Note)

    def later(self, name, value):
        """A number of the lever clamp picked changed: put in once the edits stop coming."""
        self.leverPending[name] = value
        self.leverTimer.start()

    def applyLever(self):
        """The numbers changed since the edits stopped put in, the clamp placed again."""
        pending, self.leverPending = self.leverPending, {}
        for name, value in pending.items():
            if name == "Press":
                self.pressMoved()
            else:
                self.setLever(name, value)

    def setLever(self, name, value):
        """A setting of the lever clamp picked changed: it is placed again."""
        piece = self.chosen()
        if not Lever.isLever(piece) or value is None or not hasattr(piece, name):
            return
        current = getattr(piece, name)
        if getattr(current, "Value", current) == value:
            return
        self.panel.begin()
        try:
            setattr(piece, name, value)
        except ValueError as e:
            self.leverNote.setText(str(e))
            return
        self.showLever(piece)

    def boltAutoToggled(self, auto):
        """Its bolt put as near the stock as clears it, or kept where it now is, to set."""
        piece = self.chosen()
        if not hasattr(piece, "BoltAt"):
            return
        self.setLever("BoltAt", 0.0 if auto else max(piece.BoltFound.Value, 1e-3))

    def pressMoved(self, *args):
        """The lever clamp picked put where X and Y say it presses, and kept there."""
        piece = self.chosen()
        if not Lever.isLever(piece):
            return
        self.panel.begin()
        Lever.setPress(
            self.job, piece, self.pressX.property("rawValue"), self.pressY.property("rawValue")
        )
        self.showLever(piece)

    def sizeNames(self, piece):
        """The sizes of a piece made here, as it has them; none of a clamp from its own file."""
        if piece is None or isinstance(
            getattr(piece, "Proxy", None), (Items.ObjectClamp, Lever.ObjectLever)
        ):
            return []
        names = [
            name
            for name in piece.PropertiesList
            if piece.getGroupOfProperty(name) == "Workholding"
            and piece.getTypeIdOfProperty(name) == "App::PropertyLength"
            and "Hidden" not in piece.getEditorMode(name)
        ]
        # side to side along the stock, front to back, then up
        order = {"ObjectFence": ["Length", "Width"]}.get(
            type(piece.Proxy).__name__, ["Diameter", "Width", "Length"]
        )
        order += ["Reach", "Rise", "Drop", "Height"]
        return sorted(names, key=lambda n: order.index(n) if n in order else len(order))

    def others(self, piece):
        """The others of its kind on the piece's side."""
        side = getattr(piece, "StockSide", "")
        if not side:
            return []
        same = Items.stopsOn(self.job, side) + Items.clampsOn(self.job, side)
        return [o for o in same if o != piece and getattr(o, "Source", None) == piece.Source]

    def showSize(self, piece):
        """The piece's sizes to change, unless it follows another Job's; its picture."""
        while self.sizeGrid.count():
            widget = self.sizeGrid.takeAt(0).widget()
            if widget is not None:
                # gone at once, not once the event loop comes round
                widget.setParent(None)
                widget.deleteLater()
        self.sizeBoxes = {}
        names = self.sizeNames(piece)
        fixed = piece is not None and PathWorkholding.isShared(piece)
        for i, name in enumerate(names):
            box = Widgets.mmBox(self.ui, piece.getDocumentationOfProperty(name))
            box.setProperty("rawValue", getattr(piece, name).Value)
            box.setEnabled(not fixed and not _bound(piece, name))
            box.valueChanged.connect(lambda *args, name=name: self.resized(name))
            self.sizeGrid.addWidget(
                QtWidgets.QLabel(translate("App::Property", name)), i // 2, (i % 2) * 2
            )
            self.sizeGrid.addWidget(box, i // 2, (i % 2) * 2 + 1)
            self.sizeBoxes[name] = box
        form = self.layouts[2]
        for widget in (self.sizes, form.labelForField(self.sizes)):
            widget.setVisible(bool(names))
        self.sameSide.setVisible(bool(names) and not fixed and bool(self.others(piece)))
        self.showPicture(piece)

    def showPicture(self, piece):
        """The picked one's picture: its drawing as it is now, or a clamp's own thumbnail."""
        pixmap = None
        if piece is not None:
            pixmap = _pieceDrawing(piece, self.picture.palette())
            source = getattr(piece, "Source", "")
            if pixmap is None and source and os.path.isfile(source):
                import Path.Workholding.Library as PathLibrary

                data = PathLibrary.thumbnail(source)
                if data:
                    pixmap = QtGui.QPixmap()
                    pixmap.loadFromData(data)
                    pixmap = pixmap.scaled(
                        160, 160, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                    )
        self.picture.setPixmap(pixmap if pixmap is not None else QtGui.QPixmap())
        self.picture.setVisible(pixmap is not None)

    def resized(self, name):
        """A size of the piece picked changed, and the others' of its kind on its side with it."""
        piece = self.chosen()
        box = self.sizeBoxes.get(name)
        if piece is None or box is None or PathWorkholding.isShared(piece):
            return
        value = box.property("rawValue")
        if value <= 0:
            return
        self.panel.begin()
        pieces = [piece] + (self.others(piece) if self.sameSide.isChecked() else [])
        for each in pieces:
            if not _bound(each, name):
                setattr(each, name, value)
        self.showPicture(piece)
        self.timer.start()

    def nudged(self, *args):
        """The piece picked put where its X or Y says, and kept there."""
        piece = self.chosen()
        if piece is None or not Items.isPlaced(piece) or PathWorkholding.isShared(piece):
            return
        self.panel.begin()
        Items.setPosition(piece, self.offset.property("rawValue"))
        self.timer.start()

    def removeChosen(self):
        """The piece picked taken away, the rows as the Job now has them."""
        piece = self.chosen()
        if piece is None:
            return
        self.timer.stop()
        self.panel.begin()
        FreeCADGui.Selection.clearSelection()
        Items.removePiece(piece)
        self.readIn()

    def addTable(self):
        """The table under the stock: put in, or placed under it again."""
        self.panel.begin()
        table = Items.addTable(self.job)
        self.fillList(table)

    def preview(self):
        """The stops and clamps put in as the panel says, pending: True if they could be."""
        self.timer.stop()
        self.panel.begin()
        try:
            Items.setStops(self.job, self.chosenStops())
            Items.setClamps(self.job, self.chosenClamps())
        except ValueError as e:
            self.error.setText(str(e))
            self.fillList()
            return False
        self.error.setText("")
        self.fillList()
        return True

    def finish(self):
        """A clamp's file opened for the panel closed again if nothing links to it now."""
        self.timer.stop()
        for name, doc in list(FreeCAD.listDocuments().items()):
            if name not in self.open and Items.clampIn(doc) is not None:
                _closeIfUnused(doc)
        if self.job.Document.Name in FreeCAD.listDocuments():
            FreeCADGui.setActiveDocument(self.job.Document.Name)
