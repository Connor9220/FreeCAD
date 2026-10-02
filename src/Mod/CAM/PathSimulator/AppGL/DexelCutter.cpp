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

#include "DexelCutter.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <thread>

namespace CAMSimulator
{

namespace
{

constexpr float NoEnd = 1e30f;

// the octahedral packing the dexel shaders and the mesher read: 12 bits a coordinate
float packNormal(float x, float y, float z)
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

// One ray's stretches less [t0, t1], the new ends taking the sweep's normals there: as the
// subtraction shader does, a piece thinner than sliver going, and a seventh stretch closing
// the narrowest gap or dropping the thinnest stretch.
void subtractRay(float* e, float* n, float t0, float t1, float nIn, float nOut, float sliver)
{
    float o[14];
    float on[14];
    for (int i = 0; i < 14; i++) {
        o[i] = NoEnd;
        on[i] = 0;
    }
    int c = 0;
    bool changed = false;
    for (int k = 0; k < 6; k++) {
        const float s = e[2 * k];
        const float f = e[2 * k + 1];
        if (s >= 1e29f) {
            continue;
        }
        float a1 = f;
        float an1 = n[2 * k + 1];
        bool keepA = true;
        bool keepB = false;
        float b0 = 0;
        float bn0 = 0;
        if (f > t0 && s < t1) {
            changed = true;
            keepA = s < t0 - sliver;
            a1 = t0;
            an1 = nIn;
            if (f > t1 + sliver) {
                keepB = true;
                b0 = t1;
                bn0 = nOut;
            }
        }
        if (keepA) {
            o[c] = s;
            on[c] = n[2 * k];
            o[c + 1] = a1;
            on[c + 1] = an1;
            c += 2;
        }
        if (keepB) {
            o[c] = b0;
            on[c] = bn0;
            o[c + 1] = f;
            on[c + 1] = n[2 * k + 1];
            c += 2;
        }
    }
    if (!changed) {
        return;
    }
    int drop = 14;
    if (c > 12) {
        float best = 1e30f;
        for (int k = 0; k < 7; k++) {
            const float len = o[2 * k + 1] - o[2 * k];
            if (len < best) {
                best = len;
                drop = 2 * k;
            }
            if (k < 6) {
                const float gap = o[2 * k + 2] - o[2 * k + 1];
                if (gap < best) {
                    best = gap;
                    drop = 2 * k + 1;
                }
            }
        }
    }
    for (int i = 0; i < 12; i++) {
        e[i] = i < drop ? o[i] : o[i + 2];
        n[i] = i < drop ? on[i] : on[i + 2];
    }
}

// Threads kept for the cutter's batches: starting them anew for each batch cost more than a
// small batch's work. run(n, fn) hands out fn(0) .. fn(n - 1) one at a time to whichever
// thread is free, the caller's among them, and returns when all are done.
class Pool
{
public:
    static Pool& Instance()
    {
        static Pool pool;
        return pool;
    }

    void Run(int n, const std::function<void(int)>& fn)
    {
        if (n <= 0) {
            return;
        }
        if (mThreads.empty() || n == 1) {
            for (int i = 0; i < n; i++) {
                fn(i);
            }
            return;
        }
        {
            std::lock_guard<std::mutex> lock(mMutex);
            mJob = &fn;
            mCount = n;
            mNext = 0;
            mBusy = (int)mThreads.size();
            mGeneration++;
        }
        mWake.notify_all();
        Work(fn, n);
        std::unique_lock<std::mutex> lock(mMutex);
        mDone.wait(lock, [this] { return mBusy == 0; });
        mJob = nullptr;
    }

    ~Pool()
    {
        {
            std::lock_guard<std::mutex> lock(mMutex);
            mStop = true;
            mGeneration++;
        }
        mWake.notify_all();
        for (std::thread& t : mThreads) {
            t.join();
        }
    }

private:
    Pool()
    {
        const int n = std::max(0, (int)std::thread::hardware_concurrency() - 1);
        for (int i = 0; i < n; i++) {
            mThreads.emplace_back([this] { Loop(); });
        }
    }

    void Work(const std::function<void(int)>& fn, int n)
    {
        for (int i = mNext.fetch_add(1); i < n; i = mNext.fetch_add(1)) {
            fn(i);
        }
    }

    void Loop()
    {
        long long seen = 0;
        for (;;) {
            const std::function<void(int)>* job = nullptr;
            int n = 0;
            {
                std::unique_lock<std::mutex> lock(mMutex);
                mWake.wait(lock, [&] { return mGeneration != seen; });
                seen = mGeneration;
                if (mStop) {
                    return;
                }
                job = mJob;
                n = mCount;
            }
            if (job) {
                Work(*job, n);
            }
            {
                std::lock_guard<std::mutex> lock(mMutex);
                mBusy--;
            }
            mDone.notify_one();
        }
    }

    std::vector<std::thread> mThreads;
    std::mutex mMutex;
    std::condition_variable mWake;
    std::condition_variable mDone;
    const std::function<void(int)>* mJob = nullptr;
    int mCount = 0;
    std::atomic<int> mNext {0};
    int mBusy = 0;
    long long mGeneration = 0;
    bool mStop = false;
};

}  // namespace

void DexelCutter::Setup(const vec3 origin, float res, const int dims[3])
{
    vec3_dup(mOrigin, origin);
    mRes = res;
    for (int c = 0; c < 3; c++) {
        mFar[c] = origin[c] + dims[c] * res;
    }
    mCuts.clear();
    mDraws.clear();
    mHits.clear();
}

void DexelCutter::Begin(const vec3 lo, const vec3 hi, int probe)
{
    Cut cut;
    vec3_dup(cut.lo, lo);
    vec3_dup(cut.hi, hi);
    cut.first = mDraws.size();
    cut.probe = probe;
    mCuts.push_back(cut);
}

void DexelCutter::Draw(const Shape& shape, const mat4x4 model, const mat4x4 normalRot)
{
    if (mCuts.empty() || !shape.cpuVerts || !shape.cpuIndices) {
        return;
    }
    DrawCall call;
    call.verts = shape.cpuVerts;
    call.indices = shape.cpuIndices;
    mat4x4_dup(call.model, model);
    mat4x4_dup(call.normalRot, normalRot);
    mDraws.push_back(std::move(call));
}

void DexelCutter::CutTriangles(const Cut& cut, std::vector<float>& tris) const
{
    tris.clear();
    for (size_t d = cut.first; d < cut.first + cut.count; d++) {
        const DrawCall& call = mDraws[d];
        const float* verts = reinterpret_cast<const float*>(call.verts->data());
        const GLushort* indices = call.indices->data();
        const int nIndices = (int)call.indices->size();
        const auto& model = call.model;
        const auto& normalRot = call.normalRot;
        for (int k = 0; k + 2 < nIndices; k += 3) {
            float tri[18];
            for (int corner = 0; corner < 3; corner++) {
                const float* v = verts + 6 * indices[k + corner];
                for (int r = 0; r < 3; r++) {
                    tri[corner * 3 + r] = model[0][r] * v[0] + model[1][r] * v[1]
                        + model[2][r] * v[2] + model[3][r];
                }
            }
            // A triangle beyond the lattice along one axis still ends the rays along that axis:
            // the top of a facing pass's sweep, high above the stock, is where the rays leave
            // it. Beyond along two axes it misses every grid, the rays along the third passing
            // beside the lattice, and is left out.
            int beyond = 0;
            for (int c = 0; c < 3; c++) {
                beyond += std::max({tri[c], tri[3 + c], tri[6 + c]}) < mOrigin[c]
                        || std::min({tri[c], tri[3 + c], tri[6 + c]}) > mFar[c]
                    ? 1
                    : 0;
            }
            if (beyond >= 2) {
                continue;
            }
            for (int corner = 0; corner < 3; corner++) {
                const float* v = verts + 6 * indices[k + corner];
                for (int r = 0; r < 3; r++) {
                    tri[9 + corner * 3 + r] = normalRot[0][r] * v[3] + normalRot[1][r] * v[4]
                        + normalRot[2][r] * v[5];
                }
            }
            tris.insert(tris.end(), tri, tri + 18);
        }
    }
}

void DexelCutter::End()
{
    if (!mCuts.empty()) {
        mCuts.back().count = mDraws.size() - mCuts.back().first;
    }
}

bool DexelCutter::GridRect(const Grid& g, const vec3 lo, const vec3 hi, int rect[4]) const
{
    rect[0] = std::max(0, (int)std::floor((lo[g.a] - mOrigin[g.a]) / mRes));
    rect[1] = std::max(0, (int)std::floor((lo[g.b] - mOrigin[g.b]) / mRes));
    rect[2] = std::min(g.w, (int)std::ceil((hi[g.a] - mOrigin[g.a]) / mRes) + 1);
    rect[3] = std::min(g.h, (int)std::ceil((hi[g.b] - mOrigin[g.b]) / mRes) + 1);
    return rect[2] > rect[0] && rect[3] > rect[1];
}

void DexelCutter::CaptureCut(
    const Grid& g,
    const Cut& cut,
    const std::vector<float>& tris,
    Capture& cap
) const
{
    // the sweep laid over the grid: for each ray in its rectangle where it first enters it and
    // where it last leaves, each with the sweep's surface normal there
    if (!GridRect(g, cut.lo, cut.hi, cap.rect)) {
        cap.rect[0] = cap.rect[2] = 0;
        return;
    }
    const int rw = cap.rect[2] - cap.rect[0];
    const int rh = cap.rect[3] - cap.rect[1];
    cap.tIn.assign((size_t)rw * rh, NoEnd);
    cap.tOut.assign((size_t)rw * rh, -NoEnd);
    cap.nIn.resize((size_t)rw * rh);
    cap.nOut.resize((size_t)rw * rh);
    const float oa = mOrigin[g.a];
    const float ob = mOrigin[g.b];
    for (size_t t = 0; t + 18 <= tris.size(); t += 18) {
        const float* tri = &tris[t];
        float pa[3], pb[3], pd[3];
        for (int i = 0; i < 3; i++) {
            pa[i] = tri[i * 3 + g.a];
            pb[i] = tri[i * 3 + g.b];
            pd[i] = tri[i * 3 + g.axis];
        }
        const float area = (pa[1] - pa[0]) * (pb[2] - pb[0]) - (pb[1] - pb[0]) * (pa[2] - pa[0]);
        if (std::fabs(area) < 1e-12f) {
            continue;  // edge on to the rays
        }
        const float minA = std::min({pa[0], pa[1], pa[2]});
        const float maxA = std::max({pa[0], pa[1], pa[2]});
        const float minB = std::min({pb[0], pb[1], pb[2]});
        const float maxB = std::max({pb[0], pb[1], pb[2]});
        const int i0 = std::max(cap.rect[0], (int)std::ceil((minA - oa) / mRes - 0.5f));
        const int i1 = std::min(cap.rect[2] - 1, (int)std::floor((maxA - oa) / mRes - 0.5f));
        const int j0 = std::max(cap.rect[1], (int)std::ceil((minB - ob) / mRes - 0.5f));
        const int j1 = std::min(cap.rect[3] - 1, (int)std::floor((maxB - ob) / mRes - 0.5f));
        if (i0 > i1 || j0 > j1) {
            continue;
        }
        // Row by row: the span of the row's rays inside the triangle, from where the row
        // crosses its edges, and across it the barycentric weights stepped ray by ray.
        const float inv = 1.f / area;
        // w[e] = (A_e * cb + B_e * ca + C_e) / area, for e opposite corner e
        float A[3], B[3], C[3];
        for (int e = 0; e < 3; e++) {
            const int p = (e + 1) % 3;
            const int q = (e + 2) % 3;
            A[e] = (pa[q] - pa[p]) * inv;
            B[e] = -(pb[q] - pb[p]) * inv;
            C[e] = (-(pa[q] - pa[p]) * pb[p] + (pb[q] - pb[p]) * pa[p]) * inv;
        }
        for (int j = j0; j <= j1; j++) {
            const float cb = ob + (j + 0.5f) * mRes;
            // where the row is inside: each weight >= 0 bounds ca from one side
            float aLo = -1e30f;
            float aHi = 1e30f;
            bool empty = false;
            for (int e = 0; e < 3; e++) {
                const float rest = A[e] * cb + C[e];
                if (std::fabs(B[e]) < 1e-20f) {
                    if (rest < -1e-6f) {
                        empty = true;
                    }
                    continue;
                }
                const float bound = (-1e-6f - rest) / B[e];
                if (B[e] > 0) {
                    aLo = std::max(aLo, bound);
                }
                else {
                    aHi = std::min(aHi, bound);
                }
            }
            if (empty || aLo > aHi) {
                continue;
            }
            const int ia = std::max(i0, (int)std::ceil((aLo - oa) / mRes - 0.5f));
            const int ib = std::min(i1, (int)std::floor((aHi - oa) / mRes - 0.5f));
            if (ia > ib) {
                continue;
            }
            const float ca0 = oa + (ia + 0.5f) * mRes;
            float w[3];
            for (int e = 0; e < 3; e++) {
                w[e] = A[e] * cb + B[e] * ca0 + C[e];
            }
            const float dw0 = B[0] * mRes;
            const float dw1 = B[1] * mRes;
            const float dw2 = B[2] * mRes;
            for (int i = ia; i <= ib; i++, w[0] += dw0, w[1] += dw1, w[2] += dw2) {
                const float t = w[0] * pd[0] + w[1] * pd[1] + w[2] * pd[2];
                const size_t r = (size_t)(j - cap.rect[1]) * rw + (i - cap.rect[0]);
                const bool in = t < cap.tIn[r];
                const bool out = t > cap.tOut[r];
                if (!in && !out) {
                    continue;
                }
                // the material's normal faces into the tool: the sweep's, turned round
                const float n0 = -(w[0] * tri[9] + w[1] * tri[12] + w[2] * tri[15]);
                const float n1 = -(w[0] * tri[10] + w[1] * tri[13] + w[2] * tri[16]);
                const float n2 = -(w[0] * tri[11] + w[1] * tri[14] + w[2] * tri[17]);
                const float packed = packNormal(n0, n1, n2);
                if (in) {
                    cap.tIn[r] = t;
                    cap.nIn[r] = packed;
                }
                if (out) {
                    cap.tOut[r] = t;
                    cap.nOut[r] = packed;
                }
            }
        }
    }
}

void DexelCutter::ApplyRows(const Grid& g, int gridIndex, int row0, int row1, std::atomic<int>* met)
    const
{
    // the gathered cuts, in order, on these rows of the grid
    const float sliver = 0.05f * mRes;
    // a probe meets material where it reaches into a stretch further than this: one only
    // touching the stock's face does not
    const float reach = 0.25f * mRes;
    for (size_t c = 0; c < mCuts.size(); c++) {
        const Capture& cap = mCaptures[c * 3 + gridIndex];
        const int rw = cap.rect[2] - cap.rect[0];
        if (rw <= 0) {
            continue;
        }
        const int v0 = std::max(row0, cap.rect[1]);
        const int v1 = std::min(row1, cap.rect[3]);
        for (int v = v0; v < v1; v++) {
            for (int u = cap.rect[0]; u < cap.rect[2]; u++) {
                const size_t r = (size_t)(v - cap.rect[1]) * rw + (u - cap.rect[0]);
                const float t0 = cap.tIn[r];
                const float t1 = cap.tOut[r];
                if (!(t0 < t1)) {
                    continue;  // the sweep misses this ray, or only grazes it
                }
                const size_t ray = ((size_t)v * g.w + u) * Ends;
                if (mCuts[c].probe >= 0) {
                    const float* e = g.ends + ray;
                    for (int k = 0; k < Ends; k += 2) {
                        if (e[k] < 1e29f && std::min(e[k + 1], t1) - std::max(e[k], t0) > reach) {
                            met[c].fetch_add(1, std::memory_order_relaxed);
                            break;
                        }
                    }
                    continue;
                }
                subtractRay(g.ends + ray, g.normals + ray, t0, t1, cap.nIn[r], cap.nOut[r], sliver);
            }
        }
    }
}

void DexelCutter::Flush(const Grid grids[3])
{
    if (mCuts.empty()) {
        return;
    }
    // each cut's sweep over each grid, all at once
    mCaptures.resize(mCuts.size() * 3);
    Pool& pool = Pool::Instance();
    pool.Run((int)mCuts.size(), [&](int c) {
        // each cut's triangles once, laid over the three grids
        thread_local std::vector<float> tris;
        CutTriangles(mCuts[c], tris);
        for (int g = 0; g < 3; g++) {
            CaptureCut(grids[g], mCuts[c], tris, mCaptures[c * 3 + g]);
        }
    });
    // Then taken from the rays in order, a band of rows of a grid at a time, to whichever thread
    // is free: the cuts gather where the tool is, so narrow bands keep the threads busy.
    const int bands = 8 * std::max(1, (int)std::thread::hardware_concurrency());
    std::unique_ptr<std::atomic<int>[]> met(new std::atomic<int>[mCuts.size()]);
    for (size_t c = 0; c < mCuts.size(); c++) {
        met[c].store(0);
    }
    pool.Run(3 * bands, [&](int i) {
        const int gi = i / bands;
        const int band = i % bands;
        const Grid& g = grids[gi];
        const int row0 = (int)((long long)g.h * band / bands);
        const int row1 = (int)((long long)g.h * (band + 1) / bands);
        ApplyRows(g, gi, row0, row1, met.get());
    });
    for (size_t c = 0; c < mCuts.size(); c++) {
        if (mCuts[c].probe >= 0) {
            mHits.emplace_back(mCuts[c].probe, met[c].load());
        }
    }
    mCuts.clear();
    mDraws.clear();
}

void DexelCutter::TakeHits(std::vector<std::pair<int, int>>& hits)
{
    hits.insert(hits.end(), mHits.begin(), mHits.end());
    mHits.clear();
}

}  // namespace CAMSimulator
