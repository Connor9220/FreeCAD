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


"""The workholding commands: the workholding panel on a Job, and another of a piece of its
workholding beside it."""

import FreeCAD
import Path
import Path.Workholding.Vise as PathWorkholding

from PySide.QtCore import QT_TRANSLATE_NOOP

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtWidgets

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


class CommandVise:
    """A vise of a Job: the stock seated in one it has, or one added from the library."""

    def GetResources(self):
        return {
            "Pixmap": "CAM_Vise",
            "MenuText": QT_TRANSLATE_NOOP("CAM_Vise", "Workholding…"),
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
        # the vise selected, or a part of it; else a stop or clamp selected
        vise = None
        piece = None
        for sel in FreeCADGui.Selection.getSelection():
            member = PathWorkholding.memberOf(sel)[1]
            if member is not None and PathWorkholding.isVise(member):
                vise = member
                break
            if member is not None and piece is None:
                piece = member
        import Path.Workholding.Gui.Vise as ViseGui

        FreeCADGui.Control.showDialog(ViseGui.TaskPanelVise(job, vise, None if vise else piece))


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
        return len(selection) == 1 and PathWorkholding.isMember(selection[0])

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


class CommandLibrary:
    """The Workholding Library: vises and clamps installed from a library or updated, no Job
    needed."""

    def GetResources(self):
        return {
            "Pixmap": "CAM_Vise",
            "MenuText": QT_TRANSLATE_NOOP("CAM_WorkholdingLibrary", "Workholding Library…"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_WorkholdingLibrary",
                "Install vises and clamps from a library, and update those on this computer",
            ),
        }

    def IsActive(self):
        return True

    def Activated(self):
        import Path.Workholding.Gui.Library as LibraryGui

        LibraryGui.showLibrary()


if FreeCAD.GuiUp:
    FreeCADGui.addCommand("CAM_Vise", CommandVise())
    FreeCADGui.addCommand("CAM_WorkholdingLibrary", CommandLibrary())
    FreeCADGui.addCommand("CAM_AddAnother", CommandAddAnother())

FreeCAD.Console.PrintLog("Loading WorkholdingCmd… done\n")
