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

"""Seat a Job's stock in a vise of its Workholding: against the fixed jaw, held as deep as asked,
across the jaws as asked, the moving jaw closed on it. Add a vise from its own file, and another
of a piece of workholding beside it. Or hold it on the table: stops on one side or a corner, the
stock against them, clamps round it, a table under it."""

import os


import FreeCAD
import Path
import Path.Workholding.Vise as PathWorkholding
import Path.Workholding.Items as Items
import Path.Workholding.Jaws as PathJaws
import Path.Workholding.Parallels as PathParallels
import Path.Workholding.Source as PathSource
import Path.Workholding.Gui.Widgets as Widgets
import Path.Preferences

from Path.Workholding.Common import userLength
from Path.Workholding.Constants import (
    CLEAR_TEXT_COLOR,
    ERROR_TEXT_COLOR,
    JAW_FACE_COLOR,
    LIT_FACE_GLOW,
    LIT_FACE_LIFT,
    LIT_FACE_TOLERANCE,
    LIT_FACE_TRANSPARENCY,
    NOT_CLEAR_TEXT_COLOR,
    SEAT_COLOR,
)
from Path.Workholding.Gui.Items import _StopsClamps
from Path.Workholding.Gui.Source import _closeIfUnused

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore, QtGui, QtWidgets

translate = FreeCAD.Qt.translate


class _Adding:
    """A vise being added to a Job, its transaction open until it is kept or dropped: the vise
    put in, swapped for another, the file of one no longer used closed again."""

    def __init__(self, job):
        self.job = job
        self.doc = job.Document
        self.vise = None
        self.source = None
        self.path = None
        self.doc.openTransaction(translate("CAM_AddVise", "Add vise"))

    def put(self, path):
        """The vise of the file at path in the Job, in the place of the one there was."""
        if os.path.samefile(path, self.doc.FileName):
            raise ValueError(translate("CAM_AddVise", "A vise comes from a file of its own"))
        source, opened = PathSource.openFile(path, self.doc)
        found = PathWorkholding.viseIn(source)
        if found is None:
            if opened:
                _closeIfUnused(source)
                FreeCADGui.setActiveDocument(self.doc.Name)
            raise ValueError(
                translate(
                    "CAM_AddVise", "%s holds no vise: a part with a VarSet giving its Opening."
                )
                % os.path.basename(path)
            )
        placement = None
        previous = self.source
        if self.vise is not None:
            placement = FreeCAD.Placement(self.vise.Placement)
            self.drop()
        self.vise = PathWorkholding.addVise(self.job, found, placement)
        self.source = source
        self.path = path
        # the links to the previous file gone first, then the file: the other way round, a
        # reopened file finds the deleted links and fails to open
        if previous is not None and previous != source:
            _closeIfUnused(previous)
            FreeCADGui.setActiveDocument(self.doc.Name)
        return self.vise

    def drop(self):
        """The vise put in taken out again, no longer shared."""
        PathWorkholding.release(self.vise)
        for obj in list(self.vise.Group) + [self.vise]:
            self.doc.removeObject(obj.Name)
        self.vise = None

    def share(self, owner):
        """A vise of another Job, owner, shared with the Job in the place of the one there was:
        a vise of its own, placed where the owner is, in a station free."""
        previous = self.source
        if self.vise is not None:
            self.drop()
        self.vise = PathWorkholding.shareVise(owner, self.job)
        self.source = None
        self.path = None
        if previous is not None:
            _closeIfUnused(previous)
            FreeCADGui.setActiveDocument(self.doc.Name)
        return self.vise

    def finish(self, keep):
        """The vise kept, its add one undoable step, or dropped without a trace."""
        if keep:
            self.doc.commitTransaction()
        else:
            self.doc.abortTransaction()
            self.doc.recompute()
        if self.source is not None:
            _closeIfUnused(self.source)
        FreeCADGui.setActiveDocument(self.doc.Name)


def _hex(color):
    """color, red, green and blue from 0 to 1, as a style sheet writes it."""
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in color)


class _SeatFaces:
    """The part's sides lit as the vise holds it: the one on the bottom, the one against the
    fixed jaw. Drawn over the stock, nothing in the document."""

    def __init__(self):
        self.node = None
        self.view = None

    def show(self, job, seat, jaw, vise=None):
        """seat and jaw, the Job's axes the two sides face out along; and vise's own seat and
        fixed jaw, where it stands."""
        from pivy import coin

        self.hide()
        gui = FreeCADGui.getDocument(job.Document.Name)
        views = gui.mdiViewsOfType("Gui::View3DInventor") if gui else []
        if not views:
            return
        root = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        for direction, color in ((seat, SEAT_COLOR), (jaw, JAW_FACE_COLOR)):
            for face in job.Stock.Shape.Faces:
                if _facing(face, direction):
                    root.addChild(_drawn(face, direction, color))
        if vise is not None:
            for corners, normal, color in _viseFaces(vise):
                root.addChild(_drawnQuad(corners, normal, color))
        self.view = views[0]
        self.view.getSceneGraph().addChild(root)
        self.node = root

    def hide(self):
        if self.node is not None:
            try:
                self.view.getSceneGraph().removeChild(self.node)
            except Exception:
                pass
        self.node = None


def _viseFaces(vise):
    """The vise's seat and fixed jaw face where it stands, as (corners, normal, color): the
    seat the floor, the parallels' tops or the step it is on, from the fixed jaw out to the
    moving one; the fixed jaw's face, or the step's wall, across the jaws and down from the top
    of the face, or of the jaws for a step, to the seat. Every vise is laid out so."""
    frame = PathWorkholding.jawFrame(vise)
    if frame is None:
        return []
    width = frame["width"] or 100.0
    opening = PathWorkholding.openingOf(vise)
    face = frame["face"]
    top = frame["top"]
    seat = frame["floor"]
    step = getattr(vise, "SeatStep", 0)
    if 0 < step <= len(frame["steps"]):
        seat = frame["steps"][step - 1][0]
    elif getattr(vise, "OnParallels", False):
        seat += vise.Parallels.Value
    # against the jaw as it is at the seat: its face, or a step's wall above the step's floor
    fixed = PathWorkholding.wallAt(frame, seat)
    # the moving jaw's, the opening less what the jaws take of it: the soft jaws standing proud
    # of the hard plates, less the step's depth on each
    moving = fixed - opening + frame["gapLoss"] - 2 * (fixed - face)
    # in the station the stock is in
    placement = PathWorkholding.stationPlacement(vise)
    half = width / 2

    def placed(points):
        return [placement.multVec(FreeCAD.Vector(*p)) for p in points]

    up = placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
    toward = placement.Rotation.multVec(FreeCAD.Vector(0, -1, 0))
    return [
        (
            placed(
                [
                    (-half, fixed, seat),
                    (half, fixed, seat),
                    (half, moving, seat),
                    (-half, moving, seat),
                ]
            ),
            up,
            SEAT_COLOR,
        ),
        (
            placed(
                [(-half, fixed, top), (half, fixed, top), (half, fixed, seat), (-half, fixed, seat)]
            ),
            toward,
            JAW_FACE_COLOR,
        ),
    ]


def _drawnQuad(corners, normal, color):
    """A four cornered face as Coin draws it, a little off along normal."""
    from pivy import coin

    lift = normal * LIT_FACE_LIFT
    node = coin.SoSeparator()
    material = coin.SoMaterial()
    material.diffuseColor = color
    material.emissiveColor = tuple(c * LIT_FACE_GLOW for c in color)
    material.transparency = LIT_FACE_TRANSPARENCY
    node.addChild(material)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    node.addChild(hints)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, 4, [tuple(c + lift) for c in corners])
    node.addChild(coords)
    face = coin.SoFaceSet()
    face.numVertices.setValue(4)
    node.addChild(face)
    return node


def _facing(face, direction):
    """Whether face is flat and faces out along direction."""
    import Part

    if not isinstance(face.Surface, Part.Plane):
        return False
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt((u0 + u1) / 2, (v0 + v1) / 2).dot(direction) > 0.999


def _drawn(face, direction, color):
    """face as Coin draws it, a little off the stock along direction so it shows over it."""
    from pivy import coin

    points, triangles = face.tessellate(LIT_FACE_TOLERANCE)
    lift = direction * LIT_FACE_LIFT
    node = coin.SoSeparator()
    material = coin.SoMaterial()
    material.diffuseColor = color
    material.emissiveColor = tuple(c * LIT_FACE_GLOW for c in color)
    material.transparency = LIT_FACE_TRANSPARENCY
    node.addChild(material)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(points), [tuple(p + lift) for p in points])
    node.addChild(coords)
    faces = coin.SoIndexedFaceSet()
    index = []
    for a, b, c in triangles:
        index += [a, b, c, -1]
    faces.coordIndex.setValues(0, len(index), index)
    node.addChild(faces)
    return node


def _opposite(direction):
    return ("-" if direction[0] == "+" else "+") + direction[1]


def _canChangeJaws(vise):
    """Whether the vise's jaw plates can be swapped: its file names them."""
    return vise is not None and PathWorkholding.canChangeJaws(vise)


def _jawsOf(vise):
    """The vise's jaws as they are: their kind, the soft jaws' thickness and height in mm (None
    where it does not say) and their steps, (height, depth) in mm."""
    thickness = getattr(vise, "SoftThickness", None)
    height = getattr(vise, "SoftHeight", None)
    return (
        getattr(vise, "Jaws", "Hard"),
        thickness.Value if thickness is not None else None,
        height.Value if height is not None else None,
        PathJaws.parseSteps(getattr(vise, "Steps", []), quiet=True),
    )


class _StepRows(QtWidgets.QWidget if FreeCAD.GuiUp else object):
    """The steps cut in soft jaws, a row each of a table: how far down from the jaws' top its
    floor is, how far in from their face its wall is; buttons to add one and take the chosen
    one away."""

    if FreeCAD.GuiUp:
        changed = QtCore.Signal()

    def __init__(self, ui, size):
        super().__init__()
        self.ui = ui
        # the soft jaws' (thickness, height), mm, a new step started inside
        self.size = size
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(
            [translate("CAM_Workholding", "Down"), translate("CAM_Workholding", "In")]
        )
        self.table.horizontalHeaderItem(0).setToolTip(
            translate("CAM_Workholding", "From the soft jaws' top down to the step's floor")
        )
        self.table.horizontalHeaderItem(1).setToolTip(
            translate("CAM_Workholding", "From the soft jaws' face in to the step's wall")
        )
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        layout.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        add = QtWidgets.QToolButton()
        add.setText("+")
        add.setToolTip(translate("CAM_Workholding", "Another step cut in the soft jaws"))
        add.clicked.connect(self.addStep)
        remove = QtWidgets.QToolButton()
        remove.setText("\u2212")
        remove.setToolTip(translate("CAM_Workholding", "Take the chosen step away, else the last"))
        remove.clicked.connect(self.removeStep)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        layout.addLayout(buttons)
        self.fitHeight()

    def fitHeight(self):
        """The table as tall as its rows, no taller than four."""
        rows = max(1, min(self.table.rowCount(), 4))
        row = self.table.verticalHeader().defaultSectionSize()
        self.table.setFixedHeight(
            self.table.horizontalHeader().sizeHint().height()
            + rows * row
            + 2 * self.table.frameWidth()
        )

    def addRow(self, down, inward):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate((down, inward)):
            # a tenth of the shown unit a click: steps are small
            box = Widgets.mmBox(self.ui, value=value, step=0.1)
            box.valueChanged.connect(lambda *args: self.changed.emit())
            self.table.setCellWidget(row, column, box)
        self.renumber()
        self.fitHeight()

    def renumber(self):
        self.table.setVerticalHeaderLabels(
            [
                translate("CAM_Workholding", "Step %d") % (i + 1)
                for i in range(self.table.rowCount())
            ]
        )

    def addStep(self):
        thickness, height = self.size()
        self.addRow(height / 4, thickness / 4)
        self.changed.emit()

    def removeStep(self):
        rows = self.table.rowCount()
        if not rows:
            return
        row = self.table.currentRow()
        self.table.removeRow(row if 0 <= row < rows else rows - 1)
        self.renumber()
        self.fitHeight()
        self.changed.emit()

    def steps(self):
        """The steps, (down, in) mm."""
        return [
            (
                self.table.cellWidget(r, 0).property("rawValue"),
                self.table.cellWidget(r, 1).property("rawValue"),
            )
            for r in range(self.table.rowCount())
        ]

    def setSteps(self, steps):
        self.blockSignals(True)
        self.table.setRowCount(0)
        for down, inward in steps:
            self.addRow(down, inward)
        self.fitHeight()
        self.blockSignals(False)


def _alignLabels(layouts):
    """The forms' labels all as wide as the widest, their fields in one column."""
    labels = []
    for layout in layouts:
        for row in range(layout.rowCount()):
            item = layout.itemAt(row, QtWidgets.QFormLayout.LabelRole)
            if item is not None and isinstance(item.widget(), QtWidgets.QLabel):
                labels.append(item.widget())
    width = max((label.sizeHint().width() for label in labels), default=0)
    for label in labels:
        label.setMinimumWidth(width)


def _imperial():
    """Whether lengths show in inches, as the user's units have them."""
    try:
        unit = FreeCAD.Units.Quantity(1.0, FreeCAD.Units.Length).getUserPreferred()[2]
    except Exception:
        return False
    return "in" in unit or '"' in unit


def _header(combo, text):
    """A heading in a drop-down's list, not picked: bold and grayed."""
    combo.addItem(text)
    item = combo.model().item(combo.count() - 1)
    item.setEnabled(False)
    font = item.font()
    font.setBold(True)
    item.setFont(font)


class _ComboChoice:
    """One choice of a drop-down, asked and set as a radio button is: checked when it is the
    one picked, grayed or left out of the list."""

    def __init__(self, combo, text, data, tip=None):
        self.combo = combo
        self.data = data
        combo.addItem(text, data)
        self.row = combo.count() - 1
        if tip:
            combo.setItemData(self.row, tip, QtCore.Qt.ToolTipRole)

    def isChecked(self):
        return self.combo.currentData() == self.data

    def setChecked(self, checked):
        if checked:
            self.combo.setCurrentIndex(self.row)

    def item(self):
        return self.combo.model().item(self.row)

    def isEnabled(self):
        return self.item().isEnabled()

    def setEnabled(self, enabled):
        self.item().setEnabled(enabled)

    def setVisible(self, visible):
        self.combo.view().setRowHidden(self.row, not visible)


class _ParallelPicker(QtCore.QObject if FreeCAD.GuiUp else object):
    """The parallels the stock stands on: a set, headed by its unit, and a height of it, or
    custom; how long they are, a set's own length to start; hard or soft."""

    if FreeCAD.GuiUp:
        changed = QtCore.Signal()

    def __init__(self, ui):
        super().__init__()
        self.shown = True
        self.sets = PathParallels.catalog()
        # both drop down below themselves, as a list, whatever the style: some open over the
        # one picked, part of the list above
        self.set = Widgets.combo()
        self.set.setToolTip(
            translate("CAM_Workholding", "The set of parallels: its type, thickness and length")
        )
        unit = None
        for i, entry in enumerate(self.sets):
            if entry["unit"] != unit:
                unit = entry["unit"]
                _header(self.set, unit)
            for t in entry["thicknesses"]:
                self.set.addItem(
                    "   %s  %s \u00d7 %s"
                    % (
                        entry["type"],
                        PathParallels.label(t, unit),
                        PathParallels.label(entry["length"], unit),
                    ),
                    (i, t),
                )
        self.set.addItem(translate("CAM_Workholding", "Custom\u2026"), "custom")
        self.heights = Widgets.combo()
        self.heights.setToolTip(translate("CAM_Workholding", "How tall the pair is"))
        self.pair = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.pair)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.set, 3)
        row.addWidget(self.heights, 1)

        def box(tip, value):
            b = Widgets.mmBox(ui, tip, value)
            b.valueChanged.connect(lambda *args: self.changed.emit())
            return b

        self.height = box(
            translate("CAM_Workholding", "How tall the parallels are"), FreeCAD.Units.Inch.Value
        )
        self.thickness = box(
            translate("CAM_Workholding", "How thick each parallel is"),
            PathParallels.DefaultThickness,
        )
        self.length = box(
            translate("CAM_Workholding", "How long the parallels are, across the jaws"),
            PathParallels.DefaultLength,
        )
        self.soft = QtWidgets.QComboBox()
        self.soft.addItem(translate("CAM_Workholding", "Hard, steel"), False)
        self.soft.addItem(translate("CAM_Workholding", "Soft, aluminum or plastic"), True)
        self.soft.setToolTip(
            translate(
                "CAM_Workholding",
                "A tool cutting soft parallels is warned of; hard, steel ones are a crash",
            )
        )
        self.soft.currentIndexChanged.connect(lambda *args: self.changed.emit())
        # the rows they take in the panel, those of custom ones only for them
        self.rows = [
            (QtWidgets.QLabel(translate("CAM_SeatInVise", "Parallels")), self.pair, False),
            (QtWidgets.QLabel(translate("CAM_Workholding", "Height")), self.height, True),
            (QtWidgets.QLabel(translate("CAM_Workholding", "Thickness")), self.thickness, True),
            (QtWidgets.QLabel(translate("CAM_Workholding", "Length")), self.length, False),
            (QtWidgets.QLabel(translate("CAM_Workholding", "Material")), self.soft, False),
        ]
        self.set.currentIndexChanged.connect(self.setChanged)
        self.heights.currentIndexChanged.connect(lambda *args: self.changed.emit())
        self.choose(self.set.findData("custom"))

    def choose(self, index, height=None):
        """The set at index chosen, its heights listed, height picked if it has it."""
        self.set.blockSignals(True)
        self.set.setCurrentIndex(index)
        self.set.blockSignals(False)
        self.fill(height)
        self.showCustom()

    def fill(self, height=None):
        """The chosen set's heights, the one picked kept if the set has it."""
        data = self.set.currentData()
        keep = height if height is not None else self.heights.currentData()
        self.heights.blockSignals(True)
        self.heights.clear()
        if isinstance(data, tuple):
            entry = self.sets[data[0]]
            for h in entry["heights"]:
                self.heights.addItem(PathParallels.label(h, entry["unit"]), h)
            found = -1
            if keep is not None:
                found = min(
                    range(self.heights.count()),
                    key=lambda i: abs(self.heights.itemData(i) - keep),
                )
            self.heights.setCurrentIndex(max(found, 0))
        self.heights.blockSignals(False)

    def setChanged(self, *args):
        """A set chosen: its heights, its length, soft as it is; custom, its own sizes."""
        self.fill()
        data = self.set.currentData()
        if isinstance(data, tuple):
            entry = self.sets[data[0]]
            for b in (self.length, self.soft):
                b.blockSignals(True)
            self.length.setProperty("rawValue", entry["length"])
            self.soft.setCurrentIndex(self.soft.findData(entry.get("cuttable", False)))
            for b in (self.length, self.soft):
                b.blockSignals(False)
        self.showCustom()
        self.changed.emit()

    def addTo(self, layout):
        """Its rows added to a form."""
        for label, field, custom in self.rows:
            layout.addRow(label, field)

    def setShown(self, shown):
        """Its rows shown, or hidden when the stock does not stand on parallels."""
        self.shown = shown
        self.showCustom()

    def showCustom(self):
        custom = self.set.currentData() == "custom"
        self.heights.setVisible(not custom)
        for label, field, only in self.rows:
            visible = self.shown and (custom or not only)
            label.setVisible(visible)
            field.setVisible(visible)

    def chosen(self):
        """The parallels picked, None if they would be nothing."""
        data = self.set.currentData()
        length = self.length.property("rawValue")
        soft = bool(self.soft.currentData())
        if data == "custom":
            height, thickness = self.height.property("rawValue"), self.thickness.property(
                "rawValue"
            )
            if height <= 0 or thickness <= 0 or length <= 0:
                return None
            return PathParallels.Parallel(
                height, thickness, length, soft, translate("CAM_Workholding", "Custom")
            )
        height = self.heights.currentData()
        if not isinstance(data, tuple) or height is None:
            return None
        i, t = data
        return PathParallels.parallels(self.sets[i], t, height, length)._replace(cuttable=soft)

    def setIndex(self, unit, kind, thickness):
        """The index of the set of unit and kind as thick as given, -1 if there is none."""
        for index in range(self.set.count()):
            data = self.set.itemData(index)
            if isinstance(data, tuple):
                entry = self.sets[data[0]]
                if (entry["unit"], entry["type"]) == (unit, kind) and abs(
                    data[1] - thickness
                ) < 1e-6:
                    return index
        return -1

    def showPair(self, height, thickness, length, soft, name):
        """The parallels the vise has: their set and height if they are one, else custom."""
        parts = (name or "").split(", ")
        index = self.setIndex(parts[0], parts[1], thickness) if len(parts) > 1 else -1
        data = self.set.itemData(index) if index >= 0 else None
        if data is None or not any(abs(h - height) < 1e-6 for h in self.sets[data[0]]["heights"]):
            for b, v in ((self.height, height), (self.thickness, thickness)):
                b.blockSignals(True)
                b.setProperty("rawValue", v)
                b.blockSignals(False)
            index = self.set.findData("custom")
        self.choose(index, height)
        self.length.blockSignals(True)
        self.length.setProperty("rawValue", length)
        self.length.blockSignals(False)
        self.soft.blockSignals(True)
        self.soft.setCurrentIndex(self.soft.findData(bool(soft)))
        self.soft.blockSignals(False)

    def pickNear(self, height):
        """The tallest pair of the usual set, in the user's units, no taller than height: False
        if even the shortest is too tall."""
        unit = "Imperial" if _imperial() else "Metric"
        for index in range(self.set.count()):
            data = self.set.itemData(index)
            if not isinstance(data, tuple):
                continue
            entry = self.sets[data[0]]
            if (entry["unit"], entry["type"]) != (unit, "Standard"):
                continue
            fits = [h for h in entry["heights"] if h <= height + 1e-6]
            if not fits:
                return False
            self.choose(index, max(fits))
            self.setChanged()
            self.heights.setCurrentIndex(self.heights.findData(max(fits)))
            return True
        return False


def _shareable(job):
    """The vises of other Jobs that job can share, their owners: of more than one station, one
    free, none of them in job yet."""
    found = []
    for other in _jobsOf(job.Document):
        if other == job:
            continue
        for vise in PathWorkholding.vises(other):
            owner = PathWorkholding.ownerOf(vise)
            if (
                owner not in found
                and PathWorkholding.memberOf(owner)[0] is not None
                and PathWorkholding.canShare(owner, job)
            ):
                found.append(owner)
    return found


def _jobsOf(doc):
    import Path.Main.Job as PathJob

    return [
        o for o in doc.Objects if hasattr(o, "Proxy") and isinstance(o.Proxy, PathJob.ObjectJob)
    ]


def _showSection(form, visible):
    """A section of the panel shown or hidden whole, its header with it."""
    box = form.parentWidget()
    while box is not None and "TaskBox" not in box.metaObject().className():
        box = box.parentWidget()
    if visible:
        form.setVisible(True)
    (box or form).setVisible(visible)


class TaskPanelVise:
    """A vise of a Job: one it has, its stock seated in it again, or one added from the library.

    The vise, its jaws, the grip, where across the jaws, whether to close the jaw, what moves.
    Seating a vise it has, each Apply is an undoable step of its own. Adding one, the add's
    transaction stays open: seating goes into it, OK keeps the vise, Cancel takes it out again,
    and another chosen takes its place.

    Or the stops and clamps holding the stock on the table, piece among them picked out."""

    def __init__(self, job, vise=None, piece=None):
        self.job = job
        # the vise the Job has, chosen; or an _Adding, a vise being added
        self.existing = None
        self.adding = None
        self.seatFaces = _SeatFaces()
        # seated as the panel says at each change, a moment after it: pending until OK or
        # Apply keep it, Cancel undoes it
        self.pending = False
        self.loading = False
        self.previewTimer = QtCore.QTimer()
        self.previewTimer.setSingleShot(True)
        self.previewTimer.setInterval(150)
        self.previewTimer.timeout.connect(self.preview)
        # a vise just put in: how the part sits in it is yet to be chosen, its height not read in
        self.chooseSide = False
        self.fresh = False
        # a selected vise shows in the highlight color, hiding its own
        FreeCADGui.Selection.clearSelection()
        # three sections, each a box of its own that rolls up: the vise, its jaws and how the
        # part sits in it; what the stock stands on; where along the jaws and what moves
        sections = []
        for title, icon in (
            (translate("CAM_Workholding", "Vise"), QtGui.QIcon(":/icons/CAM_Vise.svg")),
            (translate("CAM_Workholding", "Stock"), Widgets.themedIcon(":/icons/stock.svg")),
            (translate("CAM_Workholding", "Position"), QtGui.QIcon(":/icons/Std_Placement.svg")),
        ):
            section = QtWidgets.QWidget()
            section.setWindowTitle(title)
            # the task box's header shows it
            section.setWindowIcon(icon)
            sections.append((section, QtWidgets.QFormLayout(section)))
        self.form = [section for section, _ in sections]
        self.viseForm, self.seatForm, self.positionForm = self.form
        layout = sections[0][1]
        ui = FreeCADGui.UiLoader()

        # the Job's vises, then those to add: (kind, vise or path) for each entry
        self.vise = QtWidgets.QComboBox()
        self.entries = []
        vises = PathWorkholding.vises(job)
        if not vises:
            self.addEntry(translate("CAM_AddVise", "Choose a vise…"), ("none", None))
        for each in vises:
            self.addEntry(each.Label, ("vise", each))
        # vises of other Jobs with a station free, shared: a vise of this Job's own placed with
        # theirs
        for owner in _shareable(job):
            free = PathWorkholding.freeStations(owner)
            self.addEntry(
                translate("CAM_Workholding", "%s, in %s (station %s free)")
                % (
                    owner.Label,
                    PathWorkholding.memberOf(owner)[0].Label,
                    ", ".join(str(n) for n in free),
                ),
                ("share", owner),
            )
        self.lastVise = 0
        if vise in vises or (vise is None and vises):
            self.existing = vise or vises[0]
            self.lastVise = vises.index(self.existing)
            # as its file now has it, the file open with the Job
            PathWorkholding.refreshSettings(self.existing)
        self.vise.setCurrentIndex(self.lastVise)
        self.browse = Widgets.browseButton(
            translate("CAM_Workholding", "Choose a vise on this computer or from a library")
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.vise, 1)
        row.addWidget(self.browse)
        layout.addRow(translate("CAM_SeatInVise", "Vise"), row)
        # the station of a vise of several the stock goes in: its own, or one free
        self.station = QtWidgets.QComboBox()
        self.station.setToolTip(
            translate(
                "CAM_Workholding", "The station of the vise the stock goes in, one no other Job has"
            )
        )
        self.station.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.stationLabel = QtWidgets.QLabel(translate("CAM_Workholding", "Station"))
        layout.addRow(self.stationLabel, self.station)
        # how the part sits in it: the side of the part on the vise's bottom, the floor or the
        # parallels, and the side against its fixed jaw, one of the four left
        self.seat = QtWidgets.QComboBox()
        self.seat.setToolTip(
            translate("CAM_Workholding", "The side of the part on the floor or the parallels")
        )
        self.jaw = QtWidgets.QComboBox()
        self.jaw.setToolTip(
            translate("CAM_Workholding", "The side of the part against the fixed jaw")
        )
        layout.addRow(translate("CAM_Workholding", "Bottom side"), self.seat)
        layout.addRow(translate("CAM_Workholding", "Fixed jaw side"), self.jaw)
        self.seat.currentIndexChanged.connect(self.seatChanged)
        self.jaw.currentIndexChanged.connect(self.showSeat)
        # what the sides lit on the part are
        legend = QtWidgets.QLabel(
            '<span style="color:%s">\u25a0</span> %s &nbsp; '
            '<span style="color:%s">\u25a0</span> %s'
            % (
                _hex(SEAT_COLOR),
                translate("CAM_Workholding", "Bottom"),
                _hex(JAW_FACE_COLOR),
                translate("CAM_Workholding", "Fixed jaw"),
            )
        )
        layout.addRow("", legend)
        # the jaw plates: the hard jaws, or soft jaws as thick and tall as asked, steps cut in
        # them to seat the stock on; a vise whose file does not name its plates keeps its own,
        # the choice not shown
        self.jaws = QtWidgets.QComboBox()
        self.jaws.addItem(translate("CAM_Workholding", "Hard"), "Hard")
        self.jaws.addItem(translate("CAM_Workholding", "Soft"), "Soft")
        self.jaws.addItem(translate("CAM_Workholding", "Grip"), "Grip")
        self.jaws.setToolTip(
            translate(
                "CAM_Workholding", "The vise's own hard jaws, or soft jaws to cut to the part"
            )
        )
        self.jawsLabel = QtWidgets.QLabel(translate("CAM_Workholding", "Jaws"))
        layout.addRow(self.jawsLabel, self.jaws)
        self.softThickness = Widgets.mmBox(
            ui, translate("CAM_Workholding", "How thick the soft jaws are, from the vise's jaw out")
        )
        self.softHeight = Widgets.mmBox(
            ui, translate("CAM_Workholding", "How tall the soft jaws are")
        )
        self.steps = _StepRows(
            ui,
            lambda: (
                self.softThickness.property("rawValue"),
                self.softHeight.property("rawValue"),
            ),
        )
        self.softRows = []
        for label, field in (
            (translate("CAM_Workholding", "Thickness"), self.softThickness),
            (translate("CAM_Workholding", "Height"), self.softHeight),
            (translate("CAM_Workholding", "Steps"), self.steps),
        ):
            label = QtWidgets.QLabel(label)
            layout.addRow(label, field)
            self.softRows += [label, field]
        # grip jaws: their grips, how far they stand above the jaws' tops, their teeth behind
        # the jaws' face, how far they bite into the stock, how many on each jaw
        defaults = PathJaws.GripJaw

        def length(tip, value):
            return Widgets.mmBox(ui, tip, value, step=0.01)

        self.gripHeight = length(
            translate("CAM_Workholding", "How far the grips stand above the jaws' tops: the grip"),
            defaults["grip"],
        )
        self.gripSetback = length(
            translate("CAM_Workholding", "The grips' teeth behind the jaws' face"),
            defaults["setback"],
        )
        self.gripBite = length(
            translate("CAM_Workholding", "How far the grips' teeth bite into the stock"),
            defaults["bite"],
        )
        self.gripCount = QtWidgets.QSpinBox()
        self.gripCount.setRange(1, 6)
        self.gripCount.setValue(defaults["grips"])
        self.gripCount.setToolTip(translate("CAM_Workholding", "How many grips on each jaw"))
        self.gripRows = []
        for label, field in (
            (translate("CAM_Workholding", "Grip height"), self.gripHeight),
            (translate("CAM_Workholding", "Tooth setback"), self.gripSetback),
            (translate("CAM_Workholding", "Bite"), self.gripBite),
            (translate("CAM_Workholding", "Grips"), self.gripCount),
        ):
            label = QtWidgets.QLabel(label)
            layout.addRow(label, field)
            self.gripRows += [label, field]
        self.lastJaws = None
        layout = sections[1][1]

        # what the stock stands on: the vise's floor, a pair of parallels, or a step of the jaws
        self.standsOn = QtWidgets.QComboBox()
        self.byFloor = _ComboChoice(
            self.standsOn,
            translate("CAM_SeatInVise", "On the floor"),
            "floor",
            translate("CAM_SeatInVise", "The stock on the vise's floor"),
        )
        self.byParallels = _ComboChoice(
            self.standsOn,
            translate("CAM_SeatInVise", "On parallels"),
            "parallels",
            translate("CAM_SeatInVise", "The stock on a pair of parallels, as tall as they are"),
        )
        self.byStep = _ComboChoice(
            self.standsOn,
            translate("CAM_SeatInVise", "On a step"),
            "step",
            translate("CAM_SeatInVise", "The stock on a step of the jaws, as high as it"),
        )
        self.step = QtWidgets.QComboBox()
        standsOn = QtWidgets.QHBoxLayout()
        standsOn.addWidget(self.standsOn, 3)
        standsOn.addWidget(self.step, 1)
        layout.addRow(translate("CAM_SeatInVise", "Stands on"), standsOn)
        self.standsOnLabel = layout.labelForField(standsOn)
        self.parallels = _ParallelPicker(ui)
        self.parallels.addTo(layout)
        # what it comes to, at the end of the seat: why it cannot be seated, a vise too small
        # for the stock; else the grip, how much stands above the jaws, and how far the model's
        # bottom is above them, the clearance the tools have to cut it whole
        self.fit = Widgets.Note()
        self.fit.setStyleSheet("color: %s" % ERROR_TEXT_COLOR)
        layout.addRow("", self.fit)
        self.other = Widgets.Note()
        layout.addRow("", self.other)
        self.clearance = Widgets.Note()
        self.clearance.setToolTip(
            translate(
                "CAM_SeatInVise",
                "From the jaw tops up to the bottom of the model: below them, the tools can not "
                "cut the model whole without reaching the jaws",
            )
        )
        layout.addRow("", self.clearance)
        layout = sections[2][1]

        # across the jaws: centered, or off the center by so much
        self.across = QtWidgets.QComboBox()
        self.center = _ComboChoice(self.across, translate("CAM_SeatInVise", "Centered"), "center")
        self.offCenter = _ComboChoice(
            self.across, translate("CAM_SeatInVise", "Offset from center"), "offset"
        )
        layout.addRow(translate("CAM_SeatInVise", "Across the jaws"), self.across)
        self.offset = Widgets.mmBox(
            ui, translate("CAM_SeatInVise", "Along the jaws, from their center"), minimum=-10000.0
        )
        self.offset.setEnabled(False)
        layout.addRow(translate("CAM_SeatInVise", "Offset"), self.offset)
        self.across.currentIndexChanged.connect(
            lambda *args: self.offset.setEnabled(self.offCenter.isChecked())
        )

        self.close = QtWidgets.QCheckBox(translate("CAM_SeatInVise", "Close the jaw on the stock"))
        self.close.setChecked(True)
        layout.addRow("", self.close)

        self.moves = QtWidgets.QComboBox()
        self.moveVise = _ComboChoice(
            self.moves, translate("CAM_SeatInVise", "The vise, the part stays"), "vise"
        )
        self.movePart = _ComboChoice(
            self.moves, translate("CAM_SeatInVise", "The part, the vise stays"), "part"
        )
        layout.addRow(translate("CAM_SeatInVise", "What moves"), self.moves)

        # what holds the stock, a section of its own above the rest: a vise, or stops and clamps
        holds = QtWidgets.QWidget()
        holds.setWindowTitle(translate("CAM_Workholding", "Workholding"))
        holds.setWindowIcon(QtGui.QIcon(":/icons/CAM_Job.svg"))
        holdsLayout = QtWidgets.QFormLayout(holds)
        self.holds = Widgets.combo()
        self.byVise = _ComboChoice(
            self.holds,
            translate("CAM_Workholding", "Vise"),
            "vise",
            translate("CAM_Workholding", "The stock seated in a vise"),
        )
        self.byStops = _ComboChoice(
            self.holds,
            translate("CAM_Workholding", "Stops and clamps"),
            "stops",
            translate("CAM_Workholding", "The stock on the table, pushed onto stops and clamped"),
        )
        holdsLayout.addRow(translate("CAM_Workholding", "Holds it"), self.holds)
        self.stops = _StopsClamps(self, ui)
        # the table it stands on, with the stops and clamps
        sections[1][1].addRow(self.stops.table)
        self.form = [holds] + self.form + self.stops.forms
        _alignLabels([layout for _, layout in sections] + [holdsLayout] + self.stops.layouts)

        self.vise.currentIndexChanged.connect(self.viseChanged)
        self.browse.clicked.connect(self.browseVise)
        self.standsOn.currentIndexChanged.connect(self.heightByChanged)
        self.parallels.changed.connect(self.updateOther)
        self.step.currentIndexChanged.connect(self.updateOther)
        self.jaws.currentIndexChanged.connect(self.jawsChanged)
        self.steps.changed.connect(self.stepsChanged)
        for box in (self.gripHeight, self.gripSetback, self.gripBite):
            box.valueChanged.connect(self.stepsChanged)
        for signal in (
            self.seat.currentIndexChanged,
            self.jaw.currentIndexChanged,
            self.jaws.currentIndexChanged,
            self.softThickness.valueChanged,
            self.softHeight.valueChanged,
            self.steps.changed,
            self.gripHeight.valueChanged,
            self.gripSetback.valueChanged,
            self.gripBite.valueChanged,
            self.gripCount.valueChanged,
            self.standsOn.currentIndexChanged,
            self.step.currentIndexChanged,
            self.parallels.changed,
            self.across.currentIndexChanged,
            self.offset.valueChanged,
            self.close.toggled,
            self.moves.currentIndexChanged,
            self.station.currentIndexChanged,
        ):
            signal.connect(self.changed)
        self.updateGrip()
        # what the Job's Workholding holds: a vise, else stops and clamps, else a vise to add
        stopsFirst = piece is not None or (vise is None and not vises and Items.itemsOf(job))
        (self.byStops if stopsFirst else self.byVise).setChecked(True)
        self.stops.readIn()
        if piece is not None:
            self.stops.fillList(PathWorkholding.memberOf(piece)[1])
        self.holds.currentIndexChanged.connect(self.holdsChanged)
        self.holdsChanged()
        # the sections in their task boxes by then, hidden whole
        QtCore.QTimer.singleShot(0, self.holdsChanged)

    def open(self):
        self.holdsChanged()

    def holdsChanged(self, *args):
        """The sections of what holds the stock shown: the vise's, or the stops' and clamps'; the
        stock's for both, what it stands on as they have it, the vise's floor, its parallels or a
        step, or the table."""
        stops = self.byStops.isChecked()
        for form in (self.viseForm, self.positionForm):
            _showSection(form, not stops)
        for form in self.stops.forms:
            _showSection(form, stops)
        self.stops.table.setVisible(stops)
        for widget in (self.standsOnLabel, self.standsOn):
            widget.setVisible(not stops)
        for note in (self.fit, self.other, self.clearance):
            note.setVisible(not stops and bool(note.text()))
        if stops:
            self.parallels.setShown(False)
            self.step.setVisible(False)
            self.seatFaces.hide()
            return
        self.heightByChanged()
        job, vise = self.current()
        if vise is not None:
            self.updateFit()
            self.showSeat()

    def begin(self):
        """The step the stops' and clamps' changes go into, opened if it is not: pending until
        OK or Apply keep it, Cancel undoes it."""
        if not self.adding and not self.pending:
            self.job.Document.openTransaction(translate("CAM_Workholding", "Stops and clamps"))
            self.pending = True

    def applyStops(self):
        """The stops and clamps as the panel says, kept: an undoable step of its own, or part of
        a vise's add."""
        if not self.stops.preview():
            Path.Log.error(self.stops.error.text())
            return False
        if self.pending:
            self.job.Document.commitTransaction()
            self.pending = False
        return True

    def fileEntry(self, path):
        """Where the vise's file at path is in the list, None if it is not."""
        for i, (kind, value) in enumerate(self.entries):
            if kind == "file" and os.path.realpath(value) == os.path.realpath(path):
                return i
        return None

    def addEntry(self, label, entry, index=None):
        if index is None:
            index = self.vise.count()
        self.vise.insertItem(index, label)
        self.entries.insert(index, entry)

    def current(self):
        """The Job and the vise to seat its stock in, None if none is chosen."""
        if self.adding:
            return self.job, self.adding.vise
        return self.job, self.existing

    def viseChanged(self, index):
        """A vise the Job has, the one being added dropped; another Job's shared; or the one
        being added again."""
        kind, value = self.entries[index]
        if kind == "vise":
            if self.adding:
                self.adding.finish(keep=False)
                self.adding = None
            self.existing = value
            PathWorkholding.refreshSettings(value)
            self.lastVise = index
            self.updateGrip()
            return
        if kind == "share":
            self.shareChanged(index, value)
            return
        if kind == "file":
            self.addFile(value)
            return
        self.vise.blockSignals(True)
        self.vise.setCurrentIndex(self.lastVise)
        self.vise.blockSignals(False)

    def browseVise(self):
        """A vise chosen in the browser, on this computer or from a library, added in the place
        of the one being added."""
        import Path.Workholding.Gui.Library as LibraryGui

        path = LibraryGui.getVise()
        if path:
            self.addFile(path)

    def addFile(self, path):
        """The vise in the file at path added, in the place of the one being added: listed and
        chosen, seated on the stock as it comes in. In a document not saved, refused: its parts
        are linked."""
        if not self.job.Document.FileName:
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(),
                translate("CAM_AddVise", "Add Vise"),
                translate(
                    "CAM_AddVise",
                    "Save the document first: the vise's parts are linked from its own file.",
                ),
            )
            path = None
        if path:
            if not self.adding:
                # the add's transaction keeps what was seated before it
                self.pending = False
            adding = self.adding or _Adding(self.job)
            try:
                adding.put(path)
                self.adding = adding
                self.existing = None
                self.chooseSide = True
                self.fresh = True
            except ValueError as e:
                if adding.vise is None:
                    adding.finish(keep=False)
                QtWidgets.QMessageBox.warning(
                    FreeCADGui.getMainWindow(), translate("CAM_AddVise", "Add Vise"), str(e)
                )
                path = None
        self.vise.blockSignals(True)
        if path:
            found = self.fileEntry(path)
            if found is None:
                # the one being added in place of another being added
                for i in reversed(range(len(self.entries))):
                    if self.entries[i][0] == "file":
                        self.vise.removeItem(i)
                        self.entries.pop(i)
                self.addEntry(self.adding.vise.Label, ("file", path))
                found = self.vise.count() - 1
            self.vise.setCurrentIndex(found)
            self.lastVise = found
        else:
            self.vise.setCurrentIndex(self.lastVise)
        self.vise.blockSignals(False)
        if path:
            self.updateGrip()
            # seated on the stock as it comes in
            self.preview()

    def shareChanged(self, index, owner):
        """A vise of another Job shared, in the place of the one being added."""
        if not self.adding:
            # the add's transaction keeps what was seated before it
            self.pending = False
        adding = self.adding or _Adding(self.job)
        try:
            adding.share(owner)
        except ValueError as e:
            if adding.vise is None:
                adding.finish(keep=False)
                if adding is self.adding:
                    self.adding = None
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(), translate("CAM_AddVise", "Add Vise"), str(e)
            )
            self.vise.blockSignals(True)
            self.vise.setCurrentIndex(self.lastVise)
            self.vise.blockSignals(False)
            return
        self.adding = adding
        self.existing = None
        # placed where the owner is: turned as it is, the part moving to it
        self.chooseSide = False
        self.fresh = True
        self.lastVise = index
        self.updateGrip()
        self.preview()

    def jawHeight(self):
        job, vise = self.current()
        if vise is None:
            return None
        frame = PathWorkholding.jawFrame(vise)
        if frame is None:
            return None
        # from the floor to the jaw tops: the grip is from them
        return frame["top"] - frame["floor"]

    def heightByChanged(self, *args):
        """The parallels shown when the stock stands on them, the step chosen on a step."""
        self.parallels.setShown(self.byParallels.isChecked())
        self.step.setVisible(self.byStep.isChecked())
        self.updateOther()

    def extents(self):
        """The stock's bottom and top and the model's bottom, up the vise from its origin; None
        without a vise."""
        job, vise = self.current()
        if vise is None:
            return None
        inverse = PathWorkholding.stationPlacement(vise).inverse().toMatrix()

        def box(shape):
            return shape.transformed(inverse).BoundBox

        stock = box(job.Stock.Shape)
        models = [
            box(m.Shape)
            for m in getattr(job.Model, "Group", [])
            if hasattr(m, "Shape") and not m.Shape.isNull()
        ]
        model = min((b.ZMin for b in models), default=stock.ZMin)
        return stock.ZMin, stock.ZMax, model

    def stockHeight(self):
        """How tall the stock stands in the vise, None without one."""
        extents = self.extents()
        return extents[1] - extents[0] if extents else None

    def updateOther(self, *args):
        """What the stock's seat comes to: how much of it the jaws grip, how much stands above
        them, and the clearance from the jaw tops up to the model's bottom."""
        job, vise = self.current()
        frame = PathWorkholding.jawFrame(vise) if vise is not None else None
        extents = self.extents()
        self.clearance.setText("")
        if frame is None or extents is None:
            self.other.setText("")
            return
        tall = extents[1] - extents[0]
        top = frame["top"]
        if self.byStep.isChecked():
            steps = self.chosenSteps(quiet=True)
            i = self.step.currentIndex()
            if steps is None or not 0 <= i < len(steps):
                self.other.setText("")
                return
            bottom = top - steps[i][0]
            gripTop = top
        else:
            bottom = frame["floor"]
            if self.byParallels.isChecked():
                kit = self.parallels.chosen()
                if kit is None:
                    self.other.setText(translate("CAM_SeatInVise", "Choose a pair of parallels"))
                    return
                bottom += kit.height
            gripTop = top
        grip = min(gripTop - bottom, tall)
        if grip <= 0:
            self.other.setText(
                translate("CAM_SeatInVise", "The parallels stand above the jaws: nothing gripped")
            )
            return
        self.other.setText(
            translate("CAM_SeatInVise", "Gripping %s, %s above the jaws")
            % (userLength(grip), userLength(max(0.0, bottom + tall - top)))
        )
        # the model where it will be, as far up from the stock's bottom as it is now
        clearance = bottom + (extents[2] - extents[0]) - top
        if clearance >= -1e-6:
            self.clearance.setStyleSheet("color: %s" % CLEAR_TEXT_COLOR)
            self.clearance.setText(
                translate("CAM_SeatInVise", "Clearance %s: the model is clear of the jaws")
                % userLength(clearance)
            )
        else:
            self.clearance.setStyleSheet("color: %s" % NOT_CLEAR_TEXT_COLOR)
            self.clearance.setText(
                translate("CAM_SeatInVise", "Clearance %s: the model goes below the jaw tops")
                % userLength(clearance)
            )

    def jawsChanged(self, *args):
        """The rows of the jaws chosen shown: soft jaws' size and steps, grip jaws' size and
        grips; and the steps to seat on. grip jaws chosen anew start the common size, the
        stock on them."""
        kind = self.jaws.currentData()
        for i, widget in enumerate(self.softRows):
            # thickness and height, then the steps, soft jaws' own
            widget.setVisible(kind == "Soft" or (kind == "Grip" and i < 4))
        for widget in self.gripRows:
            widget.setVisible(kind == "Grip")
        anew = kind == "Grip" and self.lastJaws not in (None, "Grip")
        if anew:
            self.softThickness.setProperty("rawValue", PathJaws.GripJaw["thickness"])
            self.softHeight.setProperty("rawValue", PathJaws.GripJaw["height"])
        self.lastJaws = kind
        self.stepsChanged()
        if anew and not self.loading:
            self.byStep.setChecked(True)

    def stepsChanged(self, *args):
        """A step to seat on for each step the jaws have, the one chosen kept if it still
        is; none, nothing on a step, the grip again."""
        steps = self.chosenSteps(quiet=True)
        if steps is None:
            # half typed: as it was until it reads
            return
        chosen = self.step.currentIndex()
        self.step.blockSignals(True)
        self.step.clear()
        for i in range(len(steps)):
            self.step.addItem(translate("CAM_SeatInVise", "Step %d") % (i + 1))
        self.step.setCurrentIndex(min(max(chosen, 0), len(steps) - 1))
        self.step.blockSignals(False)
        self.byStep.setEnabled(bool(steps))
        if not steps and self.byStep.isChecked():
            self.byFloor.setChecked(True)
        self.heightByChanged()

    def chosenSteps(self, quiet=False):
        """The steps the panel says the soft jaws have, (down, in) in mm; for hard jaws, those
        they have of their own."""
        kind = self.jaws.currentData()
        if kind == "Grip":
            # the stock on the jaws' tops, as deep as the grips stand, held by their teeth
            return [
                (
                    self.gripHeight.property("rawValue"),
                    self.gripSetback.property("rawValue") + self.gripBite.property("rawValue"),
                )
            ]
        if kind != "Soft":
            job, vise = self.current()
            return PathWorkholding.builtInSteps(vise) if vise is not None else []
        return self.steps.steps()

    def chosenJaws(self):
        """The jaws the panel says, (kind, thickness, height, steps), mm, as setJaws takes them:
        a thickness or height of nothing leaves the vise's own."""
        kind = self.jaws.currentData()
        if kind not in ("Soft", "Grip"):
            return kind, None, None, None, None
        thickness = self.softThickness.property("rawValue")
        height = self.softHeight.property("rawValue")
        gripJaws = None
        if kind == "Grip":
            gripJaws = {
                "grip": self.gripHeight.property("rawValue"),
                "setback": self.gripSetback.property("rawValue"),
                "bite": self.gripBite.property("rawValue"),
                "grips": self.gripCount.value(),
            }
        return (
            kind,
            thickness if thickness > 0 else None,
            height if height > 0 else None,
            self.steps.steps() if kind == "Soft" else None,
            gripJaws,
        )

    def putJaws(self, vise):
        """The vise's jaws swapped for those the panel says, if they differ: True if they were."""
        if not _canChangeJaws(vise):
            return False
        kind, thickness, height, steps, gripJaws = self.chosenJaws()
        nowKind, nowThickness, nowHeight, nowSteps = _jawsOf(vise)
        nowGrip = PathWorkholding.gripJawsOf(vise) or {}

        def differs(value, now):
            return value is not None and (now is None or abs(value - now) > 1e-6)

        same = kind == nowKind and (
            kind not in ("Soft", "Grip")
            or not (differs(thickness, nowThickness) or differs(height, nowHeight))
        )
        if same and kind == "Soft":
            same = len(steps) == len(nowSteps) and not any(
                differs(h, nh) or differs(d, nd) for (h, d), (nh, nd) in zip(steps, nowSteps)
            )
        if same and kind == "Grip":
            same = not any(differs(gripJaws[k], nowGrip.get(k)) for k in gripJaws)
        if same:
            return False
        PathWorkholding.setJaws(
            vise, kind, thickness=thickness, height=height, steps=steps, gripJaws=gripJaws
        )
        return True

    def readJaws(self, vise):
        """The vise's jaws in the panel; a vise that cannot change them keeps its own hard
        jaws, the choice hidden."""
        can = _canChangeJaws(vise)
        kind, thickness, height, steps = _jawsOf(vise) if can else ("Hard", None, None, [])
        size = PathWorkholding.plateSize(vise) if can and thickness is None else None
        if size:
            # never soft: soft jaws start the size of the plates
            thickness, height = size[:2]
        # the jaws' row only for a vise that can change them
        self.jaws.setVisible(can)
        self.jawsLabel.setVisible(can)
        self.jaws.setCurrentIndex(max(0, self.jaws.findData(kind)))
        if thickness is not None:
            self.softThickness.setProperty("rawValue", thickness)
        if height is not None:
            self.softHeight.setProperty("rawValue", height)
        self.steps.setSteps(steps)
        gripJaws = PathWorkholding.gripJawsOf(vise) if can else None
        if gripJaws:
            self.gripHeight.setProperty("rawValue", gripJaws["grip"])
            self.gripSetback.setProperty("rawValue", gripJaws["setback"])
            self.gripBite.setProperty("rawValue", gripJaws["bite"])
            self.gripCount.setValue(gripJaws["grips"])
        self.lastJaws = kind
        self.jawsChanged()

    def updateFit(self):
        """Whether the vise opens far enough for the stock, and if turned it would."""
        job, vise = self.current()
        needed, most, turned = PathWorkholding.opening(job, vise)
        if most is None or needed <= most + 1e-6:
            self.fit.setText("")
            return

        text = translate(
            "CAM_SeatInVise", "This vise opens %s: too little for the stock, %s between the jaws."
        ) % (userLength(most), userLength(needed))
        if turned <= most + 1e-6:
            text += " " + translate("CAM_SeatInVise", "Turned a quarter round, it would fit.")
        self.fit.setText(text)

    def showOrientation(self, turn, choose=False):
        """How the part sits in the vise turned so, (up, fixed), in the two boxes, or None,
        turned some other way; with choose, nothing chosen yet. The side on the bottom faces
        away from the vise's top, the side against the fixed jaw toward it."""
        self.seat.blockSignals(True)
        self.seat.clear()
        if choose:
            self.seat.addItem(translate("CAM_Workholding", "Choose a side…"), None)
        elif turn is None:
            self.seat.addItem(translate("CAM_Workholding", "As it is"), None)
        for label, direction in Widgets.sides():
            self.seat.addItem(label, direction)
        chosen = self.seat.findData(_opposite(turn[0])) if turn and not choose else 0
        self.seat.setCurrentIndex(chosen)
        self.seat.blockSignals(False)
        self.seatChanged(jaw=turn[1] if turn else None)

    def seatChanged(self, *args, jaw=None):
        """The sides that can be against the fixed jaw, square to the one on the bottom: the one
        there was if it still can."""
        seat = self.seat.currentData()
        if seat is not None:
            self.chooseSide = False
        keep = jaw or self.jaw.currentData() or self.jawNow()
        self.jaw.clear()
        # which side is against the fixed jaw waits on which is on the bottom
        self.jaw.setEnabled(seat is not None)
        if seat is None:
            self.jaw.addItem(translate("CAM_Workholding", "As it is"), None)
            return
        for label, direction in Widgets.sides():
            if (
                abs(PathWorkholding.Directions[direction].dot(PathWorkholding.Directions[seat]))
                < 1e-9
            ):
                self.jaw.addItem(label, direction)
        found = self.jaw.findData(keep)
        self.jaw.setCurrentIndex(found if found >= 0 else 0)

    def jawNow(self):
        """The side of the part against the fixed jaw as the vise is turned now."""
        job, vise = self.current()
        if vise is None:
            return None
        turn = PathWorkholding.orientationOf(
            PathWorkholding.partTurn(job)
            .inverted()
            .multiply(PathWorkholding.stationPlacement(vise).Rotation)
        )
        return turn[1] if turn else None

    def showSeat(self, *args):
        """The two sides lit as chosen, or as the vise holds the part now."""
        job, vise = self.current()
        if vise is None:
            self.seatFaces.hide()
            return
        seat, jaw = self.seat.currentData(), self.jaw.currentData()
        if seat and jaw:
            # the part's own sides, where they are as it is turned
            part = PathWorkholding.partTurn(job)
            seat = part.multVec(PathWorkholding.Directions[seat])
            jaw = part.multVec(PathWorkholding.Directions[jaw])
        else:
            turn = PathWorkholding.stationPlacement(vise).Rotation
            seat = turn.multVec(FreeCAD.Vector(0, 0, -1))
            jaw = turn.multVec(FreeCAD.Vector(0, 1, 0))
        self.seatFaces.show(job, seat, jaw, vise)

    def turn(self):
        """The turn chosen, None to leave it as it is."""
        seat, jaw = self.seat.currentData(), self.jaw.currentData()
        if not (seat and jaw):
            return None
        return PathWorkholding.orientation(_opposite(seat), jaw)

    def changed(self, *args):
        """Something the panel says changed: seated so a moment after, not as it is read in."""
        if not self.loading:
            self.previewTimer.start()

    def preview(self):
        """Seated as the panel says, pending: True if it could be."""
        self.previewTimer.stop()
        job, vise = self.current()
        if vise is None:
            return False
        doc = job.Document
        if not self.adding and not self.pending:
            doc.openTransaction(translate("CAM_SeatInVise", "Seat in vise"))
            self.pending = True
        # on a step, the step only; on parallels, the pair; on the floor, parallels of no height;
        # a vise that does not say how tall its jaws are, as the stock stands
        on = {}
        if self.byStep.isChecked():
            on["step"] = self.step.currentIndex() + 1
        elif self.byParallels.isChecked():
            on["parallels"] = self.parallels.chosen()
            if on["parallels"] is None:
                self.fit.setText(translate("CAM_SeatInVise", "Choose a pair of parallels"))
                return False
        elif self.jawHeight() is not None:
            on["parallels"] = 0.0
        try:
            # the station first, then the jaws: the step is cut in them
            number = self.station.currentData()
            if number is not None and number != PathWorkholding.station(vise):
                PathWorkholding.setStation(vise, number)
            self.putJaws(vise)
            self.done = PathWorkholding.seat(
                job,
                vise,
                offset=self.offset.property("rawValue") if self.offCenter.isChecked() else 0.0,
                center=True,
                close=self.close.isChecked(),
                moveVise=self.moveVise.isChecked(),
                rotation=self.turn(),
                quiet=True,
                **on,
            )
        except ValueError as e:
            # why not, in place of what it would come to
            self.fit.setText(str(e))
            self.other.setText("")
            self.clearance.setText("")
            return False
        self.updateFit()
        self.showSeat()
        # what it comes to, as seated: the jaws now as chosen
        self.updateOther()
        return True

    def updateGrip(self):
        """The stock as it sits in the vise now, to start from: for a vise the Job has, as it
        was seated too, on parallels or not, off the center, the jaw closed or not. Read in, not
        a change to seat it by."""
        self.loading = True
        try:
            self.readIn()
        finally:
            self.loading = False

    def readIn(self):
        job, vise = self.current()
        self.readJaws(vise)
        self.readStation(vise)
        if vise is None:
            self.fit.setText("")
            self.updateOther()
            self.seat.setEnabled(False)
            self.jaw.setEnabled(False)
            self.showSeat()
            return
        # a vise shared with other Jobs stays where it is, turned as it is: their parts are in
        # it, so the part moves to it, and turns in it
        shared = self.shared()
        self.seat.setEnabled(True)
        if shared:
            self.movePart.setChecked(True)
        self.moves.setEnabled(not shared)
        self.updateFit()
        now = PathWorkholding.seating(job, vise)
        jaw = self.jawHeight()
        # parallels for a vise that takes them and says how tall its jaws are
        takes = PathWorkholding.takesParallels(vise)
        self.byParallels.setVisible(takes)
        self.byParallels.setEnabled(takes and jaw is not None)
        self.showOrientation(now["orientation"], choose=self.chooseSide)
        self.showSeat()
        step = now.get("step", 0)
        if self.adding and self.fresh:
            # one just added starts as a vise does, not as the last one was seated: centered,
            # the jaw closed, the stock on the floor, or on parallels holding half of a stock
            # shorter than the jaws
            self.center.setChecked(True)
            self.offset.setProperty("rawValue", 0.0)
            self.close.setChecked(True)
            tall = self.stockHeight()
            onParallels = False
            if self.byParallels.isEnabled() and tall is not None and tall < jaw:
                onParallels = self.parallels.pickNear(jaw - tall / 2)
            (self.byParallels if onParallels else self.byFloor).setChecked(True)
        self.fresh = False
        if not self.adding:
            thick, long = PathParallels.DefaultThickness, PathParallels.DefaultLength
            if step and self.byStep.isEnabled():
                self.byStep.setChecked(True)
                self.step.setCurrentIndex(min(step, self.step.count()) - 1)
            elif now["onParallels"] and self.byParallels.isEnabled():
                self.byParallels.setChecked(True)
                self.parallels.showPair(
                    vise.Parallels.Value,
                    getattr(vise, "ParallelThickness", FreeCAD.Units.Quantity(thick)).Value,
                    getattr(vise, "ParallelLength", FreeCAD.Units.Quantity(long)).Value,
                    getattr(vise, "ParallelsCuttable", False),
                    getattr(vise, "ParallelSet", ""),
                )
            elif self.byParallels.isEnabled() and now["grip"] < jaw - 1e-3:
                # held by the grip alone, as vises once were: on parallels that hold it there
                self.byParallels.setChecked(True)
                self.parallels.showPair(jaw - max(0.0, now["grip"]), thick, long, False, "")
            else:
                self.byFloor.setChecked(True)
            offCenter = abs(now["offset"]) > 1e-6
            (self.offCenter if offCenter else self.center).setChecked(True)
            self.offset.setProperty("rawValue", now["offset"] if offCenter else 0.0)
            self.close.setChecked(now["close"])
        if not self.byParallels.isEnabled() and self.byParallels.isChecked():
            self.byFloor.setChecked(True)
        self.heightByChanged()

    def shared(self):
        """Whether the vise chosen is shared with other Jobs: placed and turned for all of them,
        their parts moving to it."""
        job, vise = self.current()
        return vise is not None and PathWorkholding.isShared(vise)

    def readStation(self, vise):
        """The stations the stock can go in: the vise's own, and those no other Job has; the
        choice shown only for a vise of more than one."""
        count = len(PathWorkholding.stations(vise)) if vise is not None else 1
        self.station.blockSignals(True)
        self.station.clear()
        if count > 1:
            now = PathWorkholding.station(vise)
            for number in sorted({now} | set(PathWorkholding.freeStations(vise))):
                self.station.addItem(translate("CAM_Workholding", "Station %d") % number, number)
            self.station.setCurrentIndex(self.station.findData(now))
        self.station.blockSignals(False)
        self.station.setVisible(count > 1)
        self.stationLabel.setVisible(count > 1)

    def getStandardButtons(self):
        return (
            QtWidgets.QDialogButtonBox.Ok
            | QtWidgets.QDialogButtonBox.Apply
            | QtWidgets.QDialogButtonBox.Cancel
        )

    def clicked(self, button):
        if button == QtWidgets.QDialogButtonBox.Apply:
            if self.byStops.isChecked():
                if self.applyStops():
                    self.stops.readIn()
            elif self.apply():
                # on from where it now is
                self.updateGrip()

    def accept(self):
        if self.applyStops() if self.byStops.isChecked() else self.apply():
            self.seatFaces.hide()
            FreeCADGui.Control.closeDialog()
            if self.adding:
                self.adding.finish(keep=True)
            self.stops.finish()
            return True
        return False

    def apply(self):
        """Seated as the panel says, kept: an undoable step of its own, or part of the add."""
        job, vise = self.current()
        if vise is None:
            Path.Log.error(translate("CAM_AddVise", "Choose a vise to add"))
            return False
        if not self.preview():
            Path.Log.error(self.fit.text())
            return False
        if self.pending:
            job.Document.commitTransaction()
            self.pending = False
        done = self.done
        Path.Log.info(
            translate("CAM_SeatInVise", "%s seated: moved (%s), gripped %s, opening %s")
            % (
                vise.Label,
                ", ".join(userLength(c) for c in done["move"]),
                userLength(done["grip"]),
                userLength(done["opening"]),
            )
        )
        return True

    def reject(self):
        self.previewTimer.stop()
        self.stops.timer.stop()
        self.seatFaces.hide()
        if self.pending:
            # what the preview seated, undone
            self.job.Document.abortTransaction()
            self.job.Document.recompute()
            self.pending = False
        FreeCADGui.Control.closeDialog()
        if self.adding:
            # the vise, and any seating of it, undone with no trace in the undo list
            self.adding.finish(keep=False)
        self.stops.finish()
        return True
