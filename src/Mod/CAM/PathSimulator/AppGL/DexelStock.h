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
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#pragma once

#include "DexelCutter.h"
#include "DexelMesh.h"
#include "Shader.h"
#include "SimShapes.h"
#include "linmath.h"
#include <functional>
#include <vector>

namespace CAMSimulator
{

// The stock as dexels: three grids of rays, along X, Y and Z, each ray holding the stretches of
// its length that are still material. A cut subtracts a tool sweep from the rays it crosses,
// once, and the surface is meshed again only where cuts changed it, so a frame costs the same
// however far the program has run, and the stock is the same from any view.
//
// A ray keeps up to six stretches, a seventh closing its narrowest gap or dropping its thinnest
// stretch. A cut finds where each ray enters and leaves the sweep, the meshes the simulator
// draws it with, and takes that from the ray's stretches, the new ends taking the sweep's
// surface normal. It is done on the processor, by DexelCutter, the card only drawing the mesh,
// or on the graphics card, as the CAM preferences choose: there the rays live in float
// textures, the sweep drawn along each grid's axis and a pass over its footprint subtracting,
// OpenGL 2.1 and GLSL 1.20 as the simulator runs on.
class DexelStock
{
public:
    static constexpr int Intervals = 6;
    static constexpr int Ends = 2 * Intervals;

    ~DexelStock();

    // Set up from the stock's mesh, in the part's coordinates, the rays resolution apart. Needs
    // the GL context; false if the GL lacks what it takes, and the simulation keeps to CSG.
    bool Init(
        const std::vector<Vertex>& verts,
        const std::vector<unsigned short>& indices,
        float resolution
    );
    void Free();
    bool IsValid() const
    {
        return mValid;
    }

    // back to the stock as set up, nothing cut
    void Reset();

    // The rays as cut so far, kept on the GPU to come back to: going back restores the latest
    // before the place gone back to and cuts on from there, rather than from the start. The
    // snapshot's index, -1 if it could not be made.
    int SaveSnapshot();
    void RestoreSnapshot(int index);

    // Cut the volume drawSweep draws, the box [lo, hi] around it in the part's coordinates.
    // drawSweep draws with the current shader, which the cut sets up.
    void Cut(const vec3 lo, const vec3 hi, const std::function<void()>& drawSweep);

    // do the cuts gathered so far, when they are cut on the processor
    void Flush();
    int Pending() const
    {
        return mCpu ? mCutter.Pending() : 0;
    }
    bool OnProcessor() const
    {
        return mCpu;
    }

    // Bring the mesh up to the cuts so far: the rays they changed read back, the tiles they
    // touched meshed again, for about budgetMs. True when it is up to date.
    bool Sync(double budgetMs);

    // Draw the stock's surface into the bound geometry buffer: colour, position and normal, as
    // the mesh. pointScale is the pixels a millimetre covers at unit depth (perspective) or
    // anywhere (orthographic), for drawing the rays' ends as discs instead, to look at them.
    void Render(
        const mat4x4 view,
        const mat4x4 projection,
        float pointScale,
        bool perspective,
        const vec3 stockColor,
        const vec3 cutColor
    );

    float Resolution() const
    {
        return mRes;
    }

private:
    struct Grid
    {
        int axis = 0;  // the rays run along this axis
        int a = 1;     // the grid's columns along this one
        int b = 2;     // and its rows along this
        int w = 0;
        int h = 0;
        unsigned int tex[2][6] = {};  // two sets: ends 0-3, 4-7, 8-11, then their normals
        unsigned int fbo[2] = {};
        unsigned int initTex = 0;  // each ray's first stretch as set up, for the stock's colour
        unsigned int pointVbo = 0;
        int nPoints = 0;
        std::vector<float> initEnds;     // 12 a ray, for Reset
        std::vector<float> initNormals;  // packed, 12 a ray
        std::vector<float> ends;         // the rays as cut, read back for the mesh
        std::vector<float> normals;
    };

    bool InitOn(
        const std::vector<Vertex>& verts,
        const std::vector<unsigned short>& indices,
        float resolution,
        bool cpu
    );
    void UploadSet(Grid& g, int set);
    void ReadBack(Grid& g, const int rect[4]);
    void RenderPoints(
        const mat4x4 view,
        const mat4x4 projection,
        float pointScale,
        bool perspective,
        const vec3 stockColor,
        const vec3 cutColor
    );
    void SetupCapture(const Grid& g);
    bool GridRect(const Grid& g, const vec3 lo, const vec3 hi, int rect[4]) const;

    bool mValid = false;
    float mRes = 1.f;
    vec3 mOrigin = {0, 0, 0};
    int mDims[3] = {0, 0, 0};  // the lattice's nodes along each axis
    Grid mGrids[3];

    unsigned int mCaptureFbo = 0;
    unsigned int mCaptureTex[2] = {};  // nearest entry and farthest exit of the sweep, a ray
    unsigned int mCaptureDepth = 0;
    int mCaptureW = 0;
    int mCaptureH = 0;
    unsigned int mQuadVbo = 0;

    Shader mCaptureShader;
    Shader mSubtractShader;
    Shader mPointShader;
    Shader mMeshShader;
    Shader mCopyShader;

    struct Snapshot
    {
        unsigned int tex[3][6] = {};
        unsigned int fbo[3] = {};
    };
    void CopyGrid(const Grid& g, const unsigned int src[6], unsigned int dstFbo);
    void FreeSnapshots();
    void FreeSnapshotAt(size_t index);
    std::vector<Snapshot> mSnapshots;

    DexelMesher mMesher;

    // Cut on the processor, the default, or on the graphics card. On the processor the rays live
    // only in the copies the mesh reads, the card drawing just the mesh: its threads outpace a
    // modest card's passes, and it takes nothing from OpenGL but plain buffers.
    bool mCpu = true;
    DexelCutter mCutter;
    struct CpuSnapshot
    {
        std::vector<float> ends[3];
        std::vector<float> normals[3];
    };
    std::vector<CpuSnapshot> mCpuSnapshots;
    bool mPending = false;  // cuts since the mesh last caught up, in the box below
    vec3 mPendingLo = {0, 0, 0};
    vec3 mPendingHi = {0, 0, 0};
};

}  // namespace CAMSimulator
