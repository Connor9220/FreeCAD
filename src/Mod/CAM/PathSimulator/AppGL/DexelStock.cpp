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

#include "DexelStock.h"

#include <App/Application.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <thread>
#include <unordered_map>

// include this last as the defines can mess up other includes
#include "OpenGlWrapper.h"

namespace CAMSimulator
{

// an end that is not there: past every real one, so the ends of a ray stay in order
constexpr float NoEnd = 1e30f;

// ---------------------------------------------------------------------------------------------
// Shaders, GLSL 1.20

// The capture: a sweep drawn along a grid's axis, each fragment the coordinate along the axis
// where the ray meets the sweep's surface and the material's normal there, which faces into the
// tool. The nearest is kept in one pass, the farthest in another.
static const char* VertShaderDexelCapture = R"(
    #version 120

    layout(location = 0) attribute vec3 aPosition;
    layout(location = 1) attribute vec3 aNormal;

    uniform mat4 model;
    uniform mat4 normalRot;
    uniform mat4 view;
    uniform mat4 projection;
    uniform vec3 dirD;

    varying float vT;
    varying vec3 vN;

    void main(void)
    {
        vec4 wp = model * vec4(aPosition, 1.0);
        vT = dot(wp.xyz, dirD);
        vN = mat3(normalRot) * aNormal;
        gl_Position = projection * view * wp;
    }
)";

static const char* FragShaderDexelCapture = R"(
    #version 120

    varying float vT;
    varying vec3 vN;

    // a unit vector as one float: octahedral, 12 bits a coordinate
    float packNormal(vec3 n)
    {
        n /= (abs(n.x) + abs(n.y) + abs(n.z));
        vec2 e = n.xy;
        if (n.z < 0.0) {
            e = (1.0 - abs(n.yx)) * vec2(n.x >= 0.0 ? 1.0 : -1.0, n.y >= 0.0 ? 1.0 : -1.0);
        }
        vec2 q = floor((e * 0.5 + 0.5) * 4095.0 + 0.5);
        return q.x * 4096.0 + q.y;
    }

    void main()
    {
        // the tool's surface faces out of the tool; the material's faces into it
        gl_FragColor = vec4(vT, packNormal(-normalize(vN)), 0.0, 1.0);
    }
)";

// The subtraction: each ray's stretches less the sweep's [entry, exit], the new ends taking the
// sweep's normals there. Runs over the sweep's footprint, one fragment a ray.
static const char* VertShaderDexelQuad = R"(
    #version 120

    layout(location = 0) attribute vec2 aPosition;
    layout(location = 1) attribute vec2 aTexCoord;

    void main(void)
    {
        gl_Position = vec4(aPosition.x, aPosition.y, 0.0, 1.0);
    }
)";

static const char* FragShaderDexelSubtract = R"(
    #version 120

    uniform sampler2D End0;
    uniform sampler2D End1;
    uniform sampler2D End2;
    uniform sampler2D Nrm0;
    uniform sampler2D Nrm1;
    uniform sampler2D Nrm2;
    uniform sampler2D CapIn;
    uniform sampler2D CapOut;
    uniform vec2 gridSize;
    uniform vec2 captureSize;
    uniform float sliver;  // a piece of a stretch thinner than this left by a cut goes

    void main()
    {
        // Much of the footprint is rays the sweep misses: those are left as they are, read
        // as little as can be and written not at all, here and in the copy back.
        vec2 uv = gl_FragCoord.xy / gridSize;
        vec2 cuv = gl_FragCoord.xy / captureSize;
        vec4 capIn = texture2D(CapIn, cuv);
        vec4 capOut = texture2D(CapOut, cuv);
        if (!(capIn.w > 0.5 && capOut.w > 0.5 && capIn.x < capOut.x)) {
            discard;
        }
        vec4 e0 = texture2D(End0, uv);
        vec4 e1 = texture2D(End1, uv);
        vec4 e2 = texture2D(End2, uv);
        vec4 n0 = texture2D(Nrm0, uv);
        vec4 n1 = texture2D(Nrm1, uv);
        vec4 n2 = texture2D(Nrm2, uv);

        float e[12];
        float n[12];
        e[0] = e0.x; e[1] = e0.y; e[2] = e0.z; e[3] = e0.w;
        e[4] = e1.x; e[5] = e1.y; e[6] = e1.z; e[7] = e1.w;
        e[8] = e2.x; e[9] = e2.y; e[10] = e2.z; e[11] = e2.w;
        n[0] = n0.x; n[1] = n0.y; n[2] = n0.z; n[3] = n0.w;
        n[4] = n1.x; n[5] = n1.y; n[6] = n1.z; n[7] = n1.w;
        n[8] = n2.x; n[9] = n2.y; n[10] = n2.z; n[11] = n2.w;

        // room for one stretch more than a ray keeps: a cut through the middle of a stretch
        // leaves two
        float o[14];
        float on[14];
        for (int i = 0; i < 14; i++) {
            o[i] = 1e30;
            on[i] = 0.0;
        }

        bool covered = capIn.w > 0.5 && capOut.w > 0.5 && capIn.x < capOut.x;
        float t0 = capIn.x;
        float t1 = capOut.x;
        int c = 0;
        for (int k = 0; k < 6; k++) {
            float s = e[2 * k];
            float f = e[2 * k + 1];
            if (s > 1e29) {
                continue;
            }
            float ns = n[2 * k];
            float nf = n[2 * k + 1];
            // up to two stretches out of each: before the sweep, and after it
            float a0 = s, a1 = f, an0 = ns, an1 = nf;
            float b0 = 1e30, b1 = 1e30, bn0 = 0.0, bn1 = 0.0;
            bool keepA = true;
            if (covered && f > t0 && s < t1) {
                keepA = s < t0 - sliver;
                a1 = t0;
                an1 = capIn.y;
                if (f > t1 + sliver) {
                    b0 = t1;
                    b1 = f;
                    bn0 = capOut.y;
                    bn1 = nf;
                }
            }
            for (int i = 0; i < 14; i += 2) {
                if (keepA && i == c) {
                    o[i] = a0; o[i + 1] = a1; on[i] = an0; on[i + 1] = an1;
                }
                if (b0 < 1e29 && i == c + (keepA ? 2 : 0)) {
                    o[i] = b0; o[i + 1] = b1; on[i] = bn0; on[i + 1] = bn1;
                }
            }
            c += (keepA ? 2 : 0) + (b0 < 1e29 ? 2 : 0);
        }

        // Seven stretches will not fit: the least of the ray goes, whichever is smaller of the
        // thinnest stretch and the narrowest gap, filled. A ray along a spiral's grooves keeps
        // its true outer ends and only loses detail finer than the rest.
        int drop = 14;
        if (c > 12) {
            float best = 1e30;
            for (int k = 0; k < 7; k++) {
                float len = o[2 * k + 1] - o[2 * k];
                if (len < best) {
                    best = len;
                    drop = 2 * k;
                }
                if (k < 6) {
                    float gap = o[2 * k + 2] - o[2 * k + 1];
                    if (gap < best) {
                        best = gap;
                        drop = 2 * k + 1;
                    }
                }
            }
        }
        float r[12];
        float rn[12];
        for (int i = 0; i < 12; i++) {
            r[i] = i < drop ? o[i] : o[i + 2];
            rn[i] = i < drop ? on[i] : on[i + 2];
        }

        gl_FragData[0] = vec4(r[0], r[1], r[2], r[3]);
        gl_FragData[1] = vec4(r[4], r[5], r[6], r[7]);
        gl_FragData[2] = vec4(r[8], r[9], r[10], r[11]);
        gl_FragData[3] = vec4(rn[0], rn[1], rn[2], rn[3]);
        gl_FragData[4] = vec4(rn[4], rn[5], rn[6], rn[7]);
        gl_FragData[5] = vec4(rn[8], rn[9], rn[10], rn[11]);
    }
)";

// The copy back: the second set into the first, over the footprint, all six targets in one pass.
static const char* FragShaderDexelCopy = R"(
    #version 120

    uniform sampler2D Src0;
    uniform sampler2D Src1;
    uniform sampler2D Src2;
    uniform sampler2D Src3;
    uniform sampler2D Src4;
    uniform sampler2D Src5;
    uniform sampler2D CapIn;
    uniform sampler2D CapOut;
    uniform vec2 gridSize;
    uniform vec2 captureSize;
    uniform float cutting;  // 1 when copying back a cut: only the rays its sweep covers

    void main()
    {
        vec2 uv = gl_FragCoord.xy / gridSize;
        if (cutting > 0.5) {
            // the rays the subtraction wrote, those the sweep covers
            vec2 cuv = gl_FragCoord.xy / captureSize;
            vec4 capIn = texture2D(CapIn, cuv);
            vec4 capOut = texture2D(CapOut, cuv);
            if (!(capIn.w > 0.5 && capOut.w > 0.5 && capIn.x < capOut.x)) {
                discard;
            }
        }
        gl_FragData[0] = texture2D(Src0, uv);
        gl_FragData[1] = texture2D(Src1, uv);
        gl_FragData[2] = texture2D(Src2, uv);
        gl_FragData[3] = texture2D(Src3, uv);
        gl_FragData[4] = texture2D(Src4, uv);
        gl_FragData[5] = texture2D(Src5, uv);
    }
)";

// The surface: a point for each end of each stretch of each ray, a disc on the surface seen
// from the camera, into the geometry buffer as the meshes go.
static const char* VertShaderDexelPoints = R"(
    #version 120

    layout(location = 0) attribute float aIndex;

    uniform sampler2D End0;
    uniform sampler2D End1;
    uniform sampler2D End2;
    uniform sampler2D Nrm0;
    uniform sampler2D Nrm1;
    uniform sampler2D Nrm2;
    uniform sampler2D InitTex;
    uniform vec2 gridSize;
    uniform vec3 origin;
    uniform vec3 dirA;
    uniform vec3 dirB;
    uniform vec3 dirD;
    uniform float res;
    uniform mat4 view;
    uniform mat4 projection;
    uniform float pointScale;
    uniform float perspective;
    uniform vec3 stockColor;
    uniform vec3 cutColor;

    varying vec3 vPos;
    varying vec3 vNormal;
    varying vec3 vColor;
    varying float vRadius;

    float pick(vec4 v, float c)
    {
        return c < 0.5 ? v.x : (c < 1.5 ? v.y : (c < 2.5 ? v.z : v.w));
    }

    vec3 unpackNormal(float p)
    {
        float qx = floor(p / 4096.0);
        float qy = p - qx * 4096.0;
        vec2 e = vec2(qx, qy) / 4095.0 * 2.0 - 1.0;
        vec3 n = vec3(e, 1.0 - abs(e.x) - abs(e.y));
        if (n.z < 0.0) {
            n.xy = (1.0 - abs(n.yx)) * vec2(n.x >= 0.0 ? 1.0 : -1.0, n.y >= 0.0 ? 1.0 : -1.0);
        }
        return normalize(n);
    }

    void main(void)
    {
        float ray = floor(aIndex / 12.0);
        float slot = aIndex - ray * 12.0;
        float u = mod(ray, gridSize.x);
        float v = floor(ray / gridSize.x);
        vec2 uv = (vec2(u, v) + 0.5) / gridSize;
        float tex = floor(slot / 4.0);
        float comp = slot - tex * 4.0;

        vec4 e = tex < 0.5 ? texture2DLod(End0, uv, 0.0)
            : (tex < 1.5 ? texture2DLod(End1, uv, 0.0) : texture2DLod(End2, uv, 0.0));
        float t = pick(e, comp);
        if (t > 1e29) {
            // no end here: off the screen
            gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
            gl_PointSize = 1.0;
            vPos = vec3(0.0);
            vNormal = vec3(0.0, 0.0, 1.0);
            vColor = vec3(0.0);
            vRadius = 0.0;
            return;
        }
        vec4 nv = tex < 0.5 ? texture2DLod(Nrm0, uv, 0.0)
            : (tex < 1.5 ? texture2DLod(Nrm1, uv, 0.0) : texture2DLod(Nrm2, uv, 0.0));
        vec3 n = unpackNormal(pick(nv, comp));

        // Each surface is drawn by the grid whose rays meet it most squarely; the others only
        // graze it, their ends sparse and their normals poor. A little overlap where two are
        // nearly as good, so no seam opens between them.
        vec3 an = abs(n);
        float nd = abs(dot(n, dirD));
        if (nd < 0.85 * max(an.x, max(an.y, an.z))) {
            gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
            gl_PointSize = 1.0;
            vPos = vec3(0.0);
            vNormal = vec3(0.0, 0.0, 1.0);
            vColor = vec3(0.0);
            vRadius = 0.0;
            return;
        }

        // t is the coordinate along the ray itself, not from the origin
        vec3 p = origin - dirD * dot(origin, dirD) + dirA * ((u + 0.5) * res)
            + dirB * ((v + 0.5) * res) + dirD * t;
        vec4 vp = view * vec4(p, 1.0);
        gl_Position = projection * vp;
        // a disc reaching past the cell's corners, the cells drawn out along the slope
        vRadius = res * max(0.9, 0.6 * sqrt(1.0 + 1.0 / (nd * nd)));
        float pixels = perspective > 0.5 ? pointScale / max(-vp.z, 1e-3) : pointScale;
        gl_PointSize = 2.0 * vRadius * pixels;
        vPos = vp.xyz;
        vNormal = mat3(view) * n;

        // an end where the stock was set up is the stock's own surface
        vec2 first = texture2DLod(InitTex, uv, 0.0).xy;
        bool stock = abs(t - first.x) < 0.25 * res || abs(t - first.y) < 0.25 * res;
        vColor = stock ? stockColor : cutColor;
    }
)";

static const char* FragShaderDexelPoints = R"(
    #version 120

    uniform mat4 projection;

    varying vec3 vPos;
    varying vec3 vNormal;
    varying vec3 vColor;
    varying float vRadius;

    void main()
    {
        // The point is a disc lying on the surface: of the square drawn, only the ellipse the
        // disc makes on screen, each fragment at its depth on the disc. A side face's discs
        // then stand on the edge rather than spread over the top.
        vec2 pc = gl_PointCoord * 2.0 - 1.0;
        vec2 d = vec2(pc.x, -pc.y) * vRadius;
        vec3 n = normalize(vNormal);
        if (n.z < -0.3) {
            discard;  // facing away: what is in front covers it
        }
        float nz = max(n.z, 0.15);
        float dz = -(n.x * d.x + n.y * d.y) / nz;
        if (dot(d, d) + dz * dz > vRadius * vRadius) {
            discard;
        }
        vec3 p = vPos + vec3(d, dz);
        vec4 clip = projection * vec4(p, 1.0);
        gl_FragDepth = clip.z / clip.w * 0.5 + 0.5;

        gl_FragData[0] = vec4(vColor, 1.0);
        gl_FragData[1] = vec4(p, 0.0);
        gl_FragData[2] = vec4(n, 0.0);
    }
)";

// The surface as a mesh, into the geometry buffer as the other meshes go: the stock's own faces
// in its colour, the cut ones in theirs.
static const char* VertShaderDexelMesh = R"(
    #version 120

    layout(location = 0) attribute vec3 aPosition;
    layout(location = 1) attribute vec3 aNormal;
    layout(location = 2) attribute float aStock;

    uniform mat4 view;
    uniform mat4 projection;
    uniform vec3 stockColor;
    uniform vec3 cutColor;

    varying vec3 Position;
    varying vec3 Normal;
    varying vec3 Color;

    void main(void)
    {
        vec4 vp = view * vec4(aPosition, 1.0);
        Position = vp.xyz;
        Normal = mat3(view) * aNormal;
        Color = aStock > 0.5 ? stockColor : cutColor;
        gl_Position = projection * vp;
    }
)";

static const char* FragShaderDexelMesh = R"(
    #version 120

    varying vec3 Position;
    varying vec3 Normal;
    varying vec3 Color;

    void main()
    {
        gl_FragData[0] = vec4(Color, 1.0);
        gl_FragData[1] = vec4(Position, 0.0);
        gl_FragData[2] = vec4(normalize(Normal), 0.0);
    }
)";

// ---------------------------------------------------------------------------------------------
// helpers

// A uniform's location, looked up once for each shader and name: the names are literals, so
// their addresses do for keys. A cut sets some thirty uniforms; asking the driver each time
// cost more than the cut's own drawing.
// cleared when the shaders go, a new program possibly taking an old one's id
static std::unordered_map<unsigned long long, int> gUniformCache;

static int uniformAt(const Shader& s, const char* name)
{
    auto& cache = gUniformCache;
    const unsigned long long key = ((unsigned long long)s.shaderId << 48)
        ^ (unsigned long long)(uintptr_t)name;
    const auto it = cache.find(key);
    if (it != cache.end()) {
        return it->second;
    }
    const int loc = glGetUniformLocation(s.shaderId, name);
    cache.emplace(key, loc);
    return loc;
}

static void setUniform1i(const Shader& s, const char* name, int v)
{
    const int loc = uniformAt(s, name);
    if (loc >= 0) {
        glUniform1i(loc, v);
    }
}

static void setUniform1f(const Shader& s, const char* name, float v)
{
    const int loc = uniformAt(s, name);
    if (loc >= 0) {
        glUniform1f(loc, v);
    }
}

static void setUniform2f(const Shader& s, const char* name, float x, float y)
{
    const int loc = uniformAt(s, name);
    if (loc >= 0) {
        glUniform2f(loc, x, y);
    }
}

static void setUniform3f(const Shader& s, const char* name, const vec3 v)
{
    const int loc = uniformAt(s, name);
    if (loc >= 0) {
        glUniform3fv(loc, 1, v);
    }
}

static void setUniformMat(const Shader& s, const char* name, const mat4x4 m)
{
    const int loc = uniformAt(s, name);
    if (loc >= 0) {
        glUniformMatrix4fv(loc, 1, GL_FALSE, (const GLfloat*)m);
    }
}

// the same packing as the capture shader's, for the stock as set up
static float packNormal(float x, float y, float z)
{
    const float sum = std::fabs(x) + std::fabs(y) + std::fabs(z);
    if (sum <= 0) {
        return 0;
    }
    x /= sum;
    y /= sum;
    z /= sum;
    float ex = x;
    float ey = y;
    if (z < 0) {
        ex = (1.f - std::fabs(y)) * (x >= 0 ? 1.f : -1.f);
        ey = (1.f - std::fabs(x)) * (y >= 0 ? 1.f : -1.f);
    }
    const float qx = std::floor((ex * 0.5f + 0.5f) * 4095.f + 0.5f);
    const float qy = std::floor((ey * 0.5f + 0.5f) * 4095.f + 0.5f);
    return qx * 4096.f + qy;
}

static unsigned int makeFloatTexture(int w, int h, const float* data)
{
    unsigned int tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, w, h, 0, GL_RGBA, GL_FLOAT, data);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return tex;
}

static const unsigned int ColorAttachments[6] = {
    GL_COLOR_ATTACHMENT0,
    GL_COLOR_ATTACHMENT1,
    GL_COLOR_ATTACHMENT2,
    GL_COLOR_ATTACHMENT3,
    GL_COLOR_ATTACHMENT4,
    GL_COLOR_ATTACHMENT5,
};

// ---------------------------------------------------------------------------------------------

DexelStock::~DexelStock()
{
    Free();
}

void DexelStock::Free()
{
    for (Grid& g : mGrids) {
        for (int set = 0; set < 2; set++) {
            for (unsigned int& t : g.tex[set]) {
                GLDELETE_TEXTURE(t);
            }
            GLDELETE_FRAMEBUFFER(g.fbo[set]);
        }
        GLDELETE_TEXTURE(g.initTex);
        GLDELETE_BUFFER(g.pointVbo);
        g.initEnds.clear();
        g.initNormals.clear();
        g.ends.clear();
        g.normals.clear();
        g.nPoints = 0;
    }
    FreeSnapshots();
    mMesher.Free();
    mCutter.Setup(mOrigin, mRes, mDims);
    mMeshShader.Destroy();
    mCopyShader.Destroy();
    mPending = false;
    GLDELETE_FRAMEBUFFER(mCaptureFbo);
    GLDELETE_TEXTURE(mCaptureTex[0]);
    GLDELETE_TEXTURE(mCaptureTex[1]);
    GLDELETE_RENDERBUFFER(mCaptureDepth);
    GLDELETE_BUFFER(mQuadVbo);
    mCaptureShader.Destroy();
    mSubtractShader.Destroy();
    mPointShader.Destroy();
    gUniformCache.clear();
    mValid = false;
}

bool DexelStock::Init(
    const std::vector<Vertex>& verts,
    const std::vector<unsigned short>& indices,
    float resolution
)
{
    // Where to cut, as the CAM preferences say: on the processor or the graphics card, or, by
    // default, the processor when it has the threads for it. A card that cannot take the
    // cutting leaves it to the processor.
    const long choice = App::GetApplication()
                            .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/CAM")
                            ->GetInt("SimulatorDexelCutting", 0);
    bool cpu = choice == 1 || (choice == 0 && std::thread::hardware_concurrency() >= 8);
    if (const char* forced = std::getenv("CAMSIM_DEXEL_GPU")) {
        cpu = forced[0] != '1';
    }
    return InitOn(verts, indices, resolution, cpu)
        || (!cpu && InitOn(verts, indices, resolution, true));
}

bool DexelStock::InitOn(
    const std::vector<Vertex>& verts,
    const std::vector<unsigned short>& indices,
    float resolution,
    bool cpu
)
{
    Free();
    if (verts.empty() || indices.size() < 3 || resolution <= 0) {
        return false;
    }
    mCpu = cpu;

    // what the card takes: six float colour targets for the subtraction
    GLint maxDrawBuffers = 0;
    glGetIntegerv(GL_MAX_DRAW_BUFFERS, &maxDrawBuffers);
    if (!mCpu && maxDrawBuffers < 6) {
        return false;
    }

    // the grids, a cell beyond the stock all round
    mRes = resolution;
    vec3 lo = {1e30f, 1e30f, 1e30f};
    vec3 hi = {-1e30f, -1e30f, -1e30f};
    for (const Vertex& v : verts) {
        const float p[3] = {v.x, v.y, v.z};
        for (int c = 0; c < 3; c++) {
            lo[c] = std::min(lo[c], p[c]);
            hi[c] = std::max(hi[c], p[c]);
        }
    }
    int dims[3];
    for (int c = 0; c < 3; c++) {
        mOrigin[c] = lo[c] - mRes;
        dims[c] = (int)std::ceil((hi[c] - lo[c]) / mRes) + 2;
    }
    GLint maxTex = 0;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maxTex);
    for (int c = 0; c < 3; c++) {
        if (dims[c] > maxTex) {
            return false;
        }
    }

    for (int d = 0; d < 3; d++) {
        Grid& g = mGrids[d];
        g.axis = d;
        g.a = (d + 1) % 3;
        g.b = (d + 2) % 3;
        g.w = dims[g.a];
        g.h = dims[g.b];
        const size_t rays = (size_t)g.w * g.h;

        // Each ray's crossings of the stock's surface, from the mesh: where it goes in and
        // where it comes out, with the surface's normal there.
        struct Hit
        {
            float t;
            float n[3];
            bool enter;
        };
        std::vector<std::vector<Hit>> hits(rays);
        for (size_t k = 0; k + 2 < indices.size(); k += 3) {
            const Vertex* v[3] = {&verts[indices[k]], &verts[indices[k + 1]], &verts[indices[k + 2]]};
            float pa[3], pb[3], pd[3];
            for (int i = 0; i < 3; i++) {
                const float p[3] = {v[i]->x, v[i]->y, v[i]->z};
                pa[i] = p[g.a];
                pb[i] = p[g.b];
                pd[i] = p[d];
            }
            const float area = (pa[1] - pa[0]) * (pb[2] - pb[0]) - (pb[1] - pb[0]) * (pa[2] - pa[0]);
            if (std::fabs(area) < 1e-12f) {
                continue;  // edge on to the rays
            }
            const float minA = std::min({pa[0], pa[1], pa[2]});
            const float maxA = std::max({pa[0], pa[1], pa[2]});
            const float minB = std::min({pb[0], pb[1], pb[2]});
            const float maxB = std::max({pb[0], pb[1], pb[2]});
            const int i0 = std::max(0, (int)std::floor((minA - mOrigin[g.a]) / mRes - 0.5f));
            const int i1 = std::min(g.w - 1, (int)std::ceil((maxA - mOrigin[g.a]) / mRes - 0.5f));
            const int j0 = std::max(0, (int)std::floor((minB - mOrigin[g.b]) / mRes - 0.5f));
            const int j1 = std::min(g.h - 1, (int)std::ceil((maxB - mOrigin[g.b]) / mRes - 0.5f));
            for (int j = j0; j <= j1; j++) {
                const float cb = mOrigin[g.b] + (j + 0.5f) * mRes;
                for (int i = i0; i <= i1; i++) {
                    const float ca = mOrigin[g.a] + (i + 0.5f) * mRes;
                    float w[3];
                    for (int e = 0; e < 3; e++) {
                        const int p = (e + 1) % 3;
                        const int q = (e + 2) % 3;
                        w[e] = ((pa[q] - pa[p]) * (cb - pb[p]) - (pb[q] - pb[p]) * (ca - pa[p]))
                            / area;
                    }
                    if (w[0] < 0 || w[1] < 0 || w[2] < 0) {
                        continue;
                    }
                    Hit hit;
                    hit.t = w[0] * pd[0] + w[1] * pd[1] + w[2] * pd[2];
                    hit.n[0] = w[0] * v[0]->nx + w[1] * v[1]->nx + w[2] * v[2]->nx;
                    hit.n[1] = w[0] * v[0]->ny + w[1] * v[1]->ny + w[2] * v[2]->ny;
                    hit.n[2] = w[0] * v[0]->nz + w[1] * v[1]->nz + w[2] * v[2]->nz;
                    hit.enter = hit.n[d] < 0;  // the outward normal faces back up the ray
                    hits[(size_t)j * g.w + i].push_back(hit);
                }
            }
        }

        // the stretches between going in and coming out
        g.initEnds.assign(rays * Ends, NoEnd);
        g.initNormals.assign(rays * Ends, 0.f);
        for (size_t r = 0; r < rays; r++) {
            std::vector<Hit>& h = hits[r];
            std::sort(h.begin(), h.end(), [](const Hit& x, const Hit& y) { return x.t < y.t; });
            int depth = 0;
            int nEnds = 0;
            float lastT = -1e30f;
            bool lastEnter = false;
            for (const Hit& hit : h) {
                // a ray through an edge meets both triangles there: once is enough
                if (std::fabs(hit.t - lastT) < 1e-4f * mRes && hit.enter == lastEnter) {
                    continue;
                }
                lastT = hit.t;
                lastEnter = hit.enter;
                const int before = depth;
                depth += hit.enter ? 1 : -1;
                const bool opens = before <= 0 && depth > 0;
                const bool closes = before > 0 && depth <= 0;
                if ((opens || closes) && nEnds < Ends) {
                    g.initEnds[r * Ends + nEnds] = hit.t;
                    g.initNormals[r * Ends + nEnds] = packNormal(hit.n[0], hit.n[1], hit.n[2]);
                    nEnds++;
                }
            }
            if (nEnds % 2 != 0) {
                // an open stretch: a leak in the mesh, leave the ray empty
                for (int e = 0; e < Ends; e++) {
                    g.initEnds[r * Ends + e] = NoEnd;
                }
            }
        }

        g.ends = g.initEnds;
        g.normals = g.initNormals;
        if (mCpu) {
            continue;
        }

        // the textures, two sets, and the stock's first stretch for its colour
        for (int set = 0; set < 2; set++) {
            for (unsigned int& t : g.tex[set]) {
                t = makeFloatTexture(g.w, g.h, nullptr);
            }
            UploadSet(g, set);
            glGenFramebuffers(1, &g.fbo[set]);
            glBindFramebuffer(GL_FRAMEBUFFER, g.fbo[set]);
            for (int i = 0; i < 6; i++) {
                glFramebufferTexture2D(
                    GL_FRAMEBUFFER,
                    ColorAttachments[i],
                    GL_TEXTURE_2D,
                    g.tex[set][i],
                    0
                );
            }
            glDrawBuffers(6, ColorAttachments);
            if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
                glBindFramebuffer(GL_FRAMEBUFFER, 0);
                Free();
                return false;
            }
        }
        std::vector<float> first(rays * 4, NoEnd);
        for (size_t r = 0; r < rays; r++) {
            first[r * 4] = g.initEnds[r * Ends];
            first[r * 4 + 1] = g.initEnds[r * Ends + 1];
        }
        g.initTex = makeFloatTexture(g.w, g.h, first.data());

        // one point for each end slot of each ray
        g.nPoints = (int)(rays * Ends);
        std::vector<float> index(g.nPoints);
        for (int i = 0; i < g.nPoints; i++) {
            index[i] = (float)i;
        }
        glGenBuffers(1, &g.pointVbo);
        glBindBuffer(GL_ARRAY_BUFFER, g.pointVbo);
        glBufferData(GL_ARRAY_BUFFER, index.size() * sizeof(float), index.data(), GL_STATIC_DRAW);
    }

    for (int c = 0; c < 3; c++) {
        mDims[c] = dims[c];
    }
    if (mCpu) {
        // the processor cuts: of OpenGL only the mesh's shader
        if (mMeshShader.CompileShader("DexelMesh", VertShaderDexelMesh, FragShaderDexelMesh)
            == 0xdeadbeef) {
            Free();
            return false;
        }
        mCutter.Setup(mOrigin, mRes, mDims);
        mMesher.Setup(mOrigin, mRes, dims);
        mMesher.MarkAllDirty();
        mValid = true;
        return true;
    }

    // the capture: entry and exit of a sweep, as big as the largest grid
    mCaptureW = std::max({mGrids[0].w, mGrids[1].w, mGrids[2].w});
    mCaptureH = std::max({mGrids[0].h, mGrids[1].h, mGrids[2].h});
    mCaptureTex[0] = makeFloatTexture(mCaptureW, mCaptureH, nullptr);
    mCaptureTex[1] = makeFloatTexture(mCaptureW, mCaptureH, nullptr);
    glGenFramebuffers(1, &mCaptureFbo);
    glBindFramebuffer(GL_FRAMEBUFFER, mCaptureFbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, mCaptureTex[0], 0);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, mCaptureTex[1], 0);
    glGenRenderbuffers(1, &mCaptureDepth);
    glBindRenderbuffer(GL_RENDERBUFFER, mCaptureDepth);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, mCaptureW, mCaptureH);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, mCaptureDepth);
    glDrawBuffers(1, ColorAttachments);
    const bool complete = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (!complete) {
        Free();
        return false;
    }

    // a quad over the whole target, for the subtraction
    const float quad[] = {
        -1, -1, 0, 0, 1, -1, 1, 0, 1, 1, 1, 1, -1, -1, 0, 0, 1, 1, 1, 1, -1, 1, 0, 1,
    };
    glGenBuffers(1, &mQuadVbo);
    glBindBuffer(GL_ARRAY_BUFFER, mQuadVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);

    if (mCaptureShader.CompileShader("DexelCapture", VertShaderDexelCapture, FragShaderDexelCapture)
            == 0xdeadbeef
        || mSubtractShader.CompileShader("DexelSubtract", VertShaderDexelQuad, FragShaderDexelSubtract)
            == 0xdeadbeef
        || mPointShader.CompileShader("DexelPoints", VertShaderDexelPoints, FragShaderDexelPoints)
            == 0xdeadbeef
        || mMeshShader.CompileShader("DexelMesh", VertShaderDexelMesh, FragShaderDexelMesh)
            == 0xdeadbeef
        || mCopyShader.CompileShader("DexelCopy", VertShaderDexelQuad, FragShaderDexelCopy)
            == 0xdeadbeef) {
        Free();
        return false;
    }

    // the whole surface to mesh, the first time it is drawn
    mMesher.Setup(mOrigin, mRes, dims);
    mMesher.MarkAllDirty();
    mValid = true;
    return true;
}

void DexelStock::UploadSet(Grid& g, int set)
{
    // the ends and their normals, four a texel
    const size_t rays = (size_t)g.w * g.h;
    std::vector<float> data(rays * 4);
    for (int part = 0; part < 6; part++) {
        const std::vector<float>& src = part < 3 ? g.initEnds : g.initNormals;
        const int offset = (part % 3) * 4;
        for (size_t r = 0; r < rays; r++) {
            for (int c = 0; c < 4; c++) {
                data[r * 4 + c] = src[r * Ends + offset + c];
            }
        }
        glBindTexture(GL_TEXTURE_2D, g.tex[set][part]);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, g.w, g.h, 0, GL_RGBA, GL_FLOAT, data.data());
    }
}

void DexelStock::Reset()
{
    if (!mValid) {
        return;
    }
    mCutter.Setup(mOrigin, mRes, mDims);
    for (Grid& g : mGrids) {
        if (!mCpu) {
            UploadSet(g, 0);
            UploadSet(g, 1);
        }
        g.ends = g.initEnds;
        g.normals = g.initNormals;
    }
    mPending = false;
    mMesher.MarkAllDirty();
}

void DexelStock::CopyGrid(const Grid& g, const unsigned int src[6], unsigned int dstFbo)
{
    // all of a grid's six textures into those of another framebuffer, in one pass
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_STENCIL_TEST);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_SCISSOR_TEST);
    glDepthMask(GL_FALSE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glBindFramebuffer(GL_FRAMEBUFFER, dstFbo);
    glDrawBuffers(6, ColorAttachments);
    glViewport(0, 0, g.w, g.h);
    mCopyShader.Activate();
    const char* srcNames[6] = {"Src0", "Src1", "Src2", "Src3", "Src4", "Src5"};
    for (int i = 0; i < 6; i++) {
        glActiveTexture(GL_TEXTURE0 + i);
        glBindTexture(GL_TEXTURE_2D, src[i]);
        setUniform1i(mCopyShader, srcNames[i], i);
    }
    setUniform2f(mCopyShader, "gridSize", (float)g.w, (float)g.h);
    setUniform1f(mCopyShader, "cutting", 0.f);
    glBindBuffer(GL_ARRAY_BUFFER, mQuadVbo);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void*)0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void*)(2 * sizeof(float)));
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glActiveTexture(GL_TEXTURE0);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
}

int DexelStock::SaveSnapshot()
{
    if (!mValid) {
        return -1;
    }
    if (mCpu) {
        Flush();
        CpuSnapshot snap;
        for (int d = 0; d < 3; d++) {
            snap.ends[d] = mGrids[d].ends;
            snap.normals[d] = mGrids[d].normals;
        }
        mCpuSnapshots.push_back(std::move(snap));
        return (int)mCpuSnapshots.size() - 1;
    }
    Snapshot snap;
    for (int i = 0; i < 16 && glGetError() != GL_NO_ERROR; i++) {
        // errors from before, cleared so a failed allocation shows
    }
    for (int d = 0; d < 3; d++) {
        const Grid& g = mGrids[d];
        for (unsigned int& t : snap.tex[d]) {
            t = makeFloatTexture(g.w, g.h, nullptr);
        }
        if (glGetError() == GL_OUT_OF_MEMORY) {
            // no room on the GPU: no snapshot, going back cuts from further back
            mSnapshots.push_back(snap);
            FreeSnapshotAt(mSnapshots.size() - 1);
            return -1;
        }
        glGenFramebuffers(1, &snap.fbo[d]);
        glBindFramebuffer(GL_FRAMEBUFFER, snap.fbo[d]);
        for (int i = 0; i < 6; i++) {
            glFramebufferTexture2D(
                GL_FRAMEBUFFER,
                ColorAttachments[i],
                GL_TEXTURE_2D,
                snap.tex[d][i],
                0
            );
        }
        const bool complete = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        if (!complete) {
            mSnapshots.push_back(snap);
            FreeSnapshotAt(mSnapshots.size() - 1);
            return -1;
        }
        CopyGrid(g, g.tex[0], snap.fbo[d]);
    }
    mSnapshots.push_back(snap);
    return (int)mSnapshots.size() - 1;
}

void DexelStock::RestoreSnapshot(int index)
{
    if (mCpu) {
        if (mValid && index >= 0 && index < (int)mCpuSnapshots.size()) {
            mCutter.Setup(mOrigin, mRes, mDims);
            for (int d = 0; d < 3; d++) {
                mGrids[d].ends = mCpuSnapshots[index].ends[d];
                mGrids[d].normals = mCpuSnapshots[index].normals[d];
            }
            mMesher.MarkAllDirty();
        }
        return;
    }
    if (!mValid || index < 0 || index >= (int)mSnapshots.size()) {
        return;
    }
    for (int d = 0; d < 3; d++) {
        Grid& g = mGrids[d];
        CopyGrid(g, mSnapshots[index].tex[d], g.fbo[0]);
        // and the copy the mesh reads, all of it
        const int rect[4] = {0, 0, g.w, g.h};
        ReadBack(g, rect);
    }
    mPending = false;
    mMesher.MarkAllDirty();
}

void DexelStock::FreeSnapshotAt(size_t index)
{
    // the last one goes altogether, any other only frees its textures, the indices staying
    Snapshot& snap = mSnapshots[index];
    for (int d = 0; d < 3; d++) {
        for (unsigned int& t : snap.tex[d]) {
            GLDELETE_TEXTURE(t);
        }
        GLDELETE_FRAMEBUFFER(snap.fbo[d]);
    }
    if (index + 1 == mSnapshots.size()) {
        mSnapshots.pop_back();
    }
}

void DexelStock::FreeSnapshots()
{
    mCpuSnapshots.clear();
    while (!mSnapshots.empty()) {
        FreeSnapshotAt(mSnapshots.size() - 1);
    }
}

bool DexelStock::GridRect(const Grid& g, const vec3 lo, const vec3 hi, int rect[4]) const
{
    // the cells of the grid a box covers, if any
    rect[0] = std::max(0, (int)std::floor((lo[g.a] - mOrigin[g.a]) / mRes));
    rect[1] = std::max(0, (int)std::floor((lo[g.b] - mOrigin[g.b]) / mRes));
    rect[2] = std::min(g.w, (int)std::ceil((hi[g.a] - mOrigin[g.a]) / mRes) + 1);
    rect[3] = std::min(g.h, (int)std::ceil((hi[g.b] - mOrigin[g.b]) / mRes) + 1);
    return rect[2] > rect[0] && rect[3] > rect[1];
}

void DexelStock::SetupCapture(const Grid& g)
{
    // a flat projection along the grid's axis: columns, rows, and depth along the rays over a
    // range far wider than any tool, so nothing is clipped
    mat4x4 proj;
    mat4x4_identity(proj);
    for (int c = 0; c < 4; c++) {
        for (int r = 0; r < 4; r++) {
            proj[c][r] = 0;
        }
    }
    const float zr = 1e4f;
    const float zc = mOrigin[g.axis];
    proj[g.a][0] = 2.f / (g.w * mRes);
    proj[3][0] = -2.f * mOrigin[g.a] / (g.w * mRes) - 1.f;
    proj[g.b][1] = 2.f / (g.h * mRes);
    proj[3][1] = -2.f * mOrigin[g.b] / (g.h * mRes) - 1.f;
    proj[g.axis][2] = 1.f / zr;
    proj[3][2] = -zc / zr;
    proj[3][3] = 1.f;
    mat4x4 view;
    mat4x4_identity(view);
    vec3 dir = {0, 0, 0};
    dir[g.axis] = 1;

    mCaptureShader.Activate();
    setUniformMat(mCaptureShader, "projection", proj);
    setUniformMat(mCaptureShader, "view", view);
    setUniform3f(mCaptureShader, "dirD", dir);
}

// a sweep's shape handed to the processor's cutter rather than drawn
static void CaptureForCutter(void* context, const Shape& shape, const mat4x4& model, const mat4x4& normal)
{
    if (!shape.cpuVerts || !shape.cpuIndices) {
        return;
    }
    static_cast<DexelCutter*>(context)->Draw(shape, model, normal);
}

void DexelStock::Flush()
{
    if (!mValid || !mCpu) {
        return;
    }
    DexelCutter::Grid grids[3];
    for (int d = 0; d < 3; d++) {
        Grid& g = mGrids[d];
        grids[d] = {g.axis, g.a, g.b, g.w, g.h, g.ends.data(), g.normals.data()};
    }
    mCutter.Flush(grids);
}

void DexelStock::Cut(const vec3 lo, const vec3 hi, const std::function<void()>& drawSweep)
{
    if (!mValid) {
        return;
    }
    // a sweep that misses the stock's box, a rapid above it say, cuts nothing
    for (int c = 0; c < 3; c++) {
        if (hi[c] < mOrigin[c] || lo[c] > mOrigin[c] + mDims[c] * mRes) {
            return;
        }
    }

    if (mCpu) {
        // the sweep's triangles gathered for the processor, the mesh's tiles to remake
        mMesher.MarkDirty(lo, hi);
        mCutter.Begin(lo, hi);
        Shape::sCapture = &CaptureForCutter;
        Shape::sCaptureContext = &mCutter;
        drawSweep();
        Shape::sCapture = nullptr;
        Shape::sCaptureContext = nullptr;
        mCutter.End();
        return;
    }

    // the rays to read back for the mesh, and the tiles of it to remake
    for (int c = 0; c < 3; c++) {
        mPendingLo[c] = mPending ? std::min(mPendingLo[c], lo[c]) : lo[c];
        mPendingHi[c] = mPending ? std::max(mPendingHi[c], hi[c]) : hi[c];
    }
    mPending = true;
    mMesher.MarkDirty(lo, hi);

    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_STENCIL_TEST);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glEnable(GL_SCISSOR_TEST);

    for (Grid& g : mGrids) {
        int rect[4];
        if (!GridRect(g, lo, hi, rect)) {
            continue;
        }
        const int rw = rect[2] - rect[0];
        const int rh = rect[3] - rect[1];

        // where each ray first meets the sweep, and where it last leaves it
        glBindFramebuffer(GL_FRAMEBUFFER, mCaptureFbo);
        glViewport(0, 0, g.w, g.h);
        glScissor(rect[0], rect[1], rw, rh);
        SetupCapture(g);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);

        glDrawBuffers(1, &ColorAttachments[0]);
        glClearColor(0, 0, 0, 0);
        glClearDepthf(1.f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glDepthFunc(GL_LESS);
        drawSweep();

        glDrawBuffers(1, &ColorAttachments[1]);
        glClearDepthf(0.f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glDepthFunc(GL_GREATER);
        drawSweep();
        glClearDepthf(1.f);
        glDepthFunc(GL_LESS);

        // each ray less the sweep, into the second set
        glBindFramebuffer(GL_FRAMEBUFFER, g.fbo[1]);
        glDrawBuffers(6, ColorAttachments);
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        mSubtractShader.Activate();
        const char* names[8] = {"End0", "End1", "End2", "Nrm0", "Nrm1", "Nrm2", "CapIn", "CapOut"};
        for (int i = 0; i < 8; i++) {
            glActiveTexture(GL_TEXTURE0 + i);
            glBindTexture(GL_TEXTURE_2D, i < 6 ? g.tex[0][i] : mCaptureTex[i - 6]);
            setUniform1i(mSubtractShader, names[i], i);
        }
        setUniform2f(mSubtractShader, "gridSize", (float)g.w, (float)g.h);
        setUniform2f(mSubtractShader, "captureSize", (float)mCaptureW, (float)mCaptureH);
        setUniform1f(mSubtractShader, "sliver", 0.05f * mRes);
        glBindBuffer(GL_ARRAY_BUFFER, mQuadVbo);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void*)0);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void*)(2 * sizeof(float)));
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // and back into the first, over the rays the sweep covers
        glBindFramebuffer(GL_FRAMEBUFFER, g.fbo[0]);
        glDrawBuffers(6, ColorAttachments);
        mCopyShader.Activate();
        const char* srcNames[8] = {"Src0", "Src1", "Src2", "Src3", "Src4", "Src5", "CapIn", "CapOut"};
        for (int i = 0; i < 8; i++) {
            glActiveTexture(GL_TEXTURE0 + i);
            glBindTexture(GL_TEXTURE_2D, i < 6 ? g.tex[1][i] : mCaptureTex[i - 6]);
            setUniform1i(mCopyShader, srcNames[i], i);
        }
        setUniform2f(mCopyShader, "gridSize", (float)g.w, (float)g.h);
        setUniform2f(mCopyShader, "captureSize", (float)mCaptureW, (float)mCaptureH);
        setUniform1f(mCopyShader, "cutting", 1.f);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glDisable(GL_SCISSOR_TEST);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glActiveTexture(GL_TEXTURE0);
}

void DexelStock::ReadBack(Grid& g, const int rect[4])
{
    // the rays in rect as cut, from the first set into the copy the mesh reads
    const int rw = rect[2] - rect[0];
    const int rh = rect[3] - rect[1];
    std::vector<float> data((size_t)rw * rh * 4);
    glBindFramebuffer(GL_FRAMEBUFFER, g.fbo[0]);
    for (int part = 0; part < 6; part++) {
        glReadBuffer(ColorAttachments[part]);
        glReadPixels(rect[0], rect[1], rw, rh, GL_RGBA, GL_FLOAT, data.data());
        std::vector<float>& dst = part < 3 ? g.ends : g.normals;
        const int offset = (part % 3) * 4;
        for (int y = 0; y < rh; y++) {
            for (int x = 0; x < rw; x++) {
                const size_t r = (size_t)(rect[1] + y) * g.w + rect[0] + x;
                const float* src = &data[((size_t)y * rw + x) * 4];
                for (int c = 0; c < 4; c++) {
                    dst[r * Ends + offset + c] = src[c];
                }
            }
        }
    }
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

bool DexelStock::Sync(double budgetMs)
{
    if (!mValid) {
        return true;
    }
    Flush();
    if (mPending) {
        for (Grid& g : mGrids) {
            int rect[4];
            if (GridRect(g, mPendingLo, mPendingHi, rect)) {
                ReadBack(g, rect);
            }
        }
        mPending = false;
    }
    DexelMesher::Grid grids[3];
    for (int d = 0; d < 3; d++) {
        const Grid& g = mGrids[d];
        grids[d] = {g.axis, g.a, g.b, g.w, g.h, g.ends.data(), g.normals.data(), g.initEnds.data()};
    }
    return mMesher.Update(grids, budgetMs);
}

void DexelStock::Render(
    const mat4x4 view,
    const mat4x4 projection,
    float pointScale,
    bool perspective,
    const vec3 stockColor,
    const vec3 cutColor
)
{
    if (!mValid) {
        return;
    }
    // CAMSIM_DEXEL_POINTS=1 draws the rays' ends as discs instead, to look at the rays themselves
    const char* points = std::getenv("CAMSIM_DEXEL_POINTS");
    if (points && points[0] == '1' && !mCpu) {
        RenderPoints(view, projection, pointScale, perspective, stockColor, cutColor);
        return;
    }

    glDisable(GL_CULL_FACE);
    glDisable(GL_BLEND);
    glDisable(GL_STENCIL_TEST);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    mMeshShader.Activate();
    setUniformMat(mMeshShader, "view", view);
    setUniformMat(mMeshShader, "projection", projection);
    setUniform3f(mMeshShader, "stockColor", stockColor);
    setUniform3f(mMeshShader, "cutColor", cutColor);
    mMesher.Render();
}

void DexelStock::RenderPoints(
    const mat4x4 view,
    const mat4x4 projection,
    float pointScale,
    bool perspective,
    const vec3 stockColor,
    const vec3 cutColor
)
{

    glEnable(0x8642);  // GL_PROGRAM_POINT_SIZE: the vertex shader sizes the points
    glEnable(0x8861);  // GL_POINT_SPRITE: and the fragments know where in the point they are
    glDisable(GL_CULL_FACE);
    glDisable(GL_BLEND);
    glDisable(GL_STENCIL_TEST);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);

    mPointShader.Activate();
    setUniformMat(mPointShader, "view", view);
    setUniformMat(mPointShader, "projection", projection);
    setUniform1f(mPointShader, "pointScale", pointScale);
    setUniform1f(mPointShader, "perspective", perspective ? 1.f : 0.f);
    setUniform1f(mPointShader, "res", mRes);
    setUniform3f(mPointShader, "stockColor", stockColor);
    setUniform3f(mPointShader, "cutColor", cutColor);
    setUniform3f(mPointShader, "origin", mOrigin);
    const char* names[7] = {"End0", "End1", "End2", "Nrm0", "Nrm1", "Nrm2", "InitTex"};
    for (int i = 0; i < 7; i++) {
        setUniform1i(mPointShader, names[i], i);
    }

    for (const Grid& g : mGrids) {
        for (int i = 0; i < 7; i++) {
            glActiveTexture(GL_TEXTURE0 + i);
            glBindTexture(GL_TEXTURE_2D, i < 6 ? g.tex[0][i] : g.initTex);
        }
        vec3 dirA = {0, 0, 0}, dirB = {0, 0, 0}, dirD = {0, 0, 0};
        dirA[g.a] = 1;
        dirB[g.b] = 1;
        dirD[g.axis] = 1;
        setUniform3f(mPointShader, "dirA", dirA);
        setUniform3f(mPointShader, "dirB", dirB);
        setUniform3f(mPointShader, "dirD", dirD);
        setUniform2f(mPointShader, "gridSize", (float)g.w, (float)g.h);

        glBindBuffer(GL_ARRAY_BUFFER, g.pointVbo);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 1, GL_FLOAT, GL_FALSE, sizeof(float), (void*)0);
        glDisableVertexAttribArray(1);
        glDrawArrays(GL_POINTS, 0, g.nPoints);
    }

    glDisable(0x8861);
    glDisable(0x8642);
    glActiveTexture(GL_TEXTURE0);
}

}  // namespace CAMSimulator
