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

namespace CAMSimulator
{

// What a job asks of the dexel stock: how many cuts its moves make, the area its tools sweep,
// mm², and the memory its stock takes on the graphics card, bytes.
struct DexelJob
{
    double cuts = 0;
    double sweptArea = 0;
    double cardBytes = 0;
};

// Where the simulator runs, as the CAM preferences say: on the processor, on the graphics card,
// or, Automatic, wherever a short test of each on this computer says a job like this one is done
// sooner, on the card only when its stock fits in the card's memory. The test runs once, unseen,
// the first time the simulator is set up on this computer's processor and card, and again when
// they change or its result is cleared; what Automatic picked is kept for the preferences to
// show. Needs the simulator's GL context current. True for the processor.
bool RunOnProcessor(const DexelJob& job);

}  // namespace CAMSimulator
