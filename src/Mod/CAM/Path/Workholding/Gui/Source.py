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


"""The files a Job's vises and clamps come from, in the GUI: closed once nothing uses them, and,
where they are not found when the Job's document is opened, looked for, asking one thing at a
time."""

import os

import FreeCAD
import Path
import Path.Workholding.Source as PathSource

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore, QtWidgets

translate = FreeCAD.Qt.translate


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


def closeFilesAfter(group):
    """closeFilesAfter(group) ... the files a vise or clamp group links its parts from closed, once
    it is deleted, those nothing links to then and open in no window."""
    names = [d.Name for d in PathSource.linkedDocuments(group)]

    def close():
        for name in names:
            doc = FreeCAD.listDocuments().get(name)
            if doc is not None:
                _closeIfUnused(doc)

    if names:
        QtCore.QTimer.singleShot(0, close)


# documents whose vises' or clamps' files are being looked for
_recovering = set()


def recoverWhenIdle(doc):
    """recoverWhenIdle(doc) ... the document's vises and clamps whose files are not found
    recovered once it is loaded and no other dialog is up, asking one thing at a time."""
    if doc.Name in _recovering:
        return
    _recovering.add(doc.Name)
    QtCore.QTimer.singleShot(500, lambda: _recoverIdle(doc.Name))


def _recoverIdle(name):
    doc = FreeCAD.listDocuments().get(name)
    if doc is None:
        _recovering.discard(name)
        return
    # waits its turn: the document loaded, no other dialog up
    if doc.Restoring or QtWidgets.QApplication.activeModalWidget() is not None:
        QtCore.QTimer.singleShot(300, lambda: _recoverIdle(name))
        return
    try:
        PathSource.recoverParts(
            doc,
            askLibrary=lambda file, item: _askLibrary(doc, file, item),
            askFile=lambda file: _askFile(doc, file),
        )
        _askChanged(doc, PathSource.changedSources(doc))
    except Exception as e:
        Path.Log.error("%s: %s" % (doc.Label, e))
    finally:
        _recovering.discard(name)
        # back to the document recovered: the files opened to link to are not shown
        if name in FreeCAD.listDocuments():
            FreeCAD.setActiveDocument(name)
            FreeCADGui.setActiveDocument(name)


def _askLibrary(doc, file, item):
    """Whether to download the library's file for one not found."""
    answer = QtWidgets.QMessageBox.question(
        FreeCADGui.getMainWindow(),
        translate("CAM_Vise", "Workholding not found"),
        translate(
            "CAM_Vise",
            "%s uses %s, which was not found. The library has it: %s.\n\nDownload it?",
        )
        % (doc.Label, os.path.basename(file), item.get("label", item["id"]))
        + (
            "\n\n"
            + translate(
                "CAM_Vise",
                "The library's has changed since it was added: the Job's toolpaths were made "
                "with it as it was.",
            )
            if item.get("changed")
            else ""
        ),
    )
    return answer == QtWidgets.QMessageBox.Yes


def _usedBy(rows):
    """What a file is used by, counted: "2 vises", "1 clamp"."""
    import Path.Workholding.Vise as PathWorkholding

    vises = sum(1 for row in rows if PathWorkholding.isVise(row))
    clamps = len(rows) - vises
    said = []
    if vises:
        said.append(
            translate("CAM_Vise", "1 vise")
            if vises == 1
            else translate("CAM_Vise", "%d vises") % vises
        )
    if clamps:
        said.append(
            translate("CAM_Vise", "1 clamp")
            if clamps == 1
            else translate("CAM_Vise", "%d clamps") % clamps
        )
    return ", ".join(said)


def _askChanged(doc, changed):
    """The vises' and clamps' files changed since they were added told, one line each: OK takes
    them as they are now; Remind Me Next Time tells again the next time it is opened."""
    if not changed:
        return
    files = PathSource.changedFiles(changed)
    lines = []
    for entry in files:
        why = (
            translate("CAM_Vise", "updated from %s") % entry["library"]
            if entry["library"]
            else translate("CAM_Vise", "changed on this computer")
        )
        lines.append(
            "<p style='margin: 0 0 6px 0'><b>%s</b> — %s<br>&nbsp;&nbsp;&nbsp;&nbsp;%s</p>"
            % (os.path.basename(entry["path"]), _usedBy(entry["rows"]), why)
        )
    box = QtWidgets.QMessageBox(FreeCADGui.getMainWindow())
    box.setIcon(QtWidgets.QMessageBox.Information)
    box.setWindowTitle(translate("CAM_Vise", "Workholding Files Changed"))
    box.setTextFormat(QtCore.Qt.RichText)
    box.setText(
        "<p>%s</p>%s<p>%s</p>"
        % (
            translate("CAM_Vise", "These files have changed since they were added to %s:")
            % doc.Label,
            "".join(lines),
            translate(
                "CAM_Vise",
                "The Job uses them as they are now. Check the toolpaths near them before cutting.",
            ),
        )
    )
    box.setDetailedText("\n".join(entry["path"] for entry in files))
    later = box.addButton(
        translate("CAM_Vise", "Remind Me Next Time"), QtWidgets.QMessageBox.RejectRole
    )
    ok = box.addButton(QtWidgets.QMessageBox.Ok)
    box.setDefaultButton(ok)
    box.exec()
    if box.clickedButton() == later:
        for entry in files:
            Path.Log.warning(
                translate("CAM_Vise", "%s: %s has changed since it was added")
                % (doc.Label, entry["path"])
            )
        return
    PathSource.acceptChanged(changed)


def _askFile(doc, file):
    """The file the user finds for one not in the folders, None if none."""
    import Path.Workholding.Library as PathLibrary

    name = os.path.basename(file.replace("\\", "/"))
    answer = QtWidgets.QMessageBox.question(
        FreeCADGui.getMainWindow(),
        translate("CAM_Vise", "Workholding not found"),
        translate(
            "CAM_Vise",
            "%s uses %s, which is not in the workholding folders.\n\nFind the file?",
        )
        % (doc.Label, name),
    )
    if answer != QtWidgets.QMessageBox.Yes:
        return None
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        FreeCADGui.getMainWindow(),
        translate("CAM_Vise", "Find %s") % name,
        PathLibrary.folder(),
        translate("CAM_AddVise", "FreeCAD document (*.FCStd)"),
    )
    return path or None
