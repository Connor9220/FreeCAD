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

"""The workholding's constants, importing nothing of it: the sides of a vise's jaws,
and the colors, transparencies and line widths the workholding is shown with."""

# the jaws of a vise a part of it stands on or against
Sides = ["Fixed", "Moving"]

# soft jaws are aluminum, apart from the vise's steel; grip jaws steel, their grips dark,
# hardened, apart from the jaw they sit in
ALUMINUM_COLOR = (0.60, 0.74, 0.90)
GRIP_JAW_COLOR = (0.62, 0.64, 0.68)
GRIP_COLOR = (0.22, 0.22, 0.25)

# parallels: soft ones light, hardened steel dark
SOFT_PARALLEL_COLOR = (0.80, 0.82, 0.70)
HARDENED_PARALLEL_COLOR = (0.30, 0.32, 0.36)

# the table, wood seen through; a stop or clamp made here, steel
TABLE_COLOR = (0.80, 0.74, 0.62)
TABLE_TRANSPARENCY = 60
STOP_COLOR = (0.55, 0.57, 0.62)

# edges and vertices drawn thin
THIN_LINE_WIDTH = 1

# the part's sides lit as the vise holds it: the one on the bottom, the one against the fixed
# jaw; drawn see-through, glowing at a share of their color, a little off the face they light,
# a curved face drawn this close to its true shape, in mm
SEAT_COLOR = (0.20, 0.75, 0.25)
JAW_FACE_COLOR = (1.00, 0.55, 0.00)
LIT_FACE_TRANSPARENCY = 0.3
LIT_FACE_GLOW = 0.5
LIT_FACE_LIFT = 0.05
LIT_FACE_TOLERANCE = 0.1

# the stock in the drawing of a stop or clamp made here, as red, green and blue of 255
STOCK_DRAWING_COLOR = (138, 109, 59)

# what the panels say in: something wrong, a clearance the tools have, one they do not
ERROR_TEXT_COLOR = "#d04040"
CLEAR_TEXT_COLOR = "#46be5a"
NOT_CLEAR_TEXT_COLOR = "#e1463c"

# an update's badge on a library's icon: an orange disc, a white arrow up and rim
BADGE_COLOR = "#f08c00"
BADGE_INK_COLOR = "#ffffff"

# the black and white of the Job panel's icons, swapped on a dark theme, the black first put by
# as a color no icon has
ICON_BLACK = b"#111111"
ICON_WHITE = b"#ffffff"
ICON_SWAP = b"#d33d3d"
