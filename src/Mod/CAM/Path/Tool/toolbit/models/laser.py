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
import Path
from typing import Optional, Mapping
from PySide.QtCore import QT_TRANSLATE_NOOP
from ...shape import ToolBitShapeLaser
from ..mixins import JetToolBitMixin
from .base import ToolBit


class ToolBitLaser(JetToolBitMixin, ToolBit):
    """
    Laser cutting/engraving head.

    JetToolBitMixin is listed first so it can override ToolBit.can_rotate()
    and ToolBit.onChanged(); the class stays a direct subclass of ToolBit so
    ToolBit.__subclasses__() still finds it.

    Laser toolbits are typically used as per-material process presets ("3mm ply
    cut", "acrylic engrave") rather than as physical consumables. That is the
    intended usage; use shape subtypes and feeds & speeds presets to organise
    them.
    """

    DEFAULT_PRESSURE = "1.0 bar"
    SHAPE_CLASS = ToolBitShapeLaser

    def __init__(
        self, shape: ToolBitShapeLaser, id: str | None = None, attrs: Optional[Mapping] = None
    ):
        Path.Log.track(f"ToolBitLaser __init__ called with shape: {shape}, id: {id}")
        super().__init__(shape, id=id, attrs=attrs)
        self._init_jet_properties(self.obj)
        self._init_laser_properties(self.obj)

    def _init_laser_properties(self, obj):
        obj.addProperty(
            "App::PropertyPercent",
            "CutPower",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Laser power while cutting, as a percentage"),
        )
        obj.CutPower = 100

        obj.addProperty(
            "App::PropertyPercent",
            "PiercePower",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Laser power while piercing, as a percentage"),
        )
        obj.PiercePower = 100

        obj.addProperty(
            "App::PropertyDistance",
            "FocusOffset",
            "Attributes",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Offset of the focal point from the material surface."
                " Negative focuses below the surface",
            ),
        )
        obj.FocusOffset = FreeCAD.Units.Quantity("0.0 mm")

        obj.addProperty(
            "App::PropertyFrequency",
            "PulseFrequency",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Pulse frequency. Zero means continuous wave"),
        )
        obj.PulseFrequency = FreeCAD.Units.Quantity("0 Hz")

        obj.addProperty(
            "App::PropertyPercent",
            "PulseDutyCycle",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Duty cycle when pulsing, as a percentage"),
        )
        obj.PulseDutyCycle = 100

        obj.addProperty(
            "App::PropertyEnumeration",
            "AssistGas",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Assist gas"),
        )
        obj.AssistGas = ["Air", "Oxygen", "Nitrogen", "None"]
        obj.AssistGas = "Air"

    def get_toolhead_type(self) -> str:
        return "laser"

    @property
    def summary(self) -> str:
        kerf = self.get_property_str("KerfWidth", "?", precision=3)
        power = self.get_property("CutPower")

        return FreeCAD.Qt.translate("CAM", f"Laser, {kerf} kerf, {power}% power")
