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

"""Seating a Job's stock in a vise of its Workholding."""

import FreeCAD
import math
import os
import shutil
import tempfile

import Part
import Path.Main.Job as PathJob
import Path.Main.Workholding as PathWorkholding
import Path.Main.WorkholdingCheck as PathWorkholdingCheck
import Path.Main.WorkholdingParallels as PathParallels
import CAMTests.PathTestUtils as PathTestUtils

from FreeCAD import Vector


class TestPathWorkholding(PathTestUtils.PathTestBase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPathWorkholding")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.Length, self.box.Width, self.box.Height = 100, 60, 40
        self.doc.recompute()
        self.job = PathJob.Create("Job", [self.box], None)
        self.doc.recompute()
        # a vise turned so its jaws close along +X, the fixed jaw's face at X -20, across Y 50,
        # its jaw tops at Z 10
        self.vise = self.doc.addObject("App::Part", "Vise")
        self.vise.Placement = FreeCAD.Placement(
            Vector(-20, 50, 10), FreeCAD.Rotation(Vector(0, 0, 1), 90)
        )
        self.setup = self.doc.addObject("App::VarSet", "ViseSetup")
        self.setup.addProperty("App::PropertyLength", "Opening", "Vise", "")
        self.setup.addProperty("App::PropertyLength", "JawHeight", "Vise", "")
        self.setup.Opening = 50
        self.setup.JawHeight = 30
        self.vise.addObject(self.setup)
        self.job.Workholding.addObject(self.vise)
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def stock(self):
        return self.job.Stock.Shape.BoundBox

    def test00_found(self):
        """A container with an Opening in the Workholding is a vise."""
        self.assertEqual(PathWorkholding.vises(self.job), [self.vise])
        self.assertEqual(PathWorkholding.viseSetup(self.vise)["jawHeight"], 30)

    def test01_part_moves_into_the_vise(self):
        """The stock goes against the fixed jaw, centred across, held as deep as asked."""
        length = self.stock().XLength
        done = PathWorkholding.seat(self.job, self.vise, grip=12)
        bb = self.stock()
        self.assertRoughly(bb.XMin, -20)
        self.assertRoughly((bb.YMin + bb.YMax) / 2, 50)
        self.assertRoughly(bb.ZMin, -2)
        self.assertRoughly(self.setup.Opening.Value, length)
        self.assertRoughly(done["opening"], length)
        # the vise stayed
        self.assertRoughly(self.vise.Placement.Base.x, -20)

    def test02_vise_moves_to_the_part(self):
        """With the vise moving the part stays, and the vise comes to it."""
        before = self.stock()
        PathWorkholding.seat(self.job, self.vise, grip=12, moveVise=True)
        after = self.stock()
        self.assertRoughly(after.XMin, before.XMin)
        self.assertRoughly(after.ZMin, before.ZMin)
        self.assertRoughly(self.vise.Placement.Base.x, before.XMin)
        self.assertRoughly(self.vise.Placement.Base.y, (before.YMin + before.YMax) / 2)
        self.assertRoughly(self.vise.Placement.Base.z, before.ZMin + 12)

    def test03_offset_along_the_jaws(self):
        """Offset moves the stock along the jaws from the centre."""
        PathWorkholding.seat(self.job, self.vise, grip=5, offset=10)
        bb = self.stock()
        self.assertRoughly((bb.YMin + bb.YMax) / 2, 60)

    def test04_stock_cannot_stand_above_the_jaws(self):
        """A negative grip is refused."""
        with self.assertRaises(ValueError):
            PathWorkholding.seat(self.job, self.vise, grip=-1)

    def test05_moving_the_part_recomputes_the_operations(self):
        """An operation made from the stock, not the model, is computed again when the part
        moves: nothing links it to what moved."""
        import Path.Op.Custom as PathCustom

        op = PathCustom.Create("Op", parentJob=self.job)
        self.doc.recompute()
        self.assertNotIn("Touched", op.State)
        PathWorkholding.moveModel(self.job, Vector(0, 0, 5))
        self.assertIn("Touched", op.State)

    def test06_on_parallels(self):
        """On parallels the stock stands that high off the floor: the jaws hold the rest."""
        done = PathWorkholding.seat(self.job, self.vise, parallels=12.7)
        bb = self.stock()
        # the jaw tops at Z 10, the jaws 30 tall: the floor at -20
        self.assertRoughly(bb.ZMin, -20 + 12.7)
        self.assertRoughly(done["grip"], 30 - 12.7)
        self.assertRoughly(done["parallels"], 12.7)

    def test07_vise_linked_in(self):
        """A vise linked in from its own file stands where the link puts it."""
        self.job.Workholding.removeObject(self.vise)
        placement = self.vise.Placement
        self.vise.Placement = FreeCAD.Placement()
        link = self.doc.addObject("App::Link", "ViseLink")
        link.LinkedObject = self.vise
        link.Placement = placement
        self.job.Workholding.addObject(link)
        self.doc.recompute()
        self.assertEqual(PathWorkholding.vises(self.job), [link])
        self.assertTrue(PathWorkholding.placementOf(link).isSame(placement, 1e-9))
        PathWorkholding.seat(self.job, link, grip=12)
        bb = self.stock()
        self.assertRoughly(bb.XMin, -20)
        self.assertRoughly((bb.YMin + bb.YMax) / 2, 50)
        self.assertRoughly(bb.ZMin, -2)

    def test09_seating_as_it_was(self):
        """How the stock sits in a vise is found again: its grip and offset from where it is,
        whether on parallels and whether the jaw was closed as it was last seated."""
        PathWorkholding.seat(self.job, self.vise, parallels=12.7, offset=10, close=False)
        now = PathWorkholding.seating(self.job, self.vise)
        self.assertRoughly(now["grip"], 30 - 12.7)
        self.assertRoughly(now["offset"], 10)
        self.assertTrue(now["onParallels"])
        self.assertFalse(now["close"])
        # kept on the vise: the parallels; the grip and offset are its placement's
        self.assertTrue(self.vise.Seated)
        self.assertRoughly(self.vise.Parallels.Value, 12.7)
        self.assertNotIn("Hidden", self.vise.getEditorMode("Parallels"))
        self.assertFalse(hasattr(self.vise, "Grip") or hasattr(self.vise, "Offset"))
        PathWorkholding.seat(self.job, self.vise, grip=5)
        now = PathWorkholding.seating(self.job, self.vise)
        self.assertRoughly(now["grip"], 5)
        self.assertRoughly(now["offset"], 0)
        self.assertFalse(now["onParallels"])
        self.assertTrue(now["close"])
        # held by the grip alone: no parallels shown
        self.assertIn("Hidden", self.vise.getEditorMode("Parallels"))

    def test08_too_small_a_vise(self):
        """A vise that cannot open as far as the stock is long says so, and opens all it can."""
        self.setup.addProperty("App::PropertyLength", "MaxOpening", "Vise", "")
        self.setup.MaxOpening = 40
        needed, most, _ = PathWorkholding.opening(self.job, self.vise)
        self.assertRoughly(most, 40)
        done = PathWorkholding.seat(self.job, self.vise, grip=12)
        self.assertFalse(done["fits"])
        self.assertRoughly(self.setup.Opening.Value, 40)
        self.setup.MaxOpening = 200
        self.assertTrue(PathWorkholding.seat(self.job, self.vise, grip=12)["fits"])


class TestPathWorkholdingAdd(PathTestUtils.PathTestBase):
    """Vises added from a vise's own file, and another beside one."""

    def setUp(self):
        # a vise's own file: its body, its moving jaw driven by its Opening, and its hard jaw
        # plates, 100 across, 10 thick and 25 tall, the moving one drawn closed
        self.source = FreeCAD.newDocument("TestViseSource")
        part = self.source.addObject("App::Part", "Vise")
        part.Label = "Test vise"
        body = self.source.addObject("Part::Box", "Body")
        jaw = self.source.addObject("Part::Box", "MovingJaw")
        fixedPlate = self.source.addObject("Part::Box", "FixedPlate")
        fixedPlate.Length, fixedPlate.Width, fixedPlate.Height = 100, 10, 25
        fixedPlate.Placement.Base = Vector(-50, 0, -25)
        movingPlate = self.source.addObject("Part::Feature", "MovingPlate")
        movingPlate.Shape = Part.makeBox(100, 10, 25, Vector(-50, -10, -25))
        settings = self.source.addObject("App::VarSet", "Vise")
        settings.addProperty("App::PropertyLength", "Opening", "Vise", "")
        settings.addProperty("App::PropertyLength", "JawHeight", "Vise", "")
        settings.addProperty("App::PropertyLength", "MaxOpening", "Vise", "")
        settings.addProperty("App::PropertyStringList", "JawPlates", "Vise", "")
        settings.Opening, settings.JawHeight, settings.MaxOpening = 20, 30, 150
        settings.JawPlates = [fixedPlate.Name, movingPlate.Name]
        part.addObjects([body, jaw, fixedPlate, movingPlate, settings])
        jaw.setExpression(".Placement.Base.y", "-%s.Opening" % settings.Name)
        movingPlate.setExpression(".Placement.Base.y", "-%s.Opening" % settings.Name)
        self.source.recompute()
        self.part, self.settings = part, settings
        # a link to another document needs both saved
        self.dir = tempfile.mkdtemp()
        self.source.saveAs(os.path.join(self.dir, "vise.FCStd"))

        self.doc = FreeCAD.newDocument("TestViseAdd")
        box = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        self.job = PathJob.Create("Job", [box], None)
        self.doc.recompute()
        self.doc.saveAs(os.path.join(self.dir, "job.FCStd"))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        FreeCAD.closeDocument(self.source.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def jaw(self, vise):
        driven = [entry.split("\t")[0] for entry in vise.Drives]
        return [o for o in vise.Group if o.Name in driven][0]

    def test00_added_opens_on_its_own(self):
        """An added vise has its own settings: seating it leaves the vise's file alone."""
        vise = PathWorkholding.addVise(self.job, self.part)
        self.assertEqual(PathWorkholding.vises(self.job), [vise])
        setup = PathWorkholding.viseSetup(vise)
        # its settings on the vise itself, no VarSet in it
        self.assertEqual(setup["opening"], vise)
        self.assertFalse([o for o in vise.Group if o.TypeId == "App::VarSet"])
        self.assertRoughly(vise.JawHeight.Value, 30)
        self.assertEqual(vise.getGroupOfProperty("Opening"), "Vise")
        self.assertRoughly(setup["maxOpening"], 150)
        setup["opening"].Opening = 55
        self.doc.recompute()
        self.assertRoughly(self.jaw(vise).Placement.Base.y, -55)
        self.assertRoughly(self.settings.Opening.Value, 20)

    def bottom(self, vise):
        """The stock's bottom in the vise, from its jaw tops."""
        return PathWorkholding.seating(self.job, vise)["grip"] * -1

    def test02_seated_holds(self):
        """A seated vise slides along its jaws and up, no lower than its floor or higher than
        its jaw tops, not into the jaws or turned; not seated, it moves freely."""
        vise = PathWorkholding.addVise(self.job, self.part)
        PathWorkholding.seat(self.job, vise, grip=5, moveVise=True)
        seated = FreeCAD.Placement(vise.Placement)
        moved = FreeCAD.Placement(seated)
        moved.Base = seated.Base + Vector(7, 9, 0)
        vise.Placement = moved
        self.assertRoughly(vise.Placement.Base.x, seated.Base.x + 7)
        self.assertRoughly(vise.Placement.Base.y, seated.Base.y)
        # the vise up 100: the stock down to the floor, the jaws 30 tall, and no further
        moved = FreeCAD.Placement(vise.Placement)
        moved.Base = moved.Base + Vector(0, 0, 100)
        vise.Placement = moved
        self.assertRoughly(self.bottom(vise), -30)
        # down 100: the stock's bottom up to the jaw tops
        moved = FreeCAD.Placement(vise.Placement)
        moved.Base = moved.Base + Vector(0, 0, -100)
        vise.Placement = moved
        self.assertRoughly(self.bottom(vise), 0)
        turned = FreeCAD.Placement(vise.Placement.Base, FreeCAD.Rotation(Vector(0, 0, 1), 30))
        vise.Placement = turned
        self.assertRoughly(vise.Placement.Rotation.Angle, 0)
        vise.Seated = False
        vise.Placement = turned
        self.assertRoughly(vise.Placement.Rotation.Angle, math.radians(30))

    def test03_parallels_stand_the_stock(self):
        """Its parallels changed, a seated vise stands the stock on them."""
        vise = PathWorkholding.addVise(self.job, self.part)
        PathWorkholding.seat(self.job, vise, parallels=10, moveVise=True)
        self.assertRoughly(self.bottom(vise), -30 + 10)
        vise.Parallels = 20
        self.assertRoughly(self.bottom(vise), -30 + 20)

    def test04_turned(self):
        """Seated turned, the vise's top faces the Job's axis asked, its fixed jaw another."""
        vise = PathWorkholding.addVise(self.job, self.part)
        turn = PathWorkholding.orientation("+X", "-Z")
        PathWorkholding.seat(self.job, vise, grip=4, moveVise=True, rotation=turn)
        self.assertEqual(PathWorkholding.orientationOf(vise.Placement.Rotation), ("+X", "-Z"))
        self.assertRoughly(self.bottom(vise), -4)
        with self.assertRaises(ValueError):
            PathWorkholding.orientation("+Z", "-Z")

    def test01_another_beside_it(self):
        """Another of a vise stands beside it, opening on its own."""
        first = PathWorkholding.addVise(self.job, self.part)
        second = PathWorkholding.addAnother(first)
        self.assertEqual(PathWorkholding.vises(self.job), [first, second])
        self.assertGreater(second.Placement.Base.x, first.Placement.Base.x)
        PathWorkholding.viseSetup(second)["opening"].Opening = 70
        self.doc.recompute()
        self.assertRoughly(self.jaw(second).Placement.Base.y, -70)
        self.assertRoughly(self.jaw(first).Placement.Base.y, -20)

    def plates(self, vise):
        return [o for o in vise.Group if getattr(o, "LinkedObject", None) in self.platesOf()]

    def platesOf(self):
        return [self.source.getObject(n) for n in self.settings.JawPlates]

    def softVise(self, thickness=15, height=30, steps=("5,6", "10,3")):
        """A vise on soft jaws 15 thick, from the jaw's body, and 30 tall, from the plates'
        bottom: their face at Y -5, their top at Z 5, stepped 5 down and 6 in, then 10 down and
        3 in."""
        vise = PathWorkholding.addVise(self.job, self.part)
        PathWorkholding.setJaws(vise, "Soft", thickness, height, list(steps))
        return vise

    def test05_jaws_can_change(self):
        """A vise whose file names its jaw plates can have them changed; on its hard jaws, they
        are where the vise is laid out."""
        vise = PathWorkholding.addVise(self.job, self.part)
        self.assertTrue(PathWorkholding.canChangeJaws(vise))
        self.assertEqual(list(vise.JawPlates), ["FixedPlate", "MovingPlate"])
        self.assertFalse(PathWorkholding.canChangeJaws(self.part))
        frame = PathWorkholding.jawFrame(vise)
        self.assertEqual(frame["kind"], "Hard")
        self.assertRoughly(frame["face"], 0)
        self.assertRoughly(frame["top"], 0)
        self.assertRoughly(frame["floor"], -30)
        self.assertEqual(frame["steps"], [])
        self.assertRoughly(frame["gapLoss"], 0)
        self.assertRoughly(frame["width"], 100)
        with self.assertRaises(ValueError):
            PathWorkholding.setJaws(vise, "Soft", 15, 30, ["31,3"])
        # a vise whose file names no plates cannot
        self.settings.JawPlates = []
        other = PathWorkholding.addVise(self.job, self.part)
        self.assertFalse(PathWorkholding.canChangeJaws(other))
        with self.assertRaises(ValueError):
            PathWorkholding.setJaws(other, "Soft")

    def test06_soft_jaws(self):
        """Soft jaws stand in for the hard plates, hidden: the fixed one where its plate was, the
        moving one mirrored and moving with the Opening, both stepped."""
        vise = self.softVise()
        jaws = PathWorkholding.softJaws(vise)
        self.assertEqual(sorted(jaws), ["Fixed", "Moving"])
        self.assertEqual(vise.Jaws, "Soft")
        self.assertEqual(list(vise.Steps), ["5,6", "10,3"])
        for plate in self.plates(vise):
            self.assertFalse(plate.Visibility)
        bb = jaws["Fixed"].Shape.BoundBox
        self.assertRoughly(bb.XMin, -50)
        self.assertRoughly(bb.XMax, 50)
        self.assertRoughly(bb.YMin, -5)
        self.assertRoughly(bb.YMax, 10)
        self.assertRoughly(bb.ZMin, -25)
        self.assertRoughly(bb.ZMax, 5)
        # its steps cut out: 15 by 30, less 6 by 5 and 3 by 5 under it, across 100
        self.assertRoughly(jaws["Fixed"].Shape.Volume, (15 * 30 - 6 * 5 - 3 * 5) * 100)
        PathWorkholding.viseSetup(vise)["opening"].Opening = 40
        self.doc.recompute()
        bb = jaws["Moving"].Shape.BoundBox
        self.assertRoughly(bb.YMin, -10 - 40)
        self.assertRoughly(bb.YMax, 5 - 40)
        self.assertRoughly(bb.ZMax, 5)
        frame = PathWorkholding.jawFrame(vise)
        self.assertEqual(frame["kind"], "Soft")
        self.assertRoughly(frame["face"], -5)
        self.assertRoughly(frame["top"], 5)
        self.assertRoughly(frame["floor"], -30)
        self.assertEqual(len(frame["steps"]), 2)
        self.assertRoughly(frame["steps"][0][0], 0)
        self.assertRoughly(frame["steps"][0][1], 1)
        self.assertRoughly(frame["steps"][1][0], -5)
        self.assertRoughly(frame["steps"][1][1], -2)
        self.assertRoughly(frame["gapLoss"], 10)
        self.assertRoughly(frame["width"], 100)

    def test07_seated_on_a_step(self):
        """On a step the stock stands on its floor against its wall, the moving jaw closed to
        its own step's wall; held, it goes no lower than the step."""
        vise = self.softVise()
        length = self.job.Stock.Shape.BoundBox.YLength
        done = PathWorkholding.seat(self.job, vise, step=2)
        bb = self.job.Stock.Shape.BoundBox
        self.assertRoughly(bb.ZMin, -5)
        self.assertRoughly(bb.YMax, -2)
        # open by the stock's length, and the soft jaws' 5 proud of the plates each, less the
        # step's 3 in each
        self.assertRoughly(vise.Opening.Value, length + 10 - 6)
        self.assertRoughly(done["opening"], length + 4)
        self.doc.recompute()
        # the moving jaw's step, 3 in from its face, against the stock's far side
        moving = PathWorkholding.softJaws(vise)["Moving"].Shape.BoundBox
        self.assertRoughly(moving.YMax - 3, bb.YMin)
        now = PathWorkholding.seating(self.job, vise)
        self.assertEqual(now["step"], 2)
        self.assertRoughly(now["grip"], 10)
        self.assertEqual(now["jaws"]["kind"], "Soft")
        self.assertEqual(vise.SeatStep, 2)
        needed, _, _ = PathWorkholding.opening(self.job, vise)
        self.assertRoughly(needed, length + 4)
        # the vise up 100: the stock down no further than the step, 10 below the jaws' top
        moved = FreeCAD.Placement(vise.Placement)
        moved.Base = moved.Base + Vector(0, 0, 100)
        vise.Placement = moved
        self.assertRoughly(self.bottom(vise), -10)
        with self.assertRaises(ValueError):
            PathWorkholding.seat(self.job, vise, step=3)
        # gripped 4 from the soft jaws' top: its bottom above both steps' floors, held by the
        # jaws where they are cut back most, the first step's wall, 6 in, on each jaw
        PathWorkholding.seat(self.job, vise, grip=4)
        bb = self.job.Stock.Shape.BoundBox
        self.assertRoughly(bb.YMax, 1)
        self.assertRoughly(bb.ZMin, 1)
        self.assertRoughly(PathWorkholding.seating(self.job, vise)["grip"], 4)
        self.assertRoughly(vise.Opening.Value, length + 10 - 12)
        self.assertEqual(PathWorkholding.seating(self.job, vise)["step"], 0)
        # gripped 12, its bottom below both floors: against the soft jaws' own face
        PathWorkholding.seat(self.job, vise, grip=12)
        bb = self.job.Stock.Shape.BoundBox
        self.assertRoughly(bb.YMax, -5)
        self.assertRoughly(bb.ZMin, -7)
        self.assertRoughly(vise.Opening.Value, length + 10)

    def test08_hard_again(self):
        """Back on its hard jaws, the soft ones are gone and the plates shown, what the soft
        ones were kept for next time."""
        vise = self.softVise()
        names = [o.Name for o in PathWorkholding.softJaws(vise).values()]
        self.assertEqual(PathWorkholding.setJaws(vise, "Hard"), [])
        self.assertEqual(PathWorkholding.softJaws(vise), {})
        for name in names:
            self.assertIsNone(self.doc.getObject(name))
            self.assertFalse([e for e in vise.Drives if e.startswith(name + "\t")])
        for plate in self.plates(vise):
            self.assertTrue(plate.Visibility)
        self.assertEqual(PathWorkholding.jawFrame(vise)["kind"], "Hard")
        self.assertRoughly(vise.SoftThickness.Value, 15)
        # the Opening still drives the moving jaw
        vise.Opening = 33
        self.doc.recompute()
        self.assertRoughly(self.jaw(vise).Placement.Base.y, -33)

    def test09_hidden_plates_are_not_hit(self):
        """The hard plates the soft jaws stand in for are left out of what the tools may hit; the
        soft jaws are what may be cut into, apart from the rest."""

        def hit(at, cuttable=False):
            shape = PathJob.workholdingShape(self.job, cuttable=cuttable)
            if shape is None:
                return 0
            probe = Part.makeBox(1, 1, 1, at)
            return sum(shape.common(probe).Volume for shape in shape.Solids)

        vise = PathWorkholding.addVise(self.job, self.part)
        self.doc.recompute()
        # in the fixed plate, in front of a thin, short soft jaw
        plate = Vector(0, 1, -3)
        softJaw = Vector(0, 6, -10)
        self.assertGreater(hit(plate), 0.5)
        self.assertIsNone(PathJob.workholdingShape(self.job, cuttable=True))
        PathWorkholding.setJaws(vise, "Soft", 6, 20)
        self.assertRoughly(hit(plate), 0)
        self.assertRoughly(hit(softJaw), 0)
        self.assertGreater(hit(softJaw, cuttable=True), 0.5)
        self.assertRoughly(hit(plate, cuttable=True), 0)
        PathWorkholding.setJaws(vise, "Hard")
        self.assertGreater(hit(plate), 0.5)
        self.assertIsNone(PathJob.workholdingShape(self.job, cuttable=True))

    def test10_jaws_edited_on_the_vise(self):
        """The jaw settings changed on the vise itself, as in the property editor, remake them."""
        vise = self.softVise()
        vise.SoftThickness = 20
        vise.Steps = []
        self.doc.recompute()
        fixed = PathWorkholding.softJaws(vise)["Fixed"]
        self.assertRoughly(fixed.Shape.BoundBox.YMin, -10)
        self.assertRoughly(fixed.Shape.Volume, 20 * 30 * 100)
        vise.Jaws = "Hard"
        self.doc.recompute()
        self.assertEqual(PathWorkholding.softJaws(vise), {})
        vise.Jaws = "Soft"
        self.doc.recompute()
        self.assertEqual(sorted(PathWorkholding.softJaws(vise)), ["Fixed", "Moving"])

    def test11_another_keeps_its_jaws(self):
        """Another of a vise on soft jaws is on its own soft jaws."""
        first = self.softVise()
        second = PathWorkholding.addAnother(first)
        jaws = PathWorkholding.softJaws(second)
        self.assertEqual(sorted(jaws), ["Fixed", "Moving"])
        self.assertFalse(set(jaws.values()) & set(PathWorkholding.softJaws(first).values()))
        self.assertEqual(list(second.Steps), ["5,6", "10,3"])
        for plate in self.plates(second):
            self.assertFalse(plate.Visibility)
        self.assertEqual(len(second.Group), len(first.Group))

    def test12_hard_jaws_with_their_own_step(self):
        """Hard jaws with a step of their own, as the vise's file says in JawSteps: the stock
        stands on its floor against its wall, the moving jaw closed to its own step."""
        self.settings.addProperty("App::PropertyStringList", "JawSteps", "Vise", "")
        self.settings.JawSteps = ["6,4"]
        vise = PathWorkholding.addVise(self.job, self.part)
        self.assertEqual(list(vise.JawSteps), ["6,4"])
        frame = PathWorkholding.jawFrame(vise)
        self.assertEqual(frame["kind"], "Hard")
        self.assertEqual(frame["steps"], [(-6.0, 4.0)])
        length = self.job.Stock.Shape.BoundBox.YLength
        PathWorkholding.seat(self.job, vise, step=1)
        bb = self.job.Stock.Shape.BoundBox
        self.assertRoughly(bb.ZMin, -6)
        self.assertRoughly(bb.YMax, 4)
        # open by the stock's length less the step's 4 in each
        self.assertRoughly(vise.Opening.Value, length - 8)
        self.assertEqual(PathWorkholding.seating(self.job, vise)["step"], 1)
        # on parallels putting its bottom above the step's floor: held by the step's wall, the
        # jaws closed to it on both
        PathWorkholding.seat(self.job, vise, parallels=25)
        bb = self.job.Stock.Shape.BoundBox
        self.assertRoughly(bb.ZMin, -5)
        self.assertRoughly(bb.YMax, 4)
        self.assertRoughly(vise.Opening.Value, length - 8)
        needed, _, _ = PathWorkholding.opening(self.job, vise)
        self.assertRoughly(needed, length - 8)
        now = PathWorkholding.seating(self.job, vise)
        self.assertEqual(now["step"], 0)
        self.assertRoughly(now["grip"], 5)

    def test13_newer_schema_refused(self):
        """A vise laid out for a newer FreeCAD is not added."""
        self.settings.addProperty("App::PropertyInteger", "ViseSchema", "Vise", "")
        self.settings.ViseSchema = PathWorkholding.ViseSchema + 1
        with self.assertRaises(ValueError):
            PathWorkholding.addVise(self.job, self.part)
        self.settings.ViseSchema = PathWorkholding.ViseSchema
        vise = PathWorkholding.addVise(self.job, self.part)
        self.assertEqual(PathWorkholding.schemaOf(vise), PathWorkholding.ViseSchema)

    def test14_brought_up_to_date_with_its_file(self):
        """What the vise's file keeps fixed, and how its settings move its parts, follow the file;
        the Opening, set in the Job, stays."""
        for name in ("JawHeight", "MaxOpening"):
            self.settings.setEditorMode(name, ["ReadOnly"])
        vise = PathWorkholding.addVise(self.job, self.part)
        vise.Opening = 40
        self.assertEqual(PathWorkholding.refreshSettings(vise), [])
        # the file changed: opens less, a step, the moving jaw 1 further out
        self.settings.MaxOpening = 125
        self.settings.addProperty("App::PropertyStringList", "JawSteps", "Vise", "")
        self.settings.JawSteps = ["6,4"]
        self.settings.setEditorMode("JawSteps", ["ReadOnly"])
        self.settings.Opening = 70
        jaw = self.source.getObject("MovingJaw")
        jaw.setExpression(".Placement.Base.y", "-%s.Opening - 1 mm" % self.settings.Name)
        changed = PathWorkholding.refreshSettings(vise)
        self.assertEqual(sorted(changed), ["Drives", "JawSteps", "MaxOpening"])
        self.assertRoughly(vise.MaxOpening.Value, 125)
        self.assertEqual(list(vise.JawSteps), ["6,4"])
        self.assertRoughly(vise.Opening.Value, 40)
        self.doc.recompute()
        self.assertRoughly(self.jaw(vise).Placement.Base.y, -41)
        self.assertEqual(PathWorkholding.refreshSettings(vise), [])

    def test15_file_checked(self):
        """A vise's file is checked before it is used: one laid out as a vise passes; Python in
        it, or an Opening moving its jaw the wrong way, does not."""
        path = os.path.join(self.dir, "vise.FCStd")
        errors, _ = PathWorkholdingCheck.check(path)
        self.assertEqual(errors, [])
        self.assertEqual(PathWorkholdingCheck.pythonObjects(path), [])
        # the Opening moving the jaw toward the fixed one
        jaw = self.source.getObject("MovingJaw")
        jaw.setExpression(".Placement.Base.y", "%s.Opening" % self.settings.Name)
        errors, _ = PathWorkholdingCheck.checkDocument(self.source)
        self.assertEqual(len(errors), 1)
        # Python in the file: not opened
        self.source.addObject("App::FeaturePython", "Script")
        self.source.save()
        self.assertTrue(PathWorkholdingCheck.pythonObjects(path))
        errors, _ = PathWorkholdingCheck.check(path)
        self.assertEqual(len(errors), 1)
        self.assertIn("Python", errors[0])

    def test16_on_a_pair_of_parallels(self):
        """The stock on a pair of parallels from a set: one against each jaw, on the vise's floor,
        the moving one following the jaw; hard ones crashed into, soft ones cut; on the floor,
        gone."""
        vise = PathWorkholding.addVise(self.job, self.part)
        inch = PathParallels.INCH
        entry = [s for s in PathParallels.Sets if s["unit"] == "Imperial"][0]
        kit = PathParallels.parallels(entry, inch / 8, 0.5 * inch, 5 * inch)
        self.assertEqual(kit.name, 'Imperial, Standard, 1/8", 1/2", 5" long')
        PathWorkholding.seat(self.job, vise, parallels=kit)
        self.doc.recompute()
        made = PathWorkholding.parallelsOf(vise)
        self.assertEqual(sorted(made), ["Fixed", "Moving"])
        fixed = made["Fixed"].Shape.BoundBox
        self.assertRoughly(fixed.ZMin, -30)
        self.assertRoughly(fixed.ZMax, -30 + 0.5 * inch)
        self.assertRoughly(fixed.YMax, 0)
        self.assertRoughly(fixed.YMin, -inch / 8)
        self.assertRoughly(fixed.XLength, 5 * inch)
        self.assertRoughly(self.job.Stock.Shape.BoundBox.ZMin, -30 + 0.5 * inch)
        self.assertEqual(vise.ParallelSet, kit.name)
        vise.Opening = 70
        self.doc.recompute()
        moving = made["Moving"].Shape.BoundBox
        self.assertRoughly(moving.YMin, -70)
        self.assertRoughly(moving.YMax, -70 + inch / 8)
        # hard: among what is crashed into; soft: what is cut
        self.assertIsNone(PathJob.workholdingShape(self.job, cuttable=True))
        PathWorkholding.seat(self.job, vise, parallels=kit._replace(cuttable=True))
        self.assertTrue(all(PathWorkholding.isCuttable(o) for o in made.values()))
        self.assertEqual(len(PathJob.workholdingShape(self.job, cuttable=True).Solids), 2)
        # on the floor: no parallels, nor anything driving them
        PathWorkholding.seat(self.job, vise, parallels=0)
        self.assertEqual(PathWorkholding.parallelsOf(vise), {})
        self.assertFalse(vise.OnParallels)
        self.assertEqual(len(vise.Drives), 2)
        self.assertRoughly(self.job.Stock.Shape.BoundBox.ZMin, -30)

    def test17_vise_taking_no_parallels(self):
        """A vise whose parallels are built in takes none: the stock stands on its floor."""
        self.settings.addProperty("App::PropertyBool", "TakesParallels", "Vise", "")
        self.settings.TakesParallels = False
        vise = PathWorkholding.addVise(self.job, self.part)
        self.assertFalse(PathWorkholding.takesParallels(vise))
        with self.assertRaises(ValueError):
            PathWorkholding.seat(self.job, vise, parallels=10)
        PathWorkholding.seat(self.job, vise, parallels=0)
        self.assertRoughly(self.job.Stock.Shape.BoundBox.ZMin, -30)

    def test20_self_centering(self):
        """A self-centering vise: both jaws close about its body, which stays where it is bolted
        down as the vise opens and closes; the stock is seated, and pushed as the jaws close on
        it, to the middle of the body."""
        self.settings.addProperty("App::PropertyBool", "SelfCentering", "Vise", "")
        self.settings.SelfCentering = True
        body = self.source.getObject("Body")
        body.setExpression(".Placement.Base.y", "-%s.Opening / 2" % self.settings.Name)
        self.source.recompute()
        vise = PathWorkholding.addVise(self.job, self.part)
        self.assertTrue(PathWorkholding.selfCentering(vise))
        link = [o for o in vise.Group if getattr(o, "LinkedObject", None) == body][0]

        def middle():
            # the middle of the jaws, where the body is drawn about, in the Job
            self.doc.recompute()
            return vise.Placement.multVec(link.Placement.Base).y

        def stockMiddle():
            bb = self.job.Stock.Shape.BoundBox
            return (bb.YMin + bb.YMax) / 2

        start = middle()
        # opened, the fixed jaw goes out half as far, the body stays
        vise.Opening = 60
        self.assertRoughly(vise.Placement.Base.y, 20)
        self.assertRoughly(middle(), start)
        # seated, the stock in the middle, the body still where it was
        PathWorkholding.seat(self.job, vise, parallels=0)
        self.assertRoughly(middle(), start)
        self.assertRoughly(stockMiddle(), start)
        # off the middle and opened, the jaws closing push it back
        PathWorkholding.moveModel(self.job, Vector(0, 3, 0))
        vise.Opening = 60
        vise.CloseJaw = False
        vise.CloseJaw = True
        self.assertRoughly(middle(), start)
        self.assertRoughly(stockMiddle(), start)
        # the vise moved to the stock: its body under the stock's middle
        PathWorkholding.moveModel(self.job, Vector(0, 7, 0))
        PathWorkholding.seat(self.job, vise, parallels=0, moveVise=True)
        self.assertRoughly(middle(), stockMiddle())

    def test21_one_station_not_shared(self):
        """A vise of one station holds one Job's stock: it is not shared, and has no Station."""
        vise = PathWorkholding.addVise(self.job, self.part)
        box = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        other = PathJob.Create("Job", [box], None)
        self.doc.recompute()
        self.assertEqual(len(PathWorkholding.stations(vise)), 1)
        self.assertFalse(hasattr(vise, "Station"))
        self.assertTrue(PathWorkholding.stationPlacement(vise).isSame(vise.Placement, 1e-9))
        self.assertFalse(PathWorkholding.canShare(vise, other))
        with self.assertRaises(ValueError):
            PathWorkholding.shareVise(vise, other)
        self.assertIsNone(PathWorkholding.release(vise))

    def test18_parallel_sizes_named(self):
        """Sizes named as a set has them: inches as a machinist writes them, else mm."""
        inch = PathParallels.INCH
        self.assertEqual(PathParallels.label(1.1875 * inch, "Imperial"), '1-3/16"')
        self.assertEqual(PathParallels.label(inch / 32, "Imperial"), '1/32"')
        self.assertEqual(PathParallels.label(2 * inch, "Imperial"), '2"')
        self.assertEqual(PathParallels.label(14.0, "Metric"), "14 mm")
        units = {s["unit"] for s in PathParallels.catalogue()}
        self.assertEqual(units, {"Imperial", "Metric"})

    def test19_grip_jaws(self):
        """grip jaws in place of the plates: steel jaws, hardened grips standing proud of their
        tops; the stock on the jaws' tops, the grips' teeth bitten into it. The jaws
        are cut, the grips crashed into; they follow the moving jaw, and go with hard jaws."""
        import Path.Main.WorkholdingJaws as PathJaws

        vise = PathWorkholding.addVise(self.job, self.part)
        defaults = PathJaws.GripJaw
        jaws = PathWorkholding.setJaws(
            vise, "Grip", gripJaws={"grip": 1.5, "setback": 3, "bite": 0.5}
        )
        self.assertEqual(len(jaws), 2)
        self.assertRoughly(vise.SoftThickness.Value, defaults["thickness"])
        grips = PathWorkholding.gripsOf(vise)
        self.assertEqual(sorted(grips), [("Fixed", 0), ("Fixed", 1), ("Moving", 0), ("Moving", 1)])
        # the plates 10 thick and 25 tall: the jaw's face at 10 - its thickness, its top at
        # -25 + its height, the grips 1.5 above it
        face = 10 - defaults["thickness"]
        top = -25 + defaults["height"]
        frame = PathWorkholding.jawFrame(vise)
        self.assertEqual(frame["kind"], "Grip")
        self.assertRoughly(frame["top"], top + 1.5)
        self.assertEqual(len(frame["steps"]), 1)
        self.assertRoughly(frame["steps"][0][0], top)
        self.assertRoughly(frame["steps"][0][1], face + 3 + 0.5)
        self.doc.recompute()
        grip = grips[("Fixed", 0)].Shape.BoundBox
        self.assertRoughly(grip.ZMax, top + 1.5)
        self.assertRoughly(grip.YMin, face + 3)
        # the stock on the jaws' tops, gripped 1.5, the teeth bitten 0.5 into it
        length = self.job.Stock.Shape.BoundBox.YLength
        PathWorkholding.seat(self.job, vise, step=1)
        bb = self.job.Stock.Shape.BoundBox
        self.assertRoughly(bb.ZMin, top)
        self.assertRoughly(bb.YMax, face + 3.5)
        self.assertRoughly(PathWorkholding.seating(self.job, vise)["grip"], 1.5)
        # the moving jaw's teeth as far in on the stock's far side
        self.doc.recompute()
        moving = grips[("Moving", 0)].Shape.BoundBox
        self.assertRoughly(moving.YMax - 0.5, bb.YMin)
        self.assertRoughly(vise.Opening.Value, length + 2 * (defaults["thickness"] - 10) - 2 * 3.5)
        # the jaws cut, the grips crashed into
        self.assertTrue(all(PathWorkholding.isCuttable(j) for j in jaws))
        self.assertFalse(any(PathWorkholding.isCuttable(g) for g in grips.values()))
        # three grips a jaw; hard jaws again, none
        PathWorkholding.setJaws(vise, "Grip", gripJaws={"grips": 3})
        self.assertEqual(len(PathWorkholding.gripsOf(vise)), 6)
        PathWorkholding.setJaws(vise, "Hard")
        self.assertEqual(PathWorkholding.gripsOf(vise), {})
        self.assertEqual(PathWorkholding.softJaws(vise), {})


class TestPathWorkholdingStations(PathTestUtils.PathTestBase):
    """A vise of two stations: its stock seated in either, the vise shared by two Jobs, each in
    a station of its own."""

    # the centre jaw's thickness: station 2's fixed face on its far side, turned to face away
    centre = 20.0

    def setUp(self):
        # a vise's own file: station 1 the vise's own frame, its moving jaw driven by Opening;
        # station 2 turned about Z on the centre jaw's far side, its moving jaw driven by
        # Opening2, both drawn closed
        self.source = FreeCAD.newDocument("TestStationsSource")
        part = self.source.addObject("App::Part", "Vise")
        part.Label = "Double vise"
        body = self.source.addObject("Part::Box", "Body")
        body.Length, body.Width, body.Height = 100, 300, 10
        body.Placement.Base = Vector(-50, -150, -40)
        centre = self.source.addObject("Part::Feature", "CentreJaw")
        centre.Shape = Part.makeBox(100, self.centre, 25, Vector(-50, 0, -25))
        moving = self.source.addObject("Part::Feature", "MovingJaw")
        moving.Shape = Part.makeBox(100, 10, 25, Vector(-50, -10, -25))
        moving2 = self.source.addObject("Part::Feature", "MovingJaw2")
        moving2.Shape = Part.makeBox(100, 10, 25, Vector(-50, self.centre, -25))
        settings = self.source.addObject("App::VarSet", "Settings")
        for name in ("Opening", "Opening2", "JawHeight", "MaxOpening"):
            settings.addProperty("App::PropertyLength", name, "Vise", "")
        settings.addProperty("App::PropertyInteger", "Stations", "Vise", "")
        settings.addProperty("App::PropertyPlacementList", "StationFrames", "Vise", "")
        settings.addProperty("App::PropertyInteger", "ViseSchema", "Vise", "")
        settings.Opening, settings.Opening2 = 20, 20
        settings.JawHeight, settings.MaxOpening = 30, 150
        settings.Stations = 2
        self.frame2 = FreeCAD.Placement(
            Vector(0, self.centre, 0), FreeCAD.Rotation(Vector(0, 0, 1), 180)
        )
        settings.StationFrames = [FreeCAD.Placement(), self.frame2]
        settings.ViseSchema = 2
        for name in ("JawHeight", "MaxOpening", "Stations", "StationFrames", "ViseSchema"):
            settings.setEditorMode(name, ["ReadOnly"])
        part.addObjects([body, centre, moving, moving2, settings])
        moving.setExpression(".Placement.Base.y", "-%s.Opening" % settings.Name)
        moving2.setExpression(".Placement.Base.y", "%s.Opening2" % settings.Name)
        self.source.recompute()
        self.part, self.settings = part, settings
        self.dir = tempfile.mkdtemp()
        self.source.saveAs(os.path.join(self.dir, "double.FCStd"))

        self.doc = FreeCAD.newDocument("TestStations")
        self.jobs = []
        for i in range(3):
            box = self.doc.addObject("Part::Box", "Box")
            box.Length, box.Width, box.Height = 40 + i, 30 + i, 20
            box.Placement.Base = Vector(200 * i, 0, 0)
            self.doc.recompute()
            self.jobs.append(PathJob.Create("Job", [box], None))
            self.doc.recompute()
        self.job = self.jobs[0]
        self.doc.saveAs(os.path.join(self.dir, "jobs.FCStd"))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        FreeCAD.closeDocument(self.source.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def stock(self, job=None):
        return (job or self.job).Stock.Shape.BoundBox

    def link(self, vise, name):
        return [o for o in vise.Group if getattr(o, "LinkedObject", None).Name == name][0]

    def test00_stations(self):
        """A vise of two stations put in a Job: its frames, its stock in the first, hard jaws
        only."""
        vise = PathWorkholding.addVise(self.job, self.part)
        frames = PathWorkholding.stations(vise)
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0].isIdentity())
        self.assertTrue(frames[1].isSame(self.frame2, 1e-9))
        self.assertEqual(PathWorkholding.station(vise), 1)
        self.assertEqual(vise.getGroupOfProperty("Station"), "Seat")
        self.assertEqual(PathWorkholding.openingName(vise, 2), "Opening2")
        self.assertFalse(PathWorkholding.canChangeJaws(vise))
        self.assertEqual(PathWorkholding.schemaOf(vise), 2)
        # a vise of one station has its own frame, no Station
        self.assertEqual(len(PathWorkholding.stations(self.job.Stock)), 1)

    def test01_seated_in_station_two_part_moves(self):
        """In station 2 the stock goes against its fixed face, on the centre jaw's far side,
        and Opening2 closes on it; station 1 stays as it was."""
        vise = PathWorkholding.addVise(self.job, self.part)
        PathWorkholding.setStation(vise, 2)
        length = self.stock().YLength
        done = PathWorkholding.seat(self.job, vise, grip=5)
        bb = self.stock()
        self.assertRoughly(bb.YMin, self.centre)
        self.assertRoughly((bb.XMin + bb.XMax) / 2, 0)
        self.assertRoughly(bb.ZMin, -5)
        self.assertRoughly(vise.Opening2.Value, length)
        self.assertRoughly(done["opening"], length)
        self.assertRoughly(vise.Opening.Value, 20)
        self.assertTrue(vise.Placement.isIdentity())
        # its moving jaw closed on the stock's far side
        self.doc.recompute()
        self.assertRoughly(self.link(vise, "MovingJaw2").Shape.BoundBox.YMin, bb.YMax)
        now = PathWorkholding.seating(self.job, vise)
        self.assertRoughly(now["grip"], 5)
        self.assertRoughly(now["offset"], 0)
        # turned half round: its fixed jaw toward the Job's -Y
        self.assertEqual(now["orientation"], ("+Z", "-Y"))

    def test02_seated_in_station_two_vise_moves(self):
        """With the vise moving, station 2 comes to the stock: its fixed face against it."""
        vise = PathWorkholding.addVise(self.job, self.part)
        PathWorkholding.setStation(vise, 2)
        before = self.stock()
        PathWorkholding.seat(self.job, vise, grip=5, moveVise=True)
        after = self.stock()
        self.assertRoughly(after.YMin, before.YMin)
        self.assertRoughly(after.ZMin, before.ZMin)
        station = PathWorkholding.stationPlacement(vise)
        self.assertRoughly(station.Base.y, before.YMin)
        self.assertRoughly(station.Base.x, (before.XMin + before.XMax) / 2)
        self.assertRoughly(station.Base.z, before.ZMin + 5)
        self.assertRoughly(vise.Placement.Base.y, before.YMin - self.centre)
        self.assertRoughly(vise.Opening2.Value, before.YLength)
        # turned: the station as asked, the vise with it
        turn = PathWorkholding.orientation("+Z", "+X")
        PathWorkholding.seat(self.job, vise, grip=5, moveVise=True, rotation=turn)
        self.assertEqual(
            PathWorkholding.orientationOf(PathWorkholding.stationPlacement(vise).Rotation),
            ("+Z", "+X"),
        )
        self.assertEqual(PathWorkholding.orientationOf(vise.Placement.Rotation), ("+Z", "-X"))
        self.assertRoughly(self.stock().XMax, PathWorkholding.stationPlacement(vise).Base.x)

    def test03_on_parallels_in_station_two(self):
        """Parallels in station 2: against its fixed face, the moving one following Opening2."""
        vise = PathWorkholding.addVise(self.job, self.part)
        PathWorkholding.setStation(vise, 2)
        PathWorkholding.seat(self.job, vise, parallels=10)
        self.doc.recompute()
        made = PathWorkholding.parallelsOf(vise)
        thick = vise.ParallelThickness.Value
        fixed = made["Fixed"].Shape.BoundBox
        self.assertRoughly(fixed.YMin, self.centre)
        self.assertRoughly(fixed.YMax, self.centre + thick)
        self.assertRoughly(fixed.ZMin, -30)
        vise.Opening2 = 50
        self.doc.recompute()
        moving = made["Moving"].Shape.BoundBox
        self.assertRoughly(moving.YMax, self.centre + 50)
        self.assertRoughly(moving.YMin, self.centre + 50 - thick)
        self.assertRoughly(self.stock().ZMin, -20)

    def test04_shared(self):
        """Two Jobs share the vise, each with a vise of its own: the second placed where the
        first is, in the station free, each one's openings the other's too."""
        owner = PathWorkholding.addVise(self.job, self.part)
        other = self.jobs[1]
        follower = PathWorkholding.shareVise(owner, other)
        self.assertEqual(PathWorkholding.vises(other), [follower])
        self.assertEqual(follower.Follows, owner)
        self.assertEqual(PathWorkholding.station(follower), 2)
        self.assertEqual(PathWorkholding.freeStations(owner), [])
        self.assertEqual(PathWorkholding.followers(owner), [follower])
        self.assertEqual(PathWorkholding.shareGroup(follower), [owner, follower])
        self.assertEqual(PathWorkholding.sharedWith(owner), [other])
        self.assertEqual(PathWorkholding.memberOf(follower), (other, follower))
        self.assertEqual(PathWorkholding.memberOf(self.link(owner, "MovingJaw")), (self.job, owner))
        # the owner moved, the follower with it
        owner.Placement = FreeCAD.Placement(Vector(5, 6, 7), FreeCAD.Rotation(Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.assertTrue(follower.Placement.isSame(owner.Placement, 1e-9))
        # each shows the other's jaws where they are
        follower.Opening2 = 33
        self.assertRoughly(owner.Opening2.Value, 33)
        owner.Opening = 44
        self.assertRoughly(follower.Opening.Value, 44)
        # the follower's stock into its station, the part moving
        PathWorkholding.seat(other, follower, grip=5)
        bb = self.stock(other)
        station = PathWorkholding.stationPlacement(follower)
        self.assertRoughly(bb.ZMin, station.Base.z - 5)
        self.assertRoughly(bb.XMax, station.Base.x)
        self.assertTrue(follower.Placement.isSame(owner.Placement, 1e-9))

    def test11_simulated_with_the_other_part(self):
        """Each Job sharing the vise simulated with the other's part in its station, as big as it
        can be: its stock, hit and never cut."""
        owner = PathWorkholding.addVise(self.job, self.part)
        other = self.jobs[1]
        self.assertNotIn(other.Stock, [p for p, _ in PathJob.workholdingParts(self.job)])
        follower = PathWorkholding.shareVise(owner, other)
        PathWorkholding.seat(other, follower, grip=5)
        parts = dict(PathJob.workholdingParts(self.job))
        self.assertIn(other.Stock, parts)
        self.assertTrue(parts[other.Stock].BoundBox.isInside(other.Stock.Shape.BoundBox.Center))
        self.assertIn(self.job.Stock, dict(PathJob.workholdingParts(other)))
        self.assertNotIn(other.Stock, dict(PathJob.workholdingParts(self.job, cuttable=True)))

    def test05_shares_refused(self):
        """No third Job in a vise of two stations, nor a Job twice; a follower is not moved."""
        owner = PathWorkholding.addVise(self.job, self.part)
        follower = PathWorkholding.shareVise(owner, self.jobs[1])
        self.assertFalse(PathWorkholding.canShare(owner, self.jobs[2]))
        with self.assertRaises(ValueError):
            PathWorkholding.shareVise(owner, self.jobs[2])
        with self.assertRaises(ValueError):
            PathWorkholding.shareVise(follower, self.job)
        with self.assertRaises(ValueError):
            PathWorkholding.setStation(follower, 1)
        with self.assertRaises(ValueError):
            PathWorkholding.seat(self.jobs[1], follower, grip=5, moveVise=True)

    def test06_shared_owner_stays(self):
        """A vise once shared stays where it is for its owner too, the other Job's part being in
        it: seated by moving the part, never the vise."""
        owner = PathWorkholding.addVise(self.job, self.part)
        # alone, the vise moves to the part
        PathWorkholding.seat(self.job, owner, grip=5, moveVise=True)
        self.assertFalse(PathWorkholding.isShared(owner))
        other = self.jobs[1]
        follower = PathWorkholding.shareVise(owner, other)
        self.assertTrue(PathWorkholding.isShared(owner))
        PathWorkholding.seat(other, follower, grip=5)
        placement = FreeCAD.Placement(owner.Placement)
        with self.assertRaises(ValueError):
            PathWorkholding.seat(self.job, owner, grip=5, moveVise=True)
        PathWorkholding.seat(self.job, owner, grip=6)
        self.assertTrue(owner.Placement.isSame(placement, 1e-9))
        # the follower released, the owner alone moves again
        PathWorkholding.release(follower)
        self.assertFalse(PathWorkholding.isShared(owner))
        PathWorkholding.seat(self.job, owner, grip=5, moveVise=True)

    def test12_turned_in_a_shared_vise(self):
        """A vise shared stays turned as it is: the part turned in it instead to the sides asked,
        its stock made about it again, the sides named the part's own from then on."""
        owner = PathWorkholding.addVise(self.job, self.part)
        other = self.jobs[1]
        follower = PathWorkholding.shareVise(owner, other)
        PathWorkholding.seat(other, follower, grip=5)
        placement = FreeCAD.Placement(owner.Placement)
        PathWorkholding.seat(
            self.job, owner, grip=5, rotation=PathWorkholding.orientation("+Z", "+X")
        )
        self.doc.recompute()
        self.assertTrue(owner.Placement.isSame(placement, 1e-9))
        self.assertFalse(PathWorkholding.partTurn(self.job).isSame(FreeCAD.Rotation(), 1e-7))
        now = PathWorkholding.seating(self.job, owner)
        self.assertEqual(now["orientation"], ("+Z", "+X"))
        self.assertRoughly(now["grip"], 5)
        # its stock about it, square to the Job's axes
        stock = self.job.Stock.Shape.BoundBox
        model = self.job.Model.Group[0].Shape.BoundBox
        self.assertTrue(stock.isInside(model))
        self.assertTrue(self.job.Stock.Placement.Rotation.isSame(FreeCAD.Rotation(), 1e-9))
        # the follower turned too, its vise staying
        PathWorkholding.seat(
            other, follower, grip=5, rotation=PathWorkholding.orientation("-Z", "+Y")
        )
        self.doc.recompute()
        self.assertTrue(owner.Placement.isSame(placement, 1e-9))
        self.assertEqual(PathWorkholding.seating(other, follower)["orientation"], ("-Z", "+Y"))
        # turned back as modelled
        PathWorkholding.seat(
            self.job, owner, grip=5, rotation=PathWorkholding.orientation("+Z", "+Y")
        )
        self.assertTrue(PathWorkholding.partTurn(self.job).isSame(FreeCAD.Rotation(), 1e-7))

    def test07_follower_released(self):
        """A follower released stays where it is, on its own; its station is free again."""
        owner = PathWorkholding.addVise(self.job, self.part)
        follower = PathWorkholding.shareVise(owner, self.jobs[1])
        owner.Placement = FreeCAD.Placement(Vector(5, 6, 7), FreeCAD.Rotation())
        self.doc.recompute()
        self.assertIsNone(PathWorkholding.release(follower))
        self.assertFalse(PathWorkholding.isFollower(follower))
        self.assertEqual(follower.ExpressionEngine, [])
        self.assertRoughly(follower.Placement.Base.x, 5)
        self.assertEqual(PathWorkholding.freeStations(owner), [2])
        owner.Placement = FreeCAD.Placement()
        self.doc.recompute()
        self.assertRoughly(follower.Placement.Base.x, 5)

    def test08_owner_released(self):
        """The owner released hands its place to the first following it, which stays where it
        is; the others follow that one."""
        # a third station, so two Jobs follow
        self.settings.addProperty("App::PropertyLength", "Opening3", "Vise", "")
        self.settings.Stations = 3
        frame3 = FreeCAD.Placement(Vector(0, -200, 0), FreeCAD.Rotation())
        self.settings.StationFrames = [FreeCAD.Placement(), self.frame2, frame3]
        owner = PathWorkholding.addVise(self.job, self.part)
        owner.Placement = FreeCAD.Placement(Vector(5, 6, 7), FreeCAD.Rotation())
        first = PathWorkholding.shareVise(owner, self.jobs[1])
        second = PathWorkholding.shareVise(first, self.jobs[2])
        self.assertEqual(second.Follows, owner)
        self.assertEqual(PathWorkholding.station(second), 3)
        self.doc.recompute()
        self.assertEqual(PathWorkholding.release(owner), first)
        self.assertFalse(PathWorkholding.isFollower(first))
        self.assertEqual(second.Follows, first)
        self.assertEqual(PathWorkholding.followers(first), [second])
        self.assertEqual(PathWorkholding.followers(owner), [])
        self.assertRoughly(first.Placement.Base.x, 5)
        first.Placement = FreeCAD.Placement(Vector(9, 6, 7), FreeCAD.Rotation())
        self.doc.recompute()
        self.assertRoughly(second.Placement.Base.x, 9)
        self.assertRoughly(owner.Placement.Base.x, 5)

    def test09_job_deleted_releases(self):
        """A Job deleted no longer shares its vise: the other Job's stays where it is."""
        owner = PathWorkholding.addVise(self.job, self.part)
        owner.Placement = FreeCAD.Placement(Vector(5, 6, 7), FreeCAD.Rotation())
        follower = PathWorkholding.shareVise(owner, self.jobs[1])
        self.doc.recompute()
        self.job.Proxy.onDelete(self.job)
        self.doc.removeObject(self.job.Name)
        self.doc.recompute()
        self.assertFalse(PathWorkholding.isFollower(follower))
        self.assertRoughly(follower.Placement.Base.x, 5)

    def test10_file_checked(self):
        """A vise file of two stations is laid out right; one of a newer schema is not used."""
        errors, _ = PathWorkholdingCheck.checkDocument(self.source)
        self.assertEqual(errors, [])
        path = os.path.join(self.dir, "double.FCStd")
        self.assertEqual(PathWorkholdingCheck.checkZip(path), [])
        # station 2's jaw moving the wrong way
        self.source.getObject("MovingJaw2").setExpression(
            ".Placement.Base.y", "-%s.Opening2" % self.settings.Name
        )
        errors, _ = PathWorkholdingCheck.checkDocument(self.source)
        self.assertEqual(len(errors), 1)
        self.settings.ViseSchema = 3
        self.source.save()
        self.assertEqual(len(PathWorkholdingCheck.checkZip(path)), 1)
        with self.assertRaises(ValueError):
            PathWorkholding.addVise(self.job, self.part)


class TestPathWorkholdingRecover(PathTestUtils.PathTestBase):
    """A Job whose vise's file is not where it was: found again by its name in the folders vises
    are kept in, got from a library, picked, or said to be lost, its settings kept."""

    # the vise's own file and the Job as TestPathWorkholdingAdd makes them
    jaw = TestPathWorkholdingAdd.jaw

    def setUp(self):
        TestPathWorkholdingAdd.setUp(self)
        self.vise = PathWorkholding.addVise(self.job, self.part)
        self.vise.Opening = 42
        self.doc.recompute()
        self.doc.save()
        self.jobPath = self.doc.FileName
        self.visePath = self.source.FileName
        FreeCAD.closeDocument(self.doc.Name)
        FreeCAD.closeDocument(self.source.Name)
        # the vise's file moved away
        self.moved = os.path.join(self.dir, "elsewhere")
        os.makedirs(self.moved)
        shutil.move(self.visePath, os.path.join(self.moved, "vise.FCStd"))
        self.doc = FreeCAD.openDocument(self.jobPath)
        self.source = None

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def reopened(self):
        return [o for o in self.doc.Objects if PathWorkholding.viseSetup(o) is not None][0]

    def assertLinked(self, vise):
        parts = [o for o in vise.Group if o.isDerivedFrom("App::Link")]
        self.assertTrue(parts and all(o.LinkedObject is not None for o in parts))
        # the moving jaw where its opening says
        self.assertRoughly(self.jaw(vise).Placement.Base.y, -42)

    def test00_lost(self):
        """Its parts unlinked, by the file and the object each was linked to."""
        lost = PathWorkholding.lostParts(self.doc)
        self.assertEqual(list(lost), ["vise.FCStd"])
        self.assertEqual(
            sorted(n for _, n in lost["vise.FCStd"]),
            ["Body", "FixedPlate", "MovingJaw", "MovingPlate"],
        )

    def test01_found_in_a_folder(self):
        """Found by its name in a folder vises are kept in: linked again, nothing asked."""
        asked = []
        found = PathWorkholding.recoverParts(
            self.doc, folders=[self.moved], library=[], askFile=lambda f: asked.append(f)
        )
        self.assertEqual(found, {"vise.FCStd": os.path.join(self.moved, "vise.FCStd")})
        self.assertEqual(asked, [])
        self.assertLinked(self.reopened())
        self.assertEqual(PathWorkholding.lostParts(self.doc), {})

    def test02_got_from_a_library(self):
        """Not in the folders and not found by the user, but a library has it: downloaded into the
        first, once asked."""
        import hashlib, json

        library = os.path.join(self.dir, "library")
        os.makedirs(os.path.join(library, "vises"))
        shutil.copy(os.path.join(self.moved, "vise.FCStd"), os.path.join(library, "vises"))
        data = open(os.path.join(library, "vises", "vise.FCStd"), "rb").read()
        index = os.path.join(library, "index.json")
        item = {
            "id": "vise",
            "kind": "vise",
            "file": "vises/vise.FCStd",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "label": "Test vise",
        }
        with open(index, "w") as f:
            json.dump({"format": 1, "items": [item]}, f)
        here = os.path.join(self.dir, "here")
        asked = []
        found = PathWorkholding.recoverParts(
            self.doc,
            folders=[here],
            library=[index],
            askLibrary=lambda f, i: asked.append(i["id"]) or True,
            askFile=lambda f: asked.append("file") or None,
        )
        self.assertEqual(asked, ["file", "vise"])
        self.assertEqual(found["vise.FCStd"], os.path.join(here, "vise.FCStd"))
        self.assertLinked(self.reopened())

    def test03_picked(self):
        """Not found anywhere: the file picked."""
        found = PathWorkholding.recoverParts(
            self.doc,
            folders=[os.path.join(self.dir, "nowhere")],
            library=[],
            askLibrary=lambda f, i: True,
            askFile=lambda f: os.path.join(self.moved, "vise.FCStd"),
        )
        self.assertEqual(found["vise.FCStd"], os.path.join(self.moved, "vise.FCStd"))
        self.assertLinked(self.reopened())

    def test05_found_in_its_own_library(self):
        """Its file came from a library not among the user's, kept under another name there:
        found in it by its id."""
        import hashlib, json

        library = os.path.join(self.dir, "private")
        os.makedirs(os.path.join(library, "vises"))
        shutil.copy(
            os.path.join(self.moved, "vise.FCStd"), os.path.join(library, "vises", "renamed.FCStd")
        )
        data = open(os.path.join(library, "vises", "renamed.FCStd"), "rb").read()
        index = os.path.join(library, "index.json")
        with open(index, "w") as f:
            json.dump(
                {
                    "format": 1,
                    "items": [
                        {
                            "id": "the-vise",
                            "kind": "vise",
                            "file": "vises/renamed.FCStd",
                            "size": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        }
                    ],
                },
                f,
            )
        vise = self.reopened()
        self.assertTrue(vise.SourceFile.endswith("vise.FCStd"))
        vise.SourceLibrary = index
        vise.SourceItem = "the-vise"
        here = os.path.join(self.dir, "here")
        found = PathWorkholding.recoverParts(
            self.doc, folders=[here], library=[], askLibrary=lambda f, i: True
        )
        self.assertEqual(found["vise.FCStd"], os.path.join(here, "renamed.FCStd"))
        self.assertLinked(vise)
        self.assertEqual(vise.SourceItem, "the-vise")

    def test06_changed_file_told(self):
        """Found again, but its file is not the one it was added with: linked, and told of, the
        sha256 it was added with kept until the change is taken; its stamp's library and id
        kept on it."""
        vise = self.reopened()
        added = vise.SourceSha256
        self.assertTrue(added)
        path = os.path.join(self.moved, "vise.FCStd")
        source = FreeCAD.openDocument(path)
        settings = [o for o in source.Objects if o.TypeId == "App::VarSet"][0]
        for name, value in (("Library", "https://example.com/lib"), ("LibraryItem", "the-vise")):
            settings.addProperty("App::PropertyString", name, "About", "")
            setattr(settings, name, value)
        source.save()
        FreeCAD.closeDocument(source.Name)
        found = PathWorkholding.recoverParts(self.doc, folders=[self.moved], library=[])
        self.assertEqual(found["vise.FCStd"], path)
        self.assertLinked(vise)
        self.assertEqual(vise.SourceSha256, added)
        self.assertEqual(
            (vise.SourceLibrary, vise.SourceItem), ("https://example.com/lib", "the-vise")
        )
        changed = PathWorkholding.changedSources(self.doc)
        self.assertEqual(changed, [(vise, path)])
        PathWorkholding.acceptChanged(changed)
        self.assertNotEqual(vise.SourceSha256, added)
        self.assertEqual(PathWorkholding.changedSources(self.doc), [])

    def test07_library_copy_changed(self):
        """The library's copy is not the one it was added with: said so when it is offered."""
        import hashlib, json

        library = os.path.join(self.dir, "library")
        os.makedirs(os.path.join(library, "vises"))
        shutil.copy(os.path.join(self.moved, "vise.FCStd"), os.path.join(library, "vises"))
        index = os.path.join(library, "index.json")
        with open(index, "w") as f:
            json.dump(
                {
                    "format": 1,
                    "items": [
                        {
                            "id": "vise",
                            "kind": "vise",
                            "file": "vises/vise.FCStd",
                            "sha256": hashlib.sha256(b"another").hexdigest(),
                        }
                    ],
                },
                f,
            )
        offered = []
        PathWorkholding.recoverParts(
            self.doc,
            folders=[os.path.join(self.dir, "here")],
            library=[index],
            askLibrary=lambda f, i: offered.append(i["changed"]) or False,
        )
        self.assertEqual(offered, [True])

    def test04_left_lost(self):
        """Nothing found or picked: left as it is, its settings kept."""
        found = PathWorkholding.recoverParts(
            self.doc, folders=[], library=[], askLibrary=lambda f, i: False, askFile=lambda f: None
        )
        self.assertEqual(found, {"vise.FCStd": None})
        vise = self.reopened()
        self.assertRoughly(vise.Opening.Value, 42)
        self.assertEqual(list(PathWorkholding.lostParts(self.doc)), ["vise.FCStd"])
