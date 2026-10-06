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

import FreeCAD
import Part
import Path.Workholding.Library as PathLibrary
import CAMTests.PathTestUtils as PathTestUtils


class TestPathWorkholdingLibrary(PathTestUtils.PathTestBase):
    """A library of vises: its index read, what is here told, a vise downloaded and checked."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.library = os.path.join(self.dir, "library")
        self.here = os.path.join(self.dir, "here")
        os.makedirs(os.path.join(self.library, "vises"))
        self.vise = self.makeVise("Test_Vise", python=False)
        self.writeIndex([self.entry("Test_Vise")])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def makeVise(self, name, python):
        """A vise's file in the library: a part, a body and a VarSet with a vise's settings."""
        doc = FreeCAD.newDocument("TestLibraryVise")
        part = doc.addObject("App::Part", "Vise")
        body = doc.addObject("Part::Feature", "Body")
        body.Shape = Part.makeBox(10, 10, 10)
        settings = doc.addObject("App::VarSet", "Settings")
        for prop in ("Opening", "JawHeight", "MaxOpening"):
            settings.addProperty("App::PropertyLength", prop, "Vise", "")
        settings.MaxOpening = 100
        part.addObjects([body, settings])
        if python:
            doc.addObject("App::FeaturePython", "Script")
        path = os.path.join(self.library, "vises", name + ".FCStd")
        doc.saveAs(path)
        FreeCAD.closeDocument(doc.Name)
        return path

    def entry(self, name, **changes):
        path = os.path.join(self.library, "vises", name + ".FCStd")
        with open(path, "rb") as f:
            data = f.read()
        item = {
            "id": name,
            "kind": "vise",
            "file": "vises/%s.FCStd" % name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "label": name,
            "license": "CC-BY-4.0",
        }
        item.update(changes)
        return item

    def writeIndex(self, items, format=1):
        self.index = os.path.join(self.library, "index.json")
        with open(self.index, "w") as f:
            json.dump({"format": format, "items": items}, f)

    def test00_index_read(self):
        """The index's vises, their files' addresses beside the index, file:// or a path."""
        for address in (self.index, "file://" + self.index):
            items = PathLibrary.loadIndex(address)
            self.assertEqual([i["id"] for i in items], ["Test_Vise"])
            self.assertTrue(items[0]["url"].endswith("library/vises/Test_Vise.FCStd"))

    def test01_downloaded_and_told_here(self):
        """Not here, then downloaded into the folder vises are kept in: installed; changed here,
        told so."""
        item = PathLibrary.loadIndex(self.index)[0]
        self.assertEqual(PathLibrary.status(item, self.here), "missing")
        path = PathLibrary.download(item, self.here)
        self.assertEqual(path, os.path.join(self.here, "Test_Vise.FCStd"))
        self.assertEqual(PathLibrary.status(item, self.here), "current")
        with open(path, "ab") as f:
            f.write(b"changed")
        self.assertEqual(PathLibrary.status(item, self.here), "modified")

    def test06_stamp_read(self):
        """What a file says of itself, stamped in its settings' About group, read without
        opening it; a file not stamped says only its label."""
        doc = FreeCAD.openDocument(self.vise)
        settings = doc.getObject("Settings")
        for name, value in (
            ("Library", "https://github.com/Owner/Lib"),
            ("LibraryItem", "Test_Vise"),
            ("Type", "CNC"),
            ("Maker", "Someone"),
        ):
            settings.addProperty("App::PropertyString", name, "About", "")
            setattr(settings, name, value)
        doc.getObject("Vise").Label = "A test vise"
        doc.saveAs(os.path.join(self.dir, "stamped.FCStd"))
        FreeCAD.closeDocument(doc.Name)
        found = PathLibrary.about(os.path.join(self.dir, "stamped.FCStd"))
        self.assertEqual(
            found,
            {
                "library": "https://github.com/Owner/Lib",
                "id": "Test_Vise",
                "type": "CNC",
                "maker": "Someone",
                "label": "A test vise",
                "kind": "vise",
                "settings": {"maxOpening": 100.0},
            },
        )
        self.assertEqual(
            PathLibrary.about(self.vise),
            {"label": "Vise", "kind": "vise", "settings": {"maxOpening": 100.0}},
        )
        self.assertEqual(PathLibrary.about(os.path.join(self.dir, "none.FCStd")), {})
        # those on this computer: the stamped one by its library, the other its own
        local = PathLibrary.localItems("vise", [self.dir, os.path.dirname(self.vise)])
        self.assertEqual(
            [(i["id"], i["label"], i.get("library", "")) for i in local],
            [
                ("stamped", "A test vise", "https://github.com/Owner/Lib"),
                ("Test_Vise", "Vise", ""),
            ],
        )
        self.assertEqual(local[0]["libraryItem"], "Test_Vise")
        self.assertEqual(PathLibrary.localItems("clamp", [self.dir]), [])

    def test02_wrong_file_refused(self):
        """A file not the one the index lists, by its sha256, is refused and not saved."""
        self.writeIndex([self.entry("Test_Vise", sha256="0" * 64)])
        item = PathLibrary.loadIndex(self.index)[0]
        with self.assertRaises(ValueError):
            PathLibrary.download(item, self.here)
        self.assertEqual(PathLibrary.status(item, self.here), "missing")

    def test03_python_refused(self):
        """A vise holding Python, run when it is opened, is refused though the index lists it
        right."""
        self.makeVise("Script_Vise", python=True)
        self.writeIndex([self.entry("Script_Vise")])
        item = PathLibrary.loadIndex(self.index)[0]
        with self.assertRaises(ValueError) as caught:
            PathLibrary.download(item, self.here)
        self.assertIn("Python", str(caught.exception))
        self.assertFalse(os.path.exists(os.path.join(self.here, "Script_Vise.FCStd")))

    def test04_newer_library_refused(self):
        """An index laid out for a newer FreeCAD is not read."""
        self.writeIndex([self.entry("Test_Vise")], format=PathLibrary.IndexFormat + 1)
        with self.assertRaises(ValueError):
            PathLibrary.loadIndex(self.index)

    def test09_branches(self):
        """A library kept with its branch, a GitHub repository's looked in on it; one kept before
        branches, an address a line, read as on its default branch."""
        before = PathLibrary.libraries()
        repo = "https://github.com/Owner/Lib"
        try:
            PathLibrary.setLibraries([(repo, "dev"), ("/a folder/with spaces", ""), (" ", "x")])
            self.assertEqual(
                PathLibrary.libraries(), [(repo, "dev"), ("/a folder/with spaces", "")]
            )
            self.assertEqual(PathLibrary.sources(), [repo + "/tree/dev", "/a folder/with spaces"])
            self.assertEqual(
                PathLibrary.indexAddress(PathLibrary.sources()[0]),
                "https://raw.githubusercontent.com/Owner/Lib/dev/index.json",
            )
            PathLibrary.setLibraries([(repo, "")])
            self.assertEqual(PathLibrary.libraries(), [(repo, "")])
            self.assertEqual(PathLibrary.withBranch(repo + "/tree/old", "new"), repo + "/tree/new")
            self.assertEqual(PathLibrary.withBranch("/x/index.json", "dev"), "/x/index.json")
        finally:
            PathLibrary.setLibraries(before)

    def test10_library_names(self):
        """A library's name to show: a repository's, with its branch; a folder's."""
        for address, name in (
            ("https://github.com/Owner/Lib", "Lib"),
            ("https://github.com/Owner/Lib.git", "Lib"),
            ("https://github.com/Owner/Lib/tree/dev", "Lib (dev)"),
            ("https://raw.githubusercontent.com/Owner/Lib/main/index.json", "Lib"),
            ("https://example.com/shop/index.json", "shop"),
            ("/home/me/Shop library", "Shop library"),
            ("/home/me/Shop library/index.json", "Shop library"),
        ):
            self.assertEqual(PathLibrary.libraryName(address), name)

    def test11_updates_told(self):
        """A file here against its library's item: the one it has now, one it published before,
        an update, or one it never did, modified here; told of those on this computer, from the
        index kept, by the library they are stamped with on any of its branches."""
        item = {"sha256": "new", "history": ["old", "older"]}
        self.assertEqual(PathLibrary.state("new", item), "current")
        self.assertEqual(PathLibrary.state("older", item), "update")
        self.assertEqual(PathLibrary.state("mine", item), "modified")
        # an index that keeps the commit that published each version
        item = {
            "sha256": "new",
            "history": [{"sha256": "old", "commit": "c1"}, {"sha256": "older"}],
        }
        self.assertEqual(PathLibrary.history(item), ["old", "older"])
        self.assertEqual(PathLibrary.state("old", item), "update")
        self.assertEqual(PathLibrary.publishedIn(item, "old"), "c1")
        self.assertIsNone(PathLibrary.publishedIn(item, "older"))
        self.assertEqual(
            PathLibrary.libraryKey("https://github.com/Owner/Lib/tree/dev"),
            PathLibrary.libraryKey("https://github.com/owner/lib"),
        )
        # a stamped vise here, its library's index listing a newer one, this one before it
        doc = FreeCAD.openDocument(self.vise)
        settings = doc.getObject("Settings")
        for name, value in (("Library", "https://github.com/Owner/Lib"), ("LibraryItem", "V")):
            settings.addProperty("App::PropertyString", name, "About", "")
            setattr(settings, name, value)
        here = os.path.join(self.dir, "mine")
        os.makedirs(here)
        doc.saveAs(os.path.join(here, "V.FCStd"))
        FreeCAD.closeDocument(doc.Name)
        sha = PathLibrary.fileSha256(os.path.join(here, "V.FCStd"))
        entry = dict(self.entry("Test_Vise"), id="V", history=[sha])
        self.writeIndex([entry])
        local = PathLibrary.localItems("vise", [here])
        library = "https://github.com/Owner/Lib/tree/main"
        cached = PathLibrary._cached(library)
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        shutil.copy(self.index, cached)
        try:
            found = PathLibrary.localStates(local, [library])
            self.assertEqual(found[0][0], "update")
            self.assertEqual(found[0][1]["id"], "V")
            # not among the user's libraries: not told
            self.assertEqual(PathLibrary.localStates(local, []), [(None, None)])
            # kept, read without fetching; not fetched and not kept, said so
            self.assertEqual(len(PathLibrary.loadIndex(library, online=False)), 1)
            with self.assertRaises(ValueError):
                PathLibrary.loadIndex(os.path.join(self.dir, "nowhere.json"), online=False)
        finally:
            os.remove(cached)

    def test07_github_repository(self):
        """A GitHub repository's address stands for the index.json at its top, as served raw; a
        folder's for the one in it."""
        raw = "https://raw.githubusercontent.com/Owner/Lib/"
        for address, index in (
            ("https://github.com/Owner/Lib", raw + "HEAD/index.json"),
            ("https://github.com/Owner/Lib.git/", raw + "HEAD/index.json"),
            ("https://github.com/Owner/Lib/tree/dev", raw + "dev/index.json"),
            ("https://github.com/Owner/Lib/tree/dev/shop", raw + "dev/shop/index.json"),
            ("https://github.com/Owner/Lib/blob/main/index.json", raw + "main/index.json"),
            (raw + "main/index.json", raw + "main/index.json"),
        ):
            self.assertEqual(PathLibrary.indexAddress(address), index)
        self.writeIndex([self.entry("Test_Vise")])
        self.assertEqual(PathLibrary.indexAddress(self.library), self.index)
        self.assertEqual(PathLibrary.indexAddress(self.index), self.index)
        self.assertEqual(len(PathLibrary.loadIndex(self.library)), 1)

    def test08_clamps(self):
        """A library's clamps listed apart from its vises, downloaded where clamps are kept,
        checked as a clamp's file: one that is not a clamp refused."""
        os.makedirs(os.path.join(self.library, "clamps"))
        doc = FreeCAD.newDocument("TestLibraryClamp")
        part = doc.addObject("App::Part", "Clamp")
        body = doc.addObject("Part::Feature", "Body")
        body.Shape = Part.makeBox(10, 10, 10)
        settings = doc.addObject("App::VarSet", "Settings")
        settings.addProperty("App::PropertyString", "Kind", "Clamp", "")
        settings.Kind = "HoldDown"
        part.addObjects([body, settings])
        doc.saveAs(os.path.join(self.library, "clamps", "Test_Clamp.FCStd"))
        FreeCAD.closeDocument(doc.Name)
        data = open(os.path.join(self.library, "clamps", "Test_Clamp.FCStd"), "rb").read()
        clamp = dict(
            self.entry("Test_Vise"),
            id="Test_Clamp",
            kind="clamp",
            file="clamps/Test_Clamp.FCStd",
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        # a vise's file listed as a clamp
        fake = self.entry("Test_Vise", id="Fake", kind="clamp")
        self.writeIndex([self.entry("Test_Vise"), clamp, fake])
        self.assertEqual([i["id"] for i in PathLibrary.loadIndex(self.index)], ["Test_Vise"])
        clamps = PathLibrary.loadIndex(self.index, "clamp")
        self.assertEqual([i["id"] for i in clamps], ["Test_Clamp", "Fake"])
        self.assertEqual(len(PathLibrary.loadIndex(self.index, None)), 3)
        self.assertTrue(
            PathLibrary.localPath(clamps[0]).endswith(os.path.join("Clamps", "Test_Clamp.FCStd"))
        )
        path = PathLibrary.download(clamps[0], self.here)
        self.assertEqual(path, os.path.join(self.here, "Test_Clamp.FCStd"))
        with self.assertRaises(ValueError):
            PathLibrary.download(clamps[1], os.path.join(self.dir, "elsewhere"))

    def test05_sources_kept(self):
        """The libraries looked in, a preference; none, the default."""
        before = PathLibrary.libraries()
        try:
            PathLibrary.setLibraries([("a", ""), (" ", ""), ("b ", "")])
            self.assertEqual(PathLibrary.sources(), ["a", "b"])
            PathLibrary.setLibraries([])
            self.assertEqual(PathLibrary.sources(), PathLibrary.DefaultSources)
        finally:
            PathLibrary.setLibraries(before)
