# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026 The FreeCAD project association AISBL              *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public     *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

import json
import os
import pathlib
import tempfile
import unittest

import FreeCAD

from Path.Tool.assets import AssetManager, FileStore
from Path.Tool.camassets import asset_mapping, builtin_asset_mapping
from Path.Tool.holder import ToolHolder, ToolHolderSerializer, available_holders
from Path.Tool.toolbit import ToolBit
from CAMTests.PathTestUtils import PathTestWithAssets


class TestPathToolHolder(unittest.TestCase):
    """The tool holders FreeCAD ships, and those a user adds to the CAM asset folder."""

    tool_dir = pathlib.Path(os.path.realpath(__file__)).parent.parent / "Tools"

    def setUp(self):
        self.local_dir = tempfile.TemporaryDirectory()
        self.assets = AssetManager()
        self.assets.register_store(
            FileStore(
                name="local", base_dir=pathlib.Path(self.local_dir.name), mapping=asset_mapping
            )
        )
        self.assets.register_store(
            FileStore(name="builtin", base_dir=self.tool_dir, mapping=builtin_asset_mapping)
        )
        self.assets.register_asset(ToolHolder, ToolHolderSerializer)

    def tearDown(self):
        self.local_dir.cleanup()

    def write_local(self, id, data):
        folder = pathlib.Path(self.local_dir.name) / "Tools" / "Holder"
        folder.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data)
        (folder / f"{id}.fcholder").write_text(text)

    def test00_builtin_holders_load(self):
        """Every holder that ships with FreeCAD reads, and the ER series is all there."""
        holders = available_holders(self.assets)
        for size in ("ER11", "ER16", "ER20", "ER25", "ER32", "ER40", "ER50"):
            self.assertIn(f"{size}_Standard", holders)
        for size in ("ER8", "ER11", "ER16", "ER20", "ER25"):
            self.assertIn(f"{size}_Mini", holders)
        self.assertTrue(any(id.startswith("Router_Nut_") for id in holders))
        for id, holder in holders.items():
            self.assertEqual(holder.get_id(), id)
            self.assertGreater(holder.height, 0, id)
            self.assertGreater(holder.diameter, 0, id)

    def test01_er32_size(self):
        """A standard ER32 nut is 50 mm across and reaches 22.5 mm above its face."""
        holder = self.assets.get("toolholder://ER32_Standard", store="builtin")
        self.assertEqual(holder.label, "ER32 nut, standard")
        self.assertEqual(holder.collet, "ER32")
        self.assertAlmostEqual(holder.diameter, 50.0)
        self.assertAlmostEqual(holder.height, 22.5)

    def test02_mini_is_slimmer(self):
        """A mini nut is slimmer than the standard nut for the same collet."""
        holders = available_holders(self.assets)
        for size in ("ER11", "ER16", "ER20", "ER25"):
            self.assertLess(
                holders[f"{size}_Mini"].diameter, holders[f"{size}_Standard"].diameter, size
            )

    def test03_local_holder_replaces_builtin(self):
        """A holder in the CAM asset folder replaces the built-in one of the same name, and
        one of its own is added to them."""
        self.write_local(
            "ER32_Standard",
            {"name": "My ER32 nut", "profile": [[0, 0], [26, 0], [26, 24], [0, 24]]},
        )
        self.write_local(
            "Shrink_Fit_6mm", {"name": "Shrink fit, 6 mm", "profile": [[0, 0], [10, 0], [0, 40]]}
        )
        holders = available_holders(self.assets)
        self.assertEqual(holders["ER32_Standard"].label, "My ER32 nut")
        self.assertAlmostEqual(holders["ER32_Standard"].diameter, 52.0)
        self.assertIn("Shrink_Fit_6mm", holders)
        self.assertIn("ER16_Standard", holders)

    def test04_unreadable_local_holder_skipped(self):
        """A holder that cannot be read is left out; the rest are still there."""
        self.write_local("Broken", "{ not json")
        self.write_local("Upside_Down", {"name": "Bad", "profile": [[0, 0], [-5, 10]]})
        holders = available_holders(self.assets)
        self.assertNotIn("Broken", holders)
        self.assertNotIn("Upside_Down", holders)
        self.assertIn("ER32_Standard", holders)

    def test05_round_trip(self):
        """A holder written out reads back the same."""
        holder = ToolHolder(
            "Test_Nut",
            "Test nut",
            [[0, 0], [9, 0], [10, 1], [10, 15], [0, 15]],
            collet="ER16",
            notes="A note",
            source="Measured",
        )
        data = ToolHolderSerializer.serialize(holder)
        again = ToolHolderSerializer.deserialize(data, "Test_Nut", None)
        self.assertEqual(again.to_dict(), holder.to_dict())
        self.assertEqual(json.loads(data)["profile"][2], [10.0, 1.0])

    def test06_outline_checked(self):
        """An outline needs two points, none below the face or inside the axis, and is in mm."""
        with self.assertRaises(ValueError):
            ToolHolder("A", "A", [[0, 0]])
        with self.assertRaises(ValueError):
            ToolHolder("B", "B", [[0, 0], [5, -1]])
        with self.assertRaises(ValueError):
            ToolHolder("C", "C", [[0, 0], [-5, 1]])
        with self.assertRaises(ValueError):
            ToolHolder.from_dict("D", {"units": "in", "profile": [[0, 0], [1, 1]]})


class TestPathToolBitHolder(PathTestWithAssets):
    """A bit set in a holder, sticking out of it."""

    def bit(self, **parameters):
        attrs = self.assets.get("toolbit://5mm_Endmill").to_dict()
        attrs["parameter"].update(parameters)
        return ToolBit.from_dict(attrs)

    def test10_bit_in_no_holder(self):
        """A bit in no holder has none, sticks out by nothing, and saves as before."""
        bit = self.bit()
        self.assertIsNone(bit.get_holder_id())
        self.assertIsNone(bit.get_holder(self.assets))
        self.assertEqual(bit.get_stickout().Value, 0)
        self.assertNotIn("Holder", bit.to_dict()["parameter"])
        self.assertNotIn("Stickout", bit.to_dict()["parameter"])

    def test11_bit_in_holder(self):
        """A bit's holder and stickout load, find the holder, and save again."""
        bit = self.bit(Holder="ER20_Standard", Stickout="1.2500 in")
        self.assertEqual(bit.get_holder_id(), "ER20_Standard")
        self.assertAlmostEqual(bit.get_stickout().getValueAs("mm").Value, 31.75)
        self.assertAlmostEqual(bit.get_holder(self.assets).diameter, 35.0)
        params = bit.to_dict()["parameter"]
        self.assertEqual(params["Holder"], "ER20_Standard")
        again = ToolBit.from_dict(bit.to_dict())
        self.assertEqual(again.get_holder_id(), "ER20_Standard")
        self.assertAlmostEqual(again.get_stickout().getValueAs("mm").Value, 31.75)

    def test12_unknown_holder_kept(self):
        """A holder that is not here is kept by its id, not lost on saving."""
        bit = self.bit(Holder="Shop_Shrink_Fit")
        self.assertEqual(bit.get_holder_id(), "Shop_Shrink_Fit")
        self.assertIsNone(bit.get_holder(self.assets))
        self.assertEqual(bit.to_dict()["parameter"]["Holder"], "Shop_Shrink_Fit")

    def test13_change_holder(self):
        """A bit can be moved to another holder, and out of one."""
        bit = self.bit(Holder="ER20_Standard")
        bit.set_holder_id("ER11_Mini")
        self.assertEqual(bit.get_holder_id(), "ER11_Mini")
        bit.set_holder_id(None)
        self.assertIsNone(bit.get_holder_id())
        self.assertNotIn("Holder", bit.to_dict()["parameter"])

    def test15_stickout_in_bit_units(self):
        """Stickout saves in the bit's units, also for a bit whose file does not name them."""
        attrs = self.assets.get("toolbit://5mm_Endmill").to_dict()
        attrs["parameter"] = {
            "Diameter": "0.1250 in",
            "Length": "2.5000 in",
            "ShankDiameter": "0.1250 in",
            "CuttingEdgeHeight": "0.5000 in",
            "Stickout": "1.3650 in",
        }
        bit = ToolBit.from_dict(attrs)
        self.assertEqual(bit.obj.Units, "Imperial")
        self.assertEqual(bit.to_dict()["parameter"]["Stickout"], "1.3650 in")
        bit.obj.Units = "Metric"
        self.assertEqual(bit.to_dict()["parameter"]["Stickout"], "34.671 mm")

    def test14_stickout_in_document(self):
        """A bit put in a document keeps its holder and stickout."""
        doc = FreeCAD.newDocument("TestToolBitHolder")
        try:
            bit = self.bit(Holder="ER32_Standard", Stickout="40 mm")
            obj = bit.attach_to_doc(doc)
            self.assertEqual(obj.Holder, "ER32_Standard")
            self.assertAlmostEqual(obj.Stickout.Value, 40.0)
            self.assertEqual(obj.Proxy.get_holder_id(), "ER32_Standard")
        finally:
            FreeCAD.closeDocument(doc.Name)
