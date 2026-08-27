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
from typing import Tuple, Mapping
from .base import ToolBitShape


class ToolBitShapeWaterjet(ToolBitShape):
    """
    Waterjet cutting head.

    NozzleDiameter is the upstream orifice; MixingTubeDiameter is the exit bore
    and is what the kerf actually follows from. Abrasive settings and the rest
    of the process values live on the ToolBit (see JetToolBitMixin).
    """

    name = "Waterjet"

    @classmethod
    def schema(cls) -> Mapping[str, Tuple[str, str]]:
        return {
            "BodyDiameter": (
                FreeCAD.Qt.translate("ToolBitShape", "Diameter of the cutting head body"),
                "App::PropertyLength",
            ),
            "Length": (
                FreeCAD.Qt.translate("ToolBitShape", "Overall length of the cutting head"),
                "App::PropertyLength",
            ),
            "MixingTubeDiameter": (
                FreeCAD.Qt.translate("ToolBitShape", "Bore of the mixing tube"),
                "App::PropertyLength",
            ),
            "NozzleDiameter": (
                FreeCAD.Qt.translate("ToolBitShape", "Diameter of the water orifice"),
                "App::PropertyLength",
            ),
            "TipLength": (
                FreeCAD.Qt.translate("ToolBitShape", "Length of the mixing tube"),
                "App::PropertyLength",
            ),
        }

    @property
    def label(self) -> str:
        return FreeCAD.Qt.translate("ToolBitShape", "Waterjet Head")
