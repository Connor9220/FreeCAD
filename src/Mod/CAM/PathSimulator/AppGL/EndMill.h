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

#include "SimShapes.h"
#include <vector>

#define PROFILE_BUFFER_POINTS(npoints) ((npoints) * 2 - 1)
#define PROFILE_BUFFER_SIZE(npoints) (PROFILE_BUFFER_POINTS(npoints) * 2)
#define MILL_HEIGHT 10

namespace CAMSimulator
{

class EndMill
{
public:
    std::vector<float> profilePoints;
    float radius;
    int nPoints = 0;
    int toolId = -1;

    Shape pathShape;
    Shape halfToolShape;
    Shape toolShape;
    Shape holderShape;  // drawn with the tool, never cutting
    Shape shankShape;   // the tool above its cutting edges, never cutting either

public:
    EndMill(int toolid, float diameter);
    EndMill(const std::vector<float>& toolProfile, int toolid, float diameter);
    virtual ~EndMill();
    // the holder the tool is set in: its outline as radius, height pairs from the tool's tip,
    // from the top at its rim down to the axis at its face, as the tool's own
    void SetHolder(const std::vector<float>& holderProfile);
    bool HasHolder() const
    {
        return holderPoints.size() >= 4;
    }
    // the holder's widest radius and the heights it spans, from the tool's tip
    void HolderBounds(float& radius, float& zLo, float& zHi) const;
    // the tool above its cutting edges, up to the holder: its outline as the holder's. It
    // cuts nothing; where it meets material, the tool rubs or crashes
    void SetShank(const std::vector<float>& shankProfile);
    bool HasShank() const
    {
        return shankPoints.size() >= 4;
    }
    void ShankBounds(float& radius, float& zLo, float& zHi) const;
    void GenerateDisplayLists(float quality);
    // The tool moved straight along its axis by distance, as one solid, its tip where it is
    // lowest: at each height as wide as the tool is anywhere within distance below, so a head
    // wider than its neck takes all it passes through, not only where it stops.
    void VerticalSweep(float distance, Shape& out) const;
    unsigned int GenerateArcSegmentDL(float radius, float angleRad, float zShift, Shape* retShape) const;

protected:
    void MirrorPointBuffer();
    std::vector<float> holderPoints;
    int slices = 16;  // around the axis, as the display lists have it
    std::vector<float> shankPoints;
};

}  // namespace CAMSimulator
