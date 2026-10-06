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

"""Lever clamps: a hold-down from a file of its own, tipped until its other end rests on the
table or a riser, and strap clamps from a kit, their heels on the step of a step block that
brings them level, their studs as short as reaches."""

import math
import os
import shutil
import tempfile

import FreeCAD
import Part

import Path.Main.Job as PathJob
import Path.Workholding.Items as Items
import Path.Workholding.Lever as Lever
import Path.Workholding.Vise as PathWorkholding
import CAMTests.PathTestUtils as PathTestUtils

from FreeCAD import Vector

# the stock's height in these tests
HEIGHT = 20.0


def _varset(doc, name, values):
    varset = doc.addObject("App::VarSet", name)
    for prop, (kind, value) in values.items():
        varset.addProperty(kind, prop, "Dimensions", "")
        setattr(varset, prop, value)
    return varset


def _piece(doc, name, shape, values):
    part = doc.addObject("App::Part", name)
    solid = doc.addObject("Part::Feature", name + "_Solid")
    solid.Shape = shape
    part.addObjects([solid, _varset(doc, name + "_Dimensions", values)])
    return part


class _Lever(PathTestUtils.PathTestBase):
    def makeJob(self):
        box = self.doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 100, 60, HEIGHT
        self.doc.recompute()
        job = PathJob.Create("Job", [box], None)
        for name in ("ExtXneg", "ExtXpos", "ExtYneg", "ExtYpos", "ExtZneg", "ExtZpos"):
            setattr(job.Stock, name, 0)
        self.doc.recompute()
        return job

    def shapeOf(self, clamp, role):
        """The shape of the clamp's part of role where it stands."""
        part = next(o for o in clamp.Group if getattr(o, "LeverRole", None) == role)
        shape = Part.getShape(part, "", transform=True).copy()
        shape.Placement = clamp.Placement.multiply(shape.Placement)
        return shape

    def assertClearOfStock(self, clamp):
        stock = self.job.Stock.Shape
        for part in clamp.Group:
            shape = Part.getShape(part, "", transform=True).copy()
            shape.Placement = clamp.Placement.multiply(shape.Placement)
            if shape.Solids:
                self.assertRoughly(shape.common(stock).Volume, 0, 1e-2)


class TestPathWorkholdingLeverFile(_Lever):
    """A hold-down from a file of its own whose VarSet's Kind is Lever."""

    def setUp(self):
        # laid out as a hold-down on stock HEIGHT thick: the stock's top at 0, its edge at Y 0,
        # +Y into it. An arm 5 thick pressing on the top at Y 10, back out to a leg down to the
        # table at Y -35; a bolt at Y -20 in the table's track, a washer on the arm's top there
        self.source = FreeCAD.newDocument("TestLeverSource")
        part = self.source.addObject("App::Part", "Clamp")
        part.Label = "Hold-down"
        bar = self.source.addObject("Part::Feature", "Bar")
        bar.Shape = (
            Part.makeBox(20, 40, 5, Vector(-10, -30, 0))
            .fuse(Part.makeBox(20, 10, HEIGHT + 5, Vector(-10, -40, -HEIGHT)))
            .removeSplitter()
        )
        washer = self.source.addObject("Part::Feature", "Washer")
        washer.Shape = Part.makeCylinder(6, 2, Vector(0, -20, 5))
        bolt = self.source.addObject("Part::Feature", "Bolt")
        bolt.Shape = Part.makeCylinder(3, 60, Vector(0, -20, -HEIGHT - 5))
        settings = self.source.addObject("App::VarSet", "Settings")
        settings.addProperty("App::PropertyString", "Kind", "Clamp", "")
        settings.addProperty("App::PropertyLength", "Width", "Clamp", "")
        settings.Kind, settings.Width = "Lever", 20
        for name, kind, value in (
            ("ToeContact", "App::PropertyVector", Vector(0, 10, 0)),
            ("HeelContact", "App::PropertyVector", Vector(0, -35, -HEIGHT)),
            ("BoltAxis", "App::PropertyVector", Vector(0, -20, 5)),
            ("LeverBar", "App::PropertyStringList", ["Bar"]),
            ("LeverRides", "App::PropertyStringList", ["Washer"]),
            ("LeverAnchored", "App::PropertyStringList", ["Bolt"]),
        ):
            settings.addProperty(kind, name, "Lever", "")
            setattr(settings, name, value)
        part.addObjects([bar, washer, bolt, settings])
        self.source.recompute()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "HoldDown_Lever.FCStd")
        self.source.saveAs(self.path)

        self.doc = FreeCAD.newDocument("TestLeverFile")
        self.job = self.makeJob()
        self.doc.saveAs(os.path.join(self.dir, "job.FCStd"))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        FreeCAD.closeDocument(self.source.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test00_found(self):
        """Its file is a clamp's, of Kind Lever."""
        self.assertEqual(Items.clampFile(self.path), ("HoldDown Lever", "Lever"))
        self.assertFalse(Items.pushes(self.path))

    def test01_placed_on_its_side(self):
        """Spread along its side, it presses Overlap in from the edge, its leg on the table, the
        washer on its arm at the bolt, the bolt down in the table's track."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        self.assertTrue(Lever.isLever(clamp))
        self.assertTrue(Items.isClamp(clamp))
        bb = self.job.Stock.Shape.BoundBox
        # the bolt 30 from where it presses, its shank clear of the stock's side by a gap: the
        # washer on the clamp is above the stock
        self.assertRoughly(clamp.Overlap.Value, 30 - 3 - 3.175)
        self.assertRoughly(clamp.Placement.Base.y, bb.YMin + clamp.Overlap.Value)
        self.assertRoughly(clamp.Placement.Base.z, bb.ZMax)
        bar = self.shapeOf(clamp, "Bar")
        self.assertRoughly(bar.BoundBox.ZMin, bb.ZMin)
        self.assertLess(bar.BoundBox.YMin, bb.YMin)
        washer = self.shapeOf(clamp, "Rides")
        self.assertRoughly(washer.distToShape(bar)[0], 0, 1e-6)
        bolt = self.shapeOf(clamp, "Anchored")
        self.assertRoughly(bolt.BoundBox.ZMin, bb.ZMin - 5)
        self.assertClearOfStock(clamp)
        self.assertEqual(clamp.Support, "the table")
        self.assertEqual(clamp.Note, "")

    def test02_on_a_riser(self):
        """On a riser its leg stands on the riser, made under it."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        clamp.RestsOn = "Riser"
        clamp.RiserThickness = 4
        self.doc.recompute()
        bb = self.job.Stock.Shape.BoundBox
        bar = self.shapeOf(clamp, "Bar")
        riser = self.shapeOf(clamp, "Riser")
        self.assertRoughly(riser.BoundBox.ZMin, bb.ZMin)
        self.assertRoughly(riser.BoundBox.ZMax, bb.ZMin + 4)
        self.assertRoughly(bar.distToShape(riser)[0], 0, 1e-3)
        self.assertClearOfStock(clamp)
        clamp.RestsOn = "Table"
        self.doc.recompute()
        self.assertFalse(any(getattr(o, "LeverRole", "") == "Riser" for o in clamp.Group))

    def test03_put_where_it_presses_and_turned(self):
        """Put at an X and Y, it presses there and stays as the stock moves; its angle turns it
        about there."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        Lever.setPress(self.job, clamp, 40, 8)
        self.assertCoincide(clamp.Placement.Base, Vector(40, 8, HEIGHT))
        clamp.Angle = 30
        self.doc.recompute()
        out = clamp.Placement.Rotation.multVec(Vector(1, 0, 0))
        self.assertRoughly(math.degrees(math.atan2(out.y, out.x)), -90 + 30)
        PathWorkholding.moveModel(self.job, Vector(10, 0, 0))
        self.doc.recompute()
        Items.layout(self.job)
        self.assertCoincide(clamp.Placement.Base, Vector(50, 8, HEIGHT))

    def test04_rests_on_the_edge(self):
        """On stock thicker than it is laid out for, its arm meets the stock's edge: it rests
        there, where it was to press lifted off, and says so."""
        self.doc.getObject("Box").Height = HEIGHT + 4
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        self.assertNotEqual(clamp.Note, "")
        self.assertClearOfStock(clamp)

    def test06_bolt_cut_to_fit(self):
        """Its bolt is cut to the shortest reaching past the washer's top by an eighth, in quarter
        inch steps, shown by a trimmed copy; turned off and given a length, as long as that; as
        shipped when that is longer."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        washer = self.shapeOf(clamp, "Rides")
        bolt = next(o for o in clamp.Group if getattr(o, "LeverRole", None) == "Anchored")
        bottom = Part.getShape(bolt, "", transform=True).BoundBox.ZMin
        step = 6.35
        need = washer.BoundBox.ZMax - clamp.Placement.Base.z + 3.175 - (bottom)
        want = math.ceil(need / step - 1e-9) * step
        self.assertRoughly(clamp.BoltLength.Value, want)
        cut = self.shapeOf(clamp, "BoltCut")
        self.assertRoughly(cut.BoundBox.ZLength, want)
        self.assertFalse(bolt.Visibility)
        clamp.BoltFit = False
        clamp.BoltLength = 40
        self.doc.recompute()
        self.assertRoughly(self.shapeOf(clamp, "BoltCut").BoundBox.ZLength, 40)
        clamp.BoltLength = 100
        self.doc.recompute()
        self.assertFalse(any(getattr(o, "LeverRole", "") == "BoltCut" for o in clamp.Group))
        self.assertTrue(bolt.Visibility)

    def test05_another(self):
        """Another of it goes on its side with it, standing as it does."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        clamp.RestsOn = "Riser"
        self.doc.recompute()
        copy = PathWorkholding.addAnother(clamp)
        self.assertTrue(Lever.isLever(copy))
        self.assertEqual(copy.RestsOn, "Riser")
        self.assertEqual(len(Items.clampsOn(self.job, "-Y")), 2)


class TestPathWorkholdingStrapKit(_Lever):
    """Strap clamps from a kit's file: one of each piece, picked for each clamp."""

    def setUp(self):
        self.source = FreeCAD.newDocument("TestStrapKit")
        doc = self.source
        kit = doc.addObject("App::VarSet", "Kit")
        kit.addProperty("App::PropertyString", "Kind", "Kit", "")
        kit.addProperty("App::PropertyString", "Thread", "Kit", "")
        kit.Kind, kit.Thread = "StrapKit", "M10"
        V, L, I = "App::PropertyVector", "App::PropertyLength", "App::PropertyInteger"
        for name, length, slot in (("StepClamp_Short", 60, 20), ("StepClamp_Long", 100, 30)):
            _piece(
                doc,
                name,
                Part.makeBox(length, 20, 10, Vector(0, -10, 0)),
                {
                    "ToeContact": (V, Vector(0, 0, 0)),
                    "HeelTeeth": (V, Vector(length, 0, 0)),
                    "SlotStart": (V, Vector(slot, 0, 10)),
                    "SlotEnd": (V, Vector(slot + 15, 0, 10)),
                    "B_Width": (L, 20),
                    "TeethCount": (I, 0),
                },
            )
        # a step block lying: its tall end at X 0, 30 high, a step down every 5 along X, 5 high
        steps = [Part.makeBox(5, 20, 30 - 5 * i, Vector(5 * i, -10, 0)) for i in range(5)]
        block = steps[0].fuse(steps[1:]).removeSplitter()
        _piece(doc, "StepBlock_Small", block, {"PartNumber": ("App::PropertyString", "B1")})
        # a sawtooth block, no flat steps: its seats given in its VarSet, lying only
        saw = _piece(
            doc,
            "StepBlock_Saw",
            Part.makeBox(40, 20, 40, Vector(0, -10, 0)),
            {
                "PoseLying": (
                    "App::PropertyPlacement",
                    FreeCAD.Placement(Vector(-20, 0, 0), FreeCAD.Rotation()),
                ),
                "SeatsLying": (
                    "App::PropertyVectorList",
                    [Vector(10, 0, 33), Vector(-10, 0, 21), Vector(0, 0, 27)],
                ),
            },
        )
        for name, length in (("Stud_Short", 55), ("Stud_Long", 90)):
            _piece(
                doc,
                name,
                Part.makeCylinder(4, length),
                {"Length": (L, length), "Diameter": (L, 8)},
            )
        _piece(
            doc,
            "TSlotNut_T",
            Part.makeBox(16, 16, 10, Vector(-8, -8, 0)),
            {"TongueTop": (V, Vector(0, 0, 10))},
        )
        _piece(
            doc,
            "FlangeNut_N",
            Part.makeCylinder(8, 8),
            {"Height": (L, 8), "FlangeDiameter": (L, 16)},
        )
        _piece(doc, "CouplingNut_C", Part.makeCylinder(7, 20), {"Length": (L, 20)})
        doc.recompute()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "StrapKit_M10.FCStd")
        doc.saveAs(self.path)

        self.doc = FreeCAD.newDocument("TestStrapKitJob")
        self.job = self.makeJob()
        self.doc.saveAs(os.path.join(self.dir, "job.FCStd"))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        FreeCAD.closeDocument(self.source.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test00_found(self):
        """The kit's file is a clamp's, of Kind StrapKit, and what it holds is read."""
        self.assertEqual(Items.clampFile(self.path), ("StrapKit M10", "StrapKit"))
        kit = Lever.readKit(self.source)
        self.assertEqual([c["label"] for c in kit["clamps"]], ["StepClamp_Short", "StepClamp_Long"])
        self.assertEqual([s["length"] for s in kit["studs"]], [55, 90])
        # lying, five steps 5 apart, the highest 30; standing, steps every 5 up to 25
        treads = kit["blocks"][0]["lying"]["treads"]
        self.assertEqual([round(t[0], 6) for t in treads], [10, 15, 20, 25, 30])
        standing = kit["blocks"][0]["standing"]["treads"]
        self.assertEqual(round(standing[-1][0], 6), 25)
        # a block giving its seats: those, lowest first, its pose the one it gives
        saw = next(b for b in kit["blocks"] if b["label"] == "StepBlock_Saw")
        self.assertEqual([t[0] for t in saw["lying"]["treads"]], [21, 27, 33])
        self.assertEqual([t[1] for t in saw["lying"]["treads"]], [-10, 0, 10])
        self.assertNotIn("standing", saw)

    def test01_level_on_the_step(self):
        """Its heel on the step as high as the stock, it is level, its stud the shortest
        reaching through its nut, every piece clear of the stock."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path, "count": 2}])[0]
        bb = self.job.Stock.Shape.BoundBox
        self.assertRoughly(clamp.Tilt.Value, 0)
        bar = self.shapeOf(clamp, "Clamp")
        self.assertRoughly(bar.BoundBox.ZMin, bb.ZMax)
        block = self.shapeOf(clamp, "Block")
        self.assertRoughly(block.BoundBox.ZMin, bb.ZMin)
        self.assertRoughly(bar.distToShape(block)[0], 0, 1e-6)
        # the T-slot nut's top at the table's, the stud from its bottom up past the nut
        tnut = self.shapeOf(clamp, "TNut")
        self.assertRoughly(tnut.BoundBox.ZMax, bb.ZMin)
        stud = self.shapeOf(clamp, "Stud")
        nut = self.shapeOf(clamp, "Nut")
        self.assertRoughly(stud.BoundBox.ZMin, bb.ZMin - 10)
        self.assertGreaterEqual(stud.BoundBox.ZMax, nut.BoundBox.ZMax)
        self.assertEqual(clamp.Stud, "Stud_Short")
        self.assertClearOfStock(clamp)
        self.assertEqual(clamp.Note, "")

    def test02_higher_than_its_steps(self):
        """Stock higher than any step standing on end: lying, on the step just above it."""
        self.doc.getObject("Box").Height = 28
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        self.assertGreaterEqual(clamp.Tilt.Value, -1e-6)
        self.assertIn("lying", clamp.Support)

    def test03_another_clamp_and_a_riser(self):
        """The long step clamp chosen links it; resting on a riser makes one, the block gone."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        clamp.Clamp = "StepClamp_Long"
        self.doc.recompute()
        bar = next(o for o in clamp.Group if getattr(o, "LeverRole", None) == "Clamp")
        self.assertEqual(bar.LinkedObject.Name, "StepClamp_Long_Solid")
        clamp.RestsOn = "Riser"
        clamp.RiserThickness = 3
        self.doc.recompute()
        roles = [getattr(o, "LeverRole", None) for o in clamp.Group]
        self.assertIn("Riser", roles)
        self.assertNotIn("Block", roles)
        # its heel far below where it presses: it rests on the stock's edge, and says so
        self.assertNotEqual(clamp.Note, "")
        self.assertClearOfStock(clamp)

    def test05_step_block_on_a_riser(self):
        """A step block on a riser: the block for the height left above the riser, standing on
        it, the riser under the block."""
        self.doc.getObject("Box").Height = 40
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        clamp.RestsOn = "RiserAndStepBlock"
        clamp.RiserThickness = 15
        self.doc.recompute()
        bb = self.job.Stock.Shape.BoundBox
        self.assertGreaterEqual(clamp.Tilt.Value, -1e-6)
        block = self.shapeOf(clamp, "Block")
        self.assertRoughly(block.BoundBox.ZMin, bb.ZMin + 15)
        riser = self.shapeOf(clamp, "Riser")
        self.assertRoughly(riser.BoundBox.ZMax, bb.ZMin + 15)
        self.assertLessEqual(riser.BoundBox.XMin, block.BoundBox.XMin)
        self.assertIn("riser", clamp.Support)
        self.assertClearOfStock(clamp)

    def test06_blocks_meshed(self):
        """Stock taller than any block: two meshed teeth into teeth, the upper one upside down,
        the heel level on its flat top."""
        self.doc.getObject("Box").Height = 50
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        bb = self.job.Stock.Shape.BoundBox
        lower = self.shapeOf(clamp, "BlockUnder")
        upper = self.shapeOf(clamp, "Block")
        self.assertRoughly(lower.BoundBox.ZMin, bb.ZMin)
        self.assertRoughly(upper.BoundBox.ZMax, bb.ZMax)
        self.assertRoughly(clamp.Tilt.Value, 0)
        self.assertLess(lower.common(upper).Volume, 1e-3)
        self.assertIn("teeth into teeth", clamp.Support)
        self.assertEqual(clamp.Note, "")

    def test08_riser_when_none_reaches(self):
        """Stock taller than any two meshed: a riser under them, as thin as lets them reach,
        in its steps, the heel not below level and not so high it is said."""
        self.doc.getObject("Box").Height = 90
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        riser = self.shapeOf(clamp, "Riser")
        self.assertIsNotNone(riser)
        self.assertIn("riser", clamp.Support)
        self.assertNotIn("low", clamp.Note)
        self.assertGreaterEqual(clamp.Tilt.Value, -1e-6)
        self.assertLess(clamp.Tilt.Value, 10)

    def test09_plain_heel_on_a_pair(self):
        """A clamp whose heel has no teeth stands on a meshed pair's flat top, even where one
        block reaches."""
        for part in self.source.RootObjects:
            if part.TypeId == "App::Part" and part.Name.startswith("StepClamp_"):
                sizes = next(o for o in part.Group if o.TypeId == "App::VarSet")
                sizes.addProperty("App::PropertyBool", "HeelToothed", "Dimensions", "")
                sizes.HeelToothed = False
        self.source.save()
        self.doc.getObject("Box").Height = 20
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        self.assertIn("teeth into teeth", clamp.Support)

    def test10_never_big_on_small(self):
        """Of a pair, the block on top is never bigger than the one under it."""
        self.doc.getObject("Box").Height = 50
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        lower = self.shapeOf(clamp, "BlockUnder")
        upper = self.shapeOf(clamp, "Block")
        self.assertGreaterEqual(lower.Volume + 1e-6, upper.Volume)

    def test11_stands_on_what_is_under_it(self):
        """A plate of the workholding under its other end: its step block stands on the plate,
        not the table."""
        self.doc.getObject("Box").Height = 20
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        before = self.shapeOf(clamp, "Block").BoundBox
        plate = self.doc.addObject("Part::Box", "Plate")
        plate.Length, plate.Width, plate.Height = before.XLength + 20, before.YLength + 20, 6
        plate.Placement.Base = Vector(before.XMin - 10, before.YMin - 10, before.ZMin)
        self.job.Workholding.addObject(plate)
        self.doc.recompute()
        Items.layout(self.job)
        self.doc.recompute()
        after = self.shapeOf(clamp, "Block").BoundBox
        self.assertRoughly(after.ZMin, before.ZMin + 6, 1e-3)

    def test07_studs_joined(self):
        """Too tall for one stud: two, joined by the kit's coupling nut, the longer below."""
        self.doc.getObject("Box").Height = 100
        self.doc.recompute()
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        clamp.RestsOn = "Riser"
        clamp.RiserThickness = 100
        self.doc.recompute()
        lower = self.shapeOf(clamp, "Stud")
        upper = self.shapeOf(clamp, "StudUpper")
        coupler = self.shapeOf(clamp, "Coupler")
        self.assertRoughly(upper.BoundBox.ZMin, lower.BoundBox.ZMax)
        self.assertRoughly(coupler.BoundBox.Center.z, lower.BoundBox.ZMax)
        self.assertGreaterEqual(lower.BoundBox.ZLength, upper.BoundBox.ZLength - 1e-6)
        self.assertIn("joined", clamp.Stud)
        self.assertNotIn("stud", clamp.Note)
        # back down: one stud, the second and the coupling nut gone
        clamp.RestsOn = "StepBlock"
        self.doc.getObject("Box").Height = 20
        self.doc.recompute()
        Items.layout(self.job)
        roles = [getattr(o, "LeverRole", None) for o in clamp.Group]
        self.assertNotIn("StudUpper", roles)
        self.assertNotIn("Coupler", roles)

    def test04_bolt_where_put(self):
        """Its bolt where Bolt at puts it from the end pressing, kept in its slot; Auto as near the
        stock as clears it."""
        clamp = Items.setClamps(self.job, [{"side": "-Y", "which": self.path}])[0]
        auto = clamp.BoltFound.Value
        # the short clamp's slot runs 20 to 35 from its toe
        self.assertGreaterEqual(auto, 20 - 1e-6)
        self.assertLessEqual(auto, 35 + 1e-6)
        clamp.BoltAt = 32
        self.doc.recompute()
        self.assertRoughly(clamp.BoltFound.Value, 32)
        self.assertEqual(clamp.Note, "")
        self.assertClearOfStock(clamp)
        clamp.BoltAt = 50
        self.doc.recompute()
        self.assertRoughly(clamp.BoltFound.Value, 35)
        self.assertEqual([round(v, 6) for v in Lever.boltRange(clamp)], [20, 35])
        clamp.BoltAt = 0
        self.doc.recompute()
        self.assertRoughly(clamp.BoltFound.Value, auto)
