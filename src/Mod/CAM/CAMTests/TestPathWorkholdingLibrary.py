# SPDX-License-Identifier: LGPL-2.1-or-later

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
import Path.Main.WorkholdingLibrary as PathLibrary
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
            "licence": "CC-BY-4.0",
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
        self.assertEqual(PathLibrary.status(item, self.here), "installed")
        with open(path, "ab") as f:
            f.write(b"changed")
        self.assertEqual(PathLibrary.status(item, self.here), "changed")

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

    def test05_sources_kept(self):
        """The libraries looked in, a preference; none, the default."""
        before = PathLibrary.sources()
        try:
            PathLibrary.setSources(["a", " ", "b "])
            self.assertEqual(PathLibrary.sources(), ["a", "b"])
            PathLibrary.setSources([])
            self.assertEqual(PathLibrary.sources(), PathLibrary.DefaultSources)
        finally:
            PathLibrary.setSources(before)
