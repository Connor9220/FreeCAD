# -*- coding: utf-8 -*-
# ***************************************************************************
# *   Copyright (c) 2025 FreeCAD Contributors                               *
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

import FreeCAD
import Path
from CAMTests.PathTestUtils import PathTestBase


class TestPathCommandAnnotations(PathTestBase):
    """Test Path.Command annotations functionality."""

    def test00(self):
        """Test basic annotations property access."""
        # Create empty command
        c = Path.Command()
        self.assertIsInstance(c, Path.Command)

        # Test empty annotations
        self.assertEqual(c.Annotations, {})

        # Set annotations via property
        c.Annotations = {"tool": "tap", "material": "steel"}
        self.assertEqual(c.Annotations, {"tool": "tap", "material": "steel"})

        # Test individual annotation access
        self.assertEqual(c.Annotations.get("tool"), "tap")
        self.assertEqual(c.Annotations.get("material"), "steel")
        self.assertIsNone(c.Annotations.get("nonexistent"))

    def test01(self):
        """Test annotations with command creation."""
        # Create command with parameters
        c = Path.Command("G84", {"X": 10, "Y": 20, "Z": -5})

        # Set annotations
        c.Annotations = {"operation": "tapping", "thread": "M6"}

        # Verify command still works normally
        self.assertEqual(c.Name, "G84")
        self.assertEqual(c.Parameters["X"], 10.0)
        self.assertEqual(c.Parameters["Y"], 20.0)
        self.assertEqual(c.Parameters["Z"], -5.0)

        # Verify annotations are preserved
        self.assertEqual(c.Annotations["operation"], "tapping")
        self.assertEqual(c.Annotations["thread"], "M6")

    def test02(self):
        """Test addAnnotations method with dictionary input."""
        c = Path.Command("G1", {"X": 5, "Y": 5})

        # Test method chaining with dictionary
        result = c.addAnnotations({"note": "test note", "tool": "end mill"})

        # Verify method returns the command object for chaining
        self.assertIs(result, c)

        # Verify annotations were set
        self.assertEqual(c.Annotations["note"], "test note")
        self.assertEqual(c.Annotations["tool"], "end mill")

    def test03(self):
        """Test addAnnotations method with string input."""
        c = Path.Command("G2", {"X": 15, "Y": 15})

        # Test method chaining with string
        result = c.addAnnotations("xyz:abc test:1234 operation:milling")

        # Verify method returns the command object for chaining
        self.assertIs(result, c)

        # Verify annotations were parsed and set correctly
        self.assertEqual(c.Annotations["xyz"], "abc")
        self.assertEqual(c.Annotations["test"], "1234")
        self.assertEqual(c.Annotations["operation"], "milling")

    def test04(self):
        """Test annotations update behavior."""
        c = Path.Command("G0", {"Z": 20})

        # Set initial annotations
        c.Annotations = {"initial": "value"}
        self.assertEqual(c.Annotations, {"initial": "value"})

        # Add more annotations - should merge/update
        c.addAnnotations({"additional": "value2", "initial": "updated"})

        expected = {"initial": "updated", "additional": "value2"}
        self.assertEqual(c.Annotations, expected)

    def test05(self):
        """Test method chaining in fluent interface."""
        # Test the fluent interface - create command and set annotations in one line
        c = Path.Command("G84", {"X": 10, "Y": 10, "Z": 0.0}).addAnnotations("thread:M8 depth:15mm")

        # Verify command parameters
        self.assertEqual(c.Name, "G84")
        self.assertEqual(c.Parameters["X"], 10.0)
        self.assertEqual(c.Parameters["Y"], 10.0)
        self.assertEqual(c.Parameters["Z"], 0.0)

        # Verify annotations
        self.assertEqual(c.Annotations["thread"], "M8")
        self.assertEqual(c.Annotations["depth"], "15mm")

    def test06(self):
        """Test annotations with special characters and edge cases."""
        c = Path.Command("G1")

        # Test annotations with special characters
        c.Annotations = {
            "unicode": "café",
            "numbers": "123.45",
            "empty": "",
            "spaces": "value with spaces",
        }

        self.assertEqual(c.Annotations["unicode"], "café")
        self.assertEqual(c.Annotations["numbers"], "123.45")
        self.assertEqual(c.Annotations["empty"], "")
        self.assertEqual(c.Annotations["spaces"], "value with spaces")

    def test07(self):
        """Test annotations persistence through operations."""
        c = Path.Command("G1", {"X": 10, "Y": 20})
        c.Annotations = {"persistent": "value"}

        # Test that annotations survive parameter changes
        c.Parameters = {"X": 30, "Y": 40}
        self.assertEqual(c.Annotations["persistent"], "value")

        # Test that annotations survive name changes
        c.Name = "G2"
        self.assertEqual(c.Annotations["persistent"], "value")

    def test08(self):
        """Test multiple annotation update methods."""
        c = Path.Command()

        # Method 1: Property assignment
        c.Annotations = {"method1": "property"}

        # Method 2: addAnnotations with dict
        c.addAnnotations({"method2": "dict"})

        # Method 3: addAnnotations with string
        c.addAnnotations("method3:string")

        # Verify all methods worked and annotations are merged
        expected = {"method1": "property", "method2": "dict", "method3": "string"}
        self.assertEqual(c.Annotations, expected)

    def test09(self):
        """Test string parsing edge cases."""
        c = Path.Command()

        # Test various string formats
        c.addAnnotations("simple:value")
        self.assertEqual(c.Annotations["simple"], "value")

        # Test multiple key:value pairs
        c.Annotations = {}  # Clear first
        c.addAnnotations("key1:val1 key2:val2 key3:val3")
        expected = {"key1": "val1", "key2": "val2", "key3": "val3"}
        self.assertEqual(c.Annotations, expected)

        # Test that malformed strings are ignored
        c.Annotations = {}  # Clear first
        c.addAnnotations("valid:value invalid_no_colon")
        self.assertEqual(c.Annotations, {"valid": "value"})

    def test10(self):
        """Test annotations in gcode context."""
        # Create a tapping command with annotations
        c = Path.Command(
            "G84", {"X": 25.0, "Y": 30.0, "Z": -10.0, "R": 2.0, "P": 0.5, "F": 100.0}
        ).addAnnotations("operation:tapping thread:M6x1.0 depth:10mm")

        # Verify gcode output is unaffected by annotations
        gcode = c.toGCode()
        self.assertIn("G84", gcode)
        self.assertIn("X25", gcode)
        self.assertIn("Y30", gcode)
        self.assertIn("Z-10", gcode)

        # Verify annotations are preserved
        self.assertEqual(c.Annotations["operation"], "tapping")
        self.assertEqual(c.Annotations["thread"], "M6x1.0")
        self.assertEqual(c.Annotations["depth"], "10mm")

        # Annotations should not appear in gcode output
        self.assertNotIn("operation", gcode)
        self.assertNotIn("tapping", gcode)
        self.assertNotIn("thread", gcode)
