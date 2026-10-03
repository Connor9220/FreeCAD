// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2017 Shai Seger <shaise at gmail>                       *
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

#include <memory>
#include <TopoDS_Shape.hxx>

#include <Mod/CAM/App/Command.h>
#include <Mod/CAM/PathGlobal.h>
#include <Mod/Mesh/App/Mesh.h>
#include <Mod/Part/App/TopoShape.h>

#include "DlgCAMSimulator.h"

using namespace Path;

namespace CAMSimulator
{

/** The representation of a CNC Toolpath Simulator */

class CAMSimulatorExport CAMSim: public Base::BaseClass
{
    // TYPESYSTEM_HEADER();

public:
    static Base::Type getClassTypeId();
    Base::Type getTypeId() const override;
    static void init();
    static void* create();

private:
    static Base::Type classTypeId;


public:
    CAMSim() = default;

    void BeginSimulation(const Part::TopoShape& stock, float resolution);
    void resetSimulation(Gui::Document* doc);
    void addTool(
        const std::vector<float>& toolProfilePoints,
        int toolNumber,
        float diameter,
        float resolution,
        const std::vector<float>& holderProfilePoints = {},
        const std::vector<float>& shankProfilePoints = {}
    );
    void SetBaseShape(const Part::TopoShape& baseShape, float resolution);
    // cuttable: soft jaws, the tool cutting them only a warning
    // color, red, green and blue, else the simulator's own; with append, added to what was set
    void SetWorkholding(
        const Part::TopoShape& shape,
        float resolution,
        bool cuttable = false,
        const float* color = nullptr,
        bool append = false
    );
    void AddCommand(Command* cmd);
    void BeginOperation(const std::string& name);
    void SetFrame(
        const Base::Placement& placement,
        const Base::Rotation& pose,
        float indexRate,
        const std::vector<float>& angles
    );
    void SetRotaryAxes(const std::vector<SimRotaryAxis>& axes);
};

}  // namespace CAMSimulator
