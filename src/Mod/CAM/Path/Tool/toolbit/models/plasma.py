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
from ...shape import ToolBitShapePlasma
from ..mixins import JetToolBitMixin, format_number
from .base import ToolBit


class ToolBitPlasma(JetToolBitMixin, ToolBit):
    """
    Plasma cutting torch.

    JetToolBitMixin is listed first so it can override ToolBit.can_rotate()
    and ToolBit.onChanged(); the class stays a direct subclass of ToolBit so
    ToolBit.__subclasses__() still finds it.
    """

    DEFAULT_PRESSURE = "4.8 bar"
    SHAPE_CLASS = ToolBitShapePlasma

    def __init__(
        self, shape: ToolBitShapePlasma, id: str | None = None, attrs: Optional[Mapping] = None
    ):
        Path.Log.track(f"ToolBitPlasma __init__ called with shape: {shape}, id: {id}")
        super().__init__(shape, id=id, attrs=attrs)
        self._init_jet_properties(self.obj)
        self._init_plasma_properties(self.obj)

    def _init_plasma_properties(self, obj):
        # Amperage and ArcVoltage are deliberately plain floats rather than
        # App::PropertyElectricCurrent/ElectricPotential. Neither has a unit
        # conversion worth having here (nobody sets a torch in milliamps), and
        # under some unit schemas FreeCAD renders electric potential as the raw
        # derived unit "mm^2*kg/(s^3*A)", which Gui::QuantitySpinBox then fails
        # to edit correctly. The unit is named in the tooltip instead.
        obj.addProperty(
            "App::PropertyFloat",
            "Amperage",
            "Attributes",
            QT_TRANSLATE_NOOP(
                "App::Property", "Cutting current of the consumable set, in amps (A)"
            ),
        )
        obj.Amperage = 45.0

        obj.addProperty(
            "App::PropertyFloat",
            "ArcVoltage",
            "Attributes",
            QT_TRANSLATE_NOOP(
                "App::Property", "Target arc voltage for torch height control, in volts (V)"
            ),
        )
        obj.ArcVoltage = 120.0

        obj.addProperty(
            "App::PropertyEnumeration",
            "AssistGas",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Plasma and shield gas"),
        )
        obj.AssistGas = ["Air", "Oxygen", "Nitrogen", "Argon-Hydrogen", "None"]
        obj.AssistGas = "Air"

    def get_toolhead_type(self) -> str:
        return "plasma"

    @property
    def summary(self) -> str:
        kerf = self.get_property_str("KerfWidth", "?", precision=3)
        # _fmt_number rather than a :g format spec: summary is rendered for
        # every row of the library browser, including shallow-loaded toolbits,
        # and must not raise on an unexpected value type.
        amperage = format_number(self.get_property("Amperage"))

        return FreeCAD.Qt.translate("CAM", f"Plasma torch, {kerf} kerf, {amperage} A")
