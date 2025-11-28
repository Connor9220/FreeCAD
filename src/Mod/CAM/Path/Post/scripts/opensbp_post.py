# ***************************************************************************
# *   Copyright (c) 2014 sliptonic <shopinthewoods@gmail.com>               *
# *   Copyright (c) 2022 - 2025 Larry Woestman <LarryWoestman2@gmail.com>   *
# *   Copyright (c) 2025 Alan Grover <awgrover@gmail.com>                   *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful,            *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Lesser General Public License for more details.                   *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with FreeCAD; if not, write to the Free Software        *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************
"""FreeCAD CAM post-processor for Shopbot native opensbb, in the "refactored" style"""

import re
import argparse
from copy import copy
import operator
import math
import time

from typing import Any

from Path.Post.Processor import PostProcessor
import Path.Post.UtilsArguments as PostUtilsArguments
import Path.Post.UtilsExport as PostUtilsExport
import Path.Post.UtilsParse as PostUtilsParse

import Path
Path.write(object,"/path/to/file.ncc","post_opensbp")
"""

"""
DONE:
    uses native commands
    handles feed and jog moves
    handles XY, Z, and XYZ feed speeds
    handles arcs
    support for inch output
ToDo
    comments may not format correctly
    drilling.  Haven't looked at it.
    many other things

"""

TOOLTIP_ARGS = """
Arguments for opensbp:
    --comments          ... insert comments - mostly for debugging
    --inches            ... convert output to inches
    --no-header         ... suppress header output
    --no-show-editor    ... don't show editor, just save result
"""

now = datetime.datetime.now()

OUTPUT_COMMENTS = False
OUTPUT_HEADER = True
SHOW_EDITOR = True
COMMAND_SPACE = ","

# Preamble text will appear at the beginning of the GCODE output file.
PREAMBLE = """"""
# Postamble text will appear following the last operation.
POSTAMBLE = """"""

# Pre operation text will be inserted before every operation
PRE_OPERATION = """"""

# Post operation text will be inserted after every operation
POST_OPERATION = """"""

# Tool Change commands will be inserted before a tool change
TOOL_CHANGE = """"""


CurrentState = {}


def getMetricValue(val):
    return val


def getImperialValue(val):
    return val / 25.4


GetValue = getMetricValue


def export(objectslist, filename, argstring):
    global OUTPUT_COMMENTS
    global OUTPUT_HEADER
    global SHOW_EDITOR
    global CurrentState
    global GetValue

    for arg in argstring.split():
        if arg == "--comments":
            OUTPUT_COMMENTS = True
        if arg == "--inches":
            GetValue = getImperialValue
        if arg == "--no-header":
            OUTPUT_HEADER = False
        if arg == "--no-show-editor":
            SHOW_EDITOR = False

    for obj in objectslist:
        if not hasattr(obj, "Path"):
            s = "the object " + obj.Name
            s += " is not a path. Please select only path and Compounds."
            print(s)
            return

    CurrentState = {
        "X": 0,
        "Y": 0,
        "Z": 0,
        "F": 0,
        "S": 0,
        "JSXY": 0,
        "JSZ": 0,
        "MSXY": 0,
        "MSZ": 0,
    }
    print("postprocessing...")
    gcode = ""

    # write header
    if OUTPUT_HEADER:
        gcode += linenumber() + "'Exported by FreeCAD\n"
        gcode += linenumber() + "'Post Processor: " + __name__ + "\n"
        gcode += linenumber() + "'Output Time:" + str(now) + "\n"

    # Write the preamble
    if OUTPUT_COMMENTS:
        gcode += linenumber() + "'(begin preamble)\n"
    for line in PREAMBLE.splitlines(True):
        gcode += linenumber() + line

    for obj in objectslist:

        # do the pre_op
        if OUTPUT_COMMENTS:
            gcode += linenumber() + "'(begin operation: " + obj.Label + ")\n"
        for line in PRE_OPERATION.splitlines(True):
            gcode += linenumber() + line

        gcode += parse(obj)

        # do the post_op
        if OUTPUT_COMMENTS:
            gcode += linenumber() + "'(finish operation: " + obj.Label + ")\n"
        for line in POST_OPERATION.splitlines(True):
            gcode += linenumber() + line

    # do the post_amble
    if OUTPUT_COMMENTS:
        gcode += "'(begin postamble)\n"
    for line in POSTAMBLE.splitlines(True):
        gcode += linenumber() + line

    if SHOW_EDITOR:
        dia = PostUtils.GCodeEditorDialog()
        dia.editor.setPlainText(gcode)
        result = dia.exec_()
        if result:
            final = dia.editor.toPlainText()
        else:
            return ""

    @gcode("comment")
    def t_comment(self, path_command):
        # leaves ()
        rez = ""

        rez += self.comment(path_command.Name)

        # fixups
        # We don't have access to the Path object, and we need/want to know where we are
        # e.g. probing. This should be fixed in the new "machine" style
        if path_command.Name.startswith("(Post Processor: "):
            rez += self.comment("  " + self.post._job.PostProcessorArgs)
        elif path_command.Name.startswith("(Cam File: "):
            rez += self.comment(f"Job: {self.post._job.Label}")
        elif m := re.match(r"\(\s*MC_RUN_COMMAND\s+(.+)\)$", path_command.Name):
            # let's leave the original as a comment (if comments are on)
            rez += m.group(1) + "\n"
        elif m := re.match(r"\(PROBEOPEN (.+)\)$", path_command.Name):
            filename = m.group(1)
            if "." not in filename:
                # default .txt (really "space delimited values")
                filename += ".txt"

            # the Probe operation

            # can't get &UserDataFolder to catenate properly anywhere...
            # so, just filename
            rez += self.comment(
                "Load the My_Variables file from Custom Cut 90 in C:\\SbParts\\Custom"
            )
            rez += "C#,90" + nl
            # if re.match(r'[^:]+:', filename):
            #    # "absolute"
            #    rez += f'OPEN "{filename}" FOR OUTPUT as #1' + nl
            # else:
            #    # "relative"
            #    rez += "GetUsrPath, &UserDataFolder" + nl
            #    rez += f'OPEN &UserDataFolder & "/{filename}" FOR OUTPUT as #1' + nl
            rez += f'OPEN "{filename}" FOR OUTPUT as #1' + nl

            rez += "&hit = 0" + nl
            # subroutines, cleanup
            # but only once per post
            if self.post.values["first_probe"]:
                self.post.values["first_probe"] = False
                self._postfix.append(
                    """GOTO SkipProbeSubRoutines
CaptureZPos:
  ' for g38.2 probe, write the data on probe-contact
  ' and set flag for didn't-fail
  ' xyzab
  WRITE #1; %(1); " "; %(2); " "; %(3); " "; %(4); " "; %(5)
  &hit = 1
  RETURN
FailedToTouch:
  ' for g38.2 probe, when
  ' failed to trigger w/in movement
  MSGBOX(Failed to touch...Exiting,16,Probe Failed)
  END
SkipProbeSubRoutines:"""
                )
        elif path_command.Name == "(PROBECLOSE)":
            rez += self.comment("Clear probe-switch-trigger")
            rez += "ON INPUT(&my_ZzeroInput, 1)" + nl
            rez += "CLOSE #1" + nl

        return rez

    @gcode("G20", "G21")  # inches, metric
    def t_units(self, path_command):
        if self.set_units:
            raise ValueError(
                "You can only set the units once, already {self.set_units['command']} at {self.set_units['at']}. You tried again at {self.location(path_command)}"
            )
        else:
            # remember where
            self.set_units = {"command": path_command.Name, "at": self.location()}

            undesired_units = {"G20": "1", "G21": "0"}[path_command.Name]  # OPPOSITE!
            rez = [
                f"IF %(25) = {undesired_units} THEN GOTO WrongUnits",
            ]

            pp_which = {"G20": "G20/--inches", "G21": "G21/--metric"}[path_command.Name]
            self._postfix.append(
                nl.join(
                    [
                        "GOTO AfterWrongUnits",
                        "WrongUnits:",
                        '  if %(25) = 0 THEN &shopbot_which="inches"',
                        '  if %(25) = 1 THEN &shopbot_which="mm"',
                        # NB: no commas in strings!
                        f'    MSGBOX("Post-processor wants {pp_which} but ShopBot is " & &shopbot_which & ". Change Units in ShopBot and try again.",0,"Change Units")',
                        "    ENDALL",
                        "AfterWrongUnits:",
                    ]
                )
            )

            return nl.join(rez) + nl

    @gcode("G90")  # no relative (G91) yet, have to fix modal handling for relative
    def t_absolute_mode(self, path_command):
        self.post.values["MOTION_MODE"] = path_command.Name
        return {"G90": "SA", "G91": "SR"}[path_command.Name] + nl

    @gcode("M06")
    def t_toolchange(self, path_command):
        tool_number = int(path_command.Parameters["T"])

        # check for tool actually existing
        tool_controller = next(
            (x for x in self.post._job.Tools.Group if x.ToolNumber == tool_number), None
        )
        if not tool_controller:
            # HACK: at least till 1.1, nothing enforces tool-numbers in the job to be unique
            #   and "Tn" doesn't have to match a ToolNumber
            #   we'll do a compatibility hack ONLY if all tools == 1
            if (
                all(x.ToolNumber == 1 for x in self.post._job.Tools.Group)
                and len(self.post._job.Tools.Group) >= tool_number
            ):
                tool_controller = self.post._job.Tools.Group[tool_number - 1]
                FreeCAD.Console.PrintWarning(
                    f"Job <{self.post._job.Label}> doesn't have unique tool-numbers? at {self.location(path_command)}"
                )
            else:
                raise ValueError(
                    f"Toolchange with non-existent tool_number {tool_number} at {self.location(path_command)}. Do tools have unique tool-numbers?"
                )

        tool_name = f"{tool_controller.Label}, {tool_controller.Tool.Label}"  # not sure if we want both .Label's, just trying to help the operator
        safe_tool_name = re.sub(r"[^A-Za-z0-9/_ .-]", "", tool_name)

        rez = []

        if not self.post.values["OUTPUT_TOOL_CHANGE"]:
            rez.append(
                self.comment(
                    f"First change tool, should already be #{tool_number}: {safe_tool_name}",
                    force=True,
                ).rstrip()
            )

        rez += [
            f"&Tool={tool_number}",
            f'&ToolName="{safe_tool_name}"',
        ]

        if self.post.values["OUTPUT_TOOL_CHANGE"]:
            # automatic no prompt, or manual prompt (depends on correct shopbot setup)
            rez.append("C9")

        else:
            if self.first_tool:
                self.first_tool = False
            else:
                raise NotImplementedError(
                    f"2nd tool can't be done, #{tool_number}, no way to change-tool when --no-tool-changer at {self.location(path_command)}. Try 'Order by Tool' or 'Order by Operation' in job's 'Output' tab."
                )

        rez.append(self.set_initial_speeds(tool_controller, path_command).rstrip())
        rez = nl.join((x for x in rez if x != "")) + nl

        return rez

    @gcode("G00", "G01")
    def t_move(self, path_command):
        """Oh boy.
        opensbp specifies the xy speed, and Z speed separately for a motion.
        e.g. a "VS,sxy,sz" then the move like "M3,x,y,z".
        But, gcode has a F which the speed of the vector
        (for rapid, it's whatever-the-machine-setting-is).
        FreeCAD has horizontal speed (xy), and vertical speed (z),
        which it uses to calculate F,
        (we already set rapid at set_initial_speed() time for each tool-change).
        Finally, we have to take the delta(x,y,z) vector and project the F speed onto xy, and z
        to generate the MS command before each move command.
        The Mx or Jx just uses the axis distances.
        FIXME? If the first motion is not G0, and axis are 'Z' + X|Y,
            (e.g. G1 X10 Y20 Z30)
            then we don't know how to calculate the MS speed,
            because we need to know the last-position to split F across Z & X|Y,
            and there isn't one (that we know about), though we init'd to 0,0,0.
            We assume a G1 happens before any other motion, to establish a position.
            We could abort on this...
        """
        rez = ""

        # Optimize the command, specifying 1..5 axis values
        axis = [path_command.Parameters.get(a, None) for a in self.PositionAxis]
        last_not_none = 0
        # XYZABC, but reversed
        for i in reversed(range(0, len(axis))):
            if axis[i] is not None:
                last_not_none = i
                break
        axis = axis[: last_not_none + 1]

        if feed_rate := path_command.Parameters.get("F", None):
            if path_command.Name == "G00":
                if self.post.arguments.abort_on_unknown:
                    raise ValueError(
                        f"Rapid moves (G0) can't have an F at {self.location(path_command)}"
                    )

        _, speed_command = self.set_speed(path_command)
        rez += speed_command

        native_command = "J" if path_command.Name == "G00" else "M"
        # print(f"  ### is a '{native_command}'")

        # nb, we don't have to do anything for --axis-modal, handled by common stuff earlier!

        axis_ct = len(axis)
        if axis_ct == 1:
            native_command += "X"
        else:
            native_command += str(axis_ct)

        formatted_axis = (
            (format(a, f".{self.post.values['FEED_PRECISION']}f") if a is not None else "")
            for a in axis
        )
        rez += f"{native_command},{','.join(formatted_axis)}" + nl

        return rez

    @gcode("M03")  # clockwise only. do the spindle-controlers do CCW?
    def t_spindle_speed(self, path_command):
        native = ""

        if "S" in path_command.Parameters:
            native += f"TR,{int(path_command.Parameters['S'])}\n"  # rpm units

        # macro will do the dialog-box if you don't have a controlled spindle
        native += "C6\n"

        if self.post.values["SPINDLE_WAIT"] > 0:
            native += f"PAUSE {int(self.post.values['SPINDLE_WAIT'])}\n"

        return native

    def format_value(self, value, precision_type="FEED_PRECISION"):
        """format for the precision (e.g. AXIS_PRECISION)
        notably dealing with slightly-less-than-zero == "0" not "-0"
        """
        # format rounds, so duplicate that effect
        if abs(value) < 0.5 * 10 ** (-self.post.values[precision_type]):
            value = 0.0
        return format(value, f".{self.post.values[precision_type]}f")

    @gcode("G02", "G03")
    def t_arc(self, path_command):
        # only center-format: IJ
        # only absolute mode
        # only xy plane
        # only P1 (or no P)
        # cases:
        #   current-position is start
        #   Z causes helical-arc
        #   Pn causes arc-as-defined + (n-1) whole circles: not handled
        #   XY is the end-position for a segment
        #   none of XY means whole circle
        #   IJ is the location of the arc-center: an offset. at least one of is required
        #   F is required

        # we would have to generate multiple CG's for repetitions (P)
        handled_parameters = "XYZIJFPK"  # notably, not R

        not_handled = []
        not_handled = [a for a in path_command.Parameters if a not in handled_parameters]
        # we handle K=0.0 by ignoring it (xy-plane), other K's we don't handle
        if "K" in path_command.Parameters and path_command.Parameters["K"] != 0.0:
            not_handled.append("K")
        if "P" in path_command.Parameters and path_command.Parameters["P"] != 1:
            not_handled.append("P")
        if not_handled:
            message = (
                f"We can't do parameters {not_handled} for an arc in {self.location(path_command)}"
            )
            FreeCAD.Console.PrintError(message)
            if self.post.arguments.abort_on_unknown:
                raise ValueError(message)
            else:
                return ""

        if self.post.values["MOTION_MODE"] != "G90":
            opname = self.post.values["Operation"].Label if self.post.values["Operation"] else ""
            message = f"We can't do relative mode for arcs in [{self.post.values['line_number']}] {opname} {path_command.toGCode()}"
            FreeCAD.Console.PrintError(message)
            if self.post.arguments.abort_on_unknown:
                raise NotImplementedError(message)
            else:
                return ""

        if path_command.Name == "G02":  # CW
            dirstring = "1"
        else:  # G3 means CCW
            dirstring = "-1"
        txt = ""

        dz, speed_command = self.set_speed(path_command)
        txt += speed_command

        txt += "CG,"
        txt += ","  # no diameter

        # end
        # Omitting XY has special meaning to ShopBot, it is not the same as modal-axis
        # The PostProcess code will drop the XYZ axis on --axis-modal, but we need it:
        x = path_command.Parameters.get("X", self.current_location["X"])
        y = path_command.Parameters.get("Y", self.current_location["Y"])

        txt += self.format_value(x) + ","
        txt += self.format_value(y) + ","

        # Center is at offset:
        txt += (
            self.format_value(
                path_command.Parameters["I"] if "I" in path_command.Parameters.keys() else 0.0
            )
            + ","
        )
        txt += (
            self.format_value(
                path_command.Parameters["J"] if "J" in path_command.Parameters.keys() else 0.0
            )
            + ","
        )
        txt += "T" + ","  # move on diameter
        txt += dirstring + ","

        if "Z" not in path_command.Parameters:
            dz = 0

        # Z causes a helical, "causes the defined plunge to be made gradually as the cutter is circling down"
        # Note, dz is actual distance vector, but ShopBot uses -dz to mean "plunge" relative
        txt += self.format_value(-dz) + ","

        txt += ","  # repetitions
        txt += ","  # proportion-x
        txt += ","  # proportion-y

        if dz != 0.0:
            # helical cases
            # we don't do "bottom pass" (4) because FreeCAD seems to do that and it's not a g-code thing anyway
            if "X" not in path_command.Parameters and "Y" not in path_command.Parameters:
                # circle
                feature = 3  # spiral
            else:
                feature = 3  # spiral
        else:
            feature = 0

        txt += f"{feature},"
        txt += "1,"  # continue the CG plunging (don't pull up)
        txt += "0"  # no move before plunge

        # actual Z, opensbp plunge is a delta, note the actual Z as a comment
        z = path_command.Parameters.get("Z", self.current_location["Z"])
        txt += " ' Z" + self.format_value(z)
        txt += "\n"
        return txt

    @gcode("M00", "M01")
    def t_prompt(self, command):
        # Prompt with "Continue?" and pause, wait for user-interaction
        # If a comment precedes M00, that is used as the prompt (to emulate opensbp behavior)

        txt = ""
        if not self.post.values["last_command"].Name.startswith("("):
            # default prompt
            where = []
            if self.post._job:
                where.append(f"<{self.post._job.Label}>")
            if self.post.values["Operation"]:
                where.append(f"<{self.post.values['Operation']}>")
            txt += self.comment(f"Continue {'.'.join(where)}?", force=True)
        elif not self.post.values["OUTPUT_COMMENTS"]:
            # Force inclusion of that preceding comment as a prompt
            txt += self.comment(self.post.values["last_command"].Name, force=True)
        txt += "PAUSE\n"
        return txt

    @gcode("M05")
    def t_stop_spindle(self, command):
        return "C7\n"

    @gcode("M02", "M30")
    def t_stop(self, command):
        return "END\n"

    @gcode("M08")
    def t_coolant_on(self, command):
        return "SO,3,1\n"

    @gcode("M09")
    def t_cooland_off(self, command):
        return "SO,3,0\n"

    @gcode("G38.2")
    def t_probe(self, command):

        speed = command.Parameters.get("F", None)
        if speed is not None:
            speed = float(speed)
        if speed == 0.0:
            FreeCAD.Console.PrintWarning(
                f"G38.2 with an F0.0, set Tool speeds? at {self.location(command)}\n"
            )
            return ""
        if speed is None:
            speed = self.current_location["ms"][1]  # out of [ xy, z ]

        axis = " ".join(
            [f"{a}{command.Parameters[a]}" for a in self.PositionAxis if a in command.Parameters]
        )

        # PROBEOPEN sets up the contact-detect, so G38.2 are just moves
        rez = ""

        rez += "&hit = 0" + nl  # for did-we-hit OR fail

        # for probing, we have to setup the on-input for every move
        rez += "ON INPUT(&my_ZzeroInput, 1) GOSUB CaptureZPos" + nl

        g = f"G01 F{speed} {axis}"
        rez += self.t_move(Path.Command(g))

        # and check for fail to contact
        rez += "IF &hit = 0 THEN GOTO FailedToTouch\n"

        return rez

    def set_speed(self, path_command):
        # For non-rapid, F applies to the vector of all the axis
        # For rapid, full speed on the axis from the toolchange settings
        #   (so no output here)
        # Projects F into XY plane, and Z plane for shopbot
        # Always uses "VS" command to not "punctuate" the stack (ms/js will cause ramp up/down in speed)
        # Elides VS values if not change or 0.0 (shopbot doesn't like 0)
        # Elides trailing ,
        # Elides whole VS if no values

        if path_command.Name == "G00":
            # Actually, we just use the full speed on xy and z axis
            # which was initialized at toolchange time
            # the args to vs would be: VS,xy,z,a,b,xy_job,z_job,a_job,b_jog
            return (0, "")

        # we output VS, but this lets us track MS vs JS
        which_speed = "MS"

        last_position = [float(self.current_location[a] or 0) for a in self.PositionAxis]

        def fmt_diff(l):
            return [(f"{p:9.3f}" if p is not None else f"{str(p):9s}") for p in l]

        # Linear move
        if path_command.Name == "G01":
            d_axis = list(map(operator.sub, self.end_location, last_position))

            squared_d_axis = [v**2 for v in d_axis]
            distance = math.sqrt(sum(squared_d_axis))
            z_distance = abs(d_axis[2])
            xy_distance = math.sqrt(sum(squared_d_axis[:2]))
            axis = [a for a in self.PositionAxis if a in path_command.Parameters]

        # Arcs
        elif path_command.Name in {"G02", "G03"}:

            def arc_length_3d(center, start, end, clockwise):
                """center, start, end: (x, y, z) tuples
                clockwise: True for G2, False for G3
                Returns the true 3D arc length.
                """

                cx, cy, cz = center
                sx, sy, sz = start
                ex, ey, ez = end

                # ---- linear Z interpolation ----
                dz = ez - sz

                # ---- XY arc angle ----
                r = math.hypot(sx - cx, sy - cy)

                a0 = math.atan2(sy - cy, sx - cx)
                a1 = math.atan2(ey - cy, ex - cx)

                dtheta = a1 - a0

                if dtheta == 0:
                    dtheta = 2 * math.pi
                elif clockwise:
                    if dtheta > 0:
                        dtheta -= 2 * math.pi
                else:
                    if dtheta < 0:
                        dtheta += 2 * math.pi

                arc_xy = abs(r * dtheta)

                # ---- true helical arc length ----
                return (arc_xy, math.hypot(arc_xy, dz))

            start_position = [float(self.current_location[a] or 0) for a in "XYZ"]
            center_offset = [
                float(path_command.Parameters.get(a, None) or 0) for a in "IJK"
            ]  # k always 0
            end_position = [
                float(path_command.Parameters.get(k, start_position[i]))
                for i, k in enumerate("XYZ")
            ]
            z_distance = start_position[2] - end_position[2]

            # If the XY is omitted, it means a whole circle, and arc-length-3d will give that
            xy_distance, distance = arc_length_3d(
                map(operator.add, start_position, center_offset),  # center
                start_position,
                end_position,
                path_command.Name == "G02",  # clockwise?
            )

            axis = list("XYZ")

        distances_for_speed = [abs(xy_distance), abs(z_distance)]  # abs(xy) shouldn't be necessary

        if path_command.Name == "G00":
            # see above, we don't get to here on G0
            # Rapid speed is the full speed on xy, and z
            # no projecting on to the vector
            # FIXME: AB not handled yet
            speeds = self.current_location["js"]

        # feed motions
        else:
            # FIXME: AB speeds not handled yet

            f = path_command.Parameters.get("F", None)
            if f is None:
                f = self.current_location["F"]
                # print(f"  ### no f, last= '{f}'")

            if f is None:
                # No F and no previous, which is not good. default to machine's feed speeds.
                f = None
                if self.first_no_F:
                    FreeCAD.Console.PrintWarning(
                        f"No F, and no previous F speed at {self.location(path_command)}. Using tool's feed speeds.\n"
                    )
                    self.first_no_F = False
                speeds = ["", ""]

            else:
                # have a F/previous: use it
                f = float(f)

                # if only in xy, or only in z, then speed=F
                if xy_distance != 0.0 and z_distance == 0.0:
                    speeds = [f, 0.0]
                elif xy_distance == 0.0 and z_distance != 0.0:
                    speeds = [0.0, f]

                else:
                    # FIXME: AB not handled yet
                    speeds = [
                        ((f * d / distance) if distance != 0 else 0) for d in distances_for_speed
                    ]
                    # print(f"  ### speed w/xyz {speeds}")
            # print(f"  ### speeds  {speeds}")

        min_speed = self.post.values["MIN_SPEED"]

        def gtmin(s):
            if s == "":
                return s
            elif abs(s) >= min_speed:
                return s
            elif s == 0.0:
                return ""
            elif abs(s) < min_speed:
                return min_speed * (-1 if s < 0 else 1)
            # that's all the cases

        speeds = [gtmin(s) for s in speeds]
        speeds = [
            (format(s, f'.{self.post.values["SPEED_PRECISION"]}f') if s != "" else "")
            for s in speeds
        ]

        if which_speed == "MS":
            # axis-modal against actual output (formatted to SPEED_PRECISION)
            # and save as current

            non_elided = copy(speeds)

            if True:  # speed-modal always true
                # compare to previous 'ms' speeds, so we can skip 'MS' if nothing changes
                for i, new_speed in enumerate(speeds):
                    old_speed = self.current_location[which_speed.lower()][i]
                    if old_speed == new_speed:
                        speeds[i] = ""

            # save it for next time, for --speed-modal
            self.current_location["ms"] = non_elided

        # cleans up trailing , when trailing speeds elided
        if which_speed == "MS":
            cmd = f"VS,{','.join(speeds)}".rstrip(",")
        elif which_speed == "JS":
            # again, shouldn't get here in this version of the code
            cmd = f"VS,,,,,{','.join(speeds)}".rstrip(",")

        # If there is no speed to set (e.g. the move ends up as delta-0), no MS needed
        if cmd == "VS":
            cmd = ""
        else:
            cmd += nl
        return (z_distance, cmd)

    def set_initial_speeds(self, tool_controller, path_command):
        # need to ensure initial values for speeds
        # rapid-speed is never emitted by gcode, but we need to set it!
        # and we just set the initial speed for "feed" too

        Path.Log.debug(f"Setspeeds {tool_controller.Label}")
        native = ""

        native += self.comment(f"set speeds: {tool_controller.Label}")
        speeds = {
            "ms": [],  # xy,z
            "js": [],  # xy,z
        }

        def append_speed(which_speed, which_speed_key):
            with_units = getattr(tool_controller, which_speed)
            speed = float(with_units.getValueAs(self.post.values["UNIT_SPEED_FORMAT"]))

            if abs(speed) >= 0.5 * 10 ** (-self.post.values["SPEED_PRECISION"]):  # i.e. not zero

                formatted = format(speed, f'.{self.post.values["SPEED_PRECISION"]}f')

                speeds[which_speed_key].append(formatted)
                return None
            else:
                FreeCAD.Console.PrintWarning(
                    f"ToolController <{self.post._job.Label}>.<{tool_controller.Label}> did not set {which_speed} speed, set the HorizFeed and VertFeed. ( for {self.location(path_command)} )\n"
                )
                speeds[which_speed_key].append("")
                if which_speed.endswith("Rapid"):
                    warn_rapid.append(which_speed)
                return self.comment(f"no {which_speed}", force=True)

        warn_rapid = []  # empty is no warning

        # tool's speeds -> speeds[ 'ms' & 'js' ]
        for which_speed_key, which_speed_properties in {
            "ms": ["HorizFeed", "VertFeed"],
            "js": ["HorizRapid", "VertRapid"],
        }.items():
            for which_speed in which_speed_properties:  # by property for warning messages
                comment = append_speed(which_speed, which_speed_key)
                if comment is not None:
                    native += comment

            # for --speed-modal
            self.current_location[which_speed_key] = speeds[which_speed_key]

            # add to command-stream
            command_prefix = which_speed_key.upper()
            command = (f"{command_prefix}," + ",".join(speeds[which_speed_key])).rstrip(",")
            if command != command_prefix:  # has actual speeds
                native += command + "\n"

        # fixme: where to get A&B values?
        # speeds['ms'].append('') # a-move-speed
        # speeds['ms'].append('') # b-move-speed

        if warn_rapid:
            if not self.post.arguments.native_rapid_fallback:
                raise ValueError(
                    f"ToolController <{self.post._job.Label}>.<{tool_controller.Label}> did not set xy&z rapid speeds, and you specified --no-native-rapid-fallback. Set the rapid speeds. {self.location(path_command)}"
                )
            else:
                FreeCAD.Console.PrintWarning(
                    f'Using machine\'s rapid ("jog") for {" and ".join(warn_rapid)}, for ToolController <{self.post._job.Label}>.<{tool_controller.Label}>\n'
                )

        Path.Log.debug(f"setspeeds {speeds}")

        return native


gcode_insertmap()  # fixup DispatchMap
