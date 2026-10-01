# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from typing import Any

from Base.BaseClass import BaseClass
from Base.Placement import Placement
from Base.Rotation import Rotation
from Base.Metadata import export, no_args

from Gui import Document
from Part.App.TopoShape import TopoShape
from CAM.App.Command import Command

@export(
    Include="Mod/CAM/PathSimulator/AppGL/CAMSim.h",
    FatherInclude="Base/BaseClassPy.h",
    Namespace="CAMSimulator",
    Constructor=True,
    Delete=True,
)
class CAMSim(BaseClass):
    """
    FreeCAD python wrapper of CAMSimulator

          CAMSimulator.CAMSim():

          Create a path simulator object

    Author: Shai Seger (shaise_at_g-mail)
    License: LGPL-2.1-or-later
    """

    def BeginSimulation(self, stock: TopoShape, resolution: float) -> None:
        """
        Start a simulation process on a box shape stock with given resolution
        """
        ...

    def ResetSimulation(self, document: Document, /) -> None:
        """
        Clear the simulation and all gcode commands
        """
        ...

    def AddTool(self, shape: TopoShape, toolnumber: int, diameter: float, resolution: float) -> Any:
        """
        Set the shape of the tool to be used for simulation
        """
        ...

    def SetBaseShape(self, shape: TopoShape, resolution: float) -> None:
        """
        Set the shape of the base object of the job
        """
        ...

    def AddCommand(self, command: Command, /) -> Any:
        """
        Add a path command to the simulation.
        """
        ...

    def BeginOperation(self, name: str, /) -> None:
        """
        Mark where an operation starts: the commands added after it belong to the operation
        with the given name, until the next one starts.
        """
        ...

    def SetRotaryAxes(self, axes: list, /) -> None:
        """
        Set the rotary axes of the machine's table, as (direction: Vector, rate: float, sequence:
        int) in the order their rotations apply to the part, the first applied first. rate is in
        degrees per second; sequence is the order the axes move in, axes with one value moving
        together. SetFrame's angles give each axis's position, in this order.
        """
        ...

    def SetFrame(
        self,
        placement: Placement,
        pose: Rotation = ...,
        indexRate: float = ...,
        angles: list = ...,
        /,
    ) -> None:
        """
        Set the work plane frame the commands added after it are given in: the tool stands along
        the frame's Z and the placement moves the cuts into the world. The optional pose is the
        rotation the machine's rotary table gives the part while it cuts in the frame; the
        simulation turns the part by it. The optional indexRate is how fast, in degrees per
        second, the rotaries turn into the frame, for the time an index takes. The optional
        angles are the table's rotary positions for the pose, in degrees, in SetRotaryAxes'
        order: with them an index turns axis by axis.
        """
        ...
