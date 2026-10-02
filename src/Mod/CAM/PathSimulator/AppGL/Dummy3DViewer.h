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

#include "TopoShapeViewProvider.h"
#include <Gui/View3DInventorViewer.h>
#include <Inventor/SbLinear.h>
#include <Inventor/sensors/SoNodeSensor.h>
#include <QImage>
#include <QRect>

namespace CAMSimulator
{

class Dummy3DViewer: public Gui::View3DInventorViewer
{
public:
    Dummy3DViewer(QWidget* parent = nullptr);

    void cloneFrom(Dummy3DViewer& viewer);

    void setStockShape(const Part::TopoShape& shape);
    void setStockVisible(bool b);
    void setBaseShape(const Part::TopoShape& shape);
    void setBaseVisible(bool b);

    // FreeCAD's NaviCube, which this viewer, under the simulation and taking its mouse, works as
    // in any 3D view, drawn by it for the simulation to show over its own drawing: brought up to
    // date when the camera or the cube changed, true then. Its rectangle is in device pixels
    // from the top left; the image is empty when the cube is not shown.
    bool updateNaviCube();
    const QImage& naviCubeImage() const
    {
        return naviImage;
    }
    QRect naviCubeRect() const
    {
        return naviRect;
    }

protected:
    void paintEvent(QPaintEvent* event) override;

public:
    bool discardPaintEvent_ = true;

private:
    static void naviCubeChanged(void* data, SoSensor* sensor);

    TopoShapeViewProvider stockViewProvider;
    TopoShapeViewProvider baseViewProvider;

    SoNodeSensor naviSensor;
    SoNode* naviNode = nullptr;
    bool naviDirty = true;
    SbRotation naviCameraRot;
    SbVec2s naviSize {0, 0};
    QImage naviImage;
    QRect naviRect;
};

}  // namespace CAMSimulator
