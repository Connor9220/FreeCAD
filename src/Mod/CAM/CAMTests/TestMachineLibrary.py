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

import hashlib
import json
import os
import shutil
import tempfile
from unittest import mock

import CAMTests.PathTestUtils as PathTestUtils
from CAMAssets import library as assets
from Machine.models import library


def _machine(name):
    return json.dumps({"version": 1, "machine": {"name": name, "axes": {}}}).encode()


class TestMachineLibrary(PathTestUtils.PathTestBase):
    """A library of machines: listed from its index, one installed alone and checked."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.lib = os.path.join(self.dir, "lib")
        self.here = os.path.join(self.dir, "here")
        os.makedirs(os.path.join(self.lib, "Machines", "Generic"))
        os.makedirs(self.here)
        self.items = []
        for name in ("Grbl", "LinuxCNC"):
            data = _machine(name)
            path = "Machines/Generic/%s.fcm" % name
            with open(os.path.join(self.lib, path), "wb") as f:
                f.write(data)
            self.items.append(
                {
                    "id": "Generic/" + name,
                    "kind": "machine",
                    "file": path,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "label": name,
                    "group": "Generic",
                }
            )
        self.writeIndex()
        self.cache = mock.patch.object(
            assets, "cachedIndexPath", lambda *a: os.path.join(self.dir, "kept.json")
        )
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        shutil.rmtree(self.dir)

    def writeIndex(self, items=None, format=1):
        with open(os.path.join(self.lib, "index.json"), "w") as f:
            json.dump({"format": format, "items": self.items if items is None else items}, f)

    def test00_listed(self):
        """Each machine of the index is listed with its file's address."""
        items, keptAt = library.loadIndex(self.lib)
        self.assertEqual([i["label"] for i in items], ["Grbl", "LinuxCNC"])
        self.assertTrue(os.path.isfile(items[0]["url"]))
        self.assertIsNone(keptAt)

    def test01_installed_alone(self):
        """Installing one machine saves that file only, and it is then current here."""
        item = library.loadIndex(self.lib)[0][0]
        self.assertEqual(library.status(item, self.here), "absent")
        path = library.download(item, self.here)
        self.assertEqual(os.listdir(self.here), ["Grbl.fcm"])
        self.assertEqual(path, os.path.join(self.here, "Grbl.fcm"))
        self.assertEqual(library.status(item, self.here), "current")

    def test02_states(self):
        """A machine changed here, or an earlier version the library had, is told apart."""
        item = library.loadIndex(self.lib)[0][0]
        path = library.download(item, self.here)
        old = _machine("Grbl old")
        with open(path, "wb") as f:
            f.write(old)
        self.assertEqual(library.status(item, self.here), "modified")
        item["history"] = [{"sha256": hashlib.sha256(old).hexdigest()}]
        self.assertEqual(library.status(item, self.here), "update")

    def test03_refused(self):
        """A file that is not the one listed, or not a machine definition, is not saved."""
        item = library.loadIndex(self.lib)[0][0]
        with open(item["url"], "wb") as f:
            f.write(_machine("changed"))
        with self.assertRaises(ValueError):
            library.download(item, self.here)
        data = b'{"not": "a machine"}'
        with open(item["url"], "wb") as f:
            f.write(data)
        item["sha256"] = hashlib.sha256(data).hexdigest()
        with self.assertRaises(ValueError):
            library.download(item, self.here)
        self.assertEqual(os.listdir(self.here), [])

    def test04_kept_and_newer(self):
        """The index kept is listed when the library cannot be read; a newer one is refused."""
        library.loadIndex(self.lib)
        os.remove(os.path.join(self.lib, "index.json"))
        items, keptAt = library.loadIndex(self.lib)
        self.assertEqual(len(items), 2)
        self.assertIsNotNone(keptAt)
        os.remove(os.path.join(self.dir, "kept.json"))
        with self.assertRaises(ValueError):
            library.loadIndex(self.lib)
        self.writeIndex(format=library.INDEX_FORMAT + 1)
        with self.assertRaises(ValueError):
            library.loadIndex(self.lib)

    def test05_listed_from_the_registry(self):
        """The machine libraries are those registered under the machine schema, FreeCAD's own on
        the branch picked in the preferences, Stable unless another is."""
        prefs = library.Preferences.preferences()
        kept = prefs.GetString(library.BRANCH_PREFERENCE, "")
        try:
            prefs.RemString(library.BRANCH_PREFERENCE)
            with mock.patch.object(assets, "registered", return_value=[("L", self.lib)]) as found:
                self.assertEqual(library.libraries(), [("L", self.lib)])
                found.assert_called_with(library.SCHEMA, {library.FREECAD_LIBRARY: "Stable"})
                # the dialog can list a branch not saved yet
                library.libraries("Latest")
                found.assert_called_with(library.SCHEMA, {library.FREECAD_LIBRARY: "Latest"})
            library.setBranch(" Latest ")
            self.assertEqual(library.branch(), "Latest")
            library.setBranch("")
            self.assertEqual(library.branch(), library.DEFAULT_BRANCH)
        finally:
            if kept:
                prefs.SetString(library.BRANCH_PREFERENCE, kept)
            else:
                prefs.RemString(library.BRANCH_PREFERENCE)
