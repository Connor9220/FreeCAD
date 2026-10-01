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

#include "AxisOverlay.h"

#include <algorithm>
#include <cmath>
#include <numbers>

// include this last as the defines can mess up other includes
#include "OpenGlWrapper.h"

namespace CAMSimulator
{

static const char* VertShaderOverlay = R"(
    #version 120

    layout(location = 0) attribute vec2 aPosition;
    layout(location = 1) attribute vec4 aColor;

    uniform vec2 screen;

    varying vec4 vColor;

    void main(void)
    {
        vColor = aColor;
        gl_Position = vec4(aPosition / screen * 2.0 - 1.0, 0.0, 1.0);
    }
)";

static const char* FragShaderOverlay = R"(
    #version 120

    varying vec4 vColor;

    void main()
    {
        gl_FragColor = vColor;
    }
)";

// the outline every stroke sits on
static const float OutlineColor[4] = {0.06f, 0.07f, 0.08f, 0.55f};

// Letters as strokes in a box 0.7 wide and 1 high, two points a stroke.
struct Stroke
{
    float x0, y0, x1, y1;
};
static const Stroke GlyphX[] = {{0, 0, 0.7f, 1}, {0, 1, 0.7f, 0}};
static const Stroke GlyphY[] = {{0, 1, 0.35f, 0.5f}, {0.7f, 1, 0.35f, 0.5f}, {0.35f, 0.5f, 0.35f, 0}};
static const Stroke GlyphZ[] = {{0, 1, 0.7f, 1}, {0.7f, 1, 0, 0}, {0, 0, 0.7f, 0}};
static const Stroke GlyphA[] = {{0, 0, 0.35f, 1}, {0.35f, 1, 0.7f, 0}, {0.15f, 0.4f, 0.55f, 0.4f}};
static const Stroke GlyphB[] = {
    {0, 0, 0, 1},
    {0, 1, 0.45f, 1},
    {0.45f, 1, 0.62f, 0.86f},
    {0.62f, 0.86f, 0.62f, 0.66f},
    {0.62f, 0.66f, 0.45f, 0.52f},
    {0, 0.52f, 0.5f, 0.52f},
    {0.5f, 0.52f, 0.7f, 0.37f},
    {0.7f, 0.37f, 0.7f, 0.16f},
    {0.7f, 0.16f, 0.5f, 0},
    {0.5f, 0, 0, 0},
};
static const Stroke GlyphC[] = {
    {0.7f, 0.85f, 0.5f, 1},
    {0.5f, 1, 0.2f, 1},
    {0.2f, 1, 0, 0.78f},
    {0, 0.78f, 0, 0.22f},
    {0, 0.22f, 0.2f, 0},
    {0.2f, 0, 0.5f, 0},
    {0.5f, 0, 0.7f, 0.15f},
};
static const Stroke GlyphPrime[] = {{0.95f, 1.05f, 0.85f, 0.75f}};

AxisOverlay::~AxisOverlay()
{
    Free();
}

void AxisOverlay::Free()
{
    GLDELETE_BUFFER(mVbo);
    mShader.Destroy();
    mShaderTried = false;
}

void AxisOverlay::SetColors(unsigned long x, unsigned long y, unsigned long z, unsigned long origin)
{
    const unsigned long packed[4] = {x, y, z, origin};
    for (int i = 0; i < 4; i++) {
        mColors[i][0] = ((packed[i] >> 24) & 0xff) / 255.f;
        mColors[i][1] = ((packed[i] >> 16) & 0xff) / 255.f;
        mColors[i][2] = ((packed[i] >> 8) & 0xff) / 255.f;
        mColors[i][3] = 1.f;
    }
}

void AxisOverlay::Begin(int width, int height, float scale)
{
    mWidth = std::max(width, 1);
    mHeight = std::max(height, 1);
    mScale = std::max(scale, 0.5f);
    mOutline.clear();
    mFill.clear();
}

bool AxisOverlay::Project(const mat4x4 clip, const vec3 p, float out[2], float* depth) const
{
    vec4 v = {p[0], p[1], p[2], 1};
    vec4 c;
    mat4x4_mul_vec4(c, clip, v);
    if (c[3] <= 1e-6f) {
        return false;  // behind the eye
    }
    out[0] = (c[0] / c[3] * 0.5f + 0.5f) * mWidth;
    out[1] = (c[1] / c[3] * 0.5f + 0.5f) * mHeight;
    if (depth) {
        *depth = c[2] / c[3];
    }
    return true;
}

void AxisOverlay::Segment(const float a[2], const float b[2], float width, const float color[4])
{
    const float dx = b[0] - a[0];
    const float dy = b[1] - a[1];
    const float len = std::sqrt(dx * dx + dy * dy);
    if (len < 1e-3f) {
        return;
    }
    // a quad across the line, and a wider one under it for the outline, reaching past the ends
    auto quad = [&](std::vector<Vtx>& out, float w, float extend, const float* col) {
        const float nx = -dy / len * w * 0.5f;
        const float ny = dx / len * w * 0.5f;
        const float ex = dx / len * extend;
        const float ey = dy / len * extend;
        const Vtx p0 {a[0] - ex + nx, a[1] - ey + ny, col[0], col[1], col[2], col[3]};
        const Vtx p1 {a[0] - ex - nx, a[1] - ey - ny, col[0], col[1], col[2], col[3]};
        const Vtx p2 {b[0] + ex - nx, b[1] + ey - ny, col[0], col[1], col[2], col[3]};
        const Vtx p3 {b[0] + ex + nx, b[1] + ey + ny, col[0], col[1], col[2], col[3]};
        out.insert(out.end(), {p0, p1, p2, p0, p2, p3});
    };
    const float o = 1.5f * mScale;
    quad(mOutline, width + 2 * o, o, OutlineColor);
    quad(mFill, width, 0, color);
}

void AxisOverlay::Triangle(const float p0[2], const float p1[2], const float p2[2], const float color[4])
{
    const float* p[3] = {p0, p1, p2};
    const float cx = (p0[0] + p1[0] + p2[0]) / 3;
    const float cy = (p0[1] + p1[1] + p2[1]) / 3;
    const float o = 1.5f * mScale;
    for (int i = 0; i < 3; i++) {
        // the outline: the triangle grown about its middle
        const float dx = p[i][0] - cx;
        const float dy = p[i][1] - cy;
        const float d = std::max(std::sqrt(dx * dx + dy * dy), 1e-3f);
        const float k = 1 + 2 * o / d;
        mOutline.push_back({cx + dx * k, cy + dy * k, OutlineColor[0], OutlineColor[1], OutlineColor[2], OutlineColor[3]});
    }
    for (int i = 0; i < 3; i++) {
        mFill.push_back({p[i][0], p[i][1], color[0], color[1], color[2], color[3]});
    }
}

void AxisOverlay::Arrow(const float from[2], const float to[2], float width, float head, const float color[4])
{
    const float dx = to[0] - from[0];
    const float dy = to[1] - from[1];
    const float len = std::sqrt(dx * dx + dy * dy);
    if (len < 1e-3f) {
        return;
    }
    // an axis seen end on is short: its head shrinks with it
    head = std::min(head, len * 0.6f);
    const float tx = dx / len;
    const float ty = dy / len;
    const float base[2] = {to[0] - tx * head, to[1] - ty * head};
    Segment(from, base, width, color);
    const float s0[2] = {base[0] - ty * head * 0.42f, base[1] + tx * head * 0.42f};
    const float s1[2] = {base[0] + ty * head * 0.42f, base[1] - tx * head * 0.42f};
    Triangle(to, s0, s1, color);
}

void AxisOverlay::Dot(const float at[2], float radius, const float color[4])
{
    const int n = 12;
    for (int i = 0; i < n; i++) {
        const float a0 = 2 * std::numbers::pi_v<float> * i / n;
        const float a1 = 2 * std::numbers::pi_v<float> * (i + 1) / n;
        const float p0[2] = {at[0] + radius * std::cos(a0), at[1] + radius * std::sin(a0)};
        const float p1[2] = {at[0] + radius * std::cos(a1), at[1] + radius * std::sin(a1)};
        Triangle(at, p0, p1, color);
    }
}

void AxisOverlay::Glyph(char c, const float at[2], float size, float width, const float color[4])
{
    const Stroke* strokes = nullptr;
    int n = 0;
    auto pick = [&](const Stroke* s, int count) {
        strokes = s;
        n = count;
    };
    switch (c) {
        case 'X':
            pick(GlyphX, std::size(GlyphX));
            break;
        case 'Y':
            pick(GlyphY, std::size(GlyphY));
            break;
        case 'Z':
            pick(GlyphZ, std::size(GlyphZ));
            break;
        case 'A':
            pick(GlyphA, std::size(GlyphA));
            break;
        case 'B':
            pick(GlyphB, std::size(GlyphB));
            break;
        case 'C':
            pick(GlyphC, std::size(GlyphC));
            break;
        case '\'':
            pick(GlyphPrime, std::size(GlyphPrime));
            break;
        default:
            return;
    }
    // centred on at
    for (int i = 0; i < n; i++) {
        const float a[2] = {at[0] + (strokes[i].x0 - 0.35f) * size, at[1] + (strokes[i].y0 - 0.5f) * size};
        const float b[2] = {at[0] + (strokes[i].x1 - 0.35f) * size, at[1] + (strokes[i].y1 - 0.5f) * size};
        Segment(a, b, width, color);
    }
}

void AxisOverlay::CornerTriad(const mat4x4 rot)
{
    // the upper right, clear of the controls along the bottom
    const float s = mScale;
    const float o[2] = {mWidth - 56 * s, mHeight - 56 * s};
    const float length = 36 * s;
    // the axes as the view turns them, the farthest drawn first
    int order[3] = {0, 1, 2};
    float dir[3][3];
    for (int i = 0; i < 3; i++) {
        for (int c = 0; c < 3; c++) {
            dir[i][c] = rot[i][c];
        }
    }
    std::sort(order, order + 3, [&](int a, int b) { return dir[a][2] < dir[b][2]; });
    for (int i : order) {
        const float tip[2] = {o[0] + dir[i][0] * length, o[1] + dir[i][1] * length};
        Arrow(o, tip, 2.5f * s, 9 * s, mColors[i]);
        // the letter beyond the tip, or beside the middle when the axis faces the eye
        float lx = dir[i][0];
        float ly = dir[i][1];
        const float l = std::sqrt(lx * lx + ly * ly);
        if (l < 0.25f) {
            lx = 0.7f;
            ly = 0.7f;
        }
        else {
            lx /= l;
            ly /= l;
        }
        const float at[2] = {tip[0] + lx * 10 * s, tip[1] + ly * 10 * s};
        Glyph("XYZ"[i], at, 11 * s, 1.8f * s, mColors[i]);
    }
    const float neutral[4] = {0.85f, 0.87f, 0.9f, 1};
    Dot(o, 2.5f * s, neutral);
}

void AxisOverlay::Triad(const mat4x4 clip, const vec3 origin, const vec3 axes[3], float length, bool local)
{
    const float s = mScale;
    float o[2];
    if (!Project(clip, origin, o)) {
        return;
    }
    float tips[3][2];
    float depth[3];
    bool ok[3];
    for (int i = 0; i < 3; i++) {
        vec3 p;
        for (int c = 0; c < 3; c++) {
            p[c] = origin[c] + axes[i][c] * length;
        }
        ok[i] = Project(clip, p, tips[i], &depth[i]);
    }
    int order[3] = {0, 1, 2};
    std::sort(order, order + 3, [&](int a, int b) { return depth[a] > depth[b]; });
    for (int i : order) {
        if (!ok[i]) {
            continue;
        }
        float color[4];
        for (int c = 0; c < 4; c++) {
            // a local frame in lighter shades of the same colours
            color[c] = local && c < 3 ? mColors[i][c] + (1 - mColors[i][c]) * 0.45f : mColors[i][c];
        }
        Arrow(o, tips[i], (local ? 2.f : 3.f) * s, (local ? 9.f : 11.f) * s, color);
        float lx = tips[i][0] - o[0];
        float ly = tips[i][1] - o[1];
        const float l = std::sqrt(lx * lx + ly * ly);
        if (l < 4 * s) {
            lx = 0.7f;
            ly = 0.7f;
        }
        else {
            lx /= l;
            ly /= l;
        }
        const float at[2] = {tips[i][0] + lx * 11 * s, tips[i][1] + ly * 11 * s};
        Glyph("XYZ"[i], at, 11 * s, 1.8f * s, color);
        if (local) {
            Glyph('\'', at, 11 * s, 1.5f * s, color);
        }
    }
    Dot(o, (local ? 3.f : 4.f) * s, mColors[3]);
}

void AxisOverlay::Origin(const mat4x4 clip, const vec3 origin)
{
    float o[2];
    if (Project(clip, origin, o)) {
        Dot(o, 4.f * mScale, mColors[3]);
    }
}

void AxisOverlay::Rotary(
    const mat4x4 clip,
    const vec3 pivot,
    const vec3 dir,
    float halfLength,
    float radius,
    int color,
    char name,
    bool line
)
{
    const float s = mScale;
    const float* col = mColors[std::clamp(color, 0, 2)];
    vec3 d;
    vec3_norm(d, dir);
    vec3 a, b;
    for (int c = 0; c < 3; c++) {
        a[c] = pivot[c] - d[c] * halfLength;
        b[c] = pivot[c] + d[c] * halfLength;
    }
    if (line) {
        float sa[2], sb[2];
        if (Project(clip, a, sa) && Project(clip, b, sb)) {
            const float faint[4] = {col[0], col[1], col[2], 0.8f};
            Segment(sa, sb, 1.5f * s, faint);
        }
    }
    // the arrow round the axis at its positive end: from u towards v is a positive turn
    vec3 e = {1, 0, 0};
    if (std::fabs(d[0]) > 0.6f) {
        e[0] = 0;
        e[1] = 1;
    }
    vec3 u, v;
    vec3_mul_cross(u, d, e);
    vec3_norm(u, u);
    vec3_mul_cross(v, d, u);
    const int n = 28;
    const float sweep = 1.5f * std::numbers::pi_v<float>;
    float prev[2] = {0, 0};
    float last[2] = {0, 0};
    bool havePrev = false;
    float start[2] = {0, 0};
    for (int i = 0; i <= n; i++) {
        const float t = sweep * i / n;
        vec3 p;
        for (int c = 0; c < 3; c++) {
            p[c] = b[c] + radius * (std::cos(t) * u[c] + std::sin(t) * v[c]);
        }
        float sp[2];
        if (!Project(clip, p, sp)) {
            havePrev = false;
            continue;
        }
        if (i == 0) {
            start[0] = sp[0];
            start[1] = sp[1];
        }
        if (havePrev && i < n) {
            Segment(prev, sp, 2.f * s, col);
        }
        if (havePrev && i == n) {
            // the last stretch an arrow, the way the turn goes
            float from[2] = {prev[0], prev[1]};
            const float dx = sp[0] - prev[0];
            const float dy = sp[1] - prev[1];
            const float l = std::sqrt(dx * dx + dy * dy);
            if (l > 1e-3f) {
                // reach back far enough for a head that reads
                from[0] = sp[0] - dx / l * std::max(l, 10 * s);
                from[1] = sp[1] - dy / l * std::max(l, 10 * s);
            }
            Arrow(from, sp, 2.f * s, 9 * s, col);
        }
        last[0] = sp[0];
        last[1] = sp[1];
        prev[0] = sp[0];
        prev[1] = sp[1];
        havePrev = true;
    }
    (void)last;
    // the letter by where the arrow starts, out from the axis
    float c0[2];
    if (Project(clip, b, c0)) {
        float lx = start[0] - c0[0];
        float ly = start[1] - c0[1];
        const float l = std::sqrt(lx * lx + ly * ly);
        if (l > 1e-3f) {
            lx /= l;
            ly /= l;
        }
        const float at[2] = {start[0] + lx * 12 * s, start[1] + ly * 12 * s};
        Glyph(name, at, 12 * s, 1.9f * s, col);
    }
}

void AxisOverlay::Draw()
{
    if (mFill.empty()) {
        return;
    }
    if (!mShaderTried) {
        mShaderTried = true;
        mShader.CompileShader("AxisOverlay", VertShaderOverlay, FragShaderOverlay);
        glGenBuffers(1, &mVbo);
    }
    if (!mShader.IsValid() || mVbo == 0) {
        return;
    }

    std::vector<Vtx> all;
    all.reserve(mOutline.size() + mFill.size());
    all.insert(all.end(), mOutline.begin(), mOutline.end());
    all.insert(all.end(), mFill.begin(), mFill.end());

    glViewport(0, 0, mWidth, mHeight);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glDisable(GL_STENCIL_TEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    mShader.Activate();
    const int loc = glGetUniformLocation(mShader.shaderId, "screen");
    if (loc >= 0) {
        glUniform2f(loc, (float)mWidth, (float)mHeight);
    }
    glBindBuffer(GL_ARRAY_BUFFER, mVbo);
    glBufferData(GL_ARRAY_BUFFER, all.size() * sizeof(Vtx), all.data(), GL_STREAM_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(Vtx), (void*)0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, sizeof(Vtx), (void*)(2 * sizeof(float)));
    glDrawArrays(GL_TRIANGLES, 0, (int)all.size());
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glEnable(GL_DEPTH_TEST);
}

}  // namespace CAMSimulator
