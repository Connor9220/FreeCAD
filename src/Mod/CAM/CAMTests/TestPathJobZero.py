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

"""Each Job has a zero of its own.

The document's origin is the machine's table, where the models, the stock and
the workholding are laid out. A Job's zero is a work plane, and its program is
measured from it: setting the origin moves the zero, nothing else. A Job whose
zero is at the document's origin posts exactly as before.
"""

import json
import os
import re
import tempfile

import FreeCAD

import Path
import Path.Base.SetupSheet as PathSetupSheet
import Path.Main.Job as PathJob
import Path.Main.Stock as PathStock
import Path.Main.Workplane as PathWorkplane
import Path.Op.Custom as PathCustom
import CAMTests.PathTestUtils as PathTestUtils

from FreeCAD import Vector
from CAMTests.TestPathWorkplaneFrame import _machineCA
from CAMTests.TestPathTiltedWorkPlane import _PlaneFixture, _gcode
from CAMTests.TestPathTiltedWorkPlane import _machineCA as _tiltedMachine
import Path.Base.Generator.rotation as rotation
from Path.Post.CAMErrors import CAMValueError
from Path.Post.PostList import Postable
from Path.Post.Processor import PostProcessor, WrapperPost


class _Op:
    """An operation's stand-in, on no work plane."""

    Placement = FreeCAD.Placement()


def _item(source, commands):
    return Postable(
        item_type="operation",
        label="Op",
        path=Path.Path([Path.Command(name, args) for name, args in commands]),
        source=source,
    )


class _Job(PathTestUtils.PathTestBase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPathJobZero")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.Length, self.box.Width, self.box.Height = 100, 50, 20
        self.doc.recompute()
        self.job = PathJob.Create("Job", [self.box], None)
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def moveZero(self, x, y, z):
        PathWorkplane.zeroOf(self.job).Placement = FreeCAD.Placement(
            Vector(x, y, z), FreeCAD.Rotation()
        )

    def processor(self, machine=None):
        processor = PostProcessor(None, tooltip=None, tooltipargs=None, units=None)
        processor._job = self.job
        processor._machine = machine
        if machine is not None:
            processor._merge_machine_config()
        return processor

    @staticmethod
    def point(item):
        c = item.path.Commands[0]
        return Vector(c.x, c.y, c.z)


class TestJobZeroSetup(_Job):
    """A Job has its zero from the start, and one from an older document gets it."""

    def test_new_job_has_its_zero_at_the_origin(self):
        zero = PathWorkplane.zeroOf(self.job)
        self.assertIsNotNone(zero)
        self.assertEqual(zero.TypeId, "Part::LocalCoordinateSystem")
        self.assertTrue(zero.Placement.isIdentity(1e-9))
        self.assertEqual(PathWorkplane.workplanesOf(self.job)[0], zero)
        self.assertFalse(zero.AttachmentSupport)

    def test_older_job_gets_a_zero_at_the_origin_when_opened(self):
        zero = self.job.Zero
        self.job.Zero = None
        self.job.Workplanes.removeObject(zero)
        self.doc.removeObject(zero.Name)
        self.job.removeProperty("Zero")
        self.job.Proxy.onDocumentRestored(self.job)
        zero = PathWorkplane.zeroOf(self.job)
        self.assertIsNotNone(zero)
        self.assertTrue(zero.Placement.isIdentity(1e-9))
        self.assertEqual(PathWorkplane.workplanesOf(self.job)[0], zero)

    def test_zero_is_made_once(self):
        zero = PathWorkplane.zeroOf(self.job)
        self.assertEqual(PathWorkplane.setupZero(self.job), zero)
        self.job.Proxy.onDocumentRestored(self.job)
        self.assertEqual(PathWorkplane.zeroOf(self.job), zero)
        zeros = [o for o in self.doc.Objects if o.Name.startswith("Zero")]
        self.assertEqual(zeros, [zero])

    def test_new_plane_takes_the_zeros_fixture(self):
        self.assertEqual(PathWorkplane.createWorkplane(self.job).Fixture, "")
        self.job.Zero.Fixture = "G55"
        self.assertEqual(PathWorkplane.createWorkplane(self.job).Fixture, "G55")

    def test_zero_stays_when_the_model_moves(self):
        plane = PathWorkplane.createWorkplane(self.job)
        plane.AttachmentSupport = None
        plane.MapMode = "Deactivated"
        carried = PathJob.objectsInModelFrame(self.job)
        self.assertIn(plane, carried)
        self.assertNotIn(self.job.Zero, carried)


class TestJobZeroPost(_Job):
    """The program is measured from the Job's zero, in both kinds of post."""

    def test_zero_at_the_origin_leaves_the_path_as_it_is(self):
        item = _item(_Op(), [("G1", {"X": 1, "Y": 2, "Z": -5})])
        before = item.path.Commands[0].toGCode()
        out = self.processor()._expand_workplane_frames([("Job", [item])])
        self.assertEqual(out[0][1][0].path.Commands[0].toGCode(), before)

    def test_path_is_measured_from_the_zero(self):
        self.moveZero(10, 20, 5)
        item = _item(_Op(), [("G1", {"X": 1, "Y": 2, "Z": -5})])
        out = self.processor()._expand_workplane_frames([("Job", [item])])
        self.assertCoincide(self.point(out[0][1][0]), Vector(-9, -18, -10))

    def test_plane_operation_is_measured_from_the_zero(self):
        self.moveZero(10, 20, 5)
        plane = PathWorkplane.createWorkplane(
            self.job, placement=FreeCAD.Placement(Vector(30, 0, 20), FreeCAD.Rotation())
        )
        op = PathCustom.Create("OnPlane", parentJob=self.job)
        op.Workplane = plane
        self.doc.recompute()
        item = _item(op, [("G1", {"X": 1, "Y": 2, "Z": -5})])
        out = self.processor()._expand_workplane_frames([("Job", [item])])
        self.assertCoincide(self.point(out[0][1][0]), Vector(21, -18, 10))

    def test_operation_on_the_zero_is_written_as_stored(self):
        self.moveZero(10, 20, 5)
        op = PathCustom.Create("OnZero", parentJob=self.job)
        op.Workplane = self.job.Zero
        self.doc.recompute()
        item = _item(op, [("G1", {"X": 1, "Y": 2, "Z": -5})])
        out = self.processor()._expand_workplane_frames([("Job", [item])])
        self.assertCoincide(self.point(out[0][1][0]), Vector(1, 2, -5))

    def test_custom_gcode_on_no_plane_is_left_as_written(self):
        self.moveZero(10, 20, 5)
        op = PathCustom.Create("Custom", parentJob=self.job)
        self.doc.recompute()
        item = _item(op, [("G1", {"X": 1, "Y": 2, "Z": -5})])
        out = self.processor()._expand_workplane_frames([("Job", [item])])
        self.assertCoincide(self.point(out[0][1][0]), Vector(1, 2, -5))

    def test_legacy_post_measures_from_the_zero(self):
        self.moveZero(10, 20, 5)
        item = _item(_Op(), [("G1", {"X": 1, "Y": 2, "Z": -5})])
        WrapperPost._place_operations([("Job", [item])], self.job)
        self.assertCoincide(self.point(item), Vector(-9, -18, -10))
        # the script is not to place it again
        self.assertTrue(item.Placement.isIdentity(1e-9))

    def test_rotary_machine_refuses_a_turned_zero(self):
        from Machine.models.machine import RotationStrategy

        machine = _machineCA()
        machine.kinematics.rotation_strategy = RotationStrategy.DWO
        self.moveZero(10, 20, 5)
        item = _item(_Op(), [("G1", {"X": 1, "Y": 2, "Z": -5})])
        self.processor(machine)._expand_workplane_frames([("Job", [item])])
        PathWorkplane.zeroOf(self.job).Placement = FreeCAD.Placement(
            Vector(10, 20, 5), FreeCAD.Rotation(Vector(0, 0, 1), 30)
        )
        item = _item(_Op(), [("G1", {"X": 1, "Y": 2, "Z": -5})])
        with self.assertRaises(CAMValueError):
            self.processor(machine)._expand_workplane_frames([("Job", [item])])


class TestJobZeroRotary(_PlaneFixture):
    """A 3+2 operation on a rotary machine, with the Job's zero moved: the plane and the path
    measured from it, the rotary positions as before."""

    def expanded(self, strategy, zero):
        from Machine.models.machine import RotationStrategy

        self.machine = _tiltedMachine(getattr(RotationStrategy, strategy))
        PathWorkplane.zeroOf(self.job).Placement = FreeCAD.Placement(zero, FreeCAD.Rotation())
        op = self._op("Tilted", self._plane())
        processor = self._processor()
        processor._job = self.job
        return self._expand([self._item(op)], processor), op

    def test_twp_declares_the_plane_from_the_zero(self):
        items, op = self.expanded("TWP", Vector(10, 20, 5))
        self.assertEqual(
            self._shape(items),
            ["G68.2 X20.000 Y-10.000 Z0.000 I0.000 J45.000 K0.000", "G53.1", "operation", "G69"],
        )
        self.assertEqual(_gcode(items[2].path), _gcode(op.Path), "path emitted as stored")

    def test_dwo_path_measured_from_the_zero(self):
        at, _ = self.expanded("DWO", Vector())
        moved, _ = self.expanded("DWO", Vector(10, 20, 5))
        self.assertEqual(
            [i.item_type for i in at], [i.item_type for i in moved], "same rotary moves"
        )
        self.assertEqual(at[0].path.Commands[0].toGCode(), moved[0].path.Commands[0].toGCode())
        # each point shifted by the zero, turned as the table turns it
        chain = rotation.build_kinematic_chain(self.machine)
        angles = {k: v for c in at[0].path.Commands for k, v in c.Parameters.items()}
        shift = rotation.compute_rotation_matrix(chain, angles).multVec(Vector(10, 20, 5))
        for a, b in zip(at[-1].path.Commands, moved[-1].path.Commands):
            for k, by in (("X", shift.x), ("Y", shift.y), ("Z", shift.z)):
                if k in a.Parameters:
                    self.assertRoughly(a.Parameters[k] - b.Parameters[k], by)


class TestJobZeroTemplate(_Job):
    """A Job template keeps the stock measured from the Job's zero, and the zero on its own."""

    def setUp(self):
        super().setUp()
        old = self.job.Stock
        self.job.Stock = PathStock.CreateBox(
            self.job,
            Vector(120, 70, 30),
            FreeCAD.Placement(Vector(-10, -10, -5), FreeCAD.Rotation()),
        )
        self.doc.removeObject(old.Name)
        self.doc.recompute()
        self.files = []

    def tearDown(self):
        for name in self.files:
            os.remove(name)
        super().tearDown()

    def template(self, attrs):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
            json.dump(attrs, fp)
        self.files.append(fp.name)
        job = PathJob.Create("Again", [self.box], fp.name)
        self.doc.recompute()
        return job

    def attrs(self):
        attrs = self.job.Proxy.templateAttrs(self.job)
        attrs[PathJob.JobTemplate.Stock] = PathJob.stockTemplateAttrs(self.job)
        return json.loads(json.dumps(attrs))

    def test_oldTemplateLeavesTheZeroAtTheOrigin(self):
        attrs = self.attrs()
        del attrs[PathJob.JobTemplate.Zero]
        job = self.template(attrs)
        self.assertTrue(PathWorkplane.zeroPlacement(job).isIdentity(1e-9))
        self.assertTrue(job.Stock.Placement.Base.isEqual(Vector(-10, -10, -5), 1e-9))

    def test_stockKeptFromTheZero(self):
        self.moveZero(30, 20, 10)
        PathWorkplane.zeroOf(self.job).Fixture = "G55"
        attrs = self.attrs()
        stock = attrs[PathJob.JobTemplate.Stock]
        self.assertRoughly(stock["posX"], -40)
        self.assertRoughly(stock["posY"], -30)
        self.assertRoughly(stock["posZ"], -15)
        zero = attrs[PathJob.JobTemplate.Zero]
        self.assertRoughly(zero["posX"], 30)
        self.assertEqual(zero["Fixture"], "G55")
        # a version without a Job zero: the stock as far from its zero, the document's origin
        older = dict(attrs)
        del older[PathJob.JobTemplate.Zero]
        job = self.template(older)
        self.assertTrue(job.Stock.Placement.Base.isEqual(Vector(-40, -30, -15), 1e-9))

    def test_builtAgainWhereItWas(self):
        self.moveZero(30, 20, 10)
        PathWorkplane.zeroOf(self.job).Fixture = "G55"
        job = self.template(self.attrs())
        self.assertTrue(
            PathWorkplane.zeroPlacement(job).isSame(PathWorkplane.zeroPlacement(self.job), 1e-9)
        )
        self.assertEqual(PathWorkplane.fixtureOf(PathWorkplane.zeroOf(job)), "G55")
        self.assertTrue(job.Stock.Placement.isSame(self.job.Stock.Placement, 1e-9))

    def test_olderVersionReadsIt(self):
        """Nothing a version that reads every list as a list of dicts fails on."""
        self.moveZero(30, 20, 10)
        PathSetupSheet._traverseTemplateAttributes(self.attrs(), str)


class TestJobZeroPostedFile(PathTestUtils.PathTestBase):
    """A document from before Jobs had a zero, posted whole."""

    def setUp(self):
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")
        self.doc = FreeCAD.open(FreeCAD.getHomePath() + "/Mod/CAM/CAMTests/boxtest.fcstd")
        self.job = self.doc.getObject("Job")
        self.job.PostProcessorArgs = "--no-show-editor --no-header"

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "")

    def post(self, name):
        from Path.Post.Processor import PostProcessorFactory

        post = PostProcessorFactory.get_post_processor(self.job, name)
        return "\n".join(gcode for _, gcode in post.export())

    def words(self, gcode, axis):
        return [float(v) for v in re.findall(axis + r"(-?\d+\.\d+)", gcode)]

    def test_posts_measured_from_the_zero(self):
        self.assertIsNotNone(PathWorkplane.zeroOf(self.job))
        for name in ("linuxcnc", "linuxcnc_legacy"):
            at = self.post(name)
            PathWorkplane.zeroOf(self.job).Placement = FreeCAD.Placement(
                Vector(10, 20, 0), FreeCAD.Rotation()
            )
            moved = self.post(name)
            PathWorkplane.zeroOf(self.job).Placement = FreeCAD.Placement()
            self.assertEqual(self.post(name), at, name)
            for axis, by in (("X", 10), ("Y", 20), ("Z", 0)):
                before, after = self.words(at, axis), self.words(moved, axis)
                self.assertTrue(before, name)
                self.assertEqual(len(before), len(after), name)
                for b, a in zip(before, after):
                    self.assertRoughly(b - a, by)
