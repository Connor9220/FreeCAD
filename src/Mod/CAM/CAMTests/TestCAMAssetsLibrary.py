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

import json
import os
import shutil
import tempfile
from unittest import mock

import CAMTests.PathTestUtils as PathTestUtils
from CAMAssets import library
from freecad.content_provider import ContentProvider, ContentProviderRegistry

SCHEMA = "freecad:cam:test:library"
REPO = "https://github.com/Owner/Lib"


class TestCAMAssetsLibrary(PathTestUtils.PathTestBase):
    """What every library of CAM assets shares: its addresses, the registry, its kept index."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = mock.patch.object(
            library, "cachedIndexPath", lambda *a: os.path.join(self.dir, "kept.json")
        )
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        shutil.rmtree(self.dir)

    def test00_repository_addresses(self):
        """A hosted repository's index is the raw file at the top of a branch or folder."""
        raw = "https://raw.githubusercontent.com/Owner/Lib/"
        self.assertEqual(library.indexAddress(REPO), raw + "HEAD/index.json")
        self.assertEqual(library.indexAddress(REPO + ".git"), raw + "HEAD/index.json")
        self.assertEqual(library.indexAddress(REPO + "/tree/dev/shop"), raw + "dev/shop/index.json")
        self.assertEqual(library.withBranch(REPO, "dev"), REPO + "/tree/dev")
        self.assertEqual(
            library.withBranch(REPO + "/tree/old/shop", "new"), REPO + "/tree/new/shop"
        )
        self.assertEqual(library.withBranch("/x/index.json", "dev"), "/x/index.json")
        self.assertEqual(library.libraryKey(REPO), library.libraryKey(REPO + "/tree/dev"))
        self.assertEqual(library.libraryName(REPO + "/tree/dev"), "Lib (dev)")
        self.assertIsNone(library.entryAddress(raw + "HEAD/index.json", "file:///etc/passwd"))

    def test01_registered(self):
        """Each library registered under a schema is listed once, on its branch; one with no
        address is left out."""

        def provider(name, data):
            return ContentProvider(schema=SCHEMA, name=name, label=name, data=data)

        providers = [
            provider("Repo", {"repository": REPO, "branch": "dev"}),
            provider("RepoAgain", {"repository": REPO + ".git"}),
            provider("Folder", {"path": self.dir}),
            provider("Broken", {"repository": 3}),
        ]
        try:
            for p in providers:
                ContentProviderRegistry.register(p)
            self.assertEqual(
                library.registered(SCHEMA), [("Folder", self.dir), ("Repo", REPO + "/tree/dev")]
            )
            # a branch given for a provider by name is used over its registered one
            self.assertEqual(
                library.registered(SCHEMA, {"Repo": "main"}),
                [("Folder", self.dir), ("Repo", REPO + "/tree/main")],
            )
        finally:
            for p in providers:
                ContentProviderRegistry.unregister(schema=SCHEMA, name=p.name)

    def test02_kept_index(self):
        """An index is kept; the kept copy is read when the library cannot be, and said to be."""
        with open(os.path.join(self.dir, "index.json"), "w") as f:
            json.dump({"format": 1, "items": []}, f)
        index, keptAt = library.readIndex(self.dir, "Kept", 1)
        self.assertIsNone(keptAt)
        os.remove(os.path.join(self.dir, "index.json"))
        index, keptAt = library.readIndex(self.dir, "Kept", 1)
        self.assertEqual(index["items"], [])
        self.assertIsNotNone(keptAt)

    def test03_refused(self):
        """An index too new, or not laid out as one, is refused."""
        for content in ({"format": 2, "items": []}, {"items": "x"}, ["x"]):
            with open(os.path.join(self.dir, "index.json"), "w") as f:
                json.dump(content, f)
            with self.assertRaises(ValueError):
                library.readIndex(self.dir, "Kept", 1)
