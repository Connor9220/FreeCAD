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

"""The widgets the sections of the workholding panel share: drop-downs, notes, length boxes, the
browse button and the part's sides."""

import FreeCAD

from Path.Workholding.Constants import ICON_BLACK, ICON_SWAP, ICON_WHITE, LENGTH_STEP

if FreeCAD.GuiUp:
    from PySide import QtCore, QtGui, QtWidgets

translate = FreeCAD.Qt.translate


def mmBox(ui, tip=None, value=None, step=None, minimum=0.0):
    """mmBox(ui, tip=None, value=None, step=None, minimum=0.0) ... a box for a length in mm, as
    the user's units show it, made by ui, a FreeCADGui.UiLoader: its tooltip, value, the step a
    click takes in the unit it shows, a tenth of it when not given, and its minimum: none below
    0 unless given, a coordinate's lower."""
    box = ui.createWidget("Gui::QuantitySpinBox")
    box.setProperty("unit", "mm")
    # what is typed put in on Enter or leaving the box, as CAM's other panels do; the arrows and
    # the wheel at once
    box.setKeyboardTracking(False)
    box.setProperty("minimum", minimum)
    box.setProperty("singleStep", LENGTH_STEP if step is None else step)
    # as narrow as the panel needs, not kept as wide as its longest number: two to a row fit a
    # narrow panel
    box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
    if value is not None:
        box.setProperty("rawValue", value)
    if tip is not None:
        box.setToolTip(tip)
    return box


def browseButton(tip):
    """browseButton(tip) ... a button opening the workholding browser, to choose another."""
    button = QtWidgets.QPushButton(translate("CAM_Workholding", "Browse…"))
    button.setIcon(QtGui.QIcon.fromTheme("edit-find", QtGui.QIcon(":/icons/zoom-in.svg")))
    button.setToolTip(tip)
    return button


def themedIcon(resource, size=32):
    """themedIcon(resource, size=32) ... a black icon of the Job panel's, white on a dark theme as the Job panel shows it."""
    import Path.Base.Gui.Theme as PathGuiTheme

    if not PathGuiTheme.is_dark_theme():
        return QtGui.QIcon(resource)
    f = QtCore.QFile(resource)
    if not f.open(QtCore.QFile.ReadOnly):
        return QtGui.QIcon(resource)
    # black and white swapped
    content = bytes(f.readAll())
    content = content.replace(ICON_BLACK, ICON_SWAP).replace(ICON_WHITE, ICON_BLACK)
    content = content.replace(ICON_SWAP, ICON_WHITE)
    f.close()
    from PySide import QtSvg

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    QtSvg.QSvgRenderer(QtCore.QByteArray(content)).render(painter)
    painter.end()
    return QtGui.QIcon(pixmap)


def sides():
    """sides() ... the sides of a part, as the view cube names them, and the Job's axis each faces out."""
    return [
        (translate("CAM_Workholding", "Bottom"), "-Z"),
        (translate("CAM_Workholding", "Top"), "+Z"),
        (translate("CAM_Workholding", "Front"), "-Y"),
        (translate("CAM_Workholding", "Back"), "+Y"),
        (translate("CAM_Workholding", "Left"), "-X"),
        (translate("CAM_Workholding", "Right"), "+X"),
    ]


class Note(QtWidgets.QLabel if FreeCAD.GuiUp else object):
    """A line of the panel saying how things stand: wrapped, and gone while it says nothing;
    one not shown, never shown, what it says still read."""

    def __init__(self, shown=True):
        super().__init__()
        self.shown = shown
        self.setWordWrap(True)
        self.setVisible(False)

    def setText(self, text):
        super().setText(text)
        self.setVisible(self.shown and bool(text))


def combo(wide=False, below=False):
    """combo(wide=False, below=False) ... a drop-down; a wide one no wider than its shortest
    choices in the panel, its list as wide as its longest; below, its list opening below it."""
    combo = DropDown() if below else QtWidgets.QComboBox()
    combo.setMaxVisibleItems(16)
    if wide:
        combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(6)
    return combo


class DropDown(QtWidgets.QComboBox if FreeCAD.GuiUp else object):
    """A drop-down whose list always opens below it: the style otherwise lays the list over it
    with the current choice on the box, so one far down the list opens it upward."""

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        below = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is None or below.y() + popup.height() <= screen.bottom():
            popup.move(popup.x(), below.y())


def header(combo, text):
    """header(combo, text) ... a heading in a drop-down's list, not picked: bold and grayed."""
    combo.addItem(text)
    item = combo.model().item(combo.count() - 1)
    item.setEnabled(False)
    font = item.font()
    font.setBold(True)
    item.setFont(font)


def fitList(combo):
    """fitList(combo) ... the drop-down's list as wide as its longest choice."""
    view = combo.view()
    view.setMinimumWidth(view.sizeHintForColumn(0) + 2 * view.frameWidth() + 24)
