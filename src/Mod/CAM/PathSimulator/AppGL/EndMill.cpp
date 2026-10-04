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
