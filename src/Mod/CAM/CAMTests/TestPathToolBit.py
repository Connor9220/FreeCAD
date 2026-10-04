# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2019 sliptonic <shopinthewoods@gmail.com>               *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

from typing import cast
import math
import os
import uuid
import pathlib
import FreeCAD
from CAMTests.PathTestUtils import PathTestWithAssets
from Path.Tool.library import Library
from Path.Tool.shape import (
    ToolBitShapeBullnose,
    ToolBitShapeDovetail,
    ToolBitShapeKeyway,
    ToolBitShapeLollipop,
)
from Path.Tool.toolbit import (
    ToolBitEndmill,
    ToolBitBullnose,
    ToolBitDovetail,
    ToolBitKeyway,
    ToolBitLollipop,
)
from Path.Tool.toolbit.migration import ParameterAccessor, migrate_parameters

TOOL_DIR = pathlib.Path(os.path.realpath(__file__)).parent.parent / "Tools"
SHAPE_DIR = TOOL_DIR / "Shape"
BIT_DIR = TOOL_DIR / "Bit"


class TestPathToolBit(PathTestWithAssets):
    def testGetToolBit(self):
        """Find a tool bit from file name"""
        toolbit = self.assets.get("toolbit://5mm_Endmill")
        self.assertIsInstance(toolbit, ToolBitEndmill)
        self.assertEqual(toolbit.id, "5mm_Endmill")

    def testGetLibrary(self):
        """Find a tool library from file name"""
        library = self.assets.get("toolbitlibrary://Default")
        self.assertIsInstance(library, Library)
        self.assertEqual(library.id, "Default")

    def testBullnose(self):
        """Test ToolBitBullnose basic parameters"""
        shape = self.assets.get("toolbitshape://bullnose")
        shape = cast(ToolBitShapeBullnose, shape)

        bullnose_bit = ToolBitBullnose(shape, id="mybullnose")
        self.assertEqual(bullnose_bit.get_id(), "mybullnose")

        bullnose_bit = ToolBitBullnose(shape)
        uuid.UUID(bullnose_bit.get_id())  # will raise if not valid UUID

        # Parameters should be loaded from the shape file and set on the tool bit's object
        self.assertEqual(bullnose_bit.obj.Diameter, FreeCAD.Units.Quantity("5.0 mm"))
        self.assertEqual(bullnose_bit.obj.CornerRadius, FreeCAD.Units.Quantity("1.5 mm"))

    def testToolBitPickle(self):
        """Test if ToolBit is picklable"""
        import pickle

        shape = self.assets.get("toolbitshape://bullnose")
        shape = cast(ToolBitShapeBullnose, shape)
        bullnose_bit = ToolBitBullnose(shape, id="mybullnose")
        try:
            pickled_bit = pickle.dumps(bullnose_bit)
            unpickled_bit = pickle.loads(pickled_bit)
            self.assertIsInstance(unpickled_bit, ToolBitBullnose)
            self.assertEqual(unpickled_bit.get_id(), "mybullnose")
            # Add more assertions here to check if other attributes are preserved
        except Exception as e:
            self.fail(f"ToolBit is not picklable: {e}")


class TestPathToolBitMigration(PathTestWithAssets):
    """Legacy parameter migration, for .fctb dicts and for document objects."""

    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("TestToolBitMigration")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        super().tearDown()

    def _old_dovetail_dict(self, unit):
        return {
            "version": 2,
            "name": "Old dovetail",
            "shape": "dovetail.fcstd",
            "shape-type": "Dovetail",
            "parameter": {
                "CuttingEdgeAngle": "60.0000 \u00b0",
                "CuttingEdgeHeight": f"9.0000 {unit}",
                "Diameter": f"20.0000 {unit}",
                "Length": f"55.0000 {unit}",
                "NeckDiameter": f"8.0000 {unit}",
                "NeckHeight": f"5.0000 {unit}",
                "ShankDiameter": f"8.0000 {unit}",
                "TipDiameter": f"5.0000 {unit}",
            },
            "attribute": {},
        }

    def testDovetailDictGetsNeckCuttingHeight(self):
        """An old dovetail .fctb gains a zero NeckCuttingHeight in its own unit"""
        for unit in ("mm", "in"):
            with self.subTest(unit=unit):
                attrs = self._old_dovetail_dict(unit)
                self.assertTrue(migrate_parameters(ParameterAccessor(attrs)))
                self.assertEqual(attrs["parameter"]["NeckCuttingHeight"], f"0.0000 {unit}")
                # Nothing else changes.
                old = self._old_dovetail_dict(unit)["parameter"]
                for name, value in old.items():
                    self.assertEqual(attrs["parameter"][name], value)

    def testDovetailDictMigrationIsIdempotent(self):
        """A dovetail that has NeckCuttingHeight keeps its value"""
        attrs = self._old_dovetail_dict("mm")
        attrs["parameter"]["NeckCuttingHeight"] = "3.0000 mm"
        attrs["parameter"]["Units"] = "Metric"
        self.assertFalse(migrate_parameters(ParameterAccessor(attrs)))
        self.assertEqual(attrs["parameter"]["NeckCuttingHeight"], "3.0000 mm")

    def testDovetailObjectGetsNeckCuttingHeight(self):
        """A dovetail document object saved without NeckCuttingHeight gains it"""
        shape = cast(ToolBitShapeDovetail, self.assets.get("toolbitshape://dovetail"))
        obj = ToolBitDovetail(shape, id="olddovetail").attach_to_doc(self.doc)
        obj.removeProperty("NeckCuttingHeight")
        self.assertNotIn("NeckCuttingHeight", obj.PropertiesList)
        volume = obj.BitBody.Shape.Volume

        self.assertTrue(migrate_parameters(ParameterAccessor(obj)))
        self.assertIn("NeckCuttingHeight", obj.PropertiesList)
        self.assertEqual(obj.getGroupOfProperty("NeckCuttingHeight"), "Shape")
        self.assertEqual(obj.NeckCuttingHeight, FreeCAD.Units.Quantity("0 mm"))
        self.assertFalse(migrate_parameters(ParameterAccessor(obj)))

        # NeckCuttingHeight is not geometry: the tool is drawn as before.
        self.doc.recompute()
        self.assertAlmostEqual(obj.BitBody.Shape.Volume, volume, places=6)

    def testDovetailNeckCuttingHeightIsNotGeometry(self):
        """Changing NeckCuttingHeight leaves the dovetail's solid alone"""
        shape = cast(ToolBitShapeDovetail, self.assets.get("toolbitshape://dovetail"))
        obj = ToolBitDovetail(shape, id="dovetail").attach_to_doc(self.doc)
        self.doc.recompute()
        volume = obj.BitBody.Shape.Volume
        obj.NeckCuttingHeight = FreeCAD.Units.Quantity("3 mm")
        self.doc.recompute()
        obj.Proxy._process_queued_visual_update()
        self.assertAlmostEqual(obj.BitBody.Shape.Volume, volume, places=6)


class TestPathToolBitDerivedShapes(PathTestWithAssets):
    """Shapes whose CuttingEdgeHeight follows from their other parameters."""

    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("TestToolBitDerived")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        super().tearDown()

    def _recompute(self, obj):
        self.doc.recompute()
        obj.Proxy._process_queued_visual_update()

    def testKeyway(self):
        """Keyway: CuttingEdgeHeight = LowerCuttingHeight + NeckCuttingHeight, read-only"""
        shape = cast(ToolBitShapeKeyway, self.assets.get("toolbitshape://keyway"))
        obj = ToolBitKeyway(shape, id="keyway").attach_to_doc(self.doc)
        self._recompute(obj)
        self.assertIn("CuttingEdgeHeight", obj.PropertiesList)
        self.assertIn("ReadOnly", obj.getEditorMode("CuttingEdgeHeight"))
        self.assertAlmostEqual(obj.CuttingEdgeHeight.Value, 3.0)

        solid = obj.BitBody.Shape
        self.assertTrue(solid.isValid())
        self.assertAlmostEqual(solid.BoundBox.ZMin, 0.0, places=6)
        self.assertAlmostEqual(solid.BoundBox.ZMax, 50.0, places=6)
        self.assertAlmostEqual(solid.BoundBox.XMax, 10.0, places=6)
        volume = solid.Volume

        obj.NeckCuttingHeight = FreeCAD.Units.Quantity("4 mm")
        self._recompute(obj)
        self.assertAlmostEqual(obj.CuttingEdgeHeight.Value, 7.0)
        # The fluted part of the neck is not drawn: same solid.
        self.assertAlmostEqual(obj.BitBody.Shape.Volume, volume, places=6)

        obj.LowerCuttingHeight = FreeCAD.Units.Quantity("5 mm")
        self._recompute(obj)
        self.assertAlmostEqual(obj.CuttingEdgeHeight.Value, 9.0)
        self.assertGreater(obj.BitBody.Shape.Volume, volume)

    def testLollipop(self):
        """Lollipop: CuttingEdgeHeight is where the neck meets the ball, read-only"""
        shape = cast(ToolBitShapeLollipop, self.assets.get("toolbitshape://lollipop"))
        obj = ToolBitLollipop(shape, id="lollipop").attach_to_doc(self.doc)
        self._recompute(obj)
        self.assertIn("ReadOnly", obj.getEditorMode("CuttingEdgeHeight"))
        self.assertAlmostEqual(obj.CuttingEdgeHeight.Value, 3 + math.sqrt(9 - 2.25), places=6)

        solid = obj.BitBody.Shape
        self.assertTrue(solid.isValid())
        self.assertAlmostEqual(solid.BoundBox.ZMin, 0.0, places=6)
        self.assertAlmostEqual(solid.BoundBox.ZMax, 50.0, places=6)
        self.assertAlmostEqual(solid.BoundBox.XMax, 3.0, places=6)

        obj.NeckDiameter = FreeCAD.Units.Quantity("2 mm")
        self._recompute(obj)
        self.assertAlmostEqual(obj.CuttingEdgeHeight.Value, 3 + math.sqrt(9 - 1), places=6)

    def testLollipopBallOnAShaft(self):
        """A ball on a plain shaft (neck as wide as the shank) still builds"""
        shape = cast(ToolBitShapeLollipop, self.assets.get("toolbitshape://lollipop"))
        obj = ToolBitLollipop(shape, id="ballonshaft").attach_to_doc(self.doc)
        obj.Diameter = FreeCAD.Units.Quantity("6 mm")
        obj.NeckDiameter = FreeCAD.Units.Quantity("4 mm")
        obj.ShankDiameter = FreeCAD.Units.Quantity("4 mm")
        self._recompute(obj)
        solid = obj.BitBody.Shape
        self.assertTrue(solid.isValid())
        self.assertGreater(solid.Volume, 0)
        self.assertAlmostEqual(solid.BoundBox.ZMax, 50.0, places=6)
        self.assertAlmostEqual(solid.BoundBox.XMax, 3.0, places=6)
        # ball, plus a 2 mm radius shaft from where it leaves the ball to the top
        junction = 3 + math.sqrt(9 - 4)
        cap = math.pi * junction**2 * (9 - junction) / 3
        shaft = math.pi * 4 * (50 - junction)
        self.assertAlmostEqual(solid.Volume, cap + shaft, delta=0.05)

    def testSampleKeyway(self):
        """The shipped 3/8in keyway loads, builds, and derives its cutting edge height"""
        toolbit = self.assets.get("toolbit://375_Keyway")
        self.assertIsInstance(toolbit, ToolBitKeyway)
        obj = toolbit.attach_to_doc(self.doc)
        self._recompute(obj)
        self.assertEqual(obj.Units, "Imperial")
        self.assertAlmostEqual(obj.CuttingEdgeHeight.getValueAs("in").Value, 0.125, places=6)
        solid = obj.BitBody.Shape
        self.assertTrue(solid.isValid())
        self.assertAlmostEqual(solid.BoundBox.XMax, 0.375 * 25.4 / 2, places=4)
        self.assertAlmostEqual(solid.BoundBox.ZMax, 2.0 * 25.4, places=4)

    def testSampleLollipop(self):
        """The shipped 1/4in lollipop loads, builds, and derives its cutting edge height"""
        toolbit = self.assets.get("toolbit://250_Lollipop")
        self.assertIsInstance(toolbit, ToolBitLollipop)
        obj = toolbit.attach_to_doc(self.doc)
        self._recompute(obj)
        self.assertEqual(obj.Units, "Imperial")
        expected = 0.125 + math.sqrt(0.125**2 - 0.0625**2)
        self.assertAlmostEqual(obj.CuttingEdgeHeight.getValueAs("in").Value, expected, places=6)
        solid = obj.BitBody.Shape
        self.assertTrue(solid.isValid())
        self.assertAlmostEqual(solid.BoundBox.XMax, 0.125 * 25.4, places=4)
        self.assertAlmostEqual(solid.BoundBox.ZMax, 2.0 * 25.4, places=4)

    def testDefaultLibraryHasTheSamples(self):
        """The default library lists the keyway and lollipop samples"""
        library = self.assets.get("toolbitlibrary://Default")
        labels = [bit.label for bit in library]
        self.assertIn("3/8in Keyway", labels)
        self.assertIn("1/4in Lollipop", labels)
