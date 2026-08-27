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
from PySide.QtCore import QT_TRANSLATE_NOOP


def format_number(value, default: str = "?") -> str:
    """
    Render a value that should be numeric but may not be.

    Shallow-loaded toolbits can carry a parameter as a string, and summary
    strings are built for every row of the library browser, so a format spec
    like ``:g`` applied straight to the raw value can take the whole browser
    down with a ValueError. This never raises.
    """
    if value is None:
        return default
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


class JetToolBitMixin:
    """
    Mixin for non-contact "jet" cutting tools: plasma, laser and waterjet.

    Carries the process values that are shared by all three and that shape the
    toolpath, in the same way CuttingToolMixin carries Chipload. These live in
    the "Attributes" group rather than the shape schema because they describe
    the process, not the geometry of the body drawn in the .fcstd.

    The one exception is Diameter. Every operation in CAM offsets by
    ``Tool.Diameter`` (Profile, Pocket, Adaptive, Deburr, ...), so a jet tool
    has to publish one. For a jet the width of material removed is the kerf, so
    Diameter is kept mirrored from KerfWidth and shown read-only.

    NOTE: This mixin must be listed BEFORE ToolBit in the base class list, e.g.
    ``class ToolBitPlasma(JetToolBitMixin, ToolBit)``. Python resolves methods
    left to right, so a mixin listed after ToolBit cannot override ToolBit's
    own can_rotate()/onChanged(). Listing it first still leaves the class a
    direct subclass of ToolBit, which ToolBit.__subclasses__() relies on for
    shape-to-class lookup.
    """

    # Default assist-gas / water pressure, overridden per tool type.
    DEFAULT_PRESSURE = "0 bar"

    def _init_jet_properties(self, obj):
        """Initialize jet process properties. Call explicitly after obj is created."""
        obj.addProperty(
            "App::PropertyLength",
            "KerfWidth",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Width of material removed by the jet"),
        )
        obj.KerfWidth = FreeCAD.Units.Quantity("1.0 mm")

        obj.addProperty(
            "App::PropertyLength",
            "PierceHeight",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Standoff above the material while piercing"),
        )
        obj.PierceHeight = FreeCAD.Units.Quantity("3.8 mm")

        obj.addProperty(
            "App::PropertyLength",
            "CutHeight",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Standoff above the material while cutting"),
        )
        obj.CutHeight = FreeCAD.Units.Quantity("1.5 mm")

        obj.addProperty(
            "App::PropertyTime",
            "PierceTime",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Dwell time to pierce the material before moving"),
        )
        obj.PierceTime = FreeCAD.Units.Quantity("0.5 s")

        obj.addProperty(
            "App::PropertyPressure",
            "Pressure",
            "Attributes",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Assist gas pressure for plasma and laser, water pressure for waterjet",
            ),
        )
        obj.Pressure = FreeCAD.Units.Quantity(self.DEFAULT_PRESSURE)

        # Derived from KerfWidth. Every operation offsets by Tool.Diameter, so a
        # jet tool has to publish one, but it is an implementation detail rather
        # than something to edit: the user sets KerfWidth. Putting it in "Base"
        # keeps it off the toolbit editor (which shows only Shape/Attributes) and
        # out of the .fctb (to_dict serialises only Attributes), while leaving it
        # readable by operations. It is re-derived from KerfWidth on every load.
        if not hasattr(obj, "Diameter"):
            obj.addProperty(
                "App::PropertyLength",
                "Diameter",
                "Base",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Effective cutting width, mirrored from KerfWidth. Used by operations"
                    " to offset the toolpath",
                ),
            )
        obj.setEditorMode("Diameter", 1)  # read-only

        self._sync_diameter_to_kerf(obj)

        # A jet has no spindle and no cutter material; suppress both rather
        # than showing meaningless values (same approach as ToolBitProbe).
        obj.SpindleDirection = "None"
        obj.setEditorMode("SpindleDirection", 2)
        obj.setEditorMode("Material", 2)

    @staticmethod
    def _sync_diameter_to_kerf(obj):
        """Keep the Diameter operations read in step with the kerf."""
        if not hasattr(obj, "KerfWidth") or not hasattr(obj, "Diameter"):
            return
        if obj.Diameter != obj.KerfWidth:
            obj.Diameter = obj.KerfWidth

    def onChanged(self, obj, prop):
        # KerfWidth lives in "Attributes", so ToolBit.onChanged() returns early
        # for it. Mirror it into Diameter here before delegating.
        if prop == "KerfWidth" and "Restore" not in obj.State:
            self._sync_diameter_to_kerf(obj)
        super().onChanged(obj, prop)

    def onDocumentRestored(self, obj):
        super().onDocumentRestored(obj)
        self._sync_diameter_to_kerf(obj)

    def _update_tool_properties(self):
        # onChanged() only fires for toolbits attached to a document;
        # DetachedDocumentObject.__setattr__() stores values without notifying
        # the proxy. This hook does fire on the detached path, both at
        # construction and again from ToolBit.from_shape() once the .fctb
        # attributes have been applied, so it is what keeps Diameter correct
        # for tools loaded from the library.
        super()._update_tool_properties()
        self._sync_diameter_to_kerf(self.obj)

    def can_rotate(self) -> bool:
        return False

    def get_kerf_width(self) -> FreeCAD.Units.Quantity:
        """Width of material removed by the jet."""
        return self.obj.KerfWidth

    def set_kerf_width(self, kerf: FreeCAD.Units.Quantity):
        if not isinstance(kerf, FreeCAD.Units.Quantity):
            raise ValueError("KerfWidth must be a FreeCAD Units.Quantity")
        self.obj.KerfWidth = kerf
        self._sync_diameter_to_kerf(self.obj)

    def get_diameter(self) -> FreeCAD.Units.Quantity:
        """Effective cutting width. For a jet tool this is the kerf."""
        return self.obj.Diameter

    def set_diameter(self, diameter: FreeCAD.Units.Quantity):
        """Diameter is derived from KerfWidth; set the kerf instead."""
        self.set_kerf_width(diameter)

    def get_length(self) -> FreeCAD.Units.Quantity:
        return self.obj.Length

    def set_length(self, length: FreeCAD.Units.Quantity):
        if not isinstance(length, FreeCAD.Units.Quantity):
            raise ValueError("Length must be a FreeCAD Units.Quantity")
        self.obj.Length = length
