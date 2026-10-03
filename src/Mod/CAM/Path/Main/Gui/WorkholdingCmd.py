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

"""Seat a Job's stock in a vise of its Workholding: against the fixed jaw, held as deep as asked,
across the jaws as asked, the moving jaw closed on it. Add a vise from its own file, and another
of a piece of workholding beside it."""

import os
import re
import zipfile

from xml.etree import ElementTree

import FreeCAD
import Path
import Path.Main.Workholding as PathWorkholding
import Path.Main.WorkholdingJaws as PathJaws
import Path.Main.WorkholdingParallels as PathParallels
import Path.Preferences

from PySide.QtCore import QT_TRANSLATE_NOOP

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore, QtGui, QtWidgets

translate = FreeCAD.Qt.translate


def _jobs():
    import Path.Main.Job as PathJob

    if FreeCAD.ActiveDocument is None:
        return []
    return [
        o
        for o in FreeCAD.ActiveDocument.Objects
        if hasattr(o, "Proxy") and isinstance(o.Proxy, PathJob.ObjectJob)
    ]


def _length(value):
    """A length in mm, as the document's units show it."""
    return FreeCAD.Units.Quantity(value, FreeCAD.Units.Length).UserString


def _prefs():
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/CAM")


def _viseLabel(path):
    """The label of the vise a vise's file holds, read from the file without opening it as a
    document; None if it holds no vise: no part, or no VarSet with an Opening."""
    try:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("Document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return None
    types = {o.get("name"): o.get("type") for o in root.iter("Object") if o.get("type")}
    labels = {}
    opening = False
    data = root.find("ObjectData")
    for obj in data.findall("Object") if data is not None else []:
        name = obj.get("name")
        for prop in obj.iter("Property"):
            if prop.get("name") == "Label" and prop.find("String") is not None:
                labels[name] = prop.find("String").get("value")
            elif prop.get("name") == "Opening" and types.get(name) == "App::VarSet":
                opening = True
    parts = [name for name, kind in types.items() if kind == "App::Part"]
    if not opening or not parts:
        return None
    return labels.get(parts[0], parts[0])


def _library():
    """The vises to choose from, as (label, path), by label: the vise files in the CAM assets'
    Workholding folder and in the folder the last was added from."""
    folders = [str(Path.Preferences.getAssetPath() / "Workholding")]
    folders.append(_prefs().GetString("WorkholdingDir", ""))
    seen = set()
    vises = []
    for folder in folders:
        if not folder or not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if not name.lower().endswith(".fcstd") or os.path.realpath(path) in seen:
                continue
            seen.add(os.path.realpath(path))
            label = _viseLabel(path)
            if label is not None:
                vises.append((label, path))
    return sorted(vises, key=lambda v: v[0].lower())


def _closeIfUnused(doc):
    """The file of a vise closed if it is open only for vises' links that are gone: in no window,
    and no other document linking to it."""
    if doc.Name not in FreeCAD.listDocuments():
        return
    if any(
        doc in other.getDependentDocuments(False)
        for other in FreeCAD.listDocuments().values()
        if other != doc
    ):
        return
    gui = FreeCADGui.getDocument(doc.Name)
    if gui is not None and gui.mdiViewsOfType("Gui::View3DInventor"):
        return
    FreeCAD.closeDocument(doc.Name)


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
        source, opened = _openVise(path, self.job)
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
        _prefs().SetString("WorkholdingDir", os.path.dirname(path))
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


def _themedIcon(resource, size=32):
    """A black icon of the Job panel's, white on a dark theme as the Job panel shows it."""
    import Path.Base.Gui.Theme as PathGuiTheme

    if not PathGuiTheme.is_dark_theme():
        return QtGui.QIcon(resource)
    f = QtCore.QFile(resource)
    if not f.open(QtCore.QFile.ReadOnly):
        return QtGui.QIcon(resource)
    # black and white swapped
    content = bytes(f.readAll())
    content = content.replace(b"#111111", b"#d33d3d").replace(b"#ffffff", b"#111111")
    content = content.replace(b"#d33d3d", b"#ffffff")
    f.close()
    from PySide import QtSvg

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    QtSvg.QSvgRenderer(QtCore.QByteArray(content)).render(painter)
    painter.end()
    return QtGui.QIcon(pixmap)


class _SeatFaces:
    """The part's sides lit as the vise holds it: the one on the bottom, the one against the
    fixed jaw. Drawn over the stock, nothing in the document."""

    seat = (0.20, 0.75, 0.25)
    jaw = (1.00, 0.55, 0.00)

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
        for direction, colour in ((seat, self.seat), (jaw, self.jaw)):
            for face in job.Stock.Shape.Faces:
                if _facing(face, direction):
                    root.addChild(_drawn(face, direction, colour))
        if vise is not None:
            for corners, normal, colour in _viseFaces(vise):
                root.addChild(_drawnQuad(corners, normal, colour))
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


def _jawFrame(vise):
    """The vise's jaws in its own frame, as jawFrame says them; for a vise it cannot, its hard
    jaws from its settings. None if the vise does not say how tall its jaws are."""
    jawFrame = getattr(PathWorkholding, "jawFrame", None)
    frame = jawFrame(vise) if jawFrame is not None else None
    if frame:
        return frame
    height = PathWorkholding.viseSetup(vise)["jawHeight"]
    if height is None:
        return None
    width = getattr(vise, "JawWidth", None)
    return {
        "kind": "Hard",
        "face": 0.0,
        "top": 0.0,
        "floor": -height,
        "steps": [],
        "gapLoss": 0.0,
        "width": width.Value if width is not None else 100.0,
    }


def _viseFaces(vise):
    """The vise's seat and fixed jaw face where it stands, as (corners, normal, colour): the
    seat the floor, the parallels' tops or the step it is on, from the fixed jaw out to the
    moving one; the fixed jaw's face, or the step's wall, across the jaws and down from the top
    of the face, or of the jaws for a step, to the seat. Every vise is laid out so."""
    frame = _jawFrame(vise)
    if frame is None or frame["floor"] is None:
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
            _SeatFaces.seat,
        ),
        (
            placed(
                [(-half, fixed, top), (half, fixed, top), (half, fixed, seat), (-half, fixed, seat)]
            ),
            toward,
            _SeatFaces.jaw,
        ),
    ]


def _drawnQuad(corners, normal, colour):
    """A four cornered face as Coin draws it, a little off along normal."""
    from pivy import coin

    lift = normal * 0.05
    node = coin.SoSeparator()
    material = coin.SoMaterial()
    material.diffuseColor = colour
    material.emissiveColor = tuple(c * 0.5 for c in colour)
    material.transparency = 0.3
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


def _drawn(face, direction, colour):
    """face as Coin draws it, a little off the stock along direction so it shows over it."""
    from pivy import coin

    points, triangles = face.tessellate(0.1)
    lift = direction * 0.05
    node = coin.SoSeparator()
    material = coin.SoMaterial()
    material.diffuseColor = colour
    material.emissiveColor = tuple(c * 0.5 for c in colour)
    material.transparency = 0.3
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


def _sides():
    """The sides of a part, as the view cube names them, and the Job's axis each faces out."""
    return [
        (translate("CAM_Vise", "Bottom"), "-Z"),
        (translate("CAM_Vise", "Top"), "+Z"),
        (translate("CAM_Vise", "Front"), "-Y"),
        (translate("CAM_Vise", "Back"), "+Y"),
        (translate("CAM_Vise", "Left"), "-X"),
        (translate("CAM_Vise", "Right"), "+X"),
    ]


def _opposite(direction):
    return ("-" if direction[0] == "+" else "+") + direction[1]


def _canChangeJaws(vise):
    """Whether the vise's jaw plates can be swapped: its file names them."""
    can = getattr(PathWorkholding, "canChangeJaws", None)
    return vise is not None and can is not None and can(vise)


def _jawsOf(vise):
    """The vise's jaws as they are: their kind, the soft jaws' thickness and height in mm (None
    where it does not say) and their steps, (height, depth) in mm."""
    thickness = getattr(vise, "SoftThickness", None)
    height = getattr(vise, "SoftHeight", None)
    steps = []
    for entry in getattr(vise, "Steps", []) or []:
        try:
            h, d = (float(v) for v in entry.split(","))
        except ValueError:
            continue
        steps.append((h, d))
    return (
        getattr(vise, "Jaws", "Hard"),
        thickness.Value if thickness is not None else None,
        height.Value if height is not None else None,
        steps,
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
            [translate("CAM_Vise", "Down"), translate("CAM_Vise", "In")]
        )
        self.table.horizontalHeaderItem(0).setToolTip(
            translate("CAM_Vise", "From the soft jaws' top down to the step's floor")
        )
        self.table.horizontalHeaderItem(1).setToolTip(
            translate("CAM_Vise", "From the soft jaws' face in to the step's wall")
        )
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        layout.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        add = QtWidgets.QToolButton()
        add.setText("+")
        add.setToolTip(translate("CAM_Vise", "Another step cut in the soft jaws"))
        add.clicked.connect(self.addStep)
        remove = QtWidgets.QToolButton()
        remove.setText("\u2212")
        remove.setToolTip(translate("CAM_Vise", "Take the chosen step away, else the last"))
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
            box = self.ui.createWidget("Gui::QuantitySpinBox")
            box.setProperty("unit", "mm")
            # a tenth of the shown unit a click: steps are small
            box.setProperty("singleStep", 0.1)
            box.setProperty("rawValue", value)
            box.valueChanged.connect(lambda *args: self.changed.emit())
            self.table.setCellWidget(row, column, box)
        self.renumber()
        self.fitHeight()

    def renumber(self):
        self.table.setVerticalHeaderLabels(
            [translate("CAM_Vise", "Step %d") % (i + 1) for i in range(self.table.rowCount())]
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


class _Note(QtWidgets.QLabel if FreeCAD.GuiUp else object):
    """A line of the panel saying how things stand: wrapped, and gone while it says nothing."""

    def __init__(self):
        super().__init__()
        self.setWordWrap(True)
        self.setVisible(False)

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


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
    """A heading in a drop-down's list, not picked: bold and greyed."""
    combo.addItem(text)
    item = combo.model().item(combo.count() - 1)
    item.setEnabled(False)
    font = item.font()
    font.setBold(True)
    item.setFont(font)


class _ComboChoice:
    """One choice of a drop-down, asked and set as a radio button is: checked when it is the
    one picked, greyed or left out of the list."""

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
        self.sets = PathParallels.catalogue()
        self.set = QtWidgets.QComboBox()
        self.set.setToolTip(
            translate("CAM_Vise", "The set of parallels: its type, thickness and length")
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
        self.set.addItem(translate("CAM_Vise", "Custom\u2026"), "custom")
        self.heights = QtWidgets.QComboBox()
        self.heights.setToolTip(translate("CAM_Vise", "How tall the pair is"))
        # both drop down below themselves, as a list, whatever the style: some open over the
        # one picked, part of the list above
        for combo in (self.set, self.heights):
            combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
            combo.setMaxVisibleItems(16)
        self.pair = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.pair)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.set, 3)
        row.addWidget(self.heights, 1)

        def box(tip, value):
            b = ui.createWidget("Gui::QuantitySpinBox")
            b.setProperty("unit", "mm")
            b.setProperty("rawValue", value)
            b.setToolTip(tip)
            b.valueChanged.connect(lambda *args: self.changed.emit())
            return b

        inch = PathParallels.INCH
        self.height = box(translate("CAM_Vise", "How tall the parallels are"), inch)
        self.thickness = box(translate("CAM_Vise", "How thick each parallel is"), inch / 8)
        self.length = box(
            translate("CAM_Vise", "How long the parallels are, across the jaws"), 6 * inch
        )
        self.soft = QtWidgets.QComboBox()
        self.soft.addItem(translate("CAM_Vise", "Hard, steel"), False)
        self.soft.addItem(translate("CAM_Vise", "Soft, aluminium or plastic"), True)
        self.soft.setToolTip(
            translate(
                "CAM_Vise",
                "A tool cutting soft parallels is warned of; hard, steel ones are a crash",
            )
        )
        self.soft.currentIndexChanged.connect(lambda *args: self.changed.emit())
        # the rows they take in the panel, those of custom ones only for them
        self.rows = [
            (QtWidgets.QLabel(translate("CAM_SeatInVise", "Parallels")), self.pair, False),
            (QtWidgets.QLabel(translate("CAM_Vise", "Height")), self.height, True),
            (QtWidgets.QLabel(translate("CAM_Vise", "Thickness")), self.thickness, True),
            (QtWidgets.QLabel(translate("CAM_Vise", "Length")), self.length, False),
            (QtWidgets.QLabel(translate("CAM_Vise", "Material")), self.soft, False),
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
                height, thickness, length, soft, translate("CAM_Vise", "Custom")
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


class TaskPanelVise:
    """A vise of a Job: one it has, its stock seated in it again, or one added from the library.

    The vise, its jaws, the grip, where across the jaws, whether to close the jaw, what moves.
    Seating a vise it has, each Apply is an undoable step of its own. Adding one, the add's
    transaction stays open: seating goes into it, OK keeps the vise, Cancel takes it out again,
    and another chosen takes its place."""

    def __init__(self, job, vise=None):
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
        # a selected vise shows in the highlight colour, hiding its own
        FreeCADGui.Selection.clearSelection()
        # three sections, each a box of its own that rolls up: the vise, its jaws and how the
        # part sits in it; what the stock stands on; where along the jaws and what moves
        sections = []
        for title, icon in (
            (translate("CAM_Vise", "Vise"), QtGui.QIcon(":/icons/CAM_Vise.svg")),
            (translate("CAM_Vise", "Stock"), _themedIcon(":/icons/stock.svg")),
            (translate("CAM_Vise", "Position"), QtGui.QIcon(":/icons/Std_Placement.svg")),
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
                translate("CAM_Vise", "%s, in %s (station %s free)")
                % (
                    owner.Label,
                    PathWorkholding.memberOf(owner)[0].Label,
                    ", ".join(str(n) for n in free),
                ),
                ("share", owner),
            )
        self.addEntry(translate("CAM_Vise", "Add from the library:"), ("none", None))
        self.vise.model().item(self.vise.count() - 1).setEnabled(False)
        for label, path in _library():
            self.addEntry("    " + label, ("file", path))
        self.addEntry(translate("CAM_AddVise", "Get from library…"), ("library", None))
        self.addEntry(translate("CAM_AddVise", "Other file…"), ("other", None))
        self.lastVise = 0
        if vise in vises or (vise is None and vises):
            self.existing = vise or vises[0]
            self.lastVise = vises.index(self.existing)
            # as its file now has it, the file open with the Job
            PathWorkholding.refreshSettings(self.existing)
        self.vise.setCurrentIndex(self.lastVise)
        layout.addRow(translate("CAM_SeatInVise", "Vise"), self.vise)
        # the station of a vise of several the stock goes in: its own, or one free
        self.station = QtWidgets.QComboBox()
        self.station.setToolTip(
            translate("CAM_Vise", "The station of the vise the stock goes in, one no other Job has")
        )
        self.station.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.stationLabel = QtWidgets.QLabel(translate("CAM_Vise", "Station"))
        layout.addRow(self.stationLabel, self.station)
        # how the part sits in it: the side of the part on the vise's bottom, the floor or the
        # parallels, and the side against its fixed jaw, one of the four left
        self.seat = QtWidgets.QComboBox()
        self.seat.setToolTip(
            translate("CAM_Vise", "The side of the part on the floor or the parallels")
        )
        self.jaw = QtWidgets.QComboBox()
        self.jaw.setToolTip(translate("CAM_Vise", "The side of the part against the fixed jaw"))
        layout.addRow(translate("CAM_Vise", "Bottom side"), self.seat)
        layout.addRow(translate("CAM_Vise", "Fixed jaw side"), self.jaw)
        self.seat.currentIndexChanged.connect(self.seatChanged)
        self.jaw.currentIndexChanged.connect(self.showSeat)
        # what the sides lit on the part are
        legend = QtWidgets.QLabel(
            '<span style="color:#33bf40">\u25a0</span> %s &nbsp; '
            '<span style="color:#ff8c00">\u25a0</span> %s'
            % (
                translate("CAM_Vise", "Bottom"),
                translate("CAM_Vise", "Fixed jaw"),
            )
        )
        layout.addRow("", legend)
        # the jaw plates: the hard jaws, or soft jaws as thick and tall as asked, steps cut in
        # them to seat the stock on; a vise whose file does not name its plates keeps its own,
        # the choice not shown
        self.jaws = QtWidgets.QComboBox()
        self.jaws.addItem(translate("CAM_Vise", "Hard"), "Hard")
        self.jaws.addItem(translate("CAM_Vise", "Soft"), "Soft")
        self.jaws.addItem(translate("CAM_Vise", "Grip"), "Grip")
        self.jaws.setToolTip(
            translate("CAM_Vise", "The vise's own hard jaws, or soft jaws to cut to the part")
        )
        self.jawsLabel = QtWidgets.QLabel(translate("CAM_Vise", "Jaws"))
        layout.addRow(self.jawsLabel, self.jaws)
        self.softThickness = ui.createWidget("Gui::QuantitySpinBox")
        self.softThickness.setProperty("unit", "mm")
        self.softThickness.setToolTip(
            translate("CAM_Vise", "How thick the soft jaws are, from the vise's jaw out")
        )
        self.softHeight = ui.createWidget("Gui::QuantitySpinBox")
        self.softHeight.setProperty("unit", "mm")
        self.softHeight.setToolTip(translate("CAM_Vise", "How tall the soft jaws are"))
        self.steps = _StepRows(
            ui,
            lambda: (
                self.softThickness.property("rawValue"),
                self.softHeight.property("rawValue"),
            ),
        )
        self.softRows = []
        for label, field in (
            (translate("CAM_Vise", "Thickness"), self.softThickness),
            (translate("CAM_Vise", "Height"), self.softHeight),
            (translate("CAM_Vise", "Steps"), self.steps),
        ):
            label = QtWidgets.QLabel(label)
            layout.addRow(label, field)
            self.softRows += [label, field]
        # grip jaws: their grips, how far they stand above the jaws' tops, their teeth behind
        # the jaws' face, how far they bite into the stock, how many on each jaw
        defaults = PathJaws.GripJaw

        def length(tip, value):
            box = ui.createWidget("Gui::QuantitySpinBox")
            box.setProperty("unit", "mm")
            box.setProperty("singleStep", 0.01)
            box.setProperty("rawValue", value)
            box.setToolTip(tip)
            return box

        self.gripHeight = length(
            translate("CAM_Vise", "How far the grips stand above the jaws' tops: the grip"),
            defaults["grip"],
        )
        self.gripSetback = length(
            translate("CAM_Vise", "The grips' teeth behind the jaws' face"), defaults["setback"]
        )
        self.gripBite = length(
            translate("CAM_Vise", "How far the grips' teeth bite into the stock"), defaults["bite"]
        )
        self.gripCount = QtWidgets.QSpinBox()
        self.gripCount.setRange(1, 6)
        self.gripCount.setValue(defaults["grips"])
        self.gripCount.setToolTip(translate("CAM_Vise", "How many grips on each jaw"))
        self.gripRows = []
        for label, field in (
            (translate("CAM_Vise", "Grip height"), self.gripHeight),
            (translate("CAM_Vise", "Tooth setback"), self.gripSetback),
            (translate("CAM_Vise", "Bite"), self.gripBite),
            (translate("CAM_Vise", "Grips"), self.gripCount),
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
        self.parallels = _ParallelPicker(ui)
        self.parallels.addTo(layout)
        # what it comes to, at the end of the seat: why it cannot be seated, a vise too small
        # for the stock; else the grip, how much stands above the jaws, and how far the model's
        # bottom is above them, the clearance the tools have to cut it whole
        self.fit = _Note()
        self.fit.setStyleSheet("color: #d04040")
        layout.addRow("", self.fit)
        self.other = _Note()
        layout.addRow("", self.other)
        self.clearance = _Note()
        self.clearance.setToolTip(
            translate(
                "CAM_SeatInVise",
                "From the jaw tops up to the bottom of the model: below them, the tools can not "
                "cut the model whole without reaching the jaws",
            )
        )
        layout.addRow("", self.clearance)
        layout = sections[2][1]

        # across the jaws: centred, or off the centre by so much
        self.across = QtWidgets.QComboBox()
        self.centre = _ComboChoice(self.across, translate("CAM_SeatInVise", "Centred"), "centre")
        self.offCentre = _ComboChoice(
            self.across, translate("CAM_SeatInVise", "Offset from centre"), "offset"
        )
        layout.addRow(translate("CAM_SeatInVise", "Across the jaws"), self.across)
        self.offset = ui.createWidget("Gui::QuantitySpinBox")
        self.offset.setProperty("unit", "mm")
        self.offset.setProperty("minimum", -10000.0)
        self.offset.setToolTip(translate("CAM_SeatInVise", "Along the jaws, from their centre"))
        self.offset.setEnabled(False)
        layout.addRow(translate("CAM_SeatInVise", "Offset"), self.offset)
        self.across.currentIndexChanged.connect(
            lambda *args: self.offset.setEnabled(self.offCentre.isChecked())
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
        _alignLabels([layout for _, layout in sections])

        self.vise.currentIndexChanged.connect(self.viseChanged)
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
        """A vise the Job has, the one being added dropped; or one from a file, added in the
        place of the one being added."""
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
        path = value
        if kind == "library":
            import Path.Main.Gui.WorkholdingLibraryGui as LibraryGui

            # downloaded into the Workholding folder, then added as one of its files is
            path = LibraryGui.getVise()
        if kind == "other":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                FreeCADGui.getMainWindow(),
                translate("CAM_AddVise", "Add Vise"),
                _prefs().GetString(
                    "WorkholdingDir", str(Path.Preferences.getAssetPath() / "Workholding")
                ),
                translate("CAM_AddVise", "FreeCAD document (*.FCStd)"),
            )
        if path and not self.job.Document.FileName:
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
            found = [i for i, e in enumerate(self.entries) if e == ("file", path)]
            if found:
                found = found[0]
            else:
                found = self.vise.count() - 1
                self.addEntry("    " + self.adding.vise.Label, ("file", path), found)
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
        frame = _jawFrame(vise)
        if frame is None or frame["floor"] is None:
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
        frame = _jawFrame(vise) if vise is not None else None
        extents = self.extents()
        self.clearance.setText("")
        if frame is None or frame["floor"] is None or extents is None:
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
            % (_length(grip), _length(max(0.0, bottom + tall - top)))
        )
        # the model where it will be, as far up from the stock's bottom as it is now
        clearance = bottom + (extents[2] - extents[0]) - top
        if clearance >= -1e-6:
            self.clearance.setStyleSheet("color: #46be5a")
            self.clearance.setText(
                translate("CAM_SeatInVise", "Clearance %s: the model is clear of the jaws")
                % _length(clearance)
            )
        else:
            self.clearance.setStyleSheet("color: #e1463c")
            self.clearance.setText(
                translate("CAM_SeatInVise", "Clearance %s: the model goes below the jaw tops")
                % _length(clearance)
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
        plateSize = getattr(PathWorkholding, "plateSize", None)
        size = plateSize(vise) if can and thickness is None and plateSize is not None else None
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
        ) % (_length(most), _length(needed))
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
            self.seat.addItem(translate("CAM_Vise", "Choose a side…"), None)
        elif turn is None:
            self.seat.addItem(translate("CAM_Vise", "As it is"), None)
        for label, direction in _sides():
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
            self.jaw.addItem(translate("CAM_Vise", "As it is"), None)
            return
        for label, direction in _sides():
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
                offset=self.offset.property("rawValue") if self.offCentre.isChecked() else 0.0,
                centre=True,
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
        was seated too, on parallels or not, off the centre, the jaw closed or not. Read in, not
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
            # one just added starts as a vise does, not as the last one was seated: centred,
            # the jaw closed, the stock on the floor, or on parallels holding half of a stock
            # shorter than the jaws
            self.centre.setChecked(True)
            self.offset.setProperty("rawValue", 0.0)
            self.close.setChecked(True)
            tall = self.stockHeight()
            onParallels = False
            if self.byParallels.isEnabled() and tall is not None and tall < jaw:
                onParallels = self.parallels.pickNear(jaw - tall / 2)
            (self.byParallels if onParallels else self.byFloor).setChecked(True)
        self.fresh = False
        if not self.adding:
            inch = PathParallels.INCH
            if step and self.byStep.isEnabled():
                self.byStep.setChecked(True)
                self.step.setCurrentIndex(min(step, self.step.count()) - 1)
            elif now["onParallels"] and self.byParallels.isEnabled():
                self.byParallels.setChecked(True)
                self.parallels.showPair(
                    vise.Parallels.Value,
                    getattr(vise, "ParallelThickness", FreeCAD.Units.Quantity(inch / 8)).Value,
                    getattr(vise, "ParallelLength", FreeCAD.Units.Quantity(6 * inch)).Value,
                    getattr(vise, "ParallelsCuttable", False),
                    getattr(vise, "ParallelSet", ""),
                )
            elif self.byParallels.isEnabled() and now["grip"] < jaw - 1e-3:
                # held by the grip alone, as vises once were: on parallels that hold it there
                self.byParallels.setChecked(True)
                self.parallels.showPair(jaw - max(0.0, now["grip"]), inch / 8, 6 * inch, False, "")
            else:
                self.byFloor.setChecked(True)
            offCentre = abs(now["offset"]) > 1e-6
            (self.offCentre if offCentre else self.centre).setChecked(True)
            self.offset.setProperty("rawValue", now["offset"] if offCentre else 0.0)
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
                self.station.addItem(translate("CAM_Vise", "Station %d") % number, number)
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
            if self.apply():
                # on from where it now is
                self.updateGrip()

    def accept(self):
        if self.apply():
            self.seatFaces.hide()
            FreeCADGui.Control.closeDialog()
            if self.adding:
                self.adding.finish(keep=True)
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
                ", ".join(_length(c) for c in done["move"]),
                _length(done["grip"]),
                _length(done["opening"]),
            )
        )
        return True

    def reject(self):
        self.previewTimer.stop()
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
        return True


def _unselectable(vobj):
    """A part of the workholding not picked in the 3D view, nor lit when picked in the tree: a
    vise, its jaws, grips and parallels are there to be seen and missed, not worked on."""
    if vobj is not None and "Selectable" in vobj.PropertiesList:
        vobj.Selectable = False


class ViewProviderViseMember:
    """A part of a vise of a Job's Workholding: deleting it deletes the whole vise, a vise
    short of a part being no use."""

    def __init__(self, vobj):
        vobj.Proxy = self
        # thin lines, vertices no bigger and, where it says, the colour of the edges
        names = vobj.PropertiesList
        for name in ("LineWidth", "PointSize"):
            if name in names:
                setattr(vobj, name, 1)
        if "PointColor" in names and "LineColor" in names:
            vobj.PointColor = vobj.LineColor

    def attach(self, vobj):
        self.vobj = vobj
        _unselectable(vobj)

    def finishRestoring(self):
        # one saved before it was so: not picked in the 3D view either
        _unselectable(self.vobj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        job, vise = PathWorkholding.memberOf(obj)
        if vise is None or vise == obj:
            return True
        # the rest of the vise, all in Delete's own undoable step; what is selected too is left
        # to Delete, which still has it to remove; no longer shared with other Jobs
        PathWorkholding.release(vise)
        doc = obj.Document
        for other in list(vise.Group) + [vise]:
            if (
                other != obj
                and other.isAttachedToDocument()
                and not FreeCADGui.Selection.isSelected(other)
            ):
                doc.removeObject(other.Name)
        return True

    def doubleClicked(self, vobj):
        return _showVise(vobj.Object)


def _showVise(obj):
    """The vise panel on the vise obj is, or is part of: True if it is shown."""
    job, vise = PathWorkholding.memberOf(obj)
    if vise is None or PathWorkholding.viseSetup(vise) is None:
        return False
    if FreeCADGui.Control.activeDialog():
        return False
    FreeCADGui.Control.showDialog(TaskPanelVise(job, vise))
    return True


def _seatedDragger():
    """The Transform dragger of a seated vise without what would move it into the jaws or turn
    it: along the jaws and up, and the plane of the two, are left."""
    from pivy import coin

    view = FreeCADGui.ActiveDocument.ActiveView if FreeCADGui.ActiveDocument else None
    if view is None or not hasattr(view, "getSceneGraph"):
        return
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName("SoTransformDragger"))
    search.setInterest(coin.SoSearchAction.FIRST)
    search.apply(view.getSceneGraph())
    if search.getPath() is None:
        return
    dragger = search.getPath().getTail()
    for name in ("yTranslatorDragger", "xRotatorDragger", "yRotatorDragger", "zRotatorDragger"):
        part = dragger.getPart(name, True)
        if part is not None:
            part.getField("visible").set("FALSE")
    # the planes, where the dragger draws them
    for name in ("xyPlanarTranslatorSwitch", "yzPlanarTranslatorSwitch"):
        dragger.set("%s { whichChild -1 }" % name)


class ViewProviderVise:
    """A vise of a Job's Workholding: double-clicked, its panel; deleted, all of it."""

    def __init__(self, vobj):
        vobj.addExtension("Gui::ViewProviderGeoFeatureGroupExtensionPython")
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        # not in use, the icon an inactive operation has
        if not getattr(getattr(self, "Object", None), "Active", True):
            return ":/icons/CAM_OpActive.svg"
        return ":/icons/CAM_Vise.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def doubleClicked(self, vobj):
        return _showVise(vobj.Object)

    def setEdit(self, vobj, mode):
        # Transform: FreeCAD's dragger, once made, showing only how a seated vise may move
        if mode == 1 and getattr(vobj.Object, "Seated", False):
            QtCore.QTimer.singleShot(0, _seatedDragger)
        return None

    def onDelete(self, vobj, subelements):
        # its parts with it, all in Delete's own undoable step; what is selected too is left
        # to Delete, which still has it to remove; no longer shared with other Jobs
        PathWorkholding.release(vobj.Object)
        doc = vobj.Object.Document
        for obj in list(vobj.Object.Group):
            if obj.isAttachedToDocument() and not FreeCADGui.Selection.isSelected(obj):
                doc.removeObject(obj.Name)
        return True


def _jobOfSelection():
    """The Job the selection is of, the only Job, or the one asked for; None if none."""
    import PathScripts.PathUtils as PathUtils

    jobs = _jobs()
    for sel in FreeCADGui.Selection.getSelection():
        job = sel if hasattr(sel, "Workholding") else PathUtils.findParentJob(sel)
        if job is None:
            job = PathWorkholding.memberOf(sel)[0]
        if job in jobs:
            return job
    if len(jobs) == 1:
        return jobs[0]
    if not jobs:
        return None
    label, ok = QtWidgets.QInputDialog.getItem(
        FreeCADGui.getMainWindow(),
        translate("CAM_Vise", "Vise"),
        translate("CAM_AddVise", "Job"),
        [j.Label for j in jobs],
        0,
        False,
    )
    return jobs[[j.Label for j in jobs].index(label)] if ok else None


def _openVise(path, job):
    """The document of a vise's file, opened without a view if it is not open, the Job's
    document left in front. Returns it, and whether it was opened here. One open only in part,
    for the objects something links, is opened again whole: its vise may not be loaded."""
    wasOpen = False
    for doc in FreeCAD.listDocuments().values():
        if doc.FileName and os.path.exists(doc.FileName) and os.path.samefile(doc.FileName, path):
            if not doc.Partial:
                return doc, False
            wasOpen = True
    doc = FreeCAD.openDocument(path, hidden=True)
    FreeCAD.setActiveDocument(job.Document.Name)
    FreeCADGui.setActiveDocument(job.Document.Name)
    return doc, not wasOpen


class CommandVise:
    """A vise of a Job: the stock seated in one it has, or one added from the library."""

    def GetResources(self):
        return {
            "Pixmap": "CAM_Vise",
            "MenuText": QT_TRANSLATE_NOOP("CAM_Vise", "Vise…"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_Vise",
                "Seat the Job's stock in one of its vises, or add one from the library: against "
                "the fixed jaw, held as deep as asked, the moving jaw closed on it.",
            ),
        }

    def IsActive(self):
        if FreeCAD.ActiveDocument is None or FreeCADGui.Control.activeDialog():
            return False
        return bool(_jobs())

    def Activated(self):
        job = _jobOfSelection()
        if job is None:
            return
        # the vise selected, or a part of it
        vise = None
        for sel in FreeCADGui.Selection.getSelection():
            member = PathWorkholding.memberOf(sel)[1]
            if member is not None and PathWorkholding.viseSetup(member) is not None:
                vise = member
                break
        FreeCADGui.Control.showDialog(TaskPanelVise(job, vise))


class CommandAddAnother:
    """Another of the selected piece of workholding beside it."""

    def GetResources(self):
        return {
            "Pixmap": "CAM_Vise",
            "MenuText": QT_TRANSLATE_NOOP("CAM_AddVise", "Add Another"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_AddVise",
                "Another of the selected vise, clamp or dog beside it: a vise opening on its own.",
            ),
        }

    def IsActive(self):
        if FreeCAD.ActiveDocument is None or FreeCADGui.Control.activeDialog():
            return False
        selection = FreeCADGui.Selection.getSelection()
        return len(selection) == 1 and PathWorkholding.memberOf(selection[0])[1] is not None

    def Activated(self):
        member = FreeCADGui.Selection.getSelection()[0]
        doc = member.Document
        doc.openTransaction(translate("CAM_AddVise", "Add another"))
        try:
            copy = PathWorkholding.addAnother(member)
        except ValueError as e:
            doc.abortTransaction()
            Path.Log.error(str(e))
            return
        doc.commitTransaction()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(copy)


if FreeCAD.GuiUp:
    FreeCADGui.addCommand("CAM_Vise", CommandVise())
    FreeCADGui.addCommand("CAM_AddAnother", CommandAddAnother())

FreeCAD.Console.PrintLog("Loading WorkholdingCmd… done\n")
