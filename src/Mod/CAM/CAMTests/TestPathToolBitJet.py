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

import FreeCAD
from CAMTests.PathTestUtils import PathTestWithAssets
from Path.Base.Generator import toolchange
from Path.Tool.shape import (
    ToolBitShape,
    ToolBitShapeLaser,
    ToolBitShapePlasma,
    ToolBitShapeWaterjet,
)
from Path.Tool.toolbit import (
    ToolBit,
    ToolBitEndmill,
    ToolBitLaser,
    ToolBitPlasma,
    ToolBitProbe,
    ToolBitWaterjet,
)

# (toolbit class, shape class, shape id, toolhead type)
JET_TYPES = (
    (ToolBitPlasma, ToolBitShapePlasma, "plasma", "plasma"),
    (ToolBitLaser, ToolBitShapeLaser, "laser", "laser"),
    (ToolBitWaterjet, ToolBitShapeWaterjet, "waterjet", "waterjet"),
)


class TestPathToolBitJet(PathTestWithAssets):
    """Plasma, laser and waterjet tool bits."""

    @staticmethod
    def _make(toolbit_class, shape_class, shape_id):
        return toolbit_class(shape_class(shape_id))

    def testDirectSubclassRegistration(self):
        """The jet classes must be *direct* subclasses of ToolBit/ToolBitShape.

        Shape-to-class lookup walks __subclasses__(), which is only one level
        deep, so an intermediate base class would make these types invisible.
        """
        toolbit_classes = ToolBit.__subclasses__()
        shape_names = [c.name for c in ToolBitShape.__subclasses__()]
        for toolbit_class, shape_class, _, _ in JET_TYPES:
            self.assertIn(toolbit_class, toolbit_classes)
            self.assertIn(shape_class.name, shape_names)

    def testShapeLookupByNameAliasAndSubtype(self):
        """Names, aliases and subtypes all resolve to the parent shape class."""
        for name in ("plasma", "torch", "fine_cut"):
            self.assertIs(ToolBitShape.get_subclass_by_name(name), ToolBitShapePlasma)
        for name in ("laser", "co2", "diode", "fiber"):
            self.assertIs(ToolBitShape.get_subclass_by_name(name), ToolBitShapeLaser)
        for name in ("waterjet", "abrasive", "pure_water"):
            self.assertIs(ToolBitShape.get_subclass_by_name(name), ToolBitShapeWaterjet)

    def testToolheadType(self):
        """Each jet type reports the machine toolhead it mounts in."""
        for toolbit_class, shape_class, shape_id, toolhead in JET_TYPES:
            toolbit = self._make(toolbit_class, shape_class, shape_id)
            self.assertEqual(toolbit.get_toolhead_type(), toolhead)

    def testToolheadTypeMatchesMachineEnum(self):
        """The strings must be valid Machine ToolheadType values."""
        from Machine.models.machine import ToolheadType

        for _, _, _, toolhead in JET_TYPES:
            self.assertEqual(ToolheadType(toolhead).value, toolhead)

    def testSpindleToolsUnaffected(self):
        """Spindle-mounted tools keep the inherited default."""
        for toolbit in (
            self.assets.get("toolbit://5mm_Endmill"),
            ToolBitEndmill(self.assets.get("toolbitshape://endmill")),
            ToolBitProbe(self.assets.get("toolbitshape://probe")),
        ):
            self.assertEqual(toolbit.get_toolhead_type(), "rotary")

    def testNeverRotates(self):
        """A jet has no spindle; it must never be told to turn."""
        for toolbit_class, shape_class, shape_id, _ in JET_TYPES:
            toolbit = self._make(toolbit_class, shape_class, shape_id)
            self.assertFalse(toolbit.can_rotate())
            self.assertEqual(
                toolbit.get_spindle_direction(),
                toolchange.SpindleDirection.OFF,
            )
            self.assertEqual(toolbit.obj.SpindleDirection, "None")

    def testMeaninglessPropertiesHidden(self):
        """Spindle direction and cutter material are suppressed, not shown blank."""
        for toolbit_class, shape_class, shape_id, _ in JET_TYPES:
            obj = self._make(toolbit_class, shape_class, shape_id).obj
            # DetachedDocumentObject returns editor mode as an int: 1=RO, 2=Hidden
            self.assertEqual(obj.getEditorMode("SpindleDirection"), 2)
            self.assertEqual(obj.getEditorMode("Material"), 2)

    def testNoChipload(self):
        """A jet removes no chips, so it must not carry CuttingToolMixin state."""
        for toolbit_class, shape_class, shape_id, _ in JET_TYPES:
            obj = self._make(toolbit_class, shape_class, shape_id).obj
            self.assertFalse(hasattr(obj, "Chipload"))

    def testDiameterMirrorsKerf(self):
        """Operations offset by Tool.Diameter, which for a jet is the kerf."""
        for toolbit_class, shape_class, shape_id, _ in JET_TYPES:
            toolbit = self._make(toolbit_class, shape_class, shape_id)
            obj = toolbit.obj

            self.assertEqual(obj.Diameter, obj.KerfWidth)
            # Diameter is derived, so it is kept out of the editor's groups
            self.assertEqual(obj.getGroupOfProperty("Diameter"), "Base")
            self.assertNotIn("Diameter", toolbit._get_props(("Shape", "Attributes")))

            toolbit.set_kerf_width(FreeCAD.Units.Quantity("2.4 mm"))
            self.assertEqual(obj.Diameter, obj.KerfWidth)
            self.assertAlmostEqual(obj.Diameter.Value, 2.4)

            # set_diameter is redirected to the kerf rather than silently
            # writing a value that the next sync would discard
            toolbit.set_diameter(FreeCAD.Units.Quantity("0.9 mm"))
            self.assertAlmostEqual(obj.KerfWidth.Value, 0.9)
            self.assertAlmostEqual(obj.Diameter.Value, 0.9)

    def testKerfSurvivesLibraryRoundTrip(self):
        """A .fctb load must land the kerf in the Diameter operations read.

        The library builds toolbits detached, and DetachedDocumentObject does
        not dispatch onChanged(), so this exercises the path that regressed
        during development.
        """
        for toolbit_class, _, shape_id, _ in JET_TYPES:
            toolbit = ToolBit.from_dict(
                {
                    "shape": shape_id,
                    "shape-type": shape_id,
                    "name": f"test {shape_id}",
                    "attribute": {"KerfWidth": "2.25 mm"},
                }
            )
            self.assertIsInstance(toolbit, toolbit_class)
            self.assertAlmostEqual(toolbit.obj.KerfWidth.Value, 2.25)
            self.assertAlmostEqual(toolbit.obj.Diameter.Value, 2.25)

            attrs = toolbit.to_dict()
            self.assertEqual(attrs["shape-type"], toolbit_class.SHAPE_CLASS.name)
            self.assertEqual(attrs["parameter"]["KerfWidth"], "2.25 mm")
            # derived, so it is not written to the .fctb; it is re-synced on load
            self.assertNotIn("Diameter", attrs["parameter"])

    def testProcessDefaults(self):
        """Every jet property ships with a usable value, not None."""
        for toolbit_class, shape_class, shape_id, _ in JET_TYPES:
            obj = self._make(toolbit_class, shape_class, shape_id).obj
            for prop in ("KerfWidth", "PierceHeight", "CutHeight", "PierceTime", "Pressure"):
                self.assertTrue(hasattr(obj, prop), f"{shape_id} missing {prop}")
                self.assertIsNotNone(getattr(obj, prop), f"{shape_id}.{prop} is None")
            self.assertGreater(obj.Pressure.Value, 0.0, f"{shape_id} has no default pressure")

    def testTypeSpecificProperties(self):
        """Each type carries only its own process values."""
        plasma = self._make(ToolBitPlasma, ToolBitShapePlasma, "plasma").obj
        self.assertAlmostEqual(plasma.Amperage, 45.0)
        self.assertAlmostEqual(plasma.ArcVoltage, 120.0)
        self.assertEqual(plasma.AssistGas, "Air")
        self.assertFalse(hasattr(plasma, "CutPower"))
        self.assertFalse(hasattr(plasma, "AbrasiveType"))

        laser = self._make(ToolBitLaser, ToolBitShapeLaser, "laser").obj
        self.assertEqual(laser.CutPower, 100)
        self.assertEqual(laser.PiercePower, 100)
        self.assertEqual(laser.PulseDutyCycle, 100)
        self.assertFalse(hasattr(laser, "Amperage"))
        self.assertFalse(hasattr(laser, "AbrasiveType"))

        waterjet = self._make(ToolBitWaterjet, ToolBitShapeWaterjet, "waterjet").obj
        self.assertAlmostEqual(waterjet.AbrasiveFlowRate, 350.0)
        self.assertEqual(waterjet.AbrasiveType, "Garnet 80")
        self.assertFalse(hasattr(waterjet, "Amperage"))
        self.assertFalse(hasattr(waterjet, "CutPower"))

    def testEveryEditablePropertyGetsAnEditor(self):
        """Properties shown in the editor must not fall through to a read-only label.

        DocumentObjectEditorWidget dispatches on the property's Python value
        type; anything it does not recognise is rendered as a QLabel and cannot
        be edited. Quantity/int/bool/float/enumeration are the editable cases.
        """
        for toolbit_class, shape_class, shape_id, _ in JET_TYPES:
            toolbit = self._make(toolbit_class, shape_class, shape_id)
            obj = toolbit.obj
            for name in toolbit._get_props(("Shape", "Attributes")):
                value = obj.getPropertyByName(name)
                editable = isinstance(value, (FreeCAD.Units.Quantity, bool, int, float)) or (
                    obj.getTypeIdOfProperty(name) == "App::PropertyEnumeration"
                )
                self.assertTrue(
                    editable,
                    f"{shape_id}.{name} ({obj.getTypeIdOfProperty(name)}) would render "
                    f"as a read-only label",
                )

    def testQuantitiesSurviveReloadAsQuantities(self):
        """Unit-bearing properties must come back from a .fctb as Quantities.

        DetachedDocumentObject converts strings back to Quantity based on the
        declared property type. When a type was missing from that set the value
        returned as a bare str: unit handling broke silently and the property
        editor, which dispatches on the value's Python type, rendered it as an
        uneditable label. Length happened to be covered; Time, Pressure and the
        electrical types were not.
        """
        for toolbit_class, _, shape_id, _ in JET_TYPES:
            fresh = ToolBit.from_shape_id(shape_id)
            reloaded = ToolBit.from_dict(fresh.to_dict())
            for name in reloaded._get_props(("Shape", "Attributes")):
                prop_type = reloaded.obj.getTypeIdOfProperty(name)
                if not isinstance(fresh.obj.getPropertyByName(name), FreeCAD.Units.Quantity):
                    continue
                self.assertIsInstance(
                    reloaded.obj.getPropertyByName(name),
                    FreeCAD.Units.Quantity,
                    f"{shape_id}.{name} ({prop_type}) came back as "
                    f"{type(reloaded.obj.getPropertyByName(name)).__name__}, not Quantity",
                )

    def testEveryEditablePropertySurvivesReload(self):
        """The editor check must hold for a reloaded tool, not just a fresh one."""
        for toolbit_class, _, shape_id, _ in JET_TYPES:
            reloaded = ToolBit.from_dict(ToolBit.from_shape_id(shape_id).to_dict())
            obj = reloaded.obj
            for name in reloaded._get_props(("Shape", "Attributes")):
                value = obj.getPropertyByName(name)
                editable = isinstance(value, (FreeCAD.Units.Quantity, bool, int, float)) or (
                    obj.getTypeIdOfProperty(name) == "App::PropertyEnumeration"
                )
                self.assertTrue(
                    editable,
                    f"after reload, {shape_id}.{name} "
                    f"({obj.getTypeIdOfProperty(name)}) would render as a read-only label",
                )

    def testAmpsAndVoltsStayUnitless(self):
        """Amperage/ArcVoltage must not be electrical Quantity types.

        Some unit schemas render electric potential as the raw derived unit
        "mm^2*kg/(s^3*A)", which Gui::QuantitySpinBox cannot round-trip through
        the editor. Neither value has a conversion worth having, so both stay
        plain floats and rely on FloatPropertyEditorWidget.
        """
        plasma = self._make(ToolBitPlasma, ToolBitShapePlasma, "plasma").obj
        for name in ("Amperage", "ArcVoltage"):
            self.assertEqual(plasma.getTypeIdOfProperty(name), "App::PropertyFloat")
            self.assertIsInstance(plasma.getPropertyByName(name), float)

    def testShallowLoadPreservesValueTypes(self):
        """Shallow loading must not turn numbers into strings.

        The library browser loads assets shallow. In that mode the shape is
        built from every key in the .fctb, including Attributes-group ones that
        are not in the schema and have no recorded type; those used to be
        coerced to str and the str propagated back onto the ToolBit.
        """
        for toolbit_class, _, shape_id, _ in JET_TYPES:
            attrs = ToolBit.from_shape_id(shape_id).to_dict()
            for shallow in (False, True):
                toolbit = ToolBit.from_dict(dict(attrs), shallow=shallow)
                for name in toolbit._get_props(("Shape", "Attributes")):
                    value = toolbit.obj.getPropertyByName(name)
                    declared = toolbit.obj.getTypeIdOfProperty(name)
                    if declared == "App::PropertyFloat":
                        self.assertIsInstance(
                            value,
                            float,
                            f"shallow={shallow}: {shape_id}.{name} is "
                            f"{type(value).__name__}, expected float",
                        )
                    elif declared in ("App::PropertyLength", "App::PropertyTime"):
                        self.assertIsInstance(
                            value,
                            FreeCAD.Units.Quantity,
                            f"shallow={shallow}: {shape_id}.{name} is "
                            f"{type(value).__name__}, expected Quantity",
                        )

    def testSummaryNeverRaises(self):
        """summary is rendered for every library row and must not throw.

        A ValueError here propagates out of the browser's refresh and takes the
        whole tool list down, so it is worth pinning for both load modes.
        """
        for toolbit_class, _, shape_id, _ in JET_TYPES:
            attrs = ToolBit.from_shape_id(shape_id).to_dict()
            for shallow in (False, True):
                toolbit = ToolBit.from_dict(dict(attrs), shallow=shallow)
                self.assertTrue(toolbit.summary)
            # even with a value of the wrong type, summary degrades rather than raising
            toolbit = ToolBit.from_shape_id(shape_id)
            for name in ("Amperage", "CutPower", "AbrasiveFlowRate"):
                if hasattr(toolbit.obj, name):
                    toolbit.obj.setPropertyByName(name, "not a number")
            self.assertTrue(toolbit.summary)

    def testKerfEditOnAttachedObjectFlowsToDiameter(self):
        """Editing KerfWidth in FreeCAD's Properties editor must update Diameter.

        Users edit toolbit properties directly in the Data tab of an attached
        toolbit. That is a plain attribute set on a real DocumentObject, so it
        goes through onChanged() rather than any ToolBit API.
        """
        doc = FreeCAD.newDocument("TestJetAttached")
        try:
            for toolbit_class, _, shape_id, _ in JET_TYPES:
                toolbit = ToolBit.from_shape_id(shape_id)
                self.assertIsInstance(toolbit, toolbit_class)
                toolbit.attach_to_doc(doc)
                doc.recompute()
                obj = toolbit.obj

                self.assertTrue(hasattr(obj, "Diameter"), shape_id)
                self.assertEqual(obj.getGroupOfProperty("Diameter"), "Base", shape_id)

                for kerf in ("2.5 mm", "0.9 mm", "1.4 mm"):
                    obj.KerfWidth = FreeCAD.Units.Quantity(kerf)
                    self.assertEqual(
                        obj.Diameter,
                        obj.KerfWidth,
                        f"{shape_id}: Diameter did not follow a Properties-editor "
                        f"edit to {kerf}",
                    )
                doc.recompute()
                self.assertEqual(obj.Diameter, obj.KerfWidth, shape_id)
        finally:
            FreeCAD.closeDocument(doc.Name)

    def testFocusOffsetAcceptsNegative(self):
        """Focusing below the surface is normal, so the property must be signed."""
        laser = self._make(ToolBitLaser, ToolBitShapeLaser, "laser").obj
        laser.FocusOffset = FreeCAD.Units.Quantity("-1.5 mm")
        self.assertAlmostEqual(laser.FocusOffset.Value, -1.5)

    def testSummary(self):
        """Each type produces a non-empty, type-specific summary line."""
        for toolbit_class, shape_class, shape_id, _ in JET_TYPES:
            summary = self._make(toolbit_class, shape_class, shape_id).summary
            self.assertTrue(summary)
            self.assertIn("kerf", summary)
