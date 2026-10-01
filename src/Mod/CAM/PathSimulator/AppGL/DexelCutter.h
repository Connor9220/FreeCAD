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

#include "SimShapes.h"
#include "linmath.h"
#include <memory>
#include <vector>

namespace CAMSimulator
{

// Cutting dexels on the processor: each cut's sweep, the triangles the simulator draws it with,
// is laid over each grid of rays to find where each ray enters and leaves it, and that is taken
// from the ray's stretches, as the graphics card's passes do. The cuts are gathered and done
// together: their sweeps found on as many threads as there are, a sweep not depending on the
// stock, then taken from the rays in order, each thread taking a band of rows of a grid, so no
// two threads touch one ray.
class DexelCutter
{
public:
    static constexpr int Ends = 12;

    // a grid of rays as the cutter changes them: ray (u, v) at u + v * w, twelve ends a ray and
    // their packed normals
    struct Grid
    {
        int axis = 0;
        int a = 1;
        int b = 2;
        int w = 0;
        int h = 0;
        float* ends = nullptr;
        float* normals = nullptr;
    };

    void Setup(const vec3 origin, float res, const int dims[3]);

    // a cut: its box, then the shapes its sweep is drawn with, each placed by model and its
    // normals turned by normalRot; the triangles are taken from them on the cutting threads
    void Begin(const vec3 lo, const vec3 hi);
    void Draw(const Shape& shape, const mat4x4 model, const mat4x4 normalRot);
    void End();

    int Pending() const
    {
        return (int)mCuts.size();
    }

    // do the cuts gathered, on the grids given
    void Flush(const Grid grids[3]);

private:
    struct Cut
    {
        vec3 lo;
        vec3 hi;
        size_t first = 0;  // its draws in mDraws
        size_t count = 0;
    };
    struct DrawCall
    {
        std::shared_ptr<const std::vector<Vertex>> verts;
        std::shared_ptr<const std::vector<GLushort>> indices;
        mat4x4 model;
        mat4x4 normalRot;
    };
    // where a cut's sweep covers a grid: its rectangle of rays and, for each, the nearest entry
    // and the farthest exit with the sweep's normals there
    struct Capture
    {
        int rect[4] = {0, 0, 0, 0};
        std::vector<float> tIn;
        std::vector<float> tOut;
        std::vector<float> nIn;  // the material's normal there, packed as the rays keep them
        std::vector<float> nOut;
    };
    bool GridRect(const Grid& g, const vec3 lo, const vec3 hi, int rect[4]) const;
    // the cut's triangles, 18 floats each: three corners and their normals, in the part's space,
    // those missing every grid left out
    void CutTriangles(const Cut& cut, std::vector<float>& tris) const;
    void CaptureCut(const Grid& g, const Cut& cut, const std::vector<float>& tris, Capture& cap) const;
    void ApplyRows(const Grid& g, int gridIndex, int row0, int row1) const;

    vec3 mOrigin = {0, 0, 0};
    float mRes = 1;
    vec3 mFar = {0, 0, 0};  // the far corner of the lattice
    std::vector<Cut> mCuts;
    std::vector<DrawCall> mDraws;
    std::vector<Capture> mCaptures;  // a cut's for each grid, three a cut
};

}  // namespace CAMSimulator
