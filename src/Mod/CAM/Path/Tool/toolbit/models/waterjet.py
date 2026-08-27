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
from ...shape import ToolBitShapeWaterjet
from ..mixins import JetToolBitMixin
from .base import ToolBit


class ToolBitWaterjet(JetToolBitMixin, ToolBit):
    """
    Waterjet cutting head.

    JetToolBitMixin is listed first so it can override ToolBit.can_rotate()
    and ToolBit.onChanged(); the class stays a direct subclass of ToolBit so
    ToolBit.__subclasses__() still finds it.
    """

    DEFAULT_PRESSURE = "3800 bar"
    SHAPE_CLASS = ToolBitShapeWaterjet

    def __init__(
        self, shape: ToolBitShapeWaterjet, id: str | None = None, attrs: Optional[Mapping] = None
    ):
        Path.Log.track(f"ToolBitWaterjet __init__ called with shape: {shape}, id: {id}")
        super().__init__(shape, id=id, attrs=attrs)
        self._init_jet_properties(self.obj)
        self._init_waterjet_properties(self.obj)

    def _init_waterjet_properties(self, obj):
        obj.addProperty(
            "App::PropertyFloat",
            "AbrasiveFlowRate",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Abrasive flow rate in grams per minute"),
        )
        obj.AbrasiveFlowRate = 350.0

        obj.addProperty(
            "App::PropertyEnumeration",
            "AbrasiveType",
            "Attributes",
            QT_TRANSLATE_NOOP("App::Property", "Abrasive grit. None means pure water cutting"),
        )
        obj.AbrasiveType = ["None", "Garnet 50", "Garnet 80", "Garnet 120", "Garnet 220"]
        obj.AbrasiveType = "Garnet 80"

    def get_toolhead_type(self) -> str:
        return "waterjet"

    @property
    def summary(self) -> str:
        kerf = self.get_property_str("KerfWidth", "?", precision=3)
        abrasive = self.get_property("AbrasiveType")

        return FreeCAD.Qt.translate("CAM", f"Waterjet, {kerf} kerf, {abrasive} abrasive")
