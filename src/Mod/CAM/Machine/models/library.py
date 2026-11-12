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

"""Machine libraries: machine definitions (.fcm) to download one at a time.

The libraries are those FreeCAD and addons register as content providers under SCHEMA; what
any library of CAM assets is, and how its index is read and kept, is CAMAssets.library. A
machine picked is saved in the user's Machines folder, where the machine lists find it."""

import json
import os

from CAMAssets import library as assets
from Path import Preferences

# the content provider schema machine libraries are registered under
SCHEMA = "freecad:cam:machine:library"
# the newest index layout this FreeCAD reads
INDEX_FORMAT = 1
# the cache folder machine library indexes are kept in
KEPT = "MachineIndexes"
# FreeCAD's own machine library, whose branch the user picks in the preferences; an addon's
# library is on the branch it registers
FREECAD_LIBRARY = "FreeCAD-Machines"
BRANCHES = ("Stable", "Latest")
DEFAULT_BRANCH = "Stable"
BRANCH_PREFERENCE = "MachineLibraryBranch"


def branch():
    """branch() ... The branch of FreeCAD's machine library the user picked."""
    return Preferences.preferences().GetString(BRANCH_PREFERENCE, DEFAULT_BRANCH).strip() or (
        DEFAULT_BRANCH
    )


def setBranch(name):
    """setBranch(name) ... Pick the branch of FreeCAD's machine library; empty for the default."""
    Preferences.preferences().SetString(BRANCH_PREFERENCE, name.strip() or DEFAULT_BRANCH)


def libraries(freecadBranch=None):
    """libraries(freecadBranch=None) ... Return the registered machine libraries as (label,
    address) pairs, FreeCAD's own on freecadBranch, else on the branch picked in the
    preferences."""
    return assets.registered(SCHEMA, {FREECAD_LIBRARY: freecadBranch or branch()})


def loadIndex(address, online=True):
    """loadIndex(address, online=True) ... Return the machines a library lists, each a dict as
    the index has it plus url (its file's address), and when the list is from the copy kept
    earlier, that copy's time, else None. Raises ValueError for an index that cannot be read
    (see CAMAssets.library.readIndex)."""
    index, keptAt = assets.readIndex(address, KEPT, INDEX_FORMAT, online)
    return assets.listedItems(index, address, ("machine",), "machine"), keptAt


def localPath(item, folder):
    """localPath(item, folder) ... Where a library's machine is saved in folder."""
    return os.path.join(folder, os.path.basename(item["file"]))


def status(item, folder):
    """status(item, folder) ... How a library's machine stands in folder: "absent", "current"
    (the same file), "update" (an earlier version the library had), or "modified" (changed
    here, or another machine of that file name)."""
    sha = assets.fileSha256(localPath(item, folder))
    return "absent" if sha is None else assets.state(sha, item)


def download(item, folder):
    """download(item, folder) ... Save a library's machine in folder and return its path. Raises
    OSError if it cannot be fetched or saved, ValueError if what is fetched is not the file the
    index lists, or not a machine definition."""
    data = assets.fetchChecked(item)
    try:
        machine = json.loads(data.decode("utf-8"))["machine"]
        if not isinstance(machine, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise ValueError("%s is not a machine definition" % item["url"])
    path = localPath(item, folder)
    assets.writeAtomically(path, data)
    return path
