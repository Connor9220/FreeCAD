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


"""Where a Job's vises and clamps came from: the file each was added from, kept on it, and the
library it is stamped with; and, when a Job's document is opened, the files not found where they
were looked for again, linked again, or got from the library."""

import FreeCAD
import os
import Path

from Path.Workholding.Common import readDocumentXml
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate


# where a vise's or clamp's file came from, kept on it, hidden
SourceProperties = (
    ("SourceFile", QT_TRANSLATE_NOOP("App::Property", "The file it was added from")),
    (
        "SourceLibrary",
        QT_TRANSLATE_NOOP(
            "App::Property",
            "The library its file is stamped as published in; none when it is not",
        ),
    ),
    ("SourceItem", QT_TRANSLATE_NOOP("App::Property", "Its file's id in that library")),
    (
        "SourceSha256",
        QT_TRANSLATE_NOOP("App::Property", "Its file's sha256 when it was added, to tell a change"),
    ),
)


def keepSource(row, path=None, like=None):
    """keepSource(row, path=None, like=None) ... where the row's file came from kept on it,
    hidden: as like, a row it is another of, has it; else the file at path, its sha256, and the
    library and its id there the file is stamped with."""
    import Path.Workholding.Library as PathLibrary

    if like is not None and getattr(like, "SourceFile", ""):
        values = {name: getattr(like, name, "") for name, _ in SourceProperties}
    elif path:
        stamp = PathLibrary.about(path)
        values = {
            "SourceFile": path,
            "SourceLibrary": stamp.get("library", ""),
            "SourceItem": stamp.get("id", ""),
            "SourceSha256": PathLibrary.fileSha256(path),
        }
    else:
        return
    for name, doc in SourceProperties:
        if not hasattr(row, name):
            row.addProperty("App::PropertyString", name, "Source", doc)
            row.setEditorMode(name, ["Hidden"])
        setattr(row, name, values.get(name, "") or "")


# a document whose vises' or clamps' files are not where they were: found again, or got from the
# library


def _savedLinks(doc):
    """What each link of the document points at as its file was saved: the link's name, the file
    and the name of the object in it. Of a link whose file is not found, FreeCAD keeps them only
    there."""
    found = {}
    path = doc.FileName
    if not path or not os.path.exists(path):
        return found
    root = readDocumentXml(path)
    if root is None:
        return found
    for obj in root.iter("Object"):
        for prop in obj.iter("Property"):
            if prop.get("name") != "LinkedObject":
                continue
            link = prop.find("XLink")
            if link is not None and link.get("file"):
                found[obj.get("name")] = (link.get("file"), link.get("name"))
    return found


def lostParts(doc):
    """lostParts(doc) ... the parts of the document's vises and clamps whose files are not found,
    by the file each was linked from, as it was saved: {file: [(part, the name of its object in
    the file), ...]}."""
    import Path.Workholding.Vise as PathWorkholding

    saved = None
    lost = {}
    for row in doc.Objects:
        if not (PathWorkholding._isGroup(row) and hasattr(row, "Drives")):
            continue
        for part in getattr(row, "Group", []) or []:
            if not part.isDerivedFrom("App::Link") or part.LinkedObject is not None:
                continue
            if saved is None:
                saved = _savedLinks(doc)
            where = saved.get(part.Name)
            if where:
                lost.setdefault(where[0], []).append((part, where[1]))
    return lost


def workholdingFolders():
    """workholdingFolders() ... where vises' and clamps' files are looked for: the CAM assets'
    Workholding/Vises and Workholding/Clamps, Workholding itself, where vises were kept before,
    and the CAM assets' own folder."""
    import Path.Workholding.Library as PathLibrary
    import Path.Preferences

    assets = str(Path.Preferences.getAssetPath())
    root = os.path.join(assets, "Workholding")
    return [PathLibrary.folder(), os.path.join(root, "Clamps"), root, assets]


def _findFile(name, folders):
    base = os.path.basename(name.replace("\\", "/"))
    for folder in folders:
        path = os.path.join(folder, base)
        if os.path.isfile(path):
            return path
    return None


def openFile(path, front=None):
    """openFile(path, front=None) ... the document of the vise's or clamp's file at path, and
    whether it was opened here: one open whole as it is; else opened without a view, front, a
    document, left the active one. One open only in part, for the objects something links, is
    opened again whole: its vise or clamp may not be loaded."""
    wasOpen = False
    for doc in FreeCAD.listDocuments().values():
        if doc.FileName and os.path.exists(doc.FileName) and os.path.samefile(doc.FileName, path):
            if not doc.Partial:
                return doc, False
            wasOpen = True
    doc = FreeCAD.openDocument(path, hidden=True)
    if front is not None:
        FreeCAD.setActiveDocument(front.Name)
        if FreeCAD.GuiUp:
            import FreeCADGui

            FreeCADGui.setActiveDocument(front.Name)
    return doc, not wasOpen


def linkedDocuments(group):
    """linkedDocuments(group) ... the documents of the files the parts of a vise or clamp group
    are linked from, other than its own, in the order its parts are."""
    found = []
    for obj in getattr(group, "Group", []) or []:
        linked = getattr(obj, "LinkedObject", None) if obj.isDerivedFrom("App::Link") else None
        if (
            linked is not None
            and linked.Document != group.Document
            and linked.Document not in found
        ):
            found.append(linked.Document)
    return found


def relinkParts(parts, path):
    """relinkParts(parts, path) ... parts, (part, name) pairs, linked again to the objects of those
    names in the file at path, their vises brought up to date with it. Returns how many were."""
    import Path.Workholding.Vise as PathWorkholding

    source, _ = openFile(path)
    done = 0
    rows = []
    for part, name in parts:
        target = source.getObject(name)
        if target is None:
            continue
        part.LinkedObject = target
        done += 1
        row = part.getParentGeoFeatureGroup()
        if row is not None and row not in rows:
            rows.append(row)
    for row in rows:
        try:
            PathWorkholding.refreshSettings(row)
        except Exception as e:
            Path.Log.warning("%s: %s" % (row.Label, e))
        PathWorkholding.drive(row)
        row.touch()
    return done


def _libraryItem(parts, base, sources, indexes):
    """The library's item for the file parts were linked from: in the library their vise or clamp
    came from first, by its id there, then in sources, the user's libraries when None, by the
    file's name. indexes, an IndexCache, keeps the indexes read."""
    import Path.Workholding.Library as PathLibrary

    rows = _rows(parts)
    own = [getattr(r, "SourceLibrary", "") for r in rows if getattr(r, "SourceLibrary", "")]
    ids = {getattr(r, "SourceItem", "") for r in rows} - {""}
    addresses = own + [a for a in (PathLibrary.sources() if sources is None else sources)]
    items = indexes.items

    for address in own:
        for item in items(address):
            if item["id"] in ids:
                return item
    for address in dict.fromkeys(addresses):
        for item in items(address):
            if os.path.basename(item["file"]) == base:
                return item
    return None


def recoverParts(doc, folders=None, library=None, askLibrary=None, askFile=None):
    """recoverParts(doc, folders=None, library=None, askLibrary=None, askFile=None) ... the
    document's vises and clamps whose files are not found linked again: to a file of the same
    name in folders, workholdingFolders when None; else to the file askFile(file) gives; else,
    when askLibrary(file, item) says so, to the library's, downloaded into the first of folders,
    or where its kind is kept when folders is None, the libraries looked in library's index
    addresses, the user's when None. Those left are said so. Returns {file: the path linked to,
    or None}."""
    lost = lostParts(doc)
    if not lost:
        return {}
    import Path.Workholding.Library as PathLibrary

    into = folders[0] if folders else None
    folders = workholdingFolders() if folders is None else folders
    indexes = PathLibrary.IndexCache(said=Path.Log.info)
    found = {}
    for name, parts in lost.items():
        base = os.path.basename(name.replace("\\", "/"))
        path = _findFile(name, folders)
        if path is None and askFile is not None:
            path = askFile(name)
        if path is None and askLibrary is not None:
            item = _libraryItem(parts, base, library, indexes)
            if item is not None:
                # the library's copy not the one the Job was made with: said so when asked
                used = {getattr(r, "SourceSha256", "") for r in _rows(parts)} - {""}
                item = dict(item, changed=bool(used) and item["sha256"] not in used)
            if item is not None and askLibrary(name, item):
                try:
                    path = PathLibrary.download(item, into)
                except (OSError, ValueError) as e:
                    Path.Log.warning(str(e))
        if path:
            count = relinkParts(parts, path)
            for row in _rows(parts):
                # the sha256 the Job was made with kept: a file that differs is told of after;
                # the library and id it was from kept where the file found says none
                was = {
                    n: getattr(row, n, "") for n in ("SourceSha256", "SourceLibrary", "SourceItem")
                }
                keepSource(row, path)
                for prop, value in was.items():
                    if value and (prop == "SourceSha256" or not getattr(row, prop, "")):
                        setattr(row, prop, value)
            Path.Log.info(
                translate("CAM", "%s: %d parts linked again to %s") % (doc.Label, count, path)
            )
        else:
            Path.Log.warning(
                translate("CAM", "%s: %s not found; its vise or clamp has no parts")
                % (doc.Label, base)
            )
        found[name] = path
    if any(found.values()):
        doc.recompute()
    return found


def _rows(parts):
    return {p.getParentGeoFeatureGroup() for p, _ in parts} - {None}


def changedSources(doc):
    """changedSources(doc) ... the document's vises and clamps whose file is not the one they
    were added with, its sha256 another: (row, path) pairs. The Job's toolpaths were made against
    the one it was."""
    import Path.Workholding.Vise as PathWorkholding

    changed = []
    for row in doc.Objects:
        used = getattr(row, "SourceSha256", "")
        if not used or not PathWorkholding._isGroup(row):
            continue
        # the file its parts are linked from
        path = next((d.FileName for d in linkedDocuments(row) if d.FileName), None)
        if path and os.path.exists(path):
            import Path.Workholding.Library as PathLibrary

            if PathLibrary.fileSha256(path) != used:
                changed.append((row, path))
    return changed


def updatedFrom(row, path, indexes=None):
    """updatedFrom(row, path, indexes=None) ... the name of the library row's file was updated
    from: the file now the one the library publishes, the one row was added with one it
    published before; None if it changed some other way. Only the indexes kept are read, never
    fetched; indexes, an IndexCache, keeps those read."""
    import Path.Workholding.Library as PathLibrary

    indexes = indexes or PathLibrary.IndexCache(online=False)
    sha = PathLibrary.fileSha256(path)
    used = getattr(row, "SourceSha256", "")
    own = getattr(row, "SourceLibrary", "")
    ids = {getattr(row, "SourceItem", "")} - {""}
    # the user's address of the library row came from first, as it may name a branch
    addresses = [
        a
        for a in PathLibrary.sources()
        if own and PathLibrary.libraryKey(a) == PathLibrary.libraryKey(own)
    ]
    addresses += [own] if own else []
    addresses += PathLibrary.sources()
    for address in dict.fromkeys(addresses):
        for item in indexes.items(address, None):
            if ids and item["id"] not in ids:
                continue
            if item["sha256"] == sha and used in item.get("history", []):
                return PathLibrary.libraryName(address)
    return None


def changedFiles(changed):
    """changedFiles(changed) ... (row, path) pairs, as changedSources gives them, by file: for
    each, a dict of its path, the rows using it, and the library it was updated from, None if
    it changed some other way."""
    import Path.Workholding.Library as PathLibrary

    indexes = PathLibrary.IndexCache(online=False)
    files = {}
    for row, path in changed:
        entry = files.setdefault(path, {"path": path, "rows": [], "library": None})
        entry["rows"].append(row)
        if entry["library"] is None:
            entry["library"] = updatedFrom(row, path, indexes)
    return list(files.values())


def acceptChanged(changed):
    """acceptChanged(changed) ... (row, path) pairs, each row's file as it is now taken as the
    one it uses."""
    for row, path in changed:
        keepSource(row, path)


def recoverLater(doc):
    """recoverLater(doc) ... the document's vises and clamps whose files are not found recovered
    once it is loaded and nothing else is asking: in the GUI, which may ask; not without it."""
    if FreeCAD.GuiUp:
        import Path.Workholding.Gui.Source as SourceGui

        SourceGui.recoverWhenIdle(doc)
