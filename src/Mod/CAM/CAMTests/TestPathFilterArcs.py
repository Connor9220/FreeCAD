# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2024 FreeCAD Project                                    *
# *                                                                         *
# *   This file is part of the FreeCAD CAD program.                         *
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

"""
Unit tests for Path.filterArcs C++ implementation
"""

import FreeCAD
import Path
import Path.Geom
import unittest


class TestPathFilterArcs(unittest.TestCase):
    """Test Path.filterArcs functionality"""

    def test_filterArcs_basic(self):
        """Test basic filterArcs functionality"""
        # Create a path with a very shallow arc (should be converted to G1)
        # Arc from (0,0) to (100,0) with center at (50, 5000)
        # This creates a very large radius (~5000) and shallow deflection
        # Center offset from start: I=50, J=5000
        cmd1 = Path.Command("G0", {"X": 0, "Y": 0, "Z": 0})
        cmd2 = Path.Command("G2", {"X": 100, "Y": 0, "Z": 0, "I": 50, "J": 5000})
        cmd3 = Path.Command("G1", {"X": 100, "Y": 100, "Z": 0})

        path = Path.Path([cmd1, cmd2, cmd3])

        # Apply filterArcs with a deflection tolerance of 1.0
        # The shallow arc should be converted to a straight line
        path.filterArcs(1.0)

        # Check that the arc was converted to G1
        self.assertEqual(path.Commands[1].Name, "G1", "Arc should be converted to G1")

    def test_filterArcs_preserve_sharp(self):
        """Test that sharp arcs are preserved"""
        # Create a path with a sharp arc (should NOT be converted)
        cmd1 = Path.Command("G0", {"X": 0, "Y": 0, "Z": 0})
        cmd2 = Path.Command("G2", {"X": 10, "Y": 0, "Z": 0, "I": 5, "J": 0})  # Tighter arc

        path = Path.Path([cmd1, cmd2])

        # Apply filterArcs with a small deflection tolerance
        path.filterArcs(0.01)

        # Check that the arc was preserved
        self.assertEqual(path.Commands[1].Name, "G2", "Sharp arc should be preserved")

    def test_filterArcs_from_geom(self):
        """Test filterArcs through Path.Geom wrapper"""
        # Create commands list with shallow arc (same geometry as basic test)
        cmds = [
            Path.Command("G0", {"X": 0, "Y": 0, "Z": 0}),
            Path.Command("G2", {"X": 100, "Y": 0, "Z": 0, "I": 50, "J": 5000}),
        ]

        # Call through wrapper
        result = Path.Geom.filterArcs(cmds, 1.0)

        self.assertEqual(result[1].Name, "G1", "Geom wrapper should convert arc to G1")

    def test_filterArcs(self):
        """Test arc filtering"""
        # Create a path with a shallow arc
        cmd1 = Path.Command("G0", {"X": 0, "Y": 0, "Z": 0})
        cmd2 = Path.Command("G2", {"X": 200, "Y": 0, "Z": 0, "I": 100, "J": 0})

        path = Path.Path([cmd1, cmd2])

        # Enable filtering
        path.setFilterArcs(True)
        self.assertTrue(path.getFilterArcs(), "Filtering should be enabled")

        # Trigger recalculation by modifying path
        path.addCommands([Path.Command("G1", {"X": 300, "Y": 0, "Z": 0})])

        # Disable filtering
        path.setFilterArcs(False)
        self.assertFalse(path.getFilterArcs(), "Filtering should be disabled")

    def test_filterArcs_conversion(self):
        """Test that filtering actually converts shallow arcs"""
        # Create a path with an EXTREMELY shallow arc (deflection < 0.01 default threshold)
        # Arc from (0,0) to (10,0) with very large radius gives tiny deflection
        cmd1 = Path.Command("G0", {"X": 0, "Y": 0, "Z": 0})
        cmd2 = Path.Command("G2", {"X": 10, "Y": 0, "Z": 0, "I": 5, "J": 50000})

        path = Path.Path([cmd1, cmd2])

        # Verify arc exists initially
        self.assertEqual(path.Commands[1].Name, "G2", "Should start with G2 arc")

        # Enable filtering and trigger recalculation
        path.setFilterArcs(True)
        path.addCommands([Path.Command("G1", {"X": 10, "Y": 10, "Z": 0})])

        # The extremely shallow arc should now be converted to G1 by filtering
        # (deflection is ~0.0001, well below default threshold of 0.01)
        self.assertEqual(path.Commands[1].Name, "G1", "Shallow arc should be converted to G1")

    def test_filterArcs_fromShapes(self):
        """Test that Path.fromShapes enables arc filtering"""
        import Part

        # Create a simple rectangular wire (will generate moves, potentially with arcs)
        p1 = FreeCAD.Vector(0, 0, 0)
        p2 = FreeCAD.Vector(100, 0, 0)
        line = Part.LineSegment(p1, p2).toShape()

        # fromShapes should return a path with filtering enabled
        result = Path.fromShapes([line])

        if isinstance(result, tuple):
            path = result[0]
        else:
            path = result

        # Check that filtering is enabled by C++ fromShapes
        self.assertTrue(
            path.getFilterArcs(), "Path.fromShapes should enable arc filtering"
        )
