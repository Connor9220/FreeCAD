# -*- coding: utf-8 -*-
# This package aggregates tool bit shape classes.

import os
import json
import Path
from Path.Preferences import getAssetPath, getBuiltinAssetPath

# Import the base class and all concrete shape classes
from .models.base import ToolBitShape
from .models.ballend import ToolBitShapeBallend
from .models.bullnose import ToolBitShapeBullnose
from .models.chamfer import ToolBitShapeChamfer
from .models.custom import ToolBitShapeCustom
from .models.dovetail import ToolBitShapeDovetail
from .models.drill import ToolBitShapeDrill
from .models.endmill import ToolBitShapeEndmill
from .models.radius import ToolBitShapeRadius
from .models.probe import ToolBitShapeProbe
from .models.reamer import ToolBitShapeReamer
from .models.slittingsaw import ToolBitShapeSlittingSaw
from .models.tap import ToolBitShapeTap
from .models.threadmill import ToolBitShapeThreadMill
from .models.vbit import ToolBitShapeVBit
from .models.icon import (
    ToolBitShapeIcon,
    ToolBitShapePngIcon,
    ToolBitShapeSvgIcon,
)

# Paths for alias files
_INTERNAL_ALIASES_FILE = os.path.join(getBuiltinAssetPath(), "Shape", "shape_aliases.json")
_USER_ALIASES_FILE = os.path.join(getAssetPath(), "Tools", "Shape", "shape_aliases.json")


def _load_shape_aliases():
    """Load shape aliases from JSON file (user override or internal default)."""
    try:
        # Try user file first
        if os.path.isfile(_USER_ALIASES_FILE):
            with open(_USER_ALIASES_FILE, "r") as f:
                aliases = json.load(f)
            Path.Log.info(f"Loaded user shape aliases from {_USER_ALIASES_FILE}")
            return aliases

        # Fallback to internal file
        if os.path.isfile(_INTERNAL_ALIASES_FILE):
            with open(_INTERNAL_ALIASES_FILE, "r") as f:
                aliases = json.load(f)
            Path.Log.debug(f"Loaded default shape aliases from {_INTERNAL_ALIASES_FILE}")
            return aliases

    except Exception as e:
        Path.Log.error(f"Failed to load shape aliases: {e}")

    # Final fallback to empty dict
    return {}


def _apply_aliases_to_shape_classes():
    """Apply loaded aliases to all registered shape classes."""
    aliases_dict = _load_shape_aliases()

    # Map class names to actual classes
    shape_classes = {cls.name: cls for cls in ToolBitShape.__subclasses__()}

    for shape_name, aliases_list in aliases_dict.items():
        if shape_name in shape_classes:
            shape_class = shape_classes[shape_name]
            # Convert to tuple and assign
            shape_class.aliases = tuple(aliases_list)
            Path.Log.info(f"Applied aliases to {shape_name}: {aliases_list}")
        else:
            Path.Log.warning(f"Unknown shape class '{shape_name}' in aliases file")


# Load and apply aliases immediately after imports
_apply_aliases_to_shape_classes()

# A list of the name of each ToolBitShape
TOOL_BIT_SHAPE_NAMES = sorted([cls.name for cls in ToolBitShape.__subclasses__()])

# Define __all__ for explicit public interface
__all__ = [
    "ToolBitShape",
    "ToolBitShapeBallend",
    "ToolBitShapeBullnose",
    "ToolBitShapeChamfer",
    "ToolBitShapeCustom",
    "ToolBitShapeDovetail",
    "ToolBitShapeDrill",
    "ToolBitShapeEndmill",
    "ToolBitShapeRadius",
    "ToolBitShapeProbe",
    "ToolBitShapeReamer",
    "ToolBitShapeSlittingSaw",
    "ToolBitShapeTap",
    "ToolBitShapeThreadMill",
    "ToolBitShapeVBit",
    "TOOL_BIT_SHAPE_NAMES",
    "ToolBitShapeIcon",
    "ToolBitShapeSvgIcon",
    "ToolBitShapePngIcon",
]
