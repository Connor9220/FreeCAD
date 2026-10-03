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

"""Dogs, side clamps, edge clamps and a table, placed against the stock."""

import FreeCAD

import Path.Main.Job as PathJob
import Path.Main.WorkholdingItems as Items
import CAMTests.PathTestUtils as PathTestUtils

from FreeCAD import Vector


class TestPathWorkholdingItems(PathTestUtils.PathTestBase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPathWorkholdingItems")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.Length, self.box.Width, self.box.Height = 100, 60, 20
        self.doc.recompute()
        self.job = PathJob.Create("Job", [self.box], None)
        self.doc.recompute()
        self.bb = self.job.Stock.Shape.BoundBox

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def place(self, which, point, edge=False):
        item = Items.create(self.job, which)
        normal = Items.sideAt(self.job.Stock.Shape, point)
        if edge:
            Items.placeOnEdge(self.job, item, point, normal)
        else:
            Items.placeAgainst(self.job, item, point, normal)
        self.doc.recompute()
        return item

    def assertTouches(self, item):
        stock = self.job.Stock.Shape
        self.assertRoughly(item.Shape.distToShape(stock)[0], 0, 1e-6)
        self.assertRoughly(item.Shape.common(stock).Volume, 0, 1e-3)

    def test00_side_found(self):
        """The side clicked is the face nearest the point, facing out."""
        bb = self.bb
        n = Items.sideAt(self.job.Stock.Shape, Vector(30, bb.YMin, 5))
        self.assertRoughly(n.y, -1)
        n = Items.sideAt(self.job.Stock.Shape, Vector(bb.XMax, 20, 5))
        self.assertRoughly(n.x, 1)

    def test01_dog_against_the_front(self):
        """A dog stands on the surface the stock lies on, touching the side clicked."""
        bb = self.bb
        dog = self.place("Dog", Vector(30, bb.YMin, 5))
        self.assertTouches(dog)
        self.assertRoughly(dog.Shape.BoundBox.ZMin, bb.ZMin)
        self.assertRoughly(dog.Shape.BoundBox.YMax, bb.YMin)
        self.assertRoughly((dog.Shape.BoundBox.XMin + dog.Shape.BoundBox.XMax) / 2, 30)

    def test02_side_clamp_against_the_right(self):
        """A side clamp touches the side clicked, its body away from the stock."""
        bb = self.bb
        clamp = self.place("SideClamp", Vector(bb.XMax, 20, 5))
        self.assertTouches(clamp)
        self.assertRoughly(clamp.Shape.BoundBox.XMin, bb.XMax)

    def test03_edge_clamp_over_the_back_edge(self):
        """An edge clamp's lip lies over the top by its reach, its body beside the stock down to
        the table."""
        bb = self.bb
        clamp = self.place("EdgeClamp", Vector(50, bb.YMax, bb.ZMax), edge=True)
        cb = clamp.Shape.BoundBox
        self.assertRoughly(cb.YMin, bb.YMax - clamp.Reach.Value)
        self.assertRoughly(cb.ZMax, bb.ZMax + clamp.Rise.Value)
        self.assertRoughly(cb.ZMin, bb.ZMin)
        self.assertRoughly(clamp.Drop.Value, bb.ZLength)
        # its lip rests on the top, its body beside the side: touching, not cutting in
        self.assertTouches(clamp)

    def test04_table_under_the_stock(self):
        """A table goes under the stock, its waste board's top where the stock lies, and nothing
        is found hitting it."""
        table = Items.create(self.job, "Table")
        Items.placeTable(self.job, table)
        self.doc.recompute()
        self.assertRoughly(table.Shape.BoundBox.ZMax, self.bb.ZMin)
        self.assertFalse(table.Collides)
        dog = self.place("Dog", Vector(30, self.bb.YMin, 5))
        shape = PathJob.workholdingShape(self.job)
        self.assertEqual(len(shape.Solids), len(dog.Shape.Solids))

    def test05_click_on_the_model_lands_on_the_stock(self):
        """A point on the model, inside the stock, comes onto the stock's side nearest it."""
        bb = self.bb
        normal, point = Items.onSide(self.job.Stock.Shape, Vector(30, 0, 5))
        self.assertRoughly(normal.y, -1)
        self.assertRoughly(point.y, bb.YMin)
        self.assertRoughly(point.x, 30)

    def test06_inactive_is_not_hit(self):
        """Workholding set inactive stays, but nothing is found hitting it."""
        import Path.Main.Workholding as PathWorkholding

        dog = self.place("Dog", Vector(30, self.bb.YMin, 5))
        clamp = self.place("SideClamp", Vector(self.bb.XMax, 20, 5))
        self.assertEqual(PathWorkholding.memberOf(dog), (self.job, dog))
        PathWorkholding.setActive(dog, False)
        shape = PathJob.workholdingShape(self.job)
        self.assertEqual(len(shape.Solids), len(clamp.Shape.Solids))
        PathWorkholding.setActive(dog, True)
        shape = PathJob.workholdingShape(self.job)
        self.assertEqual(len(shape.Solids), len(clamp.Shape.Solids) + len(dog.Shape.Solids))
