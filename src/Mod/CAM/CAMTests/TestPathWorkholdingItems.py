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

"""Dogs, side clamps, edge clamps and a table, placed against the stock; stops and clamps placed
round it by side, from files of their own, and a stop shared by two Jobs."""

import os
import shutil
import tempfile

import FreeCAD
import Part

import Path.Main.Job as PathJob
import Path.Workholding.Vise as PathWorkholding
import Path.Workholding.Items as Items
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

    def place(self, which, point, normal, edge=False):
        """A piece of class which put against the stock's side whose outward normal is normal, at
        point along it: standing on the surface the stock lies on, or with edge, a hold-down over
        the stock's top edge, its body down to the table."""
        item = Items.create(self.job, which)
        bb = self.job.Stock.Shape.BoundBox
        rotation = FreeCAD.Rotation(Vector(0, 1, 0), normal * -1)
        item.Placement = FreeCAD.Placement(
            Vector(point.x, point.y, bb.ZMax if edge else bb.ZMin), rotation
        )
        if edge:
            item.Drop = bb.ZMax - bb.ZMin
        self.doc.recompute()
        return item

    def assertTouches(self, item):
        stock = self.job.Stock.Shape
        self.assertRoughly(item.Shape.distToShape(stock)[0], 0, 1e-6)
        self.assertRoughly(item.Shape.common(stock).Volume, 0, 1e-3)

    def test01_dog_against_the_front(self):
        """A dog stands on the surface the stock lies on, touching the side clicked."""
        bb = self.bb
        dog = self.place("Dog", Vector(30, bb.YMin, 5), Vector(0, -1, 0))
        self.assertTouches(dog)
        self.assertRoughly(dog.Shape.BoundBox.ZMin, bb.ZMin)
        self.assertRoughly(dog.Shape.BoundBox.YMax, bb.YMin)
        self.assertRoughly((dog.Shape.BoundBox.XMin + dog.Shape.BoundBox.XMax) / 2, 30)

    def test02_side_clamp_against_the_right(self):
        """A side clamp touches the side clicked, its body away from the stock."""
        bb = self.bb
        clamp = self.place("SideClamp", Vector(bb.XMax, 20, 5), Vector(1, 0, 0))
        self.assertTouches(clamp)
        self.assertRoughly(clamp.Shape.BoundBox.XMin, bb.XMax)

    def test03_edge_clamp_over_the_back_edge(self):
        """An edge clamp's lip lies over the top by its reach, its body beside the stock down to
        the table."""
        bb = self.bb
        clamp = self.place("EdgeClamp", Vector(50, bb.YMax, bb.ZMax), Vector(0, 1, 0), edge=True)
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
        dog = self.place("Dog", Vector(30, self.bb.YMin, 5), Vector(0, -1, 0))
        shape = PathJob.workholdingShape(self.job)
        self.assertEqual(len(shape.Solids), len(dog.Shape.Solids))

    def test06_inactive_is_not_hit(self):
        """Workholding set inactive stays, but nothing is found hitting it."""
        import Path.Workholding.Vise as PathWorkholding

        dog = self.place("Dog", Vector(30, self.bb.YMin, 5), Vector(0, -1, 0))
        clamp = self.place("SideClamp", Vector(self.bb.XMax, 20, 5), Vector(1, 0, 0))
        self.assertEqual(PathWorkholding.memberOf(dog), (self.job, dog))
        PathWorkholding.setActive(dog, False)
        shape = PathJob.workholdingShape(self.job)
        self.assertEqual(len(shape.Solids), len(clamp.Shape.Solids))
        PathWorkholding.setActive(dog, True)
        shape = PathJob.workholdingShape(self.job)
        self.assertEqual(len(shape.Solids), len(clamp.Shape.Solids) + len(dog.Shape.Solids))


class _Stock(PathTestUtils.PathTestBase):
    """A Job of a box, its stock's box, and what tells a piece touches the stock."""

    def makeJob(self, name, x=0.0):
        box = self.doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 100, 60, 20
        box.Placement.Base = Vector(x, 0, 0)
        self.doc.recompute()
        job = PathJob.Create(name, [box], None)
        self.doc.recompute()
        return job

    def bb(self, job=None):
        return (job or self.job).Stock.Shape.BoundBox

    def assertTouches(self, item, job=None):
        stock = (job or self.job).Stock.Shape
        shape = PathJob.workholdingShape(job or self.job) if item is None else item.Shape
        self.assertRoughly(shape.distToShape(stock)[0], 0, 1e-6)
        self.assertRoughly(shape.common(stock).Volume, 0, 1e-3)

    def middle(self, item):
        b = item.Shape.BoundBox
        return Vector((b.XMin + b.XMax) / 2, (b.YMin + b.YMax) / 2, b.ZMin)


class TestPathWorkholdingStops(_Stock):
    """Stops on one side of the stock or on a corner, clamps on any side, placed round it by side,
    each saying where it is placed, read back from them."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPathWorkholdingStops")
        self.job = self.makeJob("Job")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test00_sides(self):
        """The part's sides standing round the stock, each side's frame on the surface the stock
        lies on, +Y into it."""
        self.assertEqual(Items.sides(self.job), ["-Y", "+Y", "-X", "+X"])
        bb = self.bb()
        frame, length = Items.sideFrame(self.job, "-Y")
        self.assertRoughly(length, bb.XLength)
        self.assertCoincide(frame.Base, Vector(bb.Center.x, bb.YMin, bb.ZMin))
        self.assertCoincide(frame.Rotation.multVec(Vector(0, 1, 0)), Vector(0, 1, 0))
        self.assertCoincide(frame.Rotation.multVec(Vector(0, 0, 1)), Vector(0, 0, 1))
        frame, length = Items.sideFrame(self.job, "+X")
        self.assertRoughly(length, bb.YLength)
        self.assertCoincide(frame.Base, Vector(bb.XMax, bb.Center.y, bb.ZMin))
        self.assertCoincide(frame.Rotation.multVec(Vector(0, 1, 0)), Vector(-1, 0, 0))
        self.assertCoincide(frame.Rotation.multVec(Vector(0, 0, 1)), Vector(0, 0, 1))
        self.assertEqual(Items.spread(100, 2), [-25, 25])
        self.assertEqual(Items.spread(100, 1), [0])
        for got, want in zip(Items.spread(90, 3), [-30, 0, 30]):
            self.assertRoughly(got, want)

    def test01_stops_on_one_side(self):
        """Two dogs on the front, spread evenly along it, put against the stock where it is: the
        stock stays."""
        before = self.bb()
        dogs = Items.setStops(self.job, [{"side": "-Y", "which": "Dog", "count": 2}])
        self.assertEqual(len(dogs), 2)
        bb = self.bb()
        self.assertTrue(bb.isInside(before) and before.isInside(bb))
        for dog in dogs:
            self.assertTouches(dog)
            self.assertRoughly(dog.Shape.BoundBox.ZMin, bb.ZMin)
            self.assertRoughly(dog.Shape.BoundBox.YMax, bb.YMin)
        xs = sorted(self.middle(d).x for d in dogs)
        self.assertRoughly(xs[0], bb.XMin + bb.XLength / 4)
        self.assertRoughly(xs[1], bb.XMin + 3 * bb.XLength / 4)

    def test02_corner(self):
        """Three two one: two on the front, one on the left; stops on opposite sides, or on three,
        refused, those there staying."""
        Items.setStops(self.job, [{"side": "-Y", "count": 2}, {"side": "-X", "count": 1}])
        bb = self.bb()
        left = Items.stopsOn(self.job, "-X")
        self.assertEqual(len(left), 1)
        self.assertRoughly(left[0].Shape.BoundBox.XMax, bb.XMin)
        self.assertRoughly(self.middle(left[0]).y, bb.Center.y)
        self.assertTouches(left[0])
        with self.assertRaises(ValueError):
            Items.setStops(self.job, [{"side": "-Y"}, {"side": "+Y"}])
        with self.assertRaises(ValueError):
            Items.setStops(self.job, [{"side": "-Y"}, {"side": "-X"}, {"side": "+X"}])
        self.assertEqual(len(Items.stopsOn(self.job)), 3)
        # a side taken away takes its stops
        Items.setStops(self.job, [{"side": "-X", "count": 1}])
        self.assertEqual([s.StockSide for s in Items.stopsOn(self.job)], ["-X"])

    def test03_counts(self):
        """Spread evenly, each in the middle of its share of the side; fewer takes the last ones
        away, the first staying the same piece."""
        dogs = Items.setStops(self.job, [{"side": "-Y", "count": 3}])
        bb = self.bb()
        xs = sorted(self.middle(d).x for d in dogs)
        self.assertRoughly(xs[0], bb.XMin + bb.XLength / 6)
        self.assertRoughly(xs[1], bb.Center.x)
        self.assertRoughly(xs[2], bb.XMax - bb.XLength / 6)
        first = dogs[0].Name
        dogs = Items.setStops(self.job, [{"side": "-Y", "count": 1}])
        self.assertEqual([d.Name for d in dogs], [first])
        self.assertRoughly(self.middle(dogs[0]).x, bb.Center.x)
        self.assertIsNone(self.doc.getObject(first + "001"))

    def test04_fence(self):
        """A fence along the side, as long as the side, touching the stock; a dog in its place
        made anew."""
        fence = Items.setStops(self.job, [{"side": "-X", "which": "Fence"}])[0]
        name = fence.Name
        bb = self.bb()
        self.assertEqual(fence.Kind, Items.Kind.Stop)
        self.assertRoughly(fence.Length.Value, bb.YLength)
        self.assertRoughly(fence.Shape.BoundBox.YLength, bb.YLength)
        self.assertRoughly(fence.Shape.BoundBox.XMax, bb.XMin)
        self.assertTouches(fence)
        dog = Items.setStops(self.job, [{"side": "-X", "which": "Dog"}])[0]
        self.assertEqual(dog.Source, "Dog")
        self.assertIsNone(self.doc.getObject(name))

    def test05_side_clamp_not_on_a_stop_side(self):
        """A side clamp pushes the part onto the stops: refused on a side with stops, put on those
        away from them."""
        Items.setStops(self.job, [{"side": "-Y", "count": 2}, {"side": "-X"}])
        with self.assertRaises(ValueError):
            Items.setClamps(self.job, [{"side": "-Y", "which": "SideClamp"}])
        self.assertTrue(Items.pushes("SideClamp"))
        self.assertFalse(Items.pushes("EdgeClamp"))
        clamps = Items.setClamps(
            self.job,
            [
                {"side": "+Y", "which": "SideClamp", "count": 2},
                {"side": "+X", "which": "SideClamp"},
            ],
        )
        self.assertEqual(len(clamps), 3)
        bb = self.bb()
        for clamp in clamps:
            self.assertTouches(clamp)
        right = Items.clampsOn(self.job, "+X")[0]
        self.assertRoughly(right.Shape.BoundBox.XMin, bb.XMax)
        self.assertRoughly(right.Shape.BoundBox.ZMin, bb.ZMin)
        # nor can stops come to the side clamps' side
        Items.setStops(self.job, [{"side": "+X"}])
        self.assertEqual(len(Items.stopsOn(self.job, "+X")), 1)

    def test06_hold_downs_on_every_side(self):
        """Edge clamps on every side, those with stops too: each lip over the stock's top edge,
        its body beside the side down to the table."""
        Items.setStops(self.job, [{"side": "-Y", "count": 2}])
        clamps = Items.setClamps(
            self.job,
            [{"side": side, "which": "EdgeClamp", "count": 2} for side in Items.sides(self.job)],
        )
        self.assertEqual(len(clamps), 8)
        bb = self.bb()
        for clamp in clamps:
            cb = clamp.Shape.BoundBox
            self.assertRoughly(cb.ZMax, bb.ZMax + clamp.Rise.Value)
            self.assertRoughly(cb.ZMin, bb.ZMin)
            self.assertRoughly(clamp.Drop.Value, bb.ZLength)
            self.assertTouches(clamp)
        back = Items.clampsOn(self.job, "+Y")[0].Shape.BoundBox
        self.assertRoughly(back.YMin, bb.YMax - Items.clampsOn(self.job, "+Y")[0].Reach.Value)

    def test07_read_back(self):
        """Each piece says where it is placed, hidden; the Job's stops and clamps read back as they
        were set."""
        stops = [
            {"side": "-Y", "which": "Dog", "count": 2},
            {"side": "+X", "which": "Fence", "count": 1},
        ]
        clamps = [
            {"side": "+Y", "which": "SideClamp", "count": 3},
            {"side": "-X", "which": "EdgeClamp", "count": 2},
        ]
        Items.setStops(self.job, stops)
        Items.setClamps(self.job, clamps)
        self.assertEqual(Items.stopsOf(self.job), stops)
        key = lambda spec: spec["side"]
        self.assertEqual(sorted(Items.clampsOf(self.job), key=key), sorted(clamps, key=key))
        dog = Items.stopsOn(self.job, "-Y")[1]
        self.assertEqual((dog.StockSide, dog.SideIndex, dog.Source), ("-Y", 1, "Dog"))
        for name in ("StockSide", "SideIndex", "Source", "Pinned", "Along"):
            self.assertIn("Hidden", dog.getEditorMode(name))
        # the pieces and a table, all but vises
        table = Items.addTable(self.job)
        self.assertIn(table, Items.itemsOf(self.job))
        self.assertEqual(len(Items.itemsOf(self.job)), 9)
        self.assertIs(Items.addTable(self.job), table)

    def test08_positioned_and_removed(self):
        """A piece put at a Job X stays there as the side's count changes, the others spread; on
        the back, whose side runs against X, the same; when the stock moves it goes with it, kept
        from the stock's near end. One taken away, the one pinned stays."""
        dogs = Items.setStops(self.job, [{"side": "-Y", "count": 2}])
        at = self.middle(dogs[0]).x
        x = self.bb().XMin + 12
        Items.setPosition(dogs[1], x)
        self.assertRoughly(Items.positionOf(dogs[1]), x)
        self.assertRoughly(self.middle(dogs[0]).x, at)
        self.assertTouches(dogs[1])
        # pinned as the side is set again, with more
        dogs = Items.setStops(self.job, [{"side": "-Y", "count": 3}])
        self.assertRoughly(Items.positionOf(dogs[1]), x)
        self.assertTrue(dogs[1].Pinned)
        self.assertFalse(dogs[0].Pinned or dogs[2].Pinned)
        # a clamp on the back: its Job X too
        clamp = Items.setClamps(self.job, [{"side": "+Y", "which": "SideClamp", "count": 2}])[0]
        Items.setPosition(clamp, self.bb().XMax - 20)
        self.assertRoughly(Items.positionOf(clamp), self.bb().XMax - 20)
        self.assertTouches(clamp)
        # the stock moved, the one pinned with it
        PathWorkholding.moveModel(self.job, Vector(30, 0, 0))
        Items.layout(self.job)
        self.assertRoughly(Items.positionOf(dogs[1]), x + 30)
        # one taken away: the pinned one stays, the others spread again
        Items.removePiece(dogs[0])
        self.assertRoughly(Items.positionOf(dogs[1]), x + 30)

    def test09_placed_again_when_the_stock_moves(self):
        """The part moved, its stops and clamps put against its stock again."""
        Items.setStops(self.job, [{"side": "-Y", "count": 2}])
        Items.setClamps(self.job, [{"side": "+Y", "which": "EdgeClamp"}])
        PathWorkholding.moveModel(self.job, Vector(12, 7, 3))
        self.doc.recompute()
        Items.layout(self.job)
        for piece in Items.stopsOn(self.job) + Items.clampsOn(self.job):
            self.assertTouches(piece)

    def test10_sides_are_the_part_own(self):
        """The part turned a quarter round, its front faces +X: stops on its front go there."""
        PathWorkholding.turnModel(self.job, FreeCAD.Rotation(Vector(0, 0, 1), 90), self.bb().Center)
        self.doc.recompute()
        self.assertCoincide(Items.sideDirection(self.job, "-Y"), Vector(1, 0, 0))
        dog = Items.setStops(self.job, [{"side": "-Y"}])[0]
        self.assertRoughly(dog.Shape.BoundBox.XMin, self.bb().XMax)
        self.assertTouches(dog)
        # turned onto its side, its top stands round the stock and its front lies on the table
        PathWorkholding.turnModel(self.job, FreeCAD.Rotation(Vector(0, 1, 0), 90), self.bb().Center)
        self.assertNotIn("-Y", Items.sides(self.job))
        self.assertIn("+Z", Items.sides(self.job))
        with self.assertRaises(ValueError):
            Items.setStops(self.job, [{"side": "-Y"}])

    def test11_simulated(self):
        """Stops and clamps placed by side are what the simulator finds hit."""
        dogs = Items.setStops(self.job, [{"side": "-Y", "count": 2}])
        clamps = Items.setClamps(self.job, [{"side": "+Y", "which": "EdgeClamp"}])
        parts = [p for p, _ in PathJob.workholdingParts(self.job)]
        self.assertEqual(sorted(p.Name for p in parts), sorted(p.Name for p in dogs + clamps))


class TestPathWorkholdingClampFile(_Stock):
    """A clamp from a file of its own, a hold-down laid out on the stock's top edge."""

    def setUp(self):
        # a clamp's own file: a head on the stock's top edge, its jaw 6 over the top and 6 above
        # it, its body 12 out beside the side and 5 down it; a screw beside the stock. Laid out
        # as a hold-down: its origin on the top edge, +Y into the stock
        self.source = FreeCAD.newDocument("TestClampSource")
        part = self.source.addObject("App::Part", "Clamp")
        part.Label = "Hugger"
        head = self.source.addObject("Part::Feature", "Head")
        head.Shape = (
            Part.makeBox(25.4, 12, 11, Vector(-12.7, -12, -5))
            .fuse(Part.makeBox(25.4, 6, 6, Vector(-12.7, 0, 0)))
            .removeSplitter()
        )
        screw = self.source.addObject("Part::Feature", "Screw")
        screw.Shape = Part.makeCylinder(3, 30, Vector(0, -3, -24))
        settings = self.source.addObject("App::VarSet", "Settings")
        settings.addProperty("App::PropertyString", "Kind", "Clamp", "")
        settings.addProperty("App::PropertyLength", "Width", "Clamp", "")
        settings.Kind, settings.Width = "HoldDown", 25.4
        part.addObjects([head, screw, settings])
        self.source.recompute()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Hugger_Clamp.FCStd")
        self.source.saveAs(self.path)

        self.doc = FreeCAD.newDocument("TestClampFile")
        self.job = self.makeJob("Job")
        self.doc.saveAs(os.path.join(self.dir, "job.FCStd"))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)
        FreeCAD.closeDocument(self.source.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test00_found(self):
        """A clamp's file is found in its folder by the Kind its VarSet gives, read without
        opening it; others are not."""
        self.assertEqual(Items.clampFile(self.path), ("Hugger Clamp", "HoldDown"))
        self.assertFalse(Items.pushes(self.path))

    def test01_linked_and_placed(self):
        """Clamps from the file linked into the Job, their parts in their frame on the stock's top
        edge, the head's jaw over the top: placed with no clicking."""
        rows = Items.setClamps(self.job, [{"side": "+Y", "which": self.path, "count": 2}])
        self.assertEqual(len(rows), 2)
        bb = self.bb()
        for row in rows:
            self.assertEqual(row.Kind, "HoldDown")
            self.assertRoughly(row.Width.Value, 25.4)
            links = [o for o in row.Group if o.isDerivedFrom("App::Link")]
            self.assertEqual(sorted(o.LinkedObject.Name for o in links), ["Head", "Screw"])
            self.assertEqual(links[0].LinkedObject.Document, self.source)
            self.assertRoughly(row.Placement.Base.z, bb.ZMax)
            self.assertRoughly(row.Placement.Base.y, bb.YMax)
            self.assertCoincide(row.Placement.Rotation.multVec(Vector(0, 1, 0)), Vector(0, -1, 0))
        parts = dict(PathJob.workholdingParts(self.job))
        heads = [shape for part, shape in parts.items() if part.LinkedObject.Name == "Head"]
        self.assertEqual(len(heads), 2)
        for head in heads:
            self.assertRoughly(head.BoundBox.ZMax, bb.ZMax + 6)
            self.assertRoughly(head.BoundBox.YMin, bb.YMax - 6)
            self.assertRoughly(head.common(self.job.Stock.Shape).Volume, 0, 1e-3)
        self.assertEqual(
            Items.clampsOf(self.job),
            [{"side": "+Y", "which": self.path, "count": 2}],
        )
        # fewer: one taken away, its parts with it
        names = [rows[1].Name] + [o.Name for o in rows[1].Group]
        Items.setClamps(self.job, [{"side": "+Y", "which": self.path, "count": 1}])
        self.assertTrue(all(self.doc.getObject(n) is None for n in names))

    def test02_removed_whole(self):
        """One of its parts taken away takes the clamp, and the rest spread again."""
        rows = Items.setClamps(self.job, [{"side": "-X", "which": self.path, "count": 2}])
        name = rows[0].Name
        Items.removePiece(rows[0].Group[0])
        self.assertIsNone(self.doc.getObject(name))
        left = Items.clampsOn(self.job, "-X")
        self.assertEqual([r.Name for r in left], [rows[1].Name])
        self.assertRoughly(left[0].Placement.Base.y, self.bb().Center.y)

    def test03_another_beside_it(self):
        """Another of a clamp from its file beside it: linked as the first, free of its side."""
        row = Items.setClamps(self.job, [{"side": "+Y", "which": self.path}])[0]
        copy = PathWorkholding.addAnother(row, Vector(50, 0, 0))
        self.assertIsInstance(copy.Proxy, Items.ObjectClamp)
        self.assertEqual(len(copy.Group), 2)
        self.assertFalse(Items.isPlaced(copy))
        self.assertEqual(Items.clampsOn(self.job), [row])


class TestPathWorkholdingSharedStop(_Stock):
    """A dog between two parts, shared by their Jobs: each part against one of its faces."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPathWorkholdingSharedStop")
        self.job = self.makeJob("Job")
        self.other = self.makeJob("Job", 300)
        # behind the first part
        self.dog = Items.setStops(self.job, [{"side": "+Y"}])[0]

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test00_shared(self):
        """The second Job's stop on the dog's other face, as big; its part moved against it, the
        dog staying."""
        at = FreeCAD.Placement(self.dog.Placement)
        self.assertTrue(Items.canShareStop(self.dog, self.other))
        self.assertFalse(Items.canShareStop(self.dog, self.job))
        self.assertEqual(Items.shareableStops(self.other), [self.dog])
        stop = Items.shareStop(self.dog, self.other, "-Y")
        self.assertEqual(stop.Follows, self.dog)
        self.assertEqual((self.dog.Contact, stop.Contact), (1, 2))
        self.assertTrue(self.dog.Placement.isSame(at, 1e-9))
        self.assertEqual(PathWorkholding.memberOf(stop), (self.other, stop))
        self.assertEqual(PathWorkholding.shareGroup(stop), [self.dog, stop])
        # one dog: its shape where the first is
        self.assertRoughly(stop.Shape.common(self.dog.Shape).Volume, self.dog.Shape.Volume)
        # each part against a face of it, the second's front against the far one
        self.assertTouches(self.dog)
        self.assertTouches(stop, self.other)
        bb = self.bb(self.other)
        self.assertRoughly(bb.YMin, self.dog.Shape.BoundBox.YMax)
        self.assertRoughly(bb.Center.x, self.middle(self.dog).x)
        self.assertRoughly(bb.ZMin, self.bb().ZMin)
        # two faces, two Jobs
        third = self.makeJob("Job", 600)
        self.assertFalse(Items.canShareStop(self.dog, third))
        self.assertEqual(Items.shareableStops(third), [])
        with self.assertRaises(ValueError):
            Items.shareStop(self.dog, third, "-Y")

    def test01_follows(self):
        """The dog moved, the other Job's stop with it, as big as it; its part moved to it again."""
        stop = Items.shareStop(self.dog, self.other, "-Y")
        self.dog.Diameter = 15
        placement = FreeCAD.Placement(self.dog.Placement)
        placement.move(Vector(20, 30, 0))
        self.dog.Placement = placement
        self.doc.recompute()
        self.assertRoughly(stop.Diameter.Value, 15)
        self.assertRoughly(stop.Shape.common(self.dog.Shape).Volume, self.dog.Shape.Volume)
        Items.layout(self.other)
        self.assertTouches(stop, self.other)
        self.assertRoughly(self.bb(self.other).Center.x, self.middle(self.dog).x)

    def test02_turned_to_face_it(self):
        """Shared against the part's right side, the part turned so its right faces the dog."""
        stop = Items.shareStop(self.dog, self.other, "+X")
        self.assertCoincide(Items.sideDirection(self.other, "+X"), Vector(0, -1, 0))
        self.assertTouches(stop, self.other)
        self.assertRoughly(self.bb(self.other).YMin, self.dog.Shape.BoundBox.YMax)

    def test03_shared_stop_stays(self):
        """Stops shared stay where they are: more on the owner's side, its part moves. Along the
        back, the side runs right to left."""
        Items.shareStop(self.dog, self.other, "-Y")
        at = FreeCAD.Placement(self.dog.Placement)
        before = self.bb().Center
        dogs = Items.setStops(self.job, [{"side": "+Y", "count": 2}])
        self.assertEqual(dogs[0], self.dog)
        self.assertTrue(self.dog.Placement.isSame(at, 1e-9))
        self.assertRoughly(self.bb().Center.x - before.x, -self.bb().XLength / 4)
        for dog in dogs:
            self.assertTouches(dog)
        # a shared stop is not put elsewhere: it stays
        with self.assertRaises(ValueError):
            Items.setPosition(self.dog, 0)
        self.assertTrue(self.dog.Placement.isSame(at, 1e-9))

    def test04_read_back(self):
        """Shared through setStops, read back as shared on both sides."""
        Items.setStops(self.other, [{"side": "-Y", "share": self.dog}])
        stop = Items.stopsOn(self.other)[0]
        self.assertEqual(stop.Follows, self.dog)
        self.assertEqual(Items.stopsOf(self.other), [{"side": "-Y", "share": self.dog, "count": 1}])
        self.assertEqual(Items.stopsOf(self.job)[0]["sharedWith"], [self.other])
        # set again as it is, kept
        Items.setStops(self.other, [{"side": "-Y", "share": self.dog}])
        self.assertEqual(Items.stopsOn(self.other), [stop])
        # its own dog in its place, no longer shared
        Items.setStops(self.other, [{"side": "-Y", "which": "Dog"}])
        self.assertFalse(PathWorkholding.isShared(self.dog))

    def test05_released(self):
        """The dog taken away, the other Job's stop stays where it is, on its own, as big."""
        stop = Items.shareStop(self.dog, self.other, "-Y")
        at = FreeCAD.Placement(stop.Placement)
        Items.removePiece(self.dog)
        self.doc.recompute()
        self.assertFalse(PathWorkholding.isFollower(stop))
        self.assertEqual(stop.ExpressionEngine, [])
        self.assertTrue(stop.Placement.isSame(at, 1e-9))
        self.assertRoughly(stop.Diameter.Value, 0.75 * 25.4)

    def test06_job_deleted_releases(self):
        """The dog's Job deleted, the other's stop stays where it is."""
        stop = Items.shareStop(self.dog, self.other, "-Y")
        at = FreeCAD.Placement(stop.Placement)
        self.job.Proxy.onDelete(self.job)
        self.doc.removeObject(self.job.Name)
        self.doc.recompute()
        self.assertFalse(PathWorkholding.isFollower(stop))
        self.assertTrue(stop.Placement.isSame(at, 1e-9))

    def test07_simulated_with_the_other_part(self):
        """Each Job sharing the dog simulated with the other's part beyond it."""
        Items.shareStop(self.dog, self.other, "-Y")
        self.assertIn(self.other.Stock, dict(PathJob.workholdingParts(self.job)))
        self.assertIn(self.job.Stock, dict(PathJob.workholdingParts(self.other)))


class TestPathWorkholdingAddPieces(_Stock):
    """Stops and clamps added to a side a few at a time, listed by the edge each is at."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPathWorkholdingAddPieces")
        self.job = self.makeJob("Job")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test00_added_and_spread(self):
        """Added to a side, spread along it with those there, more added later too."""
        dogs = Items.addPieces(self.job, "-X", "Dog", 2)
        self.assertEqual(len(dogs), 2)
        more = Items.addPieces(self.job, "-X", "Dog", 1)
        on = Items.stopsOn(self.job, "-X")
        self.assertEqual(len(on), 3)
        ys = sorted(round(PathWorkholding.placementOf(p).Base.y, 6) for p in on)
        bb = self.bb()
        self.assertRoughly(ys[1], bb.Center.y)
        for stop in on:
            self.assertTouches(stop)
        clamps = Items.addPieces(self.job, "+Y", "EdgeClamp", 2)
        self.assertEqual(Items.clampsOn(self.job, "+Y"), clamps)
        self.assertEqual(more[0].StockSide, "-X")

    def test01_refused(self):
        """Stops on opposite sides, and a side clamp on a side with stops, refused."""
        Items.addPieces(self.job, "-X", "Dog", 2)
        with self.assertRaises(ValueError):
            Items.addPieces(self.job, "+X", "Dog", 1)
        with self.assertRaises(ValueError):
            Items.addPieces(self.job, "-X", "SideClamp", 1)
        Items.addPieces(self.job, "+X", "SideClamp", 1)
        Items.addPieces(self.job, "-Y", "Dog", 1)
        self.assertEqual({p.StockSide for p in Items.stopsOn(self.job)}, {"-X", "-Y"})

    def test02_edge_each_is_at(self):
        """A piece's edge is the one it is at now, wherever it was first put."""
        dog = Items.addPieces(self.job, "-Y", "Dog", 1)[0]
        self.assertEqual(Items.edgeOf(self.job, dog), "-Y")
        bb = self.bb()
        dog.Pinned = True
        dog.Placement.Base = Vector(bb.XMax, bb.Center.y, bb.ZMin)
        self.assertEqual(Items.edgeOf(self.job, dog), "+X")
        table = Items.addTable(self.job)
        self.assertIsNone(Items.edgeOf(self.job, table))

    def test03_side_of_a_picked_face(self):
        """A face or edge of the stock picked is on the part's side it faces; its top is on
        none."""
        shape = self.job.Stock.Shape
        front = min(shape.Faces, key=lambda f: f.BoundBox.Center.y)
        top = max(shape.Faces, key=lambda f: f.BoundBox.Center.z)
        self.assertEqual(Items.sideOfShape(self.job, front), "-Y")
        self.assertEqual(Items.sideOfShape(self.job, front.Edges[0]), "-Y")
        with self.assertRaises(ValueError):
            Items.sideOfShape(self.job, top)

    def test04_dragged_to_another_side(self):
        """Dragged near another side, a stop goes on it, pinned where it was let go; onto a side
        stops cannot go on, it is put back."""
        dogs = Items.addPieces(self.job, "-X", "Dog", 2)
        front = Items.addPieces(self.job, "-Y", "Dog", 1)[0]
        bb = self.bb()
        stay = [FreeCAD.Placement(p.Placement) for p in (dogs[1], front)]
        dogs[0].Placement = FreeCAD.Placement(
            Vector(bb.XMin + 30, bb.YMin - 4, bb.ZMin), FreeCAD.Rotation()
        )
        Items.fromTransform(dogs[0])
        self.assertEqual(dogs[0].StockSide, "-Y")
        self.assertTrue(dogs[0].Pinned)
        self.assertRoughly(PathWorkholding.placementOf(dogs[0]).Base.x, bb.XMin + 30)
        self.assertTouches(dogs[0])
        self.assertEqual([d.SideIndex for d in Items.stopsOn(self.job, "-X")], [0])
        # those already on either side not moved
        for piece, before in zip((dogs[1], front), stay):
            self.assertTrue(piece.Placement.isSame(before, 1e-6))
        before = FreeCAD.Placement(dogs[1].Placement)
        dogs[1].Placement = FreeCAD.Placement(
            Vector(bb.Center.x, bb.YMax + 4, bb.ZMin), FreeCAD.Rotation()
        )
        with self.assertRaises(ValueError):
            Items.fromTransform(dogs[1])
        self.assertEqual(dogs[1].StockSide, "-X")
        self.assertTrue(dogs[1].Placement.isSame(before, 1e-6))

    def test05_side_clamp_turned(self):
        """A side clamp turned pushes at a slant, pulled back to just touch the stock."""
        clamp = Items.addPieces(self.job, "+X", "SideClamp", 1)[0]
        place = PathWorkholding.placementOf(clamp)
        clamp.Placement = FreeCAD.Placement(
            place.Base, place.Rotation.multiply(FreeCAD.Rotation(Vector(0, 0, 1), 20))
        )
        Items.fromTransform(clamp)
        self.assertEqual(clamp.StockSide, "+X")
        self.assertRoughly(clamp.Angle.Value, 20, 1e-6)
        self.doc.recompute()
        self.assertTouches(clamp)

    def test06_clamp_dragged_moves_no_others(self):
        """A clamp dragged to another side moves none of the clamps on either side."""
        moving, left = Items.addPieces(self.job, "-Y", "EdgeClamp", 2)
        right = Items.addPieces(self.job, "+X", "EdgeClamp", 1)[0]
        stay = [FreeCAD.Placement(p.Placement) for p in (left, right)]
        bb = self.bb()
        moving.Placement = FreeCAD.Placement(
            Vector(bb.XMax + 3, bb.YMin + 10, bb.ZMax), moving.Placement.Rotation
        )
        Items.fromTransform(moving)
        self.assertEqual(moving.StockSide, "+X")
        for piece, before in zip((left, right), stay):
            self.assertTrue(piece.Placement.isSame(before, 1e-6))

    def test07_side_clamp_dragged_where_it_meets_the_stock(self):
        """A side clamp turned is dragged from where it meets the stock: moved along its side from
        there, its angle kept; turned there by its Angle, only what is beside the stock pulled
        back."""
        clamp = Items.addPieces(self.job, "+X", "SideClamp", 1)[0]
        Items.setAngle(clamp, 25)
        self.doc.recompute()
        self.assertTouches(clamp)
        contact = Items.contactFrame(self.job, clamp)
        bb = self.bb()
        self.assertRoughly(contact.Base.x, bb.XMax)
        moved = FreeCAD.Placement(contact.Base + Vector(0, 7, 0), contact.Rotation)
        Items.fromTransform(clamp, moved)
        self.assertRoughly(clamp.Angle.Value, 25, 1e-6)
        self.assertRoughly(Items.contactFrame(self.job, clamp).Base.y, contact.Base.y + 7)
        self.doc.recompute()
        self.assertTouches(clamp)

    def test08_side_clamp_turned_at_a_corner(self):
        """A side clamp turned near a corner, its nose past the side's end, moved in until it
        touches the stock's corner, not stopped short where the side would be were it longer."""
        clamp = Items.addPieces(self.job, "+X", "SideClamp", 1)[0]
        bb = self.bb()
        Items.setPosition(clamp, bb.YMax - 5)
        Items.setAngle(clamp, 40)
        self.doc.recompute()
        self.assertTouches(clamp)
        Items.setAngle(clamp, -40)
        self.doc.recompute()
        self.assertTouches(clamp)

    def test09_near_a_corner_stays_on_its_side(self):
        """Dragged near a corner but still across from its side, a piece stays on it; past the
        corner it goes to the other side."""
        dog = Items.addPieces(self.job, "-X", "Dog", 1)[0]
        bb = self.bb()
        # nearer the front's line than the left's, but still across from the left
        near = FreeCAD.Placement(Vector(bb.XMin - 3, bb.YMin + 1, bb.ZMin), FreeCAD.Rotation())
        Items.fromTransform(dog, near)
        self.assertEqual(dog.StockSide, "-X")
        past = FreeCAD.Placement(Vector(bb.XMin + 10, bb.YMin - 3, bb.ZMin), FreeCAD.Rotation())
        Items.fromTransform(dog, past)
        self.assertEqual(dog.StockSide, "-Y")
        # across to the opposite side, still between the front's ends
        back = FreeCAD.Placement(Vector(bb.XMin + 10, bb.YMax + 3, bb.ZMin), FreeCAD.Rotation())
        Items.fromTransform(dog, back)
        self.assertEqual(dog.StockSide, "+Y")

    def test10_kept_between_the_ends(self):
        """Dragged along its side past the stock's end, a piece stops at the end, touching."""
        clamp = Items.addPieces(self.job, "+X", "SideClamp", 1)[0]
        Items.setAngle(clamp, 30)
        bb = self.bb()
        far = FreeCAD.Placement(Vector(bb.XMax + 2, bb.YMax + 80, bb.ZMin), FreeCAD.Rotation())
        Items.fromTransform(clamp, far)
        self.assertEqual(clamp.StockSide, "+X")
        # past the end no further than leaves a quarter of it across from the stock
        y = Items.contactFrame(self.job, clamp).Base.y
        self.assertGreater(y, bb.YMax)
        self.assertLess(y, bb.YMax + clamp.Width.Value)
        self.doc.recompute()
        self.assertTouches(clamp)

    def test11_side_clamp_set_where_typed(self):
        """A side clamp put where X and Y are typed goes as dragged there: onto the side whose
        edge it is on, kept on its own past a corner as near the one as the other."""
        clamp = Items.addPieces(self.job, "+X", "SideClamp", 1)[0]
        bb = self.bb()
        corner = FreeCAD.Placement(Vector(bb.XMax + 5, bb.YMax + 5, bb.ZMin), FreeCAD.Rotation())
        Items.fromTransform(clamp, corner)
        self.assertEqual(clamp.StockSide, "+X")
        # where it was put, partly past the corner, touching
        self.assertRoughly(Items.contactFrame(self.job, clamp).Base.y, bb.YMax + 5)
        self.doc.recompute()
        self.assertTouches(clamp)
        back = FreeCAD.Placement(Vector(bb.XMin + 30, bb.YMax, bb.ZMin), FreeCAD.Rotation())
        Items.fromTransform(clamp, back)
        self.assertEqual(clamp.StockSide, "+Y")
        self.assertRoughly(Items.contactFrame(self.job, clamp).Base.x, bb.XMin + 30)

    def test12_placed_again_when_the_model_grows(self):
        """The model made taller and recomputed: the clamps over its top edge follow it up, with
        nothing of the workholding touched."""
        clamp = Items.addPieces(self.job, "+Y", "EdgeClamp", 1)[0]
        top = self.bb().ZMax
        self.doc.getObject("Box").Height = 35
        self.doc.recompute()
        bb = self.bb()
        self.assertRoughly(bb.ZMax, top + 15)
        self.assertRoughly(PathWorkholding.placementOf(clamp).Base.z, bb.ZMax)
        self.assertTouches(clamp)
