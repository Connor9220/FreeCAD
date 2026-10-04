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

#include "EndMill.h"
#include <algorithm>

namespace CAMSimulator
{

EndMill::EndMill(int toolid, float diameter)
{
    radius = diameter / 2;
    toolId = toolid;
}

EndMill::EndMill(const std::vector<float>& toolProfile, int toolid, float diameter)
    : EndMill(toolid, diameter)
{
    profilePoints.clear();

    int srcBuffSize = toolProfile.size();
    nPoints = srcBuffSize / 2;
    if (nPoints < 2) {
        return;
    }

    // make sure last point is at 0,0 else, add it
    bool missingCenterPoint = fabs(toolProfile[nPoints * 2 - 2]) > 0.0001f;
    if (missingCenterPoint) {
        nPoints++;
    }

    int buffSize = PROFILE_BUFFER_SIZE(nPoints);
    profilePoints.resize(buffSize);

    // copy profile points
    // add some width to reduce simulation artifacts, a point on the axis staying there: a tip
    // moved off it leaves the tool open at the tip and along its seams. A hair at most, so a big
    // tool does not cut visibly past where it goes.
    const float grow = std::min(diameter * 0.01f, 0.05f);
    for (int i = 0; i < srcBuffSize; i += 2) {
        const bool onAxis = fabs(toolProfile[i]) <= 0.0001f;
        profilePoints[i] = onAxis ? 0.0f : toolProfile[i] + grow;
        profilePoints[i + 1] = toolProfile[i + 1] - grow;
    }
    if (missingCenterPoint) {
        profilePoints[srcBuffSize] = 0.0F;
        profilePoints[srcBuffSize + 1] = profilePoints[srcBuffSize - 1];
    }

    MirrorPointBuffer();
}

EndMill::~EndMill()
{
    toolShape.FreeResources();
    halfToolShape.FreeResources();
    holderShape.FreeResources();
    shankShape.FreeResources();
    pathShape.FreeResources();
}

void EndMill::GenerateDisplayLists(float quality)
{
    // calculate number of slices based on quality: at the highest, fine enough that the cut
    // surfaces swept by a 12 mm tool keep within 0.03 mm of round
    int nslices = quality >= 9 ? 32 : 16;
    if (quality < 3) {
        nslices = 4;
    }
    else if (quality < 7) {
        nslices = 8;
    }

    slices = nslices;
    // full tool
    toolShape.RotateProfile(profilePoints.data(), nPoints, 0, 0, nslices, false);

    if (HasHolder()) {
        const int nHolderPoints = (int)holderPoints.size() / 2;
        holderShape.RotateProfile(holderPoints.data(), nHolderPoints, 0, 0, nslices, false);
    }
    if (HasShank()) {
        const int nShankPoints = (int)shankPoints.size() / 2;
        shankShape.RotateProfile(shankPoints.data(), nShankPoints, 0, 0, nslices, false);
    }

    // half tool
    halfToolShape.RotateProfile(profilePoints.data(), nPoints, 0, 0, nslices / 2, true);

    // unit path
    int nFullPoints = PROFILE_BUFFER_POINTS(nPoints);
    pathShape.ExtrudeProfileLinear(profilePoints.data(), nFullPoints, 0, 1, 0, 0, true, false);
}

void EndMill::VerticalSweep(float distance, Shape& out) const
{
    // the outline from the top down, radius and height
    std::vector<std::pair<float, float>> outline;
    for (int i = 0; i < nPoints; i++) {
        outline.emplace_back(std::fabs(profilePoints[2 * i]), profilePoints[2 * i + 1]);
    }
    if (outline.size() < 2) {
        return;
    }
    float zLo = 1e30f, zHi = -1e30f;
    for (const auto& [r, z] : outline) {
        zLo = std::min(zLo, z);
        zHi = std::max(zHi, z);
    }
    // the radius at a height between the outline's corners: its sloped and upright edges there
    auto radiusAt = [&](float z) {
        float r = 0;
        for (size_t i = 0; i + 1 < outline.size(); i++) {
            const auto [r0, z0] = outline[i];
            const auto [r1, z1] = outline[i + 1];
            if (std::fabs(z1 - z0) < 1e-6f || z < std::min(z0, z1) || z > std::max(z0, z1)) {
                continue;
            }
            r = std::max(r, r0 + (r1 - r0) * (z - z0) / (z1 - z0));
        }
        return r;
    };
    // the widest the tool is within distance below a height, just under it or just over it
    const float eps = 1e-4f;
    auto widest = [&](float h) {
        const float lo = h - distance, hi = h;
        float r = std::max(radiusAt(lo), radiusAt(hi));
        for (const auto& [rc, zc] : outline) {
            if (zc >= lo && zc <= hi) {
                r = std::max(r, rc);
            }
        }
        return r;
    };
    // the heights it changes at: the outline's corners, those a distance up, and between them
    std::vector<float> heights;
    for (const auto& [r, z] : outline) {
        heights.push_back(z);
        heights.push_back(z + distance);
    }
    std::sort(heights.begin(), heights.end());
    auto same = [](float a, float b) {
        return std::fabs(a - b) < 1e-5f;
    };
    heights.erase(std::unique(heights.begin(), heights.end(), same), heights.end());
    std::vector<float> fine;
    for (size_t i = 0; i < heights.size(); i++) {
        fine.push_back(heights[i]);
        if (i + 1 < heights.size()) {
            for (int k = 1; k < 4; k++) {
                fine.push_back(heights[i] + (heights[i + 1] - heights[i]) * k / 4.f);
            }
        }
    }
    // the swept outline from the top down: at each height its width just over it, then under it
    std::vector<float> swept;
    auto add = [&](float r, float z) {
        const size_t n = swept.size();
        if (n >= 2 && std::fabs(swept[n - 2] - r) < 1e-5f && std::fabs(swept[n - 1] - z) < 1e-5f) {
            return;
        }
        swept.push_back(r);
        swept.push_back(z);
    };
    for (auto it = fine.rbegin(); it != fine.rend(); ++it) {
        const float h = *it;
        if (h < zHi + distance - eps) {
            add(widest(h + eps), h);
        }
        if (h > zLo + eps) {
            add(widest(h - eps), h);
        }
    }
    add(0.f, zLo);
    out.RotateProfile(swept.data(), (int)swept.size() / 2, 0, 0, slices, false);
}

void EndMill::SetHolder(const std::vector<float>& holderProfile)
{
    holderPoints.assign(holderProfile.begin(), holderProfile.end() - (holderProfile.size() % 2));
}

// the widest radius of an outline of radius, height pairs, and the heights it spans
static void ProfileBounds(const std::vector<float>& points, float& radius, float& zLo, float& zHi)
{
    radius = 0;
    zLo = 1e30f;
    zHi = -1e30f;
    for (size_t i = 0; i + 1 < points.size(); i += 2) {
        radius = std::max(radius, std::fabs(points[i]));
        zLo = std::min(zLo, points[i + 1]);
        zHi = std::max(zHi, points[i + 1]);
    }
}

void EndMill::HolderBounds(float& radius, float& zLo, float& zHi) const
{
    ProfileBounds(holderPoints, radius, zLo, zHi);
}

void EndMill::SetShank(const std::vector<float>& shankProfile)
{
    shankPoints.assign(shankProfile.begin(), shankProfile.end() - (shankProfile.size() % 2));
}

void EndMill::ShankBounds(float& radius, float& zLo, float& zHi) const
{
    ProfileBounds(shankPoints, radius, zLo, zHi);
}

unsigned int EndMill::GenerateArcSegmentDL(float radius, float angleRad, float zShift, Shape* retShape) const
{
    int nFullPoints = PROFILE_BUFFER_POINTS(nPoints);
    retShape->ExtrudeProfileRadial(profilePoints.data(), nFullPoints, radius, angleRad, zShift, true, true);
    return 0;
}

void EndMill::MirrorPointBuffer()
{
    int endpoint = PROFILE_BUFFER_POINTS(nPoints) - 1;
    for (int i = 0, j = endpoint * 2; i < (nPoints - 1) * 2; i += 2, j -= 2) {
        profilePoints[j] = -profilePoints[i];
        profilePoints[j + 1] = profilePoints[i + 1];
    }
}

}  // namespace CAMSimulator
