# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026 The FreeCAD project association AISBL              *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public     *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Tool holders: the part of the spindle's nose a bit sticks out of.

A holder is kept as data, the outline that matters for cutting: points of
(radius, height) in millimetres, revolved about the tool's axis, from the face
the bit comes out of upward. A bit's stickout is measured from that face. The
outline is all a simulation or a collision check needs, so no model is opened
or recomputed to use one.

Holders ship with FreeCAD as .fcholder files in Mod/CAM/Tools/Holder, and the
CAM asset folder's Tools/Holder is read as well: a holder there replaces the
built-in one of the same name.
"""

import json
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import Path
from ..assets import Asset, AssetSerializer, AssetUri

FORMAT_VERSION = 1


class ToolHolder(Asset):
    asset_type: str = "toolholder"

    def __init__(
        self,
        id: str,
        name: str,
        profile: Sequence[Sequence[float]],
        collet: str = "",
        notes: str = "",
        source: str = "",
    ):
        super().__init__()
        self.id = id
        self.name = name
        self.profile: List[Tuple[float, float]] = [(float(r), float(z)) for r, z in profile]
        self.collet = collet
        self.notes = notes
        self.source = source
        self.validate()

    def get_id(self) -> str:
        return self.id

    @property
    def label(self) -> str:
        return self.name

    @property
    def height(self) -> float:
        """How far the holder reaches above the face the bit comes out of, in mm."""
        return max(z for _, z in self.profile)

    @property
    def diameter(self) -> float:
        """The holder's largest diameter, in mm."""
        return 2.0 * max(r for r, _ in self.profile)

    def validate(self):
        if len(self.profile) < 2:
            raise ValueError(f"Holder {self.id}: an outline needs at least two points")
        for r, z in self.profile:
            if r < 0:
                raise ValueError(f"Holder {self.id}: radius {r} is negative")
            if z < 0:
                raise ValueError(f"Holder {self.id}: height {z} is below the face the bit leaves")

    def to_dict(self) -> dict:
        data = {
            "version": FORMAT_VERSION,
            "name": self.name,
            "units": "mm",
            "profile": [[r, z] for r, z in self.profile],
        }
        if self.collet:
            data["collet"] = self.collet
        if self.notes:
            data["notes"] = self.notes
        if self.source:
            data["source"] = self.source
        return data

    @classmethod
    def from_dict(cls, id: str, data: dict) -> "ToolHolder":
        units = data.get("units", "mm")
        if units != "mm":
            raise ValueError(f"Holder {id}: outlines are in mm, not {units}")
        return cls(
            id=id,
            name=data.get("name", id),
            profile=data["profile"],
            collet=data.get("collet", ""),
            notes=data.get("notes", ""),
            source=data.get("source", ""),
        )


def dumps(data: dict) -> str:
    """A holder's JSON as its files keep it: indented, a point of the outline to a line."""
    points = data.get("profile", [])
    text = json.dumps({**data, "profile": "@profile@"}, indent=2)
    lines = ",\n".join(f"    {json.dumps(list(p))}" for p in points)
    return text.replace('"@profile@"', f"[\n{lines}\n  ]") + "\n"


class ToolHolderSerializer(AssetSerializer):
    for_class = ToolHolder
    extensions = (".fcholder",)
    mime_type = "application/x-freecad-toolholder"

    @classmethod
    def get_label(cls) -> str:
        return "FreeCAD Tool Holder"

    @classmethod
    def extract_dependencies(cls, data: bytes) -> List[AssetUri]:
        return []

    @classmethod
    def serialize(cls, asset: ToolHolder) -> bytes:
        return dumps(asset.to_dict()).encode("utf-8")

    @classmethod
    def deserialize(
        cls,
        data: bytes,
        id: str,
        dependencies: Optional[Mapping[AssetUri, Asset]],
    ) -> ToolHolder:
        return ToolHolder.from_dict(id, json.loads(data.decode("utf-8")))

    @classmethod
    def deep_deserialize(cls, data: bytes) -> ToolHolder:
        attrs = json.loads(data.decode("utf-8"))
        return ToolHolder.from_dict(attrs.get("id", attrs.get("name", "holder")), attrs)


def available_holders(asset_manager=None) -> Dict[str, ToolHolder]:
    """Every holder there is, by id: the built-in ones, and those in the CAM asset folder,
    which replace a built-in one of the same id. One that cannot be read is skipped, with a
    message saying why."""
    if asset_manager is None:
        from ..camassets import cam_assets as asset_manager

    holders: Dict[str, ToolHolder] = {}
    for store in ("builtin", "local"):
        try:
            uris = asset_manager.list_assets(asset_type=ToolHolder.asset_type, store=store)
        except Exception as e:
            Path.Log.debug(f"No tool holders in the {store} store: {e}")
            continue
        for uri in uris:
            try:
                holder = asset_manager.get(uri, store=store)
            except Exception as e:
                Path.Log.warning(f"Tool holder {uri} could not be read: {e}")
                continue
            holders[uri.asset_id] = holder
    return holders
