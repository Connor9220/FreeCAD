# SPDX-License-Identifier: LGPL-2.1-or-later

from typing import Any, Final

from Base.Metadata import constmethod, export
from Base.Persistence import Persistence

@export(
    Include="Mod/CAM/App/Path.h",
    Twin="Toolpath",
    TwinPointer="Toolpath",
    Namespace="Path",
    Delete=True,
    Constructor=True,
)
class Path(Persistence):
    """
    Path([commands]): Represents a basic Gcode path
    commands (optional) is a list of Path commands

    Author: Yorik van Havre (yorik@uncreated.net)
    License: LGPL-2.1-or-later
    """

    def addCommands(self) -> Any:
        """adds a command or a list of commands at the end of the path"""
        ...

    def insertCommand(self) -> Any:
        """insertCommand(Command,[int]):
        adds a command at the given position or at the end of the path"""
        ...

    def deleteCommand(self) -> Any:
        """deleteCommand([int]):
        deletes the command found at the given position or from the end of the path"""
        ...

    def setFromGCode(self) -> Any:
        """sets the contents of the path from a gcode string"""
        ...

    def getClearedArea(self) -> Any:
        """Gets the area cleared when a tool of the specified diameter follows the gcode represented in the path, ignoring cleared space above zmax and path segments that don't affect space within the x/y space of bbox."""
        ...

    @constmethod
    def toGCode(self) -> Any:
        """returns a gcode string representing the path"""
        ...

    @constmethod
    def copy(self) -> Any:
        """returns a copy of this path"""
        ...

    @constmethod
    def getCycleTime(self) -> Any:
        """return the cycle time estimation for this path in s"""
        ...
    Length: Final[float]
    """the total length of this path in mm"""

    Size: Final[int]
    """the number of commands in this path"""

    Commands: list
    """the list of commands of this path"""

    Center: Any
    """the center position for all rotational parameters"""

    BoundBox: Final[Any]
    """the extent of this path"""
