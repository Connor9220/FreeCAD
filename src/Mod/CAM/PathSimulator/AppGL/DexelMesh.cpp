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

#include "DexelMesh.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <future>
#include <thread>

// include this last as the defines can mess up other includes
#include "OpenGlWrapper.h"

namespace CAMSimulator
{

namespace
{

constexpr float NoEnd = 1e29f;  // ends at or past this are not there

// a surface crossing on an edge of the lattice
struct Hermite
{
    float p[3];
    float n[3];
    bool stock;
    bool guessed;  // the ray had no end here, its grid disagreeing with the Z rays
};

// the octahedral packing of the dexel shaders, undone
void unpackNormal(float packed, float n[3])
{
    const float qx = std::floor(packed / 4096.f);
    const float qy = packed - qx * 4096.f;
    float x = qx / 4095.f * 2.f - 1.f;
    float y = qy / 4095.f * 2.f - 1.f;
    const float z = 1.f - std::fabs(x) - std::fabs(y);
    if (z < 0) {
        const float ox = x;
        x = (1.f - std::fabs(y)) * (ox >= 0 ? 1.f : -1.f);
        y = (1.f - std::fabs(ox)) * (y >= 0 ? 1.f : -1.f);
    }
    const float len = std::sqrt(x * x + y * y + z * z);
    n[0] = x / len;
    n[1] = y / len;
    n[2] = z / len;
}

// x minimizing the squared distances to the crossings' planes, drawn a little toward their
// middle so a flat or a straight run of them still has one answer
void solveQef(const std::vector<const Hermite*>& hs, float out[3])
{
    double ata[3][3] = {};
    double atb[3] = {};
    double mass[3] = {};
    for (const Hermite* h : hs) {
        const double d = h->n[0] * h->p[0] + h->n[1] * h->p[1] + h->n[2] * h->p[2];
        for (int r = 0; r < 3; r++) {
            for (int c = 0; c < 3; c++) {
                ata[r][c] += (double)h->n[r] * h->n[c];
            }
            atb[r] += h->n[r] * d;
            mass[r] += h->p[r];
        }
    }
    for (double& m : mass) {
        m /= (double)hs.size();
    }
    // about the middle: (AtA + wI) dx = Atb - AtA m
    const double w = 0.05;
    double m[3][3];
    double rhs[3];
    for (int r = 0; r < 3; r++) {
        rhs[r] = atb[r];
        for (int c = 0; c < 3; c++) {
            m[r][c] = ata[r][c] + (r == c ? w : 0.0);
            rhs[r] -= ata[r][c] * mass[c];
        }
    }
    const double det = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    if (std::fabs(det) < 1e-12) {
        for (int c = 0; c < 3; c++) {
            out[c] = (float)mass[c];
        }
        return;
    }
    double x[3];
    for (int c = 0; c < 3; c++) {
        double mc[3][3];
        for (int r = 0; r < 3; r++) {
            for (int k = 0; k < 3; k++) {
                mc[r][k] = k == c ? rhs[r] : m[r][k];
            }
        }
        x[c] = (mc[0][0] * (mc[1][1] * mc[2][2] - mc[1][2] * mc[2][1])
                - mc[0][1] * (mc[1][0] * mc[2][2] - mc[1][2] * mc[2][0])
                + mc[0][2] * (mc[1][0] * mc[2][1] - mc[1][1] * mc[2][0]))
            / det;
    }
    for (int c = 0; c < 3; c++) {
        out[c] = (float)(mass[c] + x[c]);
    }
}

}  // namespace

DexelMesher::~DexelMesher()
{
    Free();
}

void DexelMesher::Setup(const vec3 origin, float res, const int dims[3])
{
    Free();
    vec3_dup(mOrigin, origin);
    mRes = res;
    for (int c = 0; c < 3; c++) {
        mDims[c] = dims[c];
        mTiles[c] = (dims[c] + Tile - 1) / Tile;
    }
    mDirtyFlag.assign((size_t)mTiles[0] * mTiles[1] * mTiles[2], 0);
}

void DexelMesher::Free()
{
    for (auto& [key, mesh] : mMeshes) {
        GLDELETE_BUFFER(mesh.vbo);
        GLDELETE_BUFFER(mesh.ibo);
    }
    mMeshes.clear();
    mDirty.clear();
    std::fill(mDirtyFlag.begin(), mDirtyFlag.end(), 0);
}

void DexelMesher::MarkDirty(const vec3 lo, const vec3 hi)
{
    // a cell's vertex reads the edges round it, its normal the faces round it, and a tile
    // carries the cells along its low sides: two cells' margin either way
    int t0[3];
    int t1[3];
    for (int c = 0; c < 3; c++) {
        const int n0 = (int)std::floor((lo[c] - mOrigin[c]) / mRes - 2.5f);
        const int n1 = (int)std::floor((hi[c] - mOrigin[c]) / mRes + 2.5f);
        t0[c] = std::clamp(n0 / Tile - (n0 < 0 ? 1 : 0), 0, mTiles[c] - 1);
        t1[c] = std::clamp(n1 / Tile, 0, mTiles[c] - 1);
    }
    for (int z = t0[2]; z <= t1[2]; z++) {
        for (int y = t0[1]; y <= t1[1]; y++) {
            for (int x = t0[0]; x <= t1[0]; x++) {
                const int key = TileKey(x, y, z);
                if (!mDirtyFlag[key]) {
                    mDirtyFlag[key] = 1;
                    mDirty.push_back(key);
                }
            }
        }
    }
}

void DexelMesher::MarkAllDirty()
{
    const vec3 lo = {mOrigin[0], mOrigin[1], mOrigin[2]};
    vec3 hi;
    for (int c = 0; c < 3; c++) {
        hi[c] = mOrigin[c] + mDims[c] * mRes;
    }
    MarkDirty(lo, hi);
}

void DexelMesher::BuildTile(int key, const Grid grids[3], Built& out) const
{
    constexpr int T = Tile;
    // Nodes a side: the tile's, two before it and two after. The tile's quads join the cells of
    // its own and the one before it, and the normals of those take the faces round them, which
    // reach a cell further either way.
    constexpr int N = T + 4;
    constexpr int C = T + 3;  // cells a side
    out.key = key;
    out.verts.clear();
    out.indices.clear();

    const int tx = key % mTiles[0];
    const int ty = (key / mTiles[0]) % mTiles[1];
    const int tz = key / (mTiles[0] * mTiles[1]);
    const int base[3] = {tx * T - 2, ty * T - 2, tz * T - 2};
    auto nodeAt = [&](int c, int n) { return mOrigin[c] + ((float)n + 0.5f) * mRes; };
    auto nidx = [](int l0, int l1, int l2) { return (l2 * N + l1) * N + l0; };

    // which nodes are in the material, from the rays along Z, each through a column of them
    std::vector<unsigned char> inside(N * N * N, 0);
    const Grid& gz = grids[2];
    int nIn = 0;
    for (int l1 = 0; l1 < N; l1++) {
        const int g1 = base[1] + l1;
        for (int l0 = 0; l0 < N; l0++) {
            const int g0 = base[0] + l0;
            if (g0 < 0 || g0 >= gz.w || g1 < 0 || g1 >= gz.h) {
                continue;
            }
            const float* e = gz.ends + ((size_t)g1 * gz.w + g0) * gz.stride;
            if (e[0] >= NoEnd) {
                continue;
            }
            for (int l2 = 0; l2 < N; l2++) {
                const float z = nodeAt(2, base[2] + l2);
                for (int k = 0; k < gz.stride; k += 2) {
                    if (e[k] >= NoEnd) {
                        break;
                    }
                    if (e[k] <= z && z < e[k + 1]) {
                        inside[nidx(l0, l1, l2)] = 1;
                        nIn++;
                        break;
                    }
                }
            }
        }
    }
    if (nIn == 0 || nIn == N * N * N) {
        return;  // no surface here
    }

    // the crossings of the edges whose ends differ, each from the ray the edge lies on
    std::vector<Hermite> hermites;
    std::vector<int> edgeId[3];
    for (int d = 0; d < 3; d++) {
        edgeId[d].assign(N * N * N, -1);
        const Grid& g = grids[d];
        for (int l2 = 0; l2 < N; l2++) {
            for (int l1 = 0; l1 < N; l1++) {
                for (int l0 = 0; l0 < N; l0++) {
                    int l[3] = {l0, l1, l2};
                    if (l[d] + 1 >= N) {
                        continue;
                    }
                    const int i0 = nidx(l0, l1, l2);
                    l[d]++;
                    const int i1 = nidx(l[0], l[1], l[2]);
                    l[d]--;
                    if (inside[i0] == inside[i1]) {
                        continue;
                    }
                    const int gn[3] = {base[0] + l0, base[1] + l1, base[2] + l2};
                    const float t0 = nodeAt(d, gn[d]);
                    const float t1 = nodeAt(d, gn[d] + 1);
                    Hermite h;
                    for (int c = 0; c < 3; c++) {
                        h.p[c] = nodeAt(c, gn[c]);
                        h.n[c] = 0;
                    }
                    h.stock = false;
                    h.guessed = false;
                    // the ray's end in the edge, the one nearest its middle, of the kind the
                    // edge crosses: where a stretch stops if the material is behind, where one
                    // starts if ahead
                    const int u = gn[g.a];
                    const int v = gn[g.b];
                    int best = -1;
                    if (u >= 0 && u < g.w && v >= 0 && v < g.h) {
                        const size_t r = ((size_t)v * g.w + u) * g.stride;
                        const float mid = 0.5f * (t0 + t1);
                        float bestDist = 1e30f;
                        const int kind = inside[i0] ? 1 : 0;
                        for (int k = 0; k < g.stride; k++) {
                            const float t = g.ends[r + k];
                            if (t >= NoEnd) {
                                break;
                            }
                            if ((k & 1) == kind && t >= t0 && t <= t1
                                && std::fabs(t - mid) < bestDist) {
                                bestDist = std::fabs(t - mid);
                                best = k;
                            }
                        }
                        if (best >= 0) {
                            const float t = g.ends[r + best];
                            h.p[d] = t;
                            unpackNormal(g.normals[r + best], h.n);
                            for (int k = 0; k < g.stride; k++) {
                                const float s = g.initEnds[r + k];
                                if (s >= NoEnd) {
                                    break;
                                }
                                if (std::fabs(s - t) < 0.25f * mRes) {
                                    h.stock = true;
                                    break;
                                }
                            }
                        }
                    }
                    if (best < 0) {
                        // the ray disagrees: the middle, facing out of the material
                        h.p[d] = 0.5f * (t0 + t1);
                        h.n[d] = inside[i0] ? 1.f : -1.f;
                        h.guessed = true;
                    }
                    edgeId[d][i0] = (int)hermites.size();
                    hermites.push_back(h);
                }
            }
        }
    }

    // a vertex in each cell the surface passes through
    struct CellVertex
    {
        float p[3];
        float h[3];  // the crossings' normals, summed
        int nh;
        float f[3];  // the faces' normals round it, summed by area
        float n[3];  // the normal it is drawn with
        bool stock;
        bool hasNormal;
        int out;  // its index in the tile's mesh, -1 if not there
    };
    std::vector<CellVertex> verts;
    std::vector<int> cellVertex(C * C * C, -1);
    auto cidx = [](int c0, int c1, int c2) { return (c2 * C + c1) * C + c0; };
    std::vector<const Hermite*> hs;
    std::vector<const Hermite*> real;
    hs.reserve(12);
    real.reserve(12);
    for (int c2 = 0; c2 < C; c2++) {
        for (int c1 = 0; c1 < C; c1++) {
            for (int c0 = 0; c0 < C; c0++) {
                hs.clear();
                for (int d = 0; d < 3; d++) {
                    const int a = (d + 1) % 3;
                    const int b = (d + 2) % 3;
                    for (int j = 0; j < 2; j++) {
                        for (int k = 0; k < 2; k++) {
                            int l[3] = {c0, c1, c2};
                            l[a] += j;
                            l[b] += k;
                            const int id = edgeId[d][nidx(l[0], l[1], l[2])];
                            if (id >= 0) {
                                hs.push_back(&hermites[id]);
                            }
                        }
                    }
                }
                if (hs.empty()) {
                    continue;
                }
                // a guessed crossing is only a stand-in: the vertex fits the real ones if any,
                // and takes their normals
                real.clear();
                for (const Hermite* h : hs) {
                    if (!h->guessed) {
                        real.push_back(h);
                    }
                }
                const std::vector<const Hermite*>& use = real.empty() ? hs : real;
                CellVertex v {};
                solveQef(use, v.p);
                const int cg[3] = {base[0] + c0, base[1] + c1, base[2] + c2};
                for (int c = 0; c < 3; c++) {
                    v.p[c] = std::clamp(v.p[c], nodeAt(c, cg[c]), nodeAt(c, cg[c] + 1));
                }
                int nStock = 0;
                for (const Hermite* h : use) {
                    for (int c = 0; c < 3; c++) {
                        v.h[c] += h->n[c];
                    }
                    nStock += h->stock ? 1 : 0;
                }
                v.nh = (int)use.size();
                v.stock = 2 * nStock > v.nh;
                v.out = -1;
                cellVertex[cidx(c0, c1, c2)] = (int)verts.size();
                verts.push_back(v);
            }
        }
    }

    // A quad across each crossed edge, its four cells round it, facing out of the material:
    // all of them for the faces' normals, those the tile owns for its mesh.
    auto quad = [&](int d, const int l[3], int q[4]) {
        const int a = (d + 1) % 3;
        const int b = (d + 2) % 3;
        const int da[4] = {-1, 0, 0, -1};
        const int db[4] = {-1, -1, 0, 0};
        for (int m = 0; m < 4; m++) {
            int c[3] = {l[0], l[1], l[2]};
            c[a] += da[m];
            c[b] += db[m];
            q[m] = cellVertex[cidx(c[0], c[1], c[2])];
            if (q[m] < 0) {
                return false;
            }
        }
        if (!inside[nidx(l[0], l[1], l[2])]) {
            std::swap(q[1], q[3]);
        }
        return true;
    };
    // the faces round each vertex, their normals by area, for its normal and for each side of
    // a crease through it
    struct Face
    {
        int v[3];
        float n[3];
    };
    std::vector<Face> faces;
    auto addFace = [&](int i0, int i1, int i2) {
        const float* p0 = verts[i0].p;
        const float* p1 = verts[i1].p;
        const float* p2 = verts[i2].p;
        const float u[3] = {p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]};
        const float w[3] = {p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]};
        Face f {{i0, i1, i2}, {u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]}};
        for (int i : {i0, i1, i2}) {
            for (int c = 0; c < 3; c++) {
                verts[i].f[c] += f.n[c];
            }
        }
        faces.push_back(f);
    };
    // how near one plane a quad's two halves are, split from its first corner to its third
    auto flatter = [&](int i0, int i1, int i2, int i3) {
        auto unitNormal = [&](int a0, int a1, int a2, float n[3]) {
            const float* p0 = verts[a0].p;
            const float* p1 = verts[a1].p;
            const float* p2 = verts[a2].p;
            const float u[3] = {p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]};
            const float w[3] = {p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]};
            n[0] = u[1] * w[2] - u[2] * w[1];
            n[1] = u[2] * w[0] - u[0] * w[2];
            n[2] = u[0] * w[1] - u[1] * w[0];
            const float l = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
            for (int c = 0; c < 3; c++) {
                n[c] = l > 1e-12f ? n[c] / l : 0.f;
            }
        };
        float na[3];
        float nb[3];
        unitNormal(i0, i1, i2, na);
        unitNormal(i0, i2, i3, nb);
        return na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2];
    };
    for (int d = 0; d < 3; d++) {
        for (int l2 = 1; l2 < C; l2++) {
            for (int l1 = 1; l1 < C; l1++) {
                for (int l0 = 1; l0 < C; l0++) {
                    if (edgeId[d][nidx(l0, l1, l2)] < 0) {
                        continue;
                    }
                    const int l[3] = {l0, l1, l2};
                    int q[4];
                    if (!quad(d, l, q)) {
                        continue;
                    }
                    if (flatter(q[0], q[1], q[2], q[3]) >= flatter(q[1], q[2], q[3], q[0])) {
                        addFace(q[0], q[1], q[2]);
                        addFace(q[0], q[2], q[3]);
                    }
                    else {
                        addFace(q[1], q[2], q[3]);
                        addFace(q[1], q[3], q[0]);
                    }
                }
            }
        }
    }

    std::vector<int> faceStart(verts.size() + 1, 0);
    for (const Face& f : faces) {
        for (int i : f.v) {
            faceStart[i + 1]++;
        }
    }
    for (size_t i = 0; i < verts.size(); i++) {
        faceStart[i + 1] += faceStart[i];
    }
    std::vector<int> faceOf(faceStart.back());
    {
        std::vector<int> fill(faceStart.begin(), faceStart.end() - 1);
        for (int k = 0; k < (int)faces.size(); k++) {
            for (int i : faces[k].v) {
                faceOf[fill[i]++] = k;
            }
        }
    }

    // The normal: the crossings' where they agree among themselves and with the faces, the
    // faces' where not. A ridge or a sliver thinner than a cell puts crossings of both its
    // sides in one cell, their normals cancelling.
    auto normalOf = [&](CellVertex& v) -> const float* {
        if (v.hasNormal) {
            return v.n;
        }
        const float hl = std::sqrt(v.h[0] * v.h[0] + v.h[1] * v.h[1] + v.h[2] * v.h[2]);
        const float fl = std::sqrt(v.f[0] * v.f[0] + v.f[1] * v.f[1] + v.f[2] * v.f[2]);
        const bool agree = hl > 0.9f * v.nh && fl > 1e-12f
            && (v.h[0] * v.f[0] + v.h[1] * v.f[1] + v.h[2] * v.f[2]) > 0.7f * hl * fl;
        for (int c = 0; c < 3; c++) {
            v.n[c] = agree || fl <= 1e-12f ? v.h[c] / std::max(hl, 1e-12f) : v.f[c] / fl;
        }
        v.hasNormal = true;
        return v.n;
    };
    auto push = [&](const float* p, const float* n, bool stock) {
        out.verts.insert(out.verts.end(), {p[0], p[1], p[2], n[0], n[1], n[2]});
        out.verts.push_back(stock ? 1.f : 0.f);
        return (int)(out.verts.size() / 7) - 1;
    };
    auto emit = [&](int i) {
        CellVertex& v = verts[i];
        if (v.out < 0) {
            v.out = push(v.p, normalOf(v), v.stock);
        }
        return v.out;
    };
    // A corner of a face turned from its vertex's normal by more than this is a crease: the
    // face keeps its own normal there, and the edge stays sharp rather than shaded round.
    const float creaseCos = 0.8f;
    // and its color: a crease between the stock's own face and a cut one runs along it
    // the corner's normal then the faces' round the vertex on the face's own side of the crease
    auto corner = [&](int i, const float* fn, bool faceStock) {
        CellVertex& v = verts[i];
        const float* n = normalOf(v);
        if (n[0] * fn[0] + n[1] * fn[1] + n[2] * fn[2] >= creaseCos) {
            return emit(i);
        }
        float side[3] = {0, 0, 0};
        for (int k = faceStart[i]; k < faceStart[i + 1]; k++) {
            const float* m = faces[faceOf[k]].n;
            const float ml = std::sqrt(m[0] * m[0] + m[1] * m[1] + m[2] * m[2]);
            if (ml > 1e-12f && m[0] * fn[0] + m[1] * fn[1] + m[2] * fn[2] >= creaseCos * ml) {
                for (int c = 0; c < 3; c++) {
                    side[c] += m[c];
                }
            }
        }
        const float sl = std::sqrt(side[0] * side[0] + side[1] * side[1] + side[2] * side[2]);
        if (sl > 1e-12f) {
            for (float& x : side) {
                x /= sl;
            }
            return push(v.p, side, faceStock);
        }
        return push(v.p, fn, faceStock);
    };
    auto triangle = [&](int i0, int i1, int i2) {
        const float* p0 = verts[i0].p;
        const float* p1 = verts[i1].p;
        const float* p2 = verts[i2].p;
        const float u[3] = {p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]};
        const float w[3] = {p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]};
        float fn[3] = {u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]};
        const float l = std::sqrt(fn[0] * fn[0] + fn[1] * fn[1] + fn[2] * fn[2]);
        if (l < 1e-12f) {
            return;  // two of its corners in one place: nothing to draw
        }
        for (float& x : fn) {
            x /= l;
        }
        // a tile holds at most 65536 vertices, the creases' own included
        if (out.verts.size() / 7 + 3 >= 65536) {
            return;
        }
        const bool faceStock = (verts[i0].stock ? 1 : 0) + (verts[i1].stock ? 1 : 0)
                + (verts[i2].stock ? 1 : 0)
            >= 2;
        out.indices.insert(
            out.indices.end(),
            {(unsigned short)corner(i0, fn, faceStock),
             (unsigned short)corner(i1, fn, faceStock),
             (unsigned short)corner(i2, fn, faceStock)}
        );
    };
    for (int d = 0; d < 3; d++) {
        for (int l2 = 2; l2 <= T + 1; l2++) {
            for (int l1 = 2; l1 <= T + 1; l1++) {
                for (int l0 = 2; l0 <= T + 1; l0++) {
                    if (edgeId[d][nidx(l0, l1, l2)] < 0) {
                        continue;
                    }
                    const int l[3] = {l0, l1, l2};
                    int q[4];
                    if (!quad(d, l, q)) {
                        continue;
                    }
                    // split along the diagonal leaving its two halves nearest one plane: on a
                    // crease across the quad, the one along the crease
                    if (flatter(q[0], q[1], q[2], q[3]) >= flatter(q[1], q[2], q[3], q[0])) {
                        triangle(q[0], q[1], q[2]);
                        triangle(q[0], q[2], q[3]);
                    }
                    else {
                        triangle(q[1], q[2], q[3]);
                        triangle(q[1], q[3], q[0]);
                    }
                }
            }
        }
    }
}

void DexelMesher::Upload(Built& built)
{
    auto it = mMeshes.find(built.key);
    if (built.indices.empty()) {
        if (it != mMeshes.end()) {
            GLDELETE_BUFFER(it->second.vbo);
            GLDELETE_BUFFER(it->second.ibo);
            mMeshes.erase(it);
        }
        return;
    }
    TileMesh& mesh = mMeshes[built.key];
    if (mesh.vbo == 0) {
        glGenBuffers(1, &mesh.vbo);
        glGenBuffers(1, &mesh.ibo);
    }
    glBindBuffer(GL_ARRAY_BUFFER, mesh.vbo);
    glBufferData(
        GL_ARRAY_BUFFER,
        built.verts.size() * sizeof(float),
        built.verts.data(),
        GL_STATIC_DRAW
    );
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, mesh.ibo);
    glBufferData(
        GL_ELEMENT_ARRAY_BUFFER,
        built.indices.size() * sizeof(unsigned short),
        built.indices.data(),
        GL_STATIC_DRAW
    );
    mesh.nIndices = (int)built.indices.size();
}

bool DexelMesher::Update(const Grid grids[3], double budgetMs)
{
    using clock = std::chrono::steady_clock;
    const auto start = clock::now();
    const int threads = (int)std::max(1u, std::thread::hardware_concurrency());

    // a batch of tiles at a time, each on a thread of its own, till the time is up
    while (!mDirty.empty()) {
        const int n = std::min((int)mDirty.size(), 2 * threads);
        std::vector<Built> built(n);
        std::vector<std::future<void>> jobs;
        jobs.reserve(n);
        for (int i = 0; i < n; i++) {
            const int key = mDirty[mDirty.size() - 1 - i];
            jobs.push_back(std::async(std::launch::async, [this, key, grids, &built, i] {
                BuildTile(key, grids, built[i]);
            }));
        }
        for (auto& job : jobs) {
            job.get();
        }
        for (Built& b : built) {
            Upload(b);
            mDirtyFlag[b.key] = 0;
        }
        mDirty.resize(mDirty.size() - n);
        const double ms = std::chrono::duration<double, std::milli>(clock::now() - start).count();
        if (ms > budgetMs) {
            break;
        }
    }
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
    return mDirty.empty();
}

void DexelMesher::Render() const
{
    for (const auto& [key, mesh] : mMeshes) {
        glBindBuffer(GL_ARRAY_BUFFER, mesh.vbo);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, mesh.ibo);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 7 * sizeof(float), (void*)0);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 7 * sizeof(float), (void*)(3 * sizeof(float)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, 7 * sizeof(float), (void*)(6 * sizeof(float)));
        glDrawElements(GL_TRIANGLES, mesh.nIndices, GL_UNSIGNED_SHORT, nullptr);
    }
    glDisableVertexAttribArray(2);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
}

}  // namespace CAMSimulator
