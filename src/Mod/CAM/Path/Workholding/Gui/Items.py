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
    ITEM_ICON,
    ITEM_LIST_ICON,
    ITEM_PREVIEW,
    LEVER_EDIT_DELAY,
    ADD_PREVIEW_DELAY,
    RECENT_CLAMPS,
    RECENT_CLAMPS_PREF,
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


# how big a stop's drawing is drawn, its views one above the other, pixels
_DRAWING_WIDTH = 170
_DRAWING_HEIGHT = 170


def _pieceDrawing(piece, palette, width=_DRAWING_WIDTH, height=_DRAWING_HEIGHT, stacked=True):
    """A drawing of a stop or clamp made here, its sizes named on it as the panel names them:
    from the front, facing the stock's side, its height, the stock behind it standing taller;
    and from above, along the stock across and front to back down, the stock's edge beyond it.
    Each view fills its half, the one above the other when stacked, else side by side. None for
    any other."""
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
    # each view's room: its left, its top, as wide and as high
    if stacked:
        cellW = width - 2 * margin
        cellH = height / 2 - textH - 6 - margin
        rooms = [(margin, 0.0), (margin, height / 2)]
    else:
        cellW = (width - 3 * margin) / 2
        cellH = height - textH - 6 - margin
        rooms = [(margin, 0.0), (2 * margin + cellW, 0.0)]
    labelW = max(metrics.horizontalAdvance(n) for n in ("Height", "Drop", "Rise", deep[0])) + 10
    under = textH + 6
    lipW = (metrics.horizontalAdvance("Reach") + 10) if edge else 0
    stockTall = v("Drop") if edge else tall * 1.5
    frontX, frontY = fit(cellW - labelW - 16, wide[1], cellH - under - 4, max(stockTall, tall))
    aboveX, aboveY = fit(
        cellW - labelW - lipW - 8, wide[1], cellH - band - under - 4, deep[1] + reach
    )
    # the piece as wide from the front as from above, one view over the other
    acrossX = min(frontX, aboveX)
    if kind == "ObjectDog":
        # round, as it is
        aboveY = min(acrossX, aboveY)
        acrossX = aboveY

    # from the front: the stock behind, taller; the piece on the table before it
    x0, y0 = rooms[0]
    cellTop = y0 + textH + 6
    text(x0 + cellW / 2, y0 + textH, translate("CAM_Workholding", "From the front"), faint)
    sx, sy = acrossX, frontY
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
    x0, y0 = rooms[1]
    cellTop = y0 + textH + 6
    text(x0 + cellW / 2, y0 + textH, translate("CAM_Workholding", "From above"), faint)
    sx, sy = acrossX, aboveY
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


# the pictures of the stops made here in the item box: a dog, a pin standing up, and a fence, a
# bar lying along the stock, in greys that read on a light or a dark panel
_PICTURES = {
    "Dog": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
<ellipse cx="20" cy="29" rx="9" ry="3" fill="#7d838c"/>
<rect x="11" y="12" width="18" height="17" fill="#9aa1aa"/>
<ellipse cx="20" cy="12" rx="9" ry="3" fill="#c3c8ce"/></svg>""",
    "Fence": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
<path d="M5 26 L30 18 L36 21 L11 29 Z" fill="#c3c8ce"/>
<path d="M11 29 L36 21 L36 25 L11 33 Z" fill="#7d838c"/>
<path d="M5 26 L11 29 L11 33 L5 30 Z" fill="#9aa1aa"/></svg>""",
}


def _picture(which, size):
    """The picture of what the item box offers, size pixels square: a stop made here drawn, a
    clamp's own file's thumbnail; None if it has none."""
    pixmap = None
    if which in _PICTURES:
        from PySide import QtSvg

        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        QtSvg.QSvgRenderer(QtCore.QByteArray(_PICTURES[which].encode())).render(painter)
        painter.end()
    elif isinstance(which, str) and os.path.isfile(which):
        import Path.Workholding.Library as PathLibrary

        data = PathLibrary.thumbnail(which)
        if data:
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(data)
            pixmap = pixmap.scaled(
                size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
    return pixmap


def _kindOf(which):
    """What an entry of the Add box is: "made", a stop made here; "clamp", a clamp's own file;
    "share", another Job's stop; "vise", a vise's own file; "viseshare", another Job's vise; None
    for none."""
    if which is None:
        return None
    if isinstance(which, (tuple, list)):
        return which[0]
    return "made" if which in Items.Classes else "clamp"


def _fileKind(path):
    """ "vise" or "clamp", as the file at path says of itself; None if it is neither."""
    import Path.Workholding.Library as PathLibrary

    return PathLibrary.about(path).get("kind") if os.path.isfile(path) else None


def _viseFile(vise):
    """The file a vise of the Job was added from, None if it is not found."""
    import Path.Workholding.Source as PathSource

    path = getattr(vise, "SourceFile", "")
    if path and os.path.isfile(path):
        return path
    found = PathSource.linkedDocuments(vise)
    return found[0].FileName if found and found[0].FileName else None


def _viseAngle(placement):
    """How a vise at placement is turned on the table, degrees: its jaws along the Job's X at 0."""
    import math

    along = placement.Rotation.multVec(FreeCAD.Vector(1, 0, 0))
    angle = math.degrees(math.atan2(along.y, along.x))
    # a hair either side of square shown as it
    return round(angle, 3) + 0.0


class _Drag:
    """How a kind of piece is dragged in the workholding panel: where it is when let go, what
    the panel shows while it moves, what letting it go does, free or not, and what is picked
    after. The panel drives every kind the same way."""

    def __init__(self, stops):
        self.stops = stops
        self.panel = stops.panel
        self.job = stops.job

    def letGoAt(self, piece):
        """Where the piece is as it is let go, read before its dragger goes."""
        return PathWorkholding.placementOf(piece)

    def shows(self, piece, at):
        """Mid-drag, at the dragger's placement: shown in the panel."""

    def letGo(self, piece, start, at, free):
        """Let go at at, the drag started at start; free, with Shift held."""

    def after(self, piece):
        """The piece picked again, its dragger made again: Add's own staying Add's."""
        stops = self.stops
        if piece in stops.shown():
            stops.fillList()
            stops.dragChosen(piece)
            return
        stops.fillList(piece)
        stops.picked()


class _PieceDrag(_Drag):
    """A stop's or clamp's: placed against the side nearest where it is let go, a lever clamp
    pressing where it is; free, left there, out of the spreading."""

    def letGoAt(self, piece):
        # from where it meets the stock, as its dragger stands
        return ViewProviders.dragPlacement(piece.ViewObject)

    def shows(self, piece, at):
        stops = self.stops
        lever = Lever.isLever(piece)
        turned = lever or getattr(piece, "Kind", None) == Items.Kind.Push
        # the piece's own placement, the dragger standing where it meets the stock
        origin = getattr(piece.ViewObject, "TransformOrigin", None)
        own = at.multiply(origin.inverse()) if origin is not None else at
        angle = Items.angleFrom(self.job, piece, own.Rotation) if turned else None
        if piece is not stops.chosen():
            # one Add only shows has no settings to show yet
            pass
        elif lever:
            for box, value in ((stops.pressX, at.Base.x), (stops.pressY, at.Base.y)):
                box.blockSignals(True)
                box.setProperty("rawValue", value)
                box.blockSignals(False)
            stops.angle.blockSignals(True)
            # the dragger turns in single precision: a hair either side of square shown as
            # 0.00, not -0.00
            stops.angle.setProperty("rawValue", round(angle, 3) + 0.0)
            stops.angle.blockSignals(False)
        else:
            stops.showPlace(piece, at.Base, angle)
        words = [_length(at.Base.x), _length(at.Base.y)]
        words.append(_degrees(angle) if angle is not None else "")
        stops.showRowAt(piece, words)

    def letGo(self, piece, start, at, free):
        if free:
            Items.setFree(piece)
            PathWorkholding.recompute(self.job.Document)
            return
        Items.fromTransform(piece, at)


class _ViseDrag(_Drag):
    """A vise's: slid along its jaws, where the stock is along them; across them, the part it
    holds with it; turned, square to the stock, onto its side or over a quarter turn at a time.
    Seated again where it is let go; free, left there unseated."""

    def shows(self, piece, at):
        stops, panel = self.stops, self.panel
        if not getattr(piece, "Seated", False):
            pass
        elif stops._slid(at):
            panel.showOffset(PathWorkholding.offsetAt(self.job, piece, at))
        else:
            # turned freely while dragged: the side it will be square to once let go shown
            turn = panel.turnAt(at, snap=True)
            if turn is not None:
                panel.showTurn(turn)
        stops.showRowAt(piece, [_length(at.Base.x), _length(at.Base.y), _degrees(_viseAngle(at))])

    def letGo(self, piece, start, at, free):
        panel = self.panel
        if free:
            # left where it is, held to no seat
            if getattr(piece, "Seated", False):
                piece.Seated = False
            PathWorkholding.recompute(self.job.Document)
            return
        seated = getattr(self.stops, "dragSeated", True)
        if seated and self.stops._slid(at):
            # across the jaws: the part held in it moved with it; along them: where it is along
            # the stock
            if start is not None:
                closing = PathWorkholding.stationPlacement(piece).Rotation.multVec(
                    FreeCAD.Vector(0, 1, 0)
                )
                across = closing * (at.Base - start.Base).dot(closing)
                across.z = 0.0
                if across.Length > 1e-6:
                    PathWorkholding.moveModel(self.job, across)
                    PathWorkholding.recompute(self.job.Document)
            panel.showOffset(PathWorkholding.seating(self.job, piece)["offset"])
        else:
            # turned, or let go free before: as it now is, square to the stock, onto its side
            # or over a quarter turn at a time
            turn = panel.turnAt(at, snap=True, tilt=True)
            if turn is not None:
                panel.showTurn(turn)
        panel.preview()
        adding = panel.adding
        if adding and piece is adding.vise:
            # the first of a row moved: the others spread from where it now is
            panel.pinAdd()
            panel.showMore(self.stops.count.value())


class _StockDrag(_Drag):
    """The stock's: the part moved and turned with it, the stock and what is placed on it; held
    in a vise, turned square to its jaws and the vise seated again; the stops and clamps placed
    against it again. Free: turned as let go."""

    def letGo(self, piece, start, at, free):
        if start is None:
            return
        stock = piece
        delta = at.multiply(start.inverse())
        pivot = start.Base
        turn = delta.Rotation
        vises = PathWorkholding.vises(self.job)
        if vises and not free:
            # in a vise: square to its jaws, a quarter at a time
            yaw = turn.toEuler()[0]
            turn = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), round(yaw / 90.0) * 90.0)
        # how far the pivot went, the turn about it
        shift = delta.Base - pivot + delta.Rotation.multVec(pivot)
        stock.Placement = start
        if not turn.isSame(FreeCAD.Rotation(), 1e-9):
            PathWorkholding.turnModel(self.job, turn, pivot)
        if shift.Length > 1e-9:
            PathWorkholding.moveModel(self.job, shift)
        PathWorkholding.recompute(self.job.Document)
        if vises:
            vise = self.panel.existing if self.panel.existing in vises else vises[0]
            self.panel.existing = vise
            self.panel.updateGrip()
            self.panel.preview()
        Items.layout(self.job)

    def after(self, piece):
        self.stops.fillList()
        self.stops.showChosen()
        QtCore.QTimer.singleShot(0, ViewProviders.stockDragger)


def _shiftHeld():
    """Whether Shift is held now: a piece let go so is left where it is, nothing placing it."""
    mods = QtWidgets.QApplication.queryKeyboardModifiers()
    return bool(mods & QtCore.Qt.ShiftModifier)


def _canDrag(piece):
    """Whether the dragger moves the piece picked: a stop or clamp as its kind allows, a vise of
    this Job's own, seated or let go free."""
    if PathWorkholding.isVise(piece):
        return not PathWorkholding.isShared(piece)
    return Items.canTransform(piece)


class _ViseArea(QtWidgets.QWidget if FreeCAD.GuiUp else object):
    """A vise's settings in the Placed section, where a clamp's show: its sections, each under a
    heading of its own, its picture beside them."""

    def __init__(self):
        super().__init__()
        self.grid = grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        self.picture = QtWidgets.QLabel()
        self.picture.setAlignment(QtCore.Qt.AlignCenter)
        grid.addWidget(self.picture, 0, 0, QtCore.Qt.AlignTop)
        self.column = QtWidgets.QVBoxLayout()
        self.column.setContentsMargins(0, 0, 0, 0)
        grid.addLayout(self.column, 0, 1)
        grid.setColumnStretch(1, 1)

    def showPicture(self, vise):
        """The vise's thumbnail from its file, none if it has none."""
        path = _viseFile(vise) if vise is not None else None
        pixmap = _picture(path, ITEM_PREVIEW) if path else None
        self.picture.setPixmap(pixmap if pixmap is not None else QtGui.QPixmap())
        if pixmap is not None:
            self.picture.setFixedSize(pixmap.size())
        self.picture.setVisible(pixmap is not None)

    def addSections(self, sections):
        """The first section beside the picture, untitled; the others under it the whole width,
        each under its title and a line across."""
        self.headings = {}
        for i, (title, widget) in enumerate(sections):
            if widget.layout() is not None:
                widget.layout().setContentsMargins(0, 0, 0, 0)
            if i == 0:
                self.column.addWidget(widget)
                self.column.addStretch(1)
                continue
            heading = QtWidgets.QWidget()
            line = QtWidgets.QHBoxLayout(heading)
            line.setContentsMargins(0, 6, 0, 0)
            label = QtWidgets.QLabel(title)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            line.addWidget(label)
            rule = QtWidgets.QFrame()
            rule.setFrameShape(QtWidgets.QFrame.HLine)
            rule.setFrameShadow(QtWidgets.QFrame.Sunken)
            line.addWidget(rule, 1)
            self.grid.addWidget(heading, self.grid.rowCount(), 0, 1, 2)
            self.grid.addWidget(widget, self.grid.rowCount(), 0, 1, 2)
            self.headings[widget] = heading

    def showSection(self, widget, visible):
        """A section shown or hidden, its title with it."""
        widget.setVisible(visible)
        if widget in self.headings:
            self.headings[widget].setVisible(visible)


class _Sizes:
    """What a stop made here is given as it is made, its sizes, gathered without making one."""

    def addProperty(self, *args):
        return self


def _madeSizes(which):
    """The sizes a stop made here starts with, by name, mm."""
    sizes = _Sizes()
    Items.Classes[which].addProperties(Items.Classes[which].__new__(Items.Classes[which]), sizes)
    return {name: value for name, value in vars(sizes).items() if isinstance(value, float)}


def _recentClamps():
    """The clamps' files added or browsed to lately, the latest first, those still there."""
    import Path.Workholding.Library as PathLibrary

    text = PathLibrary._prefs().GetString(RECENT_CLAMPS_PREF, "")
    return [path for path in text.splitlines() if path and os.path.isfile(path)]


def _rememberClamp(path):
    """A clamp's file added or browsed to, first of those used lately; the oldest forgotten."""
    import Path.Workholding.Library as PathLibrary

    real = os.path.realpath(path)
    kept = [p for p in _recentClamps() if os.path.realpath(p) != real]
    PathLibrary._prefs().SetString(
        RECENT_CLAMPS_PREF, "\n".join([path] + kept[: RECENT_CLAMPS - 1])
    )


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
        # clamps' files browsed to while the panel is open, not placed yet: used lately once they
        # are
        self.browsed = []
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

        # adding them: what goes there, made here, a clamp's own file or another Job's stop, or
        # one browsed to; the side, picked on the stock in the 3D view or named; how many, spread
        # along it; and a picture of what goes there
        layout = self.layouts[0]
        self.side = Widgets.combo()
        self.side.setToolTip(
            translate(
                "CAM_Workholding",
                "The side of the part they go on: one named, or an edge or face of the stock "
                "picked in the 3D view",
            )
        )
        self.item = Widgets.combo(wide=True, below=True)
        self.item.setToolTip(
            translate(
                "CAM_Workholding",
                "What goes there: a stop made here, a clamp this Job uses or one used lately, or "
                "another Job's stop to share",
            )
        )
        # its picture small in the box, larger in its list
        self.item.setIconSize(QtCore.QSize(ITEM_ICON, ITEM_ICON))
        view = QtWidgets.QListView()
        view.setIconSize(QtCore.QSize(ITEM_LIST_ICON, ITEM_LIST_ICON))
        self.item.setView(view)
        self.item.setItemDelegate(QtWidgets.QStyledItemDelegate(self.item))
        self.item.setMaxVisibleItems(8)
        self.item.setPlaceholderText(translate("CAM_Workholding", "Select…"))
        self.browse = Widgets.browseButton(
            translate("CAM_Workholding", "Choose a clamp from a library or a file to add")
        )
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(1, 12)
        self.count.setValue(1)
        self.count.setToolTip(translate("CAM_Workholding", "How many, spread along the side"))
        self.add = QtWidgets.QPushButton(translate("CAM_Workholding", "Add"))
        self.add.setToolTip(
            translate(
                "CAM_Workholding",
                "Put them on the side, spread along it with those there you have not moved",
            )
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.item, 1)
        row.addWidget(self.browse)
        layout.addRow(row)
        # a vise to add: how the stock first sits in it, the side on its bottom and the side
        # against its fixed jaw; changed after it is added with the rest of its settings
        self.viseSeat = QtWidgets.QComboBox()
        self.viseSeat.setToolTip(
            translate("CAM_Workholding", "The side of the part on the floor or the parallels")
        )
        for label, direction in Widgets.sides():
            self.viseSeat.addItem(label, direction)
        self.viseJaw = QtWidgets.QComboBox()
        self.viseJaw.setToolTip(
            translate("CAM_Workholding", "The side of the part against the fixed jaw")
        )
        # what Add shows taken out, nothing put in
        self.cancelAdd = QtWidgets.QPushButton(translate("CAM_Workholding", "Cancel"))
        self.cancelAdd.setToolTip(
            translate("CAM_Workholding", "Put nothing in: what Add shows taken out again")
        )
        # how many, Add and Cancel, kept together at their own size: beside the side for stops
        # and clamps, beside the fixed jaw's side for a vise
        self.addButtons = QtWidgets.QWidget()
        buttons = QtWidgets.QHBoxLayout(self.addButtons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.count)
        buttons.addWidget(self.add)
        buttons.addWidget(self.cancelAdd)
        # a vise's two sides, the buttons beside the second, as wide a space beside the first:
        # the two boxes the same length
        self.viseRows = QtWidgets.QWidget()
        self.viseGrid = QtWidgets.QGridLayout(self.viseRows)
        self.viseGrid.setContentsMargins(0, 0, 0, 0)
        self.viseGrid.addWidget(QtWidgets.QLabel(translate("CAM_Workholding", "Bottom side")), 0, 0)
        self.viseGrid.addWidget(self.viseSeat, 0, 1)
        self.viseSpace = QtWidgets.QWidget()
        self.viseGrid.addWidget(self.viseSpace, 0, 2)
        self.viseGrid.addWidget(
            QtWidgets.QLabel(translate("CAM_Workholding", "Fixed jaw side")), 1, 0
        )
        self.viseGrid.addWidget(self.viseJaw, 1, 1)
        self.viseGrid.setColumnStretch(1, 1)
        layout.addRow(self.viseRows)
        self.viseSeat.setCurrentIndex(self.viseSeat.findData("-Z"))
        self.viseJawsFor("+Y")
        self.viseRows.setVisible(False)
        # the side, how many and Add, once something is picked to add
        self.addRow = QtWidgets.QWidget()
        self.addRowLayout = QtWidgets.QHBoxLayout(self.addRow)
        self.addRowLayout.setContentsMargins(0, 0, 0, 0)
        self.addRowLayout.addWidget(self.side, 1)
        self.addRowLayout.addStretch(0)
        self.addRowLayout.addWidget(self.addButtons)
        layout.addRow(self.addRow)
        # what Add puts in: its picture and what it is, while one is chosen
        self.addPicture = QtWidgets.QLabel()
        self.addPicture.setFixedSize(ITEM_PREVIEW, ITEM_PREVIEW)
        self.addPicture.setAlignment(QtCore.Qt.AlignCenter)
        self.addName = QtWidgets.QLabel()
        self.addName.setWordWrap(True)
        font = self.addName.font()
        font.setBold(True)
        self.addName.setFont(font)
        self.addFacts = QtWidgets.QLabel()
        self.addFacts.setWordWrap(True)
        self.addFacts.setEnabled(False)
        words = QtWidgets.QVBoxLayout()
        words.addWidget(self.addName)
        words.addWidget(self.addFacts)
        self.adding = QtWidgets.QWidget()
        self.adding.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        row = QtWidgets.QHBoxLayout(self.adding)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.addPicture)
        row.addLayout(words, 1)
        row.setAlignment(words, QtCore.Qt.AlignVCenter)
        layout.addRow(self.adding)
        self.shared = Widgets.Note()
        layout.addRow(self.shared)
        self.error = Widgets.Note()
        self.error.setStyleSheet("color: %s" % ERROR_TEXT_COLOR)
        layout.addRow(self.error)
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
        # what Add shows, put in but not yet kept: the pieces' names, and what the row said
        self.previewing = []
        self.previewKey = None
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
        self.remove = QtWidgets.QPushButton(translate("CAM_Workholding", "Remove"))
        self.remove.setToolTip(translate("CAM_Workholding", "Take the one picked away"))
        # the stock, and the part with it, moved by a dragger: where it goes, the holding after
        self.moveStock = QtWidgets.QPushButton(translate("CAM_Workholding", "Move stock"))
        self.moveStock.setCheckable(True)
        self.moveStock.setToolTip(
            translate(
                "CAM_Workholding",
                "Move and turn the stock, the part with it, by a dragger in the 3D view: held in "
                "a vise it turns square to the jaws",
            )
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.moveStock)
        row.addWidget(self.remove, 1)
        layout.addRow(row)
        # the one picked's settings, its picture beside them
        self.settings = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.settings)
        grid.setContentsMargins(0, 0, 0, 0)
        self.picture = QtWidgets.QLabel()
        self.picture.setAlignment(QtCore.Qt.AlignCenter)
        grid.addWidget(self.picture, 0, 0, QtCore.Qt.AlignTop)
        fields = QtWidgets.QWidget()
        self.settingsForm = QtWidgets.QFormLayout(fields)
        self.settingsForm.setContentsMargins(0, 0, 0, 0)
        self.settingsForm.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        grid.addWidget(fields, 0, 1, QtCore.Qt.AlignTop)
        grid.setColumnStretch(1, 1)
        layout.addRow(self.settings)
        # a vise picked: its settings in place of a clamp's
        self.viseArea = _ViseArea()
        layout.addRow(self.viseArea)
        self.viseArea.setVisible(False)
        layout = self.settingsForm
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
        # X over Y, beside the piece's picture
        row = QtWidgets.QGridLayout()
        self.placeGrid = row
        self.placeLabels = []
        for i, (axis, box) in enumerate(zip(("X", "Y"), self.placeAt)):
            self.placeLabels.append(QtWidgets.QLabel(axis))
            row.addWidget(self.placeLabels[-1], i, 0)
            row.addWidget(box, i, 1)
        row.setColumnStretch(1, 1)
        # in a widget of its own: a layout cannot be hidden where QFormLayout has no
        # setRowVisible, Qt before 6.4
        holder = QtWidgets.QWidget()
        row.setContentsMargins(0, 0, 0, 0)
        holder.setLayout(row)
        layout.addRow(holder)
        self.placeRow = holder
        # a side clamp picked: how far it is turned, pushing at a slant
        self.slant = Widgets.quantityBox(self.ui)
        self.slant.setKeyboardTracking(False)
        self.slant.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.slant.setProperty("unit", "deg")
        self.slant.setProperty("minimum", -90.0)
        self.slant.setProperty("maximum", 90.0)
        self.slant.setToolTip(
            translate(
                "CAM_Workholding",
                "How far it is turned from square to its side, seen from above, pushing at a slant",
            )
        )
        self.slantGrid = QtWidgets.QGridLayout()
        self.slantGrid.addWidget(QtWidgets.QLabel(translate("CAM_Workholding", "Angle")), 0, 0)
        self.slantGrid.addWidget(self.slant, 0, 1)
        self.slantGrid.setColumnStretch(1, 1)
        self.slantRow = QtWidgets.QWidget()
        self.slantGrid.setContentsMargins(0, 0, 0, 0)
        self.slantRow.setLayout(self.slantGrid)
        layout.addRow(self.slantRow)
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
        self.angle = Widgets.quantityBox(self.ui)
        self.angle.setKeyboardTracking(False)
        self.angle.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
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
        self.sizeGrid.setColumnStretch(1, 1)
        self.sizeBoxes = {}
        layout.addRow(self.sizes)
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
        self.browse.clicked.connect(self.browseClicked)
        self.add.clicked.connect(self.addClicked)
        self.cancelAdd.clicked.connect(self.cancelClicked)
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
        self.moveStock.toggled.connect(self.stockToggled)
        self.viseSeat.currentIndexChanged.connect(lambda *args: self.viseJawsFor())
        self.viseSeat.currentIndexChanged.connect(lambda *args: self.previewPicked())
        self.viseJaw.currentIndexChanged.connect(lambda *args: self.previewPicked())
        # the side and how many shown a moment after the last change: holding the count's arrow
        # puts them in once, not at every step
        self.addTimer = QtCore.QTimer()
        self.addTimer.setSingleShot(True)
        self.addTimer.setInterval(ADD_PREVIEW_DELAY)
        self.addTimer.timeout.connect(self.previewPicked)
        self.side.currentIndexChanged.connect(lambda *args: self.addTimer.start())
        self.count.valueChanged.connect(lambda *args: self.addTimer.start())
        self.table.clicked.connect(self.addTable)

    def showRow(self, field, shown):
        """A row of the picked one's settings shown, or gone with its label and the space it
        takes."""
        form = self.settingsForm
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

    def previewPicked(self):
        """What Add has picked shown in the view: a vise seated as the row says, stops or clamps
        on the side, as many as it says; nothing picked, what was shown taken out."""
        if getattr(self, "loading", False):
            return
        self.addTimer.stop()
        if getattr(self, "previewBusy", False):
            # asked again while showing: shown again once done, as the row then says
            self.previewAgain = True
            return
        self.previewBusy = True
        if self.item.currentData() is not None and self.list.selectionModel().hasSelection():
            # what Add shows or a piece placed, one at a time: the placed one let go first
            self.list.blockSignals(True)
            self.list.clearSelection()
            self.list.setCurrentCell(-1, -1)
            self.list.blockSignals(False)
        try:
            self.previewAgain = True
            while self.previewAgain:
                self.previewAgain = False
                which = self.item.currentData()
                if _kindOf(which) in ("vise", "viseshare"):
                    self.dropPieces()
                    self.panel.previewAdd(
                        which,
                        self.viseSeat.currentData(),
                        self.viseJaw.currentData(),
                        self.count.value() if _kindOf(which) == "vise" else 1,
                    )
                else:
                    self.panel.dropAdd()
                    self.previewPieces(which)
        finally:
            self.previewBusy = False

    def _addKey(self, which):
        """What Add would put in, as the row says: what, on which side, how many."""
        side = self.side.currentData()
        if isinstance(side, tuple):
            side = side[1]
        name = which if isinstance(which, (str, tuple)) else getattr(which, "Name", None)
        return (name, side, self.count.value())

    def previewPieces(self, which):
        """The stops or clamps Add has picked put on the side, pending: Add keeps them, picking
        another drops them. A clamp's file in a document not saved shows nothing: its parts are
        linked."""
        key = self._addKey(which)
        doc = self.job.Document
        shown = getattr(self, "previewKey", None)
        whole = all(doc.getObject(name) is not None for name in self.previewing)
        if key == shown and whole:
            return
        if shown is not None and whole and key[:2] == shown[:2] and which != "Fence":
            # only how many changed: the difference put in or taken out, those shown kept where
            # they are; fences share their side's length, so made again
            self.addMore(which, key)
            return
        dropped = self.dropPieces(again=False)
        if (
            which is None
            or key[1] is None
            or (isinstance(which, str) and which not in Items.Classes and not doc.FileName)
        ):
            if dropped:
                self.preview()
            return
        self.panel.begin()
        try:
            new = Items.addPieces(self.job, key[1], which, key[2])
            self.error.setText("")
        except ValueError as e:
            self.error.setText(str(e))
            new = []
        self.previewing = [piece.Name for piece in new]
        self.previewKey = key if new else None
        self.fillList()
        # one alone moved by its dragger before Add keeps it
        self.dragChosen(new[0] if len(new) == 1 and not self.chosen() else None)

    def addMore(self, which, key):
        """What Add shows made as many as key says: more put on the side, or the last taken off."""
        doc = self.job.Document
        have = list(self.previewing)
        self.panel.begin()
        if key[2] > len(have):
            try:
                new = Items.addPieces(self.job, key[1], which, key[2] - len(have))
                self.error.setText("")
            except ValueError as e:
                self.error.setText(str(e))
                return
            self.previewing = have + [piece.Name for piece in new]
        else:
            extra = [doc.getObject(name) for name in have[key[2] :]]
            Items.removePieces([piece for piece in extra if piece is not None])
            self.previewing = [name for name in have if doc.getObject(name) is not None]
        self.previewKey = key
        self.fillList()
        self.dragChosen(self.previewPiece() if not self.chosen() else None)

    def shown(self):
        """What Add shows, not yet kept: the vises being added, or the stops or clamps."""
        adding = getattr(self.panel, "adding", None)
        if adding:
            return adding.all()
        doc = self.job.Document
        return [p for p in (doc.getObject(n) for n in getattr(self, "previewing", [])) if p]

    def shownFirst(self):
        """The one of what Add shows that its dragger moves: the first vise, or the one stop or
        clamp; None if none, or several stops or clamps."""
        adding = getattr(self.panel, "adding", None)
        if adding:
            return adding.vise
        return self.previewPiece()

    def dropShown(self):
        """What Add shows taken out, whatever it is."""
        self.panel.dropAdd()
        self.dropPieces()

    def previewPiece(self):
        """The one stop or clamp Add shows, None if it shows none or several."""
        if len(getattr(self, "previewing", [])) != 1:
            return None
        return self.job.Document.getObject(self.previewing[0])

    def dropPieces(self, again=True):
        """The stops or clamps Add showed taken out, the others on their side spread again: True
        if there were any."""
        names, self.previewKey = list(getattr(self, "previewing", [])), None
        if not names:
            return False
        if self.editing in names:
            self.dragChosen(None)
        doc = self.job.Document
        there = [doc.getObject(name) for name in names]
        Items.removePieces([p for p in there if p is not None and p.isAttachedToDocument()])
        # forgotten only once gone
        self.previewing = [name for name in self.previewing if doc.getObject(name) is not None]
        if again:
            self.preview()
        return True

    def keepPieces(self):
        """The stops or clamps Add showed kept, if they are what the row says: the last of them,
        None if there were none to keep."""
        names = getattr(self, "previewing", [])
        if not names or self._addKey(self.item.currentData()) != self.previewKey:
            return None
        self.previewing, self.previewKey = [], None
        kept = [self.job.Document.getObject(name) for name in names]
        kept = [piece for piece in kept if piece is not None]
        return kept[-1] if kept else None

    def viseJawsFor(self, keep=None):
        """The sides that can be against a vise's fixed jaw, square to the one on its bottom:
        keep, or the one there was, if it still can."""
        seat = self.viseSeat.currentData()
        keep = keep or self.viseJaw.currentData()
        self.viseJaw.blockSignals(True)
        self.viseJaw.clear()
        for label, direction in Widgets.sides():
            if (
                abs(PathWorkholding.Directions[direction].dot(PathWorkholding.Directions[seat]))
                < 1e-9
            ):
                self.viseJaw.addItem(label, direction)
        found = self.viseJaw.findData(keep)
        self.viseJaw.setCurrentIndex(found if found >= 0 else 0)
        self.viseJaw.blockSignals(False)

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

    def viseSidesPicked(self):
        """The sides of the part a vise's jaws take from an edge or face of the stock picked in
        the 3D view, (bottom side, fixed jaw side) as the part's own: an edge along the top or
        bottom goes in the corner of the fixed jaw and the floor, its upright face against the
        jaw and its flat one down; a face against the fixed jaw, the bottom side None, kept as it
        is. None if none is picked; a ValueError for one that cannot be."""
        import Part

        stock = getattr(self.job, "Stock", None)
        if stock is None:
            return None
        part = PathWorkholding.partTurn(self.job).inverted()

        def named(normal):
            normal = part.multVec(normal)
            name, d = max(PathWorkholding.Directions.items(), key=lambda e: e[1].dot(normal))
            return name if d.dot(normal) > 0.99 else None

        def normalOf(face):
            u0, u1, v0, v1 = face.ParameterRange
            return face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)

        for sel in FreeCADGui.Selection.getSelectionEx(self.job.Document.Name):
            if sel.Object != stock:
                continue
            for name, shape in zip(sel.SubElementNames, sel.SubObjects):
                if shape.ShapeType == "Face":
                    side = named(normalOf(shape))
                    if side is None:
                        raise ValueError(
                            translate("CAM_Workholding", "That face is not square to the part")
                        )
                    return None, side
                if shape.ShapeType != "Edge" or not name.startswith("Edge"):
                    continue
                edge = stock.Shape.Edges[int(name[4:]) - 1]
                faces = [f for f in stock.Shape.ancestorsOfType(edge, Part.Face)]
                normals = [normalOf(f) for f in faces]
                flat = [n for n in normals if abs(n.z) > 0.99]
                upright = [n for n in normals if abs(n.z) < 0.01]
                if len(flat) != 1 or len(upright) != 1:
                    raise ValueError(
                        translate(
                            "CAM_Workholding",
                            "Pick an edge along the top or the bottom of the stock",
                        )
                    )
                seat, jaw = named(flat[0]), named(upright[0])
                if seat is None or jaw is None:
                    raise ValueError(
                        translate("CAM_Workholding", "That edge is not square to the part")
                    )
                return seat, jaw
        return None

    def pickViseSides(self):
        """An edge or face of the stock picked in the 3D view for the vise Add shows, or the
        one picked in Placed: its bottom side and fixed jaw side set from it, seated so."""
        adding = _kindOf(self.item.currentData()) == "vise"
        chosen = self.chosen()
        placed = chosen is not None and PathWorkholding.isVise(chosen)
        if not (adding or placed):
            return
        try:
            picked = self.viseSidesPicked()
        except ValueError as e:
            self.error.setText(str(e))
            return
        if picked is None:
            return
        seat, jaw = picked
        if adding:
            seat = seat or self.viseSeat.currentData()
        else:
            seat = seat or self.panel.seat.currentData()
        if (
            seat is None
            or abs(PathWorkholding.Directions[seat].dot(PathWorkholding.Directions[jaw])) > 1e-9
        ):
            self.error.setText(
                translate(
                    "CAM_Workholding",
                    "That face is the bottom side or opposite it: pick one square to it",
                )
            )
            return
        self.error.setText("")
        if adding:
            self.viseSeat.blockSignals(True)
            self.viseSeat.setCurrentIndex(max(0, self.viseSeat.findData(seat)))
            self.viseSeat.blockSignals(False)
            self.viseJawsFor(jaw)
            self.viseJaw.blockSignals(True)
            self.viseJaw.setCurrentIndex(max(0, self.viseJaw.findData(jaw)))
            self.viseJaw.blockSignals(False)
            self.previewPicked()
        else:
            self.panel.seat.blockSignals(True)
            self.panel.seat.setCurrentIndex(max(0, self.panel.seat.findData(seat)))
            self.panel.seat.blockSignals(False)
            self.panel.seatChanged(jaw=jaw)
            self.panel.preview()
        # the stock's pick let go, so the next registers; the vise picked in Placed kept picked
        keep = chosen if placed else None
        QtCore.QTimer.singleShot(50, lambda: self._afterSidesPicked(keep))

    def _afterSidesPicked(self, vise):
        # let go without the rows following it, the vise's row picked again after
        self.syncing = True
        try:
            FreeCADGui.Selection.clearSelection()
        finally:
            self.syncing = False
        if vise is not None and vise.isAttachedToDocument():
            self.fillList(vise)

    def fillItems(self, choose=None):
        """What the row can put on a side, each with its picture: the stops made here; the
        clamps' files this Job uses; those browsed to and not placed yet; those used lately, the
        latest first; and the other Jobs' stops to share. The one chosen kept, else choose, else
        none: Select…"""
        keep = choose if choose is not None else self.item.currentData()
        self.item.blockSignals(True)
        self.item.clear()

        def add(label, which, picture=None):
            pixmap = _picture(picture or which, ITEM_LIST_ICON)
            if pixmap is not None:
                self.item.addItem(QtGui.QIcon(pixmap), label, which)
            else:
                self.item.addItem(label, which)

        Widgets.header(self.item, translate("CAM_Workholding", "Parametric"))
        add(translate("CAM_Workholding", "Dog"), "Dog")
        add(translate("CAM_Workholding", "Fence"), "Fence")
        seen = set()
        used = []
        vises = []
        for vise in PathWorkholding.vises(self.job):
            path = _viseFile(vise)
            if path and os.path.realpath(path) not in seen:
                seen.add(os.path.realpath(path))
                vises.append(path)
        for piece in Items.clampsOn(self.job):
            which = getattr(piece, "Source", "")
            if which and which not in Items.Classes and os.path.isfile(which):
                real = os.path.realpath(which)
                if real not in seen and Items.clampFile(which) is not None:
                    seen.add(real)
                    used.append(which)

        def addFile(path):
            """A vise's or a clamp's own file, as the entry its kind is."""
            if _fileKind(path) == "vise":
                add(self._clampName(path, os.path.basename(path)), ("vise", path), path)
            else:
                add(self._clampName(path, Items.clampFile(path)[0]), path)

        def usable(path):
            return os.path.isfile(path) and (
                _fileKind(path) == "vise" or Items.clampFile(path) is not None
            )

        if used or vises:
            Widgets.header(self.item, translate("CAM_Workholding", "In this Job"))
            for path in vises + used:
                addFile(path)
        browsed = []
        for path in self.browsed:
            real = os.path.realpath(path)
            if real not in seen and usable(path):
                seen.add(real)
                browsed.append(path)
        if browsed:
            Widgets.header(self.item, translate("CAM_Workholding", "Browsed"))
            for path in browsed:
                addFile(path)
        recent = []
        for path in _recentClamps():
            real = os.path.realpath(path)
            if real not in seen and usable(path):
                seen.add(real)
                recent.append(path)
        if recent:
            Widgets.header(self.item, translate("CAM_Workholding", "Recent"))
            for path in recent:
                addFile(path)
        import Path.Workholding.Gui.Vise as ViseGui

        owners = Items.shareableStops(self.job)
        viseOwners = ViseGui._shareable(self.job)
        if owners or viseOwners:
            Widgets.header(self.item, translate("CAM_Workholding", "Other Jobs"))
            for owner in viseOwners:
                free = PathWorkholding.freeStations(owner)
                add(
                    translate("CAM_Workholding", "%s, in %s (station %s free)")
                    % (
                        owner.Label,
                        PathWorkholding.memberOf(owner)[0].Label,
                        ", ".join(str(n) for n in free),
                    ),
                    ("viseshare", owner.Name),
                    _viseFile(owner),
                )
            for owner in owners:
                kind = type(getattr(owner, "Proxy", None)).__name__.replace("Object", "")
                add(
                    translate("CAM_Workholding", "%s, in %s")
                    % (owner.Label, PathWorkholding.memberOf(owner)[0].Label),
                    ("share", owner.Name),
                    kind,
                )
        # Select… until one is chosen
        self.item.setCurrentIndex(self.findItem(keep))
        self.item.blockSignals(False)
        Widgets.fitList(self.item)
        self.updateRow()

    def findItem(self, which):
        """The row of the Add box holding which, -1 if none: a file the same file however its
        path is written, an entry of a kind and its file or Job's piece the same."""
        if which is None:
            return -1

        def same(a, b):
            if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
                return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
            if isinstance(a, str) and isinstance(b, str):
                if a == b:
                    return True
                return os.path.isfile(a) and os.path.isfile(b) and os.path.samefile(a, b)
            return a == b

        for row in range(self.item.count()):
            data = self.item.itemData(row)
            if data is not None and same(data, which):
                return row
        return -1

    def itemChanged(self, *args):
        """Another chosen: its picture and what it is shown; a piece placed picked no longer,
        only one of the two shown at a time."""
        if self.item.currentData() is not None and self.list.selectionModel().hasSelection():
            self.list.clearSelection()
            self.list.setCurrentCell(-1, -1)
        self.updateRow()

    def updateRow(self):
        """One of another Job's stops is shared one at a time; what Add puts in shown."""
        which = self.item.currentData()
        kind = _kindOf(which)
        vise = kind in ("vise", "viseshare")
        # a vise goes where the stock is, not on a side: how the stock sits in it instead
        self.side.setVisible(not vise)
        # vises from a file several at once, in a row along a long stock
        self.count.setVisible(not vise or kind == "vise")
        self.count.setEnabled(kind != "share")
        self.viseRows.setVisible(kind == "vise")
        self.add.setEnabled(which is not None)
        # a vise's buttons beside its fixed jaw's side; the others' on their own row
        if kind == "vise":
            self.viseGrid.addWidget(self.addButtons, 1, 2)
            self.viseSpace.setFixedWidth(self.addButtons.sizeHint().width())
            self.addRow.setVisible(False)
        else:
            self.addRowLayout.addWidget(self.addButtons)
            self.addRow.setVisible(which is not None)
        self.showAdding(which)
        self.previewPicked()

    def showAdding(self, which):
        """What Add puts in, while one is chosen: its picture, its name and what it is, also on
        the item box as it is pointed at."""
        self.adding.setVisible(which is not None)
        if which is None:
            self.item.setToolTip(
                translate("CAM_Workholding", "What goes there: pick a stop or clamp to add")
            )
            return
        name = self.item.currentText().strip()
        facts = ""
        kind = _kindOf(which)
        if kind == "vise":
            facts = self._viseFacts(which[1])
        elif kind == "viseshare":
            facts = translate(
                "CAM_Workholding", "A vise of another Job, shared: the part goes in a station free"
            )
        elif isinstance(which, (tuple, list)):
            facts = translate(
                "CAM_Workholding", "A stop of another Job, shared: the part moves to it"
            )
        elif which in Items.Classes:
            sizes = _madeSizes(which)
            parts = [translate("CAM_Workholding", "Stop")]
            if "Diameter" in sizes:
                parts.append(translate("CAM_Workholding", "%s across") % _length(sizes["Diameter"]))
            if "Length" in sizes:
                parts.append(translate("CAM_Workholding", "%s long") % _length(sizes["Length"]))
            if "Width" in sizes:
                parts.append(translate("CAM_Workholding", "%s wide") % _length(sizes["Width"]))
            if "Height" in sizes:
                parts.append(translate("CAM_Workholding", "%s tall") % _length(sizes["Height"]))
            parts.append(translate("CAM_Workholding", "sized once placed"))
            facts = " · ".join(parts)
        elif isinstance(which, str):
            facts = self._clampFacts(which)
        self.item.setToolTip("%s\n%s" % (name, facts) if facts else name)
        picture = which
        if kind == "vise":
            picture = which[1]
        elif kind == "viseshare":
            picture = _viseFile(self.job.Document.getObject(which[1]))
        elif isinstance(which, (tuple, list)):
            owner = self.job.Document.getObject(which[1])
            picture = type(getattr(owner, "Proxy", None)).__name__.replace("Object", "")
        pixmap = _picture(picture, ITEM_PREVIEW)
        self.addPicture.setPixmap(pixmap if pixmap is not None else QtGui.QPixmap())
        self.addName.setText(name)
        self.addFacts.setText(facts)

    @staticmethod
    def _viseFacts(path):
        """A vise's file said in a line: what it is, who makes it, how wide and tall its jaws
        are and how far it opens, as much as it says."""
        import Path.Workholding.Library as PathLibrary

        about = PathLibrary.about(path)
        settings = about.get("settings") or {}
        parts = [translate("CAM_Workholding", "Vise"), about.get("maker", "")]
        if settings.get("jawWidth"):
            parts.append(
                translate("CAM_Workholding", "jaws %s wide") % _length(settings["jawWidth"])
            )
        if settings.get("maxOpening"):
            parts.append(
                translate("CAM_Workholding", "opens to %s") % _length(settings["maxOpening"])
            )
        return " · ".join(p for p in parts if p)

    @staticmethod
    def _clampFacts(path):
        """A clamp's file said in a line: what it is, how wide, how far it reaches over the stock
        and the stock it is made for, as much as it says."""
        import Path.Workholding.Library as PathLibrary

        facts = Items.clampFacts(path)
        kinds = {
            "HoldDown": translate("CAM_Workholding", "Edge clamp"),
            "Push": translate("CAM_Workholding", "Side clamp"),
            "Lever": translate("CAM_Workholding", "Hold-down clamp"),
            "StrapKit": translate("CAM_Workholding", "Strap clamp kit"),
        }
        parts = [PathLibrary.about(path).get("type") or kinds.get(facts.get("Kind"), "")]
        if "Width" in facts:
            parts.append(translate("CAM_Workholding", "%s wide") % _length(facts["Width"]))
        if "Reach" in facts:
            parts.append(translate("CAM_Workholding", "reaches %s") % _length(facts["Reach"]))
        low, high = facts.get("MinStockThickness"), facts.get("MaxStockThickness")
        if low is not None and high is not None:
            parts.append(
                translate("CAM_Workholding", "stock %s to %s") % (_length(low), _length(high))
            )
        if "Thread" in facts:
            parts.append(translate("CAM_Workholding", "%s studs") % facts["Thread"])
        return " · ".join(p for p in parts if p)

    def browseClicked(self):
        """Browse: the picker opened, what it selects listed as browsed and chosen; used lately
        once it is placed."""
        import Path.Workholding.Gui.Library as LibraryGui

        path = LibraryGui.getWorkholding()
        if not path:
            return
        if _fileKind(path) != "vise" and Items.clampFile(path) is None:
            QtWidgets.QMessageBox.warning(
                FreeCADGui.getMainWindow(),
                translate("CAM_Workholding", "Clamps"),
                translate("CAM_Workholding", "%s holds no clamp.") % os.path.basename(path),
            )
            return
        real = os.path.realpath(path)
        self.browsed = [path] + [p for p in self.browsed if os.path.realpath(p) != real]
        self.fillItems(choose=("vise", path) if _fileKind(path) == "vise" else path)

    @staticmethod
    def _clampName(path, name):
        """A clamp's file's name to show: its label, as it says, else its file's name."""
        import Path.Workholding.Library as PathLibrary

        return PathLibrary.about(path).get("label") or name

    def cancelClicked(self):
        """Nothing put in: what Add shows taken out, the row back to Select… and one."""
        self.resetRow()

    def resetRow(self):
        """The row adding them back to Select… and one, once what it showed is kept or dropped."""
        self.addTimer.stop()
        self.count.blockSignals(True)
        self.count.setValue(1)
        self.count.blockSignals(False)
        self.item.setCurrentIndex(-1)

    def addClicked(self):
        """What the row says put on its side, spread along it; a clamp's file in a document not
        saved refused first: its parts are linked."""
        if self.addTimer.isActive():
            # the side or how many changed a moment ago: shown as the row says first
            self.previewPicked()
        which = self.item.currentData()
        if _kindOf(which) in ("vise", "viseshare"):
            if self.panel.addVise(
                which,
                self.viseSeat.currentData(),
                self.viseJaw.currentData(),
                self.count.value() if which[0] == "vise" else 1,
            ):
                if which[0] == "vise":
                    _rememberClamp(which[1])
                self.resetRow()
                self.updateRow()
            return
        side = self.side.currentData()
        if isinstance(side, tuple):
            side = side[1]
        if side is None or which is None:
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
        last = self.keepPieces()
        if last is not None:
            new = [last]
        else:
            self.panel.begin()
            try:
                new = Items.addPieces(self.job, side, which, self.count.value())
            except ValueError as e:
                self.error.setText(str(e))
                return
        self.error.setText("")
        if isinstance(which, str) and which not in Items.Classes:
            _rememberClamp(which)
        # added: Select… again
        self.resetRow()
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
        """The vises, stops and clamps, and their parts, picked in the 3D view while the panel is
        open; how each was kept to put back."""
        if self.pickable is None:
            return
        for piece in PathWorkholding.vises(self.job) + Items.itemsOf(self.job):
            for obj in [piece] + list(getattr(piece, "Group", []) or []):
                vobj = getattr(obj, "ViewObject", None)
                if vobj is None or "Selectable" not in vobj.PropertiesList:
                    continue
                if obj.Name not in self.pickable:
                    self.pickable[obj.Name] = vobj.Selectable
                vobj.Selectable = True

    def selectionChanged(self):
        """The selection changed: the sides offered and the rows picked as it is now; nothing
        once the panel is closed, its observer left behind if closing failed."""
        if self.pickable is None:
            return
        try:
            self.fillSides()
        except RuntimeError:
            # the panel's widgets gone with it
            FreeCADGui.Selection.removeObserver(self)
            return
        self.pickViseSides()
        self.selectFromView()

    def addSelection(self, doc, obj, sub, pos):
        self.selectionChanged()

    def removeSelection(self, doc, obj, sub):
        self.selectionChanged()

    def setSelection(self, doc):
        self.selectionChanged()

    def clearSelection(self, doc):
        self.selectionChanged()

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
        pieces = PathWorkholding.vises(self.job) + pieces
        # what Add only shows is not placed until Add keeps it
        shown = set(getattr(self, "previewing", []))
        adding = getattr(self.panel, "adding", None)
        if adding is not None:
            shown.update(vise.Name for vise in adding.all())
        pieces = [piece for piece in pieces if piece.Name not in shown]

        def order(piece):
            if PathWorkholding.isVise(piece):
                return (-1, 0.0)
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
            if PathWorkholding.isVise(piece):
                angle = _degrees(_viseAngle(PathWorkholding.placementOf(piece)))
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
        """The vises, stops and clamps of this Job picked in the 3D view: a part of one is the
        piece."""
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
        # a piece placed picked: the row adding them back to Select…, only one of the two shown
        if self.chosenAll() and self.item.currentIndex() >= 0:
            self.item.blockSignals(True)
            self.item.setCurrentIndex(-1)
            self.item.blockSignals(False)
            self.updateRow()
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
        # a vise picked: its settings in place of a clamp's
        vise = piece is not None and PathWorkholding.isVise(piece)
        self.remove.setEnabled(piece is not None)
        self.settings.setVisible(not vise)
        self.viseArea.showPicture(piece if vise else None)
        shown = self.shown()
        if piece is not None and shown and piece not in shown:
            # a placed piece picked: what Add only shows taken out
            self.item.setCurrentIndex(-1)
            self.updateRow()
        self.panel.focusVise(piece if vise else None)
        if vise:
            piece = None
        self.showPlace(piece)
        # a lever clamp is placed where it presses, not along its side
        lever = Lever.isLever(piece)
        self.showRow(self.placeRow, piece is not None and not lever)
        self.showLever(piece if lever else None)
        self.showSize(piece)
        # what Add shows keeps its dragger while nothing placed is picked; the stock its own
        # while asked for and nothing else is
        picked = self.chosen() or self.shownFirst()
        if picked is not None and self.moveStock.isChecked():
            self.moveStock.blockSignals(True)
            self.moveStock.setChecked(False)
            self.moveStock.blockSignals(False)
        if picked is None and self.moveStock.isChecked():
            picked = self.job.Stock
        self.dragChosen(picked)

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
        self.showRow(self.slantRow, pushes)
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
            self.showValue(self.angle, round(piece.Angle.Value, 6) + 0.0)
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
                shown = Lever.boltPosition(piece) if auto else piece.BoltAt.Value
                self.showValue(self.boltAt, shown or 0.0)
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
        # off: kept where Auto put it, to set from there
        self.setLever("BoltAt", 0.0 if auto else max(Lever.boltPosition(piece) or 0.0, 1e-3))

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
            # one to a row, beside its drawing
            self.sizeGrid.addWidget(QtWidgets.QLabel(translate("App::Property", name)), i, 0)
            self.sizeGrid.addWidget(box, i, 1)
            self.sizeBoxes[name] = box
        self.showRow(self.sizes, bool(names))
        self.showRow(self.sameSide, bool(names) and not fixed and bool(self.others(piece)))
        self.alignFields()
        self.showPicture(piece)

    def alignFields(self):
        """Where it is, its angle and its sizes, their boxes all as wide and lined up: the names
        in front of them in a column as wide as the widest."""
        grids = (self.placeGrid, self.slantGrid, self.sizeGrid)
        names = [
            grid.itemAtPosition(row, 0).widget()
            for grid in grids
            for row in range(grid.rowCount())
            if grid.itemAtPosition(row, 0) is not None
        ]
        wide = max((name.sizeHint().width() for name in names if name is not None), default=0)
        for grid in grids:
            grid.setColumnMinimumWidth(0, wide)

    def showPicture(self, piece):
        """The picked one's picture beside its settings: one made here its drawing as it is
        now, its views one above the other; a clamp's own file its thumbnail."""
        pixmap = _pieceDrawing(piece, self.picture.palette()) if piece is not None else None
        source = getattr(piece, "Source", "") if piece is not None else ""
        if pixmap is None and source:
            pixmap = _picture(source, ITEM_PREVIEW)
        self.picture.setPixmap(pixmap if pixmap is not None else QtGui.QPixmap())
        if pixmap is not None:
            self.picture.setFixedSize(pixmap.size())
        self.picture.setVisible(pixmap is not None)

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
        if piece is not None and piece is self.job.Stock:
            want = piece.Name
        elif piece is not None and len(self.chosenAll()) <= 1 and _canDrag(piece):
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
            # where the drag starts: a vise turned by it, or slid along its jaws; seated then
            self.dragFrom = FreeCAD.Placement(PathWorkholding.placementOf(piece))
            self.dragSeated = bool(getattr(piece, "Seated", True))
            self.dragTimer.start()

    def showDragging(self):
        """Where the dragger has the piece being dragged, shown as it moves, as its kind's rules
        say. Kept only when let go."""
        piece = self.job.Document.getObject(self.editing) if self.editing else None
        dragger = ViewProviders.findDragger() if piece is not None else None
        if dragger is None:
            return
        at = ViewProviders.draggerPlacement(dragger)
        shown = (round(at.Base.x, 6), round(at.Base.y, 6), round(at.Rotation.Angle, 9))
        if shown == self.dragShown:
            return
        self.dragShown = shown
        self.dragRules(piece).shows(piece, at)

    def dragRules(self, piece):
        """The rules the piece is dragged by: the stock's, a vise's, a stop's or clamp's."""
        if piece is self.job.Stock:
            return _StockDrag(self)
        if PathWorkholding.isVise(piece):
            return _ViseDrag(self)
        return _PieceDrag(self)

    def _slid(self, at):
        """Whether the vise being dragged, at placement at, is only slid from where the drag
        started, not turned."""
        start = getattr(self, "dragFrom", None)
        return start is None or at.Rotation.isSame(start.Rotation, 1e-6)

    def stockToggled(self, on):
        """Move stock: nothing else picked, the dragger on the stock; off, gone."""
        if on:
            self.resetRow()
            self.list.clearSelection()
            self.list.setCurrentCell(-1, -1)
            FreeCADGui.Selection.clearSelection()
        self.showChosen()
        if on:
            QtCore.QTimer.singleShot(0, ViewProviders.stockDragger)

    def showRowAt(self, piece, words):
        """The piece's row saying where it is, mid-drag: its X, Y and angle."""
        for row in range(self.list.rowCount()):
            cell = self.list.item(row, 0)
            if cell is None or cell.data(QtCore.Qt.UserRole) != piece.Name:
                continue
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
        """The piece let go by its dragger: kept as its kind's rules say, or with Shift held left
        where it is, nothing placing it; its dragger made again where it now is."""
        piece = self.job.Document.getObject(self.editing) if self.editing else None
        if piece is None or self.applying:
            return
        rules = self.dragRules(piece)
        start = getattr(self, "dragFrom", None)
        at = rules.letGoAt(piece)
        free = _shiftHeld()
        # the dragger let go first: it does not follow the piece placed
        self.editing = None
        FreeCADGui.getDocument(self.job.Document.Name).resetEdit()
        self.applying = True
        try:
            self.panel.begin()
            rules.letGo(piece, start, at, free)
            self.error.setText("")
        except ValueError as e:
            self.error.setText(str(e))
        finally:
            self.applying = False
        rules.after(piece)

    def removeChosen(self):
        """The pieces picked taken away, the rows as the Job now has them."""
        pieces = self.chosenAll() or [p for p in [self.chosen()] if p is not None]
        if not pieces:
            return
        self.timer.stop()
        self.panel.begin()
        FreeCADGui.Selection.clearSelection()
        for piece in pieces:
            if not piece.isAttachedToDocument():
                continue
            if PathWorkholding.isVise(piece):
                if piece is self.panel.existing:
                    self.panel.focusVise(None)
                PathWorkholding.release(piece)
                doc = piece.Document
                for obj in list(piece.Group) + [piece]:
                    doc.removeObject(obj.Name)
            else:
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
            self.addTimer,
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
