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
import Path.Workholding.Gui.ViewProvider as ViewProviders
import Path.Workholding.Gui.Widgets as Widgets

from Path.Workholding.Constants import (
    DRAG_SHOW_EVERY,
    ERROR_TEXT_COLOR,
    LEVER_EDIT_DELAY,
    STOCK_DRAWING_COLOR,
    TRANSFORM_NO_DIALOG,
)
from Path.Workholding.Gui.Source import _closeIfUnused

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore, QtGui, QtWidgets

translate = FreeCAD.Qt.translate


# sizes of a stop or clamp each keeps its own, not given to the others on its side: how tall
OWN_SIZES = ("Height", "Rise")


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


def _degrees(value):
    """An angle as the table shows it, a tenth of a degree; a hair below 0 is 0.0, not -0.0."""
    return "%.1f°" % (round(value, 1) + 0.0)


def _length(value):
    """A length as the user's units show it."""
    return FreeCAD.Units.Quantity(round(value, 6) + 0.0, FreeCAD.Units.Length).UserString


class _StopsClamps:
    """The stops and clamps holding a Job's stock on the table, two sections of the panel: one row
    adding them, a side of the part, what to put there and how many, spread along it; and those
    placed, listed by the edge each is at now, each picked out, moved, set as its kind has it or
    taken away. Each change goes into the panel's pending step."""

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
        for piece in Items.clampsOn(self.job):
            which = getattr(piece, "Source", "")
            if which and which not in Items.Classes:
                clamp = Items.clampFile(which)
                if clamp is not None and all(p != which for _, p, _ in self.files):
                    self.files.append((self._clampName(which, clamp[0]), which, clamp[1]))
        sections = []
        for title, icon in (
            (translate("CAM_Workholding", "Add"), Widgets.themedIcon(":/icons/xy-in-stock.svg")),
            (translate("CAM_Workholding", "Placed"), QtGui.QIcon(":/icons/Std_Placement.svg")),
        ):
            section = QtWidgets.QWidget()
            section.setWindowTitle(title)
            section.setWindowIcon(icon)
            sections.append((section, QtWidgets.QFormLayout(section)))
        self.forms = [section for section, _ in sections]
        self.layouts = [layout for _, layout in sections]
        # rows from the top, whatever height the task box gives the section
        for layout in self.layouts:
            layout.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

        # the row adding them: the side, picked on the stock in the 3D view or named; what goes
        # there, made here or from a file, or another Job's stop; how many, spread along it
        layout = self.layouts[0]
        self.side = Widgets.combo()
        self.side.setToolTip(
            translate(
                "CAM_Workholding",
                "The side of the part they go on: one named, or an edge or face of the stock "
                "picked in the 3D view",
            )
        )
        self.item = Widgets.combo(wide=True)
        self.item.setToolTip(
            translate(
                "CAM_Workholding",
                "What goes there: a stop or clamp made here, a clamp's own file, one from a "
                "library, or another Job's stop to share",
            )
        )
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(1, 12)
        self.count.setValue(2)
        self.count.setToolTip(translate("CAM_Workholding", "How many, spread along the side"))
        self.add = QtWidgets.QPushButton(translate("CAM_Workholding", "Add"))
        self.add.setToolTip(
            translate(
                "CAM_Workholding",
                "Put them on the side, spread along it with those there you have not moved",
            )
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.side, 2)
        row.addWidget(self.item, 3)
        row.addWidget(self.count)
        row.addWidget(self.add)
        layout.addRow(row)
        self.shared = Widgets.Note()
        layout.addRow(self.shared)
        self.error = Widgets.Note()
        self.error.setStyleSheet("color: %s" % ERROR_TEXT_COLOR)
        layout.addRow(self.error)
        self.lastItem = 0
        # while the panel is open the stock is picked in the 3D view, an edge or face of it
        # offered as the side
        self.stockSelectable = None
        stock = getattr(self.job, "Stock", None)
        vobj = getattr(stock, "ViewObject", None)
        if vobj is not None and "Selectable" in vobj.PropertiesList:
            self.stockSelectable = vobj.Selectable
            vobj.Selectable = True
        # and the stops and clamps picked in it, a click on one picking its row
        self.pickable = {}
        self.makePickable()
        ViewProviders.setWholePicks(True)
        FreeCADGui.Selection.addObserver(self)
        # the one picked dragged with FreeCAD's Transform dragger, its drag kept
        self.editing = None
        self.applying = False
        FreeCAD.addDocumentObserver(self)

        # those placed, by the edge each is at: picked out in the 3D view too, moved, set, taken
        # away
        layout = self.layouts[1]
        self.list = QtWidgets.QTableWidget(0, 4)
        self.list.setHorizontalHeaderLabels(
            [
                translate("CAM_Workholding", "Piece"),
                "X",
                "Y",
                translate("CAM_Workholding", "Angle"),
            ]
        )
        self.list.verticalHeader().setVisible(False)
        self.list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.list.setShowGrid(True)
        self.list.setWordWrap(False)
        self.list.setToolTip(
            translate(
                "CAM_Workholding",
                "The Job's stops, clamps and table: picked here, picked in the 3D view too",
            )
        )
        # rows a line of text high, as the list was
        self.list.verticalHeader().setDefaultSectionSize(self.list.fontMetrics().height() + 6)
        rows = 6
        self.list.setFixedHeight(
            self.list.horizontalHeader().sizeHint().height()
            + rows * self.list.verticalHeader().defaultSectionSize()
            + 2 * self.list.frameWidth()
        )
        # its height its own: a table grows by default, and the task panel would hand the
        # section its spare height, the rows centered in it
        policy = self.list.sizePolicy()
        policy.setVerticalPolicy(QtWidgets.QSizePolicy.Fixed)
        self.list.setSizePolicy(policy)
        header = self.list.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        layout.addRow(self.list)
        # where it is: the Job's X and Y, the one across its side greyed, kept against the stock
        self.placeAt = []
        for axis in ("X", "Y"):
            self.placeAt.append(
                Widgets.mmBox(
                    self.ui,
                    translate(
                        "CAM_Workholding",
                        "Where the one picked is, the Job's %s: set along its side, kept against "
                        "the stock across it",
                    )
                    % axis,
                    minimum=-10000.0,
                )
            )
        self.remove = QtWidgets.QPushButton(translate("CAM_Workholding", "Remove"))
        self.remove.setToolTip(translate("CAM_Workholding", "Take the one picked away"))
        row = QtWidgets.QHBoxLayout()
        self.placeLabels = []
        for axis, box in zip(("X", "Y"), self.placeAt):
            self.placeLabels.append(QtWidgets.QLabel(axis))
            row.addWidget(self.placeLabels[-1])
            row.addWidget(box, 1)
        row.addWidget(self.remove)
        # in a widget of its own: a layout cannot be hidden where QFormLayout has no
        # setRowVisible, Qt before 6.4
        holder = QtWidgets.QWidget()
        row.setContentsMargins(0, 0, 0, 0)
        holder.setLayout(row)
        layout.addRow(translate("CAM_Workholding", "Position"), holder)
        self.placeRow = holder
        self.positionLabel = layout.labelForField(holder)
        # a side clamp picked: how far it is turned, pushing at a slant
        self.slant = self.ui.createWidget("Gui::QuantitySpinBox")
        self.slant.setProperty("unit", "deg")
        self.slant.setProperty("minimum", -90.0)
        self.slant.setProperty("maximum", 90.0)
        self.slant.setToolTip(
            translate(
                "CAM_Workholding",
                "How far it is turned from square to its side, seen from above, pushing at a slant",
            )
        )
        layout.addRow(translate("CAM_Workholding", "Angle"), self.slant)
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
            translate(
                "CAM_Workholding",
                "Its size given to the others of its kind on its side; how tall each stands is its own",
            )
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

        self.item.currentIndexChanged.connect(self.itemChanged)
        self.add.clicked.connect(self.addClicked)
        self.list.currentCellChanged.connect(lambda *args: self.showChosen())
        self.list.itemSelectionChanged.connect(self.picked)
        # the box being typed in is not written over until typing in it is done
        self.typing = None
        self.shownPiece = None
        self.placeTimer = QtCore.QTimer()
        self.placeTimer.setSingleShot(True)
        self.placeTimer.setInterval(LEVER_EDIT_DELAY)
        self.placeTimer.timeout.connect(self.nudged)
        for box in self.placeAt:
            box.valueChanged.connect(lambda *args, box=box: self.typed(box, self.placeTimer))
            box.editingFinished.connect(lambda box=box: self.typedDone(box, self.placeTimer))
        self.sizeTimer = QtCore.QTimer()
        self.sizeTimer.setSingleShot(True)
        self.sizeTimer.setInterval(LEVER_EDIT_DELAY)
        self.sizeTimer.timeout.connect(self.resized)
        self.sizeName = None
        self.sizePiece = None
        self.slantTimer = QtCore.QTimer()
        self.slantTimer.setSingleShot(True)
        self.slantTimer.setInterval(LEVER_EDIT_DELAY)
        self.slantTimer.timeout.connect(self.slanted)
        self.slant.valueChanged.connect(lambda *args: self.typed(self.slant, self.slantTimer))
        self.slant.editingFinished.connect(lambda: self.typedDone(self.slant, self.slantTimer))
        # the one being dragged: where the dragger has it shown as it moves
        self.dragTimer = QtCore.QTimer()
        self.dragTimer.setInterval(DRAG_SHOW_EVERY)
        self.dragTimer.timeout.connect(self.showDragging)
        self.dragShown = None
        # a number turned with the wheel placed once it stops, not at every click
        self.leverPending = {}
        self.leverTimer = QtCore.QTimer()
        self.leverTimer.setSingleShot(True)
        self.leverTimer.setInterval(LEVER_EDIT_DELAY)
        self.leverTimer.timeout.connect(self.applyLever)
        for box in (self.pressX, self.pressY, self.angle, self.riser, self.boltLength, self.boltAt):
            box.valueChanged.connect(lambda *args, box=box: self.typed(box, None))
            box.editingFinished.connect(lambda box=box: self.typedDone(box, self.leverTimer))
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

    def showRow(self, field, shown):
        """A row of the Placed section shown, or gone with its label and the space it takes."""
        form = self.layouts[1]
        if hasattr(form, "setRowVisible"):
            form.setRowVisible(field, shown)
        else:
            field.setVisible(shown)
            label = form.labelForField(field)
            if label is not None:
                label.setVisible(shown)

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

    # the row adding them

    def fillSides(self):
        """The sides the row offers: an edge or face of the stock picked in the 3D view first,
        then the part's sides standing round the stock; the one chosen kept."""
        keep = self.side.currentData()
        self.side.blockSignals(True)
        self.side.clear()
        picked = self.pickedSide()
        if picked is not None:
            what, side = picked
            words = (
                translate("CAM_Workholding", "Selected edge (%s)")
                if what == "Edge"
                else translate("CAM_Workholding", "Selected face (%s)")
            )
            self.side.addItem(words % self.names.get(side, side), ("picked", side))
        for side in Items.sides(self.job):
            self.side.addItem(self.names.get(side, side), side)
        index = self.side.findData(keep) if keep is not None else -1
        if picked is not None and (keep is None or not isinstance(keep, tuple)):
            index = 0
        self.side.setCurrentIndex(max(0, index))
        self.side.blockSignals(False)

    def pickedSide(self):
        """The edge or face of the stock picked in the 3D view and the part's side it is on:
        ("Edge" or "Face", side); None if none is, or it is on no side."""
        stock = getattr(self.job, "Stock", None)
        if stock is None:
            return None
        for sel in FreeCADGui.Selection.getSelectionEx(self.job.Document.Name):
            if sel.Object != stock:
                continue
            for name, shape in zip(sel.SubElementNames, sel.SubObjects):
                if shape.ShapeType not in ("Edge", "Face"):
                    continue
                try:
                    return shape.ShapeType, Items.sideOfShape(self.job, shape)
                except ValueError as e:
                    self.error.setText(str(e))
                    return None
        return None

    def fillItems(self):
        """What the row can put on a side: a dog or a fence, the clamps' files the Job uses, those
        installed and those chosen since, then Browse; and the other Jobs' stops to share. The
        one chosen kept."""
        import Path.Workholding.Library as PathLibrary

        keep = self.item.currentData()
        self.item.blockSignals(True)
        self.item.clear()
        for label, which in (
            (translate("CAM_Workholding", "Dog"), "Dog"),
            (translate("CAM_Workholding", "Fence"), "Fence"),
        ):
            self.item.addItem(label, which)
        Widgets.header(self.item, translate("CAM_Workholding", "From files"))
        seen = set()
        files = list(self.files)
        for found in PathLibrary.localItems("clamp"):
            files.append((found.get("label", found["id"]), found["path"], None))
        for name, path, _ in files:
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            self.item.addItem("   " + name, path)
        self.item.addItem("   " + translate("CAM_Workholding", "Browse…"), "browse")
        owners = Items.shareableStops(self.job)
        if owners:
            Widgets.header(self.item, translate("CAM_Workholding", "Share"))
            for owner in owners:
                self.item.addItem(
                    "   "
                    + translate("CAM_Workholding", "%s, in %s")
                    % (owner.Label, PathWorkholding.memberOf(owner)[0].Label),
                    ("share", owner.Name),
                )
        index = self.item.findData(keep) if keep not in (None, "browse") else -1
        if index < 0:
            index = self.item.findData("Dog")
        self.item.setCurrentIndex(index)
        self.lastItem = index
        self.item.blockSignals(False)
        Widgets.fitList(self.item)
        self.updateRow()

    def itemChanged(self, *args):
        """Browse chosen: the picker opened, what it chooses put in the list and chosen, else
        what was chosen before."""
        if self.item.currentData() == "browse":
            import Path.Workholding.Gui.Library as LibraryGui

            path = LibraryGui.getClamp()
            index = self.addClampFile(path) if path else None
            self.item.blockSignals(True)
            self.item.setCurrentIndex(index if index is not None and index >= 0 else self.lastItem)
            self.item.blockSignals(False)
        self.lastItem = self.item.currentIndex()
        self.updateRow()

    def updateRow(self):
        """One of another Job's stops is shared one at a time."""
        share = isinstance(self.item.currentData(), (tuple, list))
        self.count.setEnabled(not share)

    def addClampFile(self, path):
        """A clamp's file put in the list if it is not there: its place in the list, None if it
        holds no clamp."""
        for _, known, _ in self.files:
            if os.path.exists(known) and os.path.samefile(known, path):
                self.fillItems()
                return self.item.findData(known)
        clamp = Items.clampFile(path)
        if clamp is None:
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(),
                translate("CAM_Workholding", "Clamps"),
                translate("CAM_Workholding", "%s holds no clamp.") % os.path.basename(path),
            )
            return None
        self.files.append((self._clampName(path, clamp[0]), path, clamp[1]))
        self.fillItems()
        return self.item.findData(path)

    @staticmethod
    def _clampName(path, name):
        """A clamp's file's name to show: its label, as it says, else its file's name."""
        import Path.Workholding.Library as PathLibrary

        return PathLibrary.about(path).get("label") or name

    def addClicked(self):
        """What the row says put on its side, spread along it; a clamp's file in a document not
        saved refused first: its parts are linked."""
        side = self.side.currentData()
        if isinstance(side, tuple):
            side = side[1]
        which = self.item.currentData()
        if side is None or which in (None, "browse"):
            return
        if isinstance(which, str) and which not in Items.Classes and not self.job.Document.FileName:
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(),
                translate("CAM_Workholding", "Clamps"),
                translate(
                    "CAM_Workholding",
                    "Save the document first: the clamp's parts are linked from its own file.",
                ),
            )
            return
        self.panel.begin()
        try:
            new = Items.addPieces(self.job, side, which, self.count.value())
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.error.setText("")
        self.readIn(new[-1] if new else None)

    # read in from the Job

    def readIn(self, pick=None):
        """The row and the list as the Job's stops and clamps are: the panel shows what the
        document has."""
        self.loading = True
        try:
            self.makePickable()
            self.fillSides()
            self.fillItems()
            notes = []
            for stop in Items.stopsOn(self.job):
                for job in PathWorkholding.sharedWith(stop):
                    note = (
                        translate(
                            "CAM_Workholding",
                            "Shared with %s: its stops stay, the part moves to them",
                        )
                        % job.Label
                    )
                    if note not in notes:
                        notes.append(note)
            self.shared.setText("\n".join(notes))
        finally:
            self.loading = False
        self.fillList(pick)

    # the 3D view's picks: an edge or face of the stock offered as the side, a stop or clamp
    # picking its row

    def makePickable(self):
        """The stops and clamps, and their parts, picked in the 3D view while the panel is open;
        how each was kept to put back."""
        if self.pickable is None:
            return
        for piece in Items.itemsOf(self.job):
            for obj in [piece] + list(getattr(piece, "Group", []) or []):
                vobj = getattr(obj, "ViewObject", None)
                if vobj is None or "Selectable" not in vobj.PropertiesList:
                    continue
                if obj.Name not in self.pickable:
                    self.pickable[obj.Name] = vobj.Selectable
                vobj.Selectable = True

    def addSelection(self, doc, obj, sub, pos):
        self.fillSides()
        self.selectFromView()

    def removeSelection(self, doc, obj, sub):
        self.fillSides()
        self.selectFromView()

    def setSelection(self, doc):
        self.fillSides()
        self.selectFromView()

    def clearSelection(self, doc):
        self.fillSides()
        self.selectFromView()

    def setPreselection(self, doc, obj, sub):
        """The cursor over a part of a stop or clamp: all of it lit, a moment after, as clicking
        picks all of it."""
        if self.pickable is None or getattr(self, "hovering", False):
            return
        document = FreeCAD.getDocument(doc) if doc in FreeCAD.listDocuments() else None
        found = document.getObject(obj) if document is not None else None
        if found is None:
            return
        leaf = found.getSubObject(sub, retType=1) if sub else found
        job, piece = PathWorkholding.memberOf(leaf or found)
        if job != self.job or piece is None or (found == piece and not sub):
            return
        QtCore.QTimer.singleShot(0, lambda: self._hoverWhole(piece))

    def _hoverWhole(self, piece):
        if self.pickable is None or not piece.isAttachedToDocument():
            return
        self.hovering = True
        try:
            FreeCADGui.Selection.setPreselection(piece)
        except Exception:
            pass
        finally:
            self.hovering = False

    # those placed

    def fillList(self, pick=None):
        """The Job's stops, clamps and table listed by the side each is at now and along it, with
        where each is and, for a lever clamp or a side clamp turned, its angle; the one picked kept, and those picked in
        the 3D view."""
        keep = pick or self.chosen()
        keep = keep.Name if keep is not None else None
        pieces = Items.stopsOn(self.job) + Items.clampsOn(self.job)
        pieces += [o for o in Items.itemsOf(self.job) if o not in pieces]

        def order(piece):
            edge = Items.edgeOf(self.job, piece)
            if edge is None:
                return (len(Items.AllSides), 0.0)
            axis, _ = Items.sideAxis(self.job, edge)
            return (Items.AllSides.index(edge), PathWorkholding.placementOf(piece).Base[axis])

        self.syncing = True
        self.list.blockSignals(True)
        self.list.clearContents()
        ordered = sorted(pieces, key=order)
        self.list.setRowCount(len(ordered))
        current = None
        for row, piece in enumerate(ordered):
            text = piece.Label
            if PathWorkholding.isShared(piece):
                text += " " + translate("CAM_Workholding", "(shared)")
            # where it meets the stock, as its X and Y show it; a lever clamp where it presses
            contact = Items.contactFrame(self.job, piece)
            where = contact.Base if contact is not None else PathWorkholding.placementOf(piece).Base
            turn = getattr(piece, "Angle", None)
            angle = _degrees(turn.Value) if turn is not None else ""
            for column, words in enumerate((text, _length(where.x), _length(where.y), angle)):
                cell = QtWidgets.QTableWidgetItem(words)
                if column:
                    cell.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                cell.setData(QtCore.Qt.UserRole, piece.Name)
                self.list.setItem(row, column, cell)
            if piece.Name == keep:
                current = row
        if current is not None:
            self.list.setCurrentCell(current, 0)
            self.list.selectRow(current)
        self.list.blockSignals(False)
        self.syncing = False
        self.showChosen()

    def chosen(self):
        """The piece picked in the list, the one its settings show; None if none, or if its row
        was let go."""
        row = self.list.currentRow()
        picked = row >= 0 and self.list.selectionModel().isRowSelected(row, QtCore.QModelIndex())
        cell = self.list.item(row, 0) if picked else None
        if cell is None:
            return None
        return self.job.Document.getObject(cell.data(QtCore.Qt.UserRole))

    def chosenAll(self):
        """The pieces picked in the list."""
        found = []
        for index in self.list.selectionModel().selectedRows():
            cell = self.list.item(index.row(), 0)
            piece = self.job.Document.getObject(cell.data(QtCore.Qt.UserRole)) if cell else None
            if piece is not None:
                found.append(piece)
        return found

    def pickedInView(self):
        """The stops and clamps of this Job picked in the 3D view: a part of one is the piece."""
        found = []
        for sel in FreeCADGui.Selection.getSelectionEx(self.job.Document.Name):
            objects = [sel.Object]
            for sub in sel.SubElementNames:
                leaf = sel.Object.getSubObject(sub, retType=1)
                if leaf is not None:
                    objects.append(leaf)
            for obj in objects:
                job, piece = PathWorkholding.memberOf(obj)
                if job == self.job and piece is not None and piece not in found:
                    found.append(piece)
        return found

    def selectFromView(self):
        """A click on a stop or clamp in the 3D view, on a face or part of it, picks all of it, a
        moment after so the click is done; its row picked with it, and those of the others
        picked, the first of them shown. The stock's faces and edges stay picked as they are."""
        if getattr(self, "syncing", False):
            return
        QtCore.QTimer.singleShot(0, self._wholePieces)

    def _wholePieces(self):
        if getattr(self, "syncing", False) or self.pickable is None:
            return
        try:
            pieces = self.pickedInView()
            stock = getattr(self.job, "Stock", None)
            whole = True
            keepStock = []
            for sel in FreeCADGui.Selection.getSelectionEx(self.job.Document.Name):
                if stock is not None and sel.Object == stock:
                    keepStock.append(sel)
                    continue
                if sel.Object not in pieces or sel.SubElementNames:
                    whole = False
        except RuntimeError:
            # the panel gone meanwhile
            return
        self.syncing = True
        try:
            if not whole:
                FreeCADGui.Selection.clearSelection()
                for sel in keepStock:
                    for sub in sel.SubElementNames:
                        FreeCADGui.Selection.addSelection(sel.Object, sub)
                for piece in pieces:
                    FreeCADGui.Selection.addSelection(piece)
            picked = {p.Name for p in pieces}
            self.list.blockSignals(True)
            model = self.list.selectionModel()
            model.clearSelection()
            first = None
            for row in range(self.list.rowCount()):
                cell = self.list.item(row, 0)
                if cell is not None and cell.data(QtCore.Qt.UserRole) in picked:
                    (
                        self.list.selectRow(row)
                        if first is None
                        else model.select(
                            self.list.model().index(row, 0),
                            QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows,
                        )
                    )
                    if first is None:
                        first = row
            if first is not None:
                self.list.setCurrentCell(first, 0, QtCore.QItemSelectionModel.NoUpdate)
            self.list.blockSignals(False)
        finally:
            self.syncing = False
        self.showChosen()

    def picked(self, *args):
        """Pieces picked in the list: picked in the 3D view too."""
        if getattr(self, "syncing", False):
            return
        self.syncing = True
        try:
            FreeCADGui.Selection.clearSelection()
            for piece in self.chosenAll():
                FreeCADGui.Selection.addSelection(piece)
        finally:
            self.syncing = False
        self.showChosen()

    def showChosen(self):
        """Where the piece picked is along its side, as the Job's X or Y; one shared stays where
        it is, and only one placed by side has a place to show."""
        piece = self.chosen()
        if piece is not self.shownPiece:
            self.placeTimer.stop()
            self.slantTimer.stop()
            self.typing = None
            self.shownPiece = piece
        self.showPlace(piece)
        self.remove.setEnabled(piece is not None)
        # nothing picked, nothing to place or take away: the row gone whole, its boxes left
        # hidden with it
        self.showRow(self.placeRow, piece is not None)
        lever = Lever.isLever(piece)
        if piece is not None:
            # a lever clamp is placed where it presses, not along its side: Remove only
            for widget in self.placeAt + self.placeLabels:
                widget.setVisible(not lever)
            if self.positionLabel is not None:
                self.positionLabel.setVisible(not lever)
        self.showLever(piece if lever else None)
        self.showSize(piece)
        self.dragChosen(piece)

    def showPlace(self, piece, at=None, angle=None):
        """Where the piece picked is, where it meets the stock, the Job's X and Y, or where at
        puts it: the one along its side to set, the one across it greyed, kept against the
        stock; both to set for a side clamp, which may turn and push on a corner, put as if
        dragged there; both greyed for one shared or not placed by side."""
        placed = piece is not None and Items.isPlaced(piece) and not Lever.isLever(piece)
        along = Items.sideAxis(self.job, piece.StockSide)[0] if placed else None
        contact = Items.contactFrame(self.job, piece) if placed else None
        where = at or (contact.Base if contact is not None else None)
        free = placed and not PathWorkholding.isShared(piece)
        pushes = placed and getattr(piece, "Kind", None) == Items.Kind.Push
        for axis, box in enumerate(self.placeAt):
            self.showValue(box, where[axis] if where is not None else 0.0)
            box.setEnabled(free and (axis == along or pushes))
        self.showRow(self.slant, pushes)
        if pushes and angle is None:
            turned = getattr(piece, "Angle", None)
            angle = turned.Value if turned is not None else 0.0
        if pushes:
            self.showValue(self.slant, angle)

    def showValue(self, box, value):
        """A box set to value, unless it is being typed in."""
        if box is self.typing:
            return
        box.blockSignals(True)
        box.setProperty("rawValue", value)
        box.blockSignals(False)

    def typed(self, box, timer):
        """A box changed by the user: not written over while they type, put in once they pause."""
        self.typing = box
        if timer is not None:
            timer.start()

    def typedDone(self, box, timer):
        """Typing in a box done: what it says put in now, then the box shown as it is put in."""
        if self.typing is not box:
            return
        if timer.isActive():
            timer.stop()
            timer.timeout.emit()
        self.typing = None
        # shown as it was put in: a side clamp typed into the stock's middle is where it landed
        if box in self.placeAt:
            self.showPlace(self.chosen())

    def showLever(self, piece):
        """The lever clamp picked: where it presses, how it stands and what placing it found; the
        rows gone when none is. Edits not yet put in are dropped."""
        self.leverTimer.stop()
        self.leverPending = {}
        for field in self.leverRows:
            self.showRow(field, piece is not None)
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
            self.showValue(self.pressX, x)
            self.showValue(self.pressY, y)
            self.showValue(self.angle, piece.Angle.Value)
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
            self.showValue(self.riser, piece.RiserThickness.Value)
            if hasattr(piece, "BoltAt"):
                # no further than its slot runs
                slot = Lever.boltRange(piece)
                if slot is not None:
                    self.boltAt.setProperty("minimum", slot[0])
                    self.boltAt.setProperty("maximum", slot[1])
                auto = piece.BoltAt.Value <= 0
                self.boltAuto.setChecked(auto)
                self.showValue(self.boltAt, piece.BoltFound.Value if auto else piece.BoltAt.Value)
            bolt = hasattr(piece, "BoltFit")
            if bolt:
                self.boltFit.setChecked(piece.BoltFit)
                self.showValue(self.boltLength, piece.BoltLength.Value)
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.showRow(self.leverClamp, kit)
        slot = hasattr(piece, "BoltAt")
        self.showRow(self.boltAuto.parentWidget(), slot)
        self.boltAt.setEnabled(slot and piece.BoltAt.Value > 0)
        bolt = hasattr(piece, "BoltFit")
        self.showRow(self.boltFit.parentWidget(), bolt)
        self.boltLength.setEnabled(bolt and not piece.BoltFit)
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
        for note in (self.leverFound, self.leverNote):
            self.showRow(note, bool(note.text()))

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
        self.redrag(piece)

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
        self.redrag(piece)

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
        """The piece's sizes to change, unless it follows another Job's; its picture. The same
        piece's boxes kept, their numbers shown again, so one being typed in stays."""
        names = self.sizeNames(piece)
        fixed = piece is not None and PathWorkholding.isShared(piece)
        if piece is not None and piece is self.sizePiece and names == list(self.sizeBoxes):
            for name, box in self.sizeBoxes.items():
                self.showValue(box, getattr(piece, name).Value)
                box.setEnabled(not fixed and not _bound(piece, name))
            self.showRow(self.sameSide, bool(names) and not fixed and bool(self.others(piece)))
            self.showPicture(piece)
            return
        self.sizeTimer.stop()
        self.sizePiece = piece
        while self.sizeGrid.count():
            widget = self.sizeGrid.takeAt(0).widget()
            if widget is not None:
                # gone at once, not once the event loop comes round
                widget.setParent(None)
                widget.deleteLater()
        self.sizeBoxes = {}
        for i, name in enumerate(names):
            box = Widgets.mmBox(self.ui, piece.getDocumentationOfProperty(name))
            box.setProperty("rawValue", getattr(piece, name).Value)
            box.setEnabled(not fixed and not _bound(piece, name))
            box.valueChanged.connect(lambda *args, name=name, box=box: self.sizeTyped(name, box))
            box.editingFinished.connect(lambda box=box: self.typedDone(box, self.sizeTimer))
            self.sizeGrid.addWidget(
                QtWidgets.QLabel(translate("App::Property", name)), i // 2, (i % 2) * 2
            )
            self.sizeGrid.addWidget(box, i // 2, (i % 2) * 2 + 1)
            self.sizeBoxes[name] = box
        self.showRow(self.sizes, bool(names))
        self.showRow(self.sameSide, bool(names) and not fixed and bool(self.others(piece)))
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
        self.showRow(self.picture, pixmap is not None)

    def sizeTyped(self, name, box):
        """A size typed or turned: put in once the edits stop coming."""
        self.sizeName = name
        self.typed(box, self.sizeTimer)

    def resized(self, name=None):
        """A size of the piece picked changed, and the others' of its kind on its side with it."""
        name = name or self.sizeName
        piece = self.chosen()
        box = self.sizeBoxes.get(name)
        if piece is None or box is None or PathWorkholding.isShared(piece):
            return
        value = box.property("rawValue")
        if value <= 0:
            return
        self.panel.begin()
        # how tall each stands is its own: two dogs alike across may stand at different heights
        shared = self.sameSide.isChecked() and name not in OWN_SIZES
        pieces = [piece] + (self.others(piece) if shared else [])
        for each in pieces:
            if not _bound(each, name):
                setattr(each, name, value)
        self.showPicture(piece)
        self.timer.start()

    def nudged(self):
        """The piece picked put where its X or Y along its side says, and kept there; a side
        clamp where both say, as if dragged there: on the side nearest, pushed in to touch."""
        piece = self.chosen()
        if piece is None or not Items.isPlaced(piece) or PathWorkholding.isShared(piece):
            return
        self.panel.begin()
        if getattr(piece, "Kind", None) == Items.Kind.Push:
            contact = Items.contactFrame(self.job, piece)
            x, y = (box.property("rawValue") for box in self.placeAt)
            try:
                Items.fromTransform(
                    piece, FreeCAD.Placement(FreeCAD.Vector(x, y, contact.Base.z), contact.Rotation)
                )
                self.error.setText("")
            except ValueError as e:
                self.error.setText(str(e))
            self.fillList(piece)
            self.redrag(piece)
            return
        axis = Items.sideAxis(self.job, piece.StockSide)[0]
        Items.setPosition(piece, self.placeAt[axis].property("rawValue"))
        self.redrag(piece)
        self.timer.start()

    def slanted(self):
        """The side clamp picked turned as its Angle says."""
        piece = self.chosen()
        if piece is None or getattr(piece, "Kind", None) != Items.Kind.Push:
            return
        self.panel.begin()
        Items.setAngle(piece, self.slant.property("rawValue"))
        self.fillList(piece)
        self.redrag(piece)

    def redrag(self, piece):
        """The dragger made again where the piece now is, put there by the panel: it does not
        follow the piece placed."""
        if self.editing is None:
            return
        self.editing = None
        FreeCADGui.getDocument(self.job.Document.Name).resetEdit()
        self.dragChosen(piece)

    def dragChosen(self, piece):
        """FreeCAD's Transform dragger on the one piece picked, without its task panel, its
        arrows those its kind moves by; off another, or when several or none are picked."""
        want = None
        if piece is not None and len(self.chosenAll()) <= 1 and Items.canTransform(piece):
            want = piece.Name
        if want == self.editing:
            return
        gui = FreeCADGui.getDocument(self.job.Document.Name)
        if self.editing is not None:
            self.editing = None
            gui.resetEdit()
        self.dragTimer.stop()
        self.dragShown = None
        if want is not None:
            # the dragger moves the piece before the panel hears of it: the step its moves go
            # into opened first, so Cancel undoes the first drag too
            self.panel.begin()
        if want is not None and gui.setEdit(piece, TRANSFORM_NO_DIALOG):
            self.editing = want
            self.dragTimer.start()

    def showDragging(self):
        """Where the dragger has the piece being dragged, shown as it moves: its X, Y and angle
        in the panel and its row. Kept as its settings only when let go."""
        piece = self.job.Document.getObject(self.editing) if self.editing else None
        dragger = ViewProviders.findDragger() if piece is not None else None
        if dragger is None:
            return
        at = ViewProviders.draggerPlacement(dragger)
        shown = (round(at.Base.x, 6), round(at.Base.y, 6), round(at.Rotation.Angle, 9))
        if shown == self.dragShown:
            return
        self.dragShown = shown
        lever = Lever.isLever(piece)
        turned = lever or getattr(piece, "Kind", None) == Items.Kind.Push
        # the piece's own placement, the dragger standing where it meets the stock
        origin = getattr(piece.ViewObject, "TransformOrigin", None)
        own = at.multiply(origin.inverse()) if origin is not None else at
        angle = Items.angleFrom(self.job, piece, own.Rotation) if turned else None
        if lever:
            for box, value in ((self.pressX, at.Base.x), (self.pressY, at.Base.y)):
                box.blockSignals(True)
                box.setProperty("rawValue", value)
                box.blockSignals(False)
            self.angle.blockSignals(True)
            self.angle.setProperty("rawValue", angle)
            self.angle.blockSignals(False)
        else:
            self.showPlace(piece, at.Base, angle)
        for row in range(self.list.rowCount()):
            cell = self.list.item(row, 0)
            if cell is None or cell.data(QtCore.Qt.UserRole) != piece.Name:
                continue
            words = [_length(at.Base.x), _length(at.Base.y)]
            words.append(_degrees(angle) if angle is not None else "")
            for column, text in enumerate(words, 1):
                item = self.list.item(row, column)
                if item is not None:
                    item.setText(text)

    def slotChangedObject(self, obj, prop):
        """The piece being dragged moved by the dragger, not by its placing: kept as its
        settings, a moment after."""
        if prop != "Placement" or obj.Name != self.editing or self.applying:
            return
        # one of the same name in another document, a clamp's file open hidden
        if obj.Document != self.job.Document or Items.layingOut():
            return
        QtCore.QTimer.singleShot(0, self.applyDrag)

    def applyDrag(self):
        piece = self.job.Document.getObject(self.editing) if self.editing else None
        if piece is None or self.applying:
            return
        self.applying = True
        try:
            self.panel.begin()
            Items.fromTransform(piece, ViewProviders.dragPlacement(piece.ViewObject))
            self.error.setText("")
        except ValueError as e:
            self.error.setText(str(e))
        finally:
            self.applying = False
        # the dragger made again where the piece now is: it does not follow the piece placed
        self.editing = None
        FreeCADGui.getDocument(self.job.Document.Name).resetEdit()
        self.fillList(piece)
        self.picked()

    def removeChosen(self):
        """The pieces picked taken away, the rows as the Job now has them."""
        pieces = self.chosenAll() or [p for p in [self.chosen()] if p is not None]
        if not pieces:
            return
        self.timer.stop()
        self.panel.begin()
        FreeCADGui.Selection.clearSelection()
        for piece in pieces:
            if piece.isAttachedToDocument():
                Items.removePiece(piece)
        self.readIn()

    def addTable(self):
        """The table under the stock: put in, or placed under it again."""
        self.panel.begin()
        table = Items.addTable(self.job)
        self.fillList(table)

    def preview(self):
        """The stops and clamps placed again as they say, pending: True."""
        self.timer.stop()
        self.panel.begin()
        Items.layout(self.job)
        self.fillList()
        return True

    def finish(self, gone=False):
        """A clamp's file opened for the panel closed again if nothing links to it now; the
        stock picked no longer, as it was. With gone, the Job's document is being closed:
        nothing in it touched."""
        # nothing typed or dragged applied once the panel is gone
        for timer in (
            self.timer,
            self.dragTimer,
            self.placeTimer,
            self.sizeTimer,
            self.slantTimer,
            self.leverTimer,
        ):
            timer.stop()
        FreeCADGui.Selection.removeObserver(self)
        FreeCAD.removeDocumentObserver(self)
        if gone:
            self.editing = None
            self.pickable = None
            ViewProviders.setWholePicks(False)
            return
        if self.editing is not None:
            self.editing = None
            gui = FreeCADGui.getDocument(self.job.Document.Name)
            if gui is not None:
                gui.resetEdit()
        ViewProviders.setWholePicks(False)
        stock = getattr(self.job, "Stock", None)
        vobj = getattr(stock, "ViewObject", None)
        if vobj is not None and self.stockSelectable is not None:
            vobj.Selectable = self.stockSelectable
        for name, was in self.pickable.items():
            obj = self.job.Document.getObject(name)
            vobj = getattr(obj, "ViewObject", None)
            if vobj is not None and "Selectable" in vobj.PropertiesList:
                vobj.Selectable = was
        # closed: picks no longer followed
        self.pickable = None
        for name, doc in list(FreeCAD.listDocuments().items()):
            if name not in self.open and (
                Items.clampIn(doc) is not None or Lever.kitIn(doc) is not None
            ):
                _closeIfUnused(doc)
        if self.job.Document.Name in FreeCAD.listDocuments():
            FreeCADGui.setActiveDocument(self.job.Document.Name)
