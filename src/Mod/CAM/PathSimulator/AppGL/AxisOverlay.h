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

#include "Shader.h"
#include "linmath.h"
#include <vector>

namespace CAMSimulator
{

// Axis indicators drawn over the simulation, in the colours FreeCAD gives its axes: the
// machine's axes in a corner, the work coordinates at the program's origin, the current
// operation's work plane, and each rotary axis with an arrow round it the way it turns. All
// of it is drawn flat on the screen, each stroke over a dark outline so it reads on any stock.
class AxisOverlay
{
public:
    ~AxisOverlay();

    // colours as FreeCAD keeps them, 0xRRGGBBAA
    void SetColors(unsigned long x, unsigned long y, unsigned long z, unsigned long origin);

    // start a frame of the given size in pixels, scale being pixels per screen point
    void Begin(int width, int height, float scale);

    // the machine's axes in the upper right corner, as rot (a view's rotation) turns them
    void CornerTriad(const mat4x4 rot);

    // a triad at origin with the given axes, in the space clip takes to the screen; a local
    // one is lighter and slimmer, its letters primed
    void Triad(const mat4x4 clip, const vec3 origin, const vec3 axes[3], float length, bool local);

    // the origin's dot alone
    void Origin(const mat4x4 clip, const vec3 origin);

    // a rotary axis: its line through pivot along dir, half the given length either way, and
    // at its positive end an arrow round it the way positive turns go, labelled with name;
    // colour is that of the linear axis it turns about, 0 to 2
    void Rotary(
        const mat4x4 clip,
        const vec3 pivot,
        const vec3 dir,
        float halfLength,
        float radius,
        int color,
        char name,
        bool line
    );

    // draw what the frame collected, over what is in the framebuffer
    void Draw();
    void Free();

private:
    struct Vtx
    {
        float x, y;
        float r, g, b, a;
    };
    bool Project(const mat4x4 clip, const vec3 p, float out[2], float* depth = nullptr) const;
    void Segment(const float a[2], const float b[2], float width, const float color[4]);
    void Arrow(const float from[2], const float to[2], float width, float head, const float color[4]);
    void Triangle(const float p0[2], const float p1[2], const float p2[2], const float color[4]);
    void Glyph(char c, const float at[2], float size, float width, const float color[4]);
    void Dot(const float at[2], float radius, const float color[4]);

    float mColors[4][4] = {
        {0.8f, 0.2f, 0.2f, 1},
        {0.2f, 0.8f, 0.2f, 1},
        {0.2f, 0.2f, 0.8f, 1},
        {0.98f, 0.84f, 0.16f, 1},
    };
    int mWidth = 1;
    int mHeight = 1;
    float mScale = 1;
    std::vector<Vtx> mOutline;
    std::vector<Vtx> mFill;
    Shader mShader;
    bool mShaderTried = false;
    unsigned int mVbo = 0;
};

}  // namespace CAMSimulator
