// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 The FreeCAD project association AISBL              *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public     *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#pragma once

#include "linmath.h"
#include <unordered_map>
#include <vector>

namespace CAMSimulator
{

// The surface of a dexel stock as a mesh, by dual contouring. The rays of the three grids cross
// at the nodes of one lattice, so each edge of the lattice lies on a ray: where the material
// starts or stops along it is where the surface crosses the edge, with the surface's normal
// there. Each cell the surface passes through gets one vertex, the point best fitting the
// crossings of its edges, which keeps sharp edges sharp, and each edge the surface crosses
// joins the four cells around it with a quad.
//
// The lattice is meshed in tiles, so a cut remeshes only the tiles it touched.
class DexelMesher
{
public:
    static constexpr int Tile = 32;  // cells a side

    // a grid of rays as the mesher reads it: ray (u, v) at u + v * w, twelve ends and their
    // packed normals a ray, the ends the stock was set up with alongside
    struct Grid
    {
        int axis = 0;
        int a = 1;
        int b = 2;
        int w = 0;
        int h = 0;
        const float* ends = nullptr;
        const float* normals = nullptr;
        const float* initEnds = nullptr;
        int stride = 12;  // ends a ray: twelve, or more where a ray crosses more stretches
    };

    ~DexelMesher();

    void Setup(const vec3 origin, float res, const int dims[3]);
    void Free();

    // the tiles a change in [lo, hi] reaches, to mesh again
    void MarkDirty(const vec3 lo, const vec3 hi);
    void MarkAllDirty();
    bool HasDirty() const
    {
        return !mDirty.empty();
    }

    // Mesh the dirty tiles from the grids, for about budgetMs at the most. True when none is
    // left. Needs the GL context, for the tiles' buffers.
    bool Update(const Grid grids[3], double budgetMs);

    // Draw every tile with the bound shader: position, normal and a stock flag as attributes
    // 0, 1 and 2.
    void Render() const;

private:
    struct TileMesh
    {
        unsigned int vbo = 0;
        unsigned int ibo = 0;
        int nIndices = 0;
    };
    struct Built
    {
        int key = 0;
        std::vector<float> verts;  // 7 a vertex: position, normal, stock
        std::vector<unsigned short> indices;
    };

    int TileKey(int tx, int ty, int tz) const
    {
        return (tz * mTiles[1] + ty) * mTiles[0] + tx;
    }
    void BuildTile(int key, const Grid grids[3], Built& out) const;
    void Upload(Built& built);

    vec3 mOrigin = {0, 0, 0};
    float mRes = 1;
    int mDims[3] = {0, 0, 0};
    int mTiles[3] = {0, 0, 0};
    std::unordered_map<int, TileMesh> mMeshes;
    std::vector<char> mDirtyFlag;
    std::vector<int> mDirty;
};

}  // namespace CAMSimulator
