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

"""What is made from a Job's model when the model is moved, or taken out and added back: the
operations' base geometry and the work planes keep to the part."""

import FreeCAD

import Path.Main.Job as PathJob
import Path.Main.Workplane as PathWorkplane
import Path.Op.Custom as PathCustom
import CAMTests.PathTestUtils as PathTestUtils

from FreeCAD import Vector


class TestPathJobModelLinks(PathTestUtils.PathTestBase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPathJobModelLinks")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.Length, self.box.Width, self.box.Height = 100, 60, 40
        self.doc.recompute()
        self.job = PathJob.Create("Job", [self.box], None)
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def _model(self):
        return self.job.Model.Group[0]

    def _faceNamed(self, obj, normal):
        for i, face in enumerate(obj.Shape.Faces):
            if (face.normalAt(0, 0) - normal).Length < 1e-6:
                return "Face%d" % (i + 1)
        return None

    def _op(self, name="Op"):
        op = PathCustom.Create(name, parentJob=self.job)
        op.ToolController.Tool.Diameter = 5.0
        self.doc.recompute()
        return op

    def test02_placed_workplane_follows_the_model(self):
        """A work plane made at a placement stays where it is on the part when the model moves."""
        at = FreeCAD.Placement(Vector(10, 20, 30), FreeCAD.Rotation(Vector(0, 1, 0), -20))
        plane = PathWorkplane.createWorkplane(self.job, placement=at)
        self.assertEqual(plane.MapMode, "ObjectXY")
        self.assertTrue(plane.Placement.isSame(at, 1e-9))

        model = self._model()
        model.Placement = FreeCAD.Placement(Vector(0, 0, 7.5), FreeCAD.Rotation())
        self.doc.recompute()
        self.assertRoughly(plane.Placement.Base.z, 37.5)
        self.assertRoughly(plane.Placement.Base.x, 10)

    def test03_unattached_things_are_carried(self):
        """What is placed on the part without being attached to it is what a move carries."""
        loose = PathWorkplane.createWorkplane(self.job)
        loose.AttachmentSupport = []
        loose.MapMode = "Deactivated"
        attached = PathWorkplane.createWorkplane(self.job, placement=FreeCAD.Placement())
        text = self.doc.addObject("Part::Feature", "Text")
        op = self._op()
        op.addProperty("App::PropertyLinkList", "BaseShapes", "Test", "")
        op.BaseShapes = [text]
        carried = PathJob.objectsInModelFrame(self.job)
        self.assertIn(loose, carried)
        self.assertIn(text, carried)
        self.assertNotIn(attached, carried)
        self.assertNotIn(self._model(), carried)
