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

# what a clamp's file says it is, its VarSet's Kind: a side clamp, a hold-down over the top
# edge, a lever clamp the panel places by its points, and a strap clamp kit, one of each piece
CLAMP_KINDS = ("HoldDown", "Push", "Lever", "StrapKit")

# lever clamps, as quantities FreeCAD reads: the stud's end above its nut; the gap kept between
# the stock's side and the washer or nut when a clamp is spread along a side; the least it
# presses in from the stock's edge; a riser's length under the clamp's end, the margin it has to
# either side of it, and how thick one is made at first
LEVER_STUD_ABOVE_NUT = "0.125 in"
LEVER_EDGE_CLEARANCE = "0.125 in"
LEVER_LEAST_OVERLAP = "0.125 in"
LEVER_RISER_LENGTH = "1.5 in"
LEVER_RISER_MARGIN = "0.125 in"
LEVER_RISER_THICKNESS = "0.125 in"
# a riser put under a lever clamp's step blocks when none reaches is a multiple of this
LEVER_RISER_STEP = "0.25 in"
# how much of a strap clamp's end rests on a pair of step blocks' flat top, at least and at most,
# when its file does not say: less bears on an edge, more brings the support nearer the stud
LEVER_HEEL_REST_MIN = "0.5 in"
LEVER_HEEL_REST_MAX = "1 in"
# where it was to press lifted off the stock by more than this is said
LEVER_LIFT_NOTED = "0.002 in"
# a lever clamp's other end this many degrees above level, or more, is said to be too high
LEVER_TILT_NOTED = 10.0
# a step block's top read every this many mm along it, to mesh two teeth into teeth
LEVER_PROFILE_STEP = 0.1
# how nearly a step clamp's heel just touches its step block's teeth, mm
LEVER_SEAT_TOLERANCE = 0.05
# how far in from a lever clamp's other end it is looked at for what stands on its support
LEVER_END_REACH = "0.75 in"
# a bolt in the table's track cut to fit is cut in steps of this
LEVER_BOLT_STEP = "0.25 in"
# a riser, wood; a bolt cut to length, black oxide
RISER_COLOR = (0.80, 0.70, 0.52)
BOLT_COLOR = (0.15, 0.15, 0.17)

# the stock in the drawing of a stop or clamp made here, as red, green and blue of 255
STOCK_DRAWING_COLOR = (138, 109, 59)

# a click or a turn of the wheel in a length box: a tenth of the unit it shows, 0.1 in. or 0.1 mm
LENGTH_STEP = 0.1
# FreeCAD's edit mode for Transform's dragger without its task panel, Gui::ViewProvider's
# TransformNoDialog: a stop or clamp picked in the workholding panel dragged with it
TRANSFORM_NO_DIALOG = 4

# the status bit getPropertyStatus gives a property added to an object, not one of its own:
# App::Property::PropDynamic, which has no name of its own there
PROPERTY_ADDED = 21
# a stop or clamp put past its side's end keeps at least this much of its width across from the
# stock, to touch it
ACROSS_AT_LEAST = 0.25
# a stop or clamp is moved in square to its side until it touches the stock itself, not its box:
# in at most this many moves, each as far as it is from the stock, until it is this near, mm
TOUCH_MOVES = 16
TOUCH_NEAR = 0.01
# a turn of a lever clamp or a vise with that dragger goes by this many degrees
DRAG_TURN_STEP = 1.0
# a lever clamp let go by its dragger within this many degrees of square to its side, or to
# the sides beside it, is turned square; its Angle typed is kept as it is
LEVER_SNAP_DEGREES = 10.0
# the part's sides on the vise's bottom and against its fixed jaw lit in color: off for now
SHOW_LIT_SIDES = False
# the least a vise's jaws are left gripping the stock when it is stood higher by dragging, mm
VISE_LEAST_GRIP = 3.0
# what Add shows put in again this many ms after the last change of its side or how many
ADD_PREVIEW_DELAY = 300
# the piece being dragged: where it is shown in the panel every this many ms
DRAG_SHOW_EVERY = 60

# a lever clamp is placed again this many ms after the last turn of the wheel in its panel
LEVER_EDIT_DELAY = 250

# the stops and clamps panel: how many clamps' files it offers as used lately, kept in the CAM
# preferences under this name, one path a line; the pictures in the item box, in its list and in
# the preview of what Add puts in, and the picture beside the picked piece's settings, pixels
RECENT_CLAMPS = 5
RECENT_CLAMPS_PREF = "WorkholdingRecentClamps"
ITEM_ICON = 22
ITEM_LIST_ICON = 40
ITEM_PREVIEW = 96

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
