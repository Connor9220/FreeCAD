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
from freecad.content_provider import ContentProvider, ContentProviderRegistry
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
            library, "cachedIndexPath", lambda *a: os.path.join(self.dir, "kept.json")
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

    def test05_registered(self):
        """Every registered library is searched, each once; one with no address is left out."""
        repo = "https://github.com/Owner/Machines"

        def provider(name, data):
            return ContentProvider(schema=library.SCHEMA, name=name, label=name, data=data)

        providers = [
            provider("TestRepo", {"repository": repo, "branch": "dev"}),
            provider("TestRepoAgain", {"repository": repo + ".git", "branch": "dev"}),
            provider("TestFolder", {"path": self.lib}),
            provider("TestBroken", {"repository": 3}),
        ]
        try:
            for p in providers:
                ContentProviderRegistry.register(p)
            found = [(a, b) for _, a, b in library.libraries()]
            self.assertEqual(found.count((repo, "dev")) + found.count((repo + ".git", "dev")), 1)
            self.assertIn((self.lib, ""), found)
            self.assertNotIn(3, [a for a, _ in found])
        finally:
            for p in providers:
                ContentProviderRegistry.unregister(schema=library.SCHEMA, name=p.name)

    def test06_github_index(self):
        """A GitHub repository's index is the raw file at the top of its branch."""
        self.assertEqual(
            library.indexAddress("https://github.com/Owner/Machines", "Latest"),
            "https://raw.githubusercontent.com/Owner/Machines/Latest/index.json",
        )
        self.assertEqual(
            library.indexAddress("https://github.com/Owner/Machines.git"),
            "https://raw.githubusercontent.com/Owner/Machines/HEAD/index.json",
        )
