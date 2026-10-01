// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2024 Shai Seger <shaise at gmail>                       *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#pragma once

#include "linmath.h"
#include <cmath>
#include <string>
#include <vector>

namespace CAMSimulator
{

enum eEndMillType
{
    eEndmillFlat,
    eEndmillV,
    eEndmillBall,
    eEndmillFillet
};

enum eCmdType
{
    eNop,
    eMoveLiner,
    eRotateCW,
    eRotateCCW,
    eDril,
    eChangeTool
};

struct MillMotion
{
    eCmdType cmd = eNop;
    int tool = -1;
    float x = 0.0f, y = 0.0f, z = 0.0f;
    float i = 0.0f, j = 0.0f, k = 0.0f;
    float r = 0.0f;
    char retract_mode = '\0';
    float retract_z = 0;
    int frame = 0;       // index into the parser's frame table, 0 is the world
    float feed = 0;      // feed rate the motion is made at, in mm/s; 0 when not known
    bool rapid = false;  // a G0, or a canned cycle's rapid part
    int op = -1;         // index into the parser's operation names, -1 before the first
};

// A work plane frame: an operation's path is stored in its frame, with the tool along the frame's
// Z, and the frame places it in the world. Column-major, as linmath. The pose is the rotation the
// machine's rotary table gives the part while it cuts in the frame. Quaternions are x, y, z, w.
struct MillFrame
{
    mat4x4 mat;
    quat rot;
    quat pose;
    float indexRate = 0;  // degrees per second the rotaries turn into this frame; 0 when not known
    std::vector<float> angles;  // the table's rotary positions, degrees, as SimRotaryAxis lists them
};

// A stretch of the program's time, as shares of the whole: when a rotary axis turns, or, with
// axis -1, when the table turns as a whole
struct SimTimeSpan
{
    float start = 0;
    float end = 0;
    int axis = -1;
};

// A rotary axis of the machine's table. The simulation's list of them is in the order their
// rotations apply to the part, the first applied first.
struct SimRotaryAxis
{
    std::string name;
    vec3 axis = {0, 0, 1};
    float rate = 0;    // degrees per second
    int sequence = 0;  // the order the axes move in; axes with one value move together
};

static inline void MotionPosToVec(vec3 vec, const MillMotion& motion)
{
    vec[0] = motion.x;
    vec[1] = motion.y;
    vec[2] = motion.z;
}

// A point given in a frame, moved into the world
static inline void FramePosToWorld(vec3 out, const mat4x4 frame, float x, float y, float z)
{
    vec4 local = {x, y, z, 1.f};
    vec4 world;
    mat4x4_mul_vec4(world, frame, local);
    vec3_set(out, world[0], world[1], world[2]);
}

// The rotation of a frame alone, as the normal matrix of anything rendered in it
static inline void FrameRotation(mat4x4 rot, const mat4x4 frame)
{
    mat4x4_dup(rot, frame);
    rot[3][0] = rot[3][1] = rot[3][2] = 0.f;
}

// Whether two frames share the tool axis (their Z), so a straight move between them keeps the
// tool's orientation
static inline bool FramesShareToolAxis(const mat4x4 a, const mat4x4 b)
{
    const float eps = 1e-5f;
    return std::fabs(a[2][0] - b[2][0]) < eps && std::fabs(a[2][1] - b[2][1]) < eps
        && std::fabs(a[2][2] - b[2][2]) < eps;
}

static inline float QuatDot(const quat a, const quat b)
{
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
}

// The angle in radians of the rotation from one orientation to another
static inline float QuatAngle(const quat a, const quat b)
{
    return 2.f * std::acos(std::fmin(1.f, std::fabs(QuatDot(a, b))));
}

static inline void QuatSlerp(quat r, const quat a, const quat b, float t)
{
    float dot = QuatDot(a, b);
    float sign = 1.f;
    if (dot < 0.f) {
        dot = -dot;
        sign = -1.f;
    }
    float wa = 1.f - t;
    float wb = t;
    if (dot < 0.9995f) {
        const float theta = std::acos(dot);
        wa = std::sin(wa * theta) / std::sin(theta);
        wb = std::sin(wb * theta) / std::sin(theta);
    }
    for (int i = 0; i < 4; i++) {
        r[i] = wa * a[i] + sign * wb * b[i];
    }
    const float len = std::sqrt(QuatDot(r, r));
    for (int i = 0; i < 4; i++) {
        r[i] /= len;
    }
}

// Express a motion's position in another frame, keeping its place in the world
static inline void MotionToFrame(MillMotion& motion, const std::vector<MillFrame>& frames, int frame)
{
    if (motion.frame == frame) {
        return;
    }
    vec3 world;
    FramePosToWorld(world, frames[motion.frame].mat, motion.x, motion.y, motion.z);
    mat4x4 inv;
    mat4x4_invert(inv, frames[frame].mat);
    vec3 local;
    FramePosToWorld(local, inv, world[0], world[1], world[2]);
    motion.x = local[0];
    motion.y = local[1];
    motion.z = local[2];
    motion.frame = frame;
}

}  // namespace CAMSimulator
